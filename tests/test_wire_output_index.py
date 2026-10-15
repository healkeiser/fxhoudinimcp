"""get_network_overview read every wire's from_output as 0.

It looked the output index up in the source's outputConnections() and matched
each connection's inputNode() against the target, but on a connection taken
from outputConnections() inputNode() is the source itself (the target is
outputNode()), so nothing ever matched and the 0 it started with stayed.
Measured on a POP VOP: random1.pos <- id, add1.input1 <- v, cross1.vec2 <- P,
all three from geometryvopglobal1, all three read from_output 0 -- a wire
from P instead of v was invisible in the overview.

Wires are read off the target's inputConnections() now, where both indices
are the wire's own, and named where an index alone is ambiguous: the output
when the source has more than one, the input where inputs are named by design
(VOP, Copernicus). get_node_info's inputs carry the same.

hou is mocked here; the live check ran on Houdini 22.0.429.
"""

from __future__ import annotations

# Built-in
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Internal
import fxhoudinimcp_server.handlers.context_handlers as context  # noqa: E402
import fxhoudinimcp_server.handlers.node_handlers as nodes  # noqa: E402


def _vop(name, inputs=(), outputs=("out",), wires=(), category="Vop"):
    """A node whose *wires* are (source, output_index, input_index)."""
    node = MagicMock(name=name)
    node.name.return_value = name
    node.path.return_value = f"/obj/geo1/popnet/set_vel/{name}"
    node.inputNames.return_value = tuple(inputs)
    node.outputNames.return_value = tuple(outputs)
    node.type.return_value.category.return_value.name.return_value = category
    node.inputConnections.return_value = tuple(
        SimpleNamespace(
            inputNode=lambda s=s: s, outputIndex=lambda o=o: o, inputIndex=lambda i=i: i
        )
        for s, o, i in wires
    )
    by_index = {i: s for s, _o, i in wires}
    node.inputs.return_value = tuple(by_index.get(i) for i in range(len(inputs)))
    return node


def test_the_overview_reads_the_output_index_of_the_wire(monkeypatch):
    glob = _vop("geometryvopglobal1", outputs=("P", "v", "force", "id"))
    cross = _vop("cross1", inputs=("vec1", "vec2"), outputs=("crossprod",), wires=[(glob, 1, 1)])
    # What the old lookup saw: the source's own connection, whose inputNode()
    # is the source.
    glob.outputConnections.return_value = (
        SimpleNamespace(inputNode=lambda: glob, inputIndex=lambda: 1, outputIndex=lambda: 1),
    )
    network = MagicMock()
    network.path.return_value = "/obj/geo1/popnet/set_vel"
    network.children.return_value = (glob, cross)
    monkeypatch.setattr(context.hou, "node", lambda path: network, raising=False)
    reply = context._get_network_overview("/obj/geo1/popnet/set_vel", depth=1)
    assert reply["connections"] == [
        {
            "from": "geometryvopglobal1",
            "from_output": 1,
            "from_output_name": "v",
            "to": "cross1",
            "to_input": 1,
            "to_input_name": "vec2",
        }
    ]


def test_a_sop_wire_keeps_its_old_shape(monkeypatch):
    box = _vop("box1", outputs=("output1",), category="Sop")
    xform = _vop("xform1", inputs=("input1",), wires=[(box, 0, 0)], category="Sop")
    network = MagicMock()
    network.path.return_value = "/obj/geo1"
    network.children.return_value = (box, xform)
    monkeypatch.setattr(context.hou, "node", lambda path: network, raising=False)
    reply = context._get_network_overview("/obj/geo1", depth=1)
    assert reply["connections"] == [
        {"from": "box1", "from_output": 0, "to": "xform1", "to_input": 0}
    ]


def test_node_info_names_the_output_and_the_input():
    glob = _vop("geometryvopglobal1", outputs=("P", "v", "force", "id"))
    rnd = _vop("random1", inputs=("pos",), wires=[(glob, 3, 0)])
    entry = {"index": 0, "node_path": glob.path(), "node_name": "geometryvopglobal1"}
    nodes._name_input(entry, rnd, glob, 3, named_inputs=True)
    assert (entry["output_index"], entry["output_name"], entry["input_name"]) == (3, "id", "pos")


def test_node_info_adds_nothing_to_a_single_output_wire():
    entry = {"index": 0}
    nodes._name_input(entry, _vop("xform1"), _vop("box1", outputs=("output1",)), 0, False)
    assert entry == {"index": 0}
