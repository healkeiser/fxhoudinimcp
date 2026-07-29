"""MCP tools for Houdini's shipped documentation.

Search and retrieval over the manual that ships inside the RUNNING
Houdini install — always version-exact, available offline, and served
on demand so it costs no context until a question actually comes up.
"""

from __future__ import annotations

# Built-in
from typing import Any

# Third-party
from fxhoudinimcp._sdk import Context

# Internal
from fxhoudinimcp.server import _get_bridge, mcp


@mcp.tool()
async def search_help(
    ctx: Context,
    query: str,
    scope: str | None = None,
    limit: int = 10,
) -> dict:
    """Search the running Houdini's own documentation — concepts,
    workflows, VEX functions, expression functions, HOM API, and every
    effects manual SideFX ships. Version-exact, straight from the install.

    Use this BEFORE improvising: when unsure how a workflow is meant to
    be done ("pyro shaping", "vellum constraints"), what a VEX or
    expression function does, or what a Solaris/TOPs concept means.
    Follow up with get_help_page on a result path.

    Args:
        query: Search words (all must match a page).
        scope: Optional corpus, named after the archive. Every help
            archive in the install is searchable, which on a full 22.0 is
            47 of them. The ones worth knowing by name: "nodes", "vex",
            "expressions", "hom", "solaris", "tops", plus the workflow
            manuals "pyro", "fluid", "vellum", "destruction", "grains",
            "crowds", "model", "copy", "assets", "render", "shade",
            "anim", "character", "ref", "shelf". Omit to search all.
        limit: Max results.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"query": query, "limit": limit}
    if scope is not None:
        params["scope"] = scope
    return await bridge.execute("help.search_help", params)


@mcp.tool()
async def get_help_page(ctx: Context, path: str) -> dict:
    """Fetch one page of Houdini's shipped documentation by path.

    Read the real reference instead of writing from memory — especially
    the VEX function pages (vex/functions/...) before any justified
    wrangle, and expression pages (expressions/...) before channel
    expressions.

    Args:
        path: As returned by search_help — e.g. "nodes/sop/scatter",
            "vex/functions/noise", "expressions/ch".
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("help.get_help_page", {"path": path})
