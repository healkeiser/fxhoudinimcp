"""Scene-level handlers for FXHoudini-MCP.

Provides tools for querying and manipulating the Houdini scene (hip file),
including scene info, save/load, import/export, and context introspection.
"""

from __future__ import annotations

# Built-in
import contextlib
import os

# Third-party
import hou

# Internal
from fxhoudinimcp_server.callbacks import press
from fxhoudinimcp_server.config import (
    layout_if_enabled,
    require_inside_project_root,
    update_mode_name,
)
from fxhoudinimcp_server.dispatcher import register_handler
from fxhoudinimcp_server.outputs import (
    OUTPUT_PARMS,
    failure_verdict,
    reported_outputs,
    write_verdict,
)

###### Helpers


def _focus_network_editor(node: hou.Node) -> None:
    """Best-effort: layout the parent network, then pan the editor to *node*."""
    try:
        parent = node.parent()
        if parent is not None:
            layout_if_enabled(parent)
        for pane_tab in hou.ui.paneTabs():
            if pane_tab.type() == hou.paneTabType.NetworkEditor:
                if parent is not None:
                    pane_tab.cd(parent.path())
                pane_tab.setCurrentNode(node)
                pane_tab.homeToSelection()
                return
    except Exception:
        pass


# Extensions that are really two, so the frame number belongs before both.
# os.path.splitext("cache.bgeo.sc") yields ("cache.bgeo", ".sc"), which produced
# "cache.bgeo.0001.sc" -- a name Houdini writes but no sequence reader recognises.
_COMPOUND_EXTENSIONS = (".bgeo.sc", ".bgeo.gz", ".geo.gz", ".vdb.gz", ".usd.gz", ".tar.gz")


def _split_sequence_extension(file_path: str) -> tuple[str, str]:
    """Split a path so a frame number can go where Houdini expects it.

    Returns ``(base, extension)`` such that ``f"{base}.0001{extension}"`` is the
    conventional sequence name: ``cache.0001.bgeo.sc``, not ``cache.bgeo.0001.sc``.
    """
    lowered = file_path.lower()
    for compound in _COMPOUND_EXTENSIONS:
        if lowered.endswith(compound):
            return file_path[: -len(compound)], file_path[-len(compound) :]
    return os.path.splitext(file_path)


###### scene.get_scene_info


def get_scene_info() -> dict:
    """Return comprehensive information about the current Houdini scene."""
    hip_path = hou.hipFile.path()
    version = hou.applicationVersionString()
    fps = hou.fps()
    frame_range = list(hou.playbar.playbackRange())
    current_frame = hou.frame()

    # Count nodes by top-level context
    node_counts = {}
    for child in hou.node("/").children():
        category = child.type().category().name()
        node_counts[category] = node_counts.get(category, 0) + 1

    # Memory usage (in MB)
    try:
        mem_bytes = hou.ui.memoryUsageMessage()  # type: ignore[attr-defined]
    except Exception:
        mem_bytes = None

    return {
        "hip_file": hip_path,
        "houdini_version": version,
        "fps": fps,
        "frame_range": frame_range,
        "current_frame": current_frame,
        "node_counts": node_counts,
        "memory_usage": mem_bytes,
        "update_mode": update_mode_name(),
    }


###### scene.new_scene


def new_scene(save_current: bool = False) -> dict:
    """Create a new empty Houdini scene.

    Args:
        save_current: If True, save the current scene before clearing.
    """
    if save_current:
        hou.hipFile.save()

    hou.hipFile.clear(suppress_save_prompt=True)

    return {
        "success": True,
        "hip_file": hou.hipFile.path(),
        "message": "New scene created.",
    }


###### scene.save_scene


def save_scene(file_path: str = None) -> dict:
    """Save the current Houdini scene.

    Args:
        file_path: Destination path. If None, saves to the current hip path.
    """
    if file_path is not None:
        require_inside_project_root(file_path, "hip file")
        hou.hipFile.save(file_name=file_path)
    else:
        require_inside_project_root(hou.hipFile.path(), "hip file")
        hou.hipFile.save()

    return {
        "success": True,
        "hip_file": hou.hipFile.path(),
    }


###### scene.load_scene

# Characters that make a node path a pattern. merge's node_pattern would
# honour them, but the per-path report could not say what each one brought.
_PATTERN_CHARS = frozenset("*?^[] ")


