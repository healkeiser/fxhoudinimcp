"""Geometry (SOP) handlers for FXHoudini-MCP.

Each handler reads or modifies geometry on SOP nodes.
All functions run on the main thread via the dispatcher.
"""

from __future__ import annotations

# Built-in
import collections
import contextlib
import random
from typing import Any

# Third-party
import hou

# Internal
from fxhoudinimcp_server.config import place_new_node, update_mode_warning
from fxhoudinimcp_server.dispatcher import register_handler

###### Helpers


def _get_sop_geo(node_path: str, output_index: int = 0) -> hou.Geometry:
    """Return the cooked read-only geometry for a SOP node.

    output_index picks a secondary output: a FLIP compress node or a Vellum
    solver carries different streams on outputs 1 and 2, and "no tool reports
    per-output geometry" sent a session to execute_python for them.

    Raises:
        hou.OperationFailed: if the node doesn't exist or has no geometry.
    """
    node = hou.node(node_path)
    if node is None:
        raise hou.OperationFailed(f"Node not found: {node_path}")
    geo = node.geometry(output_index) if output_index else node.geometry()
    if geo is None:
        raise hou.OperationFailed(f"Node has no geometry: {node_path}{_cook_errors(node)}")
    return geo


def _cook_errors(node: hou.Node) -> str:
    """The node's own cook errors as a sentence tail ("" when it has none).

    "Node has no geometry" is what a node whose cook failed answers, and the
    cook error (a missing file, a bad expression) was the part that said why.
    """
    errors: list = []
    with contextlib.suppress(Exception):
        errors = list(node.errors())
    return f" -- its cook failed: {'; '.join(errors)}" if errors else ""


def _vec_to_list(v: Any) -> Any:
    """Convert hou.Vector2/3/4, hou.Color, etc. to a plain list."""
    if isinstance(v, (hou.Vector2, hou.Vector3, hou.Vector4, hou.Quaternion, hou.Color)):
        return list(v)
    if isinstance(v, hou.Matrix3):
        return [[v.at(r, c) for c in range(3)] for r in range(3)]
    if isinstance(v, hou.Matrix4):
        return [[v.at(r, c) for c in range(4)] for r in range(4)]
    return v


def _attrib_meta(attrib: hou.Attrib) -> dict[str, Any]:
    """Return JSON-safe metadata for an attribute."""
    return {
        "name": attrib.name(),
        "type": attrib.dataType().name(),
        "size": attrib.size(),
        "is_array": attrib.isArrayType(),
    }


def _attrib_class_obj(geo: hou.Geometry, attrib_class: str) -> Any:
    """Map a string class name to the hou.attribType enum value."""
    mapping = {
        "point": hou.attribType.Point,
        "prim": hou.attribType.Prim,
        "vertex": hou.attribType.Vertex,
        "detail": hou.attribType.Global,
        "global": hou.attribType.Global,
    }
    cls = mapping.get(attrib_class.lower())
    if cls is None:
        raise ValueError(
            f"Invalid attrib_class: {attrib_class!r}. Use one of {list(mapping.keys())}"
        )
    return cls


###### geometry.get_geometry_info


def _loop_context(node: hou.Node) -> dict[str, str] | None:
    """The for-each block *node* sits in, as {begin, end} paths — or None.

    A node between a block_begin and its block_end cooks once per iteration.
    Read on its own, outside the loop, it is one iteration's slice at best,
    never the loop's merged result.
    """
    try:
        parent = node.parent()
        ancestors = set(node.inputAncestors())
    except Exception:
        return None
    if parent is None:
        return None
    for child in parent.children():
        try:
            if not child.type().name().startswith("block_end"):
                continue
            if node not in child.inputAncestors():
                continue
            begin = child.parm("blockpath").evalAsNode()
        except Exception:
            continue
        if begin is not None and begin in ancestors:
            return {"begin": begin.path(), "end": child.path()}
    return None


def _cook_state(node: hou.Node) -> tuple[dict[str, Any], list[str]]:
    """How the numbers about to be reported came to be — read BEFORE geometry().

    `geometry()` cooks a dirty node on the spot, so the counts are current; but
    a node inside a for-each block is then cooked standalone, outside the loop
    (no iteration metadata, one slice at best), and those numbers are not the
    loop's result. A healthy floor inside a loop read "bbox 0 at 4 points" that
    way and sent a session hunting a defect that was not there. The state says
    whether this call cooked the node and whether it sits in a loop.
    """
    state: dict[str, Any] = {}
    warnings: list[str] = []
    with contextlib.suppress(Exception):
        state["cooked_for_this_call"] = bool(node.needsToCook())
    with contextlib.suppress(Exception):
        state["cook_count"] = int(node.cookCount())
    loop = _loop_context(node)
    if loop is not None:
        state["inside_loop"] = True
        state["loop"] = loop
        warnings.append(
            f"Node sits inside for-each loop {loop['begin']} → {loop['end']}: read this "
            f"way it shows one iteration at best (the last one the block_end cooked, or "
            f"the loop's initial input), so these numbers are not the loop's result. Read {loop['end']} for "
            f"the merged output."
        )
    return state, warnings


# Packed types countPrimType also counts under PackedPrim.
_PACKED_SUBTYPES = ("Agent", "PackedGeometry", "PackedFragment")


def prim_type_counts(geo: hou.Geometry) -> dict[str, int]:
    """Exact primitive counts per type, e.g. {"Polygon": 12, "Volume": 2}.

    countPrimType runs in C++ (0.4 ms for every type on 1000 agents); the old
    per-prim walk sampled 2,500 prims and scaled the counts up. PackedPrim
    counts every packed prim, agents included, so only the packed prims no
    more specific type claims are reported under it.
    """
    counts: dict[str, int] = {}
    for name in dir(hou.primType):
        value = getattr(hou.primType, name)
        if name.startswith("_") or name == "Unknown" or not isinstance(value, hou.EnumValue):
            continue
        with contextlib.suppress(Exception):
            if count := geo.countPrimType(value):
                counts[name] = count
    if "PackedPrim" in counts:
        other = counts.pop("PackedPrim") - sum(counts.get(t, 0) for t in _PACKED_SUBTYPES)
        if other > 0:
            counts["PackedPrim"] = other
    return counts


def _get_geometry_info(*, node_path: str, output_index: int = 0, **_: Any) -> dict[str, Any]:
    """Return summary information about a SOP node's geometry."""
    node = hou.node(node_path)
    cook_state, cook_warnings = _cook_state(node) if node is not None else ({}, [])
    geo = _get_sop_geo(node_path, output_index)

    # Attribute lists per class
    attribs: dict[str, list[dict]] = {}
    for label, getter in [
        ("point", geo.pointAttribs),
        ("prim", geo.primAttribs),
        ("vertex", geo.vertexAttribs),
        ("detail", geo.globalAttribs),
    ]:
        attribs[label] = [_attrib_meta(a) for a in getter()]

    prim_types = prim_type_counts(geo)

    bbox = geo.boundingBox()

    result: dict[str, Any] = {
        "node_path": node_path,
        "num_points": geo.intrinsicValue("pointcount"),
        "num_prims": geo.intrinsicValue("primitivecount"),
        "num_vertices": geo.intrinsicValue("vertexcount"),
        "attributes": attribs,
        "bounding_box": {
            "min": list(bbox.minvec()),
            "max": list(bbox.maxvec()),
            "size": list(bbox.sizevec()),
            "center": list(bbox.center()),
        },
        "prim_type_breakdown": prim_types,
        "cook_state": cook_state,
    }
    warnings = list(cook_warnings)
    warning = update_mode_warning()
    if warning:
        warnings.append(warning)
    if warnings:
        result["warnings"] = warnings
    return result


register_handler("geometry.get_geometry_info", _get_geometry_info)


###### geometry.get_points


