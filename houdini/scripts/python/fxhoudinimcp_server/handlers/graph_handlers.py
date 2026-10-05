"""Graph intelligence handlers for FXHoudini-MCP.

Senior-artist tooling: atomic network building with upfront validation,
whole-network verification, version-exact node documentation, and cook
profiling. These are the commands that let a client plan a whole graph,
prove the plan against the running Houdini before mutating anything,
and then look at the evidence afterwards.
"""

from __future__ import annotations

# Built-in
import contextlib
import copy
import json
import os
import re
import tempfile
import time
import zipfile
from difflib import get_close_matches
from typing import Any

# Third-party
import hou

# Internal
from fxhoudinimcp_server.config import (
    layout_if_enabled,
    place_new_node,
    place_new_nodes,
    update_mode_warning,
)
from fxhoudinimcp_server.dispatcher import register_handler
from fxhoudinimcp_server.errors import readable_message
from fxhoudinimcp_server.handlers.dop_handlers import dop_cache_note
from fxhoudinimcp_server.handlers.node_handlers import (
    _find_input,
    _find_output,
    _indirect_input_item,
    _input_table,
    _output_index,
    _resolve_input_index,
)
from fxhoudinimcp_server.handlers.parameter_handlers import (
    LockedParmError,
    _clear_expression,
    _is_locked,
    _run_callback,
    broken_references,
    locked_message,
    suggest_parms,
    template_labels,
)
from fxhoudinimcp_server.outputs import license_error

###### Helpers

# Folder types whose contents are instance templates rather than parameters.
# MultiparmBlock is the common one; the scroll and tab variants behave the same
# way for naming purposes.
_MULTIPARM_FOLDERS = tuple(
    getattr(hou.folderType, name)
    for name in ("MultiparmBlock", "ScrollingMultiparmBlock", "TabbedMultiparmBlock")
    if hasattr(hou.folderType, name)
)


def _resolve_node_type(category: hou.NodeTypeCategory, type_name: str):
    """Resolve *type_name* in *category* the way createNode would.

    hou.preferredNodeType maps an unversioned name to the version that
    createNode actually instantiates (e.g. copytopoints -> ::2.0).
    """
    with contextlib.suppress(Exception):
        preferred = hou.preferredNodeType(f"{category.name()}/{type_name}")
        if preferred is not None:
            return preferred
    types = category.nodeTypes()
    if type_name in types:
        return types[type_name]
    from fxhoudinimcp_server.handlers.hda_handlers import _version_key

    prefix = type_name + "::"
    versioned = [key for key in types if key.startswith(prefix)]
    if versioned:
        # Numeric order, not string order: ::10.0 is newer than ::2.0.
        return types[max(versioned, key=lambda key: _version_key(key[len(prefix) :]))]
    return None


def _instance_patterns(node_type) -> list[re.Pattern]:
    """Regexes matching the live names of a type's multiparm instances.

    A fresh probe node has zero instances, so `usept0` and `pt0x` on an Add
    SOP were reported as non-existent and a session fell back to a wrangle
    to make three points. The template names carry `#` where the instance
    number goes; a live name is that with digits, plus an optional vector
    component suffix.
    """
    patterns: list[re.Pattern] = []

    def walk(templates) -> None:
        for template in templates:
            if "#" in template.name():
                body = re.escape(template.name()).replace(r"\#", r"\d+")
                patterns.append(re.compile(rf"^{body}[xyzwrgba]?$"))
            if template.type() == hou.parmTemplateType.Folder:
                walk(template.parmTemplates())

    walk(node_type.parmTemplateGroup().entries())
    return patterns


def _is_instance_parm(name: str, patterns: list[re.Pattern]) -> bool:
    return any(p.match(name) for p in patterns)


def _is_dynamic_menu(probe: hou.Node, parm: hou.Parm) -> bool:
    """A menu whose items depend on state a fresh probe cannot have.

    The VOP ``signature`` menu lists only the signature the node currently
    has ("default" on a fresh mtlxmultiply) while ``set()`` accepts every
    signature the shader defines, so validating "color3" against that list
    refused a valid build. Such a menu is left to Houdini.
    """
    try:
        return parm.name() == "signature" and probe.type().category().name() == "Vop"
    except Exception:
        return False


def _connectors_of(node: hou.Node) -> dict[str, list[dict[str, Any]]]:
    """Input and output connectors of a live node, in order, with their names.

    A VOP's inputs are addressed by name (`texcoord`), and their order is not
    stable across versions; a SOP's are `input1`, `input2` behind labels such
    as "Spine curve". Both the index and the name are reported so a caller can
    wire by whichever the verb at hand accepts.
    """
    outputs: list[dict[str, Any]] = []
    names: list[str] = []
    labels: list[str] = []
    with contextlib.suppress(Exception):
        names = list(node.outputNames())
    with contextlib.suppress(Exception):
        labels = list(node.outputLabels())
    for index, name in enumerate(names):
        entry: dict[str, Any] = {"index": index, "name": name}
        if index < len(labels):
            entry["label"] = labels[index]
        outputs.append(entry)
    return {"inputs": _input_table(node), "outputs": outputs}


def _probe_connectors(scratch: hou.Node, node_type, parms: dict | None = None) -> dict:
    """Connectors of *node_type* created inside *scratch* with *parms* applied.

    A VOP's `signature`, a multiparm count or a variadic HDA decides what a
    node exposes, so build_network probes a spec that names an input AND sets
    parms the way the build will configure it: a dry run that passes then
    wires the same connectors the build resolves.
    """
    with hou.undos.disabler():
        probe = scratch.createNode(node_type.name())
        try:
            for name, value in (parms or {}).items():
                with contextlib.suppress(Exception):
                    _apply_parm(probe, name, value)
            return _connectors_of(probe)
        finally:
            with contextlib.suppress(Exception):
                probe.destroy()


def _instance_menu_errors(scratch: hou.Node, node_type, parms: dict, patterns: list) -> list[str]:
    """Menu errors on multiparm instance parms (a wedge's type1), found by probing.

    A fresh probe has no instances, so these menus went unchecked: a dry run
    passed "type1": "int" and the build then rolled back on "Invalid menu
    item". The probe gets the spec's other parms first, which creates the
    instances, then each instance value is checked against its real menu.
    """
    wanted = {
        name: value
        for name, value in parms.items()
        if _is_instance_parm(name, patterns)
        and isinstance(value, (str, int))
        and not isinstance(value, bool)
    }
    if node_type is None or not wanted:
        return []
    problems = []
    with hou.undos.disabler():
        probe = scratch.createNode(node_type.name())
        try:
            for name, value in parms.items():
                if name not in wanted and _expression_value(value) is None:
                    with contextlib.suppress(Exception):
                        _apply_parm(probe, name, value)
            for name, value in wanted.items():
                parm = probe.parm(name)
                if parm is None or not _is_strict_menu(parm.parmTemplate()):
                    continue
                with contextlib.suppress(Exception):
                    items = list(parm.menuItems())
                    if problem := _menu_error(name, value, items):
                        # These tokens are often bare numbers ('0'..'5'); the
                        # labels are what says which one means "Integer".
                        labels = dict(zip(items, parm.menuLabels(), strict=False))
                        problems.append(f"{problem} Labels: {labels}")
        finally:
            with contextlib.suppress(Exception):
                probe.destroy()
    return problems


def _locked_on_build(scratch: hou.Node, node_type, spec: dict) -> dict[str, str]:
    """Parms of *spec* that will still be locked when the build writes them.

    Replays the spec's parms, in order, on a probe of the type -- callbacks
    included when the spec asks for run_callbacks -- because the lock is the
    node's own state: `res_mode` = manual with its callback unlocks
    resolutiony, the same menu set without it does not. Answers {parm: why};
    the build is refused before anything is created, instead of rolled back
    after.
    """
    found: dict[str, str] = {}
    override = bool(spec.get("override_expression"))
    callbacks = bool(spec.get("run_callbacks"))
    with hou.undos.disabler():
        probe = scratch.createNode(node_type.name())
        try:
            for name, value in (spec.get("parms") or {}).items():
                if _expression_value(value) is not None:
                    continue
                try:
                    _apply_parm(probe, name, value, override, callbacks)
                except LockedParmError as exc:
                    found[name] = str(exc)
                except Exception:
                    pass  # a bad value is reported by the rest of validation
            for name in _spec_expressions(spec):
                parm = probe.parm(name)
                if parm is not None and name not in found:
                    reason = locked_message(parm)
                    if reason:
                        found[name] = reason
        finally:
            with contextlib.suppress(Exception):
                probe.destroy()
    return found


# OBJ-level container to probe each category's types in, where more than one
# exists (geo and sopnet both hold SOPs). Any other category is found through
# hou.NodeType.childTypeCategory(), so Cop2, Shop, VopNet and whatever SideFX
# adds next are covered without an entry here.
_PREFERRED_CONTAINERS = {
    "Sop": "geo",
    "Object": "subnet",
    "Vop": "matnet",
    "Lop": "lopnet",
    "Dop": "dopnet",
    "Cop": "copnet",
    "Chop": "chopnet",
    "Top": "topnet",
    "Driver": "ropnet",
}


def _container_for(category_name: str) -> str | None:
    """An OBJ-level type whose children are of *category_name*."""
    object_types = hou.objNodeTypeCategory().nodeTypes()
    preferred = _PREFERRED_CONTAINERS.get(category_name)
    if preferred in object_types:
        return preferred
    fallback = None
    for type_name in sorted(object_types):
        with contextlib.suppress(Exception):
            node_type = object_types[type_name]
            child = node_type.childTypeCategory()
            if child is None or child.name() != category_name:
                continue
            if not node_type.hidden():
                return type_name
            fallback = fallback or type_name
    return fallback


# Connectors per type for the session: probing creates a node, and a card is
# read again and again. Keyed on the HDA definition's modification time too,
# so a reinstalled asset is probed afresh. Each entry is (connectors,
# generated menus): one probe answers both.
_CONNECTOR_CACHE: dict[tuple, tuple[dict, dict]] = {}


def _definition_stamp(node_type) -> Any:
    with contextlib.suppress(Exception):
        definition = node_type.definition()
        if definition is not None:
            return (definition.libraryFilePath(), definition.modificationTime())
    return None


def _is_strict_menu(template) -> bool:
    """A menu whose value build_network checks against its tokens.

    Houdini itself refuses a value off the menu only on a Menu parm; a String
    parm with a "normal" menu takes any text on set() (measured on 22.0.429).
    Such a menu is still checked, because a typo in a token there writes a
    value nothing reads -- but not on a code field (tag editor = 1), where the
    menu only inserts snippets and the text is the point: a popforce's
    VEXpression (localnoiseexpression) was refused as "not a menu item".
    """
    if template.type() == hou.parmTemplateType.Menu:
        return True
    if template.type() != hou.parmTemplateType.String:
        return False
    if template.menuType() != hou.menuType.Normal:
        return False
    with contextlib.suppress(Exception):
        if template.tags().get("editor") == "1":
            return False
    return True


