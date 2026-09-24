"""Tests for set_hda_interface and edit_hda_interface — an asset's Type
Properties interface, authored and edited through the definition.

create_spare_parameter adds parameters to a node INSTANCE and never reaches
the type; nothing wrote the definition's own interface, and once written
nothing could edit it: insert at a position, remove, hide, rename, a default
expression, a button with a callback, a multiparm block. Two things measured
live on Houdini 22.0.429 shape the edit verb: Houdini refuses a whole group
over a component-name collision (`fh_range` under Base1 makes `fh_range2`, and a
template called `fh_range2` next to it fails with a bare OperationFailed), and
built-in parameters of the node type cannot be removed from an asset's
interface — Houdini puts them back at the top level without a word.

The in-Houdini handlers import `hou`; it is mocked here.
"""

from __future__ import annotations

# Built-in
import os
import sys
from unittest.mock import MagicMock

# Third-party
import pytest

# Mock Houdini modules before importing the in-Houdini server package
sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Internal
import fxhoudinimcp_server.handlers.hda_handlers as hda  # noqa: E402
import fxhoudinimcp_server.handlers.parameter_handlers as parameters  # noqa: E402


class _Parm:
    def __init__(self, name, spare):
        self._name = name
        self._spare = spare

    def name(self):
        return self._name

    def isSpare(self):
        return self._spare


class _Node:
    """A node that is NOT a subnet — the case the old guard refused."""

    def __init__(self, type_name="geo", definition=None, parms=()):
        self._type_name = type_name
        self._definition = definition
        self._parms = list(parms)
        self.editable = False
        self.propagated = None
        self.changed_to = None
        self.created = None

    def path(self):
        return "/obj/unit"

    def type(self):
        node_type = MagicMock()
        node_type.name.return_value = self._type_name
        node_type.definition.return_value = self._definition
        return node_type

    def isSubNetwork(self):
        return False

    def createDigitalAsset(self, **kwargs):
        self.created = kwargs
        return _Node(type_name=kwargs.get("name", "asset"))

    def allowEditingOfContents(self, propagate=False):
        self.propagated = propagate
        self.editable = True

    def isEditable(self):
        return self.editable

    def removeSpareParms(self):
        self._parms = [p for p in self._parms if not p.isSpare()]

    def parms(self):
        return tuple(self._parms)

    def changeNodeType(self, new_type_name, **kwargs):
        self.changed_to = new_type_name
        return _Node(type_name=new_type_name)


def _node(path, type_name="xform", **attrs):
    node = MagicMock()
    node.path.return_value = path
    node.name.return_value = path.rsplit("/", 1)[-1]
    node.type.return_value.name.return_value = type_name
    for key, value in attrs.items():
        getattr(node, key).return_value = value
    return node


def _template(name, kind="Float", components=1, scheme="XYZW", label=None):
    template = MagicMock()
    template.name.return_value = name
    template.label.return_value = label or name.title()
    template.type.return_value.name.return_value = kind
    template.numComponents.return_value = components
    template.namingScheme.return_value.name.return_value = scheme
    template.parmTemplates.return_value = ()
    return template


class _Template:
    """Stands in for hou.ParmTemplate — records what was asked for."""

    def __init__(self, name, label, kind, **kwargs):
        self._name = name
        self._label = label
        self._kind = kind
        self.kwargs = kwargs
        self.conditionals_set = {}
        self.help = None

    def name(self):
        return self._name

    def label(self):
        return self._label

    def type(self):
        return MagicMock(**{"name.return_value": self._kind})

    def setConditional(self, cond_type, expression):
        self.conditionals_set[str(cond_type)] = expression

    def conditionals(self):
        return dict(self.conditionals_set)

    def setHelp(self, text):
        self.help = text

    def parmTemplates(self):
        return tuple(self.kwargs.get("parm_templates", ()))

    def numComponents(self):
        return self.kwargs.get("components", 1)

    def isHidden(self):
        return bool(self.kwargs.get("is_hidden", False))

    def defaultValue(self):
        return self.kwargs.get("default_value")

    def isActualFolder(self):
        return self.kwargs.get("folder_type") is not hda.hou.folderType.MultiparmBlock


def _walk(templates):
    for template in templates:
        yield template
        yield from _walk(template.parmTemplates())


class _LiveGroup:
    """A ParmTemplateGroup that behaves like one: entries, find, remove."""

    def __init__(self, templates=()):
        self.templates = list(templates)
        self.cleared = False

    def entries(self):
        return tuple(self.templates)

    def parmTemplates(self):
        return tuple(self.templates)

    def clear(self):
        self.cleared = True
        self.templates = []

    def append(self, template):
        self.templates.append(template)

    def find(self, name):
        return next((t for t in _walk(self.templates) if t.name() == name), None)

    def findFolder(self, label):
        label = label[-1] if isinstance(label, tuple) else label
        return next(
            (
                t
                for t in _walk(self.templates)
                if t.type().name() == "Folder" and t.label() == label
            ),
            None,
        )

    def remove(self, template):
        self.templates.remove(template)


