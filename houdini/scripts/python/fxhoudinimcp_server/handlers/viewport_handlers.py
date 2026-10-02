"""Viewport and UI handlers for FXHoudini-MCP.

Provides tools for inspecting and controlling Houdini's viewport panes,
network editor navigation, display modes, camera assignment, and
screenshot capture of various pane types.
"""

from __future__ import annotations

# Built-in
import contextlib
import logging
import os

# Third-party
import hou

# Internal
from fxhoudinimcp_server.dispatcher import register_handler
from fxhoudinimcp_server.ui import (
    keep_viewer_state,
    require_ui,
    selection_hidden,
    set_other_objects,
)

logger = logging.getLogger(__name__)


def _no_mplay(settings) -> None:
    """Keep a flipbook from launching MPlay.

    MPlay is a child process of Houdini and inherits its file descriptors, the
    hwebserver listening socket among them. After Houdini exits, that MPlay
    keeps the port open and the next Houdini's auto-start fails with "an
    existing server is running on port N". The frame is written to disk either
    way; a viewer nobody asked for is not worth losing the next session's
    server.
    """
    with contextlib.suppress(Exception):
        settings.outputToMPlay(False)


def _capture_pane_tab_qt(pane_tab, output_path: str) -> None:
    """Capture a pane tab screenshot via Qt.

    Houdini 20.x exposed PaneTab.qtParentWidget(); Houdini 21 removed it
    in favor of qtParentWindow()/qtScreenGeometry(), so fall back to
    grabbing the pane's screen region.
    """
    pixmap = None

    if hasattr(pane_tab, "qtParentWidget"):
        try:
            widget = pane_tab.qtParentWidget()
        except Exception:
            widget = None
        if widget is not None:
            pixmap = widget.grab()

    if pixmap is None and hasattr(pane_tab, "qtScreenGeometry"):
        rect = pane_tab.qtScreenGeometry()
        try:
            from PySide6 import QtCore, QtGui
        except ImportError:
            from PySide2 import QtCore, QtGui
        # Render the pane's region from Houdini's own window. A screen grab
        # returns whatever is on top of Houdini at that moment: a terminal, a
        # browser, a white dialog (the blank capture in #38).
        window = None
        with contextlib.suppress(Exception):
            panel = pane_tab.pane().floatingPanel()
            window = hou.qt.floatingPanelWindow(panel) if panel else hou.qt.mainWindow()
        if window is not None:
            local = QtCore.QRect(window.mapFromGlobal(rect.topLeft()), rect.size())
            pixmap = window.grab(local)

    if pixmap is None and hasattr(pane_tab, "qtScreenGeometry"):
        screens = QtGui.QGuiApplication.screens()
        screen = QtGui.QGuiApplication.primaryScreen()
        for candidate in screens:
            if candidate.geometry().contains(rect.center()):
                screen = candidate
                break
        geometry = screen.geometry()
        pixmap = screen.grabWindow(
            0,
            rect.x() - geometry.x(),
            rect.y() - geometry.y(),
            rect.width(),
            rect.height(),
        )

    if pixmap is None:
        raise RuntimeError(
            f"Cannot capture pane '{pane_tab.name()}': no Qt capture API "
            f"available in this Houdini build."
        )

    if not pixmap.save(output_path):
        raise RuntimeError(
            f"Failed to save screenshot to '{output_path}'. "
            f"Ensure the path is writable and the format is supported (e.g. .png, .jpg)."
        )


def _viewer_stage(scene_viewer):
    """The USD stage a Solaris viewer is displaying, or None.

    Tried in order because which of these is a LOP depends on what the user last
    clicked: the current node, the network the viewer is in, and that network's
    display node.
    """
    candidates = []
    with contextlib.suppress(Exception):
        candidates.append(scene_viewer.currentNode())
    with contextlib.suppress(Exception):
        candidates.append(scene_viewer.pwd())
    with contextlib.suppress(Exception):
        candidates.append(scene_viewer.pwd().displayNode())
    for node in candidates:
        if node is None or not hasattr(node, "stage"):
            continue
        with contextlib.suppress(Exception):
            stage = node.stage()
            if stage is not None:
                return stage
    return None


def _camera_prims(stage, limit: int = 12) -> list[str]:
    """Camera prim paths on a stage, for error messages worth reading."""
    found: list[str] = []
    with contextlib.suppress(Exception):
        for prim in stage.Traverse():
            if str(prim.GetTypeName()) == "Camera":
                found.append(str(prim.GetPath()))
                if len(found) >= limit:
                    break
    return found


def _is_scene_graph_view(scene_viewer) -> bool:
    """Whether Hydra delegates apply at all.

    hydraRenderers() raises "Specified view is not a scene graph view" in an
    object-level viewport, which is a different situation from a build that has
    no such API, and reporting them the same way sent a caller looking for a
    Houdini upgrade instead of a Solaris viewport.
    """
    try:
        scene_viewer.hydraRenderers()
    except Exception:
        return False
    return True


