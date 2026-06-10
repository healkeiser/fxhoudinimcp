"""Coverage sweep over the command categories no other test exercises.

Strong assertions where the outcome is cheap to verify against the live
scene; smoke assertions (success OR a clean structured error — never an
unknown command or an empty message) for UI-dependent or environment-
dependent commands. The session summary in conftest reports which of the
registered commands were never called.
"""

from __future__ import annotations

# Third-party
import hou
import pytest

pytestmark = pytest.mark.integration


class TestDops:
    @pytest.fixture
    def dopnet(self, call) -> str:
        geo = call(
            "nodes.create_node", parent_path="/obj", node_type="dopnet", name="sim"
        )["node_path"]
        # The DOP object only enters the simulation when it is displayed.
        hou.node(geo).createNode("emptyobject", "thing").setDisplayFlag(True)
        return geo

    def test_dop_lifecycle(self, call, dopnet):
        call("dops.step_simulation", node_path=dopnet, steps=2)
        info = call("dops.get_simulation_info", node_path=dopnet)
        assert str(info), info
        objects = call("dops.list_dop_objects", node_path=dopnet)
        names = [o["name"] if isinstance(o, dict) else o for o in objects["objects"]]
        assert names, f"no DOP objects after stepping: {objects}"
        call(
            "dops.get_dop_object",
            node_path=dopnet,
            object_name=names[0],
            allow_error=True,
        )
        call("dops.get_dop_relationships", node_path=dopnet)
        call("dops.get_sim_memory_usage", node_path=dopnet)
        call("dops.reset_simulation", node_path=dopnet)
        call(
            "dops.get_dop_field",
            node_path=dopnet,
            object_name="thing",
            data_path="Geometry",
            field_name="vel",
            allow_error=True,
        )


class TestTops:
    def test_top_cook_lifecycle(self, call):
        topnet = call(
            "nodes.create_node", parent_path="/obj", node_type="topnet", name="pdg"
        )["node_path"]
        gen = hou.node(topnet).createNode("genericgenerator")
        gen.parm("itemcount").set(5)
        path = gen.path()

        call("tops.get_top_network_info", node_path=topnet, allow_error=True)
        call("tops.generate_static_items", node_path=path)
        states = call("tops.get_work_item_states", node_path=path)
        assert "5" in str(states) or "workitems" in str(states).lower(), states
        call("tops.get_work_item_info", node_path=path, work_item_index=0, allow_error=True)
        call("tops.get_pdg_graph", node_path=topnet, allow_error=True)
        call("tops.cook_top_node", node_path=path, block=True)
        cooked = call("tops.get_work_item_states", node_path=path)
        assert "Cooked" in str(cooked) or "success" in str(cooked).lower(), (
            f"PDG cook claimed done but no cooked work items: {cooked}"
        )
        call("tops.get_top_scheduler_info", node_path=topnet, allow_error=True)
        call("tops.dirty_work_items", node_path=path)
        call("tops.pause_top_cook", node_path=topnet, allow_error=True)
        call("tops.cancel_top_cook", node_path=topnet, allow_error=True)


class TestCops:
    def test_cop_create_and_inspect(self, call):
        copnet = call(
            "nodes.create_node", parent_path="/obj", node_type="copnet", name="comp"
        )["node_path"]
        types = call("cops.list_cop_node_types", filter="fractalnoise")
        names = [t["name"] for t in types["cop_types"]]
        assert "fractalnoise" in names, (
            f"list_cop_node_types does not surface Copernicus types: {names}"
        )
        created = call(
            "cops.create_cop_node",
            parent_path=copnet,
            cop_type="fractalnoise",
            allow_error=True,
        )
        if created["status"] == "success":
            cop_path = created["data"]["node_path"]
            call("cops.get_cop_info", node_path=cop_path, allow_error=True)
            call("cops.set_cop_flags", node_path=cop_path, display=True, allow_error=True)
            call("cops.get_cop_layer", node_path=cop_path, allow_error=True)
            call("cops.get_cop_geometry", node_path=cop_path, allow_error=True)
            call("cops.get_cop_vdb", node_path=cop_path, allow_error=True)


