"""Scene-understanding / context handlers for FXHoudini-MCP.

Provides tools for querying network structure, cook chains, node
explanations, selection management, scene summaries, state snapshots,
and detailed error analysis.
"""

from __future__ import annotations

# Built-in
from typing import Any

# Third-party
import hou

# Internal
from fxhoudinimcp_server.dispatcher import register_handler


###### Module-level state

# Snapshot storage for compare_snapshots
_snapshots: dict[str, dict] = {}


###### Helpers

def _get_node(node_path: str) -> hou.Node:
    """Resolve a node path and raise a clear error if it does not exist."""
    node = hou.node(node_path)
    if node is None:
        raise ValueError(f"Node not found: {node_path}")
    return node


def _node_flags(node: hou.Node) -> dict[str, bool]:
    """Safely read common flags from a node."""
    flags: dict[str, bool] = {}
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
    return flags


def _has_errors(node: hou.Node) -> bool:
    """Return True if the node has any errors."""
    try:
        return bool(node.errors())
    except Exception:
        return False


def _non_default_parms(node: hou.Node) -> dict[str, Any]:
    """Return a dict of parameter names to values for non-default parameters."""
    result: dict[str, Any] = {}
    for parm in node.parms():
        try:
            val = parm.eval()
        except Exception:
            continue
        try:
            tmpl = parm.parmTemplate()
            defaults = tmpl.defaultValue()
            if isinstance(defaults, tuple):
                default = defaults[0] if len(defaults) == 1 else defaults
            else:
                default = defaults
        except Exception:
            default = None
        # Compare current value to default
        if val != default:
            if isinstance(val, (hou.Vector2, hou.Vector3, hou.Vector4)):
                val = list(val)
            result[parm.name()] = val
    return result


###### context.get_network_overview

def _get_network_overview(
    path: str = "/obj",
    depth: int = 2,
    **_: Any,
) -> dict:
    """Return a compact network overview of nodes and connections.

    Args:
        path: Root network path to inspect.
        depth: How many levels deep to recurse into children.
    """

    def _build_overview(network: hou.Node, remaining_depth: int) -> dict:
        children = network.children()

        nodes_info = []
        connections = []
        display_node = None
        render_node = None

        for child in children:
            flags = _node_flags(child)
            info = {
                "name": child.name(),
                "type": child.type().name(),
                "position": list(child.position()),
                "flags": flags,
                "has_errors": _has_errors(child),
            }
            if flags.get("display"):
                display_node = child.name()
            if flags.get("render"):
                render_node = child.name()
            nodes_info.append(info)

        # Build connections as adjacency list
        for child in children:
            for input_idx, source in enumerate(child.inputs()):
                if source is not None:
                    connections.append({
                        "from": source.name(),
                        "from_output": 0,
                        "to": child.name(),
                        "to_input": input_idx,
                    })
                    # Try to find actual output index
                    for out_conn in source.outputConnections():
                        if (out_conn.inputNode().path() == child.path()
                                and out_conn.inputIndex() == input_idx):
                            connections[-1]["from_output"] = out_conn.outputIndex()
                            break

        # Build ASCII art representation
        ascii_lines = _build_ascii_flow(children)

        result: dict[str, Any] = {
            "path": network.path(),
            "node_count": len(children),
            "nodes": nodes_info,
            "connections": connections,
            "display_node": display_node,
            "render_node": render_node,
            "ascii_flow": ascii_lines,
        }

        # Recurse into children that are networks
        if remaining_depth > 1:
            child_networks = {}
            for child in children:
                if child.children():
                    child_networks[child.name()] = _build_overview(
                        child, remaining_depth - 1,
                    )
            if child_networks:
                result["child_networks"] = child_networks

        return result

    def _build_ascii_flow(children: tuple) -> str:
        """Build a simple ASCII-art text of the network flow."""
        if not children:
            return "(empty network)"

        # Build chains by following outputs from source nodes
        visited = set()
        chains = []

        # Find source nodes (no inputs connected from siblings)
        sibling_paths = {c.path() for c in children}
        source_nodes = []
        for child in children:
            inputs = child.inputs()
            has_sibling_input = False
            for inp in inputs:
                if inp is not None and inp.path() in sibling_paths:
                    has_sibling_input = True
                    break
            if not has_sibling_input:
                source_nodes.append(child)

        if not source_nodes:
            # Cycle or all connected; just start from first child
            source_nodes = [children[0]]

        def _follow_chain(node: hou.Node) -> list[str]:
            chain = []
            current = node
            while current is not None and current.path() not in visited:
                visited.add(current.path())
                flags = _node_flags(current)
                suffix = ""
                if flags.get("display"):
                    suffix += " [D]"
                if flags.get("render"):
                    suffix += " [R]"
                if flags.get("bypass"):
                    suffix += " [B]"
                chain.append(current.name() + suffix)
                # Follow first output that is a sibling
                next_node = None
                for out in current.outputs():
                    if out.path() in sibling_paths and out.path() not in visited:
                        next_node = out
                        break
                current = next_node
            return chain

        for src in source_nodes:
            if src.path() not in visited:
                chain = _follow_chain(src)
                if chain:
                    chains.append(chain)

        # Also add any unvisited nodes
        for child in children:
            if child.path() not in visited:
                chain = _follow_chain(child)
                if chain:
                    chains.append(chain)

        lines = []
        for chain in chains:
            lines.append(" -> ".join(chain))
        return "\n".join(lines) if lines else "(no connections)"

    root = _get_node(path)
    return _build_overview(root, depth)


