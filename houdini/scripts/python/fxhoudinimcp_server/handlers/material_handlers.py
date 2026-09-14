"""Materials & Shaders handlers for FXHoudini-MCP.

Provides tools for listing, inspecting, creating, and assigning
materials and shader networks within Houdini.
"""

from __future__ import annotations

# Built-in
from typing import Any

# Third-party
import hou

# Internal
from fxhoudinimcp_server.config import layout_if_enabled, place_new_node
from fxhoudinimcp_server.dispatcher import register_handler
from fxhoudinimcp_server.errors import as_text, readable_message

###### Helpers


def _get_node(node_path: str) -> hou.Node:
    """Resolve a node path and raise a clear error if it does not exist."""
    node = hou.node(node_path)
    if node is None:
        raise ValueError(f"Node not found: {node_path}")
    return node


def _focus_network_editor(node: hou.Node) -> None:
    """Best-effort: layout the parent network, then pan the editor to *node*."""
    try:
        parent = node.parent()
        if parent is not None:
            layout_if_enabled(parent)
        for pane_tab in hou.ui.paneTabs():
            if pane_tab.type() == hou.paneTabType.NetworkEditor:
                if parent is not None:
                    pane_tab.cd(parent.path())
                pane_tab.setCurrentNode(node)
                pane_tab.homeToSelection()
                return
    except Exception:
        pass


_MATERIAL_PARM_HINTS = ("materialpath", "matspecpath", "matpath", "shop_material")
_ASSIGNMENT_ROOTS = ("/obj", "/stage")
_material_parm_cache: dict[str, list[str]] = {}


def _material_parm_templates(node_type: hou.NodeType) -> list[str]:
    """String parameter names of *node_type* that hold a material path.

    Cached per type: the scene has thousands of nodes but a few dozen types.
    Multiparm instances keep their "#" (shop_materialpath#) and are expanded
    per node.
    """
    key = node_type.nameWithCategory()
    cached = _material_parm_cache.get(key)
    if cached is not None:
        return cached
    names: list[str] = []

    def walk(templates) -> None:
        for template in templates:
            if template.type() == hou.parmTemplateType.Folder:
                walk(template.parmTemplates())
                continue
            if template.type() != hou.parmTemplateType.String:
                continue
            lowered = template.name().lower()
            if any(hint in lowered for hint in _MATERIAL_PARM_HINTS):
                names.append(template.name())

    try:
        walk(node_type.parmTemplateGroup().entries())
    except Exception:
        names = []
    _material_parm_cache[key] = names
    return names


def _find_material_assignments(mat_path: str) -> tuple[list[str], int]:
    """Paths of nodes whose material-path parameters name *mat_path*.

    Reads only parameters whose name says "material path", on node types that
    have one. The previous sweep evaluated EVERY parameter of EVERY node under
    /obj: an expression such as npoints("../scatter") cooks its node when
    evaluated, and 40 of them on a 4,160-node scene cost 27 s per call --
    minutes on a production set. Returns (hits, nodes scanned).
    """
    hits: list[str] = []
    scanned = 0
    for root_path in _ASSIGNMENT_ROOTS:
        root = hou.node(root_path)
        if root is None:
            continue
        for child in root.allSubChildren():
            scanned += 1
            names = _material_parm_templates(child.type())
            if not names:
                continue
            found = False
            for name in names:
                if "#" in name:
                    prefix = name.split("#", 1)[0]
                    candidates = [
                        p
                        for p in child.parms()
                        if p.name().startswith(prefix) and p.name()[len(prefix) :].isdigit()
                    ]
                else:
                    parm = child.parm(name)
                    candidates = [parm] if parm is not None else []
                for parm in candidates:
                    try:
                        value = parm.evalAsString()
                    except Exception:
                        continue
                    if mat_path in value:
                        found = True
                        break
                if found:
                    break
            if found:
                hits.append(child.path())
    return hits, scanned


def _material_summary(node: hou.Node) -> dict[str, Any]:
    """Return a compact summary dict for a material node."""
    return {
        "path": node.path(),
        "type": node.type().name(),
        "label": node.type().description(),
        "param_count": len(node.parms()),
    }


###### materials.list_materials


