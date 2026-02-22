"""hwebserver endpoint registration for the FXHoudini-MCP plugin.

Registers API functions on Houdini's built-in HTTP server that the
external MCP server communicates with over HTTP.

Calling convention (JSON-encoded RPC):
    POST /api
    Body: json=["mcp.execute", [], {"command": "...", "params": {...}, "request_id": "..."}]

hwebserver auto-serialises the returned dict/list to JSON.
"""

from __future__ import annotations

# Built-in
import os

# Third-party
import hwebserver

# Internal
from fxhoudinimcp_server import dispatcher


@hwebserver.apiFunction(namespace="mcp")
def execute(request, command="", params=None, request_id=""):
    """Single entry point for all MCP tool calls.

    Args:
        request: hwebserver.Request (always first arg).
        command: Dotted command name (e.g. "scene.get_scene_info").
        params: Tool-specific parameters dict.
        request_id: Correlation ID echoed back in the response.
    """
    if params is None:
        params = {}

    result = dispatcher.dispatch(command, params)
    result["request_id"] = request_id
    return result


@hwebserver.apiFunction(namespace="mcp")
def health(request):
    """Health check endpoint. Returns Houdini version and session info."""
    import hou

    return {
        "status": "ok",
        "houdini_version": hou.applicationVersionString(),
        "hip_file": hou.hipFile.name(),
        "pid": os.getpid(),
    }


@hwebserver.apiFunction(namespace="mcp")
def list_commands(request):
    """List all registered command names for introspection."""
    return {"commands": dispatcher.list_commands()}
