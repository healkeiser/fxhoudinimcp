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
    """List all cache-type nodes under a root path.

    Args:
        ctx: MCP context.
        root_path: Root path to search from.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "cache.list_caches",
        {
            "root_path": root_path,
        },
    )


@mcp.tool()
async def get_cache_status(ctx: Context, node_path: str) -> dict:
    """Get the detailed status of a cache node.

    Args:
        ctx: MCP context.
        node_path: Path to the cache node.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "cache.get_cache_status",
        {
            "node_path": node_path,
        },
    )


@mcp.tool()
async def clear_cache(
    ctx: Context,
    node_path: str,
    frame_range: Optional[list[int]] = None,
) -> dict:
    """Delete cached files on disk for a cache node.

    Args:
        ctx: MCP context.
        node_path: Path to the cache node.
        frame_range: [start, end] frame range to limit deletion.
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
    """Execute a cache node to write files to disk.

    Args:
        ctx: MCP context.
        node_path: Path to the cache node.
        frame_range: [start, end] frame range to render.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"node_path": node_path}
    if frame_range is not None:
        params["frame_range"] = frame_range
    return await bridge.execute("cache.write_cache", params)
