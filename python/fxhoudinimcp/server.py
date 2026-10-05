"""MCP server definition for FXHoudini-MCP.

The SDK class is imported from ``_sdk`` rather than from mcp directly:
mcp 2.0 renamed it and moved it, and that shim is the single place
that knows.
"""

from __future__ import annotations

# Built-in
import asyncio
import contextlib
import functools
import inspect
import json
import logging
import os
from contextlib import asynccontextmanager

from fxhoudinimcp._loader import load_markdown

# Third-party
from fxhoudinimcp._sdk import Server, build_server, forbid_unknown_arguments
from fxhoudinimcp._version import __version__

# Internal
from fxhoudinimcp.bridge import HoudiniBridge, find_servers
from fxhoudinimcp.compat import compatibility_warning
from fxhoudinimcp.node_versions import staleness_warning

logger = logging.getLogger(__name__)


# Seconds between progress notifications while a command is in flight.
_HEARTBEAT = 2.0


class _ReportingBridge:
    """The lifespan bridge, with a progress heartbeat for the current request.

    A long command (a cook, a foreground cache, a verify on a heavy graph)
    used to be a static "calling fxhoudini" line for as long as it took. While
    the HTTP call is pending, this sends an MCP progress notification every
    couple of seconds naming the command and the elapsed time. The SDK drops
    the notification when the client sent no progress token, so a client that
    does not render progress pays nothing; whether Claude Code shows it is
    for the client to decide. Every other attribute goes straight through.
    """

    def __init__(self, bridge: HoudiniBridge, ctx) -> None:
        self._bridge = bridge
        self._ctx = ctx

    def __getattr__(self, name: str):
        return getattr(self._bridge, name)

    async def _heartbeat(self, command: str) -> None:
        import asyncio
        import time

        started = time.monotonic()
        while True:
            await asyncio.sleep(_HEARTBEAT)
            elapsed = time.monotonic() - started
            try:
                await self._ctx.report_progress(
                    elapsed, None, f"{command}: Houdini working for {elapsed:.0f}s"
                )
            except Exception:  # noqa: BLE001 - a heartbeat never fails the command
                return

    async def execute(self, command: str, params=None, timeout=None):
        import asyncio

        beat = asyncio.ensure_future(self._heartbeat(command))
        # Bound to a local so the compat scanner, which collects the literal
        # command names of every `.execute("...")` call, does not see a dynamic one.
        run = self._bridge.execute
        try:
            return await run(command, params, timeout)
        finally:
            beat.cancel()


def _get_bridge(ctx) -> HoudiniBridge:
    """The HoudiniBridge for this request, wrapped with a progress heartbeat."""
    bridge = ctx.request_context.lifespan_context["bridge"]
    if isinstance(bridge, HoudiniBridge):
        return _ReportingBridge(bridge, ctx)  # type: ignore[return-value]
    return bridge


# The lifespan bridge, also reachable without a request context.
#
# mcp 2.0 refuses to inject Context into a resource whose URI has no template
# variables ("Context injection for static resources is not supported"), and
# houdini://scene/info and friends are exactly that. The bridge is one per
# process, created once in lifespan, so a resource does not need the request to
# find it. Tools keep taking Context, which 2.0 still allows.
_bridge: HoudiniBridge | None = None


def current_bridge() -> HoudiniBridge:
    """The process's HoudiniBridge, for callers with no request context."""
    if _bridge is None:
        raise RuntimeError(
            "No Houdini bridge yet. Resources are readable only once the "
            "server has started and its lifespan has run."
        )
    return _bridge


async def _discover(bridge: HoudiniBridge, pinned: bool) -> None:
    """Find the Houdini to talk to, point the bridge at it, and log what it is."""
    if not pinned:
        # A second Houdini moves itself to the next free port, so assuming 8100
        # would leave that session unreachable. Only scan when the port was not
        # pinned: an explicit HOUDINI_PORT is a deliberate choice, and silently
        # connecting somewhere else would be worse than failing.
        servers = await find_servers(bridge.host, bridge.port)
        if servers:
            port = servers[0]["port"]
            if len(servers) > 1:
                others = ", ".join(f"port {s['port']} (pid {s.get('pid')})" for s in servers[1:])
                logger.warning(
                    "%d Houdini sessions are serving; using port %d (pid %s). "
                    "Others: %s. Set HOUDINI_PORT to pin a specific one.",
                    len(servers),
                    port,
                    servers[0].get("pid"),
                    others,
                )
            elif port != bridge.port:
                logger.info("Found Houdini on port %d", port)
            if port != bridge.port:
                await bridge.retarget(port)

    try:
        info = await bridge.health_check()
        houdini_version = info.get("houdini_version", "unknown")
        logger.info("Connected to Houdini %s", houdini_version)

        # The version markers in server_instructions.md are derived from the
        # Houdini builds contributors have sampled. A version outside that set
        # is not an error, but the markers stop being trustworthy and saying so
        # beats letting them quietly mislead.
        stale = staleness_warning(houdini_version)
        if stale:
            logger.warning(stale)

        # Name a plugin/server mismatch now, rather than letting one tool fail
        # later with what looks like a bug.
        try:
            mismatch = compatibility_warning(await bridge.list_commands())
        except Exception as exc:
            logger.debug("Could not check plugin commands: %s", exc)
        else:
            if mismatch:
                logger.warning(mismatch)
    except Exception as e:
        logger.warning("Cannot reach Houdini at startup: %s", e)
        logger.warning("Tools will attempt to connect on first use.")


