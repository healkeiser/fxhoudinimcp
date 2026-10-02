"""Moving the network editor no longer unbinds the viewport camera or selects nodes.

The Scene Viewer follows the network editor. On Houdini 22.0.429 a ``cd`` to
another level unbound each view's camera and selected that network's current
node: set_current_network lost the camera set one call earlier, and
set_node_flags left the object selected, so the next capture drew it in the
selection colour. Leaving a LOP network unbinds the camera once more on the
next UI tick, after the call has returned.

Every move of the editor now runs inside ui.keep_viewer_state(), and the eight
per-module copies of _focus_network_editor are one ui.focus_network_editor.

hou is mocked here; the live check ran on Houdini 22.0.429.
"""

from __future__ import annotations

# Built-in
import ast
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

# Third-party
import pytest

sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Internal
import fxhoudinimcp_server.handlers.node_handlers as nodes  # noqa: E402
import fxhoudinimcp_server.handlers.viewport_handlers as viewport  # noqa: E402
import fxhoudinimcp_server.handlers.workflow_handlers as workflow  # noqa: E402
import fxhoudinimcp_server.ui as ui  # noqa: E402

_SERVER_DIR = Path(__file__).resolve().parents[1] / "houdini" / "scripts" / "python"
_SERVER_DIR = _SERVER_DIR / "fxhoudinimcp_server"


class _FakeNode:
    def __init__(self, path, parent=None, current=None):
        self._path, self._parent, self.current = path, parent, current

    def path(self):
        return self._path

    def parent(self):
        return self._parent

    def childTypeCategory(self):  # noqa: N802
        return "Lop" if self._path.startswith("/stage") else "Object"


class _FakeView:
    """A view bound to a camera node, a USD camera prim path, or nothing."""

    def __init__(self, name, camera=None, prim=""):
        self._name, self._camera, self._prim = name, camera, prim
        self.bound = []

    def name(self):
        return self._name

    def camera(self):
        return self._camera

    def cameraPath(self):
        return self._camera.path() if self._camera is not None else self._prim

    def setCamera(self, camera):
        self.bound.append(camera)
        if isinstance(camera, str):
            self._camera, self._prim = None, camera
        else:
            self._camera, self._prim = camera, ""

    def unbind(self):
        self._camera, self._prim = None, ""


class _Houdini:
    """Panes, selection and nodes, with a network editor that moves like Houdini's."""

    def __init__(self, views, known, selection):
        self.views, self.known, self.selection = views, known, selection
        self.deferred = []
        viewer = MagicMock()
        viewer.type.return_value = "SceneViewer"
        viewer.viewports.return_value = views
        viewer.pwd.side_effect = lambda: _FakeNode(self.pwd)
        self.editor = MagicMock()
        self.editor.type.return_value = "NetworkEditor"
        self.editor.cd.side_effect = self._cd
        self.editor.setCurrentNode.side_effect = self._make_current
        self.editor.pwd.side_effect = lambda: _FakeNode(self.pwd)
        self.pwd = "/obj"
        self.panes = [viewer, self.editor]

    def _cd(self, path):
        # What 22.0.429 does: every view drops its camera, and the network's
        # current node becomes the selection.
        self.pwd = path
        for view in self.views:
            view.unbind()
        network = self.known.get(path)
        if network is not None and network.current is not None:
            self.selection[:] = [network.current]

    def _make_current(self, node):
        self.selection[:] = [node]


@pytest.fixture
def houdini(monkeypatch):
    cam = _FakeNode("/obj/cam1")
    g = _FakeNode("/obj/g", parent=_FakeNode("/obj"))
    box = _FakeNode("/obj/geo1", parent=_FakeNode("/obj"))
    sphere = _FakeNode("/obj/g/sphere1", parent=g)
    picked = _FakeNode("/obj/g/box1", parent=g)
    g.current = sphere
    views = [
        _FakeView("persp1", camera=cam),
        _FakeView("top1"),
        _FakeView("front1", prim="/cameras/shot"),
    ]
    known = {node.path(): node for node in (cam, box, sphere, picked, g)}
    state = _Houdini(views, known, [picked])
    hou = ui.hou
    monkeypatch.setattr(hou.paneTabType, "SceneViewer", "SceneViewer", raising=False)
    monkeypatch.setattr(hou.paneTabType, "NetworkEditor", "NetworkEditor", raising=False)
    monkeypatch.setattr(hou.ui, "paneTabs", lambda: state.panes, raising=False)
    # Nodes only: boxes, notes and dots are in selectedItems().
    monkeypatch.setattr(
        hou,
        "selectedNodes",
        lambda: [item for item in state.selection if item in known.values()],
        raising=False,
    )
    monkeypatch.setattr(hou, "clearAllSelected", state.selection.clear, raising=False)
    monkeypatch.setattr(
        hou, "selectedItems", lambda include_hidden=False: list(state.selection), raising=False
    )
    monkeypatch.setattr(hou, "node", known.get, raising=False)
    monkeypatch.setattr(hou, "isUIAvailable", lambda: True, raising=False)
    monkeypatch.setattr(hou, "lopNodeTypeCategory", lambda: "Lop", raising=False)
    monkeypatch.setattr(sys.modules["hdefereval"], "executeDeferred", state.deferred.append)
    monkeypatch.setattr(ui, "layout_if_enabled", lambda *a, **k: None)
    for node in known.values():
        node.setSelected = lambda on, clear_all_selected=False, _n=node: (
            state.selection.append(_n) if on else None
        )
    return state


