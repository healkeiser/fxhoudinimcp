"""export_file of a SOP creates the missing directory.

Geometry.saveToFile does not: "Could not write to the specified file" until
the directory existed. A LOP's stage.Export, a ROP's render (mkpath),
createDigitalAsset, copyToHDAFile and hipFile.save create it themselves.

hou is mocked here; the live check ran on Houdini 22.0.466.
"""

from __future__ import annotations

# Built-in
import os
import sys
from unittest.mock import MagicMock

# Third-party
import pytest

sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))


class TestExportMakesTheDirectory:
    @pytest.fixture
    def sop(self, monkeypatch, tmp_path):
        import fxhoudinimcp_server.handlers.scene_handlers as scene

        monkeypatch.setattr(scene, "require_inside_project_root", lambda path, what="": path)
        # The shared hou mock would expand the path into a MagicMock, which
        # os.makedirs then creates as a directory named after the mock.
        monkeypatch.setattr(scene.hou.text, "expandString", lambda s: s, raising=False)
        node = MagicMock()
        node.type.return_value.category.return_value.name.return_value = "Sop"
        written = []

        def save(path):
            if not os.path.isdir(os.path.dirname(path)):
                raise RuntimeError("Could not write to the specified file")
            written.append(path)

        node.geometry.return_value.saveToFile.side_effect = save
        monkeypatch.setattr(scene.hou, "node", lambda path: node)
        monkeypatch.setattr(scene.hou, "frame", lambda: 1.0)
        monkeypatch.setattr(scene.hou, "setFrame", lambda f: None)
        return scene, tmp_path, written

    def test_one_file_into_a_new_directory(self, sop):
        scene, root, written = sop
        result = scene.export_file("/obj/g/b", str(root / "out" / "b.bgeo"))
        assert written == [str(root / "out" / "b.bgeo")]
        assert result["success"] is True

    def test_a_frame_range_into_a_new_directory(self, sop):
        scene, root, written = sop
        scene.export_file("/obj/g/b", str(root / "seq" / "b.bgeo"), frame_range=[1, 2])
        assert [os.path.basename(p) for p in written] == ["b.0001.bgeo", "b.0002.bgeo"]
