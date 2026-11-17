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
import contextlib
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


@pytest.fixture(autouse=True)
def _paths_as_written(monkeypatch):
    # The shared hou mock would expand a path into a MagicMock, which
    # os.makedirs then creates as a directory named after the mock.
    for name in ("rendering_handlers", "viewport_handlers"):
        module = sys.modules.get("fxhoudinimcp_server.handlers." + name)
        if module is not None:
            monkeypatch.setattr(module.hou.text, "expandString", lambda s: s)


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
        if self._path.rsplit("/", 1)[-1].startswith("dopnet"):
            return "Dop"
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
        viewer.name.return_value = "panetab1"
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
    monkeypatch.setattr(hou, "dopNodeTypeCategory", lambda: "Dop", raising=False)
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


class TestTheViewerStaysOutOfDops:
    """The Scene Viewer followed the editor into a DOP network and drew a DOP view.

    A node created in a POP network took the editor there, and the viewer with
    it: the next capture showed the collider as solid grey geometry and the
    particles as points instead of the object's trails (22.0.429).
    """

    @staticmethod
    def _pop(houdini):
        dopnet = _FakeNode("/obj/g/dopnet1", parent=houdini.known["/obj/g"])
        return _FakeNode("/obj/g/dopnet1/popsource1", parent=dopnet)

    def test_focusing_a_node_in_a_dop_network_leaves_the_editor_where_it_was(self, houdini):
        houdini.pwd = "/obj/g"
        nodes._focus_network_editor(self._pop(houdini))
        assert houdini.pwd == "/obj/g"
        assert _cameras(houdini) == _BOUND

    def test_a_viewer_already_in_a_dop_network_is_left_there(self, houdini):
        houdini.pwd = "/obj/g/dopnet1"
        nodes._focus_network_editor(self._pop(houdini))
        assert houdini.pwd == "/obj/g/dopnet1"

    def test_a_sop_network_is_still_shown(self, houdini):
        houdini.pwd = "/obj"
        nodes._focus_network_editor(houdini.known["/obj/g/sphere1"])
        assert houdini.pwd == "/obj/g"

    def test_the_editor_captures_put_it_back_after_the_shot(self):
        """Both editor captures move it to the node's network; the shot runs inside the guard."""
        for name, function in (
            ("viewport_handlers.py", "capture_network_editor"),
            ("rendering_handlers.py", "render_node_network"),
        ):
            tree = ast.parse((_SERVER_DIR / "handlers" / name).read_text(encoding="utf-8"))
            body = next(
                n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == function
            )
            guarded = [
                n
                for n in ast.walk(body)
                if isinstance(n, ast.With)
                and any("viewer_stays_out_of_dops" in ast.unparse(i.context_expr) for i in n.items)
            ]
            assert guarded, f"{function}: no viewer_stays_out_of_dops()"
            inside = ast.unparse(guarded[0])
            assert ".cd(" in inside and "_capture_pane_tab_qt(" in inside, function


class TestCapturesNameTheViewersNetwork:
    """A capture now says which network the viewer drew, and when that is a DOP view."""

    def test_a_dop_view_is_named_with_the_way_out(self, houdini):
        viewer = MagicMock()
        viewer.pwd.return_value = _FakeNode("/obj/g/dopnet1", parent=houdini.known["/obj/g"])
        context = ui.viewer_context(viewer)
        assert context["viewer_network"] == "/obj/g/dopnet1"
        assert "DOP network /obj/g/dopnet1" in context["viewer_note"]
        assert "(/obj/g)" in context["viewer_note"]

    def test_a_sop_view_carries_only_its_network(self, houdini):
        viewer = MagicMock()
        viewer.pwd.return_value = _FakeNode("/obj/g")
        assert ui.viewer_context(viewer) == {"viewer_network": "/obj/g"}

    def test_capture_screenshot_says_so_in_its_reply(self, houdini, monkeypatch, tmp_path):
        import fxhoudinimcp_server.handlers.rendering_handlers as rendering

        houdini.pwd = "/obj/g/dopnet1"
        monkeypatch.setattr(viewport, "_find_scene_viewer", lambda: houdini.panes[0])
        monkeypatch.setattr(rendering, "_find_flipbook_output", lambda path, frame: path)
        result = viewport.capture_screenshot(str(tmp_path / "shot.png"))
        assert result["viewer_network"] == "/obj/g/dopnet1"
        assert "DOP network" in result["viewer_note"]

    def test_every_viewport_capture_reply_carries_it(self):
        for name, function in (
            ("viewport_handlers.py", "capture_screenshot"),
            ("rendering_handlers.py", "render_viewport"),
            ("rendering_handlers.py", "render_quad_view"),
        ):
            tree = ast.parse((_SERVER_DIR / "handlers" / name).read_text(encoding="utf-8"))
            body = next(
                n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == function
            )
            assert "viewer_context(" in ast.unparse(body), function


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


