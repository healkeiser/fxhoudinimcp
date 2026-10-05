"""Tests for get_parameters(inside=...), one pattern read across a network.

"Every file parameter of this material library, unexpanded" had no verb: it
was find_nodes plus one get_parameters per node, 68 calls in one session, or
an execute_python. get_parameters now takes `inside` (a network) instead of
`node_path` and answers one table of `rows` {node, parm, value, raw_value},
capped at 2000 rows with `truncated`. `patterns` is required there, and
`node_path` with `inside` is refused.

A recursive sweep does not read the nodes inside locked HDAs (the instance
itself is read): a POP network's file patterns came back as hundreds of rows
of the solvers' own internals. They are counted in
`skipped_inside_locked_assets`; include_locked_assets=True reads them.

non_default_only=True keeps only the parameters changed from their defaults,
each with its default beside the value; with `inside` it needs no patterns.
"What was changed on these 33 nodes of a POP network" was 33 get_node_info
calls or an execute_python.

hou is mocked here and only through monkeypatch; the live check ran on
Houdini 22.0.429 (six file SOPs, one call, six rows, `$JOB` visible raw).
"""

from __future__ import annotations

# Built-in
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

# Third-party
import pytest

sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Internal
import fxhoudinimcp_server.handlers.parameter_handlers as parameters  # noqa: E402


class _OperationFailed(Exception):
    pass


@pytest.fixture(autouse=True)
def _hou(monkeypatch):
    monkeypatch.setattr(parameters, "_parm_type_name", lambda pt: pt.kind)
    monkeypatch.setattr(parameters.hou, "OperationFailed", _OperationFailed)
    # The shared hou mock has no real Vector/Matrix types to test against.
    monkeypatch.setattr(parameters, "_serialize_value", lambda value: value)


def _parm(name, value, raw=None, kind="String", label=None):
    parm = MagicMock()
    parm.name.return_value = name
    parm.eval.return_value = value
    parm.rawValue.return_value = raw if raw is not None else str(value)
    parm.isAtDefault.return_value = False
    template = MagicMock()
    template.kind = kind
    template.label.return_value = label or name.title()
    template.type.return_value.name.return_value = kind
    parm.parmTemplate.return_value = template
    return parm


def _node(path, type_name, parms, inside_locked=False):
    node = MagicMock()
    node.path.return_value = path
    node.type.return_value.name.return_value = type_name
    node.parms.return_value = list(parms)
    node.isLockedHDA.return_value = False
    node.isInsideLockedHDA.return_value = inside_locked
    return node


def _image(path, raw):
    return _node(
        path,
        "mtlximage",
        [
            _parm("file", raw.replace("$JOB", "/work/proj"), raw=raw),
            _parm("filtertype", 1, kind="Int"),
        ],
    )


def _library(monkeypatch, children, descendants=None):
    parent = MagicMock()
    parent.path.return_value = "/mat/lib"
    parent.isLockedHDA.return_value = False
    parent.isInsideLockedHDA.return_value = False
    parent.children.return_value = list(children)
    parent.allSubChildren.return_value = list(descendants or children)
    monkeypatch.setattr(parameters.hou, "node", lambda path: parent if path == "/mat/lib" else None)
    return parent