class _Definition:
    """Hands out a copy of its group, stores what is written, and can play
    Houdini's part on the write (renames, reinstated built-ins)."""

    def __init__(self, templates=(), library="/proj/brick.hda", on_write=None):
        self.stored = list(templates)
        self.library = library
        self.on_write = on_write
        self.writes = 0

    def parmTemplateGroup(self):
        return _LiveGroup(self.stored)

    def setParmTemplateGroup(self, group):
        self.writes += 1
        stored = list(group.templates)
        self.stored = self.on_write(stored) if self.on_write else stored

    def nodeTypeName(self):
        return "brick"

    def libraryFilePath(self):
        return self.library


def _asset_with(monkeypatch, definition, parms=(), tuples=()):
    node = _Node(type_name="brick", definition=definition, parms=[_Parm(n, False) for n in parms])
    node.parmTuples = lambda: tuple(_Parm(n, False) for n in tuples)
    monkeypatch.setattr(hda, "_get_node", lambda path: node)
    monkeypatch.setattr(hda.hou, "node", lambda path: node, raising=False)
    monkeypatch.setattr(hda, "require_inside_project_root", lambda path, what="": path)
    return node


@pytest.fixture
def interface_env(monkeypatch):
    """Give the mocked hou just enough ParmTemplate machinery."""
    hou = hda.hou
    monkeypatch.setattr(
        hou,
        "IntParmTemplate",
        lambda n, label, c, **kw: _Template(n, label, "Int", components=c, **kw),
        raising=False,
    )
    monkeypatch.setattr(
        hou,
        "FloatParmTemplate",
        lambda n, label, c, **kw: _Template(n, label, "Float", components=c, **kw),
        raising=False,
    )
    monkeypatch.setattr(
        hou,
        "StringParmTemplate",
        lambda n, label, c, **kw: _Template(n, label, "String", components=c, **kw),
        raising=False,
    )
    monkeypatch.setattr(
        hou,
        "ToggleParmTemplate",
        lambda n, label, **kw: _Template(n, label, "Toggle", **kw),
        raising=False,
    )
    monkeypatch.setattr(
        hou,
        "MenuParmTemplate",
        lambda n, label, **kw: _Template(n, label, "Menu", **kw),
        raising=False,
    )
    monkeypatch.setattr(
        hou,
        "FolderParmTemplate",
        lambda n, label, **kw: _Template(n, label, "Folder", **kw),
        raising=False,
    )
    monkeypatch.setattr(
        hou,
        "SeparatorParmTemplate",
        lambda n, **kw: _Template(n, "", "Separator", **kw),
        raising=False,
    )
    monkeypatch.setattr(hda.hou, "folderType", MagicMock(), raising=False)
    monkeypatch.setattr(hda.hou, "menuType", MagicMock(), raising=False)
    monkeypatch.setattr(
        hda.hou,
        "parmCondType",
        MagicMock(HideWhen="parmCondType.HideWhen", DisableWhen="parmCondType.DisableWhen"),
        raising=False,
    )
    return hou