class TestCurrentDopNetwork:
    """set_current_network on a DOP network makes it the current one.

    Houdini does so when the editor enters a DOP network (measured on
    22.0.429), but neither the reply nor the docstring said it, and a session
    set it through execute_python after model_popnet, which does not.
    """

    @pytest.fixture
    def editor(self, monkeypatch):
        dop = object()
        node = MagicMock()
        node.isNetwork.return_value = True
        node.path.return_value = "/obj/project/popnet"
        current = {"net": None}
        pane = MagicMock()
        pane.type.return_value = "NetworkEditor"
        pane.pwd.return_value = node
        monkeypatch.setattr(viewport, "require_ui", lambda *a, **k: None)
        monkeypatch.setattr(viewport, "keep_viewer_state", contextlib.nullcontext)
        monkeypatch.setattr(viewport, "set_other_objects", lambda mode: mode)
        monkeypatch.setattr(viewport.hou, "node", lambda path: node, raising=False)
        monkeypatch.setattr(
            viewport.hou,
            "paneTabType",
            SimpleNamespace(NetworkEditor="NetworkEditor"),
            raising=False,
        )
        monkeypatch.setattr(
            viewport.hou, "ui", SimpleNamespace(paneTabs=lambda: [pane]), raising=False
        )
        monkeypatch.setattr(viewport.hou, "dopNodeTypeCategory", lambda: dop, raising=False)
        monkeypatch.setattr(
            viewport.hou, "setCurrentDopNet", lambda n: current.update(net=n), raising=False
        )
        monkeypatch.setattr(
            viewport.hou,
            "currentDopNet",
            lambda: SimpleNamespace(path=lambda: "/obj/project/popnet"),
            raising=False,
        )
        return node, dop, current

    def test_a_dop_network_is_made_current_and_named(self, editor):
        node, dop, current = editor
        node.childTypeCategory.return_value = dop
        reply = viewport.set_current_network("/obj/project/popnet", other_objects=None)
        assert current["net"] is node
        assert reply["current_dop_network"] == "/obj/project/popnet"

    def test_any_other_network_leaves_it(self, editor):
        node, _, current = editor
        node.childTypeCategory.return_value = object()
        reply = viewport.set_current_network("/obj/geo1", other_objects=None)
        assert current["net"] is None
        assert "current_dop_network" not in reply


# A Visible Objects pattern is saved with the hip. One left at another object
# (/obj/project_04_fern) drew the object set_current_network went into not at
# all, and every screenshot of it came out black (22.0.466).


@pytest.mark.parametrize(
    ("pattern", "hides"),
    [
        ("*", False),
        ("", False),
        ("/obj/project_04_fern", True),
        ("/obj/project_05_magic_smoke", False),
        ("project_0*", False),
        ("* ^/obj/project_05_magic_smoke", True),
        ("^project_05* /obj/project_05_magic_smoke", False),
        ("@shown", False),
        ("/obj/project_04_fern @shown", False),
        # Houdini reads commas as separators too (22.0.368).
        ("nothing,project_05_magic_smoke", False),
        ("project_04_fern, project_06", True),
        ("{project_04_fern,project_05_magic_smoke}", False),
    ],
)
def test_pattern_hides(pattern, hides):
    assert ui.pattern_hides(pattern, "/obj/project_05_magic_smoke") is hides


class _Settings:
    def __init__(self, pattern):
        self.pattern = pattern

    def visibleObjects(self):
        return self.pattern

    def setVisibleObjects(self, pattern):
        self.pattern = pattern


class _Viewport:
    def __init__(self, name, pattern):
        self._name = name
        self._settings = _Settings(pattern)

    def name(self):
        return self._name

    def settings(self):
        return self._settings


def _object(path, obj_category):
    node = MagicMock()
    node.path.return_value = path
    node.type.return_value.category.return_value = obj_category
    node.childTypeCategory.return_value = "sop"
    return node


@pytest.fixture
def viewer(monkeypatch):
    hou = ui.hou
    obj_category = object()
    monkeypatch.setattr(hou, "objNodeTypeCategory", lambda: obj_category)
    obj = _object("/obj/project_05_magic_smoke", obj_category)
    inside = MagicMock()
    inside.type.return_value.category.return_value = "sop"
    inside.parent.return_value = obj
    viewports = [_Viewport("top1", "*"), _Viewport("persp1", "/obj/project_04_fern")]
    tab = MagicMock()
    tab.name.return_value = "panetab1"
    tab.type.return_value = hou.paneTabType.SceneViewer
    tab.viewports.return_value = viewports
    tab.curViewport.return_value = viewports[1]
    tab.pwd.return_value = obj
    monkeypatch.setattr(hou.ui, "paneTabs", lambda: [tab])
    return SimpleNamespace(tab=tab, obj=obj, inside=inside, viewports=viewports)


