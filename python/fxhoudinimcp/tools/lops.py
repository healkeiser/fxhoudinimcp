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
    """Get a summary of the USD stage on a LOP node: prim count, layers, default prim, up axis, and meters per unit.

    Args:
        node_path: Path to the LOP node (e.g. "/stage/sublayer1").
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("lops.get_stage_info", {
        "node_path": node_path,
    })


@mcp.tool()
async def get_usd_prim(
    ctx: Context,
    node_path: str,
    prim_path: str,
) -> dict:
    """Get detailed information about a USD prim: type, kind, all attributes with values, and children list.

    Args:
        node_path: Path to the LOP node.
        prim_path: USD prim path on the stage (e.g. "/World/Cube").
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("lops.get_usd_prim", {
        "node_path": node_path,
        "prim_path": prim_path,
    })


@mcp.tool()
async def list_usd_prims(
    ctx: Context,
    node_path: str,
    root_path: str = "/",
    prim_type: str | None = None,
    kind: str | None = None,
    depth: int | None = None,
) -> dict:
    """List USD prims on a stage, optionally filtered by type, kind, or depth.

    Args:
        node_path: Path to the LOP node.
        root_path: Root prim path to start listing from (default: "/").
        prim_type: Filter to prims of this USD type (e.g. "Mesh", "Xform").
        kind: Filter to prims with this kind (e.g. "component", "group").
        depth: Maximum traversal depth from root_path (None = unlimited).
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
    """Read a USD attribute value from a prim, optionally at a specific time code.

    Args:
        node_path: Path to the LOP node.
        prim_path: USD prim path.
        attr_name: Name of the attribute to read.
        time: Optional time code (frame number). None for the default time.
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
    """List all layers used in the USD stage on a LOP node.

    Returns layer identifiers, display names, resolved paths, and dirty status.

    Args:
        node_path: Path to the LOP node.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("lops.get_usd_layers", {
        "node_path": node_path,
    })


@mcp.tool()
async def get_usd_prim_stats(
    ctx: Context,
    node_path: str,
    prim_path: str = "/",
) -> dict:
    """Get prim counts broken down by USD type under a root path.

    Args:
        node_path: Path to the LOP node.
        prim_path: Root prim path to gather stats from (default: "/").
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("lops.get_usd_prim_stats", {
        "node_path": node_path,
        "prim_path": prim_path,
    })


@mcp.tool()
async def get_last_modified_prims(ctx: Context, node_path: str) -> dict:
    """Get the list of USD prims that were modified by the last LOP node cook.

    Args:
        node_path: Path to the LOP node.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("lops.get_last_modified_prims", {
        "node_path": node_path,
    })


@mcp.tool()
async def create_lop_node(
    ctx: Context,
    parent_path: str,
    lop_type: str,
    name: str | None = None,
    prim_path: str | None = None,
) -> dict:
    """Create a new LOP node in Houdini with optional presets.

    Args:
        parent_path: Path to the parent node where the LOP will be created.
        lop_type: Type of LOP node to create (e.g. "sphere", "cube", "sublayer", "merge").
        name: Optional name for the new node.
        prim_path: Optional USD prim path to set on the node (if it has a primpath parameter).
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
    """Set a USD attribute value via an auto-generated inline Python LOP.

    Creates a Python LOP node wired after the specified node that sets the
    attribute on the stage.

    Args:
        node_path: Path to the LOP node to connect after.
        prim_path: USD prim path containing the attribute.
        attr_name: Name of the attribute to set.
        value: Value to set on the attribute.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("lops.set_usd_attribute", {
        "node_path": node_path,
        "prim_path": prim_path,
        "attr_name": attr_name,
        "value": value,
    })


@mcp.tool()
async def get_usd_materials(ctx: Context, node_path: str) -> dict:
    """List all USD materials on a stage with their shader connections and geometry bindings.

    Args:
        node_path: Path to the LOP node.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("lops.get_usd_materials", {
        "node_path": node_path,
    })


