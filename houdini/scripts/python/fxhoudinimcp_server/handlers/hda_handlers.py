"""HDA (Houdini Digital Asset) handlers for FXHoudini-MCP.

Provides tools for managing, inspecting, creating, and editing
Houdini Digital Assets.
"""

from __future__ import annotations

# Built-in
import contextlib
import os
from difflib import get_close_matches

# Third-party
import hou

# Internal
from fxhoudinimcp_server.config import require_inside_project_root
from fxhoudinimcp_server.dispatcher import register_handler
from fxhoudinimcp_server.errors import as_text, readable_message
from fxhoudinimcp_server.handlers.parameter_handlers import _template_to_dict

###### Helpers


def _get_node(node_path: str) -> hou.Node:
    """Return a node or raise if not found."""
    node = hou.node(node_path)
    if node is None:
        raise ValueError(f"Node not found: {node_path}")
    return node


def _get_definition(node: hou.Node) -> hou.HDADefinition:
    """Return the HDA definition for a node or raise."""
    definition = node.type().definition()
    if definition is None:
        raise ValueError(
            f"Node {node.path()} is not an HDA instance. Its type is '{node.type().name()}'."
        )
    return definition


def _is_embedded(definition: hou.HDADefinition) -> bool:
    """True for a definition stored in the hip file.

    HOM has no isEmbedded() (checked on 22.0.429); an embedded definition
    answers the literal "Embedded" for its library path.
    """
    return definition.libraryFilePath() == "Embedded"


def _definition_to_dict(definition: hou.HDADefinition) -> dict:
    """Convert an HDA definition to a plain dict."""
    info = {
        "type_name": definition.nodeTypeName(),
        "description": definition.description(),
        "icon": definition.icon(),
        "library_file": definition.libraryFilePath(),
    }

    try:
        info["version"] = definition.version()
    except Exception:
        info["version"] = None

    try:
        info["min_num_inputs"] = definition.minNumInputs()
        info["max_num_inputs"] = definition.maxNumInputs()
    except Exception:
        info["min_num_inputs"] = None
        info["max_num_inputs"] = None

    try:
        info["max_num_outputs"] = definition.maxNumOutputs()
    except Exception:
        info["max_num_outputs"] = None

    try:
        info["is_editable"] = not definition.isBlackBoxed()
    except Exception:
        info["is_editable"] = None

    try:
        info["embedded"] = _is_embedded(definition)
    except Exception:
        info["embedded"] = None

    # Section names
    try:
        info["sections"] = sorted(definition.sections().keys())
    except Exception:
        info["sections"] = []

    return info


def _parm_template_to_dict(pt) -> dict:
    """Convert a parm template to a plain dict."""
    info = {
        "name": pt.name(),
        "label": pt.label(),
        "type": str(pt.type()),
    }
    try:
        info["default_value"] = list(pt.defaultValue())
    except Exception:
        try:
            info["default_value"] = list(pt.defaultExpression())
        except Exception:
            info["default_value"] = None

    try:
        info["num_components"] = pt.numComponents()
    except Exception:
        info["num_components"] = 1

    try:
        info["is_hidden"] = pt.isHidden()
    except Exception:
        info["is_hidden"] = False

    return info


###### hda.list_installed_hdas


def list_installed_hdas(filter: str = None, limit: int = 100) -> dict:
    """List installed HDA definitions, grouped by library file.

    Unfiltered this answered every loaded definition, 3,636 on a stock 22.0
    install with each row repeating its library path: about 150k tokens. It
    is capped at *limit* definitions, with the total, and each file's path is
    given once.

    Args:
        filter: Optional substring filter for HDA type names or file paths.
        limit: Maximum definitions returned.
    """
    needle = as_text(filter, "filter").lower()
    libraries: dict[str, list[dict]] = {}
    total = 0
    shown = 0
    for hda_file in hou.hda.loadedFiles():
        try:
            definitions = hou.hda.definitionsInFile(hda_file)
        except Exception:
            definitions = []
        for defn in definitions:
            type_name = defn.nodeTypeName()
            if needle and needle not in type_name.lower() and needle not in hda_file.lower():
                continue
            total += 1
            if shown >= limit:
                continue
            shown += 1
            libraries.setdefault(hda_file, []).append(
                {
                    "type_name": type_name,
                    "category": defn.nodeTypeCategory().name(),
                    "description": defn.description(),
                    "version": defn.version() if hasattr(defn, "version") else None,
                }
            )
    for rows in libraries.values():
        rows.sort(key=lambda row: row["type_name"])
    return {
        "hda_count": total,
        "returned": shown,
        "truncated": total > shown,
        "libraries": libraries,
        "filter_applied": filter,
    }


###### hda.get_hda_info


def get_hda_info(
    node_path: str = None,
    hda_file: str = None,
    type_name: str = None,
) -> dict:
    """Return detailed information about an HDA definition.

    At least one of node_path, hda_file, or type_name must be provided.

    Args:
        node_path: Path to an HDA node instance.
        hda_file: Path to an HDA file on disk.
        type_name: Fully qualified HDA type name.
    """
    definition = None

    if node_path is not None:
        node = _get_node(node_path)
        definition = _get_definition(node)
    elif hda_file is not None:
        if not os.path.isfile(hda_file):
            raise FileNotFoundError(f"HDA file not found: {hda_file}")
        definitions = hou.hda.definitionsInFile(hda_file)
        if type_name:
            for defn in definitions:
                if defn.nodeTypeName() == type_name:
                    definition = defn
                    break
            if definition is None:
                raise ValueError(
                    f"Type '{type_name}' not found in {hda_file}. "
                    f"Available: {[d.nodeTypeName() for d in definitions]}"
                )
        elif definitions:
            definition = definitions[0]
        else:
            raise ValueError(f"No HDA definitions found in {hda_file}")
    elif type_name is not None:
        node_type = hou.nodeType(hou.sopNodeTypeCategory(), type_name)
        if node_type is None:
            # Try other categories
            for cat_func in [
                hou.objNodeTypeCategory,
                hou.lopNodeTypeCategory,
                hou.ropNodeTypeCategory,
                hou.cop2NodeTypeCategory,
                hou.topNodeTypeCategory,
                hou.dopNodeTypeCategory,
                hou.shopNodeTypeCategory,
                hou.vopNodeTypeCategory,
            ]:
                try:
                    node_type = hou.nodeType(cat_func(), type_name)
                    if node_type is not None:
                        break
                except Exception:
                    continue
        if node_type is None:
            raise ValueError(f"Node type not found: {type_name}")
        definition = node_type.definition()
        if definition is None:
            raise ValueError(f"Type '{type_name}' is not an HDA.")
    else:
        raise ValueError("At least one of node_path, hda_file, or type_name must be provided.")

    info = _definition_to_dict(definition)

    # Parameter templates
    try:
        parm_templates = definition.parmTemplateGroup().entries()
        info["parameters"] = [_parm_template_to_dict(pt) for pt in parm_templates]
    except Exception:
        info["parameters"] = []

    # Input and output labels
    try:
        input_labels = []
        for i in range(definition.maxNumInputs()):
            try:
                label = definition.inputLabel(i)
                input_labels.append(label)
            except Exception:
                break
        info["input_labels"] = input_labels
    except Exception:
        info["input_labels"] = []

    try:
        output_labels = []
        for i in range(definition.maxNumOutputs()):
            try:
                label = definition.outputLabel(i)
                output_labels.append(label)
            except Exception:
                break
        info["output_labels"] = output_labels
    except Exception:
        info["output_labels"] = []

    return info


