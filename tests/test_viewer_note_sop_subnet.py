"""A capture names a SOP subnet the viewer was taken into.

create_node, connect_nodes and set_node_flags inside a SOP subnet take the
network editor there, and the Scene Viewer with it. Inside the subnet the
viewer draws the subnet's display node only, and the next capture showed a
fragment of the object with nothing in the reply to say so: viewer_note
covered DOP networks only.

hou is mocked here; the live check ran on Houdini 22.0.466."""

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
import fxhoudinimcp_server.ui as ui  # noqa: E402


class _Category:
    def __init__(self, name):
        self.name = name


_OBJ, _SOP, _DOP = _Category("Object"), _Category("Sop"), _Category("Dop")


class _Node:
    def __init__(self, path, category, parent=None, display=None, children=_SOP):
        self._path, self._category, self._parent = path, category, parent
        self._display, self._children = display, children

    def path(self):
        return self._path

    def parent(self):
        return self._parent

    def type(self):
        return MagicMock(category=MagicMock(return_value=self._category))

    def childTypeCategory(self):  # noqa: N802 - HOM's name
        return self._children

    def displayNode(self):  # noqa: N802
        return self._display


@pytest.fixture
def categories(monkeypatch):
    monkeypatch.setattr(ui.hou, "objNodeTypeCategory", lambda: _OBJ)
    monkeypatch.setattr(ui.hou, "sopNodeTypeCategory", lambda: _SOP)
    monkeypatch.setattr(ui.hou, "dopNodeTypeCategory", lambda: _DOP)
    monkeypatch.setattr(ui, "hidden_by_visible_objects", lambda viewer: [])


def _geo():
    obj = _Node("/obj/geo1", _OBJ)
    obj._display = _Node("/obj/geo1/OUT", _SOP, obj)
    sub = _Node("/obj/geo1/core", _SOP, obj)
    sub._display = _Node("/obj/geo1/core/core_out", _SOP, sub)
    return obj, sub


def _viewer(network):
    viewer = MagicMock()
    viewer.pwd.return_value = network
    return viewer


class TestSubnetViewIsNamed:
    def test_a_sop_subnet_names_what_is_drawn_and_the_way_out(self, categories):
        _, sub = _geo()
        context = ui.viewer_context(_viewer(sub))
        assert context["viewer_network"] == "/obj/geo1/core"
        note = context["viewer_note"]
        assert "SOP subnet /obj/geo1/core" in note
        assert "/obj/geo1/core/core_out" in note
        assert "/obj/geo1/OUT" in note
        assert "set_current_network to /obj/geo1" in note

    def test_a_nested_subnet_climbs_to_the_object(self, categories):
        _, sub = _geo()
        inner = _Node("/obj/geo1/core/inner", _SOP, sub)
        note = ui.viewer_context(_viewer(inner))["viewer_note"]
        assert "set_current_network to /obj/geo1 " in note
        assert "display node (none)" in note

    def test_the_object_level_has_no_note(self, categories):
        obj, _ = _geo()
        assert ui.viewer_context(_viewer(obj)) == {"viewer_network": "/obj/geo1"}

    def test_a_dop_network_keeps_its_own_note(self, categories):
        obj, _ = _geo()
        dopnet = _Node("/obj/geo1/dopnet1", _SOP, obj, children=_DOP)
        assert "DOP network" in ui.viewer_context(_viewer(dopnet))["viewer_note"]
