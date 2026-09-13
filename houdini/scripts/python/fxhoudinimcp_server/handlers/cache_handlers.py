"""Cache management handlers for FXHoudini-MCP.

Provides tools for listing, inspecting, clearing, and writing
file caches from Houdini's filecache and rop_geometry nodes.
"""

from __future__ import annotations

import contextlib

# Built-in
import glob
import os
import time
from typing import Any

# Third-party
import hou

# Internal
from fxhoudinimcp_server.dispatcher import register_handler
from fxhoudinimcp_server.outputs import (
    at_frame as _at_frame,
)
from fxhoudinimcp_server.outputs import (
    failure_verdict,
    reported_outputs,
    write_verdict,
)


def _menu_index_by_label(parm: hou.Parm, label_substring: str) -> int | None:
    """Find a menu parameter's index whose label contains *label_substring*."""
    template = parm.parmTemplate()
    labels = list(template.menuLabels())
    items = list(template.menuItems())
    target = label_substring.lower()
    for idx, label in enumerate(labels):
        if target in label.lower():
            return int(items[idx]) if items[idx].isdigit() else idx
    return None


###### Helpers


def _get_node(node_path: str) -> hou.Node:
    """Resolve a node path and raise a clear error if it does not exist."""
    node = hou.node(node_path)
    if node is None:
        raise ValueError(f"Node not found: {node_path}")
    return node


def _is_cache_node(node: hou.Node) -> bool:
    """Check if a node is a cache-type node (filecache or rop_geometry)."""
    type_name = node.type().name()
    return type_name in (
        "filecache",
        "filecache::2.0",
        "rop_geometry",
        "rop_alembic",
        "file",
    )


# The write path first. On File Cache 2.0 `sopoutput` is where frames go and
# `file` is the load path, which in the default "constructed" mode is an
# unversioned pattern no frame is ever written to; reading it reported an
# empty cache over 60 fresh frames.
_OUTPUT_PARMS = ("sopoutput", "file", "filename", "filepath")


def _frame_glob(node: hou.Node) -> str | None:
    """A glob for every frame a cache node writes, from evaluated paths.

    The raw path is not usable: on File Cache 2.0 `sopoutput` is a Python
    expression, and on any node `$F` may be hidden behind chs() calls. So
    evaluate the path at two frames and turn the part that changed into `*`,
    widened over the whole digit run so 0009 -> 0010 still matches.
    """
    for parm_name in _OUTPUT_PARMS:
        parm = node.parm(parm_name)
        if parm is None:
            continue
        # Not evalAtFrame(): File Cache's sopoutput is a Python expression
        # whose chs() calls read the current frame, so evalAtFrame(2) returned
        # the frame-1 path. Move the playbar for real, and put it back.
        try:
            with _at_frame(1):
                at_1 = parm.eval()
            with _at_frame(2):
                at_2 = parm.eval()
        except Exception:
            continue
        if not at_1:
            continue
        if at_1 == at_2:
            return at_1
        i = 0
        while i < min(len(at_1), len(at_2)) and at_1[i] == at_2[i]:
            i += 1
        j = 0
        while j < min(len(at_1), len(at_2)) - i and at_1[-1 - j] == at_2[-1 - j]:
            j += 1
        # Widen the changed span over the digit run on either side.
        while i > 0 and at_1[i - 1].isdigit():
            i -= 1
        while j > 0 and at_1[-j].isdigit():
            j -= 1
        return at_1[:i] + "*" + (at_1[-j:] if j else "")
    return None


def _get_file_pattern(node: hou.Node) -> str | None:
    """Extract the file path pattern from a cache node."""
    for parm_name in _OUTPUT_PARMS:
        parm = node.parm(parm_name)
        if parm is not None:
            try:
                return parm.eval()
            except Exception:
                return parm.rawValue()
    return None


def _get_file_pattern_raw(node: hou.Node) -> str | None:
    """Extract the raw (unexpanded) file path pattern from a cache node."""
    for parm_name in _OUTPUT_PARMS:
        parm = node.parm(parm_name)
        if parm is not None:
            return parm.rawValue()
    return None


