"""LOPs / USD handlers for FXHoudini-MCP.

Each handler operates on LOP nodes and their USD stages.
All functions run on the main thread via the dispatcher.
"""

from __future__ import annotations

# Built-in
import contextlib
import fnmatch
import itertools
import re
from typing import Any

# Third-party
import hou

# Internal
from fxhoudinimcp_server.config import layout_if_enabled, place_new_node
from fxhoudinimcp_server.dispatcher import register_handler

# USD modules -- may not be available in all Houdini configurations
try:
    # Kind is imported to prove the module set is complete, not to be called.
    from pxr import Gf, Kind, Sdf, Usd, UsdGeom, UsdShade, Vt  # noqa: F401

    HAS_PXR = True
except ImportError:
    HAS_PXR = False


###### Helpers


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


def _require_pxr() -> None:
    """Raise if pxr modules are not available."""
    if not HAS_PXR:
        raise hou.OperationFailed(
            "USD (pxr) modules are not available in this Houdini session. "
            "Ensure you are running a Houdini build with USD support."
        )


def _get_lop_stage(node_path: str) -> Usd.Stage:
    """Return the cooked USD stage from a LOP node.

    Raises:
        hou.OperationFailed: if node doesn't exist or has no stage.
    """
    _require_pxr()
    node = hou.node(node_path)
    if node is None:
        raise hou.OperationFailed(f"Node not found: {node_path}")
    if not hasattr(node, "stage"):
        raise hou.OperationFailed(f"Node is not a LOP node (no stage()): {node_path}")
    stage = node.stage()
    if stage is None:
        raise hou.OperationFailed(f"Node has no USD stage: {node_path}")
    return stage


#: Arrays longer than this are summarised (size, type, head, range) unless the
#: caller asks for the full value. 16 keeps extent (2 vec3), xformOpOrder and
#: small primvars whole; points, faceVertexIndices and st never fit anyway.
_ARRAY_SUMMARY_LIMIT = 16
_ARRAY_HEAD = 8


def _is_usd_array(val: Any) -> bool:
    """A Vt array or any other sized sequence that is not text, a mapping or a Gf vector."""
    if (
        isinstance(val, (str, bytes, dict))
        or not hasattr(val, "__len__")
        or not hasattr(val, "__iter__")
    ):
        return False
    if HAS_PXR:
        gf = (
            Gf.Vec2f, Gf.Vec2d, Gf.Vec2h, Gf.Vec2i, Gf.Vec3f, Gf.Vec3d, Gf.Vec3h, Gf.Vec3i,
            Gf.Vec4f, Gf.Vec4d, Gf.Vec4h, Gf.Vec4i, Gf.Matrix2d, Gf.Matrix2f, Gf.Matrix3d,
            Gf.Matrix3f, Gf.Matrix4d, Gf.Matrix4f, Gf.Quatf, Gf.Quatd, Gf.Quath,
        )  # fmt: skip
        with contextlib.suppress(Exception):
            if isinstance(val, gf):
                return False
    return True


def _array_range(val: Any) -> dict[str, Any]:
    """min/max of a numeric array (per component for vectors), or {} when not numeric."""
    try:
        import numpy as np

        arr = np.asarray(val)
        if arr.dtype.kind not in "iuf" or arr.size == 0:
            return {}
        if arr.ndim == 1:
            return {"min": arr.min().item(), "max": arr.max().item()}
        return {"min": arr.min(axis=0).tolist(), "max": arr.max(axis=0).tolist()}
    except Exception:
        return {}


def _array_summary(val: Any, head: int = _ARRAY_HEAD) -> dict[str, Any]:
    """What an agent needs from a large array: how many, of what, the first few, the range.

    get_usd_prim on a building mesh answered 6.6 million characters (points,
    st, faceVertexIndices in full) and get_usd_attribute(primvars:st) 40 000
    lines. Nobody reads that; they grep it. This is the grep.
    """
    size = len(val)
    first = val[0] if size else None
    summary: dict[str, Any] = {
        "array": True,
        "size": size,
        "element_type": type(first).__name__ if size else None,
        "head": [_usd_value_to_python(v, array_limit=None) for v in itertools.islice(val, head)],
    }
    summary.update(_array_range(val))
    summary["note"] = f"{size} elements; first {min(head, size)} shown. full=True returns them all."
    return summary


def _usd_value_to_python(val: Any, array_limit: int | None = _ARRAY_SUMMARY_LIMIT) -> Any:
    """Convert USD/Gf types to JSON-safe Python types.

    An array longer than *array_limit* comes back as a summary dict (see
    _array_summary); array_limit=None returns every element.
    """
    if val is None:
        return None
    # Text first: a str is iterable with a length, so the generic Vt-array
    # fallback below walks it character by character and each 1-char str is
    # iterable again -- a token attribute (orientation, purpose, visibility)
    # came back as a ~1000-deep nested list, 24 KB per token on a Mesh.
    if isinstance(val, (bool, int, float, str)):
        return val
    if array_limit is not None and _is_usd_array(val):
        try:
            if len(val) > array_limit:
                return _array_summary(val)
        except TypeError:
            pass
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
        # Generic Vt array fallback. No cap here: array_limit above already
        # decides whether a long array is summarised, so reaching this point
        # means the caller asked for the whole thing. The old 10 000 break made
        # full=True quietly lie for every array type not enumerated above --
        # Vt.Vec2fArray (primvars:st) came back with 10 001 of 40 000 elements
        # while Vt.Vec3fArray came back whole.
        if hasattr(val, "__iter__") and hasattr(val, "__len__"):
            try:
                return [_usd_value_to_python(item) for item in val]
            except (TypeError, RuntimeError):
                pass
    # Primitives
    if isinstance(val, (bool, int, float, str)):
        return val
    if isinstance(val, (list, tuple)):
        return [_usd_value_to_python(v) for v in val]
    # Fallback
    return str(val)


