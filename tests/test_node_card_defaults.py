"""get_node_card gives a default for toggles, menus and ramps.

list() of a scalar defaultValue() raised and was swallowed, so a toggle and a
menu had no default; 17 of resample's parameters came back without one.
A ramp's default is its keys (`ramp_default`), not the key count.

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
import fxhoudinimcp_server.handlers.graph_handlers as graph  # noqa: E402

hou = graph.hou


def _template(name, kind, default, tags=None):
    template = MagicMock()
    template.name.return_value = name
    template.label.return_value = name.title()
    template.type.return_value = getattr(hou.parmTemplateType, kind)
    template.type.return_value.name.return_value = kind
    template.numComponents.return_value = 1
    template.isHidden.return_value = False
    template.defaultValue.return_value = default
    template.defaultExpression.return_value = ""
    template.menuItems.return_value = ("a", "b") if kind == "Menu" else ()
    template.menuLabels.return_value = ("A", "B") if kind == "Menu" else ()
    template.tags.return_value = tags or {}
    return template


class TestCardDefaults:
    @pytest.fixture(autouse=True)
    def _fresh(self, monkeypatch):
        monkeypatch.setattr(graph, "_CONNECTOR_CACHE", {})
        monkeypatch.setattr(graph, "_definition_stamp", lambda node_type: None)
        monkeypatch.setattr(graph, "_container_for", lambda category: "geo")
        monkeypatch.setattr(graph, "_help_text", lambda resolved, context: None)

    def _card(self, monkeypatch, templates):
        root = MagicMock()
        probe = MagicMock()
        probe.parms.return_value = []
        root.createNode.return_value.createNode.return_value = probe
        monkeypatch.setattr(hou, "node", lambda path: root)
        resolved = MagicMock()
        resolved.name.return_value = "resample"
        resolved.minNumInputs.return_value = 1
        resolved.maxNumInputs.return_value = 1
        resolved.maxNumOutputs.return_value = 1
        resolved.parmTemplateGroup.return_value.entriesWithoutFolders.return_value = templates
        resolved.parmTemplateGroup.return_value.entries.return_value = []
        monkeypatch.setattr(hou, "nodeTypeCategories", lambda: {"Sop": MagicMock()})
        monkeypatch.setattr(graph, "_resolve_node_type", lambda category, name: resolved)
        card = graph.get_node_card("resample", "Sop")
        return {p["name"]: p for p in card["parms"]}

    def test_toggle_menu_and_float_all_have_a_default(self, monkeypatch):
        parms = self._card(
            monkeypatch,
            [
                _template("dolength", "Toggle", True),
                _template("method", "Menu", 1),
                _template("length", "Float", (0.1,)),
            ],
        )
        assert parms["dolength"]["default"] is True
        assert parms["method"]["default"] == 1
        assert parms["length"]["default"] == [0.1]

    def test_a_ramp_gives_its_keys_not_a_value(self, monkeypatch):
        keys = (
            "1pos ( 0 ) 1value ( 0 ) 1interp ( linear ) 2pos ( 1 ) 2value ( 1 ) 2interp ( linear )"
        )
        parms = self._card(
            monkeypatch, [_template("ramp", "Ramp", 2, tags={"rampfloatdefault": keys})]
        )
        assert "default" not in parms["ramp"]
        assert parms["ramp"]["ramp_default"] == keys
