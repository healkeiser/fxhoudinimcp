"""Live scene-handler tests: info accuracy and file roundtrips."""

from __future__ import annotations

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
