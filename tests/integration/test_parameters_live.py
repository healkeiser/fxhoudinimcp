"""Live parameter-handler tests: returned values must match hou state."""

from __future__ import annotations

# Third-party
import hou
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def box(call) -> str:
    geo = call("nodes.create_node", parent_path="/obj", node_type="geo", name="geo1")
    data = call("nodes.create_node", parent_path=geo["node_path"], node_type="box")
    return data["node_path"]


class TestSetGet:
    def test_set_parameter_float_is_applied(self, call, box):
        call("parameters.set_parameter", node_path=box, parm_name="scale", value=2.5)
        assert hou.node(box).parm("scale").eval() == 2.5

    def test_set_parameter_string_is_applied(self, call, box):
        geo = call("nodes.create_node", parent_path="/obj", node_type="geo", name="geo2")
        file_sop = call("nodes.create_node", parent_path=geo["node_path"], node_type="file")
        call(
            "parameters.set_parameter",
            node_path=file_sop["node_path"],
            parm_name="file",
            value="$HIP/geo/test.bgeo",
        )
        parm = hou.node(file_sop["node_path"]).parm("file")
        assert parm.rawValue() == "$HIP/geo/test.bgeo"

    def test_get_parameter_roundtrip(self, call, box):
        call("parameters.set_parameter", node_path=box, parm_name="sizex", value=3.0)
        data = call("parameters.get_parameter", node_path=box, parm_name="sizex")
        assert data["value"] == 3.0

    def test_set_parameter_list_on_vector_parm(self, call, box):
        """A list value addressed at a vector parm sets the whole tuple,
        as the MCP tool docstring promises."""
        data = call(
            "parameters.set_parameter",
            node_path=box,
            parm_name="size",
            value=[1.0, 2.0, 3.0],
        )
        assert data["new_value"] == [1.0, 2.0, 3.0]
        node = hou.node(box)
        assert [node.parm(f"size{c}").eval() for c in "xyz"] == [1.0, 2.0, 3.0]

    def test_set_parameter_wrong_component_count_is_clean_error(self, call, box):
        error = call(
            "parameters.set_parameter",
            node_path=box,
            parm_name="size",
            value=[1.0, 2.0],
            expect_error=True,
        )
        assert "components" in error["message"]

    def test_set_parameters_batch_applies_all(self, call, box):
        call(
            "parameters.set_parameters",
            node_path=box,
            params={"sizex": 2.0, "sizey": 4.0, "sizez": 6.0},
        )
        node = hou.node(box)
        assert [node.parm(n).eval() for n in ("sizex", "sizey", "sizez")] == [
            2.0,
            4.0,
            6.0,
        ]

    def test_unknown_parm_suggests_close_match(self, call, box):
        error = call(
            "parameters.set_parameter",
            node_path=box,
            parm_name="sizx",
            value=1.0,
            expect_error=True,
        )
        assert "sizex" in error["message"]


class TestExpressionsAndLinks:
    def test_set_expression_evaluates(self, call, box):
        call(
            "parameters.set_expression",
            node_path=box,
            parm_name="tx",
            expression="$F * 2",
        )
        hou.setFrame(5)
        assert hou.node(box).parm("tx").eval() == 10.0

    def test_link_parameters_creates_live_reference(self, call, box):
        geo2 = call("nodes.create_node", parent_path="/obj", node_type="geo", name="geo2")
        box2 = call("nodes.create_node", parent_path=geo2["node_path"], node_type="box")[
            "node_path"
        ]
        call("parameters.set_parameter", node_path=box, parm_name="sizex", value=7.0)
        call(
            "parameters.link_parameters",
            source_path=box,
            source_parm="sizex",
            dest_path=box2,
            dest_parm="sizex",
        )
        assert hou.node(box2).parm("sizex").eval() == 7.0
        call("parameters.set_parameter", node_path=box, parm_name="sizex", value=9.0)
        assert hou.node(box2).parm("sizex").eval() == 9.0

    def test_lock_parameter_prevents_edits(self, call, box):
        call("parameters.lock_parameter", node_path=box, parm_name="sizex", locked=True)
        assert hou.node(box).parm("sizex").isLocked() is True


class TestSpareParameters:
    def test_create_spare_parameter_with_default(self, call, box):
        call(
            "parameters.create_spare_parameter",
            node_path=box,
            parm_name="my_amount",
            parm_type="float",
            label="My Amount",
            default_value=0.75,
            min_val=0.0,
            max_val=1.0,
        )
        parm = hou.node(box).parm("my_amount")
        assert parm is not None
        assert parm.eval() == 0.75


class TestGetParametersBulk:
    """Reading was one parm per call while writing was already batch."""

    def test_patterns_match_name_or_label(self, call):
        geo = call("nodes.create_node", parent_path="/obj", node_type="geo", name="parms1")[
            "node_path"
        ]
        box = hou.node(geo).createNode("box")
        result = call("parameters.get_parameters", node_path=box.path(), patterns=["size", "t"])
        names = set(result["parameters"])
        assert "sizex" in names, names
        assert result["matched"] >= len(names)

    def test_omitting_patterns_returns_everything_up_to_the_cap(self, call):
        geo = call("nodes.create_node", parent_path="/obj", node_type="geo", name="parms2")[
            "node_path"
        ]
        box = hou.node(geo).createNode("box")
        result = call("parameters.get_parameters", node_path=box.path())
        assert result["returned"] > 5
        assert result["patterns"] is None

    def test_values_are_live_not_defaults(self, call):
        geo = call("nodes.create_node", parent_path="/obj", node_type="geo", name="parms3")[
            "node_path"
        ]
        box = hou.node(geo).createNode("box")
        box.parm("sizex").set(7.5)
        result = call(
            "parameters.get_parameters",
            node_path=box.path(),
            patterns=["sizex"],
            include_defaults=True,
        )
        entry = result["parameters"]["sizex"]
        assert entry["value"] == pytest.approx(7.5)
        assert entry["is_at_default"] is False


class TestMultiparmInstanceDiscovery:
    """The recorded failure case: naming a multiparm instance parameter.

    A session spent three execute_python calls discovering that the pyro
    solver's sourcing bindings are source_volume1..4. get_node_card cannot help,
    because instance parameters exist on a node, not on its type.
    """

    def test_sourcing_bindings_are_findable_without_python(self, call):
        geo = call("nodes.create_node", parent_path="/obj", node_type="geo", name="mp1")[
            "node_path"
        ]
        solver = hou.node(geo).createNode("pyrosolver")
        result = call("parameters.get_parameters", node_path=solver.path(), patterns=["source"])
        names = set(result["parameters"])
        assert "source_volume1" in names, sorted(names)[:12]
        # The count parm that governs how many instances exist.
        counts = call("parameters.get_parameters", node_path=solver.path(), patterns=["numsources"])
        assert "numsources" in counts["parameters"]
