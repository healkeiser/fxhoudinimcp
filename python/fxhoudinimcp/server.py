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
from fxhoudinimcp._loader import load_markdown
from fxhoudinimcp._version import __version__

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
        logger.info(
            "Connected to Houdini %s", info.get("houdini_version", "unknown")
        )
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
