"""LOPs / USD handlers for FXHoudini-MCP.

Each handler operates on LOP nodes and their USD stages.
All functions run on the main thread via the dispatcher.
"""

from __future__ import annotations

# Built-in
from typing import Any

# Third-party
import hou

# Internal
from fxhoudinimcp_server.dispatcher import register_handler

# USD modules -- may not be available in all Houdini configurations
try:
    from pxr import Usd, UsdGeom, UsdShade, Sdf, Gf, Kind, Vt
    HAS_PXR = True
except ImportError:
    HAS_PXR = False


###### Helpers

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


def _require_pxr() -> None:
    """Raise if pxr modules are not available."""
    if not HAS_PXR:
        raise hou.OperationFailed(
            "USD (pxr) modules are not available in this Houdini session. "
            "Ensure you are running a Houdini build with USD support."
        )


def _get_lop_stage(node_path: str) -> "Usd.Stage":
    """Return the cooked USD stage from a LOP node.

    Raises:
        hou.OperationFailed: if node doesn't exist or has no stage.
    """
    _require_pxr()
    node = hou.node(node_path)
    if node is None:
        raise hou.OperationFailed(f"Node not found: {node_path}")
    if not hasattr(node, "stage"):
        raise hou.OperationFailed(
            f"Node is not a LOP node (no stage()): {node_path}")
    stage = node.stage()
    if stage is None:
        raise hou.OperationFailed(f"Node has no USD stage: {node_path}")
    return stage


def _usd_value_to_python(val: Any) -> Any:
    """Convert USD/Gf types to JSON-safe Python types."""
    if val is None:
        return None
    # Handle Gf vector/matrix types
    if HAS_PXR:
        if isinstance(val, (Gf.Vec2f, Gf.Vec2d, Gf.Vec2h, Gf.Vec2i)):
            return list(val)
        if isinstance(val, (Gf.Vec3f, Gf.Vec3d, Gf.Vec3h, Gf.Vec3i)):
            return list(val)
        if isinstance(val, (Gf.Vec4f, Gf.Vec4d, Gf.Vec4h, Gf.Vec4i)):
            return list(val)
        if isinstance(val, (Gf.Quatf, Gf.Quatd, Gf.Quath)):
            return {
                "real": float(val.GetReal()),
                "imaginary": list(val.GetImaginary()),
            }
        if isinstance(val, (Gf.Matrix2d, Gf.Matrix2f)):
            return [list(val.GetRow(i)) for i in range(2)]
        if isinstance(val, (Gf.Matrix3d, Gf.Matrix3f)):
            return [list(val.GetRow(i)) for i in range(3)]
        if isinstance(val, (Gf.Matrix4d, Gf.Matrix4f)):
            return [list(val.GetRow(i)) for i in range(4)]
        if isinstance(val, Gf.Range3d):
            return {"min": list(val.GetMin()), "max": list(val.GetMax())}
        if isinstance(val, Sdf.AssetPath):
            return {"path": val.path, "resolved": val.resolvedPath}
        if isinstance(val, Vt.StringArray):
            return list(val)
        if isinstance(val, (Vt.Vec3fArray, Vt.Vec3dArray)):
            return [list(v) for v in val]
        if isinstance(val, (Vt.FloatArray, Vt.DoubleArray)):
            return list(val)
        if isinstance(val, (Vt.IntArray, Vt.Int64Array)):
            return list(val)
        if isinstance(val, Vt.TokenArray):
            return [str(t) for t in val]
        # Generic Vt array fallback
        if hasattr(val, "__iter__") and hasattr(val, "__len__"):
            try:
                result = []
                for item in val:
                    result.append(_usd_value_to_python(item))
                    if len(result) > 10000:
                        break
                return result
            except (TypeError, RuntimeError):
                pass
    # Primitives
    if isinstance(val, (bool, int, float, str)):
        return val
    if isinstance(val, (list, tuple)):
        return [_usd_value_to_python(v) for v in val]
    # Fallback
    return str(val)


