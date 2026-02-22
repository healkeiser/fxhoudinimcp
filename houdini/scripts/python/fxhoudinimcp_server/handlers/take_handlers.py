"""Takes handlers for FXHoudini-MCP.

Provides tools for listing, inspecting, creating, and switching
between Houdini takes (parameter override system).
"""

from __future__ import annotations

# Built-in
from typing import Any

# Third-party
import hou

# Internal
from fxhoudinimcp_server.dispatcher import register_handler


###### takes.list_takes

def _list_takes(**_: Any) -> dict[str, Any]:
    """List all takes in the scene with their hierarchy.

    Returns each take's name, whether it is the current take, its
    parent name, and the number of children.
    """
    current_take = hou.takes.currentTake()
    current_name = current_take.name() if current_take else None

    takes_list: list[dict[str, Any]] = []
    for take in hou.takes.takes():
        parent = take.parent()
        parent_name = parent.name() if parent else None
        children = take.children()

        takes_list.append({
            "name": take.name(),
            "is_current": take.name() == current_name,
            "parent": parent_name,
            "children": [c.name() for c in children],
        })

    return {
        "count": len(takes_list),
        "takes": takes_list,
        "current_take": current_name,
    }

register_handler("takes.list_takes", _list_takes)


###### takes.get_current_take

def _get_current_take(**_: Any) -> dict[str, Any]:
    """Get the current take and list its overridden parameters.

    Returns the take name and all parameters that are overridden
    in this take with their current values.
    """
    current_take = hou.takes.currentTake()
    if current_take is None:
        return {
            "name": None,
            "overridden_parms": [],
        }

    take_name = current_take.name()

    # Collect overridden parameters
    overridden_parms: list[dict[str, Any]] = []
    for parm_tuple in current_take.parmTuples():
        node = parm_tuple.node()
        for parm in parm_tuple:
            try:
                val = parm.eval()
            except Exception:
                val = None
            overridden_parms.append({
                "node_path": node.path(),
                "parm_name": parm.name(),
                "value": val,
            })

    return {
        "name": take_name,
        "overridden_parms": overridden_parms,
    }

register_handler("takes.get_current_take", _get_current_take)


###### takes.set_current_take

def _set_current_take(*, name: str, **_: Any) -> dict[str, Any]:
    """Set the current take by name.

    Args:
        name: Name of the take to make current.
    """
    target_take = None
    for take in hou.takes.takes():
        if take.name() == name:
            target_take = take
            break

    if target_take is None:
        available = [t.name() for t in hou.takes.takes()]
        raise ValueError(
            f"Take not found: '{name}'. "
            f"Available takes: {available}"
        )

    hou.takes.setCurrentTake(target_take)

    return {
        "name": name,
        "success": True,
    }

register_handler("takes.set_current_take", _set_current_take)


###### takes.create_take

def _create_take(
    *,
    name: str,
    parent_name: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Create a new take, optionally as a child of an existing take.

    If parent_name is provided, the new take is created as a child of
    that take. Otherwise it is created under the current take.

    Args:
        name: Name for the new take.
        parent_name: Optional name of the parent take.
    """
    if parent_name is not None:
        # Find and set the parent take as current first
        parent_take = None
        for take in hou.takes.takes():
            if take.name() == parent_name:
                parent_take = take
                break

        if parent_take is None:
            available = [t.name() for t in hou.takes.takes()]
            raise ValueError(
                f"Parent take not found: '{parent_name}'. "
                f"Available takes: {available}"
            )

        hou.takes.setCurrentTake(parent_take)

    # Create the new take (it becomes a child of the current take)
    new_take = hou.takes.currentTake().addChildTake(name)
    hou.takes.setCurrentTake(new_take)

    actual_parent = new_take.parent()
    actual_parent_name = actual_parent.name() if actual_parent else None

    return {
        "name": new_take.name(),
        "parent": actual_parent_name,
    }

register_handler("takes.create_take", _create_take)
