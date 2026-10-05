"""Tests for list_children(recursive=True) and locked assets.

A recursive listing of a POP network walked into the locked solver assets: on
Houdini 22.0.429, `list_children("/obj/dopnet_object1", recursive=True)` after
the POP Network shelf tool came back at the 500-node cap, truncated, filled
with the DOP assets' insides. The recursion now stops at a locked asset, lists
the asset itself flagged `locked_asset`, and `include_locked_assets=True`
walks in as before.

hou is mocked here.
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


def _node(path, locked=False, network=False):
    node = MagicMock()
    node.path.return_value = path
    node.isLockedHDA.return_value = locked
    node.isInsideLockedHDA.return_value = False
    node.isNetwork.return_value = network
    # An unsynced locked asset answers no children: the flag must not rely on it.
    node.children.return_value = []
    return node


def _parent(monkeypatch, descendants):
    parent = _node("/obj/d")
    parent.allSubChildren.return_value = descendants
    monkeypatch.setattr(nodes, "_get_node", lambda path: parent)
    monkeypatch.setattr(nodes, "_node_summary", lambda node: {"path": node.path()})
    return parent


class TestRecursiveListingAndLockedAssets:
    def test_recursion_does_not_enter_a_locked_asset_and_flags_it(self, monkeypatch):
        solver = _node("/obj/d/popsolver", locked=True, network=True)
        source = _node("/obj/d/popsource")
        parent = _parent(monkeypatch, [solver, source])
        reply = nodes.list_children("/obj/d", recursive=True)
        parent.allSubChildren.assert_called_once_with(
            recurse_in_locked_nodes=False, sync_delayed_definition=False
        )
        assert reply["children"] == [
            {"path": "/obj/d/popsolver", "locked_asset": True},
            {"path": "/obj/d/popsource"},
        ]

    def test_a_locked_asset_that_is_not_a_network_is_not_flagged(self, monkeypatch):
        _parent(monkeypatch, [_node("/obj/d/empty", locked=True)])
        reply = nodes.list_children("/obj/d", recursive=True)
        assert reply["children"] == [{"path": "/obj/d/empty"}]

    def test_include_locked_assets_walks_in_without_flags(self, monkeypatch):
        solver = _node("/obj/d/popsolver", locked=True, network=True)
        parent = _parent(monkeypatch, [solver])
        reply = nodes.list_children("/obj/d", recursive=True, include_locked_assets=True)
        parent.allSubChildren.assert_called_once_with(
            recurse_in_locked_nodes=True, sync_delayed_definition=True
        )
        assert reply["children"] == [{"path": "/obj/d/popsolver"}]

    def test_a_flat_listing_is_unchanged(self, monkeypatch):
        solver = _node("/obj/d/popsolver", locked=True, network=True)
        parent = _parent(monkeypatch, [])
        parent.children.return_value = [solver]
        reply = nodes.list_children("/obj/d")
        parent.allSubChildren.assert_not_called()
        assert reply["children"] == [{"path": "/obj/d/popsolver"}]

    def test_listing_inside_a_locked_asset_walks_all_of_it(self, monkeypatch):
        # There every subnet is uneditable: without this, only the first level.
        parent = _parent(monkeypatch, [_node("/obj/d/popsolver/sub", network=True)])
        parent.isLockedHDA.return_value = True
        reply = nodes.list_children("/obj/d", recursive=True)
        parent.allSubChildren.assert_called_once_with(
            recurse_in_locked_nodes=True, sync_delayed_definition=True
        )
        assert reply["children"] == [{"path": "/obj/d/popsolver/sub"}]