def _prim_to_dict(prim: "Usd.Prim", include_attrs: bool = False) -> dict[str, Any]:
    """Convert a USD prim to a JSON-safe dict."""
    info: dict[str, Any] = {
        "path": str(prim.GetPath()),
        "type": str(prim.GetTypeName()),
        "is_active": prim.IsActive(),
        "has_payload": prim.HasPayload(),
    }

    # Kind metadata
    model = Usd.ModelAPI(prim)
    kind = model.GetKind() if model else ""
    info["kind"] = str(kind) if kind else ""

    if include_attrs:
        attrs: list[dict[str, Any]] = []
        for attr in prim.GetAttributes():
            attr_info: dict[str, Any] = {
                "name": attr.GetName(),
                "type": str(attr.GetTypeName()),
                "is_authored": attr.IsAuthored(),
            }
            if attr.IsAuthored() or attr.HasValue():
                try:
                    attr_info["value"] = _usd_value_to_python(attr.Get())
                except Exception:
                    attr_info["value"] = None
                    attr_info["error"] = "Could not read value"
            attrs.append(attr_info)
        info["attributes"] = attrs

        children = [str(c.GetPath()) for c in prim.GetChildren()]
        info["children"] = children

    return info


###### lops.get_stage_info

def _get_stage_info(*, node_path: str) -> dict[str, Any]:
    """Stage summary: prim count, layers, default prim, up axis, meters per unit."""
    stage = _get_lop_stage(node_path)

    # Count prims
    prim_count = 0
    for _ in stage.Traverse():
        prim_count += 1

    root_layer = stage.GetRootLayer()
    layers = [l.identifier for l in stage.GetUsedLayers()]

    up_axis = UsdGeom.GetStageUpAxis(stage)
    meters_per_unit = UsdGeom.GetStageMetersPerUnit(stage)

    default_prim = stage.GetDefaultPrim()
    default_prim_path = str(default_prim.GetPath()) if default_prim else None

    return {
        "node_path": node_path,
        "prim_count": prim_count,
        "default_prim": default_prim_path,
        "up_axis": str(up_axis),
        "meters_per_unit": float(meters_per_unit),
        "root_layer": root_layer.identifier,
        "layer_count": len(layers),
        "layers": layers[:50],  # Cap to avoid huge responses
    }

register_handler("lops.get_stage_info", _get_stage_info)


###### lops.get_usd_prim

def _get_usd_prim(
    *,
    node_path: str,
    prim_path: str,
) -> dict[str, Any]:
    """Detailed prim info with type, kind, attributes, and children."""
    stage = _get_lop_stage(node_path)

    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        raise hou.OperationFailed(
            f"USD prim not found at '{prim_path}' on stage from {node_path}")

    return {
        "node_path": node_path,
        "prim": _prim_to_dict(prim, include_attrs=True),
    }

register_handler("lops.get_usd_prim", _get_usd_prim)


###### lops.list_usd_prims

def _list_usd_prims(
    *,
    node_path: str,
    root_path: str = "/",
    prim_type: str | None = None,
    kind: str | None = None,
    depth: int | None = None,
) -> dict[str, Any]:
    """List prims filtered by type/kind/purpose with optional depth limit."""
    stage = _get_lop_stage(node_path)

    root = stage.GetPrimAtPath(root_path)
    if not root.IsValid():
        raise hou.OperationFailed(
            f"Root prim not found at '{root_path}' on stage from {node_path}")

    results: list[dict[str, Any]] = []
    root_depth = len(root_path.rstrip("/").split("/")) - 1

    for prim in stage.Traverse():
        prim_path_str = str(prim.GetPath())

        # Depth filter
        if depth is not None:
            prim_depth = len(prim_path_str.rstrip("/").split("/")) - 1
            if prim_depth - root_depth > depth:
                continue

        # Must be under root_path
        if root_path != "/" and not prim_path_str.startswith(root_path):
            continue

        # Type filter
        if prim_type is not None:
            if str(prim.GetTypeName()) != prim_type:
                continue

        # Kind filter
        if kind is not None:
            model = Usd.ModelAPI(prim)
            prim_kind = str(model.GetKind()) if model else ""
            if prim_kind != kind:
                continue

        results.append(_prim_to_dict(prim))

        # Safety cap
        if len(results) >= 5000:
            break

    return {
        "node_path": node_path,
        "root_path": root_path,
        "filters": {
            "prim_type": prim_type,
            "kind": kind,
            "depth": depth,
        },
        "count": len(results),
        "prims": results,
    }

register_handler("lops.list_usd_prims", _list_usd_prims)


