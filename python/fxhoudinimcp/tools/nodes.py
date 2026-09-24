"""MCP tool wrappers for Houdini node operations.

Each tool delegates to the corresponding handler running inside Houdini
via the HTTP bridge.
"""

from __future__ import annotations

# Built-in
from typing import Any

# Third-party
from fxhoudinimcp._sdk import Context

# Internal
from fxhoudinimcp.bridge import NO_TIMEOUT
from fxhoudinimcp.config import auto_layout_enabled
from fxhoudinimcp.errors import HoudiniCommandError
from fxhoudinimcp.server import _get_bridge, mcp


@mcp.tool()
async def create_node(
    ctx: Context,
    parent_path: str,
    node_type: str,
    name: str | None = None,
    position: list[float] | None = None,
) -> dict:
    """Create a node inside a parent network.

    Before using this, call list_node_types(context='<context>', filter='<keyword>')
    to verify a dedicated node exists for the operation. Houdini has thousands of
    nodes — many common operations (boolean, scatter, copy to points, fracture,
    ocean, hair, vellum, pyro, etc.) have dedicated nodes that are better than
    writing VEX or Python.

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
    dest_parent: str | None = None,
    new_name: str | None = None,
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
    """Get type, connections, flags, errors, cook time, and non-default parameters for a node.

    Returns only parameters that differ from their defaults (non_default_parameters)
    plus a total_param_count. Use get_parameter_schema to inspect the full parameter list.

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
    filter_type: str | None = None,
) -> dict:
    """List children of a network node.

    Avoid `recursive=True` on large networks — it can return hundreds or
    thousands of nodes. Prefer `find_nodes` with a specific pattern instead.

    Args:
        ctx: MCP context.
        parent_path: Parent network path.
        recursive: Include all descendants (use sparingly on large scenes).
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
    pattern: str | None = None,
    node_type: str | None = None,
    context: str | None = None,
    inside: str = "/",
) -> dict:
    """Search for nodes by name pattern, type, or context.

    Narrow the search: use `inside` to limit to a specific sub-network and
    supply at least one of `pattern`, `node_type`, or `context`. Searching
    from `inside="/"` with no filters scans the entire scene and can return
    hundreds of nodes.

    Args:
        ctx: MCP context.
        pattern: Glob pattern for node names (e.g. 'box*').
        node_type: Node type filter (e.g. 'box', 'null').
        context: Category filter (e.g. 'Sop', 'Object').
        inside: Root path to search within (default '/').
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
async def list_node_types(
    ctx: Context,
    context: str,
    filter: str | None = None,
    limit: int = 200,
) -> dict:
    """List available node types for a context category.

    IMPORTANT: Any context can have hundreds of node types (SOPs alone can
    exceed 800 in a production install). Always pass a `filter` keyword
    (e.g. 'mountain', 'scatter', 'boolean') instead of dumping the full list
    — the unfiltered response is capped at `limit` and may still be large.

    Args:
        ctx: MCP context.
        context: Category name (e.g. 'Sop', 'Lop', 'Dop', 'Top', 'Cop2').
        filter: Substring to filter type name or label (case-insensitive).
        limit: Max entries to return (default 200, max recommended 200).
    """
    bridge = _get_bridge(ctx)
    params: dict = {"context": context, "limit": limit}
    if filter is not None:
        params["filter"] = filter
    return await bridge.execute("nodes.list_node_types", params)