###### hda.install_hda


def install_hda(file_path: str, force: bool = False) -> dict:
    """Install an HDA file into the current Houdini session.

    Args:
        file_path: Path to the HDA file to install.
        force: If True, force reinstall even if already loaded.
    """
    # This guard sat inside the docstring above, where it never ran.
    require_inside_project_root(file_path, "HDA file")
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"HDA file not found: {file_path}")

    # Check if already installed
    loaded_files = hou.hda.loadedFiles()
    already_loaded = any(os.path.normpath(f) == os.path.normpath(file_path) for f in loaded_files)

    if already_loaded and not force:
        return {
            "success": True,
            "file_path": file_path,
            "message": "HDA file is already installed.",
            "already_loaded": True,
        }

    try:
        hou.hda.installFile(file_path)
    except Exception as e:
        raise ValueError(f"Failed to install HDA: {readable_message(e)}") from e

    # List definitions that were installed
    definitions = hou.hda.definitionsInFile(file_path)
    type_names = [d.nodeTypeName() for d in definitions]

    return {
        "success": True,
        "file_path": file_path,
        "installed_types": type_names,
        "type_count": len(type_names),
    }


###### hda.uninstall_hda


def uninstall_hda(file_path: str) -> dict:
    """Uninstall an HDA file from the current Houdini session.

    Args:
        file_path: Path to the HDA file to uninstall.
    """
    # hou.hda.uninstallFile raises a bare "The attempted operation failed." for
    # anything wrong, which tells a caller nothing about what to do next. The
    # overwhelmingly likely cause is that this file was never installed, so say so
    # and name what IS installed.
    require_inside_project_root(file_path, "HDA file")
    installed: list[str] = []
    with contextlib.suppress(Exception):  # only used to improve the message
        installed = list(hou.hda.loadedFiles())
    if installed and file_path not in installed:
        raise ValueError(
            f"HDA file is not installed, so there is nothing to uninstall: {file_path}. "
            f"Installed files: {installed[:6]}"
        )
    try:
        hou.hda.uninstallFile(file_path)
    except Exception as e:
        raise ValueError(
            f"Failed to uninstall HDA {file_path}: {readable_message(e)}. "
            f"Installed files: {installed[:6] if installed else 'none'}"
        ) from e

    return {
        "success": True,
        "file_path": file_path,
        "message": "HDA file uninstalled.",
    }


###### hda.reload_hda


def reload_hda(file_path: str) -> dict:
    """Reload an HDA file from disk.

    Args:
        file_path: Path to the HDA file to reload.
    """
    require_inside_project_root(file_path, "HDA file")
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"HDA file not found: {file_path}")

    try:
        hou.hda.reloadFile(file_path)
    except Exception as e:
        raise ValueError(f"Failed to reload HDA: {readable_message(e)}") from e

    definitions = hou.hda.definitionsInFile(file_path)
    type_names = [d.nodeTypeName() for d in definitions]

    return {
        "success": True,
        "file_path": file_path,
        "reloaded_types": type_names,
        "type_count": len(type_names),
    }


###### hda.create_hda


def create_hda(
    node_path: str,
    hda_file: str,
    type_name: str,
    label: str,
    version: str = "1.0",
) -> dict:
    """Create a new HDA from an existing subnet node.

    Args:
        node_path: Path to the subnet node to convert.
        hda_file: Destination file path for the HDA.
        type_name: The operator type name for the HDA.
        label: Human-readable label for the HDA.
        version: Version string (default "1.0").
    """
    require_inside_project_root(hda_file, "HDA file")
    node = _get_node(node_path)

    # Verify the node is a subnet
    if not node.isSubNetwork():
        raise ValueError(
            f"Node {node_path} is not a subnet. Only subnet nodes can be converted to HDAs."
        )

    # createDigitalAsset defaults to max_num_inputs=0, so a subnet that processes
    # its input geometry became an asset with no input at all.
    inputs_used = len(node.inputs())
    with contextlib.suppress(Exception):
        for index, item in enumerate(node.indirectInputs()):
            if item.outputConnections():
                inputs_used = max(inputs_used, index + 1)

    try:
        hda_node = node.createDigitalAsset(
            name=type_name,
            hda_file_name=hda_file,
            description=label,
            version=version,
            max_num_inputs=inputs_used,
        )
    except Exception as e:
        raise ValueError(f"Failed to create HDA: {readable_message(e)}") from e

    promoted = _promote_spares_to_definition(hda_node)
    return {
        "success": True,
        "node_path": hda_node.path(),
        "hda_file": hda_file,
        "type_name": type_name,
        "label": label,
        "version": version,
        "max_num_inputs": inputs_used,
        "promoted_parameters": promoted,
    }


def _promote_spares_to_definition(node: hou.Node) -> list[str]:
    """Move a converted subnet's spare parameters into its asset definition.

    createDigitalAsset leaves them as spares on the one converted node: the
    definition's interface stayed empty, every new instance came without the
    knobs, and its internals' ch("../seed") read parameters that were not there.
    Values, expressions and keyframes on the converted node are kept.
    """
    spares = list(node.spareParms())
    if not spares:
        return []
    group = node.parmTemplateGroup()
    saved = {}
    for parm in spares:
        try:
            saved[parm.name()] = ("expr", parm.expression(), parm.expressionLanguage())
        except hou.OperationFailed:
            saved[parm.name()] = (
                "value",
                parm.unexpandedString() if _is_string(parm) else parm.eval(),
            )
    node.removeSpareParms()
    node.type().definition().setParmTemplateGroup(group)
    for name, stored in saved.items():
        parm = node.parm(name)
        if parm is None:
            continue
        with contextlib.suppress(Exception):
            if stored[0] == "expr":
                parm.setExpression(stored[1], stored[2])
            else:
                parm.set(stored[1])
    return sorted({p.tuple().name() for p in spares})


def _is_string(parm: hou.Parm) -> bool:
    return parm.parmTemplate().type() == hou.parmTemplateType.String


