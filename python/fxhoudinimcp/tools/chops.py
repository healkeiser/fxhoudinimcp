"""MCP tool wrappers for Houdini CHOP (Channel Operator) operations.

Each tool delegates to the corresponding handler running inside Houdini
via the HTTP bridge.
"""

from __future__ import annotations

# Built-in
from typing import Any

# Third-party
from mcp.server.fastmcp import Context

# Internal
from fxhoudinimcp.server import _get_bridge, mcp


@mcp.tool()
async def get_chop_data(
    ctx: Context,
    node_path: str,
    channel_name: str | None = None,
    start: int | None = None,
    end: int | None = None,
) -> dict:
    """Get CHOP node track data.

    Args:
        node_path: CHOP node path.
        channel_name: Specific channel to retrieve.
        start: Start sample index.
        end: End sample index.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"node_path": node_path}
    if channel_name is not None:
        params["channel_name"] = channel_name
    if start is not None:
        params["start"] = start
    if end is not None:
        params["end"] = end
    return await bridge.execute("chops.get_chop_data", params)


@mcp.tool()
async def create_chop_node(
    ctx: Context,
    parent_path: str,
    chop_type: str,
    name: str | None = None,
) -> dict:
    """Create a new CHOP node.

    Before using this, call list_node_types(context='Chop', filter='<keyword>')
    to verify the correct node type. CHOPs has many dedicated nodes for motion
    and timing — noise, wave, spring, jiggle, lag, limit, filter, math,
    function, blend, shift, stretch, trim, cycle, speed, constraintlookatat,
    constraintpath — that may already do what you need.

    Args:
        parent_path: Parent network path.
        chop_type: CHOP node type to create.
        name: Node name override.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {
        "parent_path": parent_path,
        "chop_type": chop_type,
    }
    if name is not None:
        params["name"] = name
    return await bridge.execute("chops.create_chop_node", params)


@mcp.tool()
async def list_chop_channels(ctx: Context, node_path: str) -> dict:
    """List all channels on a CHOP node.

    Args:
        node_path: CHOP node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "chops.list_chop_channels",
        {
            "node_path": node_path,
        },
    )


@mcp.tool()
async def export_chop_to_parm(
    ctx: Context,
    chop_path: str,
    channel_name: str,
    target_node_path: str,
    target_parm_name: str,
) -> dict:
    """Export a CHOP channel to a parameter via a chop() expression.

    Args:
        chop_path: CHOP node path.
        channel_name: Channel to export.
        target_node_path: Target node path.
        target_parm_name: Parameter to receive the export.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "chops.export_chop_to_parm",
        {
            "chop_path": chop_path,
            "channel_name": channel_name,
            "target_node_path": target_node_path,
            "target_parm_name": target_parm_name,
        },
    )
