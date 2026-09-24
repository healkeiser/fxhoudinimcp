"""Node-level handlers for FXHoudini-MCP.

Provides tools for creating, inspecting, connecting, and manipulating
nodes within Houdini's node graph.
"""

from __future__ import annotations

import contextlib
import re
import time
from difflib import get_close_matches
from typing import Any

# Third-party
import hou

# Internal
from fxhoudinimcp_server.config import (
    auto_layout_enabled,
    layout_if_enabled,
    mark_placed,
    place_new_node,
)
from fxhoudinimcp_server.dispatcher import register_handler
from fxhoudinimcp_server.errors import readable_message
from fxhoudinimcp_server.serialize import to_jsonable

###### Helpers


def _get_node(node_path: str) -> hou.Node:
    """Resolve a node path and raise a clear error if it does not exist."""
    node = hou.node(node_path)
    if node is None:
        raise ValueError(f"Node not found: {node_path}")
    return node


def _node_summary(node: hou.Node) -> dict:
    """Return a compact summary dict for a single node."""
    return {
        "name": node.name(),
        "path": node.path(),
        "type": node.type().name(),
        "category": node.type().category().name(),
    }


def _focus_network_editor(node: hou.Node, place_unpositioned: bool = True) -> None:
    """Best-effort: layout the parent network, then pan the editor to *node*.

    Callers that created nothing pass ``place_unpositioned=False``, so a call
    that only rewires or flips a flag never relocates a node the user parked at
    the origin.
    """
    try:
        parent = node.parent()
        if parent is not None:
            layout_if_enabled(parent, place_unpositioned)
        for pane_tab in hou.ui.paneTabs():
            if pane_tab.type() == hou.paneTabType.NetworkEditor:
                if parent is not None:
                    pane_tab.cd(parent.path())
                pane_tab.setCurrentNode(node)
                pane_tab.homeToSelection()
                return
    except Exception:
        pass  # Never let UI helpers break a tool call


###### nodes.create_node


def create_node(
    parent_path: str,
    node_type: str,
    name: str = None,
    position: list = None,
) -> dict:
    """Create a new node inside the given parent network.

    Args:
        parent_path: Path to the parent network (e.g. "/obj" or "/obj/geo1").
        node_type: Type name (e.g. "geo", "box", "grid", "merge").
        name: Optional explicit node name.
        position: Optional [x, y] position in the network editor.
    """
    parent = _get_node(parent_path)

    try:
        node = parent.createNode(node_type, node_name=name)
    except hou.OperationFailed as e:
        raise ValueError(
            f"Failed to create node of type '{node_type}' inside '{parent_path}': {readable_message(e)}"
        ) from e

    if position is not None and len(position) >= 2:
        node.setPosition(hou.Vector2(position[0], position[1]))
        # The caller's position is final, including [0, 0] -- without the tag
        # the floor would read that as "never positioned" and move it.
        mark_placed(node)
    else:
        # No position asked for: place it beside its inputs rather than leaving
        # it at (0, 0) on top of whatever is already there.
        place_new_node(node)

    _focus_network_editor(node)

    return {
        "success": True,
        "node_path": node.path(),
        "node_type": node.type().name(),
        "name": node.name(),
        "position": list(node.position()),
    }


###### nodes.delete_node


def delete_node(node_path: str) -> dict:
    """Delete a node from the scene.

    Args:
        node_path: Absolute path to the node to delete.
    """
    node = _get_node(node_path)
    name = node.name()
    parent_path = node.parent().path()
    node.destroy()

    return {
        "success": True,
        "deleted_node": node_path,
        "name": name,
        "parent_path": parent_path,
    }


###### nodes.rename_node


def rename_node(node_path: str, new_name: str) -> dict:
    """Rename an existing node.

    Args:
        node_path: Absolute path to the node.
        new_name: Desired new name for the node.
    """
    node = _get_node(node_path)
    old_name = node.name()
    node.setName(new_name, unique_name=True)

    return {
        "success": True,
        "old_name": old_name,
        "new_name": node.name(),
        "new_path": node.path(),
    }


###### nodes.copy_node


def copy_node(
    node_path: str,
    dest_parent: str = None,
    new_name: str = None,
) -> dict:
    """Copy a node, optionally into a different parent network.

    Args:
        node_path: Path to the source node.
        dest_parent: Destination parent path. If None, copies within the same parent.
        new_name: Optional name for the copied node.
    """
    node = _get_node(node_path)
    parent = _get_node(dest_parent) if dest_parent else node.parent()

    copied = hou.copyNodesTo([node], parent)[0]

    if new_name:
        copied.setName(new_name, unique_name=True)

    return {
        "success": True,
        "source_path": node_path,
        "copied_path": copied.path(),
        "name": copied.name(),
    }


###### nodes.move_node


def move_node(node_path: str, dest_parent: str) -> dict:
    """Move a node to a different parent network.

    Args:
        node_path: Path to the node to move.
        dest_parent: Destination parent network path.
    """
    node = _get_node(node_path)
    dest = _get_node(dest_parent)

    moved = hou.moveNodesTo([node], dest)[0]

    return {
        "success": True,
        "original_path": node_path,
        "new_path": moved.path(),
        "name": moved.name(),
    }