class TestBuildParmTemplate:
    def test_strict_range_reaches_houdini(self, interface_env):
        t = hda._build_parm_template(
            {
                "name": "stud_count",
                "type": "int",
                "default": 4,
                "min": 1,
                "max": 8,
                "min_strict": True,
                "max_strict": True,
            },
            set(),
        )
        assert t.kwargs["min"] == 1
        assert t.kwargs["max"] == 8
        assert t.kwargs["min_is_strict"] is True
        assert t.kwargs["max_is_strict"] is True
        assert t.kwargs["default_value"] == (4,)

    def test_label_defaults_to_a_readable_name(self, interface_env):
        t = hda._build_parm_template({"name": "stud_count", "type": "int"}, set())
        assert t.label() == "Stud Count"

    def test_hide_when_is_attached(self, interface_env):
        t = hda._build_parm_template(
            {"name": "bevel", "type": "float", "hide_when": "{ stud_count == 1 }"}, set()
        )
        assert t.conditionals_set["parmCondType.HideWhen"] == "{ stud_count == 1 }"

    def test_menu_pairs_and_string_default(self, interface_env):
        t = hda._build_parm_template(
            {
                "name": "material",
                "type": "menu",
                "default": "metal",
                "menu_items": [["plastic", "Plastic"], ["metal", "Metal"]],
            },
            set(),
        )
        assert t.kwargs["menu_items"] == ("plastic", "metal")
        assert t.kwargs["menu_labels"] == ("Plastic", "Metal")
        assert t.kwargs["default_value"] == 1

    def test_plain_string_menu_items_are_allowed(self, interface_env):
        t = hda._build_parm_template(
            {"name": "material", "type": "menu", "menu_items": ["a", "b"]}, set()
        )
        assert t.kwargs["menu_items"] == ("a", "b")
        assert t.kwargs["menu_labels"] == ("a", "b")

    def test_a_menu_index_default_is_range_checked(self, interface_env):
        with pytest.raises(ValueError, match="out of range"):
            hda._build_parm_template(
                {"name": "material", "type": "menu", "default": 7, "menu_items": ["a", "b"]},
                set(),
            )

    def test_a_hidden_separator_is_hidden(self, interface_env):
        t = hda._build_parm_template({"name": "sep1", "type": "separator", "hidden": True}, set())
        assert t.kwargs["is_hidden"] is True

    def test_create_spare_parameters_spelling_is_accepted(self, interface_env):
        t = hda._build_parm_template(
            {"parm_name": "size", "parm_type": "float", "default_value": 2.0, "max_val": 5},
            set(),
        )
        assert t.name() == "size"
        assert t.kwargs["default_value"] == (2.0,)
        assert t.kwargs["max"] == 5

    def test_menu_default_outside_items_is_rejected(self, interface_env):
        with pytest.raises(ValueError, match="not one of its items"):
            hda._build_parm_template(
                {"name": "material", "type": "menu", "default": "gold", "menu_items": ["plastic"]},
                set(),
            )

    def test_folder_nests_children(self, interface_env):
        t = hda._build_parm_template(
            {
                "name": "controls",
                "type": "folder",
                "children": [{"name": "a", "type": "int"}, {"name": "b", "type": "float"}],
            },
            set(),
        )
        assert [c.name() for c in t.parmTemplates()] == ["a", "b"]

    def test_duplicate_names_are_rejected(self, interface_env):
        seen = set()
        hda._build_parm_template({"name": "size", "type": "int"}, seen)
        with pytest.raises(ValueError, match="Duplicate parameter name"):
            hda._build_parm_template({"name": "size", "type": "float"}, seen)

    def test_unknown_type_lists_the_supported_ones(self, interface_env):
        with pytest.raises(
            ValueError, match="int, float, vector, color, string, file, oppath, toggle, menu"
        ):
            hda._build_parm_template({"name": "x", "type": "ramp"}, set())

    def test_unknown_folder_type_is_rejected(self, interface_env):
        with pytest.raises(ValueError, match="Unknown folder_type"):
            hda._build_parm_template(
                {"name": "f", "type": "folder", "folder_type": "accordion"}, set()
            )

    def test_missing_name_is_rejected(self, interface_env):
        with pytest.raises(ValueError, match="missing 'name'"):
            hda._build_parm_template({"type": "int"}, set())

    def test_menu_without_items_is_rejected(self, interface_env):
        with pytest.raises(ValueError, match="needs menu_items"):
            hda._build_parm_template({"name": "m", "type": "menu"}, set())