def _cameras(state):
    return {view.name(): view.cameraPath() for view in state.views}


_BOUND = {"persp1": "/obj/cam1", "top1": "", "front1": "/cameras/shot"}


class TestKeepViewerState:
    def test_every_view_gets_its_camera_back(self, houdini):
        with ui.keep_viewer_state():
            houdini.editor.cd("/obj/g")
        assert _cameras(houdini) == _BOUND
        # A node camera goes back as the node, a USD prim as its path.
        assert houdini.views[0].camera().path() == "/obj/cam1"
        assert houdini.views[2].bound == ["/cameras/shot"]

    def test_a_view_that_had_no_camera_is_left_unbound(self, houdini):
        with ui.keep_viewer_state():
            houdini.editor.cd("/obj/g")
        assert houdini.views[1].bound == []

    def test_the_selection_the_move_made_is_undone(self, houdini):
        with ui.keep_viewer_state():
            houdini.editor.cd("/obj/g")
        assert [node.path() for node in houdini.selection] == ["/obj/g/box1"]

    def test_a_camera_is_not_carried_into_another_kind_of_network(self, houdini):
        # Houdini keeps a camera per context itself. A USD prim path bound
        # again in /obj matched nothing: the view drew through it with the
        # wrong aspect (22.0.368).
        houdini.pwd = "/stage"
        with ui.keep_viewer_state():
            houdini.editor.cd("/obj/g")
        for run_later in houdini.deferred:
            run_later()
        assert all(view.bound == [] for view in houdini.views)

    def test_a_selection_outside_the_new_network_is_not_selected_again(self, houdini):
        # Houdini's editor follows a selected node to its network on the next
        # UI tick: re-selecting /obj/geo1 sent the editor back from /obj/g to
        # /obj after set_current_network had answered /obj/g (22.0.368).
        houdini.selection[:] = [houdini.known["/obj/geo1"]]
        with ui.keep_viewer_state():
            houdini.editor.cd("/obj/g")
        assert houdini.selection == []
        assert _cameras(houdini) == _BOUND

    def test_an_undisturbed_viewer_is_not_written_to(self, houdini, monkeypatch):
        cleared = []
        monkeypatch.setattr(ui.hou, "clearAllSelected", lambda: cleared.append(True))
        with ui.keep_viewer_state():
            pass
        assert all(view.bound == [] for view in houdini.views)
        assert cleared == []

    def test_a_camera_dropped_on_the_next_ui_tick_comes_back_then(self, houdini):
        # Leaving a LOP network unbinds the camera after the call has returned.
        with ui.keep_viewer_state():
            houdini.editor.cd("/obj/g")
        for view in houdini.views:
            view.unbind()  # the next UI tick
        assert len(houdini.deferred) == 1
        houdini.deferred[0]()
        assert _cameras(houdini) == _BOUND

    def test_nothing_is_deferred_when_no_view_had_a_camera(self, houdini):
        for view in houdini.views:
            view.unbind()
        with ui.keep_viewer_state():
            houdini.editor.cd("/obj/g")
        assert houdini.deferred == []

    def test_state_comes_back_when_the_block_raises(self, houdini):
        with pytest.raises(RuntimeError), ui.keep_viewer_state():
            houdini.editor.cd("/obj/g")
            raise RuntimeError("the move failed half way")
        assert _cameras(houdini) == _BOUND
        assert [node.path() for node in houdini.selection] == ["/obj/g/box1"]