###### nodes.get_node_info


# Parameter kinds that carry no value: pressing, grouping, decorating.
_VALUELESS_PARM_TYPES = frozenset({"Button", "Folder", "FolderSet", "Separator", "Label"})


def _component_default(parm: hou.Parm) -> Any:
    """The default of *parm* itself, not of the tuple it belongs to.

    ``parmTemplate().defaultValue()`` describes the whole tuple, so ``ty`` on
    an xform used to be compared with ``(0.0, 0.0, 0.0)`` and every component
    of every tuple came back "non-default" (34 entries on a bare xform with
    one edit).
    """
    default = parm.parmTemplate().defaultValue()
    if isinstance(default, (tuple, list)):
        try:
            index = parm.componentIndex()
        except Exception:
            index = 0
        if not isinstance(index, int) or index < 0 or index >= len(default):
            return default[0] if len(default) == 1 else None
        return default[index]
    return default


def _is_at_default(parm: hou.Parm, value: Any, default: Any) -> bool:
    """Whether *parm* still holds its default.

    Houdini's own answer (``isAtDefault``, which also sees an expression as a
    change) is preferred; a component comparison is the fallback for
    anything that cannot answer.
    """
    try:
        answer = parm.isAtDefault()
        if isinstance(answer, bool):
            return answer
    except Exception:
        pass
    # Reached only when isAtDefault() is unavailable or answers non-bool.
    # Ramp and Data parameters have no comparable defaultValue(), so == is
    # false for them here and they reach the response -- which is why they
    # have to survive JSON encoding (see serialize.py).
    try:
        return bool(value == default)
    except Exception:
        return False


def _non_default_parms(node: hou.Node, parms: list[hou.Parm]) -> list[dict[str, Any]]:
    """The parameters of *node* that differ from their defaults, as summaries.

    Buttons, folders, separators and labels carry no value and are skipped.
    """
    summary: list[dict[str, Any]] = []
    for parm in parms:
        try:
            template = parm.parmTemplate()
            type_name = template.type().name()
        except Exception:
            continue
        if type_name in _VALUELESS_PARM_TYPES:
            continue
        try:
            val = parm.eval()
        except Exception:
            continue
        try:
            default = _component_default(parm)
        except Exception:
            default = None
        if _is_at_default(parm, val, default):
            continue
        summary.append(
            {
                "name": parm.name(),
                "label": parm.description(),
                "value": to_jsonable(val),
                "default": to_jsonable(default),
                "type": type_name,
            }
        )
    return summary


def get_node_info(node_path: str) -> dict:
    """Return comprehensive information about a node.

    Includes type, parameters summary, inputs, outputs, flags,
    errors, warnings, and cook time.

    Args:
        node_path: Absolute path to the node.
    """
    node = _get_node(node_path)

    # Errors and warnings BEFORE any parameter is evaluated. Evaluating a
    # cook-local expression outside a cook (a factory ``$N`` in a Group SOP's
    # rangeend, ``@N.x`` in a Ray SOP's dir) sets a transient "Unable to
    # evaluate expression" on the node, and errors() called afterwards in the
    # same main-thread tick makes it stick: a healthy node came back with a
    # real error, and kept it until it was force-cooked. Read first, it is
    # the node's actual state and nothing is left behind.
    try:
        errors = list(node.errors())
    except Exception:
        errors = []
    try:
        warnings = list(node.warnings())
    except Exception:
        warnings = []

    # Only return parameters that differ from their defaults — this keeps
    # the response compact (a complex node can have 500+ parms, most at default).
    # Use get_parameter_schema to inspect the full parameter list.
    all_parms = node.parms()
    parms_summary = _non_default_parms(node, all_parms)

    # Inputs
    inputs = []
    for i, conn in enumerate(node.inputs()):
        if conn is not None:
            inputs.append(
                {
                    "index": i,
                    "node_path": conn.path(),
                    "node_name": conn.name(),
                }
            )
        else:
            inputs.append({"index": i, "node_path": None, "node_name": None})

    # Outputs
    outputs = []
    for conn in node.outputs():
        outputs.append(
            {
                "node_path": conn.path(),
                "node_name": conn.name(),
            }
        )

    # Flags
    flags = {}
    with contextlib.suppress(Exception):
        flags["display"] = node.isDisplayFlagSet()
    with contextlib.suppress(Exception):
        flags["render"] = node.isRenderFlagSet()
    with contextlib.suppress(Exception):
        flags["bypass"] = node.isBypassed()
    with contextlib.suppress(Exception):
        flags["template"] = node.isTemplateFlagSet()
    with contextlib.suppress(Exception):
        flags["lock"] = node.isHardLocked()

    # Cook time
    try:
        cook_time = node.cookTime()
    except Exception:
        cook_time = None

    # Type info — icon omitted (string path, useless to LLM)
    node_type = node.type()
    type_info = {
        "name": node_type.name(),
        "label": node_type.description(),
        "category": node_type.category().name(),
    }

    return {
        "node_path": node.path(),
        "name": node.name(),
        "type": type_info,
        "total_param_count": len(all_parms),
        "non_default_parameters": parms_summary,
        "input_connectors": node.type().maxNumInputs(),
        "inputs": inputs,
        "outputs": outputs,
        "flags": flags,
        "errors": errors,
        "warnings": warnings,
        "cook_time": cook_time,
        "comment": node.comment(),
        "position": list(node.position()),
        "color": list(node.color().rgb()),
    }