###### context.get_cook_chain

def _get_cook_chain(node_path: str, **_: Any) -> dict:
    """Trace the cook dependency chain from sources to the target node.

    Walks node.inputs() recursively back to source nodes and returns
    an ordered list from source to target.

    Args:
        node_path: Absolute path to the target node.
    """
    target = _get_node(node_path)

    visited: set[str] = set()
    chain: list[dict] = []

    def _walk(node: hou.Node) -> None:
        if node.path() in visited:
            return
        visited.add(node.path())
        # Walk inputs first (sources come before dependents)
        for inp in node.inputs():
            if inp is not None:
                _walk(inp)
        # Cook time
        try:
            cook_time = node.cookTime()
        except Exception:
            cook_time = None
        chain.append({
            "path": node.path(),
            "type": node.type().name(),
            "cook_time": cook_time,
            "has_errors": _has_errors(node),
        })

    _walk(target)

    return {
        "target": node_path,
        "chain_length": len(chain),
        "chain": chain,
    }


###### context.explain_node

def _explain_node(node_path: str, **_: Any) -> dict:
    """Return a human-readable explanation of a node.

    Includes type description, non-default parameters, connections,
    current state, and a summary text field.

    Args:
        node_path: Absolute path to the node.
    """
    node = _get_node(node_path)
    node_type = node.type()

    # Type description
    type_desc = node_type.description()
    type_name = node_type.name()
    category = node_type.category().name()

    # Non-default parameters
    changed_parms = _non_default_parms(node)

    # Input connections
    inputs = []
    for i, inp in enumerate(node.inputs()):
        if inp is not None:
            inputs.append({
                "index": i,
                "path": inp.path(),
                "name": inp.name(),
                "type": inp.type().name(),
            })

    # Output connections
    outputs = []
    for out in node.outputs():
        outputs.append({
            "path": out.path(),
            "name": out.name(),
            "type": out.type().name(),
        })

    # Current state
    errors = []
    warnings = []
    try:
        errors = list(node.errors())
    except Exception:
        pass
    try:
        warnings = list(node.warnings())
    except Exception:
        pass
    try:
        cook_time = node.cookTime()
    except Exception:
        cook_time = None

    flags = _node_flags(node)

    state = {
        "errors": errors,
        "warnings": warnings,
        "cook_time": cook_time,
        "flags": flags,
    }

    # Build summary text
    summary_parts = [f"{node.name()} is a {type_desc} ({category}/{type_name})."]
    if changed_parms:
        parm_strs = [f"{k}={v!r}" for k, v in list(changed_parms.items())[:10]]
        summary_parts.append(f"Modified parameters: {', '.join(parm_strs)}.")
    if inputs:
        input_strs = [f"{inp['name']} ({inp['type']})" for inp in inputs]
        summary_parts.append(f"Inputs: {', '.join(input_strs)}.")
    else:
        summary_parts.append("No inputs connected.")
    if outputs:
        output_strs = [f"{out['name']} ({out['type']})" for out in outputs]
        summary_parts.append(f"Outputs: {', '.join(output_strs)}.")
    else:
        summary_parts.append("No outputs connected.")
    if errors:
        summary_parts.append(f"ERRORS: {'; '.join(errors)}")
    if warnings:
        summary_parts.append(f"Warnings: {'; '.join(warnings)}")
    if flags.get("display"):
        summary_parts.append("Display flag is ON.")
    if flags.get("render"):
        summary_parts.append("Render flag is ON.")
    if flags.get("bypass"):
        summary_parts.append("Node is BYPASSED.")

    return {
        "node_path": node.path(),
        "type_description": type_desc,
        "type_name": type_name,
        "category": category,
        "changed_parameters": changed_parms,
        "inputs": inputs,
        "outputs": outputs,
        "state": state,
        "summary": " ".join(summary_parts),
    }


