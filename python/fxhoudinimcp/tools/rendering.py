"""MCP tool definitions for Houdini rendering operations.

Provides tools for viewport capture, render node management, render execution,
and render progress monitoring.
"""

from __future__ import annotations

# Built-in
from typing import Any

# Third-party
from mcp.server.fastmcp import Context
from mcp.types import ImageContent, TextContent

# Internal
from fxhoudinimcp.server import mcp, _get_bridge
from fxhoudinimcp.tools import result_with_image


@mcp.tool()
async def render_viewport(
    ctx: Context,
    output_path: str,
    resolution: list[int] | None = None,
    camera: str | None = None,
) -> list[TextContent | ImageContent]:
    """Capture the current 3D viewport to an image file.

    Args:
        output_path: Image file path.
        resolution: [width, height] in pixels.
        camera: Camera node path.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"output_path": output_path}
    if resolution is not None:
        params["resolution"] = resolution
    if camera is not None:
        params["camera"] = camera
    result = await bridge.execute("rendering.render_viewport", params)
    return result_with_image(result)


@mcp.tool()
async def render_quad_view(
    ctx: Context,
    output_path: str,
    resolution: list[int] | None = None,
) -> dict:
    """Capture all four viewport panes to separate images.

    Args:
        output_path: Base image path; viewport names are appended.
        resolution: [width, height] in pixels.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"output_path": output_path}
    if resolution is not None:
        params["resolution"] = resolution
    return await bridge.execute("rendering.render_quad_view", params)


@mcp.tool()
async def list_render_nodes(ctx: Context) -> dict:
    """List all render (ROP/Driver) nodes in the scene."""
    bridge = _get_bridge(ctx)
    return await bridge.execute("rendering.list_render_nodes", {})


@mcp.tool()
async def get_render_settings(ctx: Context, node_path: str) -> dict:
    """Get render settings from a ROP node.

    Args:
        node_path: ROP node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "rendering.get_render_settings", {"node_path": node_path}
    )


@mcp.tool()
async def set_render_settings(
    ctx: Context,
    node_path: str,
    settings: dict[str, Any] = {},
) -> dict:
    """Set render parameters on a ROP node.

    Args:
        node_path: ROP node path.
        settings: Parameter name-value pairs.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "rendering.set_render_settings",
        {"node_path": node_path, "settings": settings},
    )


@mcp.tool()
async def create_render_node(
    ctx: Context,
    renderer: str,
    name: str | None = None,
    camera: str | None = None,
    output_path: str | None = None,
) -> dict:
    """Create a new render (ROP) node in /out.

    Args:
        renderer: Renderer type ('karma', 'opengl', 'mantra', 'rop_geometry', 'rop_alembic', 'usdrender', 'fetch', 'merge').
        name: Node name.
        camera: Camera node path.
        output_path: Output file path.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"renderer": renderer}
    if name is not None:
        params["name"] = name
    if camera is not None:
        params["camera"] = camera
    if output_path is not None:
        params["output_path"] = output_path
    return await bridge.execute("rendering.create_render_node", params)


@mcp.tool()
async def start_render(
    ctx: Context,
    node_path: str,
    frame_range: list[float] | None = None,
) -> dict:
    """Render a ROP node.

    Args:
        node_path: ROP node path.
        frame_range: [start, end] or [start, end, increment].
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"node_path": node_path}
    if frame_range is not None:
        params["frame_range"] = frame_range
    return await bridge.execute("rendering.start_render", params)


@mcp.tool()
async def render_node_network(
    ctx: Context,
    node_path: str,
    output_path: str,
) -> dict:
    """Capture a screenshot of a node's network editor view.

    Args:
        node_path: Node path to focus on.
        output_path: Image file path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "rendering.render_node_network",
        {"node_path": node_path, "output_path": output_path},
    )


@mcp.tool()
async def get_render_progress(ctx: Context, node_path: str) -> dict:
    """Get render progress and status of a ROP node.

    Args:
        node_path: ROP node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "rendering.get_render_progress", {"node_path": node_path}
    )
