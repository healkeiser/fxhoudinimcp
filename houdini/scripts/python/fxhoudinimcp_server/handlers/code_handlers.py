"""Houdini-side handlers for code execution operations.

Provides 4 command handlers for executing Python code, HScript commands,
evaluating expressions, and reading environment variables within Houdini.
"""

from __future__ import annotations

# Built-in
import io
import os
import sys
import traceback
from typing import Any

# Third-party
import hou

# Internal
from fxhoudinimcp_server.dispatcher import register_handler
from fxhoudinimcp_server.errors import as_text

###### Constants

_MAX_CAPTURE_BYTES = 100 * 1024  # 100 KB


###### Helpers


def _truncate_output(text: str) -> str:
    """Truncate captured output to _MAX_CAPTURE_BYTES if it exceeds the limit."""
    if len(text) > _MAX_CAPTURE_BYTES:
        return text[:_MAX_CAPTURE_BYTES] + "\n[truncated]"
    return text


def _serialize_result(value: Any) -> Any:
    """Convert arbitrary Python objects to JSON-safe types."""
    if value is None:
        return None
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (list, tuple)):
        return [_serialize_result(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _serialize_result(v) for k, v in value.items()}
    # Fallback: stringify
    return str(value)


###### Handler: code.execute_python


def _execute_python(code: str, return_expression: str | None = None, **_: Any) -> dict[str, Any]:
    """Execute arbitrary Python code inside Houdini's interpreter.

    The code is executed via `exec()` in a namespace that has `hou`
    pre-imported.  If *return_expression* is given it is evaluated with
    `eval()` in the same namespace after execution, and its result is
    returned.

    stdout and stderr are captured and included in the response so the
    caller can see print() output and any warnings.
    """
    namespace: dict[str, Any] = {"hou": hou}

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = stdout_buf, stderr_buf

    exec_error: str | None = None
    try:
        exec(code, namespace)  # noqa: S102
    except Exception:
        exec_error = traceback.format_exc()
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr

    stdout_text = _truncate_output(stdout_buf.getvalue())
    stderr_text = _truncate_output(stderr_buf.getvalue())

    if exec_error:
        response: dict[str, Any] = {
            # "executed" predates the server-wide "success" convention. Code that
            # raised is a failure, and a caller checking the usual key got None --
            # falsy, but not False, and easy to read as "no opinion".
            "success": False,
            "executed": False,
            "error": exec_error,
        }
        if stdout_text:
            response["stdout"] = stdout_text
        if stderr_text:
            response["stderr"] = stderr_text
        return response

    result: Any = None
    eval_error: str | None = None
    if return_expression is not None:
        try:
            result = eval(return_expression, namespace)  # noqa: S307
        except Exception:
            eval_error = traceback.format_exc()

    if eval_error:
        response = {
            # The code ran, but the expression the caller asked to evaluate did
            # not, so the answer they wanted is missing.
            "success": False,
            "executed": True,
            "return_value": None,
            "eval_error": eval_error,
        }
        if stdout_text:
            response["stdout"] = stdout_text
        if stderr_text:
            response["stderr"] = stderr_text
        return response

    response = {
        "success": True,
        "executed": True,
        "return_value": _serialize_result(result),
    }
    if stdout_text:
        response["stdout"] = stdout_text
    if stderr_text:
        response["stderr"] = stderr_text
    return response


register_handler("code.execute_python", _execute_python)


###### Handler: code.execute_hscript


def _execute_hscript(command: str, **_: Any) -> dict[str, Any]:
    """Execute an HScript command and return its output."""
    # A non-string reached the SWIG binding and came back as "in method
    # 'hscript', argument 1 of type 'char const *'".
    output, errors = hou.hscript(as_text(command, "command"))

    return {
        "output": _truncate_output(output) if output else output,
        "errors": _truncate_output(errors) if errors else None,
    }


register_handler("code.execute_hscript", _execute_hscript)


###### Handler: code.evaluate_expression


def _evaluate_expression(expression: str, language: str = "hscript", **_: Any) -> dict[str, Any]:
    """Evaluate an expression and return its result.

    Supports both HScript expressions (via `hou.hscriptExpression()`)
    and Python expressions (via `eval()`).
    """
    if language.lower() == "python":
        namespace: dict[str, Any] = {"hou": hou}
        result = eval(expression, namespace)  # noqa: S307
    else:
        result = hou.hscriptExpression(expression)

    return {
        "expression": expression,
        "language": language,
        "result": _serialize_result(result),
    }


register_handler("code.evaluate_expression", _evaluate_expression)


###### Handler: code.get_env_variable


def _get_env_variable(var_name: str, **_: Any) -> dict[str, Any]:
    """Get a Houdini environment variable."""
    value = hou.getenv(as_text(var_name, "var_name"))

    return {
        "var_name": var_name,
        "value": value,
        "exists": value is not None,
    }


register_handler("code.get_env_variable", _get_env_variable)


###### code.get_file_references


def _get_file_references(include_missing_only: bool = False, **_: Any) -> dict[str, Any]:
    """Every file path the scene references, with the parameter that holds it.

    Args:
        include_missing_only: Only report paths that do not exist on disk.
    """
    references = []
    for parm, path in hou.fileReferences():
        if not path:
            continue
        expanded = hou.text.expandString(path)
        exists = os.path.exists(expanded) if expanded else False
        if include_missing_only and exists:
            continue
        references.append(
            {
                "parm": parm.path() if parm is not None else None,
                "path": path,
                "expanded": expanded,
                "exists": exists,
            }
        )
    return {"count": len(references), "references": references}


register_handler("code.get_file_references", _get_file_references)


###### code.set_update_mode

_UPDATE_MODES = {
    "auto": hou.updateMode.AutoUpdate,
    "on_mouse_up": hou.updateMode.OnMouseUp,
    "manual": hou.updateMode.Manual,
}


def _set_update_mode(mode: str | None = None, **_: Any) -> dict[str, Any]:
    """Set (or, with no mode, read) Houdini's cook update mode.

    Switching to ``manual`` before a long build stops every parameter change
    from re-cooking the network; switch back to ``auto`` afterwards.

    Args:
        mode: "auto", "on_mouse_up" or "manual". Omit to read the current mode.
    """
    if mode is not None:
        key = as_text(mode, "mode").strip().lower()
        if key not in _UPDATE_MODES:
            raise ValueError(
                f"Unknown update mode '{mode}'. Use one of: {', '.join(_UPDATE_MODES)}."
            )
        hou.setUpdateMode(_UPDATE_MODES[key])
    current = hou.updateModeSetting()
    name = next((k for k, v in _UPDATE_MODES.items() if v == current), str(current))
    return {"success": True, "mode": name}


register_handler("code.set_update_mode", _set_update_mode)