def _get_points(
    *,
    node_path: str,
    attributes: list[str] | None = None,
    start: int = 0,
    count: int = 200,
    group: str | None = None,
) -> dict[str, Any]:
    """Read point positions and attributes with pagination.

    Uses indexed access (geo.point) so the cost scales with the page
    size, never with the total point count.
    """
    geo = _get_sop_geo(node_path)

    if attributes is None:
        attributes = ["P"]

    if group:
        pt_group = geo.findPointGroup(group)
        if pt_group is None:
            raise hou.OperationFailed(f"Point group not found: {group}")
        total = _group_size(pt_group, "pointCount", "points")
        end = min(start + count, total)
        page = _group_page(pt_group, "iterPoints", "points", start, end)
    else:
        total = geo.intrinsicValue("pointcount")
        end = min(start + count, total)
        page = [geo.point(i) for i in range(max(start, 0), end)]

    found = {name: geo.findPointAttrib(name) is not None for name in attributes}

    rows: list[dict[str, Any]] = []
    for pt in page:
        row: dict[str, Any] = {"index": pt.number()}
        for attr_name in attributes:
            row[attr_name] = _vec_to_list(pt.attribValue(attr_name)) if found[attr_name] else None
        rows.append(row)

    return {
        "node_path": node_path,
        "total_points": total,
        "start": start,
        "count": len(rows),
        "has_more": end < total,
        "points": rows,
    }


register_handler("geometry.get_points", _get_points)


###### geometry.get_prims


def _get_prims(
    *,
    node_path: str,
    attributes: list[str] | None = None,
    start: int = 0,
    count: int = 200,
    group: str | None = None,
) -> dict[str, Any]:
    """Read primitive data and attributes with pagination."""
    geo = _get_sop_geo(node_path)

    if group:
        pr_group = geo.findPrimGroup(group)
        if pr_group is None:
            raise hou.OperationFailed(f"Prim group not found: {group}")
        total = _group_size(pr_group, "primCount", "prims")
        end = min(start + count, total)
        page = _group_page(pr_group, "iterPrims", "prims", start, end)
    else:
        # Indexed access keeps the cost proportional to the page size.
        total = geo.intrinsicValue("primitivecount")
        end = min(start + count, total)
        page = [geo.prim(i) for i in range(max(start, 0), end)]

    # If no attributes specified, gather all prim attribute names
    if attributes is None:
        attributes = [a.name() for a in geo.primAttribs()]

    rows: list[dict[str, Any]] = []
    for prim in page:
        row: dict[str, Any] = {
            "index": prim.number(),
            "type": prim.type().name(),
            "num_vertices": prim.numVertices(),
        }
        for attr_name in attributes:
            attrib = geo.findPrimAttrib(attr_name)
            if attrib is None:
                row[attr_name] = None
                continue
            val = prim.attribValue(attr_name)
            row[attr_name] = _vec_to_list(val)
        rows.append(row)

    return {
        "node_path": node_path,
        "total_prims": total,
        "start": start,
        "count": len(rows),
        "has_more": end < total,
        "prims": rows,
    }


register_handler("geometry.get_prims", _get_prims)


###### geometry.get_attrib_values


def _get_attrib_values(
    *,
    node_path: str,
    attrib_name: str,
    attrib_class: str = "point",
    start: int = 0,
    count: int = 200,
) -> dict[str, Any]:
    """Read attribute values as a flat array with pagination.

    Values are element-major (e.g. for a float3 attribute with tuple_size=3,
    every 3 consecutive values belong to one element).  Use start/count to
    page through large attributes without blowing the LLM context.
    """
    geo = _get_sop_geo(node_path)

    cls = attrib_class.lower()
    finders = {
        "point": geo.findPointAttrib,
        "prim": geo.findPrimAttrib,
        "vertex": geo.findVertexAttrib,
    }
    if cls in finders:
        attrib = finders[cls](attrib_name)
        if attrib is None:
            raise hou.OperationFailed(
                f"{cls.capitalize()} attribute '{attrib_name}' not found on {node_path}"
            )
        all_values = _attrib_array(geo, cls, attrib)
    elif cls in ("detail", "global"):
        attrib = geo.findGlobalAttrib(attrib_name)
        if attrib is None:
            raise hou.OperationFailed(f"Detail attribute '{attrib_name}' not found on {node_path}")
        val = geo.attribValue(attrib_name)
        return {
            "node_path": node_path,
            "attrib_name": attrib_name,
            "attrib_class": attrib_class,
            "size": attrib.size(),
            "type": attrib.dataType().name(),
            "value": _vec_to_list(val),
        }
    else:
        raise ValueError(f"Invalid attrib_class: {attrib_class!r}")

    tuple_size = max(attrib.size(), 1)
    total_elements = len(all_values) // tuple_size
    # Clamp page to element boundaries
    start_elem = max(0, min(start, total_elements))
    end_elem = min(start_elem + max(1, count), total_elements)
    window = all_values[start_elem * tuple_size : end_elem * tuple_size]
    page = window.tolist() if hasattr(window, "tolist") else list(window)

    return {
        "node_path": node_path,
        "attrib_name": attrib_name,
        "attrib_class": attrib_class,
        "tuple_size": tuple_size,
        "type": attrib.dataType().name(),
        "total_elements": total_elements,
        "start": start_elem,
        "count": end_elem - start_elem,
        "has_more": end_elem < total_elements,
        "values": page,
    }


def _attrib_array(geo, cls: str, attrib):
    """Every value of one attribute, flat: a numpy view for numbers.

    The tuple of Python floats this used to build is 3M objects for P on a
    1M-point mesh, made to return a 200-element page. The raw buffer costs
    one copy in C and the page is sliced out of it.
    """
    name = attrib.name()
    data = attrib.dataType()
    if data in (hou.attribData.Float, hou.attribData.Int):
        kind = "Float" if data == hou.attribData.Float else "Int"
        with contextlib.suppress(Exception):
            import numpy as np

            numeric = hou.numericData.Float32 if kind == "Float" else hou.numericData.Int32
            raw = getattr(geo, f"{cls}{kind}AttribValuesAsString")(name, numeric)
            return np.frombuffer(raw, dtype=np.float32 if kind == "Float" else np.int32)
        return getattr(geo, f"{cls}{kind}AttribValues")(name)
    return getattr(geo, f"{cls}StringAttribValues")(name)


register_handler("geometry.get_attrib_values", _get_attrib_values)


###### geometry.set_detail_attrib


def _set_detail_attrib(
    *,
    node_path: str,
    attrib_name: str,
    value: Any,
) -> dict[str, Any]:
    """Set a detail (global) attribute via an appended Attribute Create SOP.

    SOP geometry cannot be edited in place from outside a node cook
    (hou.SopNode has no setGeometry), so this wires an attribcreate node
    after *node_path* and moves the display/render flags to it.
    """
    node = hou.node(node_path)
    if node is None:
        raise hou.OperationFailed(f"Node not found: {node_path}")
    if node.geometry() is None:
        raise hou.OperationFailed(f"Node has no geometry: {node_path}")

    attrib_node = node.parent().createNode("attribcreate", f"set_{attrib_name}")
    attrib_node.setInput(0, node)
    place_new_node(attrib_node)
    attrib_node.parm("numattr").set(1)
    attrib_node.parm("class1").set("detail")
    attrib_node.parm("name1").set(attrib_name)

    if isinstance(value, str):
        attrib_node.parm("type1").set("index")
        attrib_node.parm("string1").set(value)
    elif isinstance(value, bool):
        attrib_node.parm("type1").set("int")
        attrib_node.parm("value1v1").set(int(value))
    elif isinstance(value, int):
        attrib_node.parm("type1").set("int")
        attrib_node.parm("value1v1").set(value)
    elif isinstance(value, float):
        attrib_node.parm("type1").set("float")
        attrib_node.parm("value1v1").set(value)
    elif isinstance(value, (list, tuple)) and 1 <= len(value) <= 4:
        attrib_node.parm("type1").set("float")
        attrib_node.parm("size1").set(len(value))
        for index, component in enumerate(value):
            attrib_node.parm(f"value1v{index + 1}").set(float(component))
    else:
        attrib_node.destroy()
        raise ValueError(f"Unsupported value type: {type(value).__name__}")

    attrib_node.setDisplayFlag(True)
    attrib_node.setRenderFlag(True)

    # Read the value back from the cooked geometry so the result reports
    # what actually happened rather than what was requested.
    applied = attrib_node.geometry().attribValue(attrib_name)

    return {
        "node_path": node_path,
        "attrib_node_path": attrib_node.path(),
        "attrib_name": attrib_name,
        "value": _vec_to_list(applied),
        "success": True,
    }


