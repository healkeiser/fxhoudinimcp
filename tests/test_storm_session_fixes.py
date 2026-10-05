"""Houdini-free checks for the fixes a live storm-shot session asked for.

Each test pins one behaviour the session tripped over: a light colour
rejected by batch set_parameters, a menu typo that rolled back a whole
build, a cache frame range silently overridden by $FSTART, and a VOP
input that had to be wired by guessed index.
"""

from __future__ import annotations

# Built-in
import os
import sys
from unittest.mock import AsyncMock, MagicMock

# Third-party
import pytest

sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

from fxhoudinimcp_server.handlers import (  # noqa: E402
    cache_handlers,
    graph_handlers,
    node_handlers,
    parameter_handlers,
)


def _tuple_node(name: str, size: int) -> MagicMock:
    node = MagicMock()
    node.path.return_value = "/stage/moon"
    components = [MagicMock(**{"eval.return_value": 0.5}) for _ in range(size)]
    parm_tuple = MagicMock()
    parm_tuple.__len__.return_value = size
    parm_tuple.__iter__.return_value = iter(components)
    node.parmTuple.side_effect = lambda n: parm_tuple if n == name else None
    node.parm.side_effect = lambda n: None if n == name else MagicMock()
    node.parms.return_value = []
    return node, parm_tuple


def test_batch_set_parameters_sets_a_colour_tuple(monkeypatch):
    node, parm_tuple = _tuple_node("xn__inputscolor_zta", 3)
    monkeypatch.setattr(parameter_handlers, "_resolve_node", lambda _p: node)
    # _serialize_value asks isinstance() against hou.Vector3, which is a mock here.
    monkeypatch.setattr(parameter_handlers, "_serialize_value", lambda v: v)

    out = parameter_handlers._set_parameters("/stage/moon", {"xn__inputscolor_zta": [1, 0.8, 0.6]})

    parm_tuple.set.assert_called_once_with([1, 0.8, 0.6])
    assert out["errors"] == []
    assert out["set"][0]["parm_name"] == "xn__inputscolor_zta"


def test_batch_set_parameters_reports_a_component_count_mismatch(monkeypatch):
    node, parm_tuple = _tuple_node("xn__inputscolor_zta", 3)
    monkeypatch.setattr(parameter_handlers, "_resolve_node", lambda _p: node)

    out = parameter_handlers._set_parameters("/stage/moon", {"xn__inputscolor_zta": [1, 0.8]})

    parm_tuple.set.assert_not_called()
    assert "3 components, got 2" in out["errors"][0]["error"]


@pytest.mark.parametrize(
    ("value", "fragment"),
    [
        ("computevelocity", "is not a menu item"),
        (7, "out of range"),
    ],
)
def test_menu_error_names_the_problem(value, fragment):
    tokens = ["preserve", "mesh", "poly", "velocity"]
    message = graph_handlers._menu_error("result", value, tokens)
    assert fragment in message
    if isinstance(value, str):
        assert "velocity" in message  # did-you-mean


@pytest.mark.parametrize("value", ["velocity", 2, True])
def test_menu_error_accepts_valid_values(value):
    assert (
        graph_handlers._menu_error("result", value, ["preserve", "mesh", "poly", "velocity"])
        is None
    )


def test_frame_parm_drops_the_expression_keyframe_before_setting():
    parm = MagicMock()
    parm.keyframes.return_value = [object()]
    node = MagicMock()
    node.parm.return_value = parm

    cache_handlers._set_frame_parm(node, "f1", 10)

    parm.deleteAllKeyframes.assert_called_once()
    parm.set.assert_called_once_with(10)


def test_frame_parm_leaves_an_unkeyed_parm_alone():
    parm = MagicMock()
    parm.keyframes.return_value = []
    node = MagicMock()
    node.parm.return_value = parm

    cache_handlers._set_frame_parm(node, "f2", 100)

    parm.deleteAllKeyframes.assert_not_called()
    parm.set.assert_called_once_with(100)


def test_input_name_resolves_by_name_then_label():
    dest = MagicMock()
    dest.inputNames.return_value = ["base_color", "specular_roughness"]
    dest.inputLabels.return_value = ["Base Color", "Specular Roughness"]

    assert node_handlers._resolve_input_index(dest, 0, "specular_roughness") == 1
    assert node_handlers._resolve_input_index(dest, 0, "Specular Roughness") == 1
    assert node_handlers._resolve_input_index(dest, 3, None) == 3


