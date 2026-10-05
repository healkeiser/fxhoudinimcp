"""A node whose cook failed said "Node has no geometry" and nothing about why.

`node.geometry()` is None when the cook failed, and every geometry reader
answered "The attempted operation failed. Node has no geometry: <path>" --
in get_attrib_stats rows too. The node's own cook error (a missing file, a bad
expression) was the part that said why, and it was dropped. The message now
carries `node.errors()`.

hou is mocked here; the live check ran on Houdini 22.0.429.
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
import fxhoudinimcp_server.handlers.geometry_handlers as geometry  # noqa: E402


@pytest.fixture
def failed_node(monkeypatch):
    node = MagicMock()
    node.geometry.return_value = None
    monkeypatch.setattr(geometry.hou, "node", lambda path: node)
    monkeypatch.setattr(geometry.hou, "OperationFailed", RuntimeError, raising=False)
    return node


def test_the_cook_error_is_in_the_message(failed_node):
    failed_node.errors.return_value = ("Unable to read file '/nonexistent/x.bgeo'.",)
    with pytest.raises(RuntimeError, match="its cook failed: Unable to read file"):
        geometry._get_sop_geo("/obj/pf/bad")


def test_a_node_without_errors_keeps_the_short_message(failed_node):
    failed_node.errors.return_value = ()
    with pytest.raises(RuntimeError, match=r"^Node has no geometry: /obj/pf/bad$"):
        geometry._get_sop_geo("/obj/pf/bad")


def test_errors_that_cannot_be_read_keep_the_short_message(failed_node):
    failed_node.errors.side_effect = RuntimeError("no node")
    with pytest.raises(RuntimeError, match=r"^Node has no geometry: /obj/pf/bad$"):
        geometry._get_sop_geo("/obj/pf/bad")
