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
    """List all takes in the Houdini scene with their hierarchy.

    Returns each take's name, whether it is the current take,
    its parent name, and children names.

    Args:
        ctx: MCP context.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("takes.list_takes", {})


@mcp.tool()
async def get_current_take(ctx: Context) -> dict:
    """Get the current Houdini take and list its overridden parameters.

    Returns the take name and all parameters overridden in this take
    with their node paths, parameter names, and current values.

    Args:
        ctx: MCP context.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("takes.get_current_take", {})


@mcp.tool()
async def set_current_take(ctx: Context, name: str) -> dict:
    """Set the current take in Houdini by name.

    Args:
        ctx: MCP context.
        name: Name of the take to make current.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("takes.set_current_take", {
        "name": name,
    })


@mcp.tool()
async def create_take(
    ctx: Context,
    name: str,
    parent_name: Optional[str] = None,
) -> dict:
    """Create a new take in Houdini, optionally as a child of an existing take.

    If parent_name is provided, the new take is created as a child of
    that take. Otherwise it is created under the current take.

    Args:
        ctx: MCP context.
        name: Name for the new take.
        parent_name: Optional name of the parent take.
    """
    bridge = _get_bridge(ctx)
    params: dict = {"name": name}
    if parent_name is not None:
        params["parent_name"] = parent_name
    return await bridge.execute("takes.create_take", params)
