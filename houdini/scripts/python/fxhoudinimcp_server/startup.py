"""Server startup and lifecycle management.

Handles starting/stopping the hwebserver and loading handler modules.
"""

from __future__ import annotations

# Built-in
import json
import os
import time
import urllib.parse
import urllib.request

_server_started = False
_port = 8100

# Ceiling for the readiness poll. This runs on the calling thread -- the main
# thread during UI auto-start -- so it is a stall budget on genuine failure,
# not free headroom. A healthy start answers in well under a second, since
# mcp.health needs nothing from the main thread; the old 3s was tight only
# because the health endpoint used to deadlock against this very loop.
_READINESS_TIMEOUT = 10.0


def _health_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/api"


def _health_body() -> bytes:
    return urllib.parse.urlencode(
        {"json": json.dumps(["mcp.health", [], {}])}
    ).encode("utf-8")


def _query_health(port: int, timeout: float = 0.5) -> dict | None:
    request = urllib.request.Request(
        _health_url(port),
        data=_health_body(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
    except Exception:
        return None

    try:
        data = json.loads(payload)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _wait_for_current_process_health(
    port: int,
    timeout_seconds: float = _READINESS_TIMEOUT,
) -> dict | None:
    deadline = time.time() + max(0.0, timeout_seconds)
    current_pid = os.getpid()
    last_health = None
    while time.time() < deadline:
        health = _query_health(port)
        if health is not None:
            last_health = health
            if health.get("pid") == current_pid:
                return health
        time.sleep(0.1)
    return last_health


def _bind_localhost_only(hwebserver) -> None:
    """Restrict the server to loopback before it starts listening.

    hwebserver binds the any-address (0.0.0.0) by default, which would put
    this bridge on the LAN. That matters more here than for a typical web
    endpoint: the bridge runs arbitrary Python inside Houdini (see
    handlers/code_handlers.py) and has no authentication, so anyone able to
    reach the port has the session.

    Set FXHOUDINIMCP_BIND to override, e.g. "0.0.0.0" to accept remote
    connections deliberately.
    """
    address = os.environ.get("FXHOUDINIMCP_BIND", "127.0.0.1")
    try:
        # Note the argument order: (settings, port_name). Passing the port
        # number first raises AttributeError on 'int'.
        hwebserver.setSettingsForPort({"ADDRESS": address}, "main")
    except Exception as exc:
        print(
            f"[fxhoudinimcp] Warning: could not restrict bind address to "
            f"{address}: {exc}. The port may be reachable from the network."
        )


def start(port: int | None = None, background: bool | None = None) -> None:
    """Start the FXHoudini-MCP server.

    Registers all command handlers and ensures hwebserver is running.

    Must be called from the thread that will own the server. hwebserver keeps
    its ``Server`` object in a ``threading.local()``, so API functions
    registered on one thread are invisible to ``run()`` on another -- calling
    ``run()`` from a fresh thread fails outright with "No URL handlers have
    been added to the server."

    Args:
        port: Port for hwebserver. Defaults to FXHOUDINIMCP_PORT env var or 8100.
        background: Serve on a background thread instead of blocking. Defaults
            to Houdini's own choice, which is True in a UI session and False
            under hython. Pass True from a headless script that needs start()
            to return while the server keeps serving.
    """
    global _server_started, _port

    if _server_started:
        print("[fxhoudinimcp] Server already running")
        return

    _port = port or int(os.environ.get("FXHOUDINIMCP_PORT", "8100"))

    # Import handlers to trigger registration via register_handler() calls
    from fxhoudinimcp_server import handlers  # noqa: F401

    # Import hwebserver_app to register the API functions
    from fxhoudinimcp_server import hwebserver_app  # noqa: F401

    # Start hwebserver if not already running. In Houdini 20.5+ it may already
    # be running for built-in features; in that case registering the functions
    # above is enough. Either way, prove the HTTP endpoint is reachable before
    # advertising readiness.
    import hou
    import hwebserver

    if background is None:
        # hwebserver.run() already defaults in_background to isUIAvailable(),
        # so this matches its behaviour; it is passed explicitly so the choice
        # is visible here and does not silently change under us. Blocking in a
        # UI session would wedge Houdini's main thread; blocking under hython
        # is what keeps the process alive to serve.
        background = hou.isUIAvailable()

    _bind_localhost_only(hwebserver)

    run_error = None
    try:
        hwebserver.run(_port, debug=False, in_background=background)
    except Exception as exc:
        run_error = exc

    if not background:
        # run() blocks until shutdown when serving in the foreground, so
        # reaching this point means it either finished or never started.
        _server_started = False
        if run_error is not None:
            raise RuntimeError(
                f"hwebserver failed to start on port {_port}: {run_error}"
            )
        return

    health = _wait_for_current_process_health(_port)
    if health is None:
        _server_started = False
        detail = f": {run_error}" if run_error is not None else ""
        raise RuntimeError(
            f"hwebserver did not answer mcp.health on port {_port}{detail}"
        )

    health_pid = health.get("pid")
    if health_pid != os.getpid():
        _server_started = False
        raise RuntimeError(
            "hwebserver port {} is owned by another Houdini process "
            "(pid {}), current pid {}".format(_port, health_pid, os.getpid())
        )

    _server_started = True
    print(
        "[fxhoudinimcp] Server ready on port {} "
        "(Houdini {}, pid {})".format(
            _port,
            health.get("houdini_version", "unknown"),
            health.get("pid", "unknown"),
        )
    )


def stop() -> None:
    """Stop the FXHoudini-MCP server."""
    global _server_started
    if not _server_started:
        return

    # Note: we don't call hwebserver.requestShutdown() because that would
    # kill Houdini's built-in web server too. We just mark ourselves as stopped.
    _server_started = False
    print("[fxhoudinimcp] Server stopped")


def is_running() -> bool:
    """Check if the server is currently running."""
    return _server_started


def get_port() -> int:
    """Get the port the server is running on."""
    return _port


def ensure_running() -> None:
    """Start the server if it's not already running."""
    global _server_started
    if _server_started:
        health = _wait_for_current_process_health(_port, timeout_seconds=0.5)
        if health is not None and health.get("pid") == os.getpid():
            return
        _server_started = False
    start()