###### nodes.list_children


def list_children(
    parent_path: str,
    recursive: bool = False,
    filter_type: str = None,
) -> dict:
    """List children of a network node.

    Args:
        parent_path: Path to the parent network.
        recursive: If True, list all descendants, not just direct children.
        filter_type: Optional node type name to filter by (e.g. "box", "merge").
    """
    parent = _get_node(parent_path)

    children = parent.allSubChildren() if recursive else parent.children()

    _MAX_CHILDREN = 500
    results = []
    for child in children:
        if filter_type and child.type().name() != filter_type:
            continue
        results.append(_node_summary(child))
        if len(results) >= _MAX_CHILDREN:
            break

    return {
        "parent_path": parent_path,
        "count": len(results),
        "truncated": len(results) >= _MAX_CHILDREN,
        "children": results,
    }


###### nodes.find_nodes


def find_nodes(
    pattern: str = None,
    node_type: str = None,
    context: str = None,
    inside: str = "/",
) -> dict:
    """Search for nodes by name pattern and/or type.

    Args:
        pattern: Glob pattern for node names (e.g. "box*", "*merge*").
        node_type: Filter by node type name (e.g. "box", "null").
        context: Filter by node category name (e.g. "Sop", "Object").
        inside: Root path to search within.
    """
    root = _get_node(inside)
    all_nodes = root.allSubChildren()

    _MAX_RESULTS = 500
    results = []
    for node in all_nodes:
        # Filter by name pattern
        if pattern is not None:
            import fnmatch

            if not fnmatch.fnmatch(node.name(), pattern):
                continue

        # Filter by type
        if node_type is not None and node.type().name() != node_type:
            continue

        # Filter by category/context
        if context is not None and node.type().category().name() != context:
            continue

        results.append(_node_summary(node))
        if len(results) >= _MAX_RESULTS:
            break

    return {
        "count": len(results),
        "truncated": len(results) >= _MAX_RESULTS,
        "nodes": results,
    }


###### nodes.list_node_types


def list_node_types(
    context: str,
    filter: str = None,
    limit: int = 200,
    **_,
) -> dict:
    """List available node types in a given context category.

    Args:
        context: Category name, e.g. "Sop", "Lop", "Dop", "Top",
                 "Cop2", "Object", "Driver".
        filter: Optional substring to filter by type name or label
                (case-insensitive). Use this to avoid dumping all types.
        limit: Maximum number of types to return (default 200).
    """
    categories = hou.nodeTypeCategories()
    category = categories.get(context)
    if category is None:
        available = sorted(categories.keys())
        raise ValueError(
            f"Unknown node type category: '{context}'. Available categories: {available}"
        )

    types_dict = category.nodeTypes()
    type_list = []
    for type_name, node_type in sorted(types_dict.items()):
        # Skip hidden/deprecated types
        try:
            if node_type.hidden():
                continue
        except Exception:
            pass
        type_list.append(
            {
                "name": type_name,
                "label": node_type.description(),
            }
        )

    if filter:
        f = filter.lower()
        type_list = [t for t in type_list if f in t["name"].lower() or f in t["label"].lower()]

    total = len(type_list)
    type_list = type_list[:limit]
    return {
        "context": context,
        "total_count": total,
        "returned_count": len(type_list),
        "truncated": total > limit,
        "types": type_list,
    }


###### nodes.connect_nodes


def _input_table(node: hou.Node) -> list[dict[str, Any]]:
    """A node's input connectors in order: index, name, label, data type.

    Each read is guarded on its own, so a type whose labels or data types
    cannot be read still lists its names.
    """
    names: list[str] = []
    labels: list[str] = []
    data_types: list[str] = []
    with contextlib.suppress(Exception):
        names = list(node.inputNames())
    with contextlib.suppress(Exception):
        labels = list(node.inputLabels())
    with contextlib.suppress(Exception):
        data_types = list(node.inputDataTypes())
    table: list[dict[str, Any]] = []
    for index, name in enumerate(names):
        entry: dict[str, Any] = {"index": index, "name": name}
        if index < len(labels):
            entry["label"] = labels[index]
        if index < len(data_types):
            entry["data_type"] = data_types[index]
        table.append(entry)
    return table


_NUMBERED = re.compile(r"(.*?)(\d+)")


def _variadic_index(inputs: list[dict[str, Any]], name: str, max_inputs: int) -> int | None:
    """Index of `input3` on a node that grows inputs as they are wired.

    A merge or switch lists only the connectors it has now (a fresh merge
    shows `input1` though it takes 9999), so a name further along the same
    numbered series is still a real connector.
    """
    if not inputs or max_inputs <= len(inputs):
        return None
    first = _NUMBERED.fullmatch(str(inputs[0].get("name", "")))
    wanted = _NUMBERED.fullmatch(name)
    if first is None or wanted is None or wanted.group(1) != first.group(1):
        return None
    stem, start = first.group(1), int(first.group(2))
    if any(entry.get("name") != f"{stem}{start + entry['index']}" for entry in inputs):
        return None
    index = int(wanted.group(2)) - start
    return index if 0 <= index < max_inputs else None


