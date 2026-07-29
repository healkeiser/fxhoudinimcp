"""MCP resources for USD stage data."""

from __future__ import annotations

# Internal
from fxhoudinimcp.server import current_bridge, mcp


@mcp.resource("houdini://usd/{node_path}/stage")
async def usd_stage(node_path: str) -> dict:
    """USD stage information for a LOP node."""
    bridge = current_bridge()
    return await bridge.execute("lops.get_stage_info", {"node_path": f"/{node_path}"})
