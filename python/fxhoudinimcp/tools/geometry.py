"""MCP tools for SOP geometry inspection and manipulation."""

from __future__ import annotations

# Built-in
from typing import Any

# Third-party
from mcp.server.fastmcp import Context

# Internal
from fxhoudinimcp.server import mcp, _get_bridge


@mcp.tool()
async def get_geometry_info(ctx: Context, node_path: str) -> dict:
    """Get geometry summary for a SOP node.

    Args:
        node_path: Node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "geometry.get_geometry_info",
        {
            "node_path": node_path,
        },
    )


@mcp.tool()
async def get_points(
    ctx: Context,
    node_path: str,
    attributes: list[str] | None = None,
    start: int = 0,
    count: int = 1000,
    group: str | None = None,
) -> dict:
    """Read point positions and attributes with pagination.

    Args:
        node_path: Node path.
        attributes: Attribute names to read.
        start: Start index.
        count: Max points per page.
        group: Point group filter.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {
        "node_path": node_path,
        "start": start,
        "count": count,
    }
    if attributes is not None:
        params["attributes"] = attributes
    if group is not None:
        params["group"] = group
    return await bridge.execute("geometry.get_points", params)


@mcp.tool()
async def get_prims(
    ctx: Context,
    node_path: str,
    attributes: list[str] | None = None,
    start: int = 0,
    count: int = 1000,
    group: str | None = None,
) -> dict:
    """Read primitive data and attributes with pagination.

    Args:
        node_path: Node path.
        attributes: Attribute names to read.
        start: Start index.
        count: Max prims per page.
        group: Prim group filter.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {
        "node_path": node_path,
        "start": start,
        "count": count,
    }
    if attributes is not None:
        params["attributes"] = attributes
    if group is not None:
        params["group"] = group
    return await bridge.execute("geometry.get_prims", params)


@mcp.tool()
async def get_attrib_values(
    ctx: Context,
    node_path: str,
    attrib_name: str,
    attrib_class: str = "point",
    start: int = 0,
    count: int = 200,
) -> dict:
    """Read attribute values as a flat array with pagination.

    For spot-checking a few values prefer sample_geometry — it returns a
    representative spread of points with all their attributes in one call.
    Use get_attrib_values when you need a specific slice of one attribute.

    Values are element-major: for a float3 attribute every 3 consecutive
    values belong to one element. Check has_more and increment start to
    read subsequent pages.

    Args:
        node_path: Node path.
        attrib_name: Attribute name.
        attrib_class: "point", "prim", "vertex", or "detail".
        start: First element index to return.
        count: Max elements per page (default 200).
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "geometry.get_attrib_values",
        {
            "node_path": node_path,
            "attrib_name": attrib_name,
            "attrib_class": attrib_class,
            "start": start,
            "count": count,
        },
    )


@mcp.tool()
async def set_detail_attrib(
    ctx: Context,
    node_path: str,
    attrib_name: str,
    value: Any,
) -> dict:
    """Set a detail attribute on a SOP node.

    Args:
        node_path: Node path.
        attrib_name: Attribute name.
        value: Value to set.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "geometry.set_detail_attrib",
        {
            "node_path": node_path,
            "attrib_name": attrib_name,
            "value": value,
        },
    )


@mcp.tool()
async def get_groups(ctx: Context, node_path: str) -> dict:
    """List all geometry groups on a SOP node.

    Args:
        node_path: Node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "geometry.get_groups",
        {
            "node_path": node_path,
        },
    )


@mcp.tool()
async def get_group_members(
    ctx: Context,
    node_path: str,
    group_name: str,
    group_type: str = "point",
    start: int = 0,
    count: int = 5000,
) -> dict:
    """Get element indices in a geometry group, with pagination.

    Check has_more and increment start to read subsequent pages.

    Args:
        node_path: Node path.
        group_name: Group name.
        group_type: "point", "prim", or "edge".
        start: First element index to return.
        count: Max elements per page (default 5 000).
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "geometry.get_group_members",
        {
            "node_path": node_path,
            "group_name": group_name,
            "group_type": group_type,
            "start": start,
            "count": count,
        },
    )


@mcp.tool()
async def get_bounding_box(ctx: Context, node_path: str) -> dict:
    """Get the bounding box of a SOP node's geometry.

    Args:
        node_path: Node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "geometry.get_bounding_box",
        {
            "node_path": node_path,
        },
    )


@mcp.tool()
async def get_attribute_info(
    ctx: Context,
    node_path: str,
    attrib_name: str,
    attrib_class: str = "point",
) -> dict:
    """Get metadata for a geometry attribute.

    Args:
        node_path: Node path.
        attrib_name: Attribute name.
        attrib_class: "point", "prim", "vertex", or "detail".
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "geometry.get_attribute_info",
        {
            "node_path": node_path,
            "attrib_name": attrib_name,
            "attrib_class": attrib_class,
        },
    )


@mcp.tool()
async def sample_geometry(
    ctx: Context,
    node_path: str,
    sample_count: int = 100,
    seed: int = 0,
) -> dict:
    """Sample evenly distributed points from a SOP node's geometry.

    Args:
        node_path: Node path.
        sample_count: Number of points to sample.
        seed: Random seed.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "geometry.sample_geometry",
        {
            "node_path": node_path,
            "sample_count": sample_count,
            "seed": seed,
        },
    )


@mcp.tool()
async def get_prim_intrinsics(
    ctx: Context,
    node_path: str,
    prim_index: int | None = None,
) -> dict:
    """Get intrinsic values for primitives.

    Args:
        node_path: Node path.
        prim_index: Primitive index, or None for a summary.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"node_path": node_path}
    if prim_index is not None:
        params["prim_index"] = prim_index
    return await bridge.execute("geometry.get_prim_intrinsics", params)


@mcp.tool()
async def find_nearest_point(
    ctx: Context,
    node_path: str,
    position: list[float],
    max_results: int = 1,
) -> dict:
    """Find the nearest point(s) to a given position.

    Args:
        node_path: Node path.
        position: Query position as [x, y, z].
        max_results: Max nearest points to return.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "geometry.find_nearest_point",
        {
            "node_path": node_path,
            "position": position,
            "max_results": max_results,
        },
    )
