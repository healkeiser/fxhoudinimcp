"""MCP server definition for FXHoudini-MCP.

The SDK class is imported from ``_sdk`` rather than from mcp directly:
mcp 2.0 renamed it and moved it, and that shim is the single place
that knows.
"""

from __future__ import annotations

# Built-in
import logging
import os
from contextlib import asynccontextmanager

from fxhoudinimcp._loader import load_markdown

# Third-party
from fxhoudinimcp._sdk import Server, build_server
from fxhoudinimcp._version import __version__

# Internal
from fxhoudinimcp.bridge import HoudiniBridge, find_servers
from fxhoudinimcp.compat import compatibility_warning
from fxhoudinimcp.node_versions import staleness_warning

logger = logging.getLogger(__name__)


def _get_bridge(ctx) -> HoudiniBridge:
    """Extract the HoudiniBridge from the MCP context."""
    return ctx.request_context.lifespan_context["bridge"]


# The lifespan bridge, also reachable without a request context.
#
# mcp 2.0 refuses to inject Context into a resource whose URI has no template
# variables ("Context injection for static resources is not supported"), and
# houdini://scene/info and friends are exactly that. The bridge is one per
# process, created once in lifespan, so a resource does not need the request to
# find it. Tools keep taking Context, which 2.0 still allows.
_bridge: HoudiniBridge | None = None


def current_bridge() -> HoudiniBridge:
    """The process's HoudiniBridge, for callers with no request context."""
    if _bridge is None:
        raise RuntimeError(
            "No Houdini bridge yet. Resources are readable only once the "
            "server has started and its lifespan has run."
        )
    return _bridge


@asynccontextmanager
async def lifespan(server: Server):
    """Manage the Houdini bridge connection lifecycle."""
    host = os.getenv("HOUDINI_HOST", "localhost")
    pinned = os.getenv("HOUDINI_PORT")
    port = int(pinned) if pinned else 8100

    if not pinned:
        # A second Houdini moves itself to the next free port, so assuming 8100
        # would leave that session unreachable. Only scan when the port was not
        # pinned: an explicit HOUDINI_PORT is a deliberate choice, and silently
        # connecting somewhere else would be worse than failing.
        servers = await find_servers(host, port)
        if servers:
            port = servers[0]["port"]
            if len(servers) > 1:
                others = ", ".join(f"port {s['port']} (pid {s.get('pid')})" for s in servers[1:])
                logger.warning(
                    "%d Houdini sessions are serving; using port %d (pid %s). "
                    "Others: %s. Set HOUDINI_PORT to pin a specific one.",
                    len(servers),
                    port,
                    servers[0].get("pid"),
                    others,
                )
            elif port != 8100:
                logger.info("Found Houdini on port %d", port)

    bridge = HoudiniBridge(host=host, port=port)

    try:
        info = await bridge.health_check()
        houdini_version = info.get("houdini_version", "unknown")
        logger.info("Connected to Houdini %s", houdini_version)

        # The version markers in server_instructions.md are derived from the
        # Houdini builds contributors have sampled. A version outside that set
        # is not an error, but the markers stop being trustworthy and saying so
        # beats letting them quietly mislead.
        stale = staleness_warning(houdini_version)
        if stale:
            logger.warning(stale)

        # Name a plugin/server mismatch now, rather than letting one tool fail
        # later with what looks like a bug.
        try:
            mismatch = compatibility_warning(await bridge.list_commands())
        except Exception as exc:
            logger.debug("Could not check plugin commands: %s", exc)
        else:
            if mismatch:
                logger.warning(mismatch)
    except Exception as e:
        logger.warning("Cannot reach Houdini at startup: %s", e)
        logger.warning("Tools will attempt to connect on first use.")

    global _bridge
    _bridge = bridge
    try:
        yield {"bridge": bridge}
    finally:
        _bridge = None
        await bridge.close()


mcp = build_server(
    name="FXHoudini",
    instructions=load_markdown("instructions/server_instructions.md"),
    lifespan=lifespan,
    version=__version__,
)