###### viewport.list_panes


def list_panes() -> dict:
    """List all visible pane tabs, their types, and associated information."""
    require_ui("list Houdini's panes")
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

    # camera() returns a hou.Node, so it is None for a USD camera prim even when
    # the viewport is looking through one. cameraPath() answers for both, and
    # without it there was no way to ask "what am I actually looking through".
    info["camera_path"] = None
    with contextlib.suppress(Exception):
        info["camera_path"] = viewport.cameraPath() or None

    # cameraPath() is an echo of whatever was last set, and Houdini will happily
    # echo a path that does not exist. Repeating it unchecked would make this tool
    # a second source of the same false confidence, so resolve it: as a node, or
    # as a prim on the viewer's stage.
    if info["camera_path"]:
        resolved = hou.node(info["camera_path"]) is not None
        if not resolved:
            stage = _viewer_stage(scene_viewer)
            if stage is not None:
                with contextlib.suppress(Exception):
                    prim = stage.GetPrimAtPath(info["camera_path"])
                    resolved = bool(prim and prim.IsValid())
        info["camera_path_resolves"] = resolved

    # The active Hydra delegate. Nothing reported this before, so a viewport that
    # had silently reverted to GL looked identical to one rendering in Karma
    # until someone eyeballed a screenshot.
    info["renderer"] = None
    with contextlib.suppress(Exception):
        info["renderer"] = scene_viewer.currentHydraRenderer()
    with contextlib.suppress(Exception):
        info["available_renderers"] = list(scene_viewer.hydraRenderers())

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
    scene_viewer = _find_scene_viewer(pane_name)
    viewport = scene_viewer.curViewport()

    # A USD camera prim is not a hou.node, so resolving through hou.node() alone
    # made every Solaris shot unframeable: the tool raised "Camera node not
    # found" for a path that is perfectly valid on the stage. A recorded session
    # lost nine execute_python calls to this and still shipped the wrong framing.
    cam_node = hou.node(camera_path)
    if cam_node is not None:
        viewport.setCamera(cam_node)
        # camera() returns the node, so comparing it is real verification.
        bound = None
        with contextlib.suppress(Exception):
            bound = viewport.camera()
        if bound is None or bound.path() != cam_node.path():
            raise RuntimeError(
                f"Asked to look through '{camera_path}' but the viewport reports "
                f"'{bound.path() if bound else None}'."
            )
        return {
            "success": True,
            "verified": True,
            "camera_path": cam_node.path(),
            "is_usd_prim": False,
            "pane_name": scene_viewer.name(),
            "viewport_name": viewport.name(),
        }

    # A USD camera prim is not a hou.node, so resolving through hou.node() alone
    # made every Solaris shot unframeable. But cameraPath() cannot verify the
    # result either: it is a pure echo, and setCamera("/cameras/does_not_exist")
    # returns without error and leaves cameraPath() reporting that exact
    # nonexistent path. Verification has to be a stage lookup.
    stage = _viewer_stage(scene_viewer)
    if stage is None:
        raise ValueError(
            f"'{camera_path}' is not a node, and this viewport has no USD stage "
            f"to look it up on. A Solaris camera prim requires the viewer to be "
            f"in a LOP network."
        )
    prim = stage.GetPrimAtPath(camera_path)
    if prim is None or not prim.IsValid():
        cameras = _camera_prims(stage)
        raise ValueError(
            f"No prim at '{camera_path}' on this stage."
            + (f" Camera prims present: {cameras}" if cameras else " The stage has no cameras.")
        )
    type_name = str(prim.GetTypeName())
    if type_name != "Camera":
        raise ValueError(
            f"'{camera_path}' is a {type_name or 'typeless'} prim, not a Camera. "
            f"Camera prims present: {_camera_prims(stage)}"
        )

    viewport.setCamera(camera_path)
    echoed = None
    with contextlib.suppress(Exception):
        echoed = viewport.cameraPath() or None
    if echoed is not None and echoed.rstrip("/") != camera_path.rstrip("/"):
        raise RuntimeError(
            f"Asked to look through '{camera_path}' but the viewport is on '{echoed}'."
        )

    return {
        "success": True,
        "verified": True,
        "camera_path": camera_path,
        "is_usd_prim": True,
        "prim_type": type_name,
        "pane_name": scene_viewer.name(),
        "viewport_name": viewport.name(),
    }


###### viewport.set_viewport_display


# color_scheme's spellings, mapped to hou.viewportColorScheme names.
_COLOR_SCHEMES = {
    "dark": "Dark",
    "darkgrey": "DarkGrey",
    "dark_grey": "DarkGrey",
    "grey": "Grey",
    "gray": "Grey",
    "light": "Light",
}


