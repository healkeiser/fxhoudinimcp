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
    """Execute arbitrary Python code inside Houdini's Python interpreter.

    The code runs via exec() in a namespace with ``hou`` pre-imported.
    If return_expression is provided, it is evaluated after execution and
    its result is included in the response.

    stdout and stderr from print() calls are captured and returned.
    Use print() liberally in your code to provide progress feedback.

    Args:
        code: Python source code to execute.
        return_expression: Optional Python expression to evaluate after
                           executing the code and return its result.
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

    Returns the command output and any error messages.

    Args:
        command: The HScript command string to execute (e.g. "opparm /obj/geo1 tx 5").
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("code.execute_hscript", {"command": command})


###### code.evaluate_expression

@mcp.tool()
async def evaluate_expression(
    ctx: Context, expression: str, language: str = "hscript"
) -> dict:
    """Evaluate an expression in Houdini and return its result.

    Supports both HScript expressions (using hou.hscriptExpression) and
    Python expressions (using eval).

    Args:
        expression: The expression string to evaluate.
        language: Expression language, "hscript" (default) or "python".
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

    Reads the variable via hou.getenv(). Returns the value and whether
    the variable exists.

    Args:
        var_name: Name of the environment variable (e.g. "HIP", "JOB", "HOUDINI_PATH").
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("code.get_env_variable", {"var_name": var_name})
