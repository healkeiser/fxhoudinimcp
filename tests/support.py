"""Test helpers that paper over differences between mcp majors.

Kept out of conftest.py because tests/integration/ has its own conftest, so a
bare ``from conftest import ...`` resolves to whichever one pytest inserted
first rather than to this package's.
"""

from __future__ import annotations


def tool_input_schema(tool):
    """The tool's JSON Schema, whichever mcp major produced it.

    mcp 2.0 renamed Tool.inputSchema to Tool.input_schema. Reading the wrong one
    raises AttributeError from deep inside pydantic, which reads like a broken
    test rather than an SDK rename.
    """
    schema = getattr(tool, "input_schema", None)
    return schema if schema is not None else tool.inputSchema
