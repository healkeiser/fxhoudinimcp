"""A ramp refuses join_with_next and label_hidden, which Houdini does not store.

RampParmTemplate takes both, but the DialogScript Houdini writes drops
`joinnext` and `nolabel` from a ramp_flt / ramp_rgb parm (a Float keeps them):
set_hda_interface answered success over a definition without them.

hou is mocked here; the live check ran on Houdini 22.0.466."""

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

hou = hda.hou


class TestRampLayoutIsRefused:
    @pytest.mark.parametrize("key", ["join_with_next", "label_hidden"])
    def test_a_ramp_spec_with_the_key_is_refused(self, key):
        with pytest.raises(ValueError, match=f"does not store {key} on a ramp"):
            hda._build_parm_template({"name": "r", "type": "ramp_float", key: True}, set())

    def test_a_ramp_without_them_builds(self, monkeypatch):
        built = []
        monkeypatch.setattr(
            hda.hou, "RampParmTemplate", lambda *a, **k: built.append((a, k)) or MagicMock()
        )
        hda._build_parm_template({"name": "r", "type": "ramp_float", "callback": "x()"}, set())
        assert built and built[0][1].get("script_callback") == "x()"

    def test_from_parm_on_a_ramp_refuses_them(self, monkeypatch):
        template = MagicMock()
        template.type.return_value = hou.parmTemplateType.Ramp
        parm = MagicMock()
        parm.parmTemplate.return_value.clone.return_value = template
        monkeypatch.setattr(hda.hou, "parm", lambda path: parm, raising=False)
        with pytest.raises(ValueError, match="does not store label_hidden on a ramp"):
            hda._cloned_template({"from_parm": "/obj/n/ramp", "label_hidden": True}, "r")

    def test_modify_join_on_a_ramp_is_refused(self):
        template = MagicMock()
        template.type.return_value = hou.parmTemplateType.Ramp
        template.name.return_value = "r"
        with pytest.raises(ValueError, match="join_with_next on a ramp"):
            hda._modify_template(template, {"join_with_next": True})
        template.setJoinWithNext.assert_not_called()
