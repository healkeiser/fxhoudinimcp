"""get_material_info must not evaluate every parameter of every node.

The assignment sweep called parm.eval() on each parameter of each node under
/obj to find a string containing the material path; an expression such as
npoints("../scatter") cooks its node when evaluated, and 40 of them on a
4,160-node scene cost 27 s per call. Only material-path parameters, on node
types that have one, are read now.
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
import fxhoudinimcp_server.handlers.material_handlers as mats  # noqa: E402

hou = mats.hou


class _Template:
    def __init__(self, name, kind, children=()):
        self._name = name
        self._kind = kind
        self._children = list(children)

    def name(self):
        return self._name

    def type(self):
        return self._kind

    def parmTemplates(self):
        return self._children


class _Group:
    def __init__(self, entries):
        self._entries = entries

    def entries(self):
        return self._entries


class _NodeType:
    calls = 0

    def __init__(self, name, entries):
        self._name = name
        self._entries = entries

    def nameWithCategory(self):
        return self._name

    def parmTemplateGroup(self):
        _NodeType.calls += 1
        return _Group(self._entries)


class _Parm:
    """Evaluating a non-material parameter is the bug; make it loud."""

    def __init__(self, name, value, cheap):
        self._name = name
        self._value = value
        self._cheap = cheap

    def name(self):
        return self._name

    def evalAsString(self):
        if not self._cheap:
            raise AssertionError(f"{self._name} was evaluated (it cooks)")
        return self._value

    eval = evalAsString


class _Node:
    def __init__(self, path, node_type, parms):
        self._path = path
        self._type = node_type
        self._parms = {p.name(): p for p in parms}

    def path(self):
        return self._path

    def type(self):
        return self._type

    def parm(self, name):
        return self._parms.get(name)

    def parms(self):
        return list(self._parms.values())


def _str(name):
    return _Template(name, hou.parmTemplateType.String)


def _float(name):
    return _Template(name, hou.parmTemplateType.Float)


GEO = _NodeType("Object/geo", [_str("shop_materialpath"), _float("tx")])
XFORM = _NodeType(
    "Sop/xform", [_Template("xf", hou.parmTemplateType.Folder, [_float("tx"), _float("ty")])]
)
MATERIAL = _NodeType(
    "Sop/material",
    [
        _Template(
            "materials", hou.parmTemplateType.Folder, [_str("shop_materialpath#"), _str("group#")]
        )
    ],
)


@pytest.fixture
def scene(monkeypatch):
    nodes = [
        _Node(
            "/obj/g0", GEO, [_Parm("shop_materialpath", "/mat/m1", True), _Parm("tx", "1", False)]
        ),
        _Node("/obj/g0/x1", XFORM, [_Parm("tx", 'npoints("../heavy")', False)]),
        _Node("/obj/g1", GEO, [_Parm("shop_materialpath", "", True), _Parm("tx", "1", False)]),
        _Node(
            "/obj/g1/mat1",
            MATERIAL,
            [
                _Parm("num_materials", "2", False),
                _Parm("shop_materialpath1", "/mat/other", True),
                _Parm("shop_materialpath2", "/mat/m1", True),
                _Parm("group1", "", False),
            ],
        ),
    ]
    root = MagicMock()
    root.allSubChildren.return_value = nodes
    monkeypatch.setattr(
        mats.hou, "node", lambda path: root if path == "/obj" else None, raising=False
    )
    monkeypatch.setattr(mats, "_material_parm_cache", {})
    _NodeType.calls = 0
    return nodes


class TestAssignmentScan:
    def test_only_material_parameters_are_read(self, scene):
        hits, scanned = mats._find_material_assignments("/mat/m1")
        assert hits == ["/obj/g0", "/obj/g1/mat1"]
        assert scanned == len(scene)

    def test_multiparm_instances_are_expanded(self, scene):
        hits, _ = mats._find_material_assignments("/mat/other")
        assert hits == ["/obj/g1/mat1"]

    def test_templates_are_cached_per_type(self, scene):
        mats._find_material_assignments("/mat/m1")
        assert _NodeType.calls == 3  # geo, xform, material -- not once per node
        mats._find_material_assignments("/mat/m1")
        assert _NodeType.calls == 3

    def test_missing_root_is_tolerated(self, scene, monkeypatch):
        monkeypatch.setattr(mats.hou, "node", lambda path: None, raising=False)
        assert mats._find_material_assignments("/mat/m1") == ([], 0)
