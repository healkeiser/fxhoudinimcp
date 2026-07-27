"""Tests for the HTTP bridge to Houdini."""

from __future__ import annotations

# Built-in
from unittest.mock import AsyncMock, MagicMock, patch

# Third-party
import httpx
import pytest

# Internal
from fxhoudinimcp.bridge import HoudiniBridge
from fxhoudinimcp.errors import ConnectionError, HoudiniCommandError


class TestHoudiniBridgeInit:
    def test_default_url(self):
        bridge = HoudiniBridge()
        assert bridge.base_url == "http://localhost:8100"
        assert bridge._api_url == "http://localhost:8100/api"

    def test_custom_host_port(self):
        bridge = HoudiniBridge(host="10.0.0.1", port=9090)
        assert bridge.base_url == "http://10.0.0.1:9090"


class TestExecute:
    @pytest.fixture
    def bridge(self):
        return HoudiniBridge()

    @pytest.fixture
    def mock_response(self):
        """A factory for mock httpx.Response objects."""
        def _make(json_data, status_code=200):
            resp = MagicMock(spec=httpx.Response)
            resp.json.return_value = json_data
            resp.status_code = status_code
            resp.raise_for_status = MagicMock()
            if status_code >= 400:
                resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                    "error", request=MagicMock(), response=resp
                )
                resp.text = str(json_data)
            return resp
        return _make

    @pytest.mark.asyncio
    async def test_success(self, bridge, mock_response):
        resp = mock_response({"status": "success", "data": {"key": "val"}, "timing_ms": 5.0})
        with patch.object(bridge, "_get_client") as mock_client:
            client = AsyncMock()
            client.post = AsyncMock(return_value=resp)
            mock_client.return_value = client

            result = await bridge.execute("scene.get_info")
            assert result == {"key": "val"}
            client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_houdini_error_raises_command_error(self, bridge, mock_response):
        resp = mock_response({
            "status": "error",
            "error": {"code": "NODE_NOT_FOUND", "message": "Node not found: /bad"},
        })
        with patch.object(bridge, "_get_client") as mock_client:
            client = AsyncMock()
            client.post = AsyncMock(return_value=resp)
            mock_client.return_value = client

            with pytest.raises(HoudiniCommandError) as exc_info:
                await bridge.execute("nodes.get_info", {"path": "/bad"})
            assert exc_info.value.code == "NODE_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_connect_error(self, bridge):
        with patch.object(bridge, "_get_client") as mock_client:
            client = AsyncMock()
            client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client.return_value = client

            with pytest.raises(ConnectionError):
                await bridge.execute("scene.get_info")

    @pytest.mark.asyncio
    async def test_timeout_error(self, bridge):
        with patch.object(bridge, "_get_client") as mock_client:
            client = AsyncMock()
            client.post = AsyncMock(side_effect=httpx.ReadTimeout("timeout"))
            mock_client.return_value = client

            with pytest.raises(ConnectionError) as exc_info:
                await bridge.execute("scene.get_info")
            assert "timed out" in str(exc_info.value)

    @pytest.mark.parametrize(
        ("exc", "expected"),
        [
            # _post retries this one on a fresh pool first; reaching the
            # handler at all means the retry failed too, so Houdini is gone.
            (
                httpx.RemoteProtocolError("Server disconnected without sending"),
                "Cannot connect to Houdini",
            ),
            (httpx.ReadError(""), "ReadError"),
            (httpx.WriteError(""), "WriteError"),
            (httpx.CloseError(""), "CloseError"),
            # A TimeoutException subclass, so it keeps the more specific
            # timeout message from the branch above rather than falling through.
            (httpx.PoolTimeout(""), "timed out"),
        ],
        ids=["remote_protocol", "read", "write", "close", "pool_timeout"],
    )
    @pytest.mark.asyncio
    async def test_transport_errors_are_wrapped(self, bridge, exc, expected):
        """Every transport failure must surface as our own ConnectionError.

        These used to escape as raw httpx exceptions, and ReadError/WriteError
        carry an empty message, so the MCP client got a failure with no hint
        that Houdini was even involved.

        _reset_client is patched alongside _get_client because _post retries a
        RemoteProtocolError on a fresh pool; left real, that retry would make an
        actual connection attempt to port 8100 -- slow, and it would resolve
        differently if a Houdini happened to be listening.
        """
        client = AsyncMock()
        client.post = AsyncMock(side_effect=exc)

        with (
            patch.object(bridge, "_get_client", return_value=client),
            patch.object(bridge, "_reset_client", return_value=client),
            pytest.raises(ConnectionError) as exc_info,
        ):
            await bridge.execute("scene.get_info")

        message = str(exc_info.value)
        assert message.strip()
        assert expected in message

    @pytest.mark.asyncio
    async def test_http_status_error(self, bridge, mock_response):
        resp = mock_response({"error": "server error"}, status_code=500)
        with patch.object(bridge, "_get_client") as mock_client:
            client = AsyncMock()
            client.post = AsyncMock(return_value=resp)
            mock_client.return_value = client

            with pytest.raises(ConnectionError) as exc_info:
                await bridge.execute("scene.get_info")
            assert "500" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_raw_result_fallback(self, bridge, mock_response):
        """When response isn't wrapped in status/data, return it directly."""
        resp = mock_response({"directly": "returned"})
        with patch.object(bridge, "_get_client") as mock_client:
            client = AsyncMock()
            client.post = AsyncMock(return_value=resp)
            mock_client.return_value = client

            result = await bridge.execute("some.command")
            assert result == {"directly": "returned"}


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_success(self):
        bridge = HoudiniBridge()
        resp = MagicMock(spec=httpx.Response)
        resp.json.return_value = {"status": "ok", "houdini_version": "21.0.440"}
        resp.raise_for_status = MagicMock()

        with patch.object(bridge, "_get_client") as mock_client:
            client = AsyncMock()
            client.post = AsyncMock(return_value=resp)
            mock_client.return_value = client

            result = await bridge.health_check()
            assert result["houdini_version"] == "21.0.440"

    @pytest.mark.asyncio
    async def test_failure_raises_connection_error(self):
        bridge = HoudiniBridge()
        with patch.object(bridge, "_get_client") as mock_client:
            client = AsyncMock()
            client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client.return_value = client

            with pytest.raises(ConnectionError):
                await bridge.health_check()

    @pytest.mark.parametrize(
        "exc",
        [
            httpx.RemoteProtocolError("disconnected"),
            httpx.ReadError(""),
            httpx.PoolTimeout(""),
            httpx.ReadTimeout("slow"),
        ],
        ids=["remote_protocol", "read", "pool_timeout", "read_timeout"],
    )
    @pytest.mark.asyncio
    async def test_transport_errors_are_wrapped(self, exc):
        bridge = HoudiniBridge()
        client = AsyncMock()
        client.post = AsyncMock(side_effect=exc)

        # See the note in TestExecute: _reset_client must be patched too, or
        # _post's retry makes a real connection attempt.
        with (
            patch.object(bridge, "_get_client", return_value=client),
            patch.object(bridge, "_reset_client", return_value=client),
            pytest.raises(ConnectionError) as exc_info,
        ):
            await bridge.health_check()

        assert "cannot reach Houdini" in str(exc_info.value)


