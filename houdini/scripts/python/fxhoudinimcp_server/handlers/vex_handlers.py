"""VEX handlers for FXHoudini-MCP.

Provides tools for creating, reading, and validating VEX code
in Attribute Wrangle nodes and VEX expressions.
"""

from __future__ import annotations

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


# Map of human-readable run_over values to the attribwrangle class parm values
_RUN_OVER_MAP = {
    "Points": 0,
    "points": 0,
    "Vertices": 1,
    "vertices": 1,
    "Primitives": 2,
    "primitives": 2,
    "prims": 2,
    "Detail": 3,
    "detail": 3,
    "Numbers": 4,
    "numbers": 4,
}


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

    # Set the run_over class
    class_value = _RUN_OVER_MAP.get(run_over)
    if class_value is None:
        raise ValueError(
            f"Invalid run_over value '{run_over}'. "
            f"Must be one of: {list(set(_RUN_OVER_MAP.keys()))}"
        )

    class_parm = node.parm("class")
    if class_parm is not None:
        class_parm.set(class_value)

    return {
        "success": True,
        "node_path": node.path(),
        "node_name": node.name(),
        "run_over": run_over,
        "vex_code": vex_code,
    }


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

    return {
        "success": True,
        "node_path": node.path(),
        "vex_code": vex_code,
    }


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

    # Also get the run_over class
    run_over = None
    class_parm = node.parm("class")
    if class_parm is not None:
        class_value = class_parm.eval()
        reverse_map = {v: k for k, v in _RUN_OVER_MAP.items() if k[0].isupper()}
        run_over = reverse_map.get(class_value, str(class_value))

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
