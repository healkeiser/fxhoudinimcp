"""MCP tool definitions for Houdini rendering operations.

Provides tools for viewport capture, render node management, render execution,
and render progress monitoring.
"""

from __future__ import annotations

# Built-in
from typing import Any

# Third-party
from mcp.server.fastmcp import Context

# Internal
from fxhoudinimcp.server import mcp, _get_bridge


@mcp.tool()
async def render_viewport(
    ctx: Context,
    output_path: str,
    resolution: list[int] | None = None,
    camera: str | None = None,
) -> dict:
    """Capture the current 3D viewport to an image file.

    Renders a single frame of the active viewport. Optionally set the camera
    and resolution before capture.

    Args:
        output_path: Destination image path (e.g. .png, .jpg, .exr).
        resolution: Optional [width, height] in pixels.
        camera: Optional camera node path to look through (e.g. '/obj/cam1').
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"output_path": output_path}
    if resolution is not None:
        params["resolution"] = resolution
    if camera is not None:
        params["camera"] = camera
    return await bridge.execute("rendering.render_viewport", params)


@mcp.tool()
async def render_quad_view(
    ctx: Context,
    output_path: str,
    resolution: list[int] | None = None,
) -> dict:
    """Capture all four viewport panes (top, front, right, perspective) to image files.

    Each viewport is saved as a separate file with the viewport name appended
    to the base filename.

    Args:
        output_path: Base destination image path. Viewport names will be appended.
        resolution: Optional [width, height] in pixels for each viewport.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"output_path": output_path}
    if resolution is not None:
        params["resolution"] = resolution
    return await bridge.execute("rendering.render_quad_view", params)


@mcp.tool()
async def list_render_nodes(ctx: Context) -> dict:
    """List all render (ROP/Driver) nodes in the Houdini scene.

    Searches /out and all embedded networks recursively for nodes of
    the Driver category. Returns node paths, types, cameras, and output paths.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("rendering.list_render_nodes", {})


@mcp.tool()
async def get_render_settings(ctx: Context, node_path: str) -> dict:
    """Get key render settings from a ROP node.

    Returns parameters such as resolution, camera, output path, frame range,
    and renderer type for the specified render node.

    Args:
        node_path: Path to the ROP/Driver node (e.g. '/out/karma1').
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("rendering.get_render_settings", {"node_path": node_path})


@mcp.tool()
async def set_render_settings(
    ctx: Context,
    node_path: str,
    settings: dict[str, Any] = {},
) -> dict:
    """Set render parameters on a ROP node.

    Applies the given parameter name-value pairs to the specified render node.

    Args:
        node_path: Path to the ROP/Driver node (e.g. '/out/karma1').
        settings: Dictionary of parameter_name -> value pairs to set.
            Example: {"camera": "/obj/cam1", "resx": 1920, "resy": 1080}
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

    Supports various renderers including Karma, OpenGL, Mantra, and more.

    Args:
        renderer: Renderer type. Values include 'karma', 'opengl', 'mantra'/'ifd',
            'rop_geometry', 'rop_alembic', 'usdrender', 'fetch', 'merge', etc.
        name: Optional node name. Auto-generated if not provided.
        camera: Optional camera path to assign (e.g. '/obj/cam1').
        output_path: Optional output image/file path.
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
    """Begin rendering a ROP node.

    Executes the render for the specified node. This is a blocking operation
    that returns when the render is complete.

    Args:
        node_path: Path to the ROP/Driver node to render (e.g. '/out/karma1').
        frame_range: Optional [start, end] or [start, end, increment] frame range.
            If not provided, uses the node's own frame range settings.
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
    """Take a screenshot of the network editor showing a specific node's network.

    Navigates the network editor to the node's parent network, selects the node,
    and captures the view.

    Args:
        node_path: Path to the node whose network to capture.
        output_path: Destination image path for the screenshot.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "rendering.render_node_network",
        {"node_path": node_path, "output_path": output_path},
    )


@mcp.tool()
async def get_render_progress(ctx: Context, node_path: str) -> dict:
    """Check the render status and progress of a ROP node.

    Returns whether the node is currently cooking, any errors or warnings,
    and whether the output file exists on disk.

    Args:
        node_path: Path to the ROP/Driver node (e.g. '/out/karma1').
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("rendering.get_render_progress", {"node_path": node_path})
