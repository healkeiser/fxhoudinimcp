"""MCP tool wrappers for Houdini takes (parameter override system).

Each tool delegates to the corresponding handler running inside Houdini
via the HTTP bridge.
"""

from __future__ import annotations

# Built-in
from typing import Optional

# Third-party
from mcp.server.fastmcp import Context

# Internal
from fxhoudinimcp.server import mcp, _get_bridge


@mcp.tool()
async def list_takes(ctx: Context) -> dict:
    """List all takes in the scene with their hierarchy."""
    bridge = _get_bridge(ctx)
    return await bridge.execute("takes.list_takes", {})


@mcp.tool()
async def get_current_take(ctx: Context) -> dict:
    """Get the current take and its overridden parameters."""
    bridge = _get_bridge(ctx)
    return await bridge.execute("takes.get_current_take", {})


@mcp.tool()
async def set_current_take(ctx: Context, name: str) -> dict:
    """Set the current take by name.

    Args:
        name: Take name to make current.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "takes.set_current_take",
        {
            "name": name,
        },
    )


@mcp.tool()
async def create_take(
    ctx: Context,
    name: str,
    parent_name: Optional[str] = None,
) -> dict:
    """Create a new take, optionally under a parent take.

    Args:
        name: Name for the new take.
        parent_name: Parent take name (defaults to current take).
    """
    bridge = _get_bridge(ctx)
    params: dict = {"name": name}
    if parent_name is not None:
        params["parent_name"] = parent_name
    return await bridge.execute("takes.create_take", params)