def test_input_name_that_does_not_exist_suggests_one():
    dest = MagicMock()
    dest.path.return_value = "/stage/materials/ocean_water"
    dest.inputNames.return_value = ["base_color", "specular_roughness"]
    dest.inputLabels.return_value = ["Base Color", "Specular Roughness"]

    with pytest.raises(ValueError, match="base_color"):
        node_handlers._resolve_input_index(dest, 0, "basecolor")


def test_background_write_presses_the_top_cook_button_and_returns_launched(monkeypatch):
    """File Cache's real background path is the cookoutputnode button, not the toggle."""
    node = MagicMock()
    parms = {"cookoutputnode": MagicMock(), "execute": MagicMock()}
    node.parm.side_effect = parms.get
    monkeypatch.setattr(cache_handlers, "_get_node", lambda _p: node)
    monkeypatch.setattr(cache_handlers, "reported_outputs", lambda _n: [])
    hip = cache_handlers.hou.hipFile
    hip.isNewFile.return_value = False

    out = cache_handlers._write_cache(node_path="/obj/G/cache", background=True)

    hip.save.assert_called_once()
    parms["cookoutputnode"].pressButton.assert_called_once()
    assert out["status"] == "launched" and out["success"] is True and out["wrote_files"] is False


def test_background_write_refuses_a_node_without_the_button(monkeypatch):
    node = MagicMock()
    node.parm.return_value = None
    monkeypatch.setattr(cache_handlers, "_get_node", lambda _p: node)

    with pytest.raises(ValueError, match="cookoutputnode"):
        cache_handlers._write_cache(node_path="/obj/G/box", background=True)


@pytest.mark.parametrize(
    ("at_1", "at_2", "expected"),
    [
        (
            "/geo/a.cache/v1/a.cache_v1.0001.bgeo.sc",
            "/geo/a.cache/v1/a.cache_v1.0002.bgeo.sc",
            "/geo/a.cache/v1/a.cache_v1.*.bgeo.sc",
        ),
        ("/geo/a.1.bgeo", "/geo/a.2.bgeo", "/geo/a.*.bgeo"),
        ("/geo/static.bgeo.sc", "/geo/static.bgeo.sc", "/geo/static.bgeo.sc"),
    ],
)
def test_frame_glob_comes_from_evaluated_paths(at_1, at_2, expected, monkeypatch):
    # The helper moves the playbar and evaluates, so the fake hou has to
    # remember the frame it was set to.
    state = {"frame": 7.0}
    hou = cache_handlers.hou
    monkeypatch.setattr(hou, "frame", lambda: state["frame"])
    monkeypatch.setattr(hou, "setFrame", lambda f: state.__setitem__("frame", f))
    parm = MagicMock()
    parm.eval.side_effect = lambda: at_1 if state["frame"] == 1 else at_2
    node = MagicMock()
    node.parm.side_effect = lambda n: parm if n == "sopoutput" else None

    assert cache_handlers._frame_glob(node) == expected
    assert state["frame"] == 7.0  # playbar restored


def test_multiparm_instance_names_validate_against_the_template():
    """usept0 / pt0x on an Add SOP are real once the count is set; a zero-instance probe never has them."""
    import re

    patterns = [
        re.compile(r"^usept\d+[xyzwrgba]?$"),
        re.compile(r"^pt\d+[xyzwrgba]?$"),
        re.compile(r"^source_volume\d+[xyzwrgba]?$"),
    ]
    assert graph_handlers._is_instance_parm("usept0", patterns)
    assert graph_handlers._is_instance_parm("pt12x", patterns)
    assert graph_handlers._is_instance_parm("source_volume3", patterns)
    assert not graph_handlers._is_instance_parm("pt", patterns)
    assert not graph_handlers._is_instance_parm("points", patterns)
    assert not graph_handlers._is_instance_parm("pt0xy", patterns)


# ---------------------------------------------------------------- second storm session


