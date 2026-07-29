"""Live geometry and VEX handler tests against cooked SOP geometry."""

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


class TestGeometry:
    def test_geometry_info_counts_match_a_box(self, call, box):
        data = call("geometry.get_geometry_info", node_path=box)
        flat = str(data)
        assert "8" in flat and "6" in flat, f"expected 8 points/6 prims in {data}"

    def test_get_points_returns_eight_positions(self, call, box):
        data = call("geometry.get_points", node_path=box)
        points = data.get("points", data)
        assert len(points) == 8

    def test_bounding_box_is_unit_box(self, call, box):
        data = call("geometry.get_bounding_box", node_path=box)
        flat = str(data)
        assert "0.5" in flat and "-0.5" in flat, f"unexpected bbox: {data}"

    def test_set_detail_attrib_is_readable_from_geometry(self, call, box):
        data = call(
            "geometry.set_detail_attrib",
            node_path=box,
            attrib_name="shot_name",
            value="sh010",
        )
        attrib_node = hou.node(data["attrib_node_path"])
        assert attrib_node is not None
        assert attrib_node.geometry().attribValue("shot_name") == "sh010"
        assert data["value"] == "sh010"

    def test_sample_geometry_count_is_honest(self, call, box):
        data = call("geometry.sample_geometry", node_path=box, sample_count=4)
        assert data["sample_count"] == 4
        assert len(data["points"]) == 4
        assert all("P" in row for row in data["points"])

    def test_get_points_pagination_offsets_correctly(self, call, box):
        data = call("geometry.get_points", node_path=box, start=4, count=10)
        assert data["total_points"] == 8
        assert [row["index"] for row in data["points"]] == [4, 5, 6, 7]
        assert data["has_more"] is False
        node = hou.node(box)
        expected = list(node.geometry().point(4).position())
        assert data["points"][0]["P"] == pytest.approx(expected)

    def test_get_prims_pagination_offsets_correctly(self, call, box):
        data = call("geometry.get_prims", node_path=box, start=2, count=2)
        assert data["total_prims"] == 6
        assert [row["index"] for row in data["prims"]] == [2, 3]
        assert data["has_more"] is True

    def test_find_nearest_point_finds_exact_corner(self, call, box):
        data = call(
            "geometry.find_nearest_point",
            node_path=box,
            position=[0.5, 0.5, 0.5],
        )
        result = data["results"][0]
        assert result["position"] == pytest.approx([0.5, 0.5, 0.5])
        assert result["distance"] == pytest.approx(0.0)
        corner = hou.node(box).geometry().point(result["index"]).position()
        assert list(corner) == pytest.approx([0.5, 0.5, 0.5])

    def test_prim_intrinsics_summary_counts_box(self, call, box):
        data = call("geometry.get_prim_intrinsics", node_path=box)
        assert data["total_prims"] == 6
        assert data["summary"], "no intrinsics summarized"


class TestVex:
    def test_create_wrangle_with_valid_code_reports_valid(self, call, box):
        data = call(
            "vex.create_wrangle",
            parent_path="/obj/geo1",
            vex_code="@Cd = {1, 0, 0};",
            run_over="Points",
            name="red_wrangle",
        )
        assert data["vex_valid"] is True, data
        wrangle = hou.node(data["node_path"])
        assert wrangle is not None
        # Wire it after the box and confirm the attribute really appears.
        call(
            "nodes.connect_nodes",
            source_path=box,
            dest_path=data["node_path"],
        )
        geometry = wrangle.geometry()
        assert geometry.findPointAttrib("Cd") is not None

    def test_create_wrangle_with_broken_code_reports_invalid(self, call, box):
        data = call(
            "vex.create_wrangle",
            parent_path="/obj/geo1",
            vex_code="@P = ;  // syntax error",
            run_over="Points",
            name="broken_wrangle",
        )
        assert data["vex_valid"] is False, (
            f"validate claimed broken VEX is valid — hallucinated success: {data}"
        )
        assert data["vex_errors"], "no errors reported for broken VEX"

    def test_absolute_channel_path_warning_fires(self, call, box):
        data = call(
            "vex.create_wrangle",
            parent_path="/obj/geo1",
            vex_code='float s = ch("/obj/geo1/box1/scale"); @P *= s;',
            run_over="Points",
            name="abs_ch_wrangle",
        )
        warnings = " ".join(str(w) for w in data.get("vex_warnings", []))
        assert "absolute channel path" in warnings


class TestCode:
    def test_execute_python_returns_expression_value(self, call):
        data = call(
            "code.execute_python",
            code="count = len(hou.node('/obj').children())",
            return_expression="count",
        )
        assert str(len(hou.node("/obj").children())) in str(data)

    def test_evaluate_expression_hscript(self, call):
        hou.setFrame(42)
        data = call("code.evaluate_expression", expression="$F")
        assert "42" in str(data)