_FOLDER_TYPES = {
    "tabs": "Tabs",
    "simple": "Simple",
    "collapsible": "Collapsible",
    "radio": "RadioButtons",
    "radiobuttons": "RadioButtons",
    "import": "ImportBlock",
    "multiparm": "MultiparmBlock",
}


def _menu_pairs(spec: dict) -> tuple:
    """Normalise menu_items into (values, labels).

    Accepts ["a", "b"] or [["a", "A"], ["b", "B"]] — the second form is what
    Houdini's ordered menus actually show, and typing it as pairs beats two
    parallel lists that can silently drift apart.
    """
    items = spec.get("menu_items")
    if not items:
        raise ValueError(f"Menu parameter {spec.get('name')!r} needs menu_items.")
    values, labels = [], []
    for item in items:
        if isinstance(item, (list, tuple)):
            if len(item) != 2:
                raise ValueError(
                    f"Menu item {item!r} on {spec.get('name')!r} must be "
                    f"[value, label] or a plain string."
                )
            values.append(str(item[0]))
            labels.append(str(item[1]))
        else:
            values.append(str(item))
            labels.append(str(item))
    return tuple(values), tuple(labels)


# create_spare_parameters' spelling of the same fields, accepted here so one
# spec works for both verbs.
_SPEC_ALIASES = {
    "parm_name": "name",
    "parm_type": "type",
    "default_value": "default",
    "min_val": "min",
    "max_val": "max",
}


def _menu_default(spec: dict, values: tuple) -> int:
    """A menu's default as an index, checked against its items either way."""
    default = spec.get("default", 0)
    if isinstance(default, str):
        if default not in values:
            raise ValueError(
                f"Default {default!r} of menu {spec.get('name')!r} is not one of its "
                f"items {list(values)}."
            )
        return values.index(default)
    index = int(default)
    if not 0 <= index < len(values):
        raise ValueError(
            f"Default {index} of menu {spec.get('name')!r} is out of range: it has "
            f"{len(values)} item(s), 0-{len(values) - 1}."
        )
    return index


def _build_parm_template(spec: dict, seen: set):
    """Turn one spec dict into a hou.ParmTemplate (recursive for folders)."""
    if not isinstance(spec, dict):
        raise ValueError(f"Each parameter must be a dict, got {type(spec).__name__}.")
    spec = dict(spec)
    for alias, key in _SPEC_ALIASES.items():
        if alias in spec and key not in spec:
            spec[key] = spec.pop(alias)

    name = spec.get("name")
    if not name:
        raise ValueError(f"Parameter spec is missing 'name': {spec}")
    if name in seen:
        raise ValueError(f"Duplicate parameter name {name!r} in this interface.")
    seen.add(name)

    label = spec.get("label") or name.replace("_", " ").title()
    kind = str(spec.get("type", "float")).lower()
    components = int(spec.get("components", 1))
    common = _common_template_kwargs(spec)

    if kind == "folder":
        folder_key = str(spec.get("folder_type", "tabs")).lower()
        if folder_key not in _FOLDER_TYPES:
            raise ValueError(
                f"Unknown folder_type {folder_key!r} on {name!r}. "
                f"Use one of: {sorted(_FOLDER_TYPES)}."
            )
        children = tuple(_build_parm_template(child, seen) for child in spec.get("children", []))
        template = hou.FolderParmTemplate(
            name,
            label,
            parm_templates=children,
            folder_type=getattr(hou.folderType, _FOLDER_TYPES[folder_key]),
            is_hidden=bool(spec.get("hidden", False)),
        )
    elif kind in ("int", "integer"):
        template = hou.IntParmTemplate(
            name,
            label,
            components,
            default_value=_component_defaults(spec, components, int, 0),
            min=spec.get("min", 0),
            max=spec.get("max", 10),
            min_is_strict=bool(spec.get("min_strict", False)),
            max_is_strict=bool(spec.get("max_strict", False)),
            naming_scheme=_naming_scheme(spec, hou.parmNamingScheme.XYZW),
            **common,
        )
    elif kind in ("float", "vector", "color"):
        if kind in ("vector", "color") and "components" not in spec:
            components = 3
        look = hou.parmLook.Regular
        default_scheme = hou.parmNamingScheme.XYZW
        if kind == "color":
            look = hou.parmLook.ColorSquare
            default_scheme = hou.parmNamingScheme.RGBA
        elif kind == "vector":
            look = hou.parmLook.Vector
        template = hou.FloatParmTemplate(
            name,
            label,
            components,
            default_value=_component_defaults(spec, components, float, 0.0),
            min=spec.get("min", 0.0),
            max=spec.get("max", 1.0),
            min_is_strict=bool(spec.get("min_strict", False)),
            max_is_strict=bool(spec.get("max_strict", False)),
            look=look,
            naming_scheme=_naming_scheme(spec, default_scheme),
            **common,
        )
    elif kind == "toggle":
        template = hou.ToggleParmTemplate(
            name, label, default_value=bool(spec.get("default", False)), **common
        )
    elif kind in ("string", "file", "oppath", "node"):
        string_type = {
            "file": hou.stringParmType.FileReference,
            "oppath": hou.stringParmType.NodeReference,
            "node": hou.stringParmType.NodeReference,
        }.get(kind, hou.stringParmType.Regular)
        kwargs: dict = {}
        if spec.get("menu_items"):
            values, labels = _menu_pairs(spec)
            kwargs.update(menu_items=values, menu_labels=labels)
        template = hou.StringParmTemplate(
            name,
            label,
            components,
            default_value=_component_defaults(spec, components, str, ""),
            string_type=string_type,
            naming_scheme=_naming_scheme(spec, hou.parmNamingScheme.Base1),
            **kwargs,
            **common,
        )
    elif kind == "button":
        template = hou.ButtonParmTemplate(name, label, **common)
    elif kind == "separator":
        template = hou.SeparatorParmTemplate(name, is_hidden=bool(spec.get("hidden", False)))
    elif kind == "label":
        template = hou.LabelParmTemplate(
            name,
            label,
            column_labels=tuple(str(c) for c in spec.get("column_labels", ()) or ()),
            **{k: v for k, v in common.items() if k in ("is_hidden", "join_with_next")},
        )
    elif kind == "menu":
        values, labels = _menu_pairs(spec)
        template = hou.MenuParmTemplate(
            name,
            label,
            menu_items=values,
            menu_labels=labels,
            default_value=_menu_default(spec, values),
            menu_type=hou.menuType.Normal,
            **common,
        )
    else:
        raise ValueError(
            f"Unknown parameter type {kind!r} on {name!r}. Use one of: "
            f"int, float, vector, color, string, file, oppath, toggle, menu, "
            f"button, separator, label, folder."
        )

    for key, cond_type in (
        ("hide_when", "HideWhen"),
        ("disable_when", "DisableWhen"),
    ):
        expression = spec.get(key)
        if expression:
            template.setConditional(getattr(hou.parmCondType, cond_type), str(expression))

    if spec.get("help"):
        template.setHelp(str(spec["help"]))

    _apply_default_expression(template, spec)

    if spec.get("tags"):
        template.setTags({str(k): str(v) for k, v in dict(spec["tags"]).items()})

    return template