class TestSetHdaInterface:
    """set_hda_interface is edit_hda_interface with one insert per entry."""

    CONTROLS = {
        "name": "controls",
        "label": "Controls",
        "type": "folder",
        "children": [{"name": "stud_count", "type": "int", "min": 1, "max": 8}],
    }

    def test_appends_and_writes_the_definition_once(self, interface_env, monkeypatch):
        definition = _Definition([_Template("stdswitcher", "Transform", "Folder")])
        _asset_with(monkeypatch, definition, parms=["stud_count"])
        result = hda.set_hda_interface("/obj/unit", [self.CONTROLS])
        assert definition.writes == 1
        assert [t.name() for t in definition.stored] == ["stdswitcher", "controls"]
        assert result["added"] == ["controls", "stud_count"]
        assert result["ops"][0]["stored"][0]["children"][0]["name"] == "stud_count"
        assert result["renamed_by_houdini"] == []
        assert result["replaced"] is False

    def test_a_retry_is_refused_by_name_before_anything_is_written(
        self, interface_env, monkeypatch
    ):
        definition = _Definition([_Template("stdswitcher", "Transform", "Folder")])
        _asset_with(monkeypatch, definition)
        hda.set_hda_interface("/obj/unit", [self.CONTROLS])
        with pytest.raises(ValueError, match="already exist"):
            hda.set_hda_interface("/obj/unit", [self.CONTROLS])
        assert definition.writes == 1

    def test_replace_clears_first_and_reports_reinstated_builtins(self, interface_env, monkeypatch):
        builtin = _Template("stdswitcher", "Transform", "Folder")
        definition = _Definition([builtin], on_write=lambda stored: [builtin, *stored])
        _asset_with(monkeypatch, definition)
        result = hda.set_hda_interface("/obj/unit", [{"name": "only", "type": "int"}], replace=True)
        assert result["replaced"] is True
        assert result["reinstated_by_houdini"] == ["stdswitcher"]

    def test_dry_run_writes_nothing(self, interface_env, monkeypatch):
        definition = _Definition()
        _asset_with(monkeypatch, definition)
        result = hda.set_hda_interface("/obj/unit", [self.CONTROLS], dry_run=True)
        assert result["dry_run"] is True and definition.writes == 0

    def test_plain_node_is_rejected_with_the_alternative(self, interface_env, monkeypatch):
        node = _Node(type_name="geo", definition=None)
        monkeypatch.setattr(hda, "_get_node", lambda path: node)
        with pytest.raises(ValueError, match="create_spare_parameter"):
            hda.set_hda_interface("/obj/unit", [{"name": "x", "type": "int"}])

    def test_empty_spec_is_rejected(self, interface_env, monkeypatch):
        _asset_with(monkeypatch, _Definition())
        with pytest.raises(ValueError, match="non-empty list"):
            hda.set_hda_interface("/obj/unit", [])

    def test_nothing_is_written_when_a_spec_is_bad(self, interface_env, monkeypatch):
        definition = _Definition()
        _asset_with(monkeypatch, definition)
        with pytest.raises(ValueError):
            hda.set_hda_interface(
                "/obj/unit", [{"name": "good", "type": "int"}, {"name": "bad", "type": "ramp"}]
            )
        assert definition.writes == 0

    def test_a_library_outside_the_project_root_is_refused_before_the_write(
        self, interface_env, monkeypatch
    ):
        definition = _Definition(library="/shared/studio.hda")
        _asset_with(monkeypatch, definition)

        def outside(path, what=""):
            raise PermissionError(f"{what} '{path}' is outside FXHOUDINIMCP_PROJECT_ROOT")

        monkeypatch.setattr(hda, "require_inside_project_root", outside)
        with pytest.raises(PermissionError, match="HDA library"):
            hda.set_hda_interface("/obj/unit", [{"name": "x", "type": "int"}])
        assert definition.writes == 0

    def test_an_embedded_definition_skips_the_library_guard(self, interface_env, monkeypatch):
        # libraryFilePath() answers the literal "Embedded" for a hip-embedded
        # asset; realpathed against cwd it would land outside any project root.
        definition = _Definition(library="Embedded")
        _asset_with(monkeypatch, definition)

        def outside(path, what=""):
            raise PermissionError(f"{what} '{path}' is outside FXHOUDINIMCP_PROJECT_ROOT")

        monkeypatch.setattr(hda, "require_inside_project_root", outside)
        hda.set_hda_interface("/obj/unit", [{"name": "x", "type": "int"}])
        assert definition.writes == 1


class TestHoudiniRenamesTabFolders:
    """A tab folder placed next to an existing tab group joins its naming
    series. Measured on 22.0.429: "Look" appended to an Object asset was
    stored as "stdswitcher3_3", label and children intact."""

    def _renaming(self, stored):
        for template in stored:
            if template.label() == "Controls":
                template._name = "stdswitcher3_3"
        return stored

    def test_a_renamed_folder_is_matched_by_label(self, interface_env, monkeypatch):
        definition = _Definition(
            [_Template("stdswitcher3", "Transform", "Folder")], on_write=self._renaming
        )
        _asset_with(monkeypatch, definition, parms=["stud_count"])
        result = hda.set_hda_interface("/obj/unit", [TestSetHdaInterface.CONTROLS])
        assert result["renamed_by_houdini"] == [
            {"requested": "controls", "stored_as": "stdswitcher3_3", "label": "Controls"}
        ]
        assert result["not_found_after_write"] == []
        assert "tab group" in result["note"]
        assert result["ops"][0]["stored"][0]["name"] == "stdswitcher3_3"

    def test_the_edit_verb_reports_the_same_rename(self, interface_env, monkeypatch):
        definition = _Definition(
            [_Template("stdswitcher3", "Transform", "Folder")], on_write=self._renaming
        )
        _asset_with(monkeypatch, definition, parms=["stud_count"])
        result = hda.edit_hda_interface(
            "/obj/unit", [{"op": "insert", "spec": TestSetHdaInterface.CONTROLS}]
        )
        assert result["renamed_by_houdini"][0]["stored_as"] == "stdswitcher3_3"
        assert result["instance_parms_missing"] == []

    def test_instance_parms_cover_tuples_nesting_and_skip_folders(self, interface_env, monkeypatch):
        definition = _Definition()
        _asset_with(monkeypatch, definition, parms=["clrr", "clrg", "clrb"], tuples=["clr"])
        result = hda.set_hda_interface(
            "/obj/unit",
            [
                {
                    "name": "outer",
                    "type": "folder",
                    "children": [
                        {
                            "name": "inner",
                            "type": "folder",
                            "children": [
                                {"name": "clr", "type": "color"},
                                {"name": "bevel", "type": "float"},
                            ],
                        }
                    ],
                }
            ],
        )
        assert result["instance_parms_present"] == ["clr"]
        assert result["instance_parms_missing"] == ["bevel"]


