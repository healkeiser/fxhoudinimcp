"""Geometry (SOP) handlers for FXHoudini-MCP.

Each handler reads or modifies geometry on SOP nodes.
All functions run on the main thread via the dispatcher.
"""

from __future__ import annotations

# Built-in
import math
import random
from typing import Any

# Third-party
import hou

# Internal
from fxhoudinimcp_server.dispatcher import register_handler


###### Helpers

def _get_sop_geo(node_path: str) -> hou.Geometry:
    """Return the cooked read-only geometry for a SOP node.

    Raises:
        hou.OperationFailed: if the node doesn't exist or has no geometry.
    """
    node = hou.node(node_path)
    if node is None:
        raise hou.OperationFailed(f"Node not found: {node_path}")
    geo = node.geometry()
    if geo is None:
        raise hou.OperationFailed(f"Node has no geometry: {node_path}")
    return geo


def _vec_to_list(v: Any) -> Any:
    """Convert hou.Vector2/3/4, hou.Color, etc. to a plain list."""
    if isinstance(v, (hou.Vector2, hou.Vector3, hou.Vector4,
                       hou.Quaternion, hou.Color)):
        return list(v)
    if isinstance(v, hou.Matrix3):
        return [list(v.at(r, c) for c in range(3)) for r in range(3)]
    if isinstance(v, hou.Matrix4):
        return [list(v.at(r, c) for c in range(4)) for r in range(4)]
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
        raise ValueError(f"Invalid attrib_class: {attrib_class!r}. "
                         f"Use one of {list(mapping.keys())}")
    return cls


###### geometry.get_geometry_info

def _get_geometry_info(*, node_path: str) -> dict[str, Any]:
    """Return summary information about a SOP node's geometry."""
    geo = _get_sop_geo(node_path)

    # Attribute lists per class
    attribs: dict[str, list[dict]] = {}
    for label, getter in [
        ("point", geo.pointAttribs),
        ("prim", geo.primAttribs),
        ("vertex", geo.vertexAttribs),
        ("detail", geo.globalAttribs),
    ]:
        attribs[label] = [_attrib_meta(a) for a in getter()]

    # Prim type breakdown
    prim_types: dict[str, int] = {}
    for prim in geo.prims():
        t = prim.type().name()
        prim_types[t] = prim_types.get(t, 0) + 1

    bbox = geo.boundingBox()

    return {
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
    }

register_handler("geometry.get_geometry_info", _get_geometry_info)


###### geometry.get_points

def _get_points(
    *,
    node_path: str,
    attributes: list[str] | None = None,
    start: int = 0,
    count: int = 1000,
    group: str | None = None,
) -> dict[str, Any]:
    """Read point positions and attributes with pagination."""
    geo = _get_sop_geo(node_path)

    if attributes is None:
        attributes = ["P"]

    if group:
        pt_group = geo.findPointGroup(group)
        if pt_group is None:
            raise hou.OperationFailed(f"Point group not found: {group}")
        points = pt_group.points()
    else:
        points = geo.points()

    total = len(points)
    end = min(start + count, total)
    page = points[start:end]

    rows: list[dict[str, Any]] = []
    for pt in page:
        row: dict[str, Any] = {"index": pt.number()}
        for attr_name in attributes:
            attrib = geo.findPointAttrib(attr_name)
            if attrib is None:
                row[attr_name] = None
                continue
            val = pt.attribValue(attr_name)
            row[attr_name] = _vec_to_list(val)
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
    count: int = 1000,
    group: str | None = None,
) -> dict[str, Any]:
    """Read primitive data and attributes with pagination."""
    geo = _get_sop_geo(node_path)

    if group:
        pr_group = geo.findPrimGroup(group)
        if pr_group is None:
            raise hou.OperationFailed(f"Prim group not found: {group}")
        prims = pr_group.prims()
    else:
        prims = geo.prims()

    total = len(prims)
    end = min(start + count, total)
    page = prims[start:end]

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
) -> dict[str, Any]:
    """Read all values of one attribute efficiently as a flat array."""
    geo = _get_sop_geo(node_path)

    cls = attrib_class.lower()
    if cls == "point":
        attrib = geo.findPointAttrib(attrib_name)
        if attrib is None:
            raise hou.OperationFailed(
                f"Point attribute '{attrib_name}' not found on {node_path}")
        values = geo.pointFloatAttribValues(attrib_name) if attrib.dataType() == hou.attribData.Float \
            else geo.pointIntAttribValues(attrib_name) if attrib.dataType() == hou.attribData.Int \
            else geo.pointStringAttribValues(attrib_name)
    elif cls == "prim":
        attrib = geo.findPrimAttrib(attrib_name)
        if attrib is None:
            raise hou.OperationFailed(
                f"Prim attribute '{attrib_name}' not found on {node_path}")
        values = geo.primFloatAttribValues(attrib_name) if attrib.dataType() == hou.attribData.Float \
            else geo.primIntAttribValues(attrib_name) if attrib.dataType() == hou.attribData.Int \
            else geo.primStringAttribValues(attrib_name)
    elif cls == "vertex":
        attrib = geo.findVertexAttrib(attrib_name)
        if attrib is None:
            raise hou.OperationFailed(
                f"Vertex attribute '{attrib_name}' not found on {node_path}")
        values = geo.vertexFloatAttribValues(attrib_name) if attrib.dataType() == hou.attribData.Float \
            else geo.vertexIntAttribValues(attrib_name) if attrib.dataType() == hou.attribData.Int \
            else geo.vertexStringAttribValues(attrib_name)
    elif cls in ("detail", "global"):
        attrib = geo.findGlobalAttrib(attrib_name)
        if attrib is None:
            raise hou.OperationFailed(
                f"Detail attribute '{attrib_name}' not found on {node_path}")
        val = geo.attribValue(attrib_name)
        values = _vec_to_list(val)
        return {
            "node_path": node_path,
            "attrib_name": attrib_name,
            "attrib_class": attrib_class,
            "size": attrib.size(),
            "type": attrib.dataType().name(),
            "value": values,
        }
    else:
        raise ValueError(f"Invalid attrib_class: {attrib_class!r}")

    return {
        "node_path": node_path,
        "attrib_name": attrib_name,
        "attrib_class": attrib_class,
        "size": attrib.size(),
        "type": attrib.dataType().name(),
        "count": len(values) // max(attrib.size(), 1),
        "values": list(values),
    }

