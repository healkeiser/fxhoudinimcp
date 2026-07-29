"""JSON coercion for HOM values.

hwebserver JSON-encodes whatever an API function returns, and it does so
*after* the handler has already succeeded -- outside its own try/except (see
``APIUrlHandler._call_api``, which calls ``_check_result`` past the ``except``
clauses). A value like ``hou.Ramp`` therefore raises ``TypeError`` inside the
encoder, the exception escapes to the C++ caller, and the client receives a
bare ``HTTP 500`` with no way to tell a serialisation failure from a genuine
Houdini error.

``to_jsonable`` converts the HOM types that actually turn up in handler
results, and falls back to ``repr`` for anything unrecognised, so one exotic
parameter can never take down a whole response.
"""

from __future__ import annotations

import contextlib

# Built-in
from typing import Any

# Third-party
import hou

###### Constants

# Guards against cyclic or pathologically nested structures.
_MAX_DEPTH = 12

# Longest repr kept for a type we have no specific rule for.
_MAX_REPR = 200


def _hou_types(*names: str) -> tuple[type, ...]:
    """Resolve HOM class names to a tuple usable with isinstance().

    Names that are missing on this Houdini version -- or that are not classes,
    which is the case when ``hou`` is a test double -- are skipped.
    ``isinstance(x, ())`` is False, so an empty tuple is harmless.
    """
    resolved = []
    for name in names:
        candidate = getattr(hou, name, None)
        if isinstance(candidate, type):
            resolved.append(candidate)
    return tuple(resolved)


_VECTORS = _hou_types("Vector2", "Vector3", "Vector4")
_MATRICES = _hou_types("Matrix2", "Matrix3", "Matrix4")
_QUATERNIONS = _hou_types("Quaternion")
_RAMPS = _hou_types("Ramp")
_GEOMETRIES = _hou_types("Geometry")
_COLORS = _hou_types("Color")
_NODES = _hou_types("Node", "NetworkMovableItem")
_PARMS = _hou_types("Parm", "ParmTuple")


###### Individual HOM types


def ramp_to_dict(ramp: Any) -> dict:
    """Return a ``hou.Ramp`` as its constructor arguments.

    Keys, values and basis together round-trip back into ``hou.Ramp``, which
    is what a client needs to inspect or rebuild the ramp. Colour ramps yield
    3-tuples for their values; float ramps yield floats.
    """
    result: dict[str, Any] = {"type": "Ramp"}
    with contextlib.suppress(Exception):
        result["is_color"] = ramp.isColor()
    with contextlib.suppress(Exception):
        result["basis"] = [b.name() for b in ramp.basis()]
    with contextlib.suppress(Exception):
        result["keys"] = list(ramp.keys())
    with contextlib.suppress(Exception):
        result["values"] = [list(v) if isinstance(v, tuple) else v for v in ramp.values()]
    return result


def geometry_summary(geo: Any) -> dict:
    """Return a cheap summary of a ``hou.Geometry``.

    Counts come from intrinsics rather than ``len(geo.points())``: the latter
    materialises a Python tuple of point objects, which is ruinous on heavy
    geometry and this runs on every parameter of every inspected node.
    """
    summary: dict[str, Any] = {"type": "Geometry"}
    for key, intrinsic in (
        ("point_count", "pointcount"),
        ("prim_count", "primitivecount"),
        ("vertex_count", "vertexcount"),
    ):
        with contextlib.suppress(Exception):
            summary[key] = geo.intrinsicValue(intrinsic)
    return summary


###### Entry point


def to_jsonable(value: Any, _depth: int = 0) -> Any:
    """Convert *value* into something ``json.dumps`` accepts.

    Containers are walked recursively. Unrecognised objects degrade to a
    truncated ``repr`` rather than raising, because the caller's alternative
    is an opaque HTTP 500.
    """
    if _depth > _MAX_DEPTH:
        return repr(value)[:_MAX_REPR]

    # Fast path: already JSON-native. bool is checked via isinstance, which
    # also covers it as a subclass of int.
    if value is None or isinstance(value, (bool, int, float, str)):
        return value

    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")

    if isinstance(value, dict):
        return {str(key): to_jsonable(item, _depth + 1) for key, item in value.items()}

    # HOM vector/matrix types are iterable, so they must be matched before the
    # generic sequence branch below.
    if _VECTORS and isinstance(value, _VECTORS):
        return list(value)

    if _MATRICES and isinstance(value, _MATRICES):
        try:
            return [list(row) for row in value.asTupleOfTuples()]
        except Exception:
            return repr(value)[:_MAX_REPR]

    if _QUATERNIONS and isinstance(value, _QUATERNIONS):
        return list(value)

    if _COLORS and isinstance(value, _COLORS):
        try:
            return list(value.rgb())
        except Exception:
            return repr(value)[:_MAX_REPR]

    if _RAMPS and isinstance(value, _RAMPS):
        return ramp_to_dict(value)

    if _GEOMETRIES and isinstance(value, _GEOMETRIES):
        return geometry_summary(value)

    if _NODES and isinstance(value, _NODES):
        try:
            return value.path()
        except Exception:
            return repr(value)[:_MAX_REPR]

    if _PARMS and isinstance(value, _PARMS):
        try:
            return value.path()
        except Exception:
            return repr(value)[:_MAX_REPR]

    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(item, _depth + 1) for item in value]

    # HOM enums (hou.rampBasis, hou.parmTemplateType, ...) all expose name().
    name = getattr(value, "name", None)
    if callable(name):
        try:
            return name()
        except Exception:
            pass

    return repr(value)[:_MAX_REPR]


def json_default(value: Any) -> Any:
    """``default=`` hook for ``json.dumps``.

    Only called for objects the encoder cannot handle, so the happy path pays
    nothing. Must never return another unserialisable object: every branch of
    ``to_jsonable`` bottoms out in a JSON-native type.
    """
    return to_jsonable(value)
