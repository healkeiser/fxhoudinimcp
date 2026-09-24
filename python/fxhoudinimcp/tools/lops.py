"""MCP tools for LOPs / USD stage inspection and manipulation."""

from __future__ import annotations

# Built-in
from typing import Any

# Third-party
from fxhoudinimcp._sdk import Context

# Internal
from fxhoudinimcp._types import Value
from fxhoudinimcp.server import _get_bridge, mcp


@mcp.tool()
async def get_stage_info(ctx: Context, node_path: str = "/stage") -> dict:
    """Get USD stage info from a LOP node, or from a LOP network.

    Given a network such as "/stage", the answer is about what that network
    displays: `display_node` (and `render_node`) name it, `resolved_from` is
    "display_node", `viewport_delegate` names the Hydra delegate the Scene
    Viewer draws with, and `frame` is the current frame.

    Args:
        node_path: LOP node or LOP network path (default "/stage").
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "lops.get_stage_info",
        {
            "node_path": node_path,
        },
    )


@mcp.tool()
async def get_usd_prim(
    ctx: Context,
    node_path: str,
    prim_path: str,
    full: bool = False,
    traverse_instance_proxies: bool = False,
    time: float | None = None,
    attr_patterns: list[str] | None = None,
) -> dict:
    """Get detailed info about a USD prim.

    Array attributes longer than 16 elements (points, faceVertexIndices,
    primvars:st, ...) come back as a summary: size, element_type, the first 8
    as `head`, and min/max for numeric data. That is what a mesh question
    needs; the full arrays of a building ran to 6.6 million characters. Pass
    full=True for every element, or read one array in windows with
    get_usd_attribute(offset=, limit=).

    Values are read at `time`, or at the current frame when it is not given
    -- what a render of that frame sees; the reply names both as `time` and
    `time_source`. An attribute with time samples carries `time_samples`:
    its value differs at other frames. Relationships (a RenderSettings'
    `camera`) are listed with their `targets`. For the same attributes
    across many prims, get_usd_attributes reads them in one call.

    Args:
        node_path: LOP node path.
        prim_path: USD prim path.
        full: Return array attributes in full instead of summarised.
        traverse_instance_proxies: List the children that live on an
            instanceable prim's prototype. Without it such a prim answers
            `children: []` and is flagged `is_instanceable` with a
            `hidden_descendants` count, so the empty list is not read as
            "nothing inside".
        time: Time code (frame) to read at; default the current frame.
        attr_patterns: Glob patterns on attribute and relationship names
            (e.g. ["resolution", "karma:global:*"]); default all.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"node_path": node_path, "prim_path": prim_path}
    if full:
        params["full"] = True
    if traverse_instance_proxies:
        params["traverse_instance_proxies"] = True
    if time is not None:
        params["time"] = time
    if attr_patterns:
        params["attr_patterns"] = attr_patterns
    return await bridge.execute("lops.get_usd_prim", params)


