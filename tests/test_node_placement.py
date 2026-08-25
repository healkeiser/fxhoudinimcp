"""Tests for placing freshly created nodes (fxhoudinimcp_server.config).

Two defects live here, and they pull in opposite directions.

With FXHOUDINIMCP_AUTO_LAYOUT=0 -- the setting issue #2 asked for -- nothing
positioned a new node at all: create_node set a position only when the caller
passed one, and build_network(layout=True) funnelled into layout_if_enabled,
which the flag turns off. Every node a session built stayed at (0, 0), stacked.

With the flag either way, the handlers that did position a node called
moveToGoodPosition() bare, whose move_inputs/move_outputs/move_unconnected all
default to True -- so placing one new node could drag the user's existing nodes
around, which is the complaint issue #2 opened with.

Both are fixed by one helper that places the new node with those three pinned
to False, so "a new node gets a position" and "existing nodes never move" stop
being in tension.
"""

from __future__ import annotations

# Built-in
import os
import pathlib
import sys
from unittest.mock import MagicMock

# Third-party
import pytest

# Mock Houdini before importing the in-Houdini server package
sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Internal
import fxhoudinimcp_server.config as config  # noqa: E402
import fxhoudinimcp_server.handlers.node_handlers as nodes  # noqa: E402

_HANDLER_DIR = (
    pathlib.Path(__file__).resolve().parents[1]
    / "houdini/scripts/python/fxhoudinimcp_server/handlers"
)


class _FakeNode:
    """Records placement attempts instead of talking to Houdini."""

    def __init__(self, path="/obj/geo1/box1", raises=False, pos=(0.0, 0.0), parent=None):
        self._path = path
        self.raises = raises
        self.pos = pos
        self._parent = parent
        self.placements = []
        self.positions = []
        self.layouts = []

    def parent(self):
        return self._parent

    def moveToGoodPosition(self, **kwargs):
        if self.raises:
            raise RuntimeError("no network editor")
        self.placements.append(kwargs)

    def setPosition(self, vector):
        self.positions.append(vector)

    def position(self):
        return self.pos

    def layoutChildren(self):
        self.layouts.append(True)

    def children(self):
        return ()

    def path(self):
        return self._path

    def name(self):
        return self._path.rsplit("/", 1)[-1]

    def type(self):
        return MagicMock(**{"name.return_value": "box"})


class _FakeParent(_FakeNode):
    def __init__(self, path="/obj/geo1"):
        super().__init__(path)
        self.created = []

    def createNode(self, node_type, node_name=None):
        node = _FakeNode(f"{self._path}/{node_name or node_type}1")
        self.created.append(node)
        return node


class TestPlaceNewNode:
    def test_existing_nodes_are_pinned_down(self):
        """The three move_* kwargs are the whole point: default True moves
        the user's other nodes, which is what issue #2 objected to."""
        node = _FakeNode()
        config.place_new_node(node)
        assert node.placements == [
            {
                "relative_to_inputs": True,
                "move_inputs": False,
                "move_outputs": False,
                "move_unconnected": False,
            }
        ]

    def test_placement_failure_never_breaks_the_call(self):
        config.place_new_node(_FakeNode(raises=True))  # must not raise

    def test_nodes_are_placed_in_creation_order(self):
        order = []
        made = []
        for i in range(3):
            node = _FakeNode(f"/obj/geo1/n{i}")
            node.moveToGoodPosition = lambda _n=node, **kw: order.append(_n.name())
            made.append(node)
        config.place_new_nodes(made)
        assert order == ["n0", "n1", "n2"]

    def test_none_entries_are_skipped(self):
        node = _FakeNode()
        config.place_new_nodes([None, node, None])
        assert len(node.placements) == 1

    def test_not_gated_by_the_auto_layout_flag(self, monkeypatch):
        """The flag guards rearranging a network, not placing a new node --
        otherwise turning it off leaves every new node at the origin."""
        monkeypatch.setattr(config, "auto_layout_enabled", lambda: False)
        node = _FakeNode()
        config.place_new_node(node)
        assert node.placements


class TestCreateNodePlacement:
    @pytest.fixture
    def parent(self, monkeypatch):
        parent = _FakeParent()
        monkeypatch.setattr(nodes, "_get_node", lambda path: parent)
        monkeypatch.setattr(nodes, "_focus_network_editor", lambda node: None)
        return parent

    def test_node_without_a_position_is_placed(self, parent):
        nodes.create_node("/obj/geo1", "box")
        assert parent.created[0].placements  # not left at (0, 0)

    def test_an_explicit_position_wins(self, parent, monkeypatch):
        monkeypatch.setattr(nodes.hou, "Vector2", lambda x, y: (x, y), raising=False)
        nodes.create_node("/obj/geo1", "box", position=[5, -3])
        node = parent.created[0]
        assert node.positions == [(5, -3)]
        assert node.placements == []  # the caller's position is not second-guessed


