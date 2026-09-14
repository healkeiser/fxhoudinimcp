"""Tests for the FXHOUDINIMCP_AUTO_LAYOUT toggle (GitHub issue #2)."""

from __future__ import annotations

# Built-in
import os
import sys
from unittest.mock import MagicMock

# Third-party
import pytest

# Mock Houdini modules before importing the in-Houdini server package
sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Internal
import fxhoudinimcp_server.config as houdini_config  # noqa: E402

from fxhoudinimcp._loader import load_markdown  # noqa: E402
from fxhoudinimcp.config import auto_layout_enabled  # noqa: E402
from fxhoudinimcp.tools.nodes import layout_children  # noqa: E402


class TestAutoLayoutFlag:
    def test_default_disabled(self, monkeypatch):
        monkeypatch.delenv("FXHOUDINIMCP_AUTO_LAYOUT", raising=False)
        assert auto_layout_enabled() is False

    @pytest.mark.parametrize("value", ["0", "false", "OFF", " no "])
    def test_disabled_values(self, monkeypatch, value):
        monkeypatch.setenv("FXHOUDINIMCP_AUTO_LAYOUT", value)
        assert auto_layout_enabled() is False

    @pytest.mark.parametrize("value", ["1", "true", "on", "yes"])
    def test_enabled_values(self, monkeypatch, value):
        monkeypatch.setenv("FXHOUDINIMCP_AUTO_LAYOUT", value)
        assert auto_layout_enabled() is True


class TestLayoutGuidance:
    def test_instructions_promote_layout_when_enabled(self, monkeypatch):
        monkeypatch.setenv("FXHOUDINIMCP_AUTO_LAYOUT", "1")
        text = load_markdown("instructions/server_instructions.md")
        assert "Call layout_children frequently" in text

    def test_instructions_forbid_layout_when_disabled(self, monkeypatch):
        monkeypatch.setenv("FXHOUDINIMCP_AUTO_LAYOUT", "0")
        text = load_markdown("instructions/server_instructions.md")
        assert "NEVER call layout_children" in text
        assert "Call layout_children frequently" not in text

    def test_housekeeping_block_follows_toggle(self, monkeypatch):
        monkeypatch.setenv("FXHOUDINIMCP_AUTO_LAYOUT", "0")
        text = load_markdown(
            "workflows/model.md",
            description="a rock",
            output_context="/obj",
        )
        assert "NEVER call layout_children" in text


class TestLayoutChildrenTool:
    @pytest.mark.asyncio
    async def test_skipped_when_disabled(self, monkeypatch, mock_ctx, mock_bridge):
        monkeypatch.setenv("FXHOUDINIMCP_AUTO_LAYOUT", "0")
        result = await layout_children(mock_ctx, parent_path="/obj/geo1")
        assert result["skipped"] is True
        mock_bridge.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_executes_when_enabled(self, monkeypatch, mock_ctx, mock_bridge):
        monkeypatch.setenv("FXHOUDINIMCP_AUTO_LAYOUT", "1")
        await layout_children(mock_ctx, parent_path="/obj/geo1")
        mock_bridge.execute.assert_called_once_with(
            "nodes.layout_children", {"parent_path": "/obj/geo1"}
        )


class TestHoudiniSideConfig:
    def test_layout_if_enabled_skips_when_disabled(self, monkeypatch):
        monkeypatch.setattr(houdini_config.hou, "getenv", lambda name: "0")
        node = MagicMock()
        houdini_config.layout_if_enabled(node)
        node.layoutChildren.assert_not_called()

    def test_layout_if_enabled_skips_by_default(self, monkeypatch):
        monkeypatch.setattr(houdini_config.hou, "getenv", lambda name: None)
        monkeypatch.delenv("FXHOUDINIMCP_AUTO_LAYOUT", raising=False)
        node = MagicMock()
        houdini_config.layout_if_enabled(node)
        node.layoutChildren.assert_not_called()

    def test_layout_if_enabled_lays_out_when_opted_in(self, monkeypatch):
        monkeypatch.setattr(houdini_config.hou, "getenv", lambda name: "1")
        node = MagicMock()
        houdini_config.layout_if_enabled(node)
        node.layoutChildren.assert_called_once()

    def test_process_env_fallback(self, monkeypatch):
        monkeypatch.setattr(houdini_config.hou, "getenv", lambda name: None)
        monkeypatch.setenv("FXHOUDINIMCP_AUTO_LAYOUT", "0")
        assert houdini_config.auto_layout_enabled() is False


class TestProjectRootSandbox:
    @pytest.fixture(autouse=True)
    def plain_hou(self, monkeypatch):
        monkeypatch.setattr(houdini_config.hou, "getenv", lambda name: None)
        monkeypatch.setattr(houdini_config.hou.text, "expandString", lambda s: s)
        monkeypatch.delenv("FXHOUDINIMCP_PROJECT_ROOT", raising=False)

    def test_unset_means_no_limit(self, tmp_path):
        assert houdini_config.project_root() is None
        anywhere = str(tmp_path / "x.hip")
        assert houdini_config.require_inside_project_root(anywhere) == anywhere

    def test_inside_passes_and_outside_is_named(self, monkeypatch, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        monkeypatch.setenv("FXHOUDINIMCP_PROJECT_ROOT", str(root))
        inside = str(root / "shots" / "a.hip")
        assert houdini_config.require_inside_project_root(inside, "hip file") == inside
        with pytest.raises(PermissionError) as excinfo:
            houdini_config.require_inside_project_root(str(tmp_path / "b.hip"), "hip file")
        message = str(excinfo.value)
        assert "hip file" in message and "b.hip" in message and str(root.resolve()) in message

    def test_dot_dot_does_not_escape(self, monkeypatch, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        monkeypatch.setenv("FXHOUDINIMCP_PROJECT_ROOT", str(root))
        sneaky = str(root / "sub" / ".." / ".." / "escape.hip")
        with pytest.raises(PermissionError):
            houdini_config.require_inside_project_root(sneaky)

    def test_prefix_of_the_root_name_is_not_inside(self, monkeypatch, tmp_path):
        """/proj must not admit /proj_backup."""
        root = tmp_path / "proj"
        root.mkdir()
        monkeypatch.setenv("FXHOUDINIMCP_PROJECT_ROOT", str(root))
        with pytest.raises(PermissionError):
            houdini_config.require_inside_project_root(str(tmp_path / "proj_backup" / "a.hip"))

    def test_hou_getenv_wins_over_process_env(self, monkeypatch, tmp_path):
        monkeypatch.setattr(houdini_config.hou, "getenv", lambda name: str(tmp_path / "from_hou"))
        monkeypatch.setenv("FXHOUDINIMCP_PROJECT_ROOT", str(tmp_path / "from_os"))
        assert houdini_config.project_root() == os.path.realpath(str(tmp_path / "from_hou"))
