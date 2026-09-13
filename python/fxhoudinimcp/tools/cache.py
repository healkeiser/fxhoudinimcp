"""MCP tool wrappers for Houdini cache management operations.

Each tool delegates to the corresponding handler running inside Houdini
via the HTTP bridge.
"""

from __future__ import annotations

# Built-in
from typing import Any

# Third-party
from fxhoudinimcp._sdk import Context

# Internal
from fxhoudinimcp.server import _get_bridge, mcp

# A cache write is given an hour by the plugin; the client waits as long.
_LONG_TIMEOUT = 3600.0


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
    """Frames on disk for a cache node, against the range it is set to write.

    This is what to poll after a background write_cache: `complete` is true
    when every frame of `expected_range` is on disk, `missing_frames` lists
    the rest, `writing` is true while files are still arriving, and `hint`
    tells you when the finished cache is not yet loaded from disk. Never
    wait for a cache with a shell loop; call this between other work.

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
    frame_range: list[int] | None = None,
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
    frame_range: list[int] | None = None,
    background: bool = False,
) -> dict:
    """Execute a cache node, and report whether a cache actually appeared.

    Foreground by default: Houdini shows its own progress dialog and the
    user can cancel. The call holds until the write finishes, up to an hour;
    a client that hands a long call to a background task notifies you with
    the verdict when it lands. Do nothing else in Houdini meanwhile (every
    other call queues behind the write) and never poll the disk.

    `success` and `wrote_files` reflect the files on disk and the errors of the
    node that did the writing -- a filecache delegates to an internal ROP and
    stays silent itself, so a failed write used to be reported as success.
    Errors are named with the node they came from.

    Args:
        ctx: MCP context.
        node_path: Path to the cache node.
        frame_range: [start, end] frame range to render. Overrides the
            node's $FSTART/$FEND expressions for this and later writes.
        background: Save from a separate Houdini process (File Cache's own
            "Save to Disk in Background") so Houdini stays usable, at the
            cost of the user seeing no progress there. Saves the hip first,
            returns at once with status "launched"; follow it with
            get_cache_status. Use it only when asked to keep working while
            a cache writes. A verified foreground write turns the node's
            Load from Disk on.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"node_path": node_path, "background": background}
    if frame_range is not None:
        params["frame_range"] = frame_range
    return await bridge.execute("cache.write_cache", params, timeout=_LONG_TIMEOUT)
