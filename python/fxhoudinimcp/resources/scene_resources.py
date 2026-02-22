"""MCP resources for scene state and node information."""

from __future__ import annotations

# Third-party
from mcp.server.fastmcp import Context

# Internal
from fxhoudinimcp.server import mcp, _get_bridge


@mcp.resource("houdini://scene/info")
async def scene_info(ctx: Context) -> dict:
    """Current Houdini scene information including hip file, version, frame range, and node counts."""
    bridge = _get_bridge(ctx)
    return await bridge.execute("scene.get_scene_info", {})


@mcp.resource("houdini://scene/nodes/{path}")
async def node_info(path: str, ctx: Context) -> dict:
    """Information about a specific node at the given path."""
    bridge = _get_bridge(ctx)
    return await bridge.execute("nodes.get_node_info", {"node_path": f"/{path}"})


@mcp.resource("houdini://scene/tree")
async def scene_tree(ctx: Context) -> dict:
    """Complete node tree of the current scene."""
    bridge = _get_bridge(ctx)
    return await bridge.execute("scene.get_context_info", {"context": "all"})


@mcp.resource("houdini://errors")
async def scene_errors(ctx: Context) -> dict:
    """All nodes with errors or warnings in the scene."""
    bridge = _get_bridge(ctx)
    return await bridge.execute("viewport.find_error_nodes", {"root_path": "/"})


@mcp.resource("houdini://node-types/{context}")
async def node_types(context: str, ctx: Context) -> dict:
    """Available node types for a given context (Sop, Lop, Dop, Top, Cop2, Object, Driver)."""
    bridge = _get_bridge(ctx)
    return await bridge.execute("nodes.list_node_types", {"context": context})


@mcp.resource("houdini://hdas")
async def installed_hdas(ctx: Context) -> dict:
    """List of installed Houdini Digital Assets."""
    bridge = _get_bridge(ctx)
    return await bridge.execute("hda.list_installed_hdas", {})
