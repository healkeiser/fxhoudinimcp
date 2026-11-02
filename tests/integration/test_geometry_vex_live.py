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


class TestAttribStats:
    """Aggregates instead of 60k raw values.

    get_geometry_info named the attributes and get_attrib_values returned every
    value, so proving a field had plausible magnitudes meant execute_python.
    """

    @pytest.fixture
    def scattered(self, call) -> str:
        geo = call("nodes.create_node", parent_path="/obj", node_type="geo", name="stats1")[
            "node_path"
        ]
        built = call(
            "graph.build_network",
            parent_path=geo,
            nodes=[
                {"type": "grid", "name": "g", "parms": {"rows": 20, "cols": 20}},
                {"type": "scatter", "name": "s", "inputs": ["g"], "parms": {"npts": 500}},
                {
                    "type": "attribwrangle",
                    "name": "vals",
                    "inputs": ["s"],
                    "parms": {
                        "class": 2,
                        "snippet": "@heat = @ptnum; v@vel = set(@ptnum, -@ptnum, 1.0);",
                    },
                    "flags": {"display": True},
                },
            ],
        )
        assert built["valid"], built
        return f"{geo}/vals"

    def test_scalar_min_max_mean_sum(self, call, scattered):
        result = call("geometry.get_attrib_stats", node_path=scattered, attribs=["heat"])
        heat = result["stats"]["heat"]
        # @heat = @ptnum over 500 points: 0..499, summing to 499*500/2.
        assert heat["min"] == 0.0
        assert heat["max"] == 499.0
        assert heat["sum"] == pytest.approx(499 * 500 / 2)
        assert heat["mean"] == pytest.approx(249.5)

    def test_vector_reports_per_component_ranges(self, call, scattered):
        result = call("geometry.get_attrib_stats", node_path=scattered, attribs=["vel"])
        vel = result["stats"]["vel"]
        assert vel["size"] == 3
        components = vel["per_component"]
        assert components[0]["max"] == 499.0
        # y is -ptnum, so its minimum is the negative extreme.
        assert components[1]["min"] == -499.0
        assert components[2]["min"] == components[2]["max"] == 1.0

    def test_missing_attribute_is_named_not_raised(self, call, scattered):
        result = call("geometry.get_attrib_stats", node_path=scattered, attribs=["heat", "nope"])
        assert result["missing"] == ["nope"]
        assert "heat" in result["stats"]

    def test_string_attributes_are_skipped_not_crashed(self, call, scattered):
        node = hou.node(scattered)
        wrangle = node.createOutputNode("attribwrangle", "names")
        wrangle.parm("class").set(2)
        wrangle.parm("snippet").set('s@label = "x";')
        wrangle.setDisplayFlag(True)
        result = call("geometry.get_attrib_stats", node_path=wrangle.path(), attribs=["label"])
        assert result["stats"]["label"] == {"skipped": "not numeric"}

    def test_several_nodes_over_several_frames_in_one_call(self, call, scattered):
        timed = hou.node(scattered).createOutputNode("attribwrangle", "timed")
        timed.parm("class").set(2)
        timed.parm("snippet").set("@heat = @Frame;")
        missing = scattered.rsplit("/", 1)[0] + "/nope"
        hou.setFrame(5)
        result = call(
            "geometry.get_attrib_stats",
            node_paths=[timed.path(), scattered, missing],
            frames=[3, 1, 2],
            attribs=["heat"],
        )
        assert result["frames"] == [1.0, 2.0, 3.0]
        timed_rows = [row for row in result["rows"] if row["node_path"] == timed.path()]
        assert [row["stats"]["heat"]["mean"] for row in timed_rows] == [1.0, 2.0, 3.0]
        still = [row for row in result["rows"] if row["node_path"] == scattered]
        assert all(row["stats"]["heat"]["max"] == 499.0 for row in still)
        failed = [row for row in result["rows"] if row["node_path"] == missing]
        assert len(failed) == 3 and all(row["error"] for row in failed)
        assert hou.frame() == 5.0
        assert result["frame_restored"] == 5.0

    def test_percentiles_give_the_median(self, call, scattered):
        result = call(
            "geometry.get_attrib_stats",
            node_path=scattered,
            attribs=["heat", "vel"],
            percentiles=[0, 50, 100],
        )
        heat = result["stats"]["heat"]["percentiles"]
        assert heat["0"] == 0.0 and heat["100"] == 499.0
        assert heat["50"] == pytest.approx(249.5)
        assert result["stats"]["vel"]["percentiles"]["50"] == pytest.approx([249.5, -249.5, 1.0])

    def test_a_percentile_outside_0_100_is_refused(self, call, scattered):
        error = call(
            "geometry.get_attrib_stats", expect_error=True, node_path=scattered, percentiles=[150]
        )
        assert "0..100" in error["message"]


