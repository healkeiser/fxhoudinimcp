"""get_usd_attributes reads the same attributes across many prims at once.

Reading `sourceName` off every RenderVar, `lpetag` off every light and the
`camera` relationship of the render settings took one get_usd_prim per prim,
each around 130 attributes long on a RenderSettings, so a render-setup
question ran to 20+ calls or left for execute_python. One call now answers
it as a table: prim paths or globs (`*` within one path element, `**`
across), attribute globs, a prim type filter, and a row cap that counts what
it leaves out. Values are read at the current frame, as get_usd_prim does.

hou and pxr are mocked here; the live check ran on Houdini 22.0.429.
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
import fxhoudinimcp_server.handlers.lops_handlers as lops  # noqa: E402

# Shared with the other USD handler tests.
from _usd_fakes import attribute, prim, prim_with, relationship, usd_module  # noqa: E402


class _OperationFailed(Exception):
    """Stands in for hou.OperationFailed, which the hou stub does not define."""


@pytest.fixture
def stage(monkeypatch):
    prims = [
        prim_with(
            "/Render/rendersettings",
            "RenderSettings",
            attributes=[
                attribute("resolution", [2048, 1080], {1.0: [1920, 1080], 24.0: [1280, 720]})
            ],
            relationships=[relationship("camera", ["/cameras/cam1"])],
        ),
        prim_with("/Render/Vars", "Scope"),
        prim_with("/Render/Vars/beauty", "RenderVar", attributes=[attribute("sourceName", "Ci")]),
        prim_with(
            "/Render/Vars/diffuse",
            "RenderVar",
            attributes=[attribute("sourceName", "C<RD>.*L")],
        ),
        prim_with("/lights/key", "RectLight", attributes=[attribute("karma:light:lpetag", "key")]),
        prim_with(
            "/lights/rig/fill",
            "SphereLight",
            attributes=[attribute("karma:light:lpetag", "fill")],
        ),
    ]
    by_path = {str(p.GetPath()): p for p in prims}
    fake = MagicMock()
    fake.GetPrimAtPath.side_effect = lambda path: by_path.get(path) or prim(path, valid=False)
    walks = []
    monkeypatch.setattr(lops, "_get_lop_stage", lambda node_path: fake)
    monkeypatch.setattr(
        lops, "_traverse", lambda s, root, proxies: walks.append(proxies) or iter(prims)
    )
    monkeypatch.setattr(lops, "Usd", usd_module(), raising=False)
    monkeypatch.setattr(lops.hou, "frame", lambda: 24.0)
    monkeypatch.setattr(lops.hou, "OperationFailed", _OperationFailed, raising=False)
    return walks


def _rows(**kwargs):
    return lops._get_usd_attributes(node_path="/stage/krs", **kwargs)


class TestPrimPathGlobs:
    @pytest.mark.parametrize(
        ("pattern", "path", "hit"),
        [
            ("/Render/Vars/*", "/Render/Vars/beauty", True),
            ("/Render/Vars/*", "/Render/Vars/beauty/aov", False),
            ("/Render/**", "/Render/Vars/beauty", True),
            ("/lights/?ey", "/lights/key", True),
            ("/lights/key", "/lights/key2", False),
            ("/geo/a.b", "/geo/aXb", False),
        ],
    )
    def test_a_star_stays_in_one_path_element(self, pattern, path, hit):
        assert bool(lops._prim_pattern(pattern).match(path)) is hit


class TestGetUsdAttributes:
    def test_one_row_per_render_var(self, stage):
        reply = _rows(prims="/Render/Vars/*", attr_patterns=["sourceName"])
        assert [(r["prim"], r["prim_type"], r["value"]) for r in reply["rows"]] == [
            ("/Render/Vars/beauty", "RenderVar", "Ci"),
            ("/Render/Vars/diffuse", "RenderVar", "C<RD>.*L"),
        ]
        assert reply["prims_matched"] == 2
        assert reply["truncated"] is False

    def test_prim_type_narrows_by_glob(self, stage):
        reply = _rows(prims=["/**"], prim_type="*Light", attr_patterns=["*lpetag"])
        assert [(r["prim"], r["value"]) for r in reply["rows"]] == [
            ("/lights/key", "key"),
            ("/lights/rig/fill", "fill"),
        ]

    def test_values_are_read_at_the_current_frame(self, stage):
        reply = _rows(prims=["/Render/rendersettings"], attr_patterns=["resolution"])
        (row,) = reply["rows"]
        assert row["value"] == [1280, 720]
        assert row["time_samples"] == 2
        assert reply["time"] == 24.0
        assert reply["time_source"] == "stage_frame"
        reply = _rows(prims=["/Render/rendersettings"], attr_patterns=["resolution"], time=1)
        assert reply["rows"][0]["value"] == [1920, 1080]
        assert reply["time_source"] == "requested"

    def test_relationships_are_rows_unless_turned_off(self, stage):
        reply = _rows(prims=["/Render/rendersettings"])
        assert reply["rows"][-1] == {
            "prim": "/Render/rendersettings",
            "prim_type": "RenderSettings",
            "name": "camera",
            "relationship": True,
            "targets": ["/cameras/cam1"],
        }
        reply = _rows(prims=["/Render/rendersettings"], relationships=False)
        assert [r["name"] for r in reply["rows"]] == ["resolution"]

    def test_the_cap_counts_what_it_leaves_out(self, stage):
        reply = _rows(prims=["/**"], limit=2)
        assert reply["returned"] == 2
        assert reply["matched"] == 6
        assert reply["truncated"] is True

    def test_an_exact_path_and_a_glob_do_not_repeat_a_prim(self, stage):
        reply = _rows(prims=["/lights/key", "/lights/*"])
        assert [r["prim"] for r in reply["rows"]] == ["/lights/key"]

    def test_exact_paths_need_no_walk(self, stage):
        _rows(prims=["/lights/key"])
        assert stage == []
        _rows(prims=["/lights/**"], traverse_instance_proxies=True)
        assert stage == [True]

    def test_a_missing_exact_path_is_named(self, stage):
        with pytest.raises(_OperationFailed, match="/nope"):
            _rows(prims=["/Render/Vars/*", "/nope"])

    def test_no_prims_is_refused(self, stage):
        with pytest.raises(ValueError, match="prims"):
            _rows(prims=[])
