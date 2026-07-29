"""Graph intelligence handlers for FXHoudini-MCP.

Senior-artist tooling: atomic network building with upfront validation,
whole-network verification, version-exact node documentation, and cook
profiling. These are the commands that let a client plan a whole graph,
prove the plan against the running Houdini before mutating anything,
and then look at the evidence afterwards.
"""

from __future__ import annotations

# Built-in
import contextlib
import json
import os
import tempfile
import zipfile
from difflib import get_close_matches
from typing import Any

# Third-party
import hou

# Internal
from fxhoudinimcp_server.config import layout_if_enabled
from fxhoudinimcp_server.dispatcher import register_handler

###### Helpers


def _resolve_node_type(category: hou.NodeTypeCategory, type_name: str):
    """Resolve *type_name* in *category* the way createNode would.

    hou.preferredNodeType maps an unversioned name to the version that
    createNode actually instantiates (e.g. copytopoints -> ::2.0).
    """
    with contextlib.suppress(Exception):
        preferred = hou.preferredNodeType(f"{category.name()}/{type_name}")
        if preferred is not None:
            return preferred
    types = category.nodeTypes()
    if type_name in types:
        return types[type_name]
    prefix = type_name + "::"
    versioned = sorted(key for key in types if key.startswith(prefix))
    if versioned:
        return types[versioned[-1]]
    return None


def _parm_names_for_type(scratch: hou.Node, node_type) -> tuple[set, set]:
    """Instantiate a type once to learn its parm and parmTuple names."""
    probe = scratch.createNode(node_type.name())
    parm_names = {p.name() for p in probe.parms()}
    tuple_names = {pt.name() for pt in probe.parmTuples()}
    probe.destroy()
    return parm_names, tuple_names


def _apply_parm(node: hou.Node, name: str, value: Any) -> None:
    """Set a parm or parm tuple, broadcasting scalars and coercing floats."""
    parm = node.parm(name)
    parm_tuple = node.parmTuple(name)
    if isinstance(value, (list, tuple)):
        if parm_tuple is None:
            raise ValueError(f"'{name}' is not a parm tuple")
        if len(value) != len(parm_tuple):
            raise ValueError(f"'{name}' has {len(parm_tuple)} components, got {len(value)}")
        if all(isinstance(v, (int, float)) for v in value):
            parm_tuple.set([float(v) for v in value])
        else:
            parm_tuple.set(list(value))
    elif parm is not None:
        parm.set(value)
    elif parm_tuple is not None:
        # Scalar onto a tuple: broadcast across components.
        if isinstance(value, (int, float)):
            parm_tuple.set([float(value)] * len(parm_tuple))
        else:
            parm_tuple.set([value] * len(parm_tuple))
    else:
        raise ValueError(f"parameter '{name}' not found")


def _node_report(node: hou.Node) -> dict[str, Any]:
    report: dict[str, Any] = {
        "name": node.name(),
        "path": node.path(),
        "type": node.type().name(),
        "errors": list(node.errors()),
        "warnings": list(node.warnings()),
    }
    with contextlib.suppress(Exception):
        report["bypassed"] = node.isBypassed()
    return report


def _geometry_summary(node: hou.Node) -> dict[str, Any] | None:
    """Compact cooked-geometry evidence for a SOP node."""
    if not hasattr(node, "geometry"):
        return None
    try:
        geo = node.geometry()
    except Exception:
        return None
    if geo is None:
        return None
    bbox = geo.boundingBox()
    return {
        "points": geo.intrinsicValue("pointcount"),
        "prims": geo.intrinsicValue("primitivecount"),
        "bbox_min": list(bbox.minvec()),
        "bbox_max": list(bbox.maxvec()),
        "point_attribs": [a.name() for a in geo.pointAttribs()][:30],
    }


###### graph.build_network


