"""link_parameters links a ramp (or multiparm) entry by entry.

A ch() on a ramp links its key count only; the node then cooks its own keys
while evalAsRamp() shows the source ramp. Two multiparms of one kind are linked
the way Promote Parameter does it: opmultiparm, which only links entries
created after it, so the destination is emptied first.

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
import fxhoudinimcp_server.handlers.parameter_handlers as params  # noqa: E402

_FLOAT, _COLOR = object(), object()


def _ramp_parm(name, node_path, ramp_type, kind=_FLOAT):
    parm = MagicMock()
    parm.name.return_value = name
    parm.path.return_value = f"{node_path}/{name}"
    parm.node.return_value.path.return_value = node_path
    parm.parmTemplate.return_value.type.return_value = ramp_type
    parm.parmTemplate.return_value.parmType.return_value = kind
    # Real hou: a ramp set to 0 keys keeps one (the floor opmultiparm misses).
    first = MagicMock()
    first.multiParmInstanceIndices.return_value = (1,)
    parm.multiParmInstances.return_value = [first]
    return parm


class TestMultiparmLink:
    @pytest.fixture
    def ramps(self, monkeypatch):
        ramp_type = object()
        monkeypatch.setattr(
            params.hou, "parmTemplateType", MagicMock(Ramp=ramp_type), raising=False
        )
        monkeypatch.setattr(
            params.hou, "rampParmType", MagicMock(Float=_FLOAT, Color=_COLOR), raising=False
        )
        calls = []
        monkeypatch.setattr(
            params.hou, "hscript", lambda cmd: calls.append(cmd) or ("", ""), raising=False
        )
        return (
            _ramp_parm("myramp", "/obj/a", ramp_type),
            _ramp_parm("sloperamp", "/obj/b", ramp_type),
            calls,
        )

    def test_the_patterns_come_from_the_template(self, ramps):
        src, dst, _ = ramps
        assert params._entry_patterns(dst) == [
            "sloperamp#pos",
            "sloperamp#value",
            "sloperamp#interp",
        ]
        # A name ending in a digit takes "_" before the index (cr2_1pos).
        src.name.return_value = "r2"
        src.parmTemplate.return_value.parmType.return_value = _COLOR
        assert params._entry_patterns(src) == [
            "r2_#pos",
            "r2_#cr",
            "r2_#cg",
            "r2_#cb",
            "r2_#interp",
        ]

    def test_the_destination_is_emptied_then_linked_with_the_sources_names(self, ramps):
        src, dst, calls = ramps
        result = params._link_multiparm(src, dst, "../a")
        dst.set.assert_called_once_with(0)
        assert calls == [
            "opmultiparm /obj/b 'sloperamp#pos' '../a/myramp#pos' 'sloperamp#value' "
            "'../a/myramp#value' 'sloperamp#interp' '../a/myramp#interp'"
        ]
        assert result["is_ramp"] is True

    def test_a_color_ramp_into_a_float_ramp_is_refused(self, ramps):
        src, dst, calls = ramps
        src.parmTemplate.return_value.parmType.return_value = _COLOR
        with pytest.raises(ValueError, match="not the same kind of multiparm"):
            params._link_multiparm(src, dst, "../a")
        assert calls == []

    def test_the_key_a_ramp_keeps_is_linked_too(self, ramps, monkeypatch):
        _, dst, _ = ramps
        set_calls = []
        monkeypatch.setattr(
            params, "set_whole_expression", lambda parm, expr, lang: set_calls.append(expr)
        )
        monkeypatch.setattr(params, "_channel_function", lambda parm: "ch")
        dst.node.return_value.parm.return_value.keyframes.return_value = []
        params._link_surviving_entries(dst, [("sloperamp#value", "../a/myramp#value")])
        dst.node.return_value.parm.assert_called_with("sloperamp1value")
        assert set_calls == ['ch("../a/myramp1value")']

    def test_an_opmultiparm_error_is_raised(self, ramps, monkeypatch):
        src, dst, _ = ramps
        monkeypatch.setattr(
            params.hou, "hscript", lambda cmd: ("", "Error: no # characters"), raising=False
        )
        with pytest.raises(
            ValueError, match="opmultiparm refused the link: Error: no # characters"
        ):
            params._link_multiparm(src, dst, "../a")

    def test_a_mock_is_not_a_multiparm(self):
        assert params._is_multiparm_parent(MagicMock()) is False