def set_viewport_display(
    display_mode: str = None,
    pane_name: str = None,
    environment_background: bool = None,
    reference_plane: bool = None,
    point_size: float = None,
    color_scheme: str = None,
) -> dict:
    """Set how the viewport draws: shading, background, grid, point size, colours.

    Args:
        display_mode: One of 'wireframe', 'shaded', 'smooth', 'smooth_wire',
            'hidden_line', 'flat', 'flat_wire', 'point'.
        pane_name: Optional pane tab name.
        environment_background: Show (True) or hide (False) an environment
            light's map behind the scene, on every view of the viewer.
        reference_plane: Show (True) or hide (False) the reference plane (the
            grid).
        point_size: Diameter in pixels of particles drawn as points, on every
            view of the viewer.
        color_scheme: 'dark', 'darkgrey', 'grey' or 'light', on every view.

    Each setting is read back rather than echoed: the per-view ones as a
    ``{view name: value}`` map.
    """
    asked = (display_mode, environment_background, reference_plane, point_size, color_scheme)
    if all(value is None for value in asked):
        raise ValueError(
            "Pass display_mode, environment_background, reference_plane, point_size "
            "or color_scheme."
        )
    # Refused before anything is touched, so a bad value never half-applies a call.
    scheme = None
    if color_scheme is not None:
        scheme = _COLOR_SCHEMES.get(str(color_scheme).strip().lower().replace(" ", ""))
        if scheme is None:
            raise ValueError(
                f"Unknown color_scheme '{color_scheme}'. Supported: dark, darkgrey, grey, light."
            )
    size = None
    if point_size is not None:
        try:
            size = float(point_size)
        except (TypeError, ValueError):
            size = 0.0
        if isinstance(point_size, bool) or not size > 0:
            raise ValueError(f"point_size must be a positive number of pixels, got {point_size!r}")

    mode_map = {
        "wireframe": hou.glShadingType.Wire,
        "wire": hou.glShadingType.Wire,
        "shaded": hou.glShadingType.Smooth,
        "smooth": hou.glShadingType.Smooth,
        "smooth_wire": hou.glShadingType.SmoothWire,
        "hidden_line": hou.glShadingType.HiddenLineGhost,
        "flat": hou.glShadingType.Flat,
        "flat_wire": hou.glShadingType.FlatWire,
        "matcap": hou.glShadingType.MatCap,
        "matcap_wire": hou.glShadingType.MatCapWire,
    }

    gl_mode = None
    if display_mode is not None:
        gl_mode = mode_map.get(display_mode.lower())
        if gl_mode is None:
            raise ValueError(
                f"Unknown display mode: '{display_mode}'. Supported modes: {list(mode_map.keys())}"
            )

    scene_viewer = _find_scene_viewer(pane_name)
    result = {"success": True, "pane_name": scene_viewer.name()}

    if gl_mode is not None:
        settings = scene_viewer.curViewport().settings()
        display_set = settings.displaySet(hou.displaySetType.SceneObject)
        display_set.setShadedMode(gl_mode)
        result["display_mode"] = display_mode

    if environment_background is not None:
        # The flag is kept per view, not per viewer: a quad layout carries
        # four, and setting it on curViewport() alone leaves the map behind
        # the other three. Each view's state is read back, not echoed.
        shown = {}
        for view in scene_viewer.viewports():
            settings = view.settings()
            settings.setDisplayEnvironmentBackgroundImage(bool(environment_background))
            shown[view.name()] = settings.displayEnvironmentBackgroundImage()
        result["environment_background"] = shown

    if reference_plane is not None:
        # One plane per viewer, not per view.
        plane = scene_viewer.referencePlane()
        plane.setIsVisible(bool(reference_plane))
        result["reference_plane"] = plane.isVisible()

    if size is not None:
        # GeometryViewportSettings has particlePointSize() and no setter, so a
        # session looking for one read back 3.0 and gave up. viewdisplay -p on
        # the viewer sets it on every view. The viewer keeps one set per
        # context: .world for objects and SOPs, .solaris in a LOP network.
        # .world from /stage read back 3.0 on every view and changed the size
        # the object viewer showed later instead (22.0.368).
        in_lops = scene_viewer.pwd().childTypeCategory() == hou.lopNodeTypeCategory()
        context = "solaris" if in_lops else "world"
        viewer_path = f"{hou.ui.curDesktop().name()}.{scene_viewer.name()}.{context}"
        _, error = hou.hscript(f"viewdisplay -p {size} {viewer_path}")
        if error.strip():
            raise RuntimeError(f"viewdisplay -p failed: {error.strip()}")
        result["point_size"] = {
            view.name(): view.settings().particlePointSize() for view in scene_viewer.viewports()
        }

    if scheme is not None:
        schemes = {}
        for view in scene_viewer.viewports():
            settings = view.settings()
            settings.setColorScheme(getattr(hou.viewportColorScheme, scheme))
            schemes[view.name()] = str(settings.colorScheme()).rsplit(".", 1)[-1]
        result["color_scheme"] = schemes

    return result


###### viewport.set_viewport_direction


