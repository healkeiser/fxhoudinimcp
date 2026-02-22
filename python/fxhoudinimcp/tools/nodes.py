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
    """Create a new node inside a Houdini network.

    Args:
        ctx: MCP context.
        parent_path: Path to the parent network (e.g. "/obj", "/obj/geo1").
        node_type: Node type name (e.g. "geo", "box", "grid", "merge").
        name: Optional explicit name for the new node.
        position: Optional [x, y] position in the network editor.
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
    """Delete a node from the Houdini scene.

    Args:
        ctx: MCP context.
        node_path: Absolute path to the node to delete (e.g. "/obj/geo1").
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("nodes.delete_node", {"node_path": node_path})


@mcp.tool()
async def rename_node(ctx: Context, node_path: str, new_name: str) -> dict:
    """Rename an existing Houdini node.

    Args:
        ctx: MCP context.
        node_path: Absolute path to the node to rename.
        new_name: Desired new name for the node.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("nodes.rename_node", {
        "node_path": node_path,
        "new_name": new_name,
    })


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
        node_path: Path to the source node to copy.
        dest_parent: Destination parent path. If omitted, copies within the same parent.
        new_name: Optional name for the copied node.
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
        node_path: Path to the node to move.
        dest_parent: Destination parent network path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("nodes.move_node", {
        "node_path": node_path,
        "dest_parent": dest_parent,
    })


@mcp.tool()
async def get_node_info(ctx: Context, node_path: str) -> dict:
    """Get comprehensive information about a Houdini node.

    Returns the node's type, parameters summary (name, value, default, type),
    input/output connections, flags (display, render, bypass, template, lock),
    errors, warnings, cook time, comment, position, and color.

    Args:
        ctx: MCP context.
        node_path: Absolute path to the node (e.g. "/obj/geo1/box1").
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
    """List children of a Houdini network node.

    Args:
        ctx: MCP context.
        parent_path: Path to the parent network (e.g. "/obj", "/obj/geo1").
        recursive: If True, list all descendants recursively, not just direct children.
        filter_type: Optional node type name to filter by (e.g. "box", "merge").
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
    """Search for nodes by name pattern and/or type within the Houdini scene.

    At least one of pattern, node_type, or context should be specified
    to avoid returning every node in the scene.

    Args:
        ctx: MCP context.
        pattern: Glob pattern for node names (e.g. "box*", "*merge*").
        node_type: Filter by node type name (e.g. "box", "null").
        context: Filter by node category name (e.g. "Sop", "Object").
        inside: Root path to search within (default: "/").
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
    """List all available node types in a given Houdini context category.

    Args:
        ctx: MCP context.
        context: Category name, e.g. "Sop", "Lop", "Dop", "Top",
                 "Cop2", "Object", "Driver".
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
    """Wire two Houdini nodes together.

    Connects the output of the source node to the input of the destination node.

    Args:
        ctx: MCP context.
        source_path: Path to the source (upstream) node.
        dest_path: Path to the destination (downstream) node.
        output_index: Output connector index on the source node (default: 0).
        input_index: Input connector index on the destination node (default: 0).
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("nodes.connect_nodes", {
        "source_path": source_path,
        "dest_path": dest_path,
        "output_index": output_index,
        "input_index": input_index,
    })


@mcp.tool()
async def disconnect_node(
    ctx: Context,
    node_path: str,
    input_index: Optional[int] = None,
    disconnect_all: bool = False,
) -> dict:
    """Disconnect one or all inputs of a Houdini node.

    Provide either a specific input_index to disconnect or set
    disconnect_all=True to remove all input connections.

    Args:
        ctx: MCP context.
        node_path: Path to the node whose inputs to disconnect.
        input_index: Specific input index to disconnect. Ignored if disconnect_all is True.
        disconnect_all: If True, disconnect all inputs.
    """
    bridge = _get_bridge(ctx)
    params: dict = {"node_path": node_path, "disconnect_all": disconnect_all}
    if input_index is not None:
        params["input_index"] = input_index
    return await bridge.execute("nodes.disconnect_node", params)


@mcp.tool()
async def reorder_inputs(ctx: Context, node_path: str, new_order: list) -> dict:
    """Reorder the input connections of a Houdini node.

    Args:
        ctx: MCP context.
        node_path: Path to the node whose inputs to reorder.
        new_order: List of integers representing the new input ordering.
                   For example, [1, 0] swaps the first two inputs.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("nodes.reorder_inputs", {
        "node_path": node_path,
        "new_order": new_order,
    })


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
    """Set one or more flags on a Houdini node.

    Only the flags you explicitly provide will be changed; omitted flags
    remain untouched.

    Args:
        ctx: MCP context.
        node_path: Path to the node.
        display: Set the display flag (blue).
        render: Set the render flag (purple).
        bypass: Set the bypass flag (yellow).
        template: Set the template flag.
        lock: Set the hard-lock flag.
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
    """Auto-layout the children of a Houdini network node.

    Arranges child nodes in a clean layout within the network editor.

    Args:
        ctx: MCP context.
        parent_path: Path to the parent network (e.g. "/obj", "/obj/geo1").
        spacing: Optional spacing multiplier between nodes.
    """
    bridge = _get_bridge(ctx)
    params: dict = {"parent_path": parent_path}
    if spacing is not None:
        params["spacing"] = spacing
    return await bridge.execute("nodes.layout_children", params)


@mcp.tool()
async def set_node_position(ctx: Context, node_path: str, x: float, y: float) -> dict:
    """Set the position of a node in the Houdini network editor.

    Args:
        ctx: MCP context.
        node_path: Path to the node.
        x: Horizontal position.
        y: Vertical position.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("nodes.set_node_position", {
        "node_path": node_path,
        "x": x,
        "y": y,
    })


@mcp.tool()
async def set_node_color(
    ctx: Context,
    node_path: str,
    r: float,
    g: float,
    b: float,
) -> dict:
    """Set the display color of a node in the Houdini network editor.

    Args:
        ctx: MCP context.
        node_path: Path to the node.
        r: Red component (0.0 to 1.0).
        g: Green component (0.0 to 1.0).
        b: Blue component (0.0 to 1.0).
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("nodes.set_node_color", {
        "node_path": node_path,
        "r": r,
        "g": g,
        "b": b,
    })