def _generated_menus_of(node: hou.Node) -> dict[str, dict[str, Any]]:
    """Menus a live node computes that its type's templates do not carry.

    `filemerge::2.0` promotes `loadtype` from an inner `file1`, and its items
    come from the script `opmenu -l -a file1 loadtype`. The type's template
    answers menuItems() with an empty tuple, so the card showed a Menu with no
    items, and a session took its tokens off another node's card. A live parm
    runs the script and answers with all seven.

    Returns {parm name: {"generator": script, "items": [...], "labels": [...]}};
    "items" is absent when the live parm had none to offer either.
    """
    generated: dict[str, dict[str, Any]] = {}
    with contextlib.suppress(Exception):
        for parm in node.parms():
            with contextlib.suppress(Exception):
                template = parm.parmTemplate()
                if list(template.menuItems()):
                    continue  # a static menu: the template already has it
                if not _is_strict_menu(template):
                    # A group picker or a wrangle's snippet list: suggestions,
                    # not tokens, and whole VEX snippets doubled the card.
                    continue
                script = ""
                with contextlib.suppress(Exception):
                    script = template.itemGeneratorScript() or ""
                if not script:
                    continue
                entry: dict[str, Any] = {"generator": script}
                items = list(parm.menuItems())
                if items:
                    entry["items"] = items
                    with contextlib.suppress(Exception):
                        entry["labels"] = list(parm.menuLabels())
                generated[parm.name()] = entry
    return generated


def _connectors_for_type(
    category_name: str,
    node_type,
    generated_menus: dict | None = None,
) -> tuple[dict | None, str | None]:
    """Connector names/labels of *node_type*, probed on a throwaway instance.

    Returns (connectors, None), or (None, why) when there was nothing to probe
    in or the probe failed: a card is never refused over its connectors, and
    never reports "no inputs" when it did not look. When *generated_menus* is
    given, it is filled from the same probe with the menus a script computes
    (see _generated_menus_of): one probe, two questions. The probe runs with
    undo disabled and without the type's creation scripts (a documentation
    read must not run an asset's OnCreated); it still marks the scene
    modified, as build_network's dry run does, once per type per session.
    """
    key = (category_name, node_type.name(), _definition_stamp(node_type))
    if key in _CONNECTOR_CACHE:
        connectors, menus = _CONNECTOR_CACHE[key]
        if generated_menus is not None:
            generated_menus.update(menus)
        return connectors, None
    container = _container_for(category_name)
    if container is None:
        return None, f"no network under /obj holds {category_name} nodes to probe in"
    root = hou.node("/obj")
    if root is None:
        return None, "/obj does not exist"
    scratch = None
    try:
        with hou.undos.disabler():
            scratch = root.createNode(container, "fxhoudinimcp_card_probe")
            probe = scratch.createNode(node_type.name(), run_init_scripts=False)
            menus = _generated_menus_of(probe)
            connectors = _connectors_of(probe)
    except Exception as exc:
        return None, f"probing {node_type.name()} failed: {readable_message(exc)}"
    finally:
        with contextlib.suppress(Exception):
            if scratch is not None:
                with hou.undos.disabler():
                    scratch.destroy()
    _CONNECTOR_CACHE[key] = (connectors, menus)
    if generated_menus is not None:
        generated_menus.update(menus)
    return connectors, None


def _parm_names_for_type(
    scratch: hou.Node,
    node_type,
    parm_types: dict | None = None,
    factory_expressions: dict | None = None,
    locked: dict | None = None,
) -> tuple[set, set, dict, list, dict]:
    """Instantiate a type once to learn its parm names, tuple names, menus and
    multiparm instance patterns.

    The third element maps a strict-menu parm name to its token list (see
    _is_strict_menu); a free-text field with a suggestion menu is not a menu.
    The fourth is what `_instance_patterns` returns, the fifth the probe's
    connectors (the same probe answers both questions, and probing is not
    free). Creation scripts run here on purpose: the build that follows runs
    them, so the names validated are the names the built node has.

    The same probe fills two optional tables when they are passed:
    *parm_types* maps each parm name to its template type name ("Int",
    "Float", ...), which is how a string aimed at a numeric parm is caught
    before the build starts; *factory_expressions* maps each parm and parm
    tuple name whose components ship with an expression to {component:
    expression}, so a dry run can name the literals that will not take;
    *locked* maps each parm and parm tuple name with a component the fresh
    node locks (resolutiony on a karmarendersettings) to those components.

    Results are cached per type for the session (probing was 90% of a dry
    run's time), keyed on the HDA definition's modification time, unless a
    strict menu's items come from a script: those can follow the scene (the
    filecache `take` menu lists its takes).
    """
    key = (node_type.category().name(), node_type.name(), _definition_stamp(node_type))
    cached = _PARM_PROBE_CACHE.get(key)
    if cached is not None:
        result, types, expressions, shut_parms = cached
        if parm_types is not None:
            parm_types.update(types)
        if factory_expressions is not None:
            factory_expressions.update(copy.deepcopy(expressions))
        if locked is not None:
            locked.update(copy.deepcopy(shut_parms))
        return copy.deepcopy(result)
    parm_types = {} if parm_types is None else parm_types
    factory_expressions = {} if factory_expressions is None else factory_expressions
    locked = {} if locked is None else locked
    scene_menus = False
    probe = scratch.createNode(node_type.name())
    connectors = _connectors_of(probe)
    if parm_types is not None:
        for parm in probe.parms():
            with contextlib.suppress(Exception):
                parm_types[parm.name()] = parm.parmTemplate().type().name()
    if factory_expressions is not None:
        for parm_tuple in probe.parmTuples():
            found = {
                parm.name(): expression
                for parm in parm_tuple
                if (expression := _expression_of(parm)) is not None
            }
            if found:
                factory_expressions[parm_tuple.name()] = found
                for component, expression in found.items():
                    factory_expressions[component] = {component: expression}
    if locked is not None:
        for parm_tuple in probe.parmTuples():
            shut = [p.name() for p in parm_tuple if _is_locked(p)]
            if shut:
                locked[parm_tuple.name()] = shut
                for component in shut:
                    locked[component] = [component]
    parm_names = {p.name() for p in probe.parms()}
    tuple_names = {pt.name() for pt in probe.parmTuples()}
    menus: dict[str, list[str]] = {}
    for parm in probe.parms():
        if _is_dynamic_menu(probe, parm):
            continue
        with contextlib.suppress(Exception):
            template = parm.parmTemplate()
            items = list(parm.menuItems())
            if items and _is_strict_menu(template):
                menus[parm.name()] = items
                scene_menus = scene_menus or bool(template.itemGeneratorScript())
    probe.destroy()
    result = (parm_names, tuple_names, menus, _instance_patterns(node_type), connectors)
    if not scene_menus:
        _PARM_PROBE_CACHE[key] = (
            copy.deepcopy(result),
            dict(parm_types),
            copy.deepcopy(factory_expressions),
            copy.deepcopy(locked),
        )
    return result


# (category, type, definition stamp) -> (probe result, parm types, factory
# expressions, locked parms); see _parm_names_for_type.
_PARM_PROBE_CACHE: dict[tuple, tuple] = {}