@mcp.tool()
async def change_node_type(
    ctx: Context,
    node_path: str,
    new_type: str,
    keep_name: bool = True,
    keep_parms: bool = True,
    keep_network_contents: bool = True,
) -> dict:
    """Change a node's type in place, keeping wires, name, position, flags,
    parameter values and (for subnets/assets) network contents.

    This is how an HDA instance is moved to an installed newer version
    (`building::2.0`) without losing its edits, and how a placeholder is
    swapped for the real node. Every value set before the swap and not after
    it is named in `parms_dropped` (no such parameter on the new type) or
    `parms_reset` (back at its default). Unversioned names map to the
    preferred version, as create_node does.

    Args:
        node_path: Node to change.
        new_type: Type name in the node's own category.
        keep_name: Keep the node's name.
        keep_parms: Carry parameter values over by name.
        keep_network_contents: Keep a subnet's/asset's children (False resets
            an asset to its definition's contents, also on a node that is
            already of new_type).
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "nodes.change_node_type",
        {
            "node_path": node_path,
            "new_type": new_type,
            "keep_name": keep_name,
            "keep_parms": keep_parms,
            "keep_network_contents": keep_network_contents,
        },
    )


@mcp.tool()
async def press_button(
    ctx: Context,
    node_path: str,
    parm_name: str,
    arguments: dict[str, Any] | None = None,
    cook: bool = False,
) -> dict:
    """Press a button parameter — "Stash Input", "Reload Geometry", an
    asset's own Build button — and read the node's errors and warnings
    afterwards.

    The call holds until the callback returns, with no deadline. A callback
    that opens a dialog blocks Houdini's main thread and this bridge with it;
    read the button's script first if in doubt. A Python callback that
    RAISES does not hang anything: the bridge runs it rather than
    pressButton(), and its error comes back as this call's error.
    `callback_route` says how the press ran: python, hscript or native (a
    built-in action). For a Save to Disk or a render use write_cache /
    start_render, which report a verdict.

    A press usually only dirties the node, so `errors`/`warnings` are from
    its last cook unless `cook=True`; without it `needs_cook` says whether
    they are stale (a cook that failed leaves it True too). `has_script_callback` is False for built-in buttons that still
    do work (File's Reload, Stash's Stash Input).

    Args:
        node_path: Node that owns the button.
        parm_name: The button parameter's name.
        arguments: Optional kwargs handed to the callback script; values
            must be int, bool, float or str.
        cook: Cook the node after the press so errors describe the result.
    """
    bridge = _get_bridge(ctx)
    payload: dict[str, Any] = {"node_path": node_path, "parm_name": parm_name}
    if arguments:
        payload["arguments"] = arguments
    if cook:
        payload["cook"] = True
    return await bridge.execute("nodes.press_button", payload, timeout=NO_TIMEOUT)


@mcp.tool()
async def connect_nodes(
    ctx: Context,
    source_path: str,
    dest_path: str,
    output_index: int = 0,
    input_index: int = 0,
    input_name: str | None = None,
    indirect_input: int | None = None,
) -> dict:
    """Connect two nodes together.

    To feed a node INSIDE a subnet from one of the subnet's own input
    connectors (a SubnetIndirectInput — not a node, it has no path), pass
    the subnet as source_path and the connector index as indirect_input.

    Args:
        ctx: MCP context.
        source_path: Upstream node path; with indirect_input, the subnet
            whose input connector is the source.
        dest_path: Downstream node path.
        output_index: Source output index.
        input_index: Destination input index.
        input_name: Destination connector name or label (e.g. "base_color"
            on a VOP shader); wins over input_index.
        indirect_input: Index of the subnet input connector at source_path
            to wire from (dest_path must live inside that subnet).
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {
        "source_path": source_path,
        "dest_path": dest_path,
        "output_index": output_index,
        "input_index": input_index,
        "input_name": input_name,
    }
    if indirect_input is None:
        return await bridge.execute("nodes.connect_nodes", params)
    params["indirect_input"] = indirect_input
    try:
        return await bridge.execute("nodes.connect_nodes", params)
    except HoudiniCommandError as exc:
        # The compatibility check compares command names, and connect_nodes
        # exists on a plugin that predates indirect_input: say so.
        if exc.code == "BAD_ARGUMENTS" and "indirect_input" in str(exc):
            raise HoudiniCommandError(
                f"{exc} The Houdini plugin predates indirect_input; update the "
                f"plugin to wire from a subnet's input connector.",
                code=exc.code,
                details=exc.details,
            ) from exc
        raise