def _warning_lines(warning: Exception) -> list[str]:
    return [line.strip() for line in str(warning).splitlines() if line.strip()]


def _children_of(paths) -> dict[str, set]:
    """Child paths of each watched network, keyed by its path."""
    snapshot: dict[str, set] = {}
    for path in paths:
        node = hou.node(path)
        snapshot[path] = set()
        if node is not None:
            with contextlib.suppress(Exception):
                snapshot[path] = {child.path() for child in node.children()}
    return snapshot


def _base_name(name: str) -> str:
    """null12 -> null: the stem Houdini renumbers when a name is taken."""
    return name.rstrip("0123456789")


def _merge(file_path: str, node_paths: list | None, overwrite_on_conflict: bool) -> dict:
    if node_paths is not None and not isinstance(node_paths, (list, tuple)):
        raise ValueError("node_paths must be a list of absolute node paths.")
    requested = [str(p).rstrip("/") for p in (node_paths or [])]
    for path in requested:
        if not path.startswith("/"):
            raise ValueError(f"node_paths must be absolute (got {path!r}); e.g. '/obj/{path}'.")
        pattern_chars = sorted(set(path) & _PATTERN_CHARS)
        if pattern_chars:
            raise ValueError(
                f"node_paths are node paths, not patterns: {path!r} contains "
                f"{pattern_chars}. List each node, or omit node_paths to merge everything."
            )
    if node_paths is not None and not requested:
        return {
            "success": True,
            "file_path": file_path,
            "merged_nodes": [],
            "merged_count": 0,
            "message": "node_paths is empty: nothing was merged. Omit it to merge everything.",
        }

    # A container named alone comes without its children, so each path is
    # sent with its contents.
    pattern = " ".join(f"{path} {path}/*" for path in requested) if requested else "*"
    if requested:
        watched = sorted({path.rpartition("/")[0] for path in requested})
    else:
        watched = [context.path() for context in hou.node("/").children()]
    colliding: set = set()
    with contextlib.suppress(Exception):
        colliding = {
            node.path()
            for node in hou.hipFile.collisionNodesIfMerged(file_path, node_pattern=pattern)
        }
    before = _children_of(watched)
    warnings: list[str] = []
    try:
        hou.hipFile.merge(
            file_path,
            node_pattern=pattern,
            overwrite_on_conflict=bool(overwrite_on_conflict),
            ignore_load_warnings=False,
        )
    except hou.LoadWarning as warning:
        warnings = _warning_lines(warning)
    after = _children_of(watched)
    arrived = set()
    for network, paths in after.items():
        arrived |= paths - before.get(network, set())

    # Attribute what arrived to what was asked for. A colliding node was
    # either overwritten in place or renumbered (null1 -> null2) next to it.
    subjects = requested or sorted(path for path in colliding if path.rpartition("/")[0] in before)
    claimed: set = set()
    overwritten: list[str] = []
    conflicts: list[dict] = []
    missing: list[str] = []
    for path in subjects:
        parent, _, name = path.rpartition("/")
        if path in colliding and overwrite_on_conflict:
            overwritten.append(path)
            conflicts.append({"requested": path, "outcome": "overwritten in place"})
            continue
        if path in colliding:
            candidates = sorted(
                (
                    p
                    for p in arrived - claimed
                    if p.rpartition("/")[0] == parent
                    and p not in requested
                    and _base_name(p.rpartition("/")[2]) == _base_name(name)
                ),
                key=lambda p: (len(p), p),
            )
            if candidates:
                claimed.add(candidates[0])
                conflicts.append(
                    {
                        "requested": path,
                        "outcome": "merged under a new name",
                        "merged_as": candidates[0],
                    }
                )
                continue
        elif path in arrived:
            claimed.add(path)
            continue
        if requested:
            missing.append(path)

    merged = sorted(arrived | set(overwritten))
    descendants = 0
    for path in merged:
        with contextlib.suppress(Exception):
            descendants += len(hou.node(path).allSubChildren())
    result = {
        # Asking for nodes and getting none is a failed merge, whatever the
        # reason (not in the file, a missing parent, an unreadable file).
        "success": bool(merged) or (not requested and not warnings),
        "file_path": file_path,
        "node_pattern": pattern,
        "merged_nodes": merged,
        "merged_count": len(merged),
        "merged_descendant_count": descendants,
        "conflicts": conflicts,
        "not_found_in_file": missing,
        "warnings": warnings,
        "hip_file": hou.hipFile.path(),
        "has_unsaved_changes": hou.hipFile.hasUnsavedChanges(),
        "message": (
            f"Merged {len(merged)} node(s) from {file_path} into the current scene"
            + (f" with {len(warnings)} load warning(s)." if warnings else ".")
        ),
    }
    if missing:
        result["note"] = (
            "Paths in not_found_in_file brought nothing: check they are absolute "
            "paths that exist in the file, under a parent that exists in this scene."
        )
    return result


