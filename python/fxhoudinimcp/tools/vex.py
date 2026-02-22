"""MCP tool wrappers for Houdini VEX operations.

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
async def create_wrangle(
    ctx: Context,
    parent_path: str,
    vex_code: str,
    run_over: str = "Points",
    name: Optional[str] = None,
) -> dict:
    """Create an Attribute Wrangle node with VEX code.

    Args:
        parent_path: Parent SOP network path.
        vex_code: VEX snippet to set.
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
    return await bridge.execute("vex.create_wrangle", params)


@mcp.tool()
async def set_wrangle_code(
    ctx: Context,
    node_path: str,
    vex_code: str,
) -> dict:
    """Set VEX code on an existing Attribute Wrangle node.

    Args:
        node_path: Path to the wrangle node.
        vex_code: VEX snippet to set.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "vex.set_wrangle_code",
        {
            "node_path": node_path,
            "vex_code": vex_code,
        },
    )


@mcp.tool()
async def get_wrangle_code(ctx: Context, node_path: str) -> dict:
    """Read the VEX code from an Attribute Wrangle node.

    Args:
        node_path: Path to the wrangle node.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "vex.get_wrangle_code", {"node_path": node_path}
    )


@mcp.tool()
async def create_vex_expression(
    ctx: Context,
    node_path: str,
    parm_name: str,
    vex_code: str,
) -> dict:
    """Set a VEX expression on a parameter.

    Args:
        node_path: Path to the node.
        parm_name: Parameter name.
        vex_code: VEX expression code.
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