class TestClose:
    @pytest.mark.asyncio
    async def test_close_with_client(self):
        bridge = HoudiniBridge()
        mock_client = AsyncMock()
        mock_client.is_closed = False
        bridge._client = mock_client

        await bridge.close()
        mock_client.aclose.assert_called_once()
        assert bridge._client is None

    @pytest.mark.asyncio
    async def test_close_without_client(self):
        bridge = HoudiniBridge()
        await bridge.close()  # should not raise


class TestListCommands:
    """Used to detect a plugin older than this server."""

    @pytest.mark.asyncio
    async def test_returns_the_command_list(self):
        bridge = HoudiniBridge()
        resp = MagicMock(spec=httpx.Response)
        resp.json.return_value = {"commands": ["scene.get_scene_info", "a.b"]}
        resp.raise_for_status = MagicMock()

        with patch.object(bridge, "_get_client") as mock_client:
            client = AsyncMock()
            client.post = AsyncMock(return_value=resp)
            mock_client.return_value = client

            assert await bridge.list_commands() == ["scene.get_scene_info", "a.b"]

    @pytest.mark.asyncio
    async def test_calls_mcp_list_commands_not_mcp_execute(self):
        """It must work even when the dispatcher is missing commands."""
        bridge = HoudiniBridge()
        resp = MagicMock(spec=httpx.Response)
        resp.json.return_value = {"commands": []}
        resp.raise_for_status = MagicMock()

        with patch.object(bridge, "_get_client") as mock_client:
            client = AsyncMock()
            client.post = AsyncMock(return_value=resp)
            mock_client.return_value = client
            await bridge.list_commands()

        body = client.post.call_args.kwargs.get("data") or client.post.call_args[1]["data"]
        assert "mcp.list_commands" in body["json"]

    @pytest.mark.parametrize(
        "payload", [{}, {"commands": None}, {"commands": "nope"}, []]
    )
    @pytest.mark.asyncio
    async def test_unexpected_payload_gives_an_empty_list(self, payload):
        bridge = HoudiniBridge()
        resp = MagicMock(spec=httpx.Response)
        resp.json.return_value = payload
        resp.raise_for_status = MagicMock()

        with patch.object(bridge, "_get_client") as mock_client:
            client = AsyncMock()
            client.post = AsyncMock(return_value=resp)
            mock_client.return_value = client

            assert await bridge.list_commands() == []

    @pytest.mark.asyncio
    async def test_transport_failure_is_wrapped(self):
        bridge = HoudiniBridge()
        client = AsyncMock()
        client.post = AsyncMock(side_effect=httpx.ReadError(""))

        with (
            patch.object(bridge, "_get_client", return_value=client),
            patch.object(bridge, "_reset_client", return_value=client),
            pytest.raises(ConnectionError),
        ):
            await bridge.list_commands()
