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
    """Get the current value and metadata of a Houdini parameter.

    Returns the evaluated value, raw value, any expression, keyframe count,
    lock state, whether the parameter is at its default, and the parameter type.

    Args:
        node_path: Absolute Houdini node path (e.g. "/obj/geo1/transform1").
        parm_name: Name of the parameter (e.g. "tx", "divisions").
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
    """Set a single Houdini parameter value.

    The value type is auto-detected (int, float, string, etc.) and applied
    to the parameter.

    Args:
        node_path: Absolute Houdini node path.
        parm_name: Name of the parameter to set.
        value: The new value (int, float, string, bool, or list for tuples).
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
    """Batch-set multiple parameters on a single Houdini node.

    More efficient than calling set_parameter repeatedly. Reports individual
    successes and failures.

    Args:
        node_path: Absolute Houdini node path.
        params: Mapping of parameter names to their new values.
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
    """Get the full template schema for parameter(s) on a Houdini node.

    Returns type, range, menu items, default value, conditionals, and tags.
    If parm_name is omitted, returns schema information for every parameter
    on the node.

    Args:
        node_path: Absolute Houdini node path.
        parm_name: Optional parameter name. If None, returns all parameters.
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
    """Set an expression on a Houdini parameter.

    Args:
        node_path: Absolute Houdini node path.
        parm_name: Name of the parameter.
        expression: The expression string (e.g. "$F", "ch('../tx')").
        language: Expression language, "hscript" (default) or "python".
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
    """Get the current expression on a Houdini parameter.

    Returns the expression string and its language, or null values if the
    parameter has no expression.

    Args:
        node_path: Absolute Houdini node path.
        parm_name: Name of the parameter.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "parameters.get_expression",
        {"node_path": node_path, "parm_name": parm_name},
    )


###### parameters.revert_parameter

@mcp.tool()
async def revert_parameter(ctx: Context, node_path: str, parm_name: str) -> dict:
    """Revert a Houdini parameter to its default value.

    Removes any expression or keyframes and restores the factory default.

    Args:
        node_path: Absolute Houdini node path.
        parm_name: Name of the parameter to revert.
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

    The destination parameter will reference the source parameter via
    an HScript ch() expression.

    Args:
        source_path: Absolute path of the source node.
        source_parm: Parameter name on the source node.
        dest_path: Absolute path of the destination node.
        dest_parm: Parameter name on the destination node.
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
    """Lock or unlock a Houdini parameter.

    Locked parameters cannot be edited by users in the UI.

    Args:
        node_path: Absolute Houdini node path.
        parm_name: Name of the parameter.
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
    """Add a custom spare parameter to a Houdini node.

    Supported parameter types: "float", "int", "string", "toggle", "menu".

    Args:
        node_path: Absolute Houdini node path.
        parm_name: Internal name for the new parameter.
        parm_type: Parameter type (float, int, string, toggle, menu).
        label: Human-readable label shown in the UI.
        default_value: Default value. For float/int can be a number or list.
                       For toggle, a bool. For menu, a list of menu item strings.
        min_val: Optional minimum value (float/int types only).
        max_val: Optional maximum value (float/int types only).
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
