"""Saying "this needs a graphical Houdini" instead of crashing about it.

``hou.ui`` does not exist in hython or hbatch. Ten handlers reached for it without
checking, so asking for a viewport screenshot in a headless session answered:

    module 'hou' has no attribute 'ui'

which reads as a broken plugin and sends the caller debugging the server. The real
answer is that the operation needs a graphical session -- a different thing to know,
because it tells them to stop retrying and either open Houdini or pick a tool that
works without one.

Kept separate from the pane-finding helpers because it is the *first* question, not
a detail of the search: with no UI at all there are no panes to look through.
"""

from __future__ import annotations

# Built-in
import contextlib
from collections.abc import Iterator

# Third-party
import hou

# Internal
from fxhoudinimcp_server.config import layout_if_enabled


def ui_available() -> bool:
    """Whether this Houdini has a UI at all.

    ``hou.isUIAvailable`` is itself missing in some headless builds, so the
    attribute check comes first.
    """
    try:
        return bool(hou.isUIAvailable())
    except AttributeError:
        return hasattr(hou, "ui")


def require_ui(operation: str, *, alternative: str = "") -> None:
    """Raise a readable error when *operation* needs a UI and there is none.

    Args:
        operation: What was being attempted, named as the caller would name it
            ("capture a viewport screenshot").
        alternative: Optional pointer to something that does work headlessly.
            Worth giving whenever one exists -- a refusal that names the way
            forward saves the round trip that a bare refusal costs.
    """
    if ui_available():
        return
    message = (
        f"Cannot {operation}: this Houdini session has no UI (hython/hbatch), "
        f"so there are no panes or viewports. It needs a graphical Houdini."
    )
    if alternative:
        message += f" {alternative}"
    raise hou.OperationFailed(message)


def panes():
    """``hou.ui.paneTabs()``, but explaining itself when there is no UI."""
    require_ui("look at Houdini's panes")
    return hou.ui.paneTabs()


# vieweroption -a: what the viewer draws of the objects you are not inside.
# The same switch as the viewport's Y hotkey; display flags are left alone.
OTHER_OBJECTS = {"hide": 0, "show": 1, "ghost": 2}


def set_other_objects(mode: str | None) -> str | None:
    """Set how every Scene Viewer draws objects other than the current one.

    Returns the mode applied, or None when there was nothing to do: no UI, no
    viewer, or *mode* None. Best effort by design, since isolating the viewer
    is a courtesy to the user and never a reason to fail the call it rides on.
    """
    if mode is None or not ui_available():
        return None
    if mode not in OTHER_OBJECTS:
        raise ValueError(f"other_objects must be one of {sorted(OTHER_OBJECTS)} or None")
    applied = None
    try:
        desktop = hou.ui.curDesktop().name()
        for tab in hou.ui.paneTabs():
            if tab.type() == hou.paneTabType.SceneViewer:
                hou.hscript(f"vieweroption -a {OTHER_OBJECTS[mode]} {desktop}.{tab.name()}.world")
                applied = mode
    except Exception:
        return applied
    return applied


def _in_lops(viewer) -> bool:
    """Whether *viewer* shows a LOP network (its cameras are prims) or not (nodes)."""
    return viewer.pwd().childTypeCategory() == hou.lopNodeTypeCategory()


def _restore_cameras(cameras: list) -> None:
    """Bind each recorded (viewer, view name, camera path) again where it changed.

    Only while the viewer is in the same kind of network as when it was
    recorded. Houdini keeps a camera per context itself; a USD prim path bound
    again in an object network matched nothing, and the view drew through it
    with the wrong aspect (22.0.368).
    """
    for tab, name, path, lops in cameras:
        with contextlib.suppress(Exception):
            if _in_lops(tab) != lops:
                continue
            viewport = next(v for v in tab.viewports() if v.name() == name)
            current = viewport.camera()
            now = current.path() if current is not None else viewport.cameraPath()
            if now != path:
                viewport.setCamera(hou.node(path) or path)


