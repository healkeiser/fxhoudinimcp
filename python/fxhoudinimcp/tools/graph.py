"""MCP tools for graph-level intelligence.

Atomic network building with validation, network verification, node
documentation cards, and cook profiling — the senior-artist toolset.
"""

from __future__ import annotations

# Built-in
from typing import Any

# Third-party
from fxhoudinimcp._sdk import Context

# Internal
from fxhoudinimcp.server import _get_bridge, mcp


@mcp.tool()
async def build_network(
    ctx: Context,
    parent_path: str,
    nodes: list[dict[str, Any]],
    dry_run: bool = False,
    layout: bool = True,
) -> dict:
    """Build a whole node network in ONE atomic call — the PREFERRED way
    to construct anything of 3+ nodes (massively faster than node-by-node
    calls, and either the whole network builds or nothing does).

    Every node type, parameter name, and input reference is validated
    against the running Houdini BEFORE anything is created; errors come
    back with did-you-mean suggestions. Use dry_run=True to prove a plan
    when using unfamiliar node types. The result includes cooked
    evidence: per-node errors and the display node's geometry counts —
    read them instead of assuming success.

    Each node spec dict supports:
        type (required), name, parms (lists set whole parm tuples),
        inputs (list of source names — earlier spec names, existing
        children, or absolute paths; or dicts with index/source/
        source_output), flags (display/render/bypass/template),
        color [r,g,b], comment.

    Args:
        parent_path: Network to build inside (e.g. "/obj/geo1").
        nodes: Ordered node specs (see above).
        dry_run: Validate the whole spec without creating anything.
        layout: Lay out the parent network afterwards.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "graph.build_network",
        {
            "parent_path": parent_path,
            "nodes": nodes,
            "dry_run": dry_run,
            "layout": layout,
        },
    )


@mcp.tool()
async def verify_network(ctx: Context, parent_path: str) -> dict:
    """Inspect every node in a network at once — errors, warnings, flags,
    and the display node's cooked geometry counts.

    Call this after building or modifying a network, the way an artist
    middle-clicks nodes: if `healthy` is false or `error_nodes` is
    non-empty, fix those nodes before telling the user anything is done.

    Args:
        parent_path: Network to verify (e.g. "/obj/geo1").
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("graph.verify_network", {"parent_path": parent_path})


@mcp.tool()
async def get_node_card(
    ctx: Context,
    node_type: str,
    context: str = "Sop",
    parm_filter: str | None = None,
) -> dict:
    """Get the authoritative documentation card for a node type, straight
    from the running Houdini: real connector labels, real parameter
    names/defaults/menus, and the node's own shipped help text.

    Use this BEFORE setting parameters on a node type you have not used
    in this session — never guess parameter names. Unversioned names
    resolve to the newest version.

    Args:
        node_type: Type name (e.g. "scatter", "rbdbulletsolver").
        context: Category — "Sop", "Lop", "Dop", "Cop", "Chop", "Top",
            "Object", "Driver".
        parm_filter: Substring filter for the parameter list.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"node_type": node_type, "context": context}
    if parm_filter is not None:
        params["parm_filter"] = parm_filter
    return await bridge.execute("graph.get_node_card", params)


@mcp.tool()
async def find_expensive_nodes(
    ctx: Context,
    root_path: str = "/",
    frame: float | None = None,
    limit: int = 15,
) -> dict:
    """Profile cooking and rank the most expensive nodes — how a senior
    artist finds the slow node instead of guessing.

    Records a performance-monitor profile while force-cooking the
    display outputs under root_path. cook_ms is cumulative (parents
    include their children), so compare siblings to locate the hotspot.

    Args:
        root_path: Network to profile (a geo container, or "/" broadly).
        frame: Optionally jump to this frame before cooking.
        limit: Max nodes to return.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"root_path": root_path, "limit": limit}
    if frame is not None:
        params["frame"] = frame
    return await bridge.execute("graph.find_expensive_nodes", params)


@mcp.tool()
async def cook_frame_range(
    ctx: Context,
    node_path: str,
    start: float | None = None,
    end: float | None = None,
    step: float = 1.0,
    attribs: list[str] | None = None,
    volumes: bool = False,
) -> dict:
    """Cook a node frame by frame and report what changed on each frame.

    This is how you advance a sequential solver and how you prove a simulation
    is doing something. Frames are cooked in order, so a SOP solver, a DOP
    network or an animated chain all accumulate correctly, and per-frame cook
    time, errors, counts and attribute aggregates come back in ONE round trip
    instead of one per frame.

    Prefer this over set_frame in a loop, and over stepping by hand: a 100-frame
    check is one call rather than 100. The frame is left where the cook ended,
    ready to screenshot.

    Args:
        node_path: Node to cook; its output is what gets measured.
        start: First frame. Defaults to the playbar start.
        end: Last frame, inclusive. Defaults to the playbar end.
        step: Frame increment. Keep at 1.0 for any solver, since skipping frames
            gives it a discontinuous time step and invalid results.
        attribs: Point attributes to aggregate per frame (min/max/mean/sum).
        volumes: Also report per-volume name, resolution and value range.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {
        "node_path": node_path,
        "step": step,
        "volumes": volumes,
    }
    if start is not None:
        params["start"] = start
    if end is not None:
        params["end"] = end
    if attribs is not None:
        params["attribs"] = attribs
    return await bridge.execute("graph.cook_frame_range", params)


@mcp.tool()
async def get_cook_status(ctx: Context, node_path: str = "/obj") -> dict:
    """Whether a node has cooked, how often, and whether it is time dependent.

    Note the shape of the limitation: every command runs on Houdini's main
    thread, so a long cook blocks the bridge and cannot be polled while it runs.
    This answers the after-the-fact question instead -- did it really recook, is
    it time dependent, did it end in error -- plus whether the hip has unsaved
    changes. For asynchronous work use a ROP's background execution and
    get_render_progress.

    Args:
        node_path: Node to report on.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("graph.get_cook_status", {"node_path": node_path})