def _menu_error(parm_name: str, value: Any, tokens: list[str]) -> str | None:
    """Why `value` cannot be set on a strict menu parm, or None if it can.

    Houdini only says "Invalid menu item" at set time, after the whole build
    is under way, and build_network then rolls everything back. Catching it
    at validation keeps a typo in one token from costing the whole graph.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        if 0 <= value < len(tokens):
            return None
        return f"parm '{parm_name}': menu index {value} is out of range (0-{len(tokens) - 1})"
    if isinstance(value, str) and value not in tokens:
        close = get_close_matches(value, tokens, n=3, cutoff=0.4)
        hint = f" Did you mean: {close}?" if close else ""
        shown = tokens[:15] + (["..."] if len(tokens) > 15 else [])
        return f"parm '{parm_name}': '{value}' is not a menu item. Items: {shown}.{hint}"
    return None


def _expression_of(parm: hou.Parm) -> str | None:
    """The expression *parm* holds, or None when it holds a plain value."""
    try:
        expression = parm.expression()
    except Exception:
        return None
    return expression or None


def _referenced_parm(parm: hou.Parm) -> str | None:
    """Path of the parm a pure `ch()` reference points at, or None.

    hou.Parm.set() writes THROUGH a bare channel reference: setting tx on a
    node whose tx reads ch("../b1/sizex") changes b1's sizex, not tx.
    """
    with contextlib.suppress(Exception):
        target = parm.getReferencedParm()
        if target is not None and target.path() != parm.path():
            return str(target.path())
    return None


# Everything a node spec may carry. An unknown key used to be dropped in
# silence, so a spec with "children" built an empty container and reported
# success.
_SPEC_KEYS = frozenset(
    {
        "type",
        "name",
        "parms",
        "expressions",
        "exprs",
        "inputs",
        "flags",
        "color",
        "comment",
        "override_expression",
        "run_callbacks",
    }
)

# Keys of one dict entry of a spec's `inputs` list.
_INPUT_KEYS = frozenset({"index", "input_name", "source", "source_output", "indirect_input"})

# Template types that refuse a non-numeric literal. A string aimed at one of
# these is almost always an expression the caller meant to set.
_NUMERIC_TEMPLATES = frozenset({"Int", "Float", "Toggle"})

_EXPRESSION_LANGUAGES = {"hscript": "Hscript", "python": "Python"}


_FLAG_KEYS = frozenset({"display", "render", "bypass", "template"})


def _unknown_key_error(label: str, kind: str, key: str, known: frozenset) -> str:
    """A did-you-mean refusal for a spec or input key build_network does not know."""
    close = get_close_matches(str(key), sorted(known), n=3, cutoff=0.4)
    hint = f" Did you mean: {close}?" if close else f" Known keys: {sorted(known)}."
    return f"node {label}: unknown {kind} key '{key}'.{hint}"


def _is_numeric_text(value: str) -> bool:
    """Whether a string is just a number written out ('3', '-1.5')."""
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _expression_value(value: Any) -> str | None:
    """The expression inside a `{"expr": "..."}` parm value, or None."""
    if isinstance(value, dict) and "expr" in value:
        return str(value["expr"])
    return None


def _expression_language(name: str):
    """hou.exprLanguage for "hscript" / "python"; raises on anything else."""
    key = str(name).strip().lower()
    if key not in _EXPRESSION_LANGUAGES:
        raise ValueError(f"expression language must be 'hscript' or 'python', got {name!r}")
    return getattr(hou.exprLanguage, _EXPRESSION_LANGUAGES[key])


def _spec_expressions(spec: dict) -> dict[str, str]:
    """Every expression a spec asks for, from all three spellings.

    The `expressions` block (or its alias `exprs`), plus any parm in `parms`
    given as `{"expr": "..."}`: `parms` is where a caller reaches first, and a
    bare expression string there used to fail the whole build.
    """
    found: dict[str, str] = {}
    for block in (spec.get("expressions"), spec.get("exprs")):
        for name, expression in (block or {}).items():
            found[name] = str(expression)
    for name, value in (spec.get("parms") or {}).items():
        wrapped = _expression_value(value)
        if wrapped is not None:
            found[name] = wrapped
    return found


def _apply_parm(
    node: hou.Node,
    name: str,
    value: Any,
    override_expression: bool = False,
    run_callbacks: bool = False,
) -> dict[str, dict[str, str]]:
    """Set a parm or parm tuple, broadcasting scalars and coercing floats.

    Answers what the write did to expressions, per component:
    `expressions_kept` for an expression the literal did not replace (a Ray
    SOP's factory `@N.x` on dir), `written_through` for a pure ch() reference
    the value went through into the parm it reads, and `expressions_removed`
    when *override_expression* cleared them first. Nothing is evaluated: an
    eval outside a cook leaves errors on the node that the build's report
    would then pick up.

    A locked component raises LockedParmError before anything is written;
    *run_callbacks* runs the parm's callback after the write, the way the UI
    does -- which is what sets and clears such locks. A callback that raised
    is reported in `callbacks_not_run`.
    """
    parm = node.parm(name)
    parm_tuple = node.parmTuple(name)
    if isinstance(value, (list, tuple)) or parm is None:
        components = list(parm_tuple) if parm_tuple is not None else []
    else:
        components = [parm]
    for component in components:
        reason = locked_message(component)
        if reason:
            raise LockedParmError(reason)
    before = {p.name(): e for p in components if (e := _expression_of(p)) is not None}
    report: dict[str, dict[str, str]] = {}
    through: dict[str, str] = {}
    if before and override_expression:
        for component in components:
            if component.name() in before:
                _clear_expression(component)
        report["expressions_removed"] = before
    elif before:
        through = {
            p.name(): target
            for p in components
            if p.name() in before and (target := _referenced_parm(p)) is not None
        }
    _set_parm_value(name, parm, parm_tuple, value)
    callback = _run_callback(components[0]) if run_callbacks and components else None
    if callback is not None:
        # Keyed the way the other report kinds are: {parm: detail}.
        if callback["run"]:
            report["callbacks_run"] = {name: True}
        else:
            report["callbacks_not_run"] = {name: callback.get("error")}
    if before and not override_expression:
        for component in components:
            after = _expression_of(component)
            if after is None or component.name() not in before:
                continue
            if component.name() in through:
                report.setdefault("written_through", {})[component.name()] = through[
                    component.name()
                ]
            else:
                report.setdefault("expressions_kept", {})[component.name()] = after
    return report


def _set_parm_value(name: str, parm, parm_tuple, value: Any) -> None:
    """The plain write behind _apply_parm."""
    if isinstance(value, (list, tuple)):
        if parm_tuple is None:
            raise ValueError(f"'{name}' is not a parm tuple")
        if len(value) != len(parm_tuple):
            raise ValueError(f"'{name}' has {len(parm_tuple)} components, got {len(value)}")
        if all(isinstance(v, (int, float)) for v in value):
            parm_tuple.set([float(v) for v in value])
        else:
            parm_tuple.set(list(value))
    elif parm is not None:
        parm.set(value)
    elif parm_tuple is not None:
        # Scalar onto a tuple: broadcast across components.
        if isinstance(value, (int, float)):
            parm_tuple.set([float(value)] * len(parm_tuple))
        else:
            parm_tuple.set([value] * len(parm_tuple))
    else:
        raise ValueError(f"parameter '{name}' not found")


def _source_output(value: Any) -> int | str:
    """An output index, or an output name to be resolved against the source.

    A name ("v" on a VOP global, "P") used to die on a bare int() with
    "invalid literal for int()", in a dry run too.
    """
    if isinstance(value, bool):
        raise ValueError(f"source_output must be an output index or name, got {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = str(value).strip()
    return int(text) if text.lstrip("-").isdigit() else text


def _parse_input_entry(entry: Any, position: int) -> dict[str, Any]:
    """What one `inputs` entry of a build_network spec asks for.

    Validation and the build both read entries through this, so they cannot
    disagree about what a spec means.
    """
    if not isinstance(entry, dict):
        return {
            "index": position,
            "input_name": None,
            "source": entry,
            "indirect": None,
            "source_output": 0,
        }
    return {
        "index": int(entry.get("index", position)),
        "input_name": entry.get("input_name"),
        "source": entry.get("source"),
        "indirect": entry.get("indirect_input"),
        "source_output": _source_output(entry.get("source_output", 0)),
    }


# Attributes Houdini reads with a fixed number of components. attribrandomize
# and attribcreate default to 3, so a "pscale" built with them is a vector that
# copytopoints applies as a non-uniform scale, and nothing warns.
_ATTRIB_SIZES = {"pscale": 1, "width": 1, "Alpha": 1, "N": 3, "v": 3, "Cd": 3, "up": 3}
_ATTRIB_SIZES.update(scale=3, orient=4, rot=4)


def _misshapen_attribs(node: hou.Node) -> dict[tuple[str, str], int]:
    """{("point", "pscale"): 3} for standard attributes with the wrong size.

    Reads only geometry that is already cooked: never forces a cook, so an
    undisplayed heavy branch costs nothing here.
    """
    try:
        if not hasattr(node, "geometry") or node.needsToCook():
            return {}
        geo = node.geometry()
    except Exception:
        return {}
    if geo is None:
        return {}
    found = {}
    for kind, attribs in (("point", geo.pointAttribs()), ("prim", geo.primAttribs())):
        for attrib in attribs:
            want = _ATTRIB_SIZES.get(attrib.name())
            if want is not None and attrib.size() != want:
                found[(kind, attrib.name())] = attrib.size()
    return found


def _attrib_size_warnings(node: hou.Node) -> list[str]:
    """Misshapen attributes this node introduced, not ones it inherited."""
    found = _misshapen_attribs(node)
    if not found:
        return []
    with contextlib.suppress(Exception):
        upstream = node.inputs()[0] if node.inputs() else None
        if upstream is not None:
            for key in _misshapen_attribs(upstream):
                found.pop(key, None)
    return [
        f"{kind} attribute '{name}' has {size} components where Houdini's standard "
        f"is {_ATTRIB_SIZES[name]}; set the creating node's size to match"
        for (kind, name), size in found.items()
    ]


_MESSAGE_LINES = 12


def _condensed(message: str) -> str:
    """A node message with repeated lines dropped and the rest capped.

    An HDA solver reports each failing inner node once per field it merges:
    a FLIP solver missing pscale came back as ~40 lines, the one that named
    the cause buried among copies of "Error cooking SOP: .../FLIP_DATA".
    """
    lines = list(dict.fromkeys(line.strip() for line in message.splitlines() if line.strip()))
    if len(lines) > _MESSAGE_LINES:
        lines = lines[:_MESSAGE_LINES] + [f"... {len(lines) - _MESSAGE_LINES} more distinct lines"]
    return "\n".join(lines)


def _node_report(node: hou.Node) -> dict[str, Any]:
    """Path and type, plus errors / warnings / bypassed only when there are any.

    A clean node used to carry errors: [], warnings: [] and bypassed: false,
    which on a 40-node verify was most of the answer. Absent means none.
    """
    report: dict[str, Any] = {"path": node.path(), "type": node.type().name()}
    # A dangling channel reference cooks clean in Houdini, so it is reported
    # as an error here: otherwise a build reads healthy while it is broken.
    # ponytail: scans every parm of every node; cache per verify if large networks get slow.
    errors = [_condensed(e) for e in node.errors()] + [
        e for p in node.parms() for e in broken_references(p)
    ]
    warnings = [_condensed(w) for w in node.warnings()] + _attrib_size_warnings(node)
    if errors:
        report["errors"] = errors
    if warnings:
        report["warnings"] = warnings
    with contextlib.suppress(Exception):
        if node.isBypassed():
            report["bypassed"] = True
    return report


# Stages bigger than this are summarised from the first prims only.
_STAGE_PRIM_CAP = 20000


def _stage_summary(node: hou.Node) -> dict[str, Any] | None:
    """Compact stage evidence for a LOP node: what a render of it would contain.

    A Solaris build used to answer geometry: null, so "is there a camera, are
    the lights in, does every gprim have a material" took three more calls.
    """
    try:
        from pxr import UsdGeom, UsdShade

        stage = node.stage()
    except Exception:
        return None
    if stage is None:
        return None
    counts: dict[str, int] = {}
    meshes = []
    for index, prim in enumerate(stage.Traverse()):
        if index >= _STAGE_PRIM_CAP:
            counts["(truncated)"] = 1
            break
        type_name = str(prim.GetTypeName()) or "(untyped)"
        counts[type_name] = counts.get(type_name, 0) + 1
        # Gprim, not Mesh: a Sphere or Cube LOP renders grey without a
        # material just the same.
        if prim.IsA(UsdGeom.Gprim):
            meshes.append(prim)
    summary: dict[str, Any] = {"prims_by_type": counts}
    lights = sum(n for t, n in counts.items() if "Light" in t)
    summary["cameras"] = counts.get("Camera", 0)
    summary["lights"] = lights
    if meshes:
        with contextlib.suppress(Exception):
            materials, _ = UsdShade.MaterialBindingAPI.ComputeBoundMaterials(
                meshes, UsdShade.Tokens.full
            )
            unbound = [
                str(m.GetPath()) for m, mat in zip(meshes, materials, strict=False) if not mat
            ]
            summary["gprims_without_material"] = len(unbound)
            if unbound:
                summary["unbound_examples"] = unbound[:5]
    return summary


_VOLUME_SUMMARY_KEYS = ("name", "resolution", "min_value", "max_value")


def _geometry_summary(node: hou.Node) -> dict[str, Any] | None:
    """Compact cooked evidence: geometry for a SOP, the stage for a LOP, the
    image layer for a Copernicus COP (whose geometry() is one quad)."""
    if hasattr(node, "stage") and not hasattr(node, "geometry"):
        return _stage_summary(node)
    is_cop = False
    with contextlib.suppress(Exception):
        is_cop = node.type().category().name() == "Cop"
    if is_cop:
        with contextlib.suppress(Exception):
            from fxhoudinimcp_server.handlers.cop_handlers import _layer_summary

            layer = node.layer()
            if layer is not None:
                return {"layer": _layer_summary(layer)}
    if hasattr(node, "tracks") and not hasattr(node, "geometry"):
        # A CHOP's evidence is its channels: that they exist, under the names
        # an export will look for, and that they move.
        with contextlib.suppress(Exception):
            from fxhoudinimcp_server.handlers.chop_handlers import _track_entry

            tracks = node.tracks()
            summary = {"channels": [_track_entry(track) for track in tracks[:12]]}
            if len(tracks) > 12:
                summary["channels_total"] = len(tracks)
            return summary
        return None
    if not hasattr(node, "geometry"):
        return None
    try:
        geo = node.geometry()
    except Exception:
        return None
    if geo is None:
        return None
    bbox = geo.boundingBox()
    summary = {
        "points": geo.intrinsicValue("pointcount"),
        "prims": geo.intrinsicValue("primitivecount"),
        "bbox_min": list(bbox.minvec()),
        "bbox_max": list(bbox.maxvec()),
        "point_attribs": [a.name() for a in geo.pointAttribs()][:30],
    }
    with contextlib.suppress(Exception):
        from fxhoudinimcp_server.handlers.geometry_handlers import prim_type_counts

        if types := prim_type_counts(geo):
            summary["prim_types"] = types
    # A heightfield or a pyro source is volumes: "7 points, attrib P" said
    # nothing about which layers exist or whether they hold anything.
    with contextlib.suppress(Exception):
        from fxhoudinimcp_server.handlers.geometry_handlers import _volume_entry

        volumes = list(geo.primsOfType(hou.primType.Volume)) + list(
            geo.primsOfType(hou.primType.VDB)
        )
        if volumes:
            summary["volumes"] = [
                {k: v for k, v in _volume_entry(prim).items() if k in _VOLUME_SUMMARY_KEYS}
                for prim in volumes[:12]
            ]
            if len(volumes) > 12:
                summary["volumes_total"] = len(volumes)
    warning = update_mode_warning()
    if warning:
        summary["warning"] = warning
    return summary


###### graph.build_network

# Tried in this order when a missing parent's container type is inferred from
# the specs, so a spec of types every context has (null, merge) lands in SOPs.
_INFERRED_CATEGORIES = ("Sop", "Lop", "Dop", "Cop", "Chop", "Top", "Driver", "Vop")


def _missing_parent_container(parent_path: str, nodes: Any) -> str | None:
    """The type to create a missing *parent_path* as, or None.

    Building from an empty /obj or /tasks is the usual start, and it used to
    cost a separate create_node before build_network, whose dry run otherwise
    stopped at "Parent not found" without checking a single spec. Only a
    parent directly under an existing OBJ network (any context's container)
    or TOP manager (a topnet) is created, and only when every spec type
    resolves in one context.
    """
    head, _, name = parent_path.rstrip("/").rpartition("/")
    above = hou.node(head or "/")
    if not name or above is None:
        return None
    holds = above.childTypeCategory().name() if above.childTypeCategory() else None
    if holds not in ("Object", "TopNet"):
        return None
    types = {spec.get("type") for spec in nodes or [] if isinstance(spec, dict)}
    if not types or None in types:
        return None
    categories = hou.nodeTypeCategories()
    for category_name in _INFERRED_CATEGORIES:
        category = categories.get(category_name)
        if category and all(_resolve_node_type(category, t) is not None for t in types):
            if holds == "TopNet":
                return "topnet" if category_name == "Top" else None
            return _container_for(category_name)
    return None


def _dry_run_in_scratch(above, container: str, name: str, nodes: list, parent_path: str) -> dict:
    """Validate *nodes* inside a throwaway container named like the real one.

    Same name, so every path in the answer is the one the real build will use.
    """
    with hou.undos.disabler():
        scratch = above.createNode(container, name)
        try:
            result = build_network(scratch.path(), nodes, dry_run=True)
        finally:
            scratch.destroy()
    result["would_create_parent"] = {"path": parent_path, "type": container}
    return result


def _upstream_with(node: hou.Node, method: str, include_self: bool = False) -> hou.Node | None:
    """*node* (when include_self) or the nearest node up its first inputs having *method*."""
    current = node if include_self else (node.inputs() or (None,))[0]
    seen = set()
    while current is not None and current.path() not in seen:
        if hasattr(current, method):
            return current
        seen.add(current.path())
        current = (current.inputs() or (None,))[0]
    return None


def _build_in_new_container(
    parent_path: str, container: str, nodes: list, dry_run: bool, layout: bool
) -> dict:
    """build_network into a parent created for the purpose; a failed build removes it."""
    head, _, name = parent_path.rstrip("/").rpartition("/")
    above = hou.node(head or "/")
    if dry_run:
        return _dry_run_in_scratch(above, container, name, nodes, parent_path)
    parent = above.createNode(container, name)
    place_new_node(parent)
    try:
        result = build_network(parent.path(), nodes, dry_run=False, layout=layout)
    except Exception:
        parent.destroy()
        raise
    if result.get("success"):
        result["created_parent"] = {"path": parent.path(), "type": container}
    else:
        parent.destroy()
    return result


def build_network(
    parent_path: str,
    nodes: list,
    dry_run: bool = False,
    layout: bool = True,
    **_: Any,
) -> dict:
    """Build a whole node network atomically, with upfront validation.

    Every node type, parameter name, and input reference in the spec is
    validated against the running Houdini BEFORE anything is created —
    invalid specs return the full error list and mutate nothing. With
    dry_run=True only the validation runs.

    Args:
        parent_path: Network to build inside (e.g. "/obj/geo1").
        nodes: Node specs, each a dict:
            type (str, required): node type name (unversioned ok).
            name (str): node name, referenceable by later specs.
            parms (dict): parameter values; lists set whole parm tuples.
                A value written {"expr": "...", "language": "hscript" |
                "python"} is set as an expression (hscript by default). A
                string on a numeric parm is refused during validation and
                answered with that spelling. A literal on a parm that holds
                an expression (a Ray SOP's factory `@N.x` on dir) does not
                replace it: the dry run lists these in
                `expressions_in_the_way`, the build reports
                `expressions_kept`.
            expressions (dict): parm name -> expression, as a whole block
                (alias: exprs). Names are validated like those in `parms`.
            override_expression (bool): clear the expressions that literals
                in `parms` land on, so the literals take. Parms are written
                in the order given.
            run_callbacks (bool): run each parm's callback after its write, as
                the UI does. A LOCKED parm (karmarendersettings resolutiony
                under res_mode autoheight) is refused at validation, nothing
                built, with the lock's controlling menu named in
                `locked_parms`; its callback is what unlocks it, so
                {"res_mode": "manual", "resolution": [...]} with
                run_callbacks: true builds.
            inputs (list): wiring. Entries are either a source string
                (wired positionally) or {"index" | "input_name", "source",
                "source_output"}; "input_name" is a connector name or
                label, as get_node_card lists them, and wins over "index";
                "source_output" is an output index or an output name or
                label ("v", "P").
                Sources resolve to spec node names first, then children of
                parent, then absolute paths. {"indirect_input": n} instead
                of "source" wires from connector n of the parent subnet
                itself.
            flags (dict): display/render/bypass/template booleans.
            color (list[3]) and comment (str): network annotations.
            Any other key, in a spec or in an input entry, is a validation
            error with a did-you-mean, not a request dropped in silence.
        dry_run: Validate only; never mutates the scene.
        layout: Also lay out the whole parent network afterwards, which only
            happens when FXHOUDINIMCP_AUTO_LAYOUT is enabled. It does not gate
            placement: the nodes this call creates are always positioned, each
            relative to its inputs, and nodes that already existed never move.
    """
    parent = hou.node(parent_path)
    errors: list[str] = []
    if parent is None and (container := _missing_parent_container(parent_path, nodes)):
        return _build_in_new_container(parent_path, container, nodes, dry_run, layout)
    if parent is None:
        return {
            "success": False,
            "valid": False,
            "errors": [f"Parent not found: {parent_path}"],
            # Every other command reports a single message; carry one here too so a
            # caller does not have to know that this one answers in a list.
            "message": f"Parent not found: {parent_path}",
        }
    category = parent.childTypeCategory()
    if category is None:
        return {
            "success": False,
            "valid": False,
            "errors": [f"{parent_path} cannot contain child nodes"],
        }

    if not isinstance(nodes, list) or not nodes:
        return {
            "success": False,
            "valid": False,
            "errors": ["'nodes' must be a non-empty list"],
        }

    ###### Phase 1: validate everything before touching the scene

    spec_names: list[str] = []
    existing = {child.name() for child in parent.children()}
    resolved_types: dict[str, Any] = {}

    for index, spec in enumerate(nodes):
        if not isinstance(spec, dict):
            errors.append(f"node #{index}: spec must be a dict, got {type(spec).__name__}")
            continue
        label = spec.get("name") or spec.get("type") or f"#{index}"
        # A key this verb does not know is a request it cannot honour. Dropping
        # it quietly is how a spec with "children" reported success for a
        # subnet that was built empty.
        for key in spec:
            if key not in _SPEC_KEYS:
                errors.append(_unknown_key_error(label, "spec", key, _SPEC_KEYS))
        # {"lock": true} or {"Display": true} used to vanish without a word.
        for key in spec.get("flags") or {}:
            if key not in _FLAG_KEYS:
                errors.append(_unknown_key_error(label, "flag", key, _FLAG_KEYS))
        for entry in spec.get("inputs") or []:
            if isinstance(entry, dict):
                for key in entry:
                    if key not in _INPUT_KEYS:
                        errors.append(_unknown_key_error(label, "input", key, _INPUT_KEYS))
        type_name = spec.get("type")
        if not type_name:
            errors.append(f"node {label}: missing 'type'")
            continue
        if type_name not in resolved_types:
            node_type = _resolve_node_type(category, type_name)
            if node_type is None:
                close = get_close_matches(type_name, list(category.nodeTypes()), n=3, cutoff=0.5)
                hint = f" Did you mean: {close}?" if close else ""
                errors.append(
                    f"node {label}: type '{type_name}' does not exist in {category.name()}.{hint}"
                )
                continue
            resolved_types[type_name] = node_type
        name = spec.get("name")
        if name:
            if name in spec_names:
                errors.append(f"duplicate node name in spec: '{name}'")
            if name in existing:
                errors.append(f"node '{name}' already exists under {parent_path}")
            spec_names.append(name)

    # Learn parameter names by instantiating each unique type once (probe
    # nodes are destroyed immediately; display/render flags restored), so
    # bad parm names fail validation, not the build. Runs even when other
    # errors exist: report everything in one pass. The same probe records
    # each parm's template type and the expressions the type ships with.
    parm_knowledge: dict[str, tuple[set, set, dict, list, dict]] = {}
    template_knowledge: dict[str, dict[str, str]] = {}
    expression_knowledge: dict[str, dict[str, dict[str, str]]] = {}
    locked_knowledge: dict[str, dict[str, list[str]]] = {}
    # Parms a spec would write while they are still locked, per spec label.
    locked_parms: dict[str, dict[str, str]] = {}
    # Connectors of a spec that names an input and sets parms, probed with
    # those parms applied (see _probe_connectors).
    spec_connectors: dict[int, dict] = {}
    if resolved_types:
        display_before = parent.displayNode() if hasattr(parent, "displayNode") else None
        render_before = parent.renderNode() if hasattr(parent, "renderNode") else None
        try:
            for type_name, node_type in resolved_types.items():
                template_knowledge[type_name] = {}
                expression_knowledge[type_name] = {}
                locked_knowledge[type_name] = {}
                parm_knowledge[type_name] = _parm_names_for_type(
                    parent,
                    node_type,
                    parm_types=template_knowledge[type_name],
                    factory_expressions=expression_knowledge[type_name],
                    locked=locked_knowledge[type_name],
                )
            for index, spec in enumerate(nodes):
                if not isinstance(spec, dict):
                    continue
                node_type = resolved_types.get(spec.get("type"))
                names_an_input = any(
                    isinstance(entry, dict) and entry.get("input_name")
                    for entry in spec.get("inputs") or []
                )
                if node_type is not None and spec.get("parms") and names_an_input:
                    spec_connectors[index] = _probe_connectors(parent, node_type, spec["parms"])
                # A lock is the node's own state, so a spec that writes a parm
                # a fresh node locks is replayed in order on a probe of its
                # own -- with its callbacks when it asks for run_callbacks,
                # since those are what clear the lock. Only such a spec: the
                # replay runs the spec's real callbacks, dry run included, and
                # a callback's effects outside the probe cannot be undone.
                shut = locked_knowledge.get(spec.get("type")) or {}
                aimed = set(spec.get("parms") or {}) | set(_spec_expressions(spec))
                if node_type is not None and any(name in shut for name in aimed):
                    found = _locked_on_build(parent, node_type, spec)
                    if found:
                        label = spec.get("name") or spec.get("type") or f"#{index}"
                        locked_parms[label] = found
        finally:
            with contextlib.suppress(Exception):
                if display_before is not None:
                    display_before.setDisplayFlag(True)
                if render_before is not None:
                    render_before.setRenderFlag(True)

    # Refused here, before the build: a locked parm used to fail the build
    # halfway and roll back every node, the ones before it included.
    for label, found in locked_parms.items():
        for parm_name, reason in found.items():
            errors.append(f"node {label}: parm '{parm_name}': {reason}")

    # The parent's input connectors, listed once per build rather than once
    # per entry that uses one.
    # None when the listing itself failed: _indirect_input_item then lists
    # again and reports the real HOM message instead of "not a subnet".
    listed: list = []

    def parent_connectors() -> list | None:
        if not listed:
            connectors: list | None = None
            with contextlib.suppress(Exception):
                connectors = list(parent.indirectInputs())
            listed.append(connectors)
        return listed[0]

    def _source_outputs(source: Any) -> list | None:
        """Output connectors of an input source, or None when they cannot be known."""
        for position, other in enumerate(nodes):
            if isinstance(other, dict) and other.get("name") == source:
                connectors = spec_connectors.get(position)
                knowledge = parm_knowledge.get(other.get("type"))
                if connectors is None and knowledge:
                    connectors = knowledge[4]
                return None if connectors is None else connectors.get("outputs", [])
        node = parent.node(str(source)) or hou.node(str(source))
        return None if node is None else _connectors_of(node)["outputs"]

    # Literals the spec aims at parms whose factory expression will outlive
    # them, named before anything is built.
    in_the_way: dict[str, dict[str, dict[str, str]]] = {}

    for index, spec in enumerate(nodes):
        if not isinstance(spec, dict):
            continue  # already reported above
        label = spec.get("name") or spec.get("type") or f"#{index}"
        if not spec.get("override_expression"):
            shipped = expression_knowledge.get(spec.get("type")) or {}
            for parm_name, value in (spec.get("parms") or {}).items():
                if parm_name in locked_parms.get(label, {}):
                    continue  # refused as locked; an expression note would mislead
                if _expression_value(value) is None and parm_name in shipped:
                    in_the_way.setdefault(label, {})[parm_name] = shipped[parm_name]
        knowledge = parm_knowledge.get(spec.get("type"))
        if knowledge:
            parm_names, tuple_names, menus, instance_patterns, _ = knowledge
            templates = template_knowledge.get(spec.get("type")) or {}
            for parm_name in _spec_expressions(spec):
                if parm_name in parm_names or _is_instance_parm(parm_name, instance_patterns):
                    continue
                if parm_name in tuple_names:
                    # setExpression() is per component; the build would find
                    # no parm by the tuple's name and roll everything back.
                    components = sorted(p for p in parm_names if p.startswith(parm_name))
                    errors.append(
                        f"node {label}: '{parm_name}' is a parm tuple; an expression "
                        f"goes on each component {components}"
                    )
                    continue
                close = get_close_matches(parm_name, sorted(parm_names), n=3, cutoff=0.5)
                hint = f" Did you mean: {close}?" if close else ""
                errors.append(f"node {label}: no parm '{parm_name}' to put an expression on.{hint}")
            for parm_name, value in (spec.get("parms") or {}).items():
                if isinstance(value, dict):
                    # An expression wrapper; its parm name was checked above.
                    unknown = sorted(set(value) - {"expr", "language"})
                    if "expr" not in value:
                        errors.append(
                            f"node {label}: parm '{parm_name}' was given a dict without "
                            f"'expr'. Write {{\"expr\": \"ch('../x')\"}} for an expression, "
                            f"or a plain value."
                        )
                    elif unknown:
                        errors.append(
                            f"node {label}: parm '{parm_name}': unknown key(s) {unknown} "
                            f"in the expression value (known: ['expr', 'language'])"
                        )
                    elif str(value.get("language", "hscript")).strip().lower() not in (
                        _EXPRESSION_LANGUAGES
                    ):
                        errors.append(
                            f"node {label}: parm '{parm_name}': expression language "
                            f"{value['language']!r} is not 'hscript' or 'python'"
                        )
                    continue
                if parm_name in menus:
                    problem = _menu_error(parm_name, value, menus[parm_name])
                    if problem:
                        errors.append(f"node {label}: {problem}")
                elif (
                    isinstance(value, str)
                    and not _is_numeric_text(value)
                    and templates.get(parm_name) in _NUMERIC_TEMPLATES
                ):
                    # Houdini's own refusal is "Cannot set a numeric parm to a
                    # non-numeric value" plus a dump of the C++ overloads,
                    # raised mid-build, so the whole graph rolled back. Caught
                    # here instead, in terms of what the caller meant.
                    errors.append(
                        f"node {label}: parm '{parm_name}' is numeric "
                        f"({templates[parm_name]}) and will not take the string "
                        f"{value!r}. To set it as an expression, write "
                        f'"{parm_name}": {{"expr": {value!r}}} or put it in the '
                        f"spec's 'expressions' block."
                    )
                if (
                    parm_name not in parm_names
                    and parm_name not in tuple_names
                    and not _is_instance_parm(parm_name, instance_patterns)
                ):
                    labels = dict.fromkeys(parm_names | tuple_names, "")
                    if resolved := resolved_types.get(spec.get("type")):
                        labels.update(template_labels(resolved.parmTemplateGroup().entries()))
                    close = suggest_parms(parm_name, labels)
                    hint = f" Did you mean: {close}?" if close else ""
                    errors.append(
                        f"node {label}: parm '{parm_name}' does not exist "
                        f"on {spec.get('type')}.{hint}"
                    )
            errors.extend(
                f"node {label}: {problem}"
                for problem in _instance_menu_errors(
                    parent,
                    resolved_types.get(spec.get("type")),
                    spec.get("parms") or {},
                    instance_patterns,
                )
            )
        node_type = resolved_types.get(spec.get("type"))
        max_inputs = node_type.maxNumInputs() if node_type else 0
        # None when the type did not resolve: that error is already reported,
        # and a connector error on top of it would only be noise.
        connectors = spec_connectors.get(index)
        if connectors is None and knowledge:
            connectors = knowledge[4]
        for position, entry in enumerate(spec.get("inputs") or []):
            wire = _parse_input_entry(entry, position)
            source, indirect = wire["source"], wire["indirect"]
            input_index: int | None = wire["index"]
            if wire["input_name"]:
                # Resolved here, by the rule the build uses, so a wrong
                # name fails the dry run, not the build.
                input_index = None
                if connectors is not None:
                    try:
                        input_index = _find_input(
                            connectors["inputs"], str(wire["input_name"]), max_inputs
                        )
                    except ValueError as exc:
                        errors.append(f"node {label}: {spec.get('type')} {exc}")
            if input_index is not None and input_index >= max_inputs > 0:
                errors.append(
                    f"node {label}: input {input_index} exceeds max inputs "
                    f"({max_inputs}) of {spec.get('type')}"
                )
            if indirect is not None:
                # The parent subnet's own connector: not a node, so it has no
                # path a source string could name.
                if source is not None:
                    errors.append(
                        f"node {label}: an input takes either 'source' or "
                        f"'indirect_input', not both (got {source!r} and {indirect!r})"
                    )
                try:
                    _indirect_input_item(parent, indirect, parent_connectors())
                except ValueError as exc:
                    errors.append(f"node {label}: {exc}")
                if wire["source_output"] != 0:
                    errors.append(
                        f"node {label}: a subnet input connector has one output; "
                        f"source_output must be 0, got {wire['source_output']}"
                    )
                continue
            if (
                source not in spec_names
                and source not in existing
                and hou.node(str(source)) is None
            ):
                errors.append(
                    f"node {label}: input source '{source}' is not a spec "
                    f"node, a child of {parent_path}, or an absolute path"
                )
            elif isinstance(wire["source_output"], str):
                # An output name is resolved here, on what the source exposes
                # (a spec node's probed connectors, or a live node's), so a
                # typo fails the dry run, not the build.
                outputs = _source_outputs(source)
                if outputs is not None:
                    try:
                        _find_output(outputs, wire["source_output"])
                    except ValueError as exc:
                        errors.append(f"node {label}: input source '{source}' {exc}")

    if errors:
        reply: dict[str, Any] = {
            "success": False,
            "valid": False,
            "errors": errors,
            "created": [],
        }
        if locked_parms:
            reply["locked_parms"] = locked_parms
        return reply
    if dry_run:
        result = {
            "success": True,
            "valid": True,
            "dry_run": True,
            "validated_nodes": len(nodes),
            "validated_types": sorted(t.name() for t in resolved_types.values()),
        }
        if in_the_way:
            result["expressions_in_the_way"] = in_the_way
            result["warning"] = (
                f"These parms hold an expression that a literal from the spec will not "
                f"replace: {in_the_way}. Pass override_expression: true on the spec to "
                f"clear it, or set the value as an expression."
            )
        return result

    ###### Phase 2: build (atomic — any failure rolls back)

    created: dict[str, hou.Node] = {}
    # Per node path: what the literals in `parms` did to expressions.
    parm_reports: dict[str, dict[str, dict[str, str]]] = {}
    flags_not_applied: dict[str, list[str]] = {}
    display_moved: dict[str, str] = {}
    try:
        for spec in nodes:
            node = parent.createNode(resolved_types[spec["type"]].name(), spec.get("name"))
            created[spec.get("name") or node.name()] = node

        for spec, node in zip(nodes, created.values(), strict=False):
            override = bool(spec.get("override_expression"))
            callbacks = bool(spec.get("run_callbacks"))
            for parm_name, value in (spec.get("parms") or {}).items():
                if _expression_value(value) is not None:
                    continue  # an {"expr": ...} value, set with the expressions below
                try:
                    written = _apply_parm(node, parm_name, value, override, callbacks)
                except Exception as exc:
                    items = []
                    with contextlib.suppress(Exception):
                        items = list(node.parm(parm_name).menuItems())
                    shown = f" Menu items: {items[:20]}" if items else ""
                    raise RuntimeError(
                        f"{node.path()} parm '{parm_name}': {readable_message(exc)}.{shown}"
                    ) from exc
                for kind, found in written.items():
                    parm_reports.setdefault(node.path(), {}).setdefault(kind, {}).update(found)
            # "build_network cannot set expressions" was a live session's stated
            # reason for rebuilding a lantern rig in execute_python. It can, from
            # `expressions`, from `exprs`, or from an {"expr": ...} value in `parms`.
            languages = {
                name: value.get("language")
                for name, value in (spec.get("parms") or {}).items()
                if isinstance(value, dict)
            }
            for parm_name, expression in _spec_expressions(spec).items():
                parm = node.parm(parm_name)
                if parm is None:
                    raise RuntimeError(
                        f"{node.path()}: no parm '{parm_name}' to put an expression on"
                    )
                language = languages.get(parm_name)
                if language:
                    parm.setExpression(expression, language=_expression_language(language))
                else:
                    parm.setExpression(expression)
            for position, entry in enumerate(spec.get("inputs") or []):
                wire = _parse_input_entry(entry, position)
                source_output = wire["source_output"]
                input_index = _resolve_input_index(node, wire["index"], wire["input_name"])
                if wire["indirect"] is not None:
                    source = parent_connectors()[int(wire["indirect"])]
                else:
                    source_name = wire["source"]
                    source = (
                        created.get(source_name)
                        or parent.node(str(source_name))
                        or hou.node(str(source_name))
                    )
                node.setInput(input_index, source, _output_index(source, source_output))
            flags = spec.get("flags") or {}
            for flag, setter in (
                ("display", "setDisplayFlag"),
                ("render", "setRenderFlag"),
                ("bypass", "bypass"),
                ("template", "setTemplateFlag"),
            ):
                if flag not in flags:
                    continue
                if hasattr(node, setter):
                    getattr(node, setter)(bool(flags[flag]))
                    continue
                # A ROP or VOP has no display/template flag: say so rather
                # than skip it as if it had been set.
                flags_not_applied.setdefault(node.path(), []).append(flag)
                if flag == "display" and flags[flag]:
                    # A usdrender_rop at the end of a stage: what the caller
                    # wants seen is what it renders, its input.
                    upstream = _upstream_with(node, setter)
                    if upstream is not None:
                        upstream.setDisplayFlag(True)
                        display_moved[node.path()] = upstream.path()
            if spec.get("color"):
                node.setColor(hou.Color(tuple(spec["color"])))
            if spec.get("comment"):
                node.setComment(spec["comment"])
                node.setGenericFlag(hou.nodeFlag.DisplayComment, True)
    except Exception as exc:
        for node in created.values():
            with contextlib.suppress(Exception):
                node.destroy()
        return {
            "success": False,
            "valid": False,
            "errors": [f"build failed and was rolled back: {readable_message(exc)}"],
            "created": [],
        }

    # In a network that was empty, Houdini leaves the display flag on the
    # first node created: a Solaris build displayed (and reported) its lone
    # sphere instead of the finished stage. Unless a spec chose, the last
    # node that can carry the flag gets it, as an artist would set it.
    asked_for_display = any(
        isinstance(spec, dict) and "display" in (spec.get("flags") or {}) for spec in nodes
    )
    if not existing and not asked_for_display and created:
        with contextlib.suppress(Exception):
            last = _upstream_with(list(created.values())[-1], "setDisplayFlag", include_self=True)
            if last is not None:
                last.setDisplayFlag(True)

    # Placement is a floor, not a layout option: whatever `layout` says and
    # whatever the auto-layout flag says, a node THIS call created must not be
    # left stacked at the origin. Each lands relative to its inputs, in
    # creation order; nodes that already existed are never moved, so building
    # into a hand-arranged network stays safe.
    place_new_nodes(created.values())

    if layout:
        # The caller also asked for a layout of the parent, which stays gated
        # by the auto-layout flag as before.
        layout_if_enabled(parent)

    ###### Phase 3: verify — cook and report evidence

    display = parent.displayNode() if hasattr(parent, "displayNode") else None
    if display is None:
        display = list(created.values())[-1]
    with contextlib.suppress(hou.OperationFailed):
        display.cook(force=False)

    reports = [_node_report(node) for node in created.values()]
    for report in reports:
        report.update(parm_reports.get(report["path"], {}))
    error_nodes = [r["path"] for r in reports if r.get("errors")]
    evidence = _geometry_summary(display)
    if evidence is None and hasattr(parent, "stage"):
        # Shaders built inside a Material Library: the evidence is the stage
        # the library now authors (its Material prims), not null.
        with contextlib.suppress(Exception):
            evidence = {"stage_of": parent.path(), **_stage_summary(parent)}
    result = {
        "success": True,
        "valid": True,
        "created": reports,
        "display_node": display.path() if display is not None else None,
        "geometry": evidence,
        "error_nodes": error_nodes,
        "node_count": len(reports),
    }
    if flags_not_applied:
        result["flags_not_applied"] = flags_not_applied
    if display_moved:
        result["display_set_upstream"] = display_moved
    # A literal that did not take is part of the spec this call did not
    # build, so it is said at the top level, not only inside a node report:
    # a bare set() used to leave a Ray SOP's @N.x in place and answer success.
    kept = {
        path: sorted(found["expressions_kept"])
        for path, found in parm_reports.items()
        if found.get("expressions_kept")
    }
    through = {
        path: found["written_through"]
        for path, found in parm_reports.items()
        if found.get("written_through")
    }
    warnings: list[str] = []
    if kept:
        result["expressions_kept"] = kept
        warnings.append(
            f"Literal(s) in the spec did not take, the parameter kept its expression: "
            f"{kept}. Pass override_expression: true on the spec to replace them."
        )
    if through:
        result["written_through"] = through
        warnings.append(
            f"These parameters are pure channel references, so the value was written "
            f"into the parameter each one reads, not into itself: {through}. Pass "
            f"override_expression: true on the spec to break the link instead."
        )
    not_run = {
        path: found["callbacks_not_run"]
        for path, found in parm_reports.items()
        if found.get("callbacks_not_run")
    }
    if not_run:
        result["callbacks_not_run"] = not_run
        warnings.append(
            f"Callbacks asked for with run_callbacks did not go through: {not_run}. "
            f"The values were written; what the callback would have done was not."
        )
    if warnings:
        result["warning"] = " ".join(warnings)
    if cache := dop_cache_note(created.values()):
        result["simulation_cache"] = cache
    return result


###### graph.verify_network


def _needs_to_cook(node: hou.Node) -> bool:
    with contextlib.suppress(Exception):
        return bool(node.needsToCook())
    return False


def _has_errors(node: hou.Node) -> bool:
    with contextlib.suppress(Exception):
        return bool(node.errors())
    return False


def verify_network(parent_path: str, force_cook: bool = False, **_: Any) -> dict:
    """Inspect every node in a network: the 'middle-click everything' pass.

    Cooks the display node, then reports per-node errors/warnings/flags
    plus cooked-geometry evidence, so claims about a build can be checked
    against reality in one call.

    `node.errors()` is the verdict of the node's last cook. A node off the
    display chain whose cause of failure was fixed since (a File SOP given
    a path that now exists) keeps listing the old error until something
    cooks it. Such a node, one with errors that needs a cook, is marked
    `stale` and named in `stale_error_nodes`.

    `force_cook=True` cooks the display node with force and recooks every
    node that has errors before the report is taken, so the verdict is about
    the network as it is now. Every erroring node, not only the dirty ones:
    an error left by evaluating a parameter outside a cook does not mark the
    node dirty, and only a forced cook of that node clears it. The default
    cooks the display node only, as before, so a heavy scene is not
    recooked without being asked.
    """
    parent = hou.node(parent_path)
    if parent is None:
        raise ValueError(f"Network not found: {parent_path}")

    display = parent.displayNode() if hasattr(parent, "displayNode") else None
    if display is None:
        # A copnet has no displayNode(): the child with the flag is the answer.
        display = next(
            (c for c in parent.children() if getattr(c, "isDisplayFlagSet", lambda: False)()),
            None,
        )
    if display is not None:
        with contextlib.suppress(hou.OperationFailed):
            display.cook(force=bool(force_cook))

    children = list(parent.children())
    # Recook before any report is taken: a recook cooks the node's inputs
    # too, so a report taken earlier in the same loop could be out of date.
    recooked = set()
    if force_cook:
        for child in children:
            if _has_errors(child):
                with contextlib.suppress(hou.OperationFailed):
                    child.cook(force=True)
                recooked.add(child.path())

    reports = []
    stale_nodes = []
    for child in children:
        report = _node_report(child)
        if child.path() in recooked:
            report["recooked"] = True
        # _has_errors, not report["errors"]: those also list dangling ch()
        # references, which no recook fixes.
        elif _has_errors(child) and _needs_to_cook(child):
            report["stale"] = True
            stale_nodes.append(child.path())
        if getattr(child, "isDisplayFlagSet", lambda: False)():
            report["display"] = True
        reports.append(report)

    error_nodes = [r["path"] for r in reports if r.get("errors")]
    licensing = license_error([e for r in reports for e in r.get("errors", ())])
    result = {
        "parent_path": parent_path,
        "node_count": len(reports),
        "display_node": display.path() if display is not None else None,
        "geometry": _geometry_summary(display) if display is not None else None,
        "error_nodes": error_nodes,
        "stale_error_nodes": stale_nodes,
        "healthy": not error_nodes,
        # Named apart from the rest because no scene change fixes it.
        "license_error": licensing,
        "force_cook": bool(force_cook),
        "nodes": reports,
    }
    if stale_nodes:
        result["note"] = (
            "Errors on stale nodes are from a cook that predates their last change; "
            "call verify_network(force_cook=True) to recook them before judging."
        )
    return result


###### graph.get_node_card

_HELP_ZIP_INDEX: dict[str, str] | None = None

_CATEGORY_HELP_DIRS = {
    "Sop": ["sop"],
    "Object": ["obj"],
    "Driver": ["out"],
    "Dop": ["dop"],
    "Lop": ["lop"],
    "Cop": ["copernicus", "cop"],
    "Cop2": ["cop2"],
    "Chop": ["chop"],
    "Top": ["top"],
    "Vop": ["vex", "vop"],
}


def _help_text(node_type, category_name: str) -> str | None:
    """Houdini's own help for a node type, version-exact, headless-safe."""
    global _HELP_ZIP_INDEX
    # hou.text.expandString, not the deprecated hou.expandString.
    zip_path = os.path.join(hou.text.expandString("$HFS"), "houdini", "help", "nodes.zip")
    if _HELP_ZIP_INDEX is None:
        _HELP_ZIP_INDEX = {}
        if os.path.isfile(zip_path):
            with zipfile.ZipFile(zip_path) as zf:
                _HELP_ZIP_INDEX = {name.lower(): name for name in zf.namelist()}

    # "copytopoints::2.0" -> base "copytopoints" (version stripped);
    # "kinefx::rigpose" -> base "rigpose" (namespace stripped). Help files
    # are stored unversioned (old versions get a trailing dash).
    parts = node_type.name().split("::")
    base = parts[-1]
    if len(parts) > 1 and parts[-1][:1].isdigit():
        base = parts[-2]
    candidates = []
    for help_dir in _CATEGORY_HELP_DIRS.get(category_name, [category_name.lower()]):
        candidates += [
            f"{help_dir}/{base}.txt",
            f"{help_dir}/{base}-.txt",
        ]
    for candidate in candidates:
        actual = _HELP_ZIP_INDEX.get(candidate.lower())
        if actual:
            with zipfile.ZipFile(zip_path) as zf:
                return zf.read(actual).decode("utf-8", "replace")

    embedded = node_type.embeddedHelp()
    return embedded or None


def get_node_card(
    node_type: str,
    context: str = "Sop",
    parm_filter: str = None,
    include_help: bool = True,
    **_: Any,
) -> dict:
    """Version-exact documentation card for a node type.

    Sources everything from the running Houdini: real connector labels,
    real parameter names/defaults/menus, and the node's own shipped help
    text — so there is never a reason to guess.
    """
    categories = hou.nodeTypeCategories()
    category = categories.get(context)
    if category is None:
        raise ValueError(f"Unknown context '{context}'. Available: {sorted(categories.keys())}")
    resolved = _resolve_node_type(category, node_type)
    if resolved is None:
        close = get_close_matches(node_type, list(category.nodeTypes()), n=5, cutoff=0.4)
        raise ValueError(f"Node type '{node_type}' not found in {context}. Close matches: {close}")

    # Connectors, in order, by index AND name: the index of `texcoord` on
    # mtlximage is 3, and until now there was nowhere to read that. The same
    # throwaway probe also answers the menus a live parm computes but the
    # type's template does not carry, so it runs before the parameter walk.
    generated_menus: dict[str, dict[str, Any]] = {}
    connectors, not_probed = _connectors_for_type(context, resolved, generated_menus)

    parms: list[dict[str, Any]] = []
    _PARM_CAP = 80
    _MENU_CAP = 15
    truncated = False
    omitted: list[str] = []
    matched = 0
    for template in resolved.parmTemplateGroup().entriesWithoutFolders():
        name, label = template.name(), template.label()
        if (
            parm_filter
            and parm_filter.lower() not in name.lower()
            and parm_filter.lower() not in label.lower()
        ):
            continue
        matched += 1
        if len(parms) >= _PARM_CAP:
            # Past the cap the card still names the parameter, without its
            # details. A File Cache has 82 parameters and the cap was 80, so
            # `savebackground` was invisible and got hunted down by hand.
            truncated = True
            omitted.append(name)
            continue
        entry: dict[str, Any] = {
            "name": name,
            "label": label,
            "type": template.type().name(),
            "size": template.numComponents(),
        }
        # Hidden parameters are still settable, and skipping them silently made
        # this card answer "that parameter does not exist" about parameters that
        # do. Reported and flagged instead, so a caller can tell the difference
        # between hidden and absent.
        if template.isHidden():
            entry["hidden"] = True
        # A name containing '#' is a multiparm instance template, not a real
        # parameter name: the live parameters are source_volume1, source_volume2
        # and so on. Saying so here saves discovering it by trial and error.
        if "#" in name:
            entry["multiparm_instance"] = True
        with contextlib.suppress(Exception):
            entry["default"] = list(template.defaultValue())
        items: list[str] = []
        menu_source = "template"
        with contextlib.suppress(Exception):
            items = list(template.menuItems())
        with contextlib.suppress(Exception):
            labels = list(template.menuLabels())
            # Tokens alone were "0", "1", "2" for pyrosource's Mode, and the
            # labels (Surface Scatter, Keep Input, Volume Scatter) took a
            # script to read. Sent only when they say more than the tokens.
            if items and labels and labels != items:
                entry["menu_labels"] = labels[:_MENU_CAP]
        generated = generated_menus.get(name)
        if not items and generated:
            # The template has no items because a script computes them
            # (`opmenu -l -a file1 loadtype` on filemerge::2.0). An empty Menu
            # on the card reads as "no menu", and a session then took its
            # tokens off another node's card.
            entry["menu_generator"] = generated["generator"]
            items = list(generated.get("items") or [])
            menu_source = "generator"
            labels = generated.get("labels") or []
            if labels:
                entry["menu_labels"] = list(labels)[:_MENU_CAP]
            if not items:
                entry["note"] = (
                    "This menu's items are computed by the script in "
                    "menu_generator and could not be read off a probe instance; "
                    "the menu is not empty on a real node."
                )
        if items:
            entry["menu"] = items[:_MENU_CAP]
            entry["menu_source"] = menu_source
            if len(items) > _MENU_CAP:
                # Silent truncation reads as "these are all the options",
                # which is how a caller picks a token that is not in a menu
                # it never saw the rest of.
                entry["menu_truncated"] = True
                entry["menu_count"] = len(items)
        parms.append(entry)

    # Multiparm blocks, which are the reason a parameter can be real and yet
    # findable under no name the caller can guess: the folder's own name is the
    # instance count parameter, and the contents are templates with '#' in them.
    # Recursive, because a multiparm block is almost always nested inside a
    # regular tab folder rather than sitting at the top level. Walking only the
    # top level found none on any real node type.
    multiparms: list[dict[str, Any]] = []

    def _collect_multiparms(entries) -> None:
        for folder in entries:
            if not isinstance(folder, hou.FolderParmTemplate):
                continue
            with contextlib.suppress(Exception):
                if folder.folderType() in _MULTIPARM_FOLDERS:
                    multiparms.append(
                        {
                            "count_parm": folder.name(),
                            "label": folder.label(),
                            "folder_type": folder.folderType().name(),
                            "instance_parms": [
                                child.name()
                                for child in folder.parmTemplates()
                                if "#" in child.name()
                            ][:_PARM_CAP],
                            # Where "#" starts counting: Rig Pose's first
                            # instance is group0, most nodes' is name1, and
                            # guessing wrong cost a failed set_parameters.
                            "first_index": int(folder.tags().get("multistartoffset", "1")),
                        }
                    )
            with contextlib.suppress(Exception):
                _collect_multiparms(folder.parmTemplates())

    _collect_multiparms(resolved.parmTemplateGroup().entries())

    help_text = _help_text(resolved, context) if include_help else None
    if help_text and len(help_text) > 5000:
        help_text = help_text[:5000] + "\n[... help truncated]"

    card = {
        "type": resolved.name(),
        "label": resolved.description(),
        "context": context,
        "min_inputs": resolved.minNumInputs(),
        "max_inputs": resolved.maxNumInputs(),
        "max_outputs": resolved.maxNumOutputs(),
        "connectors_probed": connectors is not None,
        "is_generator": resolved.minNumInputs() == 0,
        "parm_count": len(parms),
        "parms_matched": matched,
        # Capped: 274 names (5.6 KB) on a Pyro Solver card filtered to a few.
        "parms_omitted": omitted[:50],
        **({"parms_omitted_count": len(omitted)} if len(omitted) > 50 else {}),
        "parms_truncated": truncated,
        "parms": parms,
        "multiparms": multiparms,
    }
    if help_text is not None:
        card["help"] = help_text
    if connectors is not None:
        card["inputs"] = connectors["inputs"]
        card["outputs"] = connectors["outputs"]
    else:
        card["connectors_note"] = f"Connectors were not read: {not_probed}."
    return card


###### graph.find_expensive_nodes


def find_expensive_nodes(
    root_path: str = "/",
    frame: float = None,
    limit: int = 15,
    **_: Any,
) -> dict:
    """Profile cooking under *root_path* and rank nodes by cook cost.

    Records a hou.perfMon profile while force-cooking the display SOPs
    under the root, then returns the most expensive nodes — how a senior
    finds the slow node instead of guessing.
    """
    root = hou.node(root_path)
    if root is None:
        raise ValueError(f"Node not found: {root_path}")

    if frame is not None:
        hou.setFrame(frame)

    # Collect containers whose children we will force-cook. cook(force)
    # only re-cooks the node itself — cached upstream results record as
    # zero — so every node must be cooked individually inside the profile.
    containers: list[hou.Node] = []
    if hasattr(root, "displayNode") and root.displayNode() is not None:
        containers.append(root)
    else:
        for child in root.allSubChildren():
            if hasattr(child, "displayNode") and child.displayNode() is not None:
                containers.append(child)
            if len(containers) >= 25:
                break

    targets: list[hou.Node] = []
    _NODE_CAP = 300
    for container in containers:
        for child in container.children():
            targets.append(child)
            if len(targets) >= _NODE_CAP:
                break
        if len(targets) >= _NODE_CAP:
            break

    profile = hou.perfMon.startProfile("fxhoudinimcp_expensive_nodes")
    try:
        for target in targets:
            with contextlib.suppress(hou.OperationFailed, AttributeError):
                target.cook(force=True)
    finally:
        profile.stop()

    out = os.path.join(tempfile.mkdtemp(), "profile.hperf")
    profile.save(out)
    with open(out, encoding="utf-8") as fh:
        data = json.load(fh)

    rows: list[tuple[float, str]] = []

    def _walk(entry: dict, path_parts: list[str]) -> None:
        name = entry.get("name", "")
        is_real_node = (
            bool(name)
            and not name.startswith("{")
            and name
            not in (
                "Total Statistics",
                "Other",
                "Nodes",
            )
        )
        parts = path_parts + [name] if is_real_node else path_parts
        cook_ms = 0.0
        for frame_block in (entry.get("stats") or {}).values():
            for sub in frame_block.values():
                cook_ms += sub.get("Cook", 0.0)
        if is_real_node and cook_ms >= 0.5:
            rows.append((cook_ms, "/" + "/".join(parts)))
        for child in entry.get("children") or []:
            _walk(child, parts)

    _walk(data.get("stats", {}), [])
    rows.sort(reverse=True)

    return {
        "root_path": root_path,
        "cooked_nodes": len(targets),
        "top_nodes": [{"path": path, "cook_ms": round(ms, 2)} for ms, path in rows[:limit]],
        "note": (
            "cook_ms is cumulative (parents include children); compare "
            "siblings to find the real hotspot"
        ),
    }


###### Registration

register_handler("graph.build_network", build_network)
register_handler("graph.verify_network", verify_network)
register_handler("graph.get_node_card", get_node_card)
register_handler("graph.find_expensive_nodes", find_expensive_nodes)


###### graph.cook_frame_range

# A sequential solver has to be cooked in order, one frame at a time, and the
# only evidence that it is doing anything is how its output changes across those
# frames. Doing that from the client costs one round trip per frame -- ~50ms
# each before any work happens -- so a 100 frame check was 100 round trips, and
# the alternative was execute_python. Six of thirteen execute_python calls in one
# recorded session were this, every one of them explaining that no tool steps a
# SOP-level solver. step_simulation does not: it requires a DOP network, never
# cooks, and returns no measurements.
_MAX_FRAMES = 480
_FRAME_ATTRIB_CAP = 8


def _frame_stats(entry: dict[str, Any]) -> dict[str, Any]:
    """One attribute's aggregates for a frame row, per axis for a vector.

    min/max over all of P's components mixes x, y and z, so "did the liquid
    land on the ground" could not be read off it; the y range answers that.
    """
    row = {k: v for k, v in entry.items() if k in ("min", "max", "mean", "sum")}
    if entry.get("per_component"):
        row["per_axis"] = [[c["min"], c["max"]] for c in entry["per_component"]]
    return row


def _frame_measurement(
    node: hou.Node,
    attribs: list[str] | None,
    volumes: bool,
) -> dict[str, Any]:
    """What changed on this frame: counts, errors, and the asked-for aggregates."""
    row: dict[str, Any] = {}
    geo = node.geometry()
    if geo is None:
        row["points"] = row["prims"] = 0
        return row
    # Intrinsics, not len(iterPoints()): that builds a Python object per point,
    # every frame, on exactly the heavy sims this tool is for.
    row["points"] = geo.intrinsicValue("pointcount")
    row["prims"] = geo.intrinsicValue("primitivecount")
    # Counts stay flat while pieces fall or cloth drapes; the bounds are the
    # cheap proof that anything moved.
    bbox = geo.boundingBox()
    row["bbox"] = [list(bbox.minvec()), list(bbox.maxvec())]

    if attribs:
        from fxhoudinimcp_server.handlers.geometry_handlers import _get_attrib_stats

        stats = _get_attrib_stats(
            node_path=node.path(),
            attribs=attribs[:_FRAME_ATTRIB_CAP],
            attrib_class="point",
        )
        row["attribs"] = {name: _frame_stats(entry) for name, entry in stats["stats"].items()}
        if stats["missing"]:
            row["missing_attribs"] = stats["missing"]

    if volumes:
        from fxhoudinimcp_server.handlers.geometry_handlers import _get_volume_info

        info = _get_volume_info(node_path=node.path())
        row["volumes"] = [
            {
                k: v
                for k, v in entry.items()
                if k in ("name", "resolution", "active_voxels", "min_value", "max_value")
            }
            for entry in info["volumes"]
        ]
    return row


def _shape(row: dict[str, Any]) -> tuple:
    return row.get("points"), row.get("prims"), json.dumps(row.get("bbox"))


def cook_frame_range(
    node_path: str,
    start: float | None = None,
    end: float | None = None,
    step: float = 1.0,
    attribs: list[str] | str | None = None,
    volumes: bool = False,
    **_: Any,
) -> dict[str, Any]:
    """Cook a node frame by frame and report what changed on each frame.

    This is the tool for proving a simulation is doing something, and the only
    correct way to advance a sequential solver: frames are cooked in order, so a
    SOP solver, a DOP network or a plain animated chain all accumulate properly.

    The frame is left at the last one cooked, because that is what stepping a
    solver means; the caller usually wants to screenshot or read it afterwards.

    There is no deadline: the range runs under Houdini's progress bar, and when
    it is stopped from there the frames cooked so far come back with
    ``interrupted``. A node that keeps its own cache across frames (Trail, a
    SOP Solver) starts from what it already holds: press its reset button
    (press_button, e.g. Trail's ``clear``) or reset_simulation first, then
    cook from the first frame.

    Args:
        node_path: Node to cook. Its output is what gets measured.
        start: First frame. Defaults to the playbar start.
        end: Last frame, inclusive. Defaults to the playbar end.
        step: Frame increment. 1.0 for a sequential solver -- skipping frames
            gives a solver a discontinuous time step and invalid results.
        attribs: Point attributes to aggregate per frame (min/max/mean/sum).
        volumes: Also report per-volume name, resolution and value range.
    """
    node = hou.node(node_path)
    if node is None:
        raise hou.OperationFailed(f"Node not found: {node_path}")

    playbar_start, playbar_end = hou.playbar.frameRange()
    start = float(playbar_start if start is None else start)
    end = float(playbar_end if end is None else end)
    if step <= 0:
        raise ValueError("step must be greater than 0")
    if end < start:
        raise ValueError(f"end ({end}) is before start ({start})")

    count = int((end - start) / step) + 1
    if count > _MAX_FRAMES:
        raise ValueError(
            f"{count} frames requested; the cap is {_MAX_FRAMES}. Narrow the "
            "range, or raise step if the node is not a sequential solver."
        )

    if isinstance(attribs, str):
        attribs = [attribs]

    frames: list[dict[str, Any]] = []
    total_ms = 0.0
    first_error_frame: float | None = None

    interrupted_at: float | None = None
    # No deadline (dispatcher): a heavy sim takes as long as it takes, so the
    # range runs under Houdini's progress bar and is stopped from there; the
    # frames cooked by then are the answer.
    with hou.InterruptableOperation(
        "Cooking frames",
        long_operation_name=f"cook_frame_range {node_path}",
        open_interrupt_dialog=True,
    ) as operation:
        for index in range(count):
            frame = start + index * step
            try:
                operation.updateLongProgress(
                    index / count, f"Frame {frame:g} ({index + 1}/{count})"
                )
            except hou.OperationInterrupted:
                interrupted_at = frame
                break
            hou.setFrame(frame)
            began = time.time()
            try:
                node.cook(force=False)
                cook_error = None
            except hou.OperationInterrupted:
                interrupted_at = frame
                break
            except hou.OperationFailed as exc:
                # A cook failure is data, not a reason to abandon the range: a solver
                # that fails on one frame and recovers is exactly what the caller is
                # trying to see.
                cook_error = str(exc).splitlines()[0][:200]
            elapsed_ms = round((time.time() - began) * 1000, 1)
            total_ms += elapsed_ms

            row: dict[str, Any] = {"frame": frame, "cook_ms": elapsed_ms}
            if cook_error:
                row["cook_error"] = cook_error
            with contextlib.suppress(hou.OperationFailed):
                # Only when there are any: an empty pair per frame is most of a
                # 240-frame answer.
                if errors := [e.splitlines()[0][:200] for e in node.errors()]:
                    row["errors"] = errors
                if warnings := [w.splitlines()[0][:200] for w in node.warnings()]:
                    row["warnings"] = warnings
            if row.get("errors") and first_error_frame is None:
                first_error_frame = frame
            try:
                row.update(_frame_measurement(node, attribs, volumes))
            except hou.OperationFailed as exc:
                row["measure_error"] = str(exc).splitlines()[0][:200]
            frames.append(row)

    shown = _thin_frame_rows(frames)
    result: dict[str, Any] = {
        "node_path": node_path,
        "start": start,
        "end": end,
        "step": step,
        "frames_cooked": len(frames),
        "total_cook_ms": round(total_ms, 1),
        "mean_cook_ms": round(total_ms / len(frames), 1) if frames else 0.0,
        "first_error_frame": first_error_frame,
        # True when counts and bounds never changed: the node cooks, but over
        # this range it does nothing, which is what a sim with no gravity, a
        # pinned-everything cloth or an unconnected source looks like.
        "static": len(frames) > 1 and all(_shape(row) == _shape(frames[0]) for row in frames),
        "current_frame": hou.frame(),
        "frames": shown,
    }
    if interrupted_at is not None:
        result["interrupted"] = True
        result["interrupted_at_frame"] = interrupted_at
        result["interrupted_note"] = (
            f"Stopped from Houdini's progress bar at frame {interrupted_at:g}; the rows "
            "above are the frames cooked before that."
        )
    if frames:
        slowest = max(frames, key=lambda row: row["cook_ms"])
        result["slowest_frame"] = {"frame": slowest["frame"], "cook_ms": slowest["cook_ms"]}
    if len(shown) < len(frames):
        result["frames_shown"] = len(shown)
        result["frames_note"] = (
            "Rows are evenly spaced frames plus every frame with an error or "
            "warning; the totals above cover every frame. Cook a narrower range "
            "for every row."
        )
    return result


# Rows returned when a range is long: 48 frames of a crowd were 15 KB of rows
# that differed in the fourth digit, and 240 would have been 75 KB.
_FRAME_ROWS_SHOWN = 25


def _thin_frame_rows(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Evenly spaced rows (first and last included) plus every row with a problem."""
    if len(frames) <= _FRAME_ROWS_SHOWN:
        return frames
    last = len(frames) - 1
    keep = {round(i * last / (_FRAME_ROWS_SHOWN - 1)) for i in range(_FRAME_ROWS_SHOWN)}
    flagged = [
        i
        for i, row in enumerate(frames)
        if row.get("errors") or row.get("cook_error") or row.get("warnings")
    ]
    keep.update(flagged[:_FRAME_ROWS_SHOWN])
    return [frames[i] for i in sorted(keep)]


register_handler("graph.cook_frame_range", cook_frame_range)


###### graph.get_cook_status


def get_cook_status(node_path: str = "/obj", **_: Any) -> dict:
    """Whether a node has cooked, how often, and whether it changes per frame.

    Read the limitation first: every command runs on Houdini's main thread, so a
    long cook BLOCKS the bridge and cannot be polled from outside while it runs.
    A recorded session ended up watching the Houdini process's CPU from
    PowerShell for exactly that reason, and no tool can change that shape. What
    this answers is the after-the-fact question -- did the thing actually recook,
    is it time dependent, did it end up in error. For genuinely asynchronous
    work, use a ROP's background execution and poll get_render_progress.

    Args:
        node_path: Node to report on.
    """
    node = hou.node(node_path)
    if node is None:
        raise hou.OperationFailed(f"Node not found: {node_path}")

    result: dict[str, Any] = {
        "node_path": node.path(),
        "type": node.type().name(),
        "frame": hou.frame(),
    }
    for key, method in (
        ("cook_count", "cookCount"),
        ("is_time_dependent", "isTimeDependent"),
    ):
        with contextlib.suppress(Exception):
            result[key] = getattr(node, method)()
    with contextlib.suppress(Exception):
        result["errors"] = [e.splitlines()[0][:200] for e in node.errors()]
        result["warnings"] = [w.splitlines()[0][:200] for w in node.warnings()]
    with contextlib.suppress(Exception):
        result["unsaved_changes"] = hou.hipFile.hasUnsavedChanges()
    with contextlib.suppress(Exception):
        result["hip_file"] = hou.hipFile.path()
    return result


register_handler("graph.get_cook_status", get_cook_status)