def _find_input(inputs: list[dict[str, Any]], input_name: str, max_inputs: int = 0) -> int:
    """Index of the input called *input_name*: names first, then labels, then
    the rest of a numbered variadic series. The one rule build_network's dry
    run and every wiring verb use, so validation and wiring cannot disagree.
    """
    for entry in inputs:
        if entry.get("name") == input_name:
            return int(entry["index"])
    for entry in inputs:
        if entry.get("label") == input_name:
            return int(entry["index"])
    variadic = _variadic_index(inputs, input_name, max_inputs)
    if variadic is not None:
        return variadic
    candidates: list[str] = []
    for entry in inputs:
        for value in (entry.get("name"), entry.get("label")):
            if value and value not in candidates:
                candidates.append(value)
    close = get_close_matches(input_name, candidates, n=3, cutoff=0.4)
    if close:
        hint = f" Did you mean: {close}?"
    else:
        hint = f" Inputs: {candidates[:15] + (['...'] if len(candidates) > 15 else [])}"
    raise ValueError(f"has no input named '{input_name}'.{hint}")


def _resolve_input_index(dest: hou.Node, input_index: int, input_name: str | None) -> int:
    """Turn an input name (VOP connector such as "base_color") into its index.

    VOP shaders have dozens of inputs and their order is not stable across
    versions; the name is what the node card shows. Indices still work.
    """
    if not input_name:
        return int(input_index)
    max_inputs = 0
    with contextlib.suppress(Exception):
        max_inputs = int(dest.type().maxNumInputs())
    try:
        return _find_input(_input_table(dest), str(input_name), max_inputs)
    except ValueError as exc:
        raise ValueError(f"{dest.path()} {exc}") from None


def _indirect_input_item(subnet: hou.Node, indirect: Any, connectors: list | None = None):
    """Input connector *indirect* of *subnet*, or ValueError saying why not.

    The one rule for connect_nodes, connect_nodes_batch and build_network.
    *connectors* is the subnet's indirectInputs() when the caller already
    listed them.
    """
    if isinstance(indirect, float) and indirect.is_integer():
        indirect = int(indirect)
    if isinstance(indirect, bool) or not isinstance(indirect, int):
        raise ValueError(f"indirect_input must be an integer, got {indirect!r}")
    if connectors is None:
        try:
            connectors = list(subnet.indirectInputs())
        except Exception as exc:
            raise ValueError(
                f"{subnet.path()} has no input connectors to wire from: {readable_message(exc)}"
            ) from exc
    if not connectors:
        # Not a subnet (a Box answers an empty tuple on 22.0 rather than the
        # documented InvalidNodeType), or a subnet with no inputs.
        raise ValueError(
            f"{subnet.path()} has no input connectors to wire from: it is not a "
            f"subnet, or a subnet without inputs."
        )
    if not 0 <= indirect < len(connectors):
        raise ValueError(
            f"{subnet.path()} has {len(connectors)} input connector(s); asked for #{indirect}."
        )
    return connectors[indirect]


def _resolve_source(
    source_path: str, indirect_input: Any, dest: hou.Node, output_index: int
) -> Any:
    """The item to wire from: a node, or one of a subnet's indirect inputs.

    A subnet's input connectors are not nodes inside it — they are
    `SubnetIndirectInput` items with no path of their own, so the first node
    of a chain built inside a subnet could not be fed from the outside by any
    verb. `indirect_input=n` names connector n of the subnet at `source_path`.
    """
    node = _get_node(source_path)
    if indirect_input is None:
        return node
    item = _indirect_input_item(node, indirect_input)
    if dest.parent() != node:
        raise ValueError(
            f"{dest.path()} is not inside {node.path()}: a subnet's input connector "
            f"feeds only nodes inside that subnet."
        )
    if int(output_index) != 0:
        raise ValueError(
            f"a subnet input connector has one output; output_index must be 0, got {output_index}."
        )
    return item


def connect_nodes(
    source_path: str,
    dest_path: str,
    output_index: int = 0,
    input_index: int = 0,
    input_name: str | None = None,
    indirect_input: int | None = None,
) -> dict:
    """Wire two nodes together.

    Args:
        source_path: Path to the source (upstream) node — or, with
            `indirect_input`, the subnet whose input connector is the source.
        dest_path: Path to the destination (downstream) node.
        output_index: Output connector index on the source node.
        input_index: Input connector index on the destination node.
        input_name: Input connector name or label; wins over input_index.
        indirect_input: Index of the subnet input connector at `source_path`
            to wire from (the node at dest_path must live inside that subnet).
    """
    dest = _get_node(dest_path)
    source = _resolve_source(source_path, indirect_input, dest, output_index)

    input_index = _resolve_input_index(dest, input_index, input_name)
    dest.setInput(input_index, source, output_index)

    _focus_network_editor(dest, place_unpositioned=False)

    result = {
        "success": True,
        "source_path": _get_node(source_path).path(),
        "dest_path": dest.path(),
        "output_index": output_index,
        "input_index": input_index,
    }
    if indirect_input is not None:
        # source_path stays a path a caller can reuse; the connector is here.
        result["indirect_input"] = int(indirect_input)
    return result