def load_scene(
    file_path: str,
    merge: bool = False,
    node_paths: list | None = None,
    overwrite_on_conflict: bool = False,
) -> dict:
    """Open a hip file, or merge it (or named nodes from it) into this scene.

    Load warnings (missing assets and the like) come back in `warnings`
    instead of failing the call. A merge reports what arrived: node_paths
    are absolute (`/obj/building`), each brought with its contents; a node
    that already exists is merged under a new name unless
    overwrite_on_conflict=True overwrites it in place, and `conflicts` says
    which.

    Args:
        file_path: Path to the .hip/.hipnc/.hiplc file.
        merge: If True, merge nodes into the current scene instead of replacing it.
        node_paths: With merge, the absolute node paths to merge; default everything.
        overwrite_on_conflict: With merge, overwrite same-named nodes instead
            of renaming the merged copy.
    """
    require_inside_project_root(file_path, "hip file")
    if not os.path.isfile(hou.text.expandString(file_path)):
        raise FileNotFoundError(f"File not found: {file_path}")
    if not merge and (node_paths is not None or overwrite_on_conflict):
        raise ValueError("node_paths and overwrite_on_conflict apply only with merge=True.")

    if merge:
        return _merge(file_path, node_paths, overwrite_on_conflict)

    warnings: list[str] = []
    try:
        hou.hipFile.load(file_path, suppress_save_prompt=True, ignore_load_warnings=False)
    except hou.LoadWarning as warning:
        warnings = _warning_lines(warning)
    message = f"Loaded {file_path}."
    if warnings:
        message = f"Loaded {file_path} with {len(warnings)} load warning(s)."
    return {
        "success": True,
        "hip_file": hou.hipFile.path(),
        "message": message,
        "warnings": warnings,
    }


###### scene.import_file


def import_file(
    file_path: str,
    parent_path: str = "/obj",
    node_name: str = None,
) -> dict:
    """Import a geometry, USD, or Alembic file into the scene.

    Supports .bgeo, .obj, .abc, .usd, .usda, .usdc, and similar formats.
    Creates the appropriate node type under the given parent network.

    Args:
        file_path: Path to the file to import.
        parent_path: Network path under which to create the import node.
        node_name: Optional explicit node name.
    """
    require_inside_project_root(file_path, "import file")
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    parent = hou.node(parent_path)
    if parent is None:
        raise ValueError(f"Parent node not found: {parent_path}")

    ext = os.path.splitext(file_path)[1].lower()

    # Decide the import strategy from what the parent can contain — the
    # default parent /obj is a Manager whose children are Object nodes.
    child_category = parent.childTypeCategory()
    child_cat = child_category.name() if child_category is not None else None

    if ext in (".abc",):
        # Alembic: alembic SOP inside SOP networks, archive elsewhere
        if child_cat == "Sop":
            node = parent.createNode("alembic", node_name or "alembic_import")
            node.parm("fileName").set(file_path)
            created_path = node.path()
        else:
            container = parent.createNode("alembicarchive", node_name or "alembic_import")
            container.parm("fileName").set(file_path)
            press(container.parm("buildHierarchy"))  # a Python callback
            created_path = container.path()
    elif ext in (".usd", ".usda", ".usdc", ".usdz"):
        # USD: use a sublayer inside LOP networks, a LOP network elsewhere
        if child_cat == "Lop":
            node = parent.createNode("sublayer", node_name or "usd_import")
            node.parm("filepath1").set(file_path)
            created_path = node.path()
        else:
            lopnet = parent.createNode("lopnet", node_name or "usd_import")
            sub = lopnet.createNode("sublayer", "sublayer1")
            sub.parm("filepath1").set(file_path)
            created_path = lopnet.path()
    else:
        # Generic geometry: a File SOP, wrapped in a geo container when
        # the parent cannot hold SOPs directly
        if child_cat == "Sop":
            file_node = parent.createNode("file", node_name or "file_import")
            file_node.parm("file").set(file_path)
            created_path = file_node.path()
        else:
            geo = parent.createNode("geo", node_name or "file_import")
            # Remove default file node if present
            for child in geo.children():
                child.destroy()
            file_node = geo.createNode("file", "file1")
            file_node.parm("file").set(file_path)
            file_node.setDisplayFlag(True)
            file_node.setRenderFlag(True)
            created_path = geo.path()

    # Focus on the created node
    created_node = hou.node(created_path)
    if created_node is not None:
        _focus_network_editor(created_node)

    return {
        "success": True,
        "node_path": created_path,
        "file_path": file_path,
    }


