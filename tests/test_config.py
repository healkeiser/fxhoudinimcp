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
    def test_default_enabled(self, monkeypatch):
        monkeypatch.delenv("FXHOUDINIMCP_AUTO_LAYOUT", raising=False)
        assert auto_layout_enabled() is True

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
        monkeypatch.delenv("FXHOUDINIMCP_AUTO_LAYOUT", raising=False)
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
        monkeypatch.delenv("FXHOUDINIMCP_AUTO_LAYOUT", raising=False)
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

    def test_layout_if_enabled_lays_out_by_default(self, monkeypatch):
        monkeypatch.setattr(houdini_config.hou, "getenv", lambda name: None)
        monkeypatch.delenv("FXHOUDINIMCP_AUTO_LAYOUT", raising=False)
        node = MagicMock()
        houdini_config.layout_if_enabled(node)
        node.layoutChildren.assert_called_once()

    def test_process_env_fallback(self, monkeypatch):
        monkeypatch.setattr(houdini_config.hou, "getenv", lambda name: None)
        monkeypatch.setenv("FXHOUDINIMCP_AUTO_LAYOUT", "0")
        assert houdini_config.auto_layout_enabled() is False
