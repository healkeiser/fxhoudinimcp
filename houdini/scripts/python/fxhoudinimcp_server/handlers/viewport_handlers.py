"""Viewport and UI handlers for FXHoudini-MCP.

Provides tools for inspecting and controlling Houdini's viewport panes,
network editor navigation, display modes, camera assignment, and
screenshot capture of various pane types.
"""

from __future__ import annotations

# Built-in
import logging
import os

# Third-party
import hou

# Internal
from fxhoudinimcp_server.dispatcher import register_handler

logger = logging.getLogger(__name__)


###### viewport.list_panes

def list_panes() -> dict:
    """List all visible pane tabs, their types, and associated information."""
    pane_tabs = hou.ui.paneTabs()
    panes = []
    for pt in pane_tabs:
        info = {
            "name": pt.name(),
            "type": pt.type().name(),
            "is_current_tab": pt.isCurrentTab(),
        }
        # For scene viewers, add viewport info
        if pt.type() == hou.paneTabType.SceneViewer:
            try:
                cur_vp = pt.curViewport()
                info["current_viewport"] = cur_vp.name()
                info["viewport_count"] = len(pt.viewports())
            except (hou.OperationFailed, hou.ObjectWasDeleted, AttributeError) as e:
                logger.debug("Could not read viewport info for pane '%s': %s", pt.name(), e)
        # For network editors, add current path
        if pt.type() == hou.paneTabType.NetworkEditor:
            try:
                info["current_path"] = pt.pwd().path()
            except (hou.OperationFailed, hou.ObjectWasDeleted, AttributeError) as e:
                logger.debug("Could not read network editor path for pane '%s': %s", pt.name(), e)
        panes.append(info)

    return {
        "panes": panes,
        "count": len(panes),
    }


###### viewport.get_viewport_info

def get_viewport_info(pane_name: str = None) -> dict:
    """Get current viewport settings including camera, display mode, and view transform.

    Args:
        pane_name: Optional pane tab name. If None, uses the first Scene Viewer found.
    """
    scene_viewer = _find_scene_viewer(pane_name)
    viewport = scene_viewer.curViewport()

    info = {
        "pane_name": scene_viewer.name(),
        "viewport_name": viewport.name(),
    }

    # Camera
    try:
        cam = viewport.camera()
        info["camera"] = cam.path() if cam is not None else None
    except (hou.OperationFailed, hou.ObjectWasDeleted, AttributeError) as e:
        logger.debug("Could not read viewport camera: %s", e)
        info["camera"] = None

    # Display mode / shading
    try:
        settings = viewport.settings()
        display_set = settings.displaySet(hou.displaySetType.SceneObject)
        info["shading_mode"] = str(display_set.shadedMode())
    except (hou.OperationFailed, AttributeError) as e:
        logger.debug("Could not read shading mode: %s", e)
        info["shading_mode"] = None

    # View transform (model-view matrix)
    try:
        xform = viewport.viewTransform()
        info["view_transform"] = [list(row) for row in xform.asTupleOfTuples()]
    except (hou.OperationFailed, AttributeError) as e:
        logger.debug("Could not read view transform: %s", e)
        info["view_transform"] = None

    # Viewport type (perspective, top, front, right, UV, etc.)
    try:
        info["viewport_type"] = str(viewport.type())
    except (hou.OperationFailed, AttributeError) as e:
        logger.debug("Could not read viewport type: %s", e)
        info["viewport_type"] = None

    return info


###### viewport.set_viewport_camera

def set_viewport_camera(
    camera_path: str,
    pane_name: str = None,
) -> dict:
    """Set the viewport to look through a specific camera.

    Args:
        camera_path: Path to the camera node (e.g. '/obj/cam1').
        pane_name: Optional pane tab name.
    """
    cam_node = hou.node(camera_path)
    if cam_node is None:
        raise ValueError(f"Camera node not found: {camera_path}")

    scene_viewer = _find_scene_viewer(pane_name)
    viewport = scene_viewer.curViewport()
    viewport.setCamera(cam_node)

    return {
        "success": True,
        "camera_path": cam_node.path(),
        "pane_name": scene_viewer.name(),
        "viewport_name": viewport.name(),
    }


###### viewport.set_viewport_display

