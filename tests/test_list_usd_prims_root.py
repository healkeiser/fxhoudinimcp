"""list_usd_prims(root_path="/materials/BLD") also returned /materials/BLD_probes.

root_path was applied as a string prefix; a sibling whose name merely starts
with the same characters passed. The handler now walks Usd.PrimRange(root)
and tests Sdf.Path.HasPrefix, which compares path elements.

hou and pxr are mocked here; the live check ran on Houdini 22.0.429.
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


class _Path:
    """Enough of Sdf.Path: element-wise prefix and element count."""

    def __init__(self, text):
        self.text = text
        self.elements = [e for e in text.split("/") if e]

    @property
    def pathElementCount(self):
        return len(self.elements)

    def HasPrefix(self, other):
        return self.elements[: len(other.elements)] == other.elements

    def __str__(self):
        return self.text


def _prim(path):
    prim = MagicMock()
    prim.GetPath.return_value = _Path(path)
    prim.GetTypeName.return_value = "Xform"
    prim.IsValid.return_value = True
    return prim


ALL = ["/materials", "/materials/BLD", "/materials/BLD/wood", "/materials/BLD_probes", "/geo"]


def _run(monkeypatch, root_path, **kwargs):
    prims = {p: _prim(p) for p in ALL}
    stage = MagicMock()
    stage.Traverse.return_value = list(prims.values())
    prims["/"] = _prim("/")  # the pseudo-root: GetPrimAtPath finds it, Traverse() never lists it
    stage.GetPrimAtPath.side_effect = lambda p: prims[p]
    monkeypatch.setattr(lops, "_get_lop_stage", lambda node_path: stage)
    monkeypatch.setattr(lops, "_prim_to_dict", lambda prim: {"path": str(prim.GetPath())})
    usd = MagicMock()
    # A subtree walk hands back the root and everything under it, siblings excluded.
    usd.PrimRange.side_effect = lambda root: [
        prims[p] for p in ALL if _Path(p).HasPrefix(root.GetPath())
    ]
    monkeypatch.setattr(lops, "Usd", usd, raising=False)
    reply = lops._list_usd_prims(node_path="/stage/out", root_path=root_path, **kwargs)
    return [p["path"] for p in reply["prims"]], reply["count"]


class TestRootPathIsAPathNotAPrefix:
    def test_a_sibling_sharing_the_prefix_is_not_listed(self, monkeypatch):
        paths, count = _run(monkeypatch, "/materials/BLD")
        assert paths == ["/materials/BLD", "/materials/BLD/wood"]
        assert count == 2

    def test_root_slash_still_lists_everything(self, monkeypatch):
        paths, _ = _run(monkeypatch, "/")
        assert paths == ALL

    def test_depth_counts_elements_below_root(self, monkeypatch):
        paths, _ = _run(monkeypatch, "/materials", depth=1)
        assert paths == ["/materials", "/materials/BLD", "/materials/BLD_probes"]


class TestPrimStatsUseTheSamePathTest:
    def test_a_sibling_sharing_the_prefix_is_not_counted(self, monkeypatch):
        prims = {p: _prim(p) for p in ALL}
        stage = MagicMock()
        stage.Traverse.return_value = list(prims.values())
        prims["/"] = _prim("/")
        stage.GetPrimAtPath.side_effect = lambda p: prims[p]
        monkeypatch.setattr(lops, "_get_lop_stage", lambda node_path: stage)
        usd = MagicMock()
        usd.PrimRange.side_effect = lambda root: [
            prims[p] for p in ALL if _Path(p).HasPrefix(root.GetPath())
        ]
        monkeypatch.setattr(lops, "Usd", usd, raising=False)

        reply = lops._get_usd_prim_stats(node_path="/stage/out", prim_path="/materials/BLD")

        assert reply["total_prims"] == 2
        assert reply["type_counts"] == {"Xform": 2}
