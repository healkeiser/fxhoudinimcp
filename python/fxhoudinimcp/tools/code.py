"""MCP tools for code execution inside Houdini.

Exposes 4 tools for running Python code, HScript commands, evaluating
expressions, and reading Houdini environment variables.
"""

from __future__ import annotations

# Built-in
from typing import Any

# Third-party
from mcp.server.fastmcp import Context

# Internal
from fxhoudinimcp.server import mcp, _get_bridge


###### code.execute_python


@mcp.tool()
async def execute_python(
    ctx: Context, code: str, return_expression: str | None = None
) -> dict:
    """Execute Python code inside Houdini's interpreter.

    Args:
        code: Python source code to execute.
        return_expression: Python expression to evaluate after execution.
    """
    bridge = _get_bridge(ctx)
    payload: dict[str, Any] = {"code": code}
    if return_expression is not None:
        payload["return_expression"] = return_expression
    return await bridge.execute("code.execute_python", payload)


###### code.execute_hscript


@mcp.tool()
async def execute_hscript(ctx: Context, command: str) -> dict:
    """Execute an HScript command in Houdini.

    Args:
        command: HScript command string to execute.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("code.execute_hscript", {"command": command})


###### code.evaluate_expression


@mcp.tool()
async def evaluate_expression(
    ctx: Context, expression: str, language: str = "hscript"
) -> dict:
    """Evaluate an expression in Houdini and return its result.

    Args:
        expression: Expression string to evaluate.
        language: Expression language, "hscript" or "python".
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "code.evaluate_expression",
        {"expression": expression, "language": language},
    )


###### code.get_env_variable


@mcp.tool()
async def get_env_variable(ctx: Context, var_name: str) -> dict:
    """Get a Houdini environment variable value.

    Args:
        var_name: Name of the environment variable.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("code.get_env_variable", {"var_name": var_name})
