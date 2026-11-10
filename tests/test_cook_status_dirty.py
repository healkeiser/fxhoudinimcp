"""get_cook_status says whether a node is dirty, next to how often it cooked.

hou is mocked here; the live check ran on Houdini 22.0.466.
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
import fxhoudinimcp_server.handlers.graph_handlers as graph  # noqa: E402


def test_cook_status_says_whether_the_node_is_dirty(monkeypatch):
    node = MagicMock()
    node.path.return_value = "/obj/g/box1"
    node.type.return_value.name.return_value = "box"
    node.cookCount.return_value = 4
    node.needsToCook.return_value = True
    node.errors.return_value = ()
    node.warnings.return_value = ()
    monkeypatch.setattr(graph.hou, "node", lambda path: node)
    result = graph.get_cook_status("/obj/g/box1")
    assert result["cook_count"] == 4
    assert result["needs_to_cook"] is True
