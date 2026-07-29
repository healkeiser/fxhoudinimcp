"""MCP resources for geometry data."""

from __future__ import annotations

# Internal
from fxhoudinimcp.server import current_bridge, mcp


@mcp.resource("houdini://geometry/{node_path}/summary")
async def geo_summary(node_path: str) -> dict:
    """Geometry summary for a SOP node: point/prim counts, attributes, bounding box."""
    bridge = current_bridge()
    return await bridge.execute("geometry.get_geometry_info", {"node_path": f"/{node_path}"})
