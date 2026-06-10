"""Deep authoring scenarios: HDA packaging, Solaris scene assembly,
MaterialX lookdev, and USD lighting — every claim checked on the stage.
"""

from __future__ import annotations

# Built-in
import os

# Third-party
import hou
import pytest

pytestmark = pytest.mark.integration


class TestHdaAuthoringScenario:
    """User: 'Package this setup into a reusable asset and use it again.'"""

    def test_create_hda_and_reinstance_it(self, call, tmp_path):
        subnet = call(
            "nodes.create_node", parent_path="/obj", node_type="subnet", name="rock"
        )["node_path"]
        call("nodes.create_node", parent_path=subnet, node_type="geo", name="inner")

        hda_file = str(tmp_path / "rock_asset.hda").replace("\\", "/")
        created = call(
            "hda.create_hda",
            node_path=subnet,
            hda_file=hda_file,
            type_name="audit::rock_asset",
            label="Rock Asset",
        )
        assert os.path.isfile(hda_file), "create_hda claimed success, wrote no file"
        flat = str(created)
        assert "rock_asset" in flat, created

        # The user outcome: the new type is instantiable like any built-in.
        instance = call(
            "nodes.create_node",
            parent_path="/obj",
            node_type="audit::rock_asset",
            name="rock_copy",
        )
        node = hou.node(instance["node_path"])
        assert node is not None
        assert node.type().definition() is not None, "instance is not an HDA"
        assert node.type().definition().libraryFilePath() == hda_file

        info = call("hda.get_hda_info", node_path=instance["node_path"])
        assert "Rock Asset" in str(info)
        sections = call("hda.get_hda_sections", node_path=instance["node_path"])
        assert sections, sections


class TestSolarisSceneScenario:
    """User: 'Build a USD scene: import my SOP asset, shade it with
    MaterialX, light it, add a camera, and set up Karma.'"""

    def test_full_usd_scene_assembly(self, call):
        # SOP asset to bring in
        geo = call(
            "nodes.create_node", parent_path="/obj", node_type="geo", name="hero"
        )["node_path"]
        call("nodes.create_node", parent_path=geo, node_type="testgeometry_pighead")

        lopnet = call(
            "nodes.create_node", parent_path="/obj", node_type="lopnet", name="assembly"
        )["node_path"]

        # 1. Import the SOP geometry onto the stage. The import root is
        # the pathprefix parm (primpath is unrelated on sopimport).
        imported = call(
            "lops.create_lop_node",
            parent_path=lopnet,
            lop_type="sopimport",
            name="hero_import",
        )["node_path"]
        call(
            "parameters.set_parameters",
            node_path=imported,
            params={
                "soppath": geo,
                "enable_pathprefix": True,
                "pathprefix": "/geo/hero",
            },
        )

        # 2. MaterialX material in a material library
        matlib = call(
            "lops.create_lop_node",
            parent_path=lopnet,
            lop_type="materiallibrary",
            name="mats",
        )["node_path"]
        call("nodes.connect_nodes", source_path=imported, dest_path=matlib)
        call(
            "parameters.set_parameter",
            node_path=matlib,
            parm_name="matpathprefix",
            value="/materials/",
        )
        shader = call(
            "nodes.create_node",
            parent_path=matlib,
            node_type="mtlxstandard_surface",
            name="clay",
        )["node_path"]
        call(
            "parameters.set_parameters",
            node_path=shader,
            params={"base_colorr": 0.6, "base_colorg": 0.3, "base_colorb": 0.2},
        )

        # 3. Bind the material to the hero prim
        assign = call(
            "lops.create_lop_node",
            parent_path=lopnet,
            lop_type="assignmaterial",
            name="bind",
        )["node_path"]
        call("nodes.connect_nodes", source_path=matlib, dest_path=assign)
        call(
            "parameters.set_parameters",
            node_path=assign,
            params={"primpattern1": "/geo/hero", "matspecpath1": "/materials/clay"},
        )

        # 4. Lights and camera
        light = call(
            "lops.create_light", parent_path=lopnet, light_type="dome", intensity=2.5
        )
        light_node = light["node_path"]
        call("nodes.connect_nodes", source_path=assign, dest_path=light_node)
        camera = call(
            "lops.create_lop_node",
            parent_path=lopnet,
            lop_type="camera",
            name="render_cam",
            prim_path="/cameras/render_cam",
        )["node_path"]
        call("nodes.connect_nodes", source_path=light_node, dest_path=camera)

        # 5. Karma render settings as the stage output
        settings = call(
            "lops.create_lop_node",
            parent_path=lopnet,
            lop_type="karmarendersettings",
            name="karma",
        )["node_path"]
        call("nodes.connect_nodes", source_path=camera, dest_path=settings)
        call("nodes.set_node_flags", node_path=settings, display=True)

        # The user outcome: ONE stage containing everything.
        prims = str(call("lops.list_usd_prims", node_path=settings))
        for expected in ("/geo/hero", "/materials/clay", "/cameras/render_cam"):
            assert expected in prims, f"{expected} missing from final stage"

        materials = call("lops.get_usd_materials", node_path=settings)
        assert "clay" in str(materials)

        hero = call(
            "lops.get_usd_prim", node_path=settings, prim_path="/geo/hero"
        )
        assert hero, hero

        # The dome light exists with the intensity actually applied.
        light_prim_path = light.get("prim_path") or "/lights/" + light_node.split("/")[-1]
        intensity = call(
            "lops.get_usd_attribute",
            node_path=settings,
            prim_path=light_prim_path,
            attr_name="inputs:intensity",
        )
        assert "2.5" in str(intensity), (
            f"create_light claimed intensity=2.5 but stage says: {intensity}"
        )

        stats = call("lops.get_usd_prim_stats", node_path=settings)
        assert stats, stats


