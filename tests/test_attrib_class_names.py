"""attrib_class="primitive" was refused, and the refusal listed nothing.

attribcreate's Class menu, the parameter UI and hou.attribType.Prim all call
the class "primitive"; get_attrib_values, get_attribute_info and
get_attrib_stats took only "prim" and answered "Invalid attrib_class:
'primitive'". A session found "prim" by guessing. The plural spellings and
"global" are accepted too, and a refusal names what is.

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
import fxhoudinimcp_server.handlers.geometry_handlers as geometry  # noqa: E402


@pytest.mark.parametrize(
    "spelling, key",
    [
        ("primitive", "prim"),
        ("Primitive", "prim"),
        ("prims", "prim"),
        ("points", "point"),
        ("vertices", "vertex"),
        ("global", "detail"),
        (" detail ", "detail"),
    ],
)
def test_houdinis_words_for_the_class_are_accepted(spelling, key):
    assert geometry._attrib_class_key(spelling) == key


def test_a_refusal_names_the_accepted_classes():
    with pytest.raises(ValueError, match="Use 'point', 'prim' \\(or 'primitive'\\), 'vertex'"):
        geometry._attrib_class_key("face")


def test_get_attrib_values_reads_a_primitive_attribute(monkeypatch):
    geo = MagicMock()
    attrib = geo.findPrimAttrib.return_value
    attrib.size.return_value = 1
    attrib.dataType.return_value.name.return_value = "Float"
    monkeypatch.setattr(geometry, "_get_sop_geo", lambda path: geo)
    monkeypatch.setattr(geometry, "_attrib_array", lambda g, cls, a: [0.5, 1.0])
    result = geometry._get_attrib_values(
        node_path="/obj/geo1/mask", attrib_name="mask", attrib_class="primitive"
    )
    geo.findPrimAttrib.assert_called_once_with("mask")
    assert result["total_elements"] == 2


def test_get_attribute_info_takes_the_same_spelling(monkeypatch):
    geo = MagicMock()
    monkeypatch.setattr(geometry, "_get_sop_geo", lambda path: geo)
    monkeypatch.setattr(geometry, "_vec_to_list", lambda v: [0.0])
    geometry._get_attribute_info(
        node_path="/obj/geo1/mask", attrib_name="mask", attrib_class="Primitive"
    )
    geo.findPrimAttrib.assert_called_once_with("mask")


def test_get_attrib_stats_takes_the_same_spelling(monkeypatch):
    geo = MagicMock()
    geo.primAttribs.return_value = ()
    monkeypatch.setattr(geometry, "_get_sop_geo", lambda path: geo)
    result = geometry._attrib_stats_once("/obj/geo1/mask", ["mask"], "primitives")
    geo.primAttribs.assert_called()
    assert result["missing"] == ["mask"]


def test_get_group_members_takes_primitive_for_the_group_type(monkeypatch):
    geo = MagicMock()
    geo.findPrimGroup.return_value = None
    monkeypatch.setattr(geometry, "_get_sop_geo", lambda path: geo)
    monkeypatch.setattr(geometry.hou, "OperationFailed", RuntimeError, raising=False)
    with pytest.raises(RuntimeError, match="Prim group 'top' not found"):
        geometry._get_group_members(
            node_path="/obj/geo1/mask", group_name="top", group_type="primitive"
        )
