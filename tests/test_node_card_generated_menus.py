"""get_node_card showed a script-generated menu as a Menu with no items.

`filemerge::2.0` promotes `loadtype` from an inner `file1`, and its items come
from the script `opmenu -l -a file1 loadtype`. The type's template answers
menuItems() with an empty tuple, so the card carried `"type": "Menu"` and no
`menu` key, and a session took its tokens off the `file` SOP's card instead.
A live parm runs the script. The card already makes a throwaway probe for the
connectors, so the same probe now answers the menu: `menu`, `menu_labels`,
`menu_source: "generator"` and the script in `menu_generator`.

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
import fxhoudinimcp_server.handlers.graph_handlers as graph  # noqa: E402

hou = graph.hou

LOADTYPE_ITEMS = ("full", "infobbox", "info", "points", "delayed", "packedseq", "packedgeo")
LOADTYPE_LABELS = (
    "All Geometry",
    "Bounding Box",
    "Info",
    "Point Cloud",
    "Packed Disk Primitive",
    "Packed Disk Sequence",
    "Packed Geometry",
)
GENERATOR = "opmenu -l -a file1 loadtype"


def _parm(name, items=(), labels=(), template_items=(), generator="", menu_type=None):
    parm = MagicMock()
    menu_type = hou.parmTemplateType.Menu if menu_type is None else menu_type
    parm.name.return_value = name
    parm.menuItems.return_value = tuple(items)
    parm.menuLabels.return_value = tuple(labels)
    template = MagicMock()
    template.menuItems.return_value = tuple(template_items)
    template.itemGeneratorScript.return_value = generator
    template.type.return_value = menu_type
    parm.parmTemplate.return_value = template
    return parm


def _template(name, items=(), label=None, labels=None):
    template = MagicMock()
    template.name.return_value = name
    template.label.return_value = label or name.title()
    template.type.return_value.name.return_value = "Menu"
    template.numComponents.return_value = 1
    template.isHidden.return_value = False
    template.defaultValue.return_value = (0,)
    template.menuItems.return_value = tuple(items)
    template.menuLabels.return_value = tuple(items if labels is None else labels)
    return template


def _probe(parms):
    probe = MagicMock()
    probe.parms.return_value = list(parms)
    probe.inputNames.return_value = ["input1"]
    probe.inputLabels.return_value = ["Input 1"]
    probe.inputDataTypes.return_value = []
    probe.outputNames.return_value = ["output1"]
    probe.outputLabels.return_value = ["Output 1"]
    return probe


class TestGeneratedMenusOfAProbe:
    def test_a_script_generated_menu_is_read_off_the_live_parm(self):
        probe = _probe(
            [
                _parm("loadtype", LOADTYPE_ITEMS, LOADTYPE_LABELS, generator=GENERATOR),
                _parm("static", template_items=("a", "b")),
                _parm("plain"),
            ]
        )
        generated = graph._generated_menus_of(probe)
        assert set(generated) == {"loadtype"}
        assert generated["loadtype"]["items"] == list(LOADTYPE_ITEMS)
        assert generated["loadtype"]["labels"][0] == "All Geometry"
        assert generated["loadtype"]["generator"] == GENERATOR

    def test_a_static_menu_is_left_to_the_template(self):
        probe = _probe([_parm("group", template_items=("a",), generator="x")])
        assert graph._generated_menus_of(probe) == {}

    def test_a_suggestion_menu_is_left_out(self):
        # attribwrangle's snippet (StringReplace) and group pickers
        # (StringToggle): their items are suggestions, not tokens.
        snippet = _parm(
            "snippet", ("// code",), generator="x", menu_type=hou.parmTemplateType.String
        )
        snippet.parmTemplate.return_value.menuType.return_value = "replace"
        assert graph._generated_menus_of(_probe([snippet])) == {}

    def test_a_generator_that_yields_nothing_still_names_its_script(self):
        probe = _probe([_parm("loadtype", generator=GENERATOR)])
        assert graph._generated_menus_of(probe) == {"loadtype": {"generator": GENERATOR}}

    def test_one_failing_parm_does_not_lose_the_others(self):
        broken = _parm("broken", generator="x")
        broken.menuItems.side_effect = RuntimeError("script error")
        probe = _probe([broken, _parm("loadtype", LOADTYPE_ITEMS, generator=GENERATOR)])
        assert set(graph._generated_menus_of(probe)) == {"loadtype"}


class TestTheCardReadsGeneratedMenus:
    @pytest.fixture(autouse=True)
    def _fresh(self, monkeypatch):
        monkeypatch.setattr(graph, "_CONNECTOR_CACHE", {})
        monkeypatch.setattr(graph, "_definition_stamp", lambda node_type: None)
        monkeypatch.setattr(graph, "_container_for", lambda category: "geo")
        monkeypatch.setattr(graph, "_help_text", lambda resolved, context: None)

    def _card(self, monkeypatch, templates, probe, **kwargs):
        root = MagicMock()
        scratch = MagicMock()
        root.createNode.return_value = scratch
        scratch.createNode.return_value = probe
        monkeypatch.setattr(hou, "node", lambda path: root)

        resolved = MagicMock()
        resolved.name.return_value = "filemerge::2.0"
        resolved.description.return_value = "File Merge"
        resolved.minNumInputs.return_value = 0
        resolved.maxNumInputs.return_value = 0
        resolved.maxNumOutputs.return_value = 1
        resolved.parmTemplateGroup.return_value.entriesWithoutFolders.return_value = templates
        resolved.parmTemplateGroup.return_value.entries.return_value = []
        monkeypatch.setattr(hou, "nodeTypeCategories", lambda: {"Sop": MagicMock()})
        monkeypatch.setattr(graph, "_resolve_node_type", lambda category, name: resolved)
        card = graph.get_node_card("filemerge", "Sop", **kwargs)
        return card, root

    def test_the_card_lists_the_generated_items_with_labels_and_source(self, monkeypatch):
        probe = _probe([_parm("loadtype", LOADTYPE_ITEMS, LOADTYPE_LABELS, generator=GENERATOR)])
        card, _ = self._card(monkeypatch, [_template("loadtype")], probe, parm_filter="loadtype")
        (entry,) = card["parms"]
        assert entry["menu"] == list(LOADTYPE_ITEMS)
        assert entry["menu_labels"] == list(LOADTYPE_LABELS)
        assert entry["menu_source"] == "generator"
        assert entry["menu_generator"] == GENERATOR
        assert "note" not in entry
        assert card["connectors_probed"] is True

    def test_a_static_menu_keeps_the_template_and_says_so(self, monkeypatch):
        probe = _probe([])
        card, _ = self._card(monkeypatch, [_template("mode", items=("a", "b"))], probe)
        (entry,) = card["parms"]
        assert entry["menu"] == ["a", "b"]
        assert entry["menu_source"] == "template"
        assert "menu_generator" not in entry

    def test_a_static_menu_of_numbers_carries_its_labels(self, monkeypatch):
        # pyrosource's Mode came as "0"/"1"/"2" and nothing else.
        labels = ("Surface Scatter", "Keep Input", "Volume Scatter")
        template = _template("mode", items=("0", "1", "2"), labels=labels)
        card, _ = self._card(monkeypatch, [template], _probe([]))
        (entry,) = card["parms"]
        assert entry["menu"] == ["0", "1", "2"]
        assert entry["menu_labels"] == list(labels)
        assert entry["menu_source"] == "template"

    def test_labels_that_repeat_the_tokens_are_left_out(self, monkeypatch):
        card, _ = self._card(monkeypatch, [_template("mode", items=("a", "b"))], _probe([]))
        (entry,) = card["parms"]
        assert "menu_labels" not in entry

    def test_an_empty_generated_menu_is_not_shown_as_no_menu(self, monkeypatch):
        probe = _probe([_parm("loadtype", generator=GENERATOR)])
        card, _ = self._card(monkeypatch, [_template("loadtype")], probe)
        (entry,) = card["parms"]
        assert "menu" not in entry
        assert entry["menu_generator"] == GENERATOR
        assert "menu_generator" in entry["note"]

    def test_a_second_card_reads_the_menus_from_the_cache(self, monkeypatch):
        probe = _probe([_parm("loadtype", LOADTYPE_ITEMS, generator=GENERATOR)])
        _, first_root = self._card(monkeypatch, [_template("loadtype")], probe)
        card, second_root = self._card(monkeypatch, [_template("loadtype")], probe)
        first_root.createNode.assert_called_once()
        second_root.createNode.assert_not_called()
        assert card["parms"][0]["menu"] == list(LOADTYPE_ITEMS)
        assert card["parms"][0]["menu_source"] == "generator"


class _FolderSetTemplate:
    """Stands in for hou.FolderSetParmTemplate, so isinstance() can find it."""

    def __init__(self, folder_type, names):
        self._type, self._names = folder_type, names

    def folderType(self):
        return self._type

    def folderNames(self):
        return tuple(self._names)


class _CardHarness:
    """TestTheCardReadsGeneratedMenus' probe and card, for the classes below."""

    _fresh = TestTheCardReadsGeneratedMenus._fresh
    _card = TestTheCardReadsGeneratedMenus._card


