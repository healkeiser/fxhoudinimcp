"""Node-level handlers for FXHoudini-MCP.

Provides tools for creating, inspecting, connecting, and manipulating
nodes within Houdini's node graph.
"""

from __future__ import annotations

# Third-party
import hou

# Internal
from fxhoudinimcp_server.dispatcher import register_handler


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


def _focus_network_editor(node: hou.Node) -> None:
    """Best-effort: layout the parent network, then pan the editor to *node*."""
    try:
        parent = node.parent()
        if parent is not None:
            parent.layoutChildren()
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
            f"Failed to create node of type '{node_type}' inside '{parent_path}': {e}"
        )

    if position is not None and len(position) >= 2:
        node.setPosition(hou.Vector2(position[0], position[1]))

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

def get_node_info(node_path: str) -> dict:
    """Return comprehensive information about a node.

    Includes type, parameters summary, inputs, outputs, flags,
    errors, warnings, and cook time.

    Args:
        node_path: Absolute path to the node.
    """
    node = _get_node(node_path)

    # Parameter summary (name, value, default)
    parms_summary = []
    for parm in node.parms():
        try:
            val = parm.eval()
        except Exception:
            val = None
        try:
            default = parm.parmTemplate().defaultValue()
            if isinstance(default, tuple) and len(default) == 1:
                default = default[0]
        except Exception:
            default = None
        parms_summary.append({
            "name": parm.name(),
            "label": parm.description(),
            "value": val if not isinstance(val, (hou.Vector2, hou.Vector3, hou.Vector4)) else list(val),
            "default": default if not isinstance(default, tuple) else list(default),
            "type": parm.parmTemplate().type().name(),
        })

    # Inputs
    inputs = []
    for i, conn in enumerate(node.inputs()):
        if conn is not None:
            inputs.append({
                "index": i,
                "node_path": conn.path(),
                "node_name": conn.name(),
            })
        else:
            inputs.append({"index": i, "node_path": None, "node_name": None})

    # Outputs
    outputs = []
    for conn in node.outputs():
        outputs.append({
            "node_path": conn.path(),
            "node_name": conn.name(),
        })

    # Flags
    flags = {}
    try:
        flags["display"] = node.isDisplayFlagSet()
    except Exception:
        pass
    try:
        flags["render"] = node.isRenderFlagSet()
    except Exception:
        pass
    try:
        flags["bypass"] = node.isBypassed()
    except Exception:
        pass
    try:
        flags["template"] = node.isTemplateFlagSet()
    except Exception:
        pass
    try:
        flags["lock"] = node.isHardLocked()
    except Exception:
        pass

    # Errors and warnings
    try:
        errors = list(node.errors())
    except Exception:
        errors = []
    try:
        warnings = list(node.warnings())
    except Exception:
        warnings = []

    # Cook time
    try:
        cook_time = node.cookTime()
    except Exception:
        cook_time = None

    # Type info
    node_type = node.type()
    type_info = {
        "name": node_type.name(),
        "label": node_type.description(),
        "category": node_type.category().name(),
        "icon": node_type.icon(),
    }

    return {
        "node_path": node.path(),
        "name": node.name(),
        "type": type_info,
        "parameters": parms_summary,
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

    if recursive:
        children = parent.allSubChildren()
    else:
        children = parent.children()

    results = []
    for child in children:
        if filter_type and child.type().name() != filter_type:
            continue
        results.append(_node_summary(child))

    return {
        "parent_path": parent_path,
        "count": len(results),
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

    results = []
    for node in all_nodes:
        # Filter by name pattern
        if pattern is not None:
            import fnmatch
            if not fnmatch.fnmatch(node.name(), pattern):
                continue

        # Filter by type
        if node_type is not None:
            if node.type().name() != node_type:
                continue

        # Filter by category/context
        if context is not None:
            if node.type().category().name() != context:
                continue

        results.append(_node_summary(node))

    return {
        "count": len(results),
        "nodes": results,
    }


###### nodes.list_node_types

def list_node_types(context: str) -> dict:
    """List all available node types in a given context category.

    Args:
        context: Category name, e.g. "Sop", "Lop", "Dop", "Top",
                 "Cop2", "Object", "Driver".
    """
    categories = hou.nodeTypeCategories()
    category = categories.get(context)
    if category is None:
        available = sorted(categories.keys())
        raise ValueError(
            f"Unknown node type category: '{context}'. "
            f"Available categories: {available}"
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
        type_list.append({
            "name": type_name,
            "label": node_type.description(),
            "icon": node_type.icon(),
        })

    return {
        "context": context,
        "count": len(type_list),
        "types": type_list,
    }


###### nodes.connect_nodes

def connect_nodes(
    source_path: str,
    dest_path: str,
    output_index: int = 0,
    input_index: int = 0,
) -> dict:
    """Wire two nodes together.

    Args:
        source_path: Path to the source (upstream) node.
        dest_path: Path to the destination (downstream) node.
        output_index: Output connector index on the source node.
        input_index: Input connector index on the destination node.
    """
    source = _get_node(source_path)
    dest = _get_node(dest_path)

    dest.setInput(input_index, source, output_index)

    _focus_network_editor(dest)

    return {
        "success": True,
        "source_path": source.path(),
        "dest_path": dest.path(),
        "output_index": output_index,
        "input_index": input_index,
    }


###### nodes.connect_nodes_batch

def connect_nodes_batch(
    connections: list,
) -> dict:
    """Wire multiple node pairs in a single call.

    Args:
        connections: List of dicts, each with keys:
            source_path, dest_path, output_index (default 0), input_index (default 0).
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
            source = _get_node(src_path)
            dest = _get_node(dst_path)
            dest.setInput(in_idx, source, out_idx)
            last_dest = dest
            results.append({
                "source_path": source.path(),
                "dest_path": dest.path(),
                "output_index": out_idx,
                "input_index": in_idx,
            })
        except Exception as exc:
            errors.append({
                "source_path": src_path,
                "dest_path": dst_path,
                "error": str(exc),
            })

    if last_dest is not None:
        _focus_network_editor(last_dest)

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

    if disconnect_all:
        for i in range(len(node.inputs())):
            if node.inputs()[i] is not None:
                node.setInput(i, None)
                disconnected.append(i)
    elif input_index is not None:
        current_inputs = node.inputs()
        if input_index < len(current_inputs) and current_inputs[input_index] is not None:
            node.setInput(input_index, None)
            disconnected.append(input_index)
        else:
            raise ValueError(
                f"Input index {input_index} is out of range or already disconnected "
                f"on node {node_path}."
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
    current_inputs = list(node.inputs())

    if len(new_order) > len(current_inputs):
        raise ValueError(
            f"new_order has {len(new_order)} entries but node only has "
            f"{len(current_inputs)} inputs."
        )

    # Disconnect all first
    for i in range(len(current_inputs)):
        node.setInput(i, None)

    # Reconnect in the new order
    for new_idx, old_idx in enumerate(new_order):
        if old_idx < len(current_inputs) and current_inputs[old_idx] is not None:
            node.setInput(new_idx, current_inputs[old_idx])

    return {
        "success": True,
        "node_path": node_path,
        "new_order": new_order,
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
    changed = {}

    if display is not None:
        try:
            node.setDisplayFlag(display)
            changed["display"] = display
        except hou.OperationFailed:
            pass  # Some node types don't support display flag

    if render is not None:
        try:
            node.setRenderFlag(render)
            changed["render"] = render
        except hou.OperationFailed:
            pass

    if bypass is not None:
        try:
            node.bypass(bypass)
            changed["bypass"] = bypass
        except hou.OperationFailed:
            pass

    if template is not None:
        try:
            node.setTemplateFlag(template)
            changed["template"] = template
        except hou.OperationFailed:
            pass

    if lock is not None:
        try:
            node.setHardLocked(lock)
            changed["lock"] = lock
        except hou.OperationFailed:
            pass

    if not changed:
        raise ValueError(
            "No flags were changed. Either no flags were specified or "
            "the node does not support the requested flags."
        )

    if changed.get("display"):
        _focus_network_editor(node)

    return {
        "success": True,
        "node_path": node_path,
        "changed_flags": changed,
    }


###### nodes.layout_children

def layout_children(parent_path: str, spacing: float = None) -> dict:
    """Auto-layout the children of a network node.

    Args:
        parent_path: Path to the parent network.
        spacing: Optional spacing multiplier between nodes.
    """
    parent = _get_node(parent_path)

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


###### Registration

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
register_handler("nodes.connect_nodes_batch", connect_nodes_batch)
register_handler("nodes.disconnect_node", disconnect_node)
register_handler("nodes.reorder_inputs", reorder_inputs)
register_handler("nodes.set_node_flags", set_node_flags)
register_handler("nodes.layout_children", layout_children)
register_handler("nodes.set_node_position", set_node_position)
register_handler("nodes.set_node_color", set_node_color)