def _traverse(stage: Usd.Stage, root: Usd.Prim | None, instance_proxies: bool) -> Any:
    """Prims under *root* (or the whole stage), optionally through instances.

    The default USD traversal stops at an instanceable prim: its children
    live on the prototype, and GetChildren() on the instance answers with an
    empty tuple. A stage of instanced trees therefore counted one Mesh per
    prototype, and finding the meshes took execute_python with
    TraverseInstanceProxies. The predicate is opt-in because instance
    proxies multiply the prim count by whatever the instancer instances.

    Args:
        stage: The stage to walk.
        root: Subtree root, or None for the whole stage.
        instance_proxies: Descend into instanceable prims.
    """
    if root is None:
        if instance_proxies:
            return stage.Traverse(Usd.TraverseInstanceProxies())
        return stage.Traverse()
    if instance_proxies:
        return Usd.PrimRange(root, Usd.TraverseInstanceProxies())
    return Usd.PrimRange(root)


def _hidden_descendants(prim: Usd.Prim) -> int:
    """How many prims an instanceable prim hides behind an empty GetChildren()."""
    count = 0
    with contextlib.suppress(Exception):
        for _ in Usd.PrimRange(prim, Usd.TraverseInstanceProxies()):
            count += 1
    # The range starts at the prim itself.
    return max(0, count - 1)


def _stage_frame() -> float | None:
    """The current frame, or None when hou cannot say."""
    with contextlib.suppress(Exception):
        return float(hou.frame())
    return None


def _read_time(time: float | None) -> tuple[Any, float | None, str]:
    """(time code, time, time_source) for reading many attributes at once.

    No *time* means the current frame, which is what the viewport and a
    render of that frame resolve. A time-sampled attribute read at the
    default time code answers its default slot instead, a value the render
    never sees once samples exist. An attribute without samples resolves to
    its default at any time code, so one frame serves every attribute.
    """
    if time is not None:
        return Usd.TimeCode(float(time)), float(time), "requested"
    frame = _stage_frame()
    if frame is not None:
        return Usd.TimeCode(frame), frame, "stage_frame"
    return Usd.TimeCode.Default(), None, "default"


def _name_matcher(patterns: list[str] | str | None):
    """A predicate on attribute/relationship names: globs, None = everything."""
    if not patterns:
        return lambda name: True
    if isinstance(patterns, str):
        patterns = [patterns]
    return lambda name: any(fnmatch.fnmatchcase(name, p) for p in patterns)


def _attr_entry(attr: Any, time_code: Any, full: bool) -> dict[str, Any]:
    """One attribute: name, type, authored, value at *time_code*, sample count."""
    entry: dict[str, Any] = {
        "name": attr.GetName(),
        "type": str(attr.GetTypeName()),
        "is_authored": attr.IsAuthored(),
    }
    if attr.IsAuthored() or attr.HasValue():
        try:
            entry["value"] = _usd_value_to_python(
                attr.Get(time_code), array_limit=None if full else _ARRAY_SUMMARY_LIMIT
            )
        except Exception:
            entry["value"] = None
            entry["error"] = "Could not read value"
    samples = 0
    with contextlib.suppress(Exception):
        samples = int(attr.GetNumTimeSamples())
    if samples:
        # The value above is the one at this time, not the default slot; the
        # count says it differs at other frames.
        entry["time_samples"] = samples
    return entry


def _relationship_entry(rel: Any) -> dict[str, Any]:
    """One relationship: name and targets (a RenderSettings' `camera`)."""
    return {"name": rel.GetName(), "relationship": True, "targets": _binding_targets(rel)}


def _prim_to_dict(
    prim: Usd.Prim,
    include_attrs: bool = False,
    full: bool = False,
    instance_proxies: bool = False,
    time_code: Any = None,
    attr_patterns: list[str] | str | None = None,
) -> dict[str, Any]:
    """Convert a USD prim to a JSON-safe dict.

    With include_attrs, array values longer than _ARRAY_SUMMARY_LIMIT are
    summarised unless *full* is set, and `children` lists the prims under
    an instanceable prim's prototype when *instance_proxies* is set. Values
    are read at *time_code* (default: the default time code), and
    *attr_patterns* narrows the attributes and relationships listed.
    """
    # is_active / has_payload only when they are not the default: true and
    # false on nearly every row of a listing, about a third of each row.
    info: dict[str, Any] = {"path": str(prim.GetPath()), "type": str(prim.GetTypeName())}
    if not prim.IsActive():
        info["is_active"] = False
    if prim.HasPayload():
        info["has_payload"] = True
    # An empty `children` on an instanceable prim is not an empty prim: its
    # contents live on the prototype, and only an instance-proxy walk sees
    # them. Say so, with a count, instead of letting [] read as "nothing".
    # The count walks the whole prototype, so only the single-prim reply
    # (the one that lists `children`) pays for it, not every list entry.
    with contextlib.suppress(Exception):
        if prim.IsInstanceable():
            info["is_instanceable"] = True
            hidden = _hidden_descendants(prim) if include_attrs else 0
            if hidden:
                info["hidden_descendants"] = hidden
        if prim.IsInstanceProxy():
            info["is_instance_proxy"] = True

    # Kind metadata
    model = Usd.ModelAPI(prim)
    kind = model.GetKind() if model else ""
    info["kind"] = str(kind) if kind else ""

    if include_attrs:
        if time_code is None:
            time_code = Usd.TimeCode.Default()
        wanted = _name_matcher(attr_patterns)
        info["attributes"] = [
            _attr_entry(attr, time_code, full)
            for attr in prim.GetAttributes()
            if wanted(attr.GetName())
        ]
        with contextlib.suppress(Exception):
            info["relationships"] = [
                _relationship_entry(rel) for rel in prim.GetRelationships() if wanted(rel.GetName())
            ]

        if instance_proxies:
            children = [
                str(c.GetPath())
                for c in prim.GetFilteredChildren(
                    Usd.TraverseInstanceProxies(Usd.PrimDefaultPredicate)
                )
            ]
            info["instance_proxies_included"] = True
        else:
            children = [str(c.GetPath()) for c in prim.GetChildren()]
        info["children"] = children

    return info


###### lops.get_stage_info


def _viewport_delegate() -> str | None:
    """Name of the Hydra delegate the first Scene Viewer draws with, if any."""
    with contextlib.suppress(Exception):
        for pane_tab in hou.ui.paneTabs():
            if pane_tab.type() == hou.paneTabType.SceneViewer:
                return str(pane_tab.currentHydraRenderer())
    return None


