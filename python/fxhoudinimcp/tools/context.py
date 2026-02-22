"""MCP tool wrappers for Houdini scene-understanding / context operations.

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
async def get_network_overview(
    ctx: Context,
    path: str = "/obj",
    depth: int = 2,
) -> dict:
    """Get a compact overview of a Houdini network.

    Returns each node's name, type, position, flags, and error state,
    connections as an adjacency list, which node has the display/render
    flag, an ASCII-art text representation of the network flow, and
    optionally recurses into child networks.

    Args:
        ctx: MCP context.
        path: Root network path to inspect (default: "/obj").
        depth: How many levels deep to recurse into child networks (default: 2).
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("context.get_network_overview", {
        "path": path,
        "depth": depth,
    })


@mcp.tool()
async def get_cook_chain(ctx: Context, node_path: str) -> dict:
    """Trace the cook dependency chain for a Houdini node.

    Walks the node's inputs recursively back to source nodes and returns
    an ordered list from source to target, including each node's path,
    type, cook time, and error state.

    Args:
        ctx: MCP context.
        node_path: Absolute path to the target node (e.g. "/obj/geo1/mountain1").
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("context.get_cook_chain", {
        "node_path": node_path,
    })


@mcp.tool()
async def explain_node(ctx: Context, node_path: str) -> dict:
    """Get a human-readable explanation of a Houdini node.

    Returns the node type description, non-default parameters, input and
    output connections, current state (errors, warnings, cook time, flags),
    and a summary text field suitable for display.

    Args:
        ctx: MCP context.
        node_path: Absolute path to the node (e.g. "/obj/geo1/box1").
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("context.explain_node", {
        "node_path": node_path,
    })


@mcp.tool()
async def get_selection(ctx: Context) -> dict:
    """Get the current selection in Houdini.

    Returns selected nodes (path, type, name) and, if available,
    geometry component selection (points, primitives, edges) with
    the selection type, count, and source node path.

    Args:
        ctx: MCP context.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("context.get_selection")


@mcp.tool()
async def set_selection(
    ctx: Context,
    node_paths: Optional[list] = None,
) -> dict:
    """Select nodes in Houdini by their paths.

    Clears the existing selection first, then selects the specified nodes.
    Pass an empty list to clear the selection entirely.

    Args:
        ctx: MCP context.
        node_paths: List of absolute node paths to select (default: []).
    """
    bridge = _get_bridge(ctx)
    params: dict = {}
    if node_paths is not None:
        params["node_paths"] = node_paths
    return await bridge.execute("context.set_selection", params)


@mcp.tool()
async def get_scene_summary(ctx: Context) -> dict:
    """Get a high-level summary of the entire Houdini scene.

    Returns all /obj children with their types and SOP contents, all /out
    render nodes with output paths, all /stage LOP children, total node
    count, error count, current frame, frame range, and FPS.

    Args:
        ctx: MCP context.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("context.get_scene_summary")


@mcp.tool()
async def compare_snapshots(
    ctx: Context,
    action: str = "take",
    snapshot_name: str = "default",
) -> dict:
    """Take or compare scene state snapshots for structural diffing.

    Use action="take" to capture the current scene state (node paths and
    non-default parameter values). Use action="compare" to diff the current
    state against a previously stored snapshot, returning nodes added,
    nodes removed, and parameters changed.

    Args:
        ctx: MCP context.
        action: "take" to store current state, "compare" to diff against stored.
        snapshot_name: Name of the snapshot (default: "default").
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("context.compare_snapshots", {
        "action": action,
        "snapshot_name": snapshot_name,
    })


@mcp.tool()
async def get_node_errors_detailed(
    ctx: Context,
    node_path: Optional[str] = None,
    root_path: str = "/",
) -> dict:
    """Get detailed error analysis for Houdini nodes.

    If node_path is given, analyzes that specific node's errors and warnings.
    Otherwise, scans all descendants of root_path for errors. For each error,
    returns the node path, error message, node type, and suspect parameters
    that might be causing the issue (e.g. file paths pointing to missing files).

    Args:
        ctx: MCP context.
        node_path: Specific node to analyze. If omitted, scans root_path descendants.
        root_path: Root path to scan when node_path is not given (default: "/").
    """
    bridge = _get_bridge(ctx)
    params: dict = {"root_path": root_path}
    if node_path is not None:
        params["node_path"] = node_path
    return await bridge.execute("context.get_node_errors_detailed", params)
