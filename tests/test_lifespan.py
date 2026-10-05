"""The lifespan must not hold up the MCP handshake (issue #129)."""

from __future__ import annotations

# Built-in
import asyncio

# Third-party
import pytest

# Internal
from fxhoudinimcp import server


@pytest.mark.asyncio
async def test_lifespan_yields_before_discovery_finishes(monkeypatch):
    # The SDK answers `initialize` only after the lifespan yields, so a slow
    # port scan here is a slow handshake, and Cline drops servers after 3 s.
    async def slow_scan(*args, **kwargs):
        await asyncio.sleep(30)
        return []

    monkeypatch.delenv("HOUDINI_PORT", raising=False)
    monkeypatch.setattr(server, "find_servers", slow_scan)
    async with asyncio.timeout(1):
        async with server.lifespan(None) as state:
            assert state["bridge"].port == 8100