def _vector3(value, name: str) -> tuple:
    """Three floats from *value*, or a ValueError naming *name*."""
    try:
        numbers = tuple(float(v) for v in value)
    except (TypeError, ValueError):
        numbers = ()
    if len(numbers) != 3:
        raise ValueError(f"{name} must be three numbers, got {value!r}")
    return numbers


def _looked_through(viewport) -> tuple[str | None, bool]:
    """(camera the viewport looks through, whether it is a USD prim), or (None, False).

    A USD camera prim is no node: camera() is None there and only cameraPath()
    names it.
    """
    bound = viewport.camera()
    if bound is not None:
        return bound.path(), False
    path = viewport.cameraPath() or None
    return path, path is not None


def set_viewport_direction(
    direction: str = None,
    pane_name: str = None,
    rotation: list = None,
    pivot: list = None,
    distance: float = None,
) -> dict:
    """Set the viewport to a standard viewing direction, or place the free view.

    Args:
        direction: One of 'front', 'back', 'top', 'bottom', 'left', 'right',
            'perspective'.
        pane_name: Optional pane tab name.
        rotation: [rx, ry, rz] in degrees: the free view's rotation about its
            pivot.
        pivot: [x, y, z] the free view orbits.
        distance: How far the free view sits from its pivot.

    rotation, pivot and distance place the viewport's own (non-camera) view,
    after *direction* if both are given, and the reply reads it back as
    ``view``. A viewport looking through a camera is refused: what it shows
    is the camera, so the camera is what to move.
    """
    direction_map = {
        "front": hou.geometryViewportType.Front,
        "back": hou.geometryViewportType.Back,
        "top": hou.geometryViewportType.Top,
        "bottom": hou.geometryViewportType.Bottom,
        "left": hou.geometryViewportType.Left,
        "right": hou.geometryViewportType.Right,
        "perspective": hou.geometryViewportType.Perspective,
    }

    free_view = rotation is not None or pivot is not None or distance is not None
    if direction is None and not free_view:
        raise ValueError("Pass direction, or rotation / pivot / distance for the free view.")
    view_type = None
    if direction is not None:
        view_type = direction_map.get(str(direction).lower())
        if view_type is None:
            raise ValueError(
                f"Unknown direction '{direction}'. Supported: {list(direction_map.keys())}"
            )
    # Checked before the viewer is touched, so a bad value never half-applies.
    angles = _vector3(rotation, "rotation") if rotation is not None else None
    centre = _vector3(pivot, "pivot") if pivot is not None else None
    if distance is not None:
        try:
            far = float(distance)
        except (TypeError, ValueError):
            far = 0.0
        if isinstance(distance, bool) or not far > 0:
            raise ValueError(f"distance must be a positive number, got {distance!r}")

    scene_viewer = _find_scene_viewer(pane_name)
    viewport = scene_viewer.curViewport()
    if free_view:
        # setDefaultCamera() unbound a USD camera prim without a word (22.0.368).
        looks_through, is_prim = _looked_through(viewport)
        if looks_through:
            move = (
                "its LOP's parameters (set_parameters) or set_usd_attribute on the prim"
                if is_prim
                else "set_object_transform on the camera object"
            )
            raise ValueError(
                f"The viewport looks through {looks_through}: rotation/pivot/distance "
                f"place the viewport's own view. Move the camera instead, with {move}."
            )
    if view_type is not None:
        viewport.changeType(view_type)
        viewport.frameAll()

    result = {
        "success": True,
        "direction": direction,
        "pane_name": scene_viewer.name(),
        "viewport_name": viewport.name(),
    }
    if not free_view:
        return result

    # The view's translation is a world position that the rotation turns about
    # the pivot: the eye is pivot + R * (translation - pivot). Measured on
    # 22.0.429: moving only the pivot left the eye where it was, looking past
    # the new pivot. So the eye's offset from the pivot (pan in x/y, distance
    # in z) is what is kept, and the translation follows the pivot.
    view = viewport.defaultCamera().stash()
    old_pivot = list(view.pivot())
    offset = [t - p for t, p in zip(view.translation(), old_pivot, strict=True)]
    if angles is not None:
        # setRotation() takes the transpose of what buildRotate() gives: as is,
        # the view looked along the inverse turn, (0.5, 0.3, -0.8) where a cam
        # object with the same r looks along (-0.47, -0.34, -0.81) (22.0.429).
        rotate = hou.hmath.buildRotate(hou.Vector3(*angles))
        view.setRotation(rotate.extractRotationMatrix3().transposed())
    if centre is not None or distance is not None:
        new_pivot = list(centre) if centre is not None else old_pivot
        if distance is not None:
            offset[2] = far
        view.setPivot(hou.Vector3(*new_pivot))
        view.setTranslation(hou.Vector3(*(p + o for p, o in zip(new_pivot, offset, strict=True))))
    viewport.setDefaultCamera(view)

    now = viewport.defaultCamera()
    now_pivot = list(now.pivot())
    result["view"] = {
        "rotation": [
            round(v, 4) for v in hou.Matrix4(now.rotation().transposed()).extractRotates()
        ],
        "pivot": [round(v, 4) for v in now_pivot],
        "distance": round(now.translation()[2] - now_pivot[2], 4),
    }
    return result


