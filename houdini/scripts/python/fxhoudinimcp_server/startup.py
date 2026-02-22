"""Server startup and lifecycle management.

Handles starting/stopping the hwebserver and loading handler modules.
"""

from __future__ import annotations

# Built-in
import os

_server_started = False
_port = 8100


def start(port: int | None = None) -> None:
    """Start the FXHoudini-MCP server.

    Registers all command handlers and ensures hwebserver is running.

    Args:
        port: Port for hwebserver. Defaults to FXHOUDINIMCP_PORT env var or 8100.
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

    # Start hwebserver if not already running.
    # In Houdini 20.5+, hwebserver may already be running for built-in features.
    # In that case, our @apiFunction decorators are already registered and
    # we just need to note that the server is active.
    import hwebserver

    try:
        hwebserver.run(_port, debug=False)
    except Exception:
        # Server may already be running, that's fine, our endpoints are registered
        pass

    _server_started = True
    print(f"[fxhoudinimcp] Server ready on port {_port}")


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
    if not _server_started:
        start()
