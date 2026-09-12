"""MCP tool modules for FXHoudini-MCP.

Importing this package registers all MCP tools with the FastMCP server.
Each submodule uses the `@mcp.tool()` decorator at import time.
"""

from __future__ import annotations

# Internal. Importing a tool module registers its tools on mcp.
from fxhoudinimcp.tools import (
    animation,  # noqa: F401
    cache,  # noqa: F401
    chops,  # noqa: F401
    code,  # noqa: F401
    context,  # noqa: F401
    cops,  # noqa: F401
    dops,  # noqa: F401
    geometry,  # noqa: F401
    graph,  # noqa: F401
    hda,  # noqa: F401
    help,  # noqa: F401
    lops,  # noqa: F401
    materials,  # noqa: F401
    nodes,  # noqa: F401
    parameters,  # noqa: F401
    rendering,  # noqa: F401
    scene,  # noqa: F401
    shelf,  # noqa: F401
    takes,  # noqa: F401
    tops,  # noqa: F401
    vex,  # noqa: F401
    viewport,  # noqa: F401
    workflows,  # noqa: F401
)
