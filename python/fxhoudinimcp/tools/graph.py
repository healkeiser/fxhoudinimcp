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

    Each node spec dict supports exactly these keys; an unknown one (in a
    spec or in an input entry) is a validation error with a did-you-mean,
    never a silently dropped request:
        type (required), name, parms (lists set whole parm tuples; a value
        written {"expr": "ch('../x')"} is set as an expression, with an
        optional "language": "hscript" | "python", also as one component
        of a list: "t": [{"expr": "$F"}, 0, 0]), expressions (or its
        alias exprs: a block of parm name -> expression), inputs (list of
        source names — earlier spec names, existing children, or absolute
        paths; or dicts with index or input_name / source / source_output,
        where input_name is a connector name or label as get_node_card
        lists them and source_output an output index or name ("v", "P");
        or {"indirect_input": n} to wire from connector n of
        the parent subnet itself), flags (display/render/bypass/template),
        color [r,g,b], comment, override_expression, run_callbacks. Parms
        are written in the order given.

    A string aimed at a numeric parameter is caught during validation and
    answered with the {"expr": ...} spelling, instead of failing mid-build
    and rolling the whole graph back.

    A literal in parms does not replace an expression the parm already
    holds (a Ray SOP ships dir = @N.x): the dry run lists such parms in
    `expressions_in_the_way`, the build reports `expressions_kept` and a
    `warning`. "override_expression": true on the spec clears them first.

    Display: in a network that was empty, the last node gets the display
    flag unless a spec sets one. A display flag asked of a node that has
    none (a usdrender_rop) goes to its nearest input that has one, listed in
    `display_set_upstream`.

    A LOCKED parm (karmarendersettings resolutiony while res_mode is
    autoheight) takes nothing; such a spec is refused at validation, nothing
    built, with `locked_parms` naming the menu whose callback sets the lock.
    Houdini runs callbacks only from the UI: "run_callbacks": true on the spec
    runs each parm's callback after its write, so {"res_mode": "manual",
    "resolution": [1920, 1080]} builds. Validation replays a spec on a probe,
    its callbacks included, only when it writes a parm a fresh node locks.

    There is no "children" key: build the subnet, then call build_network
    again with the subnet as parent_path.

    Nodes built inside a DOP network come with `simulation_cache`: the
    network to pass to reset_simulation before reading a frame it cooked.

    Args:
        parent_path: Network to build inside (e.g. "/obj/geo1"). A missing
            parent directly under /obj is created, as the container the
            specs' context needs (geo for SOPs, lopnet for LOPs), and
            removed again if the build fails; a dry run reports it as
            `would_create_parent`.
        nodes: Ordered node specs (see above).
        dry_run: Validate the whole spec without creating anything.
        layout: Also lay out the parent network afterwards (default True;
            honoured only when auto-layout is enabled). The nodes this call
            creates are always positioned, each relative to its inputs,
            regardless of this flag; nodes that already existed keep their
            exact positions, so building into a hand-arranged network is safe.
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
async def verify_network(ctx: Context, parent_path: str, force_cook: bool = False) -> dict:
    """Inspect every node in a network at once — errors, warnings, flags,
    and the display node's cooked geometry counts.

    Call this after building or modifying a network, the way an artist
    middle-clicks nodes: if `healthy` is false or `error_nodes` is
    non-empty, fix those nodes before telling the user anything is done.
    Each node lists `errors`, `warnings`, `bypassed` and `display` only when
    it has them; absent means none. For a LOP network the evidence is the
    stage (prims, cameras, lights, gprims without a material), for a COP
    network the image layer (resolution, channel ranges).

    A node's errors are its LAST cook's verdict. A node that nothing has
    cooked since its cause was fixed is reported `stale` and listed in
    `stale_error_nodes`; pass force_cook=True to recook before judging.
    The default cooks only the display node, so a heavy scene is left alone.

    Args:
        parent_path: Network to verify (e.g. "/obj/geo1").
        force_cook: Cook the display node with force and recook every node
            that has errors, so the verdict is about the network as it is now.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "graph.verify_network", {"parent_path": parent_path, "force_cook": force_cook}
    )


@mcp.tool()
async def get_node_card(
    ctx: Context,
    node_type: str,
    context: str = "Sop",
    parm_filter: str | None = None,
    include_help: bool | None = None,
) -> dict:
    """Get the authoritative documentation card for a node type, straight
    from the running Houdini: connectors in order (`inputs` / `outputs`
    with index, name and label — the index of `texcoord` on mtlximage
    lives here), real parameter names/defaults/menus, and the node's own
    shipped help text. Connectors are read off a probe node the first time
    a type is asked for in a session (no undo entry, creation scripts not
    run); `connectors_probed: false` with `connectors_note` means they could
    not be read, not that the type has none. A menu whose items a script
    computes (`loadtype` on filemerge::2.0) is read off the same probe and
    marked `menu_source: "generator"`, with the script in `menu_generator`.
    A radio folder set (`switcher1` on an Add SOP: By Pattern / By Group)
    is listed as a `FolderSet` parm whose menu is its folders; a default
    that is an expression (`$F` on timeshift's `frame`) is in
    `default_expression`; a VOP's outputs carry their `data_type`.

    Use this BEFORE setting parameters on a node type you have not used
    in this session — never guess parameter names. Unversioned names
    resolve to the newest version.

    Args:
        node_type: Type name (e.g. "scatter", "rbdbulletsolver").
        context: Category — "Sop", "Lop", "Vop" (MaterialX and other shader
            nodes inside a material network), "Dop", "Cop", "Chop", "Top",
            "Object", "Driver"; also "Cop2", "Shop", "VopNet".
        parm_filter: Substring filter for the parameter list.
        include_help: The node's help text (about 4 KB). Default: included
            for a whole card, left out when parm_filter asks for specific
            parameters. Pass True or False to decide.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"node_type": node_type, "context": context}
    if parm_filter is not None:
        params["parm_filter"] = parm_filter
    # A filtered card is a question about a few parameters; the help text was
    # 5 of its 7 KB on a Pyro Solver.
    if include_help is None:
        include_help = parm_filter is None
    if not include_help:
        params["include_help"] = False
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
    time, errors, counts, bounding box and attribute aggregates come back in
    ONE round trip instead of one per frame. `static: true` means counts and
    bounds never changed over the range: the node cooks but does nothing.
    Past 25 frames the rows are 25 evenly spaced frames plus every frame with
    an error or warning (`frames_shown`); totals, `static` and
    `slowest_frame` still cover every frame.

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
