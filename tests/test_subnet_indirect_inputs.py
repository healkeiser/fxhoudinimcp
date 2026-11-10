"""A subnet's input connectors could not be wired from by any verb.

They are `SubnetIndirectInput` items, not nodes: they have no path, so
connect_nodes, connect_nodes_batch and build_network — all of which name a
source by path — had no way to feed the first node of a chain built inside a
subnet from the subnet's own input. That took `node.setInput(0,
subnet.indirectInputs()[0])` in execute_python. The three verbs now take
`indirect_input=n` (build_network: `{"indirect_input": n}` in place of a
source), and an index past the subnet's connectors, or a plain node given as
the subnet, is refused by name.

hou is mocked here; the live check ran on Houdini 22.0.429, where the wire is
visible through inputConnections() — hou.Node.inputs() lists nodes only and
shows nothing for an indirect input.
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
import fxhoudinimcp_server.handlers.graph_handlers as graph  # noqa: E402
import fxhoudinimcp_server.handlers.node_handlers as nodes  # noqa: E402

hou = graph.hou


def _node(path, type_name="xform"):
    node = MagicMock()
    node.path.return_value = path
    node.name.return_value = path.rsplit("/", 1)[-1]
    node.type.return_value.name.return_value = type_name
    return node


def _subnet(path="/obj/geo1/subnet1", connectors=1):
    subnet = _node(path, "subnet")
    items = [MagicMock(name=f"indirect{i}") for i in range(connectors)]
    subnet.indirectInputs.return_value = items
    return subnet, items


def _conn(index, item, output=0):
    conn = MagicMock()
    conn.inputIndex.return_value = index
    conn.inputItem.return_value = item
    conn.inputItemOutputIndex.return_value = output
    return conn


class TestConnectNodes:
    def _install(self, monkeypatch, lookup):
        monkeypatch.setattr(nodes, "_get_node", lambda path: lookup[path])
        monkeypatch.setattr(nodes, "_focus_network_editor", lambda *a, **k: None)
        for node in lookup.values():
            # The verb reads each wire back through inputConnections().
            wires = []
            node.inputConnections.side_effect = lambda wires=wires: list(wires)
            node.setInput.side_effect = lambda i, item, out=0, wires=wires: wires.append(
                _conn(i, item, out)
            )

    def _inside(self, subnet, name="matchsize1"):
        dest = _node(f"{subnet.path()}/{name}", "matchsize")
        dest.parent.return_value = subnet
        return dest

    def test_wires_from_the_subnets_connector(self, monkeypatch):
        subnet, (connector,) = _subnet()
        dest = self._inside(subnet)
        self._install(monkeypatch, {subnet.path(): subnet, dest.path(): dest})

        result = nodes.connect_nodes(subnet.path(), dest.path(), indirect_input=0)

        dest.setInput.assert_called_once_with(0, connector, 0)
        assert result["indirect_input"] == 0
        # A path a caller can feed to the next call; the connector is its own key.
        assert result["source_path"] == "/obj/geo1/subnet1"

    def test_an_index_out_of_range_is_named(self, monkeypatch):
        subnet, _ = _subnet()
        dest = self._inside(subnet)
        self._install(monkeypatch, {subnet.path(): subnet, dest.path(): dest})
        with pytest.raises(ValueError, match="1 input connector"):
            nodes.connect_nodes(subnet.path(), dest.path(), indirect_input=3)

    def test_a_node_without_input_connectors_is_refused_clearly(self, monkeypatch):
        # Measured on 22.0.429: a Box answers indirectInputs() with an empty
        # tuple instead of raising InvalidNodeType.
        box = _node("/obj/geo1/box1", "box")
        box.indirectInputs.return_value = ()
        dest = _node("/obj/geo1/xform1")
        self._install(monkeypatch, {box.path(): box, dest.path(): dest})
        with pytest.raises(ValueError, match="not a subnet"):
            nodes.connect_nodes(box.path(), dest.path(), indirect_input=0)

    def test_a_destination_outside_the_subnet_is_refused_by_name(self, monkeypatch):
        subnet, _ = _subnet()
        outside = _node("/obj/geo1/box1", "box")
        outside.parent.return_value = _node("/obj/geo1", "geo")
        self._install(monkeypatch, {subnet.path(): subnet, outside.path(): outside})
        with pytest.raises(ValueError, match="is not inside /obj/geo1/subnet1"):
            nodes.connect_nodes(subnet.path(), outside.path(), indirect_input=0)
        outside.setInput.assert_not_called()

    def test_a_connector_has_one_output(self, monkeypatch):
        subnet, _ = _subnet()
        dest = self._inside(subnet)
        self._install(monkeypatch, {subnet.path(): subnet, dest.path(): dest})
        with pytest.raises(ValueError, match="output_index must be 0"):
            nodes.connect_nodes(subnet.path(), dest.path(), output_index=1, indirect_input=0)

    def test_the_index_must_be_an_integer(self, monkeypatch):
        subnet, (connector,) = _subnet()
        with pytest.raises(ValueError, match="must be an integer, got 'first'"):
            nodes._indirect_input_item(subnet, "first")
        with pytest.raises(ValueError, match="must be an integer"):
            nodes._indirect_input_item(subnet, 0.5)
        assert nodes._indirect_input_item(subnet, 0.0) is connector

    def test_without_the_argument_nothing_changes(self, monkeypatch):
        src = _node("/obj/geo1/box1", "box")
        dest = _node("/obj/geo1/xform1")
        self._install(monkeypatch, {src.path(): src, dest.path(): dest})
        result = nodes.connect_nodes(src.path(), dest.path())
        dest.setInput.assert_called_once_with(0, src, 0)
        assert result["source_path"] == "/obj/geo1/box1"
        assert "indirect_input" not in result

    def test_the_batch_takes_the_same_key(self, monkeypatch):
        subnet, (connector,) = _subnet()
        dest = self._inside(subnet)
        self._install(monkeypatch, {subnet.path(): subnet, dest.path(): dest})
        result = nodes.connect_nodes_batch(
            [{"source_path": subnet.path(), "dest_path": dest.path(), "indirect_input": 0}]
        )
        assert result["success"] is True
        dest.setInput.assert_called_once_with(0, connector, 0)
        assert result["connected"][0]["indirect_input"] == 0

    def test_a_bad_index_in_the_batch_lands_in_errors_not_an_exception(self, monkeypatch):
        subnet, _ = _subnet()
        dest = self._inside(subnet)
        self._install(monkeypatch, {subnet.path(): subnet, dest.path(): dest})
        result = nodes.connect_nodes_batch(
            [{"source_path": subnet.path(), "dest_path": dest.path(), "indirect_input": 4}]
        )
        assert result["success"] is False
        assert "1 input connector" in result["errors"][0]["error"]


class TestUndoingAnIndirectWire:
    """inputs() hides a wire from a subnet's connector: it reports None when
    the subnet's own input is open. inputConnections() shows it."""

    def _wired(self, monkeypatch):
        connector = MagicMock(name="indirect0")
        node = _node("/obj/geo1/subnet1/matchsize1", "matchsize")
        node.inputs.return_value = ()
        node.inputConnections.return_value = [_conn(0, connector)]
        monkeypatch.setattr(nodes, "_get_node", lambda path: node)
        return node, connector

    def test_disconnect_all_removes_it(self, monkeypatch):
        node, _ = self._wired(monkeypatch)
        result = nodes.disconnect_node(node.path(), disconnect_all=True)
        node.setInput.assert_called_once_with(0, None)
        assert result["disconnected_inputs"] == [0]

    def test_disconnect_by_index_removes_it(self, monkeypatch):
        node, _ = self._wired(monkeypatch)
        nodes.disconnect_node(node.path(), input_index=0)
        node.setInput.assert_called_once_with(0, None)

    def test_reorder_keeps_the_connector_and_the_output_index(self, monkeypatch):
        node, connector = self._wired(monkeypatch)
        upstream = _node("/obj/geo1/subnet1/box1", "box")
        node.inputConnections.return_value = [_conn(0, connector), _conn(1, upstream, output=2)]
        nodes.reorder_inputs(node.path(), [1, 0])
        assert node.setInput.call_args_list[-2:] == [
            ((0, upstream, 2),),
            ((1, connector, 0),),
        ]

    def test_a_bad_order_is_refused_before_anything_is_disconnected(self, monkeypatch):
        node, _ = self._wired(monkeypatch)
        with pytest.raises(ValueError, match="refers to inputs"):
            nodes.reorder_inputs(node.path(), [5])
        node.setInput.assert_not_called()


