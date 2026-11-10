"""MCP tool wrappers for Houdini scene operations.

Each tool delegates to the corresponding handler running inside Houdini
via the HTTP bridge.
"""

from __future__ import annotations

# Built-in
from typing import Any

# Third-party
from fxhoudinimcp._sdk import Context

# Internal
from fxhoudinimcp.compat import compatibility_warning, missing_commands
from fxhoudinimcp.errors import ConnectionError as HoudiniConnectionError
from fxhoudinimcp.node_versions import sampled_series, staleness_warning
from fxhoudinimcp.server import _get_bridge, mcp


@mcp.tool()
async def get_houdini_connection_status(ctx: Context) -> dict:
    """Check the MCP-to-Houdini bridge without raising on disconnect.

    Returns structured connection diagnostics, including the configured bridge
    URL and Houdini health payload when reachable, and `sessions`: every
    Houdini serving the plugin (port, pid, version), the one in use marked
    current. connect_houdini switches; start_houdini starts one. Use this
    before live viewport workflows when Houdini may have restarted.
    """
    from fxhoudinimcp.tools.session import list_sessions

    bridge = _get_bridge(ctx)
    try:
        sessions = await list_sessions(bridge)
    except Exception:
        sessions = None
    try:
        health = await bridge.health_check()
    except HoudiniConnectionError as exc:
        return {
            "connected": False,
            "base_url": bridge.base_url,
            "error": str(exc),
            "details": exc.details,
            "sessions": sessions,
        }
    except Exception as exc:
        return {
            "connected": False,
            "base_url": bridge.base_url,
            "error": str(exc),
            "details": {"type": type(exc).__name__},
            "sessions": sessions,
        }

    # mcp.health is deliberately free of hou.* access, so it cannot report the
    # open scene. Fetch that separately to keep this tool's payload shape
    # unchanged for callers that read health["hip_file"].
    #
    # Best-effort with a short timeout, and never fatal: unlike health, this
    # goes through main-thread dispatch, so a busy Houdini would otherwise turn
    # a diagnostic that is supposed to always answer into one that hangs.
    health = dict(health)
    if "hip_file" not in health:
        try:
            scene = await bridge.execute("scene.get_scene_info", timeout=5.0)
        except Exception:
            scene = None
        if isinstance(scene, dict):
            for key in ("hip_file", "houdini_version"):
                if scene.get(key) is not None:
                    health.setdefault(key, scene[key])

    payload = {
        "connected": True,
        "base_url": bridge.base_url,
        "health": health,
        "sessions": sessions,
    }

    # Advisory only: tells the assistant when the version markers in the
    # instructions were never checked against this Houdini, so it knows to
    # confirm node names rather than trusting a "(21.0+)" to include it.
    stale = staleness_warning(health.get("houdini_version"))
    if stale:
        payload["node_version_data"] = {
            "sampled_series": sampled_series(),
            "warning": stale,
        }

    # Surface a plugin older than this server, so a later "No handler registered
    # for command" is recognisable as a version gap rather than a bug.
    try:
        available = await bridge.list_commands()
    except Exception:
        available = None
    if available is not None:
        mismatch = compatibility_warning(available)
        if mismatch:
            payload["plugin_compatibility"] = {
                "missing_commands": missing_commands(available),
                "warning": mismatch,
            }

    return payload


@mcp.tool()
async def get_scene_info(ctx: Context) -> dict:
    """Get information about the current Houdini scene."""
    bridge = _get_bridge(ctx)
    return await bridge.execute("scene.get_scene_info")