def test_interactive_shelf_tools_are_named():
    from fxhoudinimcp_server.handlers import shelf_handlers

    script = "import toolutils\nsel = toolutils.sceneViewer().selectGeometry(prompt='pick')\n"
    assert shelf_handlers.interactive_markers(script) == ["selectGeometry(", "sceneViewer().select"]
    assert shelf_handlers.interactive_markers("hou.node('/obj').createNode('geo')") == []


def test_license_error_is_singled_out():
    from fxhoudinimcp_server import outputs

    errors = ["Unable to open camera", "No licenses could be found to run this application."]
    assert outputs.license_error(errors) == errors[1]
    assert outputs.license_error(["bad path"]) is None


def test_write_cache_stays_in_the_foreground_by_default(monkeypatch):
    monkeypatch.setattr(cache_handlers.hou.hipFile, "isNewFile", lambda: False)
    parms = {"cookoutputnode": MagicMock(), "execute": MagicMock(), "trange": None}
    node = MagicMock()
    node.parm.side_effect = parms.get
    monkeypatch.setattr(cache_handlers, "_get_node", lambda p: node)
    monkeypatch.setattr(cache_handlers, "_set_frame_parm", lambda *a: None)
    monkeypatch.setattr(cache_handlers, "reported_outputs", lambda n: [])
    monkeypatch.setattr(
        cache_handlers,
        "write_verdict",
        lambda *a, **k: {"success": True, "wrote_files": True, "message": "ok", "errors": []},
    )

    result = cache_handlers._write_cache(node_path="/obj/g/c", frame_range=[1, 80])
    assert result["background"] is False
    parms["execute"].pressButton.assert_called_once()
    parms["cookoutputnode"].pressButton.assert_not_called()


def test_caches_and_renders_have_no_deadline(monkeypatch):
    from fxhoudinimcp_server import dispatcher

    monkeypatch.delenv("FXHOUDINIMCP_TIMEOUT", raising=False)
    monkeypatch.delenv("FXHOUDINIMCP_TIMEOUT_CACHE_WRITE_CACHE", raising=False)
    assert dispatcher.command_timeout("cache.write_cache") is None
    assert dispatcher.command_timeout("rendering.start_render") is None
    assert dispatcher.command_timeout("nodes.create_node") == dispatcher._COMMAND_TIMEOUT
    monkeypatch.setenv("FXHOUDINIMCP_TIMEOUT_CACHE_WRITE_CACHE", "30")
    assert dispatcher.command_timeout("cache.write_cache") == 30.0


def test_timeout_message_points_at_background_for_caches():
    from fxhoudinimcp_server import dispatcher

    assert "do not poll the disk" in dispatcher._TIMEOUT_HINTS["cache.write_cache"]
    assert "no deadline" in dispatcher._TIMEOUT_HINTS["rendering.start_render"]


@pytest.mark.asyncio
async def test_reporting_bridge_heartbeats_while_a_command_runs(monkeypatch):
    import asyncio

    from fxhoudinimcp import server

    monkeypatch.setattr(server, "_HEARTBEAT", 0.01)
    inner = MagicMock(spec=server.HoudiniBridge)

    async def slow(command, params=None, timeout=None):
        await asyncio.sleep(0.05)
        return {"ok": command}

    inner.execute = slow
    ctx = MagicMock()
    ctx.report_progress = AsyncMock()
    ctx.request_context.lifespan_context = {"bridge": inner}
    monkeypatch.setattr(server, "HoudiniBridge", MagicMock)
    ctx.request_context.lifespan_context["bridge"] = MagicMock()
    ctx.request_context.lifespan_context["bridge"].execute = slow

    bridge = server._get_bridge(ctx)
    assert await bridge.execute("scene.get_scene_info") == {"ok": "scene.get_scene_info"}
    assert ctx.report_progress.await_count >= 1
    message = ctx.report_progress.await_args.args[2]
    assert message.startswith("scene.get_scene_info: Houdini working for")