###### context.get_selection

def _get_selection(**_: Any) -> dict:
    """Get the current selection in Houdini.

    Returns selected nodes and, if available, geometry component
    selection (points, prims, edges).
    """
    # Node selection
    selected_nodes = hou.selectedNodes()
    nodes_info = []
    for node in selected_nodes:
        nodes_info.append({
            "path": node.path(),
            "type": node.type().name(),
            "name": node.name(),
        })

    # Geometry selection
    geo_info: dict[str, Any] | None = None
    try:
        # Attempt to get geometry-level selection from the current viewer
        viewer = hou.ui.curDesktop().paneTabOfType(hou.paneTabType.SceneViewer)
        if viewer is not None:
            sel = viewer.currentGeometrySelection()
            if sel is not None:
                sel_type = sel.geometryType()
                selections = sel.selections()
                total_count = 0
                sel_node_path = None
                if selections:
                    # Get the node from the first selected node context
                    sel_nodes = sel.nodes()
                    if sel_nodes:
                        sel_node_path = sel_nodes[0].path()
                        geo = sel_nodes[0].geometry()
                        if geo is not None:
                            for s in selections:
                                total_count += len(s.selectionString(
                                    geo,
                                ).split()) if s.selectionString(geo) else 0
                type_name = "unknown"
                if sel_type == hou.geometryType.Points:
                    type_name = "points"
                elif sel_type == hou.geometryType.Primitives:
                    type_name = "primitives"
                elif sel_type == hou.geometryType.Edges:
                    type_name = "edges"
                elif sel_type == hou.geometryType.Vertices:
                    type_name = "vertices"
                geo_info = {
                    "type": type_name,
                    "count": total_count,
                    "node_path": sel_node_path,
                }
    except Exception:
        # Geometry selection may not be available in all contexts
        pass

    return {
        "nodes": nodes_info,
        "geometry": geo_info,
    }


###### context.set_selection

def _set_selection(node_paths: list | None = None, **_: Any) -> dict:
    """Select nodes by their paths.

    Clears the existing selection first, then selects the specified nodes.

    Args:
        node_paths: List of absolute node paths to select.
    """
    if node_paths is None:
        node_paths = []

    hou.clearAllSelected()

    selected_count = 0
    for path in node_paths:
        node = hou.node(path)
        if node is not None:
            node.setSelected(True)
            selected_count += 1

    return {
        "success": True,
        "selected_count": selected_count,
        "requested_count": len(node_paths),
    }


