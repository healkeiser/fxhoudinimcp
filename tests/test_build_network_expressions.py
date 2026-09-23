"""build_network: expressions in a spec, unknown spec keys, literals over expressions.

Three ways a spec used to fail, each measured live on Houdini 22.0.429:

* An expression string in `parms` on a numeric parm (`switch` / `input` =
  `ch("../seed")`) failed mid-build with "Cannot set a numeric parm to a
  non-numeric value" and rolled the whole graph back. A value written
  `{"expr": ...}` is now set as an expression, the `expressions` block (alias
  `exprs`) is validated by parm name, and a string on a numeric parm is refused
  during validation with the spelling to use instead.
* An unknown key in a spec was dropped in silence: a spec with `"children"`
  built an empty subnet and answered success. It is now a validation error
  with a did-you-mean, so the dry run catches it first.
* A literal from `parms` on a parm that ships with an expression (a Ray SOP's
  `dir` = `@N.x/@N.y/@N.z`) did not land, and the build answered success. The
  dry run now names such parms (`expressions_in_the_way`), the build reports
  `expressions_kept`, and `override_expression` clears them first.

hou is mocked here; the live checks ran on Houdini 22.0.429.
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


class _Parm:
    """A parm that keeps an expression the way HOM does: set() does not clear it."""

    def __init__(self, name, value=0.0, expression=None, template="Float", reference=None):
        self._name = name
        self._value = value
        self._expression = expression
        self._template = template
        self._reference = reference
        self.set_expressions: list = []

    def name(self):
        return self._name

    def path(self):
        return f"/obj/geo1/n/{self._name}"

    def getReferencedParm(self):  # noqa: N802 - HOM spelling
        if self._reference is not None:
            target = MagicMock()
            target.path.return_value = self._reference
            return target
        return self

    def expression(self):
        if self._expression is None:
            raise RuntimeError("no expression")
        return self._expression

    def deleteAllKeyframes(self):  # noqa: N802 - HOM spelling
        self._expression = None

    def set(self, value):
        self._value = value

    def setExpression(self, expression, language=None):  # noqa: N802 - HOM spelling
        self.set_expressions.append((expression, language))
        self._expression = expression

    def parmTemplate(self):  # noqa: N802 - HOM spelling
        template = MagicMock()
        template.type.return_value.name.return_value = self._template
        return template


class _Tuple(list):
    def __init__(self, name, parms):
        super().__init__(parms)
        self._name = name

    def name(self):
        return self._name

    def set(self, values):
        for parm, value in zip(self, values, strict=True):
            parm.set(value)


def _node(path, parms=(), tuples=()):
    node = MagicMock()
    node.path.return_value = path
    node.name.return_value = path.rsplit("/", 1)[-1]
    by_name = {p.name(): p for p in parms}
    by_tuple = {t.name(): t for t in tuples}
    node.parm.side_effect = by_name.get
    node.parmTuple.side_effect = by_tuple.get
    node.errors.return_value = []
    node.warnings.return_value = []
    return node


def _ray():
    components = [_Parm(f"dir{axis}", expression=f"@N.{axis}") for axis in "xyz"]
    return _node("/obj/geo1/ray1", tuples=[_Tuple("dir", components)]), components


###### The probe


class TestTheProbeAnswersMore:
    def test_template_types_and_factory_expressions_come_from_the_same_probe(self, monkeypatch):
        components = [_Parm(f"dir{axis}", expression=f"@N.{axis}") for axis in "xyz"]
        entity = _Parm("entity", template="Menu")
        probe = MagicMock()
        probe.parms.return_value = [entity, *components]
        probe.parmTuples.return_value = [_Tuple("entity", [entity]), _Tuple("dir", components)]
        probe.inputNames.return_value = ["input1"]
        probe.inputLabels.return_value = ["Input 1"]
        probe.outputNames.return_value = []
        scratch = MagicMock()
        scratch.createNode.return_value = probe
        monkeypatch.setattr(graph, "_instance_patterns", lambda t: [])
        monkeypatch.setattr(graph, "_is_dynamic_menu", lambda probe, parm: True)

        types: dict = {}
        shipped: dict = {}
        result = graph._parm_names_for_type(
            scratch, MagicMock(), parm_types=types, factory_expressions=shipped
        )

        assert len(result) == 5  # existing callers unpack five
        assert types == {"entity": "Menu", "dirx": "Float", "diry": "Float", "dirz": "Float"}
        assert shipped["dir"] == {"dirx": "@N.x", "diry": "@N.y", "dirz": "@N.z"}
        assert shipped["diry"] == {"diry": "@N.y"}
        assert "entity" not in shipped
        probe.destroy.assert_called_once()


###### Writing one parm


class TestApplyParmNamesWhatItCouldNotDo:
    def test_a_literal_over_at_n_is_reported_kept(self):
        node, components = _ray()
        report = graph._apply_parm(node, "dir", [0, 1, 0])
        assert report == {"expressions_kept": {"dirx": "@N.x", "diry": "@N.y", "dirz": "@N.z"}}
        assert [p._expression for p in components] == ["@N.x", "@N.y", "@N.z"]

    def test_override_expression_lands_the_literal(self):
        node, components = _ray()
        report = graph._apply_parm(node, "dir", [0, 1, 0], override_expression=True)
        assert report == {"expressions_removed": {"dirx": "@N.x", "diry": "@N.y", "dirz": "@N.z"}}
        assert [p._expression for p in components] == [None, None, None]
        assert [p._value for p in components] == [0.0, 1.0, 0.0]

    def test_a_plain_parm_reports_nothing(self):
        scale = _Parm("scale", value=1.0)
        node = _node("/obj/geo1/box1", parms=[scale])
        assert graph._apply_parm(node, "scale", 2.0) == {}
        assert scale._value == 2.0

    def test_a_pure_reference_is_named_as_written_through(self):
        tx = _Parm("tx", expression='ch("../b1/sizex")', reference="/obj/geo1/b1/sizex")
        node = _node("/obj/geo1/xf", parms=[tx])
        report = graph._apply_parm(node, "tx", 2.0)
        assert report == {"written_through": {"tx": "/obj/geo1/b1/sizex"}}

    def test_nothing_is_evaluated(self):
        node, components = _ray()
        for component in components:
            component.eval = MagicMock(side_effect=AssertionError("evaluated"))
        graph._apply_parm(node, "dir", [0, 1, 0])


###### Spec helpers


class TestSpecHelpers:
    def test_all_three_spellings_end_up_in_one_table(self):
        spec = {
            "expressions": {"a": "1"},
            "exprs": {"b": "2"},
            "parms": {"c": {"expr": "3"}, "d": 4},
        }
        assert graph._spec_expressions(spec) == {"a": "1", "b": "2", "c": "3"}

    def test_numeric_text_is_told_from_an_expression(self):
        assert graph._is_numeric_text("3")
        assert graph._is_numeric_text("-1.5")
        assert not graph._is_numeric_text('ch("../x")')
        assert not graph._is_numeric_text("$F")

    def test_the_language_name_is_checked(self):
        with pytest.raises(ValueError, match="hscript"):
            graph._expression_language("vex")


###### Validation


class _FakeParent:
    """Just enough of a network for build_network's validation phase."""

    def __init__(self, path="/obj/geo1"):
        self._path = path

    def path(self):
        return self._path

    def childTypeCategory(self):  # noqa: N802 - HOM spelling
        category = MagicMock()
        category.name.return_value = "Sop"
        category.nodeTypes.return_value = {"switch": None, "box": None}
        return category

    def children(self):
        return []

    def displayNode(self):  # noqa: N802 - HOM spelling
        return None

    def renderNode(self):  # noqa: N802 - HOM spelling
        return None


