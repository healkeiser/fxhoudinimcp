"""get_volume_info places each volume's grid, not only its bbox.

Whether two volumes share a grid could not be read off the answer: two
heightfields of one size reported bboxes of +-1008 and +-1008.5, and a session
fell back to execute_python with indexToPos on the first and last voxel. Each
entry now carries voxel_size, first_voxel_center and last_voxel_center; a
VDB's grid is its active voxels' index box, whose max is one past the last.

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
import fxhoudinimcp_server.handlers.geometry_handlers as geometry  # noqa: E402


class _Grid:
    """A volume whose voxel (i, j, k) sits at (i, j, k) - 1007.5 + offset."""

    def __init__(self, resolution, offset=0.0, active=None):
        self._resolution = resolution
        self._offset = offset
        self._active = active

    def resolution(self):
        return self._resolution

    def voxelSize(self):
        return (1.0, 1.0, 1.0)

    def indexToPos(self, index):
        return tuple(c - 1007.5 + self._offset for c in index)

    def activeVoxelBoundingBox(self):
        box = MagicMock()
        box.minvec.return_value = self._active[0]
        box.maxvec.return_value = self._active[1]
        return box


class Volume(_Grid):
    pass


class VDB(_Grid):
    pass


def test_a_dense_volume_runs_from_index_0_to_res_minus_1():
    grid = geometry._voxel_grid(Volume((2016, 2016, 1)))
    assert grid["voxel_size"] == [1.0, 1.0, 1.0]
    assert grid["first_voxel_center"] == [-1007.5, -1007.5, -1007.5]
    assert grid["last_voxel_center"] == [1007.5, 1007.5, -1007.5]


def test_a_shifted_grid_shows_in_the_centres():
    same = geometry._voxel_grid(Volume((2016, 2016, 1)))
    shifted = geometry._voxel_grid(Volume((2016, 2016, 1), offset=0.5))
    assert shifted["voxel_size"] == same["voxel_size"]
    assert shifted["first_voxel_center"][0] - same["first_voxel_center"][0] == 0.5


def test_a_vdb_runs_over_its_active_box_whose_max_is_one_past():
    grid = geometry._voxel_grid(VDB((15, 15, 15), active=((-7, -7, -7), (8, 8, 8))))
    assert grid["first_voxel_center"] == [-1014.5] * 3
    assert grid["last_voxel_center"] == [-1000.5] * 3


def test_an_empty_vdb_places_no_voxel():
    assert geometry._voxel_grid(VDB((0, 0, 0), active=((0, 0, 0), (0, 0, 0)))) == {}


def test_the_entry_carries_the_grid(monkeypatch):
    prim = Volume((4, 4, 4))
    prim.number = lambda: 0
    prim.attribValue = lambda name: "density"
    prim.intrinsicNames = lambda: []
    prim.boundingBox = MagicMock()
    entry = geometry._volume_entry(prim)
    assert entry["first_voxel_center"] == [-1007.5] * 3
    assert entry["last_voxel_center"] == [-1004.5] * 3
