"""build_network's strict-menu check must leave the VOP signature menu to Houdini.

The check reads menu items off a fresh probe node. A MaterialX node's
``signature`` menu lists only the signature it currently has ("default" on a
fresh mtlxmultiply), while ``set("color3")`` is accepted and
``currentSignatureName()`` then reports color3. So ``{"signature": "color3"}``
failed validation with "'color3' is not a menu item. Items: ['default']" and a
typed MaterialX graph could not be built in one call.
"""

from __future__ import annotations

# Built-in
import os
import sys
from unittest.mock import MagicMock

sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Internal
import fxhoudinimcp_server.handlers.graph_handlers as graph  # noqa: E402

hou = graph.hou


def _scratch(category: str, parm_names: list[str]):
    probe = MagicMock()
    probe.type.return_value.category.return_value.name.return_value = category
    parms = []
    for name in parm_names:
        parm = MagicMock()
        parm.name.return_value = name
        parm.menuItems.return_value = ["default"]
        parm.parmTemplate.return_value.type.return_value = hou.parmTemplateType.Menu
        parms.append(parm)
    probe.parms.return_value = parms
    probe.parmTuples.return_value = []
    scratch = MagicMock()
    scratch.createNode.return_value = probe
    return scratch


class TestSignatureMenuIsLeftToHoudini:
    def test_vop_signature_menu_is_not_validated(self, monkeypatch):
        monkeypatch.setattr(graph, "_instance_patterns", lambda node_type: [])
        _, _, menus, _ = graph._parm_names_for_type(
            _scratch("Vop", ["signature", "operation"]), MagicMock()
        )
        assert "signature" not in menus
        assert menus["operation"] == ["default"]

    def test_a_sop_parameter_called_signature_is_still_checked(self, monkeypatch):
        monkeypatch.setattr(graph, "_instance_patterns", lambda node_type: [])
        _, _, menus, _ = graph._parm_names_for_type(_scratch("Sop", ["signature"]), MagicMock())
        assert menus["signature"] == ["default"]
