"""MCP tools for SOP geometry inspection and manipulation."""

from __future__ import annotations

# Built-in
from typing import Any

# Third-party
from fxhoudinimcp._sdk import Context

# Internal
from fxhoudinimcp._types import Value
from fxhoudinimcp.bridge import NO_TIMEOUT
from fxhoudinimcp.server import _get_bridge, mcp


@mcp.tool()
async def get_geometry_info(ctx: Context, node_path: str, output_index: int = 0) -> dict:
    """Get geometry summary for a SOP node.

    Args:
        node_path: Node path.
        output_index: Which output to read, for nodes with several (FLIP
            compress, Vellum solver, whitewater source): 0 is the first.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "geometry.get_geometry_info",
        {"node_path": node_path, "output_index": output_index},
    )


@mcp.tool()
async def get_points(
    ctx: Context,
    node_path: str,
    attributes: list[str] | None = None,
    start: int = 0,
    count: int = 200,
    group: str | None = None,
) -> dict:
    """Read point positions and attributes with pagination.

    Args:
        node_path: Node path.
        attributes: Attribute names to read.
        start: Start index.
        count: Max points per page (200 by default, about 14 KB; page on with
            start while has_more is true).
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
    count: int = 200,
    group: str | None = None,
) -> dict:
    """Read primitive data and attributes with pagination.

    Args:
        node_path: Node path.
        attributes: Attribute names to read.
        start: Start index.
        count: Max prims per page (200 by default; page on with start while
            has_more is true).
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
    value: Value,
) -> dict:
    """Set a detail attribute on a SOP node.

    Appends an Attribute Create SOP after the node and moves the display
    flag to it; the result includes the new node's path.

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
    prim_indices: list[int] | None = None,
    prim_range: list[int] | None = None,
    intrinsics: list[str] | None = None,
) -> dict:
    """Get intrinsic values for primitives: one, many, or all of them.

    Read many prims in one call rather than one call per prim. `intrinsics`
    alone sweeps every prim for those intrinsics and answers with a `prims`
    table plus `stats` (min/max/avg and the prim index each extreme belongs
    to, per component for a vector such as `bounds`); `prim_indices` or
    `prim_range` narrow it to the prims you care about. Up to 2000 rows per
    call; beyond that the reply says `truncated` and `requested_count`, and
    `stats` cover only the rows returned: page with `prim_range`.

    Args:
        node_path: Node path.
        prim_index: One primitive index, or None for a summary.
        prim_indices: Several primitive indices, read in one call.
        prim_range: [start, end] (end inclusive) instead of a list.
        intrinsics: Only these intrinsics, e.g. ["bounds", "packedfulltransform"].
            With none of the index arguments, they are read for every prim.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"node_path": node_path}
    if prim_index is not None:
        params["prim_index"] = prim_index
    if prim_indices is not None:
        params["prim_indices"] = prim_indices
    if prim_range is not None:
        params["prim_range"] = prim_range
    if intrinsics is not None:
        params["intrinsics"] = intrinsics
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


@mcp.tool()
async def get_attrib_stats(
    ctx: Context,
    node_path: str | None = None,
    attribs: list[str] | None = None,
    attrib_class: str = "point",
    frames: list[float] | None = None,
    node_paths: list[str] | None = None,
    percentiles: list[float] | None = None,
    group: str | None = None,
    unique: bool = False,
    distance_to: str | None = None,
) -> dict:
    """Aggregate statistics for numeric attributes: min, max, mean, sum.

    Use this to prove something is happening, rather than reading values.
    get_geometry_info names the attributes; get_attrib_values returns every
    value, which on a 60k-point cache tells you nothing you can read. Vector
    attributes also report per-component ranges, so a velocity field's per-axis
    extremes come back in the same call.

    Args:
        node_path: SOP node path.
        attribs: Attribute names. Omit for every attribute of the class. A
            name written "age/life" is the ratio of two attributes, per
            element (elements dividing by zero are counted, not used).
        attrib_class: "point", "prim", "vertex" (uv and N usually live
            there) or "detail".
        frames: Measure at each of these frames: a row per node per frame,
            frames cooked in increasing order, the current frame put back.
            element_count is the point count and P's per-component min/max
            the bounds, so a sim's count and spread over time is ONE call.
        node_paths: Several nodes (variants) in the same call, instead of
            node_path.
        percentiles: e.g. [5, 50, 95] for the distribution (50 = median).
        group: Only the elements in this group pattern, as a SOP group field
            takes it: "grp", "@id>=0", "0-99"; space-separated parts add up.
            Point and prim classes.
        unique: Count distinct values of integer and string attributes
            (`unique_count`, `most_common`); for the prim class also
            `vertices_per_prim`, a trail's length and its distribution.
        distance_to: A SOP whose surface each point's distance is measured
            to (`distance_to` in the reply: min / max / mean, percentiles):
            particles crawling on or hovering over a mesh. Point class; the
            scene is not changed. Both are taken in their own SOP space:
            object transforms are not applied, so use it within one object.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"attrib_class": attrib_class}
    if group is not None:
        params["group"] = group
    if unique:
        params["unique"] = True
    if distance_to is not None:
        params["distance_to"] = distance_to
    for key, value in (
        ("node_path", node_path),
        ("attribs", attribs),
        ("frames", frames),
        ("node_paths", node_paths),
        ("percentiles", percentiles),
    ):
        if value is not None:
            params[key] = value
    if frames or node_paths:
        # Several frames of a simulation cook as long as they take.
        return await bridge.execute("geometry.get_attrib_stats", params, timeout=NO_TIMEOUT)
    return await bridge.execute("geometry.get_attrib_stats", params)


