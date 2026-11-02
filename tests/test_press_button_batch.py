"""press_button on several nodes, with parameters written before each press.

press_button took one button on one node. Resetting a File COP's AOV
multiparm (aovs = 0) and pressing Add AOVs from File on eight of them was
sixteen calls: set_parameters per node, then press_button per node. One call
now takes node_paths and set_first; every node, button and parameter is
checked before anything is written, the batch is one undo step, and a press
that fails stops it, naming the nodes already pressed.

hou is mocked here; the live check ran on Houdini 22.0.466.
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
import fxhoudinimcp_server.handlers.node_handlers as nodes  # noqa: E402
import fxhoudinimcp_server.handlers.parameter_handlers as parameters  # noqa: E402


def _file_cop(path, has_button=True):
    node = MagicMock()
    node.path.return_value = path
    parm = MagicMock()
    parm.name.return_value = "addaovs"
    parm.parmTemplate.return_value.type.return_value.name.return_value = "Button"
    parm.parmTemplate.return_value.scriptCallback.return_value = ""
    parm.parmTemplate.return_value.tags.return_value = {}
    known = {"addaovs": parm if has_button else None, "aovs": MagicMock()}
    node.parm.side_effect = lambda name: known.get(name)
    node.parmTuple.side_effect = lambda name: None
    node.parms.return_value = [p for p in known.values() if p is not None]
    node.errors.return_value = []
    node.warnings.return_value = []
    return node


@pytest.fixture
def cops(monkeypatch):
    found = {f"/img/cop/file{i}": _file_cop(f"/img/cop/file{i}") for i in range(1, 4)}
    monkeypatch.setattr(nodes, "_get_node", lambda path: found[path])
    order = []
    monkeypatch.setattr(nodes, "action_script", lambda parm: "")
    monkeypatch.setattr(nodes, "callback_script", lambda parm: "")

    def press(parm, arguments):
        order.append(("press", parm))
        return "native"

    monkeypatch.setattr(nodes, "press", press)

    def set_parameters(node_path, params, **_):
        order.append(("set", node_path, dict(params)))
        return {
            "node_path": node_path,
            "set": [{"parm_name": "aovs", "new_value": 0}],
            "errors": [],
        }

    monkeypatch.setattr(parameters, "_set_parameters", set_parameters)
    monkeypatch.setattr(nodes.hou, "undos", MagicMock(), raising=False)
    return found, order


class TestPressButtonOnSeveralNodes:
    def test_each_node_is_reset_then_pressed_in_one_undo_step(self, cops):
        found, order = cops
        paths = list(found)
        result = nodes.press_button(node_paths=paths, parm_name="addaovs", set_first={"aovs": 0})
        assert result["pressed"] == 3
        assert [r["node_path"] for r in result["results"]] == paths
        assert result["results"][0]["set_first"] == [{"parm_name": "aovs", "new_value": 0}]
        assert [step[0] for step in order] == ["set", "press"] * 3
        assert order[0][1] == "/img/cop/file1"
        nodes.hou.undos.group.assert_called_once()

    def test_a_node_without_the_button_stops_it_before_anything_is_written(self, cops):
        found, order = cops
        found["/img/cop/file3"] = _file_cop("/img/cop/file3", has_button=False)
        with pytest.raises(ValueError, match="/img/cop/file3 has no parameter 'addaovs'"):
            nodes.press_button(node_paths=list(found), parm_name="addaovs", set_first={"aovs": 0})
        assert order == []

    def test_a_missing_set_first_parameter_is_named_before_anything_is_written(self, cops):
        found, order = cops
        with pytest.raises(ValueError, match="no parameter 'aov_count' to set first"):
            nodes.press_button(
                node_paths=list(found), parm_name="addaovs", set_first={"aov_count": 0}
            )
        assert order == []

    def test_a_failing_press_names_the_nodes_already_pressed(self, cops, monkeypatch):
        found, order = cops

        def press(parm, arguments):
            if len([step for step in order if step[0] == "press"]) == 1:
                raise RuntimeError("no file")
            order.append(("press", parm))
            return "native"

        monkeypatch.setattr(nodes, "press", press)
        with pytest.raises(ValueError, match=r"Pressed before it: \['/img/cop/file1'\]"):
            nodes.press_button(node_paths=list(found), parm_name="addaovs")

    def test_one_node_answers_in_the_single_form(self, cops):
        found, _ = cops
        result = nodes.press_button("/img/cop/file1", "addaovs", set_first={"aovs": 0})
        assert result["node_path"] == "/img/cop/file1"
        assert "results" not in result
        assert result["set_first"]

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"parm_name": "addaovs"},
            {"node_path": "/img/cop/file1", "node_paths": ["/img/cop/file2"], "parm_name": "x"},
            {"node_paths": [], "parm_name": "addaovs"},
            {"node_path": "/img/cop/file1"},
            {"node_path": "/img/cop/file1", "parm_name": "addaovs", "set_first": {}},
        ],
    )
    def test_a_malformed_call_is_refused(self, cops, kwargs):
        with pytest.raises(ValueError):
            nodes.press_button(**kwargs)


def test_a_bad_path_is_named_before_a_missing_parm_name(monkeypatch):
    # test_path_validation_live passes only node_path.
    def missing(path):
        raise ValueError(f"Node not found: {path}")

    monkeypatch.setattr(nodes, "_get_node", missing)
    with pytest.raises(ValueError, match="/obj/nope"):
        nodes.press_button(node_path="/obj/nope")
