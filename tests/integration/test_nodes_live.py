"""Live node-handler tests: verify returned claims against actual scene state."""

from __future__ import annotations

# Third-party
import hou
import pytest

pytestmark = pytest.mark.integration


def _make_geo(call, name: str = "geo1") -> str:
    data = call("nodes.create_node", parent_path="/obj", node_type="geo", name=name)
    return data["node_path"]


class TestCreateDelete:
    def test_create_node_exists_with_claimed_type(self, call):
        geo = _make_geo(call)
        box = call("nodes.create_node", parent_path=geo, node_type="box")
        node = hou.node(box["node_path"])
        assert node is not None
        assert node.type().name() == "box"
        assert box["node_type"] == "box"

    def test_create_node_honors_position(self, call):
        geo = _make_geo(call)
        box = call(
            "nodes.create_node",
            parent_path=geo,
            node_type="box",
            position=[4.0, -2.0],
        )
        assert tuple(hou.node(box["node_path"]).position()) == (4.0, -2.0)

    def test_create_node_unknown_type_is_clean_error(self, call):
        error = call(
            "nodes.create_node",
            parent_path="/obj",
            node_type="definitely_not_a_real_node",
            expect_error=True,
        )
        assert "definitely_not_a_real_node" in error["message"]

    def test_delete_node_removes_it(self, call):
        _make_geo(call, name="doomed")
        call("nodes.delete_node", node_path="/obj/doomed")
        assert hou.node("/obj/doomed") is None

    def test_rename_node(self, call):
        _make_geo(call, name="before")
        call("nodes.rename_node", node_path="/obj/before", new_name="after")
        assert hou.node("/obj/before") is None
        assert hou.node("/obj/after") is not None

    def test_copy_node_creates_independent_copy(self, call):
        geo = _make_geo(call)
        box = call("nodes.create_node", parent_path=geo, node_type="box")
        copy = call("nodes.copy_node", node_path=box["node_path"])
        copied = hou.node(copy["copied_path"])
        assert copied is not None
        assert copied.path() != box["node_path"]
        assert copied.type().name() == "box"

    def test_copy_node_lands_beside_its_original(self, call):
        geo = _make_geo(call)
        box = call("nodes.create_node", parent_path=geo, node_type="box", position=[3.0, -2.0])
        copy = call("nodes.copy_node", node_path=box["node_path"])
        copied = hou.node(copy["copied_path"])
        assert copied.position()[0] > 3.0  # not on top of the original
        assert copied.position()[1] == -2.0
        assert copy["position"] == list(copied.position())

    def test_copy_node_honors_offset(self, call):
        geo = _make_geo(call)
        box = call("nodes.create_node", parent_path=geo, node_type="box", position=[3.0, -2.0])
        copy = call("nodes.copy_node", node_path=box["node_path"], offset=[0.0, -5.0])
        assert tuple(hou.node(copy["copied_path"]).position()) == (3.0, -7.0)


class TestWiring:
    def test_connect_nodes_wires_claimed_inputs(self, call):
        geo = _make_geo(call)
        a = call("nodes.create_node", parent_path=geo, node_type="box")["node_path"]
        b = call("nodes.create_node", parent_path=geo, node_type="sphere")["node_path"]
        m = call("nodes.create_node", parent_path=geo, node_type="merge")["node_path"]
        call("nodes.connect_nodes", source_path=a, dest_path=m, input_index=0)
        call("nodes.connect_nodes", source_path=b, dest_path=m, input_index=1)
        assert [n.path() for n in hou.node(m).inputs()] == [a, b]

    def test_disconnect_node_removes_input(self, call):
        geo = _make_geo(call)
        a = call("nodes.create_node", parent_path=geo, node_type="box")["node_path"]
        x = call("nodes.create_node", parent_path=geo, node_type="xform")["node_path"]
        call("nodes.connect_nodes", source_path=a, dest_path=x)
        call("nodes.disconnect_node", node_path=x, input_index=0)
        assert hou.node(x).inputs() == ()

    def test_set_node_flags_bypass_is_real(self, call):
        geo = _make_geo(call)
        box = call("nodes.create_node", parent_path=geo, node_type="box")["node_path"]
        call("nodes.set_node_flags", node_path=box, bypass=True)
        assert hou.node(box).isBypassed() is True

    def test_set_node_position_is_applied(self, call):
        geo = _make_geo(call)
        box = call("nodes.create_node", parent_path=geo, node_type="box")["node_path"]
        call("nodes.set_node_position", node_path=box, x=1.5, y=-3.0)
        assert tuple(hou.node(box).position()) == (1.5, -3.0)


class TestDiscovery:
    def test_find_nodes_returns_only_existing_paths(self, call):
        geo = _make_geo(call)
        call("nodes.create_node", parent_path=geo, node_type="box", name="findme1")
        call("nodes.create_node", parent_path=geo, node_type="box", name="findme2")
        data = call("nodes.find_nodes", pattern="findme*")
        assert data["count"] == 2
        for summary in data["nodes"]:
            assert hou.node(summary["path"]) is not None

    def test_list_node_types_names_are_instantiable(self, call):
        data = call("nodes.list_node_types", context="Sop", filter="scatter")
        names = [t["name"] for t in data["types"]]
        assert any(n.startswith("scatter") for n in names)
        category = hou.nodeTypeCategories()["Sop"]
        for name in names:
            assert name in category.nodeTypes(), f"claimed type {name} does not exist"

    def test_get_node_info_matches_reality(self, call):
        geo = _make_geo(call, name="infogeo")
        data = call("nodes.get_node_info", node_path=geo)
        assert data["name"] == "infogeo"
        assert data["node_path"] == "/obj/infogeo"
        assert data["type"]["name"] == "geo"

    def test_list_children_counts_match(self, call):
        geo = _make_geo(call)
        for _ in range(3):
            call("nodes.create_node", parent_path=geo, node_type="box")
        data = call("nodes.list_children", parent_path=geo)
        assert len(hou.node(geo).children()) == 3
        children = data.get("children", data.get("nodes", []))
        assert len(children) == 3


