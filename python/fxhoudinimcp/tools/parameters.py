"""MCP tools for Houdini parameter operations.

Exposes 10 tools covering parameter get/set, expressions, channel
references, locking, schema inspection, and spare parameter creation.
"""

from __future__ import annotations

# Built-in
from typing import Any

# Third-party
from mcp.server.fastmcp import Context

# Internal
from fxhoudinimcp.server import mcp, _get_bridge


###### parameters.get_parameter


@mcp.tool()
async def get_parameter(ctx: Context, node_path: str, parm_name: str) -> dict:
    """Get the value and metadata of a parameter.

    Args:
        node_path: Node path.
        parm_name: Parameter name.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "parameters.get_parameter",
        {"node_path": node_path, "parm_name": parm_name},
    )


###### parameters.set_parameter


@mcp.tool()
async def set_parameter(
    ctx: Context, node_path: str, parm_name: str, value: Any
) -> dict:
    """Set a parameter value.

    Args:
        node_path: Node path.
        parm_name: Parameter name.
        value: New value (int, float, string, bool, or list).
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "parameters.set_parameter",
        {"node_path": node_path, "parm_name": parm_name, "value": value},
    )


###### parameters.set_parameters


@mcp.tool()
async def set_parameters(
    ctx: Context, node_path: str, params: dict[str, Any]
) -> dict:
    """Batch-set multiple parameters on a node.

    Args:
        node_path: Node path.
        params: Mapping of parameter names to values.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "parameters.set_parameters",
        {"node_path": node_path, "params": params},
    )


###### parameters.get_parameter_schema


@mcp.tool()
async def get_parameter_schema(
    ctx: Context, node_path: str, parm_name: str | None = None
) -> dict:
    """Get the template schema for parameter(s) on a node.

    Args:
        node_path: Node path.
        parm_name: Parameter name. If None, returns all parameters.
    """
    bridge = _get_bridge(ctx)
    payload: dict[str, Any] = {"node_path": node_path}
    if parm_name is not None:
        payload["parm_name"] = parm_name
    return await bridge.execute("parameters.get_parameter_schema", payload)


###### parameters.set_expression


@mcp.tool()
async def set_expression(
    ctx: Context,
    node_path: str,
    parm_name: str,
    expression: str,
    language: str = "hscript",
) -> dict:
    """Set an expression on a parameter.

    Args:
        node_path: Node path.
        parm_name: Parameter name.
        expression: Expression string.
        language: "hscript" (default) or "python".
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "parameters.set_expression",
        {
            "node_path": node_path,
            "parm_name": parm_name,
            "expression": expression,
            "language": language,
        },
    )


###### parameters.get_expression


@mcp.tool()
async def get_expression(ctx: Context, node_path: str, parm_name: str) -> dict:
    """Get the expression on a parameter.

    Args:
        node_path: Node path.
        parm_name: Parameter name.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "parameters.get_expression",
        {"node_path": node_path, "parm_name": parm_name},
    )


###### parameters.revert_parameter


@mcp.tool()
async def revert_parameter(
    ctx: Context, node_path: str, parm_name: str
) -> dict:
    """Revert a parameter to its default value.

    Args:
        node_path: Node path.
        parm_name: Parameter name.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "parameters.revert_parameter",
        {"node_path": node_path, "parm_name": parm_name},
    )


###### parameters.link_parameters


@mcp.tool()
async def link_parameters(
    ctx: Context,
    source_path: str,
    source_parm: str,
    dest_path: str,
    dest_parm: str,
) -> dict:
    """Create a channel reference from one parameter to another.

    Args:
        source_path: Source node path.
        source_parm: Source parameter name.
        dest_path: Destination node path.
        dest_parm: Destination parameter name.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "parameters.link_parameters",
        {
            "source_path": source_path,
            "source_parm": source_parm,
            "dest_path": dest_path,
            "dest_parm": dest_parm,
        },
    )


###### parameters.lock_parameter


@mcp.tool()
async def lock_parameter(
    ctx: Context, node_path: str, parm_name: str, locked: bool
) -> dict:
    """Lock or unlock a parameter.

    Args:
        node_path: Node path.
        parm_name: Parameter name.
        locked: True to lock, False to unlock.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "parameters.lock_parameter",
        {"node_path": node_path, "parm_name": parm_name, "locked": locked},
    )


###### parameters.create_spare_parameter


@mcp.tool()
async def create_spare_parameter(
    ctx: Context,
    node_path: str,
    parm_name: str,
    parm_type: str,
    label: str,
    default_value: Any = None,
    min_val: float | None = None,
    max_val: float | None = None,
) -> dict:
    """Add a spare parameter to a node.

    Args:
        node_path: Node path.
        parm_name: Internal parameter name.
        parm_type: "float", "int", "string", "toggle", or "menu".
        label: UI label.
        default_value: Default value.
        min_val: Minimum value (float/int only).
        max_val: Maximum value (float/int only).
    """
    bridge = _get_bridge(ctx)
    payload: dict[str, Any] = {
        "node_path": node_path,
        "parm_name": parm_name,
        "parm_type": parm_type,
        "label": label,
    }
    if default_value is not None:
        payload["default_value"] = default_value
    if min_val is not None:
        payload["min_val"] = min_val
    if max_val is not None:
        payload["max_val"] = max_val
    return await bridge.execute("parameters.create_spare_parameter", payload)
