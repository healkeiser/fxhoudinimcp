"""Placing the free view and framing part of the scene took execute_python.

set_viewport_direction knew the seven named directions and nothing else: an
orbit to a given angle meant GeometryViewportCamera.setRotation() through
execute_python. frame_all only did home-all, so framing one object meant the
spread of every object in the scene, or frameBoundingBox() by hand.

set_viewport_direction now takes rotation / pivot / distance for the free
(non-camera) view and reads it back; frame_all takes node_paths (their world
bounds) and bounds. Bad values are refused before the viewer is looked up.

hou is mocked here; the live check ran on Houdini 22.0.429.
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
import fxhoudinimcp_server.handlers.viewport_handlers as viewport  # noqa: E402

###### Fakes


class _Vec(tuple):
    """hou.Vector3: a tuple that a _Move multiplies."""

    def __new__(cls, *values):
        return super().__new__(cls, values)

    def __mul__(self, transform):
        return _Vec(*(a + b for a, b in zip(self, transform.offset, strict=True)))


class _Move:
    """A world transform that only translates."""

    def __init__(self, *offset):
        self.offset = offset


class _Rotation:
    """What buildRotate / extractRotationMatrix3 / Matrix4 hand around: the angles.

    A transposed one is the inverse turn: its angles read back scrambled.
    """

    def __init__(self, angles, transposed=False):
        self.angles = tuple(angles)
        self.is_transposed = transposed

    def extractRotationMatrix3(self):
        return self

    def transposed(self):
        return _Rotation(self.angles, not self.is_transposed)

    def extractRotates(self):
        if self.is_transposed:
            return tuple(-a for a in reversed(self.angles))
        return self.angles


class _FreeView:
    """GeometryViewportCamera: a world translation, rotated about the pivot."""

    def __init__(self, rotation=(0.0, 0.0, 0.0), pivot=(0.0, 0.0, 0.0), distance=10.0):
        self._rotation = _Rotation(rotation, transposed=True)
        self._pivot = _Vec(*pivot)
        self._translation = _Vec(pivot[0], pivot[1], pivot[2] + distance)

    def stash(self):
        copy = _FreeView()
        copy._rotation, copy._pivot, copy._translation = (
            self._rotation,
            self._pivot,
            self._translation,
        )
        return copy

    def setRotation(self, matrix):
        self._rotation = matrix

    def rotation(self):
        return self._rotation

    def setPivot(self, pivot):
        self._pivot = pivot

    def pivot(self):
        return self._pivot

    def setTranslation(self, translation):
        self._translation = translation

    def translation(self):
        return self._translation


class _FakeViewport:
    def __init__(self, camera=None):
        self._camera = camera
        self.view = _FreeView()
        self.prim = ""
        self.takes = True
        self.calls = []

    def name(self):
        return "persp1"

    def camera(self):
        return self._camera

    def cameraPath(self):
        return self._camera.path() if self._camera is not None else self.prim

    def defaultCamera(self):
        return self.view

    def setDefaultCamera(self, view):
        self.calls.append("setDefaultCamera")
        if self.takes:
            self.view = view

    def changeType(self, view_type):
        self.calls.append(("changeType", view_type))

    def frameAll(self):
        self.calls.append("frameAll")

    def homeAll(self):
        self.calls.append("homeAll")

    def frameBoundingBox(self, box):
        self.calls.append(("frameBoundingBox", box))


class _FakeObj:
    """An object node: display SOP plus world transform."""

    def __init__(self, path, display=None, offset=(0.0, 0.0, 0.0)):
        self._path, self._display, self._offset = path, display, offset

    def path(self):
        return self._path

    def parent(self):
        return None

    def displayNode(self):
        return self._display

    def worldTransform(self):
        return _Move(*self._offset)


class _FakeSop:
    def __init__(self, path, parent=None, box=None):
        self._path, self._parent, self._box = path, parent, box

    def path(self):
        return self._path

    def parent(self):
        return self._parent

    def geometry(self):
        if self._box is None:
            return None
        box = MagicMock()
        box.isValid.return_value = True
        box.minvec.return_value = self._box[:3]
        box.maxvec.return_value = self._box[3:]
        return MagicMock(**{"boundingBox.return_value": box})


@pytest.fixture
def houdini(monkeypatch):
    """A viewer with one free view, and hou's maths reduced to tuples."""
    view = _FakeViewport()
    viewer = MagicMock()
    viewer.name.return_value = "panetab1"
    viewer.curViewport.return_value = view
    looked_up = []

    def find(pane_name=None):
        looked_up.append(pane_name)
        return viewer

    hou = viewport.hou
    monkeypatch.setattr(viewport, "_find_scene_viewer", find)
    monkeypatch.setattr(hou, "Vector3", _Vec, raising=False)
    monkeypatch.setattr(hou, "Matrix4", lambda rotation: rotation, raising=False)
    monkeypatch.setattr(hou.hmath, "buildRotate", _Rotation, raising=False)
    monkeypatch.setattr(hou, "BoundingBox", lambda *box: box, raising=False)
    monkeypatch.setattr(hou, "ObjNode", _FakeObj, raising=False)
    nodes = {}
    monkeypatch.setattr(hou, "node", nodes.get, raising=False)
    view.nodes, view.looked_up = nodes, looked_up
    return view