def test_set_current_network_shows_the_object_again(viewer):
    reset = ui.show_viewed_object(viewer.inside)
    assert reset == [
        {
            "pane": "panetab1",
            "viewport": "persp1",
            "visible_objects": "/obj/project_04_fern",
            "object": "/obj/project_05_magic_smoke",
        }
    ]
    assert [v.settings().visibleObjects() for v in viewer.viewports] == ["*", "*"]


def test_capture_names_a_pattern_that_hides_the_object(viewer):
    context = ui.viewer_context(viewer.tab)
    assert "/obj/project_04_fern" in context["visible_objects_note"]
    viewer.viewports[1].settings().setVisibleObjects("*")
    assert "visible_objects_note" not in ui.viewer_context(viewer.tab)


def test_nothing_is_reset_at_obj_level(viewer, monkeypatch):
    manager = MagicMock()
    manager.type.return_value.category.return_value = ui.hou.objNodeTypeCategory()
    manager.childTypeCategory.return_value = ui.hou.objNodeTypeCategory()
    assert ui.show_viewed_object(manager) == []
    assert viewer.viewports[1].settings().visibleObjects() == "/obj/project_04_fern"


# set_current_network on a SOP (not a network): NetworkEditor.cd() did nothing
# and the reply said success. The node is made current in its own network, and
# an editor that did not get there is an error (22.0.466).


@pytest.fixture
def sop_editor(monkeypatch):
    hou = viewport.hou
    geo = MagicMock()
    geo.path.return_value = "/obj/acc_vis"
    geo.isNetwork.return_value = True
    box = MagicMock()
    box.path.return_value = "/obj/acc_vis/box1"
    box.isNetwork.return_value = False
    box.parent.return_value = geo
    nodes = {"/obj/acc_vis": geo, "/obj/acc_vis/box1": box}
    state = {"pwd": MagicMock(path=lambda: "/obj/fern/popnet"), "current": None, "moves": True}
    pane = MagicMock()
    pane.type.return_value = "NetworkEditor"
    pane.name.return_value = "panetab7"
    pane.pwd.side_effect = lambda: state["pwd"]

    def cd(path):
        # As measured: cd() to a SOP leaves the editor where it is.
        if state["moves"] and nodes[path].isNetwork():
            state["pwd"] = nodes[path]

    pane.cd.side_effect = cd
    pane.setCurrentNode.side_effect = lambda n: state.update(current=n)
    monkeypatch.setattr(viewport, "require_ui", lambda *a, **k: None)
    monkeypatch.setattr(viewport, "keep_viewer_state", contextlib.nullcontext)
    monkeypatch.setattr(viewport, "set_other_objects", lambda mode: mode)
    monkeypatch.setattr(viewport, "show_viewed_object", lambda network: [])
    monkeypatch.setattr(hou, "node", lambda path: nodes.get(path))
    monkeypatch.setattr(hou, "paneTabType", SimpleNamespace(NetworkEditor="NetworkEditor"))
    monkeypatch.setattr(hou, "ui", SimpleNamespace(paneTabs=lambda: [pane]))
    monkeypatch.setattr(hou, "dopNodeTypeCategory", lambda: object())
    return SimpleNamespace(state=state, geo=geo, box=box)


def test_a_sop_is_made_current_in_its_network(sop_editor):
    reply = viewport.set_current_network("/obj/acc_vis/box1")
    assert sop_editor.state["pwd"] is sop_editor.geo
    assert sop_editor.state["current"] is sop_editor.box
    assert reply["entered"] == "/obj/acc_vis" and reply["current_node"] == "/obj/acc_vis/box1"


def test_a_network_is_entered_as_before(sop_editor):
    reply = viewport.set_current_network("/obj/acc_vis")
    assert sop_editor.state["pwd"] is sop_editor.geo
    assert "entered" not in reply and "current_node" not in reply


def test_an_editor_that_did_not_move_is_an_error(sop_editor):
    sop_editor.state["moves"] = False
    with pytest.raises(RuntimeError, match="/obj/fern/popnet"):
        viewport.set_current_network("/obj/acc_vis")


def test_the_reset_is_named_in_the_reply(sop_editor, monkeypatch):
    entry = {
        "pane": "panetab1",
        "viewport": "persp1",
        "visible_objects": "/obj/project_04_fern",
        "object": "/obj/acc_vis",
    }
    asked = []
    monkeypatch.setattr(
        viewport, "show_viewed_object", lambda network: asked.append(network) or [entry]
    )
    reply = viewport.set_current_network("/obj/acc_vis")
    assert asked == [sop_editor.geo] and reply["visible_objects_reset"] == [entry]
    asked.clear()
    reply = viewport.set_current_network("/obj/acc_vis", other_objects=None)
    assert asked == [] and "visible_objects_reset" not in reply