###### context.get_scene_summary

def _get_scene_summary(**_: Any) -> dict:
    """Return a high-level overview of the entire Houdini scene.

    Includes /obj, /out, /stage children, total node count,
    error summary, and timeline info.
    """
    # /obj children
    obj_children = []
    obj_node = hou.node("/obj")
    if obj_node is not None:
        for child in obj_node.children():
            info: dict[str, Any] = {
                "name": child.name(),
                "type": child.type().name(),
            }
            # Count SOPs inside and find displayed SOP
            sub_children = child.children()
            sop_count = 0
            displayed_sop = None
            for sub in sub_children:
                if sub.type().category().name() == "Sop":
                    sop_count += 1
                    try:
                        if sub.isDisplayFlagSet():
                            displayed_sop = sub.name()
                    except Exception:
                        pass
            info["sop_count"] = sop_count
            info["displayed_sop"] = displayed_sop
            obj_children.append(info)

    # /out children (render nodes)
    out_children = []
    out_node = hou.node("/out")
    if out_node is not None:
        for child in out_node.children():
            info = {
                "name": child.name(),
                "type": child.type().name(),
            }
            # Try to get output path from common parameter names
            output_path = None
            for parm_name in ("sopoutput", "vm_picture", "picture",
                              "lopoutput", "outputimage"):
                parm = child.parm(parm_name)
                if parm is not None:
                    try:
                        output_path = parm.eval()
                        break
                    except Exception:
                        pass
            info["output_path"] = output_path
            out_children.append(info)

    # /stage children (LOP networks)
    stage_children = []
    stage_node = hou.node("/stage")
    if stage_node is not None:
        for child in stage_node.children():
            stage_children.append({
                "name": child.name(),
                "type": child.type().name(),
            })

    # Total node count and error scan
    total_nodes = 0
    error_count = 0
    root = hou.node("/")
    if root is not None:
        all_nodes = root.allSubChildren()
        total_nodes = len(all_nodes)
        for node in all_nodes:
            if _has_errors(node):
                error_count += 1

    # Timeline info
    current_frame = hou.frame()
    try:
        frame_range = list(hou.playbar.playbackRange())
    except Exception:
        frame_range = [1, 240]
    fps = hou.fps()

    return {
        "obj_children": obj_children,
        "out_children": out_children,
        "stage_children": stage_children,
        "total_nodes": total_nodes,
        "error_count": error_count,
        "current_frame": current_frame,
        "frame_range": frame_range,
        "fps": fps,
    }


###### context.compare_snapshots

def _compare_snapshots(
    action: str = "take",
    snapshot_name: str = "default",
    **_: Any,
) -> dict:
    """Take or compare scene snapshots for structural diffing.

    Args:
        action: "take" to store current state, "compare" to diff against stored.
        snapshot_name: Name of the snapshot to take or compare against.
    """
    global _snapshots

    def _capture_state() -> dict[str, dict]:
        """Capture current scene state as a lightweight snapshot."""
        state: dict[str, dict] = {}
        root = hou.node("/")
        if root is None:
            return state
        for node in root.allSubChildren():
            parms = _non_default_parms(node)
            state[node.path()] = {
                "type": node.type().name(),
                "params": parms,
            }
        return state

    if action == "take":
        snapshot = _capture_state()
        _snapshots[snapshot_name] = snapshot
        return {
            "success": True,
            "action": "take",
            "snapshot_name": snapshot_name,
            "node_count": len(snapshot),
        }

    elif action == "compare":
        stored = _snapshots.get(snapshot_name)
        if stored is None:
            raise ValueError(
                f"No snapshot named '{snapshot_name}' found. "
                f"Available snapshots: {list(_snapshots.keys())}"
            )

        current = _capture_state()

        stored_paths = set(stored.keys())
        current_paths = set(current.keys())

        nodes_added = sorted(current_paths - stored_paths)
        nodes_removed = sorted(stored_paths - current_paths)

        # Find parameter changes on nodes that exist in both
        params_changed: list[dict] = []
        for path in sorted(stored_paths & current_paths):
            old_params = stored[path]["params"]
            new_params = current[path]["params"]
            if old_params != new_params:
                # Determine what changed
                all_keys = set(old_params.keys()) | set(new_params.keys())
                changes: dict[str, dict] = {}
                for key in all_keys:
                    old_val = old_params.get(key)
                    new_val = new_params.get(key)
                    if old_val != new_val:
                        changes[key] = {"old": old_val, "new": new_val}
                if changes:
                    params_changed.append({
                        "path": path,
                        "changes": changes,
                    })

        return {
            "action": "compare",
            "snapshot_name": snapshot_name,
            "nodes_added": nodes_added,
            "nodes_removed": nodes_removed,
            "params_changed": params_changed,
            "nodes_added_count": len(nodes_added),
            "nodes_removed_count": len(nodes_removed),
            "params_changed_count": len(params_changed),
        }

    else:
        raise ValueError(
            f"Unknown action '{action}'. Must be 'take' or 'compare'."
        )


