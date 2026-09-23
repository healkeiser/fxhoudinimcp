"""Houdini-side handlers for parameter operations.

Provides 14 command handlers for reading, writing, and managing
node parameters, expressions, channel references, and spare parameters.
"""

from __future__ import annotations

import contextlib
import re

# Built-in
from difflib import get_close_matches
from typing import Any

# Third-party
import hou

# Internal
from fxhoudinimcp_server.dispatcher import register_handler
from fxhoudinimcp_server.serialize import geometry_summary

###### Helpers


def _resolve_node(node_path: str) -> hou.Node:
    """Return the hou.Node at *node_path* or raise."""
    node = hou.node(node_path)
    if node is None:
        raise ValueError(f"Node not found: {node_path}")
    return node


def _available_parm_names(node: hou.Node) -> list[str]:
    """Return sorted list of parameter names on a node."""
    return sorted(p.name() for p in node.parms())


def _resolve_parm(node_path: str, parm_name: str) -> hou.Parm:
    """Return the hou.Parm on *node_path* named *parm_name* or raise."""
    node = _resolve_node(node_path)
    parm = node.parm(parm_name)
    if parm is None:
        available = _available_parm_names(node)
        close = get_close_matches(parm_name, available, n=3, cutoff=0.4)
        hint = f" Did you mean: {close}?" if close else ""
        raise ValueError(
            f"Parameter '{parm_name}' not found on node '{node_path}'.{hint} "
            f"Available parameters: {available}"
        )
    return parm


def _parm_type_name(parm_template: hou.ParmTemplate) -> str:
    """Return a human-readable type string for a parameter template."""
    return parm_template.type().name()


def _serialize_value(value: Any) -> Any:
    """Convert a value to a JSON-safe Python type."""
    if isinstance(value, hou.Vector2):
        return list(value)
    if isinstance(value, hou.Vector3):
        return list(value)
    if isinstance(value, hou.Vector4):
        return list(value)
    if isinstance(value, hou.Matrix3):
        return [list(row) for row in value.asTupleOfTuples()]
    if isinstance(value, hou.Matrix4):
        return [list(row) for row in value.asTupleOfTuples()]
    if isinstance(value, hou.Ramp):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_serialize_value(v) for v in value]
    return value


def _data_parm_summary(parm: hou.Parm, pt: hou.ParmTemplate) -> dict[str, Any]:
    """What a Data parameter holds, never the blob itself.

    Counts come from serialize.geometry_summary (intrinsics), not from
    parm.asData(): that serialises the whole geometry to a string on the main
    thread, which is ruinous on a heavy stash and measures characters, not
    bytes.
    """
    summary: dict[str, Any] = {"is_set": False}
    with contextlib.suppress(Exception):
        summary["data_parm_type"] = pt.dataParmType().name()
    value = None
    with contextlib.suppress(Exception):
        value = parm.eval()
    if isinstance(value, hou.Geometry):
        # Set, possibly to an empty geometry: the counts say which.
        summary["is_set"] = True
        summary["geometry"] = geometry_summary(value)
    elif isinstance(value, dict):
        # A KeyValueDictionary evaluates to {} when empty.
        summary["is_set"] = bool(value)
        summary["key_count"] = len(value)
    elif value is not None:
        summary["is_set"] = True
        summary["value_type"] = type(value).__name__
    return summary


def _data_parm_value(parm: hou.Parm, pt: hou.ParmTemplate) -> dict[str, Any] | None:
    """For a Data parameter, the fields a reader reports; None for any other.

    eval() on a Data parameter is a hou.Geometry or None and rawValue() is
    empty either way, so `value` alone cannot tell "unset" from "set to an
    empty geometry". `value` stays the geometry summary it always serialised
    to; `data` says whether the blob is set and what it holds.
    """
    if _parm_type_name(pt) != "Data":
        return None
    data = _data_parm_summary(parm, pt)
    value = data.get("geometry")
    if "key_count" in data:
        # A KeyValueDictionary always answered with the dictionary itself.
        with contextlib.suppress(Exception):
            value = _serialize_value(parm.eval())
    return {"value": value, "data": data}


def _template_to_dict(pt: hou.ParmTemplate) -> dict[str, Any]:
    """Convert a ParmTemplate to a JSON-serialisable dictionary."""
    info: dict[str, Any] = {
        "name": pt.name(),
        "label": pt.label(),
        "type": _parm_type_name(pt),
        "num_components": pt.numComponents(),
        "is_hidden": pt.isHidden(),
    }

    # Default value
    try:
        info["default_value"] = list(pt.defaultValue())
    except Exception:
        try:
            info["default_value"] = pt.defaultValue()
        except Exception:
            info["default_value"] = None

    # Range
    try:
        info["min"] = pt.minValue()
        info["max"] = pt.maxValue()
        info["min_is_strict"] = pt.minIsStrict()
        info["max_is_strict"] = pt.maxIsStrict()
    except Exception:
        pass

    # Menu items — capped at 50 to avoid enormous enum lists
    try:
        items = pt.menuItems()
        labels = pt.menuLabels()
        if items:
            info["menu_items"] = list(items)[:50]
            info["menu_labels"] = list(labels)[:50]
            if len(items) > 50:
                info["menu_items_truncated"] = True
    except Exception:
        pass

    # Naming scheme (for multi-component parms)
    with contextlib.suppress(Exception):
        info["naming_scheme"] = pt.namingScheme().name()

    # Conditionals and tags omitted — internal Houdini UI metadata,
    # not useful for LLM-driven parameter setting.

    return info


###### Handler: parameters.get_parameter


def _get_parameter(node_path: str, parm_name: str, **_: Any) -> dict[str, Any]:
    """Get the current value, expression, keyframe info, and metadata of a parameter."""
    parm = _resolve_parm(node_path, parm_name)
    pt = parm.parmTemplate()

    data_parm = _data_parm_value(parm, pt)
    result: dict[str, Any] = {
        "node_path": node_path,
        "parm_name": parm_name,
        "value": data_parm["value"] if data_parm else _serialize_value(parm.eval()),
        "raw_value": _serialize_value(parm.rawValue()),
        "parm_type": _parm_type_name(pt),
        "is_locked": parm.isLocked(),
        "is_at_default": parm.isAtDefault(),
    }
    if data_parm:
        result["data"] = data_parm["data"]

    # Expression
    try:
        result["expression"] = parm.expression()
        result["expression_language"] = parm.expressionLanguage().name()
    except hou.OperationFailed:
        result["expression"] = None
        result["expression_language"] = None

    # Keyframes
    keyframes = parm.keyframes()
    result["keyframe_count"] = len(keyframes)

    return result