###### scene.export_file


def export_file(
    node_path: str,
    file_path: str,
    frame_range: list = None,
) -> dict:
    """Export a node's output to a file on disk.

    For SOP nodes, uses the geometry's saveToFile method.
    For ROP/Driver nodes, executes the render.
    For LOP nodes, exports the USD stage.

    Args:
        node_path: Path to the node whose output to export.
        file_path: Destination file path.
        frame_range: Optional [start, end] or [start, end, step] frame range.
    """
    node = hou.node(node_path)
    if node is None:
        raise ValueError(f"Node not found: {node_path}")
    require_inside_project_root(file_path, "export file")

    category = node.type().category().name()

    if category == "Sop":
        # Export geometry. saveToFile raises on failure, so returning normally is
        # genuine evidence here -- unlike the Driver branch below.
        geo = node.geometry()
        if geo is None:
            raise ValueError(f"Node {node_path} has no geometry (cook may have failed).")
        if frame_range is not None:
            start = int(frame_range[0])
            end = int(frame_range[1])
            step = int(frame_range[2]) if len(frame_range) > 2 else 1
            saved_frames = []
            # Exporting is a query, so it must not move the playbar. This loop used
            # to leave the scene parked on the last exported frame, which silently
            # changed what every later tool saw.
            original_frame = hou.frame()
            try:
                base, ext = _split_sequence_extension(file_path)
                for frame in range(start, end + 1, step):
                    hou.setFrame(frame)
                    frame_geo = node.geometry()
                    frame_file = f"{base}.{frame:04d}{ext}"
                    frame_geo.saveToFile(frame_file)
                    saved_frames.append(frame_file)
            finally:
                hou.setFrame(original_frame)
            return {
                "success": True,
                "node_path": node_path,
                "files": saved_frames,
                "frame_range": frame_range,
                "restored_frame": original_frame,
            }
        else:
            geo.saveToFile(file_path)
            return {
                "success": True,
                "node_path": node_path,
                "file_path": file_path,
            }
    elif category == "Driver":
        # Two things were wrong here. A ROP's render() returning without raising is
        # NOT evidence that anything was written -- it may shell out to husk or
        # mantra, and a non-zero exit is recorded on the node while render() returns
        # normally -- yet this branch answered with the hardcoded string "Render
        # complete." regardless. And it ignored file_path altogether, rendering to
        # whatever the ROP's own output parm already said, while the docstring
        # promised file_path was the destination.
        target_parm = next((p for name in OUTPUT_PARMS if (p := node.parm(name))), None)
        if target_parm is None:
            raise ValueError(
                f"{node_path} has no recognised output parameter "
                f"({', '.join(OUTPUT_PARMS)}), so there is nowhere to write "
                f"'{file_path}'. Set the ROP's output path and use start_render."
            )
        # Repointing the ROP is a means, not the request, so put it back afterwards
        # rather than leaving the artist's node aimed somewhere they did not choose.
        original_output = target_parm.unexpandedString()
        target_parm.set(file_path)
        try:
            before = reported_outputs(node)
            try:
                if frame_range is not None:
                    start = float(frame_range[0])
                    end = float(frame_range[1])
                    step = float(frame_range[2]) if len(frame_range) > 2 else 1.0
                    # The increment is the third element of frame_range; there is no
                    # frame_increment keyword, and passing one raises TypeError.
                    node.render(frame_range=(start, end, step), output_progress=True)
                else:
                    node.render(output_progress=True)
            except hou.OperationFailed as e:
                return {
                    "node_path": node_path,
                    "requested_path": file_path,
                    "output_parm": target_parm.name(),
                    **failure_verdict(node, before, e, action="Export"),
                }
            return {
                "node_path": node_path,
                "requested_path": file_path,
                "output_parm": target_parm.name(),
                **write_verdict(node, before, action="Export"),
            }
        finally:
            with contextlib.suppress(Exception):
                target_parm.set(original_output)
    elif category == "Lop":
        # USD export. Export() raises on failure, but it also returns False on
        # some failures rather than raising, so take it at its word either way.
        stage = node.stage()
        if stage is None:
            raise ValueError(f"Node {node_path} has no USD stage.")
        exported = stage.Export(file_path)
        wrote = os.path.exists(file_path)
        return {
            "success": exported is not False and wrote,
            "node_path": node_path,
            "file_path": file_path,
            "wrote_files": wrote,
            "message": (
                "Exported USD stage."
                if wrote
                else f"Export returned without raising, but no file exists at {file_path}."
            ),
        }
    else:
        raise ValueError(
            f"Export not supported for node category '{category}'. "
            "Supported categories: Sop, Driver, Lop."
        )


