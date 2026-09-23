"""verify_network repeated a node's old error after its cause was fixed.

`node.errors()` is the verdict of the node's last cook. A File SOP off the
display chain, cooked once with a missing path and then pointed at a file
that exists, still listed "Unable to read file" with needsToCook() True, and
verify_network called it broken. It only ever cooked the display node, so
nothing refreshed that verdict. Such a node is now marked `stale` and named
in `stale_error_nodes`, and `force_cook=True` recooks every erroring node
before the report is taken.

hou is mocked here; the live check ran on Houdini 22.0.429.
"""

from __future__ import annotations

# Built-in
import os
import sys
from unittest.mock import MagicMock

sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Internal
import fxhoudinimcp_server.handlers.graph_handlers as graph  # noqa: E402

hou = graph.hou


class _OperationFailed(Exception):
    """Stands in for hou.OperationFailed, which the hou stub does not define."""


class _Node:
    """A node whose errors are what its last cook left.

    `errors_after_cook` is what a forced cook leaves: an empty list for a
    node whose cause was fixed, the same error for a real one.
    """

    def __init__(self, path, errors=(), needs_to_cook=False, errors_after_cook=(), on_cook=None):
        self._path = path
        self._errors = list(errors)
        self._needs_to_cook = needs_to_cook
        self._after = list(errors_after_cook)
        self._on_cook = on_cook
        self.cooks = []

    def path(self):
        return self._path

    def name(self):
        return self._path.rsplit("/", 1)[-1]

    def type(self):
        node_type = MagicMock()
        node_type.name.return_value = "file"
        return node_type

    def errors(self):
        return tuple(self._errors)

    def warnings(self):
        return ()

    def isBypassed(self):
        return False

    def isDisplayFlagSet(self):
        return False

    def needsToCook(self):
        return self._needs_to_cook

    def cook(self, force=False):
        self.cooks.append(force)
        self._errors = list(self._after)
        self._needs_to_cook = False
        if self._on_cook is not None:
            self._on_cook()


def _network(monkeypatch, *children):
    display = MagicMock()
    display.path.return_value = "/obj/geo1/OUT"
    parent = MagicMock()
    parent.displayNode.return_value = display
    parent.children.return_value = list(children)
    monkeypatch.setattr(hou, "node", lambda path: parent)
    monkeypatch.setattr(hou, "OperationFailed", _OperationFailed, raising=False)
    monkeypatch.setattr(graph, "_geometry_summary", lambda node: None)
    monkeypatch.setattr(graph, "license_error", lambda errors: None)
    return display


def _row(result, path):
    return next(r for r in result["nodes"] if r["path"] == path)


class TestAStaleErrorIsNamed:
    def test_an_error_on_a_node_that_needs_a_cook_is_stale(self, monkeypatch):
        fixed = _Node("/obj/geo1/file1", ["Unable to read file"], needs_to_cook=True)
        display = _network(monkeypatch, fixed)

        result = graph.verify_network("/obj/geo1")

        assert result["stale_error_nodes"] == ["/obj/geo1/file1"]
        assert _row(result, "/obj/geo1/file1")["stale"] is True
        # The error is still reported: stale is not the same as fixed.
        assert result["error_nodes"] == ["/obj/geo1/file1"]
        assert result["healthy"] is False
        assert "force_cook=True" in result["note"]
        assert result["force_cook"] is False
        assert fixed.cooks == []
        display.cook.assert_called_once_with(force=False)

    def test_a_current_error_is_not_stale(self, monkeypatch):
        broken = _Node("/obj/geo1/file1", ["Unable to read file"], needs_to_cook=False)
        _network(monkeypatch, broken)

        result = graph.verify_network("/obj/geo1")

        assert result["stale_error_nodes"] == []
        assert result["error_nodes"] == ["/obj/geo1/file1"]
        assert "stale" not in _row(result, "/obj/geo1/file1")
        assert "note" not in result

    def test_a_dirty_node_without_errors_is_not_stale(self, monkeypatch):
        dirty = _Node("/obj/geo1/box1", needs_to_cook=True)
        _network(monkeypatch, dirty)

        result = graph.verify_network("/obj/geo1")

        assert result["stale_error_nodes"] == []
        assert result["healthy"] is True
        assert "stale" not in _row(result, "/obj/geo1/box1")


class TestForceCookRejudges:
    def test_force_cook_recooks_a_stale_node_and_judges_the_fresh_cook(self, monkeypatch):
        fixed = _Node("/obj/geo1/file1", ["Unable to read file"], needs_to_cook=True)
        display = _network(monkeypatch, fixed)

        result = graph.verify_network("/obj/geo1", force_cook=True)

        assert fixed.cooks == [True]
        display.cook.assert_called_once_with(force=True)
        assert result["error_nodes"] == []
        assert result["stale_error_nodes"] == []
        assert result["healthy"] is True
        assert result["force_cook"] is True
        assert _row(result, "/obj/geo1/file1")["recooked"] is True
        assert "note" not in result

    def test_force_cook_clears_an_error_on_a_node_that_is_not_dirty(self, monkeypatch):
        # An error left by evaluating a parm outside a cook: the node does
        # not need a cook, and only a forced cook of the node itself clears it.
        pinned = _Node("/obj/geo1/group1", ["Unable to evaluate expression"])
        _network(monkeypatch, pinned)

        result = graph.verify_network("/obj/geo1", force_cook=True)

        assert pinned.cooks == [True]
        assert result["healthy"] is True

    def test_a_real_error_survives_force_cook(self, monkeypatch):
        broken = _Node(
            "/obj/geo1/file1",
            ["Unable to read file"],
            needs_to_cook=True,
            errors_after_cook=["Unable to read file"],
        )
        _network(monkeypatch, broken)

        result = graph.verify_network("/obj/geo1", force_cook=True)

        assert result["error_nodes"] == ["/obj/geo1/file1"]
        assert result["healthy"] is False
        row = _row(result, "/obj/geo1/file1")
        assert row["recooked"] is True
        assert "stale" not in row

    def test_force_cook_leaves_clean_nodes_alone(self, monkeypatch):
        clean = _Node("/obj/geo1/box1", needs_to_cook=True)
        _network(monkeypatch, clean)

        result = graph.verify_network("/obj/geo1", force_cook=True)

        assert clean.cooks == []
        assert "recooked" not in _row(result, "/obj/geo1/box1")

    def test_reports_are_taken_after_every_recook(self, monkeypatch):
        # Recooking a node cooks its inputs, and an input listed earlier can
        # pick up an error of its own; its row must show it.
        upstream = _Node("/obj/geo1/box1")

        def cook_the_input():
            upstream._errors = ["Invalid size"]

        downstream = _Node(
            "/obj/geo1/file1",
            ["Unable to read file"],
            needs_to_cook=True,
            on_cook=cook_the_input,
        )
        _network(monkeypatch, upstream, downstream)

        result = graph.verify_network("/obj/geo1", force_cook=True)

        assert result["error_nodes"] == ["/obj/geo1/box1"]

    def test_a_cook_that_fails_still_reports_the_node(self, monkeypatch):
        broken = _Node("/obj/geo1/file1", ["Unable to read file"], needs_to_cook=True)

        def fail(force=False):
            broken.cooks.append(force)
            raise _OperationFailed("cook failed")

        broken.cook = fail
        _network(monkeypatch, broken)

        result = graph.verify_network("/obj/geo1", force_cook=True)

        assert broken.cooks == [True]
        assert result["error_nodes"] == ["/obj/geo1/file1"]
        assert _row(result, "/obj/geo1/file1")["recooked"] is True
