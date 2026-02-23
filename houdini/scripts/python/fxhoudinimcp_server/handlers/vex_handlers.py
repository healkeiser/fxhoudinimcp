"""VEX handlers for FXHoudini-MCP.

Provides tools for creating, reading, and validating VEX code
in Attribute Wrangle nodes and VEX expressions.
"""

from __future__ import annotations

# Built-in
import re

# Third-party
import hou

# Internal
from fxhoudinimcp_server.dispatcher import register_handler


###### Helpers

def _get_node(node_path: str) -> hou.Node:
    """Return a node or raise if not found."""
    node = hou.node(node_path)
    if node is None:
        raise ValueError(f"Node not found: {node_path}")
    return node


def _validate_vex_quick(node: hou.Node) -> dict:
    """Cook a wrangle node and return any VEX errors/warnings."""
    try:
        node.cook(force=True)
    except hou.OperationFailed:
        pass

    errors = []
    warnings = []
    try:
        errors = list(node.errors() or [])
    except Exception:
        pass
    try:
        warnings = list(node.warnings() or [])
    except Exception:
        pass

    return {
        "vex_valid": len(errors) == 0,
        "vex_errors": errors,
        "vex_warnings": warnings,
    }


def _resolve_class_value(node: hou.Node, run_over: str) -> int:
    """Resolve a run_over string to the correct menu index on this node.

    Reads the ``class`` parameter's menu labels dynamically so the mapping
    is always correct regardless of Houdini version.
    """
    class_parm = node.parm("class")
    if class_parm is None:
        raise ValueError(
            f"Node {node.path()} has no 'class' parameter — "
            "is it an Attribute Wrangle?"
        )

    template = class_parm.parmTemplate()
    labels = list(template.menuLabels())
    items = list(template.menuItems())

    # Try exact match first (case-insensitive), then substring match
    target = run_over.strip().lower()
    for idx, label in enumerate(labels):
        if label.lower() == target:
            return int(items[idx]) if items[idx].isdigit() else idx
    for idx, label in enumerate(labels):
        if target in label.lower():
            return int(items[idx]) if items[idx].isdigit() else idx

    raise ValueError(
        f"Invalid run_over value '{run_over}'. "
        f"Available options: {labels}"
    )


def _reverse_class_label(node: hou.Node) -> str | None:
    """Return the human-readable label for the current class value."""
    class_parm = node.parm("class")
    if class_parm is None:
        return None
    value = class_parm.eval()
    template = class_parm.parmTemplate()
    labels = list(template.menuLabels())
    items = list(template.menuItems())
    for idx, item in enumerate(items):
        if (item.isdigit() and int(item) == value) or idx == value:
            return labels[idx] if idx < len(labels) else str(value)
    return str(value)


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
        pass


# Regex pattern for detecting absolute channel paths in VEX code
_RE_ABS_CH = re.compile(r'ch[sfiv]?\s*\(\s*["\']/')


def _check_channel_paths(vex_code: str) -> list[str]:
    """Return warnings if the VEX code contains absolute channel refs."""
    warnings = []
    if _RE_ABS_CH.search(vex_code):
        warnings.append(
            "VEX contains absolute channel path (ch(\"/...\")). "
            "Prefer relative paths — use ../parm_name to reach the "
            "immediate parent, ../../parm_name for two levels up, etc. "
            "Absolute paths break when nodes are renamed or moved."
        )
    return warnings


###### vex.create_wrangle

def create_wrangle(
    parent_path: str,
    vex_code: str,
    run_over: str = "Points",
    name: str = None,
) -> dict:
    """Create an Attribute Wrangle node with VEX code.

    Args:
        parent_path: Path to the parent SOP network.
        vex_code: The VEX snippet code to set.
        run_over: What to run the wrangle over:
                  "Points", "Vertices", "Primitives", "Detail", or "Numbers".
        name: Optional explicit name for the node.
    """
    parent = hou.node(parent_path)
    if parent is None:
        raise ValueError(f"Parent node not found: {parent_path}")

    # Create the attribwrangle node
    try:
        if name:
            node = parent.createNode("attribwrangle", name)
        else:
            node = parent.createNode("attribwrangle")
    except hou.OperationFailed as e:
        raise ValueError(f"Failed to create attribwrangle node: {e}")

    # Set the VEX snippet
    snippet_parm = node.parm("snippet")
    if snippet_parm is None:
        raise ValueError(
            f"Created node {node.path()} does not have a 'snippet' parameter."
        )
    snippet_parm.set(vex_code)

    # Set the run_over class (resolved dynamically from menu labels)
    class_value = _resolve_class_value(node, run_over)
    node.parm("class").set(class_value)

    _focus_network_editor(node)

    # Build relative prefix map so the AI knows what each ../ level reaches.
    ancestors = {}
    current = node.parent()
    level = 1
    while current is not None:
        dots = "/".join([".."] * level)
        ancestors[dots] = current.path()
        current = current.parent()
        level += 1

    result = {
        "success": True,
        "node_path": node.path(),
        "node_name": node.name(),
        "run_over": run_over,
        "vex_code": vex_code,
        "channel_prefix": "../",
        "channel_ancestors": ancestors,
        "channel_hint": (
            "Use relative paths for channel references. "
            "See channel_ancestors to find the correct ../ depth "
            "for the node whose parameters you want to reference."
        ),
    }
    result.update(_validate_vex_quick(node))

    path_warnings = _check_channel_paths(vex_code)
    if path_warnings:
        result.setdefault("vex_warnings", []).extend(path_warnings)

    return result