def _resolve_stage_node(node_path: str) -> tuple[hou.Node, dict[str, Any]]:
    """The LOP whose stage answers for *node_path*, plus what it stands for.

    `/stage` is a network, not a LOP, and get_stage_info refused it with
    "Node is not a LOP node (no stage())", which left "what is the viewport
    showing" to execute_python and displayNode(). A network now answers
    through its display node, and the reply says so.

    Raises:
        hou.OperationFailed: if the node does not exist, or neither it nor
            its display node holds a stage.
    """
    node = hou.node(node_path)
    if node is None:
        raise hou.OperationFailed(f"Node not found: {node_path}")
    if hasattr(node, "stage"):
        return node, {}
    if not hasattr(node, "displayNode"):
        raise hou.OperationFailed(f"Node is not a LOP node (no stage()): {node_path}")
    display = None
    with contextlib.suppress(Exception):
        display = node.displayNode()
    if display is None:
        raise hou.OperationFailed(
            f"Node is not a LOP node (no stage()): {node_path} is a network with "
            "no display node. Set the display flag on a LOP inside it, or pass "
            "that LOP's path."
        )
    if not hasattr(display, "stage"):
        raise hou.OperationFailed(
            f"Node is not a LOP node (no stage()): {node_path}, and its display "
            f"node {display.path()} is not a LOP either."
        )
    context: dict[str, Any] = {
        "requested_path": node_path,
        "resolved_from": "display_node",
        "display_node": display.path(),
    }
    with contextlib.suppress(Exception):
        render = node.renderNode()
        if render is not None:
            context["render_node"] = render.path()
    return display, context


def _get_stage_info(*, node_path: str = "/stage") -> dict[str, Any]:
    """Stage summary: prim count, layers, default prim, up axis, meters per unit.

    Accepts a LOP network (`/stage`) as well as a LOP: the network answers
    through its display node, which is what the viewport shows.
    """
    node, context = _resolve_stage_node(node_path)
    node_path = node.path()
    stage = _get_lop_stage(node_path)

    # Count prims
    prim_count = 0
    for _ in stage.Traverse():
        prim_count += 1

    root_layer = stage.GetRootLayer()
    layers = [layer.identifier for layer in stage.GetUsedLayers()]

    up_axis = UsdGeom.GetStageUpAxis(stage)
    meters_per_unit = UsdGeom.GetStageMetersPerUnit(stage)

    default_prim = stage.GetDefaultPrim()
    default_prim_path = str(default_prim.GetPath()) if default_prim else None

    result: dict[str, Any] = {
        "node_path": node_path,
        "prim_count": prim_count,
        "default_prim": default_prim_path,
        "up_axis": str(up_axis),
        "meters_per_unit": float(meters_per_unit),
        "root_layer": root_layer.identifier,
        "layer_count": len(layers),
        "layers": layers[:50],  # Cap to avoid huge responses
        "frame": float(hou.frame()),
    }
    result.update(context)
    delegate = _viewport_delegate()
    if delegate:
        result["viewport_delegate"] = delegate
    return result


register_handler("lops.get_stage_info", _get_stage_info)


###### lops.get_usd_prim


def _get_usd_prim(
    *,
    node_path: str,
    prim_path: str,
    full: bool = False,
    traverse_instance_proxies: bool = False,
    time: float | None = None,
    attr_patterns: list[str] | str | None = None,
) -> dict[str, Any]:
    """Detailed prim info with type, kind, attributes, relationships, and children.

    Array attributes are summarised (size, element type, head, range) unless
    *full* is set; get_usd_attribute reads one array in windows. An
    instanceable prim answers `children: []` until traverse_instance_proxies
    is set, since its contents live on the prototype.

    Values are read at *time*, or at the current frame without it. They used
    to come from the default slot: a RenderSettings whose `resolution` had a
    default of (2048, 1080) and samples of (1920, 1080) at frame 1 and
    (1280, 720) at frame 24 answered (2048, 1080) on frame 24, which a render
    of that frame never uses. A time-sampled attribute carries
    `time_samples`. *attr_patterns* (globs) narrows attributes and
    relationships.
    """
    stage = _get_lop_stage(node_path)

    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        raise hou.OperationFailed(f"USD prim not found at '{prim_path}' on stage from {node_path}")

    time_code, time_used, time_source = _read_time(time)
    return {
        "node_path": node_path,
        "prim": _prim_to_dict(
            prim,
            include_attrs=True,
            full=bool(full),
            instance_proxies=bool(traverse_instance_proxies),
            time_code=time_code,
            attr_patterns=attr_patterns,
        ),
        "arrays_summarised": not full,
        "time": time_used,
        "time_source": time_source,
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
    traverse_instance_proxies: bool = False,
) -> dict[str, Any]:
    """List prims filtered by type/kind/purpose with optional depth limit.

    With traverse_instance_proxies the walk descends into instanceable prims
    and lists the prims under their prototypes.
    """
    stage = _get_lop_stage(node_path)

    root = stage.GetPrimAtPath(root_path)
    if not root.IsValid():
        raise hou.OperationFailed(f"Root prim not found at '{root_path}' on stage from {node_path}")

    results: list[dict[str, Any]] = []
    truncated = False
    root_sdf_path = root.GetPath()
    root_depth = root_sdf_path.pathElementCount

    # Walk the subtree of *root* only. A string prefix test used to stand in
    # for "is under root", and "/materials/BLD" then matched
    # "/materials/BLD_probes" too; Sdf.Path.HasPrefix compares path
    # elements, and Usd.PrimRange(root) never leaves the subtree at all.
    proxies = bool(traverse_instance_proxies)
    prims = iter(_traverse(stage, None if root_path == "/" else root, proxies))
    prune = getattr(prims, "PruneChildren", None)  # a Usd.PrimRange iterator has it

    for prim in prims:
        prim_path = prim.GetPath()

        # Must be under root_path (element-wise, not character-wise)
        if root_path != "/" and not prim_path.HasPrefix(root_sdf_path):
            continue

        # Depth filter, counted in path elements below root. The walk stops
        # descending at the limit instead of visiting and discarding the whole
        # stage below it.
        if depth is not None:
            below = prim_path.pathElementCount - root_depth
            if below >= depth and prune is not None:
                prune()
            if below > depth:
                continue

        # Type filter
        if prim_type is not None and str(prim.GetTypeName()) != prim_type:
            continue

        # Kind filter
        if kind is not None:
            model = Usd.ModelAPI(prim)
            prim_kind = str(model.GetKind()) if model else ""
            if prim_kind != kind:
                continue

        # Capped lower than the old 5000 (about 450 KB), and said when it cuts.
        if len(results) >= _PRIM_LIST_CAP:
            truncated = True
            break
        results.append(_prim_to_dict(prim))

    return {
        "node_path": node_path,
        "root_path": root_path,
        "filters": {
            "prim_type": prim_type,
            "kind": kind,
            "depth": depth,
        },
        "instance_proxies_included": proxies,
        "count": len(results),
        "truncated": truncated,
        "prims": results,
    }


