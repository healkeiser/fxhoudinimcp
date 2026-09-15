"""in Manual update mode create_curve answered success with point_count 0.

Nothing cooks on its own in Manual mode, so the node's read-back was empty
and no reply said why; get_scene_info did not show the mode either. The
config helper names the mode, cooked-evidence verbs attach a warning,
create_curve cooks its own node, and get_scene_info carries update_mode.

hou is mocked here; the live check ran on Houdini 22.0.429.
"""

from __future__ import annotations

# Built-in
import os
import sys
from unittest.mock import MagicMock

sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Internal
import fxhoudinimcp_server.config as config  # noqa: E402
import fxhoudinimcp_server.handlers.graph_handlers as graph  # noqa: E402

hou = config.hou


class TestUpdateModeIsNamedAndWarnedAbout:
    def test_auto_gives_no_warning(self, monkeypatch):
        monkeypatch.setattr(hou, "updateModeSetting", lambda: hou.updateMode.AutoUpdate)
        assert config.update_mode_name() == "auto"
        assert config.update_mode_warning() is None

    def test_manual_is_named_and_points_at_the_fix(self, monkeypatch):
        monkeypatch.setattr(hou, "updateModeSetting", lambda: hou.updateMode.Manual)
        assert config.update_mode_name() == "manual"
        warning = config.update_mode_warning()
        assert "'manual'" in warning
        assert "set_update_mode('auto')" in warning

    def test_an_unanswerable_hou_is_not_an_error(self, monkeypatch):
        def boom():
            raise RuntimeError("no hou here")

        monkeypatch.setattr(hou, "updateModeSetting", boom)
        assert config.update_mode_name() is None
        assert config.update_mode_warning() is None


class TestGeometryEvidenceCarriesTheWarning:
    def _node(self):
        node = MagicMock()
        geo = node.geometry.return_value
        geo.intrinsicValue.side_effect = lambda name: 0
        geo.boundingBox.return_value.minvec.return_value = (0, 0, 0)
        geo.boundingBox.return_value.maxvec.return_value = (0, 0, 0)
        geo.pointAttribs.return_value = []
        return node

    def test_build_network_summary_says_why_zero_points(self, monkeypatch):
        monkeypatch.setattr(graph, "update_mode_warning", lambda: "Update mode is 'manual': …")
        summary = graph._geometry_summary(self._node())
        assert summary["points"] == 0
        assert summary["warning"].startswith("Update mode is 'manual'")

    def test_no_warning_key_in_auto(self, monkeypatch):
        monkeypatch.setattr(graph, "update_mode_warning", lambda: None)
        assert "warning" not in graph._geometry_summary(self._node())
