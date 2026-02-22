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
    """Get a summary of a SOP node's geometry: point/prim/vertex counts, attribute list (name, type, size for each class), bounding box, and primitive type breakdown.

    Args:
        node_path: Path to the SOP node (e.g. "/obj/geo1/sphere1").
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("geometry.get_geometry_info", {
        "node_path": node_path,
    })


@mcp.tool()
async def get_points(
    ctx: Context,
    node_path: str,
    attributes: list[str] | None = None,
    start: int = 0,
    count: int = 1000,
    group: str | None = None,
) -> dict:
    """Read point positions and attributes from a SOP node with pagination.

    Args:
        node_path: Path to the SOP node.
        attributes: List of attribute names to read (default: ["P"]).
        start: Starting point index for pagination.
        count: Maximum number of points to return per page.
        group: Optional point group name to filter by.
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
    """Read primitive data and attributes from a SOP node with pagination.

    Args:
        node_path: Path to the SOP node.
        attributes: List of prim attribute names to read (default: all prim attributes).
        start: Starting primitive index for pagination.
        count: Maximum number of primitives to return per page.
        group: Optional primitive group name to filter by.
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
) -> dict:
    """Read all values of a single geometry attribute efficiently as a flat array.

    This uses Houdini's fast bulk attribute reading methods (e.g. pointFloatAttribValues)
    for maximum performance on large geometry.

    Args:
        node_path: Path to the SOP node.
        attrib_name: Name of the attribute to read.
        attrib_class: Attribute class - "point", "prim", "vertex", or "detail".
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("geometry.get_attrib_values", {
        "node_path": node_path,
        "attrib_name": attrib_name,
        "attrib_class": attrib_class,
    })


@mcp.tool()
async def set_detail_attrib(
    ctx: Context,
    node_path: str,
    attrib_name: str,
    value: Any,
) -> dict:
    """Set a detail (global) attribute on a SOP node's geometry.

    The attribute is created if it does not exist. Supports float, int, string,
    and list (vector) values.

    Args:
        node_path: Path to the SOP node.
        attrib_name: Name of the detail attribute.
        value: Value to set (float, int, string, or list of floats).
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("geometry.set_detail_attrib", {
        "node_path": node_path,
        "attrib_name": attrib_name,
        "value": value,
    })


@mcp.tool()
async def get_groups(ctx: Context, node_path: str) -> dict:
    """List all point, primitive, and edge groups on a SOP node's geometry with membership counts.

    Args:
        node_path: Path to the SOP node.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("geometry.get_groups", {
        "node_path": node_path,
    })


@mcp.tool()
async def get_group_members(
    ctx: Context,
    node_path: str,
    group_name: str,
    group_type: str = "point",
) -> dict:
    """Get the element indices that belong to a geometry group.

    Args:
        node_path: Path to the SOP node.
        group_name: Name of the group.
        group_type: Type of group - "point", "prim", or "edge".
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("geometry.get_group_members", {
        "node_path": node_path,
        "group_name": group_name,
        "group_type": group_type,
    })


@mcp.tool()
async def get_bounding_box(ctx: Context, node_path: str) -> dict:
    """Get the axis-aligned bounding box (AABB) of a SOP node's geometry.

    Returns min, max, size, and center vectors.

    Args:
        node_path: Path to the SOP node.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("geometry.get_bounding_box", {
        "node_path": node_path,
    })


@mcp.tool()
async def get_attribute_info(
    ctx: Context,
    node_path: str,
    attrib_name: str,
    attrib_class: str = "point",
) -> dict:
    """Get detailed information about a geometry attribute (type, size, default value).

    Args:
        node_path: Path to the SOP node.
        attrib_name: Name of the attribute.
        attrib_class: Attribute class - "point", "prim", "vertex", or "detail".
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("geometry.get_attribute_info", {
        "node_path": node_path,
        "attrib_name": attrib_name,
        "attrib_class": attrib_class,
    })


@mcp.tool()
async def sample_geometry(
    ctx: Context,
    node_path: str,
    sample_count: int = 100,
    seed: int = 0,
) -> dict:
    """Smart sampling: get N evenly distributed points from a SOP node's geometry.

    Useful for inspecting large geometry without reading every point. Returns all
    point attributes for each sampled point.

    Args:
        node_path: Path to the SOP node.
        sample_count: Number of points to sample (default: 100).
        seed: Random seed for reproducible sampling (default: 0).
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("geometry.sample_geometry", {
        "node_path": node_path,
        "sample_count": sample_count,
        "seed": seed,
    })


@mcp.tool()
async def get_prim_intrinsics(
    ctx: Context,
    node_path: str,
    prim_index: int | None = None,
) -> dict:
    """Get intrinsic values for primitives (typename, measuredarea, measuredperimeter, etc.).

    If prim_index is None, returns an aggregated summary across all primitives.
    Otherwise returns intrinsics for the specific primitive.

    Args:
        node_path: Path to the SOP node.
        prim_index: Specific primitive index, or None for a summary of all.
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
    """Find the nearest point(s) in a SOP node's geometry to a given 3D position.

    Args:
        node_path: Path to the SOP node.
        position: Query position as [x, y, z].
        max_results: Maximum number of nearest points to return (default: 1).
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("geometry.find_nearest_point", {
        "node_path": node_path,
        "position": position,
        "max_results": max_results,
    })
