"""Runtime configuration flags for the in-Houdini MCP server."""

from __future__ import annotations

# Built-in
import contextlib
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
    """Lay out *node*'s children unless auto-layout is disabled.

    Also the placement floor for every creation path: each handler already
    funnels through here (directly or via its ``_focus_network_editor``), so a
    freshly created child must not be left at ``(0, 0)`` no matter what
    ``FXHOUDINIMCP_AUTO_LAYOUT`` says. With auto-layout on, ``layoutChildren``
    positions everything anyway; with it off, only the children still stacked
    at the origin are placed, and nothing that already had a position moves.

    The floor covers *node* itself too: the workflow handlers call this on a
    container they just created (``layout_if_enabled(geo)``), and nothing else
    ever positions that container, so back-to-back ``setup_*_sim`` calls used
    to pile their containers at ``/obj``'s origin. ``layoutChildren`` never
    moves the parent, so this half is not gated by the flag.
    """
    _place_if_unplaced(node)
    if auto_layout_enabled():
        node.layoutChildren()
    else:
        place_new_nodes(_children_stacked_at_origin(node))


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
    # Placement is cosmetic -- never fail a create because of it.
    with contextlib.suppress(Exception):
        node.moveToGoodPosition(**_PLACE_KWARGS)


def place_new_nodes(nodes) -> None:
    """Place freshly created *nodes*, in creation order.

    Order matters: each node is positioned relative to its inputs, so the
    upstream end of a fresh chain has to be placed first.
    """
    for node in nodes:
        if node is not None:
            place_new_node(node)


def _children_stacked_at_origin(parent: hou.Node) -> list:
    """Children still parked at ``(0, 0)`` -- Houdini's mark of the unplaced.

    A node nothing has positioned sits exactly at the origin, so this is how
    the placement floor recognises fresh nodes without tracking every
    ``createNode`` call. The cost: a node someone deliberately parked at
    exactly ``(0, 0)`` gets nudged once. ``children()`` returns creation
    order, which is what ``relative_to_inputs`` placement needs.
    """
    with contextlib.suppress(Exception):
        return [child for child in parent.children() if tuple(child.position()) == (0.0, 0.0)]
    return []


def _place_if_unplaced(node: hou.Node) -> None:
    """Place *node* itself if it is still parked at the origin.

    Guarded against top-level managers: ``moveToGoodPosition`` on ``/obj``
    happily relocates it inside the root network (measured on 22.0.368), so a
    node whose parent is the root -- ``/obj``, ``/out``, ``/mat``, ... -- is
    left alone. Those are exactly the nodes that legitimately live at their
    default positions forever.
    """
    with contextlib.suppress(Exception):
        parent = node.parent()
        if (
            parent is not None
            and parent.parent() is not None
            and tuple(node.position()) == (0.0, 0.0)
        ):
            place_new_node(node)
