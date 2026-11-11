"""get_cop_layer reads a cable output as a cable.

A five-wire blend output read back as its first wire, under the output's name,
with nothing to say other wires existed. HOM has no cable flag: a plain output
is a cable of one wire, often named ("noise"), and outputDataTypes() answers
Mono for a cablepack. More than one wire is a cable.

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
import fxhoudinimcp_server.handlers.cop_handlers as cops  # noqa: E402


class _Layer:
    def __init__(self, values, channels=1, res=(2, 2), storage="Float32", data_type=None):
        import array

        self._bytes = array.array("f", values).tobytes()
        self._channels, self._res, self._storage = channels, res, storage
        self.data_type = data_type or ("Mono" if channels == 1 else "RGB")

    def storageType(self):  # noqa: N802
        return self._storage

    def bufferResolution(self):  # noqa: N802
        return self._res

    def channelCount(self):  # noqa: N802
        return self._channels

    def allBufferElements(self, *_):  # noqa: N802
        # Real hou converts to the storage asked for (Float32, 1 channel).
        return self._bytes


class _Cable:
    def __init__(self, wires):
        self._wires = wires  # [(name, layer)]

    def wireCount(self):  # noqa: N802
        return len(self._wires)

    def wireNames(self):  # noqa: N802
        return tuple(name for name, _ in self._wires)

    def wireName(self, i):  # noqa: N802
        return self._wires[i][0]

    def layerByIndex(self, i):  # noqa: N802
        return self._wires[i][1]

    def wireDataTypeByIndex(self, i):  # noqa: N802
        return self._wires[i][1].data_type


def _cop(cable):
    node = MagicMock()
    node.cable.return_value = cable
    return node


class TestCable:
    def test_one_wire_is_a_plain_layer_named_or_not(self):
        # A Fractal Noise output is one wire named "noise" (22.0.466).
        assert cops._output_cable(_cop(_Cable([("", _Layer([0] * 4))])), 0) is None
        assert cops._output_cable(_cop(_Cable([("noise", _Layer([0] * 4))])), 0) is None

    def test_two_wires_are_a_cable(self):
        two = _Cable([("", _Layer([0] * 4)), ("", _Layer([0] * 4))])
        assert cops._output_cable(_cop(two), 0) is two

    def test_a_wire_by_name_or_index(self):
        cable = _Cable([("dirt", None), ("rock", None)])
        assert cops._resolve_wire(cable, "rock") == 1
        assert cops._resolve_wire(cable, 1) == 1
        assert cops._resolve_wire(cable, "1") == 1
        with pytest.raises(ValueError, match=r"No wire named 'sand'.*\['dirt', 'rock'\]"):
            cops._resolve_wire(cable, "sand")
        with pytest.raises(ValueError, match="out of range"):
            cops._resolve_wire(cable, 2)
        # A cablepack of unnamed inputs names every wire "".
        with pytest.raises(ValueError, match="2 wires are named ''; give its index"):
            cops._resolve_wire(_Cable([("", None), ("", None)]), "")

    def test_the_wire_sum_is_per_pixel(self):
        pytest.importorskip("numpy")  # Houdini ships it; the test env may not
        cable = _Cable(
            [
                ("dirt", _Layer([0.2, 0.5, 1.0, 0.0])),
                ("rock", _Layer([0.8, 0.5, 0.0, 0.5])),
                ("rgb", _Layer([0.0] * 12, channels=3)),
                ("big", _Layer([0.0] * 16, res=(4, 4))),
                # An ID wire is one Int32 channel, but not a weight.
                ("ids", _Layer([1.0] * 4, storage="Int32", data_type="ID")),
            ]
        )
        result = cops._wire_sum(cable)
        assert result["wires"] == ["dirt", "rock"]
        assert result["min"] == pytest.approx(0.5)
        assert result["max"] == pytest.approx(1.0)
        assert result["average"] == pytest.approx(0.875)
        assert [s["wire"] for s in result["skipped"]] == ["rgb", "big", "ids"]


def test_a_cable_whose_first_wire_has_no_layer_answers_unavailable(monkeypatch):
    class _GeoFirst(_Cable):
        def layerByIndex(self, i):  # noqa: N802
            if i == 0:
                raise RuntimeError("wire 0 is Geometry")
            return super().layerByIndex(i)

    cable = _GeoFirst([("geo", _Layer([0] * 4, data_type="Geometry")), ("mask", _Layer([0] * 4))])
    node = _cop(cable)
    node.layer.side_effect = RuntimeError("no layer")
    monkeypatch.setattr(cops, "_get_cop_node", lambda path: node)
    result = cops.get_cop_layer("/obj/c/pack")
    assert result["is_cable"] is True
    assert result["copernicus_layer"] == {"available": False}
    assert [w["name"] for w in result["wires"]] == ["geo", "mask"]