###### lops.get_usd_attribute

def _get_usd_attribute(
    *,
    node_path: str,
    prim_path: str,
    attr_name: str,
    time: float | None = None,
) -> dict[str, Any]:
    """Read a USD attribute value at an optional time code."""
    stage = _get_lop_stage(node_path)

    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        raise hou.OperationFailed(
            f"USD prim not found at '{prim_path}' on stage from {node_path}")

    attr = prim.GetAttribute(attr_name)
    if not attr.IsValid():
        raise hou.OperationFailed(
            f"Attribute '{attr_name}' not found on prim '{prim_path}'")

    time_code = Usd.TimeCode(time) if time is not None else Usd.TimeCode.Default()
    value = attr.Get(time_code)

    return {
        "node_path": node_path,
        "prim_path": prim_path,
        "attr_name": attr_name,
        "type": str(attr.GetTypeName()),
        "is_authored": attr.IsAuthored(),
        "time": time,
        "value": _usd_value_to_python(value),
    }

register_handler("lops.get_usd_attribute", _get_usd_attribute)


###### lops.get_usd_layers

def _get_usd_layers(*, node_path: str) -> dict[str, Any]:
    """List all layers used in the stage."""
    stage = _get_lop_stage(node_path)

    layers: list[dict[str, Any]] = []
    for layer in stage.GetUsedLayers():
        layer_info: dict[str, Any] = {
            "identifier": layer.identifier,
            "display_name": layer.GetDisplayName(),
            "resolved_path": layer.realPath,
            "dirty": layer.dirty,
        }
        if hasattr(layer, "anonymous") and layer.anonymous:
            layer_info["anonymous"] = True
        layers.append(layer_info)

    return {
        "node_path": node_path,
        "count": len(layers),
        "layers": layers,
    }

register_handler("lops.get_usd_layers", _get_usd_layers)


###### lops.get_usd_prim_stats

def _get_usd_prim_stats(
    *,
    node_path: str,
    prim_path: str = "/",
) -> dict[str, Any]:
    """Prim counts broken down by type under the given root."""
    stage = _get_lop_stage(node_path)

    type_counts: dict[str, int] = {}
    total = 0

    for prim in stage.Traverse():
        path = str(prim.GetPath())
        if prim_path != "/" and not path.startswith(prim_path):
            continue
        total += 1
        type_name = str(prim.GetTypeName()) or "(untyped)"
        type_counts[type_name] = type_counts.get(type_name, 0) + 1

    # Sort by count descending
    sorted_types = sorted(type_counts.items(), key=lambda x: -x[1])

    return {
        "node_path": node_path,
        "prim_path": prim_path,
        "total_prims": total,
        "type_counts": dict(sorted_types),
    }

register_handler("lops.get_usd_prim_stats", _get_usd_prim_stats)


###### lops.get_last_modified_prims

def _get_last_modified_prims(*, node_path: str) -> dict[str, Any]:
    """Prims modified by the last LOP cook.

    Uses the node's lastModifiedPrims() if available (Houdini 19.5+),
    otherwise falls back to inspecting the edit target layer.
    """
    _require_pxr()
    node = hou.node(node_path)
    if node is None:
        raise hou.OperationFailed(f"Node not found: {node_path}")

    # Attempt lastModifiedPrims() (Houdini 19.5+)
    if hasattr(node, "lastModifiedPrims"):
        paths = node.lastModifiedPrims()
        return {
            "node_path": node_path,
            "count": len(paths),
            "prims": [str(p) for p in paths],
        }

    # Fallback: inspect the edit target layer for authored prims
    stage = node.stage()
    if stage is None:
        raise hou.OperationFailed(f"Node has no stage: {node_path}")

    edit_target = stage.GetEditTarget()
    layer = edit_target.GetLayer()

    authored: list[str] = []
    def _walk(path: "Sdf.Path") -> None:
        spec = layer.GetPrimAtPath(path)
        if spec:
            authored.append(str(path))
            for child_name in spec.nameChildren:
                _walk(path.AppendChild(child_name))

    root = Sdf.Path.absoluteRootPath
    root_spec = layer.GetPrimAtPath(root)
    if root_spec:
        for child_name in root_spec.nameChildren:
            _walk(root.AppendChild(child_name))

    return {
        "node_path": node_path,
        "count": len(authored),
        "prims": authored,
        "note": "Fallback: showing all prims authored in the edit target layer",
    }

