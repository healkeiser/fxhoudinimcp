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