_NAMING_SCHEMES = {
    "base1": "Base1",
    "xyzw": "XYZW",
    "xyz": "XYZW",
    "rgba": "RGBA",
    "rgb": "RGBA",
    "uvw": "UVW",
    "uv": "UVW",
    "minmax": "MinMax",
    "maxmin": "MaxMin",
    "startend": "StartEnd",
    "beginend": "BeginEnd",
    "xywh": "XYWH",
}


def _naming_scheme(spec: dict, default):
    """The hou.parmNamingScheme a spec asks for (`naming_scheme`), else *default*.

    A 2-component float called `fh_range` is `fh_rangex`/`fh_rangey` under the
    default XYZW scheme and `fh_range1`/`fh_range2` under Base1 — the kind of
    thing that otherwise has to be set by hand on every int and float pair.
    """
    key = spec.get("naming_scheme")
    if key is None:
        return default
    attr = _NAMING_SCHEMES.get(str(key).lower().replace("_", ""))
    if attr is None:
        raise ValueError(
            f"Unknown naming_scheme {key!r} on {spec.get('name')!r}. "
            f"Use one of: {sorted(set(_NAMING_SCHEMES.values()))}."
        )
    return getattr(hou.parmNamingScheme, attr)


def _component_defaults(spec: dict, components: int, cast, fallback) -> tuple:
    """Per-component defaults: a list is taken as is, a scalar is repeated."""
    default = spec.get("default", fallback)
    if isinstance(default, (list, tuple)):
        values = [cast(v) for v in default]
        if len(values) != components:
            raise ValueError(
                f"{spec.get('name')!r}: default has {len(values)} value(s) for "
                f"{components} component(s)."
            )
        return tuple(values)
    return tuple([cast(default)] * components)


def _script_language(spec: dict, key: str = "callback_language"):
    language = str(spec.get(key, "python")).lower()
    if language in ("python", "py"):
        return hou.scriptLanguage.Python
    if language in ("hscript", "hs"):
        return hou.scriptLanguage.Hscript
    raise ValueError(f"{key} must be 'python' or 'hscript', got {language!r}.")


def _common_template_kwargs(spec: dict) -> dict:
    """Constructor kwargs every value template accepts: hidden, join, help,
    callback. Conditionals and default expressions are set afterwards."""
    kwargs: dict = {}
    if spec.get("hidden"):
        kwargs["is_hidden"] = True
    if spec.get("join_with_next"):
        kwargs["join_with_next"] = True
    if spec.get("label_hidden"):
        kwargs["is_label_hidden"] = True
    callback = spec.get("callback")
    if callback:
        kwargs["script_callback"] = str(callback)
        kwargs["script_callback_language"] = _script_language(spec)
    return kwargs


def _apply_default_expression(template, spec: dict) -> None:
    """`default_expression` on a spec: one string, or one per component."""
    expression = spec.get("default_expression")
    if expression is None:
        return
    if not hasattr(template, "setDefaultExpression"):
        raise ValueError(
            f"{spec.get('name')!r}: a {template.type().name()} parameter has no default expression."
        )
    components = template.numComponents()
    if isinstance(expression, (list, tuple)):
        expressions = [str(e) for e in expression]
    else:
        expressions = [str(expression)] * components
    if len(expressions) != components:
        raise ValueError(
            f"{spec.get('name')!r}: {len(expressions)} default expression(s) for "
            f"{components} component(s)."
        )
    language = _script_language(spec, "default_expression_language")
    template.setDefaultExpression(tuple(expressions))
    template.setDefaultExpressionLanguage(tuple([language] * components))


def _describe_template(template) -> dict:
    """Read back what Houdini actually stored for one template.

    Built on parameter_handlers._template_to_dict, so the readback carries
    the default value and hidden state and uses get_parameter_schema's keys.
    """
    info = _template_to_dict(template)
    try:
        conditionals = template.conditionals()
        if conditionals:
            info["conditionals"] = {
                str(key).replace("parmCondType.", ""): value for key, value in conditionals.items()
            }
    except Exception:
        pass
    # Folders are recognised by their reported type, not by isinstance: the
    # group hands back plain ParmTemplates and the check has to survive that.
    if info["type"] == "Folder":
        info["children"] = [_describe_template(child) for child in template.parmTemplates()]
    return info


def set_hda_interface(
    node_path: str,
    parameters: list,
    replace: bool = False,
    dry_run: bool = False,
) -> dict:
    """Author an HDA's Type Properties interface — the definition, not spares.

    `create_spare_parameter` adds parameters to a node INSTANCE; they never
    reach the asset's type. This writes the definition's parameter interface:
    tab folders, strict ranges, ordered menus and Hide/Disable When.

    Each entry of `parameters` is a dict:
        name, label, type (int|float|string|toggle|menu|folder),
        default, min, max, min_strict, max_strict, components,
        menu_items ([value, label] pairs or plain strings),
        folder_type (tabs|simple|collapsible|radio) and children for folders,
        hide_when / disable_when (Houdini conditional expressions), help.
    create_spare_parameters' spelling (parm_name, parm_type, default_value,
    min_val, max_val) is accepted too.

    It is edit_hda_interface with one `insert` per entry (after clearing the
    interface when `replace`): the same checks before anything is written,
    the same single write and the same readback.

    Args:
        node_path: An instance of the HDA whose definition is edited.
        parameters: Interface spec (see above).
        replace: Start from an empty interface instead of appending to the
            existing one. Built-in parameters of the node type cannot be
            removed; Houdini puts them back (`reinstated_by_houdini`).
        dry_run: Validate and report the plan without writing.
    """
    _get_node(node_path)  # a bad path is named before a bad spec
    if not isinstance(parameters, (list, tuple)) or not parameters:
        raise ValueError("parameters must be a non-empty list of specs.")
    ops = [{"op": "insert", "spec": spec} for spec in parameters]
    result = _edit_interface(node_path, ops, dry_run=dry_run, clear_first=bool(replace))
    result["replaced"] = bool(replace)
    return result


###### hda.edit_hda_interface

_COMPONENT_SUFFIXES = {
    "XYZW": ["x", "y", "z", "w"],
    "RGBA": ["r", "g", "b", "a"],
    "UVW": ["u", "v", "w"],
    "XYWH": ["x", "y", "w", "h"],
    "MinMax": ["min", "max"],
    "MaxMin": ["max", "min"],
    "StartEnd": ["start", "end"],
    "BeginEnd": ["begin", "end"],
}


