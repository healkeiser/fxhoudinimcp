"""get_node_info called every tuple component "non-default".

A bare xform with tx = 1 answered with 34 non_default_parameters: each
component's scalar value was compared with the whole tuple's default
((0.0, 0.0, 0.0)), so ty, tz, r*, s*, the pivots and two buttons all came
back as edits. The summary now compares a component with its own default,
and skips valueless parameters.

hou is mocked here; the live check ran on Houdini 22.0.429.
"""

from __future__ import annotations

# Built-in
import os
import sys
from unittest.mock import MagicMock

sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Internal
import fxhoudinimcp_server.handlers.node_handlers as nodes  # noqa: E402


def _parm(name, kind, value, default, index=0, at_default=None, tags=None):
    parm = MagicMock()
    parm.name.return_value = name
    parm.description.return_value = name.upper()
    parm.eval.return_value = value
    parm.componentIndex.return_value = index
    parm.parmTemplate.return_value.type.return_value.name.return_value = kind
    parm.parmTemplate.return_value.defaultValue.return_value = default
    parm.parmTemplate.return_value.tags.return_value = tags or {}
    if at_default is None:
        parm.isAtDefault.side_effect = RuntimeError("not answered")
    else:
        parm.isAtDefault.return_value = at_default
    return parm


def _xform_like():
    """tx = 1, everything else at default, plus two buttons."""
    parms_ = []
    for base in ("t", "r", "s", "p"):
        for i, axis in enumerate("xyz"):
            value = 1.0 if (base, axis) == ("t", "x") else 0.0
            parms_.append(_parm(f"{base}{axis}", "Float", value, (0.0, 0.0, 0.0), index=i))
    parms_.append(_parm("movecentroid", "Button", 0, (0,)))
    parms_.append(_parm("pre_xform", "Button", 0, (0,)))
    parms_.append(_parm("prexform_folder", "FolderSet", 0, (0,)))
    return parms_


class TestComponentsAreComparedWithTheirOwnDefault:
    def test_one_edited_component_is_the_only_entry(self, monkeypatch):
        monkeypatch.setattr(nodes, "to_jsonable", lambda v: v)
        summary = nodes._non_default_parms(MagicMock(), _xform_like())
        assert [p["name"] for p in summary] == ["tx"]
        assert summary[0]["value"] == 1.0
        assert summary[0]["default"] == 0.0

    def test_houdinis_own_answer_wins_when_it_gives_one(self, monkeypatch):
        monkeypatch.setattr(nodes, "to_jsonable", lambda v: v)
        # value equals the default, but an expression drives it: Houdini says "changed".
        driven = _parm("tx", "Float", 0.0, (0.0, 0.0, 0.0), at_default=False)
        plain = _parm("ty", "Float", 0.0, (0.0, 0.0, 0.0), index=1, at_default=True)
        summary = nodes._non_default_parms(MagicMock(), [driven, plain])
        assert [p["name"] for p in summary] == ["tx"]

    def test_a_ramp_without_a_comparable_default_still_reaches_the_reply(self, monkeypatch):
        monkeypatch.setattr(nodes, "to_jsonable", lambda v: str(v))

        class Ramp:
            def __eq__(self, other):
                raise TypeError("no")

        ramp = _parm("ramp", "Ramp", Ramp(), None)
        summary = nodes._non_default_parms(MagicMock(), [ramp])
        assert [p["name"] for p in summary] == ["ramp"]