###### vex.set_wrangle_code

def set_wrangle_code(node_path: str, vex_code: str) -> dict:
    """Set VEX code on an existing Attribute Wrangle node.

    Args:
        node_path: Path to the wrangle node.
        vex_code: The VEX snippet code to set.
    """
    node = _get_node(node_path)

    snippet_parm = node.parm("snippet")
    if snippet_parm is None:
        raise ValueError(
            f"Node {node_path} does not have a 'snippet' parameter. "
            "Is it an Attribute Wrangle?"
        )

    snippet_parm.set(vex_code)

    result = {
        "success": True,
        "node_path": node.path(),
        "vex_code": vex_code,
        "channel_prefix": "../",
    }
    result.update(_validate_vex_quick(node))

    path_warnings = _check_channel_paths(vex_code)
    if path_warnings:
        result.setdefault("vex_warnings", []).extend(path_warnings)

    return result


###### vex.get_wrangle_code

def get_wrangle_code(node_path: str) -> dict:
    """Read the VEX code from an Attribute Wrangle node.

    Args:
        node_path: Path to the wrangle node.
    """
    node = _get_node(node_path)

    snippet_parm = node.parm("snippet")
    if snippet_parm is None:
        raise ValueError(
            f"Node {node_path} does not have a 'snippet' parameter. "
            "Is it an Attribute Wrangle?"
        )

    vex_code = snippet_parm.eval()

    # Also get the run_over class (resolved dynamically from menu labels)
    run_over = _reverse_class_label(node)

    return {
        "node_path": node.path(),
        "vex_code": vex_code,
        "run_over": run_over,
    }


###### vex.create_vex_expression

def create_vex_expression(
    node_path: str,
    parm_name: str,
    vex_code: str,
) -> dict:
    """Set a VEX expression on a parameter.

    This sets the parameter's expression language to VEX and assigns
    the given expression code.

    Args:
        node_path: Path to the node.
        parm_name: Name of the parameter.
        vex_code: The VEX expression code.
    """
    node = _get_node(node_path)

    parm = node.parm(parm_name)
    if parm is None:
        raise ValueError(
            f"Parameter '{parm_name}' not found on node {node_path}."
        )

    try:
        parm.setExpression(vex_code, language=hou.exprLanguage.Hscript)
    except Exception:
        # If Hscript doesn't work, try setting as a Python expression
        try:
            parm.setExpression(vex_code, language=hou.exprLanguage.Python)
        except Exception as e:
            raise ValueError(
                f"Failed to set expression on {node_path}/{parm_name}: {e}"
            )

    return {
        "success": True,
        "node_path": node.path(),
        "parm_name": parm_name,
        "vex_code": vex_code,
    }


###### vex.validate_vex

def validate_vex(node_path: str) -> dict:
    """Validate VEX code by cooking the node and checking for errors.

    Args:
        node_path: Path to the wrangle node to validate.
    """
    node = _get_node(node_path)

    # Read the current VEX code for reference
    vex_code = None
    snippet_parm = node.parm("snippet")
    if snippet_parm is not None:
        vex_code = snippet_parm.eval()

    # Force cook the node to trigger VEX compilation
    try:
        node.cook(force=True)
    except hou.OperationFailed:
        pass  # Errors will be captured below

    # Gather errors and warnings
    errors = []
    warnings = []

    try:
        node_errors = node.errors()
        if node_errors:
            errors = list(node_errors)
    except Exception:
        pass

    try:
        node_warnings = node.warnings()
        if node_warnings:
            warnings = list(node_warnings)
    except Exception:
        pass

    is_valid = len(errors) == 0

    result = {
        "node_path": node.path(),
        "is_valid": is_valid,
        "errors": errors,
        "warnings": warnings,
    }

    if vex_code is not None:
        result["vex_code"] = vex_code

    if is_valid:
        result["message"] = "VEX code is valid."
    else:
        result["message"] = f"VEX code has {len(errors)} error(s)."

    return result


###### Registration

register_handler("vex.create_wrangle", create_wrangle)
register_handler("vex.set_wrangle_code", set_wrangle_code)
register_handler("vex.get_wrangle_code", get_wrangle_code)
register_handler("vex.create_vex_expression", create_vex_expression)
register_handler("vex.validate_vex", validate_vex)