register_handler("parameters.get_parameter", _get_parameter)


###### Handler: parameters.set_parameter


def _expression_driven(parms: list[hou.Parm]) -> str | None:
    """A sentence naming the first of *parms* driven by an expression, or None.

    Houdini answers a set() on such a parameter with a generic permission
    error ("locked assets, takes, product permissions..."); resolutiony on a
    karmarendersettings is the common case, driven by the autoheight expression
    while res_mode says so (#41).
    """
    for parm in parms:
        try:
            expression = parm.expression()
        except hou.OperationFailed:
            continue
        return (
            f"'{parm.name()}' on {parm.node().path()} is driven by the expression "
            f"{expression!r}, so it cannot be set directly. Set the parameter that "
            f"controls it, or remove the expression with revert_parameter first."
        )
    return None


def _expression_of(parm: hou.Parm) -> str | None:
    """The expression *parm* holds, or None when it holds a plain value."""
    try:
        expression = parm.expression()
    except Exception:
        return None
    return expression if isinstance(expression, str) and expression else None


def _clear_expression(parm: hou.Parm) -> None:
    """Remove *parm*'s expression without evaluating it.

    deleteAllKeyframes() keeps the parm at its current value, so it evaluates
    the expression it removes -- outside a cook, where a Ray SOP's `@N.x` or a
    `$N` stamps "Local variable 'N' not found" on a healthy node, and that
    warning outlives the build. A constant takes the expression's place first,
    so the value kept is that constant; the caller's set() overwrites it.
    """
    with contextlib.suppress(Exception):
        parm.setExpression("0", hou.exprLanguage.Hscript, replace_expression=True)
    with contextlib.suppress(Exception):
        parm.deleteAllKeyframes()


def _values_match(requested: Any, actual: Any) -> bool:
    """Whether a write of *requested* is what *actual* now reads back as."""
    if isinstance(requested, bool) or isinstance(actual, bool):
        return bool(requested) == bool(actual)
    if isinstance(requested, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(requested) - float(actual)) <= 1e-6 * max(1.0, abs(float(actual)))
    return requested == actual


def _referenced_parm(parm: hou.Parm) -> str | None:
    """Path of the parm a pure `ch()` reference points at, or None.

    A parm holding a bare channel reference is a window onto another parm, and
    hou.Parm.set() writes THROUGH it: setting tx on a node whose tx reads
    ch("../b1/sizex") changes b1's sizex, not tx. eval() then answers with the
    value asked for, so the write looks like a plain success while another
    node quietly moved.
    """
    with contextlib.suppress(Exception):
        target = parm.getReferencedParm()
        if target is not None and target.path() != parm.path():
            return str(target.path())
    return None


_WRITTEN_THROUGH_NOTE = (
    "This parameter is a pure channel reference, so the value was written into "
    "the parameter it reads, not into this one. Break the link with "
    "revert_parameter, or set the source directly, if that was not intended."
)

_EXPRESSION_KEPT_NOTE = (
    "The parameter still holds its expression, so the literal did not take. "
    "Set the parameter that drives it, replace the expression with "
    "set_expression, or repeat this call with override_expression=true."
)

_EXPRESSION_KEPT_SAME_VALUE_NOTE = (
    "The value asked for is what the expression evaluates to right now, but the "
    "expression is still there and will keep driving the parameter. "
    + _EXPRESSION_KEPT_NOTE.split(". ", 1)[1]
)


def _raw_string(parm: hou.Parm) -> str | None:
    """The unexpanded text of a String parm (`$JOB/geo/a_$F4.bgeo.sc`), or None."""
    with contextlib.suppress(Exception):
        if parm.parmTemplate().type() == hou.parmTemplateType.String:
            return parm.unexpandedString()
    return None


def _write_parm(parm: hou.Parm, value: Any, override_expression: bool = False) -> dict[str, Any]:
    """Set one parm and report honestly whether the write actually took.

    hou.Parm.set() on a parm that holds an expression does NOT remove the
    expression: eval() keeps answering with it, and the reply used to look
    like a success anyway, the truth only in a `new_value` nobody compared
    against what was asked for. override_expression clears it first, without
    evaluating it (see _clear_expression).

    Whether the expression survived decides `expression_kept`, not whether the
    values differ: zeroing a factory `$N` that evaluates to 0 leaves the
    expression in place just the same. A String parm echoes its raw text next
    to the expanded one, since `$JOB/...` read back as an absolute path looks
    like the very mistake a caller checks for.
    """
    before = _expression_of(parm)
    through = _referenced_parm(parm) if before is not None else None
    if before is not None and override_expression:
        _clear_expression(parm)
        through = None
    parm.set(value)
    after = _expression_of(parm)
    new_value = _serialize_value(parm.eval())
    info: dict[str, Any] = {"new_value": new_value}
    raw = _raw_string(parm)
    if raw is not None:
        info["raw_value"] = raw
    matches = _values_match(value, new_value)
    if after is not None and through is not None and matches:
        # The value did land, in the parm this one reads.
        info["written_through"] = through
        info["expression"] = after
        info["note"] = _WRITTEN_THROUGH_NOTE
    elif after is not None:
        info["expression_kept"] = True
        info["expression"] = after
        info["requested"] = _serialize_value(value)
        if matches:
            info["same_as_evaluated"] = True
        info["note"] = _EXPRESSION_KEPT_SAME_VALUE_NOTE if matches else _EXPRESSION_KEPT_NOTE
    elif before is not None:
        info["expression_removed"] = before
    return info


