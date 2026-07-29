"""Tests for pure serialization and helper functions."""

from __future__ import annotations

# Built-in
import json
import os
import sys
from unittest.mock import MagicMock

# Internal
from fxhoudinimcp.bridge import _rpc_body

# Mock `hou` before importing Houdini-side helpers
sys.modules.setdefault("hou", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

from fxhoudinimcp_server.handlers.code_handlers import (  # noqa: E402
    _MAX_CAPTURE_BYTES,
    _serialize_result,
    _truncate_output,
)


class TestRpcBody:
    def test_with_kwargs(self):
        body = _rpc_body("mcp.execute", command="test", params={"a": 1})
        parsed = json.loads(body["json"])
        assert parsed[0] == "mcp.execute"
        assert parsed[1] == []
        assert parsed[2] == {"command": "test", "params": {"a": 1}}

    def test_no_kwargs(self):
        body = _rpc_body("mcp.health")
        parsed = json.loads(body["json"])
        assert parsed == ["mcp.health", [], {}]

    def test_returns_dict_with_json_key(self):
        body = _rpc_body("fn")
        assert isinstance(body, dict)
        assert "json" in body
        assert isinstance(body["json"], str)


class TestTruncateOutput:
    def test_empty_string(self):
        assert _truncate_output("") == ""

    def test_short_string_unchanged(self):
        assert _truncate_output("hello") == "hello"

    def test_exact_limit_unchanged(self):
        text = "x" * _MAX_CAPTURE_BYTES
        assert _truncate_output(text) == text

    def test_over_limit_truncated(self):
        text = "x" * (_MAX_CAPTURE_BYTES + 1000)
        result = _truncate_output(text)
        assert result.endswith("\n[truncated]")
        assert len(result) == _MAX_CAPTURE_BYTES + len("\n[truncated]")


class TestSerializeResult:
    def test_none(self):
        assert _serialize_result(None) is None

    def test_primitives(self):
        assert _serialize_result(True) is True
        assert _serialize_result(42) == 42
        assert _serialize_result(3.14) == 3.14
        assert _serialize_result("hello") == "hello"

    def test_bytes(self):
        assert _serialize_result(b"hello") == "hello"

    def test_bytes_with_invalid_utf8(self):
        result = _serialize_result(b"\xff\xfe")
        assert isinstance(result, str)

    def test_list(self):
        assert _serialize_result([1, 2, 3]) == [1, 2, 3]

    def test_tuple_becomes_list(self):
        assert _serialize_result((1, 2)) == [1, 2]

    def test_nested_list(self):
        assert _serialize_result([1, [2, 3]]) == [1, [2, 3]]

    def test_dict(self):
        assert _serialize_result({"a": 1, "b": "x"}) == {"a": 1, "b": "x"}

    def test_dict_with_non_string_keys(self):
        result = _serialize_result({1: "a", 2: "b"})
        assert result == {"1": "a", "2": "b"}

    def test_nested_structures(self):
        data = {"list": [1, (2, 3)], "nested": {"key": b"val"}}
        result = _serialize_result(data)
        assert result == {"list": [1, [2, 3]], "nested": {"key": "val"}}

    def test_arbitrary_object_becomes_string(self):
        class Foo:
            def __str__(self):
                return "I am Foo"

        result = _serialize_result(Foo())
        assert result == "I am Foo"