def _folder_set(name, folder_type, names):
    parm = MagicMock()
    parm.name.return_value = name
    parm.parmTemplate.return_value = _FolderSetTemplate(folder_type, names)
    return parm


class TestRadioFoldersAreParametersOnTheCard(_CardHarness):
    """An Add SOP's card had no `switcher1`, the parm that picks By Pattern or By Group.

    The template walk skips folders, and the radio set's parameter went with
    them: 12 parms on the card, 16 on a live Add. Which folder is picked
    decides the result (`attrname=id` made 0 primitives under By Pattern and
    126 under By Group). Radio sets are read off the probe under their live
    name and listed as a FolderSet parm whose menu is the folders; tab
    folders only choose what the pane shows and stay out.
    """

    @pytest.fixture(autouse=True)
    def _types(self, monkeypatch):
        monkeypatch.setattr(hou, "FolderSetParmTemplate", _FolderSetTemplate, raising=False)
        monkeypatch.setattr(
            hou,
            "folderType",
            MagicMock(RadioButtons="radio", Tabs="tabs"),
            raising=False,
        )

    def _add_probe(self):
        return _probe(
            [
                _folder_set("switcher1", "radio", ["By Pattern", "By Group"]),
                _folder_set("stdswitcher1", "tabs", ["Points", "Polygons"]),
                _parm("attrname"),
            ]
        )

    def test_a_radio_set_is_read_off_the_probe_and_tabs_are_not(self):
        assert graph._radio_folder_sets_of(self._add_probe()) == {
            "switcher1": {
                "folder_set": "RadioButtons",
                "items": ["0", "1"],
                "labels": ["By Pattern", "By Group"],
            }
        }

    def test_the_card_lists_the_set_as_a_menu_of_its_folders(self, monkeypatch):
        card, _ = self._card(
            monkeypatch, [_template("attrname", label="Attribute Name")], self._add_probe()
        )
        entry = next(p for p in card["parms"] if p["name"] == "switcher1")
        assert entry["type"] == "FolderSet"
        assert entry["menu"] == ["0", "1"]
        assert entry["menu_labels"] == ["By Pattern", "By Group"]
        assert entry["menu_source"] == "folder_set"
        assert "stdswitcher1" not in [p["name"] for p in card["parms"]]
        assert card["parm_count"] == card["parms_matched"] == 2

    def test_a_filter_finds_it_by_a_folder_s_label(self, monkeypatch):
        card, _ = self._card(
            monkeypatch,
            [_template("attrname", label="Attribute Name")],
            self._add_probe(),
            parm_filter="group",
        )
        assert [p["name"] for p in card["parms"]] == ["switcher1"]


