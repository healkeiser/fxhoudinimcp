"""MCP resources for geometry data."""

from __future__ import annotations

# Third-party
from mcp.server.fastmcp import Context

# Internal
from fxhoudinimcp.server import mcp, _get_bridge


@mcp.resource("houdini://geometry/{node_path}/summary")
async def geo_summary(node_path: str, ctx: Context) -> dict:
    """Geometry summary for a SOP node: point/prim counts, attributes, bounding box."""
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "geometry.get_geometry_info", {"node_path": f"/{node_path}"}
    )
