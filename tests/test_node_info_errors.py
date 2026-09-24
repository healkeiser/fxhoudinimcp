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
