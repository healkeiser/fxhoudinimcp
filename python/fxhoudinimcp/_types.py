"""Shared type aliases for MCP tool parameters.

Tool parameters must not be annotated with bare ``Any``: pydantic renders
``Any`` as a schema with no ``type`` (e.g. ``{"title": "Value"}``), which
strict MCP clients such as OpenCode reject during JSON Schema conversion.
"""

from __future__ import annotations

# A JSON-compatible parameter or attribute value: scalar or flat list.
Value = bool | int | float | str | list[bool | int | float | str]
