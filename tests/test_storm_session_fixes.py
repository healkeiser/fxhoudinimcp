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


def test_write_cache_picks_background_past_24_frames(monkeypatch):
    monkeypatch.setattr(cache_handlers, "_serialize_value", lambda v: v, raising=False)
    monkeypatch.setattr(cache_handlers.hou.hipFile, "isNewFile", lambda: False)
    monkeypatch.setattr(cache_handlers.hou.hipFile, "save", lambda: None)
    parms = {"cookoutputnode": MagicMock(), "execute": MagicMock(), "trange": None}
    node = MagicMock()
    node.parm.side_effect = parms.get
    monkeypatch.setattr(cache_handlers, "_get_node", lambda p: node)
    monkeypatch.setattr(cache_handlers, "_set_frame_parm", lambda *a: None)
    monkeypatch.setattr(cache_handlers, "reported_outputs", lambda n: [])

    long_range = cache_handlers._write_cache(node_path="/obj/g/c", frame_range=[1, 80])
    assert long_range["status"] == "launched"
    assert long_range["decided"].startswith("background chosen")
    parms["cookoutputnode"].pressButton.assert_called_once()
    parms["execute"].pressButton.assert_not_called()


def test_timeout_message_points_at_background_for_caches():
    from fxhoudinimcp_server import dispatcher

    assert "background=True" in dispatcher._TIMEOUT_HINTS["cache.write_cache"]
    assert "get_render_progress" in dispatcher._TIMEOUT_HINTS["rendering.start_render"]


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
