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
    """Get an overview of a TOP network.

    Args:
        ctx: MCP context.
        node_path: TOPnet or TOP node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "tops.get_top_network_info", {"node_path": node_path}
    )


@mcp.tool()
async def cook_top_node(
    ctx: Context,
    node_path: str,
    block: bool = True,
    generate_only: bool = False,
) -> dict:
    """Cook a TOP node to execute its work items.

    Args:
        ctx: MCP context.
        node_path: TOP node path.
        block: Wait for cooking to complete.
        generate_only: Only generate work items, do not cook.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "tops.cook_top_node",
        {
            "node_path": node_path,
            "block": block,
            "generate_only": generate_only,
        },
    )


@mcp.tool()
async def cancel_top_cook(ctx: Context, node_path: str) -> dict:
    """Cancel active cooking on a TOP network.

    Args:
        ctx: MCP context.
        node_path: TOP node or TOPnet path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "tops.cancel_top_cook", {"node_path": node_path}
    )


@mcp.tool()
async def pause_top_cook(ctx: Context, node_path: str) -> dict:
    """Pause cooking on a TOP network.

    Args:
        ctx: MCP context.
        node_path: TOP node or TOPnet path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("tops.pause_top_cook", {"node_path": node_path})


@mcp.tool()
async def dirty_work_items(
    ctx: Context,
    node_path: str,
    remove_outputs: bool = False,
) -> dict:
    """Dirty work items on a TOP node so they can be regenerated.

    Args:
        ctx: MCP context.
        node_path: TOP node path.
        remove_outputs: Also remove output files from disk.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "tops.dirty_work_items",
        {
            "node_path": node_path,
            "remove_outputs": remove_outputs,
        },
    )


@mcp.tool()
async def get_work_item_states(ctx: Context, node_path: str) -> dict:
    """Get work item state counts for a TOP node.

    Args:
        ctx: MCP context.
        node_path: TOP node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "tops.get_work_item_states", {"node_path": node_path}
    )


@mcp.tool()
async def get_work_item_info(
    ctx: Context,
    node_path: str,
    work_item_index: int,
) -> dict:
    """Get detailed information about a specific work item.

    Args:
        ctx: MCP context.
        node_path: TOP node path.
        work_item_index: Work item index within the node.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "tops.get_work_item_info",
        {
            "node_path": node_path,
            "work_item_index": work_item_index,
        },
    )


@mcp.tool()
async def get_pdg_graph(ctx: Context, node_path: str) -> dict:
    """Get the PDG dependency graph structure for a TOP network.

    Args:
        ctx: MCP context.
        node_path: TOPnet or TOP node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("tops.get_pdg_graph", {"node_path": node_path})


@mcp.tool()
async def generate_static_items(ctx: Context, node_path: str) -> dict:
    """Generate static work items on a TOP node without cooking.

    Args:
        ctx: MCP context.
        node_path: TOP node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "tops.generate_static_items", {"node_path": node_path}
    )


@mcp.tool()
async def get_top_scheduler_info(ctx: Context, node_path: str) -> dict:
    """Get information about TOP scheduler nodes in a network.

    Args:
        ctx: MCP context.
        node_path: TOP scheduler or TOPnet path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "tops.get_top_scheduler_info", {"node_path": node_path}
    )