register_handler("lops.get_last_modified_prims", _get_last_modified_prims)


###### lops.create_lop_node

def _create_lop_node(
    *,
    parent_path: str,
    lop_type: str,
    name: str | None = None,
    prim_path: str | None = None,
) -> dict[str, Any]:
    """Create a new LOP node with optional presets."""
    parent = hou.node(parent_path)
    if parent is None:
        raise hou.OperationFailed(f"Parent node not found: {parent_path}")

    node = parent.createNode(lop_type, node_name=name)

    # Set prim_path parameter if the node type has one
    if prim_path is not None:
        parm = node.parm("primpath")
        if parm is None:
            parm = node.parm("primpattern")
        if parm is not None:
            parm.set(prim_path)

    node.moveToGoodPosition()
    _focus_network_editor(node)

    return {
        "node_path": node.path(),
        "type": node.type().name(),
        "name": node.name(),
        "prim_path": prim_path,
    }

register_handler("lops.create_lop_node", _create_lop_node)


###### lops.set_usd_attribute

def _set_usd_attribute(
    *,
    node_path: str,
    prim_path: str,
    attr_name: str,
    value: Any,
) -> dict[str, Any]:
    """Set a USD attribute via an inline Python LOP.

    Creates a Python LOP node as a child of the specified node's parent
    that sets the attribute value on the stage.
    """
    _require_pxr()
    node = hou.node(node_path)
    if node is None:
        raise hou.OperationFailed(f"Node not found: {node_path}")

    parent = node.parent()

    # Create a Python LOP to set the attribute
    python_node = parent.createNode("python", node_name="set_usd_attr_auto")
    python_node.setInput(0, node)

    # Build the Python snippet
    val_repr = repr(value)
    snippet = f"""
import hou
node = hou.pwd()
stage = node.editableStage()
prim = stage.GetPrimAtPath("{prim_path}")
if prim.IsValid():
    attr = prim.GetAttribute("{attr_name}")
    if attr.IsValid():
        attr.Set({val_repr})
    else:
        raise RuntimeError("Attribute '{attr_name}' not found on prim '{prim_path}'")
else:
    raise RuntimeError("Prim not found: {prim_path}")
"""
    python_node.parm("python").set(snippet.strip())
    python_node.moveToGoodPosition()
    _focus_network_editor(python_node)

    # Cook to apply
    python_node.cook(force=True)

    return {
        "node_path": node_path,
        "python_node": python_node.path(),
        "prim_path": prim_path,
        "attr_name": attr_name,
        "value": _usd_value_to_python(value) if HAS_PXR else value,
        "success": True,
    }

register_handler("lops.set_usd_attribute", _set_usd_attribute)


###### lops.get_usd_materials

def _get_usd_materials(*, node_path: str) -> dict[str, Any]:
    """List all materials with their bindings."""
    stage = _get_lop_stage(node_path)

    materials: list[dict[str, Any]] = []
    bindings_map: dict[str, list[str]] = {}

    # Find all materials
    for prim in stage.Traverse():
        if prim.IsA(UsdShade.Material):
            mat_path = str(prim.GetPath())
            mat = UsdShade.Material(prim)
            mat_info: dict[str, Any] = {
                "path": mat_path,
                "name": prim.GetName(),
            }
            # Surface and displacement outputs
            surface = mat.GetSurfaceOutput()
            if surface:
                connected = surface.GetConnectedSource()
                if connected and connected[0]:
                    mat_info["surface_shader"] = str(connected[0].GetPath())
            displacement = mat.GetDisplacementOutput()
            if displacement:
                connected = displacement.GetConnectedSource()
                if connected and connected[0]:
                    mat_info["displacement_shader"] = str(connected[0].GetPath())

            materials.append(mat_info)
            bindings_map[mat_path] = []

    # Find bindings
    for prim in stage.Traverse():
        binding = UsdShade.MaterialBindingAPI(prim)
        try:
            bound = binding.GetDirectBinding()
            mat_path = str(bound.GetMaterialPath())
            if mat_path and mat_path in bindings_map:
                bindings_map[mat_path].append(str(prim.GetPath()))
        except Exception:
            pass

    # Attach bindings to materials
    for mat in materials:
        mat["bound_to"] = bindings_map.get(mat["path"], [])

    return {
        "node_path": node_path,
        "count": len(materials),
        "materials": materials,
    }

