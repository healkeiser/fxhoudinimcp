"""End-to-end scenarios: the tool-call sequences an instruction-following
assistant would run for real user requests, verified against the live scene.

Each scenario follows the server instructions: discover node types first
(NODE-FIRST RULE), prefer workflow tools and native nodes, log status,
lay out networks, and leave the display flag on the result.
"""

from __future__ import annotations

# Built-in
import time

# Third-party
import hou
import pytest

pytestmark = pytest.mark.integration


class TestProceduralModelingScenario:
    """User: 'Create a procedural rocky terrain with scattered rocks.'"""

    def test_node_discovery_surfaces_the_right_builtins(self, call):
        """The NODE-FIRST RULE only works if list_node_types actually
        surfaces the built-in nodes the instructions promise."""
        for keyword, expected_prefix in [
            ("heightfield", "heightfield"),
            ("scatter", "scatter"),
            ("copy", "copytopoints"),
            ("mountain", "mountain"),
        ]:
            data = call("nodes.list_node_types", context="Sop", filter=keyword)
            names = [t["name"] for t in data["types"]]
            assert any(n.startswith(expected_prefix) for n in names), (
                f"filter={keyword!r} did not surface {expected_prefix!r}: "
                f"{names[:10]}"
            )

    def test_full_terrain_build(self, call):
        call("viewport.log_status", message="Creating terrain...")
        geo = call(
            "nodes.create_node", parent_path="/obj", node_type="geo", name="terrain"
        )["node_path"]

        chain = call(
            "workflow.build_sop_chain",
            parent_path=geo,
            steps=[
                {"type": "grid", "params": {"rows": 60, "cols": 60}},
                {"type": "mountain", "params": {"height": 2.0}},
                {"type": "scatter", "params": {"npts": 50}},
            ],
        )
        scatter_path = chain["nodes"][-1]["path"]

        rock = call(
            "nodes.create_node", parent_path=geo, node_type="box", name="rock"
        )["node_path"]
        call(
            "parameters.set_parameter", node_path=rock, parm_name="scale", value=0.1
        )
        copy = call(
            "nodes.create_node",
            parent_path=geo,
            node_type="copytopoints::2.0",
            name="copy_rocks",
        )["node_path"]
        call(
            "nodes.connect_nodes_batch",
            connections=[
                {"source_path": rock, "dest_path": copy, "input_index": 0},
                {"source_path": scatter_path, "dest_path": copy, "input_index": 1},
            ],
        )
        call("nodes.set_node_flags", node_path=copy, display=True, render=True)
        call("nodes.layout_children", parent_path=geo)
        call("viewport.log_status", message="Terrain done.")

        # The user-facing outcome: displayed geometry is 50 copied rocks.
        info = call("geometry.get_geometry_info", node_path=copy)
        assert info["num_points"] == 50 * 8, info["num_points"]
        assert info["num_prims"] == 50 * 6, info["num_prims"]
        node = hou.node(copy)
        assert node.isDisplayFlagSet()
        assert not node.errors()


class TestSimulationScenario:
    """User: 'Make a smoke simulation that looks like a campfire plume.'"""

    def test_pyro_sim_produces_actual_smoke(self, call):
        geo = call(
            "nodes.create_node", parent_path="/obj", node_type="geo", name="fire"
        )["node_path"]
        source = call(
            "nodes.create_node", parent_path=geo, node_type="sphere", name="emitter"
        )["node_path"]
        call("parameters.set_parameter", node_path=source, parm_name="scale", value=0.3)

        sim = call("workflow.setup_pyro_sim", source_geo=source, name="campfire")
        assert sim["success"] is True

        # Keep the sim cheap: coarse voxels if the solver exposes divsize.
        solver = sim["solver_path"]
        if hou.node(solver).parm("divsize") is not None:
            call(
                "parameters.set_parameter",
                node_path=solver,
                parm_name="divsize",
                value=0.2,
            )

        # Advance a few frames and verify smoke volumes actually exist —
        # the part a user sees, and the part success flags can't fake.
        start = time.perf_counter()
        call("animation.set_frame", frame=5)
        info = call("geometry.get_geometry_info", node_path=solver)
        cook_seconds = time.perf_counter() - start
        print(f"[scenario] pyro cook to frame 5: {cook_seconds:.1f}s")

        breakdown = info["prim_type_breakdown"]
        assert any(
            "Volume" in type_name or "VDB" in type_name
            for type_name in breakdown
        ), f"no smoke volumes at frame 5: {breakdown}"
        assert cook_seconds < 60, f"pyro cook too slow: {cook_seconds:.1f}s"


