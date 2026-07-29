"""Live tests for the graph intelligence commands.

build_network must validate before mutating, build atomically, and
report cooked evidence; node cards must be version-exact; the profiler
must actually find the expensive node.
"""

from __future__ import annotations

# Third-party
import hou
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def geo(call) -> str:
    return call("nodes.create_node", parent_path="/obj", node_type="geo", name="geo1")["node_path"]


class TestBuildNetworkValidation:
    def test_dry_run_catches_everything_and_mutates_nothing(self, call, geo):
        result = call(
            "graph.build_network",
            parent_path=geo,
            dry_run=True,
            nodes=[
                {"type": "box", "name": "b"},
                {"type": "not_a_real_sop", "name": "x"},
                {
                    "type": "scatter",
                    "name": "s",
                    "parms": {"nptss": 50},
                    "inputs": ["b", "ghost_node"],
                },
            ],
        )
        assert result["valid"] is False
        flat = " ".join(result["errors"])
        assert "not_a_real_sop" in flat
        assert "nptss" in flat and "npts" in flat, f"no did-you-mean: {flat}"
        assert "ghost_node" in flat
        assert len(hou.node(geo).children()) == 0, "dry_run mutated the scene"

    def test_invalid_spec_builds_nothing_even_without_dry_run(self, call, geo):
        result = call(
            "graph.build_network",
            parent_path=geo,
            nodes=[{"type": "box"}, {"type": "definitely_fake"}],
        )
        assert result["valid"] is False
        assert len(hou.node(geo).children()) == 0, "invalid spec half-built"

    def test_valid_dry_run_reports_resolved_types(self, call, geo):
        result = call(
            "graph.build_network",
            parent_path=geo,
            dry_run=True,
            nodes=[{"type": "copytopoints", "name": "c"}],
        )
        assert result["valid"] is True
        assert any(t.startswith("copytopoints") for t in result["validated_types"])
        assert len(hou.node(geo).children()) == 0


class TestBuildNetworkBuild:
    def test_full_network_in_one_call_with_evidence(self, call, geo):
        result = call(
            "graph.build_network",
            parent_path=geo,
            nodes=[
                {
                    "type": "grid",
                    "name": "ground",
                    "parms": {"rows": 30, "cols": 30, "size": [8.0, 8.0]},
                },
                {
                    "type": "mountain",
                    "name": "shape",
                    "inputs": ["ground"],
                    "parms": {"height": 1.5},
                },
                {"type": "scatter", "name": "pts", "inputs": ["shape"], "parms": {"npts": 64}},
                {"type": "box", "name": "pebble", "parms": {"scale": 0.1}},
                {
                    "type": "copytopoints",
                    "name": "copies",
                    "inputs": ["pebble", "pts"],
                    "flags": {"display": True, "render": True},
                    "color": [0.2, 0.6, 0.9],
                    "comment": "built atomically",
                },
            ],
        )
        assert result["valid"] is True, result.get("errors")
        assert result["node_count"] == 5
        assert result["error_nodes"] == [], result["error_nodes"]

        # Claims vs reality
        copies = hou.node(f"{geo}/copies")
        assert copies.isDisplayFlagSet()
        assert [n.name() for n in copies.inputs()] == ["pebble", "pts"]
        assert hou.node(f"{geo}/ground").parmTuple("size").eval() == (8.0, 8.0)
        assert result["geometry"]["points"] == 64 * 8
        assert list(copies.color().rgb()) == pytest.approx([0.2, 0.6, 0.9])

    def test_existing_name_collision_is_rejected(self, call, geo):
        call("nodes.create_node", parent_path=geo, node_type="box", name="taken")
        result = call(
            "graph.build_network",
            parent_path=geo,
            nodes=[{"type": "sphere", "name": "taken"}],
        )
        assert result["valid"] is False
        assert "taken" in " ".join(result["errors"])

    def test_input_can_reference_existing_child(self, call, geo):
        existing = call("nodes.create_node", parent_path=geo, node_type="box", name="base")[
            "node_path"
        ]
        result = call(
            "graph.build_network",
            parent_path=geo,
            nodes=[{"type": "xform", "name": "move", "inputs": ["base"]}],
        )
        assert result["valid"] is True, result.get("errors")
        assert hou.node(f"{geo}/move").inputs()[0].path() == existing