register_handler("lops.get_usd_materials", _get_usd_materials)


###### lops.find_usd_prims

def _find_usd_prims(
    *,
    node_path: str,
    pattern: str,
) -> dict[str, Any]:
    """Search prims by path pattern (supports * and ** wildcards)."""
    stage = _get_lop_stage(node_path)

    import fnmatch

    results: list[dict[str, Any]] = []
    for prim in stage.Traverse():
        prim_path = str(prim.GetPath())
        if fnmatch.fnmatch(prim_path, pattern) or pattern in prim_path:
            results.append(_prim_to_dict(prim))
            if len(results) >= 5000:
                break

    return {
        "node_path": node_path,
        "pattern": pattern,
        "count": len(results),
        "prims": results,
    }

register_handler("lops.find_usd_prims", _find_usd_prims)


###### lops.get_usd_composition

def _get_usd_composition(
    *,
    node_path: str,
    prim_path: str,
) -> dict[str, Any]:
    """Composition arcs for a prim (references, payloads, inherits, specializes, variants)."""
    stage = _get_lop_stage(node_path)

    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        raise hou.OperationFailed(
            f"USD prim not found at '{prim_path}' on stage from {node_path}")

    prim_index = prim.GetPrimIndex()

    arcs: list[dict[str, Any]] = []
    if prim_index.IsValid():
        for node in prim_index.nodeRange:
            arc_info: dict[str, Any] = {
                "arc_type": str(node.arcType),
                "layer": str(node.layerStack.identifier.rootLayer)
                         if node.layerStack else None,
                "path": str(node.path),
                "has_specs": node.hasSpecs,
            }
            arcs.append(arc_info)

    # Also gather explicit references, payloads, inherits, specializes
    metadata = prim.GetPrimStack()
    references: list[str] = []
    payloads: list[str] = []
    inherits: list[str] = []
    specializes: list[str] = []

    for spec in metadata:
        if hasattr(spec, "referenceList"):
            for ref in spec.referenceList.prependedItems:
                references.append({
                    "asset": str(ref.assetPath) if ref.assetPath else None,
                    "prim_path": str(ref.primPath) if ref.primPath else None,
                })
        if hasattr(spec, "payloadList"):
            for pl in spec.payloadList.prependedItems:
                payloads.append({
                    "asset": str(pl.assetPath) if pl.assetPath else None,
                    "prim_path": str(pl.primPath) if pl.primPath else None,
                })
        if hasattr(spec, "inheritPathList"):
            for inh in spec.inheritPathList.prependedItems:
                inherits.append(str(inh))
        if hasattr(spec, "specializesList"):
            for sp in spec.specializesList.prependedItems:
                specializes.append(str(sp))

    return {
        "node_path": node_path,
        "prim_path": prim_path,
        "arc_count": len(arcs),
        "composition_arcs": arcs,
        "references": references,
        "payloads": payloads,
        "inherits": inherits,
        "specializes": specializes,
    }

register_handler("lops.get_usd_composition", _get_usd_composition)


###### lops.get_usd_variants

def _get_usd_variants(
    *,
    node_path: str,
    prim_path: str,
) -> dict[str, Any]:
    """Variant sets and current selections for a prim."""
    stage = _get_lop_stage(node_path)

    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        raise hou.OperationFailed(
            f"USD prim not found at '{prim_path}' on stage from {node_path}")

    variant_sets: list[dict[str, Any]] = []
    vsets = prim.GetVariantSets()
    for name in vsets.GetNames():
        vset = vsets.GetVariantSet(name)
        variant_sets.append({
            "name": name,
            "variants": vset.GetVariantNames(),
            "selection": vset.GetVariantSelection(),
        })

    return {
        "node_path": node_path,
        "prim_path": prim_path,
        "count": len(variant_sets),
        "variant_sets": variant_sets,
    }

register_handler("lops.get_usd_variants", _get_usd_variants)


###### lops.inspect_usd_layer

