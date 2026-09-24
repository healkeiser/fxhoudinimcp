"""MCP tool wrappers for Houdini Digital Asset (HDA) operations.

Each tool delegates to the corresponding handler running inside Houdini
via the HTTP bridge.
"""

from __future__ import annotations

# Built-in
# Third-party
from fxhoudinimcp._sdk import Context

# Internal
from fxhoudinimcp.server import _get_bridge, mcp


@mcp.tool()
async def list_installed_hdas(
    ctx: Context,
    filter: str | None = None,
    limit: int = 100,
) -> dict:
    """List installed HDA definitions, grouped by library file.

    A stock install loads thousands; pass a filter (namespace, name or path
    fragment). `truncated` says when `limit` cut the list.

    Args:
        ctx: MCP context.
        filter: Substring filter for type names or file paths.
        limit: Maximum definitions returned.
    """
    bridge = _get_bridge(ctx)
    params: dict = {"limit": limit}
    if filter is not None:
        params["filter"] = filter
    return await bridge.execute("hda.list_installed_hdas", params)


@mcp.tool()
async def get_hda_info(
    ctx: Context,
    node_path: str | None = None,
    hda_file: str | None = None,
    type_name: str | None = None,
) -> dict:
    """Get detailed information about an HDA definition.

    Args:
        ctx: MCP context.
        node_path: Node path.
        hda_file: HDA file path.
        type_name: HDA type name.
    """
    bridge = _get_bridge(ctx)
    params: dict = {}
    if node_path is not None:
        params["node_path"] = node_path
    if hda_file is not None:
        params["hda_file"] = hda_file
    if type_name is not None:
        params["type_name"] = type_name
    return await bridge.execute("hda.get_hda_info", params)


@mcp.tool()
async def install_hda(
    ctx: Context,
    file_path: str,
    force: bool = False,
) -> dict:
    """Install an HDA file into the current session.

    Args:
        ctx: MCP context.
        file_path: HDA file path.
        force: Force reinstall even if already loaded.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "hda.install_hda",
        {
            "file_path": file_path,
            "force": force,
        },
    )


@mcp.tool()
async def uninstall_hda(ctx: Context, file_path: str) -> dict:
    """Uninstall an HDA file from the current session.

    Args:
        ctx: MCP context.
        file_path: HDA file path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("hda.uninstall_hda", {"file_path": file_path})


@mcp.tool()
async def reload_hda(ctx: Context, file_path: str) -> dict:
    """Reload an HDA file from disk.

    Args:
        ctx: MCP context.
        file_path: HDA file path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("hda.reload_hda", {"file_path": file_path})


@mcp.tool()
async def create_hda(
    ctx: Context,
    node_path: str,
    hda_file: str,
    type_name: str,
    label: str,
    version: str = "1.0",
) -> dict:
    """Create a new HDA from an existing subnet node.

    Args:
        ctx: MCP context.
        node_path: Subnet node path.
        hda_file: Destination HDA file path.
        type_name: Operator type name.
        label: Human-readable label.
        version: Version string.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "hda.create_hda",
        {
            "node_path": node_path,
            "hda_file": hda_file,
            "type_name": type_name,
            "label": label,
            "version": version,
        },
    )


@mcp.tool()
async def update_hda(ctx: Context, node_path: str) -> dict:
    """Save the current node contents back to its HDA definition.

    Args:
        ctx: MCP context.
        node_path: Node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("hda.update_hda", {"node_path": node_path})


@mcp.tool()
async def get_hda_sections(ctx: Context, node_path: str) -> dict:
    """List all sections in an HDA definition.

    Args:
        ctx: MCP context.
        node_path: Node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("hda.get_hda_sections", {"node_path": node_path})


@mcp.tool()
async def get_hda_section_content(
    ctx: Context,
    node_path: str,
    section_name: str,
) -> dict:
    """Read the content of a specific section in an HDA definition.

    Args:
        ctx: MCP context.
        node_path: Node path.
        section_name: Section name.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "hda.get_hda_section_content",
        {
            "node_path": node_path,
            "section_name": section_name,
        },
    )


@mcp.tool()
async def set_hda_section_content(
    ctx: Context,
    node_path: str,
    section_name: str,
    content: str,
) -> dict:
    """Write content to a specific section in an HDA definition.

    Args:
        ctx: MCP context.
        node_path: Node path.
        section_name: Section name.
        content: Section content.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "hda.set_hda_section_content",
        {
            "node_path": node_path,
            "section_name": section_name,
            "content": content,
        },
    )


