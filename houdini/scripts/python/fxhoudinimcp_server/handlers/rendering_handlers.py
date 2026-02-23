"""Rendering handlers for FXHoudini-MCP.

Provides tools for viewport capture, render node management, and rendering
operations including Karma, OpenGL, and other Houdini renderers.
"""

from __future__ import annotations

# Built-in
import base64
import logging
import os

# Third-party
import hou

# Internal
from fxhoudinimcp_server.dispatcher import register_handler

logger = logging.getLogger(__name__)


###### rendering.render_viewport

def _find_flipbook_output(output_path: str, frame: float) -> str:
    """Find the actual output file after flipbook, handling frame number insertion.

    Houdini's flipbook may insert a frame number into the filename
    (e.g. "output.0001.png" instead of "output.png") even for single-frame
    captures. This helper locates the actual file and optionally renames it.
    """
    if os.path.isfile(output_path):
        return output_path

    # Try common frame-number patterns
    base, ext = os.path.splitext(output_path)
    frame_int = int(frame)
    candidates = [
        f"{base}.{frame_int:04d}{ext}",
        f"{base}.{frame_int:03d}{ext}",
        f"{base}.{frame_int}{ext}",
        f"{base}_{frame_int:04d}{ext}",
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            # Rename to the originally requested path
            try:
                os.rename(candidate, output_path)
                return output_path
            except OSError:
                return candidate

    return output_path


def render_viewport(
    output_path: str,
    resolution: list = None,
    camera: str = None,
) -> dict:
    """Capture the current viewport to an image file.

    Args:
        output_path: Destination image path (e.g. .png, .jpg, .exr).
        resolution: Optional [width, height] override.
        camera: Optional camera node path to look through before capture.
    """
    # Ensure the output directory exists
    out_dir = os.path.dirname(output_path)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    # Get the current scene viewer
    scene_viewer = None
    for pane_tab in hou.ui.paneTabs():
        if pane_tab.type() == hou.paneTabType.SceneViewer:
            scene_viewer = pane_tab
            break

    if scene_viewer is None:
        raise RuntimeError(
            "No Scene Viewer pane found. A viewport must be open to capture."
        )

    viewport = scene_viewer.curViewport()

    # Optionally set the camera
    if camera is not None:
        cam_node = hou.node(camera)
        if cam_node is None:
            raise ValueError(f"Camera node not found: {camera}")
        viewport.setCamera(cam_node)

    cur_frame = hou.frame()

    # Build the flipbook settings for image capture
    settings = scene_viewer.flipbookSettings().stash()
    settings.frameRange((cur_frame, cur_frame))
    settings.output(output_path)

    if resolution is not None:
        if len(resolution) != 2:
            raise ValueError("resolution must be a list of [width, height]")
        settings.useResolution(True)
        settings.resolution(tuple(resolution))

    # Use the flipbook approach for a single-frame capture
    scene_viewer.flipbook(viewport, settings)

    # Handle frame number that flipbook may insert into the filename
    actual_path = _find_flipbook_output(output_path, cur_frame)

    # Downscale + JPEG-compress before base64 to avoid token bloat.
    image_base64 = None
    mime_type = "image/jpeg"
    if os.path.isfile(actual_path):
        from fxhoudinimcp_server.handlers.viewport_handlers import _downscale_and_encode
        image_base64, mime_type = _downscale_and_encode(actual_path)

    return {
        "success": True,
        "output_path": actual_path,
        "file_exists": os.path.isfile(actual_path),
        "resolution": resolution,
        "camera": camera,
        "frame": cur_frame,
        "image_base64": image_base64,
        "mime_type": mime_type,
    }


###### rendering.render_quad_view

def render_quad_view(
    output_path: str,
    resolution: list = None,
) -> dict:
    """Capture all four viewport panes (quad view) to an image file.

    Args:
        output_path: Destination image path.
        resolution: Optional [width, height] override.
    """
    out_dir = os.path.dirname(output_path)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    scene_viewer = None
    for pane_tab in hou.ui.paneTabs():
        if pane_tab.type() == hou.paneTabType.SceneViewer:
            scene_viewer = pane_tab
            break

    if scene_viewer is None:
        raise RuntimeError("No Scene Viewer pane found.")

    viewports = scene_viewer.viewports()
    if not viewports:
        raise RuntimeError("No viewports available in the Scene Viewer.")

    saved_files = []
    base, ext = os.path.splitext(output_path)

    for vp in viewports:
        vp_name = vp.name()
        vp_output = f"{base}_{vp_name}{ext}"

        settings = scene_viewer.flipbookSettings().stash()
        settings.frameRange((hou.frame(), hou.frame()))
        settings.output(vp_output)

        if resolution is not None:
            if len(resolution) != 2:
                raise ValueError("resolution must be a list of [width, height]")
            settings.resolution(tuple(resolution))

        scene_viewer.flipbook(vp, settings)
        saved_files.append({"viewport": vp_name, "output_path": vp_output})

    return {
        "success": True,
        "viewports": saved_files,
        "frame": hou.frame(),
    }


###### rendering.list_render_nodes

def list_render_nodes() -> dict:
    """List all ROP (render) nodes in /out and embedded in other networks.

    Searches for all nodes whose type category is 'Driver'.
    """
    render_nodes = []

    def _collect_rops(parent):
        """Recursively collect all Driver-category nodes."""
        for child in parent.children():
            try:
                cat = child.type().category().name()
            except (hou.ObjectWasDeleted, AttributeError) as e:
                logger.debug("Could not read category for node: %s", e)
                continue
            if cat == "Driver":
                info = {
                    "name": child.name(),
                    "path": child.path(),
                    "type": child.type().name(),
                    "description": child.type().description(),
                }
                # Safely retrieve common render parameters
                try:
                    cam_parm = child.parm("camera")
                    info["camera"] = cam_parm.eval() if cam_parm else None
                except (hou.OperationFailed, AttributeError) as e:
                    logger.debug("Could not read camera parm for '%s': %s", child.path(), e)
                    info["camera"] = None
                try:
                    out_parm = (
                        child.parm("vm_picture")
                        or child.parm("copoutput")
                        or child.parm("sopoutput")
                        or child.parm("picture")
                    )
                    info["output"] = out_parm.eval() if out_parm else None
                except (hou.OperationFailed, AttributeError) as e:
                    logger.debug("Could not read output parm for '%s': %s", child.path(), e)
                    info["output"] = None
                render_nodes.append(info)
            # Recurse into children regardless of category
            try:
                if child.children():
                    _collect_rops(child)
            except (hou.OperationFailed, hou.ObjectWasDeleted) as e:
                logger.debug("Could not recurse into children of '%s': %s", child.path(), e)

    _collect_rops(hou.node("/"))

    return {
        "render_nodes": render_nodes,
        "count": len(render_nodes),
    }


###### rendering.get_render_settings

def get_render_settings(node_path: str) -> dict:
    """Get key render settings from a ROP node.

    Args:
        node_path: Path to the ROP/Driver node.
    """
    node = hou.node(node_path)
    if node is None:
        raise ValueError(f"Node not found: {node_path}")

    if node.type().category().name() != "Driver":
        raise ValueError(
            f"Node {node_path} is not a ROP/Driver node "
            f"(category: {node.type().category().name()})."
        )

    settings = {
        "node_path": node.path(),
        "node_type": node.type().name(),
        "description": node.type().description(),
    }

    # Common render parameters to extract
    parm_names = [
        "camera", "vm_picture", "picture", "copoutput", "sopoutput",
        "res_overridex", "res_overridey", "resx", "resy",
        "resoverride", "res",
        "f1", "f2", "f3",  # frame range start, end, increment
        "trange",  # time range mode
        "override_camerares",
        "renderer",
        "vm_renderengine",
    ]

    for parm_name in parm_names:
        try:
            parm = node.parm(parm_name)
            if parm is not None:
                val = parm.eval()
                # Convert hou types to plain Python
                if hasattr(val, "path"):
                    val = val.path()
                settings[parm_name] = val
        except (hou.OperationFailed, AttributeError) as e:
            logger.debug("Could not read render parm '%s': %s", parm_name, e)

    # Check for parm tuples (e.g. resolution)
    for tuple_name in ["res", "t"]:
        try:
            pt = node.parmTuple(tuple_name)
            if pt is not None:
                settings[tuple_name] = [p.eval() for p in pt]
        except (hou.OperationFailed, AttributeError) as e:
            logger.debug("Could not read render parm tuple '%s': %s", tuple_name, e)

    return settings


###### rendering.set_render_settings

def set_render_settings(node_path: str, settings: dict) -> dict:
    """Set render parameters on a ROP node.

    Args:
        node_path: Path to the ROP/Driver node.
        settings: Dict of parameter_name -> value pairs to set.
    """
    node = hou.node(node_path)
    if node is None:
        raise ValueError(f"Node not found: {node_path}")

    if node.type().category().name() != "Driver":
        raise ValueError(
            f"Node {node_path} is not a ROP/Driver node "
            f"(category: {node.type().category().name()})."
        )

    applied = {}
    errors = {}

    for parm_name, value in settings.items():
        try:
            parm = node.parm(parm_name)
            if parm is None:
                # Try as a parm tuple
                pt = node.parmTuple(parm_name)
                if pt is not None:
                    pt.set(value)
                    applied[parm_name] = value
                else:
                    errors[parm_name] = f"Parameter not found: {parm_name}"
            else:
                parm.set(value)
                applied[parm_name] = value
        except Exception as e:
            errors[parm_name] = str(e)

    return {
        "success": len(errors) == 0,
        "node_path": node.path(),
        "applied": applied,
        "errors": errors if errors else None,
    }


###### rendering.create_render_node

def create_render_node(
    renderer: str,
    name: str = None,
    camera: str = None,
    output_path: str = None,
) -> dict:
    """Create a new render (ROP) node in /out.

    Args:
        renderer: Renderer type. Supported values include:
            'karma' (USD Karma), 'opengl' (OpenGL), 'ifd' (Mantra),
            'rop_geometry' (Geometry ROP), 'fetch', 'merge', etc.
        name: Optional node name. Auto-generated if not provided.
        camera: Optional camera path to assign.
        output_path: Optional output image/file path.
    """
    out_context = hou.node("/out")
    if out_context is None:
        raise RuntimeError("/out context not found.")

    # Map friendly renderer names to actual node types
    renderer_map = {
        "karma": "karma",
        "opengl": "opengl",
        "mantra": "ifd",
        "ifd": "ifd",
        "geometry": "rop_geometry",
        "rop_geometry": "rop_geometry",
        "alembic": "rop_alembic",
        "rop_alembic": "rop_alembic",
        "fetch": "fetch",
        "merge": "merge",
        "usdrender": "usdrender",
        "usd_rop": "usd_rop",
        "filmboxfbx": "filmboxfbx",
        "comp": "comp",
        "wedge": "wedge",
        "baketexture": "baketexture",
    }

    node_type = renderer_map.get(renderer.lower(), renderer)

    try:
        node = out_context.createNode(node_type, name)
    except hou.OperationFailed as e:
        raise ValueError(
            f"Failed to create render node of type '{node_type}': {e}"
        )

    # Set camera if provided
    if camera is not None:
        cam_parm = node.parm("camera")
        if cam_parm is not None:
            cam_parm.set(camera)

    # Set output path if provided
    if output_path is not None:
        # Try common output parameter names
        for parm_name in ("vm_picture", "picture", "copoutput", "sopoutput"):
            parm = node.parm(parm_name)
            if parm is not None:
                parm.set(output_path)
                break

    node.moveToGoodPosition()

    return {
        "success": True,
        "node_path": node.path(),
        "node_type": node.type().name(),
        "renderer": renderer,
    }


###### rendering.start_render

def start_render(
    node_path: str,
    frame_range: list = None,
) -> dict:
    """Begin rendering a ROP node.

    Args:
        node_path: Path to the ROP/Driver node.
        frame_range: Optional [start, end] frame range. If not provided,
            renders with the node's own frame range settings.
    """
    node = hou.node(node_path)
    if node is None:
        raise ValueError(f"Node not found: {node_path}")

    if node.type().category().name() != "Driver":
        raise ValueError(
            f"Node {node_path} is not a ROP/Driver node "
            f"(category: {node.type().category().name()})."
        )

    try:
        if frame_range is not None:
            if len(frame_range) < 2:
                raise ValueError("frame_range must have at least [start, end].")
            start = float(frame_range[0])
            end = float(frame_range[1])
            inc = float(frame_range[2]) if len(frame_range) > 2 else 1.0
            node.render(
                frame_range=(start, end),
                frame_increment=inc,
                output_progress=True,
            )
        else:
            node.render(output_progress=True)
    except hou.OperationFailed as e:
        return {
            "success": False,
            "node_path": node_path,
            "error": str(e),
        }

    return {
        "success": True,
        "node_path": node_path,
        "frame_range": frame_range,
        "message": "Render completed.",
    }


###### rendering.render_node_network

def render_node_network(
    node_path: str,
    output_path: str,
) -> dict:
    """Take a screenshot of the network editor showing a specific node's network.

    Args:
        node_path: Path to the node whose network to capture.
        output_path: Destination image path.
    """
    node = hou.node(node_path)
    if node is None:
        raise ValueError(f"Node not found: {node_path}")

    out_dir = os.path.dirname(output_path)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    # Find a network editor pane tab
    network_editor = None
    for pane_tab in hou.ui.paneTabs():
        if pane_tab.type() == hou.paneTabType.NetworkEditor:
            network_editor = pane_tab
            break

    if network_editor is None:
        raise RuntimeError("No Network Editor pane found.")

    # Navigate to the node's parent network so the node is visible
    parent = node.parent()
    if parent is not None:
        network_editor.cd(parent.path())

    # Frame the node in the editor
    network_editor.setCurrentNode(node)
    network_editor.homeToSelection()

    # Capture the network editor as an image via Qt widget grab
    from fxhoudinimcp_server.handlers.viewport_handlers import (
        _capture_pane_tab_qt, _downscale_and_encode,
    )
    _capture_pane_tab_qt(network_editor, output_path)

    image_base64 = None
    mime_type = "image/jpeg"
    if os.path.isfile(output_path):
        image_base64, mime_type = _downscale_and_encode(output_path)

    return {
        "success": True,
        "node_path": node_path,
        "output_path": output_path,
        "image_base64": image_base64,
        "mime_type": mime_type,
    }


###### rendering.get_render_progress

def get_render_progress(node_path: str) -> dict:
    """Check the render status / progress of a ROP node.

    Args:
        node_path: Path to the ROP/Driver node.
    """
    node = hou.node(node_path)
    if node is None:
        raise ValueError(f"Node not found: {node_path}")

    if node.type().category().name() != "Driver":
        raise ValueError(
            f"Node {node_path} is not a ROP/Driver node "
            f"(category: {node.type().category().name()})."
        )

    is_cooking = node.isCooking() if hasattr(node, "isCooking") else False

    # Check cook count as a proxy for activity
    try:
        cook_count = node.cookCount()
    except (hou.OperationFailed, AttributeError) as e:
        logger.debug("Could not read cook count for '%s': %s", node_path, e)
        cook_count = None

    # Check for errors and warnings
    try:
        errors = list(node.errors()) if node.errors() else []
    except (hou.OperationFailed, AttributeError) as e:
        logger.debug("Could not read errors for '%s': %s", node_path, e)
        errors = []

    try:
        warnings = list(node.warnings()) if node.warnings() else []
    except (hou.OperationFailed, AttributeError) as e:
        logger.debug("Could not read warnings for '%s': %s", node_path, e)
        warnings = []

    # Retrieve the output file to check if it exists on disk
    output_file = None
    for parm_name in ("vm_picture", "picture", "copoutput", "sopoutput"):
        try:
            parm = node.parm(parm_name)
            if parm is not None:
                output_file = parm.eval()
                break
        except (hou.OperationFailed, AttributeError) as e:
            logger.debug("Could not read output parm '%s': %s", parm_name, e)

    output_exists = False
    if output_file:
        try:
            output_exists = os.path.isfile(output_file)
        except OSError as e:
            logger.debug("Could not check output file existence: %s", e)

    return {
        "node_path": node.path(),
        "is_cooking": is_cooking,
        "cook_count": cook_count,
        "errors": errors,
        "warnings": warnings,
        "output_file": output_file,
        "output_exists": output_exists,
    }


###### Registration

register_handler("rendering.render_viewport", render_viewport)
register_handler("rendering.render_quad_view", render_quad_view)
register_handler("rendering.list_render_nodes", list_render_nodes)
register_handler("rendering.get_render_settings", get_render_settings)
register_handler("rendering.set_render_settings", set_render_settings)
register_handler("rendering.create_render_node", create_render_node)
register_handler("rendering.start_render", start_render)
register_handler("rendering.render_node_network", render_node_network)
register_handler("rendering.get_render_progress", get_render_progress)
