"""Runtime configuration flags for the in-Houdini MCP server."""

from __future__ import annotations

# Built-in
import os

# Third-party
import hou

_FALSY = {"0", "false", "off", "no"}


def auto_layout_enabled() -> bool:
    """Whether handlers may auto-arrange nodes in the network editor.

    Reads ``FXHOUDINIMCP_AUTO_LAYOUT`` via ``hou.getenv`` first (so it can
    be set in houdini.env or toggled at runtime with ``hou.putenv``), then
    falls back to the process environment. Defaults to enabled; set to
    ``0`` to preserve existing node layouts.
    """
    value = hou.getenv("FXHOUDINIMCP_AUTO_LAYOUT")
    if value is None:
        value = os.environ.get("FXHOUDINIMCP_AUTO_LAYOUT", "1")
    return value.strip().lower() not in _FALSY


def layout_if_enabled(node: hou.Node) -> None:
    """Lay out *node*'s children unless auto-layout is disabled."""
    if auto_layout_enabled():
        node.layoutChildren()


###### Placement of freshly created nodes

# moveToGoodPosition defaults every one of these to True, which lets it drag a
# new node's inputs, outputs and unconnected neighbours around. That is exactly
# the "ruins intentional layouts" complaint from issue #2, so pin them: place
# the node that was just made, move nothing that was already there.
_PLACE_KWARGS = {
    "relative_to_inputs": True,
    "move_inputs": False,
    "move_outputs": False,
    "move_unconnected": False,
}


def place_new_node(node: hou.Node) -> None:
    """Give a *freshly created* node a sensible position, moving nothing else.

    Deliberately not gated by ``FXHOUDINIMCP_AUTO_LAYOUT``: that flag guards
    *rearranging an existing network*, while this only places the node that was
    just created. Without it, a session run with the flag off leaves every new
    node at ``(0, 0)`` in one unreadable pile.

    Measured on Houdini 22.0.368: a node with inputs lands directly under them,
    a node without inputs takes a free column beside the network, and nodes
    that already existed never move.
    """
    try:
        node.moveToGoodPosition(**_PLACE_KWARGS)
    except Exception:
        pass  # placement is cosmetic -- never fail a create because of it


def place_new_nodes(nodes) -> None:
    """Place freshly created *nodes*, in creation order.

    Order matters: each node is positioned relative to its inputs, so the
    upstream end of a fresh chain has to be placed first.
    """
    for node in nodes:
        if node is not None:
            place_new_node(node)