register_handler("geometry.get_attrib_values", _get_attrib_values)


###### geometry.set_detail_attrib

def _set_detail_attrib(
    *,
    node_path: str,
    attrib_name: str,
    value: Any,
) -> dict[str, Any]:
    """Set a detail (global) attribute on a SOP node's geometry."""
    node = hou.node(node_path)
    if node is None:
        raise hou.OperationFailed(f"Node not found: {node_path}")

    geo = node.geometry()
    if geo is None:
        raise hou.OperationFailed(f"Node has no geometry: {node_path}")

    with geo.freeze() as frozen_geo:
        # Determine attribute type from value
        if isinstance(value, float):
            if frozen_geo.findGlobalAttrib(attrib_name) is None:
                frozen_geo.addAttrib(hou.attribType.Global, attrib_name, 0.0)
            frozen_geo.setGlobalAttribValue(attrib_name, value)
        elif isinstance(value, int):
            if frozen_geo.findGlobalAttrib(attrib_name) is None:
                frozen_geo.addAttrib(hou.attribType.Global, attrib_name, 0)
            frozen_geo.setGlobalAttribValue(attrib_name, value)
        elif isinstance(value, str):
            if frozen_geo.findGlobalAttrib(attrib_name) is None:
                frozen_geo.addAttrib(hou.attribType.Global, attrib_name, "")
            frozen_geo.setGlobalAttribValue(attrib_name, value)
        elif isinstance(value, (list, tuple)):
            default = [0.0] * len(value)
            if frozen_geo.findGlobalAttrib(attrib_name) is None:
                frozen_geo.addAttrib(hou.attribType.Global, attrib_name, default)
            frozen_geo.setGlobalAttribValue(attrib_name, value)
        else:
            raise ValueError(f"Unsupported value type: {type(value).__name__}")

        node.setGeometry(frozen_geo)

    return {
        "node_path": node_path,
        "attrib_name": attrib_name,
        "value": _vec_to_list(value),
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
        groups["point_groups"].append({
            "name": grp.name(),
            "count": len(grp.points()),
        })

    for grp in geo.primGroups():
        groups["prim_groups"].append({
            "name": grp.name(),
            "count": len(grp.prims()),
        })

    for grp in geo.edgeGroups():
        groups["edge_groups"].append({
            "name": grp.name(),
            "count": len(grp.edges()),
        })

    return {
        "node_path": node_path,
        **groups,
    }

register_handler("geometry.get_groups", _get_groups)


###### geometry.get_group_members

def _get_group_members(
    *,
    node_path: str,
    group_name: str,
    group_type: str = "point",
) -> dict[str, Any]:
    """Get element indices belonging to a group."""
    geo = _get_sop_geo(node_path)

    gt = group_type.lower()
    if gt == "point":
        grp = geo.findPointGroup(group_name)
        if grp is None:
            raise hou.OperationFailed(
                f"Point group '{group_name}' not found on {node_path}")
        indices = [pt.number() for pt in grp.points()]
    elif gt == "prim":
        grp = geo.findPrimGroup(group_name)
        if grp is None:
            raise hou.OperationFailed(
                f"Prim group '{group_name}' not found on {node_path}")
        indices = [pr.number() for pr in grp.prims()]
    elif gt == "edge":
        grp = geo.findEdgeGroup(group_name)
        if grp is None:
            raise hou.OperationFailed(
                f"Edge group '{group_name}' not found on {node_path}")
        indices = [[e.points()[0].number(), e.points()[1].number()]
                   for e in grp.edges()]
    else:
        raise ValueError(f"Invalid group_type: {group_type!r}. "
                         f"Use 'point', 'prim', or 'edge'.")

    return {
        "node_path": node_path,
        "group_name": group_name,
        "group_type": group_type,
        "count": len(indices),
        "members": indices,
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
            f"{attrib_class.title()} attribute '{attrib_name}' "
            f"not found on {node_path}")

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

    points = geo.points()
    total = len(points)

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
        sampled_indices = sorted(set(
            min(int(i * step + rng.uniform(0, step * 0.5)), total - 1)
            for i in range(actual_count)
        ))

    # Gather attributes
    point_attrib_names = [a.name() for a in geo.pointAttribs()]

    rows: list[dict[str, Any]] = []
    for idx in sampled_indices:
        pt = points[idx]
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

def _get_prim_intrinsics(
    *,
    node_path: str,
    prim_index: int | None = None,
) -> dict[str, Any]:
    """Get intrinsic values for primitives.

    If prim_index is None, return a summary across all primitives.
    Otherwise return intrinsics for the specified primitive.
    """
    geo = _get_sop_geo(node_path)

    if prim_index is not None:
        prims = geo.prims()
        if prim_index < 0 or prim_index >= len(prims):
            raise hou.OperationFailed(
                f"Prim index {prim_index} out of range "
                f"(0..{len(prims) - 1}) on {node_path}")
        prim = prims[prim_index]
        intrinsic_names = prim.intrinsicNames()
        intrinsics: dict[str, Any] = {}
        for name in intrinsic_names:
            val = prim.intrinsicValue(name)
            intrinsics[name] = _vec_to_list(val)

        return {
            "node_path": node_path,
            "prim_index": prim_index,
            "prim_type": prim.type().name(),
            "intrinsics": intrinsics,
        }

    # Summary mode: aggregate intrinsics across all prims
    prims = geo.prims()
    if len(prims) == 0:
        return {
            "node_path": node_path,
            "total_prims": 0,
            "summary": {},
        }

    # Use first prim to discover intrinsic names
    sample_prim = prims[0]
    intrinsic_names = sample_prim.intrinsicNames()

    summary: dict[str, Any] = {}
    for name in intrinsic_names:
        try:
            first_val = sample_prim.intrinsicValue(name)
            if isinstance(first_val, (int, float)):
                # Compute min/max/avg for numeric intrinsics
                vals = [p.intrinsicValue(name) for p in prims]
                summary[name] = {
                    "min": min(vals),
                    "max": max(vals),
                    "avg": sum(vals) / len(vals),
                    "sample": first_val,
                }
            elif isinstance(first_val, str):
                # Collect unique string values
                unique = set()
                for p in prims:
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

    return {
        "node_path": node_path,
        "total_prims": len(prims),
        "intrinsic_names": list(intrinsic_names),
        "summary": summary,
    }

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

    pos = hou.Vector3(position)

    points = geo.points()
    if len(points) == 0:
        return {
            "node_path": node_path,
            "position": position,
            "results": [],
        }

    # Compute distances and sort
    distances: list[tuple[float, int]] = []
    for pt in points:
        pt_pos = pt.position()
        dist = (pt_pos - pos).length()
        distances.append((dist, pt.number()))

    distances.sort(key=lambda x: x[0])
    top = distances[:max(max_results, 1)]

    results: list[dict[str, Any]] = []
    for dist, idx in top:
        pt = points[idx]
        results.append({
            "index": idx,
            "position": list(pt.position()),
            "distance": dist,
        })

    return {
        "node_path": node_path,
        "query_position": position,
        "max_results": max_results,
        "results": results,
    }

register_handler("geometry.find_nearest_point", _find_nearest_point)