def set_viewport_display(
    display_mode: str,
    pane_name: str = None,
) -> dict:
    """Set the viewport display/shading mode.

    Args:
        display_mode: One of 'wireframe', 'shaded', 'smooth', 'smooth_wire',
            'hidden_line', 'flat', 'flat_wire', 'point'.
        pane_name: Optional pane tab name.
    """
    mode_map = {
        "wireframe": hou.glShadingType.Wire,
        "wire": hou.glShadingType.Wire,
        "shaded": hou.glShadingType.SmoothShaded,
        "smooth": hou.glShadingType.SmoothShaded,
        "smooth_wire": hou.glShadingType.SmoothWire,
        "hidden_line": hou.glShadingType.HiddenLineGhost,
        "flat": hou.glShadingType.FlatShaded,
        "flat_wire": hou.glShadingType.FlatWire,
    }

    gl_mode = mode_map.get(display_mode.lower())
    if gl_mode is None:
        raise ValueError(
            f"Unknown display mode: '{display_mode}'. "
            f"Supported modes: {list(mode_map.keys())}"
        )

    scene_viewer = _find_scene_viewer(pane_name)
    viewport = scene_viewer.curViewport()

    settings = viewport.settings()
    display_set = settings.displaySet(hou.displaySetType.SceneObject)
    display_set.setShadedMode(gl_mode)

    return {
        "success": True,
        "display_mode": display_mode,
        "pane_name": scene_viewer.name(),
    }


###### viewport.frame_selection

def frame_selection(pane_name: str = None) -> dict:
    """Frame the current selection in the viewport.

    Args:
        pane_name: Optional pane tab name.
    """
    scene_viewer = _find_scene_viewer(pane_name)
    viewport = scene_viewer.curViewport()

    viewport.frameSelected()

    return {
        "success": True,
        "pane_name": scene_viewer.name(),
        "viewport_name": viewport.name(),
    }


###### viewport.frame_all

def frame_all(pane_name: str = None) -> dict:
    """Frame all geometry in the viewport (home all).

    Args:
        pane_name: Optional pane tab name.
    """
    scene_viewer = _find_scene_viewer(pane_name)
    viewport = scene_viewer.curViewport()

    viewport.homeAll()

    return {
        "success": True,
        "pane_name": scene_viewer.name(),
        "viewport_name": viewport.name(),
    }


###### viewport.capture_screenshot

def capture_screenshot(
    pane_name: str,
    output_path: str,
) -> dict:
    """Capture a screenshot of a specific pane tab.

    Args:
        pane_name: Name of the pane tab to capture.
        output_path: Destination image path.
    """
    out_dir = os.path.dirname(output_path)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    pane_tab = _find_pane_by_name(pane_name)

    # For scene viewers, use flipbook for capture
    if pane_tab.type() == hou.paneTabType.SceneViewer:
        viewport = pane_tab.curViewport()
        settings = pane_tab.flipbookSettings().stash()
        settings.frameRange((hou.frame(), hou.frame()))
        settings.output(output_path)
        pane_tab.flipbook(viewport, settings)
    else:
        # For other pane types, try the saveAsImage approach
        try:
            pane_tab.saveAsImage(output_path)
        except AttributeError:
            raise RuntimeError(
                f"Pane type '{pane_tab.type().name()}' does not support "
                f"direct image capture. Use viewport.capture_network_editor "
                f"for network editors."
            )

    return {
        "success": True,
        "pane_name": pane_name,
        "output_path": output_path,
    }


###### viewport.capture_network_editor

def capture_network_editor(
    output_path: str,
    node_path: str = None,
) -> dict:
    """Capture a screenshot of the network editor.

    Args:
        output_path: Destination image path.
        node_path: Optional node path to navigate to before capture.
    """
    out_dir = os.path.dirname(output_path)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    network_editor = None
    for pane_tab in hou.ui.paneTabs():
        if pane_tab.type() == hou.paneTabType.NetworkEditor:
            network_editor = pane_tab
            break

    if network_editor is None:
        raise RuntimeError("No Network Editor pane found.")

    # Navigate to the specified node if provided
    if node_path is not None:
        node = hou.node(node_path)
        if node is None:
            raise ValueError(f"Node not found: {node_path}")
        parent = node.parent()
        if parent is not None:
            network_editor.cd(parent.path())
        network_editor.setCurrentNode(node)
        network_editor.homeToSelection()

    # Capture the network editor
    try:
        network_editor.saveAsImage(output_path)
    except AttributeError:
        try:
            desktop = hou.ui.curDesktop()
            desktop.saveAsImage(output_path)
        except Exception as e:
            raise RuntimeError(
                f"Failed to capture network editor screenshot: {e}"
            )

    return {
        "success": True,
        "output_path": output_path,
        "node_path": node_path,
    }


