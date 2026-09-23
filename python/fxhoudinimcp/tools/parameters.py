"""MCP tools for Houdini parameter operations.

Exposes 14 tools covering parameter get/set, expressions, channel
references, locking, schema inspection, and spare parameter creation.
"""

from __future__ import annotations

# Built-in
from typing import Any

# Third-party
from fxhoudinimcp._sdk import Context

# Internal
from fxhoudinimcp._types import Value
from fxhoudinimcp.server import _get_bridge, mcp

###### parameters.get_parameter


@mcp.tool()
async def get_parameter(ctx: Context, node_path: str, parm_name: str) -> dict:
    """Get the value and metadata of a parameter.

    Args:
        node_path: Node path.
        parm_name: Parameter name.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "parameters.get_parameter",
        {"node_path": node_path, "parm_name": parm_name},
    )


###### parameters.set_parameter


@mcp.tool()
async def set_parameter(
    ctx: Context,
    node_path: str,
    parm_name: str,
    value: Value,
    override_expression: bool = False,
    run_callbacks: bool = False,
) -> dict:
    """Set a parameter value.

    A parameter that holds an expression does NOT take a literal: Houdini
    writes the value into a slot the expression keeps overriding. The reply
    then carries `expression_kept: true` with the surviving `expression` and
    what you `requested` (plus `same_as_evaluated` when the expression happens
    to evaluate to that value right now) — read those before calling the write
    done. Pass override_expression=True to clear the expression first.

    A parameter holding a BARE ch() reference is the opposite trap: Houdini
    writes THROUGH it into the parameter it reads, so the value lands on
    another node. The reply names that parameter in `written_through`.

    A String parameter echoes `raw_value` (the unexpanded text, `$JOB/...`)
    next to the expanded `new_value`.

    A LOCKED parameter (karmarendersettings resolutiony under res_mode
    autoheight) takes nothing at all; the error names the menu whose callback
    sets the lock. Houdini runs such callbacks only from the UI: set that menu
    with run_callbacks=True first, then the locked parameter.

    Args:
        node_path: Node path.
        parm_name: Parameter name.
        value: New value (int, float, string, bool, or list).
        override_expression: Remove an expression standing in the way,
            instead of reporting that the write did not take.
        run_callbacks: Run the parameter's callback script after the write,
            as editing it in the UI does (`callback_run` in the reply, and
            `callback_error` when the callback raised).
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "parameters.set_parameter",
        {
            "node_path": node_path,
            "parm_name": parm_name,
            "value": value,
            "override_expression": override_expression,
            "run_callbacks": run_callbacks,
        },
    )


###### parameters.set_parameters