def _list_materials(*, root_path: str = "/mat", **_: Any) -> dict[str, Any]:
    """List all material nodes under the given root path.

    Walks children of the specified root (typically /mat) and also
    checks /stage if it exists, collecting material node summaries.

    Args:
        root_path: Root path to search for materials (default: "/mat").
    """
    # The requested root must exist. The loop below tolerates a missing node so
    # that the /stage it adds on its own can be absent, but applying that tolerance
    # to the caller's own argument meant a misspelled root_path came back
    # {"count": 0, "materials": []} -- indistinguishable from a scene with no
    # materials, and the caller goes looking for why its shaders vanished.
    if hou.node(root_path) is None:
        raise ValueError(
            f"Root path not found: {root_path}. Materials usually live under /mat, "
            f"or under a material library LOP in /stage."
        )

    materials: list[dict[str, Any]] = []
    search_paths = [root_path]

    # Also search /stage if it exists and is not already the root
    if root_path != "/stage" and hou.node("/stage") is not None:
        search_paths.append("/stage")

    for search_path in search_paths:
        root = hou.node(search_path)
        if root is None:
            continue

        for node in root.allSubChildren():
            type_name = node.type().name()
            category = node.type().category().name()

            # Match material-like node types
            if (
                category == "Vop"
                or "material" in type_name.lower()
                or "shader" in type_name.lower()
                or type_name
                in (
                    "principledshader::2.0",
                    "principledshader",
                    "mtlxstandard_surface",
                    "materialbuilder",
                )
            ):
                materials.append(_material_summary(node))

    return {
        "count": len(materials),
        "materials": materials,
    }


register_handler("materials.list_materials", _list_materials)


###### materials.get_material_info


def _get_material_info(*, node_path: str, **_: Any) -> dict[str, Any]:
    """Get detailed information about a material node.

    Returns the material's type, all non-default parameters, shader VOP
    nodes inside (if it's a material builder), and geometry nodes that
    reference this material.

    Args:
        node_path: Absolute path to the material node.
    """
    node = _get_node(node_path)

    # Gather non-default parameters
    params: dict[str, Any] = {}
    for parm in node.parms():
        try:
            val = parm.eval()
            default = parm.parmTemplate().defaultValue()
            if isinstance(default, tuple) and len(default) == 1:
                default = default[0]
            if val != default:
                params[parm.name()] = val
        except Exception:
            pass

    # List shader VOP nodes inside (if this is a material builder)
    shaders: list[dict[str, str]] = []
    try:
        for child in node.children():
            if child.type().category().name() == "Vop":
                shaders.append(
                    {
                        "name": child.name(),
                        "path": child.path(),
                        "type": child.type().name(),
                    }
                )
    except Exception:
        pass

    # Nodes that reference this material: material-path parameters only, on
    # the node types that have one (see _find_material_assignments).
    try:
        assignments, scanned = _find_material_assignments(node.path())
    except Exception:
        assignments, scanned = [], 0

    return {
        "path": node.path(),
        "type": node.type().name(),
        "params": params,
        "shaders": shaders,
        "assignments": assignments,
        "assignment_scan": {"nodes": scanned, "roots": list(_ASSIGNMENT_ROOTS)},
    }


register_handler("materials.get_material_info", _get_material_info)


###### materials.create_material_network


# The documented create_material_network keys, per shader node type. Only
# metalness happens to share its name with the mtlxstandard_surface parameter;
# base_color and roughness were dropped on the floor, silently (#39).
_SHADER_PARM_ALIASES: dict[str, dict[str, str]] = {
    "mtlxstandard_surface": {"roughness": "specular_roughness"},
    "principledshader::2.0": {
        "base_color": "basecolor",
        "roughness": "rough",
        "metalness": "metallic",
        "opacity": "opac",
    },
}


def _apply_shader_params(
    node: hou.Node, shader_type: str, params: dict[str, Any]
) -> tuple[dict[str, str], dict[str, str]]:
    """Set *params* on a shader node; a list sets the parm tuple of that name.

    Returns (applied, skipped): applied maps each key to the parameter it
    landed on, skipped maps each key that landed nowhere to the reason, so a
    caller sees a dropped key instead of a default value.
    """
    aliases = _SHADER_PARM_ALIASES.get(shader_type, {})
    applied: dict[str, str] = {}
    skipped: dict[str, str] = {}
    for key, value in params.items():
        name = aliases.get(key, key)
        target = node.parmTuple(name) if isinstance(value, (list, tuple)) else node.parm(name)
        if target is None:
            skipped[key] = f"no parameter '{name}' on {shader_type}"
            continue
        try:
            target.set(value)
        except Exception as exc:  # noqa: BLE001 - report, do not abort the material
            skipped[key] = readable_message(exc)
            continue
        applied[key] = name
    return applied, skipped