class TestLightRigScenario:
    """User: 'Give me a three-point light rig.'"""

    def test_rig_lights_are_chained_and_configured(self, call):
        lopnet = call(
            "nodes.create_node", parent_path="/obj", node_type="lopnet", name="rig"
        )["node_path"]
        rig = call(
            "lops.create_light_rig",
            parent_path=lopnet,
            preset="three_point",
            intensity_mult=2.0,
        )
        created = rig.get("created_nodes", rig.get("nodes", rig.get("all_nodes")))
        assert created and len(created) == 3, rig

        # All three lights must be on the LAST node's stage (chained).
        last = created[-1]
        lights = call("lops.list_lights", node_path=last)
        flat = str(lights)
        for name in ("key_light", "fill_light", "rim_light"):
            assert name in flat, f"{name} missing from rig output stage: {flat}"

        # Intensity multiplier must actually land on the USD prims.
        key = call(
            "lops.get_usd_attribute",
            node_path=last,
            prim_path="/lights/key_light",
            attr_name="inputs:intensity",
        )
        assert "2" in str(key.get("value", key)), (
            f"key light intensity (1.0 * mult 2.0) not applied: {key}"
        )


class TestMaterialXLookdevScenario:
    """User: 'Make me a MaterialX clay shader.' — the materialx branch of
    create_material sets parms through _set_parm_safe, which silently
    swallows failures, so verify every claimed value on the shader."""

    def test_materialx_params_really_applied(self, call):
        data = call(
            "workflow.create_material",
            name="mtlx_clay",
            mat_type="materialx",
            base_color=[0.2, 0.3, 0.4],
            roughness=0.6,
            metallic=1.0,
        )
        shader = hou.node(data["material_path"])
        assert shader is not None
        assert shader.type().name().startswith("mtlx"), shader.type().name()
        base = [shader.parm(f"base_color{c}").eval() for c in "rgb"]
        assert base == pytest.approx([0.2, 0.3, 0.4]), (
            f"base_color claimed applied but shader has {base}"
        )
        assert shader.parm("specular_roughness").eval() == pytest.approx(0.6)
        assert shader.parm("metalness").eval() == pytest.approx(1.0)