@mcp.tool()
async def list_usd_prims(
    ctx: Context,
    node_path: str,
    root_path: str = "/",
    prim_type: str | None = None,
    kind: str | None = None,
    depth: int | None = None,
    traverse_instance_proxies: bool = False,
) -> dict:
    """List USD prims on a stage with filtering.

    Instanced geometry is invisible to the default walk: an instanceable
    prim has no children of its own, they belong to its prototype. Set
    traverse_instance_proxies to list the prims under it.

    Args:
        node_path: LOP node path.
        root_path: Root prim path to list from.
        prim_type: USD type filter (e.g. "Mesh", "Xform").
        kind: Kind filter (e.g. "component", "group").
        depth: Max traversal depth.
        traverse_instance_proxies: Descend into instanceable prims and list
            the prims under their prototypes.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {
        "node_path": node_path,
        "root_path": root_path,
    }
    if prim_type is not None:
        params["prim_type"] = prim_type
    if kind is not None:
        params["kind"] = kind
    if depth is not None:
        params["depth"] = depth
    if traverse_instance_proxies:
        params["traverse_instance_proxies"] = True
    return await bridge.execute("lops.list_usd_prims", params)


@mcp.tool()
async def get_usd_attribute(
    ctx: Context,
    node_path: str,
    prim_path: str,
    attr_name: str,
    time: float | None = None,
    full: bool = False,
    offset: int = 0,
    limit: int = 64,
) -> dict:
    """Read a USD attribute value from a prim.

    A long array (over 16 elements) answers with `value` as a summary (size,
    element_type, head, min/max) plus `slice`: the elements from `offset`,
    at most `limit` of them (default the first 64), with `has_more`. Walk a
    big array by raising offset; pass full=True to get every element in
    `value` at once.

    A time-sampled attribute (a PointInstancer's `positions`, `protoIndices`)
    has nothing in its default slot: read with no time it answers null. With
    no `time` given, the current frame is read instead, and the reply carries
    `time`, `time_source`, `time_samples` and `time_range`, so `value: null`
    never stands unexplained next to `is_authored: true`.

    Args:
        node_path: LOP node path.
        prim_path: USD prim path.
        attr_name: Attribute name.
        time: Time code (frame number). Omitted on a time-sampled attribute,
            the current frame is used (the first sample outside the range).
        full: Return the whole array as `value`.
        offset: First element of the window for a long array.
        limit: Window size for a long array.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {
        "node_path": node_path,
        "prim_path": prim_path,
        "attr_name": attr_name,
    }
    if time is not None:
        params["time"] = time
    if full:
        params["full"] = True
    if offset:
        params["offset"] = offset
    if limit != 64:
        params["limit"] = limit
    return await bridge.execute("lops.get_usd_attribute", params)


@mcp.tool()
async def get_usd_attributes(
    ctx: Context,
    node_path: str,
    prims: list[str],
    attr_patterns: list[str] | None = None,
    prim_type: str | None = None,
    relationships: bool = True,
    time: float | None = None,
    full: bool = False,
    traverse_instance_proxies: bool = False,
    limit: int = 500,
) -> dict:
    """Read the same attributes across many prims as one table.

    One row per prim and attribute: {prim, prim_type, name, type, value,
    time_samples?} or, for a relationship, {prim, prim_type, name,
    relationship: true, targets}. The call for "sourceName of every
    RenderVar", "lpetag of every light", "the camera of the render
    settings" -- instead of one get_usd_prim per prim. `matched` counts every
    row found; `truncated` says the `limit` cut some off.

    Args:
        node_path: LOP node path.
        prims: Prim paths or globs: `*` stays within one path element,
            `**` crosses them (["/Render/Vars/*"], ["/lights/**"]).
        attr_patterns: Glob patterns on attribute and relationship names
            (["sourceName"], ["*lpetag"]); default all.
        prim_type: Keep only prims of this type (glob, e.g. "*Light").
        relationships: Include relationships as rows.
        time: Time code (frame) to read at; default the current frame.
        full: Return array values in full instead of summarised.
        traverse_instance_proxies: Let globs match prims inside instances.
        limit: Row cap.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"node_path": node_path, "prims": prims}
    if attr_patterns:
        params["attr_patterns"] = attr_patterns
    if prim_type:
        params["prim_type"] = prim_type
    if not relationships:
        params["relationships"] = False
    if time is not None:
        params["time"] = time
    if full:
        params["full"] = True
    if traverse_instance_proxies:
        params["traverse_instance_proxies"] = True
    if limit != 500:
        params["limit"] = limit
    return await bridge.execute("lops.get_usd_attributes", params)


@mcp.tool()
async def get_usd_layers(ctx: Context, node_path: str) -> dict:
    """List all layers in a USD stage.

    Args:
        node_path: LOP node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "lops.get_usd_layers",
        {
            "node_path": node_path,
        },
    )


