"""promote_vop_parameters: the network editor's Promote Parameter, batched.

A VOP input became a parameter only through execute_python:
insertParmGenerator makes the Parameter VOP and wires it in, but the parm
appears on the VOP network that owns it (POP VOP, Attribute VOP) only once
that network is compiled -- measured on 22.0.429, a cook did not bring it,
vop_forcecompile did. The verb checks the whole batch before it changes
anything (a wired input is refused, not rewired), compiles each owner once,
and names where every parm landed.

hou is mocked here; the live check ran on Houdini 22.0.429.
"""

from __future__ import annotations

# Built-in
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

# Third-party
import pytest

sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Internal
import fxhoudinimcp_server.handlers.parameter_handlers as parameters  # noqa: E402


class _FakeVop:
    """A VOP node with named inputs, inside an owner network."""

    def __init__(self, path, inputs, owner, wired=None):
        self._path = path
        self._inputs = list(inputs)
        self._owner = owner
        self._wired = dict(wired or {})
        self.made = []

    def path(self):
        return self._path

    def parent(self):
        return self._owner

    def inputNames(self):  # noqa: N802 — HOM spelling
        return tuple(self._inputs)

    def inputs(self):
        return tuple(self._wired.get(i) for i in range(len(self._inputs)))

    def type(self):
        return SimpleNamespace(category=lambda: SimpleNamespace(name=lambda: "Vop"))

    def insertParmGenerator(self, input_name, gen_type, use_value):  # noqa: N802
        gen = MagicMock()
        gen.path.return_value = f"{self._owner.path()}/{input_name}"
        parm = MagicMock()
        parm.eval.return_value = input_name
        parm.set.side_effect = lambda v: parm.eval.configure_mock(return_value=v)
        gen.parm.side_effect = lambda n: parm if n == "parmname" else MagicMock()
        self.made.append((input_name, gen_type, use_value, gen))
        return gen


@pytest.fixture
def popvop(monkeypatch):
    owner = MagicMock()
    owner.path.return_value = "/obj/geo/popnet/set_nage"
    owner.type.return_value.category.return_value.name.return_value = "Dop"
    owner.shown = set()
    owner.parm.side_effect = lambda n: "COMPILE" if n == "vop_forcecompile" else None
    owner.parmTuple.side_effect = lambda n: (
        SimpleNamespace(eval=lambda: (1.5,)) if n in owner.shown else None
    )
    owner.parent.return_value = None
    mul = _FakeVop(
        "/obj/geo/popnet/set_nage/multiply1",
        ("input1", "input2"),
        owner,
        {0: SimpleNamespace(path=lambda: "/obj/geo/popnet/set_nage/geometryvopglobal1")},
    )
    fit = _FakeVop("/obj/geo/popnet/set_nage/fit1", ("val", "srcmin", "srcmax", "destmin"), owner)
    table = {mul.path(): mul, fit.path(): fit}
    pressed = []

    def press(button):
        pressed.append(button)
        # The parms come with the compile, under each generator's parmname.
        owner.shown |= {made[3].parm("parmname").eval() for vop in (mul, fit) for made in vop.made}

    monkeypatch.setattr(parameters.hou, "VopNode", _FakeVop, raising=False)
    monkeypatch.setattr(
        parameters.hou,
        "node",
        lambda p: table.get(p) or (owner if p == owner.path() else None),
        raising=False,
    )
    monkeypatch.setattr(
        parameters.hou,
        "vopParmGenType",
        SimpleNamespace(Parameter="P", Constant="C", SubnetInput="S"),
        raising=False,
    )
    monkeypatch.setattr(parameters, "press", press)
    return SimpleNamespace(owner=owner, mul=mul, fit=fit, pressed=pressed)


class TestPromoteVopParameters:
    def test_a_batch_is_promoted_and_the_owner_compiled_once(self, popvop):
        reply = parameters._promote_vop_parameters(
            [
                {"node_path": popvop.mul.path(), "input": "input2", "name": "age_scale"},
                {"node_path": popvop.fit.path(), "input": "destmin"},
            ]
        )
        assert popvop.pressed == ["COMPILE"]
        assert reply["success"] is True
        assert [(e["parm_name"], e["owner"]) for e in reply["promoted"]] == [
            ("age_scale", popvop.owner.path()),
            ("destmin", popvop.owner.path()),
        ]
        assert popvop.mul.made[0][1:3] == ("P", True)

    def test_a_wired_input_is_refused_before_anything_is_made(self, popvop):
        with pytest.raises(ValueError, match="already wired"):
            parameters._promote_vop_parameters(
                [
                    {"node_path": popvop.fit.path(), "input": "destmin"},
                    {"node_path": popvop.mul.path(), "input": "input1"},
                ]
            )
        assert popvop.fit.made == [] and popvop.pressed == []

    def test_an_unknown_input_gets_a_suggestion(self, popvop):
        with pytest.raises(ValueError, match=r"Did you mean \['input2'"):
            parameters._promote_vop_parameters(
                [{"node_path": popvop.mul.path(), "input": "inptu2"}]
            )

    def test_a_parm_that_did_not_appear_is_said_so(self, popvop, monkeypatch):
        monkeypatch.setattr(parameters, "press", lambda button: None)
        reply = parameters._promote_vop_parameters(
            [{"node_path": popvop.fit.path(), "input": "destmin"}]
        )
        assert reply["success"] is False
        assert "vop_forcecompile" in reply["promoted"][0]["note"]
