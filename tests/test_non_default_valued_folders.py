"""non_default_only keeps radio folders and multiparm counts.

Every Folder/FolderSet was skipped as "the tab left open": an Add SOP switched
to By Group (switcher1, a radio folder) and its point count (a multiparm) were
left out of get_parameters(non_default_only=True), get_parameters(inside=...)
and get_node_info's non_default_parameters. A network rebuilt from that answer
came back By Pattern, with no primitives and no error. A tab folder is still
skipped.

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
import fxhoudinimcp_server.handlers.node_handlers as nodes  # noqa: E402
import fxhoudinimcp_server.handlers.parameter_handlers as parameters  # noqa: E402


def _template(kind, folder_type=None):
    template = MagicMock()
    template.kind = kind
    template.type.return_value.name.return_value = kind
    template.label.return_value = kind
    template.defaultValue.return_value = (0,)
    template.tags.return_value = {}
    if folder_type is not None:
        template.folderType.return_value.name.return_value = folder_type
    return template


def _parm(name, value, kind="Int", folder_type=None):
    parm = MagicMock()
    parm.name.return_value = name
    parm.description.return_value = name
    parm.eval.return_value = value
    parm.rawValue.return_value = str(value)
    parm.componentIndex.return_value = 0
    parm.isAtDefault.return_value = value == 0
    parm.parmTemplate.return_value = _template(kind, folder_type)
    return parm


def _add_sop():
    """An Add SOP switched to By Group, with two points, on its second tab."""
    return [
        _parm("stdswitcher1", 1, "FolderSet", "Tabs"),
        _parm("points", 2, "Folder", "MultiparmBlock"),
        _parm("switcher1", 1, "FolderSet", "RadioButtons"),
        _parm("add", 4, "Menu"),
        _parm("reload", 0, "Button"),
    ]


class TestValuedFolders:
    @pytest.mark.parametrize(
        ("kind", "folder_type", "valueless"),
        [
            ("FolderSet", "Tabs", True),
            ("FolderSet", "RadioButtons", False),
            ("Folder", "MultiparmBlock", False),
            ("Folder", "ScrollingMultiparmBlock", False),
            ("Folder", "TabbedMultiparmBlock", False),
            ("Folder", "Collapsible", True),
            ("Button", None, True),
            ("Separator", None, True),
            ("Int", None, False),
        ],
    )
    def test_which_parms_carry_a_value(self, kind, folder_type, valueless):
        assert nodes._is_valueless(_template(kind, folder_type)) is valueless

    def test_a_folder_that_will_not_say_its_type_stays_valueless(self):
        template = _template("FolderSet")
        template.folderType.side_effect = RuntimeError("no folder type")
        assert nodes._is_valueless(template) is True


class TestNonDefaultKeepsRadioAndMultiparmFolders:
    @pytest.fixture(autouse=True)
    def _plain(self, monkeypatch):
        monkeypatch.setattr(parameters, "_parm_type_name", lambda pt: pt.kind)
        monkeypatch.setattr(parameters, "_serialize_value", lambda value: value)
        monkeypatch.setattr(nodes, "to_jsonable", lambda v: v)

    def _node(self, monkeypatch):
        node = MagicMock()
        node.path.return_value = "/obj/geo1/add1"
        node.type.return_value.name.return_value = "add"
        node.parms.return_value = _add_sop()
        node.isLockedHDA.return_value = False
        node.isInsideLockedHDA.return_value = False
        return node

    def test_get_parameters_on_one_node(self, monkeypatch):
        node = self._node(monkeypatch)
        monkeypatch.setattr(parameters.hou, "node", lambda path: node)
        result = parameters._get_parameters("/obj/geo1/add1", non_default_only=True)
        assert sorted(result["parameters"]) == ["add", "points", "switcher1"]

    def test_get_parameters_inside_a_network(self, monkeypatch):
        node = self._node(monkeypatch)
        parent = MagicMock()
        parent.path.return_value = "/obj/geo1"
        parent.isLockedHDA.return_value = False
        parent.isInsideLockedHDA.return_value = False
        parent.children.return_value = [node]
        monkeypatch.setattr(parameters.hou, "node", lambda path: parent)
        result = parameters._get_parameters(inside="/obj/geo1", non_default_only=True)
        assert sorted(r["parm"] for r in result["rows"]) == ["add", "points", "switcher1"]

    def test_a_radio_folder_asked_for_by_name_is_a_row(self, monkeypatch):
        node = self._node(monkeypatch)
        parent = MagicMock()
        parent.path.return_value = "/obj/geo1"
        parent.isLockedHDA.return_value = False
        parent.isInsideLockedHDA.return_value = False
        parent.children.return_value = [node]
        monkeypatch.setattr(parameters.hou, "node", lambda path: parent)
        result = parameters._get_parameters(inside="/obj/geo1", patterns=["switcher1", "points"])
        assert sorted(r["parm"] for r in result["rows"]) == ["points", "switcher1"]

    def test_get_node_info_summary(self, monkeypatch):
        summary = nodes._non_default_parms(MagicMock(), _add_sop())
        assert sorted(p["name"] for p in summary) == ["add", "points", "switcher1"]