def build_network(
    parent_path: str,
    nodes: list,
    dry_run: bool = False,
    layout: bool = True,
    **_: Any,
) -> dict:
    """Build a whole node network atomically, with upfront validation.

    Every node type, parameter name, and input reference in the spec is
    validated against the running Houdini BEFORE anything is created —
    invalid specs return the full error list and mutate nothing. With
    dry_run=True only the validation runs.

    Args:
        parent_path: Network to build inside (e.g. "/obj/geo1").
        nodes: Node specs, each a dict:
            type (str, required): node type name (unversioned ok).
            name (str): node name, referenceable by later specs.
            parms (dict): parameter values; lists set whole parm tuples.
            inputs (list): wiring. Entries are either a source string
                (wired positionally) or {"index", "source",
                "source_output"}. Sources resolve to spec node names
                first, then children of parent, then absolute paths.
            flags (dict): display/render/bypass/template booleans.
            color (list[3]) and comment (str): network annotations.
        dry_run: Validate only; never mutates the scene.
        layout: Lay out the parent network afterwards (respects the
            FXHOUDINIMCP_AUTO_LAYOUT toggle).
    """
    parent = hou.node(parent_path)
    errors: list[str] = []
    if parent is None:
        return {"valid": False, "errors": [f"Parent not found: {parent_path}"]}
    category = parent.childTypeCategory()
    if category is None:
        return {
            "valid": False,
            "errors": [f"{parent_path} cannot contain child nodes"],
        }

    if not isinstance(nodes, list) or not nodes:
        return {"valid": False, "errors": ["'nodes' must be a non-empty list"]}

    ###### Phase 1: validate everything before touching the scene

    spec_names: list[str] = []
    existing = {child.name() for child in parent.children()}
    resolved_types: dict[str, Any] = {}

    for index, spec in enumerate(nodes):
        label = spec.get("name") or spec.get("type") or f"#{index}"
        type_name = spec.get("type")
        if not type_name:
            errors.append(f"node {label}: missing 'type'")
            continue
        if type_name not in resolved_types:
            node_type = _resolve_node_type(category, type_name)
            if node_type is None:
                close = get_close_matches(type_name, list(category.nodeTypes()), n=3, cutoff=0.5)
                hint = f" Did you mean: {close}?" if close else ""
                errors.append(
                    f"node {label}: type '{type_name}' does not exist in {category.name()}.{hint}"
                )
                continue
            resolved_types[type_name] = node_type
        name = spec.get("name")
        if name:
            if name in spec_names:
                errors.append(f"duplicate node name in spec: '{name}'")
            if name in existing:
                errors.append(f"node '{name}' already exists under {parent_path}")
            spec_names.append(name)

    # Learn parameter names by instantiating each unique type once (probe
    # nodes are destroyed immediately; display/render flags restored), so
    # bad parm names fail validation, not the build. Runs even when other
    # errors exist: report everything in one pass.
    parm_knowledge: dict[str, tuple[set, set]] = {}
    if resolved_types:
        display_before = parent.displayNode() if hasattr(parent, "displayNode") else None
        render_before = parent.renderNode() if hasattr(parent, "renderNode") else None
        try:
            for type_name, node_type in resolved_types.items():
                parm_knowledge[type_name] = _parm_names_for_type(parent, node_type)
        finally:
            with contextlib.suppress(Exception):
                if display_before is not None:
                    display_before.setDisplayFlag(True)
                if render_before is not None:
                    render_before.setRenderFlag(True)

    for index, spec in enumerate(nodes):
        label = spec.get("name") or spec.get("type") or f"#{index}"
        knowledge = parm_knowledge.get(spec.get("type"))
        if knowledge:
            parm_names, tuple_names = knowledge
            for parm_name in spec.get("parms") or {}:
                if parm_name not in parm_names and parm_name not in tuple_names:
                    close = get_close_matches(
                        parm_name,
                        sorted(parm_names | tuple_names),
                        n=3,
                        cutoff=0.5,
                    )
                    hint = f" Did you mean: {close}?" if close else ""
                    errors.append(
                        f"node {label}: parm '{parm_name}' does not exist "
                        f"on {spec.get('type')}.{hint}"
                    )
        node_type = resolved_types.get(spec.get("type"))
        max_inputs = node_type.maxNumInputs() if node_type else 0
        for input_index, entry in enumerate(spec.get("inputs") or []):
            if isinstance(entry, dict):
                source = entry.get("source")
                input_index = int(entry.get("index", input_index))
            else:
                source = entry
            if input_index >= max_inputs > 0:
                errors.append(
                    f"node {label}: input {input_index} exceeds max inputs "
                    f"({max_inputs}) of {spec.get('type')}"
                )
            if (
                source not in spec_names
                and source not in existing
                and hou.node(str(source)) is None
            ):
                errors.append(
                    f"node {label}: input source '{source}' is not a spec "
                    f"node, a child of {parent_path}, or an absolute path"
                )

    if errors:
        return {"valid": False, "errors": errors, "created": []}
    if dry_run:
        return {
            "valid": True,
            "dry_run": True,
            "validated_nodes": len(nodes),
            "validated_types": sorted(t.name() for t in resolved_types.values()),
        }

    ###### Phase 2: build (atomic — any failure rolls back)

    created: dict[str, hou.Node] = {}
    try:
        for spec in nodes:
            node = parent.createNode(resolved_types[spec["type"]].name(), spec.get("name"))
            created[spec.get("name") or node.name()] = node

        for spec, node in zip(nodes, created.values(), strict=False):
            for parm_name, value in (spec.get("parms") or {}).items():
                try:
                    _apply_parm(node, parm_name, value)
                except Exception as exc:
                    raise RuntimeError(f"{node.path()} parm '{parm_name}': {exc}") from exc
            for input_index, entry in enumerate(spec.get("inputs") or []):
                if isinstance(entry, dict):
                    source_name = entry.get("source")
                    input_index = int(entry.get("index", input_index))
                    source_output = int(entry.get("source_output", 0))
                else:
                    source_name, source_output = entry, 0
                source = (
                    created.get(source_name)
                    or parent.node(str(source_name))
                    or hou.node(str(source_name))
                )
                node.setInput(input_index, source, source_output)
            flags = spec.get("flags") or {}
            for flag, setter in (
                ("display", "setDisplayFlag"),
                ("render", "setRenderFlag"),
                ("bypass", "bypass"),
                ("template", "setTemplateFlag"),
            ):
                if flag in flags and hasattr(node, setter):
                    getattr(node, setter)(bool(flags[flag]))
            if spec.get("color"):
                node.setColor(hou.Color(tuple(spec["color"])))
            if spec.get("comment"):
                node.setComment(spec["comment"])
                node.setGenericFlag(hou.nodeFlag.DisplayComment, True)
    except Exception as exc:
        for node in created.values():
            with contextlib.suppress(Exception):
                node.destroy()
        return {
            "valid": False,
            "errors": [f"build failed and was rolled back: {exc}"],
            "created": [],
        }

    if layout:
        layout_if_enabled(parent)

    ###### Phase 3: verify — cook and report evidence

    display = parent.displayNode() if hasattr(parent, "displayNode") else None
    if display is None:
        display = list(created.values())[-1]
    with contextlib.suppress(hou.OperationFailed):
        display.cook(force=False)

    reports = [_node_report(node) for node in created.values()]
    error_nodes = [r["path"] for r in reports if r["errors"]]
    return {
        "valid": True,
        "created": reports,
        "display_node": display.path() if display is not None else None,
        "geometry": _geometry_summary(display),
        "error_nodes": error_nodes,
        "node_count": len(reports),
    }


