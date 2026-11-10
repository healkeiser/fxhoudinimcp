"""set_hda_interface checks every spec key; look, ramps with keys, from_parm.

`look` and `is_label_hidden` came back success over templates that had neither:
spec keys were never checked. Ramp parameters can now carry their default keys,
and from_parm copies another node's parameter template, a stock ramp with its
keys.

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
import fxhoudinimcp_server.handlers.hda_handlers as hda  # noqa: E402


class TestInterfaceSpecs:
    def test_an_unknown_key_is_refused_with_a_guess(self):
        with pytest.raises(ValueError, match=r"unknown key\(s\) 'looks' \(did you mean look\?\)"):
            hda._check_spec_keys({"name": "z", "looks": "log"})

    def test_is_label_hidden_is_the_same_key(self):
        assert hda._SPEC_ALIASES["is_label_hidden"] == "label_hidden"

    @pytest.mark.parametrize(
        "spelling", ["logarithmic", "Log", "parmLook.Logarithmic", "LOGARITHMIC"]
    )
    def test_a_look_in_any_spelling(self, spelling, monkeypatch):
        monkeypatch.setattr(hda.hou, "parmLook", MagicMock(Logarithmic="LOG"), raising=False)
        assert hda._look({"name": "a", "look": spelling}) == "LOG"

    def test_an_unknown_look_is_named(self):
        with pytest.raises(ValueError, match="unknown look 'wavy'"):
            hda._look({"name": "a", "look": "wavy"})

    def test_ramp_keys_become_houdinis_default_tag(self):
        tag, count = hda._ramp_default_tag(
            {
                "name": "r",
                "default": [
                    {"pos": 0, "value": 0},
                    {"pos": 1, "value": 1, "interp": "catmull-rom"},
                ],
            },
            color=False,
        )
        assert count == 2
        assert (
            tag
            == "1pos ( 0.0 ) 1value ( 0.0 ) 1interp ( linear ) 2pos ( 1.0 ) 2value ( 1.0 ) 2interp ( catmull-rom )"
        )
        tag, _ = hda._ramp_default_tag(
            {"name": "c", "default": [{"pos": 0, "value": [1, 0, 0]}]}, color=True
        )
        assert tag == "1pos ( 0.0 ) 1c ( 1.0 0.0 0.0 ) 1interp ( linear )"

    @pytest.mark.parametrize(
        ("default", "match"),
        [
            ([{"pos": 0}], "needs pos and value"),
            ([{"pos": 0, "value": 1, "interp": "smooth"}], "interp 'smooth'"),
            ("0,1", "list of keys"),
        ],
    )
    def test_bad_ramp_keys_are_named(self, default, match):
        with pytest.raises(ValueError, match=match):
            hda._ramp_default_tag({"name": "r", "default": default}, color=False)

    def test_a_color_key_needs_three_values(self):
        with pytest.raises(ValueError, match=r"\[r, g, b\]"):
            hda._ramp_default_tag({"name": "c", "default": [{"pos": 0, "value": 1}]}, color=True)

    def test_from_parm_clones_and_renames(self, monkeypatch):
        source = MagicMock()
        clone = source.parmTemplate.return_value.clone.return_value
        monkeypatch.setattr(
            hda.hou,
            "parm",
            lambda path: source if path == "/obj/m/sloperamp" else None,
            raising=False,
        )
        template = hda._cloned_template(
            {"from_parm": "/obj/m/sloperamp", "label": "Slope", "label_hidden": True}, "slope"
        )
        assert template is clone
        clone.setName.assert_called_once_with("slope")
        clone.setLabel.assert_called_once_with("Slope")
        clone.hideLabel.assert_called_once_with(True)

    def test_from_parm_that_is_not_a_parm_is_named(self, monkeypatch):
        monkeypatch.setattr(hda.hou, "parm", lambda path: None, raising=False)
        monkeypatch.setattr(hda.hou, "parmTuple", lambda path: None, raising=False)
        with pytest.raises(ValueError, match="from_parm '/obj/m/nope' is not a parameter"):
            hda._cloned_template({"from_parm": "/obj/m/nope"}, "x")

    def test_from_parm_refuses_keys_it_would_ignore(self):
        # The clone keeps the source's type, default and range whole.
        with pytest.raises(
            ValueError, match=r"from_parm copies the template whole, so \['default'\]"
        ):
            hda._build_parm_template({"name": "s", "from_parm": "/obj/n/ramp", "default": 1}, set())