###### context.get_node_errors_detailed

def _get_node_errors_detailed(
    node_path: str | None = None,
    root_path: str = "/",
    **_: Any,
) -> dict:
    """Deep error analysis for a specific node or all descendants of a root.

    For each error, returns the node path, error message, node type,
    and parameters that might be causing it (e.g. file path params
    pointing to missing files).

    Args:
        node_path: If given, analyze errors on this specific node.
        root_path: If node_path is None, scan all descendants of this root.
    """
    import os as _os

    results: list[dict] = []

    def _analyze_node(node: hou.Node) -> None:
        errors = []
        warnings = []
        try:
            errors = list(node.errors())
        except Exception:
            pass
        try:
            warnings = list(node.warnings())
        except Exception:
            pass

        if not errors and not warnings:
            return

        # Identify parameters that might be causing issues
        suspect_parms: list[dict] = []
        for parm in node.parms():
            try:
                tmpl = parm.parmTemplate()
                # Check file-type parameters
                if tmpl.type() == hou.parmTemplateType.String:
                    tags = tmpl.tags()
                    is_file = (
                        tags.get("filechooser_mode") is not None
                        or "file" in parm.name().lower()
                        or tmpl.stringType() == hou.stringParmType.FileReference
                    )
                    if is_file:
                        val = parm.eval()
                        if val and not val.startswith("op:"):
                            # Expand Houdini variables
                            expanded = hou.text.expandString(val)
                            if expanded and not _os.path.exists(expanded):
                                suspect_parms.append({
                                    "name": parm.name(),
                                    "value": val,
                                    "expanded": expanded,
                                    "issue": "file_not_found",
                                })
            except Exception:
                pass

        entry = {
            "node_path": node.path(),
            "node_type": node.type().name(),
            "errors": errors,
            "warnings": warnings,
            "suspect_parameters": suspect_parms,
        }
        results.append(entry)

    if node_path is not None:
        node = _get_node(node_path)
        _analyze_node(node)
    else:
        root = _get_node(root_path)
        _analyze_node(root)
        for child in root.allSubChildren():
            _analyze_node(child)

    return {
        "scanned_path": node_path or root_path,
        "error_node_count": len(results),
        "details": results,
    }


###### Registration

register_handler("context.get_network_overview", _get_network_overview)
register_handler("context.get_cook_chain", _get_cook_chain)
register_handler("context.explain_node", _explain_node)
register_handler("context.get_selection", _get_selection)
register_handler("context.set_selection", _set_selection)
register_handler("context.get_scene_summary", _get_scene_summary)
register_handler("context.compare_snapshots", _compare_snapshots)
register_handler("context.get_node_errors_detailed", _get_node_errors_detailed)
