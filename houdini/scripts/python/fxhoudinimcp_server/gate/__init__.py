"""Gate package: security gate middleware and install_gate() entry point.

Wraps fxhoudinimcp_server.dispatcher.dispatch() with a security chokepoint
backed by the homedini.dcc.mcp_gate pure core.  All 179 registered handlers
are gated by construction — no per-handler opt-in required.

Usage:
    from fxhoudinimcp_server.gate import install_gate
    install_gate()  # call once after handlers are registered, before hwebserver starts
"""

from __future__ import annotations

from typing import Any

__all__ = ["install_gate"]


def install_gate(*args: Any, **kwargs: Any) -> Any:
    """Install the security gate, resolving the implementation at CALL time.

    Deliberately NOT `from ...middleware import install_gate` at module level. That binds the
    function OBJECT once, when this package is first imported; a later
    `importlib.reload(...gate.middleware)` re-executes the submodule but never re-executes THIS
    file, so the cached name would keep calling the PRE-reload function -- meaning the documented
    public entry point would silently install the old, un-hardened gate while the reloaded module
    sat unused. Resolving inside the call follows the reload instead (the CL-005/CL-011 class of
    stale-binding bug, found by adversarial review of ADR-0007 Phase 3).
    """
    from fxhoudinimcp_server.gate import middleware

    return middleware.install_gate(*args, **kwargs)
