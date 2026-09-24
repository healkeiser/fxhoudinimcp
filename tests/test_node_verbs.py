"""Tests for change_node_type and press_button.

Two Houdini gestures had no tool: swapping a node's type in place (Type
Properties "change type", or moving an asset instance to an installed newer
version without losing its edits) and pressing a button parameter ("Stash
Input", "Reload Geometry", an asset's Build button). Both were being done
through execute_python, where the swap silently dropped parameter values and
a pressed button reported nothing about the node afterwards.

hou is mocked here; the live path was checked on Houdini 22.0.429.
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
import fxhoudinimcp_server.handlers.node_handlers as nodes  # noqa: E402


def _node(path, type_name="xform"):
    node = MagicMock()
    node.path.return_value = path
    node.name.return_value = path.rsplit("/", 1)[-1]
    node.type.return_value.name.return_value = type_name
    return node


def _parm(name, at_default):
    parm = MagicMock()
    parm.name.return_value = name
    parm.isAtDefault.return_value = at_default
    return parm


class TestChangeNodeType:
    def _setup(self, monkeypatch, old="xform", new="null"):
        node = _node("/obj/geo1/keepme", old)
        category = node.type.return_value.category.return_value
        category.name.return_value = "Sop"
        category.nodeTypes.return_value = {"xform": None, "null": None}
        node.parms.return_value = [
            _parm("tx", False),
            _parm("scale", False),
            _parm("ty", True),
            _parm("sx", True),
        ]
        changed = _node("/obj/geo1/keepme", new)
        # tx has no home on the new type; scale survives but is back at its
        # default; sx was never set and is simply gone.
        changed.parms.return_value = [_parm("scale", True), _parm("ty", True)]
        changed.inputs.return_value = [_node("/obj/geo1/box1", "box")]
        changed.outputs.return_value = []
        changed.children.return_value = []
        changed.type.return_value.definition.return_value = None
        node.changeNodeType.return_value = changed
        resolved = MagicMock()
        resolved.name.return_value = new
        monkeypatch.setattr(nodes, "_get_node", lambda path: node)
        monkeypatch.setattr(graph, "_resolve_node_type", lambda cat, name: resolved)
        monkeypatch.setattr(nodes, "_focus_network_editor", lambda *a, **k: None)
        return node, changed

    def test_the_swap_keeps_contents_by_default_and_names_dropped_values(self, monkeypatch):
        node, changed = self._setup(monkeypatch)
        result = nodes.change_node_type("/obj/geo1/keepme", "null")
        node.changeNodeType.assert_called_once_with(
            "null", keep_name=True, keep_parms=True, keep_network_contents=True
        )
        assert result["changed"] is True
        assert result["new_type"] == "null"
        assert result["parms_dropped"] == ["tx"]
        assert result["parms_reset"] == ["scale"]
        assert result["parms_removed_count"] == 2
        assert result["inputs"] == ["/obj/geo1/box1"]

    def test_the_same_type_is_a_noop_with_the_same_reply_shape(self, monkeypatch):
        node, _ = self._setup(monkeypatch, old="null", new="null")
        node.inputs.return_value = []
        node.outputs.return_value = []
        node.children.return_value = []
        node.type.return_value.definition.return_value = None
        result = nodes.change_node_type("/obj/geo1/keepme", "null")
        assert result["changed"] is False
        assert "already of type" in result["message"]
        assert result["parms_dropped"] == [] and result["parms_reset"] == []
        for key in ("inputs", "outputs", "keep_parms", "child_count"):
            assert key in result
        node.changeNodeType.assert_not_called()

    def test_resetting_contents_forces_the_same_type(self, monkeypatch):
        node, _ = self._setup(monkeypatch, old="null", new="null")
        result = nodes.change_node_type("/obj/geo1/keepme", "null", keep_network_contents=False)
        node.changeNodeType.assert_called_once_with(
            "null",
            keep_name=True,
            keep_parms=True,
            keep_network_contents=False,
            force_change_on_node_type_match=True,
        )
        assert result["changed"] is True

    def test_an_unknown_type_is_refused_with_a_hint(self, monkeypatch):
        self._setup(monkeypatch)
        monkeypatch.setattr(graph, "_resolve_node_type", lambda *a, **k: None)
        with pytest.raises(ValueError, match="does not exist in Sop"):
            nodes.change_node_type("/obj/geo1/keepme", "nul")

    def test_hom_refusal_is_readable(self, monkeypatch):
        node, _ = self._setup(monkeypatch)
        node.changeNodeType.side_effect = RuntimeError("locked asset")
        with pytest.raises(ValueError, match="Could not change"):
            nodes.change_node_type("/obj/geo1/keepme", "null")


class TestResolveNodeType:
    def test_preferred_version_wins_then_exact_then_newest(self, monkeypatch):
        preferred = MagicMock(return_value=None)
        monkeypatch.setattr(graph.hou, "preferredNodeType", preferred)
        category = MagicMock()
        category.name.return_value = "Sop"
        category.nodeTypes.return_value = {"curve": "classic", "curve::2.0": "new"}
        assert graph._resolve_node_type(category, "curve") == "classic"
        assert graph._resolve_node_type(category, "curve::2.0") == "new"
        category.nodeTypes.return_value = {"copytopoints::2.0": "v2", "copytopoints::3.0": "v3"}
        assert graph._resolve_node_type(category, "copytopoints") == "v3"
        assert graph._resolve_node_type(category, "nope") is None
        preferred.return_value = "preferred"
        assert graph._resolve_node_type(category, "anything") == "preferred"

    def test_the_newest_version_is_ordered_by_number_not_by_string(self, monkeypatch):
        monkeypatch.setattr(graph.hou, "preferredNodeType", MagicMock(return_value=None))
        category = MagicMock()
        category.name.return_value = "Sop"
        category.nodeTypes.return_value = {"mytool::2.0": "v2", "mytool::10.0": "v10"}
        assert graph._resolve_node_type(category, "mytool") == "v10"


class TestPressButton:
    def _node_with_button(self, monkeypatch, kind="Button"):
        node = _node("/obj/geo1/stash1", "stash")
        parm = MagicMock()
        parm.name.return_value = "stashinput"
        parm.parmTemplate.return_value.type.return_value.name.return_value = kind
        parm.parmTemplate.return_value.scriptCallback.return_value = "..."
        node.parm.side_effect = lambda name: parm if name == "stashinput" else None
        node.parms.return_value = [parm]
        node.errors.return_value = []
        node.warnings.return_value = ["w"]
        node.needsToCook.return_value = True
        monkeypatch.setattr(nodes, "_get_node", lambda path: node)
        return node, parm

    def test_the_button_is_pressed_and_the_node_state_read_back(self, monkeypatch):
        node, parm = self._node_with_button(monkeypatch)
        result = nodes.press_button("/obj/geo1/stash1", "stashinput")
        parm.pressButton.assert_called_once_with()
        node.cook.assert_not_called()
        assert result["warnings"] == ["w"]
        assert result["cooked"] is False
        assert result["needs_cook"] is True
        assert result["has_script_callback"] is True
        assert "duration_ms" in result
        assert "note" not in result

    def test_cook_true_cooks_after_the_press_and_survives_a_failed_cook(self, monkeypatch):
        node, parm = self._node_with_button(monkeypatch)
        node.cook.side_effect = RuntimeError("Error while cooking.")
        node.errors.return_value = ["Unable to read file"]
        result = nodes.press_button("/obj/geo1/stash1", "stashinput", cook=True)
        parm.pressButton.assert_called_once_with()
        node.cook.assert_called_once()
        assert result["cooked"] is True
        assert result["errors"] == ["Unable to read file"]

    def test_a_failing_errors_read_does_not_lose_the_press(self, monkeypatch):
        node, parm = self._node_with_button(monkeypatch)
        node.errors.side_effect = RuntimeError("no errors() here")
        result = nodes.press_button("/obj/geo1/stash1", "stashinput")
        parm.pressButton.assert_called_once_with()
        assert result["success"] is True
        assert result["errors"] == []

    def test_an_unsupported_argument_is_refused_before_pressing(self, monkeypatch):
        _, parm = self._node_with_button(monkeypatch)
        with pytest.raises(ValueError, match=r"arguments\['items'\] is list"):
            nodes.press_button("/obj/geo1/stash1", "stashinput", arguments={"items": [1, 2]})
        parm.pressButton.assert_not_called()

    def test_press_button_has_no_deadline(self):
        import fxhoudinimcp_server.dispatcher as dispatcher

        assert dispatcher.command_timeout("nodes.press_button") is None

    def test_arguments_reach_the_callback(self, monkeypatch):
        _, parm = self._node_with_button(monkeypatch)
        nodes.press_button("/obj/geo1/stash1", "stashinput", arguments={"mode": 1})
        parm.pressButton.assert_called_once_with({"mode": 1})

    def test_a_non_button_is_pressed_but_noted(self, monkeypatch):
        self._node_with_button(monkeypatch, kind="Toggle")
        result = nodes.press_button("/obj/geo1/stash1", "stashinput")
        assert "not a Button" in result["note"]

    def test_a_missing_parm_lists_the_buttons(self, monkeypatch):
        self._node_with_button(monkeypatch)
        with pytest.raises(ValueError, match="Buttons on this node: \\['stashinput'\\]"):
            nodes.press_button("/obj/geo1/stash1", "stash_input")

    def test_a_failing_callback_is_readable(self, monkeypatch):
        _, parm = self._node_with_button(monkeypatch)
        parm.pressButton.side_effect = RuntimeError("script error")
        with pytest.raises(ValueError, match="Callback of"):
            nodes.press_button("/obj/geo1/stash1", "stashinput")

    def test_the_reply_names_the_route(self, monkeypatch):
        _, parm = self._node_with_button(monkeypatch)
        parm.parmTemplate.return_value.scriptCallback.return_value = ""
        result = nodes.press_button("/obj/geo1/stash1", "stashinput")
        parm.pressButton.assert_called_once_with()
        assert result["callback_route"] == "native"

    def test_a_raising_python_callback_is_the_reply_not_a_modal_window(self, monkeypatch):
        # pressButton() would answer this exception with Houdini's modal "Error
        # running callback" window and hold the main thread; the bridge runs the
        # script itself and the exception is this call's error.
        node, parm = self._node_with_button(monkeypatch)
        parm.node.return_value = node
        template = parm.parmTemplate.return_value
        template.scriptCallback.return_value = "raise RuntimeError('boom')"
        template.scriptCallbackLanguage.return_value = nodes.hou.scriptLanguage.Python
        monkeypatch.setattr(nodes.hou, "pwd", lambda: None)
        monkeypatch.setattr(nodes.hou, "setPwd", lambda _node: None)
        monkeypatch.setattr(nodes.hou, "undos", MagicMock())
        with pytest.raises(ValueError, match="stash1/stashinput raised RuntimeError: boom"):
            nodes.press_button("/obj/geo1/stash1", "stashinput")
        parm.pressButton.assert_not_called()
