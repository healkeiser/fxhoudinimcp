"""capture_network_editor frames the node at once, and says what it framed.

``homeToSelection()`` animates the editor's view over the next event-loop
ticks, while the capture runs in the same tick, so the image came out
mid-flight: the whole network with the node a dot in a corner, or an empty
stretch between the previous node and this one. The view is now set with
``setVisibleBounds(transition_time=0)`` and the reply carries the rect the
image shows, so the frame can be checked without opening it.
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
import fxhoudinimcp_server.handlers.viewport_handlers as viewport  # noqa: E402


def _rect(xmin, ymin, xmax, ymax):
    rect = MagicMock()
    rect.min.return_value = (xmin, ymin)
    rect.max.return_value = (xmax, ymax)
    return rect


def _node(x, y, w=1.0, h=0.3):
    node = MagicMock()
    node.position.return_value = (x, y)
    node.size.return_value = (w, h)
    return node


@pytest.fixture
def editor(monkeypatch):
    """A Network Editor pane; hou.BoundingRect hands back its four numbers."""
    pane = MagicMock()
    pane.type.return_value = "NetworkEditor"
    pane.visibleBounds.return_value = _rect(20.0, -70.0, 40.0, -50.0)
    monkeypatch.setattr(viewport.hou.ui, "paneTabs", lambda: [pane])
    monkeypatch.setattr(viewport.hou.paneTabType, "NetworkEditor", "NetworkEditor")
    monkeypatch.setattr(viewport.hou, "BoundingRect", lambda *box: box)
    monkeypatch.setattr(viewport, "_capture_pane_tab_qt", lambda pane_tab, path: None)
    return pane


def _centre(box):
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def _use_nodes(monkeypatch, nodes):
    monkeypatch.setattr(viewport.hou, "node", lambda path: nodes.get(path))


class TestNetworkEditorIsFramedAtOnce:
    def test_the_view_is_set_without_an_animated_home(self, editor, monkeypatch, tmp_path):
        _use_nodes(monkeypatch, {"/stage/TARGET": _node(30.0, -60.0)})

        viewport.capture_network_editor(str(tmp_path / "ne.png"), "/stage/TARGET")

        editor.homeToSelection.assert_not_called()
        (box,), kwargs = editor.setVisibleBounds.call_args
        assert kwargs == {"transition_time": 0.0, "set_center_when_scale_rejected": True}
        # The node sits inside the requested rect, with room around it.
        assert box[0] < 30.0 and box[1] < -60.0 and box[2] > 31.0 and box[3] > -59.7

    def test_each_capture_is_centred_on_its_own_node(self, editor, monkeypatch, tmp_path):
        # Two nodes of one size give two rects at one zoom: the case Houdini
        # ignores without set_center_when_scale_rejected.
        _use_nodes(
            monkeypatch,
            {"/stage/far": _node(30.0, -60.0), "/stage/near": _node(0.0, 0.0)},
        )
        out = str(tmp_path / "ne.png")

        viewport.capture_network_editor(out, "/stage/far")
        viewport.capture_network_editor(out, "/stage/near")

        (first,), _ = editor.setVisibleBounds.call_args_list[0]
        (second,), kwargs = editor.setVisibleBounds.call_args_list[1]
        assert _centre(first) == pytest.approx((30.5, -59.85))
        assert _centre(second) == pytest.approx((0.5, 0.15))
        assert kwargs["set_center_when_scale_rejected"] is True


class TestTheReplySaysWhatIsInTheFrame:
    def test_a_framed_node_is_reported_in_view(self, editor, monkeypatch, tmp_path):
        _use_nodes(monkeypatch, {"/stage/TARGET": _node(30.0, -60.0)})

        reply = viewport.capture_network_editor(str(tmp_path / "ne.png"), "/stage/TARGET")

        assert reply["node_path"] == "/stage/TARGET"
        assert reply["node_bounds"] == [30.0, -60.0, 31.0, -59.7]
        assert reply["visible_bounds"] == [20.0, -70.0, 40.0, -50.0]
        assert reply["node_in_view"] is True

    def test_a_view_that_did_not_reach_the_node_is_reported(self, editor, monkeypatch, tmp_path):
        # The editor still shows the previous stretch of the network.
        editor.visibleBounds.return_value = _rect(-10.0, -5.0, 10.0, 5.0)
        _use_nodes(monkeypatch, {"/stage/TARGET": _node(30.0, -60.0)})

        reply = viewport.capture_network_editor(str(tmp_path / "ne.png"), "/stage/TARGET")

        assert reply["node_in_view"] is False

    def test_without_a_node_only_the_view_is_reported(self, editor, tmp_path):
        reply = viewport.capture_network_editor(str(tmp_path / "ne.png"))

        editor.setVisibleBounds.assert_not_called()
        assert reply["visible_bounds"] == [20.0, -70.0, 40.0, -50.0]
        assert "node_bounds" not in reply
        assert "node_in_view" not in reply

    def test_an_unreadable_view_leaves_the_answer_open(self, editor, monkeypatch, tmp_path):
        editor.visibleBounds.side_effect = RuntimeError("no view")
        _use_nodes(monkeypatch, {"/stage/TARGET": _node(30.0, -60.0)})

        reply = viewport.capture_network_editor(str(tmp_path / "ne.png"), "/stage/TARGET")

        assert reply["success"] is True
        assert reply["visible_bounds"] is None
        assert reply["node_in_view"] is None