###### graph.verify_network


def verify_network(parent_path: str, **_: Any) -> dict:
    """Inspect every node in a network: the 'middle-click everything' pass.

    Cooks the display node, then reports per-node errors/warnings/flags
    plus cooked-geometry evidence, so claims about a build can be checked
    against reality in one call.
    """
    parent = hou.node(parent_path)
    if parent is None:
        raise ValueError(f"Network not found: {parent_path}")

    display = parent.displayNode() if hasattr(parent, "displayNode") else None
    if display is not None:
        with contextlib.suppress(hou.OperationFailed):
            display.cook(force=False)

    reports = []
    for child in parent.children():
        report = _node_report(child)
        report["display"] = child.isDisplayFlagSet() if hasattr(child, "isDisplayFlagSet") else None
        reports.append(report)

    error_nodes = [r["path"] for r in reports if r["errors"]]
    return {
        "parent_path": parent_path,
        "node_count": len(reports),
        "display_node": display.path() if display is not None else None,
        "geometry": _geometry_summary(display) if display is not None else None,
        "error_nodes": error_nodes,
        "healthy": not error_nodes,
        "nodes": reports,
    }


###### graph.get_node_card

_HELP_ZIP_INDEX: dict[str, str] | None = None

_CATEGORY_HELP_DIRS = {
    "Sop": ["sop"],
    "Object": ["obj"],
    "Driver": ["out"],
    "Dop": ["dop"],
    "Lop": ["lop"],
    "Cop": ["copernicus", "cop"],
    "Cop2": ["cop2"],
    "Chop": ["chop"],
    "Top": ["top"],
    "Vop": ["vex", "vop"],
}