@mcp.tool()
async def connect_nodes_batch(
    ctx: Context,
    connections: list[dict[str, Any]],
) -> dict:
    """Connect multiple node pairs in a single call.

    Args:
        connections: List of connections. Each dict has keys:
            source_path (str), dest_path (str),
            output_index (int, default 0), input_index (int, default 0),
            input_name (str, optional: connector name or label, wins over input_index),
            indirect_input (int, optional: source_path is then a subnet and this is
            the index of its input connector to wire from — for the first node of
            a chain built inside that subnet).
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "nodes.connect_nodes_batch",
        {"connections": connections},
    )


@mcp.tool()
async def disconnect_node(
    ctx: Context,
    node_path: str,
    input_index: int | None = None,
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
async def reorder_inputs(ctx: Context, node_path: str, new_order: list[int]) -> dict:
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
    display: bool | None = None,
    render: bool | None = None,
    bypass: bool | None = None,
    template: bool | None = None,
    lock: bool | None = None,
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
    spacing: float | None = None,
) -> dict:
    """Auto-layout children of a network node.

    Does nothing when auto-layout is disabled via FXHOUDINIMCP_AUTO_LAYOUT=0.

    Args:
        ctx: MCP context.
        parent_path: Parent network path.
        spacing: Spacing multiplier between nodes.
    """
    if not auto_layout_enabled():
        return {
            "skipped": True,
            "reason": (
                "Auto-layout is disabled (FXHOUDINIMCP_AUTO_LAYOUT=0). "
                "Leave node positions as they are; do not retry."
            ),
        }
    bridge = _get_bridge(ctx)
    params: dict = {"parent_path": parent_path}
    if spacing is not None:
        params["spacing"] = spacing
    return await bridge.execute("nodes.layout_children", params)


@mcp.tool()
async def set_node_position(ctx: Context, node_path: str, x: float, y: float) -> dict:
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


@mcp.tool()
async def create_network_box(
    ctx: Context,
    parent_path: str,
    node_paths: list[str] | None = None,
    comment: str | None = None,
    color: list[float] | None = None,
) -> dict:
    """Draw a titled network box around nodes, to document a graph you built.

    Args:
        ctx: MCP context.
        parent_path: Network the box lives in.
        node_paths: Sibling nodes to enclose; the box fits around them.
        comment: Title shown on the box.
        color: RGB in 0..1.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"parent_path": parent_path}
    if node_paths is not None:
        params["node_paths"] = node_paths
    if comment is not None:
        params["comment"] = comment
    if color is not None:
        params["color"] = color
    return await bridge.execute("nodes.create_network_box", params)


@mcp.tool()
async def create_sticky_note(
    ctx: Context,
    parent_path: str,
    text: str,
    position: list[float] | None = None,
    size: list[float] | None = None,
    color: list[float] | None = None,
) -> dict:
    """Leave a sticky note in a network.

    Args:
        ctx: MCP context.
        parent_path: Network the note lives in.
        text: Note text.
        position: [x, y] in network editor units.
        size: [width, height] in network editor units.
        color: RGB in 0..1.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"parent_path": parent_path, "text": text}
    if position is not None:
        params["position"] = position
    if size is not None:
        params["size"] = size
    if color is not None:
        params["color"] = color
    return await bridge.execute("nodes.create_sticky_note", params)


@mcp.tool()
async def set_object_transform(
    ctx: Context,
    node_path: str,
    translate: list[float] | None = None,
    rotate: list[float] | None = None,
    scale: list[float] | None = None,
    parent: str | None = None,
) -> dict:
    """Set an object's translate, rotate, scale and/or parent in one call.

    Only the arguments you pass change. Object-level nodes under /obj only;
    SOP transforms are a Transform SOP, not this.

    Args:
        ctx: MCP context.
        node_path: Object node, e.g. "/obj/geo1".
        translate: [tx, ty, tz].
        rotate: [rx, ry, rz] in degrees.
        scale: [sx, sy, sz].
        parent: Object to parent under, or "" to unparent.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"node_path": node_path}
    if translate is not None:
        params["translate"] = translate
    if rotate is not None:
        params["rotate"] = rotate
    if scale is not None:
        params["scale"] = scale
    if parent is not None:
        params["parent"] = parent
    return await bridge.execute("nodes.set_object_transform", params)