class TestTheCardShowsADefaultExpression(_CardHarness):
    """timeshift's card said `frame: default [0.0]`; a new Time Shift has frame = $F.

    Only a build's `expressions_removed` told otherwise. The template's
    defaultExpression() is now on the card as `default_expression`.
    """

    def _entry(self, monkeypatch, expressions):
        frame = _template("frame")
        frame.defaultValue.return_value = (0.0,)
        frame.defaultExpression.return_value = expressions
        card, _ = self._card(monkeypatch, [frame], _probe([]))
        return card["parms"][0]

    def test_an_expression_default_is_named(self, monkeypatch):
        entry = self._entry(monkeypatch, ("$F",))
        assert entry["default"] == [0.0]
        assert entry["default_expression"] == ["$F"]

    def test_a_plain_default_has_none(self, monkeypatch):
        assert "default_expression" not in self._entry(monkeypatch, ("",))

    def test_a_toggle_s_one_string_is_not_split_into_letters(self, monkeypatch):
        # Toggle and Menu templates return a str, not a tuple.
        entry = self._entry(monkeypatch, 'ch("../enable")')
        assert entry["default_expression"] == ['ch("../enable")']

    def test_the_component_holding_the_expression_is_kept_in_place(self, monkeypatch):
        entry = self._entry(monkeypatch, ("", "$F", ""))
        assert entry["default_expression"] == ["", "$F", ""]