class TestLayoutIfEnabledChokepoint:
    """Every creation path already ends in layout_if_enabled -- directly or
    via each handler's _focus_network_editor -- so the placement floor lives
    there: with auto-layout off, children still stacked at the origin are
    placed, and children that already have a position never move."""

    def _parent(self, children):
        parent = _FakeNode("/obj/geo1")
        parent.children = lambda: tuple(children)
        return parent

    def test_flag_off_places_only_the_origin_children(self, monkeypatch):
        monkeypatch.setattr(config, "auto_layout_enabled", lambda: False)
        fresh = _FakeNode("/obj/geo1/box1")
        arranged = _FakeNode("/obj/geo1/sphere1", pos=(3.25, -1.5))
        parent = self._parent([arranged, fresh])
        config.layout_if_enabled(parent)
        assert fresh.placements  # the unplaced node got a position
        assert arranged.placements == []  # the hand-placed one never moved
        assert parent.layouts == []  # and no layout ran with the flag off

    def test_flag_on_lays_out_as_before(self, monkeypatch):
        monkeypatch.setattr(config, "auto_layout_enabled", lambda: True)
        parent = self._parent([_FakeNode()])
        config.layout_if_enabled(parent)
        assert parent.layouts == [True]

    def test_origin_children_are_placed_in_creation_order(self, monkeypatch):
        monkeypatch.setattr(config, "auto_layout_enabled", lambda: False)
        order = []
        made = []
        for i in range(3):
            node = _FakeNode(f"/obj/geo1/n{i}")
            node.moveToGoodPosition = lambda _n=node, **kw: order.append(_n.name())
            made.append(node)
        config.layout_if_enabled(self._parent(made))
        assert order == ["n0", "n1", "n2"]

    def test_children_failure_never_breaks_the_call(self, monkeypatch):
        monkeypatch.setattr(config, "auto_layout_enabled", lambda: False)
        parent = _FakeNode("/obj/geo1")

        def _boom():
            raise RuntimeError("parent vanished")

        parent.children = _boom
        config.layout_if_enabled(parent)  # must not raise

    def test_a_container_parked_at_the_origin_is_placed_too(self, monkeypatch):
        """The workflow handlers call layout_if_enabled(geo) on a container
        they just created and nothing else positions it -- so back-to-back
        setup_*_sim calls piled their containers at /obj's origin."""
        monkeypatch.setattr(config, "auto_layout_enabled", lambda: False)
        root = _FakeNode("/")
        obj = _FakeNode("/obj", parent=root)
        geo = _FakeNode("/obj/pyro_sim", parent=obj)
        config.layout_if_enabled(geo)
        assert geo.placements

    def test_container_placement_is_not_gated_by_the_flag(self, monkeypatch):
        """layoutChildren never moves the parent, so with auto-layout ON the
        container still needs the floor."""
        monkeypatch.setattr(config, "auto_layout_enabled", lambda: True)
        root = _FakeNode("/")
        obj = _FakeNode("/obj", parent=root)
        geo = _FakeNode("/obj/pyro_sim", parent=obj)
        config.layout_if_enabled(geo)
        assert geo.placements
        assert geo.layouts == [True]  # and the children still get their layout

    def test_top_level_managers_are_never_moved(self, monkeypatch):
        """moveToGoodPosition on /obj relocates it inside the root network
        (measured on 22.0.368), so nodes sitting directly under the root are
        exempt from the floor."""
        monkeypatch.setattr(config, "auto_layout_enabled", lambda: False)
        obj = _FakeNode("/obj", parent=_FakeNode("/"))
        config.layout_if_enabled(obj)
        assert obj.placements == []

    def test_an_already_positioned_container_is_left_alone(self, monkeypatch):
        monkeypatch.setattr(config, "auto_layout_enabled", lambda: False)
        root = _FakeNode("/")
        obj = _FakeNode("/obj", parent=root)
        geo = _FakeNode("/obj/fixture", pos=(2.0, -1.0), parent=obj)
        config.layout_if_enabled(geo)
        assert geo.placements == []


class TestHandlerSourceGuard:
    def test_no_bare_move_to_good_position_in_handlers(self):
        """Regression guard: a bare call takes the dangerous defaults, so every
        handler goes through config.place_new_node instead."""
        offenders = [
            path.name
            for path in sorted(_HANDLER_DIR.glob("*.py"))
            if "moveToGoodPosition" in path.read_text(encoding="utf-8")
        ]
        assert offenders == []

    def test_every_creating_handler_reaches_a_placement_route(self):
        """A handler that calls createNode must reach the placement floor
        somehow: place_new_node directly, or layout_if_enabled (usually via
        its _focus_network_editor). Guards the next handler someone adds --
        the bare-call guard above passes trivially for a file that never
        positions anything at all."""
        routes = ("place_new_node", "layout_if_enabled", "_focus_network_editor")
        offenders = []
        for path in sorted(_HANDLER_DIR.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            if "createNode(" in text and not any(route in text for route in routes):
                offenders.append(path.name)
        assert offenders == []
