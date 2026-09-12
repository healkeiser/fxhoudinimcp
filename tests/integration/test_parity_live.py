"""Live tests for the tools added for parity with other Houdini MCP servers.

Undo, network boxes, sticky notes, object transforms, PDG failure listing, HDA
versions, file references and the update mode. Each asserts against the scene,
not against the handler's own claim.
"""

from __future__ import annotations

# Built-in
import os

# Third-party
import hou
import pytest

pytestmark = pytest.mark.integration


def _geo(call, name="parity_geo") -> str:
    return call("nodes.create_node", parent_path="/obj", node_type="geo", name=name)["node_path"]


class TestUndoRedo:
    def test_undo_reverses_one_command_whole(self, call):
        geo = _geo(call)
        before = len(hou.node(geo).children())
        call(
            "graph.build_network",
            parent_path=geo,
            nodes=[
                {"name": "a", "type": "box"},
                {"name": "b", "type": "sphere"},
                {"name": "m", "type": "merge", "inputs": ["a", "b"]},
            ],
        )
        assert len(hou.node(geo).children()) == before + 3
        if not hou.undos.areEnabled():
            error = call("scene.undo", expect_error=True)
            assert "graphical" in str(error["message"]).lower()
            call("scene.redo", expect_error=True)
            return
        undone = call("scene.undo")
        assert undone["success"], undone
        # One tool call is one undo step: all three nodes go together.
        assert len(hou.node(geo).children()) == before, undone
        assert "graph.build_network" in undone["undone"][0]
        redone = call("scene.redo")
        assert redone["success"], redone
        assert len(hou.node(geo).children()) == before + 3

    def test_nothing_to_undo_is_reported_not_faked(self, call):
        if not hou.undos.areEnabled():
            pytest.skip("hython keeps no undo history")
        hou.undos.clear()
        answer = call("scene.undo")
        assert answer["success"] is False and "nothing" in answer["message"].lower()
        answer = call("scene.redo")
        assert answer["success"] is False and "nothing" in answer["message"].lower()


class TestNetworkAnnotations:
    def test_network_box_holds_the_named_nodes(self, call):
        geo = _geo(call)
        box = call("nodes.create_node", parent_path=geo, node_type="box")["node_path"]
        sphere = call("nodes.create_node", parent_path=geo, node_type="sphere")["node_path"]
        made = call(
            "nodes.create_network_box",
            parent_path=geo,
            node_paths=[box, sphere],
            comment="inputs",
            color=[0.2, 0.4, 0.8],
        )
        nb = hou.node(geo).findNetworkBox(made["name"])
        assert nb is not None
        assert {n.path() for n in nb.nodes()} == {box, sphere}
        assert nb.comment() == "inputs"
        assert set(made["contains"]) == {box, sphere}

    def test_box_refuses_a_node_from_another_network(self, call):
        geo = _geo(call)
        other = _geo(call, "parity_other")
        stray = call("nodes.create_node", parent_path=other, node_type="box")["node_path"]
        error = call(
            "nodes.create_network_box", parent_path=geo, node_paths=[stray], expect_error=True
        )
        assert stray in error["message"]

    def test_sticky_note_carries_its_text(self, call):
        geo = _geo(call)
        made = call(
            "nodes.create_sticky_note",
            parent_path=geo,
            text="built by the parity suite",
            position=[3.0, 1.5],
        )
        note = hou.node(geo).findStickyNote(made["name"])
        assert note is not None
        assert note.text() == "built by the parity suite"
        assert tuple(note.position()) == (3.0, 1.5)


class TestObjectTransform:
    def test_sets_only_what_it_was_given(self, call):
        geo = _geo(call)
        hou.node(geo).parmTuple("s").set((2, 2, 2))
        result = call(
            "nodes.set_object_transform", node_path=geo, translate=[1, 2, 3], rotate=[0, 90, 0]
        )
        node = hou.node(geo)
        assert tuple(node.parmTuple("t").eval()) == (1.0, 2.0, 3.0)
        assert tuple(node.parmTuple("r").eval()) == (0.0, 90.0, 0.0)
        assert tuple(node.parmTuple("s").eval()) == (2.0, 2.0, 2.0), "scale must be untouched"
        assert result["translate"] == [1.0, 2.0, 3.0]

    def test_parent_and_unparent(self, call):
        child = _geo(call, "parity_child")
        parent = _geo(call, "parity_parent")
        call("nodes.set_object_transform", node_path=child, parent=parent)
        assert hou.node(child).inputs()[0].path() == parent
        call("nodes.set_object_transform", node_path=child, parent="")
        assert not hou.node(child).inputs()

    def test_refuses_a_sop(self, call):
        geo = _geo(call)
        box = call("nodes.create_node", parent_path=geo, node_type="box")["node_path"]
        error = call(
            "nodes.set_object_transform", node_path=box, translate=[1, 0, 0], expect_error=True
        )
        assert "object" in error["message"].lower()

    def test_refuses_nothing_to_do(self, call):
        geo = _geo(call)
        error = call("nodes.set_object_transform", node_path=geo, expect_error=True)
        assert "nothing" in error["message"].lower()