@mcp.tool()
async def get_usd_prim_stats(
    ctx: Context,
    node_path: str,
    prim_path: str = "/",
    traverse_instance_proxies: bool = False,
) -> dict:
    """Get prim counts by USD type under a root path.

    Instanced geometry counts once per prototype, not per instance:
    `instanceable_prims` says how many prims were counted without their
    contents, and traverse_instance_proxies counts what is under them.

    Args:
        node_path: LOP node path.
        prim_path: Root prim path to gather stats from.
        traverse_instance_proxies: Count prims under instanceable prototypes.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "lops.get_usd_prim_stats",
        {
            "node_path": node_path,
            "prim_path": prim_path,
            "traverse_instance_proxies": traverse_instance_proxies,
        },
    )


@mcp.tool()
async def get_last_modified_prims(ctx: Context, node_path: str) -> dict:
    """Get prims modified by the last LOP node cook.

    Args:
        node_path: LOP node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "lops.get_last_modified_prims",
        {
            "node_path": node_path,
        },
    )


@mcp.tool()
async def create_lop_node(
    ctx: Context,
    parent_path: str,
    lop_type: str,
    name: str | None = None,
    prim_path: str | None = None,
) -> dict:
    """Create a new LOP node.

    Before using this, call list_node_types(context='Lop', filter='<keyword>')
    to verify the correct node type. Solaris ships many specialized LOPs —
    sublayer, reference, materiallibrary, assignmaterial, karmarendersettings,
    editproperties, xform, prune, configurelayer, collection, addvariant —
    that may not be obvious from their names.

    Args:
        parent_path: Parent node path.
        lop_type: LOP node type (e.g. "sphere", "sublayer", "merge").
        name: Node name.
        prim_path: USD prim path to set on the node.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {
        "parent_path": parent_path,
        "lop_type": lop_type,
    }
    if name is not None:
        params["name"] = name
    if prim_path is not None:
        params["prim_path"] = prim_path
    return await bridge.execute("lops.create_lop_node", params)


@mcp.tool()
async def set_usd_attribute(
    ctx: Context,
    node_path: str,
    prim_path: str,
    attr_name: str,
    value: Value,
) -> dict:
    """Set a USD attribute value via an inline Python LOP.

    Args:
        node_path: LOP node path to connect after.
        prim_path: USD prim path.
        attr_name: Attribute name.
        value: Value to set.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "lops.set_usd_attribute",
        {
            "node_path": node_path,
            "prim_path": prim_path,
            "attr_name": attr_name,
            "value": value,
        },
    )


@mcp.tool()
async def get_usd_bound_material(
    ctx: Context,
    node_path: str,
    prim_paths: list[str],
    purpose: str = "full",
) -> dict:
    """The material each prim renders with, resolved the way the renderer
    resolves it (ComputeBoundMaterials), and where the binding comes from:
    `direct` on the prim, `inherited` from which ancestor, or which
    `collection`. A binding to a material prim that does not exist is
    reported in `missing_material`, not as unbound.

    Batched: pass every prim of interest in one call.

    Args:
        node_path: LOP node whose stage to read.
        prim_paths: Prim paths to resolve.
        purpose: "full" (default; what Karma renders, falling back to an
            all-purpose binding), "preview", or "all" (all-purpose bindings
            only).
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "lops.get_usd_bound_material",
        {"node_path": node_path, "prim_paths": prim_paths, "purpose": purpose},
    )


@mcp.tool()
async def get_usd_materials(ctx: Context, node_path: str) -> dict:
    """List all USD materials on a stage.

    Each material reports surface_shaders keyed by render context: "surface"
    is the universal output, a UsdPreviewSurface for viewports and Storm,
    and "mtlx" is the MaterialX shader Karma renders. surface_shader is the
    mtlx one when present, so it agrees with get_material_info on the same
    material.

    `bound_to` lists the prims a binding is authored on. `rendered_on` (up
    to 50 paths) and `rendered_on_count` are the geometry that resolves to
    the material for rendering, including geometry bound through a parent
    or a collection; get_usd_bound_material says why for a given prim.

    Args:
        node_path: LOP node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "lops.get_usd_materials",
        {
            "node_path": node_path,
        },
    )


