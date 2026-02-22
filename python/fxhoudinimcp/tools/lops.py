"""MCP tools for LOPs / USD stage inspection and manipulation."""

from __future__ import annotations

# Built-in
from typing import Any

# Third-party
from mcp.server.fastmcp import Context

# Internal
from fxhoudinimcp.server import mcp, _get_bridge


@mcp.tool()
async def get_stage_info(ctx: Context, node_path: str) -> dict:
    """Get USD stage info from a LOP node.

    Args:
        node_path: LOP node path.
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
) -> dict:
    """Get detailed info about a USD prim.

    Args:
        node_path: LOP node path.
        prim_path: USD prim path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "lops.get_usd_prim",
        {
            "node_path": node_path,
            "prim_path": prim_path,
        },
    )


@mcp.tool()
async def list_usd_prims(
    ctx: Context,
    node_path: str,
    root_path: str = "/",
    prim_type: str | None = None,
    kind: str | None = None,
    depth: int | None = None,
) -> dict:
    """List USD prims on a stage with filtering.

    Args:
        node_path: LOP node path.
        root_path: Root prim path to list from.
        prim_type: USD type filter (e.g. "Mesh", "Xform").
        kind: Kind filter (e.g. "component", "group").
        depth: Max traversal depth.
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
    return await bridge.execute("lops.list_usd_prims", params)


@mcp.tool()
async def get_usd_attribute(
    ctx: Context,
    node_path: str,
    prim_path: str,
    attr_name: str,
    time: float | None = None,
) -> dict:
    """Read a USD attribute value from a prim.

    Args:
        node_path: LOP node path.
        prim_path: USD prim path.
        attr_name: Attribute name.
        time: Time code (frame number).
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {
        "node_path": node_path,
        "prim_path": prim_path,
        "attr_name": attr_name,
    }
    if time is not None:
        params["time"] = time
    return await bridge.execute("lops.get_usd_attribute", params)


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
) -> dict:
    """Get prim counts by USD type under a root path.

    Args:
        node_path: LOP node path.
        prim_path: Root prim path to gather stats from.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "lops.get_usd_prim_stats",
        {
            "node_path": node_path,
            "prim_path": prim_path,
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
    value: Any,
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
async def get_usd_materials(ctx: Context, node_path: str) -> dict:
    """List all USD materials on a stage.

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
) -> dict:
    """Search USD prims by path pattern.

    Args:
        node_path: LOP node path.
        pattern: Glob pattern (supports *, **) or substring.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "lops.find_usd_prims",
        {
            "node_path": node_path,
            "pattern": pattern,
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
