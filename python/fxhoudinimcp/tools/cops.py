"""MCP tool wrappers for Houdini COP (Copernicus) operations.

Each tool delegates to the corresponding handler running inside Houdini
via the HTTP bridge.
"""

from __future__ import annotations

# Built-in
from typing import Optional

# Third-party
from mcp.server.fastmcp import Context

# Internal
from fxhoudinimcp.server import mcp, _get_bridge


@mcp.tool()
async def get_cop_info(ctx: Context, node_path: str) -> dict:
    """Get information about a COP node including output type, data format, and resolution.

    Args:
        ctx: MCP context.
        node_path: Path to the COP node.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("cops.get_cop_info", {"node_path": node_path})


@mcp.tool()
async def get_cop_geometry(
    ctx: Context,
    node_path: str,
    output_index: int = 0,
) -> dict:
    """Get geometry representation from a COP node.

    In Copernicus (Houdini 20.5+), COP nodes can output geometry data.
    Returns point/primitive counts, attributes, and bounding box info.

    Args:
        ctx: MCP context.
        node_path: Path to the COP node.
        output_index: Output connector index (default 0).
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("cops.get_cop_geometry", {
        "node_path": node_path,
        "output_index": output_index,
    })


@mcp.tool()
async def get_cop_layer(
    ctx: Context,
    node_path: str,
    output_index: int = 0,
) -> dict:
    """Get image layer data information from a COP node.

    Returns the planes, components, depth, and resolution of the image layers.

    Args:
        ctx: MCP context.
        node_path: Path to the COP node.
        output_index: Output connector index (default 0).
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("cops.get_cop_layer", {
        "node_path": node_path,
        "output_index": output_index,
    })


@mcp.tool()
async def create_cop_node(
    ctx: Context,
    parent_path: str,
    cop_type: str,
    name: Optional[str] = None,
) -> dict:
    """Create a Copernicus COP node in the specified network.

    Args:
        ctx: MCP context.
        parent_path: Path to the parent COP network.
        cop_type: The COP node type to create (e.g. "file", "vopcop2gen").
        name: Optional explicit name for the node.
    """
    bridge = _get_bridge(ctx)
    params: dict = {
        "parent_path": parent_path,
        "cop_type": cop_type,
    }
    if name is not None:
        params["name"] = name
    return await bridge.execute("cops.create_cop_node", params)


@mcp.tool()
async def set_cop_flags(
    ctx: Context,
    node_path: str,
    display: Optional[bool] = None,
    export_flag: Optional[bool] = None,
    compress: Optional[bool] = None,
) -> dict:
    """Set flags on a COP node (display, export/render, compress).

    Args:
        ctx: MCP context.
        node_path: Path to the COP node.
        display: Set the display flag.
        export_flag: Set the render/export flag.
        compress: Set the compress flag.
    """
    bridge = _get_bridge(ctx)
    params: dict = {"node_path": node_path}
    if display is not None:
        params["display"] = display
    if export_flag is not None:
        params["export_flag"] = export_flag
    if compress is not None:
        params["compress"] = compress
    return await bridge.execute("cops.set_cop_flags", params)


@mcp.tool()
async def list_cop_node_types(
    ctx: Context,
    filter: Optional[str] = None,
) -> dict:
    """List available COP node types in Houdini.

    Returns all Cop2 node types with their labels and input counts.

    Args:
        ctx: MCP context.
        filter: Optional substring filter for node type names.
    """
    bridge = _get_bridge(ctx)
    params: dict = {}
    if filter is not None:
        params["filter"] = filter
    return await bridge.execute("cops.list_cop_node_types", params)


@mcp.tool()
async def get_cop_vdb(
    ctx: Context,
    node_path: str,
    output_index: int = 0,
) -> dict:
    """Get VDB volumetric data information from a COP node.

    In Copernicus, COP nodes can work with VDB data. Returns VDB primitive
    info including data type, voxel counts, bounding box, and transform.

    Args:
        ctx: MCP context.
        node_path: Path to the COP node.
        output_index: Output connector index (default 0).
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("cops.get_cop_vdb", {
        "node_path": node_path,
        "output_index": output_index,
    })