@mcp.tool()
async def get_volume_info(
    ctx: Context,
    node_path: str,
    max_volumes: int = 24,
    threshold: float | None = None,
    bins: int | list[float] = 0,
) -> dict:
    """Per-volume name, resolution, active voxels, value range, mean and sum.

    A primitive count cannot tell a correctly named non-empty density field from
    an empty one, which is the question worth asking before wiring a solver's
    sourcing. This is the SOP counterpart of get_cop_vdb.

    threshold or bins read the voxels (VDB: active ones) for percentiles, a
    histogram, the count over threshold and box_above_threshold, the world box
    of the voxels over it: where the smoke is, not where the grid is.

    Args:
        node_path: SOP node path holding volume or VDB primitives.
        max_volumes: Cap on volumes reported.
        threshold: Split the voxels at this value and box the ones above it.
        bins: Histogram bin count, or a list of bin edges.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"node_path": node_path, "max_volumes": max_volumes}
    if threshold is not None:
        params["threshold"] = threshold
    if bins:
        params["bins"] = bins
    return await bridge.execute("geometry.get_volume_info", params)


@mcp.tool()
async def sample_volume(
    ctx: Context,
    node_path: str,
    fields: list[str],
    positions: list[list[float]] | None = None,
    from_node: str | None = None,
    limit: int = 1000,
    bins: int | list[float] = 0,
    threshold: float | None = None,
) -> dict:
    """Read named volume fields at world positions, or at another SOP's points.

    "What does the collision SDF read where the particles are" is one call
    with from_node, and adds no node to the scene. A VDB SDF reads its
    background (the band width) outside its narrow band, not the distance.

    Args:
        node_path: SOP holding the volumes.
        fields: Volume names (the name attribute), e.g. ["density"].
        positions: [[x, y, z], ...] in world space.
        from_node: SOP whose points are the positions, instead of positions.
        limit: Values are returned up to this many positions; the summary always is.
        bins: Histogram bin count, or a list of bin edges, for the summary.
        threshold: Count the samples above this value.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"node_path": node_path, "fields": fields, "limit": limit}
    if positions is not None:
        params["positions"] = positions
    if from_node is not None:
        params["from_node"] = from_node
    if bins:
        params["bins"] = bins
    if threshold is not None:
        params["threshold"] = threshold
    return await bridge.execute("geometry.sample_volume", params)


@mcp.tool()
async def compare_volumes(
    ctx: Context,
    node_path: str,
    field: str,
    against: str,
    against_node: str | None = None,
    bands: int | list[float] = 10,
) -> dict:
    """How much of one field sits in each band of another field.

    "How much density is inside the collider" is field="density",
    against="surface" (an SDF), bands=[-1000, 0, 1000]: the first band's
    field_total is what is inside. Both are sampled on a grid over field's box.

    Args:
        node_path: SOP holding field.
        field: Volume to total, e.g. "density".
        against: Volume whose value picks the band, e.g. a collider SDF.
        against_node: SOP holding against, when not node_path.
        bands: Band count, or a list of band edges.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {
        "node_path": node_path,
        "field": field,
        "against": against,
        "bands": bands,
    }
    if against_node is not None:
        params["against_node"] = against_node
    return await bridge.execute("geometry.compare_volumes", params)
