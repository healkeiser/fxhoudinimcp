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

# Internal
from fxhoudinimcp.server import mcp, _get_bridge


@mcp.tool()
async def list_panes(ctx: Context) -> dict:
    """List all visible pane tabs in the Houdini UI.

    Returns each pane's name, type, and whether it is the current tab.
    Scene Viewers include viewport info; Network Editors include current path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("viewport.list_panes", {})


@mcp.tool()
async def get_viewport_info(
    ctx: Context,
    pane_name: str | None = None,
) -> dict:
    """Get current viewport settings including camera, display mode, and view transform.

    Args:
        pane_name: Optional pane tab name. If not provided, uses the first
            Scene Viewer found.
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
        camera_path: Path to the camera node (e.g. '/obj/cam1').
        pane_name: Optional pane tab name. If not provided, uses the first
            Scene Viewer found.
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
    """Set the viewport display/shading mode.

    Args:
        display_mode: One of 'wireframe', 'shaded', 'smooth', 'smooth_wire',
            'hidden_line', 'flat', 'flat_wire'.
        pane_name: Optional pane tab name. If not provided, uses the first
            Scene Viewer found.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"display_mode": display_mode}
    if pane_name is not None:
        params["pane_name"] = pane_name
    return await bridge.execute("viewport.set_viewport_display", params)


@mcp.tool()
async def frame_selection(
    ctx: Context,
    pane_name: str | None = None,
) -> dict:
    """Frame the current selection in the viewport.

    Adjusts the viewport camera to center on and fit the currently
    selected geometry or nodes.

    Args:
        pane_name: Optional pane tab name. If not provided, uses the first
            Scene Viewer found.
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
    """Frame all geometry in the viewport (home all).

    Adjusts the viewport camera to fit all visible geometry in the scene.

    Args:
        pane_name: Optional pane tab name. If not provided, uses the first
            Scene Viewer found.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {}
    if pane_name is not None:
        params["pane_name"] = pane_name
    return await bridge.execute("viewport.frame_all", params)


@mcp.tool()
async def capture_screenshot(
    ctx: Context,
    pane_name: str,
    output_path: str,
) -> dict:
    """Capture a screenshot of a specific pane tab.

    For Scene Viewers, uses the flipbook mechanism for high-quality capture.
    For other pane types, uses the saveAsImage approach.

    Args:
        pane_name: Name of the pane tab to capture.
        output_path: Destination image file path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "viewport.capture_screenshot",
        {"pane_name": pane_name, "output_path": output_path},
    )


@mcp.tool()
async def capture_network_editor(
    ctx: Context,
    output_path: str,
    node_path: str | None = None,
) -> dict:
    """Capture a screenshot of the network editor.

    Optionally navigates to a specific node before capturing.

    Args:
        output_path: Destination image file path.
        node_path: Optional node path to navigate to and frame before capture.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"output_path": output_path}
    if node_path is not None:
        params["node_path"] = node_path
    return await bridge.execute("viewport.capture_network_editor", params)


@mcp.tool()
async def set_current_network(
    ctx: Context,
    network_path: str,
) -> dict:
    """Navigate the network editor to a specific network path.

    Changes the network editor's current directory to the specified path,
    allowing you to browse a different part of the node graph.

    Args:
        network_path: Path to the network to navigate to (e.g. '/obj/geo1').
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

    Recursively searches from the root path for any nodes that have
    cook errors or warnings, returning their paths, types, and messages.

    Args:
        root_path: Root node path to start searching from. Defaults to '/'.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "viewport.find_error_nodes",
        {"root_path": root_path},
    )