@mcp.tool()
async def set_parameters(
    ctx: Context,
    node_path: str,
    params: dict[str, Any],
    override_expression: bool = False,
    run_callbacks: bool = False,
) -> dict:
    """Batch-set multiple parameters on a node, in the order given.

    Parameters that held an expression and therefore ignored the literal are
    listed in `expressions_kept`, with a top-level `warning`: a batch whose
    `errors` is empty can still contain a write that did not take. Values that
    landed on ANOTHER node, because the parameter is a bare ch() reference
    Houdini writes through, are in `written_through`. Each entry in `set`
    carries the same keys as set_parameter's reply. Pass
    override_expression=True to clear those expressions and links instead.

    Locked parameters are in `errors` with `locked: true` and listed in
    `locked_parms`; the error names the menu whose callback sets the lock.
    With run_callbacks=True each parameter's callback runs after its write, so
    `{"res_mode": "manual", "resolutiony": 1080}` unlocks and then writes; a
    callback that raised is listed in `callbacks_not_run`.

    Args:
        node_path: Node path.
        params: Mapping of parameter names to values, written in this order.
        override_expression: Remove expressions standing in the way.
        run_callbacks: Run each parameter's callback script after its write,
            as the UI does.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "parameters.set_parameters",
        {
            "node_path": node_path,
            "params": params,
            "override_expression": override_expression,
            "run_callbacks": run_callbacks,
        },
    )


###### parameters.get_parameter_schema


@mcp.tool()
async def get_parameter_schema(
    ctx: Context,
    node_path: str,
    parm_name: str | None = None,
    filter: str | None = None,
) -> dict:
    """Get the template schema for parameter(s) on a node.

    Most nodes have dozens of parameters; many have 100+. Always use
    `parm_name` or `filter` unless you genuinely need the full list.

    Args:
        node_path: Node path.
        parm_name: Exact parameter name for a single-parameter lookup.
        filter: Substring to match against parameter name or label
                (case-insensitive). Use instead of dumping all params.
    """
    bridge = _get_bridge(ctx)
    payload: dict[str, Any] = {"node_path": node_path}
    if parm_name is not None:
        payload["parm_name"] = parm_name
    if filter is not None:
        payload["filter"] = filter
    return await bridge.execute("parameters.get_parameter_schema", payload)


###### parameters.get_parm_references


@mcp.tool()
async def get_parm_references(
    ctx: Context,
    node_path: str,
    parm_name: str | None = None,
    direction: str = "both",
    limit: int = 200,
    include_node_level: bool | None = None,
) -> dict:
    """Who references a parameter, and what it references — in one call.

    `incoming`: for each parameter of the node (or just parm_name), the
    parameters elsewhere whose expressions read it — what breaks if this
    control is renamed. `outgoing`: what this node's expressions and
    backtick strings read, resolved to parameter paths (pure ch() links and
    richer expressions alike; `unresolved` names a written target that no
    longer exists). `node_dependents` / `node_references` give the
    node-level view for this node only; `include_node_level` in the reply
    says whether they were included.

    Args:
        node_path: Node to inspect.
        parm_name: One parameter instead of all of them.
        direction: "both", "incoming" or "outgoing".
        limit: Cap on reported entries.
        include_node_level: Include node_dependents / node_references. Default:
            on for a whole-node query, off when parm_name names one parameter;
            on an asset with hundreds of children those lists run to about
            100 KB and answer a question about the node, not the parameter.
    """
    bridge = _get_bridge(ctx)
    payload: dict[str, Any] = {"node_path": node_path, "direction": direction, "limit": limit}
    if parm_name is not None:
        payload["parm_name"] = parm_name
    if include_node_level is not None:
        payload["include_node_level"] = include_node_level
    return await bridge.execute("parameters.get_parm_references", payload)


###### parameters.get_parm_template_tree


@mcp.tool()
async def get_parm_template_tree(
    ctx: Context,
    node_path: str | None = None,
    type_name: str | None = None,
    context: str = "Sop",
    folder: str | list[str] | None = None,
    max_entries: int = 400,
) -> dict:
    """The whole parameter interface as a tree, the way Type Properties shows
    it: folders (with folder_type — tabs, collapsible, multiparm), every
    parameter in order with defaults, default expressions, ranges, menu
    items, Hide/Disable When conditionals, callbacks, naming scheme; a
    multiparm's `default_instances`. Each entry uses get_parameter_schema's
    keys (`default_value`, `is_hidden`, `menu_items`...).

    get_hda_info shows only the top folders and get_parameter_schema
    flattens the structure away; read this before editing an interface.
    Give node_path for a node (its instance interface, spares included) or
    type_name + context for a type.

    Args:
        node_path: Node whose interface to read.
        type_name: Node type instead (with context).
        context: Category of type_name — "Sop", "Object", "Lop", ...
        folder: Narrow to one folder by label, or a list of nested labels.
        max_entries: Cap on entries (depth-first); the reply says when it cut.
    """
    bridge = _get_bridge(ctx)
    payload: dict[str, Any] = {"context": context, "max_entries": max_entries}
    if node_path is not None:
        payload["node_path"] = node_path
    if type_name is not None:
        payload["type_name"] = type_name
    if folder is not None:
        payload["folder"] = folder
    return await bridge.execute("parameters.get_parm_template_tree", payload)


###### parameters.set_expression


@mcp.tool()
async def set_expression(
    ctx: Context,
    node_path: str,
    parm_name: str,
    expression: str,
    language: str = "hscript",
) -> dict:
    """Set an expression on a parameter.

    Args:
        node_path: Node path.
        parm_name: Parameter name.
        expression: Expression string.
        language: "hscript" (default) or "python".
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "parameters.set_expression",
        {
            "node_path": node_path,
            "parm_name": parm_name,
            "expression": expression,
            "language": language,
        },
    )


###### parameters.get_expression


@mcp.tool()
async def get_expression(ctx: Context, node_path: str, parm_name: str) -> dict:
    """Get the expression on a parameter.

    Args:
        node_path: Node path.
        parm_name: Parameter name.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "parameters.get_expression",
        {"node_path": node_path, "parm_name": parm_name},
    )


###### parameters.revert_parameter


@mcp.tool()
async def revert_parameter(ctx: Context, node_path: str, parm_name: str) -> dict:
    """Revert a parameter to its default value.

    A locked parameter cannot be reverted; the error names what sets the lock.

    Args:
        node_path: Node path.
        parm_name: Parameter name.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "parameters.revert_parameter",
        {"node_path": node_path, "parm_name": parm_name},
    )


###### parameters.link_parameters


