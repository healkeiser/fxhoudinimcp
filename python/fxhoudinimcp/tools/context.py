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
    """Get a compact overview of a network.

    Args:
        path: Network path.
        depth: Recursion depth.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "context.get_network_overview",
        {
            "path": path,
            "depth": depth,
        },
    )


@mcp.tool()
async def get_cook_chain(ctx: Context, node_path: str) -> dict:
    """Trace the cook dependency chain for a node.

    Args:
        node_path: Node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "context.get_cook_chain",
        {
            "node_path": node_path,
        },
    )


@mcp.tool()
async def explain_node(ctx: Context, node_path: str) -> dict:
    """Explain a node in human-readable form.

    Args:
        node_path: Node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "context.explain_node",
        {
            "node_path": node_path,
        },
    )


@mcp.tool()
async def get_selection(ctx: Context) -> dict:
    """Get the current node selection."""
    bridge = _get_bridge(ctx)
    return await bridge.execute("context.get_selection")


@mcp.tool()
async def set_selection(
    ctx: Context,
    node_paths: Optional[list] = None,
) -> dict:
    """Set the node selection.

    Args:
        node_paths: Node paths to select.
    """
    bridge = _get_bridge(ctx)
    params: dict = {}
    if node_paths is not None:
        params["node_paths"] = node_paths
    return await bridge.execute("context.set_selection", params)


@mcp.tool()
async def get_scene_summary(ctx: Context) -> dict:
    """Get a high-level summary of the scene."""
    bridge = _get_bridge(ctx)
    return await bridge.execute("context.get_scene_summary")


@mcp.tool()
async def compare_snapshots(
    ctx: Context,
    action: str = "take",
    snapshot_name: str = "default",
) -> dict:
    """Take or compare scene state snapshots.

    Args:
        action: "take" or "compare".
        snapshot_name: Snapshot name.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "context.compare_snapshots",
        {
            "action": action,
            "snapshot_name": snapshot_name,
        },
    )


@mcp.tool()
async def get_node_errors_detailed(
    ctx: Context,
    node_path: Optional[str] = None,
    root_path: str = "/",
) -> dict:
    """Get detailed error analysis for nodes.

    Args:
        node_path: Node to analyze, or scan from root_path if omitted.
        root_path: Root path to scan.
    """
    bridge = _get_bridge(ctx)
    params: dict = {"root_path": root_path}
    if node_path is not None:
        params["node_path"] = node_path
    return await bridge.execute("context.get_node_errors_detailed", params)
