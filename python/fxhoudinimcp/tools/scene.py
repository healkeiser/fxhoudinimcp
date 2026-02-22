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
from fxhoudinimcp.server import mcp, _get_bridge


@mcp.tool()
async def get_scene_info(ctx: Context) -> dict:
    """Get comprehensive information about the current Houdini scene.

    Returns the hip file path, Houdini version, FPS, frame range,
    current frame, node counts by context, and memory usage.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("scene.get_scene_info")


@mcp.tool()
async def new_scene(ctx: Context, save_current: bool = False) -> dict:
    """Create a new empty Houdini scene.

    Args:
        ctx: MCP context.
        save_current: If True, save the current scene before clearing it.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("scene.new_scene", {"save_current": save_current})


@mcp.tool()
async def save_scene(ctx: Context, file_path: Optional[str] = None) -> dict:
    """Save the current Houdini scene to disk.

    Args:
        ctx: MCP context.
        file_path: Destination file path. If omitted, saves to the current hip file path.
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
        ctx: MCP context.
        file_path: Path to the .hip / .hipnc / .hiplc file to open.
        merge: If True, merge the file into the current scene instead of replacing it.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("scene.load_scene", {
        "file_path": file_path,
        "merge": merge,
    })


@mcp.tool()
async def import_file(
    ctx: Context,
    file_path: str,
    parent_path: str = "/obj",
    node_name: Optional[str] = None,
) -> dict:
    """Import a geometry, USD, or Alembic file into the Houdini scene.

    Automatically creates the appropriate node type based on the file extension.
    Supported formats include .bgeo, .obj, .abc, .usd, .usda, .usdc, and more.

    Args:
        ctx: MCP context.
        file_path: Path to the file to import.
        parent_path: Network path under which to create the import node (default: "/obj").
        node_name: Optional explicit name for the created node.
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
    frame_range: Optional[list] = None,
) -> dict:
    """Export a node's output to a file on disk.

    For SOP nodes, exports the cooked geometry. For ROP/Driver nodes,
    triggers a render. For LOP nodes, exports the USD stage.

    Args:
        ctx: MCP context.
        node_path: Path to the node whose output to export.
        file_path: Destination file path on disk.
        frame_range: Optional frame range as [start, end] or [start, end, step].
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
    """Get detailed information about a Houdini network context.

    Returns the context's node type, child type category, child count,
    and a list of all children with their types, errors, and warnings.

    Args:
        ctx: MCP context.
        context: Context path such as "/obj", "/stage", "/out", "/shop", "/ch", or "/img".
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("scene.get_context_info", {"context": context})