@pytest.fixture
def validating_build(monkeypatch):
    """build_network with its type/parm probes answered from a table."""
    node_type = MagicMock()
    node_type.name.return_value = "switch"
    node_type.maxNumInputs.return_value = 4
    monkeypatch.setattr(hou, "node", lambda path: _FakeParent(path))
    monkeypatch.setattr(graph, "_resolve_node_type", lambda cat, name: node_type)

    def knowledge(scratch, resolved, parm_types=None, factory_expressions=None, locked=None):
        if parm_types is not None:
            parm_types.update(
                {"input": "Int", "name": "String", "tx": "Float", "ty": "Float", "tz": "Float"}
            )
        connectors = {"inputs": [], "outputs": []}
        return {"input", "name", "tx", "ty", "tz"}, {"t"}, {}, [], connectors

    monkeypatch.setattr(graph, "_parm_names_for_type", knowledge)
    return graph.build_network


class TestUnknownSpecKeysAreRefused:
    def test_children_is_named_instead_of_dropped(self, validating_build):
        result = validating_build(
            "/obj", [{"type": "switch", "name": "n1", "children": [{"type": "box"}]}], dry_run=True
        )
        assert result["valid"] is False
        assert any("unknown spec key 'children'" in e for e in result["errors"])

    def test_a_typo_gets_a_did_you_mean(self, validating_build):
        result = validating_build("/obj", [{"type": "switch", "parm": {}}], dry_run=True)
        assert any("'parms'" in e for e in result["errors"])

    def test_an_unknown_input_key_is_refused_too(self, validating_build):
        result = validating_build(
            "/obj", [{"type": "switch", "inputs": [{"srcs": "box1"}]}], dry_run=True
        )
        assert any("unknown input key 'srcs'" in e for e in result["errors"])

    def test_a_spec_that_is_not_a_dict_is_named_not_crashed_on(self, validating_build):
        result = validating_build("/obj", ["box"], dry_run=True)
        assert result["valid"] is False
        assert any("must be a dict" in e for e in result["errors"])

    def test_a_clean_spec_still_validates(self, validating_build):
        result = validating_build(
            "/obj", [{"type": "switch", "name": "sw", "parms": {"input": 1}}], dry_run=True
        )
        assert result["valid"] is True