class TestRecursiveSweepStopsAtLockedAssets:
    def _popnet(self, monkeypatch):
        solver = _node("/obj/sim/popnet/popsolver1", "popsolver", [_parm("file", "")])
        buried = _node(
            "/obj/sim/popnet/popsolver1/filedef",
            "file",
            [_parm("file", "default.bgeo")],
            inside_locked=True,
        )
        cache = _node("/obj/sim/filecache1", "filecache", [_parm("file", "$HIP/sim.bgeo.sc")])
        parent = _library(monkeypatch, [], descendants=[solver, buried, cache])
        return parent

    def test_the_insides_of_a_locked_asset_are_skipped_and_counted(self, monkeypatch):
        self._popnet(monkeypatch)
        result = parameters._get_parameters(inside="/mat/lib", patterns=["file"], recursive=True)
        assert [r["node"] for r in result["rows"]] == [
            "/obj/sim/popnet/popsolver1",
            "/obj/sim/filecache1",
        ]
        assert result["nodes_scanned"] == 2
        assert result["skipped_inside_locked_assets"] == 1
        assert "include_locked_assets=True" in result["note"]

    def test_include_locked_assets_reads_them(self, monkeypatch):
        self._popnet(monkeypatch)
        result = parameters._get_parameters(
            inside="/mat/lib", patterns=["file"], recursive=True, include_locked_assets=True
        )
        assert len(result["rows"]) == 3
        assert "skipped_inside_locked_assets" not in result
        assert "note" not in result

    def test_reading_inside_loads_the_delayed_contents(self, monkeypatch):
        # A fresh popsolver's ~670 nodes are not loaded until synced, so
        # include_locked_assets answered none of them.
        parent = self._popnet(monkeypatch)
        parameters._get_parameters(
            inside="/mat/lib", patterns=["file"], recursive=True, include_locked_assets=True
        )
        parent.allSubChildren.assert_called_once_with(sync_delayed_definition=True)
        parent.allSubChildren.reset_mock()
        parameters._get_parameters(inside="/mat/lib", patterns=["file"], recursive=True)
        parent.allSubChildren.assert_called_once_with(sync_delayed_definition=False)

    def test_a_sweep_that_starts_inside_a_locked_asset_reads_it(self, monkeypatch):
        parent = self._popnet(monkeypatch)
        parent.isLockedHDA.return_value = True
        result = parameters._get_parameters(inside="/mat/lib", patterns=["file"], recursive=True)
        assert len(result["rows"]) == 3
        assert "skipped_inside_locked_assets" not in result

    def test_the_skipped_count_follows_node_type(self, monkeypatch):
        # node_type="file" scanned 2 and reported every buried node skipped.
        self._popnet(monkeypatch)
        result = parameters._get_parameters(
            inside="/mat/lib", patterns=["file"], recursive=True, node_type="filecache"
        )
        assert result["nodes_scanned"] == 1
        # The one buried node is a "file", not a "filecache": nothing to skip.
        assert "skipped_inside_locked_assets" not in result

    def test_nothing_skipped_answers_as_before(self, monkeypatch):
        _library(monkeypatch, [], descendants=[_image("/mat/lib/sub/img", "$JOB/a.exr")])
        result = parameters._get_parameters(inside="/mat/lib", patterns=["file"], recursive=True)
        assert len(result["rows"]) == 1
        assert "skipped_inside_locked_assets" not in result


class TestGetParametersInsideANetwork:
    def test_one_call_one_row_per_parm_with_the_raw_text(self, monkeypatch):
        _library(
            monkeypatch,
            [
                _image("/mat/lib/base_color", "$JOB/tex/wood_col.exr"),
                _image("/mat/lib/rough", "/abs/tex/wood_rough.exr"),
            ],
        )
        result = parameters._get_parameters(inside="/mat/lib", patterns=["file"])
        assert [(r["node"], r["parm"], r.get("raw_value")) for r in result["rows"]] == [
            ("/mat/lib/base_color", "file", "$JOB/tex/wood_col.exr"),
            ("/mat/lib/rough", "file", None),
        ]
        assert result["rows"][0]["value"] == "/work/proj/tex/wood_col.exr"
        assert result["nodes_scanned"] == 2
        assert result["nodes_matched"] == 2
        assert result["truncated"] is False

    def test_patterns_are_required(self, monkeypatch):
        _library(monkeypatch, [_image("/mat/lib/a", "$JOB/a.exr")])
        with pytest.raises(ValueError, match="patterns is required"):
            parameters._get_parameters(inside="/mat/lib")

    def test_node_path_and_inside_together_are_refused(self):
        with pytest.raises(ValueError, match="not both"):
            parameters._get_parameters(
                node_path="/mat/lib/rough", inside="/mat/lib", patterns=["file"]
            )

    def test_neither_node_path_nor_inside_is_refused(self):
        with pytest.raises(ValueError, match="node_path is required"):
            parameters._get_parameters(patterns=["file"])

    def test_a_missing_network_is_named(self, monkeypatch):
        _library(monkeypatch, [])
        with pytest.raises(_OperationFailed, match="/mat/nope"):
            parameters._get_parameters(inside="/mat/nope", patterns=["file"])

    def test_node_type_narrows_and_recursive_reaches_descendants(self, monkeypatch):
        image = _image("/mat/lib/sub/img", "$JOB/a.exr")
        other = _node("/mat/lib/sub/null", "null", [_parm("file", "x")])
        parent = _library(monkeypatch, [], descendants=[image, other])
        result = parameters._get_parameters(
            inside="/mat/lib", patterns=["file"], recursive=True, node_type="mtlximage"
        )
        assert [r["node"] for r in result["rows"]] == ["/mat/lib/sub/img"]
        assert result["nodes_scanned"] == 1
        parent.children.assert_not_called()

    def test_a_button_matched_by_label_is_not_a_row(self, monkeypatch):
        node = _node(
            "/mat/lib/cache",
            "filecache",
            [_parm("file", "a.bgeo"), _parm("reload", 0, kind="Button", label="Reload File")],
        )
        _library(monkeypatch, [node])
        result = parameters._get_parameters(inside="/mat/lib", patterns=["file"])
        assert [r["parm"] for r in result["rows"]] == ["file"]

    def test_rows_past_the_cap_are_counted_and_flagged(self, monkeypatch):
        monkeypatch.setattr(parameters, "_SWEEP_ROW_CAP", 3)
        _library(monkeypatch, [_image(f"/mat/lib/img{i}", "$JOB/a.exr") for i in range(5)])
        result = parameters._get_parameters(inside="/mat/lib", patterns="file")
        assert result["returned"] == 3
        assert result["matched"] == 5
        assert result["truncated"] is True
        assert result["patterns"] == ["file"]

    def test_include_defaults_reaches_the_rows(self, monkeypatch):
        _library(monkeypatch, [_image("/mat/lib/a", "$JOB/a.exr")])
        result = parameters._get_parameters(
            inside="/mat/lib", patterns=["file"], include_defaults=True
        )
        assert result["rows"][0]["is_at_default"] is False

    def test_a_single_node_still_answers_parameters(self, monkeypatch):
        node = _image("/mat/lib/a", "$JOB/a.exr")
        monkeypatch.setattr(parameters.hou, "node", lambda path: node)
        result = parameters._get_parameters("/mat/lib/a", patterns=["file"])
        assert result["parameters"]["file"]["raw_value"] == "$JOB/a.exr"
        assert "rows" not in result


