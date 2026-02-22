"""MCP tool wrappers for Houdini node operations.

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
async def create_node(
    ctx: Context,
    parent_path: str,
    node_type: str,
    name: Optional[str] = None,
    position: Optional[list] = None,
) -> dict:
    """Create a node inside a parent network.

    Args:
        ctx: MCP context.
        parent_path: Parent network path.
        node_type: Node type (e.g. 'geo', 'box', 'grid').
        name: Node name.
        position: [x, y] network editor position.
    """
    bridge = _get_bridge(ctx)
    params: dict = {
        "parent_path": parent_path,
        "node_type": node_type,
    }
    if name is not None:
        params["name"] = name
    if position is not None:
        params["position"] = position
    return await bridge.execute("nodes.create_node", params)


@mcp.tool()
async def delete_node(ctx: Context, node_path: str) -> dict:
    """Delete a node.

    Args:
        ctx: MCP context.
        node_path: Node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("nodes.delete_node", {"node_path": node_path})


@mcp.tool()
async def rename_node(ctx: Context, node_path: str, new_name: str) -> dict:
    """Rename a node.

    Args:
        ctx: MCP context.
        node_path: Node path.
        new_name: New node name.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "nodes.rename_node",
        {
            "node_path": node_path,
            "new_name": new_name,
        },
    )


@mcp.tool()
async def copy_node(
    ctx: Context,
    node_path: str,
    dest_parent: Optional[str] = None,
    new_name: Optional[str] = None,
) -> dict:
    """Copy a node, optionally into a different parent network.

    Args:
        ctx: MCP context.
        node_path: Source node path.
        dest_parent: Destination parent path.
        new_name: Name for the copy.
    """
    bridge = _get_bridge(ctx)
    params: dict = {"node_path": node_path}
    if dest_parent is not None:
        params["dest_parent"] = dest_parent
    if new_name is not None:
        params["new_name"] = new_name
    return await bridge.execute("nodes.copy_node", params)


@mcp.tool()
async def move_node(ctx: Context, node_path: str, dest_parent: str) -> dict:
    """Move a node to a different parent network.

    Args:
        ctx: MCP context.
        node_path: Node path.
        dest_parent: Destination parent path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "nodes.move_node",
        {
            "node_path": node_path,
            "dest_parent": dest_parent,
        },
    )


@mcp.tool()
async def get_node_info(ctx: Context, node_path: str) -> dict:
    """Get detailed information about a node.

    Args:
        ctx: MCP context.
        node_path: Node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("nodes.get_node_info", {"node_path": node_path})


@mcp.tool()
async def list_children(
    ctx: Context,
    parent_path: str,
    recursive: bool = False,
    filter_type: Optional[str] = None,
) -> dict:
    """List children of a network node.

    Args:
        ctx: MCP context.
        parent_path: Parent network path.
        recursive: Include all descendants.
        filter_type: Node type filter (e.g. 'box', 'merge').
    """
    bridge = _get_bridge(ctx)
    params: dict = {
        "parent_path": parent_path,
        "recursive": recursive,
    }
    if filter_type is not None:
        params["filter_type"] = filter_type
    return await bridge.execute("nodes.list_children", params)


@mcp.tool()
async def find_nodes(
    ctx: Context,
    pattern: Optional[str] = None,
    node_type: Optional[str] = None,
    context: Optional[str] = None,
    inside: str = "/",
) -> dict:
    """Search for nodes by name pattern, type, or context.

    Args:
        ctx: MCP context.
        pattern: Glob pattern for node names (e.g. 'box*').
        node_type: Node type filter (e.g. 'box', 'null').
        context: Category filter (e.g. 'Sop', 'Object').
        inside: Root path to search within.
    """
    bridge = _get_bridge(ctx)
    params: dict = {"inside": inside}
    if pattern is not None:
        params["pattern"] = pattern
    if node_type is not None:
        params["node_type"] = node_type
    if context is not None:
        params["context"] = context
    return await bridge.execute("nodes.find_nodes", params)


@mcp.tool()
async def list_node_types(ctx: Context, context: str) -> dict:
    """List available node types for a context category.

    Args:
        ctx: MCP context.
        context: Category name (e.g. 'Sop', 'Lop', 'Dop', 'Top', 'Cop2').
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("nodes.list_node_types", {"context": context})