class TestExpressionsInASpec:
    def test_a_string_on_a_numeric_parm_is_caught_before_anything_is_built(self, validating_build):
        result = validating_build(
            "/obj", [{"type": "switch", "parms": {"input": 'ch("../seed")'}}], dry_run=True
        )
        assert result["valid"] is False
        message = "\n".join(result["errors"])
        assert "is numeric (Int)" in message
        assert '"expr"' in message
        assert "expressions" in message

    def test_a_numeric_string_is_still_accepted(self, validating_build):
        result = validating_build(
            "/obj", [{"type": "switch", "parms": {"input": "2"}}], dry_run=True
        )
        assert result["valid"] is True

    def test_a_string_parm_takes_a_string(self, validating_build):
        result = validating_build(
            "/obj", [{"type": "switch", "parms": {"name": "hello"}}], dry_run=True
        )
        assert result["valid"] is True

    def test_the_expr_wrapper_validates(self, validating_build):
        result = validating_build(
            "/obj",
            [{"type": "switch", "parms": {"input": {"expr": 'ch("../seed")'}}}],
            dry_run=True,
        )
        assert result["valid"] is True

    def test_a_dict_without_expr_is_refused(self, validating_build):
        result = validating_build(
            "/obj", [{"type": "switch", "parms": {"input": {"value": 2}}}], dry_run=True
        )
        assert any("without 'expr'" in e for e in result["errors"])

    def test_an_unknown_language_is_refused(self, validating_build):
        result = validating_build(
            "/obj",
            [{"type": "switch", "parms": {"input": {"expr": "1", "language": "vex"}}}],
            dry_run=True,
        )
        assert any("'hscript' or 'python'" in e for e in result["errors"])

    def test_an_expression_on_a_parm_that_does_not_exist_fails_validation(self, validating_build):
        result = validating_build(
            "/obj", [{"type": "switch", "exprs": {"inputt": "1"}}], dry_run=True
        )
        message = "\n".join(result["errors"])
        assert "no parm 'inputt' to put an expression on" in message
        assert "input" in message.split("Did you mean", 1)[1]

    def test_an_expression_on_a_whole_tuple_names_its_components(self, validating_build):
        result = validating_build(
            "/obj", [{"type": "switch", "expressions": {"t": "$F"}}], dry_run=True
        )
        assert result["valid"] is False
        assert "['tx', 'ty', 'tz']" in result["errors"][0]


###### Literals over factory expressions


@pytest.fixture
def ray_type(monkeypatch):
    node_type = MagicMock()
    node_type.name.return_value = "ray"
    node_type.maxNumInputs.return_value = 2
    monkeypatch.setattr(graph, "_resolve_node_type", lambda cat, name: node_type)

    def knowledge(scratch, resolved, parm_types=None, factory_expressions=None, locked=None):
        if factory_expressions is not None:
            factory_expressions["dir"] = {"dirx": "@N.x", "diry": "@N.y", "dirz": "@N.z"}
        connectors = {"inputs": [], "outputs": []}
        return {"dirx", "diry", "dirz", "entity"}, {"dir"}, {}, [], connectors

    monkeypatch.setattr(graph, "_parm_names_for_type", knowledge)
    return node_type