def _expand_frame_pattern(pattern: str) -> str:
    """Convert a Houdini frame pattern ($F4, $F, etc.) to a glob pattern."""
    import re

    # Replace $F4, $F3, $F with wildcard
    result = re.sub(r"\$F\d*", "*", pattern)
    # Replace `$HIP`, `$JOB` etc. with their expanded values
    with contextlib.suppress(Exception):
        result = hou.text.expandString(result)
    return result


###### cache.list_caches


def _list_caches(*, root_path: str = "/", **_: Any) -> dict[str, Any]:
    """Recursively find all cache-type nodes under the given root.

    Looks for filecache, rop_geometry, and similar nodes, returning
    their file path patterns and frame ranges.

    Args:
        root_path: Root path to search from (default: "/").
    """
    root = _get_node(root_path)
    all_nodes = root.allSubChildren()

    caches: list[dict[str, Any]] = []
    for node in all_nodes:
        if not _is_cache_node(node):
            continue

        file_pattern = _get_file_pattern(node)
        raw_pattern = _get_file_pattern_raw(node)

        # Try to get frame range
        frame_range = None
        for start_name, end_name in [
            ("f1", "f2"),
            ("trange", None),
        ]:
            start_parm = node.parm(start_name)
            end_parm = node.parm(end_name) if end_name else None
            if start_parm is not None and end_parm is not None:
                with contextlib.suppress(Exception):
                    frame_range = [start_parm.eval(), end_parm.eval()]
                break

        # Determine status by checking if any files exist
        status = "unknown"
        if file_pattern:
            glob_pattern = _frame_glob(node) or _expand_frame_pattern(
                raw_pattern if raw_pattern else file_pattern
            )
            try:
                existing = glob.glob(glob_pattern)
                status = f"cached ({len(existing)} files)" if existing else "empty"
            except Exception:
                status = "unknown"

        caches.append(
            {
                "node_path": node.path(),
                "file_pattern": file_pattern,
                "frame_range": frame_range,
                "status": status,
            }
        )

    return {
        "count": len(caches),
        "caches": caches,
    }


register_handler("cache.list_caches", _list_caches)


###### cache.get_cache_status


def _get_cache_status(*, node_path: str, **_: Any) -> dict[str, Any]:
    """Get the status of a specific cache node.

    Expands the file path pattern, checks which frames exist on disk,
    and calculates the total size.

    Args:
        node_path: Path to the cache node.
    """
    node = _get_node(node_path)

    file_pattern = _get_file_pattern(node)
    raw_pattern = _get_file_pattern_raw(node)

    if not file_pattern and not raw_pattern:
        raise ValueError(f"Could not determine file pattern for node: {node_path}")

    # Find existing files using glob
    glob_pattern = _frame_glob(node) or _expand_frame_pattern(
        raw_pattern if raw_pattern else file_pattern
    )

    try:
        existing_files = sorted(glob.glob(glob_pattern))
    except Exception:
        existing_files = []

    # Extract frame numbers from filenames
    import re

    frames_on_disk: list[int] = []
    total_size_bytes = 0

    for filepath in existing_files:
        # Try to extract frame number from filename
        match = re.search(r"\.(\d+)\.", os.path.basename(filepath))
        if match:
            frames_on_disk.append(int(match.group(1)))

        # Accumulate file sizes
        with contextlib.suppress(OSError):
            total_size_bytes += os.path.getsize(filepath)

    total_size_mb = round(total_size_bytes / (1024 * 1024), 2)
    is_valid = len(existing_files) > 0

    # Completeness against the node's own range, so a poll can stop on
    # `complete` instead of counting files in a shell loop.
    expected: list[int] | None = None
    with contextlib.suppress(Exception):
        f1, f2 = node.parm("f1"), node.parm("f2")
        if f1 is not None and f2 is not None:
            expected = list(range(int(f1.eval()), int(f2.eval()) + 1))
    missing = [f for f in expected if f not in set(frames_on_disk)] if expected else []
    complete = bool(expected) and not missing

    # Is something still writing? A background hython shows only as files
    # arriving, so the age of the newest one is the evidence there is.
    newest_age: float | None = None
    with contextlib.suppress(Exception):
        newest_age = round(time.time() - max(os.path.getmtime(f) for f in existing_files), 1)

    # A complete cache that the node does not load is the worst of both: the
    # frames are on disk and the viewport still cooks the sim live. A session
    # froze Houdini for eleven minutes on a fresh million-polygon mesh cache
    # exactly this way.
    load_parm = node.parm("loadfromdisk")
    load_from_disk = bool(load_parm.eval()) if load_parm is not None else None
    hint = None
    if complete and load_from_disk is False:
        hint = (
            "Cache is complete but Load from Disk is off, so the node still cooks "
            "the input live: set_parameter(node_path, 'loadfromdisk', 1)."
        )

    return {
        "node_path": node_path,
        "file_pattern": file_pattern,
        "glob_pattern": glob_pattern,
        "file_count": len(existing_files),
        "frames_on_disk": frames_on_disk,
        "expected_range": [expected[0], expected[-1]] if expected else None,
        "missing_frames": missing[:50],
        "complete": complete,
        "newest_file_age_seconds": newest_age,
        "writing": newest_age is not None and newest_age < 30 and not complete,
        "load_from_disk": load_from_disk,
        "hint": hint,
        "total_size_mb": total_size_mb,
        "is_valid": is_valid,
    }


