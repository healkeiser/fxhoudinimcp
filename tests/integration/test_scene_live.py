"""Live scene-handler tests: info accuracy and file roundtrips."""

from __future__ import annotations

# Built-in
import os

# Third-party
import hou
import pytest

pytestmark = pytest.mark.integration


class TestSceneInfo:
    def test_scene_info_matches_hou(self, call):
        data = call("scene.get_scene_info")
        flat = str(data)
        assert hou.applicationVersionString() in flat
        assert str(hou.fps()) in flat or str(int(hou.fps())) in flat

    def test_new_scene_clears_obj(self, call):
        call("nodes.create_node", parent_path="/obj", node_type="geo", name="geo1")
        call("scene.new_scene")
        assert hou.node("/obj/geo1") is None


class TestFileRoundtrip:
    def test_export_then_import_preserves_geometry(self, call, tmp_path):
        geo = call("nodes.create_node", parent_path="/obj", node_type="geo", name="geo1")[
            "node_path"
        ]
        box = call("nodes.create_node", parent_path=geo, node_type="box")
        out = tmp_path / "box.bgeo.sc"
        call(
            "scene.export_file",
            node_path=box["node_path"],
            file_path=str(out).replace("\\", "/"),
        )
        assert out.exists(), "export_file claimed success but wrote no file"

        data = call(
            "scene.import_file",
            file_path=str(out).replace("\\", "/"),
            node_name="reimported",
        )
        flat = str(data)
        imported = hou.node("/obj/reimported")
        assert imported is not None, f"import_file result: {flat}"
        sops = imported.children() if imported.children() else ()
        assert sops, "imported container has no SOPs"
        assert sops[0].geometry().intrinsicValue("pointcount") == 8


class TestExportFileTellsTheTruth:
    """export_file's Driver branch was the same false-success bug as start_render.

    It called ``node.render()`` and returned the hardcoded string "Render
    complete.", reading no errors and checking no file -- so pointing it at a ROP
    that shells out to husk or mantra would report completion while the renderer
    exited non-zero. It also ignored ``file_path`` entirely, rendering to whatever
    the ROP's own output parm already said, while its docstring promised
    ``file_path`` was the destination.
    """

    @pytest.fixture
    def rop(self, call):
        """A geometry ROP in /out -- category Driver, unlike a rop_geometry SOP."""
        geo = call("nodes.create_node", parent_path="/obj", node_type="geo", name="exportgeo")[
            "node_path"
        ]
        box = hou.node(geo).createNode("box")
        driver = hou.node("/out").createNode("geometry")
        driver.parm("soppath").set(box.path())
        assert driver.type().category().name() == "Driver"
        return driver

    def test_it_writes_to_the_path_it_was_given(self, call, rop, tmp_path):
        out = str(tmp_path / "asked_for.bgeo.sc").replace("\\", "/")
        rop.parm("sopoutput").set(str(tmp_path / "ignored.bgeo.sc").replace("\\", "/"))

        result = call("scene.export_file", node_path=rop.path(), file_path=out)
        assert result["success"] is True, result
        assert result["wrote_files"] is True, result
        # The bug: file_path was accepted and discarded.
        assert os.path.isfile(out), f"claimed success, wrote nothing to {out}: {result}"
        assert not os.path.exists(str(tmp_path / "ignored.bgeo.sc"))

    def test_an_unwritable_destination_is_reported_as_failure(self, call, rop, unwritable_dir):
        result = call(
            "scene.export_file",
            node_path=rop.path(),
            file_path=f"{unwritable_dir}/nope.bgeo.sc",
        )
        assert result["success"] is False, result
        assert result.get("errors") or result.get("error"), result
        assert result["wrote_files"] is False, result
        # The old answer was literally "Render complete." regardless.
        assert "Render complete." not in str(result), result

    def test_it_puts_the_rops_output_path_back(self, call, rop, tmp_path):
        """Repointing the ROP is a means, not the request.

        Leaving it aimed at a temp file the artist never chose is a silent scene
        mutation that would surface later as a render going to the wrong place.
        """
        original = str(tmp_path / "artists_own_choice.bgeo.sc").replace("\\", "/")
        rop.parm("sopoutput").set(original)
        call(
            "scene.export_file",
            node_path=rop.path(),
            file_path=str(tmp_path / "elsewhere.bgeo.sc").replace("\\", "/"),
        )
        assert rop.parm("sopoutput").unexpandedString() == original

    def test_a_frame_range_export_does_not_move_the_playbar(self, call, tmp_path):
        """The SOP loop called hou.setFrame per frame and never restored it.

        Every later query then silently saw a different frame than the user left
        the scene on.
        """
        geo = call("nodes.create_node", parent_path="/obj", node_type="geo", name="framegeo")[
            "node_path"
        ]
        box = hou.node(geo).createNode("box")
        hou.setFrame(7)

        result = call(
            "scene.export_file",
            node_path=box.path(),
            file_path=str(tmp_path / "seq.bgeo.sc").replace("\\", "/"),
            frame_range=[1, 3],
        )
        assert result["success"] is True, result
        assert hou.frame() == 7, f"export moved the playbar to {hou.frame()}"
        assert result["restored_frame"] == 7, result
        assert len(list(tmp_path.glob("seq.*.bgeo.sc"))) == 3, result