def _component_names(template) -> list[str]:
    """The parameter names a template creates on the node.

    Houdini refuses the whole group when two templates produce the same
    component name — a 2-float `fh_range` under Base1 makes `fh_range2`, which
    collides with a template called `fh_range2` — and says only
    "operation failed" (measured live on 22.0.429). The names are predicted
    here so the collision is reported by name, before anything is written.
    """
    name = template.name()
    if template.type().name() == "Folder":
        return [name]
    count = 1
    with contextlib.suppress(Exception):
        count = int(template.numComponents())
    if count <= 1 or "#" in name:
        return [name]
    scheme = "XYZW"
    with contextlib.suppress(Exception):
        scheme = template.namingScheme().name()
    if scheme == "Base1":
        return [f"{name}{i + 1}" for i in range(count)]
    suffixes = _COMPONENT_SUFFIXES.get(scheme, [str(i + 1) for i in range(count)])
    return [f"{name}{suffixes[i] if i < len(suffixes) else i + 1}" for i in range(count)]


def _is_multiparm(template) -> bool:
    """A multiparm block is a Folder template that is not an actual folder."""
    if template.type().name() != "Folder":
        return False
    with contextlib.suppress(Exception):
        return not template.isActualFolder()
    return False


def _flatten_templates(entries, into_multiparms: bool = False) -> list:
    """Every template in *entries*, folders included, depth-first.

    A multiparm block's children (`item#`) are templates, not parameters of
    the interface: they are left out unless *into_multiparms* (the collision
    scan wants them, because two blocks with an `item#` both make `item1`).
    """
    flat = []
    for entry in entries:
        flat.append(entry)
        if entry.type().name() != "Folder":
            continue
        if _is_multiparm(entry) and not into_multiparms:
            continue
        with contextlib.suppress(Exception):
            flat.extend(_flatten_templates(entry.parmTemplates(), into_multiparms))
    return flat


def _names_under(template) -> set:
    """*template*'s name and every name inside it."""
    names = {template.name()}
    if template.type().name() == "Folder":
        with contextlib.suppress(Exception):
            names |= {t.name() for t in _flatten_templates(template.parmTemplates(), True)}
    return names


def _component_collisions(group) -> list[dict]:
    """Pairs of templates whose names or component names collide.

    Two templates of one name collide (Houdini: "Parameter name 'size' is
    invalid or already exists", measured on 22.0.429) — except folders of
    one tab set, which share a name by design. Multiparm children are
    scanned too: two blocks with an `item#` both make `item1`.
    """
    owners: dict[str, tuple[str, bool]] = {}
    collisions: list[dict] = []
    for template in _flatten_templates(group.entries(), into_multiparms=True):
        is_folder = template.type().name() == "Folder"
        # The tuple's own name is a name on the node as well: `fh_range2` the
        # tuple collides with `fh_range2` the second component of `fh_range`.
        for component in dict.fromkeys([*_component_names(template), template.name()]):
            other = owners.get(component)
            if other is not None and not (other[1] and is_folder):
                collisions.append(
                    {"component": component, "templates": [other[0], template.name()]}
                )
            owners.setdefault(component, (template.name(), is_folder))
    return collisions


def _folder_labels(target) -> tuple | None:
    """A folder target as the labels tuple findFolder wants, or None."""
    if isinstance(target, (list, tuple)):
        return tuple(str(t) for t in target)
    return None


def _find_target(group, target, what: str = "target"):
    """Resolve an op target: a template name, a folder label, or nested labels.

    Names are what `parm_name`s are (`stud_count`, `t`); folders are usually
    addressed by label ("Controls") because their internal names are
    Houdini's (`stdswitcher3_2`). Returns (template, kind).
    """
    labels = _folder_labels(target)
    if labels is not None:
        folder = group.findFolder(labels)
        if folder is None:
            raise ValueError(f"No folder labelled {labels!r} for {what}.")
        return folder, "folder"
    name = str(target)
    template = group.find(name)
    if template is not None:
        return template, ("folder" if template.type().name() == "Folder" else "parm")
    folder = group.findFolder(name)
    if folder is not None:
        return folder, "folder"
    flat = _flatten_templates(group.entries())
    candidates = sorted({t.name() for t in flat} | {t.label() for t in flat if t.label()})
    close = get_close_matches(name, candidates, n=5, cutoff=0.4)
    hint = f" Did you mean: {close}?" if close else ""
    raise ValueError(
        f"No parameter named or folder labelled {name!r} for {what}.{hint} "
        f"(Component names such as 'tx' are not template names: use 't'.)"
    )


def _place(group, template, op: dict) -> str:
    """Insert *template* where *op* says: after / before / in_folder / end."""
    if op.get("after") is not None:
        anchor, _kind = _find_target(group, op["after"], "'after'")
        group.insertAfter(anchor, template)
        return f"after {anchor.name()}"
    if op.get("before") is not None:
        anchor, _kind = _find_target(group, op["before"], "'before'")
        group.insertBefore(anchor, template)
        return f"before {anchor.name()}"
    if op.get("in_folder") is not None:
        folder, kind = _find_target(group, op["in_folder"], "'in_folder'")
        if kind != "folder":
            raise ValueError(f"'in_folder' {op['in_folder']!r} is a parameter, not a folder.")
        group.appendToFolder(folder, template)
        return f"end of folder {folder.label()!r}"
    group.append(template)
    return "end"


_MODIFY_KEYS = (
    "label",
    "help",
    "default",
    "default_expression",
    "default_expression_language",
    "min",
    "max",
    "min_strict",
    "max_strict",
    "hide_when",
    "disable_when",
    "hidden",
    "join_with_next",
    "menu_items",
    "callback",
    "callback_language",
    "naming_scheme",
    "new_name",
    "tags",
)


