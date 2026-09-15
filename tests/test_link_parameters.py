"""link_parameters wrote ch("/absolute/path") for a String parameter.

ch() evaluates the referenced channel as a number, so four String spare parms
inside an HDA read back "0" after linking; and an absolute path breaks the
moment the pair is moved, collapsed or instanced. The handler now picks chs()
for a String destination and writes the path relative to the destination node,
as Houdini's own Paste Relative References does.

hou is mocked here; the live check ran on Houdini 22.0.429.
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
import fxhoudinimcp_server.handlers.parameter_handlers as parms  # noqa: E402

hou = parms.hou


def _parm(node, name, kind, value):
    parm = MagicMock()
    parm.name.return_value = name
    parm.path.return_value = f"{node.path()}/{name}"
    parm.node.return_value = node
    parm.parmTemplate.return_value.type.return_value = kind
    parm.eval.return_value = value
    return parm


def _node(path, rel_to):
    node = MagicMock()
    node.path.return_value = path
    node.relativePathTo.side_effect = lambda other: rel_to
    return node


def _link(monkeypatch, src, dst):
    lookup = {(src.node().path(), src.name()): src, (dst.node().path(), dst.name()): dst}
    monkeypatch.setattr(
        parms, "_resolve_parm", lambda node_path, parm_name: lookup[(node_path, parm_name)]
    )
    monkeypatch.setattr(parms, "_serialize_value", lambda value: value)
    return parms._link_parameters(
        source_path=src.node().path(),
        source_parm=src.name(),
        dest_path=dst.node().path(),
        dest_parm=dst.name(),
    )


class TestStringParmsAreLinkedWithChs:
    def test_string_destination_uses_chs_and_a_relative_path(self, monkeypatch):
        ctrl = _node("/obj/gaps/CONTROL", "../CONTROL")
        n2 = _node("/obj/gaps/n2", "../CONTROL")
        src = _parm(ctrl, "mat", hou.parmTemplateType.String, "/obj/shopnet1/brick")
        dst = _parm(n2, "label", hou.parmTemplateType.String, "/obj/shopnet1/brick")

        reply = _link(monkeypatch, src, dst)

        dst.setExpression.assert_called_once_with('chs("../CONTROL/mat")', hou.exprLanguage.Hscript)
        assert reply["expression"] == 'chs("../CONTROL/mat")'
        assert reply["function"] == "chs"
        assert reply["relative"] is True
        assert reply["value"] == "/obj/shopnet1/brick"
        assert "warning" not in reply

    def test_float_destination_keeps_ch(self, monkeypatch):
        a = _node("/obj/geo1/box1", "../box2")
        b = _node("/obj/geo1/box2", "../box1")
        src = _parm(a, "sizex", hou.parmTemplateType.Float, 7.0)
        dst = _parm(b, "sizex", hou.parmTemplateType.Float, 7.0)

        reply = _link(monkeypatch, src, dst)

        assert reply["expression"] == 'ch("../box1/sizex")'
        assert reply["function"] == "ch"
        assert reply["value"] == 7.0

    def test_same_node_is_a_bare_parameter_name(self, monkeypatch):
        node = _node("/obj/geo1/box1", ".")
        src = _parm(node, "sizex", hou.parmTemplateType.Float, 1.0)
        dst = _parm(node, "sizey", hou.parmTemplateType.Float, 1.0)

        reply = _link(monkeypatch, src, dst)

        assert reply["expression"] == 'ch("sizex")'

    def test_mixed_types_are_named_in_a_warning(self, monkeypatch):
        ctrl = _node("/obj/CONTROL", "../CONTROL")
        n2 = _node("/obj/n2", "../CONTROL")
        src = _parm(ctrl, "count", hou.parmTemplateType.Int, 3)
        dst = _parm(n2, "label", hou.parmTemplateType.String, "3")

        reply = _link(monkeypatch, src, dst)

        assert reply["function"] == "chs"
        assert "converts the value on read" in reply["warning"]