def _help_text(node_type, category_name: str) -> str | None:
    """Houdini's own help for a node type, version-exact, headless-safe."""
    global _HELP_ZIP_INDEX
    # hou.text.expandString, not the deprecated hou.expandString.
    zip_path = os.path.join(hou.text.expandString("$HFS"), "houdini", "help", "nodes.zip")
    if _HELP_ZIP_INDEX is None:
        _HELP_ZIP_INDEX = {}
        if os.path.isfile(zip_path):
            with zipfile.ZipFile(zip_path) as zf:
                _HELP_ZIP_INDEX = {name.lower(): name for name in zf.namelist()}

    # "copytopoints::2.0" -> base "copytopoints" (version stripped);
    # "kinefx::rigpose" -> base "rigpose" (namespace stripped). Help files
    # are stored unversioned (old versions get a trailing dash).
    parts = node_type.name().split("::")
    base = parts[-1]
    if len(parts) > 1 and parts[-1][:1].isdigit():
        base = parts[-2]
    candidates = []
    for help_dir in _CATEGORY_HELP_DIRS.get(category_name, [category_name.lower()]):
        candidates += [
            f"{help_dir}/{base}.txt",
            f"{help_dir}/{base}-.txt",
        ]
    for candidate in candidates:
        actual = _HELP_ZIP_INDEX.get(candidate.lower())
        if actual:
            with zipfile.ZipFile(zip_path) as zf:
                return zf.read(actual).decode("utf-8", "replace")

    embedded = node_type.embeddedHelp()
    return embedded or None


def get_node_card(
    node_type: str,
    context: str = "Sop",
    parm_filter: str = None,
    include_help: bool = True,
    **_: Any,
) -> dict:
    """Version-exact documentation card for a node type.

    Sources everything from the running Houdini: real connector labels,
    real parameter names/defaults/menus, and the node's own shipped help
    text — so there is never a reason to guess.
    """
    categories = hou.nodeTypeCategories()
    category = categories.get(context)
    if category is None:
        raise ValueError(f"Unknown context '{context}'. Available: {sorted(categories.keys())}")
    resolved = _resolve_node_type(category, node_type)
    if resolved is None:
        close = get_close_matches(node_type, list(category.nodeTypes()), n=5, cutoff=0.4)
        raise ValueError(f"Node type '{node_type}' not found in {context}. Close matches: {close}")

    parms: list[dict[str, Any]] = []
    _PARM_CAP = 80
    truncated = False
    for template in resolved.parmTemplateGroup().entriesWithoutFolders():
        if template.isHidden():
            continue
        name, label = template.name(), template.label()
        if (
            parm_filter
            and parm_filter.lower() not in name.lower()
            and parm_filter.lower() not in label.lower()
        ):
            continue
        if len(parms) >= _PARM_CAP:
            truncated = True
            break
        entry: dict[str, Any] = {
            "name": name,
            "label": label,
            "type": template.type().name(),
            "size": template.numComponents(),
        }
        with contextlib.suppress(Exception):
            entry["default"] = list(template.defaultValue())
        try:
            items = template.menuItems()
            if items:
                entry["menu"] = list(items)[:15]
        except Exception:
            pass
        parms.append(entry)

    help_text = _help_text(resolved, context) if include_help else None
    if help_text and len(help_text) > 5000:
        help_text = help_text[:5000] + "\n[... help truncated]"

    return {
        "type": resolved.name(),
        "label": resolved.description(),
        "context": context,
        "min_inputs": resolved.minNumInputs(),
        "max_inputs": resolved.maxNumInputs(),
        "max_outputs": resolved.maxNumOutputs(),
        "is_generator": resolved.minNumInputs() == 0,
        "parm_count": len(parms),
        "parms_truncated": truncated,
        "parms": parms,
        "help": help_text,
    }