def _inspect_usd_layer(
    *,
    node_path: str,
    layer_index: int = 0,
) -> dict[str, Any]:
    """Inspect a specific layer in the stage by index."""
    stage = _get_lop_stage(node_path)

    layers = stage.GetUsedLayers()
    if layer_index < 0 or layer_index >= len(layers):
        raise hou.OperationFailed(
            f"Layer index {layer_index} out of range "
            f"(0..{len(layers) - 1}) for stage from {node_path}")

    layer = layers[layer_index]

    # Gather authored prims in this layer
    authored_prims: list[str] = []
    def _walk_layer(path: "Sdf.Path") -> None:
        spec = layer.GetPrimAtPath(path)
        if spec:
            authored_prims.append(str(path))
            if hasattr(spec, "nameChildren"):
                for child_name in spec.nameChildren:
                    _walk_layer(path.AppendChild(child_name))

    root = Sdf.Path.absoluteRootPath
    root_spec = layer.GetPrimAtPath(root)
    if root_spec and hasattr(root_spec, "nameChildren"):
        for child_name in root_spec.nameChildren:
            _walk_layer(root.AppendChild(child_name))

    # Sublayers
    sublayers = [str(s) for s in layer.subLayerPaths] if hasattr(layer, "subLayerPaths") else []

    return {
        "node_path": node_path,
        "layer_index": layer_index,
        "identifier": layer.identifier,
        "display_name": layer.GetDisplayName(),
        "resolved_path": layer.realPath,
        "dirty": layer.dirty,
        "authored_prim_count": len(authored_prims),
        "authored_prims": authored_prims[:500],  # Cap output size
        "sublayers": sublayers,
        "default_prim": str(layer.defaultPrim) if layer.defaultPrim else None,
        "documentation": layer.documentation if hasattr(layer, "documentation") else None,
    }

register_handler("lops.inspect_usd_layer", _inspect_usd_layer)


###### lops.create_light

