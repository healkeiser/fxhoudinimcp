"""Tests for the command dispatcher."""

from __future__ import annotations

# Built-in
import os
import sys
from unittest.mock import MagicMock

# Third-party
import pytest

# Mock Houdini modules before importing dispatcher
sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Force hython fallback (no hdefereval threading)
import fxhoudinimcp_server.dispatcher as _disp  # noqa: E402
from fxhoudinimcp_server.dispatcher import (  # noqa: E402
    _handler_registry,
    dispatch,
    list_commands,
    register_handler,
)

_disp.HAS_HDEFEREVAL = False


class TestHandlerRegistry:
    def setup_method(self):
        """Clear registry before each test."""
        _handler_registry.clear()

    def test_register_and_list(self):
        register_handler("b.cmd", lambda: None)
        register_handler("a.cmd", lambda: None)
        register_handler("c.cmd", lambda: None)
        assert list_commands() == ["a.cmd", "b.cmd", "c.cmd"]

    def test_register_overwrites(self):
        def fn1():
            return "first"

        def fn2():
            return "second"

        register_handler("test.cmd", fn1)
        register_handler("test.cmd", fn2)
        assert _handler_registry["test.cmd"] is fn2

    def test_list_empty(self):
        assert list_commands() == []


class TestDispatch:
    def setup_method(self):
        _handler_registry.clear()

    def test_success(self):
        def handler(name="world"):
            return {"greeting": f"hello {name}"}

        register_handler("test.greet", handler)
        result = dispatch("test.greet", {"name": "claude"})

        assert result["status"] == "success"
        assert result["data"] == {"greeting": "hello claude"}
        assert "timing_ms" in result
        assert isinstance(result["timing_ms"], float)

    def test_unknown_command(self):
        result = dispatch("nonexistent.command", {})
        assert result["status"] == "error"
        assert result["error"]["code"] == "UNKNOWN_COMMAND"
        assert "available_commands" in result["error"]

    def test_handler_exception(self):
        def bad_handler(**_):
            raise ValueError("something went wrong")

        register_handler("test.fail", bad_handler)
        result = dispatch("test.fail", {})

        assert result["status"] == "error"
        assert result["error"]["code"] == "ValueError"
        assert "something went wrong" in result["error"]["message"]
        assert "traceback" in result["error"]

    def test_timing_always_present(self):
        register_handler("test.noop", lambda **_: {})
        result = dispatch("test.noop", {})
        assert "timing_ms" in result
        assert result["timing_ms"] >= 0

    def test_handler_with_no_params(self):
        register_handler("test.simple", lambda **_: {"ok": True})
        result = dispatch("test.simple", {})
        assert result["status"] == "success"
        assert result["data"]["ok"] is True


class TestCommandTimeout:
    """FXHOUDINIMCP_TIMEOUT_<COMMAND>, then FXHOUDINIMCP_TIMEOUT, then the default."""

    def test_default(self, monkeypatch):
        monkeypatch.delenv("FXHOUDINIMCP_TIMEOUT", raising=False)
        monkeypatch.delenv("FXHOUDINIMCP_TIMEOUT_TOPS_COOK_TOP_NODE", raising=False)
        assert _disp.command_timeout("tops.cook_top_node") == _disp._COMMAND_TIMEOUT

    def test_global_override(self, monkeypatch):
        monkeypatch.setenv("FXHOUDINIMCP_TIMEOUT", "5")
        assert _disp.command_timeout("nodes.create_node") == 5.0

    def test_per_command_wins_over_global(self, monkeypatch):
        monkeypatch.setenv("FXHOUDINIMCP_TIMEOUT", "5")
        monkeypatch.setenv("FXHOUDINIMCP_TIMEOUT_TOPS_COOK_TOP_NODE", "900")
        assert _disp.command_timeout("tops.cook_top_node") == 900.0
        assert _disp.command_timeout("nodes.create_node") == 5.0

    @pytest.mark.parametrize("bad", ["soon", "0", "-3", " "])
    def test_garbage_falls_through(self, monkeypatch, bad):
        monkeypatch.setenv("FXHOUDINIMCP_TIMEOUT_NODES_CREATE_NODE", bad)
        monkeypatch.setenv("FXHOUDINIMCP_TIMEOUT", "7")
        assert _disp.command_timeout("nodes.create_node") == 7.0

    def test_timeout_message_names_the_variable(self, monkeypatch):
        """A caller who hits the wall must be told which knob to turn."""
        import threading

        monkeypatch.setattr(_disp, "HAS_DEFEREVAL", True, raising=False)
        monkeypatch.setattr(_disp, "HAS_HDEFEREVAL", True)
        monkeypatch.setenv("FXHOUDINIMCP_TIMEOUT_SLOW_CMD", "0.05")
        release = threading.Event()
        fake = MagicMock()
        fake.executeInMainThreadWithResult = lambda fn: (release.wait(2), fn())[1]
        monkeypatch.setattr(_disp, "hdefereval", fake)
        _handler_registry.clear()
        register_handler("slow.cmd", lambda: {"ok": True})
        try:
            result = dispatch("slow.cmd", {})
        finally:
            release.set()
        assert result["status"] == "error"
        assert result["error"]["code"] == "TIMEOUT"
        assert "FXHOUDINIMCP_TIMEOUT_SLOW_CMD" in result["error"]["message"]


class TestUndoGroup:
    """One dispatched command is one undo step."""

    def setup_method(self):
        _handler_registry.clear()

    def test_handler_runs_inside_a_group_named_for_the_command(self, monkeypatch):
        hou = sys.modules["hou"]
        group = MagicMock()
        group.__enter__ = MagicMock(return_value=None)
        group.__exit__ = MagicMock(return_value=False)
        hou.undos.group = MagicMock(return_value=group)
        seen = []
        register_handler("nodes.create_node", lambda: seen.append(group.__enter__.called) or {})
        dispatch("nodes.create_node", {})
        hou.undos.group.assert_called_once_with("MCP nodes.create_node")
        assert seen == [True], "handler ran before the undo group opened"
        assert group.__exit__.called

    @pytest.mark.parametrize("command", ["scene.undo", "scene.redo"])
    def test_undo_itself_is_not_grouped(self, monkeypatch, command):
        hou = sys.modules["hou"]
        hou.undos.group = MagicMock()
        register_handler(command, lambda: {})
        dispatch(command, {})
        hou.undos.group.assert_not_called()

    def test_a_group_that_cannot_open_does_not_block_the_command(self):
        hou = sys.modules["hou"]
        hou.undos.group = MagicMock(side_effect=RuntimeError("no undo here"))
        register_handler("x.cmd", lambda: {"ran": True})
        assert dispatch("x.cmd", {})["data"] == {"ran": True}