class TestNavigationKeepsTheViewer:
    def test_set_current_network_keeps_the_camera_and_the_selection(self, houdini):
        viewport.set_current_network("/obj/g", other_objects=None)
        houdini.editor.cd.assert_called_once_with("/obj/g")
        assert _cameras(houdini) == _BOUND
        assert [node.path() for node in houdini.selection] == ["/obj/g/box1"]

    def test_focusing_a_node_keeps_the_camera_and_the_selection(self, houdini):
        # set_node_flags, connect_nodes and create_node all end here.
        sphere = houdini.known["/obj/g/sphere1"]
        sphere._parent = houdini.known["/obj/g"]
        nodes._focus_network_editor(sphere, place_unpositioned=False)
        houdini.editor.setCurrentNode.assert_called_once_with(sphere)
        assert _cameras(houdini) == _BOUND
        assert [node.path() for node in houdini.selection] == ["/obj/g/box1"]

    def test_the_sim_setups_still_hide_the_other_objects(self, houdini, monkeypatch):
        hidden = []
        monkeypatch.setattr(ui, "set_other_objects", hidden.append)
        workflow._focus_network_editor(houdini.known["/obj/g"])
        assert hidden == ["hide"]

    def test_the_other_handlers_leave_the_other_objects_alone(self, houdini, monkeypatch):
        hidden = []
        monkeypatch.setattr(ui, "set_other_objects", hidden.append)
        nodes._focus_network_editor(houdini.known["/obj/g"])
        assert hidden == []

    def test_focusing_never_breaks_the_call(self, houdini, monkeypatch):
        def no_panes():
            raise RuntimeError("no UI")

        monkeypatch.setattr(ui.hou.ui, "paneTabs", no_panes)
        nodes._focus_network_editor(houdini.known["/obj/g"])  # must not raise


class TestEveryEditorMoveKeepsTheViewer:
    def test_each_cd_runs_inside_keep_viewer_state(self):
        """A network editor cd outside keep_viewer_state drops the viewer's camera.

        Eight handler modules each carried their own copy of the pan before;
        a ninth copy, or a new verb that navigates, would bring the bug back.
        """
        offenders = []
        files = [*sorted((_SERVER_DIR / "handlers").glob("*.py")), _SERVER_DIR / "ui.py"]
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            kept = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.With) and any(
                    isinstance(item.context_expr, ast.Call)
                    and isinstance(item.context_expr.func, ast.Name)
                    and item.context_expr.func.id == "keep_viewer_state"
                    for item in node.items
                ):
                    kept.update(id(inner) for inner in ast.walk(node))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "cd"
                    and id(node) not in kept
                ):
                    offenders.append(f"{path.name}:{node.lineno}")
        assert offenders == []


class TestCapturesDrawNoSelection:
    """A selected object was drawn with its outline in every viewport capture."""

    def test_the_selection_is_empty_during_the_block_and_back_after(self, houdini):
        during = []
        with ui.selection_hidden():
            during.append(list(houdini.selection))
        assert during == [[]]
        assert [node.path() for node in houdini.selection] == ["/obj/g/box1"]

    def test_it_comes_back_when_the_capture_raises(self, houdini):
        with pytest.raises(RuntimeError), ui.selection_hidden():
            raise RuntimeError("flipbook failed")
        assert [node.path() for node in houdini.selection] == ["/obj/g/box1"]

    def test_a_selected_network_box_comes_back_too(self, houdini):
        box = SimpleNamespace(path=lambda: "/obj/g/__netbox1")
        box.setSelected = lambda on, clear_all_selected=False: (
            houdini.selection.append(box) if on else None
        )
        houdini.selection.append(box)
        with ui.selection_hidden():
            assert houdini.selection == []
        assert [item.path() for item in houdini.selection] == ["/obj/g/box1", "/obj/g/__netbox1"]

    def test_nothing_is_touched_without_a_selection(self, houdini, monkeypatch):
        houdini.selection.clear()
        cleared = []
        monkeypatch.setattr(ui.hou, "clearAllSelected", lambda: cleared.append(True))
        with ui.selection_hidden():
            pass
        assert cleared == []

    def test_every_viewport_flipbook_runs_inside_it(self):
        found = []
        for path in sorted((_SERVER_DIR / "handlers").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            hidden = {
                id(call)
                for block in ast.walk(tree)
                if isinstance(block, ast.With)
                and any("selection_hidden" in ast.unparse(i.context_expr) for i in block.items)
                for call in ast.walk(block)
                if isinstance(call, ast.Call)
            }
            for call in ast.walk(tree):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "flipbook"
                ):
                    found.append((path.name, call.lineno, id(call) in hidden))
        assert found, "no flipbook call found -- the guard lost its target"
        bare = [(name, line) for name, line, inside in found if not inside]
        assert bare == [], f"flipbook() outside ui.selection_hidden(): {bare}"