###### viewport.set_viewport_direction


class TestFreeView:
    def test_rotation_pivot_and_distance_are_read_back(self, houdini):
        result = viewport.set_viewport_direction(
            rotation=[-20, 30, 0], pivot=[1, 2, 3], distance=15
        )
        assert result["view"] == {
            "rotation": [-20.0, 30.0, 0.0],
            "pivot": [1.0, 2.0, 3.0],
            "distance": 15.0,
        }
        assert result["direction"] is None
        assert "changeType" not in str(houdini.calls)

    def test_the_view_gets_the_transpose_of_buildrotate(self, houdini):
        # The view's own rotation is laid out transposed: a cam object with the
        # same r and this view look the same way only with .transposed().
        viewport.set_viewport_direction(rotation=[-20, 30, 0])
        stored = houdini.view.rotation()
        assert stored.is_transposed
        assert stored.angles == (-20.0, 30.0, 0.0)

    def test_the_reply_is_read_back_not_echoed(self, houdini):
        houdini.takes = False  # the viewport kept its old view
        result = viewport.set_viewport_direction(rotation=[-20, 30, 0])
        assert result["view"]["rotation"] == [0.0, 0.0, 0.0]

    def test_what_was_not_passed_is_kept(self, houdini):
        result = viewport.set_viewport_direction(pivot=[1, 2, 3])
        assert result["view"]["rotation"] == [0.0, 0.0, 0.0]
        assert result["view"]["distance"] == 10.0

    def test_the_eye_follows_a_new_pivot(self, houdini):
        # The translation is a world position: left alone, the eye stays put
        # and looks past the new pivot.
        viewport.set_viewport_direction(pivot=[1, 2, 3], distance=9)
        assert tuple(houdini.view.translation()) == (1.0, 2.0, 12.0)

    def test_a_pan_survives_a_new_pivot(self, houdini):
        houdini.view = _FreeView(pivot=(0.0, 0.0, 0.0))
        houdini.view.setTranslation(_Vec(0.5, -0.25, 10.0))
        result = viewport.set_viewport_direction(pivot=[1, 2, 3])
        assert tuple(houdini.view.translation()) == (1.5, 1.75, 13.0)
        assert result["view"]["distance"] == 10.0

    def test_a_direction_first_then_the_orbit(self, houdini):
        result = viewport.set_viewport_direction("perspective", rotation=[0, 45, 0])
        assert houdini.calls[:2] == [
            ("changeType", viewport.hou.geometryViewportType.Perspective),
            "frameAll",
        ]
        assert result["view"]["rotation"] == [0.0, 45.0, 0.0]

    def test_a_viewport_looking_through_a_camera_is_refused(self, houdini):
        houdini._camera = _FakeObj("/obj/cam1")
        with pytest.raises(ValueError, match="looks through /obj/cam1"):
            viewport.set_viewport_direction("front", rotation=[0, 45, 0])
        assert houdini.calls == []  # not even the direction

    def test_a_viewport_looking_through_a_usd_camera_is_refused(self, houdini):
        # camera() is None for a prim; setDefaultCamera() unbound it (22.0.368).
        houdini.prim = "/cameras/ucam"
        with pytest.raises(ValueError, match="looks through /cameras/ucam"):
            viewport.set_viewport_direction(rotation=[0, 90, 0])
        assert houdini.calls == []

    def test_the_refusal_names_the_tool_for_the_kind_of_camera(self, houdini):
        # set_object_transform cannot move a USD prim.
        houdini.prim = "/cameras/ucam"
        with pytest.raises(ValueError, match="set_usd_attribute") as prim:
            viewport.set_viewport_direction(rotation=[0, 90, 0])
        assert "set_object_transform" not in str(prim.value)
        houdini.prim, houdini._camera = "", _FakeObj("/obj/cam1")
        with pytest.raises(ValueError, match="set_object_transform"):
            viewport.set_viewport_direction(rotation=[0, 90, 0])

    @pytest.mark.parametrize(
        ("kwargs", "named"),
        [
            ({"rotation": [0, 45]}, "rotation"),
            ({"rotation": "down"}, "rotation"),
            ({"pivot": [0, "a", 0]}, "pivot"),
            ({"distance": 0}, "distance"),
            ({"distance": -3}, "distance"),
            ({"distance": True}, "distance"),
        ],
    )
    def test_a_bad_value_is_refused_before_the_viewer(self, houdini, kwargs, named):
        with pytest.raises(ValueError, match=named):
            viewport.set_viewport_direction(**kwargs)
        assert houdini.looked_up == []

    def test_nothing_to_set_is_refused(self, houdini):
        with pytest.raises(ValueError, match="Pass direction"):
            viewport.set_viewport_direction()


