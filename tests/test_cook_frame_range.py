"""cook_frame_range has no deadline and is stopped from Houdini's progress bar.

A session cooked 24 frames of a sparse pyro sim at 13 s a frame: the command
ran into the plugin's 120 s deadline while Houdini kept cooking, and the next
command timed out queued behind it. The range now runs under
hou.InterruptableOperation with no dispatcher deadline, like write_cache, and
a stop from the progress bar answers with the frames cooked before it.

hou is mocked here; the live check ran on Houdini 22.0.429.
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
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Internal
import fxhoudinimcp_server.dispatcher as dispatcher  # noqa: E402
import fxhoudinimcp_server.handlers.graph_handlers as graph  # noqa: E402

hou = graph.hou


class _Interrupted(Exception):
    pass


class _Failed(Exception):
    pass


class _Operation:
    """hou.InterruptableOperation: the progress bar, stopped after *stop_after* updates."""

    def __init__(self, stop_after=None):
        self.stop_after = stop_after
        self.updates = []

    def __call__(self, *args, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def updateLongProgress(self, fraction, text):  # noqa: N802
        if self.stop_after is not None and len(self.updates) >= self.stop_after:
            raise _Interrupted("interrupted")
        self.updates.append(text)


@pytest.fixture
def node(monkeypatch):
    node = MagicMock()
    node.errors.return_value = []
    node.warnings.return_value = []
    monkeypatch.setattr(hou, "node", lambda path: node, raising=False)
    monkeypatch.setattr(hou, "OperationInterrupted", _Interrupted, raising=False)
    monkeypatch.setattr(hou, "OperationFailed", _Failed, raising=False)
    monkeypatch.setattr(hou, "setFrame", lambda frame: None, raising=False)
    monkeypatch.setattr(hou, "frame", lambda: 1.0, raising=False)
    monkeypatch.setattr(hou.playbar, "frameRange", lambda: (1, 10), raising=False)
    monkeypatch.setattr(graph, "_frame_measurement", lambda *args: {"points": 1})
    return node


def test_a_stop_from_the_progress_bar_answers_with_the_frames_cooked(node, monkeypatch):
    monkeypatch.setattr(hou, "InterruptableOperation", _Operation(stop_after=3), raising=False)
    result = graph.cook_frame_range("/obj/sim", start=1, end=10)
    assert result["frames_cooked"] == 3
    assert result["interrupted"] is True
    assert result["interrupted_at_frame"] == 4.0
    assert "frame 4" in result["interrupted_note"]


def test_a_cook_stopped_midway_is_not_a_cook_error(node, monkeypatch):
    monkeypatch.setattr(hou, "InterruptableOperation", _Operation(), raising=False)
    node.cook.side_effect = [None, _Interrupted("interrupted")]
    result = graph.cook_frame_range("/obj/sim", start=1, end=10)
    assert result["frames_cooked"] == 1
    assert result["interrupted_at_frame"] == 2.0
    assert "cook_error" not in result["frames"][0]


def test_a_whole_range_says_nothing_of_a_stop_and_shows_progress(node, monkeypatch):
    operation = _Operation()
    monkeypatch.setattr(hou, "InterruptableOperation", operation, raising=False)
    result = graph.cook_frame_range("/obj/sim", start=1, end=4)
    assert result["frames_cooked"] == 4
    assert "interrupted" not in result
    assert operation.updates == ["Frame 1 (1/4)", "Frame 2 (2/4)", "Frame 3 (3/4)", "Frame 4 (4/4)"]


def test_a_failed_frame_is_still_data_and_the_range_goes_on(node, monkeypatch):
    monkeypatch.setattr(hou, "InterruptableOperation", _Operation(), raising=False)
    node.cook.side_effect = [None, _Failed("Solver failed\nmore"), None]
    result = graph.cook_frame_range("/obj/sim", start=1, end=3)
    assert result["frames_cooked"] == 3
    assert result["frames"][1]["cook_error"] == "Solver failed"
    assert "interrupted" not in result


def test_the_range_has_no_deadline(monkeypatch):
    # Every install writes FXHOUDINIMCP_TIMEOUT=120; it must not reach here.
    monkeypatch.setenv("FXHOUDINIMCP_TIMEOUT", "120")
    monkeypatch.delenv("FXHOUDINIMCP_TIMEOUT_GRAPH_COOK_FRAME_RANGE", raising=False)
    assert dispatcher.command_timeout("graph.cook_frame_range") is None
    assert "progress bar" in dispatcher._TIMEOUT_HINTS["graph.cook_frame_range"]
    monkeypatch.setenv("FXHOUDINIMCP_TIMEOUT_GRAPH_COOK_FRAME_RANGE", "600")
    assert dispatcher.command_timeout("graph.cook_frame_range") == 600.0