###### nodes.change_node_type


def _non_default_parm_names(node: hou.Node) -> set[str]:
    names = set()
    for parm in node.parms():
        with contextlib.suppress(Exception):
            if not parm.isAtDefault():
                names.add(parm.name())
    return names


def change_node_type(
    node_path: str,
    new_type: str,
    keep_name: bool = True,
    keep_parms: bool = True,
    keep_network_contents: bool = True,
) -> dict:
    """Swap a node for another type in place — wires, name, position, flags
    and (by default) parameter values and network contents kept.

    This is the Type Properties "change type" / asset "upgrade to version"
    gesture: an HDA instance moved to an installed newer version keeps its
    edits. Every value that was set before the swap and is not set after it
    is named in `parms_dropped` (no home on the new type) or `parms_reset`
    (back at its default), measured on the node rather than inferred from
    the flags.

    Args:
        node_path: Node to change.
        new_type: Type name in the node's own category (unversioned names
            map to the preferred version, as create_node does).
        keep_name: Keep the node's name (default True).
        keep_parms: Carry parameter values over by name (default True).
        keep_network_contents: Keep the children of a subnet/asset (default
            True). False resets an asset to its definition's contents, also
            when the node already is of the requested type.
    """
    from fxhoudinimcp_server.handlers.graph_handlers import _resolve_node_type

    node = _get_node(node_path)
    category = node.type().category()
    resolved = _resolve_node_type(category, new_type)
    if resolved is None:
        close = get_close_matches(new_type, list(category.nodeTypes()), n=3, cutoff=0.5)
        hint = f" Did you mean: {close}?" if close else ""
        raise ValueError(f"Type '{new_type}' does not exist in {category.name()}.{hint}")
    old_type = node.type().name()
    same_type = resolved.name() == old_type
    # Re-applying the same type only does something when the contents are
    # to be reset; otherwise it would be a no-op that still costs an undo.
    changing = not same_type or not keep_network_contents

    before_parms = {p.name() for p in node.parms()}
    before_non_default = _non_default_parm_names(node)
    changed = node
    if changing:
        kwargs = {
            "keep_name": bool(keep_name),
            "keep_parms": bool(keep_parms),
            "keep_network_contents": bool(keep_network_contents),
        }
        if same_type:
            kwargs["force_change_on_node_type_match"] = True
        try:
            changed = node.changeNodeType(resolved.name(), **kwargs)
        except Exception as exc:
            raise ValueError(
                f"Could not change {node_path} ({old_type}) to {resolved.name()}: "
                f"{readable_message(exc)}"
            ) from exc
        _focus_network_editor(changed, place_unpositioned=False)

    after_parms = {p.name() for p in changed.parms()}
    lost = before_non_default - _non_default_parm_names(changed)
    result: dict[str, Any] = {
        "success": True,
        "node_path": changed.path(),
        "old_type": old_type,
        "new_type": changed.type().name(),
        "changed": changing,
        "keep_parms": bool(keep_parms),
        "keep_network_contents": bool(keep_network_contents),
        # Set values with no home on the new type, and set values that are
        # back at their default: together, everything the swap lost.
        "parms_dropped": sorted(lost - after_parms),
        "parms_reset": sorted(lost & after_parms),
        # Every parameter the new type lacks, set or not.
        "parms_removed_count": len(before_parms - after_parms),
        "inputs": [i.path() if i is not None else None for i in changed.inputs()],
        "outputs": [o.path() for o in changed.outputs()],
    }
    if not changing:
        result["message"] = f"{changed.path()} is already of type {old_type}; nothing changed."
    with contextlib.suppress(Exception):
        result["child_count"] = len(changed.children())
    with contextlib.suppress(Exception):
        if changed.type().definition() is not None:
            result["matches_definition"] = changed.matchesCurrentDefinition()
    return result


###### nodes.press_button

# The value types HOM's pressButton accepts in its arguments dict.
_BUTTON_ARGUMENT_TYPES = (bool, int, float, str)