class TestVolumeInfo:
    """Per-volume identity, not just a primitive count."""

    @pytest.fixture
    def volumes(self, call) -> str:
        geo = call("nodes.create_node", parent_path="/obj", node_type="geo", name="vol1")[
            "node_path"
        ]
        built = call(
            "graph.build_network",
            parent_path=geo,
            nodes=[
                {"type": "sphere", "name": "s", "parms": {"type": "polymesh", "rows": 20}},
                {
                    "type": "vdbfrompolygons",
                    "name": "vdb",
                    "inputs": ["s"],
                    "flags": {"display": True},
                },
            ],
        )
        assert built["valid"], built
        return f"{geo}/vdb"

    def test_names_resolution_and_voxel_counts(self, call, volumes):
        result = call("geometry.get_volume_info", node_path=volumes)
        assert result["volume_count"] >= 1
        entry = result["volumes"][0]
        assert entry["name"], entry
        # A VDB built from a real sphere must have active voxels; zero here is
        # exactly the empty-field bug this tool exists to catch.
        assert entry["active_voxels"] > 0, entry

    def test_the_grid_is_placed_by_its_voxel_centres(self, call, volumes):
        entry = call("geometry.get_volume_info", node_path=volumes)["volumes"][0]
        prim = hou.node(volumes).geometry().prims()[0]
        box = prim.activeVoxelBoundingBox()
        first = prim.indexToPos(tuple(int(c) for c in box.minvec()))
        last = prim.indexToPos(tuple(int(c) - 1 for c in box.maxvec()))
        assert entry["voxel_size"] == pytest.approx(list(prim.voxelSize()), rel=1e-6)
        assert entry["first_voxel_center"] == pytest.approx(list(first), abs=1e-5)
        assert entry["last_voxel_center"] == pytest.approx(list(last), abs=1e-5)
        # The centres sit half a voxel inside the bbox.
        half = entry["voxel_size"][0] / 2
        assert entry["first_voxel_center"][0] == pytest.approx(
            entry["bbox_min"][0] + half, abs=1e-4
        )

    def test_no_volumes_is_an_empty_answer_not_an_error(self, call):
        geo = call("nodes.create_node", parent_path="/obj", node_type="geo", name="novol")[
            "node_path"
        ]
        box = hou.node(geo).createNode("box")
        box.setDisplayFlag(True)
        result = call("geometry.get_volume_info", node_path=box.path())
        assert result["volume_count"] == 0
        assert result["volumes"] == []


class TestVolumeMeasurements:
    """Sum, threshold box, sampling and comparison, on known geometry.

    A 1-unit box centred on x=1 as a filled fog VDB and a dense iso volume,
    and a 0.3 sphere SDF at the same centre as the collider.
    """

    @pytest.fixture
    def scene(self, call) -> str:
        geo = call("nodes.create_node", parent_path="/obj", node_type="geo")["node_path"]
        built = call(
            "graph.build_network",
            parent_path=geo,
            nodes=[
                {"type": "box", "name": "box1", "parms": {"t": [1, 0, 0]}},
                {
                    "type": "vdbfrompolygons",
                    "name": "fog",
                    "inputs": ["box1"],
                    "parms": {"builddistance": 0, "buildfog": 1, "fillinterior": 1},
                },
                {"type": "isooffset", "name": "dense", "inputs": ["box1"]},
                {
                    "type": "sphere",
                    "name": "ball",
                    "parms": {"t": [1, 0, 0], "rad": [0.3, 0.3, 0.3], "type": "polymesh"},
                },
                {
                    "type": "vdbfrompolygons",
                    "name": "collider",
                    "inputs": ["ball"],
                    "parms": {"voxelsize": 0.05, "fillinterior": 1},
                },
            ],
        )
        assert built["valid"], built
        return geo

    def test_sum_is_given_without_reading_voxels(self, call, scene):
        entry = call("geometry.get_volume_info", node_path=f"{scene}/fog")["volumes"][0]
        assert "voxel_stats" not in entry
        assert entry["sum"] == pytest.approx(entry["mean_value"] * entry["active_voxels"])

    @pytest.mark.parametrize("node", ["fog", "dense"])
    def test_threshold_box_is_where_the_box_is(self, call, scene, node):
        entry = call(
            "geometry.get_volume_info", node_path=f"{scene}/{node}", threshold=0.5, bins=4
        )["volumes"][0]
        stats = entry["voxel_stats"]
        assert stats["sum"] == pytest.approx(entry["sum"], rel=1e-4)
        assert sum(b["count"] for b in stats["histogram"]) == stats["count"]
        box = entry["box_above_threshold"]
        # Centred on x=1 and inside the unit box: a swapped axis or a dropped
        # VDB index origin puts it elsewhere.
        assert (box["min"][0] + box["max"][0]) / 2 == pytest.approx(1.0, abs=0.06)
        assert box["min"][0] >= 0.45 and box["max"][0] <= 1.55
        assert abs(box["min"][1]) <= 0.55 and abs(box["max"][2]) <= 0.55

    def test_sample_reads_inside_and_outside(self, call, scene):
        result = call(
            "geometry.sample_volume",
            node_path=f"{scene}/fog",
            fields=["density"],
            positions=[[1, 0, 0], [5, 0, 0]],
        )
        inside, outside = result["values"]["density"]
        assert inside == pytest.approx(1.0, abs=0.05)
        assert outside == 0.0

    def test_sample_names_the_fields_there_are(self, call, scene):
        result = call(
            "geometry.sample_volume",
            node_path=f"{scene}/fog",
            fields=["nope"],
            positions=[[0, 0, 0]],
            expect_error=True,
        )
        assert "density" in result["message"]

    def test_compare_puts_some_density_inside_the_collider(self, call, scene):
        result = call(
            "geometry.compare_volumes",
            node_path=f"{scene}/fog",
            field="density",
            against="surface",
            against_node=f"{scene}/collider",
            bands=[-1000, 0, 1000],
        )
        inside, outside = result["bands"]
        assert inside["samples"] > 0 and outside["samples"] > inside["samples"]
        assert inside["field_total"] + outside["field_total"] == pytest.approx(
            result["field_total"]
        )