class TestTheInterfaceIsCheckedBeforeTheWrite:
    def test_a_parameter_of_a_removed_folder_can_be_inserted_again(
        self, interface_env, monkeypatch
    ):
        controls = _Template(
            "controls",
            "Controls",
            "Folder",
            parm_templates=[_Template("stud_count", "Stud Count", "Int")],
        )
        definition = _Definition([controls])
        _asset_with(monkeypatch, definition)
        result = hda.edit_hda_interface(
            "/obj/unit",
            [
                {"op": "remove", "name": "Controls"},
                {"op": "insert", "spec": {"name": "stud_count", "type": "int"}},
            ],
        )
        assert [t.name() for t in definition.stored] == ["stud_count"]
        assert result["removed"] == ["controls"]

    def test_a_rename_onto_an_existing_name_is_refused(self, interface_env, monkeypatch):
        width = MagicMock()
        width.name.return_value = "width"
        width.type.return_value.name.return_value = "Float"
        clone = MagicMock()
        clone.name.return_value = "size"
        width.clone.return_value = clone
        size = _Template("size", "Size", "Float")
        definition = _Definition([width, size])
        _asset_with(monkeypatch, definition)
        with pytest.raises(ValueError, match="already exist"):
            hda.edit_hda_interface(
                "/obj/unit", [{"op": "rename", "name": "width", "new_name": "size"}]
            )
        assert definition.writes == 0

    def test_two_templates_of_one_name_collide_but_tab_folders_do_not(self):
        group = MagicMock()
        group.entries.return_value = [_template("size"), _template("size")]
        assert hda._component_collisions(group)[0]["component"] == "size"
        group.entries.return_value = [_template("tabs", "Folder"), _template("tabs", "Folder")]
        assert hda._component_collisions(group) == []

    def test_two_multiparms_with_the_same_child_collide(self):
        def block(name):
            folder = _template(name, "Folder")
            folder.isActualFolder.return_value = False
            folder.parmTemplates.return_value = (_template("item#"),)
            return folder

        group = MagicMock()
        group.entries.return_value = [block("a"), block("b")]
        assert hda._component_collisions(group)[0]["component"] == "item#"

    def test_multiparm_children_are_not_interface_parameters(self):
        folder = _template("items", "Folder")
        folder.isActualFolder.return_value = False
        folder.parmTemplates.return_value = (_template("item#"),)
        assert [t.name() for t in hda._flatten_templates([folder])] == ["items"]
        assert len(hda._flatten_templates([folder], into_multiparms=True)) == 2


class TestComponentNames:
    def test_schemes_predict_what_houdini_creates(self):
        assert hda._component_names(_template("fh_range", components=2, scheme="Base1")) == [
            "fh_range1",
            "fh_range2",
        ]
        assert hda._component_names(_template("fh_xy", components=2, scheme="XYZW")) == [
            "fh_xyx",
            "fh_xyy",
        ]
        assert hda._component_names(_template("clr", components=3, scheme="RGBA")) == [
            "clrr",
            "clrg",
            "clrb",
        ]
        assert hda._component_names(_template("single")) == ["single"]
        assert hda._component_names(_template("item#", components=2)) == ["item#"]
        assert hda._component_names(_template("f", "Folder")) == ["f"]

    def test_a_collision_between_two_templates_is_named(self):
        group = MagicMock()
        group.entries.return_value = [
            _template("fh_range", components=2, scheme="Base1"),
            _template("fh_range2", components=2, scheme="XYZW"),
        ]
        collisions = hda._component_collisions(group)
        assert collisions == [{"component": "fh_range2", "templates": ["fh_range", "fh_range2"]}]

    def test_no_collision_between_distinct_names(self):
        group = MagicMock()
        group.entries.return_value = [
            _template("fh_range", components=2, scheme="Base1"),
            _template("fh_xy", components=2, scheme="XYZW"),
        ]
        assert hda._component_collisions(group) == []