###### viewport.set_viewport_renderer


def set_viewport_renderer(
    renderer: str,
    pane_name: str = None,
) -> dict:
    """Set the viewport's Hydra rendering delegate.

    In LOPs/Solaris the viewport can render through different Hydra delegates
    (GL, Storm, Karma CPU, Karma XPU, etc.) without writing to disk.

    Args:
        renderer: Renderer name — e.g. "GL", "Storm", "Karma CPU",
            "Karma XPU", "Houdini GL". Case-insensitive partial match.
        pane_name: Optional pane tab name.
    """
    scene_viewer = _find_scene_viewer(pane_name)
    viewport = scene_viewer.curViewport()

    # hou.SceneViewer.hydraRenderers/setHydraRenderer/currentHydraRenderer is the
    # documented pair for this. The previous implementation went through
    # viewport.settings().setRenderer() with an hscript fallback and, crucially,
    # never read the renderer back: it returned success whenever a setter did not
    # raise. A recorded session spent nine execute_python calls discovering that
    # the viewport was still on GL while this tool reported Karma, and every
    # screenshot it verified against was therefore the wrong image.
    available: list[str] = []
    with contextlib.suppress(Exception):
        available = list(scene_viewer.hydraRenderers())
    if not available:
        with contextlib.suppress(Exception):
            settings = viewport.settings()
            if hasattr(settings, "rendererNames"):
                available = list(settings.rendererNames())

    target = renderer.strip().lower()
    matched_name = next((n for n in available if n.lower() == target), None)
    if matched_name is None:
        matched_name = next((n for n in available if target in n.lower()), None)
    if matched_name is None and not available:
        matched_name = renderer
    if matched_name is None:
        raise ValueError(f"Renderer '{renderer}' not found. Available renderers: {available}")

    def _current() -> str | None:
        with contextlib.suppress(Exception):
            return scene_viewer.currentHydraRenderer()
        return None

    before = _current()
    attempts: list[str] = []
    for label, apply in (
        ("setHydraRenderer", lambda: scene_viewer.setHydraRenderer(matched_name)),
        (
            "settings.setRenderer",
            lambda: viewport.settings().setRenderer(matched_name),
        ),
        (
            "hscript viewdisplay",
            lambda: hou.hscript(f'viewdisplay -R "{matched_name}" {viewport.name()}'),
        ),
    ):
        try:
            apply()
        except Exception as exc:  # noqa: BLE001 - each route is best-effort
            attempts.append(f"{label}: {type(exc).__name__}")
            continue
        attempts.append(f"{label}: no error")
        if (_current() or "").lower() == matched_name.lower():
            break

    active = _current()
    # The renderer Houdini reports is the answer. Anything else is a guess about
    # whether a setter worked.
    applied = active is not None and active.lower() == matched_name.lower()
    if not applied and active is None:
        if not _is_scene_graph_view(scene_viewer):
            # Not a missing API: Hydra delegates only exist for a scene graph
            # view, so this request is meaningless in an object-level viewport
            # and saying "unverifiable" would hide a real mistake.
            raise ValueError(
                "This viewport is not a scene graph view, so it has no Hydra "
                "delegate to set. Hydra renderers (Karma, Storm) apply to a "
                "Solaris viewport: put the viewer in a LOP network first."
            )
        # A scene graph view with no readback: state genuinely unknown, so say so
        # rather than claiming the requested renderer is live.
        return {
            "success": True,
            "verified": False,
            "requested": matched_name,
            "renderer": None,
            "note": (
                "This Houdini exposes no currentHydraRenderer(), so the active "
                "renderer could not be confirmed. Capture a screenshot before "
                "trusting the viewport."
            ),
            "available_renderers": available,
            "attempts": attempts,
            "pane_name": scene_viewer.name(),
            "viewport_name": viewport.name(),
        }
    if not applied:
        raise RuntimeError(
            f"Asked for renderer '{matched_name}' but the viewport is still on "
            f"'{active}' (was '{before}'). Tried: {'; '.join(attempts)}. "
            f"Available renderers: {available}"
        )

    return {
        "success": True,
        "verified": True,
        "renderer": active,
        "previous_renderer": before,
        "available_renderers": available,
        "pane_name": scene_viewer.name(),
        "viewport_name": viewport.name(),
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


def _world_bounds(node: hou.Node) -> list | None:
    """[xmin, ymin, zmin, xmax, ymax, zmax] of what *node* shows, in world space.

    An object is its display SOP; a SOP's geometry is in its object's space,
    so it goes through that object's world transform. None without geometry.
    """
    owner, target = node, node
    if isinstance(node, hou.ObjNode):
        target = node.displayNode()
    else:
        while owner is not None and not isinstance(owner, hou.ObjNode):
            owner = owner.parent()
    try:
        box = target.geometry().boundingBox()
    except Exception:
        return None
    if not box.isValid():
        return None
    low, high = box.minvec(), box.maxvec()
    corners = [
        (x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])
    ]
    if owner is not None:
        transform = owner.worldTransform()
        corners = [tuple(hou.Vector3(*corner) * transform) for corner in corners]
    return [
        *(min(corner[i] for corner in corners) for i in range(3)),
        *(max(corner[i] for corner in corners) for i in range(3)),
    ]


