"""set_parameter / set_parameters say what a write actually did.

hou.Parm.set() on a parameter that holds an expression does not remove the
expression: the literal goes into a slot the expression keeps overriding, and
the reply used to be a plain `new_value` with an empty `errors`, which reads as
success. On a parameter holding a bare ch() reference, set() writes THROUGH it
into the parameter it reads, so another node moves and the reply said nothing.
A String parameter echoed only its expanded value, so `$JOB/...` came back as
an absolute path.

The replies now name all three: `expression_kept` (decided by whether the
expression survived, not by whether the values differ), `written_through`, and
`raw_value`; `override_expression` clears the expression first.

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
import fxhoudinimcp_server.handlers.parameter_handlers as parameters  # noqa: E402

hou = parameters.hou


class _PermissionError(Exception):
    """Stands in for hou.PermissionError, which the hou stub does not define."""


class _OperationFailed(Exception):
    """Stands in for hou.OperationFailed, which the hou stub does not define."""


def _node(path, type_name="xform"):
    node = MagicMock()
    node.path.return_value = path
    node.name.return_value = path.rsplit("/", 1)[-1]
    node.type.return_value.name.return_value = type_name
    return node


class _Parm:
    """A parm whose set() behaves the way HOM's does on an expression.

    set() writes the value into the parm's own slot while the expression keeps
    answering for eval(); only deleteAllKeyframes() drops it, and it evaluates
    the expression it drops to keep the value (logged in `evaluated_on_clear`).
    With *reference* the parm is a bare ch() onto that parm, and set() lands
    there instead.
    """

    def __init__(
        self,
        name,
        value=0,
        expression=None,
        expression_value=None,
        node_path="/obj/geo1/n",
        reference=None,
        string=False,
        raw=None,
    ):
        self._name = name
        self._value = value
        self._expression = expression
        self._expression_value = value if expression_value is None else expression_value
        self._node_path = node_path
        self._reference = reference
        self._string = string
        self._raw = raw
        self.deleted = False
        self.evaluated_on_clear: list = []

    def name(self):
        return self._name

    def path(self):
        return f"{self._node_path}/{self._name}"

    def node(self):
        return _node(self._node_path)

    def getReferencedParm(self):  # noqa: N802 — HOM spelling
        return self._reference if self._reference is not None else self

    def expression(self):
        if self._expression is None:
            raise hou.OperationFailed("not animated")
        return self._expression

    def setExpression(self, expression, language=None, replace_expression=True):  # noqa: N802
        self._expression = expression

    def deleteAllKeyframes(self):  # noqa: N802 — HOM spelling
        # HOM keeps the parm at its current value, so it evaluates what it drops.
        self.evaluated_on_clear.append(self._expression)
        self.deleted = True
        self._expression = None

    def set(self, value):
        if self._expression is not None and self._reference is not None:
            self._reference.set(value)
            self._expression_value = value
            return
        if self._string:
            # A String parm keeps the text and expands it on eval().
            self._raw = value
            value = value.replace("$JOB", "/work/proj").replace("$F4", "0001")
        self._value = value

    def eval(self):
        return self._expression_value if self._expression is not None else self._value

    def unexpandedString(self):  # noqa: N802 — HOM spelling
        return self._raw if self._raw is not None else self._value

    def parmTemplate(self):  # noqa: N802 — HOM spelling
        template = MagicMock()
        kind = hou.parmTemplateType.String if self._string else hou.parmTemplateType.Float
        template.type.return_value = kind
        return template


class _Tuple(list):
    def set(self, values):
        # parmTuple.set() reaches each component, exactly as HOM's does.
        for parm, value in zip(self, values, strict=True):
            parm.set(value)


@pytest.fixture(autouse=True)
def _hou(monkeypatch):
    monkeypatch.setattr(hou, "PermissionError", _PermissionError, raising=False)
    monkeypatch.setattr(hou, "OperationFailed", _OperationFailed, raising=False)
    # hou.Vector2 is a MagicMock here, so isinstance() in the real serializer
    # raises. Values in these tests are plain Python already.
    monkeypatch.setattr(parameters, "_serialize_value", lambda value: value)


def _set(monkeypatch, parm, value, **kw):
    monkeypatch.setattr(parameters, "_resolve_parm", lambda path, name: parm)
    return parameters._set_parameter("/obj/geo1/n", parm.name(), value, **kw)


def _batch(monkeypatch, parms, params, **kw):
    node = _node("/obj/geo1/n")
    node.parm.side_effect = lambda name: parms.get(name)
    node.parmTuple.side_effect = lambda name: None
    monkeypatch.setattr(parameters, "_resolve_node", lambda path: node)
    monkeypatch.setattr(parameters, "_available_parm_names", lambda node: sorted(parms))
    return parameters._set_parameters("/obj/geo1/n", params, **kw)


###### A literal on an expression


class TestExpressionKept:
    def test_a_kept_expression_is_named_instead_of_reported_as_success(self, monkeypatch):
        parm = _Parm("fh_count", value=0, expression='ch("fh_seed") * 10', expression_value=40)
        result = _set(monkeypatch, parm, 3)
        assert result["new_value"] == 40
        assert result["expression_kept"] is True
        assert result["expression"] == 'ch("fh_seed") * 10'
        assert result["requested"] == 3
        assert "same_as_evaluated" not in result
        assert "override_expression" in result["note"]

    def test_an_equal_value_still_names_the_kept_expression(self, monkeypatch):
        # Zeroing a factory $N that evaluates to 0 leaves the expression in
        # place: the parm reads what was asked for, and is not what was asked for.
        parm = _Parm("rangeend", value=0, expression="$N", expression_value=0)
        result = _set(monkeypatch, parm, 0)
        assert result["expression_kept"] is True
        assert result["same_as_evaluated"] is True
        assert "evaluates to right now" in result["note"]

    def test_override_expression_clears_it_and_the_write_lands(self, monkeypatch):
        parm = _Parm("fh_count", value=0, expression='ch("fh_seed") * 10', expression_value=40)
        result = _set(monkeypatch, parm, 3, override_expression=True)
        assert parm.deleted is True
        assert result["new_value"] == 3
        assert "expression_kept" not in result
        assert result["expression_removed"] == 'ch("fh_seed") * 10'

    def test_a_plain_parm_answers_exactly_as_before(self, monkeypatch):
        parm = _Parm("tx", value=0)
        result = _set(monkeypatch, parm, 1.5)
        assert result == {"node_path": "/obj/geo1/n", "parm_name": "tx", "new_value": 1.5}

    def test_override_on_a_plain_parm_changes_nothing(self, monkeypatch):
        parm = _Parm("tx", value=0)
        result = _set(monkeypatch, parm, 1.5, override_expression=True)
        assert parm.deleted is False
        assert "expression_removed" not in result

    def test_the_batch_warns_at_the_top_level(self, monkeypatch):
        driven = _Parm("cache_end", value=0, expression='ch("bld_amn")', expression_value=281)
        plain = _Parm("cache_start", value=1)
        reply = _batch(
            monkeypatch,
            {"cache_end": driven, "cache_start": plain},
            {"cache_end": 3, "cache_start": 5},
        )
        assert reply["errors"] == []
        assert reply["expressions_kept"] == ["cache_end"]
        assert "did not take" in reply["warning"]
        assert reply["set"][0]["expression_kept"] is True
        assert reply["set"][1] == {"parm_name": "cache_start", "new_value": 5}

    def test_the_batch_names_an_equal_value_too(self, monkeypatch):
        parm = _Parm("rangeend", value=0, expression="$N", expression_value=0)
        reply = _batch(monkeypatch, {"rangeend": parm}, {"rangeend": 0})
        assert reply["expressions_kept"] == ["rangeend"]
        assert "warning" in reply

    def test_the_batch_passes_override_expression_through(self, monkeypatch):
        parm = _Parm("rangeend", value=0, expression="$N", expression_value=7)
        reply = _batch(monkeypatch, {"rangeend": parm}, {"rangeend": 0}, override_expression=True)
        assert reply["set"][0]["expression_removed"] == "$N"
        assert "expressions_kept" not in reply
        assert "warning" not in reply

    def test_a_clean_batch_has_no_warning(self, monkeypatch):
        reply = _batch(monkeypatch, {"tx": _Parm("tx")}, {"tx": 2.0})
        assert set(reply) == {"node_path", "set", "errors"}

    def test_a_permission_error_still_names_the_driving_expression(self, monkeypatch):
        # A karma resolutiony driven by autoheight refuses set() outright (#41).
        parm = _Parm("resolutiony", expression="pythonexprf('autoheight')")
        parm.set = MagicMock(side_effect=_PermissionError("locked assets, takes..."))
        with pytest.raises(ValueError, match="autoheight"):
            _set(monkeypatch, parm, 1080)

    def test_values_match_tolerates_int_against_float(self):
        assert parameters._values_match(3, 3.0)
        assert not parameters._values_match(3, 40)
        assert parameters._values_match("full", "full")
        assert not parameters._values_match(True, 0)


###### A literal on a bare channel reference


class TestWrittenThrough:
    def test_a_write_through_names_where_it_landed(self, monkeypatch):
        source = _Parm("sizex", value=9, node_path="/obj/geo1/b1")
        parm = _Parm("tx", expression='ch("../b1/sizex")', expression_value=9, reference=source)
        result = _set(monkeypatch, parm, 1.0)
        assert source.eval() == 1.0
        assert result["new_value"] == 1.0
        assert result["written_through"] == "/obj/geo1/b1/sizex"
        assert result["expression"] == 'ch("../b1/sizex")'
        assert "expression_kept" not in result
        assert "written into the parameter it reads" in result["note"]

    def test_a_computed_expression_is_not_a_write_through(self, monkeypatch):
        parm = _Parm("fh_count", expression='ch("fh_seed") * 10', expression_value=40)
        result = _set(monkeypatch, parm, 3)
        assert result["expression_kept"] is True
        assert "written_through" not in result

    def test_override_expression_breaks_the_link_instead(self, monkeypatch):
        source = _Parm("sizex", value=9, node_path="/obj/geo1/b1")
        parm = _Parm("tx", expression='ch("../b1/sizex")', expression_value=9, reference=source)
        result = _set(monkeypatch, parm, 1.0, override_expression=True)
        assert source.eval() == 9
        assert result["new_value"] == 1.0
        assert "written_through" not in result
        assert result["expression_removed"] == 'ch("../b1/sizex")'

    def test_the_batch_surfaces_a_write_through(self, monkeypatch):
        source = _Parm("sizex", value=9, node_path="/obj/geo1/b1")
        linked = _Parm("tx", expression='ch("../b1/sizex")', expression_value=9, reference=source)
        reply = _batch(monkeypatch, {"tx": linked}, {"tx": 1.0})
        assert reply["written_through"] == {"tx": "/obj/geo1/b1/sizex"}
        assert "rather than into them" in reply["warning"]
        assert "expressions_kept" not in reply


###### Tuples


class TestTuples:
    def test_a_tuple_names_the_component_that_kept_its_expression(self):
        tx = _Parm("tx", expression="$F * 7", expression_value=7)
        ty = _Parm("ty", value=0)
        node = _node("/obj/geo1")
        node.parmTuple.return_value = _Tuple([tx, ty])
        values, report = parameters._set_tuple(node, "t", [1.0, 2.0])
        assert values == [7, 2.0]
        assert report["expression_kept"] is True
        assert report["expression_components"] == [
            {"component": "tx", "index": 0, "expression": "$F * 7", "requested": 1.0}
        ]
        assert report["requested"] == [1.0, 2.0]

    def test_a_tuple_reports_a_write_through_per_component(self):
        source = _Parm("sizex", value=9, node_path="/obj/geo1/b1")
        tx = _Parm("tx", expression='ch("../b1/sizex")', expression_value=9, reference=source)
        ty = _Parm("ty", value=0)
        node = _node("/obj/geo1")
        node.parmTuple.return_value = _Tuple([tx, ty])
        values, report = parameters._set_tuple(node, "t", [1.0, 2.0])
        assert values == [1.0, 2.0]
        assert report["written_through"] == {"tx": "/obj/geo1/b1/sizex"}
        assert "expression_kept" not in report

    def test_a_plain_tuple_reports_nothing(self):
        node = _node("/obj/geo1")
        node.parmTuple.return_value = _Tuple([_Parm("tx"), _Parm("ty")])
        values, report = parameters._set_tuple(node, "t", [1.0, 2.0])
        assert values == [1.0, 2.0]
        assert report == {}

    def test_override_expression_clears_every_component(self):
        tx = _Parm("tx", expression="$F * 7", expression_value=7)
        ty = _Parm("ty", expression="$F", expression_value=1)
        node = _node("/obj/geo1")
        node.parmTuple.return_value = _Tuple([tx, ty])
        values, report = parameters._set_tuple(node, "t", [1.0, 2.0], override_expression=True)
        assert tx.deleted and ty.deleted
        assert values == [1.0, 2.0]
        assert "expression_kept" not in report

    def test_the_single_setter_merges_the_tuple_report(self, monkeypatch):
        tx = _Parm("tx", expression="$F * 7", expression_value=7)
        node = _node("/obj/geo1/n")
        node.parmTuple.return_value = _Tuple([tx, _Parm("ty")])
        monkeypatch.setattr(parameters, "_resolve_node", lambda path: node)
        result = parameters._set_parameter("/obj/geo1/n", "t", [1.0, 2.0])
        assert result["parm_name"] == "t"
        assert result["expression_kept"] is True
        assert result["expression_components"][0]["component"] == "tx"


###### Clearing an expression does not evaluate it


class TestClearingDoesNotEvaluate:
    """deleteAllKeyframes() evaluates the expression it drops; outside a cook a
    Ray SOP's `@N.x` then leaves "Local variable 'N' not found" on the node.
    A constant stands in first, so the only thing evaluated is that constant.
    """

    def test_a_constant_stands_in_before_the_channel_goes(self):
        parm = _Parm("dirx", expression="@N.x")
        parameters._clear_expression(parm)
        assert parm.evaluated_on_clear == ["0"]
        assert parm.deleted is True
        assert parm._expression is None

    def test_set_parameter_clears_without_evaluating(self, monkeypatch):
        parm = _Parm("dirx", value=0, expression="@N.x", expression_value=0)
        result = _set(monkeypatch, parm, 1.0, override_expression=True)
        assert parm.evaluated_on_clear == ["0"]
        assert result["new_value"] == 1.0
        assert result["expression_removed"] == "@N.x"

    def test_set_parameters_clears_without_evaluating(self, monkeypatch):
        parm = _Parm("dirx", value=0, expression="@N.x", expression_value=0)
        reply = _batch(monkeypatch, {"dirx": parm}, {"dirx": 1.0}, override_expression=True)
        assert parm.evaluated_on_clear == ["0"]
        assert reply["set"][0]["expression_removed"] == "@N.x"

    def test_a_tuple_clears_every_component_without_evaluating(self):
        components = [_Parm(f"dir{axis}", expression=f"@N.{axis}") for axis in "xyz"]
        node = _node("/obj/geo1/ray1", type_name="ray")
        node.parmTuple.return_value = _Tuple(components)
        values, report = parameters._set_tuple(node, "dir", [0, 1, 0], override_expression=True)
        assert [p.evaluated_on_clear for p in components] == [["0"], ["0"], ["0"]]
        assert values == [0, 1, 0]
        assert "expression_kept" not in report


###### String parameters echo their raw text


class TestRawValue:
    def test_a_string_parm_echoes_its_raw_text(self, monkeypatch):
        parm = _Parm("file", value="", string=True)
        result = _set(monkeypatch, parm, "$JOB/geo/probe_$F4.bgeo.sc")
        assert result["raw_value"] == "$JOB/geo/probe_$F4.bgeo.sc"
        assert result["new_value"] == "/work/proj/geo/probe_0001.bgeo.sc"

    def test_a_numeric_parm_has_no_raw_value(self, monkeypatch):
        result = _set(monkeypatch, _Parm("scale", value=2.0), 2.0)
        assert "raw_value" not in result

    def test_a_string_tuple_echoes_raw_text_per_component(self):
        a = _Parm("a", value="", string=True)
        b = _Parm("b", value=0)
        node = _node("/obj/geo1")
        node.parmTuple.return_value = _Tuple([a, b])
        values, report = parameters._set_tuple(node, "ab", ["$JOB/x", 1])
        assert values == ["/work/proj/x", 1]
        assert report["raw_value"] == ["$JOB/x", None]


###### The client tools


class TestClientTools:
    async def test_set_parameter_forwards_override_expression(self, mock_ctx, mock_bridge):
        from fxhoudinimcp.tools.parameters import set_parameter

        await set_parameter(mock_ctx, "/obj/geo1/n", "tx", 1.0, override_expression=True)
        payload = mock_bridge.execute.call_args.args[1]
        assert payload["override_expression"] is True

    async def test_set_parameters_defaults_to_reporting(self, mock_ctx, mock_bridge):
        from fxhoudinimcp.tools.parameters import set_parameters

        await set_parameters(mock_ctx, "/obj/geo1/n", {"tx": 1.0})
        payload = mock_bridge.execute.call_args.args[1]
        assert payload["override_expression"] is False
