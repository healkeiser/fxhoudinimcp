"""Rendering handlers for FXHoudini-MCP.

Provides tools for viewport capture, render node management, and rendering
operations including Karma, OpenGL, and other Houdini renderers.
"""

from __future__ import annotations

import contextlib

# Built-in
import logging
import os
import subprocess
import tempfile
import time
from typing import Any

# Third-party
import hou

# Internal
from fxhoudinimcp_server.callbacks import CallbackError, press
from fxhoudinimcp_server.config import place_new_node
from fxhoudinimcp_server.dispatcher import register_handler
from fxhoudinimcp_server.errors import readable_message
from fxhoudinimcp_server.handlers.viewport_handlers import _no_mplay
from fxhoudinimcp_server.outputs import (
    at_frame,
    failure_verdict,
    license_error,
    reported_outputs,
    write_verdict,
)
from fxhoudinimcp_server.ui import require_ui

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
    require_ui(
        "capture a viewport screenshot",
        alternative="For a rendered image without a UI, build a ROP and use start_render.",
    )
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
        raise RuntimeError("No Scene Viewer pane found. A viewport must be open to capture.")

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
    _no_mplay(settings)
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

    return {
        "success": True,
        "output_path": actual_path,
        "file_exists": os.path.isfile(actual_path),
        "resolution": resolution,
        "camera": camera,
        "frame": cur_frame,
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
    require_ui(
        "capture a quad view",
        alternative="For a rendered image without a UI, build a ROP and use start_render.",
    )
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

        _no_mplay(settings)
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
    node, _, _ = _renderable(node_path)

    settings = {
        "node_path": node.path(),
        "node_type": node.type().name(),
        "description": node.type().description(),
    }

    # Common render parameters to extract
    parm_names = [
        "camera",
        "vm_picture",
        "picture",
        "copoutput",
        "sopoutput",
        "res_overridex",
        "res_overridey",
        "resx",
        "resy",
        "resoverride",
        "res",
        "res_mode",
        "resolutionx",
        "resolutiony",
        "f1",
        "f2",
        "f3",  # frame range start, end, increment
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
    node, _, _ = _renderable(node_path)

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
            f"Failed to create render node of type '{node_type}': {readable_message(e)}"
        ) from e

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

    place_new_node(node)

    return {
        "success": True,
        "node_path": node.path(),
        "node_type": node.type().name(),
        "renderer": renderer,
    }


###### rendering.start_render

# Where ROP-style nodes keep their frame range.
_RANGE_PARMS = ("f1", "f2", "f3")


def _apply_frame_range_parms(node: hou.Node, frame_range: list) -> None:
    """Set trange/f1..f3 on a node whose execution is a button press."""
    trange = node.parm("trange")
    if trange is not None:
        # 1 is "Render Frame Range" on every stock ROP-style node.
        trange.set(1)
    values = [float(frame_range[0]), float(frame_range[1])]
    values.append(float(frame_range[2]) if len(frame_range) > 2 else 1.0)
    for name, value in zip(_RANGE_PARMS, values, strict=False):
        parm = node.parm(name)
        if parm is not None:
            parm.set(value)


def _renderable(node_path: str) -> tuple[hou.Node, str, bool]:
    """The node, its category, and whether it has render() (else an execute button).

    Category is the wrong test. It rejected the LOP usdrender_rop, which is how
    Solaris renders, along with SOP ROPs and a File Cache's Save to Disk -- so a
    recorded session pressed all of those by hand through execute_python ten
    times. What matters is whether the node can be executed at all. Used by
    start_render and get_render_progress alike, so the two agree: a session
    started a Karma LOP with one and was refused progress on it by the other.
    """
    node = hou.node(node_path)
    if node is None:
        raise ValueError(f"Node not found: {node_path}")
    category = node.type().category().name()
    can_render = hasattr(node, "render")
    if not can_render and node.parm("execute") is None:
        buttons = [
            p.name() for p in node.parms() if p.parmTemplate().type() == hou.parmTemplateType.Button
        ]
        raise ValueError(
            f"{node_path} ({category}) has neither render() nor an 'execute' "
            f"button, so there is nothing to trigger."
            + (f" Buttons it does have: {buttons[:6]}" if buttons else "")
        )
    return node, category, can_render


# node_path -> the background render launched for it. One per node: a second
# launch on the same node replaces the record (the earlier process keeps going).
_BACKGROUND_RENDERS: dict[str, dict[str, Any]] = {}

_BACKGROUND_SCRIPT = """
import sys, hou
hip, path, has_range, start, end, inc = sys.argv[1:7]
hou.hipFile.load(hip, suppress_save_prompt=True, ignore_load_warnings=True)
node = hou.node(path)
if node is None:
    raise SystemExit("node not found after load: " + path)
if hasattr(node, "render"):
    if has_range == "1":
        node.render(frame_range=(float(start), float(end), float(inc)), verbose=True, output_progress=True)
    else:
        node.render(verbose=True, output_progress=True)
else:
    node.parm("execute").pressButton()
errors = list(node.errors())
if errors:
    sys.stderr.write("\\n".join(errors) + "\\n")
    raise SystemExit(1)
"""


def _launch_background_render(node: hou.Node, frame_range: list | None) -> dict[str, Any]:
    """Render from a fresh hython on the saved hip, like Houdini's own
    "Render in Background", and return at once with how to follow it."""
    if hou.hipFile.isNewFile():
        raise ValueError("Save the hip first (save_scene): a background render loads it from disk")
    hou.hipFile.save()
    hfs = hou.getenv("HFS") or ""
    hython = os.path.join(hfs, "bin", "hython.exe" if os.name == "nt" else "hython")
    if not os.path.exists(hython):
        raise ValueError(f"hython not found at {hython}; cannot render in the background")
    fd, log_path = tempfile.mkstemp(prefix="fxhoudinimcp_render_", suffix=".log")
    log = os.fdopen(fd, "w")
    args = [hython, "-c", _BACKGROUND_SCRIPT, hou.hipFile.path(), node.path()]
    if frame_range is not None:
        inc = frame_range[2] if len(frame_range) > 2 else 1
        args += ["1", str(frame_range[0]), str(frame_range[1]), str(inc)]
    else:
        args += ["0", "0", "0", "1"]
    env = dict(os.environ)
    # Houdini 21 hython segfaults on the bundled OpenFX plugins; harmless elsewhere.
    env.setdefault("HOUDINI_DISABLE_OPENFX_DEFAULT_PATH", "1")
    proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, env=env)  # noqa: S603
    record = {
        "pid": proc.pid,
        "proc": proc,
        "log": log_path,
        "started": time.time(),
        "frame_range": frame_range,
    }
    _BACKGROUND_RENDERS[node.path()] = record
    return record