class TestChops:
    def test_chop_data_and_export(self, call):
        chopnet = call(
            "nodes.create_node", parent_path="/obj", node_type="chopnet", name="motion"
        )["node_path"]
        wave = call(
            "chops.create_chop_node", parent_path=chopnet, chop_type="wave"
        )
        wave_path = wave["node_path"]
        channels = call("chops.list_chop_channels", node_path=wave_path)
        assert channels.get("channels"), channels
        channel = channels["channels"][0]
        channel_name = channel["name"] if isinstance(channel, dict) else channel
        data = call(
            "chops.get_chop_data",
            node_path=wave_path,
            channel_name=channel_name,
            start=0,
            end=10,
        )
        assert str(data), data
        geo = call(
            "nodes.create_node", parent_path="/obj", node_type="geo", name="target"
        )["node_path"]
        call(
            "chops.export_chop_to_parm",
            chop_path=wave_path,
            channel_name=channel_name,
            target_node_path=geo,
            target_parm_name="tx",
            allow_error=True,
        )


class TestTakes:
    def test_take_roundtrip(self, call):
        call("takes.create_take", name="lighting_v2")
        call("takes.set_current_take", name="lighting_v2")
        current = call("takes.get_current_take")
        assert "lighting_v2" in str(current)
        takes = call("takes.list_takes")
        assert "lighting_v2" in str(takes)
        call("takes.set_current_take", name="Main", allow_error=True)


class TestHda:
    def test_hda_create_inspect_roundtrip(self, call, tmp_path):
        geo = call(
            "nodes.create_node", parent_path="/obj", node_type="subnet", name="asset"
        )["node_path"]
        hda_file = str(tmp_path / "test_asset.hda").replace("\\", "/")
        created = call(
            "hda.create_hda",
            node_path=geo,
            hda_file=hda_file,
            type_name="test::asset",
            label="Test Asset",
            allow_error=True,
        )
        if created["status"] != "success":
            pytest.skip(f"create_hda not available here: {created['error']['message']}")
        import os

        assert os.path.isfile(hda_file), "create_hda claimed success, wrote no file"
        node_path = created["data"].get("node_path", geo)
        call("hda.get_hda_info", node_path=node_path, allow_error=True)
        sections = call("hda.get_hda_sections", node_path=node_path, allow_error=True)
        if sections["status"] == "success":
            listed = sections["data"].get("sections", [])
            name = listed[0]["name"] if listed and isinstance(listed[0], dict) else (
                listed[0] if listed else "Contents"
            )
            call(
                "hda.get_hda_section_content",
                node_path=node_path,
                section_name=str(name),
                allow_error=True,
            )
        call(
            "hda.set_hda_section_content",
            node_path=node_path,
            section_name="Comment",
            content="made by integration tests",
            allow_error=True,
        )
        call("hda.update_hda", node_path=node_path, allow_error=True)
        call("hda.reload_hda", file_path=hda_file, allow_error=True)
        call("hda.install_hda", file_path=hda_file, force=True, allow_error=True)
        call("hda.uninstall_hda", file_path=hda_file, allow_error=True)

    def test_list_installed_hdas(self, call):
        listed = call("hda.list_installed_hdas")
        assert listed, listed


class TestCache:
    def test_cache_status_and_listing(self, call, tmp_path):
        geo = call(
            "nodes.create_node", parent_path="/obj", node_type="geo", name="cached"
        )["node_path"]
        box = call("nodes.create_node", parent_path=geo, node_type="box")["node_path"]
        fc = call(
            "nodes.create_node", parent_path=geo, node_type="filecache", name="cache1"
        )["node_path"]
        call("nodes.connect_nodes", source_path=box, dest_path=fc)
        # Point the cache at tmp with an explicit file — the default
        # constructed path resolves under $HIP, i.e. the repo checkout.
        node = hou.node(fc)
        if node.parm("filemethod") is not None:
            node.parm("filemethod").set(1)
        if node.parm("file") is not None:
            node.parm("file").set(str(tmp_path / "box.bgeo.sc").replace("\\", "/"))
        if node.parm("trange") is not None:
            node.parm("trange").set(0)  # single frame, not 1-240

        caches = call("cache.list_caches", root_path="/obj")
        assert "cache1" in str(caches)
        call("cache.get_cache_status", node_path=fc, allow_error=True)
        call("cache.write_cache", node_path=fc, frame_range=[1, 1], allow_error=True)
        call("cache.clear_cache", node_path=fc, allow_error=True)