###### viewport.set_current_network

def set_current_network(network_path: str) -> dict:
    """Navigate the network editor to a specific network path.

    Args:
        network_path: Path to the network to navigate to (e.g. '/obj/geo1').
    """
    node = hou.node(network_path)
    if node is None:
        raise ValueError(f"Network path not found: {network_path}")

    network_editor = None
    for pane_tab in hou.ui.paneTabs():
        if pane_tab.type() == hou.paneTabType.NetworkEditor:
            network_editor = pane_tab
            break

    if network_editor is None:
        raise RuntimeError("No Network Editor pane found.")

    network_editor.cd(network_path)

    return {
        "success": True,
        "network_path": network_path,
        "pane_name": network_editor.name(),
    }


###### viewport.find_error_nodes

def find_error_nodes(root_path: str = "/") -> dict:
    """Find all nodes with errors or warnings, recursively from a root path.

    Args:
        root_path: Root node path to start searching from. Defaults to '/'.
    """
    root = hou.node(root_path)
    if root is None:
        raise ValueError(f"Root path not found: {root_path}")

    error_nodes = []
    warning_nodes = []

    def _check_node(node):
        """Recursively check nodes for errors and warnings."""
        try:
            errors = node.errors()
            if errors:
                error_nodes.append({
                    "path": node.path(),
                    "name": node.name(),
                    "type": node.type().name(),
                    "errors": list(errors),
                })
        except (hou.OperationFailed, hou.ObjectWasDeleted, AttributeError) as e:
            logger.debug("Could not read errors for node '%s': %s", node.path(), e)

        try:
            warnings = node.warnings()
            if warnings:
                warning_nodes.append({
                    "path": node.path(),
                    "name": node.name(),
                    "type": node.type().name(),
                    "warnings": list(warnings),
                })
        except (hou.OperationFailed, hou.ObjectWasDeleted, AttributeError) as e:
            logger.debug("Could not read warnings for node '%s': %s", node.path(), e)

        # Recurse into children
        try:
            for child in node.children():
                _check_node(child)
        except (hou.OperationFailed, hou.ObjectWasDeleted) as e:
            logger.debug("Could not iterate children of node '%s': %s", node.path(), e)

    _check_node(root)

    return {
        "error_nodes": error_nodes,
        "warning_nodes": warning_nodes,
        "error_count": len(error_nodes),
        "warning_count": len(warning_nodes),
        "root_path": root_path,
    }


###### Helpers

def _find_scene_viewer(pane_name: str = None):
    """Find a Scene Viewer pane tab by name, or the first one available.

    Args:
        pane_name: Optional specific pane tab name.

    Returns:
        A hou.SceneViewer pane tab.

    Raises:
        RuntimeError: If no Scene Viewer is found.
        ValueError: If the named pane is not a Scene Viewer.
    """
    if pane_name is not None:
        pane_tab = _find_pane_by_name(pane_name)
        if pane_tab.type() != hou.paneTabType.SceneViewer:
            raise ValueError(
                f"Pane '{pane_name}' is a {pane_tab.type().name()}, "
                f"not a Scene Viewer."
            )
        return pane_tab

    for pane_tab in hou.ui.paneTabs():
        if pane_tab.type() == hou.paneTabType.SceneViewer:
            return pane_tab

    raise RuntimeError("No Scene Viewer pane found.")


def _find_pane_by_name(pane_name: str):
    """Find a pane tab by its name.

    Args:
        pane_name: The pane tab name.

    Returns:
        The matching hou.PaneTab.

    Raises:
        ValueError: If no pane with the given name exists.
    """
    for pane_tab in hou.ui.paneTabs():
        if pane_tab.name() == pane_name:
            return pane_tab

    available = [pt.name() for pt in hou.ui.paneTabs()]
    raise ValueError(
        f"Pane tab not found: '{pane_name}'. "
        f"Available panes: {available}"
    )


###### Registration

register_handler("viewport.list_panes", list_panes)
register_handler("viewport.get_viewport_info", get_viewport_info)
register_handler("viewport.set_viewport_camera", set_viewport_camera)
register_handler("viewport.set_viewport_display", set_viewport_display)
register_handler("viewport.frame_selection", frame_selection)
register_handler("viewport.frame_all", frame_all)
register_handler("viewport.capture_screenshot", capture_screenshot)
register_handler("viewport.capture_network_editor", capture_network_editor)
register_handler("viewport.set_current_network", set_current_network)
register_handler("viewport.find_error_nodes", find_error_nodes)
