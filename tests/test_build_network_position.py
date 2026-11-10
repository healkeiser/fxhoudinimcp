"""build_network places a node where its spec says.

Where the user arranges nodes by hand, `position` was "unknown spec key" and
each node cost a set_node_position. A positioned node is not auto-placed; a
malformed position is a validation error.

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
import fxhoudinimcp_server.handlers.graph_handlers as graph  # noqa: E402


class TestPositionKey:
    @pytest.mark.parametrize("value", [[1, 2], (0.5, -3.0)])
    def test_two_numbers_are_a_position(self, value):
        assert graph._is_xy(value)

    @pytest.mark.parametrize("value", [[1], [1, 2, 3], "1,2", [True, 0], {"x": 1, "y": 2}, None])
    def test_anything_else_is_not(self, value):
        assert not graph._is_xy(value)

    def test_position_is_a_known_spec_key(self):
        assert "position" in graph._SPEC_KEYS
