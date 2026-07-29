"""Shared fixtures for fxhoudinimcp tests."""

from __future__ import annotations

# Built-in
from unittest.mock import AsyncMock, MagicMock

# Third-party
import pytest


@pytest.fixture
def mock_bridge():
    """A mocked HoudiniBridge whose execute() returns a success dict."""
    bridge = AsyncMock()
    bridge.execute = AsyncMock(return_value={"executed": True})
    bridge.health_check = AsyncMock(return_value={"status": "ok", "houdini_version": "21.0.440"})
    # A compatible plugin by default: the connection-status tool checks for a
    # plugin older than the server, and an unset mock would look like one.
    from fxhoudinimcp.compat import required_commands

    bridge.list_commands = AsyncMock(return_value=sorted(required_commands()))
    return bridge


@pytest.fixture
def mock_ctx(mock_bridge):
    """A mocked MCP Context wired to mock_bridge."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {"bridge": mock_bridge}
    return ctx


@pytest.fixture
def process_bridge(mock_bridge, monkeypatch):
    """Publish mock_bridge as the process bridge that resources read.

    Resources stopped taking Context when mcp 2.0 refused to inject it into a
    static resource, so they read fxhoudinimcp.server._bridge instead. Patching
    the module attribute is what a running lifespan does.
    """
    import fxhoudinimcp.server as server

    monkeypatch.setattr(server, "_bridge", mock_bridge)
    return mock_bridge
