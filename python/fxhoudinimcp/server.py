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
    instructions=(
        "MCP server for SideFX Houdini with 168 tools across 19 categories.\n\n"
        "PROGRESS FEEDBACK (do this first, always):\n"
        "- Call log_status at the start of every major step so the user can "
        "follow your work in Houdini's status bar in real time. Examples: "
        "'Creating base geometry...', 'Wiring SOP chain...', "
        "'Setting up pyro simulation...', 'Assigning materials...'. "
        "This costs almost nothing and is the user's only live feedback.\n\n"
        "TOOL PRIORITY for geometry (highest to lowest):\n"
        "  1. Workflow tools — build_sop_chain, setup_pyro_sim, setup_rbd_sim, "
        "setup_flip_sim, setup_vellum_sim. These build entire networks in ONE "
        "call. Always prefer them over building node-by-node.\n"
        "  2. Native SOP nodes via create_node + connect_nodes_batch — box, "
        "grid, sphere, polyextrude, boolean, scatter, copy_to_points, "
        "attribute_randomize, blast, transform, polybevel, mountain, etc. "
        "Use set_parameters (plural, batch) to set multiple params in one call.\n"
        "  3. VEX wrangles via create_wrangle — ONLY when no built-in SOP can "
        "express the logic. NOT for shapes, copies, random attributes, or "
        "boolean operations — those all have dedicated SOP nodes.\n"
        "  4. execute_python — absolute last resort for hou.* API calls that "
        "no dedicated tool exposes. NEVER use it to create nodes, set "
        "parameters, connect nodes, or write Python SOPs — every one of those "
        "has a dedicated tool. Using execute_python for node building hides "
        "errors, produces wrong parameter values (e.g. wrong numeric enum for "
        "'class'), and bypasses validation.\n\n"
        "- After EVERY create_wrangle or set_wrangle_code call, immediately "
        "call validate_vex. Do not proceed until it reports no errors.\n"
        "- build_sop_chain takes a list of steps and wires them all at once. "
        "Prefer it over individual create_node calls for linear SOP chains.\n"
        "- Before writing ANY VEX, ask: does a SOP node already do this? "
        "Call list_node_types with context='Sop' to check.\n"
        "- NEVER hardcode tweakable values. Create a controller null ('CTRL') "
        "with spare parameters for user-facing controls.\n"
        "- Call layout_children after every batch of nodes, not just at the end.\n"
        "- When a workflow tool exists (setup_pyro_sim, setup_rbd_sim, etc.), "
        "use it instead of building from scratch."
    ),
    lifespan=lifespan,
)