_PRIM_LIST_CAP = 1000


register_handler("lops.list_usd_prims", _list_usd_prims)


###### lops.get_usd_attribute


def _get_usd_attribute(
    *,
    node_path: str,
    prim_path: str,
    attr_name: str,
    time: float | None = None,
    full: bool = False,
    offset: int = 0,
    limit: int = 64,
) -> dict[str, Any]:
    """Read a USD attribute value at an optional time code.

    A long array answers with a summary as `value` and a window of elements
    as `slice` (offset/limit, default the first 64); full=True returns the
    whole array as `value`.

    A time-sampled attribute (a PointInstancer's `positions`, `protoIndices`)
    has nothing in its default slot, so Get() with the default time code
    answers None -- USD's semantics, and `value: null` next to
    `is_authored: true` read as "the attribute is empty". With no *time*
    given and samples present, the current frame is read instead (the first
    sample when the frame is outside the sampled range), and the reply names
    the time it used and the samples it found.
    """
    stage = _get_lop_stage(node_path)

    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        raise hou.OperationFailed(f"USD prim not found at '{prim_path}' on stage from {node_path}")

    attr = prim.GetAttribute(attr_name)
    if not attr.IsValid():
        raise hou.OperationFailed(f"Attribute '{attr_name}' not found on prim '{prim_path}'")

    samples: list[float] = []
    with contextlib.suppress(Exception):
        samples = [float(t) for t in attr.GetTimeSamples()]

    time_used = time
    time_source = "requested" if time is not None else "default"
    if time is None and samples:
        time_used, time_source = _stage_frame(), "stage_frame"
        if time_used is None or not (samples[0] <= time_used <= samples[-1]):
            time_used = samples[0]
            time_source = "first_sample"

    time_code = Usd.TimeCode(time_used) if time_used is not None else Usd.TimeCode.Default()
    value = attr.Get(time_code)

    reply: dict[str, Any] = {
        "node_path": node_path,
        "prim_path": prim_path,
        "attr_name": attr_name,
        "type": str(attr.GetTypeName()),
        "is_authored": attr.IsAuthored(),
        "time": time_used,
        "requested_time": time,
        "time_source": time_source,
    }
    if samples:
        reply["time_samples"] = len(samples)
        reply["time_range"] = [samples[0], samples[-1]]
        if time is None:
            reply["note"] = (
                f"'{attr_name}' is time-sampled ({len(samples)} samples over "
                f"{samples[0]}..{samples[-1]}); no time was given, so it was read "
                f"at {time_used} ({time_source}). Pass time= to pin a frame."
            )
    if full or not _is_usd_array(value) or len(value) <= _ARRAY_SUMMARY_LIMIT:
        reply["value"] = _usd_value_to_python(value, array_limit=None)
        return reply

    offset = max(0, int(offset))
    # At least one: limit=0 answered an empty window with has_more true, so a
    # caller paging until has_more goes false advanced by zero forever.
    limit = max(1, int(limit))
    try:
        # Vt arrays slice natively; islice walked every element up to offset
        # (60 ms at offset 499 000 on a 500k Vec3fArray, against 0.08 ms here).
        page = value[offset : offset + limit]
    except TypeError:  # a sized iterable that does not support slicing
        page = itertools.islice(value, offset, offset + limit)
    window = [_usd_value_to_python(v, array_limit=None) for v in page]
    reply["value"] = _array_summary(value)
    reply["slice"] = {
        "offset": offset,
        "limit": limit,
        "count": len(window),
        "has_more": offset + len(window) < len(value),
        "values": window,
    }
    return reply


register_handler("lops.get_usd_attribute", _get_usd_attribute)


###### lops.get_usd_attributes

#: Rows one get_usd_attributes call returns; the rest is counted, not sent.
_ATTRIBUTE_ROW_CAP = 500


def _prim_pattern(pattern: str) -> re.Pattern:
    """A prim-path glob as a regex.

    `*` and `?` stay inside one path element and `**` crosses them, so
    `/Render/Vars/*` is the RenderVars and `/Render/**` everything under
    /Render.
    """
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def _matching_prims(
    stage: Usd.Stage, node_path: str, prims: list[str], instance_proxies: bool
) -> list[Usd.Prim]:
    """Prims named by *prims*: exact paths looked up, globs matched on one walk.

    Raises:
        hou.OperationFailed: if an exact path names no prim.
    """
    found: dict[str, Usd.Prim] = {}
    globs = [p for p in prims if any(c in p for c in "*?")]
    for path in prims:
        if path in globs:
            continue
        prim = stage.GetPrimAtPath(path)
        if not prim or not prim.IsValid():
            raise hou.OperationFailed(f"USD prim not found at '{path}' on stage from {node_path}")
        found[str(prim.GetPath())] = prim
    if globs:
        compiled = [_prim_pattern(g) for g in globs]
        for prim in _traverse(stage, None, instance_proxies):
            path = str(prim.GetPath())
            if path not in found and any(c.match(path) for c in compiled):
                found[path] = prim
    return list(found.values())