register_handler("geometry.set_detail_attrib", _set_detail_attrib)


###### geometry.get_groups


def _get_groups(*, node_path: str) -> dict[str, Any]:
    """List all point/prim/edge groups with membership counts."""
    geo = _get_sop_geo(node_path)

    groups: dict[str, list[dict[str, Any]]] = {
        "point_groups": [],
        "prim_groups": [],
        "edge_groups": [],
    }

    for grp in geo.pointGroups():
        groups["point_groups"].append(
            {
                "name": grp.name(),
                "count": _group_size(grp, "pointCount", "points"),
            }
        )

    for grp in geo.primGroups():
        groups["prim_groups"].append(
            {
                "name": grp.name(),
                "count": _group_size(grp, "primCount", "prims"),
            }
        )

    for grp in geo.edgeGroups():
        groups["edge_groups"].append(
            {
                "name": grp.name(),
                "count": _group_size(grp, "edgeCount", "edges"),
            }
        )

    return {
        "node_path": node_path,
        **groups,
    }


def _group_page(group, iterator: str, lister: str, start: int, end: int) -> list:
    """Members start..end of a group, walking only that far into it."""
    import itertools

    try:
        return list(itertools.islice(getattr(group, iterator)(), max(start, 0), end))
    except Exception:
        return list(getattr(group, lister)()[start:end])


def _group_size(group, counter: str, lister: str) -> int:
    """A group's member count without building its members (pointCount etc.)."""
    try:
        return int(getattr(group, counter)())
    except Exception:
        return len(getattr(group, lister)())


register_handler("geometry.get_groups", _get_groups)


###### geometry.get_group_members


def _get_group_members(
    *,
    node_path: str,
    group_name: str,
    group_type: str = "point",
    start: int = 0,
    count: int = 5000,
) -> dict[str, Any]:
    """Get element indices belonging to a group, with pagination."""
    geo = _get_sop_geo(node_path)

    gt = group_type.lower()
    if gt == "point":
        grp = geo.findPointGroup(group_name)
        if grp is None:
            raise hou.OperationFailed(f"Point group '{group_name}' not found on {node_path}")
        total = _group_size(grp, "pointCount", "points")
        end = min(start + max(1, count), total)
        page = [pt.number() for pt in _group_page(grp, "iterPoints", "points", start, end)]
    elif gt == "prim":
        grp = geo.findPrimGroup(group_name)
        if grp is None:
            raise hou.OperationFailed(f"Prim group '{group_name}' not found on {node_path}")
        total = _group_size(grp, "primCount", "prims")
        end = min(start + max(1, count), total)
        page = [pr.number() for pr in _group_page(grp, "iterPrims", "prims", start, end)]
    elif gt == "edge":
        grp = geo.findEdgeGroup(group_name)
        if grp is None:
            raise hou.OperationFailed(f"Edge group '{group_name}' not found on {node_path}")
        total = _group_size(grp, "edgeCount", "edges")
        end = min(start + max(1, count), total)
        page = [
            [points[0].number(), points[1].number()]
            for points in (edge.points() for edge in grp.edges()[start:end])
        ]
    else:
        raise ValueError(f"Invalid group_type: {group_type!r}. Use 'point', 'prim', or 'edge'.")

    return {
        "node_path": node_path,
        "group_name": group_name,
        "group_type": group_type,
        "total_count": total,
        "start": start,
        "count": len(page),
        "has_more": end < total,
        "members": page,
    }


register_handler("geometry.get_group_members", _get_group_members)


###### geometry.get_bounding_box


def _get_bounding_box(*, node_path: str) -> dict[str, Any]:
    """Get axis-aligned bounding box for a SOP node's geometry."""
    geo = _get_sop_geo(node_path)
    bbox = geo.boundingBox()

    return {
        "node_path": node_path,
        "min": list(bbox.minvec()),
        "max": list(bbox.maxvec()),
        "size": list(bbox.sizevec()),
        "center": list(bbox.center()),
    }


register_handler("geometry.get_bounding_box", _get_bounding_box)


###### geometry.get_attribute_info


def _get_attribute_info(
    *,
    node_path: str,
    attrib_name: str,
    attrib_class: str = "point",
) -> dict[str, Any]:
    """Detailed attribute info: type, size, default value."""
    geo = _get_sop_geo(node_path)

    cls = attrib_class.lower()
    finders = {
        "point": geo.findPointAttrib,
        "prim": geo.findPrimAttrib,
        "vertex": geo.findVertexAttrib,
        "detail": geo.findGlobalAttrib,
        "global": geo.findGlobalAttrib,
    }
    finder = finders.get(cls)
    if finder is None:
        raise ValueError(f"Invalid attrib_class: {attrib_class!r}")

    attrib = finder(attrib_name)
    if attrib is None:
        raise hou.OperationFailed(
            f"{attrib_class.title()} attribute '{attrib_name}' not found on {node_path}"
        )

    default = attrib.defaultValue()

    return {
        "node_path": node_path,
        "attrib_name": attrib_name,
        "attrib_class": attrib_class,
        "type": attrib.dataType().name(),
        "size": attrib.size(),
        "is_array": attrib.isArrayType(),
        "default_value": _vec_to_list(default),
        "qualifier": attrib.qualifier() if hasattr(attrib, "qualifier") else None,
        "type_name": attrib.dataType().name(),
    }


register_handler("geometry.get_attribute_info", _get_attribute_info)


###### geometry.sample_geometry


def _sample_geometry(
    *,
    node_path: str,
    sample_count: int = 100,
    seed: int = 0,
) -> dict[str, Any]:
    """Smart sampling: get N evenly distributed points from geometry."""
    geo = _get_sop_geo(node_path)

    total = geo.intrinsicValue("pointcount")

    if total == 0:
        return {
            "node_path": node_path,
            "total_points": 0,
            "sample_count": 0,
            "points": [],
        }

    # Determine indices to sample
    actual_count = min(sample_count, total)

    if actual_count >= total:
        # Return all points
        sampled_indices = list(range(total))
    else:
        # Evenly spaced sampling with optional seed for reproducibility
        rng = random.Random(seed)
        step = total / actual_count
        # Start with evenly spaced, then jitter slightly for variety
        sampled_indices = sorted(
            {
                min(int(i * step + rng.uniform(0, step * 0.5)), total - 1)
                for i in range(actual_count)
            }
        )

    # Gather attributes — indexed access keeps the cost O(sample_count)
    point_attrib_names = [a.name() for a in geo.pointAttribs()]

    rows: list[dict[str, Any]] = []
    for idx in sampled_indices:
        pt = geo.point(idx)
        row: dict[str, Any] = {"index": pt.number()}
        for attr_name in point_attrib_names:
            val = pt.attribValue(attr_name)
            row[attr_name] = _vec_to_list(val)
        rows.append(row)

    return {
        "node_path": node_path,
        "total_points": total,
        "sample_count": len(rows),
        "seed": seed,
        "attributes": point_attrib_names,
        "points": rows,
    }


register_handler("geometry.sample_geometry", _sample_geometry)


###### geometry.get_prim_intrinsics