class TestEditHdaInterface:
    def _asset(self, monkeypatch, names=("stdswitcher", "t", "r", "s")):
        node = _node("/obj/asset1", "asset")
        definition = node.type.return_value.definition.return_value
        definition.nodeTypeName.return_value = "asset"
        definition.libraryFilePath.return_value = "/tmp/asset.hda"
        templates = {name: _template(name) for name in names}
        group = MagicMock()
        # The group under edit behaves like a list: remove() drops the entry.
        group.entries.side_effect = lambda: list(group.live)
        group.live = list(templates.values())
        group.remove.side_effect = lambda t: group.live.remove(t)
        group.find.side_effect = lambda name: templates.get(name)
        group.findFolder.return_value = None
        # What Houdini stores after the write: here, everything it started with
        # (built-ins come back), plus whatever the test appends to `stored`.
        stored = MagicMock()
        stored.entries.side_effect = lambda: list(templates.values()) + list(stored.extra)
        stored.extra = []
        stored.isHidden.return_value = True
        stored.isFolderHidden.return_value = True
        definition.parmTemplateGroup.side_effect = [group, stored]
        group.stored = stored
        node.parms.return_value = []
        node.parmTuples.return_value = []
        hou = hda.hou
        monkeypatch.setattr(hou, "node", lambda path: node)
        monkeypatch.setattr(hda, "_get_node", lambda path: node)
        monkeypatch.setattr(hda, "_component_collisions", lambda g: [])
        monkeypatch.setattr(hda, "_describe_template", lambda t: {"name": t.name()})
        monkeypatch.setattr(hda, "require_inside_project_root", lambda path, what="": path)
        return node, definition, group, templates

    def test_ops_are_applied_in_order_and_written_once(self, monkeypatch):
        node, definition, group, templates = self._asset(monkeypatch)
        built = _template("stud_count", "Int")
        monkeypatch.setattr(
            hda, "_build_parm_template", lambda spec, seen: (seen.add(spec["name"]), built)[1]
        )
        group.insertAfter.side_effect = lambda anchor, t: group.live.append(t)
        group.stored.extra.append(built)
        result = hda.edit_hda_interface(
            "/obj/asset1",
            [
                {"op": "insert", "spec": {"name": "stud_count", "type": "int"}, "after": "t"},
                {"op": "hide", "name": "r"},
                {"op": "remove", "name": "s"},
            ],
        )
        group.insertAfter.assert_called_once_with(templates["t"], built)
        group.hide.assert_called_once_with(templates["r"], True)
        group.remove.assert_called_once_with(templates["s"])
        definition.setParmTemplateGroup.assert_called_once_with(group)
        assert result["added"] == ["stud_count"]
        assert result["ops"][0]["placed"] == "after t"
        assert result["ops"][1]["stored_hidden"] is True
        assert result["removed"] == []
        assert result["reinstated_by_houdini"] == ["s"]

    def test_a_removed_builtin_that_comes_back_is_reported(self, monkeypatch):
        node, definition, group, templates = self._asset(monkeypatch)
        # Houdini re-adds `s` after the write: the stored group still has it.
        result = hda.edit_hda_interface("/obj/asset1", [{"op": "remove", "name": "s"}])
        assert result["removed"] == []
        assert result["reinstated_by_houdini"] == ["s"]
        assert "cannot be removed" in result["note"]

    def test_a_failing_op_writes_nothing(self, monkeypatch):
        node, definition, group, templates = self._asset(monkeypatch)
        with pytest.raises(ValueError, match="No parameter named or folder labelled 'tx'"):
            hda.edit_hda_interface("/obj/asset1", [{"op": "remove", "name": "tx"}])
        definition.setParmTemplateGroup.assert_not_called()

    def test_a_collision_is_refused_before_the_write(self, monkeypatch):
        node, definition, group, templates = self._asset(monkeypatch)
        monkeypatch.setattr(
            hda,
            "_component_collisions",
            lambda g: [{"component": "fh_range2", "templates": ["fh_range", "fh_range2"]}],
        )
        with pytest.raises(ValueError, match="'fh_range2' is produced by both"):
            hda.edit_hda_interface("/obj/asset1", [{"op": "hide", "name": "r"}])
        definition.setParmTemplateGroup.assert_not_called()

    def test_dry_run_reports_the_plan_without_writing(self, monkeypatch):
        node, definition, group, templates = self._asset(monkeypatch)
        result = hda.edit_hda_interface("/obj/asset1", [{"op": "hide", "name": "r"}], dry_run=True)
        assert result["dry_run"] is True
        definition.setParmTemplateGroup.assert_not_called()

    def test_modify_clones_and_replaces(self, monkeypatch):
        node, definition, group, templates = self._asset(monkeypatch)
        clone = templates["r"].clone.return_value
        clone.name.return_value = "r"
        result = hda.edit_hda_interface(
            "/obj/asset1",
            [{"op": "set_conditional", "name": "r", "disable_when": "{ t == 0 }"}],
        )
        hou = hda.hou
        clone.setConditional.assert_called_once_with(hou.parmCondType.DisableWhen, "{ t == 0 }")
        group.replace.assert_called_once_with(templates["r"], clone)
        assert result["ops"][0]["changed"] == ["disable_when"]

    def test_a_default_expression_that_fails_on_the_instance_is_named(self, monkeypatch):
        node, definition, group, templates = self._asset(monkeypatch)
        clone = templates["r"].clone.return_value
        clone.name.return_value = "r"
        clone.defaultExpression.return_value = (_EXPRESSION,)
        monkeypatch.setattr(
            hda,
            "_describe_template",
            lambda t: (
                {"name": t.name(), "default_expression": [_EXPRESSION]}
                if t.name() == "r"
                else {"name": t.name()}
            ),
        )
        instance = _ExpressionNode()
        parm = _ExpressionParm(instance, "r", failing=True)
        node.parmTuple = lambda name: (parm,) if name == "r" else None
        result = hda.edit_hda_interface(
            "/obj/asset1",
            [{"op": "modify", "name": "r", "default_expression_language": "python"}],
        )
        assert result["instance_expression_errors"] == [{"parm": "r", "error": _failure("r")}]
        assert "default_expression_language" in result["note"]

    def test_an_unknown_op_is_named(self, monkeypatch):
        self._asset(monkeypatch)
        with pytest.raises(ValueError, match="unknown op 'explode'"):
            hda.edit_hda_interface("/obj/asset1", [{"op": "explode", "name": "r"}])

    def test_a_non_asset_is_refused(self, monkeypatch):
        node = _node("/obj/geo1", "geo")
        node.type.return_value.definition.return_value = None
        monkeypatch.setattr(hda, "_get_node", lambda path: node)
        with pytest.raises(ValueError, match="not an HDA instance"):
            hda.edit_hda_interface("/obj/geo1", [{"op": "hide", "name": "r"}])