class TestSetViewerContext:
    """Moving the VIEWER, not the network editor.

    This is the prerequisite for a Solaris preview: without a scene graph view
    there is no Hydra delegate and no USD camera to bind. A recorded session
    burned several execute_python calls on it.
    """

    def test_headless_says_there_is_no_viewer(self, call):
        if hou.isUIAvailable():
            pytest.skip("graphical session: covered by gui_session_check.py instead")
        error = call("viewport.set_viewer_context", network_path="/stage", expect_error=True)
        # The useful failure is "no Scene Viewer", not an AttributeError from
        # somewhere inside hou.ui.
        assert error["message"].strip(), error


class TestLoadSceneMerge:
    @pytest.fixture
    def source_hip(self, tmp_path):
        obj = hou.node("/obj")
        obj.createNode("null", "null1")
        building = obj.createNode("geo", "building")
        building.createNode("box", "walls")
        obj.createNode("geo", "geo1").createNode("sphere", "sphere1")
        path = str(tmp_path / "source.hip").replace("\\", "/")
        hou.hipFile.save(path)
        hou.hipFile.clear(suppress_save_prompt=True)
        return path

    def test_named_nodes_arrive_and_a_collision_is_renumbered(self, call, source_hip):
        hou.node("/obj").createNode("null", "null1")
        data = call(
            "scene.load_scene",
            file_path=source_hip,
            merge=True,
            node_paths=["/obj/null1", "/obj/building"],
        )
        assert data["success"] is True
        assert data["merged_nodes"] == ["/obj/building", "/obj/null2"]
        assert hou.node("/obj/building/walls") is not None
        assert data["conflicts"] == [
            {
                "requested": "/obj/null1",
                "outcome": "merged under a new name",
                "merged_as": "/obj/null2",
            }
        ]

    def test_a_node_merged_into_an_existing_container_is_reported(self, call, source_hip):
        hou.node("/obj").createNode("geo", "geo1")
        data = call(
            "scene.load_scene", file_path=source_hip, merge=True, node_paths=["/obj/geo1/sphere1"]
        )
        assert data["merged_nodes"] == ["/obj/geo1/sphere1"]
        assert hou.node("/obj/geo1/sphere1") is not None

    def test_a_node_absent_from_the_file_is_not_found_and_not_success(self, call, source_hip):
        hou.node("/obj").createNode("null", "local_only")
        data = call(
            "scene.load_scene", file_path=source_hip, merge=True, node_paths=["/obj/local_only"]
        )
        assert data["success"] is False
        assert data["not_found_in_file"] == ["/obj/local_only"]
        assert data["conflicts"] == []

    def test_an_empty_list_merges_nothing(self, call, source_hip):
        data = call("scene.load_scene", file_path=source_hip, merge=True, node_paths=[])
        assert data["merged_nodes"] == []
        assert hou.node("/obj").children() == ()
