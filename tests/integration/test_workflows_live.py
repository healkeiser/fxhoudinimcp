"""Live workflow-handler tests.

Workflow handlers build whole networks and report success aggressively
(parameter sets are silently swallowed by ``_set_parm_safe``), so every
claim in the returned dict is checked against the live scene.
"""

from __future__ import annotations

# Third-party
import hou
import pytest

pytestmark = pytest.mark.integration


class TestBuildSopChain:
    def test_chain_is_wired_in_order_with_params(self, call):
        geo = call("nodes.create_node", parent_path="/obj", node_type="geo", name="geo1")[
            "node_path"
        ]
        data = call(
            "workflow.build_sop_chain",
            parent_path=geo,
            steps=[
                {"type": "box"},
                {"type": "polybevel", "params": {"offset": 0.05}},
                {"type": "scatter", "params": {"npts": 123}},
            ],
        )
        paths = [entry["path"] for entry in data["nodes"]]
        assert len(paths) == 3, data
        nodes = [hou.node(p) for p in paths]
        assert all(n is not None for n in nodes), f"claimed nodes missing: {paths}"
        # Wired sequentially.
        assert nodes[1].inputs()[0].path() == paths[0]
        assert nodes[2].inputs()[0].path() == paths[1]
        # Claimed params actually applied.
        assert nodes[2].parm("npts").eval() == 123

    def test_unknown_step_type_does_not_claim_success(self, call):
        geo = call("nodes.create_node", parent_path="/obj", node_type="geo", name="geo1")[
            "node_path"
        ]
        result = call(
            "workflow.build_sop_chain",
            parent_path=geo,
            steps=[{"type": "box"}, {"type": "not_a_real_sop"}],
            expect_error=True,
        )
        assert "not_a_real_sop" in str(result)


class TestCreateMaterial:
    def test_principled_material_params_are_really_applied(self, call):
        data = call(
            "workflow.create_material",
            name="audit_mat",
            mat_type="principled",
            base_color=[0.1, 0.2, 0.3],
            roughness=0.7,
            metallic=1.0,
            opacity=0.5,
        )
        shader = hou.node(data["material_path"])
        assert shader is not None
        basecolor = [shader.parm("basecolor" + c).eval() for c in ("r", "g", "b")]
        assert basecolor == pytest.approx([0.1, 0.2, 0.3])
        assert shader.parm("rough").eval() == pytest.approx(0.7)
        assert shader.parm("metallic").eval() == pytest.approx(1.0)
        opac = shader.parm("opac")
        assert opac is not None and opac.eval() == pytest.approx(0.5), (
            "opacity claimed applied but parm missing or unchanged "
            "(_set_parm_safe swallows failures)"
        )

    def test_assign_material_sets_material_sop(self, call):
        geo = call("nodes.create_node", parent_path="/obj", node_type="geo", name="geo1")[
            "node_path"
        ]
        call("nodes.create_node", parent_path=geo, node_type="box")
        mat = call("workflow.create_material", name="assign_mat")
        data = call(
            "workflow.assign_material",
            geo_path=geo,
            material_path=mat["material_path"],
        )
        flat = str(data)
        material_sops = [c for c in hou.node(geo).children() if c.type().name() == "material"]
        assert material_sops, f"no Material SOP created: {flat}"
        assert material_sops[0].parm("shop_materialpath1").eval() == mat["material_path"]


class TestSimSetups:
    def test_setup_pyro_sim_claimed_nodes_exist(self, call):
        geo = call("nodes.create_node", parent_path="/obj", node_type="geo", name="geo1")[
            "node_path"
        ]
        sphere = call("nodes.create_node", parent_path=geo, node_type="sphere")
        data = call("workflow.setup_pyro_sim", source_geo=sphere["node_path"])
        assert data["success"] is True
        for path in data["all_nodes"]:
            assert hou.node(path) is not None, f"claimed node missing: {path}"

    def test_setup_rbd_sim_actually_simulates(self, call):
        geo = call("nodes.create_node", parent_path="/obj", node_type="geo", name="geo1")[
            "node_path"
        ]
        box = call("nodes.create_node", parent_path=geo, node_type="box")["node_path"]
        call("parameters.set_parameter", node_path=box, parm_name="ty", value=3.0)
        data = call("workflow.setup_rbd_sim", geo_path=geo)
        assert data["success"] is True
        for path in data["all_nodes"]:
            assert hou.node(path) is not None, f"claimed node missing: {path}"

        # The sim must actually move geometry — a network that looks right
        # but cooks empty (the original voronoifracture had no cell-point
        # input) passes existence checks while fooling the user.
        display = hou.node(data["geo_path"]).displayNode()
        hou.setFrame(1)
        start_geo = display.geometry()
        assert start_geo is not None and not display.errors(), display.errors()
        start_y = start_geo.boundingBox().center()[1]
        hou.setFrame(12)
        end_y = display.geometry().boundingBox().center()[1]
        assert end_y < start_y - 0.3, f"RBD pieces did not fall: y {start_y:.2f} -> {end_y:.2f}"


class TestSetupRender:
    def test_render_setup_resolution_is_really_applied(self, call):
        data = call(
            "workflow.setup_render",
            renderer="karma",
            resolution=[640, 480],
            samples=8,
            name="audit_render",
        )
        rop = hou.node(data["rop_path"])
        assert rop is not None
        camera = hou.node(data["camera_path"])
        assert camera is not None, f"claimed camera missing: {data['camera_path']}"
        applied = []
        for node in (rop, camera):
            for parm_name in ("resolutionx", "res1", "resx"):
                parm = node.parm(parm_name)
                if parm is not None:
                    applied.append(parm.eval())
        assert 640 in applied, (
            f"resolution [640, 480] claimed in result but not found on ROP or camera: {data}"
        )
