"""Fixtures for integration tests that require a live Houdini.

These tests run under hython, Houdini's standalone Python interpreter:

    tests/run_integration.ps1

The directory is ignored automatically when the real ``hou`` module is
unavailable (plain ``pytest`` runs, or unit-test runs where ``hou`` is
mocked into ``sys.modules``).
"""

from __future__ import annotations

# Built-in
import os
import sys
from collections import defaultdict

# Third-party
import pytest

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", "..", "houdini", "scripts", "python"
    ),
)

try:
    import hou

    _REAL_HOU = isinstance(hou.applicationVersionString(), str)
except Exception:
    _REAL_HOU = False

if not _REAL_HOU:
    collect_ignore_glob = ["*"]
else:
    import fxhoudinimcp_server.dispatcher as dispatcher
    import fxhoudinimcp_server.handlers  # noqa: F401  (registers all handlers)

    # hython is single-threaded with no UI event loop; run handlers
    # directly on this thread instead of marshalling via hdefereval.
    dispatcher.HAS_HDEFEREVAL = False

# (command, milliseconds) for every dispatched call, across the session.
_OP_TIMINGS: list[tuple[str, float]] = []

# Smoke-mode (allow_error) calls that actually failed: their success path
# is still unverified. Reported in the session summary.
_SMOKE_ERRORS: dict[str, str] = {}


@pytest.fixture(autouse=True)
def fresh_scene():
    """Start every test from an empty scene."""
    hou.hipFile.clear(suppress_save_prompt=True)
    yield


@pytest.fixture
def call():
    """Dispatch a command exactly as the HTTP bridge would.

    Returns the handler's data dict on success. With ``expect_error=True``,
    asserts the command failed and returns the error dict instead.
    """

    # Leading underscores on the bound arguments keep them from colliding
    # with handler parameters of the same name (e.g. execute_hscript's
    # "command"), which arrive via **params.
    def _call(
        _command: str,
        expect_error: bool = False,
        allow_error: bool = False,
        **params,
    ):
        result = dispatcher.dispatch(_command, params)
        _OP_TIMINGS.append((_command, result.get("timing_ms", 0.0)))
        if allow_error:
            # Smoke mode: success or a CLEAN structured error both pass.
            if result["status"] == "error":
                error = result["error"]
                assert error.get("code") != "UNKNOWN_COMMAND", error
                assert str(error.get("message", "")).strip(), (
                    f"{_command} failed with an empty error message: {error}"
                )
                _SMOKE_ERRORS.setdefault(
                    _command, str(error.get("message", ""))[:70]
                )
            return result
        if expect_error:
            assert result["status"] == "error", (
                f"{_command} unexpectedly succeeded: {result.get('data')}"
            )
            return result["error"]
        assert result["status"] == "success", (
            f"{_command} failed: {result.get('error', {}).get('message')}"
        )
        return result["data"]

    return _call


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Print per-command timing aggregates and session command coverage."""
    if not _OP_TIMINGS:
        return
    stats: dict[str, list[float]] = defaultdict(list)
    for command, ms in _OP_TIMINGS:
        stats[command].append(ms)
    rows = sorted(
        ((max(v), sum(v) / len(v), len(v), k) for k, v in stats.items()),
        reverse=True,
    )
    terminalreporter.write_sep("=", "handler timings (ms)")
    terminalreporter.write_line(
        f"{'command':<42} {'calls':>5} {'mean':>9} {'max':>9}"
    )
    for mx, mean, count, command in rows:
        terminalreporter.write_line(
            f"{command:<42} {count:>5} {mean:>9.1f} {mx:>9.1f}"
        )

    registered = set(dispatcher.list_commands())
    called = set(stats)
    untested = sorted(registered - called)
    terminalreporter.write_sep(
        "=", f"command coverage: {len(called & registered)}/{len(registered)}"
    )
    if untested:
        terminalreporter.write_line("never called this session:")
        for command in untested:
            terminalreporter.write_line(f"  {command}")
    if _SMOKE_ERRORS:
        terminalreporter.write_line(
            "smoke-mode calls that errored (success path unverified):"
        )
        for command, message in sorted(_SMOKE_ERRORS.items()):
            terminalreporter.write_line(f"  {command}: {message}")
