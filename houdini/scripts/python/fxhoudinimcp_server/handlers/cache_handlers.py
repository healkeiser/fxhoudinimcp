"""Cache management handlers for FXHoudini-MCP.

Provides tools for listing, inspecting, clearing, and writing
file caches from Houdini's filecache and rop_geometry nodes.
"""

from __future__ import annotations

# Built-in
import glob
import os
from typing import Any

# Third-party
import hou

# Internal
from fxhoudinimcp_server.dispatcher import register_handler


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
        "filecache", "filecache::2.0", "rop_geometry",
        "rop_alembic", "file",
    )


def _get_file_pattern(node: hou.Node) -> str | None:
    """Extract the file path pattern from a cache node."""
    for parm_name in ("file", "sopoutput", "filename", "filepath"):
        parm = node.parm(parm_name)
        if parm is not None:
            try:
                return parm.eval()
            except Exception:
                return parm.rawValue()
    return None


def _get_file_pattern_raw(node: hou.Node) -> str | None:
    """Extract the raw (unexpanded) file path pattern from a cache node."""
    for parm_name in ("file", "sopoutput", "filename", "filepath"):
        parm = node.parm(parm_name)
        if parm is not None:
            return parm.rawValue()
    return None


def _expand_frame_pattern(pattern: str) -> str:
    """Convert a Houdini frame pattern ($F4, $F, etc.) to a glob pattern."""
    import re
    # Replace $F4, $F3, $F with wildcard
    result = re.sub(r'\$F\d*', '*', pattern)
    # Replace `$HIP`, `$JOB` etc. with their expanded values
    try:
        result = hou.text.expandString(result)
    except Exception:
        pass
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
                try:
                    frame_range = [start_parm.eval(), end_parm.eval()]
                except Exception:
                    pass
                break

        # Determine status by checking if any files exist
        status = "unknown"
        if file_pattern:
            glob_pattern = _expand_frame_pattern(
                raw_pattern if raw_pattern else file_pattern
            )
            try:
                existing = glob.glob(glob_pattern)
                if existing:
                    status = f"cached ({len(existing)} files)"
                else:
                    status = "empty"
            except Exception:
                status = "unknown"

        caches.append({
            "node_path": node.path(),
            "file_pattern": file_pattern,
            "frame_range": frame_range,
            "status": status,
        })

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
    glob_pattern = _expand_frame_pattern(
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
        match = re.search(r'\.(\d+)\.', os.path.basename(filepath))
        if match:
            frames_on_disk.append(int(match.group(1)))

        # Accumulate file sizes
        try:
            total_size_bytes += os.path.getsize(filepath)
        except OSError:
            pass

    total_size_mb = round(total_size_bytes / (1024 * 1024), 2)
    is_valid = len(existing_files) > 0

    return {
        "node_path": node_path,
        "file_pattern": file_pattern,
        "glob_pattern": glob_pattern,
        "file_count": len(existing_files),
        "frames_on_disk": frames_on_disk,
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

    glob_pattern = _expand_frame_pattern(
        raw_pattern if raw_pattern else file_pattern
    )

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
            match = re.search(r'\.(\d+)\.', os.path.basename(filepath))
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

def _write_cache(
    *,
    node_path: str,
    frame_range: list[int] | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Execute (render) a cache node to write files to disk.

    Presses the "execute" button on the cache node or calls render()
    for ROP-style caches.

    Args:
        node_path: Path to the cache node.
        frame_range: Optional [start_frame, end_frame] to render. If not
            provided, uses the node's own frame range settings.
    """
    node = _get_node(node_path)

    # Set frame range if provided
    if frame_range is not None and len(frame_range) >= 2:
        # Try to set trange to "custom" or specific frame range parms
        trange_parm = node.parm("trange")
        if trange_parm is not None:
            trange_parm.set(1)  # 1 = "Render Specific Frame Range"

        f1_parm = node.parm("f1")
        f2_parm = node.parm("f2")
        if f1_parm is not None:
            f1_parm.set(frame_range[0])
        if f2_parm is not None:
            f2_parm.set(frame_range[1])

    # Execute the cache
    status = "success"
    try:
        # Try pressing the execute button first (filecache style)
        execute_parm = node.parm("execute")
        if execute_parm is not None:
            execute_parm.pressButton()
        else:
            # Fall back to render() for ROP-style nodes
            if frame_range is not None and len(frame_range) >= 2:
                frame_range_tuple = (
                    frame_range[0],
                    frame_range[1],
                    1,  # frame increment
                )
                node.render(frame_range=frame_range_tuple)
            else:
                node.render()
    except hou.OperationFailed as e:
        status = f"error: {e}"
    except Exception as e:
        status = f"error: {e}"

    # Determine what frame range was used
    actual_range = frame_range
    if actual_range is None:
        f1_parm = node.parm("f1")
        f2_parm = node.parm("f2")
        if f1_parm is not None and f2_parm is not None:
            try:
                actual_range = [f1_parm.eval(), f2_parm.eval()]
            except Exception:
                pass

    return {
        "node_path": node_path,
        "frame_range": actual_range,
        "status": status,
    }

register_handler("cache.write_cache", _write_cache)