def frame_all(pane_name: str = None, node_paths: list = None, bounds: list = None) -> dict:
    """Frame all geometry in the viewport (home all), or only some of it.

    Args:
        pane_name: Optional pane tab name.
        node_paths: Frame the world bounds of these objects or SOPs only.
        bounds: Frame [xmin, ymin, zmin, xmax, ymax, zmax], in world space.

    With *node_paths* or *bounds* (both: the box around all of them), the
    reply carries ``framed_bounds``, and ``no_geometry`` names any node that
    had nothing to frame.
    """
    box = None
    empty: list = []
    if bounds is not None:
        try:
            box = [float(v) for v in bounds]
        except (TypeError, ValueError):
            box = []
        if len(box) != 6 or any(box[i] > box[i + 3] for i in range(3)):
            raise ValueError(f"bounds must be [xmin, ymin, zmin, xmax, ymax, zmax], got {bounds!r}")
    if node_paths is not None:
        if isinstance(node_paths, str):
            node_paths = [node_paths]
        missing = [path for path in node_paths if hou.node(str(path)) is None]
        if missing:
            raise ValueError(f"Node(s) not found: {missing}")
        for path in node_paths:
            found = _world_bounds(hou.node(str(path)))
            if found is None:
                empty.append(path)
            elif box is None:
                box = found
            else:
                box = [min(box[i], found[i]) for i in range(3)] + [
                    max(box[i], found[i]) for i in range(3, 6)
                ]
        if box is None:
            raise ValueError(f"Nothing to frame: no geometry on {empty}")

    scene_viewer = _find_scene_viewer(pane_name)
    viewport = scene_viewer.curViewport()
    result = {
        "success": True,
        "pane_name": scene_viewer.name(),
        "viewport_name": viewport.name(),
    }
    # Framing moves the viewport's own view, so a camera it looked through is
    # dropped one UI tick later: both homeAll() and frameBoundingBox() did
    # that to /obj/refcam on 22.0.368, and the reply said nothing. The camera
    # itself does not move. Say so rather than refuse: no tool unbinds a
    # camera, so a refusal would leave framing impossible.
    looks_through, _ = _looked_through(viewport)
    if looks_through:
        result["camera_released"] = looks_through
        result["note"] = (
            f"The viewport stopped looking through {looks_through} to frame; the camera "
            f"did not move. set_viewport_camera looks through it again."
        )
    if box is None:
        viewport.homeAll()
        return result

    viewport.frameBoundingBox(hou.BoundingBox(*box))
    result["framed_bounds"] = [round(v, 4) for v in box]
    if empty:
        result["no_geometry"] = empty
    return result


###### viewport.capture_screenshot


def capture_screenshot(
    output_path: str,
    pane_name: str = None,
) -> dict:
    """Capture a screenshot of a specific pane tab, or the active viewport.

    Args:
        output_path: Destination image path.
        pane_name: Name of the pane tab to capture. If not provided,
            captures the first Scene Viewer found.
    """
    out_dir = os.path.dirname(output_path)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    # Named pane if asked for, otherwise the first Scene Viewer.
    pane_tab = _find_pane_by_name(pane_name) if pane_name is not None else _find_scene_viewer()

    cur_frame = hou.frame()

    # For scene viewers, use flipbook for capture
    if pane_tab.type() == hou.paneTabType.SceneViewer:
        viewport = pane_tab.curViewport()
        settings = pane_tab.flipbookSettings().stash()
        settings.frameRange((cur_frame, cur_frame))
        settings.output(output_path)
        _no_mplay(settings)
        # A selected object would be drawn with its selection outline.
        with selection_hidden():
            pane_tab.flipbook(viewport, settings)

        # Handle frame number that flipbook may insert
        from fxhoudinimcp_server.handlers.rendering_handlers import _find_flipbook_output

        actual_path = _find_flipbook_output(output_path, cur_frame)
    else:
        actual_path = output_path
        # For other pane types, use Qt widget grab
        _capture_pane_tab_qt(pane_tab, output_path)

    return {
        "success": True,
        "pane_name": pane_tab.name(),
        "output_path": actual_path,
        "file_exists": os.path.isfile(actual_path),
    }


###### viewport.capture_network_editor

# Network units of context around the framed node, each side: enough for its
# immediate neighbours to show, few enough that the node is still readable.
_FRAME_PAD_X = 5.0
_FRAME_PAD_Y = 3.0


def _bounds_list(bounds) -> list | None:
    """``hou.BoundingRect`` -> ``[xmin, ymin, xmax, ymax]``, rounded."""
    try:
        return [round(v, 3) for v in (*bounds.min(), *bounds.max())]
    except Exception:
        return None