class TestDefaultBesideTheValue:
    """include_defaults said "changed" without saying from what."""

    def _with_default(self, parm, defaults, index=0, expressions=("",)):
        parm.componentIndex.return_value = index
        template = parm.parmTemplate.return_value
        template.defaultValue.return_value = defaults
        template.defaultExpression.return_value = expressions
        return parm

    def test_the_component_default_is_reported(self):
        parm = self._with_default(_parm("ty", 2.5, kind="Float"), (0.0, 1.0, 0.0), index=1)
        assert parameters._default_of(parm) == {"default": 1.0}

    def test_a_default_expression_is_named(self):
        parm = self._with_default(_parm("f1", 1, kind="Float"), (1.0,), expressions=("$FSTART",))
        assert parameters._default_of(parm) == {"default": 1.0, "default_expression": "$FSTART"}

    def test_a_single_string_expression_is_not_cut_to_one_character(self):
        # A toggle or a menu answers one value and one expression string.
        parm = self._with_default(_parm("enable", 1, kind="Toggle"), False, expressions="$F>1")
        assert parameters._default_of(parm) == {"default": False, "default_expression": "$F>1"}

    def test_a_toggle_token_is_not_an_expression(self):
        # box's rebar answers "off" from defaultExpression() on 22.0.368.
        parm = self._with_default(_parm("rebar", 0, kind="Toggle"), False, expressions="off")
        assert parameters._default_of(parm) == {"default": False}

    def test_a_template_without_a_default_answers_nothing(self):
        parm = _parm("folder", 0, kind="Folder")
        parm.parmTemplate.return_value.defaultValue.side_effect = AttributeError
        assert parameters._default_of(parm) == {}

    def test_a_single_node_reports_the_default_beside_the_value(self, monkeypatch):
        parm = self._with_default(_parm("sizex", 7.5, kind="Float"), (1.0,))
        node = _node("/obj/geo1/box1", "box", [parm])
        monkeypatch.setattr(parameters.hou, "node", lambda path: node)
        result = parameters._get_parameters("/obj/geo1/box1", include_defaults=True)
        assert result["parameters"]["sizex"] == {
            "value": 7.5,
            "is_at_default": False,
            "default": 1.0,
        }
        plain = parameters._get_parameters("/obj/geo1/box1")
        assert "default" not in plain["parameters"]["sizex"]

    def test_a_parm_at_its_default_does_not_repeat_it(self, monkeypatch):
        # The default only repeats the value there: +85% on a popsource sweep.
        parm = self._with_default(_parm("sizex", 1.0, kind="Float"), (1.0,))
        parm.isAtDefault.return_value = True
        node = _node("/obj/geo1/box1", "box", [parm])
        monkeypatch.setattr(parameters.hou, "node", lambda path: node)
        result = parameters._get_parameters("/obj/geo1/box1", include_defaults=True)
        assert result["parameters"]["sizex"] == {"value": 1.0, "is_at_default": True}

    def test_the_default_reaches_the_rows(self, monkeypatch):
        image = _image("/mat/lib/a", "$JOB/a.exr")
        self._with_default(image.parms.return_value[0], ("",))
        _library(monkeypatch, [image])
        result = parameters._get_parameters(
            inside="/mat/lib", patterns=["file"], include_defaults=True
        )
        assert result["rows"][0]["default"] == ""