class TestCode:
    def test_hscript_and_python(self, call):
        out = call("code.execute_hscript", command="echo hello_houdini")
        assert "hello_houdini" in str(out)
        result = call(
            "code.evaluate_expression", expression="1 + 1", language="python"
        )
        assert "2" in str(result)
        env = call("code.get_env_variable", var_name="HFS")
        assert "houdini" in str(env).lower() or "hfs" in str(env).lower()


class TestContext:
    def test_context_introspection(self, call):
        geo = call(
            "nodes.create_node", parent_path="/obj", node_type="geo", name="g"
        )["node_path"]
        box = call("nodes.create_node", parent_path=geo, node_type="box")["node_path"]
        xform = call("nodes.create_node", parent_path=geo, node_type="xform")[
            "node_path"
        ]
        call("nodes.connect_nodes", source_path=box, dest_path=xform)
        chain = call("context.get_cook_chain", node_path=xform)
        assert "box" in str(chain)
        call("context.get_network_overview", path="/obj", depth=2)
        call("context.set_selection", node_paths=[box])
        selection = call("context.get_selection")
        assert "box" in str(selection)
        call("context.compare_snapshots", action="take", snapshot_name="t1")
        call(
            "context.compare_snapshots",
            action="compare",
            snapshot_name="t1",
            allow_error=True,
        )
        call("context.get_node_errors_detailed", root_path="/obj")


class TestRendering:
    def test_geometry_rop_renders_a_real_file(self, call, tmp_path):
        geo = call(
            "nodes.create_node", parent_path="/obj", node_type="geo", name="g"
        )["node_path"]
        box = call("nodes.create_node", parent_path=geo, node_type="box")["node_path"]
        rop = call(
            "nodes.create_node", parent_path="/out", node_type="geometry", name="bake"
        )["node_path"]
        out_file = str(tmp_path / "baked.bgeo.sc").replace("\\", "/")
        call(
            "parameters.set_parameters",
            node_path=rop,
            params={"soppath": box, "sopoutput": out_file},
        )
        call("rendering.start_render", node_path=rop)
        assert (tmp_path / "baked.bgeo.sc").is_file(), (
            "start_render claimed success but wrote no file"
        )
        call("rendering.get_render_progress", node_path=rop, allow_error=True)

    def test_render_settings_roundtrip(self, call):
        created = call(
            "rendering.create_render_node", renderer="mantra", name="m1", allow_error=True
        )
        if created["status"] != "success":
            pytest.skip(str(created["error"]["message"]))
        rop = created["data"].get("node_path", "/out/m1")
        settings = call("rendering.get_render_settings", node_path=rop)
        assert settings, settings
        call(
            "rendering.set_render_settings",
            node_path=rop,
            settings={"vm_samples": 2},
            allow_error=True,
        )

    def test_viewport_renders_fail_cleanly_headless(self, call, tmp_path):
        if hou.isUIAvailable():
            pytest.skip("graphical session")
        out = str(tmp_path / "vp.png").replace("\\", "/")
        for command in ("rendering.render_viewport", "rendering.render_quad_view"):
            result = call(command, output_path=out, allow_error=True)
            assert result["status"] in ("success", "error")