class TestVerifyNetwork:
    def test_reports_broken_nodes(self, call, geo):
        call("nodes.create_node", parent_path=geo, node_type="box", name="good")
        bad = call("nodes.create_node", parent_path=geo, node_type="file", name="bad")["node_path"]
        call(
            "parameters.set_parameter",
            node_path=bad,
            parm_name="file",
            value="/does/not/exist.bgeo",
        )
        call("nodes.set_node_flags", node_path=bad, display=True)
        report = call("graph.verify_network", parent_path=geo)
        assert report["healthy"] is False
        assert f"{geo}/bad" in report["error_nodes"]
        assert report["node_count"] == 2

    def test_healthy_network_reports_geometry(self, call, geo):
        call(
            "graph.build_network",
            parent_path=geo,
            nodes=[{"type": "box", "name": "b", "flags": {"display": True}}],
        )
        report = call("graph.verify_network", parent_path=geo)
        assert report["healthy"] is True
        assert report["geometry"]["points"] == 8


class TestNodeCard:
    def test_box_card_is_authoritative(self, call):
        card = call("graph.get_node_card", node_type="box", context="Sop")
        assert card["label"] == "Box"
        assert card["is_generator"] is True
        size = next(p for p in card["parms"] if p["name"] == "size")
        assert size["size"] == 3
        assert card["help"] and "cube" in card["help"].lower()

    def test_versioned_resolution_and_connector_labels(self, call):
        card = call("graph.get_node_card", node_type="copytopoints", context="Sop")
        assert card["type"].startswith("copytopoints::")
        assert card["max_inputs"] >= 2
        pack = call(
            "graph.get_node_card",
            node_type="copytopoints",
            context="Sop",
            parm_filter="pack",
        )
        assert any(p["name"] == "pack" for p in pack["parms"])

    def test_unknown_type_suggests_close_matches(self, call):
        error = call(
            "graph.get_node_card",
            node_type="scatterr",
            context="Sop",
            expect_error=True,
        )
        assert "scatter" in error["message"]


class TestExpensiveNodes:
    def test_profiler_finds_the_hotspot(self, call, geo):
        call(
            "graph.build_network",
            parent_path=geo,
            nodes=[
                {"type": "grid", "name": "g", "parms": {"rows": 400, "cols": 400}},
                {"type": "mountain", "name": "heavy", "inputs": ["g"]},
                {"type": "scatter", "name": "pts", "inputs": ["heavy"], "flags": {"display": True}},
            ],
        )
        result = call("graph.find_expensive_nodes", root_path=geo, limit=10)
        paths = [row["path"] for row in result["top_nodes"]]
        assert any("heavy" in p for p in paths), paths
        assert all(row["cook_ms"] >= 0.5 for row in result["top_nodes"])


