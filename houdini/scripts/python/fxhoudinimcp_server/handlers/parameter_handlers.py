"""Houdini-side handlers for parameter operations.

Provides 10 command handlers for reading, writing, and managing
node parameters, expressions, channel references, and spare parameters.
"""

from __future__ import annotations

# Built-in
from typing import Any

# Third-party
import hou

# Internal
from fxhoudinimcp_server.dispatcher import register_handler


###### Helpers

def _resolve_node(node_path: str) -> hou.Node:
    """Return the hou.Node at *node_path* or raise."""
    node = hou.node(node_path)
    if node is None:
        raise ValueError(f"Node not found: {node_path}")
    return node


def _resolve_parm(node_path: str, parm_name: str) -> hou.Parm:
    """Return the hou.Parm on *node_path* named *parm_name* or raise."""
    node = _resolve_node(node_path)
    parm = node.parm(parm_name)
    if parm is None:
        raise ValueError(
            f"Parameter '{parm_name}' not found on node '{node_path}'"
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

    # Menu items
    try:
        items = pt.menuItems()
        labels = pt.menuLabels()
        if items:
            info["menu_items"] = list(items)
            info["menu_labels"] = list(labels)
    except Exception:
        pass

    # Naming scheme (for multi-component parms)
    try:
        info["naming_scheme"] = pt.namingScheme().name()
    except Exception:
        pass

    # Conditionals
    try:
        conditionals = {}
        for cond_type in hou.parmCondType.values.values():
            expr = pt.conditionalString(cond_type)
            if expr:
                conditionals[cond_type.name()] = expr
        if conditionals:
            info["conditionals"] = conditionals
    except Exception:
        pass

    # Tags
    try:
        tags = pt.tags()
        if tags:
            info["tags"] = dict(tags)
    except Exception:
        pass

    return info


###### Handler: parameters.get_parameter

def _get_parameter(node_path: str, parm_name: str, **_: Any) -> dict[str, Any]:
    """Get the current value, expression, keyframe info, and metadata of a parameter."""
    parm = _resolve_parm(node_path, parm_name)
    pt = parm.parmTemplate()

    result: dict[str, Any] = {
        "node_path": node_path,
        "parm_name": parm_name,
        "value": _serialize_value(parm.eval()),
        "raw_value": _serialize_value(parm.rawValue()),
        "parm_type": _parm_type_name(pt),
        "is_locked": parm.isLocked(),
        "is_at_default": parm.isAtDefault(),
    }

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

def _set_parameter(
    node_path: str, parm_name: str, value: Any, **_: Any
) -> dict[str, Any]:
    """Set a parameter value, auto-detecting the appropriate type."""
    parm = _resolve_parm(node_path, parm_name)

    parm.set(value)

    return {
        "node_path": node_path,
        "parm_name": parm_name,
        "new_value": _serialize_value(parm.eval()),
    }


register_handler("parameters.set_parameter", _set_parameter)


###### Handler: parameters.set_parameters

def _set_parameters(
    node_path: str, params: dict[str, Any], **_: Any
) -> dict[str, Any]:
    """Batch-set multiple parameters on a single node."""
    node = _resolve_node(node_path)

    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for name, value in params.items():
        parm = node.parm(name)
        if parm is None:
            errors.append({"parm_name": name, "error": f"Parameter '{name}' not found"})
            continue
        try:
            parm.set(value)
            results.append({
                "parm_name": name,
                "new_value": _serialize_value(parm.eval()),
            })
        except Exception as exc:
            errors.append({"parm_name": name, "error": str(exc)})

    return {
        "node_path": node_path,
        "set": results,
        "errors": errors,
    }


register_handler("parameters.set_parameters", _set_parameters)


###### Handler: parameters.get_parameter_schema

def _get_parameter_schema(
    node_path: str, parm_name: str | None = None, **_: Any
) -> dict[str, Any]:
    """Get full parameter template info.

    If *parm_name* is ``None``, return info for every parameter on the node.
    """
    node = _resolve_node(node_path)

    if parm_name is not None:
        parm = node.parm(parm_name)
        if parm is None:
            raise ValueError(
                f"Parameter '{parm_name}' not found on node '{node_path}'"
            )
        return {
            "node_path": node_path,
            "parameter": _template_to_dict(parm.parmTemplate()),
        }

    # All parameters
    ptg = node.parmTemplateGroup()
    parm_infos: list[dict[str, Any]] = []

    def _walk(entries: tuple) -> None:
        for entry in entries:
            if isinstance(entry, hou.FolderParmTemplate):
                _walk(entry.parmTemplates())
            else:
                parm_infos.append(_template_to_dict(entry))

    _walk(ptg.parmTemplates())

    return {
        "node_path": node_path,
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

    if language.lower() == "python":
        lang = hou.exprLanguage.Python
    else:
        lang = hou.exprLanguage.Hscript

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

def _link_parameters(
    source_path: str,
    source_parm: str,
    dest_path: str,
    dest_parm: str,
    **_: Any,
) -> dict[str, Any]:
    """Create a channel reference from destination parameter to source parameter."""
    src = _resolve_parm(source_path, source_parm)
    dst = _resolve_parm(dest_path, dest_parm)

    # Build the channel reference expression
    ref_expr = 'ch("{}")'.format(src.path())
    dst.setExpression(ref_expr, hou.exprLanguage.Hscript)

    return {
        "source": src.path(),
        "destination": dst.path(),
        "expression": ref_expr,
    }


register_handler("parameters.link_parameters", _link_parameters)


###### Handler: parameters.lock_parameter

def _lock_parameter(
    node_path: str, parm_name: str, locked: bool, **_: Any
) -> dict[str, Any]:
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
            f"Unsupported parm_type '{parm_type}'. "
            f"Supported types: {list(type_map.keys())}"
        )

    # Build keyword arguments for the template constructor
    kwargs: dict[str, Any] = {}

    if template_cls in (hou.FloatParmTemplate, hou.IntParmTemplate):
        # These require num_components; default to 1
        if default_value is not None:
            if not isinstance(default_value, (list, tuple)):
                default_value = [default_value]
            kwargs["num_components"] = len(default_value)
            kwargs["default_value"] = (
                tuple(default_value)
            )
        else:
            kwargs["num_components"] = 1

        if min_val is not None:
            kwargs["min"] = min_val
            kwargs["min_is_strict"] = False
        if max_val is not None:
            kwargs["max"] = max_val
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
            parm_name, label,
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
