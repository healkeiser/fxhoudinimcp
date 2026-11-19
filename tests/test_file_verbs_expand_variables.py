"""File verbs expand Houdini variables ($JOB, $HIP) in the paths they are given.

load_scene already did; save_scene, import_file, export_file, the HDA library
verbs, get_hda_info and the image verbs passed "$JOB/..." to HOM, os.path or
os.makedirs as written: "Error creating file", "not found", or
"Permission denied: '$JOB'" (a directory named $JOB under Houdini's cwd).

hou is mocked here; the live check ran on Houdini 22.0.466."""

from __future__ import annotations

# Built-in
import contextlib
import os
import sys
from unittest.mock import MagicMock

# Third-party
import pytest

sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Internal
import fxhoudinimcp_server.handlers.hda_handlers as hda  # noqa: E402
import fxhoudinimcp_server.handlers.scene_handlers as scene  # noqa: E402


@pytest.fixture
def job(monkeypatch, tmp_path):
    monkeypatch.setattr(scene.hou.text, "expandString", lambda s: s.replace("$JOB", str(tmp_path)))
    monkeypatch.setattr(scene, "require_inside_project_root", lambda path, what="": path)
    monkeypatch.setattr(hda, "require_inside_project_root", lambda path, what="": path)
    return tmp_path


class TestFileVerbsExpand:
    def test_save_scene(self, job, monkeypatch):
        saved = []
        monkeypatch.setattr(
            scene.hou.hipFile, "save", lambda file_name=None: saved.append(file_name)
        )
        scene.save_scene("$JOB/a.hiplc")
        assert saved == [f"{job}/a.hiplc"]

    def test_import_file_finds_the_file(self, job, monkeypatch):
        (job / "x.bgeo").write_bytes(b"")
        parent = MagicMock()
        parent.childTypeCategory.return_value.name.return_value = "Sop"
        monkeypatch.setattr(scene.hou, "node", lambda path: parent)
        scene.import_file("$JOB/x.bgeo", "/obj/g")
        parent.createNode.return_value.parm.return_value.set.assert_called_with(f"{job}/x.bgeo")

    @pytest.mark.parametrize("verb", ["install_hda", "reload_hda"])
    def test_hda_file_verbs_find_the_file(self, job, monkeypatch, verb):
        (job / "a.hda").write_bytes(b"")
        seen = []
        monkeypatch.setattr(hda.hou.hda, "installFile", lambda path, **k: seen.append(path))
        monkeypatch.setattr(hda.hou.hda, "reloadFile", lambda path: seen.append(path))
        monkeypatch.setattr(hda.hou.hda, "definitionsInFile", lambda path: [], raising=False)
        with contextlib.suppress(Exception):
            getattr(hda, verb)("$JOB/a.hda")
        assert f"{job}/a.hda" in seen

    def test_uninstall_compares_the_expanded_path(self, job, monkeypatch):
        path = f"{job}/a.hda"
        monkeypatch.setattr(hda.hou.hda, "loadedFiles", lambda: [path])
        gone = []
        monkeypatch.setattr(hda.hou.hda, "uninstallFile", gone.append)
        hda.uninstall_hda("$JOB/a.hda")
        assert gone == [path]


class _Stop(Exception):
    pass


class TestOutputPathsExpandVariables:
    """ "$JOB/out/a.png" reached os.makedirs as written: Permission denied: '$JOB'."""

    @pytest.fixture
    def expand(self, monkeypatch):
        import fxhoudinimcp_server.handlers.hda_handlers as hdas
        import fxhoudinimcp_server.handlers.rendering_handlers as rendering
        import fxhoudinimcp_server.handlers.viewport_handlers as viewport

        made = []

        def makedirs(path, exist_ok=False):
            made.append(path)
            raise _Stop

        for module in (rendering, viewport, hdas):
            monkeypatch.setattr(
                module.hou.text, "expandString", lambda s: s.replace("$JOB", "/proj")
            )
            monkeypatch.setattr(module.os, "makedirs", makedirs)
            monkeypatch.setattr(module.os.path, "isdir", lambda p: False)
        return made, rendering, viewport, hdas

    @pytest.mark.parametrize(
        ("module", "verb", "kwargs"),
        [
            ("rendering", "render_viewport", {}),
            ("rendering", "render_quad_view", {}),
            ("rendering", "render_node_network", {"node_path": "/obj"}),
            ("viewport", "capture_screenshot", {}),
            ("viewport", "capture_network_editor", {}),
        ],
    )
    def test_the_directory_made_is_the_expanded_one(self, expand, module, verb, kwargs):
        made, rendering, viewport, _ = expand
        handler = getattr({"rendering": rendering, "viewport": viewport}[module], verb)
        with pytest.raises(_Stop):
            handler(output_path="$JOB/out/a.png", **kwargs)
        assert made == ["/proj/out"]

    def test_get_hda_info_reads_the_expanded_file(self, expand, monkeypatch):
        _, _, _, hdas = expand
        asked = []
        monkeypatch.setattr(hdas.os.path, "isfile", lambda p: asked.append(p) or False)
        with pytest.raises(FileNotFoundError, match="/proj/a.hda"):
            hdas.get_hda_info(hda_file="$JOB/a.hda")
        assert asked == ["/proj/a.hda"]