def _set_tuple(
    node: hou.Node,
    parm_name: str,
    value: list | tuple,
    override_expression: bool = False,
) -> tuple[Any | None, dict[str, Any]]:
    """Apply a list value to the parm tuple of that name; None if there is none.

    A list/tuple value addressed at a vector parameter name (e.g. "size" on a
    box, "t" on a transform, a light's colour) is applied to the whole parm
    tuple, so callers are not forced to know the per-component names.

    Answers `(values, report)`, where *report* carries what _write_parm reports
    for a single parm, per component: which kept an expression, which wrote
    through a channel reference, and the raw text of String components.
    """
    parm_tuple = node.parmTuple(parm_name)
    if parm_tuple is None:
        return None, {}
    if len(value) != len(parm_tuple):
        raise ValueError(
            f"Parameter '{parm_name}' on {node.path()} has "
            f"{len(parm_tuple)} components, got {len(value)} values."
        )
    components = list(parm_tuple)
    through = {
        parm.name(): target
        for parm in components
        if _expression_of(parm) is not None and (target := _referenced_parm(parm)) is not None
    }
    if override_expression:
        for parm in components:
            if _expression_of(parm) is not None:
                _clear_expression(parm)
        through = {}
    try:
        parm_tuple.set(value)
    except hou.PermissionError:
        reason = _expression_driven(components)
        if reason:
            raise ValueError(reason) from None
        raise
    new_value = [_serialize_value(p.eval()) for p in components]
    kept: list[dict[str, Any]] = []
    landed_elsewhere: dict[str, str] = {}
    for index, parm in enumerate(components):
        expression = _expression_of(parm)
        if expression is None:
            continue
        matches = _values_match(value[index], new_value[index])
        if parm.name() in through and matches:
            landed_elsewhere[parm.name()] = through[parm.name()]
            continue
        # Kept whenever the expression survived, equal values or not.
        entry: dict[str, Any] = {
            "component": parm.name(),
            "index": index,
            "expression": expression,
            "requested": _serialize_value(value[index]),
        }
        if matches:
            entry["same_as_evaluated"] = True
        kept.append(entry)
    report: dict[str, Any] = {}
    raw = [_raw_string(p) for p in components]
    if any(r is not None for r in raw):
        report["raw_value"] = raw
    if kept:
        same = all(entry.get("same_as_evaluated") for entry in kept)
        report.update(
            {
                "expression_kept": True,
                "expression_components": kept,
                "requested": [_serialize_value(v) for v in value],
                "note": _EXPRESSION_KEPT_SAME_VALUE_NOTE if same else _EXPRESSION_KEPT_NOTE,
            }
        )
    if landed_elsewhere:
        report["written_through"] = landed_elsewhere
        report.setdefault("note", _WRITTEN_THROUGH_NOTE)
    return new_value, report


def _set_parameter(
    node_path: str,
    parm_name: str,
    value: Any,
    override_expression: bool = False,
    **_: Any,
) -> dict[str, Any]:
    """Set a parameter value, auto-detecting the appropriate type."""
    if isinstance(value, (list, tuple)):
        new_value, report = _set_tuple(
            _resolve_node(node_path), parm_name, value, bool(override_expression)
        )
        if new_value is not None:
            result: dict[str, Any] = {
                "node_path": node_path,
                "parm_name": parm_name,
                "new_value": new_value,
            }
            result.update(report)
            return result

    parm = _resolve_parm(node_path, parm_name)

    try:
        written = _write_parm(parm, value, bool(override_expression))
    except hou.PermissionError:
        reason = _expression_driven([parm])
        if reason:
            raise ValueError(reason) from None
        raise

    result = {"node_path": node_path, "parm_name": parm_name}
    result.update(written)
    return result


register_handler("parameters.set_parameter", _set_parameter)


###### Handler: parameters.set_parameters


def _set_parameters(
    node_path: str,
    params: dict[str, Any],
    override_expression: bool = False,
    **_: Any,
) -> dict[str, Any]:
    """Batch-set multiple parameters on a single node."""
    node = _resolve_node(node_path)
    override = bool(override_expression)

    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    available = _available_parm_names(node)
    for name, value in params.items():
        # A list on a vector name sets the whole tuple, exactly as the single
        # setter does. The batch path used to know only per-component names,
        # which made "prefer set_parameters" and "set a light colour" collide.
        if isinstance(value, (list, tuple)):
            try:
                new_value, report = _set_tuple(node, name, value, override)
            except Exception as exc:
                errors.append({"parm_name": name, "error": str(exc)})
                continue
            if new_value is not None:
                entry: dict[str, Any] = {"parm_name": name, "new_value": new_value}
                entry.update(report)
                results.append(entry)
                continue
        parm = node.parm(name)
        if parm is None:
            close = get_close_matches(name, available, n=3, cutoff=0.4)
            hint = f" Did you mean: {close}?" if close else ""
            errors.append({"parm_name": name, "error": f"Parameter '{name}' not found.{hint}"})
            continue
        try:
            entry = {"parm_name": name}
            entry.update(_write_parm(parm, value, override))
            results.append(entry)
        except Exception as exc:
            errors.append({"parm_name": name, "error": str(exc)})

    # A batch whose `errors` is empty while a parm kept its expression reads as
    # a clean success: name it at the top level too, so a caller that only
    # reads `errors` still sees that a write did not take, or landed elsewhere.
    kept = [entry["parm_name"] for entry in results if entry.get("expression_kept")]
    through = {
        entry["parm_name"]: entry["written_through"]
        for entry in results
        if entry.get("written_through")
    }
    reply: dict[str, Any] = {
        "node_path": node_path,
        "set": results,
        "errors": errors,
    }
    warnings: list[str] = []
    if kept:
        reply["expressions_kept"] = kept
        warnings.append(
            f"{len(kept)} parameter(s) kept an expression and did not take the "
            f"value asked for: {kept}. {_EXPRESSION_KEPT_NOTE}"
        )
    if through:
        reply["written_through"] = through
        warnings.append(
            f"{len(through)} value(s) were written into the parameters these read "
            f"rather than into them: {through}. {_WRITTEN_THROUGH_NOTE}"
        )
    if warnings:
        reply["warning"] = " ".join(warnings)
    return reply


register_handler("parameters.set_parameters", _set_parameters)


###### Handler: parameters.get_parameter_schema