class TestViewportHeadless:
    """Every viewport command must degrade cleanly without a UI."""

    @pytest.mark.parametrize(
        ("command", "params"),
        [
            ("viewport.list_panes", {}),
            ("viewport.get_viewport_info", {}),
            ("viewport.set_viewport_display", {"display_mode": "smooth"}),
            ("viewport.set_viewport_direction", {"direction": "top"}),
            ("viewport.set_viewport_renderer", {"renderer": "Houdini GL"}),
            ("viewport.frame_all", {}),
            ("viewport.frame_selection", {}),
            ("viewport.set_current_network", {"network_path": "/obj"}),
            ("viewport.find_error_nodes", {}),
        ],
    )
    def test_clean_headless_behavior(self, call, command, params):
        result = call(command, allow_error=True, **params)
        assert result["status"] in ("success", "error")


class TestRemainingNodesParamsScene:
    def test_move_reorder_color(self, call):
        geo_a = call(
            "nodes.create_node", parent_path="/obj", node_type="geo", name="a"
        )["node_path"]
        geo_b = call(
            "nodes.create_node", parent_path="/obj", node_type="geo", name="b"
        )["node_path"]
        box = call("nodes.create_node", parent_path=geo_a, node_type="box")["node_path"]
        moved = call("nodes.move_node", node_path=box, dest_parent=geo_b)
        assert hou.node(moved["new_path"]).parent().path() == geo_b
        call("nodes.set_node_color", node_path=moved["new_path"], r=1.0, g=0.0, b=0.0)
        assert list(hou.node(moved["new_path"]).color().rgb()) == [1.0, 0.0, 0.0]

        merge = call("nodes.create_node", parent_path=geo_b, node_type="merge")[
            "node_path"
        ]
        s1 = call("nodes.create_node", parent_path=geo_b, node_type="sphere")[
            "node_path"
        ]
        call(
            "nodes.connect_nodes_batch",
            connections=[
                {"source_path": moved["new_path"], "dest_path": merge, "input_index": 0},
                {"source_path": s1, "dest_path": merge, "input_index": 1},
            ],
        )
        call("nodes.reorder_inputs", node_path=merge, new_order=[1, 0])
        assert hou.node(merge).inputs()[0].path() == s1

    def test_parameter_extras(self, call):
        geo = call(
            "nodes.create_node", parent_path="/obj", node_type="geo", name="g"
        )["node_path"]
        box = call("nodes.create_node", parent_path=geo, node_type="box")["node_path"]
        call("parameters.set_expression", node_path=box, parm_name="tx", expression="$F")
        expr = call("parameters.get_expression", node_path=box, parm_name="tx")
        assert "$F" in str(expr)
        call("parameters.set_parameter", node_path=box, parm_name="sizex", value=9.0)
        call("parameters.revert_parameter", node_path=box, parm_name="sizex")
        assert hou.node(box).parm("sizex").isAtDefault()
        call(
            "parameters.create_spare_parameters",
            node_path=box,
            parameters=[
                {"parm_name": "amount", "parm_type": "float", "label": "Amount"},
                {"parm_name": "label_text", "parm_type": "string", "label": "Label"},
            ],
            folder_name="Custom",
        )
        assert hou.node(box).parm("amount") is not None

    def test_scene_save_and_load(self, call, tmp_path):
        call("nodes.create_node", parent_path="/obj", node_type="geo", name="persisted")
        hip = str(tmp_path / "scene.hip").replace("\\", "/")
        call("scene.save_scene", file_path=hip)
        call("scene.new_scene")
        assert hou.node("/obj/persisted") is None
        call("scene.load_scene", file_path=hip)
        assert hou.node("/obj/persisted") is not None


class TestMaterialsModule:
    def test_material_network_and_info(self, call):
        created = call(
            "materials.create_material_network",
            name="brushed_metal",
            shader_type="principled",
            params={"rough": 0.3},
        )
        path = created.get("material_path", created.get("node_path"))
        assert path and hou.node(path) is not None, created
        info = call("materials.get_material_info", node_path=path)
        assert info, info
        listed = call("materials.list_materials", root_path="/mat")
        assert "brushed_metal" in str(listed)
        geo = call(
            "nodes.create_node", parent_path="/obj", node_type="geo", name="g"
        )["node_path"]
        call("nodes.create_node", parent_path=geo, node_type="box")
        call("materials.assign_material", geo_path=geo, material_path=path)