@mcp.tool()
async def link_parameters(
    ctx: Context,
    source_path: str,
    source_parm: str,
    dest_path: str,
    dest_parm: str,
    replace_existing: bool = False,
) -> dict:
    """Create a channel reference from one parameter to another.

    The destination gets an HScript expression that reads the source as its
    own type: chs() for a String parameter, ch() for numbers, toggles and
    menus. The path is relative to the destination node (chs("../CTRL/mat")),
    so the link survives moving the pair, collapsing into a subnet or
    instancing an HDA. The reply carries the expression, the function used
    and the destination's evaluated value.

    Args:
        source_path: Source node path.
        source_parm: Source parameter name.
        dest_path: Destination node path.
        dest_parm: Destination parameter name.
        replace_existing: Overwrite a destination that already has keyframes
            or an expression. Refused otherwise, so animation is never lost
            by accident. A link whose source already reads the destination
            through ch() is refused as a cycle in every case.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "parameters.link_parameters",
        {
            "source_path": source_path,
            "source_parm": source_parm,
            "dest_path": dest_path,
            "dest_parm": dest_parm,
            "replace_existing": replace_existing,
        },
    )


###### parameters.lock_parameter


@mcp.tool()
async def lock_parameter(ctx: Context, node_path: str, parm_name: str, locked: bool) -> dict:
    """Lock or unlock a parameter.

    Args:
        node_path: Node path.
        parm_name: Parameter name.
        locked: True to lock, False to unlock.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "parameters.lock_parameter",
        {"node_path": node_path, "parm_name": parm_name, "locked": locked},
    )


###### parameters.create_spare_parameter


@mcp.tool()
async def create_spare_parameter(
    ctx: Context,
    node_path: str,
    parm_name: str,
    parm_type: str,
    label: str,
    default_value: Value | None = None,
    min_val: float | None = None,
    max_val: float | None = None,
) -> dict:
    """Add a spare parameter to a node.

    Args:
        node_path: Node path.
        parm_name: Internal parameter name.
        parm_type: "float", "int", "string", "toggle", or "menu".
        label: UI label.
        default_value: Default value.
        min_val: Minimum value (float/int only).
        max_val: Maximum value (float/int only).
    """
    bridge = _get_bridge(ctx)
    payload: dict[str, Any] = {
        "node_path": node_path,
        "parm_name": parm_name,
        "parm_type": parm_type,
        "label": label,
    }
    if default_value is not None:
        payload["default_value"] = default_value
    if min_val is not None:
        payload["min_val"] = min_val
    if max_val is not None:
        payload["max_val"] = max_val
    return await bridge.execute("parameters.create_spare_parameter", payload)


@mcp.tool()
async def create_spare_parameters(
    ctx: Context,
    node_path: str,
    parameters: list[dict[str, Any]],
    folder_name: str | None = None,
    folder_type: str = "Tabs",
) -> dict:
    """Batch-create multiple spare parameters in one call, optionally in a folder tab.

    A name that already exists as a spare parameter is updated in place
    (label, default, range); its current value and keyframes are kept.
    A type change on an existing parameter is refused.

    Args:
        node_path: Node path.
        parameters: List of parameter specs. Each dict has keys:
            parm_name (str), parm_type (str: "float"/"int"/"string"/"toggle"/"menu"),
            label (str), default_value (optional), min_val (optional), max_val (optional).
        folder_name: If provided, wraps all parameters in a named folder tab.
        folder_type: Folder style: "Tabs", "Collapsible", or "Simple".
    """
    bridge = _get_bridge(ctx)
    payload: dict[str, Any] = {
        "node_path": node_path,
        "parameters": parameters,
    }
    if folder_name is not None:
        payload["folder_name"] = folder_name
        payload["folder_type"] = folder_type
    return await bridge.execute("parameters.create_spare_parameters", payload)


@mcp.tool()
async def get_parameters(
    ctx: Context,
    node_path: str | None = None,
    patterns: list[str] | None = None,
    include_defaults: bool = False,
    inside: str | None = None,
    recursive: bool = False,
    node_type: str | None = None,
) -> dict:
    """Read many parameter values at once, matched by name or label substring.

    The batch counterpart of set_parameters. Several unrelated groups of
    settings ("flame", "wind", "buoy") come back in one call instead of one call
    each, and unlike get_node_card these are the live values on this node rather
    than the defaults for its type.

    Pass `inside` instead of `node_path` to read the same patterns across a
    whole network in one call: "every file parm of this material library,
    unexpanded" comes back as `rows` of {node, parm, value, raw_value}, up to
    2000 rows. `raw_value` is the unexpanded text ($JOB/...), shown when it
    differs from the value, exactly as for a single node.

    Args:
        node_path: Node to read.
        patterns: Substrings matched against parameter name and label. Omit for
            everything, up to the cap. Required with `inside`.
        include_defaults: Also report whether each value is still the default.
        inside: Network to read instead of a single node.
        recursive: With `inside`, include every descendant, not only children.
        node_type: With `inside`, only nodes of this type (e.g. "mtlximage").
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"include_defaults": include_defaults}
    if node_path is not None:
        params["node_path"] = node_path
    if patterns is not None:
        params["patterns"] = patterns
    if inside is not None:
        params["inside"] = inside
        params["recursive"] = recursive
        if node_type is not None:
            params["node_type"] = node_type
    return await bridge.execute("parameters.get_parameters", params)