def _create_light(
    *,
    parent_path: str = "/stage",
    light_type: str = "dome",
    name: str | None = None,
    intensity: float = 1.0,
    color: list[float] | None = None,
    position: list[float] | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Create a USD light node in a LOP network.

    Supports dome, distant, rect, sphere, disk, and cylinder light types.
    Sets intensity, color, and position parameters as specified.

    Args:
        parent_path: Parent LOP network path (default: "/stage").
        light_type: Type of light: "dome", "distant", "rect", "sphere",
            "disk", or "cylinder".
        name: Optional name for the light node.
        intensity: Light intensity (default: 1.0).
        color: Optional [r, g, b] color values (0.0 to 1.0).
        position: Optional [x, y, z] world position.
    """
    parent = hou.node(parent_path)
    if parent is None:
        raise hou.OperationFailed(f"Parent node not found: {parent_path}")

    # Map light_type to LOP node type
    light_type_map = {
        "dome": "domelight",
        "distant": "distantlight",
        "rect": "rectlight",
        "sphere": "spherelight",
        "disk": "disklight",
        "cylinder": "cylinderlight",
    }

    lop_type = light_type_map.get(light_type)
    if lop_type is None:
        available = sorted(light_type_map.keys())
        raise hou.OperationFailed(
            f"Unknown light type: '{light_type}'. "
            f"Available types: {available}"
        )

    node = parent.createNode(lop_type, node_name=name)

    # Set intensity
    intensity_parm = node.parm("xn__inputsintensity_i0b")
    if intensity_parm is None:
        intensity_parm = node.parm("intensity")
    if intensity_parm is not None:
        intensity_parm.set(intensity)

    # Set color
    if color is not None and len(color) >= 3:
        for i, suffix in enumerate(["r", "g", "b"]):
            parm = node.parm(f"xn__inputscolor_{suffix}0b")
            if parm is None:
                parm = node.parm(f"color{suffix}")
            if parm is not None:
                parm.set(color[i])

    # Set position via translate parameters
    if position is not None and len(position) >= 3:
        for i, axis in enumerate(["x", "y", "z"]):
            parm = node.parm(f"t{axis}")
            if parm is not None:
                parm.set(position[i])

    node.moveToGoodPosition()
    _focus_network_editor(node)

    # Determine the prim path
    prim_path_parm = node.parm("primpath")
    prim_path = prim_path_parm.eval() if prim_path_parm else None

    return {
        "node_path": node.path(),
        "light_type": light_type,
        "prim_path": prim_path,
    }

register_handler("lops.create_light", _create_light)


###### lops.list_lights

def _list_lights(*, node_path: str, **_: Any) -> dict[str, Any]:
    """List all USD lights on a LOP stage.

    Cooks the LOP node and traverses the USD stage to find all
    UsdLux light prims.

    Args:
        node_path: Path to the LOP node.
    """
    _require_pxr()
    from pxr import UsdLux

    stage = _get_lop_stage(node_path)

    lights: list[dict[str, Any]] = []
    for prim in stage.Traverse():
        # Check if the prim is a light
        if not prim.HasAPI(UsdLux.LightAPI):
            # Also check by type name for older USD versions
            type_name = str(prim.GetTypeName())
            if "Light" not in type_name:
                continue

        light_info: dict[str, Any] = {
            "prim_path": str(prim.GetPath()),
            "light_type": str(prim.GetTypeName()),
        }

        # Read common light attributes
        for attr_name in ("inputs:intensity", "intensity"):
            attr = prim.GetAttribute(attr_name)
            if attr and attr.HasValue():
                light_info["intensity"] = _usd_value_to_python(attr.Get())
                break

        for attr_name in ("inputs:color", "color"):
            attr = prim.GetAttribute(attr_name)
            if attr and attr.HasValue():
                light_info["color"] = _usd_value_to_python(attr.Get())
                break

        # Check visibility / enabled
        vis_attr = prim.GetAttribute("visibility")
        if vis_attr and vis_attr.HasValue():
            light_info["enabled"] = str(vis_attr.Get()) != "invisible"
        else:
            light_info["enabled"] = prim.IsActive()

        lights.append(light_info)

    return {
        "node_path": node_path,
        "count": len(lights),
        "lights": lights,
    }

register_handler("lops.list_lights", _list_lights)


###### lops.set_light_properties

def _set_light_properties(
    *,
    node_path: str,
    prim_path: str,
    properties: dict[str, Any],
    **_: Any,
) -> dict[str, Any]:
    """Set properties on a USD light prim via an inline Python LOP.

    Supported properties include: intensity, color, exposure, diffuse,
    specular, shadow_enable, and more.

    Args:
        node_path: Path to the LOP node to connect after.
        prim_path: USD prim path of the light.
        properties: Dict of property name -> value to set.
    """
    _require_pxr()
    node = hou.node(node_path)
    if node is None:
        raise hou.OperationFailed(f"Node not found: {node_path}")

    parent = node.parent()

    # Map friendly property names to USD attribute names
    attr_name_map = {
        "intensity": "inputs:intensity",
        "color": "inputs:color",
        "exposure": "inputs:exposure",
        "diffuse": "inputs:diffuse",
        "specular": "inputs:specular",
        "shadow_enable": "inputs:shadow:enable",
        "temperature": "inputs:colorTemperature",
        "enable_temperature": "inputs:enableColorTemperature",
    }

    # Build Python snippet to set attributes
    set_lines: list[str] = []
    updated_properties: list[str] = []

    for prop_name, prop_value in properties.items():
        usd_attr = attr_name_map.get(prop_name, prop_name)
        val_repr = repr(prop_value)
        set_lines.append(
            f'    attr = prim.GetAttribute("{usd_attr}")\n'
            f'    if attr and attr.IsValid():\n'
            f'        attr.Set({val_repr})'
        )
        updated_properties.append(prop_name)

    if not set_lines:
        return {
            "prim_path": prim_path,
            "updated_properties": [],
            "note": "No properties to set",
        }

    snippet = (
        'import hou\n'
        'node = hou.pwd()\n'
        'stage = node.editableStage()\n'
        f'prim = stage.GetPrimAtPath("{prim_path}")\n'
        'if prim.IsValid():\n'
        + "\n".join(set_lines)
    )

    python_node = parent.createNode("python", node_name="set_light_props_auto")
    python_node.setInput(0, node)
    python_node.parm("python").set(snippet)
    python_node.moveToGoodPosition()
    _focus_network_editor(python_node)
    python_node.cook(force=True)

    return {
        "prim_path": prim_path,
        "python_node": python_node.path(),
        "updated_properties": updated_properties,
    }

register_handler("lops.set_light_properties", _set_light_properties)


###### lops.create_light_rig

def _create_light_rig(
    *,
    parent_path: str = "/stage",
    preset: str = "three_point",
    intensity_mult: float = 1.0,
    **_: Any,
) -> dict[str, Any]:
    """Create a preset lighting rig in a LOP network.

    Available presets:
    - "three_point": Key light + fill light + rim light
    - "studio": Softbox-style setup with rect lights
    - "outdoor": Dome light + distant light (sun)
    - "hdri": Single dome light

    Args:
        parent_path: Parent LOP network path (default: "/stage").
        preset: Lighting preset name.
        intensity_mult: Multiplier applied to all light intensities.
    """
    parent = hou.node(parent_path)
    if parent is None:
        raise hou.OperationFailed(f"Parent node not found: {parent_path}")

    presets = {
        "three_point": [
            {"type": "distantlight", "name": "key_light",
             "intensity": 1.0, "color": [1.0, 0.95, 0.9],
             "rx": -45, "ry": -30},
            {"type": "distantlight", "name": "fill_light",
             "intensity": 0.4, "color": [0.85, 0.9, 1.0],
             "rx": -30, "ry": 45},
            {"type": "distantlight", "name": "rim_light",
             "intensity": 0.6, "color": [1.0, 1.0, 1.0],
             "rx": -15, "ry": 160},
        ],
        "studio": [
            {"type": "rectlight", "name": "softbox_key",
             "intensity": 2.0, "color": [1.0, 0.98, 0.95],
             "tx": -2, "ty": 3, "tz": 2, "rx": -40, "ry": -30},
            {"type": "rectlight", "name": "softbox_fill",
             "intensity": 1.0, "color": [0.9, 0.95, 1.0],
             "tx": 2, "ty": 2.5, "tz": 2, "rx": -35, "ry": 30},
            {"type": "rectlight", "name": "softbox_back",
             "intensity": 1.5, "color": [1.0, 1.0, 1.0],
             "tx": 0, "ty": 3, "tz": -3, "rx": -20, "ry": 180},
        ],
        "outdoor": [
            {"type": "domelight", "name": "sky_dome",
             "intensity": 0.3, "color": [0.7, 0.85, 1.0]},
            {"type": "distantlight", "name": "sun",
             "intensity": 1.5, "color": [1.0, 0.95, 0.85],
             "rx": -50, "ry": -30},
        ],
        "hdri": [
            {"type": "domelight", "name": "hdri_dome",
             "intensity": 1.0, "color": [1.0, 1.0, 1.0]},
        ],
    }

    preset_config = presets.get(preset)
    if preset_config is None:
        available = sorted(presets.keys())
        raise hou.OperationFailed(
            f"Unknown lighting preset: '{preset}'. "
            f"Available presets: {available}"
        )

    created_nodes: list[str] = []

    for light_def in preset_config:
        lop_type = light_def["type"]
        light_name = light_def.get("name")
        node = parent.createNode(lop_type, node_name=light_name)

        # Set intensity with multiplier
        base_intensity = light_def.get("intensity", 1.0)
        final_intensity = base_intensity * intensity_mult
        intensity_parm = node.parm("xn__inputsintensity_i0b")
        if intensity_parm is None:
            intensity_parm = node.parm("intensity")
        if intensity_parm is not None:
            intensity_parm.set(final_intensity)

        # Set color
        light_color = light_def.get("color")
        if light_color:
            for i, suffix in enumerate(["r", "g", "b"]):
                parm = node.parm(f"xn__inputscolor_{suffix}0b")
                if parm is None:
                    parm = node.parm(f"color{suffix}")
                if parm is not None:
                    parm.set(light_color[i])

        # Set transform parameters
        for axis in ["x", "y", "z"]:
            for prefix in ["t", "r"]:
                key = f"{prefix}{axis}"
                if key in light_def:
                    parm = node.parm(key)
                    if parm is not None:
                        parm.set(light_def[key])

        node.moveToGoodPosition()
        created_nodes.append(node.path())

    # Focus on the last created light to keep the editor alive
    if created_nodes:
        last_node = hou.node(created_nodes[-1])
        if last_node is not None:
            _focus_network_editor(last_node)

    return {
        "nodes": created_nodes,
        "preset": preset,
        "lights_created": len(created_nodes),
    }

register_handler("lops.create_light_rig", _create_light_rig)
