"""FXHoudini-MCP: Comprehensive MCP server for SideFX Houdini."""

from __future__ import annotations

try:
    # Written at build time by hatch-vcs, so it is the only place that knows
    # the real version. This used to be a hardcoded "0.1.0", which meant
    # fxhoudinimcp.__version__ disagreed with the package metadata, with
    # mcp._mcp_server.version, and with the truth, from 1.0.0 onwards.
    from fxhoudinimcp._version import __version__
except ImportError:  # pragma: no cover - a source tree that was never built
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