###### scene.get_context_info


def get_context_info(context: str) -> dict:
    """Return detailed information about a network context.

    Args:
        context: Context path (e.g. "/obj", "/stage", "/out", "/shop", "/ch", "/img").
    """
    ctx_node = hou.node(context)
    if ctx_node is None:
        raise ValueError(f"Context not found: {context}")

    children = ctx_node.children()
    child_info = []
    for child in children:
        info = {
            "name": child.name(),
            "path": child.path(),
            "type": child.type().name(),
            "category": child.type().category().name(),
        }
        # Safely get errors/warnings
        try:
            errors = child.errors()
            warnings = child.warnings()
            info["errors"] = list(errors) if errors else []
            info["warnings"] = list(warnings) if warnings else []
        except Exception:
            info["errors"] = []
            info["warnings"] = []
        child_info.append(info)

    # Available node type categories at this level
    try:
        cat_name = ctx_node.type().childTypeCategory().name()
    except Exception:
        cat_name = None

    return {
        "context_path": context,
        "node_type": ctx_node.type().name(),
        "category": ctx_node.type().category().name(),
        "child_type_category": cat_name,
        "child_count": len(children),
        "children": child_info,
    }


###### scene.undo / scene.redo


def _undo_available() -> None:
    if not hou.undos.areEnabled():
        raise RuntimeError(
            "Undo is not available in this session (hython and batch mode keep no "
            "undo history). Undo needs a graphical Houdini."
        )


def undo(steps: int = 1) -> dict:
    """Undo the most recent change(s).

    Every MCP command is one undo step, so one call reverses one tool call
    however many nodes it touched.

    Args:
        steps: How many steps to undo (default 1).
    """
    _undo_available()
    steps = max(1, int(steps))
    undone: list[str] = []
    for _ in range(steps):
        labels = hou.undos.undoLabels()
        if not labels:
            break
        hou.undos.performUndo()
        undone.append(labels[0])
    if not undone:
        return {"success": False, "undone": [], "message": "Nothing to undo."}
    return {
        "success": True,
        "undone": undone,
        "remaining": len(hou.undos.undoLabels()),
    }


def redo(steps: int = 1) -> dict:
    """Redo the most recently undone change(s).

    Args:
        steps: How many steps to redo (default 1).
    """
    _undo_available()
    steps = max(1, int(steps))
    redone: list[str] = []
    for _ in range(steps):
        labels = hou.undos.redoLabels()
        if not labels:
            break
        hou.undos.performRedo()
        redone.append(labels[0])
    if not redone:
        return {"success": False, "redone": [], "message": "Nothing to redo."}
    return {
        "success": True,
        "redone": redone,
        "remaining": len(hou.undos.redoLabels()),
    }


###### Registration

register_handler("scene.undo", undo)
register_handler("scene.redo", redo)
register_handler("scene.get_scene_info", get_scene_info)
register_handler("scene.new_scene", new_scene)
register_handler("scene.save_scene", save_scene)
register_handler("scene.load_scene", load_scene)
register_handler("scene.import_file", import_file)
register_handler("scene.export_file", export_file)
register_handler("scene.get_context_info", get_context_info)
