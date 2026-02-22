"""MCP tool wrappers for Houdini CHOP (Channel Operator) operations.

Each tool delegates to the corresponding handler running inside Houdini
via the HTTP bridge.
"""

from __future__ import annotations

# Built-in
from typing import Any, Optional

# Third-party
from mcp.server.fastmcp import Context

# Internal
from fxhoudinimcp.server import mcp, _get_bridge


@mcp.tool()
async def get_chop_data(
    ctx: Context,
    node_path: str,
    channel_name: Optional[str] = None,
    start: Optional[int] = None,
    end: Optional[int] = None,
) -> dict:
    """Get CHOP node track data from Houdini.

    If channel_name is given, returns that channel's samples within an
    optional sample range. Otherwise returns all channel names and metadata
    (sample count, rate, min/max values).

    Args:
        ctx: MCP context.
        node_path: Path to the CHOP node (e.g. "/obj/chopnet1/wave1").
        channel_name: Optional specific channel name to retrieve samples for.
        start: Optional start sample index.
        end: Optional end sample index.
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
    name: Optional[str] = None,
) -> dict:
    """Create a new CHOP node inside a Houdini network.

    Args:
        ctx: MCP context.
        parent_path: Path to the parent network (e.g. "/obj/chopnet1").
        chop_type: Type of CHOP node to create (e.g. "wave", "noise", "math").
        name: Optional name for the new node.
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
    """List all tracks/channels on a Houdini CHOP node.

    For each channel returns: name, length, sample rate, and value range
    (min/max).

    Args:
        ctx: MCP context.
        node_path: Path to the CHOP node (e.g. "/obj/chopnet1/wave1").
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("chops.list_chop_channels", {
        "node_path": node_path,
    })


@mcp.tool()
async def export_chop_to_parm(
    ctx: Context,
    chop_path: str,
    channel_name: str,
    target_node_path: str,
    target_parm_name: str,
) -> dict:
    """Export a CHOP channel to a Houdini parameter via a chop() expression.

    Creates a CHOP export reference by setting a chop() expression on the
    target parameter that reads from the specified channel.

    Args:
        ctx: MCP context.
        chop_path: Path to the CHOP node (e.g. "/obj/chopnet1/wave1").
        channel_name: Name of the channel to export (e.g. "chan1").
        target_node_path: Path to the target node containing the parameter.
        target_parm_name: Name of the parameter to set the expression on.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("chops.export_chop_to_parm", {
        "chop_path": chop_path,
        "channel_name": channel_name,
        "target_node_path": target_node_path,
        "target_parm_name": target_parm_name,
    })