def _background_status(node_path: str) -> dict[str, Any] | None:
    record = _BACKGROUND_RENDERS.get(node_path)
    if record is None:
        return None
    proc = record["proc"]
    code = proc.poll()
    tail = ""
    with (
        contextlib.suppress(OSError),
        open(record["log"], encoding="utf-8", errors="replace") as fh,
    ):
        tail = "".join(fh.readlines()[-8:])
    return {
        "pid": record["pid"],
        "running": code is None,
        "exit_code": code,
        "elapsed_seconds": round(time.time() - record["started"], 1),
        "frame_range": record["frame_range"],
        "log": record["log"],
        "log_tail": tail,
    }


def start_render(
    node_path: str,
    frame_range: list = None,
    background: bool = False,
) -> dict:
    """Begin rendering a ROP node.

    Args:
        node_path: Path to any node that renders or writes: a /out ROP, a
            LOP usdrender_rop, a SOP ROP Geometry or File Cache, and so on.
        frame_range: Optional [start, end] or [start, end, increment]. If not
            provided, the node's own frame range settings are used.
        background: Render from a separate hython on the saved hip and return
            at once; get_render_progress follows the process. Off by default:
            a foreground render shows the user Houdini's own progress dialog,
            and the dispatcher puts no deadline on it.
    """
    node, category, can_render = _renderable(node_path)
    execute_parm = node.parm("execute")

    if frame_range is not None and len(frame_range) < 2:
        raise ValueError("frame_range must have at least [start, end].")

    if background:
        before = reported_outputs(node)
        record = _launch_background_render(node, frame_range)
        return {
            "node_path": node_path,
            "category": category,
            "method": "hython subprocess on the saved hip",
            "background": True,
            "pid": record["pid"],
            "log": record["log"],
            "frame_range": frame_range,
            "success": True,
            "wrote_files": False,
            "status": "launched",
            "message": (
                "Background render launched; poll get_render_progress(node_path) "
                "for the process state, its log tail and the files on disk."
            ),
            "outputs": before,
        }

    # Snapshot the outputs so "did this write anything" is answerable afterwards
    # rather than inferred from a call that did not raise. Evaluated at the first
    # frame of the range: at the playbar's frame a render of 41-43 read as
    # "nothing was written".
    first_frame = float(frame_range[0]) if frame_range else None
    with at_frame(first_frame):
        before = reported_outputs(node)

    method = None
    try:
        if can_render:
            method = "render()"
            if frame_range is not None:
                start = float(frame_range[0])
                end = float(frame_range[1])
                inc = float(frame_range[2]) if len(frame_range) > 2 else 1.0
                # RopNode.render takes the increment as the third element of
                # frame_range; there is no frame_increment keyword.
                node.render(frame_range=(start, end, inc), output_progress=True)
            else:
                node.render(output_progress=True)
        else:
            # A File Cache SOP has no render(); its Save to Disk is a button, and
            # its range lives on trange/f rather than in a render() argument.
            method = "execute button"
            if frame_range is not None:
                _apply_frame_range_parms(node, frame_range)
            # Save to Disk is a Python callback: pressButton() would answer
            # its exception with a modal window instead of raising.
            press(execute_parm)
    except (hou.OperationFailed, CallbackError) as e:
        with at_frame(first_frame):
            verdict = failure_verdict(node, before, e)
        return {"node_path": node_path, "category": category, "method": method, **verdict}

    # render() returning without raising is NOT evidence that a render happened.
    # A LOP usdrender_rop shells out to husk, and when husk exits non-zero -- no
    # license, bad scene, missing camera -- the ROP records the error and render()
    # still returns normally. Reporting that as success is how a caller ends up
    # verifying a screenshot of an image that was never written, so read the
    # node's own errors and whether the files moved.
    with at_frame(first_frame):
        verdict = write_verdict(node, before, action="Render")
    return {
        "node_path": node_path,
        "category": category,
        "method": method,
        "background": False,
        "frame_range": frame_range,
        **verdict,
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
    require_ui(
        "screenshot the network editor",
        alternative="get_network_overview and list_children describe a network without a UI.",
    )
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
    from fxhoudinimcp_server.handlers.viewport_handlers import _capture_pane_tab_qt

    _capture_pane_tab_qt(network_editor, output_path)

    return {
        "success": True,
        "node_path": node_path,
        "output_path": output_path,
        "file_exists": os.path.isfile(output_path),
    }


###### rendering.get_render_progress


def get_render_progress(node_path: str) -> dict:
    """Check the render status / progress of a ROP node.

    Args:
        node_path: Path to the ROP/Driver node.
    """
    node, category, _ = _renderable(node_path)

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

    background = _background_status(node_path)
    outputs = reported_outputs(node)
    if output_file is None:
        for entry in outputs:
            if entry.get("path"):
                output_file = entry["path"]
                output_exists = bool(entry.get("exists"))
                break
    return {
        "node_path": node.path(),
        "category": category,
        "is_cooking": is_cooking,
        "cook_count": cook_count,
        "errors": errors,
        "warnings": warnings,
        "license_error": license_error(errors),
        "output_file": output_file,
        "output_exists": output_exists,
        "outputs": outputs,
        "background": background,
        "done": (background is not None and not background["running"])
        or (background is None and not is_cooking),
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