def test_verified_foreground_write_turns_load_from_disk_on(monkeypatch):
    monkeypatch.setattr(cache_handlers.hou.hipFile, "isNewFile", lambda: False)
    parms = {"execute": MagicMock(), "loadfromdisk": MagicMock(), "trange": None}
    node = MagicMock()
    node.parm.side_effect = parms.get
    monkeypatch.setattr(cache_handlers, "_get_node", lambda p: node)
    monkeypatch.setattr(cache_handlers, "_set_frame_parm", lambda *a: None)
    monkeypatch.setattr(cache_handlers, "reported_outputs", lambda n: [])
    monkeypatch.setattr(
        cache_handlers,
        "write_verdict",
        lambda *a, **k: {"success": True, "wrote_files": True, "message": "ok", "errors": []},
    )

    result = cache_handlers._write_cache(node_path="/obj/g/c", frame_range=[1, 5])
    assert result["load_from_disk_enabled"] is True
    parms["loadfromdisk"].set.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_no_timeout_sentinel_disables_the_http_deadline(monkeypatch):
    from fxhoudinimcp import bridge as bridge_mod

    b = bridge_mod.HoudiniBridge(timeout=7.0)
    seen = {}

    class FakeClient:
        async def post(self, url, data=None, timeout="unset"):
            seen["timeout"] = timeout
            return MagicMock()

    async def fake_client():
        return FakeClient()

    monkeypatch.setattr(b, "_get_client", fake_client)
    await b._post({}, timeout=bridge_mod.NO_TIMEOUT)
    assert seen["timeout"] is None
    await b._post({})
    assert seen["timeout"] == 7.0


def test_failure_verdict_names_the_upstream_node():
    from fxhoudinimcp_server import outputs

    def fake_node(path, errors=(), parms=None, ancestors=()):
        n = MagicMock()
        n.path.return_value = path
        n.errors.return_value = list(errors)
        n.inputAncestors.return_value = list(ancestors)
        table = parms or {}
        n.parm.side_effect = lambda name: table.get(name)
        n.node.side_effect = lambda p: None
        return n

    solver = fake_node(
        "/obj/FLIP_ocean/ww_solver", errors=["Error: whitewater solver ran out of memory"]
    )
    ww_cache = fake_node("/obj/FLIP_ocean/ww_cache", ancestors=[solver])
    soppath = MagicMock()
    soppath.eval.return_value = "/obj/FLIP_ocean/ww_cache"
    fetch = fake_node("/out/cache_05_ww", parms={"soppath": soppath})
    chain = fake_node("/out/cache_08_flip_mesh", ancestors=[fetch])
    monkey_hou = MagicMock()
    monkey_hou.node.side_effect = lambda p: {"/obj/FLIP_ocean/ww_cache": ww_cache}.get(p)
    original = outputs.hou
    outputs.hou = monkey_hou
    try:
        outputs.reported_outputs = lambda n: []
        verdict = outputs.failure_verdict(chain, [], "The attempted operation failed.")
    finally:
        outputs.hou = original
    assert verdict["errors"][0] == "The attempted operation failed."
    assert any("ww_solver" in e and "out of memory" in e for e in verdict["errors"])
    assert "ww_solver" in verdict["message"]


# ---------------------------------------------------------------- run_shelf_tool in a working scene


class _FakeObject:
    """Stands in for hou.ObjNode, which isinstance() needs as a real class."""

    def __init__(self, path: str, type_name: str = "geo"):
        self._path = path
        self._type = type_name
        self.setSelected = MagicMock()
        self.destroy = MagicMock()

    def path(self):
        return self._path

    def type(self):
        return MagicMock(**{"name.return_value": self._type})


def _shelf_scene(monkeypatch, nodes: dict, selected: list | None = None):
    """A scene /obj whose tree is *nodes* (path -> node), and one shelf tool.

    The tool's script calls kwargs["run"](kwargs), so each test says what the
    tool does without a script that interactive_markers would refuse to run.
    """
    from fxhoudinimcp_server.handlers import shelf_handlers

    hou = shelf_handlers.hou
    tool = MagicMock()
    tool.name.return_value = "the_tool"
    tool.script.return_value = "kwargs['run'](kwargs)"
    monkeypatch.setattr(hou.shelves, "tools", lambda: {"the_tool": tool})
    obj = MagicMock()
    obj.path.return_value = "/obj"
    obj.allSubChildren.side_effect = lambda recurse_in_locked_nodes=False: list(nodes.values())
    monkeypatch.setattr(hou, "node", lambda path: obj if path == "/obj" else nodes.get(path))
    monkeypatch.setattr(hou, "ObjNode", _FakeObject, raising=False)
    monkeypatch.setattr(hou, "currentDopNet", lambda: None)
    chosen = selected if selected is not None else []
    monkeypatch.setattr(hou, "selectedNodes", lambda: list(chosen))
    monkeypatch.setattr(hou, "clearAllSelected", chosen.clear)
    for node in [*nodes.values(), *chosen]:
        node.setSelected.side_effect = lambda on, clear_all_selected=False, n=node: chosen.append(n)
    return shelf_handlers, chosen