class TestBuildNetwork:
    def _network(self, monkeypatch, connectors=4):
        parent, items = _subnet("/obj/geo1/subnet1", connectors)
        parent.children.return_value = []
        parent.displayNode.return_value = None
        parent.renderNode.return_value = None
        category = MagicMock()
        category.name.return_value = "Sop"
        parent.childTypeCategory.return_value = category
        node_type = MagicMock()
        node_type.name.return_value = "matchsize"
        node_type.maxNumInputs.return_value = 2
        probe = MagicMock()
        probe.parms.return_value = []
        probe.parmTuples.return_value = []
        parent.createNode.return_value = probe
        monkeypatch.setattr(hou, "node", lambda path: parent if path == parent.path() else None)
        monkeypatch.setattr(graph, "_resolve_node_type", lambda cat, name: node_type)
        monkeypatch.setattr(graph, "_instance_patterns", lambda t: [])
        return parent, items, probe

    def _dry(self, inputs):
        return graph.build_network(
            "/obj/geo1/subnet1",
            [{"type": "matchsize", "name": "ms", "inputs": inputs}],
            dry_run=True,
        )

    def test_a_connector_index_validates_without_a_source(self, monkeypatch):
        self._network(monkeypatch)
        assert self._dry([{"indirect_input": 0}])["valid"] is True

    def test_an_index_past_the_connectors_fails_the_dry_run(self, monkeypatch):
        self._network(monkeypatch)
        result = self._dry([{"indirect_input": 9}])
        assert result["valid"] is False
        assert "4 input connector(s); asked for #9" in result["errors"][0]

    def test_source_and_indirect_input_together_are_refused(self, monkeypatch):
        self._network(monkeypatch)
        result = self._dry([{"source": "doesnotexist", "indirect_input": 0}])
        assert result["valid"] is False
        assert "not both" in result["errors"][0]

    def test_a_source_output_on_a_connector_fails_the_dry_run(self, monkeypatch):
        self._network(monkeypatch)
        result = self._dry([{"indirect_input": 0, "source_output": 2}])
        assert result["valid"] is False
        assert "source_output must be 0" in result["errors"][0]

    def test_a_failing_listing_reports_the_real_message(self, monkeypatch):
        parent, _, _ = self._network(monkeypatch)
        parent.indirectInputs.side_effect = RuntimeError("HOM said no")
        result = self._dry([{"indirect_input": 0}])
        assert result["valid"] is False
        assert "HOM said no" in result["errors"][0]
        assert "not a subnet" not in result["errors"][0]

    def test_the_parent_s_connectors_are_listed_once(self, monkeypatch):
        parent, _, _ = self._network(monkeypatch)
        self._dry([{"indirect_input": 0}, {"indirect_input": 1, "index": 1}])
        assert parent.indirectInputs.call_count == 1

    def test_the_build_wires_the_connector(self, monkeypatch):
        parent, items, probe = self._network(monkeypatch)
        monkeypatch.setattr(graph, "place_new_nodes", lambda nodes: None)
        monkeypatch.setattr(graph, "layout_if_enabled", lambda *a, **k: None)
        result = graph.build_network(
            "/obj/geo1/subnet1",
            [{"type": "matchsize", "name": "ms", "inputs": [{"indirect_input": 2, "index": 1}]}],
        )
        assert result["success"] is True, result
        probe.setInput.assert_any_call(1, items[2], 0)