@mcp.tool()
async def find_usd_prims(
    ctx: Context,
    node_path: str,
    pattern: str,
) -> dict:
    """Search USD prims by path pattern (supports * and ** wildcards, and substring matching).

    Args:
        node_path: Path to the LOP node.
        pattern: Search pattern (e.g. "*/Cube*", "**/materials/*", or a substring).
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("lops.find_usd_prims", {
        "node_path": node_path,
        "pattern": pattern,
    })


@mcp.tool()
async def get_usd_composition(
    ctx: Context,
    node_path: str,
    prim_path: str,
) -> dict:
    """Get the composition arcs for a USD prim: references, payloads, inherits, specializes, and variant selections.

    Args:
        node_path: Path to the LOP node.
        prim_path: USD prim path to inspect.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("lops.get_usd_composition", {
        "node_path": node_path,
        "prim_path": prim_path,
    })


@mcp.tool()
async def get_usd_variants(
    ctx: Context,
    node_path: str,
    prim_path: str,
) -> dict:
    """Get variant sets and current selections for a USD prim.

    Args:
        node_path: Path to the LOP node.
        prim_path: USD prim path to inspect.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("lops.get_usd_variants", {
        "node_path": node_path,
        "prim_path": prim_path,
    })


@mcp.tool()
async def inspect_usd_layer(
    ctx: Context,
    node_path: str,
    layer_index: int = 0,
) -> dict:
    """Inspect a specific USD layer in the stage by its index.

    Returns the layer identifier, authored prims, sublayers, default prim, and more.

    Args:
        node_path: Path to the LOP node.
        layer_index: Index of the layer to inspect (0 = root layer).
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("lops.inspect_usd_layer", {
        "node_path": node_path,
        "layer_index": layer_index,
    })


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
    """Create a USD light node in a Houdini LOP network.

    Supports dome, distant, rect, sphere, disk, and cylinder light types
    with configurable intensity, color, and position.

    Args:
        ctx: MCP context.
        parent_path: Parent LOP network path (default: "/stage").
        light_type: Type of light: "dome", "distant", "rect", "sphere",
            "disk", or "cylinder".
        name: Optional name for the light node.
        intensity: Light intensity (default: 1.0).
        color: Optional [r, g, b] color values (0.0 to 1.0).
        position: Optional [x, y, z] world position.
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
    """List all USD lights on a Houdini LOP stage.

    Cooks the LOP node and traverses the USD stage to find all UsdLux
    light prims, returning their type, intensity, color, and enabled state.

    Args:
        ctx: MCP context.
        node_path: Path to the LOP node (e.g. "/stage/domelight1").
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("lops.list_lights", {
        "node_path": node_path,
    })


@mcp.tool()
async def set_light_properties(
    ctx: Context,
    node_path: str,
    prim_path: str,
    properties: dict[str, Any],
) -> dict:
    """Set properties on a USD light prim in Houdini via an inline Python LOP.

    Supports properties like intensity, color, exposure, diffuse, specular,
    shadow_enable, temperature, and enable_temperature.

    Args:
        ctx: MCP context.
        node_path: Path to the LOP node to connect after.
        prim_path: USD prim path of the light (e.g. "/lights/key_light").
        properties: Dict of property name -> value to set.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("lops.set_light_properties", {
        "node_path": node_path,
        "prim_path": prim_path,
        "properties": properties,
    })


@mcp.tool()
async def create_light_rig(
    ctx: Context,
    parent_path: str = "/stage",
    preset: str = "three_point",
    intensity_mult: float = 1.0,
) -> dict:
    """Create a preset lighting rig in a Houdini LOP network.

    Available presets:
    - "three_point": Key + fill + rim lights
    - "studio": Softbox-style rect light setup
    - "outdoor": Dome light + distant sun light
    - "hdri": Single dome light

    Args:
        ctx: MCP context.
        parent_path: Parent LOP network path (default: "/stage").
        preset: Lighting preset name (default: "three_point").
        intensity_mult: Multiplier applied to all light intensities (default: 1.0).
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("lops.create_light_rig", {
        "parent_path": parent_path,
        "preset": preset,
        "intensity_mult": intensity_mult,
    })