@contextlib.contextmanager
def keep_viewer_state() -> Iterator[None]:
    """Keep every view's camera and the node selection across a network editor move.

    The Scene Viewer follows the network editor, and a ``cd`` to another level
    unbinds each view's camera and selects that network's current node
    (measured on 22.0.429): set_current_network lost a camera set one call
    earlier, and set_node_flags left the object selected, so the next viewport
    capture drew it in the selection colour. Leaving a LOP network unbinds the
    camera once more on the next UI tick, after the call has returned, so the
    cameras are bound again then too.

    Best effort: nothing here raises, and a state the move left untouched is
    not written back.
    """
    cameras: list = []
    selected: list = []
    with contextlib.suppress(Exception):
        selected = list(hou.selectedNodes())
    with contextlib.suppress(Exception):
        for tab in hou.ui.paneTabs():
            if tab.type() != hou.paneTabType.SceneViewer:
                continue
            for viewport in tab.viewports():
                path = None
                with contextlib.suppress(Exception):
                    camera = viewport.camera()
                    # A USD camera prim is a path, not a node.
                    path = camera.path() if camera is not None else viewport.cameraPath()
                if path:
                    cameras.append((tab, viewport.name(), path, _in_lops(tab)))
    try:
        yield
    finally:
        _restore_cameras(cameras)
        if cameras:
            with contextlib.suppress(Exception):
                import hdefereval

                hdefereval.executeDeferred(lambda: _restore_cameras(cameras))
        with contextlib.suppress(Exception):
            now = sorted(node.path() for node in hou.selectedNodes())
            if now != sorted(node.path() for node in selected):
                # The editor follows a selected node to its network on the next
                # UI tick (22.0.368): selecting one outside the network the
                # editor moved to pulled it back, and set_current_network
                # answered for a network the editor had already left. Only the
                # nodes in that network are selected again.
                shown = {
                    tab.pwd().path()
                    for tab in hou.ui.paneTabs()
                    if tab.type() == hou.paneTabType.NetworkEditor
                }
                keep = [n for n in selected if not shown or n.parent().path() in shown]
                if now != sorted(node.path() for node in keep):
                    hou.clearAllSelected()
                    for node in keep:
                        node.setSelected(True, clear_all_selected=False)


def focus_network_editor(
    node: hou.Node,
    place_unpositioned: bool = True,
    other_objects: str | None = None,
) -> None:
    """Best-effort: lay out *node*'s network, then pan the network editor to *node*.

    The handlers that create or rewire a node end here. Callers that created
    nothing pass ``place_unpositioned=False``, so a call that only rewires or
    flips a flag never relocates a node the user parked at the origin.
    *other_objects* goes to set_other_objects once the editor has moved. The
    viewer's cameras and the selection survive the move (keep_viewer_state).
    """
    try:
        parent = node.parent()
        if parent is not None:
            layout_if_enabled(parent, place_unpositioned)
        with keep_viewer_state():
            for pane_tab in hou.ui.paneTabs():
                if pane_tab.type() == hou.paneTabType.NetworkEditor:
                    if parent is not None:
                        pane_tab.cd(parent.path())
                    pane_tab.setCurrentNode(node)
                    pane_tab.homeToSelection()
                    if other_objects is not None:
                        set_other_objects(other_objects)
                    return
    except Exception:
        pass  # Never let UI helpers break a tool call


@contextlib.contextmanager
def selection_hidden() -> Iterator[None]:
    """Draw no selection highlight for the block (a viewport capture), then put it back.

    A selected object is drawn with a selection outline, and a capture took it
    along whoever had selected it. The viewer has no switch for that highlight
    (neither HOM nor viewdisplay), so the node selection is cleared for the
    block. What was selected is put back as it was: the editor already shows
    it (it follows a selected node into its network), so it does not move.
    """
    selected: list = []
    with contextlib.suppress(Exception):
        # clearAllSelected() also clears boxes, notes, dots and hidden nodes.
        selected = list(hou.selectedItems(include_hidden=True))
        if selected:
            hou.clearAllSelected()
    try:
        yield
    finally:
        if selected:
            with contextlib.suppress(Exception):
                for n in selected:
                    n.setSelected(True, clear_all_selected=False)
