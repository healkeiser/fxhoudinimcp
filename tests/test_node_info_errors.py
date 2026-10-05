"""get_node_info left a real error on a healthy node.

Evaluating a cook-local expression outside a cook -- a factory ``$N`` in a
Group SOP's rangeend, ``@N.x`` in a Ray SOP's dir -- sets a transient "Unable to
evaluate expression" on the node. Calling errors() afterwards, in the same
main-thread tick, makes it stick. get_node_info evaluated every parameter for
its non-default summary and read errors() after that, so a freshly cooked,
healthy node answered with an error and kept it until it was force-cooked.
Errors are now read before any parameter is evaluated.

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

PINNED = "Unable to evaluate expression (Bad data type for function or operation (/obj/geo1/grp/rangeend))."


class _Node:
    """A healthy node whose $N parm behaves as HOM's does outside a cook.

    eval() on it arms a transient error; errors() called while it is armed
    turns it into a real one that every later errors() call returns.
    """

    def __init__(self):
        self.armed = False
        self.pinned = False
        rangeend = MagicMock()
        rangeend.name.return_value = "rangeend"
        rangeend.parmTemplate.return_value.type.return_value.name.return_value = "Int"
        rangeend.isAtDefault.return_value = True

        def evaluate():
            self.armed = True
            return 0

        rangeend.eval.side_effect = evaluate
        self._parms = [rangeend]

    def parms(self):
        return self._parms

    def errors(self):
        if self.armed:
            self.pinned = True
        return (PINNED,) if self.pinned else ()

    def warnings(self):
        return ()

    def __getattr__(self, name):
        return MagicMock()


def test_a_healthy_node_reports_no_error_and_keeps_none(monkeypatch):
    node = _Node()
    monkeypatch.setattr(nodes, "_get_node", lambda path: node)
    monkeypatch.setattr(nodes, "to_jsonable", lambda v: v)

    info = nodes.get_node_info("/obj/geo1/grp")

    assert info["errors"] == []
    node.armed = False  # the next call runs in a later main-thread tick
    assert node.errors() == ()  # nothing was left on the node either


def test_a_real_error_is_still_reported(monkeypatch):
    node = _Node()
    node.pinned = True  # already broken before the call
    monkeypatch.setattr(nodes, "_get_node", lambda path: node)
    monkeypatch.setattr(nodes, "to_jsonable", lambda v: v)

    assert nodes.get_node_info("/obj/geo1/grp")["errors"] == [PINNED]


def _parm(name, expression, at_default=False, value=0.0):
    parm = MagicMock()
    parm.name.return_value = name
    parm.description.return_value = name
    parm.parmTemplate.return_value.type.return_value.name.return_value = "Float"
    parm.parmTemplate.return_value.defaultValue.return_value = (0.0,)
    parm.componentIndex.return_value = 0
    parm.isAtDefault.return_value = at_default
    parm.expression.return_value = expression
    parm.eval.return_value = value
    return parm


class TestSopLocalVariablesAreNamedNotEvaluated:
    """A pivot at $CEX $CEY $CEZ read as px = 0.0 on a healthy Transform.

    SOP local variables only exist while the node cooks. Outside a cook eval()
    answers 0 for them, so the summary showed a centred pivot as the origin,
    and the evaluation itself put "Unable to evaluate expression" on the node
    (22.0.429). Such a parameter is now named with its expression and not
    evaluated.
    """

    def _summary(self, monkeypatch, *parms):
        monkeypatch.setattr(nodes, "to_jsonable", lambda v: v)
        return nodes._non_default_parms(MagicMock(), list(parms))

    def test_a_centroid_pivot_comes_with_its_expression_and_no_value(self, monkeypatch):
        px = _parm("px", "$CEX")
        (entry,) = self._summary(monkeypatch, px)
        assert entry["value"] is None
        assert entry["expression"] == "$CEX"
        assert entry["local_variable"] is True
        assert "cook" in entry["note"]
        px.eval.assert_not_called()

    def test_a_factory_local_variable_at_its_default_is_left_out_unevaluated(self, monkeypatch):
        rangeend = _parm("rangeend", "$N-1", at_default=True)
        assert self._summary(monkeypatch, rangeend) == []
        rangeend.eval.assert_not_called()

    def test_an_ordinary_expression_is_still_evaluated(self, monkeypatch):
        tx = _parm("tx", 'ch("../ctrl/tx")', value=2.0)
        (entry,) = self._summary(monkeypatch, tx)
        assert entry["value"] == 2.0
        assert "local_variable" not in entry

    def test_get_node_info_leaves_no_error_behind_for_one(self, monkeypatch):
        node = _Node()
        px = _parm("px", "$CEX")
        px.eval.side_effect = lambda: setattr(node, "armed", True) or 0.0
        node._parms = [px]
        monkeypatch.setattr(nodes, "_get_node", lambda path: node)
        monkeypatch.setattr(nodes, "to_jsonable", lambda v: v)

        info = nodes.get_node_info("/obj/geo1/xform1")

        assert info["non_default_parameters"][0]["local_variable"] is True
        assert node.armed is False

    def test_the_pattern_knows_the_sop_locals_and_nothing_else(self):
        for text in ("$CEX", "$GCY", "$BBZ", "$SIZEX", "$XMIN", "$NPT", "$PT * 2", "@N.x"):
            assert nodes._COOK_LOCAL.search(text), text
        for text in ("$F", "$T", "$HIP/geo", "ch('tx')", "$CEXTRA", "$NAME"):
            assert not nodes._COOK_LOCAL.search(text), text
