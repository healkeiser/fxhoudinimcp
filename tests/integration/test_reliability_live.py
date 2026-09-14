"""The two promises that decide whether an artist keeps the server installed.

A failed multi-node build leaves nothing behind and costs the user nothing
from their own undo history; a freshly created node never lands on a node the
user placed. Both are asserted against the scene, not the handler's claim.
"""

from __future__ import annotations

# Third-party
import hou
import pytest

pytestmark = pytest.mark.integration


def _geo(call, name="reliability_geo") -> str:
    return call("nodes.create_node", parent_path="/obj", node_type="geo", name=name)["node_path"]


class TestFailedBuildRollsBack:
    def test_nothing_is_left_behind(self, call):
        geo = _geo(call)
        before = {n.name() for n in hou.node(geo).children()}
        # Validation cannot see this: the expression names a parm that only fails
        # once the node exists, so the build fails on the third node.
        result = call(
            "graph.build_network",
            parent_path=geo,
            nodes=[
                {"name": "a", "type": "box"},
                {"name": "b", "type": "sphere"},
                {"name": "m", "type": "merge", "inputs": ["a", "b"], "expressions": {"nope": "1"}},
            ],
            allow_error=True,
        )
        data = result.get("data") or result
        assert data.get("success") is False, result
        assert "rolled back" in " ".join(data.get("errors", [])), result
        assert {n.name() for n in hou.node(geo).children()} == before

    def test_the_failure_does_not_eat_the_users_previous_step(self, call):
        if not hou.undos.areEnabled():
            pytest.skip("hython keeps no undo history")
        geo = _geo(call)
        call("nodes.create_node", parent_path=geo, node_type="box", name="mine")
        call(
            "graph.build_network",
            parent_path=geo,
            nodes=[{"name": "m", "type": "merge", "expressions": {"nope": "1"}}],
            allow_error=True,
        )
        undone = call("scene.undo")
        # Whatever Houdini kept of the failed step, one undo must not remove the
        # box the user made before it.
        assert hou.node(f"{geo}/mine") is not None, undone


@pytest.fixture
def manual_layout():
    """The contract under test is the one FXHOUDINIMCP_AUTO_LAYOUT=0 promises.

    With the flag on, create_node runs layoutChildren() on the parent and
    every node moves; this test found a hand-placed node three units away
    when the flag still defaulted to on. Off is the default now; pinned here
    so the test says what it asserts.
    """
    hou.putenv("FXHOUDINIMCP_AUTO_LAYOUT", "0")
    yield
    hou.unsetenv("FXHOUDINIMCP_AUTO_LAYOUT")


class TestFreshNodesRespectPlacedOnes:
    def test_a_new_node_never_lands_on_an_existing_one(self, call, manual_layout):
        geo = _geo(call)
        parked = hou.node(geo).createNode("box", "parked_at_origin")
        parked.setPosition(hou.Vector2(0.0, 0.0))
        others = [hou.node(geo).createNode("sphere", f"placed_{i}") for i in range(3)]
        for i, node in enumerate(others):
            node.setPosition(hou.Vector2(3.0 * (i + 1), -1.0))
        positions_before = {n.name(): tuple(n.position()) for n in others}

        call("nodes.create_node", parent_path=geo, node_type="grid", name="fresh_0")
        # The documented ceiling: a node sitting at exactly (0, 0) with no
        # placement tag cannot be told from one the server left there, so it is
        # nudged. Once. It is tagged by that nudge and never touched again.
        nudged_to = tuple(parked.position())
        for i in range(1, 4):
            call("nodes.create_node", parent_path=geo, node_type="grid", name=f"fresh_{i}")
        assert tuple(parked.position()) == nudged_to

        for name, position in positions_before.items():
            moved = hou.node(f"{geo}/{name}").position() - hou.Vector2(position)
            assert moved.length() < 1e-6, (name, tuple(moved))
        spots = [tuple(round(v, 3) for v in n.position()) for n in hou.node(geo).children()]
        assert len(spots) == len(set(spots)), spots
