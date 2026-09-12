"""The HTTP endpoint refuses requests that did not come from the MCP bridge.

Loopback binding keeps the LAN out, but a browser tab is on loopback too: a page
can POST a form-encoded body to 127.0.0.1 with no CORS preflight, and the
endpoint runs arbitrary Python. The guard tested here is what stands between a
visited web page and hou.
"""

from __future__ import annotations

# Built-in
import os
import sys
from unittest.mock import MagicMock

# Third-party
import pytest

sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.modules.setdefault("hwebserver", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

from fxhoudinimcp_server.hwebserver_app import _bare_host, _foreign_request_reason  # noqa: E402


class _Request:
    def __init__(self, headers: dict, host: str = "127.0.0.1:8100"):
        self._headers = headers
        self._host = host

    def headers(self):
        return self._headers

    def host(self):
        return self._host


@pytest.fixture(autouse=True)
def loopback_bind(monkeypatch):
    monkeypatch.delenv("FXHOUDINIMCP_BIND", raising=False)


def test_bridge_request_is_allowed():
    assert _foreign_request_reason(_Request({"Host": "127.0.0.1:8100"})) is None


@pytest.mark.parametrize("host", ["localhost:8100", "localhost", "[::1]:8100", "127.0.0.1"])
def test_every_loopback_spelling_is_allowed(host):
    assert _foreign_request_reason(_Request({}, host=host)) is None


def test_browser_origin_is_refused():
    reason = _foreign_request_reason(
        _Request({"Origin": "https://evil.example", "Host": "127.0.0.1:8100"})
    )
    assert reason and "Origin" in reason and "evil.example" in reason


def test_origin_check_is_case_insensitive():
    assert _foreign_request_reason(_Request({"origin": "null"})) is not None


def test_dns_rebinding_host_is_refused():
    reason = _foreign_request_reason(_Request({}, host="attacker.example:8100"))
    assert reason and "attacker.example" in reason


def test_widened_bind_accepts_foreign_hosts(monkeypatch):
    """Someone who set FXHOUDINIMCP_BIND=0.0.0.0 asked for remote clients."""
    monkeypatch.setenv("FXHOUDINIMCP_BIND", "0.0.0.0")
    assert _foreign_request_reason(_Request({}, host="render-42.farm:8100")) is None


def test_widened_bind_still_refuses_browsers(monkeypatch):
    monkeypatch.setenv("FXHOUDINIMCP_BIND", "0.0.0.0")
    assert _foreign_request_reason(_Request({"Origin": "https://x.example"})) is not None


def test_unreadable_headers_do_not_crash():
    class Broken:
        def headers(self):
            raise RuntimeError("no headers")

        def host(self):
            return "127.0.0.1:8100"

    assert _foreign_request_reason(Broken()) is None


@pytest.mark.parametrize(
    ("host", "bare"),
    [
        ("127.0.0.1:8100", "127.0.0.1"),
        ("localhost", "localhost"),
        ("[::1]:8100", "[::1]"),
        ("[::1]", "[::1]"),
    ],
)
def test_bare_host(host, bare):
    assert _bare_host(host) == bare