@mcp.tool()
async def new_scene(ctx: Context, save_current: bool = False) -> dict:
    """Create a new empty Houdini scene.

    Args:
        save_current: Save the current scene before clearing.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("scene.new_scene", {"save_current": save_current})


@mcp.tool()
async def save_scene(ctx: Context, file_path: str | None = None) -> dict:
    """Save the current Houdini scene to disk.

    Args:
        file_path: Destination path; defaults to the current hip file.
    """
    bridge = _get_bridge(ctx)
    params: dict = {}
    if file_path is not None:
        params["file_path"] = file_path
    return await bridge.execute("scene.save_scene", params)


@mcp.tool()
async def load_scene(
    ctx: Context,
    file_path: str,
    merge: bool = False,
    node_paths: list[str] | None = None,
    overwrite_on_conflict: bool = False,
) -> dict:
    """Open a Houdini hip file, or merge it — or named nodes from it — into
    the current scene.

    Load warnings (missing assets and the like) come back in `warnings`.
    A merge reports what arrived: `merged_nodes`, `conflicts` (a node that
    already exists is merged under a new name, or overwritten in place with
    overwrite_on_conflict=True) and `not_found_in_file`. node_paths are
    absolute (`/obj/building_v3`) and bring their contents. A merge keeps
    the scene's `set -g` variables ($JOB, $POSE) the file would overwrite,
    named in `globals_restored` with the file's value and the kept one;
    variables the file adds are listed in `globals_added`.

    Args:
        file_path: Path to the hip file to open; $JOB, $HIP and other
            variables are expanded.
        merge: Merge into the current scene instead of replacing it.
        node_paths: With merge, the absolute node paths to merge; default
            everything.
        overwrite_on_conflict: With merge, overwrite same-named nodes
            instead of renaming the merged copy.
    """
    bridge = _get_bridge(ctx)
    payload: dict[str, Any] = {"file_path": file_path, "merge": merge}
    # Sent only when used, so a plugin that predates them still loads and
    # merges whole files.
    if node_paths is not None:
        payload["node_paths"] = node_paths
    if overwrite_on_conflict:
        payload["overwrite_on_conflict"] = True
    return await bridge.execute("scene.load_scene", payload)


@mcp.tool()
async def import_file(
    ctx: Context,
    file_path: str,
    parent_path: str = "/obj",
    node_name: str | None = None,
) -> dict:
    """Import a geometry, USD, or Alembic file into the scene.

    Args:
        file_path: Path to the file to import.
        parent_path: Network path for the import node.
        node_name: Name for the created node.
    """
    bridge = _get_bridge(ctx)
    params: dict = {
        "file_path": file_path,
        "parent_path": parent_path,
    }
    if node_name is not None:
        params["node_name"] = node_name
    return await bridge.execute("scene.import_file", params)


@mcp.tool()
async def export_file(
    ctx: Context,
    node_path: str,
    file_path: str,
    frame_range: list[float] | None = None,
) -> dict:
    """Export a node's output to a file on disk, and report whether it landed.

    SOPs are saved directly, LOPs export their USD stage, and a /out ROP is
    pointed at file_path and executed (its own output path is restored
    afterwards). Reports `wrote_files`, so `success: True` means a file appeared
    or changed -- not merely that the call returned. A frame_range writes
    `name.0001.ext` per frame and leaves the playbar where it was.

    Args:
        node_path: Path to the node to export.
        file_path: Destination file path. For a ROP this overrides its output
            parameter for the duration of the export.
        frame_range: Frame range as [start, end] or [start, end, step].
    """
    bridge = _get_bridge(ctx)
    params: dict = {
        "node_path": node_path,
        "file_path": file_path,
    }
    if frame_range is not None:
        params["frame_range"] = frame_range
    return await bridge.execute("scene.export_file", params)


@mcp.tool()
async def get_context_info(ctx: Context, context: str) -> dict:
    """Get information about a Houdini network context.

    Args:
        context: Context path, e.g. "/obj", "/stage", "/out".
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("scene.get_context_info", {"context": context})


@mcp.tool()
async def undo(ctx: Context, steps: int = 1) -> dict:
    """Undo the last change(s) made in Houdini.

    Every tool call is one undo step, however many nodes it touched, so one
    undo reverses one build_network or set_parameters call. Needs a graphical
    Houdini: hython keeps no undo history.

    Args:
        ctx: MCP context.
        steps: How many steps to undo (default 1).
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("scene.undo", {"steps": steps})


@mcp.tool()
async def redo(ctx: Context, steps: int = 1) -> dict:
    """Redo the last undone change(s) in Houdini.

    Args:
        ctx: MCP context.
        steps: How many steps to redo (default 1).
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("scene.redo", {"steps": steps})
