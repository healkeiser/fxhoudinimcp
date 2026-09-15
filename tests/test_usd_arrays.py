"""get_usd_prim and get_usd_attribute returned whole arrays.

get_usd_prim on a building mesh was 6.6 million characters and
get_usd_attribute(primvars:st) 40 000 lines. Arrays over 16 elements are now
summarised (size, element type, head, range) unless full=True, and
get_usd_attribute reads a long array in windows.

hou and pxr are mocked here (plain lists stand in for Vt arrays); the live
check ran on Houdini 22.0.429.
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
import fxhoudinimcp_server.handlers.lops_handlers as lops  # noqa: E402


class TestArraysAreSummarised:
    def test_a_short_array_passes_whole(self):
        assert lops._usd_value_to_python([1, 2, 3]) == [1, 2, 3]

    def test_a_long_array_is_a_summary(self):
        value = lops._usd_value_to_python(list(range(100)))
        assert value["array"] is True
        assert value["size"] == 100
        assert value["head"] == [0, 1, 2, 3, 4, 5, 6, 7]
        assert value["element_type"] == "int"
        assert "100 elements" in value["note"]

    def test_full_returns_everything(self):
        assert lops._usd_value_to_python(list(range(100)), array_limit=None) == list(range(100))

    def test_text_is_never_an_array(self):
        assert lops._usd_value_to_python("a string longer than sixteen chars") == (
            "a string longer than sixteen chars"
        )

    def test_a_token_is_returned_whole_even_with_pxr_present(self, monkeypatch):
        # With pxr importable the generic Vt fallback used to walk a str
        # character by character into a nested list.
        monkeypatch.setattr(lops, "HAS_PXR", True)
        for name in ("Gf", "Sdf", "Vt"):
            monkeypatch.setattr(lops, name, MagicMock(), raising=False)
        assert lops._usd_value_to_python("rightHanded") == "rightHanded"


def _stage(monkeypatch, value):
    attr = MagicMock()
    attr.IsValid.return_value = True
    attr.Get.return_value = value
    attr.GetTypeName.return_value = "float3[]"
    attr.IsAuthored.return_value = True
    prim = MagicMock()
    prim.IsValid.return_value = True
    prim.GetAttribute.return_value = attr
    stage = MagicMock()
    stage.GetPrimAtPath.return_value = prim
    monkeypatch.setattr(lops, "_get_lop_stage", lambda node_path: stage)
    monkeypatch.setattr(lops, "Usd", MagicMock(), raising=False)


class TestGetUsdAttributeWindows:
    def test_default_window_is_the_first_64(self, monkeypatch):
        _stage(monkeypatch, list(range(1000)))
        reply = lops._get_usd_attribute(node_path="/stage/x", prim_path="/p", attr_name="points")
        assert reply["value"]["size"] == 1000
        assert reply["slice"]["values"] == list(range(64))
        assert reply["slice"]["has_more"] is True

    def test_offset_and_limit_walk_the_array(self, monkeypatch):
        _stage(monkeypatch, list(range(1000)))
        reply = lops._get_usd_attribute(
            node_path="/stage/x", prim_path="/p", attr_name="points", offset=990, limit=64
        )
        assert reply["slice"] == {
            "offset": 990,
            "limit": 64,
            "count": 10,
            "has_more": False,
            "values": list(range(990, 1000)),
        }

    def test_full_hands_back_the_array(self, monkeypatch):
        _stage(monkeypatch, list(range(1000)))
        reply = lops._get_usd_attribute(
            node_path="/stage/x", prim_path="/p", attr_name="points", full=True
        )
        assert reply["value"] == list(range(1000))
        assert "slice" not in reply

    def test_a_short_array_has_no_slice(self, monkeypatch):
        _stage(monkeypatch, [1.0, 2.0])
        reply = lops._get_usd_attribute(node_path="/stage/x", prim_path="/p", attr_name="extent")
        assert reply["value"] == [1.0, 2.0]
        assert "slice" not in reply