class TestOnlyWhatWasChanged:
    """Which parameters of a network were changed, and from what, in one call."""

    @staticmethod
    def _changed(name, value, default, at_default=False):
        parm = _parm(name, value, kind="Float")
        parm.isAtDefault.return_value = at_default
        parm.componentIndex.return_value = 0
        template = parm.parmTemplate.return_value
        template.defaultValue.return_value = (default,)
        template.defaultExpression.return_value = ("",)
        return parm

    def _source(self):
        return _node(
            "/mat/lib/source_first_input",
            "popsource",
            [
                self._changed("life", 1.0, 100.0),
                self._changed("seed", 0.0, 0.0, at_default=True),
            ],
        )

    def test_a_single_node_answers_only_the_changed_parm_with_its_default(self, monkeypatch):
        node = self._source()
        monkeypatch.setattr(parameters.hou, "node", lambda path: node)
        result = parameters._get_parameters("/mat/lib/source_first_input", non_default_only=True)
        assert result["parameters"] == {
            "life": {"value": 1.0, "is_at_default": False, "default": 100.0}
        }
        assert result["matched"] == 1

    def test_a_network_needs_no_patterns(self, monkeypatch):
        quiet = _node("/mat/lib/solver", "popsolver", [self._changed("substep", 1.0, 1.0, True)])
        _library(monkeypatch, [self._source(), quiet])
        result = parameters._get_parameters(inside="/mat/lib", non_default_only=True)
        assert [(r["node"], r["parm"], r["default"]) for r in result["rows"]] == [
            ("/mat/lib/source_first_input", "life", 100.0)
        ]
        assert result["nodes_scanned"] == 2
        assert result["nodes_matched"] == 1
        assert result["non_default_only"] is True

    def test_patterns_still_narrow_it(self, monkeypatch):
        _library(monkeypatch, [self._source()])
        result = parameters._get_parameters(
            inside="/mat/lib", patterns=["seed"], non_default_only=True
        )
        assert result["rows"] == []

    def test_a_parm_that_cannot_say_counts_as_default(self, monkeypatch):
        parm = self._changed("odd", 1.0, 0.0)
        parm.isAtDefault.side_effect = RuntimeError("no default")
        _library(monkeypatch, [_node("/mat/lib/n", "null", [parm])])
        result = parameters._get_parameters(inside="/mat/lib", non_default_only=True)
        assert result["rows"] == []

    def test_a_switched_folder_tab_is_not_a_change(self, monkeypatch):
        # A folder stores its open tab; measured on 22.0, a switched tab is
        # off its default.
        node = _node("/obj/geo1/w", "attribwrangle", [_parm("folder01", 1, kind="Folder")])
        monkeypatch.setattr(parameters.hou, "node", lambda path: node)
        result = parameters._get_parameters("/obj/geo1/w", non_default_only=True)
        assert result["parameters"] == {}

    def test_a_ramp_and_its_keys_answer_with_the_ramp_s_own_default(self, monkeypatch):
        # Measured on 22.0: a fresh popcolor's ramp2pos is off isAtDefault,
        # and the ramp parm stays at it after a key moved.
        monkeypatch.setattr(parameters.hou, "parmTemplateType", SimpleNamespace(Ramp="Ramp"))
        ramp = _parm("ramp", 2, kind="Ramp")
        ramp.parmTemplate.return_value.type.return_value = "Ramp"
        ramp.isAtDefault.return_value = True
        key = _parm("ramp2pos", 1.0, kind="Float")
        key.parentMultiParm.return_value = ramp
        ramp.isAtRampDefault.return_value = True
        assert not parameters._off_default(key)
        assert not parameters._off_default(ramp)
        ramp.isAtRampDefault.return_value = False
        assert parameters._off_default(key)
        assert parameters._off_default(ramp)

    def test_without_it_a_network_still_wants_patterns_and_names_the_way_out(self, monkeypatch):
        _library(monkeypatch, [self._source()])
        with pytest.raises(ValueError, match="non_default_only"):
            parameters._get_parameters(inside="/mat/lib")
        plain = parameters._get_parameters(inside="/mat/lib", patterns=["life"])
        assert "non_default_only" not in plain
