"""connect_nodes and connect_nodes_batch refuse what they cannot honour.

An entry key the batch did not know was dropped: {"dest_input": 2} wired input
0 and replaced the wire already there, and the reply said input_index 0. Every
entry is now checked before a wire is made, and the spellings other verbs use
(dest_input, index, source_output) name the right key. Inside a locked asset
Houdini takes setInput without a word and makes no wire; both verbs answered
success over an unchanged network. Each wire is now read back.

hou is mocked here; the live check ran on Houdini 22.0.466.
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
import fxhoudinimcp_server.handlers.node_handlers as nodes  # noqa: E402


def _conn(index, item, output=0):
    conn = MagicMock()
    conn.inputIndex.return_value = index
    conn.inputItem.return_value = item
    conn.inputItemOutputIndex.return_value = output
    return conn


def _node(path, takes_wires=True, locked_in=None):
    node = MagicMock(name=path)
    node.path.return_value = path
    wires: list = []
    node.inputConnections.side_effect = lambda: list(wires)
    if takes_wires:
        node.setInput.side_effect = lambda i, item, out=0: wires.append(_conn(i, item, out))
    node.isInsideLockedHDA.return_value = locked_in is not None
    node.isLockedHDA.return_value = False
    if locked_in is not None:
        node.parent.return_value = locked_in
    return node


@pytest.fixture
def net(monkeypatch):
    asset = MagicMock()
    asset.path.return_value = "/obj/g/asset"
    asset.isLockedHDA.return_value = True
    lookup = {
        "/obj/g/a": _node("/obj/g/a"),
        "/obj/g/m": _node("/obj/g/m"),
        "/obj/g/asset/m": _node("/obj/g/asset/m", takes_wires=False, locked_in=asset),
    }
    monkeypatch.setattr(nodes, "_get_node", lambda path: lookup[path])
    monkeypatch.setattr(nodes, "_focus_network_editor", lambda *a, **k: None)
    monkeypatch.setattr(nodes, "dop_cache_note", lambda *a, **k: None)
    return lookup


class TestConnectionKeys:
    def test_an_unknown_key_refuses_the_batch_before_any_wire(self, net):
        with pytest.raises(
            ValueError,
            match=r"unknown key 'dest_input' \(did you mean input_index\?\).*Nothing was wired",
        ):
            nodes.connect_nodes_batch(
                [
                    {"source_path": "/obj/g/a", "dest_path": "/obj/g/m", "input_index": 1},
                    {"source_path": "/obj/g/a", "dest_path": "/obj/g/m", "dest_input": 2},
                ]
            )
        net["/obj/g/m"].setInput.assert_not_called()

    def test_a_missing_path_and_a_non_dict_are_named(self, net):
        with pytest.raises(
            ValueError,
            match=r"connections\[0\]: 'dest_path' is required.*connections\[1\] is not a dict",
        ):
            nodes.connect_nodes_batch([{"source_path": "/obj/g/a"}, "a->m"])

    def test_an_empty_list_is_refused(self, net):
        with pytest.raises(ValueError, match="non-empty list"):
            nodes.connect_nodes_batch([])

    def test_known_keys_wire_as_before(self, net):
        result = nodes.connect_nodes_batch(
            [{"source_path": "/obj/g/a", "dest_path": "/obj/g/m", "input_index": 2}]
        )
        assert result["success"] is True
        assert result["connected"][0]["input_index"] == 2


class TestWireIsReadBack:
    def test_a_wire_houdini_did_not_make_is_an_error_in_the_batch(self, net):
        result = nodes.connect_nodes_batch(
            [{"source_path": "/obj/g/a", "dest_path": "/obj/g/asset/m", "input_index": 1}]
        )
        assert result["success"] is False
        assert result["connected"] == []
        assert "made no wire" in result["errors"][0]["error"]
        assert "locked asset /obj/g/asset" in result["errors"][0]["error"]

    def test_connect_nodes_raises_on_it(self, net):
        with pytest.raises(
            ValueError, match="made no wire into /obj/g/asset/m input 0.*allow_editing_of_contents"
        ):
            nodes.connect_nodes("/obj/g/a", "/obj/g/asset/m")

    def test_a_wire_from_another_output_does_not_count(self, net):
        dest = net["/obj/g/m"]
        dest.setInput.side_effect = None
        dest.inputConnections.side_effect = lambda: [_conn(0, net["/obj/g/a"], 1)]
        with pytest.raises(ValueError, match="made no wire"):
            nodes.connect_nodes("/obj/g/a", "/obj/g/m")