@mcp.tool()
async def list_hda_versions(ctx: Context, node_path: str) -> dict:
    """Every installed definition of an HDA node's type: version, file, which is current.

    Args:
        ctx: MCP context.
        node_path: An HDA instance.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("hda.list_hda_versions", {"node_path": node_path})


@mcp.tool()
async def set_hda_interface(
    ctx: Context,
    node_path: str,
    parameters: list[dict],
    replace: bool = False,
    dry_run: bool = False,
) -> dict:
    """Author an HDA's Type Properties interface in one call.

    Use this for the asset's TYPE interface — tab folders, strict ranges,
    ordered menus, Hide/Disable When. `create_spare_parameter` is a different
    thing: it adds parameters to one node instance and never reaches the type.

    Each entry of `parameters` is a dict:
        name, label, type (int|float|string|toggle|menu|folder),
        default, min, max, min_strict, max_strict, components,
        menu_items ([value, label] pairs or plain strings),
        folder_type (tabs|simple|collapsible|radio) + children for folders,
        hide_when / disable_when (Houdini conditionals), help.

    Example — a Controls tab whose Bevel disappears for a single stud:
        [{"name": "controls", "label": "Controls", "type": "folder",
          "children": [
            {"name": "stud_count", "type": "int", "default": 4,
             "min": 1, "max": 8, "min_strict": True, "max_strict": True},
            {"name": "bevel", "type": "float", "default": 0.02,
             "min": 0.0, "max": 0.1, "hide_when": "{ stud_count == 1 }"},
            {"name": "material", "type": "menu",
             "menu_items": [["plastic", "Plastic"], ["metal", "Metal"]]}]}]

    It is edit_hda_interface with one insert per entry: names already in the
    interface are refused before anything is written, and the reply is read
    back off the definition — `ops[].stored`, `renamed_by_houdini` (a tab
    folder joins the existing tab set's naming series), `not_found_after_write`,
    `instance_parms_missing` and `instance_expression_errors`.

    Args:
        ctx: MCP context.
        node_path: An instance of the HDA whose definition is edited.
        parameters: Interface spec (see above). create_spare_parameters'
            spelling (parm_name, parm_type, default_value) is accepted too.
        replace: Start from an empty interface. Built-in parameters of the node
            type cannot be removed: Houdini puts them back
            (`reinstated_by_houdini`).
        dry_run: Validate and report the plan without writing.
    """
    bridge = _get_bridge(ctx)
    payload: dict = {"node_path": node_path, "parameters": parameters, "replace": replace}
    if dry_run:
        payload["dry_run"] = True
    return await bridge.execute("hda.set_hda_interface", payload)


@mcp.tool()
async def edit_hda_interface(
    ctx: Context,
    node_path: str,
    ops: list[dict],
    dry_run: bool = False,
) -> dict:
    """Edit an HDA's EXISTING Type Properties interface in one atomic call:
    insert at a position, remove, hide/show, replace, modify, move.

    set_hda_interface only appends. Every op here works on the definition's
    parameter group; all ops are applied to a copy, the result is checked
    for component-name collisions, and it is written once — a failing op
    changes nothing. Read the interface first with get_parm_template_tree.

    Ops (dicts, applied in order):
        {"op": "insert", "spec": {...}, "after": name | "before": name |
            "in_folder": label or [labels]}  — omit the position to append.
            spec is a set_hda_interface spec, plus types button (with
            "callback", Python by default), separator, label, vector, color,
            file, oppath; and fields naming_scheme (base1|xyzw|rgba|minmax|
            startend|uvw), default_expression (+ default_expression_language),
            hidden, join_with_next, callback, tags; folder_type "multiparm"
            for a multiparm block (children named "item#").
        {"op": "remove", "name": name_or_folder_label}
        {"op": "hide" | "show", "name": ...}
        {"op": "replace", "name": ..., "spec": {...}}
        {"op": "modify", "name": ..., <label | help | default |
            default_expression | default_expression_language | min | max |
            min_strict | max_strict | hide_when | disable_when ("" clears) |
            hidden | join_with_next | menu_items | callback | naming_scheme |
            new_name | tags>}
            ("rename", "set_conditional", "set_default" are aliases)
        {"op": "move", "name": ..., "after" | "before" | "in_folder": ...}

    Names are template names (`t`, not `tx`; `stud_count`); folders are
    addressed by label ("Controls"). Built-in parameters of the node type
    (an Object's Transform) cannot be removed — Houdini re-adds them at the
    top level and the reply says so in `reinstated_by_houdini`; hide them.

    `default_expression_language` is "hscript" (Houdini's default) or
    "python"; given alone in a modify, it changes the language of the
    expression already there. `stored` reads both back, and
    `instance_expression_errors` names a default expression that does not
    evaluate on the instance.

    Args:
        ctx: MCP context.
        node_path: An instance of the HDA whose definition is edited.
        ops: Operations, in order.
        dry_run: Validate and report the plan without writing.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "hda.edit_hda_interface",
        {"node_path": node_path, "ops": ops, "dry_run": dry_run},
    )