def test_run_shelf_tool_names_nodes_built_inside_existing_networks(monkeypatch):
    nodes = {p: _FakeObject(p, "null") for p in ("/obj/d", "/obj/d/popnet")}
    shelf_handlers, _ = _shelf_scene(monkeypatch, nodes)
    popnet = nodes["/obj/d/popnet"]
    dop_nets = iter([popnet, popnet])
    monkeypatch.setattr(shelf_handlers.hou, "currentDopNet", lambda: next(dop_nets))

    def flip_tank(_kwargs):
        # The FLIP tool puts its solver into the current POP network and adds a tank object.
        for path, type_name in (
            ("/obj/d/popnet/flipsolver1", "flipsolver"),
            ("/obj/tank", "geo"),
            ("/obj/tank/wavetank", "null"),
        ):
            nodes[path] = _FakeObject(path, type_name)

    reply = shelf_handlers.run_shelf_tool("the_tool", kwargs={"run": flip_tank})

    assert [c["path"] for c in reply["created"]] == ["/obj/tank"]
    assert reply["created_in_existing"] == [
        {"path": "/obj/d/popnet/flipsolver1", "type": "flipsolver"}
    ]
    assert reply["existing_networks_changed"] == ["/obj/d/popnet"]
    assert reply["current_dop_network"] == {"before": "/obj/d/popnet", "after": "/obj/d/popnet"}


def test_run_shelf_tool_takes_the_objects_already_selected(monkeypatch):
    ball, cam = _FakeObject("/obj/ball"), _FakeObject("/obj/cam", "cam")
    shelf_handlers, _ = _shelf_scene(monkeypatch, {}, selected=[ball, cam])
    picked = []

    def make_flip(kwargs):
        viewer = shelf_handlers.hou.SceneViewer
        picked.extend(viewer.selectObjects(None, "Select objects", allowed_types=("geo",)))

    reply = shelf_handlers.run_shelf_tool("the_tool", kwargs={"run": make_flip})

    assert picked == [ball]
    assert "ran_as_ctrl_click" not in reply


def test_run_shelf_tool_selection_answers_in_place_of_the_scene(monkeypatch):
    ball, other = _FakeObject("/obj/ball"), _FakeObject("/obj/other")
    shelf_handlers, selected = _shelf_scene(monkeypatch, {"/obj/ball": ball}, selected=[other])
    picked = []

    def make_flip(kwargs):
        picked.extend(shelf_handlers.hou.SceneViewer.selectObjects(None, "Select objects"))

    shelf_handlers.run_shelf_tool("the_tool", kwargs={"run": make_flip}, selection=["/obj/ball"])

    assert picked == [ball]
    assert selected == [other]


def test_run_shelf_tool_refuses_a_selection_path_that_does_not_exist(monkeypatch):
    shelf_handlers, _ = _shelf_scene(monkeypatch, {})
    with pytest.raises(ValueError, match="no such node"):
        shelf_handlers.run_shelf_tool("the_tool", selection=["/obj/nope"])


def test_select_objects_still_refuses_with_nothing_suitable(monkeypatch):
    shelf_handlers, _ = _shelf_scene(monkeypatch, {})
    monkeypatch.setattr(shelf_handlers.hou, "selectedNodes", lambda: [_FakeObject("/obj/c", "cam")])
    with pytest.raises(shelf_handlers.InteractivePrompt):
        shelf_handlers._object_selection(None)(None, "pick", allowed_types=("geo",))
    # use_existing_selection=False asks for a fresh pick, which needs a click.
    monkeypatch.setattr(shelf_handlers.hou, "selectedNodes", lambda: [_FakeObject("/obj/g")])
    with pytest.raises(shelf_handlers.InteractivePrompt):
        shelf_handlers._object_selection(None)(None, "pick", use_existing_selection=False)


