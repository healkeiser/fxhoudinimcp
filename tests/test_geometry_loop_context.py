"""get_geometry_info on a node inside a for-each loop passed off one slice as the result.

`geometry()` cooks a dirty node on the spot, but a node between a block_begin
and its block_end is then cooked standalone, outside the loop: no iteration
metadata, one slice at best. A healthy floor inside a loop read "bbox 0 at 4
points" that way, and the session went hunting a defect that was not there.
The reply now carries `cook_state` (whether this call cooked the node, its cook
count, and the loop it sits in) plus a warning that names the block_end to read.

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
import fxhoudinimcp_server.handlers.geometry_handlers as geometry  # noqa: E402


def _node(path, type_name="xform"):
    node = MagicMock()
    node.path.return_value = path
    node.name.return_value = path.rsplit("/", 1)[-1]
    node.type.return_value.name.return_value = type_name
    return node


def _loop():
    """box1 -> fb (block_begin) -> xform_loop -> fe (block_end), all in /obj/geo1."""
    parent = MagicMock()
    begin = _node("/obj/geo1/fb", "block_begin")
    inner = _node("/obj/geo1/xform_loop", "xform")
    end = _node("/obj/geo1/fe", "block_end")
    other = _node("/obj/geo1/box1", "box")
    inner.parent.return_value = parent
    inner.inputAncestors.return_value = [begin, other]
    end.inputAncestors.return_value = [inner, begin, other]
    end.parm.return_value.evalAsNode.return_value = begin
    parent.children.return_value = [other, begin, inner, end]
    return inner, begin, end


def _outside():
    node = _node("/obj/geo1/box1", "box")
    node.parent.return_value.children.return_value = [node]
    node.inputAncestors.return_value = []
    node.needsToCook.return_value = False
    node.cookCount.return_value = 3
    return node


def _with_geometry(node, calls):
    """Give *node* an empty but well-formed geometry and log when it is read."""
    geo = MagicMock()
    geo.intrinsicValue.side_effect = lambda name: 0
    bbox = geo.boundingBox.return_value
    bbox.minvec.return_value = (0.0, 0.0, 0.0)
    bbox.maxvec.return_value = (0.0, 0.0, 0.0)
    bbox.sizevec.return_value = (0.0, 0.0, 0.0)
    bbox.center.return_value = (0.0, 0.0, 0.0)
    for getter in ("pointAttribs", "primAttribs", "vertexAttribs", "globalAttribs"):
        getattr(geo, getter).return_value = []

    def read(*_args):
        calls.append("geometry")
        return geo

    node.geometry.side_effect = read
    return node


@pytest.fixture
def lookup(monkeypatch):
    """Route hou.node to one fake node; update mode is Auto unless a test says otherwise."""
    nodes: dict[str, MagicMock] = {}
    monkeypatch.setattr(geometry.hou, "node", lambda path: nodes.get(path))
    monkeypatch.setattr(geometry, "update_mode_warning", lambda: None)
    return nodes


class TestLoopContext:
    def test_a_node_between_begin_and_end_is_inside_the_loop(self):
        inner, _begin, _end = _loop()
        assert geometry._loop_context(inner) == {"begin": "/obj/geo1/fb", "end": "/obj/geo1/fe"}

    def test_a_node_feeding_the_end_but_not_fed_by_the_begin_is_outside(self):
        inner, _begin, _end = _loop()
        inner.inputAncestors.return_value = []  # nothing upstream: the loop's input, not its body
        assert geometry._loop_context(inner) is None

    def test_a_node_the_end_does_not_depend_on_is_outside(self):
        inner, _begin, end = _loop()
        end.inputAncestors.return_value = [_begin]
        assert geometry._loop_context(inner) is None

    def test_a_node_without_a_parent_is_outside(self):
        node = _node("/obj", "obj")
        node.parent.return_value = None
        assert geometry._loop_context(node) is None


class TestCookState:
    def test_names_the_loop_and_whether_this_call_cooked(self):
        inner, _begin, _end = _loop()
        inner.needsToCook.return_value = True
        inner.cookCount.return_value = 1
        state, warnings = geometry._cook_state(inner)
        assert state["cooked_for_this_call"] is True
        assert state["cook_count"] == 1
        assert state["inside_loop"] is True
        assert state["loop"] == {"begin": "/obj/geo1/fb", "end": "/obj/geo1/fe"}
        assert len(warnings) == 1
        assert "standalone" in warnings[0] and "/obj/geo1/fe" in warnings[0]

    def test_a_cooked_node_outside_a_loop_is_quiet(self):
        state, warnings = geometry._cook_state(_outside())
        assert state == {"cooked_for_this_call": False, "cook_count": 3}
        assert warnings == []


class TestGeometryInfoCarriesTheCookState:
    def test_inside_a_loop_the_reply_warns_and_names_the_block_end(self, lookup):
        calls: list[str] = []
        inner, _begin, _end = _loop()
        inner.needsToCook.side_effect = lambda: calls.append("needsToCook") or True
        inner.cookCount.return_value = 1
        lookup["/obj/geo1/xform_loop"] = _with_geometry(inner, calls)

        result = geometry._get_geometry_info(node_path="/obj/geo1/xform_loop")

        assert result["cook_state"]["inside_loop"] is True
        assert result["cook_state"]["cooked_for_this_call"] is True
        assert result["cook_state"]["loop"]["end"] == "/obj/geo1/fe"
        assert len(result["warnings"]) == 1
        assert "/obj/geo1/fe" in result["warnings"][0]
        # geometry() cooks the node, so the state has to be read before it.
        assert calls == ["needsToCook", "geometry"]

    def test_outside_a_loop_there_is_no_warning(self, lookup):
        lookup["/obj/geo1/box1"] = _with_geometry(_outside(), [])
        result = geometry._get_geometry_info(node_path="/obj/geo1/box1")
        assert result["cook_state"] == {"cooked_for_this_call": False, "cook_count": 3}
        assert "warnings" not in result

    def test_the_update_mode_warning_is_kept_alongside(self, lookup, monkeypatch):
        monkeypatch.setattr(geometry, "update_mode_warning", lambda: "Update mode is 'manual': …")
        inner, _begin, _end = _loop()
        inner.needsToCook.return_value = False
        inner.cookCount.return_value = 4
        lookup["/obj/geo1/xform_loop"] = _with_geometry(inner, [])
        result = geometry._get_geometry_info(node_path="/obj/geo1/xform_loop")
        assert len(result["warnings"]) == 2
        assert result["warnings"][1].startswith("Update mode is 'manual'")
