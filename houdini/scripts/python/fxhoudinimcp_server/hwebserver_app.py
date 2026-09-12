"""hwebserver endpoint registration for the FXHoudini-MCP plugin.

Registers API functions on Houdini's built-in HTTP server that the
external MCP server communicates with over HTTP.

Calling convention (JSON-encoded RPC):
    POST /api
    Body: json=["mcp.execute", [], {"command": "...", "params": {...}, "request_id": "..."}]

Responses are JSON-encoded here rather than left to hwebserver, so that a
value HOM cannot serialise degrades instead of collapsing into an opaque 500.
"""

from __future__ import annotations

# Built-in
import json
import os
import traceback

# Third-party
import hwebserver

# Internal
from fxhoudinimcp_server import dispatcher
from fxhoudinimcp_server.serialize import json_default

###### Registration


def _api_function(namespace: str):
    """Register an API function with hwebserver and keep the module attribute.

    hwebserver's module-level ``apiFunction`` decorator returns ``None``,
    because ``Server._apiFunction`` has no return statement. Registration
    itself works, but the decorated name would otherwise be bound to ``None``,
    which breaks anything that later imports the function -- including tests.

    Registration is thread-local: hwebserver keeps its ``Server`` in a
    ``threading.local()``, so the thread that imports this module must also be
    the thread that calls ``hwebserver.run()``. See startup.py.
    """

    def decorator(function):
        hwebserver.apiFunction(namespace=namespace)(function)
        return function

    return decorator


def _json_response(payload: dict) -> hwebserver.Response:
    """Encode *payload* as an HTTP JSON response.

    hwebserver would otherwise call ``json.dumps`` itself, from a place
    outside its own exception handling, so an unserialisable value there
    escapes as a bare HTTP 500 with no diagnostic. Encoding here lets a
    ``default=`` hook coerce stray HOM objects, and lets a genuine encoding
    failure come back as a readable error instead of a blank 500.
    """
    try:
        body = json.dumps(payload, default=json_default)
    except Exception as exc:
        body = json.dumps(
            {
                "status": "error",
                "error": {
                    "code": "SERIALIZATION_ERROR",
                    "message": (f"Result could not be JSON-encoded: {type(exc).__name__}: {exc}"),
                    "traceback": traceback.format_exc(),
                },
            }
        )
    return hwebserver.Response(body.encode("utf-8"), 200, "application/json")


###### Request origin guard

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


def _bare_host(host: str) -> str:
    """Strip a trailing :port from a Host value, IPv6 brackets included."""
    if host.startswith("["):
        return host.split("]", 1)[0] + "]"
    if host.count(":") == 1:
        return host.rsplit(":", 1)[0]
    return host


def _foreign_request_reason(request) -> str | None:
    """Why *request* must not reach the dispatcher, or None if it may.

    Binding to loopback keeps the LAN out but not the browser: a page you have
    open can POST a form-encoded body to 127.0.0.1 without any CORS preflight,
    and this endpoint runs arbitrary Python. Browsers always send ``Origin`` on
    a cross-origin POST and the MCP bridge never does, so the header alone is
    the tell. The ``Host`` check closes DNS rebinding, where a hostname the
    attacker controls resolves to 127.0.0.1: unless FXHOUDINIMCP_BIND was
    widened on purpose, only a loopback host name is served.
    """
    try:
        headers = {str(k).lower(): str(v) for k, v in dict(request.headers()).items()}
    except Exception:
        headers = {}
    if "origin" in headers:
        return (
            f"request carries an Origin header ({headers['origin']}); "
            f"browsers are not clients of this endpoint"
        )

    if os.environ.get("FXHOUDINIMCP_BIND", "127.0.0.1") != "127.0.0.1":
        return None
    try:
        host = str(request.host())
    except Exception:
        host = headers.get("host", "")
    bare = _bare_host(host).lower()
    if bare and bare not in _LOOPBACK_HOSTS:
        return f"Host header '{host}' is not loopback"
    return None


def _forbidden(reason: str) -> hwebserver.Response:
    body = json.dumps({"status": "error", "error": {"code": "FORBIDDEN_ORIGIN", "message": reason}})
    return hwebserver.Response(body.encode("utf-8"), 403, "application/json")


###### Endpoints


@_api_function("mcp")
def execute(request, command="", params=None, request_id=""):
    """Single entry point for all MCP tool calls.

    Args:
        request: hwebserver.Request (always first arg).
        command: Dotted command name (e.g. "scene.get_scene_info").
        params: Tool-specific parameters dict.
        request_id: Correlation ID echoed back in the response.
    """
    reason = _foreign_request_reason(request)
    if reason is not None:
        return _forbidden(reason)
    if params is None:
        params = {}

    result = dispatcher.dispatch(command, params)
    result["request_id"] = request_id
    return _json_response(result)


@_api_function("mcp")
def health(request):
    """Liveness check. Deliberately free of any hou.* access.

    This is what startup polls to decide the server is ready, and hwebserver
    serves it from a worker thread. Touching HOM here deadlocks a GUI session:
    the main thread is inside startup's readiness loop and so is not running
    Houdini's event loop, while HOM access from the worker needs precisely
    that main thread to make progress. Neither side can advance.

    Version comes from the environment for the same reason -- Houdini exports
    HOUDINI_VERSION, so reporting it costs no HOM call. Anything needing the
    scene itself belongs in session_info.
    """
    return {
        "status": "ok",
        "pid": os.getpid(),
        "houdini_version": os.environ.get("HOUDINI_VERSION", "unknown"),
    }


@_api_function("mcp")
def session_info(request):
    """Scene-level session details, marshalled to the main thread.

    Separate from health because this does touch HOM: it goes through the
    normal dispatch path, so it is only safe once the session is idle.
    """
    return _json_response(dispatcher.dispatch("scene.get_scene_info", {}))


@_api_function("mcp")
def list_commands(request):
    """List all registered command names for introspection."""
    return {"commands": dispatcher.list_commands()}
