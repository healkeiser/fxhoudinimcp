"""A spare menu parameter gets its items, labels and default.

create_spare_parameter(parm_type="menu") built an empty menu (Houdini shows a
"none" placeholder) and answered created: true; a token in default_value was
dropped; labels always repeated the tokens. Measured on 22.0.429. hou is mocked
here.
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
import fxhoudinimcp_server.handlers.parameter_handlers as parameters  # noqa: E402

hou = parameters.hou


class _Menu:
    """Stands in for hou.MenuParmTemplate: keeps what it was built with."""

    def __init__(self, name, label, menu_items=(), menu_labels=(), default_value=0):
        self._name, self.label = name, label
        self.items, self.labels, self.default = tuple(menu_items), tuple(menu_labels), default_value

    def name(self):
        return self._name

    def menuItems(self):  # noqa: N802 - HOM's name
        return self.items

    def menuLabels(self):  # noqa: N802 - HOM's name
        return self.labels

    def defaultValue(self):  # noqa: N802 - HOM's name
        return self.default


@pytest.fixture
def menus(monkeypatch):
    monkeypatch.setattr(hou, "MenuParmTemplate", _Menu, raising=False)


def _node(monkeypatch):
    """A node whose parm template group remembers what was added."""
    added: dict = {}
    group = MagicMock()
    group.addParmTemplate.side_effect = lambda t: added.__setitem__(t.name(), t)
    group.find.return_value = None
    node = MagicMock()
    node.parmTemplateGroup.return_value = group
    node.parm.side_effect = lambda name: (
        MagicMock(parmTemplate=lambda: added[name]) if name in added else None
    )
    monkeypatch.setattr(parameters, "_resolve_node", lambda path: node)
    return node, added


class TestMenuTemplate:
    def test_pairs_give_values_and_labels(self, menus):
        t = parameters._menu_template(
            "technique", "Technique", [["0", "Uniform"], ["1", "Attribute Paint"]], None
        )
        assert t.items == ("0", "1")
        assert t.labels == ("Uniform", "Attribute Paint")
        assert t.default == 0

    def test_default_by_value_or_index(self, menus):
        items = ["plastic", "metal", "glass"]
        assert parameters._menu_template("m", "M", items, "metal").default == 1
        assert parameters._menu_template("m", "M", items, 2).default == 2

    def test_a_default_that_is_not_an_item_is_refused(self, menus):
        with pytest.raises(ValueError, match="not one of its items"):
            parameters._menu_template("m", "M", ["a", "b"], "c")

    def test_a_menu_without_items_is_refused(self, menus):
        with pytest.raises(ValueError, match="needs menu_items"):
            parameters._menu_template("m", "M", None, None)

    def test_a_token_without_items_is_refused_not_dropped(self, menus):
        # default_value="metal" alone built an empty menu and said nothing.
        with pytest.raises(ValueError, match="needs menu_items"):
            parameters._menu_template("m", "M", None, "metal")

    def test_a_list_in_default_value_still_means_the_items(self, menus):
        t = parameters._menu_template("m", "M", None, ["plastic", "metal"])
        assert t.items == t.labels == ("plastic", "metal")
        assert t.default == 0


class TestCreateSpareParameter:
    def test_the_reply_reads_the_menu_back(self, menus, monkeypatch):
        _node(monkeypatch)
        reply = parameters._create_spare_parameter(
            "/obj/g/ctrl",
            "technique",
            "menu",
            "Technique",
            default_value="1",
            menu_items=[["0", "Uniform"], ["1", "Attribute Paint"]],
        )
        assert reply["created"] is True
        assert reply["menu_items"] == [["0", "Uniform"], ["1", "Attribute Paint"]]
        assert reply["default_value"] == "1"

    def test_nothing_is_added_when_the_menu_is_refused(self, menus, monkeypatch):
        node, added = _node(monkeypatch)
        with pytest.raises(ValueError, match="needs menu_items"):
            parameters._create_spare_parameter("/obj/g/ctrl", "m", "menu", "M")
        assert added == {}
        node.setParmTemplateGroup.assert_not_called()

    def test_the_batch_takes_menu_items_in_its_spec(self, menus, monkeypatch):
        _, added = _node(monkeypatch)
        reply = parameters._create_spare_parameters(
            "/obj/g/ctrl",
            [
                {
                    "parm_name": "mode",
                    "parm_type": "menu",
                    "label": "Mode",
                    "menu_items": [["a", "Alpha"], ["b", "Beta"]],
                    "default_value": "b",
                }
            ],
        )
        assert reply["created"] == ["mode"]
        assert added["mode"].labels == ("Alpha", "Beta")
        assert added["mode"].default == 1


def test_the_tool_forwards_menu_items(mock_ctx, mock_bridge):
    import asyncio

    from fxhoudinimcp.tools.parameters import create_spare_parameter

    asyncio.run(
        create_spare_parameter(
            mock_ctx, "/obj/g/ctrl", "m", "menu", "M", menu_items=[["0", "Zero"]]
        )
    )
    command, params = mock_bridge.execute.call_args[0][:2]
    assert command == "parameters.create_spare_parameter"
    assert params["menu_items"] == [["0", "Zero"]]