class TestExtendedSpecs:
    def test_naming_scheme_is_looked_up_case_insensitively(self):
        hou = hda.hou
        assert hda._naming_scheme({"naming_scheme": "base1"}, None) is hou.parmNamingScheme.Base1
        assert hda._naming_scheme({}, "default") == "default"
        with pytest.raises(ValueError, match="Unknown naming_scheme"):
            hda._naming_scheme({"naming_scheme": "abc", "name": "x"}, None)

    def test_component_defaults_take_a_list_or_repeat_a_scalar(self):
        assert hda._component_defaults({"default": [0, 1]}, 2, float, 0.0) == (0.0, 1.0)
        assert hda._component_defaults({"default": 3}, 2, int, 0) == (3, 3)
        with pytest.raises(ValueError, match="2 value\\(s\\) for 3"):
            hda._component_defaults({"default": [0, 1], "name": "v"}, 3, float, 0.0)

    def test_a_callback_defaults_to_python(self):
        hou = hda.hou
        kwargs = hda._common_template_kwargs({"callback": "hou.pwd().cook()", "hidden": True})
        assert kwargs["script_callback"] == "hou.pwd().cook()"
        assert kwargs["script_callback_language"] is hou.scriptLanguage.Python
        assert kwargs["is_hidden"] is True

    def test_default_expression_is_spread_over_components(self):
        template = MagicMock()
        template.numComponents.return_value = 2
        hda._apply_default_expression(template, {"name": "v", "default_expression": "ch('tx')"})
        template.setDefaultExpression.assert_called_once_with(("ch('tx')", "ch('tx')"))
        with pytest.raises(ValueError, match="1 default expression"):
            hda._apply_default_expression(
                template, {"name": "v", "default_expression": ["ch('tx')"]}
            )


_EXPRESSION = 'strsplit(strsplit(chs("file"), "/", -1), ".", 0)'


class _Language:
    """str() of a hou.scriptLanguage value, which is what the readback parses."""

    def __init__(self, name):
        self._name = name

    def __str__(self):
        return f"scriptLanguage.{self._name}"


def _failure(parm_name):
    return (
        "Unable to evaluate expression (\nTraceback (most recent call last):\n"
        "NameError: name 'strsplit' is not defined\n"
        f" (/obj/asset1/{parm_name}))."
    )


class _ExpressionNode:
    """A node whose error list behaves like Houdini's: a failing evaluation
    adds the message, and only a cook clears it."""

    def __init__(self, messages=()):
        self.messages = list(messages)
        self.parms = []
        self.cooks = 0

    def errors(self):
        return tuple(self.messages)

    def warnings(self):
        return ()

    def cook(self, force=False):
        self.cooks += 1
        self.messages = []
        for parm in self.parms:
            parm.eval()


class _ExpressionParm:
    def __init__(self, node, name, failing=False, expression=_EXPRESSION, language="Hscript"):
        self._node = node
        self._name = name
        self.failing = failing
        self._expression = expression
        self._language = language
        self.reverted = False
        node.parms.append(self)

    def name(self):
        return self._name

    def path(self):
        return f"/obj/asset1/{self._name}"

    def node(self):
        return self._node

    def eval(self):
        if not self.failing:
            return "River_Banks"
        message = _failure(self._name)
        if message not in self._node.messages:
            self._node.messages.append(message)
        return ""

    def expression(self):
        return self._expression

    def expressionLanguage(self):
        return _Language(self._language)

    def deleteAllKeyframes(self):
        pass

    def revertToDefaults(self):
        self.reverted = True