@mcp.tool()
async def connect_nodes(
    ctx: Context,
    source_path: str,
    dest_path: str,
    output_index: int = 0,
    input_index: int = 0,
) -> dict:
    """Connect two nodes together.

    Args:
        ctx: MCP context.
        source_path: Upstream node path.
        dest_path: Downstream node path.
        output_index: Source output index.
        input_index: Destination input index.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "nodes.connect_nodes",
        {
            "source_path": source_path,
            "dest_path": dest_path,
            "output_index": output_index,
            "input_index": input_index,
        },
    )


@mcp.tool()
async def disconnect_node(
    ctx: Context,
    node_path: str,
    input_index: Optional[int] = None,
    disconnect_all: bool = False,
) -> dict:
    """Disconnect one or all inputs of a node.

    Args:
        ctx: MCP context.
        node_path: Node path.
        input_index: Input index to disconnect.
        disconnect_all: Disconnect all inputs.
    """
    bridge = _get_bridge(ctx)
    params: dict = {"node_path": node_path, "disconnect_all": disconnect_all}
    if input_index is not None:
        params["input_index"] = input_index
    return await bridge.execute("nodes.disconnect_node", params)


@mcp.tool()
async def reorder_inputs(ctx: Context, node_path: str, new_order: list) -> dict:
    """Reorder the input connections of a node.

    Args:
        ctx: MCP context.
        node_path: Node path.
        new_order: New input ordering (e.g. [1, 0] swaps first two).
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "nodes.reorder_inputs",
        {
            "node_path": node_path,
            "new_order": new_order,
        },
    )


@mcp.tool()
async def set_node_flags(
    ctx: Context,
    node_path: str,
    display: Optional[bool] = None,
    render: Optional[bool] = None,
    bypass: Optional[bool] = None,
    template: Optional[bool] = None,
    lock: Optional[bool] = None,
) -> dict:
    """Set flags on a node.

    Args:
        ctx: MCP context.
        node_path: Node path.
        display: Display flag.
        render: Render flag.
        bypass: Bypass flag.
        template: Template flag.
        lock: Lock flag.
    """
    bridge = _get_bridge(ctx)
    params: dict = {"node_path": node_path}
    if display is not None:
        params["display"] = display
    if render is not None:
        params["render"] = render
    if bypass is not None:
        params["bypass"] = bypass
    if template is not None:
        params["template"] = template
    if lock is not None:
        params["lock"] = lock
    return await bridge.execute("nodes.set_node_flags", params)


@mcp.tool()
async def layout_children(
    ctx: Context,
    parent_path: str,
    spacing: Optional[float] = None,
) -> dict:
    """Auto-layout children of a network node.

    Args:
        ctx: MCP context.
        parent_path: Parent network path.
        spacing: Spacing multiplier between nodes.
    """
    bridge = _get_bridge(ctx)
    params: dict = {"parent_path": parent_path}
    if spacing is not None:
        params["spacing"] = spacing
    return await bridge.execute("nodes.layout_children", params)


@mcp.tool()
async def set_node_position(
    ctx: Context, node_path: str, x: float, y: float
) -> dict:
    """Set a node's position in the network editor.

    Args:
        ctx: MCP context.
        node_path: Node path.
        x: Horizontal position.
        y: Vertical position.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "nodes.set_node_position",
        {
            "node_path": node_path,
            "x": x,
            "y": y,
        },
    )


@mcp.tool()
async def set_node_color(
    ctx: Context,
    node_path: str,
    r: float,
    g: float,
    b: float,
) -> dict:
    """Set a node's color in the network editor.

    Args:
        ctx: MCP context.
        node_path: Node path.
        r: Red (0.0-1.0).
        g: Green (0.0-1.0).
        b: Blue (0.0-1.0).
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "nodes.set_node_color",
        {
            "node_path": node_path,
            "r": r,
            "g": g,
            "b": b,
        },
    )