def _modify_template(template, op: dict) -> list[str]:
    """Apply the `modify` fields of *op* to a cloned template; names what changed."""
    changed: list[str] = []
    if op.get("new_name") is not None:
        template.setName(str(op["new_name"]))
        changed.append("name")
    if op.get("label") is not None:
        template.setLabel(str(op["label"]))
        changed.append("label")
    if op.get("help") is not None:
        template.setHelp(str(op["help"]))
        changed.append("help")
    if "hidden" in op:
        template.hide(bool(op["hidden"]))
        changed.append("hidden")
    if "join_with_next" in op:
        template.setJoinWithNext(bool(op["join_with_next"]))
        changed.append("join_with_next")
    for key, cond_type in (("hide_when", "HideWhen"), ("disable_when", "DisableWhen")):
        if key in op:
            cond = getattr(hou.parmCondType, cond_type)
            if op[key]:
                template.setConditional(cond, str(op[key]))
            else:
                template.setConditional(cond, "")
            changed.append(key)
    if "default" in op:
        components = 1
        with contextlib.suppress(Exception):
            components = template.numComponents()
        kind = template.type().name()
        if kind == "Menu":
            items = tuple(template.menuItems())
            template.setDefaultValue(
                _menu_default({"name": template.name(), "default": op["default"]}, items)
            )
        elif kind == "Toggle":
            template.setDefaultValue(bool(op["default"]))
        elif kind in ("Int", "Float", "String"):
            cast = {"Int": int, "Float": float, "String": str}[kind]
            template.setDefaultValue(
                _component_defaults({"default": op["default"]}, components, cast, cast())
            )
        else:
            raise ValueError(f"A {kind} parameter has no default value to set.")
        changed.append("default")
    if "default_expression" in op:
        _apply_default_expression(template, {"name": template.name(), **op})
        changed.append("default_expression")
    if "min" in op:
        template.setMinValue(op["min"])
        changed.append("min")
    if "max" in op:
        template.setMaxValue(op["max"])
        changed.append("max")
    if "min_strict" in op:
        template.setMinIsStrict(bool(op["min_strict"]))
        changed.append("min_strict")
    if "max_strict" in op:
        template.setMaxIsStrict(bool(op["max_strict"]))
        changed.append("max_strict")
    if op.get("menu_items") is not None:
        values, labels = _menu_pairs({"name": template.name(), "menu_items": op["menu_items"]})
        template.setMenuItems(values)
        template.setMenuLabels(labels)
        changed.append("menu_items")
    if op.get("callback") is not None:
        template.setScriptCallback(str(op["callback"]))
        template.setScriptCallbackLanguage(_script_language(op))
        changed.append("callback")
    if op.get("naming_scheme") is not None:
        template.setNamingScheme(_naming_scheme(op, template.namingScheme()))
        changed.append("naming_scheme")
    if op.get("tags") is not None:
        template.setTags({str(k): str(v) for k, v in dict(op["tags"]).items()})
        changed.append("tags")
    if not changed:
        raise ValueError(f"modify on {template.name()!r} names nothing to change ({_MODIFY_KEYS}).")
    return changed


_OP_ALIASES = {
    "add": "insert",
    "append": "insert",
    "add_button": "insert",
    "add_multiparm": "insert",
    "delete": "remove",
    "show": "show",
    "set": "modify",
    "set_conditional": "modify",
    "set_default": "modify",
    "set_default_expression": "modify",
    "set_label": "modify",
    "rename": "modify",
    "update": "modify",
}


def _refuse_taken(names: set, existing: set, index: int, what: str) -> None:
    """Refuse names already in the interface, by name, before anything is written."""
    taken = sorted(name for name in names if name in existing)
    if taken:
        raise ValueError(
            f"op #{index} ({what}): {taken} already exist(s) in the interface; use "
            f"'replace' or 'modify' for an existing parameter, or another name."
        )


def _apply_op(group, op: dict, index: int, existing: set) -> dict:
    """Apply one op to *group*; returns a record for the reply."""
    if not isinstance(op, dict):
        raise ValueError(f"op #{index} must be a dict, got {type(op).__name__}.")
    raw_kind = str(op.get("op", "")).lower()
    kind = _OP_ALIASES.get(raw_kind, raw_kind)
    record: dict = {"index": index, "op": raw_kind or "?"}
    if kind == "insert":
        spec = op.get("spec")
        if not isinstance(spec, dict):
            raise ValueError(f"op #{index} (insert) needs a 'spec' dict.")
        if raw_kind == "add_button":
            spec = {"type": "button", **spec}
        if raw_kind == "add_multiparm":
            spec = {"type": "folder", "folder_type": "multiparm", **spec}
        seen: set = set()
        template = _build_parm_template(spec, seen)
        _refuse_taken(seen, existing, index, "insert")
        record["placed"] = _place(group, template, op)
        record["names"] = sorted(seen)
        existing.update(seen)
        return record
    if kind in ("remove", "hide", "show"):
        target, target_kind = _find_target(
            group, op.get("name") or op.get("folder"), f"op #{index}"
        )
        record["target"] = target.name()
        record["target_kind"] = target_kind
        if kind == "remove":
            # A removed folder takes its contents with it.
            existing.difference_update(_names_under(target))
            group.remove(target)
        else:
            hidden = kind == "hide" and bool(op.get("hidden", True))
            if target_kind == "folder":
                group.hideFolder(
                    _folder_labels(op.get("name") or op.get("folder")) or target.label(), hidden
                )
            else:
                group.hide(target, hidden)
            record["hidden"] = hidden
        return record
    if kind == "replace":
        target, _target_kind = _find_target(group, op.get("name"), f"op #{index}")
        spec = op.get("spec")
        if not isinstance(spec, dict):
            raise ValueError(f"op #{index} (replace) needs a 'spec' dict.")
        seen = set()
        template = _build_parm_template(spec, seen)
        freed = _names_under(target)
        _refuse_taken(seen, existing - freed, index, "replace")
        group.replace(target, template)
        existing.difference_update(freed)
        existing.update(seen)
        record["target"] = target.name()
        record["names"] = sorted(seen)
        return record
    if kind == "modify":
        target, _target_kind = _find_target(group, op.get("name"), f"op #{index}")
        clone = target.clone()
        record["target"] = target.name()
        record["changed"] = _modify_template(clone, op)
        if clone.name() != target.name():
            _refuse_taken({clone.name()}, existing, index, "rename")
        group.replace(target, clone)
        if clone.name() != target.name():
            existing.discard(target.name())
            existing.add(clone.name())
            record["renamed_to"] = clone.name()
        return record
    if kind == "move":
        target, _target_kind = _find_target(group, op.get("name"), f"op #{index}")
        clone = target.clone()
        group.remove(target)
        record["target"] = target.name()
        record["placed"] = _place(group, clone, op)
        return record
    raise ValueError(
        f"op #{index}: unknown op {raw_kind!r}. Use insert, remove, hide, show, "
        f"replace, modify (rename / set_conditional / set_default are aliases) or move."
    )


def edit_hda_interface(node_path: str, ops: list, dry_run: bool = False) -> dict:
    """Edit an HDA's existing Type Properties interface — atomically.

    `set_hda_interface` only appends. This takes a list of operations over
    the definition's ParmTemplateGroup — insert at a position, remove, hide,
    replace, modify (label / default / default_expression / conditionals /
    menu / callback / rename), move — applies them all to a copy, checks the
    result for name and component-name collisions, and writes once. Any
    failing op leaves the definition untouched.

    Args:
        node_path: An instance of the HDA whose definition is edited.
        ops: Operation dicts, applied in order.
        dry_run: Validate and report the plan without writing.
    """
    _get_node(node_path)  # a bad path is named before bad ops
    if not isinstance(ops, (list, tuple)) or not ops:
        raise ValueError("ops must be a non-empty list of operation dicts.")
    return _edit_interface(node_path, ops, dry_run=dry_run, clear_first=False)


