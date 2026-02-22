"""MCP tool wrappers for Houdini PDG/TOPs operations.

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
async def get_top_network_info(ctx: Context, node_path: str) -> dict:
    """Get an overview of a TOP network including node count, scheduler info, and cook state.

    Args:
        ctx: MCP context.
        node_path: Path to a TOP network node (topnet) or a TOP node inside one.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("tops.get_top_network_info", {"node_path": node_path})


@mcp.tool()
async def cook_top_node(
    ctx: Context,
    node_path: str,
    block: bool = True,
    generate_only: bool = False,
) -> dict:
    """Cook a TOP node to execute its work items.

    Uses blocking cook by default. Set generate_only=True to only generate
    work items without executing them.

    Args:
        ctx: MCP context.
        node_path: Path to the TOP node to cook.
        block: If True, wait for cooking to complete before returning.
        generate_only: If True, only generate work items without cooking.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("tops.cook_top_node", {
        "node_path": node_path,
        "block": block,
        "generate_only": generate_only,
    })


@mcp.tool()
async def cancel_top_cook(ctx: Context, node_path: str) -> dict:
    """Cancel any active cooking on a TOP network.

    Args:
        ctx: MCP context.
        node_path: Path to a TOP node or TOP network.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("tops.cancel_top_cook", {"node_path": node_path})


@mcp.tool()
async def pause_top_cook(ctx: Context, node_path: str) -> dict:
    """Pause cooking on a TOP network.

    Args:
        ctx: MCP context.
        node_path: Path to a TOP node or TOP network.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("tops.pause_top_cook", {"node_path": node_path})


@mcp.tool()
async def dirty_work_items(
    ctx: Context,
    node_path: str,
    remove_outputs: bool = False,
) -> dict:
    """Dirty (invalidate) work items on a TOP node so they can be regenerated.

    Args:
        ctx: MCP context.
        node_path: Path to the TOP node.
        remove_outputs: If True, also remove output files from disk.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("tops.dirty_work_items", {
        "node_path": node_path,
        "remove_outputs": remove_outputs,
    })


@mcp.tool()
async def get_work_item_states(ctx: Context, node_path: str) -> dict:
    """Get the count of work items in each state for a TOP node.

    States include: waiting, scheduled, cooking, cooked_success,
    cooked_fail, cooked_cancel, etc.

    Args:
        ctx: MCP context.
        node_path: Path to the TOP node.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("tops.get_work_item_states", {"node_path": node_path})


@mcp.tool()
async def get_work_item_info(
    ctx: Context,
    node_path: str,
    work_item_index: int,
) -> dict:
    """Get detailed information about a specific work item on a TOP node.

    Returns the work item's ID, name, state, frame, priority, attributes,
    and output files.

    Args:
        ctx: MCP context.
        node_path: Path to the TOP node.
        work_item_index: Index of the work item within the node.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("tops.get_work_item_info", {
        "node_path": node_path,
        "work_item_index": work_item_index,
    })


@mcp.tool()
async def get_pdg_graph(ctx: Context, node_path: str) -> dict:
    """Get the PDG dependency graph structure for a TOP network.

    Returns all nodes and their dependency connections (edges).

    Args:
        ctx: MCP context.
        node_path: Path to a TOP network node or TOP node inside one.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("tops.get_pdg_graph", {"node_path": node_path})


@mcp.tool()
async def generate_static_items(ctx: Context, node_path: str) -> dict:
    """Generate static work items on a TOP node without cooking them.

    Useful for previewing what work items will be created before running the graph.

    Args:
        ctx: MCP context.
        node_path: Path to the TOP node.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("tops.generate_static_items", {"node_path": node_path})


@mcp.tool()
async def get_top_scheduler_info(ctx: Context, node_path: str) -> dict:
    """Get information about TOP scheduler nodes in a network.

    If node_path points to a scheduler, returns its details. Otherwise,
    returns info about all schedulers found in the TOP network.

    Args:
        ctx: MCP context.
        node_path: Path to a TOP scheduler node or a TOP network.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("tops.get_top_scheduler_info", {"node_path": node_path})