def press_button(
    node_path: str,
    parm_name: str,
    arguments: dict | None = None,
    cook: bool = False,
) -> dict:
    """Press a button parameter and report what the node says afterwards.

    Runs the button's callback exactly as a click would ("Stash Input",
    "Reload Geometry", an asset's own Build button). The call holds until
    the callback returns, with no deadline; a callback that opens a dialog
    holds Houdini's main thread, and with it this bridge, until the dialog
    is closed.

    A press usually only dirties the node: `errors` and `warnings` are from
    its last cook, which may predate the press. `cook=True` cooks the node
    after the press so they describe the result; without it `needs_cook`
    says whether they are stale (a cook that failed leaves it True too).

    Args:
        node_path: Node that owns the button.
        parm_name: The button parameter's name.
        arguments: Optional kwargs handed to the callback script; values
            must be int, bool, float or str.
        cook: Cook the node after the press (default False).
    """
    node = _get_node(node_path)
    parm = node.parm(parm_name)
    if parm is None:
        names = [p.name() for p in node.parms()]
        close = get_close_matches(parm_name, names, n=3, cutoff=0.4)
        buttons = [p.name() for p in node.parms() if p.parmTemplate().type().name() == "Button"]
        hint = f" Did you mean: {close}?" if close else ""
        raise ValueError(
            f"{node.path()} has no parameter '{parm_name}'.{hint} Buttons on this node: {buttons}"
        )
    for key, value in (arguments or {}).items():
        if not isinstance(value, _BUTTON_ARGUMENT_TYPES):
            raise ValueError(
                f"arguments['{key}'] is {type(value).__name__}; a button callback "
                f"takes only int, bool, float or str values. Nothing was pressed."
            )
    template = parm.parmTemplate()
    parm_type = template.type().name()
    started = time.perf_counter()
    try:
        if arguments:
            parm.pressButton(dict(arguments))
        else:
            parm.pressButton()
    except Exception as exc:
        raise ValueError(
            f"Callback of {node.path()}/{parm_name} failed: {readable_message(exc)}"
        ) from exc
    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    result: dict[str, Any] = {
        "success": True,
        "node_path": node.path(),
        "parm_name": parm.name(),
        "parm_type": parm_type,
        "duration_ms": duration_ms,
        "cooked": False,
    }
    if cook:
        # A failed cook is an answer, not a failure of the press: its
        # messages land in errors() below.
        with contextlib.suppress(Exception):
            node.cook(force=False)
        result["cooked"] = True
    with contextlib.suppress(Exception):
        result["needs_cook"] = node.needsToCook()
    for key, read in (("errors", node.errors), ("warnings", node.warnings)):
        try:
            result[key] = list(read())
        except Exception:
            result[key] = []
    with contextlib.suppress(Exception):
        # Built-in buttons (File's Reload, Stash's Stash Input) are handled in
        # C++ and have no script callback; False does not mean inert.
        result["has_script_callback"] = bool(template.scriptCallback())
    if parm_type != "Button":
        result["note"] = (
            f"'{parm_name}' is a {parm_type} parameter, not a Button; its callback "
            f"script (if any) was triggered the way pressButton does for any parameter."
        )
    return result


###### nodes.connect_nodes_batch


def connect_nodes_batch(
    connections: list,
) -> dict:
    """Wire multiple node pairs in a single call.

    Args:
        connections: List of dicts, each with keys:
            source_path, dest_path, output_index (default 0), input_index (default 0),
            input_name (optional; a connector name or label, wins over input_index),
            indirect_input (optional; source_path is then a subnet and this is the
            index of its input connector to wire from).
    """
    results = []
    errors = []

    last_dest = None
    for conn in connections:
        src_path = conn["source_path"]
        dst_path = conn["dest_path"]
        out_idx = int(conn.get("output_index", 0))
        in_idx = int(conn.get("input_index", 0))
        try:
            dest = _get_node(dst_path)
            source = _resolve_source(src_path, conn.get("indirect_input"), dest, out_idx)
            in_idx = _resolve_input_index(dest, in_idx, conn.get("input_name"))
            dest.setInput(in_idx, source, out_idx)
            last_dest = dest
            entry = {
                "source_path": _get_node(src_path).path(),
                "dest_path": dest.path(),
                "output_index": out_idx,
                "input_index": in_idx,
            }
            if conn.get("indirect_input") is not None:
                entry["indirect_input"] = int(conn["indirect_input"])
            results.append(entry)
        except Exception as exc:
            errors.append(
                {
                    "source_path": src_path,
                    "dest_path": dst_path,
                    "error": str(exc),
                }
            )

    if last_dest is not None:
        _focus_network_editor(last_dest, place_unpositioned=False)

    return {
        "success": len(errors) == 0,
        "connected": results,
        "errors": errors,
    }


###### nodes.disconnect_node


def disconnect_node(
    node_path: str,
    input_index: int = None,
    disconnect_all: bool = False,
) -> dict:
    """Disconnect one or all inputs of a node.

    Args:
        node_path: Path to the node whose inputs to disconnect.
        input_index: Specific input index to disconnect. Ignored if disconnect_all is True.
        disconnect_all: If True, disconnect all inputs.
    """
    node = _get_node(node_path)
    disconnected = []
    # inputConnections(), not inputs(): inputs() hides a wire from a subnet's
    # input connector (it reports the node outside the subnet, or None when
    # that input is open), so such a wire could be made but not removed.
    connected = sorted({conn.inputIndex() for conn in node.inputConnections()})

    if disconnect_all:
        for i in connected:
            node.setInput(i, None)
            disconnected.append(i)
    elif input_index is not None:
        if input_index in connected:
            node.setInput(input_index, None)
            disconnected.append(input_index)
        else:
            raise ValueError(
                f"Input index {input_index} is out of range or already disconnected "
                f"on node {node_path}. Connected inputs: {connected}."
            )
    else:
        raise ValueError("Provide either input_index or set disconnect_all=True.")

    return {
        "success": True,
        "node_path": node_path,
        "disconnected_inputs": disconnected,
    }


###### nodes.reorder_inputs