class TestLopsModule:
    @pytest.fixture
    def stage(self, call) -> str:
        lopnet = call(
            "nodes.create_node", parent_path="/obj", node_type="lopnet", name="stage"
        )["node_path"]
        sphere = call(
            "lops.create_lop_node",
            parent_path=lopnet,
            lop_type="sphere",
            prim_path="/geo/ball",
        )
        return sphere["node_path"]

    def test_usd_stage_walkthrough(self, call, stage):
        prim = call("lops.get_usd_prim", node_path=stage, prim_path="/geo/ball")
        assert "Sphere" in str(prim)
        set_result = call(
            "lops.set_usd_attribute",
            node_path=stage,
            prim_path="/geo/ball",
            attr_name="radius",
            value=3.0,
        )
        # set_usd_attribute appends a Python LOP; read back through it.
        out_node = set_result["python_node"]
        radius = call(
            "lops.get_usd_attribute",
            node_path=out_node,
            prim_path="/geo/ball",
            attr_name="radius",
        )
        assert "3" in str(radius.get("value", radius)), radius
        call("lops.get_usd_layers", node_path=stage)
        call("lops.inspect_usd_layer", node_path=stage, layer_index=0, allow_error=True)
        call("lops.get_usd_prim_stats", node_path=stage)
        call("lops.get_last_modified_prims", node_path=stage)
        found = call("lops.find_usd_prims", node_path=stage, pattern="*ball*")
        assert "ball" in str(found)
        call("lops.get_usd_composition", node_path=stage, prim_path="/geo/ball")
        call("lops.get_usd_variants", node_path=stage, prim_path="/geo/ball")
        call("lops.get_usd_materials", node_path=stage)

    def test_usd_lighting(self, call):
        lopnet = call(
            "nodes.create_node", parent_path="/obj", node_type="lopnet", name="lights"
        )["node_path"]
        light = call(
            "lops.create_light", parent_path=lopnet, light_type="dome", intensity=2.0
        )
        light_node = light.get("node_path")
        assert light_node and hou.node(light_node) is not None, light
        lights = call("lops.list_lights", node_path=light_node)
        assert lights, lights
        prim_path = light.get("prim_path")
        assert prim_path, light
        updated = call(
            "lops.set_light_properties",
            node_path=light_node,
            prim_path=prim_path,
            properties={"intensity": 5.0},
        )
        intensity = call(
            "lops.get_usd_attribute",
            node_path=updated["python_node"],
            prim_path=prim_path,
            attr_name="inputs:intensity",
        )
        assert "5" in str(intensity.get("value", intensity)), (
            f"set_light_properties claimed intensity=5.0 but stage says {intensity}"
        )


