"""FastMCP server definition for FXHoudini-MCP."""

from __future__ import annotations

# Built-in
import logging
import os
from contextlib import asynccontextmanager

# Third-party
from mcp.server.fastmcp import FastMCP

# Internal
from fxhoudinimcp.bridge import HoudiniBridge
from fxhoudinimcp.compat import compatibility_warning
from fxhoudinimcp._loader import load_markdown
from fxhoudinimcp._version import __version__
from fxhoudinimcp.node_versions import staleness_warning

logger = logging.getLogger(__name__)


def _get_bridge(ctx) -> HoudiniBridge:
    """Extract the HoudiniBridge from the MCP context."""
    return ctx.request_context.lifespan_context["bridge"]


@asynccontextmanager
async def lifespan(server: FastMCP):
    """Manage the Houdini bridge connection lifecycle."""
    host = os.getenv("HOUDINI_HOST", "localhost")
    port = int(os.getenv("HOUDINI_PORT", "8100"))

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

        # The plugin ships from the repository, not from PyPI, so upgrading the
        # package does not update it. Name the gap now rather than letting one
        # tool fail later with what looks like a bug.
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

    try:
        yield {"bridge": bridge}
    finally:
        await bridge.close()


mcp = FastMCP(
    name="FXHoudini",
    instructions=load_markdown("server_instructions.md"),
    lifespan=lifespan,
)
mcp._mcp_server.version = __version__
