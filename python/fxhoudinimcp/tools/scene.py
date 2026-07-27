"""MCP tool wrappers for Houdini scene operations.

Each tool delegates to the corresponding handler running inside Houdini
via the HTTP bridge.
"""

from __future__ import annotations

# Built-in
from typing import Optional

# Third-party
from mcp.server.fastmcp import Context

# Internal
from fxhoudinimcp.errors import ConnectionError as HoudiniConnectionError
from fxhoudinimcp.node_versions import sampled_series, staleness_warning
from fxhoudinimcp.server import mcp, _get_bridge


@mcp.tool()
async def get_houdini_connection_status(ctx: Context) -> dict:
    """Check the Codex-to-Houdini bridge without raising on disconnect.

    Returns structured connection diagnostics, including the configured bridge
    URL and Houdini health payload when reachable. Use this before live viewport
    workflows when Houdini may have restarted or its hwebserver may not be
    running.
    """
    bridge = _get_bridge(ctx)
    try:
        health = await bridge.health_check()
    except HoudiniConnectionError as exc:
        return {
            "connected": False,
            "base_url": bridge.base_url,
            "error": str(exc),
            "details": exc.details,
        }
    except Exception as exc:
        return {
            "connected": False,
            "base_url": bridge.base_url,
            "error": str(exc),
            "details": {"type": type(exc).__name__},
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
    return await bridge.execute(
        "scene.new_scene", {"save_current": save_current}
    )


@mcp.tool()
async def save_scene(ctx: Context, file_path: Optional[str] = None) -> dict:
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
async def load_scene(ctx: Context, file_path: str, merge: bool = False) -> dict:
    """Open or merge a Houdini hip file.

    Args:
        file_path: Path to the hip file to open.
        merge: Merge into the current scene instead of replacing it.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "scene.load_scene",
        {
            "file_path": file_path,
            "merge": merge,
        },
    )


@mcp.tool()
async def import_file(
    ctx: Context,
    file_path: str,
    parent_path: str = "/obj",
    node_name: Optional[str] = None,
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
    frame_range: Optional[list[float]] = None,
) -> dict:
    """Export a node's output to a file on disk.

    Args:
        node_path: Path to the node to export.
        file_path: Destination file path.
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
