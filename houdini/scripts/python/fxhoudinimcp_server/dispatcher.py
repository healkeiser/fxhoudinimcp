"""Main-thread dispatch mechanism for executing hou.* calls safely.

Houdini requires all hou.* API calls to run on the main thread.
hwebserver handlers run on worker threads, so we use
hdefereval.executeInMainThreadWithResult() to marshal calls
to the main thread and block until they complete.
"""

from __future__ import annotations

# Built-in
import logging
import threading
import time
import traceback
from collections.abc import Callable
from typing import Any

# Third-party (hdefereval is only available in graphical Houdini sessions)
try:
    import hdefereval

    HAS_HDEFEREVAL = True
except ImportError:
    HAS_HDEFEREVAL = False

from fxhoudinimcp_server.errors import readable_message

logger = logging.getLogger(__name__)

###### Constants

_COMMAND_TIMEOUT = 120  # seconds

# Registry of command name -> handler function
_handler_registry: dict[str, Callable] = {}


def register_handler(command: str, handler: Callable) -> None:
    """Register a handler function for a command name.

    Args:
        command: Dotted command name (e.g. "scene.get_scene_info")
        handler: Function to call with **params
    """
    _handler_registry[command] = handler


def list_commands() -> list[str]:
    """Return all registered command names."""
    return sorted(_handler_registry.keys())


def _argument_error(command: str, handler: Callable, exc: TypeError) -> str | None:
    """Restate a signature mismatch in terms of the command and its arguments.

    Returns None when the TypeError came from inside the handler rather than from
    calling it, in which case the original error is the honest one to report --
    rewriting it would hide a genuine bug behind a message about arguments.
    """
    text = str(exc)
    if not any(
        marker in text
        for marker in (
            "required positional argument",
            "unexpected keyword argument",
            "required keyword-only argument",
            "positional arguments but",
        )
    ):
        return None
    # The mismatch must be about THIS handler, not some function it called.
    name = getattr(handler, "__name__", "")
    if name and f"{name}()" not in text:
        return None

    import inspect

    required: list[str] = []
    optional: list[str] = []
    try:
        for parameter in inspect.signature(handler).parameters.values():
            if parameter.kind in (parameter.VAR_KEYWORD, parameter.VAR_POSITIONAL):
                continue
            (required if parameter.default is parameter.empty else optional).append(parameter.name)
    except (TypeError, ValueError):
        return None

    detail = text.split("() ", 1)[-1]
    return (
        f"{command} was called with the wrong arguments ({detail}). "
        f"Required: {required or 'none'}. Optional: {optional or 'none'}."
    )


def dispatch(command: str, params: dict[str, Any]) -> dict[str, Any]:
    """Execute a command on the main thread and return the result.

    This is called from hwebserver worker threads. It uses
    hdefereval.executeInMainThreadWithResult() to safely execute
    hou.* calls on the main thread.

    Args:
        command: The command name to execute
        params: Parameters to pass to the handler

    Returns:
        A response dict with "status", "data"/"error", and "timing_ms" keys.
    """
    handler = _handler_registry.get(command)
    if handler is None:
        return {
            "status": "error",
            "error": {
                "code": "UNKNOWN_COMMAND",
                "message": f"No handler registered for command: {command}",
                "available_commands": list_commands(),
            },
        }

    start_time = time.time()

    def _execute():
        try:
            result = handler(**params)
            return {"status": "success", "data": result}
        except TypeError as e:
            # A signature mismatch is Python talking about itself: "log_status()
            # missing 1 required positional argument: 'message'" names an internal
            # function, not the command, and does not say what the command accepts.
            # The MCP tool schema catches this for compliant clients; anything
            # reaching the HTTP bridge directly gets a usable answer instead.
            argument_error = _argument_error(command, handler, e)
            if argument_error is None:
                raise
            return {
                "status": "error",
                "error": {
                    "code": "BAD_ARGUMENTS",
                    "message": argument_error,
                    "traceback": traceback.format_exc(),
                },
            }
        except Exception as e:
            return {
                "status": "error",
                "error": {
                    "code": type(e).__name__,
                    "message": readable_message(e),
                    "traceback": traceback.format_exc(),
                },
            }

    try:
        if HAS_HDEFEREVAL:
            # Run hdefereval call in a worker thread so we can enforce a timeout
            container: dict[str, Any] = {}

            def _run():
                try:
                    container["result"] = hdefereval.executeInMainThreadWithResult(_execute)
                except Exception as exc:
                    container["error"] = exc
                    container["tb"] = traceback.format_exc()

            worker = threading.Thread(target=_run, daemon=True)
            worker.start()
            worker.join(timeout=_COMMAND_TIMEOUT)

            if worker.is_alive():
                logger.error("Command '%s' timed out after %s seconds", command, _COMMAND_TIMEOUT)
                result = {
                    "status": "error",
                    "error": {
                        "code": "TIMEOUT",
                        "message": (
                            f"Command '{command}' did not complete within "
                            f"{_COMMAND_TIMEOUT} seconds."
                        ),
                    },
                }
            elif "error" in container:
                result = {
                    "status": "error",
                    "error": {
                        "code": "DISPATCH_ERROR",
                        "message": f"Failed to dispatch to main thread: {container['error']}",
                        "traceback": container.get("tb", ""),
                    },
                }
            else:
                result = container["result"]
        else:
            # Fallback for hython (single-threaded, no hdefereval needed)
            result = _execute()
    except Exception as e:
        result = {
            "status": "error",
            "error": {
                "code": "DISPATCH_ERROR",
                "message": f"Failed to dispatch to main thread: {e}",
                "traceback": traceback.format_exc(),
            },
        }

    result["timing_ms"] = round((time.time() - start_time) * 1000, 2)
    return result
