"""create_hda signs a Copernicus subnet's connectors from the subnet's own parms.

createDigitalAsset signs them with what the wires carry when it runs: a cable
output came out { Mono } (or undef), and a cableunpack after the asset found no
fields. The subnet declares its connectors in inputtype#/outputtype# and the
label parms; the definition's input/output/signature lines are rewritten from
those and read back in `connectors`.

hou is mocked here; the live check ran on Houdini 22.0.466.
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
import fxhoudinimcp_server.handlers.hda_handlers as hda  # noqa: E402

_SCRIPT = (
    "# Dialog script for e1 automatically generated\n\n{\n    name\te1\n    script\te1\n"
    '    label\tE1\n\n    input\tinput1\t"src"\n    output\toutput1\t"dst"\n'
    '    signature\tdefault\t"Default"\t{ RGBA }\t{ Mono }\n\n'
    '    help {\n\t""\n    }\n\n    parm {\n        name    "k"\n    }\n}\n'
)


class _Definition:
    def __init__(self, script=_SCRIPT):
        self.script = script
        self.max_inputs = 1
        self.min_inputs = 1

    def sections(self):
        section = MagicMock()
        section.contents.return_value = self.script
        return {"DialogScript": section}

    def addSection(self, name, contents):  # noqa: N802 (HOM's name)
        assert name == "DialogScript"
        self.script = contents

    def setMaxNumInputs(self, n):  # noqa: N802
        self.max_inputs = n

    def maxNumInputs(self):  # noqa: N802
        return self.max_inputs

    def minNumInputs(self):  # noqa: N802
        return self.min_inputs

    def setMinNumInputs(self, n):  # noqa: N802
        self.min_inputs = n

    def nodeTypeName(self):  # noqa: N802
        return "e1"


class TestDialogScriptConnectors:
    def test_read(self):
        read = hda._read_connectors(_Definition())
        assert read["inputs"] == [{"name": "input1", "label": "src", "type": "RGBA"}]
        assert read["outputs"] == [{"name": "output1", "label": "dst", "type": "Mono"}]

    def test_write_replaces_the_lines_in_place_and_reads_back(self):
        definition = _Definition()
        hda._write_connectors(
            definition,
            [
                {"name": "height", "label": "Height", "type": "Mono"},
                {"name": "m", "label": 'a "b"', "type": "RGB"},
            ],
            [{"name": "layers", "label": "Layers", "type": "Cable"}],
        )
        lines = definition.script.splitlines()
        assert lines.index('    input\theight\t"Height"') == lines.index("    label\tE1") + 2
        assert '    signature\tdefault\t"Default"\t{ Mono RGB }\t{ Cable }' in lines
        assert "src" not in definition.script and "parm {" in definition.script
        read = hda._read_connectors(definition)
        assert read["inputs"][1] == {"name": "m", "label": 'a "b"', "type": "RGB"}
        assert read["outputs"] == [{"name": "layers", "label": "Layers", "type": "Cable"}]


def _cop_subnet(types_in, types_out, labels_in=(), labels_out=()):
    node = MagicMock()
    node.type.return_value.category.return_value.name.return_value = "Cop"
    values = {"inputs": len(types_in), "outputs": len(types_out)}
    for side, types, labels in (("input", types_in, labels_in), ("output", types_out, labels_out)):
        for n, token in enumerate(types, 1):
            values[f"{side}type{n}"] = token
            values[f"{side}label{n}"] = labels[n - 1] if n - 1 < len(labels) else ""

    def parm(name):
        if name not in values:
            return None
        p = MagicMock()
        p.evalAsString.return_value = str(values[name])
        p.evalAsInt.return_value = values[name]
        return p

    node.parm.side_effect = parm
    node.inputNames.return_value = tuple(f"input{n}" for n in range(1, len(types_in) + 1))
    node.outputNames.return_value = tuple(f"output{n}" for n in range(1, len(types_out) + 1))
    return node


class TestCreateHdaSignsCopConnectors:
    def test_the_subnet_parms_are_what_gets_signed(self):
        node = _cop_subnet(["vector4", "float"], ["cable"], ["src", "Mask"], ["Layers"])
        inputs, outputs = hda._subnet_connectors(node)
        assert [c["type"] for c in inputs] == ["RGBA", "Mono"]
        assert inputs[1]["label"] == "Mask"
        assert outputs == [{"name": "output1", "label": "Layers", "type": "Cable"}]

    def test_a_sop_subnet_is_left_to_houdini(self):
        node = MagicMock()
        node.type.return_value.category.return_value.name.return_value = "Sop"
        assert hda._subnet_connectors(node) is None

    def test_create_hda_rewrites_the_signature_and_reads_it_back(self, monkeypatch):
        node = _cop_subnet(["vector4"], ["cable"], [], ["Layers"])
        node.inputs.return_value = ()
        node.indirectInputs.return_value = ()
        definition = _Definition()
        asset = MagicMock()
        asset.type.return_value.definition.return_value = definition
        node.createDigitalAsset.return_value = asset
        monkeypatch.setattr(hda, "_get_node", lambda path: node)
        monkeypatch.setattr(hda, "require_inside_project_root", lambda *a, **k: None)
        monkeypatch.setattr(hda, "_promote_spares_to_definition", lambda n: [])
        result = hda.create_hda("/obj/cn/s", "/tmp/e1.hda", "e1", "E1")
        assert node.createDigitalAsset.call_args.kwargs["max_num_inputs"] == 1
        assert result["connectors"]["outputs"] == [
            {"name": "output1", "label": "Layers", "type": "Cable"}
        ]
        assert "{ RGBA }\t{ Cable }" in definition.script
        assert result["max_num_inputs"] == definition.max_inputs

    def test_a_signing_failure_after_the_asset_exists_is_a_warning(self, monkeypatch):
        # The subnet is already an asset: raising would tell the caller nothing was made.
        node = _cop_subnet(["vector4"], ["cable"], [], ["Layers"])
        node.inputs.return_value = ()
        node.indirectInputs.return_value = ()
        definition = _Definition()
        asset = MagicMock()
        asset.type.return_value.definition.return_value = definition
        node.createDigitalAsset.return_value = asset
        monkeypatch.setattr(hda, "_get_node", lambda path: node)
        monkeypatch.setattr(hda, "require_inside_project_root", lambda *a, **k: None)
        monkeypatch.setattr(hda, "_promote_spares_to_definition", lambda n: [])
        monkeypatch.setattr(hda, "_write_connectors", MagicMock(side_effect=KeyError("layout")))
        result = hda.create_hda("/obj/cn/s", "/tmp/e1.hda", "e1", "E1")
        assert result["success"] is True
        assert "could not be signed" in result["warning"]
