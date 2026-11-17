"""link_parameters refuses multiparms numbered from different first indices.

opmultiparm puts one instance number in both '#': with the source counted
from 1 and the destination from 0 (multistartoffset), dst0 read src0, which
does not exist, and every new entry is created the same way.

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
import fxhoudinimcp_server.handlers.parameter_handlers as parameters  # noqa: E402


class TestLinkRefusesMixedFirstIndices:
    def _multiparm(self, name, offset):
        parm = MagicMock()
        parm.name.return_value = name
        parm.path.return_value = f"/obj/n/{name}"
        template = parm.parmTemplate.return_value
        template.type.return_value = "folder"
        template.tags.return_value = {} if offset is None else {"multistartoffset": str(offset)}
        return parm

    def test_mixed_offsets_are_refused_before_anything_changes(self, monkeypatch):
        monkeypatch.setattr(parameters, "_entry_patterns", lambda p: [f"{p.name()}#"])
        hscript = MagicMock(return_value=("", ""))
        monkeypatch.setattr(parameters.hou, "hscript", hscript)
        src, dst = self._multiparm("src", None), self._multiparm("dst", 0)
        with pytest.raises(ValueError, match=r"from 0 .* from 1 \(multistartoffset\)"):
            parameters._link_multiparm(src, dst, "")
        dst.set.assert_not_called()
        dst.deleteAllKeyframes.assert_not_called()
        hscript.assert_not_called()

    def test_equal_offsets_still_link(self, monkeypatch):
        monkeypatch.setattr(parameters, "_entry_patterns", lambda p: [f"{p.name()}#"])
        hscript = MagicMock(return_value=("", ""))
        monkeypatch.setattr(parameters.hou, "hscript", hscript)
        src, dst = self._multiparm("src", 0), self._multiparm("dst", 0)
        result = parameters._link_multiparm(src, dst, "")
        assert result["multiparm_links"] == [["dst#", "src#"]]
        hscript.assert_called_once()