class TestTheDryRunNamesExpressionsInTheWay:
    def test_a_literal_over_a_factory_expression_is_named(self, monkeypatch, ray_type):
        monkeypatch.setattr(hou, "node", lambda path: _FakeParent(path))
        spec = [{"type": "ray", "name": "r", "parms": {"entity": 0, "dir": [0, 1, 0]}}]
        result = graph.build_network("/obj/geo1", spec, dry_run=True)
        assert result["valid"] is True
        assert result["expressions_in_the_way"] == {
            "r": {"dir": {"dirx": "@N.x", "diry": "@N.y", "dirz": "@N.z"}}
        }
        assert "override_expression" in result["warning"]

    def test_override_expression_clears_the_warning(self, monkeypatch, ray_type):
        monkeypatch.setattr(hou, "node", lambda path: _FakeParent(path))
        spec = [{"type": "ray", "parms": {"dir": [0, 1, 0]}, "override_expression": True}]
        result = graph.build_network("/obj/geo1", spec, dry_run=True)
        assert result["valid"] is True
        assert "expressions_in_the_way" not in result
        assert "warning" not in result


###### The build


class _BuildParent(_FakeParent):
    """A network whose createNode hands out prepared nodes, in order."""

    def __init__(self, made):
        super().__init__("/obj/geo1")
        self._made = iter(made)

    def createNode(self, type_name, name=None):  # noqa: N802 - HOM spelling
        return next(self._made)

    def node(self, path):
        return None


@pytest.fixture
def building(monkeypatch):
    monkeypatch.setattr(graph, "place_new_nodes", lambda nodes: None)
    monkeypatch.setattr(graph, "layout_if_enabled", lambda parent: None)
    monkeypatch.setattr(graph, "_geometry_summary", lambda node: None)

    def build(parent, spec):
        monkeypatch.setattr(hou, "node", lambda path: parent)
        return graph.build_network("/obj/geo1", spec)

    return build


class TestTheBuildSaysWhatDidNotTake:
    def test_the_build_reports_kept_expressions_at_both_levels(self, building, ray_type):
        node, _ = _ray()
        # The validation probe comes from the fixture; createNode only builds.
        result = building(_BuildParent([node]), [{"type": "ray", "parms": {"dir": [0, 1, 0]}}])
        assert result["success"] is True
        assert result["expressions_kept"] == {"/obj/geo1/ray1": ["dirx", "diry", "dirz"]}
        assert result["created"][0]["expressions_kept"]["diry"] == "@N.y"
        assert "override_expression" in result["warning"]

    def test_override_expression_lands_the_literal_and_says_so(self, building, ray_type):
        node, components = _ray()
        result = building(
            _BuildParent([node]),
            [{"type": "ray", "parms": {"dir": [0, 1, 0]}, "override_expression": True}],
        )
        assert "expressions_kept" not in result and "warning" not in result
        assert set(result["created"][0]["expressions_removed"]) == {"dirx", "diry", "dirz"}
        assert [p._value for p in components] == [0.0, 1.0, 0.0]

    def test_an_expr_value_is_set_as_an_expression_in_its_language(self, building, monkeypatch):
        node_type = MagicMock()
        node_type.name.return_value = "switch"
        node_type.maxNumInputs.return_value = 4
        monkeypatch.setattr(graph, "_resolve_node_type", lambda cat, name: node_type)
        monkeypatch.setattr(
            graph,
            "_parm_names_for_type",
            lambda scratch, resolved, parm_types=None, factory_expressions=None, locked=None: (
                {"input", "seed"},
                set(),
                {},
                [],
                {"inputs": [], "outputs": []},
            ),
        )
        switch_input = _Parm("input", template="Int")
        seed = _Parm("seed", template="Int")
        node = _node("/obj/geo1/switch1", parms=[switch_input, seed])
        result = building(
            _BuildParent([node]),
            [
                {
                    "type": "switch",
                    "parms": {"input": {"expr": "hou.frame() % 2", "language": "python"}},
                    "exprs": {"seed": "$F"},
                }
            ],
        )
        assert result["success"] is True, result
        assert switch_input.set_expressions == [("hou.frame() % 2", hou.exprLanguage.Python)]
        assert seed.set_expressions == [("$F", None)]
        assert switch_input._value == 0.0  # the wrapper was never set() as a value