def _frame_node(network_editor, node) -> list:
    """Put *node* in the middle of the editor at once, not after a flight.

    ``homeToSelection()`` animates the view over the next event-loop ticks,
    while the capture runs in this same tick, so the image came out mid-flight:
    the whole network, or an empty stretch between the previous node and this
    one. ``setVisibleBounds(transition_time=0)`` moves the view before the grab.

    ``set_center_when_scale_rejected``: a rect at the zoom the editor already
    has counts as a rejected scale change, and without the flag the call then
    changes nothing at all, so every capture after the first stayed on the
    first node (measured on 22.0.429).

    Returns the node's own rect in network space.
    """
    pos = node.position()
    size = node.size()
    xmin, ymin = pos[0], pos[1]
    xmax, ymax = xmin + size[0], ymin + size[1]
    network_editor.setVisibleBounds(
        hou.BoundingRect(
            xmin - _FRAME_PAD_X,
            ymin - _FRAME_PAD_Y,
            xmax + _FRAME_PAD_X,
            ymax + _FRAME_PAD_Y,
        ),
        transition_time=0.0,
        set_center_when_scale_rejected=True,
    )
    return [round(v, 3) for v in (xmin, ymin, xmax, ymax)]


def capture_network_editor(
    output_path: str,
    node_path: str = None,
) -> dict:
    """Capture a screenshot of the network editor.

    Args:
        output_path: Destination image path.
        node_path: Optional node path to frame before capture.

    The reply carries ``visible_bounds`` (the network space the image shows)
    and, with *node_path*, ``node_bounds`` and ``node_in_view``, so what the
    image holds can be checked without opening it.
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
    node_bounds = None
    if node_path is not None:
        node = hou.node(node_path)
        if node is None:
            raise ValueError(f"Node not found: {node_path}")
        with keep_viewer_state():
            parent = node.parent()
            if parent is not None:
                network_editor.cd(parent.path())
            network_editor.setCurrentNode(node)
            node_bounds = _frame_node(network_editor, node)

    # Capture the network editor via Qt widget grab
    _capture_pane_tab_qt(network_editor, output_path)

    result = {
        "success": True,
        "output_path": output_path,
        "node_path": node_path,
        "file_exists": os.path.isfile(output_path),
        "visible_bounds": None,
    }
    with contextlib.suppress(Exception):
        result["visible_bounds"] = _bounds_list(network_editor.visibleBounds())
    if node_bounds is not None:
        view = result["visible_bounds"]
        result["node_bounds"] = node_bounds
        result["node_in_view"] = (
            None
            if view is None
            else (
                view[0] <= node_bounds[0]
                and view[1] <= node_bounds[1]
                and node_bounds[2] <= view[2]
                and node_bounds[3] <= view[3]
            )
        )
    return result


###### viewport.set_current_network


def set_current_network(network_path: str, other_objects: str | None = "hide") -> dict:
    """Navigate the network editor to a specific network path.

    The viewer follows the network editor into the object, and *other_objects*
    sets what it draws of every other object (the viewport's Y hotkey): "hide"
    by default, so work in one object is not drawn over, and slowed by, the
    rest of the scene. No display flag changes.

    Args:
        network_path: Path to the network to navigate to (e.g. '/obj/geo1').
        other_objects: "hide", "ghost", "show", or None to leave the viewer as is.
    """
    node = hou.node(network_path)
    if node is None:
        raise ValueError(f"Network path not found: {network_path}")

    require_ui(
        "navigate the network editor",
        alternative="Without a UI the network can still be read with list_children.",
    )
    network_editor = None
    for pane_tab in hou.ui.paneTabs():
        if pane_tab.type() == hou.paneTabType.NetworkEditor:
            network_editor = pane_tab
            break

    if network_editor is None:
        raise RuntimeError("No Network Editor pane found.")

    # The viewer follows the editor; its cameras and the selection stay.
    with keep_viewer_state():
        network_editor.cd(network_path)

    return {
        "success": True,
        "network_path": network_path,
        "pane_name": network_editor.name(),
        "other_objects": set_other_objects(other_objects),
    }


###### viewport.find_error_nodes


_ERROR_NODE_CAP = 50


def find_error_nodes(root_path: str = "/") -> dict:
    """Find all nodes with errors or warnings, recursively from a root path.

    Args:
        root_path: Root node path to start searching from. Defaults to '/'.
    """
    root = hou.node(root_path)
    if root is None:
        raise ValueError(f"Root path not found: {root_path}")

    from fxhoudinimcp_server.handlers.graph_handlers import _condensed

    error_nodes = []
    warning_nodes = []
    counts = {"errors": 0, "warnings": 0}

    def _check_node(node):
        """Recursively check nodes for errors and warnings.

        Messages are condensed (one upstream error repeats on every node
        downstream of it) and each list holds the first 50 nodes; the counts
        stay complete. `name` is gone: it is the tail of `path`.
        """
        for kind, reader, bucket in (
            ("errors", node.errors, error_nodes),
            ("warnings", node.warnings, warning_nodes),
        ):
            try:
                messages = reader()
            except (hou.OperationFailed, hou.ObjectWasDeleted, AttributeError) as e:
                logger.debug("Could not read %s for node '%s': %s", kind, node.path(), e)
                continue
            if messages:
                counts[kind] += 1
                if len(bucket) < _ERROR_NODE_CAP:
                    bucket.append(
                        {
                            "path": node.path(),
                            "type": node.type().name(),
                            kind: [_condensed(m) for m in messages],
                        }
                    )

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
        "error_count": counts["errors"],
        "warning_count": counts["warnings"],
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
    require_ui(
        "find a Scene Viewer",
        alternative="Geometry can still be inspected with get_geometry_info and sample_geometry.",
    )
    if pane_name is not None:
        pane_tab = _find_pane_by_name(pane_name)
        if pane_tab.type() != hou.paneTabType.SceneViewer:
            raise ValueError(
                f"Pane '{pane_name}' is a {pane_tab.type().name()}, not a Scene Viewer."
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
    require_ui(f"find the pane {pane_name!r}")
    for pane_tab in hou.ui.paneTabs():
        if pane_tab.name() == pane_name:
            return pane_tab

    available = [pt.name() for pt in hou.ui.paneTabs()]
    raise ValueError(f"Pane tab not found: '{pane_name}'. Available panes: {available}")


###### viewport.log_status


def log_status(message: str, severity: str = "message") -> dict:
    """Display a status message in Houdini's status bar.

    Args:
        message: The status message to display.
        severity: Severity level — "message" (default), "important",
            "warning", or "error".
    """
    severity_map = {
        "message": hou.severityType.Message,
        "important": hou.severityType.ImportantMessage,
        "warning": hou.severityType.Warning,
        "error": hou.severityType.Error,
    }
    sev = severity_map.get(severity.lower(), hou.severityType.Message)
    if hou.isUIAvailable():
        hou.ui.setStatusMessage(message, severity=sev)
    else:
        # Headless sessions (hython/hbatch) have no status bar; stay a
        # harmless no-op so instruction-following clients never error.
        print(f"[status] {message}")
    return {"message": message, "severity": severity}


###### Registration

register_handler("viewport.list_panes", list_panes)
register_handler("viewport.get_viewport_info", get_viewport_info)
register_handler("viewport.set_viewport_camera", set_viewport_camera)
register_handler("viewport.set_viewport_display", set_viewport_display)
register_handler("viewport.set_viewport_direction", set_viewport_direction)
register_handler("viewport.set_viewport_renderer", set_viewport_renderer)
register_handler("viewport.frame_selection", frame_selection)
register_handler("viewport.frame_all", frame_all)
register_handler("viewport.capture_screenshot", capture_screenshot)
register_handler("viewport.capture_network_editor", capture_network_editor)
register_handler("viewport.set_current_network", set_current_network)
register_handler("viewport.find_error_nodes", find_error_nodes)
register_handler("viewport.log_status", log_status)


###### viewport.set_viewer_context


def set_viewer_context(
    network_path: str,
    current_node: str = None,
    pane_name: str = None,
) -> dict:
    """Point the Scene Viewer at a network, and optionally a node within it.

    set_current_network moves the network EDITOR. This moves the VIEWER, which is
    a different pane and the one that decides whether a scene graph view exists at
    all. Without it there was no way to enter Solaris, so no way to preview a USD
    stage or set a Hydra delegate: a recorded session burned several
    execute_python calls on exactly this, and even this project's own GUI checks
    had to reach for Python.

    Args:
        network_path: Network for the viewer to display, e.g. "/stage".
        current_node: Optional node inside it to make current, which is what
            selects the stage a Solaris viewport shows.
        pane_name: Optional pane tab name.
    """
    network = hou.node(network_path)
    if network is None:
        raise ValueError(f"Network not found: {network_path}")

    scene_viewer = _find_scene_viewer(pane_name)
    scene_viewer.setPwd(network)

    if current_node is not None:
        # "karma" means the node of that name inside the network; hou.node()
        # alone reads it as relative to /, and the documented usage failed.
        node = network.node(current_node) or hou.node(current_node)
        if node is None:
            raise ValueError(f"Node not found: {current_node}")
        scene_viewer.setCurrentNode(node)

    result = {
        "success": True,
        "network_path": scene_viewer.pwd().path(),
        "pane_name": scene_viewer.name(),
        # Whether Hydra delegates apply here, which is the question the caller is
        # usually really asking.
        "is_scene_graph_view": _is_scene_graph_view(scene_viewer),
    }
    with contextlib.suppress(Exception):
        current = scene_viewer.currentNode()
        result["current_node"] = current.path() if current else None
    return result


register_handler("viewport.set_viewer_context", set_viewer_context)
