"""HTTP bridge connecting the MCP server to Houdini's hwebserver.

Houdini's hwebserver uses an RPC-style calling convention:

    POST /api
    Content-Type: application/x-www-form-urlencoded
    Body: json=["namespace.function", [positional_args], {keyword_args}]

The server returns the function's return value JSON-encoded.
"""

from __future__ import annotations

# Built-in
import json
import logging
import uuid
from typing import Any

# Third-party
import httpx

# Internal
from fxhoudinimcp.errors import ConnectionError, HoudiniCommandError

logger = logging.getLogger(__name__)


def _rpc_body(func_name: str, **kwargs: Any) -> dict[str, str]:
    """Build form data for an hwebserver JSON-encoded RPC call."""
    return {"json": json.dumps([func_name, [], kwargs])}


class HoudiniBridge:
    """Manages HTTP communication between the MCP server and Houdini's hwebserver.

    Houdini's hwebserver exposes @apiFunction endpoints via a single /api URL.
    Calls are dispatched by function name inside the JSON-encoded body.
    """

    def __init__(self, host: str = "localhost", port: int = 8100, timeout: float = 60.0):
        self.base_url = f"http://{host}:{port}"
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def _api_url(self) -> str:
        return f"{self.base_url}/api"

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def execute(
        self,
        command: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Execute a command on Houdini and return the result data.

        Args:
            command: The command name (e.g. "scene.get_scene_info")
            params: Command parameters
            timeout: Override timeout for this request (seconds)

        Returns:
            The response data dict on success.

        Raises:
            ConnectionError: Cannot reach Houdini
            HoudiniCommandError: Houdini returned an error
        """
        request_id = str(uuid.uuid4())
        logger.info("→ Houdini: %s", command)

        client = await self._get_client()
        if timeout:
            client = httpx.AsyncClient(timeout=timeout)

        try:
            response = await client.post(
                self._api_url,
                data=_rpc_body(
                    "mcp.execute",
                    command=command,
                    params=params or {},
                    request_id=request_id,
                ),
            )
            response.raise_for_status()
        except httpx.ConnectError as e:
            raise ConnectionError(
                f"Cannot connect to Houdini at {self.base_url}. "
                "Is Houdini running with the fxhoudinimcp plugin loaded?",
                details={"url": self.base_url, "original_error": str(e)},
            ) from e
        except httpx.HTTPStatusError as e:
            raise ConnectionError(
                f"Houdini returned HTTP {e.response.status_code}",
                details={"status_code": e.response.status_code, "body": e.response.text},
            ) from e
        except httpx.TimeoutException as e:
            raise ConnectionError(
                f"Request to Houdini timed out after {timeout or self.timeout}s",
                details={"timeout": timeout or self.timeout},
            ) from e
        finally:
            if timeout:
                await client.aclose()

        result = response.json()
        timing = result.get("timing_ms", "") if isinstance(result, dict) else ""
        logger.info("← Houdini: %s (%sms)", command, timing)

        if isinstance(result, dict) and result.get("status") == "error":
            err = result.get("error", {})
            raise HoudiniCommandError(
                message=err.get("message", "Unknown Houdini error"),
                code=err.get("code", "UNKNOWN"),
                details=err,
            )

        if isinstance(result, dict) and result.get("status") == "success":
            return result.get("data", {})

        # apiFunction may return the raw result directly
        return result

    async def health_check(self) -> dict[str, Any]:
        """Check if Houdini is responsive.

        Returns:
            Dict with houdini_version, hip_file, pid, etc.
        """
        client = await self._get_client()
        try:
            response = await client.post(
                self._api_url,
                data=_rpc_body("mcp.health"),
            )
            response.raise_for_status()
            return response.json()
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise ConnectionError(
                f"Health check failed: cannot reach Houdini at {self.base_url}",
                details={"original_error": str(e)},
            ) from e

    async def close(self) -> None:
        """Close the HTTP client connection."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