def _intrinsic_row(prim, names: list[str] | None) -> dict[str, Any]:
    """One prim's intrinsics, all of them or just the ones asked for."""
    wanted = names if names is not None else list(prim.intrinsicNames())
    row: dict[str, Any] = {}
    for name in wanted:
        try:
            row[name] = _vec_to_list(prim.intrinsicValue(name))
        except Exception:
            row[name] = None
    return row


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _extremes(values: list[Any], rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """min/max/avg over the numeric entries, and the prim each extreme is on."""
    numbers = [v for v in values if _is_number(v)]
    if not numbers:
        return None
    low = min(numbers)
    high = max(numbers)
    return {
        "min": low,
        "max": high,
        "avg": sum(numbers) / len(numbers),
        "min_prim": rows[values.index(low)]["prim_index"],
        "max_prim": rows[values.index(high)]["prim_index"],
    }


def _intrinsic_table(
    geo: hou.Geometry,
    indices: list[int],
    names: list[str] | None,
    total_prims: int,
) -> dict[str, Any]:
    """A table of intrinsics over many prims, with extremes per column.

    Finding the packed prims whose `bounds` ran away used to cost one call
    per prim: 281 calls, about 14 s at 50 ms each.
    """
    rows: list[dict[str, Any]] = []
    for index in indices:
        prim = geo.prim(index)
        row = {"prim_index": index, "prim_type": prim.type().name()}
        row.update(_intrinsic_row(prim, names))
        rows.append(row)

    columns = names if names is not None else sorted({k for r in rows for k in r} - {"prim_index"})
    stats: dict[str, Any] = {}
    for column in columns:
        values = [r.get(column) for r in rows]
        scalar = _extremes(values, rows)
        if scalar is not None:
            stats[column] = scalar
            continue
        # A vector intrinsic (`bounds` is six floats): one min/max over whole
        # lists answers nothing, so each component gets its own extremes and
        # the prim they belong to.
        vectors = [v for v in values if isinstance(v, (list, tuple))]
        if not vectors or len({len(v) for v in vectors}) != 1:
            continue
        components: list[dict[str, Any]] = []
        for component in range(len(vectors[0])):
            column_values = [v[component] if isinstance(v, (list, tuple)) else None for v in values]
            extremes = _extremes(column_values, rows)
            if extremes is not None:
                components.append({"index": component, **extremes})
        if components:
            stats[column] = {"components": components}
    # The stats cover every row; the rows returned are the first
    # _INTRINSIC_ROWS_SHOWN plus the prims holding an extreme. 2000 full rows
    # were up to 922 KB, while the question is almost always "which prims
    # are the outliers", which the stats answer.
    extreme = set()
    for entry in stats.values():
        for item in [entry, *entry.get("components", [])]:
            extreme.update(item[key] for key in ("min_prim", "max_prim") if key in item)
    shown = [
        r for i, r in enumerate(rows) if i < _INTRINSIC_ROWS_SHOWN or r["prim_index"] in extreme
    ]
    result = {
        "total_prims": total_prims,
        "prim_count": len(rows),
        "intrinsics": names,
        "prims": shown,
        "stats": stats,
    }
    if len(shown) < len(rows):
        result["rows_shown"] = len(shown)
        result["note"] = (
            f"Stats cover all {len(rows)} prims; rows shown are the first "
            f"{_INTRINSIC_ROWS_SHOWN} and the prims holding an extreme. Ask for "
            f"prim_indices to read specific rows."
        )
    return result


_INTRINSIC_ROWS_SHOWN = 100


#: Rows one batched call returns. Beyond it the caller gets a window and is
#: told there is more, rather than a reply nobody can read.
_INTRINSIC_ROW_CAP = 2000


def _get_prim_intrinsics(
    *,
    node_path: str,
    prim_index: int | None = None,
    prim_indices: list[int] | None = None,
    prim_range: list[int] | None = None,
    intrinsics: list[str] | None = None,
) -> dict[str, Any]:
    """Get intrinsic values for primitives.

    If prim_index is None and nothing else narrows the request, return a
    summary across all primitives. With prim_index, return the intrinsics of
    that one primitive.

    prim_indices or prim_range read many prims in one call and answer with a
    table (`prims`) plus `stats`: min/max/avg per intrinsic and the prim each
    extreme belongs to. `intrinsics` narrows the columns; given alone, it
    sweeps every prim for those intrinsics.
    """
    geo = _get_sop_geo(node_path)
    total_prims = geo.intrinsicValue("primitivecount")
    names = [str(n) for n in intrinsics] if intrinsics else None

    indices: list[int] | None = None
    if prim_indices is not None or prim_range is not None:
        if prim_indices is not None and prim_range is not None:
            raise hou.OperationFailed("Pass prim_indices or prim_range, not both.")
        if prim_range is not None:
            if len(prim_range) != 2:
                raise hou.OperationFailed("prim_range must be [start, end] (end inclusive).")
            start, end = int(prim_range[0]), int(prim_range[1])
            # Refuse before building the list: [0, 10**9] would allocate
            # a billion ints on Houdini's main thread just to reject them.
            if start < 0 or end >= total_prims or start > end:
                raise hou.OperationFailed(
                    f"prim_range {[start, end]} out of range "
                    f"(0..{total_prims - 1}, start <= end) on {node_path}"
                )
            indices = list(range(start, end + 1))
        else:
            indices = [int(i) for i in prim_indices]
        out_of_range = [i for i in indices if i < 0 or i >= total_prims]
        if out_of_range:
            raise hou.OperationFailed(
                f"Prim index/indices {out_of_range[:10]} out of range "
                f"(0..{total_prims - 1}) on {node_path}"
            )
    elif names and prim_index is None:
        # One or two intrinsics across every prim.
        indices = list(range(total_prims))

    if indices is not None:
        table = _intrinsic_table(geo, indices[:_INTRINSIC_ROW_CAP], names, total_prims)
        table["node_path"] = node_path
        if len(indices) > _INTRINSIC_ROW_CAP:
            table["truncated"] = True
            table["requested_count"] = len(indices)
        return table

    if prim_index is not None:
        if prim_index < 0 or prim_index >= total_prims:
            raise hou.OperationFailed(
                f"Prim index {prim_index} out of range (0..{total_prims - 1}) on {node_path}"
            )
        prim = geo.prim(prim_index)
        return {
            "node_path": node_path,
            "prim_index": prim_index,
            "prim_type": prim.type().name(),
            "intrinsics": _intrinsic_row(prim, names),
        }

    # Summary mode: aggregate intrinsics across (a sample of) the prims.
    # Reading every intrinsic of every prim is O(names * prims) HOM calls
    # — 14+ seconds on a 250k-prim mesh — so cap the statistics sample.
    if total_prims == 0:
        return {
            "node_path": node_path,
            "total_prims": 0,
            "summary": {},
        }

    _SUMMARY_SAMPLE_LIMIT = 1_000
    if total_prims <= _SUMMARY_SAMPLE_LIMIT:
        sample_prims = [geo.prim(i) for i in range(total_prims)]
        sample_note = None
    else:
        step = total_prims / _SUMMARY_SAMPLE_LIMIT
        sample_prims = [geo.prim(int(i * step)) for i in range(_SUMMARY_SAMPLE_LIMIT)]
        sample_note = f"statistics sampled from {_SUMMARY_SAMPLE_LIMIT}/{total_prims} prims"

    sample_prim = sample_prims[0]
    intrinsic_names = sample_prim.intrinsicNames()

    summary: dict[str, Any] = {}
    for name in intrinsic_names:
        try:
            first_val = sample_prim.intrinsicValue(name)
            if isinstance(first_val, (int, float)):
                # Compute min/max/avg for numeric intrinsics
                vals = [p.intrinsicValue(name) for p in sample_prims]
                summary[name] = {
                    "min": min(vals),
                    "max": max(vals),
                    "avg": sum(vals) / len(vals),
                    "sample": first_val,
                }
            elif isinstance(first_val, str):
                # Collect unique string values
                unique = set()
                for p in sample_prims:
                    unique.add(p.intrinsicValue(name))
                    if len(unique) > 20:
                        break
                summary[name] = {
                    "unique_values": sorted(unique)[:20],
                    "sample": first_val,
                }
            else:
                summary[name] = {
                    "sample": _vec_to_list(first_val),
                }
        except Exception:
            summary[name] = {"sample": None, "error": "Could not read"}

    result = {
        "node_path": node_path,
        "total_prims": total_prims,
        "intrinsic_names": list(intrinsic_names),
        "summary": summary,
    }
    if sample_note:
        result["summary_note"] = sample_note
    return result


register_handler("geometry.get_prim_intrinsics", _get_prim_intrinsics)


###### geometry.find_nearest_point


def _find_nearest_point(
    *,
    node_path: str,
    position: list[float],
    max_results: int = 1,
) -> dict[str, Any]:
    """Find nearest point(s) to a given position."""
    geo = _get_sop_geo(node_path)

    if len(position) != 3:
        raise ValueError("position must be a list of 3 floats [x, y, z]")

    total = geo.intrinsicValue("pointcount")
    if total == 0:
        return {
            "node_path": node_path,
            "position": position,
            "results": [],
        }

    k = max(max_results, 1)
    flat = geo.pointFloatAttribValues("P")

    try:
        import numpy as np

        coords = np.array(flat, dtype=np.float64).reshape(-1, 3)
        squared = ((coords - np.array(position)) ** 2).sum(axis=1)
        if k >= len(squared):
            top_indices = np.argsort(squared)
        else:
            top_indices = np.argpartition(squared, k)[:k]
            top_indices = top_indices[np.argsort(squared[top_indices])]
        top = [(float(squared[i]) ** 0.5, int(i)) for i in top_indices[:k]]
    except ImportError:
        px, py, pz = position
        distances: list[tuple[float, int]] = []
        for i in range(total):
            dx = flat[i * 3] - px
            dy = flat[i * 3 + 1] - py
            dz = flat[i * 3 + 2] - pz
            distances.append((dx * dx + dy * dy + dz * dz, i))
        distances.sort(key=lambda x: x[0])
        top = [(d**0.5, i) for d, i in distances[:k]]

    results: list[dict[str, Any]] = []
    for dist, idx in top:
        results.append(
            {
                "index": idx,
                "position": list(flat[idx * 3 : idx * 3 + 3]),
                "distance": dist,
            }
        )

    return {
        "node_path": node_path,
        "query_position": position,
        "max_results": max_results,
        "results": results,
    }


register_handler("geometry.find_nearest_point", _find_nearest_point)


###### geometry.get_attrib_stats


_STATS_ATTRIB_CAP = 12


def _numeric_components(values: Any) -> list[float]:
    """Flatten a scalar, vector or tuple attribute value to floats."""
    if isinstance(values, (int, float)):
        return [float(values)]
    try:
        return [float(v) for v in values]
    except (TypeError, ValueError):
        return []


def _element_count(geo: hou.Geometry, cls: str, element_getter: Any) -> int:
    """Points, prims or vertices in *geo*, from intrinsics when they answer."""
    intrinsic = {"point": "pointcount", "prim": "primitivecount", "vertex": "vertexcount"}[cls]
    with contextlib.suppress(Exception):
        count = geo.intrinsicValue(intrinsic)
        if isinstance(count, int):
            return count
    return len(element_getter())


def _get_attrib_stats(
    *,
    node_path: str | None = None,
    attribs: list[str] | str | None = None,
    attrib_class: str = "point",
    frames: list | None = None,
    node_paths: list[str] | None = None,
    percentiles: list | None = None,
    group: str | None = None,
    unique: bool = False,
    distance_to: str | None = None,
) -> dict[str, Any]:
    """The statistics below, for one node now, or for several nodes over several frames.

    Counting particles at a handful of frames across several variants of a
    setup took a set_frame plus a get_attrib_stats per node per frame, by the
    hundred, or a loop in execute_python. *frames* and *node_paths* make
    it one call: a row per node per frame, frames visited in increasing order
    (a simulation cooks forward), and the current frame put back afterwards. A
    node that fails is a row with its error, not a failed call. *percentiles*
    (e.g. [5, 50, 95]) adds the distribution a median or a framing needs.
    *group* narrows the elements to a group pattern (`grp`, `@id>=0`, `0-99`),
    *unique* counts distinct values of integer and string attributes, and
    *distance_to* measures each point's distance to another SOP's surface. An
    attribute name written "age/life" is the ratio of two attributes.
    """
    if node_path is not None and node_paths:
        # node_paths used to win and node_path was dropped without a word.
        raise ValueError("Pass either node_path or node_paths, not both.")
    nodes = list(node_paths or ([] if node_path is None else [node_path]))
    if not nodes:
        raise ValueError("Pass node_path, or node_paths for several nodes.")
    quantiles = _check_percentiles(percentiles)
    # node_paths always answers rows, even with one entry: a caller looping
    # over variants should not get a different shape when only one is left.
    # The narrowing options are passed only when asked for.
    narrowing = {
        key: value
        for key, value in (("group", group), ("unique", unique), ("distance_to", distance_to))
        if value
    }
    if frames is None and node_paths is None:
        return _attrib_stats_once(nodes[0], attribs, attrib_class, quantiles, **narrowing)
    wanted_frames = sorted({float(f) for f in frames}) if frames else [hou.frame()]
    current = hou.frame()
    rows: list[dict[str, Any]] = []
    try:
        for frame in wanted_frames:
            hou.setFrame(frame)
            for path in nodes:
                try:
                    row = _attrib_stats_once(path, attribs, attrib_class, quantiles, **narrowing)
                except Exception as exc:
                    row = {"node_path": path, "error": str(exc)}
                row["frame"] = frame
                rows.append(row)
    finally:
        hou.setFrame(current)
    return {
        "attrib_class": attrib_class,
        "frames": wanted_frames,
        "node_paths": nodes,
        "rows": rows,
        "frame_restored": current,
    }


def _check_percentiles(percentiles: list | None) -> list[float] | None:
    if percentiles is None:
        return None
    values = [float(p) for p in percentiles]
    if not values or any(p < 0 or p > 100 for p in values):
        raise ValueError(f"percentiles must be numbers in 0..100, got {percentiles!r}")
    return values


def _python_percentile(values: list[float], q: float) -> float:
    """Linear-interpolated percentile, numpy's default method."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 100.0
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _attrib_stats_once(
    node_path: str,
    attribs: list[str] | str | None,
    attrib_class: str,
    percentiles: list[float] | None = None,
    group: str | None = None,
    unique: bool = False,
    distance_to: str | None = None,
) -> dict[str, Any]:
    """Aggregate statistics for numeric attributes: min, max, mean, sum.

    get_geometry_info names the attributes and get_attrib_values returns every
    value, which on a 62k-point cache is unusable in a conversation. Proving a
    simulation is doing something needs the aggregate, not the values, and that
    is otherwise only reachable through execute_python.
    """
    geo = _get_sop_geo(node_path)

    cls = attrib_class.lower()
    listers = {
        "point": (geo.pointAttribs, geo.points),
        "prim": (geo.primAttribs, geo.prims),
        # uv and N usually live on vertices, and the UV range is what decides a
        # texture's tiling multiplier.
        "vertex": (geo.vertexAttribs, lambda: [v for prim in geo.prims() for v in prim.vertices()]),
        "detail": (geo.globalAttribs, None),
        "global": (geo.globalAttribs, None),
    }
    if cls not in listers:
        raise ValueError(f"Invalid attrib_class: {attrib_class!r}")
    lister, element_getter = listers[cls]

    if isinstance(attribs, str):
        attribs = [attribs]
    available = {a.name(): a for a in lister()}
    wanted = attribs or sorted(available)
    # "age/life": how far through its life each particle is has no attribute
    # of its own. A name with a slash that is not an attribute is a ratio.
    ratios = [name for name in wanted if "/" in name and name not in available]
    wanted = [name for name in wanted if name not in ratios]

    missing = [name for name in wanted if name not in available]
    wanted = [name for name in wanted if name in available][:_STATS_ATTRIB_CAP]

    if cls in ("detail", "global"):
        if group or distance_to or ratios:
            # Refused rather than dropped: there is one detail element.
            raise ValueError(
                "group, distance_to and attribute ratios apply to point and prim "
                "statistics, not detail"
            )
        # A detail attribute is a single value, so "statistics" is the value.
        stats = {name: {"value": _vec_to_list(geo.attribValue(available[name]))} for name in wanted}
        return {
            "node_path": node_path,
            "attrib_class": attrib_class,
            "element_count": 1,
            "stats": stats,
            "missing": missing,
        }

    if element_getter is None:
        raise ValueError(
            f"attrib_class {attrib_class!r} has no per-element statistics; "
            "use point, prim, vertex or detail"
        )

    # Element numbers in the group, or None for all: counting only the
    # particles, without a collider's points merged into the same geometry.
    rows = _group_rows(geo, cls, group)

    elements = None  # built only when a fast path is missing: vertices are costly
    stats: dict[str, Any] = {}
    for name in wanted:
        attrib = available[name]
        if attrib.isArrayType():
            stats[name] = {"skipped": "not numeric"}
            continue
        if attrib.dataType() == hou.attribData.String:
            stats[name] = (
                _string_counts(geo, cls, name, rows, attrib.size())
                if unique
                else {"skipped": "not numeric"}
            )
            continue
        size = attrib.size()
        kind = "Int" if attrib.dataType() == hou.attribData.Int else "Float"
        fast = _numpy_stats(geo, cls, kind, name, size, percentiles, rows, unique)
        if fast is not None:
            stats[name] = fast
            continue
        # attribValues() is a single C++ call for the whole array, where a Python
        # loop over 62k elements would be thousands of times slower.
        try:
            flat = list(getattr(geo, f"{cls}{kind}AttribValues")(name))
        except (AttributeError, hou.OperationFailed):
            flat = None
        if flat is None:
            if elements is None:
                elements = element_getter()
            flat = []
            for element in elements:
                flat.extend(_numeric_components(element.attribValue(attrib)))
        if rows is not None:
            width = max(size, 1)
            flat = [v for row in rows for v in flat[row * width : (row + 1) * width]]
        if not flat:
            stats[name] = {"count": 0}
            continue
        entry: dict[str, Any] = {
            "count": len(flat) // max(size, 1),
            "size": size,
            "min": min(flat),
            "max": max(flat),
            "sum": sum(flat),
            "mean": sum(flat) / len(flat),
        }
        if size > 1:
            # Per-component ranges, because a velocity field's interesting number
            # is usually the per-axis extreme rather than the flattened one.
            entry["per_component"] = [
                {
                    "min": min(flat[i::size]),
                    "max": max(flat[i::size]),
                    "mean": sum(flat[i::size]) / len(flat[i::size]),
                }
                for i in range(size)
            ]
        if percentiles:
            columns = [flat[i::size] for i in range(size)]
            entry["percentiles"] = {
                f"{q:g}": (
                    _python_percentile(columns[0], q)
                    if size == 1
                    else [_python_percentile(column, q) for column in columns]
                )
                for q in percentiles
            }
        if unique and kind == "Int" and size == 1:
            entry.update(_value_counts(flat))
        stats[name] = entry

    result = {
        "node_path": node_path,
        "attrib_class": attrib_class,
        "element_count": (_element_count(geo, cls, element_getter) if rows is None else len(rows)),
        "stats": stats,
        "missing": missing,
        "truncated": bool(attribs is None and len(available) > _STATS_ATTRIB_CAP),
    }
    if rows is not None:
        result["group"] = group
    for ratio in ratios:
        stats[ratio] = _ratio_stats(geo, cls, available, ratio, rows, percentiles)
    if cls == "prim" and unique:
        # A trail's length is its vertex count; there is no attribute for it.
        # Asked for only: it walks every primitive in Python.
        result["vertices_per_prim"] = _vertices_per_prim(geo, rows)
    if distance_to:
        result["distance_to"] = _distance_stats(geo, cls, distance_to, rows, percentiles)
    return result


def _group_rows(geo, cls: str, group: str | None) -> list[int] | None:
    """Numbers of the *cls* elements in the group pattern *group*, or None for all."""
    if not group:
        return None
    if cls not in ("point", "prim"):
        raise ValueError(f"group applies to point and prim statistics, not {cls!r}")
    try:
        found = geo.globPoints(group) if cls == "point" else geo.globPrims(group)
    except hou.OperationFailed:
        # HOM says only "Invalid pattern", also for a group that does not exist.
        raise ValueError(f"no {cls} group, or an invalid pattern: {group!r}") from None
    return sorted(element.number() for element in found)


def _value_counts(values: list, cap: int = 10) -> dict[str, Any]:
    """How many distinct values, and the most frequent ones with their counts."""
    counts = collections.Counter(values)
    return {
        "unique_count": len(counts),
        "most_common": [[value, count] for value, count in counts.most_common(cap)],
    }


def _string_counts(
    geo, cls: str, name: str, rows: list[int] | None, size: int = 1
) -> dict[str, Any]:
    """count / unique_count / most_common of a string attribute, a tuple per element."""
    values = list(getattr(geo, f"{cls}StringAttribValues")(name))
    if size > 1:
        # HOM flattens the tuples: ('a0', 'b', 'a1', 'b') for two elements.
        values = [tuple(values[i : i + size]) for i in range(0, len(values), size)]
    if rows is not None:
        values = [values[row] for row in rows]
    return {"count": len(values), **_value_counts(values)}


_VERTICES_PER_PRIM_CAP = 200_000


def _vertices_per_prim(geo, rows: list[int] | None) -> dict[str, Any]:
    """Distribution of vertex counts per primitive (a trail's length)."""
    # ponytail: a Python walk, ~8 s per 1M prims measured on 22.0; no HOM bulk
    # accessor found. Capped so a big mesh's `unique` does not time out.
    total = len(rows) if rows is not None else geo.intrinsicValue("primitivecount")
    if total > _VERTICES_PER_PRIM_CAP:
        return {"skipped": f"{total} prims; counted up to {_VERTICES_PER_PRIM_CAP}"}
    prims = geo.prims()
    counts = (
        [prims[row].numVertices() for row in rows]
        if rows is not None
        else [prim.numVertices() for prim in prims]
    )
    if not counts:
        return {"count": 0}
    return {
        "min": min(counts),
        "max": max(counts),
        "mean": sum(counts) / len(counts),
        **_value_counts(counts),
    }


def _list_stats(values: list[float], percentiles: list[float] | None) -> dict[str, Any]:
    """count / min / max / mean (and percentiles) of plain numbers."""
    if not values:
        return {"count": 0}
    entry: dict[str, Any] = {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / len(values),
    }
    if percentiles:
        entry["percentiles"] = {f"{q:g}": _python_percentile(values, q) for q in percentiles}
    return entry


def _ratio_stats(
    geo, cls: str, available: dict, ratio: str, rows: list[int] | None, percentiles
) -> dict[str, Any]:
    """Statistics of one attribute divided by another, element by element.

    An element whose denominator is zero is counted in `zero_denominator`,
    not used. A missing or non-scalar attribute is an `error` in the entry,
    not a failed call.
    """
    names = [part.strip() for part in ratio.split("/", 1)]
    columns = []
    for name in names:
        attrib = available.get(name)
        if attrib is None:
            return {"error": f"no {cls} attribute '{name}'"}
        if attrib.isArrayType() or attrib.dataType() == hou.attribData.String or attrib.size() != 1:
            return {"error": f"'{name}' is not a single number per element"}
        kind = "Int" if attrib.dataType() == hou.attribData.Int else "Float"
        column = list(getattr(geo, f"{cls}{kind}AttribValues")(name))
        columns.append([column[row] for row in rows] if rows is not None else column)
    numerators, denominators = columns
    values = [n / d for n, d in zip(numerators, denominators, strict=True) if d != 0]
    entry = {"ratio_of": names, **_list_stats(values, percentiles)}
    if len(values) < len(numerators):
        entry["zero_denominator"] = len(numerators) - len(values)
    return entry


def _distance_stats(
    geo, cls: str, target_path: str, rows: list[int] | None, percentiles
) -> dict[str, Any]:
    """How far each point is from another SOP's surface: crawling, hovering, sticking.

    nearestPrim in a Python loop costs about 4 ms a point. The Ray SOP's
    Minimum Distance runs as a verb on a copy in memory instead (20 000
    points in 8 ms on 22.0.429, the same distances); the scene is not
    touched and no node is created.
    """
    if cls != "point":
        raise ValueError(f"distance_to measures points, not {cls!r} elements")
    target = _get_sop_geo(target_path)
    if not target.prims():
        raise ValueError(f"'{target_path}' has no primitives to measure the distance to")
    verb = hou.sopNodeTypeCategory().nodeVerb("ray")
    parms = verb.parms()
    parms.update({"method": 0, "dotrans": 0, "putdist": 1})  # Minimum Distance, points stay
    verb.setParms(parms)
    work = hou.Geometry()
    work.merge(geo)
    verb.execute(work, [work.freeze(), target])
    distances = list(work.pointFloatAttribValues("dist"))
    if rows is not None:
        distances = [distances[row] for row in rows]
    return {"target": target_path, **_list_stats(distances, percentiles)}


def _numpy_stats(
    geo,
    cls: str,
    kind: str,
    name: str,
    size: int,
    percentiles: list[float] | None = None,
    rows: list[int] | None = None,
    unique: bool = False,
) -> dict[str, Any] | None:
    """min/max/sum/mean (and per component) from the raw buffer, or None.

    The list-of-floats path built one Python float per component and walked
    it several times: 645 ms for P on a 1M-point grid, paid again on every
    frame of cook_frame_range. The buffer goes straight into numpy instead.
    """
    try:
        import numpy as np

        if kind == "Int":
            raw = getattr(geo, f"{cls}IntAttribValuesAsString")(name, hou.numericData.Int32)
            values = np.frombuffer(raw, dtype=np.int32)
        else:
            raw = getattr(geo, f"{cls}FloatAttribValuesAsString")(name, hou.numericData.Float32)
            values = np.frombuffer(raw, dtype=np.float32)
    except Exception:
        return None
    size = max(size, 1)
    table = values.reshape(-1, size)
    if rows is not None:
        table = table[np.asarray(rows, dtype=np.int64)]
    if table.size == 0:
        return {"count": 0}
    counted = None
    if unique and kind == "Int" and size == 1:
        # sourceptnum, id: how many distinct, and which come up most.
        found, counts = np.unique(table[:, 0], return_counts=True)
        order = np.argsort(-counts, kind="stable")[:10]
        counted = {
            "unique_count": int(found.size),
            "most_common": [[int(found[i]), int(counts[i])] for i in order],
        }
    table = table.astype(np.float64)
    cast = int if kind == "Int" else float
    entry: dict[str, Any] = {
        "count": int(table.shape[0]),
        "size": size,
        "min": cast(table.min()),
        "max": cast(table.max()),
        "sum": float(table.sum()),
        "mean": float(table.mean()),
    }
    if size > 1:
        # Per-component ranges, because a velocity field's interesting number
        # is usually the per-axis extreme rather than the flattened one.
        entry["per_component"] = [
            {"min": cast(lo), "max": cast(hi), "mean": float(mean)}
            for lo, hi, mean in zip(table.min(0), table.max(0), table.mean(0), strict=False)
        ]
    if percentiles:
        found = np.percentile(table, percentiles, axis=0)
        entry["percentiles"] = {
            f"{q:g}": float(row[0]) if size == 1 else [float(v) for v in row]
            for q, row in zip(percentiles, found, strict=True)
        }
    if counted is not None:
        entry.update(counted)
    return entry


register_handler("geometry.get_attrib_stats", _get_attrib_stats)


###### geometry.get_volume_info


# Volume statistics come from intrinsics, which is the only route that works for
# both types: hou.VDB has activeVoxelCount() but no minValue()/maxValue(), and
# hou.Volume has neither. The intrinsics below are present on both.
#
# NEVER read the "voxeldata" intrinsic here: it returns every voxel value, so on
# a real sim field it is millions of floats through the bridge. The whole point
# of this handler is to answer the question without moving the data.
_VOLUME_INTRINSICS = (
    ("min_value", "volumeminvalue"),
    ("max_value", "volumemaxvalue"),
    ("mean_value", "volumeavgvalue"),
    ("active_voxels", "activevoxelcount"),
    ("voxel_size", "voxelsize"),
)


def _volume_entry(prim: Any) -> dict[str, Any]:
    """Name, resolution, voxel counts and value range for one volume prim."""
    entry: dict[str, Any] = {"prim_number": prim.number(), "kind": type(prim).__name__}
    with contextlib.suppress(Exception):
        entry["name"] = prim.attribValue("name")
    with contextlib.suppress(Exception):
        entry["resolution"] = list(prim.resolution())

    available = set()
    with contextlib.suppress(Exception):
        available = set(prim.intrinsicNames())
    for key, intrinsic in _VOLUME_INTRINSICS:
        if intrinsic not in available:
            continue
        with contextlib.suppress(Exception):
            value = prim.intrinsicValue(intrinsic)
            entry[key] = list(value) if isinstance(value, tuple) else value

    # A dense volume has no active-voxel concept, so report the grid total under
    # its own name rather than pretending the two numbers mean the same thing.
    if "active_voxels" not in entry and entry.get("resolution"):
        res = entry["resolution"]
        entry["total_voxels"] = res[0] * res[1] * res[2]

    with contextlib.suppress(Exception):
        bbox = prim.boundingBox()
        entry["bbox_min"] = list(bbox.minvec())
        entry["bbox_max"] = list(bbox.maxvec())
    return entry


def _volume_prims(geo: hou.Geometry) -> list:
    """Volume and VDB primitives of ``geo``, in primitive order."""
    # primsOfType, not a walk over geo.prims(): that built a Python object per
    # prim to find none, 983 ms on a 1M-prim mesh, and cook_frame_range asked
    # on every frame.
    try:
        return sorted(
            list(geo.primsOfType(hou.primType.Volume)) + list(geo.primsOfType(hou.primType.VDB)),
            key=lambda prim: prim.number(),
        )
    except Exception:
        return [
            prim
            for prim in geo.prims()
            if isinstance(prim, (hou.Volume, hou.VDB)) or type(prim).__name__ in ("Volume", "VDB")
        ]


def _volume_name(prim: Any) -> str:
    try:
        return prim.attribValue("name") or ""
    except Exception:
        return ""


def _named_volume(geo: hou.Geometry, name: str, node_path: str) -> Any:
    """The first volume called ``name``, or an error listing the names there are."""
    prims = _volume_prims(geo)
    for prim in prims:
        if _volume_name(prim) == name:
            return prim
    have = sorted({_volume_name(prim) for prim in prims} - {""})
    raise ValueError(
        f"No volume named '{name}' on {node_path}. It has: {', '.join(have) or 'no named volumes'}."
    )


# The voxel statistics, sampling and field comparison below are adapted from
# JTCHE/houdini-mcp (MIT, Copyright (c) 2025 Capoom, (c) 2026 John Chedeville);
# see NOTICE.

# Past this many voxels a read is refused rather than stalling the session:
# a VDB comes back as a Python tuple, about 180 ms per 8M voxels.
_MAX_VOXELS_READ = 64_000_000


def _voxel_array(prim: Any):
    """A volume's voxels as a float numpy array indexed [z, y, x], and its index origin.

    A VDB gives only its active region, and its bounding box maxvec is
    exclusive, so the shape is max - min (a box from 5 to 16 holds 11 voxels
    per axis, checked on Houdini 22.0).
    """
    import numpy as np

    if isinstance(prim, hou.VDB) or type(prim).__name__ == "VDB":
        box = prim.activeVoxelBoundingBox()
        low, high = box.minvec(), box.maxvec()
        shape = [int(round(high[axis] - low[axis])) for axis in range(3)]
        origin = [int(round(low[axis])) for axis in range(3)]
        count = shape[0] * shape[1] * shape[2]
        if count <= 0:
            return np.zeros((0, 0, 0)), origin
        if count > _MAX_VOXELS_READ:
            raise ValueError(
                f"{count} active voxels is more than the {_MAX_VOXELS_READ} this reads. "
                "Call get_volume_info without threshold/bins for the intrinsics."
            )
        values = np.asarray(prim.voxelRangeAsFloat(box), dtype=np.float64)
    else:
        shape = list(prim.resolution())
        origin = [0, 0, 0]
        if shape[0] * shape[1] * shape[2] > _MAX_VOXELS_READ:
            raise ValueError(
                f"A {shape} grid is more than the {_MAX_VOXELS_READ} voxels this reads. "
                "Call get_volume_info without threshold/bins for the intrinsics."
            )
        # The byte string is about 6x faster than allVoxels() on an 8M grid.
        values = np.frombuffer(prim.allVoxelsAsString(), dtype=np.float32).astype(np.float64)
    if values.size != shape[0] * shape[1] * shape[2]:
        raise ValueError(
            f"Houdini gave {values.size} voxels for a {shape} region, so the array has no "
            "shape. Use sample_volume to read it at positions."
        )
    return values.reshape(shape[2], shape[1], shape[0]), origin


_PERCENTILES = (1, 5, 25, 50, 75, 95, 99)


def _edges(bins: Any):
    """A bin count, or a list of edges the caller chose (SDF bands, say)."""
    return [float(edge) for edge in bins] if isinstance(bins, (list, tuple)) else int(bins)


def _value_summary(values, bins: Any = 0, threshold: float | None = None) -> dict[str, Any]:
    """Count, extremes, mean, sum, percentiles; on request a histogram and a threshold split."""
    import numpy as np

    values = np.asarray(values, dtype=np.float64).ravel()
    if not values.size:
        return {"count": 0}
    report: dict[str, Any] = {
        "count": int(values.size),
        "min": float(values.min()),
        "max": float(values.max()),
        "mean": float(values.mean()),
        "sum": float(values.sum()),
        "percentiles": {
            str(share): float(value)
            for share, value in zip(_PERCENTILES, np.percentile(values, _PERCENTILES), strict=True)
        },
    }
    if bins:
        counts, edges = np.histogram(values, bins=_edges(bins))
        report["histogram"] = [
            {"from": float(edges[i]), "to": float(edges[i + 1]), "count": int(n)}
            for i, n in enumerate(counts)
        ]
    if threshold is not None:
        above = int((values > threshold).sum())
        report["threshold"] = {
            "value": threshold,
            "above": above,
            "at_or_below": int(values.size) - above,
            "share_above": round(above / values.size, 4),
        }
    return report


def _box_above(prim: Any, array, origin: list[int], threshold: float) -> dict[str, Any] | None:
    """World box of the voxels over ``threshold``: where the smoke is, not where the grid is."""
    import numpy as np

    found = np.argwhere(array > threshold)
    if not len(found):
        return None
    corners = []
    for corner in (found.min(axis=0), found.max(axis=0)):
        z, y, x = (int(value) for value in corner)
        corners.append(list(prim.indexToPos((x + origin[0], y + origin[1], z + origin[2]))))
    return {
        "min": [min(a, b) for a, b in zip(*corners, strict=True)],
        "max": [max(a, b) for a, b in zip(*corners, strict=True)],
        "note": "Voxel centres; widen by half a voxel for the cell edges.",
    }


def _get_volume_info(
    *,
    node_path: str,
    max_volumes: int = 24,
    threshold: float | None = None,
    bins: Any = 0,
) -> dict[str, Any]:
    """Per-volume names, resolution, active voxels and value ranges.

    get_geometry_info reports a primitive count, which cannot distinguish a
    correctly named non-empty density field from an empty one. get_cop_vdb
    covers Copernicus; this is the SOP side of the same question.

    Without threshold or bins only intrinsics are read. With either, the voxels
    are read once per volume for percentiles, a histogram, the split at the
    threshold and the world box of the voxels over it.
    """
    geo = _get_sop_geo(node_path)
    volumes = _volume_prims(geo)
    shown = volumes[:max_volumes]
    entries = []
    for prim in shown:
        entry = _volume_entry(prim)
        voxels = entry.get("active_voxels", entry.get("total_voxels"))
        if "mean_value" in entry and voxels is not None:
            # Free: the mean intrinsic is sum / voxels. On a VDB both count
            # active voxels only, which for fog is the whole field.
            entry["sum"] = entry["mean_value"] * voxels
        if threshold is not None or bins:
            array, origin = _voxel_array(prim)
            entry["voxel_stats"] = _value_summary(array, bins, threshold)
            if threshold is not None and array.size:
                entry["box_above_threshold"] = _box_above(prim, array, origin, threshold)
        entries.append(entry)
    return {
        "node_path": node_path,
        "volume_count": len(volumes),
        "volumes": entries,
        "truncated": len(volumes) > len(shown),
    }


register_handler("geometry.get_volume_info", _get_volume_info)


###### geometry.sample_volume


def _points_at(positions: list) -> hou.Geometry:
    points = hou.Geometry()
    points.createPoints([hou.Vector3(*position) for position in positions])
    return points


def _read_fields_at(geo: hou.Geometry, fields: list[str], points: hou.Geometry) -> dict:
    """Each field's value at each point, sampled in compiled code by the attribfromvolume verb."""
    import numpy as np

    verb = hou.sopNodeTypeCategory().nodeVerb("attribfromvolume")
    found = {}
    for field in fields:
        verb.setParms({"field": field, "name": "__mcp_sample", "type": 0, "size": 1})
        result = hou.Geometry()
        verb.execute(result, [points, geo])
        found[field] = np.asarray(result.pointFloatAttribValues("__mcp_sample"), dtype=np.float64)
    return found


def _sample_volume(
    *,
    node_path: str,
    fields: list[str],
    positions: list | None = None,
    from_node: str | None = None,
    limit: int = 1000,
    bins: Any = 0,
    threshold: float | None = None,
) -> dict[str, Any]:
    """Named volumes read at world positions, or at another node's points."""
    geo = _get_sop_geo(node_path)
    for field in fields:
        _named_volume(geo, field, node_path)
    if from_node:
        points = _get_sop_geo(from_node)
    elif positions:
        points = _points_at(positions)
    else:
        raise ValueError(
            "Give positions ([[x, y, z], ...]) or from_node (a SOP whose points to read at)."
        )
    read = _read_fields_at(geo, fields, points)
    count = len(next(iter(read.values()))) if read else 0
    report: dict[str, Any] = {
        "node_path": node_path,
        "positions": count,
        "summary": {
            field: _value_summary(values, bins, threshold) for field, values in read.items()
        },
    }
    if count <= limit:
        report["values"] = {field: values.tolist() for field, values in read.items()}
    else:
        report["note"] = f"{count} positions: summary only. Raise limit for the values."
    return report


register_handler("geometry.sample_volume", _sample_volume)


###### geometry.compare_volumes


def _grid_positions(prim: Any, most: int = 30000) -> list:
    """Voxel-centred world positions over a volume's box, coarsened until under ``most``."""
    box = prim.boundingBox()
    size, low = box.sizevec(), box.minvec()
    voxel = prim.intrinsicValue("voxelsize")
    step = float(min(voxel)) if isinstance(voxel, (tuple, list)) else float(voxel)
    if step <= 0:
        step = max(size) / 32 or 1.0
    while (size[0] / step) * (size[1] / step) * (size[2] / step) > most:
        step *= 2
    counts = [max(1, int(size[axis] / step)) for axis in range(3)]
    return [
        [low[0] + (i + 0.5) * step, low[1] + (j + 0.5) * step, low[2] + (k + 0.5) * step]
        for i in range(counts[0])
        for j in range(counts[1])
        for k in range(counts[2])
    ]


def _compare_volumes(
    *,
    node_path: str,
    field: str,
    against: str,
    against_node: str | None = None,
    bands: Any = 10,
) -> dict[str, Any]:
    """How much of ``field`` sits where ``against`` is in each band.

    "How much density is inside the collider", with the collider an SDF, is
    bands=[-1e9, 0, 1e9] and the total in the first band. Both fields are
    sampled in world space on a grid over the first one's box, so a Volume and
    a VDB compare the same way.
    """
    import numpy as np

    geo = _get_sop_geo(node_path)
    prim = _named_volume(geo, field, node_path)
    other = _get_sop_geo(against_node) if against_node else geo
    _named_volume(other, against, against_node or node_path)

    points = _points_at(_grid_positions(prim))
    here = _read_fields_at(geo, [field], points)[field]
    there = _read_fields_at(other, [against], points)[against]
    if not here.size:
        return {"node_path": node_path, "field": field, "against": against, "samples": 0}
    counts, edges = np.histogram(there, bins=_edges(bands))
    totals, _ = np.histogram(there, bins=edges, weights=here)
    return {
        "node_path": node_path,
        "field": field,
        "against": against,
        "samples": int(here.size),
        "field_total": float(here.sum()),
        "bands": [
            {
                "from": float(edges[i]),
                "to": float(edges[i + 1]),
                "samples": int(counts[i]),
                "field_total": float(totals[i]),
            }
            for i in range(len(counts))
        ],
        "note": "Totals sum sampled values, not integrals: compare bands, not absolute amounts.",
    }


register_handler("geometry.compare_volumes", _compare_volumes)
