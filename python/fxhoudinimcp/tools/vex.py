"""MCP tool wrappers for Houdini VEX operations.

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


@mcp.tool()
async def create_wrangle(
    ctx: Context,
    parent_path: str,
    vex_code: str,
    justification: str,
    run_over: str = "Points",
    name: str | None = None,
) -> dict:
    """Create an Attribute Wrangle node with VEX code.

    LAST RESORT. VEX is for attribute math that no node expresses —
    NEVER for modeling, scattering, copying, deforming, grouping, or
    randomizing, which all have dedicated nodes. Building geometry in a
    wrangle when a native node exists is a failure, not a shortcut.

    The justification parameter is mandatory: state which
    list_node_types searches you ran and why none of the results can do
    this. If you cannot write that sentence honestly, you have not
    checked — check first.

    Args:
        parent_path: Parent SOP network path.
        vex_code: VEX snippet to set.
        justification: Which native nodes you checked (the actual
            list_node_types filters used) and why none can express this
            logic.
        run_over: Element to run over ("Points", "Vertices", "Primitives", "Detail", "Numbers").
        name: Node name.
    """
    bridge = _get_bridge(ctx)
    params: dict = {
        "parent_path": parent_path,
        "vex_code": vex_code,
        "run_over": run_over,
    }
    if name is not None:
        params["name"] = name
    result = await bridge.execute("vex.create_wrangle", params)
    if isinstance(result, dict):
        result["justification"] = justification
    return result


@mcp.tool()
async def set_wrangle_code(
    ctx: Context,
    node_path: str,
    vex_code: str | None = None,
    edits: list[dict[str, str]] | None = None,
) -> dict:
    """Set VEX code on an existing Attribute Wrangle node — whole, or in part.

    For one block of a long snippet, pass `edits` instead of `vex_code`:
    [{"old": "<exact text now in the snippet>", "new": "<its replacement>"}],
    applied in order; each `old` must occur exactly once (add a neighbouring
    line to make it unique), and one bad edit writes nothing. The reply then
    gives `edits_applied` (line range and new text of each) instead of the
    whole code.

    Args:
        node_path: Path to the wrangle node.
        vex_code: VEX snippet to set.
        edits: Exact replacements in the current snippet, instead of vex_code.
    """
    bridge = _get_bridge(ctx)
    payload: dict[str, Any] = {"node_path": node_path}
    if vex_code is not None:
        payload["vex_code"] = vex_code
    if edits is not None:
        payload["edits"] = edits
    return await bridge.execute("vex.set_wrangle_code", payload)


@mcp.tool()
async def get_wrangle_code(ctx: Context, node_path: str) -> dict:
    """Read the VEX code from an Attribute Wrangle node.

    Args:
        node_path: Path to the wrangle node.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("vex.get_wrangle_code", {"node_path": node_path})


@mcp.tool()
async def create_vex_expression(
    ctx: Context,
    node_path: str,
    parm_name: str,
    vex_code: str,
) -> dict:
    """Set an HScript expression on a parameter, evaluated before it is kept.

    Parameters cannot run VEX: attribute @ syntax is refused with a pointer to
    create_wrangle. An expression that does not evaluate is not kept.

    Args:
        node_path: Path to the node.
        parm_name: Parameter name.
        vex_code: Expression code, in HScript syntax.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "vex.create_vex_expression",
        {
            "node_path": node_path,
            "parm_name": parm_name,
            "vex_code": vex_code,
        },
    )


@mcp.tool()
async def validate_vex(ctx: Context, node_path: str) -> dict:
    """Validate VEX code by cooking the node and checking for errors.

    Args:
        node_path: Path to the wrangle node.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("vex.validate_vex", {"node_path": node_path})