def _string_template(menu_type=None, tags=None):
    template = MagicMock()
    template.type.return_value = hou.parmTemplateType.String
    template.menuType.return_value = hou.menuType.Normal if menu_type is None else menu_type
    template.tags.return_value = dict(tags or {})
    return template


class TestWhichMenusAreStrict:
    """Houdini refuses an off-menu value only on a Menu parm (measured on 22.0.429).

    A String parm with a normal menu takes any text. Its tokens are still
    checked (a typo there writes a value nothing reads), except on a code
    field, whose menu only inserts snippets: a popforce's VEXpression was
    refused by build_network as "not a menu item" though Houdini takes it.
    """

    def test_a_menu_parm_is_strict(self):
        template = MagicMock()
        template.type.return_value = hou.parmTemplateType.Menu
        assert graph._is_strict_menu(template)

    def test_a_string_choice_menu_is_still_checked(self):
        assert graph._is_strict_menu(_string_template())

    def test_a_code_field_with_a_snippet_menu_is_free_text(self):
        vexpression = _string_template(tags={"editor": "1", "editorlang": "vex"})
        assert not graph._is_strict_menu(vexpression)

    def test_a_replace_menu_is_free_text(self):
        assert not graph._is_strict_menu(_string_template(menu_type="replace"))

    def test_unreadable_tags_keep_the_menu_strict(self):
        template = _string_template()
        template.tags.side_effect = RuntimeError("no tags")
        assert graph._is_strict_menu(template)


class TestBuildNetworkTakesCodeInASnippetField:
    def _network(self, monkeypatch):
        code = _parm("localnoiseexpression", ("amp = 1;", "offset = @P;"), generator="x")
        code.parmTemplate.return_value = _string_template(tags={"editor": "1"})
        mode = _parm("mode", ("velocity", "force"))
        probe = _probe([code, mode])
        probe.parmTuples.return_value = []
        for parm in (code, mode):
            parm.expression.return_value = ""
        parent = MagicMock()
        parent.path.return_value = "/obj/dopnet1"
        parent.children.return_value = []
        parent.displayNode.return_value = None
        parent.renderNode.return_value = None
        parent.childTypeCategory.return_value.name.return_value = "Dop"
        parent.createNode.return_value = probe
        node_type = MagicMock()
        node_type.name.return_value = "popforce"
        node_type.maxNumInputs.return_value = 4
        node_type.definition.return_value = None
        monkeypatch.setattr(graph, "_PARM_PROBE_CACHE", {})
        monkeypatch.setattr(hou, "node", lambda path: parent if path == parent.path() else None)
        monkeypatch.setattr(graph, "_resolve_node_type", lambda cat, name: node_type)
        monkeypatch.setattr(graph, "_instance_patterns", lambda t: [])

    def _dry(self, parms):
        return graph.build_network(
            "/obj/dopnet1", [{"type": "popforce", "name": "pf", "parms": parms}], dry_run=True
        )

    def test_the_vexpression_validates(self, monkeypatch):
        self._network(monkeypatch)
        result = self._dry({"localnoiseexpression": "offset.x = @id;"})
        assert result["valid"] is True, result

    def test_a_typo_in_a_menu_token_is_still_caught(self, monkeypatch):
        self._network(monkeypatch)
        result = self._dry({"mode": "velocty"})
        assert result["valid"] is False
        assert "'velocty' is not a menu item" in result["errors"][0]