def reorder_inputs(node_path: str, new_order: list) -> dict:
    """Reorder the input connections of a node.

    Args:
        node_path: Path to the node.
        new_order: List of integers representing the new input ordering.
                   For example, [1, 0] swaps the first two inputs.
    """
    node = _get_node(node_path)
    # Every wire with the item it comes from and that item's output: a
    # subnet input connector is an item, not a node, and inputs() hides it.
    wires = {
        conn.inputIndex(): (conn.inputItem(), conn.inputItemOutputIndex())
        for conn in node.inputConnections()
    }
    count = max([len(node.inputs())] + [index + 1 for index in wires])

    if len(new_order) > count:
        raise ValueError(
            f"new_order has {len(new_order)} entries but node only has {count} inputs."
        )
    bad = [old for old in new_order if not isinstance(old, int) or not 0 <= old < count]
    if bad:
        raise ValueError(f"new_order refers to inputs {bad}; {node_path} has inputs 0-{count - 1}.")

    # Inputs new_order does not mention follow in their original order. They
    # used to be cleared and never rewired: [1, 0] on a 3-input merge, the
    # docstring's own example, silently dropped input 2.
    order = list(new_order) + [i for i in range(count) if i not in new_order]

    # Checked before anything is disconnected, so a refusal leaves the wires.
    for i in wires:
        node.setInput(i, None)
    for new_idx, old_idx in enumerate(order):
        if old_idx in wires:
            item, output_index = wires[old_idx]
            node.setInput(new_idx, item, output_index)

    return {
        "success": True,
        "node_path": node_path,
        "new_order": order,
    }


###### nodes.set_node_flags


def set_node_flags(
    node_path: str,
    display: bool = None,
    render: bool = None,
    bypass: bool = None,
    template: bool = None,
    lock: bool = None,
) -> dict:
    """Set one or more flags on a node.

    Args:
        node_path: Path to the node.
        display: Set the display flag.
        render: Set the render flag.
        bypass: Set the bypass flag.
        template: Set the template flag.
        lock: Set the hard-lock flag.
    """
    node = _get_node(node_path)
    requested = {
        "display": display,
        "render": render,
        "bypass": bypass,
        "template": template,
        "lock": lock,
    }
    changed: dict[str, bool] = {}
    not_applied: dict[str, str] = {}
    for flag, wanted in requested.items():
        if wanted is None:
            continue
        setter, getter = _FLAG_ACCESSORS[flag]
        try:
            getattr(node, setter)(bool(wanted))
            actual = bool(getattr(node, getter)())
        except (AttributeError, hou.OperationFailed) as exc:
            not_applied[flag] = f"{node.type().name()} has no {flag} flag ({type(exc).__name__})"
            continue
        # Read back: Houdini ignores some requests without raising. A SOP's
        # display flag cannot be turned off (one node always holds it), and
        # this used to report display: False regardless.
        if actual == bool(wanted):
            changed[flag] = actual
        else:
            not_applied[flag] = f"asked for {bool(wanted)}, Houdini kept {actual}"

    if not changed and not not_applied:
        raise ValueError("No flags were specified.")

    if changed.get("display"):
        _focus_network_editor(node, place_unpositioned=False)

    result = {"success": not not_applied, "node_path": node_path, "changed_flags": changed}
    if not_applied:
        result["not_applied"] = not_applied
    return result


# flag -> (setter, reader), for set_node_flags' readback.
_FLAG_ACCESSORS = {
    "display": ("setDisplayFlag", "isDisplayFlagSet"),
    "render": ("setRenderFlag", "isRenderFlagSet"),
    "bypass": ("bypass", "isBypassed"),
    "template": ("setTemplateFlag", "isTemplateFlagSet"),
    "lock": ("setHardLocked", "isHardLocked"),
}


###### nodes.layout_children


def layout_children(parent_path: str, spacing: float = None) -> dict:
    """Auto-layout the children of a network node.

    Args:
        parent_path: Path to the parent network.
        spacing: Optional spacing multiplier between nodes.
    """
    # Resolve first, so a bad path is named even when layout is disabled.
    parent = _get_node(parent_path)

    if not auto_layout_enabled():
        return {
            "success": False,
            "skipped": True,
            "reason": "Auto-layout is disabled (FXHOUDINIMCP_AUTO_LAYOUT=0).",
        }

    if spacing is not None:
        parent.layoutChildren(horizontal_spacing=spacing, vertical_spacing=spacing)
    else:
        parent.layoutChildren()

    children_paths = [c.path() for c in parent.children()]

    return {
        "success": True,
        "parent_path": parent_path,
        "laid_out_count": len(children_paths),
    }


###### nodes.set_node_position


def set_node_position(node_path: str, x: float, y: float) -> dict:
    """Set the position of a node in the network editor.

    Args:
        node_path: Path to the node.
        x: Horizontal position.
        y: Vertical position.
    """
    node = _get_node(node_path)
    node.setPosition(hou.Vector2(x, y))

    return {
        "success": True,
        "node_path": node_path,
        "position": [x, y],
    }


###### nodes.set_node_color