class TestDirectionAlone:
    def test_reply_keeps_its_keys(self, houdini):
        result = viewport.set_viewport_direction("top")
        assert result == {
            "success": True,
            "direction": "top",
            "pane_name": "panetab1",
            "viewport_name": "persp1",
        }
        assert "setDefaultCamera" not in houdini.calls

    def test_unknown_direction_still_names_the_choices(self, houdini):
        with pytest.raises(ValueError, match="Supported"):
            viewport.set_viewport_direction("sideways")


###### viewport.frame_all


def _framed(houdini):
    return [call[1] for call in houdini.calls if call[0] == "frameBoundingBox"]


class TestFrameAll:
    def test_alone_it_still_homes_all(self, houdini):
        result = viewport.frame_all()
        assert houdini.calls == ["homeAll"]
        assert result == {"success": True, "pane_name": "panetab1", "viewport_name": "persp1"}

    def test_a_camera_looked_through_is_reported_released(self, houdini):
        # homeAll() and frameBoundingBox() both dropped /obj/refcam one UI tick
        # later, with a plain success reply (22.0.368).
        houdini._camera = _FakeObj("/obj/refcam")
        for kwargs in ({}, {"bounds": [-1, 0, -1, 1, 2, 1]}):
            result = viewport.frame_all(**kwargs)
            assert result["camera_released"] == "/obj/refcam"
            assert "set_viewport_camera" in result["note"]

    def test_a_usd_camera_is_reported_by_its_prim_path(self, houdini):
        houdini.prim = "/cameras/ucam"
        assert viewport.frame_all()["camera_released"] == "/cameras/ucam"

    def test_a_box_is_framed(self, houdini):
        result = viewport.frame_all(bounds=[-1, 0, -1, 1, 2, 1])
        assert _framed(houdini) == [(-1.0, 0.0, -1.0, 1.0, 2.0, 1.0)]
        assert result["framed_bounds"] == [-1.0, 0.0, -1.0, 1.0, 2.0, 1.0]

    def test_a_point_is_padded_to_a_unit_cube(self, houdini):
        # frameBoundingBox() of a zero-size box put the eye 0.019 from it.
        result = viewport.frame_all(bounds=[1, 2, 3, 1, 2, 3])
        assert _framed(houdini) == [(0.5, 1.5, 2.5, 1.5, 2.5, 3.5)]
        assert result["framed_bounds"] == [0.5, 1.5, 2.5, 1.5, 2.5, 3.5]
        assert result["padded"] is True

    def test_a_flat_box_is_framed_as_it_is(self, houdini):
        result = viewport.frame_all(bounds=[0, 0, 0, 4, 0, 2])
        assert _framed(houdini) == [(0.0, 0.0, 0.0, 4.0, 0.0, 2.0)]
        assert "padded" not in result

    def test_an_object_is_framed_where_it_sits_in_the_world(self, houdini):
        sop = _FakeSop("/obj/geo1/box1", box=(-1, -1, -1, 1, 1, 1))
        houdini.nodes["/obj/geo1"] = _FakeObj("/obj/geo1", display=sop, offset=(10, 0, 0))
        result = viewport.frame_all(node_paths=["/obj/geo1"])
        assert result["framed_bounds"] == [9.0, -1.0, -1.0, 11.0, 1.0, 1.0]

    def test_a_sop_goes_through_its_object_transform(self, houdini):
        geo = _FakeObj("/obj/geo1", offset=(0, 5, 0))
        houdini.nodes["/obj/geo1/box1"] = _FakeSop("/obj/geo1/box1", geo, (-1, -1, -1, 1, 1, 1))
        result = viewport.frame_all(node_paths=["/obj/geo1/box1"])
        assert result["framed_bounds"] == [-1.0, 4.0, -1.0, 1.0, 6.0, 1.0]

    def test_several_nodes_and_a_box_frame_the_box_around_all(self, houdini):
        houdini.nodes["/obj/a/s"] = _FakeSop("/obj/a/s", _FakeObj("/obj/a"), (0, 0, 0, 1, 1, 1))
        houdini.nodes["/obj/b/s"] = _FakeSop("/obj/b/s", _FakeObj("/obj/b"), (4, 0, 0, 5, 1, 1))
        result = viewport.frame_all(node_paths=["/obj/a/s", "/obj/b/s"], bounds=[0, -2, 0, 1, 0, 1])
        assert result["framed_bounds"] == [0.0, -2.0, 0.0, 5.0, 1.0, 1.0]

    def test_a_node_without_geometry_is_named_not_framed(self, houdini):
        houdini.nodes["/obj/a/s"] = _FakeSop("/obj/a/s", _FakeObj("/obj/a"), (0, 0, 0, 1, 1, 1))
        houdini.nodes["/obj/null1"] = _FakeObj("/obj/null1")  # no display SOP
        result = viewport.frame_all(node_paths=["/obj/a/s", "/obj/null1"])
        assert result["no_geometry"] == ["/obj/null1"]
        assert result["framed_bounds"] == [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]

    def test_nothing_to_frame_is_refused(self, houdini):
        houdini.nodes["/obj/null1"] = _FakeObj("/obj/null1")
        with pytest.raises(ValueError, match="no geometry on"):
            viewport.frame_all(node_paths=["/obj/null1"])
        assert houdini.calls == []

    def test_a_missing_node_is_refused_before_the_viewer(self, houdini):
        with pytest.raises(ValueError, match="/obj/gone"):
            viewport.frame_all(node_paths=["/obj/gone"])
        assert houdini.looked_up == []

    @pytest.mark.parametrize(
        "bad", [[0, 0, 0, 1, 1], [1, 0, 0, 0, 1, 1], "all", [0, 0, 0, 1, "x", 1]]
    )
    def test_bad_bounds_are_refused_before_the_viewer(self, houdini, bad):
        with pytest.raises(ValueError, match="bounds must be"):
            viewport.frame_all(bounds=bad)
        assert houdini.looked_up == []