def _get_parameter_schema(
    node_path: str,
    parm_name: str | None = None,
    filter: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Get full parameter template info.

    If *parm_name* is given, return info for that one parameter.
    If *filter* is given, return only parameters whose name or label
    contains the filter string (case-insensitive).
    Otherwise return all non-hidden parameters.
    """
    node = _resolve_node(node_path)

    if parm_name is not None:
        parm = node.parm(parm_name)
        if parm is None:
            return {
                "node_path": node_path,
                "error": f"Parameter '{parm_name}' not found",
                "available_parameters": _available_parm_names(node),
            }
        return {
            "node_path": node_path,
            "parameter": _template_to_dict(parm.parmTemplate()),
        }

    # All parameters — hidden params skipped to keep the response compact.
    ptg = node.parmTemplateGroup()
    parm_infos: list[dict[str, Any]] = []

    def _walk(entries: tuple) -> None:
        for entry in entries:
            if isinstance(entry, hou.FolderParmTemplate):
                _walk(entry.parmTemplates())
            elif not entry.isHidden():
                parm_infos.append(_template_to_dict(entry))

    _walk(ptg.parmTemplates())

    if filter:
        f = filter.lower()
        parm_infos = [p for p in parm_infos if f in p["name"].lower() or f in p["label"].lower()]

    return {
        "node_path": node_path,
        "parameter_count": len(parm_infos),
        "parameters": parm_infos,
    }


register_handler("parameters.get_parameter_schema", _get_parameter_schema)


###### Handler: parameters.set_expression


def _set_expression(
    node_path: str,
    parm_name: str,
    expression: str,
    language: str = "hscript",
    **_: Any,
) -> dict[str, Any]:
    """Set an expression on a parameter."""
    parm = _resolve_parm(node_path, parm_name)

    lang = hou.exprLanguage.Python if language.lower() == "python" else hou.exprLanguage.Hscript

    parm.setExpression(expression, lang)

    return {
        "node_path": node_path,
        "parm_name": parm_name,
        "expression": expression,
        "language": language,
    }


register_handler("parameters.set_expression", _set_expression)


###### Handler: parameters.get_expression


def _get_expression(node_path: str, parm_name: str, **_: Any) -> dict[str, Any]:
    """Get the current expression on a parameter."""
    parm = _resolve_parm(node_path, parm_name)

    try:
        expr = parm.expression()
        lang = parm.expressionLanguage().name()
    except hou.OperationFailed:
        expr = None
        lang = None

    return {
        "node_path": node_path,
        "parm_name": parm_name,
        "expression": expr,
        "language": lang,
    }


register_handler("parameters.get_expression", _get_expression)


###### Handler: parameters.revert_parameter


def _revert_parameter(node_path: str, parm_name: str, **_: Any) -> dict[str, Any]:
    """Revert a parameter to its default value."""
    parm = _resolve_parm(node_path, parm_name)

    parm.revertToDefaults()

    return {
        "node_path": node_path,
        "parm_name": parm_name,
        "reverted": True,
        "value": _serialize_value(parm.eval()),
    }


register_handler("parameters.revert_parameter", _revert_parameter)


###### Handler: parameters.link_parameters


def _channel_function(parm: hou.Parm) -> str:
    """The HScript channel function that reads *parm* as its own type.

    ``ch()`` evaluates the referenced channel as a number, so a String parameter
    linked with it reads back as "0". Strings need ``chs()``; every
    numeric kind (float, int, toggle, int-valued menu) reads with ``ch()``.
    """
    try:
        kind = parm.parmTemplate().type()
    except Exception:
        return "ch"
    return "chs" if kind == hou.parmTemplateType.String else "ch"


def _relative_channel_path(dst: hou.Parm, src: hou.Parm) -> str:
    """Path to *src* as *dst* would write it: relative, the way Houdini's own
    Paste Relative References does.

    An absolute path (``ch("/obj/gaps/CONTROL/mat")``) breaks the moment the
    pair is moved, collapsed into a subnet or saved into an HDA and instanced
    elsewhere; a relative one survives all three.
    """
    rel = dst.node().relativePathTo(src.node())
    if rel in ("", "."):
        return src.name()
    return f"{rel}/{src.name()}"


_CH_REF = re.compile(r"""\bch[fis]?\(\s*["']([^"']+)["']\s*\)""")


def _reaches(parm: hou.Parm, goal: str, seen: set[str]) -> bool:
    """True when *parm* reads *goal* through static HScript ch() references.

    Only literal ``ch("path")`` calls are followed; Python or computed
    references cannot be validated and are treated as leaves.
    """
    if parm.path() == goal:
        return True
    if parm.path() in seen:
        return False
    seen.add(parm.path())
    for key in parm.keyframes():
        with contextlib.suppress(hou.OperationFailed):
            for ref in _CH_REF.findall(key.expression()):
                dep = parm.node().parm(ref)
                if dep is not None and _reaches(dep, goal, seen):
                    return True
    return False


def _link_parameters(
    source_path: str,
    source_parm: str,
    dest_path: str,
    dest_parm: str,
    replace_existing: bool = False,
    **_: Any,
) -> dict[str, Any]:
    """Create a channel reference from destination parameter to source parameter.

    The expression uses ``chs()`` for a String destination and ``ch()`` for
    everything else, and a path relative to the destination node. The reply
    reads the destination back so the caller sees the linked value, not just
    the expression text.

    A destination that already has keyframes or an expression is refused
    unless *replace_existing* is set, and a link whose source already reads
    the destination through static ch() references is refused as a cycle.
    """
    src = _resolve_parm(source_path, source_parm)
    dst = _resolve_parm(dest_path, dest_parm)

    if dst.keyframes() and not replace_existing:
        raise ValueError(
            f"{dst.path()} already has animation or an expression; "
            "pass replace_existing=True to overwrite it."
        )
    if _reaches(src, dst.path(), set()):
        raise ValueError(f"Linking {dst.path()} to {src.path()} would create a channel cycle.")

    function = _channel_function(dst)
    channel_path = _relative_channel_path(dst, src)
    ref_expr = f'{function}("{channel_path}")'
    dst.setExpression(ref_expr, hou.exprLanguage.Hscript)

    reply: dict[str, Any] = {
        "source": src.path(),
        "destination": dst.path(),
        "expression": ref_expr,
        "function": function,
        "relative": not channel_path.startswith("/"),
    }
    with contextlib.suppress(Exception):
        reply["value"] = _serialize_value(dst.eval())
    src_kind = _channel_function(src)
    if src_kind != function:
        reply["warning"] = (
            f"'{dst.name()}' is a {'String' if function == 'chs' else 'numeric'} parameter "
            f"linked to a {'String' if src_kind == 'chs' else 'numeric'} source; "
            f"{function}() converts the value on read."
        )
    return reply


register_handler("parameters.link_parameters", _link_parameters)


###### Handler: parameters.lock_parameter


def _lock_parameter(node_path: str, parm_name: str, locked: bool, **_: Any) -> dict[str, Any]:
    """Lock or unlock a parameter."""
    parm = _resolve_parm(node_path, parm_name)

    parm.lock(locked)

    return {
        "node_path": node_path,
        "parm_name": parm_name,
        "locked": parm.isLocked(),
    }


register_handler("parameters.lock_parameter", _lock_parameter)


###### Handler: parameters.create_spare_parameter


def _create_spare_parameter(
    node_path: str,
    parm_name: str,
    parm_type: str,
    label: str,
    default_value: Any = None,
    min_val: float | None = None,
    max_val: float | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Add a custom spare parameter to a node."""
    node = _resolve_node(node_path)

    # Map string type names to ParmTemplate constructors
    type_map: dict[str, type] = {
        "float": hou.FloatParmTemplate,
        "int": hou.IntParmTemplate,
        "string": hou.StringParmTemplate,
        "toggle": hou.ToggleParmTemplate,
        "menu": hou.MenuParmTemplate,
    }

    template_cls = type_map.get(parm_type.lower())
    if template_cls is None:
        raise ValueError(
            f"Unsupported parm_type '{parm_type}'. Supported types: {list(type_map.keys())}"
        )

    # Build keyword arguments for the template constructor
    kwargs: dict[str, Any] = {}

    if template_cls in (hou.FloatParmTemplate, hou.IntParmTemplate):
        # Cast to the correct numeric type for the template
        _cast = int if template_cls is hou.IntParmTemplate else float

        # These require num_components; default to 1
        if default_value is not None:
            if not isinstance(default_value, (list, tuple)):
                default_value = [default_value]
            kwargs["num_components"] = len(default_value)
            kwargs["default_value"] = tuple(_cast(v) for v in default_value)
        else:
            kwargs["num_components"] = 1

        if min_val is not None:
            kwargs["min"] = _cast(min_val)
            kwargs["min_is_strict"] = False
        if max_val is not None:
            kwargs["max"] = _cast(max_val)
            kwargs["max_is_strict"] = False

        pt = template_cls(parm_name, label, **kwargs)

    elif template_cls is hou.StringParmTemplate:
        kwargs["num_components"] = 1
        if default_value is not None:
            if not isinstance(default_value, (list, tuple)):
                default_value = [default_value]
            kwargs["default_value"] = tuple(str(v) for v in default_value)
        pt = template_cls(parm_name, label, **kwargs)

    elif template_cls is hou.ToggleParmTemplate:
        dv = bool(default_value) if default_value is not None else False
        pt = template_cls(parm_name, label, default_value=dv)

    elif template_cls is hou.MenuParmTemplate:
        # For menu type, default_value should be a list of menu items
        items = default_value if isinstance(default_value, (list, tuple)) else []
        pt = template_cls(
            parm_name,
            label,
            menu_items=tuple(str(i) for i in items),
            menu_labels=tuple(str(i) for i in items),
        )
    else:
        pt = template_cls(parm_name, label, **kwargs)

    # Add to node
    ptg = node.parmTemplateGroup()
    ptg.addParmTemplate(pt)
    node.setParmTemplateGroup(ptg)

    return {
        "node_path": node_path,
        "parm_name": parm_name,
        "parm_type": parm_type,
        "label": label,
        "created": True,
    }


register_handler("parameters.create_spare_parameter", _create_spare_parameter)


###### Handler: parameters.create_spare_parameters


def _build_parm_template(spec: dict) -> hou.ParmTemplate:
    """Build a single ParmTemplate from a specification dict."""
    type_map: dict[str, type] = {
        "float": hou.FloatParmTemplate,
        "int": hou.IntParmTemplate,
        "string": hou.StringParmTemplate,
        "toggle": hou.ToggleParmTemplate,
        "menu": hou.MenuParmTemplate,
    }

    parm_name = spec["parm_name"]
    parm_type = spec["parm_type"].lower()
    label = spec["label"]
    default_value = spec.get("default_value")
    min_val = spec.get("min_val")
    max_val = spec.get("max_val")

    template_cls = type_map.get(parm_type)
    if template_cls is None:
        raise ValueError(f"Unsupported parm_type '{parm_type}' for parameter '{parm_name}'.")

    kwargs: dict[str, Any] = {}

    if template_cls in (hou.FloatParmTemplate, hou.IntParmTemplate):
        _cast = int if template_cls is hou.IntParmTemplate else float
        if default_value is not None:
            if not isinstance(default_value, (list, tuple)):
                default_value = [default_value]
            kwargs["num_components"] = len(default_value)
            kwargs["default_value"] = tuple(_cast(v) for v in default_value)
        else:
            kwargs["num_components"] = 1
        if min_val is not None:
            kwargs["min"] = _cast(min_val)
            kwargs["min_is_strict"] = False
        if max_val is not None:
            kwargs["max"] = _cast(max_val)
            kwargs["max_is_strict"] = False
        return template_cls(parm_name, label, **kwargs)

    if template_cls is hou.StringParmTemplate:
        kwargs["num_components"] = 1
        if default_value is not None:
            if not isinstance(default_value, (list, tuple)):
                default_value = [default_value]
            kwargs["default_value"] = tuple(str(v) for v in default_value)
        return template_cls(parm_name, label, **kwargs)

    if template_cls is hou.ToggleParmTemplate:
        dv = bool(default_value) if default_value is not None else False
        return template_cls(parm_name, label, default_value=dv)

    if template_cls is hou.MenuParmTemplate:
        items = default_value if isinstance(default_value, (list, tuple)) else []
        return template_cls(
            parm_name,
            label,
            menu_items=tuple(str(i) for i in items),
            menu_labels=tuple(str(i) for i in items),
        )

    return template_cls(parm_name, label, **kwargs)


_FOLDER_TYPE_MAP = {
    "Tabs": hou.folderType.Tabs,
    "tabs": hou.folderType.Tabs,
    "Collapsible": hou.folderType.Collapsible,
    "collapsible": hou.folderType.Collapsible,
    "Simple": hou.folderType.Simple,
    "simple": hou.folderType.Simple,
}


def _create_spare_parameters(
    node_path: str,
    parameters: list,
    folder_name: str | None = None,
    folder_type: str = "Tabs",
    **_: Any,
) -> dict[str, Any]:
    """Batch-create spare parameters, optionally inside a folder/tab."""
    node = _resolve_node(node_path)
    ptg = node.parmTemplateGroup()

    templates = []
    created = []
    updated = []
    for spec in parameters:
        pt = _build_parm_template(spec)
        existing = ptg.find(spec["parm_name"])
        if existing is None:
            # A tuple component such as "tx" is not a template name, so the
            # group does not know it, but Houdini refuses it at commit time.
            component = node.parm(spec["parm_name"])
            if component is not None:
                raise ValueError(
                    f"'{spec['parm_name']}' is a component of the existing tuple "
                    f"'{component.tuple().name()}'; pick another name."
                )
            templates.append(pt)
            created.append(spec["parm_name"])
            continue
        # Same name: edit in place. Houdini keeps the current value and
        # keyframes when the name and type are unchanged, so a type change
        # is refused rather than silently dropping data.
        current = node.parm(spec["parm_name"]) or node.parmTuple(spec["parm_name"])
        if current is not None and not (
            current.isSpare()
            if isinstance(current, hou.Parm)
            else all(p.isSpare() for p in current)
        ):
            raise ValueError(
                f"'{spec['parm_name']}' is a built-in parameter; only spare parameters can be edited."
            )
        if existing.type() != pt.type():
            raise ValueError(
                f"'{spec['parm_name']}' exists as {existing.type().name()}; "
                f"cannot change it to {pt.type().name()} without losing its value."
            )
        ptg.replace(spec["parm_name"], pt)
        updated.append(spec["parm_name"])

    if not templates:
        pass
    elif folder_name is not None:
        ft = _FOLDER_TYPE_MAP.get(folder_type, hou.folderType.Tabs)
        folder = hou.FolderParmTemplate(
            folder_name.lower().replace(" ", "_"),
            folder_name,
            parm_templates=templates,
            folder_type=ft,
        )
        ptg.addParmTemplate(folder)
    else:
        for pt in templates:
            ptg.addParmTemplate(pt)

    node.setParmTemplateGroup(ptg)

    return {
        "node_path": node_path,
        "created": created,
        "updated": updated,
        "count": len(created) + len(updated),
        "folder_name": folder_name,
    }


register_handler("parameters.create_spare_parameters", _create_spare_parameters)


###### parameters.get_parameters

_GET_PARMS_CAP = 60

# Rows a network sweep returns before it reports `truncated`.
_SWEEP_ROW_CAP = 2000


def _parm_entry(parm: hou.Parm, include_defaults: bool) -> dict[str, Any]:
    """One parameter as get_parameters reports it, for a node or a sweep row."""
    data_parm = _data_parm_value(parm, parm.parmTemplate())
    entry: dict[str, Any] = data_parm or {"value": _serialize_value(parm.eval())}
    raw = parm.rawValue()
    # Only worth reporting when it differs: an expression is the thing a
    # caller most often needs to see and a literal is just noise.
    if not data_parm and isinstance(raw, str) and raw != str(entry["value"]):
        entry["raw_value"] = raw
    if include_defaults:
        entry["is_at_default"] = parm.isAtDefault()
    return entry


def _matches_patterns(parm: hou.Parm, lowered: list[str] | None) -> bool:
    """Whether any lowered pattern is a substring of the parm's name or label."""
    if lowered is None:
        return True
    name = parm.name().lower()
    label = parm.parmTemplate().label().lower()
    return any(p in name or p in label for p in lowered)


def _get_parameters(
    node_path: str | None = None,
    patterns: list[str] | str | None = None,
    include_defaults: bool = False,
    inside: str | None = None,
    recursive: bool = False,
    node_type: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Current values for every parameter matching any of several patterns.

    set_parameters has been batch from the start while reading stayed one parm
    per call, so checking five unrelated groups of settings cost five round
    trips. get_node_card reports names and defaults for a node *type*; this
    reports the live values on a specific node.

    With *inside* instead of *node_path*, the same patterns are read across a
    whole network and come back as one table of `rows`. "Every file parameter
    of this material library, unexpanded" was find_nodes plus one
    get_parameters per node: 68 calls in one session.

    Args:
        node_path: Node to read.
        patterns: Substrings matched against parameter name and label. Omit for
            every non-hidden parameter, up to the cap. Required with *inside*.
        include_defaults: Also report whether each value is still the default.
        inside: A network to read instead of one node; answers `rows`.
        recursive: With *inside*, every descendant, not only the children.
        node_type: With *inside*, only nodes of this type name.
    """
    if inside is not None:
        if node_path is not None:
            raise ValueError("Pass either node_path (one node) or inside (a network), not both.")
        return _sweep_parameters(inside, patterns, include_defaults, recursive, node_type)
    if node_path is None:
        raise ValueError("node_path is required (or inside, to read a whole network).")
    node = hou.node(node_path)
    if node is None:
        raise hou.OperationFailed(f"Node not found: {node_path}")

    if isinstance(patterns, str):
        patterns = [patterns]
    lowered = [p.lower() for p in patterns] if patterns else None

    values: dict[str, Any] = {}
    matched = 0
    for parm in node.parms():
        if not _matches_patterns(parm, lowered):
            continue
        matched += 1
        if len(values) >= _GET_PARMS_CAP:
            continue
        values[parm.name()] = _parm_entry(parm, include_defaults)

    return {
        "node_path": node_path,
        "node_type": node.type().name(),
        "patterns": patterns,
        "matched": matched,
        "returned": len(values),
        "truncated": matched > len(values),
        "parameters": values,
    }


def _sweep_parameters(
    inside: str,
    patterns: list[str] | str | None,
    include_defaults: bool,
    recursive: bool,
    node_type: str | None,
) -> dict[str, Any]:
    """get_parameters over the nodes of a network, as one table of rows."""
    from fxhoudinimcp_server.handlers.node_handlers import _VALUELESS_PARM_TYPES

    parent = hou.node(inside)
    if parent is None:
        raise hou.OperationFailed(f"Node not found: {inside}")
    if isinstance(patterns, str):
        patterns = [patterns]
    if not patterns:
        raise ValueError(
            "patterns is required with inside: every parameter of a whole network "
            "is not an answer anyone can read. Name what to look for, e.g. ['file']."
        )
    lowered = [p.lower() for p in patterns]
    nodes = parent.allSubChildren() if recursive else parent.children()
    rows: list[dict[str, Any]] = []
    matched = 0
    scanned = 0
    nodes_matched = 0
    for node in nodes:
        if node_type and node.type().name() != node_type:
            continue
        scanned += 1
        hit = False
        for parm in node.parms():
            # A button or a folder matched by label has no value to report.
            with contextlib.suppress(Exception):
                if parm.parmTemplate().type().name() in _VALUELESS_PARM_TYPES:
                    continue
            if not _matches_patterns(parm, lowered):
                continue
            matched += 1
            hit = True
            if len(rows) >= _SWEEP_ROW_CAP:
                continue
            row: dict[str, Any] = {"node": node.path(), "parm": parm.name()}
            row.update(_parm_entry(parm, include_defaults))
            rows.append(row)
        nodes_matched += hit
    return {
        "inside": parent.path(),
        "recursive": bool(recursive),
        "node_type": node_type,
        "patterns": patterns,
        "nodes_scanned": scanned,
        "nodes_matched": nodes_matched,
        "matched": matched,
        "returned": len(rows),
        "truncated": matched > len(rows),
        "rows": rows,
    }


register_handler("parameters.get_parameters", _get_parameters)


###### Handler: parameters.get_parm_references

# Every HScript function that reads a channel by path
# ($HFS/houdini/help/expressions.zip). Longest first, so chsop is not read
# as chs.
_CHANNEL_FUNCTIONS = (
    "ch", "chexist", "chexpr", "chexprf", "chexprt", "chf", "chramp", "chrampf",
    "chrampraw", "chrampt", "chs", "chsop", "chsoplist", "chsraw", "cht",
)  # fmt: skip
_CHANNEL_NAMES = "|".join(sorted(_CHANNEL_FUNCTIONS, key=len, reverse=True))
_CHANNEL_REF_RE = re.compile(r"\b(?:" + _CHANNEL_NAMES + r""")\s*\(\s*['"]([^'"]+)['"]""")
_BACKTICKS_RE = re.compile(r"`([^`]*)`")


def _outgoing_reference(parm: hou.Parm) -> dict[str, Any] | None:
    """What *parm* reads from, or None when it reads no other channel.

    A pure `ch("../src/tx")` resolves through getReferencedParm(). Anything
    richer -- `ch("../src/scale") * 2` -- answers with the parm itself there
    (measured on 22.0.429), so the channel references are read out of the
    expression text and resolved relative to the node. A string parameter's
    backtick expressions (`$HIP/`chs("../CTRL/version")`/geo.bgeo.sc`) are not
    an expression() at all; they are read from unexpandedString(). An
    expression that reads no channel (`$F * 2`) is not a reference.
    """
    expression = None
    with contextlib.suppress(Exception):
        expression = parm.expression()
    texts: list[str] = []
    in_backticks = False
    if expression:
        texts = [expression]
    else:
        with contextlib.suppress(Exception):
            raw = parm.unexpandedString()
            texts = _BACKTICKS_RE.findall(raw)
            if texts:
                expression, in_backticks = raw, True
    if not texts:
        return None
    entry: dict[str, Any] = {"parm": parm.name(), "expression": expression}
    if in_backticks:
        entry["in_backticks"] = True
    else:
        with contextlib.suppress(Exception):
            direct = parm.getReferencedParm()
            if direct is not None and direct.path() != parm.path():
                entry["references"] = [direct.path()]
                entry["pure_reference"] = True
                return entry
    resolved: list[str] = []
    unresolved: list[str] = []
    node = parm.node()
    for text in texts:
        for token in _CHANNEL_REF_RE.findall(text):
            target = None
            with contextlib.suppress(Exception):
                target = node.parm(token)
            if target is not None:
                resolved.append(target.path())
            else:
                unresolved.append(token)
    if not resolved and not unresolved:
        return None
    entry["references"] = resolved
    if unresolved:
        # Written in the expression, but no such parameter now: a renamed or
        # deleted target, which is exactly what a rename audit is after.
        entry["unresolved"] = unresolved
    entry["pure_reference"] = False
    return entry


def _capped_paths(nodes: Any, exclude: str, limit: int) -> tuple[list[str], int]:
    paths = sorted({n.path() for n in nodes} - {exclude})
    return paths[:limit], len(paths)


def _get_parm_references(
    node_path: str,
    parm_name: str | None = None,
    direction: str = "both",
    limit: int = 200,
    include_node_level: bool | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Who references a parameter, and what it references -- both directions.

    `incoming` lists, per parameter of *node_path* (or the one *parm_name*),
    the parameters elsewhere whose expressions read it (parmsReferencingThis).
    `outgoing` lists what this node's expressions and backtick strings read.
    Node-level `dependents` / `references` round it off, so "what breaks if I
    rename this control" is one call instead of a HOM script.

    *include_node_level* decides whether the node-level lists are included.
    None (the default) includes them for a whole-node query and leaves them
    out when *parm_name* names one parameter: they answer a question about
    the node, not about that parameter.
    """
    if direction not in ("both", "incoming", "outgoing"):
        raise ValueError("direction must be 'both', 'incoming' or 'outgoing'.")
    limit = int(limit)
    node = _resolve_node(node_path)
    parms = [_resolve_parm(node_path, parm_name)] if parm_name is not None else list(node.parms())

    dependents: list = []
    with contextlib.suppress(Exception):
        dependents = list(node.dependents(include_children=False))
    # parmsReferencingThis() walks the whole scene, once per parameter. A
    # reader through ch() or backticks makes its node a dependent (a
    # self-reference makes this node its own), so with no dependents there is
    # nothing to find and the scan is skipped.
    scan_incoming = direction in ("both", "incoming") and bool(dependents)

    incoming: list[dict[str, Any]] = []
    outgoing: list[dict[str, Any]] = []
    truncated = False
    for parm in parms:
        found: list[tuple[list, dict[str, Any]]] = []
        if scan_incoming:
            with contextlib.suppress(Exception):
                refs = [p.path() for p in parm.parmsReferencingThis()]
                if refs:
                    found.append((incoming, {"parm": parm.name(), "referenced_by": refs}))
        if direction in ("both", "outgoing"):
            entry = _outgoing_reference(parm)
            if entry is not None:
                found.append((outgoing, entry))
        if not found:
            continue
        # Truncated only when there is an entry that does not fit.
        if len(incoming) + len(outgoing) + len(found) > limit:
            truncated = True
            break
        for target, entry in found:
            target.append(entry)

    result: dict[str, Any] = {
        "node_path": node.path(),
        "parm_name": parm_name,
        "direction": direction,
        "incoming": incoming,
        "outgoing": outgoing,
        "truncated": truncated,
    }
    # Asked about one parameter, the answer is about that parameter. On an
    # asset with 947 children the node-level lists came to about 117 KB, next
    # to 7 KB of parameter entries, for a question they do not answer. Still
    # on by default for a whole-node query, and either way on request.
    node_level = parm_name is None if include_node_level is None else bool(include_node_level)
    result["include_node_level"] = node_level
    if node_level:
        # This node only (include_children=False: a subnet's descendants are
        # not its own references), capped like the parameter lists.
        result["node_dependents"], count = _capped_paths(dependents, node.path(), limit)
        if count > limit:
            result["node_dependents_count"] = count
        with contextlib.suppress(Exception):
            references = node.references(include_children=False)
            result["node_references"], count = _capped_paths(references, node.path(), limit)
            if count > limit:
                result["node_references_count"] = count
    with contextlib.suppress(Exception):
        if node.needsToCook():
            result["note"] = (
                "node_dependents / node_references, and the dependents check that "
                "decides whether `incoming` is scanned, are as of this node's last "
                "cook (HOM: they can differ until it cooks); `outgoing` is parsed "
                "from expressions and is not."
            )
    return result


register_handler("parameters.get_parm_references", _get_parm_references)


###### Handler: parameters.get_parm_template_tree


def _template_tree_entry(pt: hou.ParmTemplate) -> dict[str, Any]:
    """One template as the Type Properties dialog shows it: folders, ranges,
    menus, conditionals, callbacks, defaults -- nothing evaluated.

    Built on _template_to_dict, so the tree and get_parameter_schema report a
    template with the same keys (default_value, is_hidden, min_is_strict,
    menu_items...) and the same fixes; the tree adds what only the tree needs.
    """
    entry = _template_to_dict(pt)
    with contextlib.suppress(Exception):
        conditionals = pt.conditionals()
        if conditionals:
            entry["conditionals"] = {
                key.name() if hasattr(key, "name") else str(key): value
                for key, value in conditionals.items()
            }
    with contextlib.suppress(Exception):
        help_text = pt.help()
        if help_text:
            entry["help"] = help_text
    with contextlib.suppress(Exception):
        if pt.joinsWithNext():
            entry["join_with_next"] = True
    with contextlib.suppress(Exception):
        tags = dict(pt.tags())
        if tags:
            entry["tags"] = {
                k: (v if len(str(v)) <= 120 else str(v)[:120] + "...") for k, v in tags.items()
            }
    if entry["type"] == "Folder":
        with contextlib.suppress(Exception):
            entry["folder_type"] = pt.folderType().name()
            if "Multiparm" in entry["folder_type"]:
                # A multiparm folder's default is the instance count a fresh
                # node gets.
                entry["default_instances"] = entry.get("default_value")
        with contextlib.suppress(Exception):
            if pt.endsTabGroup():
                entry["ends_tab_group"] = True
        children: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            for child in pt.parmTemplates():
                # One unreadable child costs that child, not the folder.
                with contextlib.suppress(Exception):
                    children.append(_template_tree_entry(child))
        entry["children"] = children
        return entry
    with contextlib.suppress(Exception):
        expressions = [e for e in pt.defaultExpression() if e]
        if expressions:
            entry["default_expression"] = expressions
    with contextlib.suppress(Exception):
        callback = pt.scriptCallback()
        if callback:
            entry["callback"] = callback
            entry["callback_language"] = pt.scriptCallbackLanguage().name()
    with contextlib.suppress(Exception):
        string_type = pt.stringType().name()
        if string_type != "Regular":
            entry["string_type"] = string_type
    with contextlib.suppress(Exception):
        entry["data_parm_type"] = pt.dataParmType().name()
    with contextlib.suppress(Exception):
        look = pt.look().name()
        if look != "Regular":
            entry["look"] = look
    return entry


def _count_tree(entries: list[dict[str, Any]]) -> int:
    return sum(1 + _count_tree(entry.get("children", [])) for entry in entries)


def _prune_tree(entries: list[dict[str, Any]], budget: list[int]) -> list[dict[str, Any]]:
    """Keep the first *budget* entries depth-first; the rest are cut."""
    kept: list[dict[str, Any]] = []
    for entry in entries:
        if budget[0] <= 0:
            break
        budget[0] -= 1
        if "children" in entry:
            entry["children"] = _prune_tree(entry["children"], budget)
        kept.append(entry)
    return kept


def _node_type_for_tree(context: str, type_name: str):
    """Resolve *type_name* in *context* the way createNode would, through the
    same resolver build_network and get_node_card use."""
    from fxhoudinimcp_server.handlers.graph_handlers import _resolve_node_type

    categories = hou.nodeTypeCategories()
    category = categories.get(context)
    if category is None:
        raise ValueError(f"Unknown context '{context}'. Available: {sorted(categories)}")
    resolved = _resolve_node_type(category, type_name)
    if resolved is None:
        close = get_close_matches(type_name, list(category.nodeTypes()), n=5, cutoff=0.4)
        raise ValueError(f"Node type '{type_name}' not found in {context}. Close: {close}")
    return resolved


def _get_parm_template_tree(
    node_path: str | None = None,
    type_name: str | None = None,
    context: str = "Sop",
    folder: Any = None,
    max_entries: int = 400,
    **_: Any,
) -> dict[str, Any]:
    """The whole parameter interface as a tree -- folders, conditionals, menu
    items, multiparm blocks, callbacks -- for a node or a node type.

    get_hda_info shows the top folders and get_parameter_schema flattens the
    rest away; neither can answer "what is in the Controls tab, in order,
    with its Hide When rules". This does. `folder` narrows to one folder by
    label (or a list of nested labels).
    """
    if node_path is not None:
        node = _resolve_node(node_path)
        group = node.parmTemplateGroup()
        subject: dict[str, Any] = {"node_path": node.path(), "type": node.type().name()}
    elif type_name is not None:
        node_type = _node_type_for_tree(context, type_name)
        group = node_type.parmTemplateGroup()
        subject = {"type": node_type.name(), "context": context}
    else:
        raise ValueError("Give node_path or type_name.")

    if folder is not None:
        labels = tuple(folder) if isinstance(folder, (list, tuple)) else (str(folder),)
        found = group.findFolder(labels)
        if found is None:
            available = [e.label() for e in group.entries() if _parm_type_name(e) == "Folder"]
            raise ValueError(f"No folder labelled {labels!r}. Top-level folders: {available}")
        entries = [_template_tree_entry(found)]
    else:
        entries = [_template_tree_entry(entry) for entry in group.entries()]

    total = _count_tree(entries)
    truncated = total > int(max_entries)
    if truncated:
        entries = _prune_tree(entries, [int(max_entries)])

    result = dict(subject)
    result.update(
        {
            "folder": folder,
            "entry_count": total,
            "truncated": truncated,
            "entries": entries,
        }
    )
    if truncated:
        result["note"] = (
            f"{total} entries, showing the first {int(max_entries)}. Narrow with "
            f"folder=<label> or raise max_entries."
        )
    return result


register_handler("parameters.get_parm_template_tree", _get_parm_template_tree)