class TestAnOlderPlugin:
    """The compatibility check compares command names, and connect_nodes
    exists on a plugin that predates indirect_input."""

    @pytest.mark.asyncio
    async def test_a_rejected_indirect_input_names_the_plugin_as_the_cause(
        self, mock_ctx, mock_bridge
    ):
        from fxhoudinimcp.errors import HoudiniCommandError
        from fxhoudinimcp.tools.nodes import connect_nodes

        mock_bridge.execute.side_effect = HoudiniCommandError(
            "nodes.connect_nodes was called with the wrong arguments "
            "(got an unexpected keyword argument 'indirect_input').",
            code="BAD_ARGUMENTS",
        )
        with pytest.raises(HoudiniCommandError, match="plugin predates indirect_input"):
            await connect_nodes(
                mock_ctx, "/obj/geo1/subnet1", "/obj/geo1/subnet1/ms", indirect_input=0
            )

    @pytest.mark.asyncio
    async def test_other_errors_pass_through_untouched(self, mock_ctx, mock_bridge):
        from fxhoudinimcp.errors import HoudiniCommandError
        from fxhoudinimcp.tools.nodes import connect_nodes

        mock_bridge.execute.side_effect = HoudiniCommandError(
            "Node not found", code="COMMAND_ERROR"
        )
        with pytest.raises(HoudiniCommandError, match="^Node not found$"):
            await connect_nodes(mock_ctx, "/obj/nope", "/obj/geo1/ms", indirect_input=0)