@mcp.tool()
async def find_usd_prims(
    ctx: Context,
    node_path: str,
    pattern: str,
    traverse_instance_proxies: bool = False,
) -> dict:
    """Search USD prims by path pattern.

    Args:
        node_path: LOP node path.
        pattern: Glob pattern (supports *, **) or substring.
        traverse_instance_proxies: Search prims under instanceable
            prototypes too; the default walk never visits them.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "lops.find_usd_prims",
        {
            "node_path": node_path,
            "pattern": pattern,
            "traverse_instance_proxies": traverse_instance_proxies,
        },
    )


@mcp.tool()
async def get_usd_composition(
    ctx: Context,
    node_path: str,
    prim_path: str,
) -> dict:
    """Get composition arcs for a USD prim.

    Args:
        node_path: LOP node path.
        prim_path: USD prim path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "lops.get_usd_composition",
        {
            "node_path": node_path,
            "prim_path": prim_path,
        },
    )


@mcp.tool()
async def get_usd_variants(
    ctx: Context,
    node_path: str,
    prim_path: str,
) -> dict:
    """Get variant sets and selections for a USD prim.

    Args:
        node_path: LOP node path.
        prim_path: USD prim path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "lops.get_usd_variants",
        {
            "node_path": node_path,
            "prim_path": prim_path,
        },
    )


@mcp.tool()
async def inspect_usd_layer(
    ctx: Context,
    node_path: str,
    layer_index: int = 0,
) -> dict:
    """Inspect a USD layer by index.

    Args:
        node_path: LOP node path.
        layer_index: Layer index (0 = root layer).
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "lops.inspect_usd_layer",
        {
            "node_path": node_path,
            "layer_index": layer_index,
        },
    )


@mcp.tool()
async def create_light(
    ctx: Context,
    parent_path: str = "/stage",
    light_type: str = "dome",
    name: str | None = None,
    intensity: float = 1.0,
    color: list[float] | None = None,
    position: list[float] | None = None,
) -> dict:
    """Create a USD light in a LOP network.

    Args:
        parent_path: Parent LOP network path.
        light_type: "dome", "distant", "rect", "sphere", "disk", or "cylinder".
        name: Light node name.
        intensity: Light intensity.
        color: [r, g, b] color values.
        position: [x, y, z] world position.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {
        "parent_path": parent_path,
        "light_type": light_type,
        "intensity": intensity,
    }
    if name is not None:
        params["name"] = name
    if color is not None:
        params["color"] = color
    if position is not None:
        params["position"] = position
    return await bridge.execute("lops.create_light", params)


@mcp.tool()
async def list_lights(ctx: Context, node_path: str) -> dict:
    """List all USD lights on a LOP stage.

    Args:
        node_path: LOP node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "lops.list_lights",
        {
            "node_path": node_path,
        },
    )


@mcp.tool()
async def set_light_properties(
    ctx: Context,
    node_path: str,
    prim_path: str,
    properties: dict[str, Any],
) -> dict:
    """Set properties on a USD light prim via an inline Python LOP.

    Args:
        node_path: LOP node path to connect after.
        prim_path: USD light prim path.
        properties: Property name-value pairs to set.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "lops.set_light_properties",
        {
            "node_path": node_path,
            "prim_path": prim_path,
            "properties": properties,
        },
    )


@mcp.tool()
async def create_light_rig(
    ctx: Context,
    parent_path: str = "/stage",
    preset: str = "three_point",
    intensity_mult: float = 1.0,
) -> dict:
    """Create a preset lighting rig in a LOP network.

    Args:
        parent_path: Parent LOP network path.
        preset: "three_point", "studio", "outdoor", or "hdri".
        intensity_mult: Multiplier for all light intensities.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "lops.create_light_rig",
        {
            "parent_path": parent_path,
            "preset": preset,
            "intensity_mult": intensity_mult,
        },
    )