register_handler("cache.get_cache_status", _get_cache_status)


###### cache.clear_cache


def _clear_cache(
    *,
    node_path: str,
    frame_range: list[int] | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Delete cached files from disk for a cache node.

    If frame_range is provided, only deletes files for frames within
    that range. Otherwise deletes all matching files.

    Args:
        node_path: Path to the cache node.
        frame_range: Optional [start_frame, end_frame] to limit deletion.
    """
    node = _get_node(node_path)

    raw_pattern = _get_file_pattern_raw(node)
    file_pattern = _get_file_pattern(node)

    if not file_pattern and not raw_pattern:
        raise ValueError(f"Could not determine file pattern for node: {node_path}")

    glob_pattern = _expand_frame_pattern(raw_pattern if raw_pattern else file_pattern)

    try:
        existing_files = sorted(glob.glob(glob_pattern))
    except Exception:
        existing_files = []

    import re

    deleted_count = 0
    freed_bytes = 0

    for filepath in existing_files:
        should_delete = True

        # If frame_range is specified, only delete matching frames
        if frame_range is not None and len(frame_range) >= 2:
            match = re.search(r"\.(\d+)\.", os.path.basename(filepath))
            if match:
                frame_num = int(match.group(1))
                if frame_num < frame_range[0] or frame_num > frame_range[1]:
                    should_delete = False
            else:
                should_delete = False

        if should_delete:
            try:
                file_size = os.path.getsize(filepath)
                os.remove(filepath)
                deleted_count += 1
                freed_bytes += file_size
            except OSError:
                pass

    freed_mb = round(freed_bytes / (1024 * 1024), 2)

    return {
        "node_path": node_path,
        "deleted_count": deleted_count,
        "freed_mb": freed_mb,
    }


register_handler("cache.clear_cache", _clear_cache)


###### cache.write_cache


def _set_frame_parm(node: hou.Node, name: str, value: float) -> None:
    """Set f1/f2, removing the $FSTART/$FEND keyframe a fresh cache node ships with.

    parm.set() on a parm driven by an expression keyframe leaves the
    expression in charge: set(10) evaluates back to $FSTART. So the range this
    function was asked for used to be silently ignored.
    """
    parm = node.parm(name)
    if parm is None:
        return
    if parm.keyframes():
        parm.deleteAllKeyframes()
    parm.set(value)


def _write_cache(
    *,
    node_path: str,
    frame_range: list[int] | None = None,
    background: bool = False,
    **_: Any,
) -> dict[str, Any]:
    """Execute (render) a cache node to write files to disk.

    Presses the "execute" button on the cache node or calls render()
    for ROP-style caches.

    Args:
        node_path: Path to the cache node.
        frame_range: Optional [start_frame, end_frame] to render. If not
            provided, uses the node's own frame range settings.
        background: Write from a separate Houdini process so the session
            stays responsive. File Cache implements this as a PDG cook of its
            internal TOP network (the "Save to Disk in Background" button,
            parm `cookoutputnode`); its `savebackground` toggle on its own
            changes nothing, and pressing `execute` with the toggle on still
            blocks the main thread for the whole write, which is what a live
            session measured. The return reports the launch; poll
            get_cache_status for the files.
    """
    node = _get_node(node_path)

    # Foreground is the default on purpose: it holds the main thread, but the
    # user sees Houdini's own progress dialog and can cancel, where a
    # background hython shows them nothing. The dispatcher gives this command
    # an hour, so the verdict comes back instead of a timeout.
    bg_button = node.parm("cookoutputnode")
    if background and bg_button is None:
        raise ValueError(
            f"{node_path} has no background save (no 'cookoutputnode' button); "
            "background=True needs a File Cache 2.0 style node"
        )
    # The worker process loads the hip from disk, so a never-saved hip has no
    # file to load and an unsaved change would be cached as last saved.
    if background and hou.hipFile.isNewFile():
        raise ValueError("Save the hip first (save_scene): a background cache loads it from disk")

    # Set frame range if provided
    if frame_range is not None and len(frame_range) >= 2:
        # Try to set trange to "custom" or specific frame range parms
        trange_parm = node.parm("trange")
        if trange_parm is not None:
            # Resolve menu index dynamically (avoids version-specific hardcoding)
            trange_idx = _menu_index_by_label(trange_parm, "specific frame")
            trange_parm.set(trange_idx if trange_idx is not None else 1)

        _set_frame_parm(node, "f1", frame_range[0])
        _set_frame_parm(node, "f2", frame_range[1])

    # Snapshot the output before executing, so "did a cache appear" is answerable
    # afterwards. pressButton() is fire-and-forget: a File Cache SOP that fails to
    # write records the failure on the node and raises nothing at all, so this
    # function used to set status = "success" on the strength of having pressed a
    # button. That is the report an artist trusts before closing Houdini for the
    # night, and it was never evidence that a cache exists.
    first_frame = frame_range[0] if frame_range else None
    with _at_frame(first_frame):
        before = reported_outputs(node)

    failure: Exception | None = None
    method = "execute button"
    try:
        if background:
            hou.hipFile.save()
            method = "cookoutputnode button (PDG, background process)"
            bg_button.pressButton()
            return {
                "node_path": node_path,
                "frame_range": frame_range,
                "method": method,
                "background": True,
                "success": True,
                "wrote_files": False,
                "status": "launched",
                "message": (
                    "Background cache launched in a separate Houdini process; "
                    "poll get_cache_status(node_path) for frames on disk."
                ),
                "outputs": before,
            }
        # Try pressing the execute button first (filecache style)
        execute_parm = node.parm("execute")
        if execute_parm is not None:
            execute_parm.pressButton()
        else:
            # Fall back to render() for ROP-style nodes
            method = "render()"
            if frame_range is not None and len(frame_range) >= 2:
                frame_range_tuple = (
                    frame_range[0],
                    frame_range[1],
                    1,  # frame increment
                )
                node.render(frame_range=frame_range_tuple)
            else:
                node.render()
    except Exception as e:  # noqa: BLE001 - reported, not swallowed
        failure = e

    # Determine what frame range was used
    actual_range = frame_range
    if actual_range is None:
        f1_parm = node.parm("f1")
        f2_parm = node.parm("f2")
        if f1_parm is not None and f2_parm is not None:
            with contextlib.suppress(Exception):
                actual_range = [f1_parm.eval(), f2_parm.eval()]

    with _at_frame(first_frame):
        verdict = (
            failure_verdict(node, before, failure, action="Cache write")
            if failure is not None
            else write_verdict(node, before, action="Cache write")
        )

    # A verified write is what Load from Disk is for; leaving it off keeps the
    # sim cooking live behind a finished cache.
    load_parm = node.parm("loadfromdisk")
    load_enabled = False
    if verdict["success"] and load_parm is not None:
        with contextlib.suppress(Exception):
            load_parm.set(1)
            load_enabled = True
    return {
        "node_path": node_path,
        "frame_range": actual_range,
        "method": method,
        "background": background,
        "load_from_disk_enabled": load_enabled,
        # Kept so existing callers reading `status` still work, but derived from
        # the same evidence as `success` rather than from an unconditional string.
        "status": (
            "success"
            if verdict["success"]
            else "error: " + ("; ".join(verdict.get("errors", [])) or verdict["message"])
        ),
        **verdict,
    }


register_handler("cache.write_cache", _write_cache)
