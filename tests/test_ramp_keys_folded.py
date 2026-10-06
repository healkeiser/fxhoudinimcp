"""non_default_only reports a changed ramp as one entry, not one row per key.

A 100-key colour ramp on a Copernicus heightfield_visualize listed 500 key
parms: 60 per node ran out at the twelfth key, and a sweep of five such nodes
spent its 2000 rows on four and lost an edit on the fifth (22.0.429). The
ramp's own entry carries every key. hou is mocked here.
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

# Internal
import fxhoudinimcp_server.handlers.parameter_handlers as parameters  # noqa: E402

hou = parameters.hou
RAMP, FLOAT = "Ramp", "Float"


class _Parm:
    def __init__(self, name, kind=FLOAT, label=None, ramp=None, changed=True):
        self._name, self._kind, self._label = name, kind, label or name
        self._ramp, self._changed = ramp, changed

    def name(self):
        return self._name

    def parmTemplate(self):  # noqa: N802 - HOM's name
        template = MagicMock()
        template.type.return_value = self._kind
        template.label.return_value = self._label
        return template

    def isMultiParmInstance(self):  # noqa: N802 - HOM's name
        return self._ramp is not None

    def parentMultiParm(self):  # noqa: N802 - HOM's name
        return self._ramp

    def isAtDefault(self):  # noqa: N802 - HOM's name
        return not self._changed

    def isAtRampDefault(self):  # noqa: N802 - HOM's name
        return not self._changed


def _ramp_node(path, keys=100, other=()):
    ramp = _Parm("colorramp", RAMP, label="Color Ramp")
    parms = [ramp, *other]
    for i in range(1, keys + 1):
        for suffix in ("pos", "cr", "cg", "cb", "interp"):
            parms.append(_Parm(f"colorramp{i}{suffix}", label=f"Point {i}", ramp=ramp))
    node = MagicMock()
    node.path.return_value = path
    node.type.return_value.name.return_value = "heightfield_visualize"
    node.parms.return_value = parms
    return node


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(hou, "parmTemplateType", MagicMock(Ramp=RAMP), raising=False)
    monkeypatch.setattr(parameters, "_valueless", lambda parm: False)
    monkeypatch.setattr(parameters, "_parm_entry", lambda parm, defaults: {"value": parm.name()})


class TestOneNode:
    def test_a_changed_ramp_is_one_entry(self, env, monkeypatch):
        node = _ramp_node("/obj/c/hfvis", other=[_Parm("maskrangey")])
        monkeypatch.setattr(hou, "node", lambda path: node)
        reply = parameters._get_parameters(node_path="/obj/c/hfvis", non_default_only=True)
        assert list(reply["parameters"]) == ["colorramp", "maskrangey"]
        assert reply["truncated"] is False

    def test_a_key_named_apart_from_its_ramp_is_listed(self, env, monkeypatch):
        node = _ramp_node("/obj/c/hfvis", keys=3)
        monkeypatch.setattr(hou, "node", lambda path: node)
        reply = parameters._get_parameters(
            node_path="/obj/c/hfvis", patterns=["colorramp2"], non_default_only=True
        )
        assert sorted(reply["parameters"]) == [
            f"colorramp2{s}" for s in sorted(("pos", "cr", "cg", "cb", "interp"))
        ]

    def test_a_pattern_naming_the_ramp_keeps_it_whole(self, env, monkeypatch):
        node = _ramp_node("/obj/c/hfvis", keys=3)
        monkeypatch.setattr(hou, "node", lambda path: node)
        reply = parameters._get_parameters(
            node_path="/obj/c/hfvis", patterns=["color"], non_default_only=True
        )
        assert list(reply["parameters"]) == ["colorramp"]

    def test_without_non_default_only_the_keys_are_listed_as_before(self, env, monkeypatch):
        node = _ramp_node("/obj/c/hfvis", keys=2)
        monkeypatch.setattr(hou, "node", lambda path: node)
        reply = parameters._get_parameters(node_path="/obj/c/hfvis", patterns=["colorramp"])
        assert len(reply["parameters"]) == 1 + 2 * 5


def test_a_sweep_reaches_the_edit_on_the_fifth_node(env, monkeypatch):
    nodes = [_ramp_node(f"/obj/c/hfvis{i}") for i in range(1, 5)]
    nodes.append(_ramp_node("/obj/c/hfvis5", other=[_Parm("heightscale")]))
    parent = MagicMock()
    parent.path.return_value = "/obj/c"
    parent.children.return_value = nodes
    parent.isLockedHDA.return_value = False
    parent.isInsideLockedHDA.return_value = False
    for node in nodes:
        node.isLockedHDA.return_value = False
        node.isInsideLockedHDA.return_value = False
    monkeypatch.setattr(hou, "node", lambda path: parent)
    reply = parameters._get_parameters(inside="/obj/c", non_default_only=True)
    assert ("/obj/c/hfvis5", "heightscale") in [(r["node"], r["parm"]) for r in reply["rows"]]
    assert len(reply["rows"]) == 6
    assert reply["truncated"] is False