def _get_usd_attributes(
    *,
    node_path: str,
    prims: list[str] | str,
    attr_patterns: list[str] | str | None = None,
    prim_type: str | None = None,
    relationships: bool = True,
    time: float | None = None,
    full: bool = False,
    traverse_instance_proxies: bool = False,
    limit: int = _ATTRIBUTE_ROW_CAP,
) -> dict[str, Any]:
    """Attributes (and relationships) of many prims as one table.

    Reading `sourceName` off every RenderVar, `lpetag` off every light and
    the `camera` relationship of the render settings took a get_usd_prim per
    prim, each around 130 attributes long on a RenderSettings. One row per
    prim and attribute instead, capped at *limit* with the rest counted.

    *prims*: prim paths or globs (`*` within one path element, `**`
    across); *prim_type* narrows by type name (glob, e.g. `*Light`). Values
    are read at *time* or the current frame, as get_usd_prim does.
    """
    stage = _get_lop_stage(node_path)
    if isinstance(prims, str):
        prims = [prims]
    if not isinstance(prims, (list, tuple)) or not prims:
        raise ValueError("prims must be a prim path or glob, or a non-empty list of them.")
    prims = [str(p) for p in prims]
    wanted = _name_matcher(attr_patterns)
    time_code, time_used, time_source = _read_time(time)
    limit = max(1, int(limit))

    matched_prims = _matching_prims(stage, node_path, prims, bool(traverse_instance_proxies))
    if prim_type:
        matched_prims = [
            prim
            for prim in matched_prims
            if fnmatch.fnmatchcase(str(prim.GetTypeName()), prim_type)
        ]
    rows: list[dict[str, Any]] = []
    matched = 0
    for prim in matched_prims:
        base = {"prim": str(prim.GetPath()), "prim_type": str(prim.GetTypeName())}
        for attr in prim.GetAttributes():
            if not wanted(attr.GetName()):
                continue
            matched += 1
            if len(rows) < limit:
                rows.append({**base, **_attr_entry(attr, time_code, bool(full))})
        if relationships:
            for rel in prim.GetRelationships():
                if not wanted(rel.GetName()):
                    continue
                matched += 1
                if len(rows) < limit:
                    rows.append({**base, **_relationship_entry(rel)})
    return {
        "node_path": node_path,
        "prims": prims,
        "attr_patterns": attr_patterns,
        "prim_type": prim_type,
        "prims_matched": len(matched_prims),
        "time": time_used,
        "time_source": time_source,
        "matched": matched,
        "returned": len(rows),
        "truncated": matched > len(rows),
        "rows": rows,
    }


register_handler("lops.get_usd_attributes", _get_usd_attributes)


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
    traverse_instance_proxies: bool = False,
) -> dict[str, Any]:
    """Prim counts broken down by type under the given root.

    Without traverse_instance_proxies, instanced geometry is counted once per
    prototype, not once per instance; `instanceable_prims` says whether that
    is happening.
    """
    stage = _get_lop_stage(node_path)

    type_counts: dict[str, int] = {}
    total = 0
    instanceable = 0

    root = stage.GetPrimAtPath(prim_path)
    if not root.IsValid():
        raise hou.OperationFailed(f"Root prim not found at '{prim_path}' on stage from {node_path}")
    # Same test as list_usd_prims: a path, not a string prefix.
    proxies = bool(traverse_instance_proxies)
    prims = _traverse(stage, None if prim_path == "/" else root, proxies)
    for prim in prims:
        total += 1
        type_name = str(prim.GetTypeName()) or "(untyped)"
        type_counts[type_name] = type_counts.get(type_name, 0) + 1
        with contextlib.suppress(Exception):
            if prim.IsInstanceable():
                instanceable += 1

    # Sort by count descending
    sorted_types = sorted(type_counts.items(), key=lambda x: -x[1])

    result: dict[str, Any] = {
        "node_path": node_path,
        "prim_path": prim_path,
        "total_prims": total,
        "type_counts": dict(sorted_types),
        "instance_proxies_included": proxies,
        "instanceable_prims": instanceable,
    }
    if instanceable and not proxies:
        result["note"] = (
            f"{instanceable} instanceable prim(s) were counted without their "
            f"contents. Pass traverse_instance_proxies=true to count the "
            f"geometry under their prototypes."
        )
    return result


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

    def _walk(path: Sdf.Path) -> None:
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

    # Set prim_path parameter if the node type has one. The reply used to echo
    # prim_path back even for types with neither parm (assignmaterial,
    # materiallibrary), as if it had been applied.
    prim_path_applied = None
    if prim_path is not None:
        parm = node.parm("primpath")
        if parm is None:
            parm = node.parm("primpattern")
        prim_path_applied = parm is not None
        if parm is not None:
            parm.set(prim_path)

    place_new_node(node)
    _focus_network_editor(node)

    return {
        "node_path": node.path(),
        "type": node.type().name(),
        "name": node.name(),
        "prim_path": prim_path,
        **(
            {}
            if prim_path_applied is not False
            else {
                "prim_path_applied": False,
                "warning": f"{node.type().name()} has no primpath or primpattern parm; prim_path was not set.",
            }
        ),
    }


register_handler("lops.create_lop_node", _create_lop_node)


###### lops.set_usd_attribute


def _edit_attributes_after(node: hou.Node, node_name: str, prim_path: str, values: dict) -> dict:
    """Set USD attributes with a Python LOP spliced in after *node*.

    The LOP used to hang off *node* with nothing reading it: the downstream
    wiring and the display flag stayed on *node*, so the viewport and every ROP
    kept the old stage while the call said success. A missing prim or
    attribute, or a Set() that returns False, only skipped a line.

    Returns python_node, errors (from the cook) and the values read back.
    """
    lines = [
        "node = hou.pwd()",
        "stage = node.editableStage()",
        f"prim = stage.GetPrimAtPath({prim_path!r})",
        "if not prim or not prim.IsValid():",
        f"    raise RuntimeError('Prim not found: ' + {prim_path!r})",
    ]
    for attr_name, value in values.items():
        lines += [
            f"attr = prim.GetAttribute({attr_name!r})",
            "if not attr or not attr.IsValid():",
            f"    raise RuntimeError('No attribute ' + {attr_name!r} + ' on ' + {prim_path!r})",
            f"if not attr.Set({value!r}):",
            f"    raise RuntimeError('USD refused the value for ' + {attr_name!r})",
        ]
    python_node = node.parent().createNode("pythonscript", node_name=node_name)
    python_node.parm("python").set("\n".join(lines))
    # Splice: whatever read node now reads the edit, and so does the viewer.
    readers = [(c.outputNode(), c.inputIndex()) for c in node.outputConnections()]
    for reader, index in readers:
        reader.setInput(index, python_node)
    python_node.setInput(0, node)
    moved_flags = []
    for flag, setter in (
        ("isDisplayFlagSet", "setDisplayFlag"),
        ("isRenderFlagSet", "setRenderFlag"),
    ):
        with contextlib.suppress(Exception):
            if getattr(node, flag)():
                getattr(python_node, setter)(True)
                moved_flags.append(setter)
    place_new_node(python_node)
    with contextlib.suppress(hou.OperationFailed):
        python_node.cook(force=True)
    errors = [e.strip() for e in python_node.errors()]
    if errors:
        # A failed edit left spliced in would break every node downstream of
        # it: put the wiring and the flags back and remove it.
        for reader, index in readers:
            reader.setInput(index, node)
        for setter in moved_flags:
            with contextlib.suppress(Exception):
                getattr(node, setter)(True)
        python_node.destroy()
        return {"python_node": None, "errors": errors, "read_back": {}}
    _focus_network_editor(python_node)
    read_back: dict = {}
    with contextlib.suppress(Exception):
        prim = python_node.stage().GetPrimAtPath(prim_path)
        for attr_name in values:
            read_back[attr_name] = _usd_value_to_python(prim.GetAttribute(attr_name).Get())
    return {"python_node": python_node.path(), "errors": errors, "read_back": read_back}


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

    edit = _edit_attributes_after(node, "set_usd_attr_auto", prim_path, {attr_name: value})
    result = {
        "node_path": node_path,
        "python_node": edit["python_node"],
        "prim_path": prim_path,
        "attr_name": attr_name,
        "success": not edit["errors"],
    }
    if edit["errors"]:
        result["errors"] = edit["errors"]
        result["rolled_back"] = True
    else:
        result["value"] = edit["read_back"].get(attr_name)
    return result