class TestPdgFailures:
    @pytest.fixture
    def failing_top(self, call) -> str:
        topnet = call(
            "nodes.create_node", parent_path="/obj", node_type="topnet", name="parity_pdg"
        )["node_path"]
        gen = hou.node(topnet).createNode("genericgenerator")
        gen.parm("itemcount").set(2)
        script = gen.createOutputNode("pythonscript")
        script.parm("script").set("raise RuntimeError('parity: deliberate failure')")
        # By default the Python Script TOP runs its script while *generating*, so a
        # raise there yields zero work items and a node error, not failed items.
        script.parm("pdg_cooktype").set(1)  # Cook (In-Process)
        script.setDisplayFlag(True)
        call("tops.generate_static_items", node_path=script.path())
        call("tops.cook_top_node", node_path=script.path(), block=True, allow_error=True)
        states = call("tops.get_work_item_states", node_path=script.path())
        assert states["total_work_items"] > 0, f"the failing TOP produced no work items: {states}"
        return script.path()

    def test_failed_items_are_listed(self, call, failing_top):
        failed = call("tops.get_failed_work_items", node_path=failing_top)
        states = call("tops.get_work_item_states", node_path=failing_top)["state_counts"]
        assert failed["failed_count"] == states.get("cooked_fail", 0), (failed, states)
        assert all(item["state"] == "cooked_fail" for item in failed["failed"])

    def test_node_logs_and_item_logs(self, call, failing_top):
        node_level = call("tops.get_top_logs", node_path=failing_top)
        assert "errors" in node_level and "warnings" in node_level
        item_level = call("tops.get_top_logs", node_path=failing_top, work_item_index=0)
        assert item_level["work_item"]["index"] == 0
        assert "log" in item_level
        error = call(
            "tops.get_top_logs", node_path=failing_top, work_item_index=999, expect_error=True
        )
        assert "999" in error["message"]


class TestHdaVersions:
    def test_lists_the_definition_it_was_created_with(self, call, tmp_path):
        geo = _geo(call)
        sub = hou.node(geo).createNode("subnet", "parity_sub")
        hda_file = str(tmp_path / "parity.hda").replace("\\", "/")
        made = call(
            "hda.create_hda",
            node_path=sub.path(),
            hda_file=hda_file,
            type_name="parity::asset",
            label="Parity",
            version="2.3",
        )
        versions = call("hda.list_hda_versions", node_path=made["node_path"])
        assert versions["current_version"] == "2.3"
        assert any(
            os.path.normpath(v["library_file"]) == os.path.normpath(hda_file) and v["is_current"]
            for v in versions["versions"]
        ), versions

    def test_refuses_a_plain_node(self, call):
        geo = _geo(call)
        error = call("hda.list_hda_versions", node_path=geo, expect_error=True)
        assert "not an HDA" in error["message"]


class TestFileReferences:
    def test_reports_the_path_and_whether_it_exists(self, call, tmp_path):
        geo = _geo(call)
        file_sop = hou.node(geo).createNode("file")
        missing = str(tmp_path / "does_not_exist.bgeo").replace("\\", "/")
        file_sop.parm("file").set(missing)
        refs = call("code.get_file_references", include_missing_only=True)
        ours = [r for r in refs["references"] if r["parm"] == file_sop.parm("file").path()]
        assert ours and ours[0]["exists"] is False and ours[0]["path"] == missing, refs


class TestUpdateMode:
    def test_round_trip(self, call):
        original = hou.updateModeSetting()
        try:
            assert call("code.set_update_mode", mode="manual")["mode"] == "manual"
            assert hou.updateModeSetting() == hou.updateMode.Manual
            assert call("code.set_update_mode")["mode"] == "manual"
            assert call("code.set_update_mode", mode="auto")["mode"] == "auto"
            assert hou.updateModeSetting() == hou.updateMode.AutoUpdate
        finally:
            hou.setUpdateMode(original)

    def test_unknown_mode_names_the_choices(self, call):
        error = call("code.set_update_mode", mode="sometimes", expect_error=True)
        assert "manual" in error["message"] and "sometimes" in error["message"]


class TestProjectRootSandbox:
    def test_paths_outside_the_root_are_refused_and_inside_allowed(
        self, call, tmp_path, monkeypatch
    ):
        root = tmp_path / "project"
        root.mkdir()
        monkeypatch.setenv("FXHOUDINIMCP_PROJECT_ROOT", str(root))
        hou.putenv("FXHOUDINIMCP_PROJECT_ROOT", str(root))
        try:
            geo = _geo(call)
            box = call("nodes.create_node", parent_path=geo, node_type="box")["node_path"]
            outside = str(tmp_path / "escape.bgeo").replace("\\", "/")
            error = call("scene.export_file", node_path=box, file_path=outside, expect_error=True)
            assert (
                "FXHOUDINIMCP_PROJECT_ROOT" in error["message"]
                and "escape.bgeo" in error["message"]
            )
            assert not os.path.exists(outside)
            inside = str(root / "kept.bgeo").replace("\\", "/")
            call("scene.export_file", node_path=box, file_path=inside)
            assert os.path.exists(inside)
            error = call("scene.load_scene", file_path=outside, expect_error=True)
            assert "FXHOUDINIMCP_PROJECT_ROOT" in error["message"]
        finally:
            hou.unsetenv("FXHOUDINIMCP_PROJECT_ROOT")
