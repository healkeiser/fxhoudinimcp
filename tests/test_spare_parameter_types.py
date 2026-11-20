"""Spare parameters take vector, color and ramp types, as set_hda_interface does.

create_spare_parameter(s) knew float, int, string, toggle and menu only: a
direction vector and a priority ramp on a subnet's interface took
execute_python with a hand-built ParmTemplateGroup. The interface builder
already makes all four, with the Vector / ColorSquare look and a ramp's
default keys, and its aliases read the spare spelling (parm_name,
parm_type, default_value, min_val, max_val) as is.

hou is mocked here; the live check ran on Houdini 22.0.466."""

from __future__ import annotations

# Built-in
import ast
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Third-party
import pytest

sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Internal
import fxhoudinimcp_server.handlers.hda_handlers as hda  # noqa: E402
import fxhoudinimcp_server.handlers.parameter_handlers as parms  # noqa: E402

_TOOLS = Path(__file__).resolve().parents[1] / "python" / "fxhoudinimcp" / "tools"


class TestSpareTypesAreTheInterfaceTypes:
    @pytest.fixture
    def built(self, monkeypatch):
        seen = []

        def interface_template(spec, names):
            seen.append(spec)
            return f"template:{spec['parm_type']}"

        monkeypatch.setattr(hda, "_build_parm_template", interface_template)
        return seen

    @pytest.mark.parametrize("kind", ["vector", "color", "ramp_float", "ramp_color", "Ramp_Float"])
    def test_the_type_goes_to_the_interface_builder(self, built, kind):
        spec = {
            "parm_name": "sun_dir",
            "parm_type": kind,
            "label": "Sun",
            "default_value": [0, 1, 0],
        }
        assert parms._build_parm_template(spec) == f"template:{kind}"
        assert built == [spec]

    def test_the_spec_is_not_changed_in_place(self, built):
        spec = {"parm_name": "r", "parm_type": "ramp_float", "label": "R"}
        parms._build_parm_template(spec)
        assert built[0] is not spec

    def test_the_interface_builder_reads_the_spare_spelling(self):
        for alias, key in (
            ("parm_name", "name"),
            ("parm_type", "type"),
            ("default_value", "default"),
            ("min_val", "min"),
            ("max_val", "max"),
        ):
            assert hda._SPEC_ALIASES[alias] == key

    def test_an_unknown_type_names_the_supported_ones(self):
        with pytest.raises(ValueError, match="Supported: .*vector.*ramp_float"):
            parms._build_parm_template({"parm_name": "x", "parm_type": "ramp", "label": "X"})

    def test_the_single_verb_builds_through_the_same_builder(self, monkeypatch):
        specs = []

        def builder(spec):
            specs.append(spec)
            raise RuntimeError("stop")

        monkeypatch.setattr(parms, "_build_parm_template", builder)
        monkeypatch.setattr(parms, "_resolve_node", lambda path: MagicMock())
        keys = [{"pos": 0, "value": 0}, {"pos": 1, "value": 1}]
        with pytest.raises(RuntimeError, match="stop"):
            parms._create_spare_parameter(
                "/obj/g", "prio", "ramp_float", "Priority", default_value=keys
            )
        assert specs == [
            {
                "parm_name": "prio",
                "parm_type": "ramp_float",
                "label": "Priority",
                "default_value": keys,
            }
        ]

    def test_the_single_tool_takes_ramp_keys(self):
        tree = ast.parse((_TOOLS / "parameters.py").read_text(encoding="utf-8"))
        tool = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "create_spare_parameter"
        )
        default = next(a for a in tool.args.args if a.arg == "default_value")
        assert "list[dict[str, Any]]" in ast.unparse(default.annotation)
        assert "ramp_float" in ast.get_docstring(tool)


def _kind(name):
    kind = MagicMock()
    kind.name.return_value = name
    return kind


class TestRampKindChangeIsRefused:
    """A float and a color ramp share hou.parmTemplateType.Ramp: the batch
    verb's type check let one replace the other, and every key was dropped
    (found live on Houdini 22.0.368)."""

    def _run(self, monkeypatch, existing_kind, new_kind):
        ramp = parms.hou.parmTemplateType.Ramp
        existing = MagicMock()
        existing.type.return_value = ramp
        existing.parmType.return_value = existing_kind
        new = MagicMock()
        new.type.return_value = ramp
        new.parmType.return_value = new_kind
        node = MagicMock()
        node.parm.return_value = None
        node.parmTuple.return_value = None
        node.parmTemplateGroup.return_value.find.return_value = existing
        monkeypatch.setattr(parms, "_resolve_node", lambda path: node)
        monkeypatch.setattr(parms, "_build_parm_template", lambda spec: new)
        spec = {"parm_name": "prio", "parm_type": "ramp_color", "label": "P"}
        return parms._create_spare_parameters("/obj/g", [spec]), node

    def test_a_float_ramp_does_not_become_a_color_ramp(self, monkeypatch):
        with pytest.raises(ValueError, match="without losing its keys"):
            self._run(monkeypatch, _kind("Float"), _kind("Color"))

    def test_the_same_kind_is_updated_in_place(self, monkeypatch):
        kind = _kind("Float")
        result, node = self._run(monkeypatch, kind, kind)
        assert result["updated"] == ["prio"]
        node.setParmTemplateGroup.assert_called_once()
