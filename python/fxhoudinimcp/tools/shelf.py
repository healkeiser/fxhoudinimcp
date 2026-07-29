"""MCP tools for Houdini's shelf tools.

Some setups are authored by a shelf tool rather than by node creation -- the ocean
procedural's internals come from ``dopparticlefluidtoolutils.largeOcean`` -- so
build_network structurally cannot produce them, and reading SideFX's own recipe is
often more valuable than running it.
"""

from __future__ import annotations

# Built-in
from typing import Any

# Third-party
from fxhoudinimcp._sdk import Context

# Internal
from fxhoudinimcp.server import _get_bridge, mcp


@mcp.tool()
async def list_shelf_tools(
    ctx: Context,
    filter: str | None = None,
    limit: int = 60,
) -> dict:
    """Find shelf tools by name, label or keyword.

    Use this when a setup exists as a shelf tool rather than as a node: oceans,
    quick sims, rigging setups. A full install ships around 8,000 of them, so
    always filter.

    Args:
        filter: Substring matched against name, label and keywords.
        limit: Maximum tools to return.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"limit": limit}
    if filter is not None:
        params["filter"] = filter
    return await bridge.execute("shelf.list_shelf_tools", params)


@mcp.tool()
async def get_shelf_tool_script(ctx: Context, tool_name: str) -> dict:
    """Read the script a shelf tool runs, plus its help and imports.

    This is how you learn SideFX's own recipe instead of reinventing it. Most
    scripts are two or three lines calling a worker in a toolutils module, and the
    reported imports name exactly what to read next.

    Args:
        tool_name: Internal tool name, from list_shelf_tools.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("shelf.get_shelf_tool_script", {"tool_name": tool_name})


@mcp.tool()
async def run_shelf_tool(
    ctx: Context,
    tool_name: str,
    kwargs: dict[str, Any] | None = None,
    parent_path: str | None = None,
) -> dict:
    """Run a shelf tool and report the nodes it created.

    Most shelf tools call hou.ui, because Houdini invokes them from a click, so
    they work in a graphical session and fail with a clear message in a headless
    one. When that happens, read the recipe with get_shelf_tool_script and build
    the network directly.

    Args:
        tool_name: Internal tool name, from list_shelf_tools.
        kwargs: Overrides merged into the synthetic kwargs the script reads.
        parent_path: An extra network to watch for new nodes. /obj, /stage,
            /out, /mat and /img are always watched, because a shelf tool is
            free to build in more than one of them: largeOcean creates both
            a geo in /obj and a LOP in /stage.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"tool_name": tool_name}
    if kwargs is not None:
        params["kwargs"] = kwargs
    if parent_path is not None:
        params["parent_path"] = parent_path
    return await bridge.execute("shelf.run_shelf_tool", params)