@asynccontextmanager
async def lifespan(server: Server):
    """Manage the Houdini bridge connection lifecycle."""
    host = os.getenv("HOUDINI_HOST", "localhost")
    pinned = os.getenv("HOUDINI_PORT")
    port = int(pinned) if pinned else 8100

    # The plugin gives a command FXHOUDINIMCP_TIMEOUT seconds (120 by default)
    # and this client used to give up at a hard-coded 60. A cache launch that
    # took 70 seconds then read as "timed out" here while Houdini finished the
    # job, and the agent had to poll the disk to learn that. The client waits
    # for the plugin's own deadline plus a margin unless HOUDINI_TIMEOUT says
    # otherwise; a per-command FXHOUDINIMCP_TIMEOUT_<COMMAND> raised on the
    # Houdini side needs HOUDINI_TIMEOUT raised here to match.
    plugin_timeout = float(os.getenv("FXHOUDINIMCP_TIMEOUT", "120"))
    timeout = float(os.getenv("HOUDINI_TIMEOUT", str(plugin_timeout + 15)))
    bridge = HoudiniBridge(host=host, port=port, timeout=timeout)

    # The SDK answers `initialize` only once this lifespan yields, and with no
    # Houdini running the scan and health check took about 4 s on Windows,
    # where a closed localhost port times out instead of refusing. Cline gives
    # up after 3 s and drops every tool (issue #129). So discovery runs beside
    # the handshake instead of before it.
    # ponytail: a tool called in the first second can still hit 8100 while
    # Houdini is on 8101+; connect_houdini fixes it, await the task if it bites.
    discovery = asyncio.ensure_future(_discover(bridge, bool(pinned)))

    global _bridge
    _bridge = bridge
    try:
        yield {"bridge": bridge}
    finally:
        discovery.cancel()
        _bridge = None
        await bridge.close()


mcp = build_server(
    name="FXHoudini",
    instructions=load_markdown("instructions/server_instructions.md"),
    lifespan=lifespan,
    version=__version__,
)


def _trim(value):
    """Floats cut to 7 significant digits, the precision of Houdini's float32 geometry.

    HOM hands back doubles, so a bbox corner arrives as -10.388985633850098:
    eighteen characters, nine of them noise the geometry never stored.
    """
    if isinstance(value, float):
        return float(f"{value:.7g}")
    if isinstance(value, dict):
        return {key: _trim(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_trim(item) for item in value]
    return value


def compact_json(result: dict) -> str:
    """A tool result as the model reads it: no indentation, trimmed floats.

    The SDK serialises a dict with indent=2, which on a verify_network or a
    node card is about a third whitespace, paid on every call.
    """
    return json.dumps(_trim(result), separators=(",", ":"), ensure_ascii=False, default=str)


_sdk_tool = mcp.tool


def _compact_tool(*args, **kwargs):
    """mcp.tool(), registering a copy that answers in compact JSON.

    The module-level function stays the original, returning its dict, so code
    and tests that call a tool directly see no difference.
    """
    register = _sdk_tool(*args, **kwargs)

    def decorator(function):
        @functools.wraps(function)
        async def compact(*call_args, **call_kwargs):
            result = await function(*call_args, **call_kwargs)
            return compact_json(result) if isinstance(result, dict) else result

        # Resolved against the tool's own module: inspect.signature follows
        # __wrapped__ to string annotations ("Context"), and mcp 1.14 then
        # evaluated them in this module, where Context is not defined. A
        # __signature__ stops the unwrapping.
        with contextlib.suppress(Exception):
            compact.__signature__ = inspect.signature(function, eval_str=True)
        register(compact)
        forbid_unknown_arguments(mcp, kwargs.get("name") or function.__name__)
        return function

    return decorator


mcp.tool = _compact_tool