def _edit_interface(node_path: str, ops: list, dry_run: bool, clear_first: bool) -> dict:
    """The one write path of set_hda_interface and edit_hda_interface."""
    node = _get_node(node_path)
    try:
        definition = _get_definition(node)
    except ValueError as exc:
        raise ValueError(
            f"{exc} There is no definition whose interface could be edited; for "
            f"parameters on this node only, use create_spare_parameter."
        ) from exc

    group = definition.parmTemplateGroup()
    before_names = {t.name() for t in _flatten_templates(group.entries())}
    if clear_first:
        group.clear()
    existing = {t.name() for t in _flatten_templates(group.entries())}
    records: list[dict] = []
    for index, op in enumerate(ops):
        try:
            records.append(_apply_op(group, op, index, existing))
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(
                f"op #{index} ({op.get('op') if isinstance(op, dict) else op!r}): "
                f"{readable_message(exc)}"
            ) from exc

    collisions = _component_collisions(group)
    if collisions:
        raise ValueError(
            "Name collision — Houdini would refuse the whole interface: "
            + "; ".join(
                f"'{c['component']}' is produced by both {c['templates'][0]!r} and "
                f"{c['templates'][1]!r}"
                for c in collisions
            )
            + ". A 2-component parameter under Base1 makes <name>1/<name>2; under XYZW, "
            "<name>x/<name>y. Nothing was written."
        )

    planned_templates = {t.name(): t for t in _flatten_templates(group.entries())}
    planned = set(planned_templates)
    result: dict = {
        "success": True,
        "node_path": node_path,
        "type_name": definition.nodeTypeName(),
        "hda_file": definition.libraryFilePath(),
        "dry_run": bool(dry_run),
        "ops": records,
        "added": sorted(planned - before_names),
        "removed": sorted(before_names - planned),
    }
    if dry_run:
        result["message"] = f"{len(records)} op(s) validated; nothing written."
        return result

    # setParmTemplateGroup saves the definition into its .hda library (and a
    # backup beside it), so the library is held to the project root like
    # every other HDA file this server writes. An embedded definition lives
    # in the hip file and answers the literal "Embedded" for a path.
    if not _is_embedded(definition):
        require_inside_project_root(definition.libraryFilePath(), "HDA library")
    try:
        definition.setParmTemplateGroup(group)
    except Exception as exc:
        raise ValueError(
            f"Houdini refused the edited interface: {readable_message(exc)}. Nothing was written."
        ) from exc

    stored_group = definition.parmTemplateGroup()
    stored_list = _flatten_templates(stored_group.entries())
    stored = {t.name(): t for t in stored_list}

    # A tab folder placed next to an existing tab group joins that group and
    # takes its naming series (measured: "controls" was stored as
    # "stdswitcher3_3"), keeping its label. Planned folders missing by name
    # are matched to unclaimed stored folders by label.
    unclaimed = [t for t in stored_list if t.name() not in planned]
    renamed: dict[str, str] = {}
    for name in sorted(planned - set(stored)):
        wanted = planned_templates[name]
        if wanted.type().name() != "Folder":
            continue
        match = next(
            (t for t in unclaimed if t.type().name() == "Folder" and t.label() == wanted.label()),
            None,
        )
        if match is not None:
            unclaimed.remove(match)
            renamed[name] = match.name()

    # Built-in parameters of the node's own type (an Object's Transform,
    # its Subnet folder) cannot be removed from a definition: Houdini puts
    # them back, at the top level, and says nothing (measured live).
    reinstated = sorted(name for name in result["removed"] if name in stored)
    result["removed"] = [name for name in result["removed"] if name not in reinstated]
    result["reinstated_by_houdini"] = reinstated
    added = set(result["added"])
    # A folder the caller placed, stored under another name...
    result["renamed_by_houdini"] = [
        {"requested": name, "stored_as": renamed[name], "label": stored[renamed[name]].label()}
        for name in sorted(renamed)
        if name in added
    ]
    # ...and folders that were already there, renumbered with the series.
    result["renumbered_by_houdini"] = [
        {"name": name, "stored_as": renamed[name], "label": stored[renamed[name]].label()}
        for name in sorted(renamed)
        if name not in added
    ]
    result["not_found_after_write"] = sorted(
        name for name in planned if name not in stored and name not in renamed
    )
    for record in records:
        target = record.get("renamed_to") or record.get("target")
        if record.get("op") in ("hide", "show") and target in stored:
            with contextlib.suppress(Exception):
                record["stored_hidden"] = (
                    stored_group.isFolderHidden(stored[target].label())
                    if record.get("target_kind") == "folder"
                    else stored_group.isHidden(target)
                )
        names = record.get("names") or ([target] if target else [])
        record["stored"] = [
            _describe_template(stored[renamed.get(n, n)])
            for n in names
            if renamed.get(n, n) in stored
        ]

    # Parameters the instance should now carry: value templates only. A
    # folder of a tab set has no tuple of its own (the set's tuple takes the
    # first folder's name), and a multiparm child `item#` exists only as
    # item1, item2, ...
    instance = hou.node(node_path)
    on_node = {parm.name() for parm in instance.parms()}
    on_node |= {t.name() for t in instance.parmTuples()}
    expected = sorted(
        name
        for name in result["added"]
        if planned_templates[name].type().name() != "Folder" and "#" not in name
    )
    result["instance_parms_present"] = [name for name in expected if name in on_node]
    result["instance_parms_missing"] = [name for name in expected if name not in on_node]
    notes = []
    if result["renamed_by_houdini"]:
        notes.append(
            "Houdini renamed the folder(s) in renamed_by_houdini: a tab folder placed next "
            "to an existing tab group joins that group and takes its naming series. The "
            "label and the parameters inside keep the names you asked for."
        )
    if reinstated:
        notes.append(
            "Built-in parameters of the node type cannot be removed from an asset's "
            "interface; Houdini re-adds them at the top level. Hide them instead "
            "({'op': 'hide', 'name': ...})."
        )
    if notes:
        result["note"] = " ".join(notes)
    return result


###### hda.update_hda