class TestDefaultExpressionLanguage:
    """A default expression is Hscript unless the spec says otherwise.

    Houdini's own default is Hscript: StringParmTemplate(default_expression=...),
    FloatParmTemplate(...) and setDefaultExpression() without a language all
    store Hscript (measured on 22.0.429). The handler defaulted to Python, so
    an Hscript expression such as strsplit(chs("file"), ...) evaluated to ""
    on every instance with a NameError on the node, and the reply said success.
    """

    def test_a_default_expression_is_hscript_unless_told(self):
        hou = hda.hou
        template = MagicMock()
        template.numComponents.return_value = 1
        hda._apply_default_expression(template, {"name": "out", "default_expression": _EXPRESSION})
        template.setDefaultExpressionLanguage.assert_called_once_with((hou.scriptLanguage.Hscript,))

    def test_the_language_given_is_used(self):
        hou = hda.hou
        template = MagicMock()
        template.numComponents.return_value = 2
        hda._apply_default_expression(
            template,
            {
                "name": "v",
                "default_expression": "hou.frame()",
                "default_expression_language": "python",
            },
        )
        template.setDefaultExpressionLanguage.assert_called_once_with(
            (hou.scriptLanguage.Python, hou.scriptLanguage.Python)
        )

    def test_a_callback_still_defaults_to_python(self):
        assert hda._script_language({}) is hda.hou.scriptLanguage.Python

    def test_modify_with_the_language_alone_relabels_the_expression_there(self):
        hou = hda.hou
        template = MagicMock()
        template.name.return_value = "out"
        template.defaultExpression.return_value = (_EXPRESSION,)
        changed = hda._modify_template(template, {"default_expression_language": "hscript"})
        assert changed == ["default_expression_language"]
        template.setDefaultExpressionLanguage.assert_called_once_with((hou.scriptLanguage.Hscript,))
        template.setDefaultExpression.assert_not_called()

    def test_modify_with_both_names_both(self):
        template = MagicMock()
        template.name.return_value = "out"
        template.numComponents.return_value = 1
        changed = hda._modify_template(
            template,
            {"default_expression": _EXPRESSION, "default_expression_language": "hscript"},
        )
        assert changed == ["default_expression", "default_expression_language"]

    def test_a_language_without_an_expression_is_refused(self):
        template = MagicMock()
        template.name.return_value = "out"
        template.defaultExpression.return_value = ("",)
        with pytest.raises(ValueError, match="no default expression to set a language for"):
            hda._modify_template(template, {"default_expression_language": "python"})

    def test_the_readback_carries_the_expression_and_its_language(self):
        template = _template("out", kind="String")
        template.defaultExpression.return_value = (_EXPRESSION,)
        template.defaultExpressionLanguage.return_value = (_Language("Hscript"),)
        info = hda._describe_template(template)
        assert info["default_expression"] == [_EXPRESSION]
        assert info["default_expression_language"] == ["hscript"]

    def test_no_expression_no_readback_keys(self):
        template = _template("out", kind="String")
        template.defaultExpression.return_value = ("",)
        info = hda._describe_template(template)
        assert "default_expression" not in info

    def test_a_failing_expression_is_reported_by_the_node_error(self):
        node = _ExpressionNode()
        parm = _ExpressionParm(node, "out", failing=True)
        assert parameters._expression_error(parm) == _failure("out")

    def test_a_stale_message_after_the_fix_is_cleared_by_a_cook(self):
        # Measured on 22.0.429: the "Unable to evaluate expression" message
        # stays on the node after the expression is fixed, until it cooks.
        node = _ExpressionNode(messages=[_failure("out")])
        parm = _ExpressionParm(node, "out", failing=False)
        assert parameters._expression_error(parm) is None
        assert node.cooks == 1

    def test_a_clean_parm_costs_no_cook(self):
        node = _ExpressionNode()
        parm = _ExpressionParm(node, "out", failing=False)
        assert parameters._expression_error(parm) is None
        assert node.cooks == 0

    def test_revert_names_the_language_and_the_error_of_a_default_expression(self, monkeypatch):
        node = _ExpressionNode()
        parm = _ExpressionParm(node, "out", failing=True, language="Python")
        monkeypatch.setattr(parameters, "_resolve_parm", lambda path, name: parm)
        # hou.Vector2 is a MagicMock here, so the real serializer cannot run.
        monkeypatch.setattr(parameters, "_serialize_value", lambda value: value)
        result = parameters._revert_parameter("/obj/asset1", "out")
        assert parm.reverted is True
        assert result["default_expression"] == _EXPRESSION
        assert result["default_expression_language"] == "python"
        assert result["expression_error"] == _failure("out")

    def test_revert_of_a_working_default_expression_names_no_error(self, monkeypatch):
        node = _ExpressionNode()
        parm = _ExpressionParm(node, "out", failing=False)
        monkeypatch.setattr(parameters, "_resolve_parm", lambda path, name: parm)
        # hou.Vector2 is a MagicMock here, so the real serializer cannot run.
        monkeypatch.setattr(parameters, "_serialize_value", lambda value: value)
        result = parameters._revert_parameter("/obj/asset1", "out")
        assert result["value"] == "River_Banks"
        assert result["default_expression_language"] == "hscript"
        assert "expression_error" not in result