def _create_material_network(
    *,
    name: str,
    shader_type: str = "principled",
    params: dict[str, Any] | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Create a new material network in /mat.

    Creates a material node of the specified shader type and optionally
    sets parameter values from the provided dict.

    Args:
        name: Name for the new material node.
        shader_type: Type of shader to create. "principled" creates a
            principledshader::2.0; "materialx" creates mtlxstandard_surface.
        params: Optional dict of parameter name -> value to set.
    """
    mat_context = hou.node("/mat")
    if mat_context is None:
        # Create /mat if it doesn't exist
        mat_context = hou.node("/").createNode("matnet", "mat")

    # Map shader_type to actual Houdini node type
    type_map = {
        "principled": "principledshader::2.0",
        "materialx": "mtlxstandard_surface",
    }
    actual_type = type_map.get(shader_type, shader_type)

    try:
        node = mat_context.createNode(actual_type, node_name=name)
    except hou.OperationFailed as e:
        raise ValueError(
            f"Failed to create material of type '{actual_type}' in /mat: {readable_message(e)}"
        ) from e

    applied, skipped = _apply_shader_params(node, actual_type, params or {})

    place_new_node(node)
    _focus_network_editor(node)

    return {
        "material_path": node.path(),
        "shader_type": actual_type,
        "applied": applied,
        "skipped": skipped,
    }


register_handler("materials.create_material_network", _create_material_network)


###### materials.assign_material


def _assign_material(
    *,
    geo_path: str,
    material_path: str,
    **_: Any,
) -> dict[str, Any]:
    """Assign a material to a geometry node.

    Finds the SOP network inside the geo node, creates a material SOP
    after the last displayed node, sets the material path, and sets
    the display flag on the new material SOP.

    Args:
        geo_path: Path to the geometry (Object-level) node.
        material_path: Path to the material node to assign.
    """
    geo_node = _get_node(geo_path)

    # Find the SOP network inside the geo node
    # Look for the display node (the one with the display flag set)
    display_node = None
    sop_children = geo_node.children()

    for child in sop_children:
        try:
            if child.isDisplayFlagSet():
                display_node = child
                break
        except Exception:
            continue

    if display_node is None and sop_children:
        display_node = sop_children[-1]

    # Create a material SOP
    mat_sop = geo_node.createNode("material", node_name="assign_material")

    # Connect to the display node
    if display_node is not None:
        mat_sop.setInput(0, display_node)

    # Set the material path
    mat_parm = mat_sop.parm("shop_materialpath1")
    if mat_parm is not None:
        mat_parm.set(material_path)

    # Set display flag on the new material SOP
    mat_sop.setDisplayFlag(True)
    mat_sop.setRenderFlag(True)
    place_new_node(mat_sop)
    _focus_network_editor(mat_sop)

    return {
        "material_sop_path": mat_sop.path(),
    }


register_handler("materials.assign_material", _assign_material)


###### materials.list_material_types


def _list_material_types(
    *,
    filter: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    """List available VOP/material node types.

    Inspects the Vop and Shop node type categories to find available
    material and shader types. Optionally filters by a substring.

    Args:
        filter: Optional substring to filter type names by.
    """
    results: list[dict[str, str]] = []

    categories_to_search = ["Vop", "Shop"]
    all_categories = hou.nodeTypeCategories()

    for cat_name in categories_to_search:
        category = all_categories.get(cat_name)
        if category is None:
            continue

        types_dict = category.nodeTypes()
        for type_name, node_type in sorted(types_dict.items()):
            # Skip hidden types
            try:
                if node_type.hidden():
                    continue
            except Exception:
                pass

            label = node_type.description()

            # Apply filter if provided
            filter_lower = as_text(filter, "filter").lower()
            if filter_lower and (
                filter_lower not in type_name.lower() and filter_lower not in label.lower()
            ):
                continue

            results.append(
                {
                    "name": type_name,
                    "label": label,
                    "category": cat_name,
                }
            )

    return {
        "count": len(results),
        "types": results,
    }


register_handler("materials.list_material_types", _list_material_types)
