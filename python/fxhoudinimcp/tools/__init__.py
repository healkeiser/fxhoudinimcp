"""MCP tool modules for FXHoudini-MCP.

Importing this package registers all MCP tools with the FastMCP server.
Each submodule uses the ``@mcp.tool()`` decorator at import time.
"""

from __future__ import annotations

# Internal
from fxhoudinimcp.tools import scene  # noqa: F401
from fxhoudinimcp.tools import nodes  # noqa: F401
from fxhoudinimcp.tools import parameters  # noqa: F401
from fxhoudinimcp.tools import code  # noqa: F401
from fxhoudinimcp.tools import dops  # noqa: F401
from fxhoudinimcp.tools import animation  # noqa: F401
from fxhoudinimcp.tools import rendering  # noqa: F401
from fxhoudinimcp.tools import viewport  # noqa: F401
from fxhoudinimcp.tools import tops  # noqa: F401
from fxhoudinimcp.tools import cops  # noqa: F401
from fxhoudinimcp.tools import hda  # noqa: F401
from fxhoudinimcp.tools import vex  # noqa: F401
from fxhoudinimcp.tools import geometry  # noqa: F401
from fxhoudinimcp.tools import lops  # noqa: F401
from fxhoudinimcp.tools import context  # noqa: F401
from fxhoudinimcp.tools import workflows  # noqa: F401
from fxhoudinimcp.tools import materials  # noqa: F401
from fxhoudinimcp.tools import chops  # noqa: F401
from fxhoudinimcp.tools import cache  # noqa: F401
from fxhoudinimcp.tools import takes  # noqa: F401
