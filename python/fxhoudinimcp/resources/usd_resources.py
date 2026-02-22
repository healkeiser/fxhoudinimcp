"""MCP resources for USD stage data."""

from __future__ import annotations

# Third-party
from mcp.server.fastmcp import Context

# Internal
from fxhoudinimcp.server import mcp, _get_bridge


@mcp.resource("houdini://usd/{node_path}/stage")
async def usd_stage(node_path: str, ctx: Context) -> dict:
    """USD stage information for a LOP node."""
    bridge = _get_bridge(ctx)
    return await bridge.execute("lops.get_stage_info", {"node_path": f"/{node_path}"})
