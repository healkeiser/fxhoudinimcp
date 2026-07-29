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
    os.path.join(os.path.dirname(__file__), "..", "..", "houdini", "scripts", "python"),
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

# How each command was exercised, which is the part "188/188 covered" does not say.
# Coverage counts dispatches; it cannot distinguish a command whose failure is
# asserted from one that was called once inside a try/except. Six real bugs shipped
# behind a full coverage number -- start_render, export_file and write_cache all
# reported success for writes that never happened -- because every test asked "does
# this return" and none asked "does it admit when it fails".
#
# Modes recorded per command:
#   "smoke"    - allow_error=True: the answer is not asserted at all
#   "success"  - a plain call, so status success was asserted
#   "raises"   - expect_error=True: the error path is asserted
#   "reports"  - a plain call that came back with data success False, i.e. the
#                handler's own reported-failure branch ran under a passing test.
#                Needed because a tool that returns {"success": False} rather than
#                raising is invisible to expect_error.
_CALL_MODES: dict[str, set[str]] = defaultdict(set)


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
        assert_failure: bool = False,
        **params,
    ):
        result = dispatcher.dispatch(_command, params)
        _OP_TIMINGS.append((_command, result.get("timing_ms", 0.0)))
        if assert_failure:
            # "This must not report success, by either route." Handlers signal
            # failure two ways -- raising, or returning success: False -- and a
            # table of bad inputs should not have to know which a given handler
            # picked. allow_error cannot express this: it accepts success too, and
            # records the call as a smoke test that asserted nothing.
            if result["status"] == "error":
                _CALL_MODES[_command].add("raises")
                message = str(result["error"].get("message", ""))
                assert message.strip(), f"{_command} failed with an empty message"
                return result["error"]
            data = result.get("data") or {}
            assert isinstance(data, dict) and data.get("success") is False, (
                f"{_command} reported success for input that should have failed: {data}"
            )
            _CALL_MODES[_command].add("reports")
            return data
        if allow_error:
            # Smoke mode: success or a CLEAN structured error both pass.
            _CALL_MODES[_command].add("smoke")
            if result["status"] == "error":
                error = result["error"]
                assert error.get("code") != "UNKNOWN_COMMAND", error
                assert str(error.get("message", "")).strip(), (
                    f"{_command} failed with an empty error message: {error}"
                )
                _SMOKE_ERRORS.setdefault(_command, str(error.get("message", ""))[:70])
            return result
        if expect_error:
            _CALL_MODES[_command].add("raises")
            assert result["status"] == "error", (
                f"{_command} unexpectedly succeeded: {result.get('data')}"
            )
            return result["error"]
        assert result["status"] == "success", (
            f"{_command} failed: {result.get('error', {}).get('message')}"
        )
        data = result["data"]
        _CALL_MODES[_command].add(
            # A handler that reports its own failure instead of raising exercises a
            # different branch, and one no expect_error test can reach.
            "reports" if isinstance(data, dict) and data.get("success") is False else "success"
        )
        return data

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
    terminalreporter.write_line(f"{'command':<42} {'calls':>5} {'mean':>9} {'max':>9}")
    for mx, mean, count, command in rows:
        terminalreporter.write_line(f"{command:<42} {count:>5} {mean:>9.1f} {mx:>9.1f}")

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
        terminalreporter.write_line("smoke-mode calls that errored (success path unverified):")
        for command, message in sorted(_SMOKE_ERRORS.items()):
            terminalreporter.write_line(f"  {command}: {message}")

    _report_failure_coverage(terminalreporter, registered)


def _report_failure_coverage(terminalreporter, registered: set[str]) -> None:
    """How many commands are asserted to FAIL correctly, not merely to run.

    The number above counts dispatches. This one counts commands with a test that
    makes them go wrong and checks what they say about it, which is the property
    that was missing when start_render, export_file and write_cache all shipped
    reporting success for writes that never happened.
    """
    # Mutually exclusive and exhaustive, so the four numbers add up to the total.
    # A first version reported 16 + 125 + 42 against 188 and left five commands in
    # no bucket at all -- the ones called in both smoke and plain mode. Publishing a
    # coverage number with an unexplained hole in it is the habit this whole branch
    # is about.
    failing: set[str] = set()
    success_only: set[str] = set()
    smoke_only: set[str] = set()
    never: set[str] = set()
    for command in registered:
        modes = _CALL_MODES[command]
        if modes & {"raises", "reports"}:
            failing.add(command)
        elif "success" in modes:
            success_only.add(command)
        elif modes:
            smoke_only.add(command)
        else:
            never.add(command)

    total = len(registered)
    assert len(failing) + len(success_only) + len(smoke_only) + len(never) == total
    terminalreporter.write_sep("=", f"failure-path coverage: {len(failing)}/{total}")
    terminalreporter.write_line(
        f"  {len(failing):>3} asserted to fail correctly (error raised or reported)"
    )
    terminalreporter.write_line(
        f"  {len(success_only):>3} success path only -- never made to go wrong"
    )
    terminalreporter.write_line(f"  {len(smoke_only):>3} smoke only -- the answer is not asserted")
    terminalreporter.write_line(f"  {len(never):>3} never called")
    if failing:
        terminalreporter.write_line("asserted to fail correctly:")
        for command in sorted(failing):
            terminalreporter.write_line(f"  {command} ({','.join(sorted(_CALL_MODES[command]))})")
    if smoke_only:
        terminalreporter.write_line("smoke only (called, but nothing about the answer checked):")
        for command in sorted(smoke_only):
            terminalreporter.write_line(f"  {command}")