register_handler("lops.set_usd_attribute", _set_usd_attribute)


###### lops.get_usd_materials


# Geometry paths listed per material; the count is always complete.
_RENDERED_ON_CAP = 50


def _get_usd_materials(*, node_path: str) -> dict[str, Any]:
    """List all materials with their bindings.

    `bound_to` is where a binding is authored (a direct allPurpose binding);
    `rendered_on` / `rendered_on_count` are the gprims that resolve to the
    material for rendering, inherited and collection bindings included.
    get_usd_bound_material says why for a given prim.
    """
    stage = _get_lop_stage(node_path)

    materials: list[dict[str, Any]] = []
    bindings_map: dict[str, list[str]] = {}
    # Direct bindings are matched against the materials after the walk, since
    # a binding can precede its material in traversal order.
    direct: list[tuple[str, str]] = []
    gprims = []

    # One walk collects materials, direct bindings and gprims.
    for prim in stage.Traverse():
        with contextlib.suppress(Exception):
            bound = UsdShade.MaterialBindingAPI(prim).GetDirectBinding()
            bound_path = str(bound.GetMaterialPath())
            if bound_path:
                direct.append((bound_path, str(prim.GetPath())))
        with contextlib.suppress(Exception):
            if prim.IsA(UsdGeom.Gprim):
                gprims.append(prim)
                continue
        if prim.IsA(UsdShade.Material):
            mat_path = str(prim.GetPath())
            mat = UsdShade.Material(prim)
            mat_info: dict[str, Any] = {
                "path": mat_path,
                "name": prim.GetName(),
            }
            # Surface outputs, one per render context. A /mat material imported
            # through a Material Library carries two: the universal one, wired
            # to a UsdPreviewSurface for viewports and Storm, and "mtlx", wired
            # to the MaterialX shader, which is what Karma renders. Reporting
            # only the universal one made get_material_info and this tool
            # disagree about a material's shader (#39).
            surfaces: dict[str, str] = {}
            for output in mat.GetSurfaceOutputs():
                connected = output.GetConnectedSource()
                if not (connected and connected[0]):
                    continue
                # "surface" for the universal output, "mtlx:surface" otherwise
                context = output.GetBaseName().removesuffix(":surface") or "surface"
                surfaces[context] = str(connected[0].GetPath())
            if surfaces:
                mat_info["surface_shaders"] = surfaces
                mat_info["surface_shader"] = surfaces.get(
                    "mtlx", surfaces.get("surface", next(iter(surfaces.values())))
                )
            displacement = mat.GetDisplacementOutput()
            if displacement:
                connected = displacement.GetConnectedSource()
                if connected and connected[0]:
                    mat_info["displacement_shader"] = str(connected[0].GetPath())

            materials.append(mat_info)
            bindings_map[mat_path] = []

    for mat_path, prim_path in direct:
        if mat_path in bindings_map:
            bindings_map[mat_path].append(prim_path)

    # What each material is rendered on. bound_to only names the prims a
    # binding is authored on, so geometry bound through a parent or a
    # collection looked unbound; this resolves every gprim the way Karma does
    # (purpose "full"), in one batch.
    rendered_on: dict[str, list[str]] = {}
    with contextlib.suppress(Exception):
        if gprims:
            resolved, _ = UsdShade.MaterialBindingAPI.ComputeBoundMaterials(
                gprims, UsdShade.Tokens.full
            )
            for prim, material in zip(gprims, resolved, strict=False):
                if material:
                    rendered_on.setdefault(str(material.GetPath()), []).append(str(prim.GetPath()))

    # Attach bindings to materials
    for mat in materials:
        mat["bound_to"] = bindings_map.get(mat["path"], [])
        on = rendered_on.get(mat["path"], [])
        mat["rendered_on_count"] = len(on)
        mat["rendered_on"] = on[:_RENDERED_ON_CAP]

    return {
        "node_path": node_path,
        "count": len(materials),
        "materials": materials,
    }


register_handler("lops.get_usd_materials", _get_usd_materials)


###### lops.get_usd_bound_material

# The purpose Karma renders with is "full", and ComputeBoundMaterial("full")
# falls back to an allPurpose binding by itself. allPurpose ("all" here) is
# the narrowest query, not a union: it ignores a full-purpose binding.
_BINDING_PURPOSES = {"full": "full", "preview": "preview", "all": "allPurpose"}


def _binding_source(prim_path: str, rel: Any) -> dict[str, Any]:
    """Where a resolved binding comes from: the prim, an ancestor, or a collection."""
    source: dict[str, Any] = {}
    with contextlib.suppress(Exception):
        source["relationship"] = str(rel.GetPath())
    binding_prim = None
    with contextlib.suppress(Exception):
        binding_prim = str(rel.GetPrim().GetPath())
        source["binding_prim"] = binding_prim
    is_collection = False
    with contextlib.suppress(Exception):
        is_collection = bool(
            UsdShade.MaterialBindingAPI.CollectionBinding.IsCollectionBindingRel(rel)
        )
    if is_collection:
        source["kind"] = "collection"
        # material:binding:collection:preview:furn names the purpose too; the
        # API answers with the collection itself (/set.collection:furn).
        with contextlib.suppress(Exception):
            binding = UsdShade.MaterialBindingAPI.CollectionBinding(rel)
            source["collection"] = str(binding.GetCollectionPath())
    elif binding_prim == prim_path:
        source["kind"] = "direct"
    else:
        source["kind"] = "inherited"
    with contextlib.suppress(Exception):
        source["strength"] = str(UsdShade.MaterialBindingAPI.GetMaterialBindingStrength(rel))
    return source