class TestChangeNodeType:
    def test_swap_keeps_wires_and_names_what_was_lost(self, call):
        geo = _make_geo(call)
        box = hou.node(geo).createNode("box")
        null = hou.node(geo).createNode("null")
        null.setInput(0, box)
        box.parm("tx").set(5)
        box.parm("sizex").set(3)
        data = call("nodes.change_node_type", node_path=box.path(), new_type="tube")
        node = hou.node(data["node_path"])
        assert node.type().name() == "tube"
        assert data["changed"] is True
        assert null.inputs()[0].path() == node.path()
        assert node.parm("tx").eval() == 5
        # sizex has no home on a tube: it is named, not silently lost.
        assert "sizex" in data["parms_dropped"]
        assert "tx" not in data["parms_dropped"] + data["parms_reset"]

    def test_same_type_is_a_no_op_with_the_full_reply(self, call):
        geo = _make_geo(call)
        box = hou.node(geo).createNode("box")
        data = call("nodes.change_node_type", node_path=box.path(), new_type="box")
        assert data["changed"] is False
        assert data["parms_dropped"] == [] and data["parms_reset"] == []
        assert "message" in data

    def test_spare_parms_survive_the_swap(self, call):
        geo = _make_geo(call)
        null = hou.node(geo).createNode("null")
        group = null.parmTemplateGroup()
        group.append(hou.FloatParmTemplate("tweak", "Tweak", 1))
        null.setParmTemplateGroup(group)
        null.parm("tweak").set(3.0)
        data = call("nodes.change_node_type", node_path=null.path(), new_type="xform")
        assert hou.node(data["node_path"]).parm("tweak").eval() == 3.0
        assert "tweak" not in data["parms_dropped"] + data["parms_reset"]


class TestPressButton:
    def test_errors_are_stale_until_cooked(self, call):
        geo = _make_geo(call)
        file_sop = hou.node(geo).createNode("file")
        file_sop.parm("file").set("/nonexistent/fxh_press_button.bgeo")
        data = call("nodes.press_button", node_path=file_sop.path(), parm_name="reload")
        assert data["cooked"] is False
        assert data["needs_cook"] is True
        # Reload is handled in C++: no script callback, and still not inert.
        assert data["has_script_callback"] is False

        data = call("nodes.press_button", node_path=file_sop.path(), parm_name="reload", cook=True)
        assert data["cooked"] is True
        assert any("fxh_press_button" in e for e in data["errors"])

    def test_an_unsupported_argument_type_is_refused_before_pressing(self, call):
        geo = _make_geo(call)
        file_sop = hou.node(geo).createNode("file")
        error = call(
            "nodes.press_button",
            node_path=file_sop.path(),
            parm_name="reload",
            arguments={"items": [1, 2]},
            expect_error=True,
        )
        assert "items" in error["message"] and "list" in error["message"]


class TestSubnetInputConnectors:
    def _subnet(self):
        geo = hou.node("/obj").createNode("geo")
        subnet = geo.createNode("subnet")
        inner = subnet.createNode("null")
        return geo, subnet, inner

    def _wires(self, node):
        return [(c.inputIndex(), type(c.inputItem()).__name__) for c in node.inputConnections()]

    def test_the_wire_is_made_and_can_be_removed(self, call):
        _, subnet, inner = self._subnet()
        data = call(
            "nodes.connect_nodes",
            source_path=subnet.path(),
            dest_path=inner.path(),
            indirect_input=0,
        )
        assert data["source_path"] == subnet.path()
        assert self._wires(inner) == [(0, "OpSubnetIndirectInput")]
        # inputs() hides this wire; disconnect_node must still find it.
        assert inner.inputs() == ()
        call("nodes.disconnect_node", node_path=inner.path(), disconnect_all=True)
        assert self._wires(inner) == []

    def test_reorder_keeps_the_connector(self, call):
        _, subnet, inner = self._subnet()
        other = subnet.createNode("box")
        merge = subnet.createNode("merge")
        merge.setInput(0, subnet.indirectInputs()[0])
        merge.setInput(1, other)
        call("nodes.reorder_inputs", node_path=merge.path(), new_order=[1, 0])
        assert merge.inputConnections()[0].inputItem() == other
        assert type(merge.inputConnections()[1].inputItem()).__name__ == "OpSubnetIndirectInput"

    def test_a_destination_outside_the_subnet_is_refused_by_name(self, call):
        geo, subnet, _ = self._subnet()
        box = geo.createNode("box")
        error = call(
            "nodes.connect_nodes",
            source_path=subnet.path(),
            dest_path=box.path(),
            indirect_input=0,
            expect_error=True,
        )
        assert "is not inside" in error["message"]

    def test_build_network_wires_from_the_connector(self, call):
        _, subnet, _ = self._subnet()
        call(
            "graph.build_network",
            parent_path=subnet.path(),
            nodes=[{"type": "null", "name": "fed", "inputs": [{"indirect_input": 0}]}],
        )
        assert self._wires(subnet.node("fed")) == [(0, "OpSubnetIndirectInput")]
