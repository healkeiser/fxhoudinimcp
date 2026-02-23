"""MCP tool definitions for Houdini viewport and UI operations.

Provides tools for inspecting and controlling Houdini's viewport panes,
display modes, camera assignment, screenshot capture, network editor
navigation, and error node discovery.
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
async def list_panes(ctx: Context) -> dict:
    """List all visible pane tabs in the Houdini UI."""
    bridge = _get_bridge(ctx)
    return await bridge.execute("viewport.list_panes", {})


@mcp.tool()
async def get_viewport_info(
    ctx: Context,
    pane_name: str | None = None,
) -> dict:
    """Get viewport settings for a pane tab.

    Args:
        pane_name: Pane tab name.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {}
    if pane_name is not None:
        params["pane_name"] = pane_name
    return await bridge.execute("viewport.get_viewport_info", params)


@mcp.tool()
async def set_viewport_camera(
    ctx: Context,
    camera_path: str,
    pane_name: str | None = None,
) -> dict:
    """Set the viewport to look through a specific camera.

    Args:
        camera_path: Camera node path.
        pane_name: Pane tab name.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"camera_path": camera_path}
    if pane_name is not None:
        params["pane_name"] = pane_name
    return await bridge.execute("viewport.set_viewport_camera", params)


@mcp.tool()
async def set_viewport_display(
    ctx: Context,
    display_mode: str,
    pane_name: str | None = None,
) -> dict:
    """Set the viewport shading mode.

    Args:
        display_mode: One of 'wireframe', 'shaded', 'smooth', 'smooth_wire',
            'hidden_line', 'flat', 'flat_wire', 'matcap', 'matcap_wire'.
        pane_name: Pane tab name.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"display_mode": display_mode}
    if pane_name is not None:
        params["pane_name"] = pane_name
    return await bridge.execute("viewport.set_viewport_display", params)


@mcp.tool()
async def set_viewport_renderer(
    ctx: Context,
    renderer: str,
    pane_name: str | None = None,
) -> dict:
    """Set the viewport's Hydra rendering delegate for live preview.

    Use this during lookdev to preview materials and lighting directly in the
    viewport instead of writing full renders to disk.

    Args:
        renderer: Renderer name — "GL", "Storm", "Karma CPU", "Karma XPU", etc. Case-insensitive partial match.
        pane_name: Pane tab name.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"renderer": renderer}
    if pane_name is not None:
        params["pane_name"] = pane_name
    return await bridge.execute("viewport.set_viewport_renderer", params)


@mcp.tool()
async def frame_selection(
    ctx: Context,
    pane_name: str | None = None,
) -> dict:
    """Frame the current selection in the viewport.

    Args:
        pane_name: Pane tab name.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {}
    if pane_name is not None:
        params["pane_name"] = pane_name
    return await bridge.execute("viewport.frame_selection", params)


@mcp.tool()
async def frame_all(
    ctx: Context,
    pane_name: str | None = None,
) -> dict:
    """Frame all geometry in the viewport.

    Args:
        pane_name: Pane tab name.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {}
    if pane_name is not None:
        params["pane_name"] = pane_name
    return await bridge.execute("viewport.frame_all", params)


@mcp.tool()
async def set_viewport_direction(
    ctx: Context,
    direction: str,
    pane_name: str | None = None,
) -> dict:
    """Set the viewport to a standard viewing direction.

    Args:
        direction: "front", "back", "top", "bottom", "left", "right", or "perspective".
        pane_name: Pane tab name.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"direction": direction}
    if pane_name is not None:
        params["pane_name"] = pane_name
    return await bridge.execute("viewport.set_viewport_direction", params)


@mcp.tool()
async def capture_screenshot(
    ctx: Context,
    output_path: str,
    pane_name: str | None = None,
) -> list[TextContent | ImageContent]:
    """Capture a screenshot of the viewport or a specific pane tab.

    Args:
        output_path: Image file path.
        pane_name: Pane tab name.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"output_path": output_path}
    if pane_name is not None:
        params["pane_name"] = pane_name
    result = await bridge.execute("viewport.capture_screenshot", params)
    return result_with_image(result)


@mcp.tool()
async def capture_network_editor(
    ctx: Context,
    output_path: str,
    node_path: str | None = None,
) -> list[TextContent | ImageContent]:
    """Capture a screenshot of the network editor.

    Args:
        output_path: Image file path.
        node_path: Node path to navigate to before capture.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"output_path": output_path}
    if node_path is not None:
        params["node_path"] = node_path
    result = await bridge.execute("viewport.capture_network_editor", params)
    return result_with_image(result)


@mcp.tool()
async def set_current_network(
    ctx: Context,
    network_path: str,
) -> dict:
    """Navigate the network editor to a specific network path.

    Args:
        network_path: Network path to navigate to.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "viewport.set_current_network",
        {"network_path": network_path},
    )


@mcp.tool()
async def find_error_nodes(
    ctx: Context,
    root_path: str = "/",
) -> dict:
    """Find all nodes with errors or warnings in the scene.

    Args:
        root_path: Root node path to search from.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "viewport.find_error_nodes",
        {"root_path": root_path},
    )