def set_node_color(node_path: str, r: float, g: float, b: float) -> dict:
    """Set the color of a node in the network editor.

    Args:
        node_path: Path to the node.
        r: Red component (0.0 to 1.0).
        g: Green component (0.0 to 1.0).
        b: Blue component (0.0 to 1.0).
    """
    node = _get_node(node_path)
    color = hou.Color((r, g, b))
    node.setColor(color)

    return {
        "success": True,
        "node_path": node_path,
        "color": [r, g, b],
    }


###### nodes.create_network_box


def create_network_box(
    parent_path: str,
    node_paths: list[str] | None = None,
    comment: str | None = None,
    color: list[float] | None = None,
) -> dict:
    """Draw a network box around nodes, so a built graph explains itself.

    Args:
        parent_path: Network the box lives in.
        node_paths: Nodes to put inside; the box shrinks to fit them.
        comment: Title shown on the box.
        color: RGB in 0..1.
    """
    parent = _get_node(parent_path)
    box = parent.createNetworkBox()
    for path in node_paths or []:
        node = _get_node(path)
        if node.parent() != parent:
            raise ValueError(f"{path} is not a child of {parent_path}; a box only holds siblings.")
        box.addItem(node)
    if comment:
        box.setComment(comment)
    if color is not None:
        box.setColor(hou.Color(*color))
    if node_paths:
        box.fitAroundContents()
    return {
        "success": True,
        "name": box.name(),
        "parent_path": parent.path(),
        "contains": [n.path() for n in box.nodes()],
    }


###### nodes.create_sticky_note


def create_sticky_note(
    parent_path: str,
    text: str,
    position: list[float] | None = None,
    size: list[float] | None = None,
    color: list[float] | None = None,
) -> dict:
    """Leave a note in a network.

    Args:
        parent_path: Network the note lives in.
        text: Note text.
        position: [x, y] in network editor units.
        size: [w, h] in network editor units.
        color: RGB in 0..1.
    """
    parent = _get_node(parent_path)
    note = parent.createStickyNote()
    note.setText(text)
    if position is not None:
        note.setPosition(hou.Vector2(*position))
    if size is not None:
        note.setSize(hou.Vector2(*size))
    if color is not None:
        note.setColor(hou.Color(*color))
    return {
        "success": True,
        "name": note.name(),
        "parent_path": parent.path(),
        "position": list(note.position()),
    }


###### nodes.set_object_transform

_XFORM_PARMS = {"translate": "t", "rotate": "r", "scale": "s"}


def set_object_transform(
    node_path: str,
    translate: list[float] | None = None,
    rotate: list[float] | None = None,
    scale: list[float] | None = None,
    parent: str | None = None,
) -> dict:
    """Set an object's transform parameters and/or parent in one call.

    Args:
        node_path: Object-level node (/obj/...).
        translate: [tx, ty, tz].
        rotate: [rx, ry, rz] in degrees.
        scale: [sx, sy, sz].
        parent: Path of the object to parent under, or "" to unparent.
    """
    node = _get_node(node_path)
    if node.type().category().name() != "Object":
        raise ValueError(
            f"{node_path} is a {node.type().category().name()} node; transforms live on "
            f"object-level nodes under /obj."
        )
    applied: dict = {}
    for key, values in (("translate", translate), ("rotate", rotate), ("scale", scale)):
        prefix = _XFORM_PARMS[key]
        if values is None:
            continue
        if len(values) != 3:
            raise ValueError(f"{key} needs three values, got {len(values)}.")
        tuple_parm = node.parmTuple(prefix)
        if tuple_parm is None:
            raise ValueError(f"{node_path} has no '{prefix}' parameter.")
        tuple_parm.set([float(v) for v in values])
        applied[key] = list(tuple_parm.eval())
    if parent is not None:
        if parent == "":
            node.setInput(0, None)
            applied["parent"] = None
        else:
            new_parent = _get_node(parent)
            node.setInput(0, new_parent)
            applied["parent"] = new_parent.path()
    if not applied:
        raise ValueError("Nothing to set: give translate, rotate, scale or parent.")
    return {"success": True, "node_path": node.path(), **applied}


###### Registration

register_handler("nodes.create_network_box", create_network_box)
register_handler("nodes.create_sticky_note", create_sticky_note)
register_handler("nodes.set_object_transform", set_object_transform)
register_handler("nodes.create_node", create_node)
register_handler("nodes.delete_node", delete_node)
register_handler("nodes.rename_node", rename_node)
register_handler("nodes.copy_node", copy_node)
register_handler("nodes.move_node", move_node)
register_handler("nodes.get_node_info", get_node_info)
register_handler("nodes.list_children", list_children)
register_handler("nodes.find_nodes", find_nodes)
register_handler("nodes.list_node_types", list_node_types)
register_handler("nodes.connect_nodes", connect_nodes)
register_handler("nodes.change_node_type", change_node_type)
register_handler("nodes.press_button", press_button)
register_handler("nodes.connect_nodes_batch", connect_nodes_batch)
register_handler("nodes.disconnect_node", disconnect_node)
register_handler("nodes.reorder_inputs", reorder_inputs)
register_handler("nodes.set_node_flags", set_node_flags)
register_handler("nodes.layout_children", layout_children)
register_handler("nodes.set_node_position", set_node_position)
register_handler("nodes.set_node_color", set_node_color)
