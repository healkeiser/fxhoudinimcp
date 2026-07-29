"""Tests for Houdini-side startup health checks."""

from __future__ import annotations

# Built-in
import os
import sys

# Third-party
import pytest

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"),
)

from fxhoudinimcp_server import startup  # noqa: E402


@pytest.fixture(autouse=True)
def reset_startup_state(monkeypatch):
    monkeypatch.setattr(startup, "_server_started", False)
    monkeypatch.setattr(startup, "_starting", False)
    monkeypatch.setattr(startup, "_port", 8100)


def test_wait_for_current_process_health_accepts_current_pid(monkeypatch):
    monkeypatch.setattr(
        startup,
        "_query_health",
        lambda port: {
            "status": "ok",
            "pid": os.getpid(),
            "houdini_version": "21.0.631",
        },
    )

    health = startup._wait_for_current_process_health(8100)

    assert health is not None
    assert health["pid"] == os.getpid()


def test_ensure_running_restarts_when_cached_state_is_stale(monkeypatch):
    calls = []
    monkeypatch.setattr(startup, "_server_started", True)
    monkeypatch.setattr(
        startup,
        "_wait_for_current_process_health",
        lambda port, timeout_seconds=0.5: None,
    )
    monkeypatch.setattr(startup, "start", lambda **kw: calls.append(kw))

    startup.ensure_running()

    assert calls == [{"wait": True}]


def test_ensure_running_keeps_live_server(monkeypatch):
    calls = []
    monkeypatch.setattr(startup, "_server_started", True)
    monkeypatch.setattr(
        startup,
        "_wait_for_current_process_health",
        lambda port, timeout_seconds=0.5: {"pid": os.getpid()},
    )
    monkeypatch.setattr(startup, "start", lambda **kw: calls.append(kw))

    startup.ensure_running()

    assert calls == []


###### Off-main-thread readiness (idea from @husman2012, PR #13)


def test_ensure_running_passes_wait_through(monkeypatch):
    """Auto-start must reach start() with wait=False, or the UI still stalls."""
    calls = []
    monkeypatch.setattr(startup, "start", lambda **kw: calls.append(kw))

    startup.ensure_running(wait=False)

    assert calls == [{"wait": False}]


def test_ensure_running_is_a_noop_while_starting(monkeypatch):
    calls = []
    monkeypatch.setattr(startup, "_starting", True)
    monkeypatch.setattr(startup, "start", lambda **kw: calls.append(kw))

    startup.ensure_running()

    assert calls == []


def test_confirm_ready_marks_running(monkeypatch):
    monkeypatch.setattr(
        startup,
        "_wait_for_current_process_health",
        lambda port: {"pid": os.getpid(), "houdini_version": "22.0.368"},
    )

    startup._confirm_ready(None)

    assert startup.is_running() is True


def test_confirm_ready_raises_when_nothing_answers(monkeypatch):
    """The synchronous path must raise so Start Server can report why."""
    monkeypatch.setattr(startup, "_wait_for_current_process_health", lambda port: None)

    with pytest.raises(RuntimeError, match="did not answer"):
        startup._confirm_ready(None)
    assert startup.is_running() is False


def test_confirm_ready_rejects_another_process(monkeypatch):
    monkeypatch.setattr(
        startup,
        "_wait_for_current_process_health",
        lambda port: {"pid": os.getpid() + 1},
    )

    with pytest.raises(RuntimeError, match="owned by another Houdini process"):
        startup._confirm_ready(None)
    assert startup.is_running() is False


def test_async_confirm_never_raises_and_clears_starting(monkeypatch, capsys):
    """A worker-thread exception would die unheard, so it must be reported."""
    monkeypatch.setattr(startup, "_starting", True)
    monkeypatch.setattr(startup, "_wait_for_current_process_health", lambda port: None)

    startup._confirm_ready_async(None)  # must not raise

    assert startup.is_starting() is False, "a failed start would wedge the menu"
    assert startup.is_running() is False
    assert "Auto-start failed" in capsys.readouterr().out


def test_async_confirm_clears_starting_on_success(monkeypatch):
    monkeypatch.setattr(startup, "_starting", True)
    monkeypatch.setattr(
        startup,
        "_wait_for_current_process_health",
        lambda port: {"pid": os.getpid(), "houdini_version": "22.0.368"},
    )

    startup._confirm_ready_async(None)

    assert startup.is_starting() is False
    assert startup.is_running() is True


def test_start_declines_while_a_start_is_in_flight(monkeypatch, capsys):
    """A menu click during auto-start must not start a second server."""
    monkeypatch.setattr(startup, "_starting", True)
    startup.start()
    assert "still starting" in capsys.readouterr().out


def test_readiness_timeout_is_generous_now_that_it_is_off_thread():
    """Off the main thread the ceiling costs nothing, so do not keep it tight."""
    assert startup._READINESS_TIMEOUT >= 15.0


###### Concurrent Houdini sessions (idea from @husman2012, PR #13)


def test_first_port_is_used_when_free():
    assert startup._pick_free_port(8100, probe=lambda port: None) == 8100


def test_skips_a_port_owned_by_another_houdini():
    """A second session used to fail outright instead of moving over."""
    other = {"pid": os.getpid() + 1}
    probe = lambda port: other if port == 8100 else None  # noqa: E731
    assert startup._pick_free_port(8100, probe=probe) == 8101


def test_skips_several_occupied_ports():
    other = {"pid": os.getpid() + 1}
    probe = lambda port: other if port < 8103 else None  # noqa: E731
    assert startup._pick_free_port(8100, probe=probe) == 8103


def test_reuses_a_port_this_process_already_serves():
    """Restarting in a session that already has a server must not move ports."""
    mine = {"pid": os.getpid()}
    probe = lambda port: mine if port == 8100 else None  # noqa: E731
    assert startup._pick_free_port(8100, probe=probe) == 8100


def test_our_own_port_wins_over_moving_on():
    """Ours at 8101 should be reused, not skipped for a free 8102."""

    def probe(port):
        if port == 8100:
            return {"pid": os.getpid() + 1}
        if port == 8101:
            return {"pid": os.getpid()}
        return None

    assert startup._pick_free_port(8100, probe=probe) == 8101


def test_raises_when_every_port_is_taken():
    other = {"pid": os.getpid() + 1}
    with pytest.raises(RuntimeError, match="No free port"):
        startup._pick_free_port(8100, probe=lambda port: other, max_tries=4)


def test_search_range_is_bounded():
    """Each failed probe costs a request, so the range must stay small."""
    assert 4 <= startup._PORT_SEARCH_RANGE <= 64