def test_a_single_object_prompt_takes_the_first_selected(monkeypatch):
    shelf_handlers, _ = _shelf_scene(monkeypatch, {})
    first, second = _FakeObject("/obj/a"), _FakeObject("/obj/b")
    monkeypatch.setattr(shelf_handlers.hou, "selectedNodes", lambda: [first, second])
    assert shelf_handlers._object_selection(None)(None, "pick", allow_multisel=False) == (first,)


def test_run_shelf_tool_still_refuses_every_other_prompt(monkeypatch):
    shelf_handlers, _ = _shelf_scene(monkeypatch, {}, selected=[_FakeObject("/obj/ball")])

    def wants_points(_kwargs):
        shelf_handlers.hou.SceneViewer.selectGeometry(None, "Select points")

    with pytest.raises(ValueError, match="selectGeometry"):
        shelf_handlers.run_shelf_tool("the_tool", kwargs={"run": wants_points})


def test_run_shelf_tool_puts_the_selection_back(monkeypatch):
    mine = _FakeObject("/obj/mine")
    nodes = {"/obj/mine": mine}
    shelf_handlers, selected = _shelf_scene(monkeypatch, nodes, selected=[mine])

    def builds_and_selects(_kwargs):
        # A shelf script selects what it builds, as it would for a click.
        nodes["/obj/tank"] = _FakeObject("/obj/tank", "geo")
        selected[:] = [nodes["/obj/tank"]]

    shelf_handlers.run_shelf_tool("the_tool", kwargs={"run": builds_and_selects})

    assert selected == [mine]


def test_a_refused_tool_removes_what_it_built_inside_existing_networks(monkeypatch):
    nodes = {p: _FakeObject(p, "null") for p in ("/obj/d", "/obj/d/popnet")}
    shelf_handlers, _ = _shelf_scene(monkeypatch, nodes)

    def half_built(_kwargs):
        for path in ("/obj/d/popnet/flipsolver1", "/obj/d/popnet/flipsolver1/inner"):
            nodes[path] = _FakeObject(path, "null")
        raise shelf_handlers.InteractivePrompt("selectGeometry")

    with pytest.raises(ValueError, match="waits for a viewport selection"):
        shelf_handlers.run_shelf_tool("the_tool", kwargs={"run": half_built, "ctrlclick": True})

    nodes["/obj/d/popnet/flipsolver1"].destroy.assert_called_once()
    # The child goes with its parent; the networks that were there stay.
    nodes["/obj/d/popnet/flipsolver1/inner"].destroy.assert_not_called()
    nodes["/obj/d/popnet"].destroy.assert_not_called()


def test_a_sop_parent_path_is_where_a_sop_tool_places_its_nodes(monkeypatch):
    lesson = _FakeObject("/obj/lesson")
    shelf_handlers, _ = _shelf_scene(monkeypatch, {"/obj/lesson": lesson})
    hou = shelf_handlers.hou
    lesson.childTypeCategory = lambda: "Sop"
    monkeypatch.setattr(hou, "sopNodeTypeCategory", lambda: "Sop")
    editor = MagicMock()
    editor.type.return_value = hou.paneTabType.NetworkEditor
    editor.pwd.return_value.path.return_value = "/obj"
    monkeypatch.setattr(hou.ui, "paneTabs", lambda: [editor])
    panes = []

    reply = shelf_handlers.run_shelf_tool(
        "the_tool", kwargs={"run": lambda kw: panes.append(kw["pane"])}, parent_path="/obj/lesson"
    )

    assert panes == [editor]
    # The editor shows the network for the run, then goes back where it was.
    assert [c.args[0] for c in editor.cd.call_args_list] == ["/obj/lesson", "/obj"]
    assert reply["placed_in"] == "/obj/lesson"


@pytest.mark.asyncio
async def test_run_shelf_tool_passes_the_selection_to_houdini():
    from fxhoudinimcp.tools import shelf

    ctx = MagicMock()
    bridge = MagicMock()
    bridge.execute = AsyncMock(return_value={})
    ctx.request_context.lifespan_context = {"bridge": bridge}
    await shelf.run_shelf_tool(ctx, "dynamics_makeflip", selection=["/obj/ball"])
    bridge.execute.assert_awaited_once_with(
        "shelf.run_shelf_tool", {"tool_name": "dynamics_makeflip", "selection": ["/obj/ball"]}
    )