def update_hda(node_path: str) -> dict:
    """Save the current node contents back to its HDA definition.

    Args:
        node_path: Path to the HDA node instance.
    """
    node = _get_node(node_path)
    definition = _get_definition(node)
    library = definition.libraryFilePath()
    embedded = _is_embedded(definition)

    def _mtime() -> float | None:
        if embedded:
            return None
        with contextlib.suppress(Exception):
            return os.path.getmtime(library)
        return None

    before = _mtime()
    try:
        node.type().definition().updateFromNode(node)
    except Exception as e:
        raise ValueError(f"Failed to update HDA definition: {readable_message(e)}") from e
    after = _mtime()

    # updateFromNode() writes the library file itself (measured on 22.0.429:
    # the mtime moves and a fresh instance carries the new contents). Saying
    # so, with the file's mtime, spares a caller a second save() through
    # execute_python "just in case". None means "could not tell", not "no".
    saved = None if before is None or after is None else after != before
    if embedded:
        message = (
            "HDA definition updated from node contents. It is embedded in the hip "
            "file, so it is kept when the scene is saved."
        )
    else:
        message = "HDA definition updated from node contents and written to the library file."
    return {
        "success": True,
        "node_path": node.path(),
        "type_name": definition.nodeTypeName(),
        "library_file": library,
        "library_file_mtime": after,
        "saved_to_disk": saved,
        "message": message,
        "note": (
            "To check the result with a fresh instance of the type: its children load "
            "lazily, so cook it (or look one up with node.node('name')) before reading "
            "children() -- an uncooked instance answers with an empty list."
        ),
    }


###### hda.get_hda_sections


def get_hda_sections(node_path: str) -> dict:
    """List all sections in an HDA definition.

    Sections include DialogScript, PythonModule, Help, ExtraFileOptions, etc.

    Args:
        node_path: Path to an HDA node instance.
    """
    node = _get_node(node_path)
    definition = _get_definition(node)

    sections = definition.sections()
    section_info = []

    for name, section in sorted(sections.items()):
        info = {"name": name}
        try:
            content = section.contents()
            info["size_bytes"] = len(content) if content else 0
        except Exception:
            info["size_bytes"] = None
        section_info.append(info)

    return {
        "node_path": node.path(),
        "type_name": definition.nodeTypeName(),
        "section_count": len(section_info),
        "sections": section_info,
    }


###### hda.get_hda_section_content


def get_hda_section_content(node_path: str, section_name: str) -> dict:
    """Read the content of a specific section in an HDA definition.

    Args:
        node_path: Path to an HDA node instance.
        section_name: Name of the section to read (e.g. "PythonModule", "Help").
    """
    node = _get_node(node_path)
    definition = _get_definition(node)

    sections = definition.sections()
    if section_name not in sections:
        available = sorted(sections.keys())
        raise ValueError(
            f"Section '{section_name}' not found in HDA '{definition.nodeTypeName()}'. "
            f"Available sections: {available}"
        )

    try:
        content = sections[section_name].contents()
    except Exception as e:
        raise ValueError(f"Failed to read section '{section_name}': {readable_message(e)}") from e

    return {
        "node_path": node.path(),
        "type_name": definition.nodeTypeName(),
        "section_name": section_name,
        "content": content,
        "size_bytes": len(content) if content else 0,
    }


###### hda.set_hda_section_content


def set_hda_section_content(
    node_path: str,
    section_name: str,
    content: str,
) -> dict:
    """Write content to a specific section in an HDA definition.

    Creates the section if it does not exist.

    Args:
        node_path: Path to an HDA node instance.
        section_name: Name of the section to write (e.g. "PythonModule", "Help").
        content: The content to write to the section.
    """
    node = _get_node(node_path)
    definition = _get_definition(node)

    try:
        definition.addSection(section_name, content)
    except Exception as e:
        raise ValueError(f"Failed to write section '{section_name}': {readable_message(e)}") from e

    return {
        "success": True,
        "node_path": node.path(),
        "type_name": definition.nodeTypeName(),
        "section_name": section_name,
        "size_bytes": len(content) if content else 0,
        "message": f"Section '{section_name}' updated.",
    }


###### hda.list_hda_versions


def list_hda_versions(node_path: str) -> dict:
    """Every installed definition of a node's HDA type, across versions and files.

    Args:
        node_path: An HDA instance.
    """
    node = _get_node(node_path)
    current = _get_definition(node)
    node_type = node.type()
    own = _type_name_components(node_type.name())
    if own is None:
        raise hou.OperationFailed(f"Cannot read the type name of '{node_type.name()}'")
    scope, namespace, name, _ = own

    # Houdini keeps a version in the type name (brick::1.1 is a different
    # NodeType from brick), so allInstalledDefinitions() of one type never
    # shows the family. Walk the category for every type sharing
    # scope, namespace and name.
    versions = []
    for type_name, family_type in node_type.category().nodeTypes().items():
        components = _type_name_components(type_name)
        if components is None or components[:3] != (scope, namespace, name):
            continue
        for definition in family_type.allInstalledDefinitions():
            versions.append(
                {
                    "type_name": type_name,
                    "version": definition.version() or components[3] or None,
                    "library_file": definition.libraryFilePath(),
                    "is_current": definition.isCurrent(),
                    "is_preferred": definition.isPreferred(),
                    "is_instance_type": family_type == node_type,
                }
            )
    versions.sort(key=lambda row: _version_key(row["version"]))
    return {
        "node_path": node.path(),
        "type_name": node_type.name(),
        "family": {"scope": scope, "namespace": namespace, "name": name},
        "current_version": current.version() or None,
        "versions": versions,
    }


def _type_name_components(type_name: str) -> tuple[str, str, str, str] | None:
    """(scope, namespace, name, version) of a full node type name, or None."""
    try:
        parts = hou.hda.componentsFromFullNodeTypeName(type_name)
    except Exception:
        return None
    if not isinstance(parts, (tuple, list)) or len(parts) != 4:
        return None
    return tuple(str(part) for part in parts)


def _version_key(version) -> tuple:
    """Sort key that orders 1.2 before 1.10 and puts an unversioned first."""
    if not version:
        return (0, ())
    parts = []
    for piece in str(version).split("."):
        parts.append((0, int(piece)) if piece.isdigit() else (1, piece))
    return (1, tuple(parts))


###### Registration

register_handler("hda.list_hda_versions", list_hda_versions)
register_handler("hda.list_installed_hdas", list_installed_hdas)
register_handler("hda.get_hda_info", get_hda_info)
register_handler("hda.install_hda", install_hda)
register_handler("hda.uninstall_hda", uninstall_hda)
register_handler("hda.reload_hda", reload_hda)
register_handler("hda.create_hda", create_hda)
register_handler("hda.set_hda_interface", set_hda_interface)
register_handler("hda.edit_hda_interface", edit_hda_interface)
register_handler("hda.update_hda", update_hda)
register_handler("hda.get_hda_sections", get_hda_sections)
register_handler("hda.get_hda_section_content", get_hda_section_content)
register_handler("hda.set_hda_section_content", set_hda_section_content)
