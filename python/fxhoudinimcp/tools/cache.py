"""MCP tool wrappers for Houdini cache management operations.

Each tool delegates to the corresponding handler running inside Houdini
via the HTTP bridge.
"""

from __future__ import annotations

# Built-in
from typing import Any, Optional

# Third-party
from mcp.server.fastmcp import Context

# Internal
from fxhoudinimcp.server import mcp, _get_bridge


@mcp.tool()
async def list_caches(
    ctx: Context,
    root_path: str = "/",
) -> dict:
    """List all cache-type nodes (filecache, rop_geometry) in Houdini.

    Recursively searches under the given root path for cache nodes and
    returns their file path patterns, frame ranges, and current status.

    Args:
        ctx: MCP context.
        root_path: Root path to search from (default: "/").
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("cache.list_caches", {
        "root_path": root_path,
    })


@mcp.tool()
async def get_cache_status(ctx: Context, node_path: str) -> dict:
    """Get the detailed status of a specific Houdini cache node.

    Expands the file path pattern, checks which frames exist on disk,
    and calculates the total file size.

    Args:
        ctx: MCP context.
        node_path: Path to the cache node (e.g. "/obj/geo1/filecache1").
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("cache.get_cache_status", {
        "node_path": node_path,
    })


@mcp.tool()
async def clear_cache(
    ctx: Context,
    node_path: str,
    frame_range: Optional[list[int]] = None,
) -> dict:
    """Delete cached files from disk for a Houdini cache node.

    If frame_range is provided, only deletes files for frames within
    that range. Otherwise deletes all matching cached files.

    Args:
        ctx: MCP context.
        node_path: Path to the cache node (e.g. "/obj/geo1/filecache1").
        frame_range: Optional [start_frame, end_frame] to limit deletion.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"node_path": node_path}
    if frame_range is not None:
        params["frame_range"] = frame_range
    return await bridge.execute("cache.clear_cache", params)


@mcp.tool()
async def write_cache(
    ctx: Context,
    node_path: str,
    frame_range: Optional[list[int]] = None,
) -> dict:
    """Execute a Houdini cache node to write files to disk.

    Presses the execute button on filecache nodes or calls render()
    for ROP-style cache nodes.

    Args:
        ctx: MCP context.
        node_path: Path to the cache node (e.g. "/obj/geo1/filecache1").
        frame_range: Optional [start_frame, end_frame] to render. If not
            provided, uses the node's own frame range settings.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"node_path": node_path}
    if frame_range is not None:
        params["frame_range"] = frame_range
    return await bridge.execute("cache.write_cache", params)