def _binding_targets(rel: Any) -> list[str]:
    with contextlib.suppress(Exception):
        return [str(target) for target in rel.GetTargets()]
    return []


def _get_usd_bound_material(
    *, node_path: str, prim_paths: Any, purpose: str = "full", **_: Any
) -> dict[str, Any]:
    """The material each prim renders with, and why.

    get_usd_materials reports where bindings are authored; a prim bound
    through its parent, or through a collection, is not listed there. This
    resolves the binding the way the renderer does (ComputeBoundMaterials, for
    the whole batch at once) and names the source: direct, inherited from
    which ancestor, or which collection. A binding whose material prim does
    not exist is reported as such, not as "unbound".
    """
    stage = _get_lop_stage(node_path)
    token_name = _BINDING_PURPOSES.get(str(purpose).lower())
    if token_name is None:
        raise ValueError(f"purpose must be one of {sorted(_BINDING_PURPOSES)}, got {purpose!r}.")
    token = getattr(UsdShade.Tokens, token_name)
    if isinstance(prim_paths, str):
        prim_paths = [prim_paths]
    if not isinstance(prim_paths, (list, tuple)) or not prim_paths:
        raise ValueError("prim_paths must be a prim path or a non-empty list of them.")

    rows: list[dict[str, Any]] = []
    found: list[tuple[dict[str, Any], Any]] = []
    for raw in prim_paths:
        prim_path = str(raw)
        prim = stage.GetPrimAtPath(prim_path)
        row: dict[str, Any] = {"prim": prim_path, "material": None}
        if not prim or not prim.IsValid():
            row["error"] = "prim not found on this stage"
        else:
            found.append((row, prim))
        rows.append(row)

    if found:
        materials, rels = UsdShade.MaterialBindingAPI.ComputeBoundMaterials(
            [prim for _, prim in found], token
        )
        for (row, prim), material, rel in zip(found, materials, rels, strict=False):
            if material and material.GetPrim().IsValid():
                row["material"] = str(material.GetPath())
            if rel:
                row["source"] = _binding_source(row["prim"], rel)
                if row["material"] is None:
                    # Bound, to a material prim that is not on the stage.
                    row["missing_material"] = _binding_targets(rel)
            with contextlib.suppress(Exception):
                # Purpose-specific first, then all-purpose, the renderer's own
                # fallback. assignmaterial authors the all-purpose relationship,
                # so asking only for "full" answered null for a prim whose
                # source said kind: direct.
                api = UsdShade.MaterialBindingAPI(prim)
                row["direct_binding"] = None
                for which in dict.fromkeys((token, UsdShade.Tokens.allPurpose)):
                    path = str(api.GetDirectBinding(which).GetMaterialPath())
                    if path:
                        row["direct_binding"] = path
                        break

    return {
        "node_path": node_path,
        "purpose": str(purpose).lower(),
        "count": len(rows),
        "bound": sum(1 for row in rows if row["material"]),
        "missing_material": sum(1 for row in rows if "missing_material" in row),
        "not_found": sum(1 for row in rows if "error" in row),
        "bindings": rows,
    }


register_handler("lops.get_usd_bound_material", _get_usd_bound_material)


###### lops.find_usd_prims