class TestMopUp:
    """Exercise the commands no other test reaches."""

    def test_geometry_inspection_extras(self, call):
        geo = call(
            "nodes.create_node", parent_path="/obj", node_type="geo", name="g"
        )["node_path"]
        box = call("nodes.create_node", parent_path=geo, node_type="box")["node_path"]
        grp = call(
            "nodes.create_node", parent_path=geo, node_type="groupcreate", name="top_grp"
        )["node_path"]
        call("nodes.connect_nodes", source_path=box, dest_path=grp)
        values = call(
            "geometry.get_attrib_values", node_path=box, attrib_name="P", count=8
        )
        assert values["total_elements"] == 8
        assert len(values["values"]) == 8 * 3
        info = call(
            "geometry.get_attribute_info", node_path=box, attrib_name="P"
        )
        assert info, info
        groups = call("geometry.get_groups", node_path=grp)
        assert "top_grp" in str(groups), groups
        members = call(
            "geometry.get_group_members",
            node_path=grp,
            group_name="top_grp",
            group_type="prim",
        )
        assert members, members

    def test_context_and_scene_extras(self, call):
        geo = call(
            "nodes.create_node", parent_path="/obj", node_type="geo", name="g"
        )["node_path"]
        explained = call("context.explain_node", node_path=geo)
        assert "geo" in str(explained)
        call("context.get_scene_summary")
        ctx = call("scene.get_context_info", context="/obj")
        assert ctx, ctx
        schema = call(
            "parameters.get_parameter_schema", node_path=geo, filter="translate"
        )
        assert "tx" in str(schema) or "translate" in str(schema).lower()

    def test_vex_extras(self, call):
        call("nodes.create_node", parent_path="/obj", node_type="geo", name="g")
        wrangle = call(
            "vex.create_wrangle", parent_path="/obj/g", vex_code="@Cd = {1,1,1};"
        )["node_path"]
        call("vex.set_wrangle_code", node_path=wrangle, vex_code="@Cd = {0,0,1};")
        code = call("vex.get_wrangle_code", node_path=wrangle)
        assert "{0,0,1}" in str(code)
        validated = call("vex.validate_vex", node_path=wrangle)
        assert validated["is_valid"] is True, validated
        call(
            "vex.create_vex_expression",
            node_path=wrangle,
            parm_name="tx",
            expression="@Frame",
            allow_error=True,
        )

    def test_lops_and_materials_extras(self, call):
        lopnet = call(
            "nodes.create_node", parent_path="/obj", node_type="lopnet", name="stage"
        )["node_path"]
        sphere = call(
            "lops.create_lop_node", parent_path=lopnet, lop_type="sphere"
        )["node_path"]
        call("lops.get_stage_info", node_path=sphere)
        prims = call("lops.list_usd_prims", node_path=sphere)
        assert prims, prims
        rig = call("lops.create_light_rig", parent_path=lopnet, preset="three_point")
        assert rig, rig
        types = call("materials.list_material_types")
        assert "principled" in str(types)

    def test_rendering_and_viewport_extras(self, call, tmp_path):
        rops = call("rendering.list_render_nodes")
        assert rops is not None
        out = str(tmp_path / "net.png").replace("\\", "/")
        call(
            "rendering.render_node_network",
            node_path="/obj",
            output_path=out,
            allow_error=True,
        )
        cam = call(
            "nodes.create_node", parent_path="/obj", node_type="cam", name="cam1"
        )["node_path"]
        call("viewport.set_viewport_camera", camera_path=cam, allow_error=True)

    def test_flip_and_vellum_workflows_build_real_networks(self, call):
        geo = call(
            "nodes.create_node", parent_path="/obj", node_type="geo", name="src"
        )["node_path"]
        sphere = call("nodes.create_node", parent_path=geo, node_type="sphere")
        flip = call("workflow.setup_flip_sim", source_geo=sphere["node_path"])
        assert flip["success"] is True
        for path in flip.get("all_nodes", []):
            assert hou.node(path) is not None, f"claimed node missing: {path}"

        cloth_geo = call(
            "nodes.create_node", parent_path="/obj", node_type="geo", name="cloth"
        )["node_path"]
        call("nodes.create_node", parent_path=cloth_geo, node_type="grid")
        vellum = call("workflow.setup_vellum_sim", geo_path=cloth_geo)
        assert vellum["success"] is True
        for path in vellum.get("all_nodes", []):
            assert hou.node(path) is not None, f"claimed node missing: {path}"


class TestAnimationModule:
    def test_remaining_animation_commands(self, call):
        geo = call(
            "nodes.create_node", parent_path="/obj", node_type="geo", name="g"
        )["node_path"]
        call(
            "animation.set_keyframes",
            node_path=geo,
            parm_name="tx",
            keyframes=[{"frame": 1, "value": 0.0}, {"frame": 10, "value": 2.0}],
        )
        call("animation.delete_keyframe", node_path=geo, parm_name="tx", frame=10)
        keys = call("animation.get_keyframes", node_path=geo, parm_name="tx")
        assert "1" in str(keys), keys
        call("animation.set_frame_range", start=1, end=100)
        assert hou.playbar.frameRange() == hou.Vector2(1, 100)
        call("animation.set_playback_range", start=1, end=50)
        call("animation.set_frame", frame=25)
        frame = call("animation.get_frame")
        assert "25" in str(frame)
        call("animation.playbar_control", action="stop", allow_error=True)
