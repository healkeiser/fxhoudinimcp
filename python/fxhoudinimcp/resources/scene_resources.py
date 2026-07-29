"""MCP resources for scene state and node information."""

from __future__ import annotations

# Internal
from fxhoudinimcp.server import current_bridge, mcp


@mcp.resource("houdini://scene/info")
async def scene_info() -> dict:
    """Current Houdini scene information including hip file, version, frame range, and node counts."""
    bridge = current_bridge()
    return await bridge.execute("scene.get_scene_info", {})


@mcp.resource("houdini://scene/nodes/{path}")
async def node_info(path: str) -> dict:
    """Information about a specific node at the given path."""
    bridge = current_bridge()
    return await bridge.execute("nodes.get_node_info", {"node_path": f"/{path}"})


@mcp.resource("houdini://scene/tree")
async def scene_tree() -> dict:
    """Top-level node tree of the current scene."""
    bridge = current_bridge()
    return await bridge.execute("scene.get_context_info", {"context": "/"})


@mcp.resource("houdini://errors")
async def scene_errors() -> dict:
    """All nodes with errors or warnings in the scene."""
    bridge = current_bridge()
    return await bridge.execute("viewport.find_error_nodes", {"root_path": "/"})


@mcp.resource("houdini://node-types/{context}")
async def node_types(context: str) -> dict:
    """Available node types for a given context (Sop, Lop, Dop, Top, Cop2, Object, Driver)."""
    bridge = current_bridge()
    return await bridge.execute("nodes.list_node_types", {"context": context})


@mcp.resource("houdini://hdas")
async def installed_hdas() -> dict:
    """List of installed Houdini Digital Assets."""
    bridge = current_bridge()
    return await bridge.execute("hda.list_installed_hdas", {})