def _find_usd_prims(
    *,
    node_path: str,
    pattern: str,
    traverse_instance_proxies: bool = False,
) -> dict[str, Any]:
    """Search prims by path pattern (supports * and ** wildcards).

    With traverse_instance_proxies the search reaches prims under
    instanceable prototypes, which the default walk never visits.
    """
    stage = _get_lop_stage(node_path)

    import fnmatch

    proxies = bool(traverse_instance_proxies)
    results: list[dict[str, Any]] = []
    truncated = False
    for prim in _traverse(stage, None, proxies):
        prim_path = str(prim.GetPath())
        if fnmatch.fnmatch(prim_path, pattern) or pattern in prim_path:
            if len(results) >= _PRIM_LIST_CAP:
                truncated = True
                break
            results.append(_prim_to_dict(prim))

    return {
        "node_path": node_path,
        "pattern": pattern,
        "instance_proxies_included": proxies,
        "count": len(results),
        "truncated": truncated,
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
        raise hou.OperationFailed(f"USD prim not found at '{prim_path}' on stage from {node_path}")

    prim_index = prim.GetPrimIndex()

    # Pcp.PrimIndex has no nodeRange in current USD builds; walk the
    # composition graph from rootNode instead.
    def _walk_nodes(node):
        yield node
        for child in node.children:
            yield from _walk_nodes(child)

    arcs: list[dict[str, Any]] = []
    if prim_index.IsValid():
        for node in _walk_nodes(prim_index.rootNode):
            arc_info: dict[str, Any] = {
                "arc_type": str(node.arcType),
                "layer": str(node.layerStack.identifier.rootLayer) if node.layerStack else None,
                "path": str(getattr(node, "path", "")),
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
                references.append(
                    {
                        "asset": str(ref.assetPath) if ref.assetPath else None,
                        "prim_path": str(ref.primPath) if ref.primPath else None,
                    }
                )
        if hasattr(spec, "payloadList"):
            for pl in spec.payloadList.prependedItems:
                payloads.append(
                    {
                        "asset": str(pl.assetPath) if pl.assetPath else None,
                        "prim_path": str(pl.primPath) if pl.primPath else None,
                    }
                )
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
        raise hou.OperationFailed(f"USD prim not found at '{prim_path}' on stage from {node_path}")

    variant_sets: list[dict[str, Any]] = []
    vsets = prim.GetVariantSets()
    for name in vsets.GetNames():
        vset = vsets.GetVariantSet(name)
        variant_sets.append(
            {
                "name": name,
                "variants": vset.GetVariantNames(),
                "selection": vset.GetVariantSelection(),
            }
        )

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
            f"(0..{len(layers) - 1}) for stage from {node_path}"
        )

    layer = layers[layer_index]

    # Gather authored prims in this layer
    authored_prims: list[str] = []

    def _walk_layer(path: Sdf.Path) -> None:
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


# Houdini 20.5+ ships no rectlight/spherelight/disklight/cylinderlight LOPs:
# those shapes are the generic "light" node (light::2.0) with its lighttype
# menu set. Only dome and distant lights keep a node type of their own.
# Values are (node type, lighttype menu token or None).
_LOP_LIGHT_TYPES: dict[str, tuple[str, str | None]] = {
    "dome": ("domelight", None),
    "distant": ("distantlight", None),
    "rect": ("light", "UsdLuxRectLight"),
    "sphere": ("light", "UsdLuxSphereLight"),
    "disk": ("light", "UsdLuxDiskLight"),
    "cylinder": ("light", "UsdLuxCylinderLight"),
    "point": ("light", "point"),
}


def _lop_light_type(light_type: str) -> tuple[str, str | None]:
    """(node type, lighttype menu token or None) for "rect", "dome", ..."""
    entry = _LOP_LIGHT_TYPES.get(light_type)
    if entry is None:
        available = sorted(_LOP_LIGHT_TYPES)
        raise hou.OperationFailed(
            f"Unknown light type: '{light_type}'. Available types: {available}"
        )
    return entry


def _set_light_shape(node: hou.Node, shape: str | None) -> None:
    """Pick *shape* on a generic light node's lighttype menu; no-op for None."""
    if shape is None:
        return
    parm = node.parm("lighttype")
    if parm is not None:
        parm.set(shape)


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

    lop_type, shape = _lop_light_type(light_type)
    node = parent.createNode(lop_type, node_name=name)
    _set_light_shape(node, shape)

    # Set intensity ("inputs:intensity" punycodes to xn__inputsintensity_i0a)
    intensity_parm = node.parm("xn__inputsintensity_i0a")
    if intensity_parm is None:
        intensity_parm = node.parm("intensity")
    if intensity_parm is not None:
        intensity_parm.set(intensity)

    # Set color
    if color is not None and len(color) >= 3:
        for i, suffix in enumerate(["r", "g", "b"]):
            parm = node.parm(f"xn__inputscolor_zta{suffix}")
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

    place_new_node(node)
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

    if not properties:
        return {"prim_path": prim_path, "updated_properties": [], "note": "No properties to set"}
    usd_names = {name: attr_name_map.get(name, name) for name in properties}
    edit = _edit_attributes_after(
        node,
        "set_light_props_auto",
        prim_path,
        {usd_names[name]: value for name, value in properties.items()},
    )
    result = {
        "prim_path": prim_path,
        "python_node": edit["python_node"],
        "success": not edit["errors"],
        "updated_properties": [] if edit["errors"] else list(properties),
    }
    if edit["errors"]:
        result["errors"] = edit["errors"]
        result["rolled_back"] = True
    else:
        result["values"] = {name: edit["read_back"].get(usd_names[name]) for name in properties}
    return result


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
            {
                "type": "distant",
                "name": "key_light",
                "intensity": 1.0,
                "color": [1.0, 0.95, 0.9],
                "rx": -45,
                "ry": -30,
            },
            {
                "type": "distant",
                "name": "fill_light",
                "intensity": 0.4,
                "color": [0.85, 0.9, 1.0],
                "rx": -30,
                "ry": 45,
            },
            {
                "type": "distant",
                "name": "rim_light",
                "intensity": 0.6,
                "color": [1.0, 1.0, 1.0],
                "rx": -15,
                "ry": 160,
            },
        ],
        "studio": [
            {
                "type": "rect",
                "name": "softbox_key",
                "intensity": 2.0,
                "color": [1.0, 0.98, 0.95],
                "tx": -2,
                "ty": 3,
                "tz": 2,
                "rx": -40,
                "ry": -30,
            },
            {
                "type": "rect",
                "name": "softbox_fill",
                "intensity": 1.0,
                "color": [0.9, 0.95, 1.0],
                "tx": 2,
                "ty": 2.5,
                "tz": 2,
                "rx": -35,
                "ry": 30,
            },
            {
                "type": "rect",
                "name": "softbox_back",
                "intensity": 1.5,
                "color": [1.0, 1.0, 1.0],
                "tx": 0,
                "ty": 3,
                "tz": -3,
                "rx": -20,
                "ry": 180,
            },
        ],
        "outdoor": [
            {"type": "dome", "name": "sky_dome", "intensity": 0.3, "color": [0.7, 0.85, 1.0]},
            {
                "type": "distant",
                "name": "sun",
                "intensity": 1.5,
                "color": [1.0, 0.95, 0.85],
                "rx": -50,
                "ry": -30,
            },
        ],
        "hdri": [
            {"type": "dome", "name": "hdri_dome", "intensity": 1.0, "color": [1.0, 1.0, 1.0]},
        ],
    }

    preset_config = presets.get(preset)
    if preset_config is None:
        available = sorted(presets.keys())
        raise hou.OperationFailed(
            f"Unknown lighting preset: '{preset}'. Available presets: {available}"
        )

    created_nodes: list[str] = []
    previous: hou.Node | None = None

    for light_def in preset_config:
        lop_type, shape = _lop_light_type(light_def["type"])
        node = parent.createNode(lop_type, node_name=light_def.get("name"))
        _set_light_shape(node, shape)

        # Chain the lights so the last node's stage contains the whole rig.
        if previous is not None:
            node.setInput(0, previous)
        previous = node

        # Set intensity with multiplier. USD light parms are punycoded
        # ("inputs:intensity" -> xn__inputsintensity_i0a).
        base_intensity = light_def.get("intensity", 1.0)
        final_intensity = base_intensity * intensity_mult
        intensity_parm = node.parm("xn__inputsintensity_i0a")
        if intensity_parm is None:
            intensity_parm = node.parm("intensity")
        if intensity_parm is not None:
            intensity_parm.set(final_intensity)

        # Set color ("inputs:color" components -> xn__inputscolor_zta{r,g,b})
        light_color = light_def.get("color")
        if light_color:
            for i, suffix in enumerate(["r", "g", "b"]):
                parm = node.parm(f"xn__inputscolor_zta{suffix}")
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

        place_new_node(node)
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