class TestAnimationScenario:
    """User: 'Animate a bouncing ball.'"""

    def test_keyframed_ball_evaluates_midair(self, call):
        geo = call(
            "nodes.create_node", parent_path="/obj", node_type="geo", name="ball"
        )["node_path"]
        call("nodes.create_node", parent_path=geo, node_type="sphere")
        for frame, value in [(1, 0.0), (12, 5.0), (24, 0.0)]:
            call(
                "animation.set_keyframe",
                node_path=geo,
                parm_name="ty",
                frame=frame,
                value=value,
            )
        keys = call("animation.get_keyframes", node_path=geo, parm_name="ty")
        assert "3" in str(keys.get("count", keys)), keys

        call("animation.set_frame", frame=12)
        assert hou.node(geo).parm("ty").eval() == pytest.approx(5.0)
        call("animation.set_frame", frame=1)
        assert hou.node(geo).parm("ty").eval() == pytest.approx(0.0)


class TestLookdevScenario:
    """User: 'Shade the terrain red and set up a render.'"""

    def test_material_render_pipeline(self, call):
        geo = call(
            "nodes.create_node", parent_path="/obj", node_type="geo", name="asset"
        )["node_path"]
        call("nodes.create_node", parent_path=geo, node_type="testgeometry_pighead")
        mat = call(
            "workflow.create_material",
            name="red_clay",
            base_color=[0.8, 0.1, 0.1],
            roughness=0.9,
        )
        call(
            "workflow.assign_material",
            geo_path=geo,
            material_path=mat["material_path"],
        )
        render = call(
            "workflow.setup_render",
            renderer="mantra",
            resolution=[320, 240],
            samples=4,
            name="preview",
        )
        assert hou.node(render["rop_path"]) is not None
        assert hou.node(render["camera_path"]) is not None

    def test_actual_image_render(self, call, tmp_path):
        """User: 'Render me a frame.' — a real 64x64 mantra render to disk."""
        geo = call(
            "nodes.create_node", parent_path="/obj", node_type="geo", name="subject"
        )["node_path"]
        call("nodes.create_node", parent_path=geo, node_type="sphere")
        render = call(
            "workflow.setup_render",
            renderer="mantra",
            resolution=[64, 64],
            samples=1,
            name="micro",
        )
        out = str(tmp_path / "frame.exr").replace("\\", "/")
        call(
            "parameters.set_parameter",
            node_path=render["rop_path"],
            parm_name="vm_picture",
            value=out,
        )
        result = call(
            "rendering.start_render",
            node_path=render["rop_path"],
            frame_range=[1, 1],
            allow_error=True,
        )
        data = result.get("data", {})
        if result["status"] != "success" or not data.get("success", True):
            reason = str(
                result.get("error", {}).get("message") or data.get("error")
            )[:80]
            pytest.skip(f"mantra render unavailable here: {reason}")
        assert (tmp_path / "frame.exr").is_file(), (
            "start_render claimed success but no image was written"
        )


class TestScreenshotScenario:
    """User: 'Show me what it looks like.' — headless behavior must be a
    clean, actionable error, not a Python traceback."""

    def test_viewport_screenshot_fails_gracefully_headless(self, call):
        if hou.isUIAvailable():
            pytest.skip("graphical session: screenshots are exercised by GUI use")
        error = call("viewport.capture_screenshot", expect_error=True)
        message = error["message"].lower()
        assert message.strip(), "empty error message"
        assert any(
            hint in message
            for hint in ("ui", "graphical", "viewport", "headless", "gui")
        ), f"unhelpful headless error: {error['message']}"

    def test_network_editor_capture_fails_gracefully_headless(self, call):
        if hou.isUIAvailable():
            pytest.skip("graphical session: captures are exercised by GUI use")
        call("nodes.create_node", parent_path="/obj", node_type="geo", name="g")
        error = call(
            "viewport.capture_network_editor", expect_error=True
        )
        message = error["message"].lower()
        assert any(
            hint in message
            for hint in ("ui", "graphical", "network editor", "headless", "gui")
        ), f"unhelpful headless error: {error['message']}"

    def test_log_status_is_harmless_headless(self, call):
        # Instructions say to call log_status constantly; it must never
        # break a headless session.
        call("viewport.log_status", message="working...")