class TestCookFrameRange:
    """Stepping a solver and measuring it, in one call.

    Six of thirteen execute_python calls in a recorded session were this: no
    tool cooked a sequential SOP solver across frames, and step_simulation
    refuses anything that is not a DOP network and measures nothing.
    """

    @pytest.fixture
    def animated(self, call, geo) -> str:
        """A sphere whose radius is driven by frame, so counts change over time."""
        built = call(
            "graph.build_network",
            parent_path=geo,
            nodes=[
                {"type": "sphere", "name": "src", "parms": {"type": "polymesh", "rows": 12}},
                {
                    "type": "attribwrangle",
                    "name": "mark",
                    "inputs": ["src"],
                    "parms": {
                        # class 2 is points; 0 is detail, which is why asking for
                        # point statistics on this attribute found nothing.
                        "class": 2,
                        "snippet": "@heat = @Frame * 2.0; @Cd = set(@heat, 0, 0);",
                    },
                    "flags": {"display": True},
                },
            ],
        )
        assert built["valid"], built
        return f"{geo}/mark"

    def test_reports_a_row_per_frame_with_cook_cost(self, call, animated):
        result = call("graph.cook_frame_range", node_path=animated, start=1, end=5)
        assert result["frames_cooked"] == 5
        assert [row["frame"] for row in result["frames"]] == [1.0, 2.0, 3.0, 4.0, 5.0]
        assert all("cook_ms" in row for row in result["frames"])
        assert result["total_cook_ms"] >= 0
        # The frame is deliberately left where the cook ended.
        assert result["current_frame"] == 5.0

    def test_attribute_aggregates_show_the_change_over_time(self, call, animated):
        result = call(
            "graph.cook_frame_range",
            node_path=animated,
            start=1,
            end=4,
            attribs=["heat"],
        )
        maxima = [row["attribs"]["heat"]["max"] for row in result["frames"]]
        # @heat = @Frame * 2, so the maximum must climb with the frame. This is
        # the evidence a caller wants and could not get before.
        assert maxima == sorted(maxima), maxima
        assert maxima[0] < maxima[-1], maxima

    def test_counts_come_back_per_frame(self, call, animated):
        result = call("graph.cook_frame_range", node_path=animated, start=1, end=2)
        for row in result["frames"]:
            assert row["points"] > 0
            assert row["prims"] > 0

    def test_range_cap_and_bad_input_are_clean_errors(self, call, animated):
        error = call(
            "graph.cook_frame_range",
            node_path=animated,
            start=1,
            end=5000,
            expect_error=True,
        )
        assert "cap" in error["message"].lower()

        error = call(
            "graph.cook_frame_range", node_path=animated, start=10, end=1, expect_error=True
        )
        assert "before" in error["message"].lower()

    def test_works_on_a_sequential_solver(self, call, geo):
        """The actual motivating case: a solver SOP accumulating over frames."""
        built = call(
            "graph.build_network",
            parent_path=geo,
            nodes=[
                {"type": "sphere", "name": "seed", "parms": {"type": "polymesh"}},
                {
                    "type": "attribwrangle",
                    "name": "init",
                    "inputs": ["seed"],
                    "parms": {"class": 2, "snippet": "@acc = 0;"},
                },
                {"type": "solver", "name": "sim", "inputs": ["init"], "flags": {"display": True}},
            ],
        )
        assert built["valid"], built
        solver = f"{geo}/sim"
        inside = hou.node(solver)
        # Solver SOP contents are a locked asset until editing is allowed.
        inside.allowEditingOfContents()
        # The editable SOP network is d/s, holding Prev_Frame -> OUT. Build INSIDE
        # it: createOutputNode on d/s would put the node in the dopnet above,
        # which has no SOP types at all.
        sopsolver = inside.node("d/s")
        wrangle = sopsolver.createNode("attribwrangle", "accumulate")
        wrangle.setFirstInput(sopsolver.node("Prev_Frame"))
        wrangle.parm("class").set(2)
        # Reads the previous frame's value, so this is only correct if the frames
        # were cooked in order -- which is the whole point of the test.
        wrangle.parm("snippet").set("@acc = @acc + 1;")
        sopsolver.node("OUT").setFirstInput(wrangle)

        result = call("graph.cook_frame_range", node_path=solver, start=1, end=6, attribs=["acc"])
        maxima = [row["attribs"]["acc"]["max"] for row in result["frames"]]
        # Sequential accumulation: strictly increasing, which only happens if the
        # frames were cooked in order.
        assert maxima == sorted(maxima), maxima
        assert maxima[-1] > maxima[0], maxima


class TestNodeCardIntrospection:
    """The card must not answer "no such parameter" about parameters that exist.

    It skipped hidden parameters outright and said nothing about multiparm
    blocks, so a recorded session spent three execute_python calls discovering
    that the sourcing bindings were named source_volume1..4.
    """

    def test_multiparm_blocks_are_reported_with_their_count_parm(self, call):
        # attribcreate's numattr is a MultiparmBlock nested inside a tab folder,
        # which is why a top-level-only walk reported none anywhere.
        card = call("graph.get_node_card", node_type="attribcreate", context="Sop")
        blocks = {b["count_parm"]: b for b in card["multiparms"]}
        assert "numattr" in blocks, list(blocks)
        block = blocks["numattr"]
        assert block["folder_type"] == "MultiparmBlock"
        # Instance templates carry '#'; the live parm substitutes an index.
        assert block["instance_parms"], block
        assert all("#" in name for name in block["instance_parms"])

    def test_truncation_reports_how_much_was_dropped(self, call):
        # pyrosolver has ~354 parameters against an 80 cap, and silently
        # returning 80 reads as "that is all of them".
        card = call("graph.get_node_card", node_type="pyrosolver", context="Sop")
        assert card["parms_truncated"] is True
        assert card["parms_matched"] > card["parm_count"]

    def test_hidden_parameters_are_no_longer_dropped_silently(self, call):
        """Hidden parameters are settable, so omitting them answered "no such
        parameter" about parameters that exist. Not every type has one, so this
        asserts the mechanism rather than a specific name."""
        card = call("graph.get_node_card", node_type="pyrosolver", context="Sop")
        assert card["parms_matched"] >= card["parm_count"]
        for parm in card["parms"]:
            if parm.get("hidden"):
                assert parm["name"]

    def test_menu_truncation_is_visible(self, call):
        card = call("graph.get_node_card", node_type="pyrosolver", context="Sop")
        for parm in card["parms"]:
            if parm.get("menu_truncated"):
                assert parm["menu_count"] > len(parm["menu"])
                break
