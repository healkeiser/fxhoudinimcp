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
from unittest.mock import MagicMock

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