###### graph.find_expensive_nodes


def find_expensive_nodes(
    root_path: str = "/",
    frame: float = None,
    limit: int = 15,
    **_: Any,
) -> dict:
    """Profile cooking under *root_path* and rank nodes by cook cost.

    Records a hou.perfMon profile while force-cooking the display SOPs
    under the root, then returns the most expensive nodes — how a senior
    finds the slow node instead of guessing.
    """
    root = hou.node(root_path)
    if root is None:
        raise ValueError(f"Node not found: {root_path}")

    if frame is not None:
        hou.setFrame(frame)

    # Collect containers whose children we will force-cook. cook(force)
    # only re-cooks the node itself — cached upstream results record as
    # zero — so every node must be cooked individually inside the profile.
    containers: list[hou.Node] = []
    if hasattr(root, "displayNode") and root.displayNode() is not None:
        containers.append(root)
    else:
        for child in root.allSubChildren():
            if hasattr(child, "displayNode") and child.displayNode() is not None:
                containers.append(child)
            if len(containers) >= 25:
                break

    targets: list[hou.Node] = []
    _NODE_CAP = 300
    for container in containers:
        for child in container.children():
            targets.append(child)
            if len(targets) >= _NODE_CAP:
                break
        if len(targets) >= _NODE_CAP:
            break

    profile = hou.perfMon.startProfile("fxhoudinimcp_expensive_nodes")
    try:
        for target in targets:
            with contextlib.suppress(hou.OperationFailed, AttributeError):
                target.cook(force=True)
    finally:
        profile.stop()

    out = os.path.join(tempfile.mkdtemp(), "profile.hperf")
    profile.save(out)
    with open(out, encoding="utf-8") as fh:
        data = json.load(fh)

    rows: list[tuple[float, str]] = []

    def _walk(entry: dict, path_parts: list[str]) -> None:
        name = entry.get("name", "")
        is_real_node = (
            bool(name)
            and not name.startswith("{")
            and name
            not in (
                "Total Statistics",
                "Other",
                "Nodes",
            )
        )
        parts = path_parts + [name] if is_real_node else path_parts
        cook_ms = 0.0
        for frame_block in (entry.get("stats") or {}).values():
            for sub in frame_block.values():
                cook_ms += sub.get("Cook", 0.0)
        if is_real_node and cook_ms >= 0.5:
            rows.append((cook_ms, "/" + "/".join(parts)))
        for child in entry.get("children") or []:
            _walk(child, parts)

    _walk(data.get("stats", {}), [])
    rows.sort(reverse=True)

    return {
        "root_path": root_path,
        "cooked_nodes": len(targets),
        "top_nodes": [{"path": path, "cook_ms": round(ms, 2)} for ms, path in rows[:limit]],
        "note": (
            "cook_ms is cumulative (parents include children); compare "
            "siblings to find the real hotspot"
        ),
    }


###### Registration

register_handler("graph.build_network", build_network)
register_handler("graph.verify_network", verify_network)
register_handler("graph.get_node_card", get_node_card)
register_handler("graph.find_expensive_nodes", find_expensive_nodes)
