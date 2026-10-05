"""Shelf tool handlers for FXHoudini-MCP.

Some of Houdini's most useful setups are not authored by node creation at all:
they are shelf tools. The ocean procedural is the clear case -- its internals come
from ``dopparticlefluidtoolutils.largeOcean``, so build_network structurally
cannot produce it. A recorded session spent seven execute_python calls listing
shelf tools, reading their scripts and calling the worker functions by hand, every
one of them noting that no dedicated tool exposes any of this.

Reading the script matters as much as running it: SideFX's own recipe for a
horizon-scale ocean (layered spectra on an 8km grid, so the waves do not visibly
tile) lives in that script, and it is the difference between a fire-shaped blob
and the real thing.
"""

from __future__ import annotations

# Built-in
import contextlib
import fnmatch
from collections.abc import Iterator
from typing import Any

# Third-party
import hou

# Internal
from fxhoudinimcp_server.dispatcher import register_handler
from fxhoudinimcp_server.errors import as_int, as_text
from fxhoudinimcp_server.ui import keep_viewer_state

###### Helpers

_LIST_CAP = 60
_SCRIPT_CAP = 20_000

# Top-level networks a shelf tool might build in.
_WATCHED_NETWORKS = ("/obj", "/stage", "/out", "/mat", "/img")

# What a shelf tool script expects to find in `kwargs`. Houdini populates these
# from the click that invoked the tool; a programmatic call has to supply them.
_DEFAULT_KWARGS: dict[str, Any] = {
    "pane": None,
    "activepane": None,
    "altclick": False,
    "ctrlclick": False,
    "shiftclick": False,
    "cmdclick": False,
    "autoplace": True,
    "branch": None,
}


def _tool_entry(tool, include_help: bool = False) -> dict[str, Any]:
    entry: dict[str, Any] = {"name": tool.name()}
    with contextlib.suppress(Exception):
        entry["label"] = tool.label()
    with contextlib.suppress(Exception):
        entry["language"] = tool.language().name()
    with contextlib.suppress(Exception):
        keywords = list(tool.keywords())
        if keywords:
            entry["keywords"] = keywords[:8]
    if include_help:
        with contextlib.suppress(Exception):
            help_text = tool.help() or ""
            entry["help"] = help_text[:400]
    return entry


###### shelf.list_shelf_tools


def list_shelf_tools(
    filter: str | None = None,
    limit: int = _LIST_CAP,
    **_: Any,
) -> dict[str, Any]:
    """Find shelf tools by name, label or keyword.

    A full install ships around 8,000 of them, so an unfiltered list is useless;
    filter by what the setup is called ("ocean", "vellum", "fracture").

    Args:
        filter: Substring matched against name, label and keywords.
        limit: Maximum tools to return.
    """
    tools = hou.shelves.tools()
    needle = as_text(filter, "filter").strip().lower()
    limit = as_int(limit, "limit")

    matched = []
    for name, tool in tools.items():
        if needle:
            haystack = name.lower()
            with contextlib.suppress(Exception):
                haystack += " " + (tool.label() or "").lower()
            with contextlib.suppress(Exception):
                haystack += " " + " ".join(tool.keywords()).lower()
            if needle not in haystack:
                continue
        matched.append((name, tool))

    matched.sort(key=lambda pair: pair[0])
    shown = matched[: max(1, limit)]
    return {
        "filter": filter,
        "total_installed": len(tools),
        "matched": len(matched),
        "returned": len(shown),
        "truncated": len(matched) > len(shown),
        "tools": [_tool_entry(tool) for _, tool in shown],
    }


register_handler("shelf.list_shelf_tools", list_shelf_tools)


###### shelf.get_shelf_tool_script


def get_shelf_tool_script(tool_name: str, **_: Any) -> dict[str, Any]:
    """The script a shelf tool runs, plus its help.

    This is how you learn SideFX's own recipe for a setup rather than
    reinventing it. Most scripts are a couple of lines that call a worker in a
    toolutils module, which names exactly what to read next.

    Args:
        tool_name: Internal tool name, as returned by list_shelf_tools.
    """
    tools = hou.shelves.tools()
    tool = tools.get(tool_name)
    if tool is None:
        from difflib import get_close_matches

        close = get_close_matches(tool_name, list(tools), n=5, cutoff=0.4)
        raise ValueError(
            f"No shelf tool named '{tool_name}'."
            + (f" Close matches: {close}" if close else " Try list_shelf_tools(filter=...).")
        )

    script = ""
    with contextlib.suppress(Exception):
        script = tool.script() or ""
    result = _tool_entry(tool, include_help=True)
    result["script"] = script[:_SCRIPT_CAP]
    result["script_truncated"] = len(script) > _SCRIPT_CAP
    result["script_length"] = len(script)
    # Naming the modules it imports saves a round trip: the recipe worth reading
    # is almost always in one of them, not in these two or three lines.
    modules = sorted(
        {
            line.split()[1].split(".")[0]
            for line in script.splitlines()
            if line.strip().startswith("import ") and len(line.split()) > 1
        }
    )
    result["imports"] = modules
    return result


register_handler("shelf.get_shelf_tool_script", get_shelf_tool_script)


###### shelf.run_shelf_tool


# Calls that block the main thread until a person clicks in a viewport or a
# dialog. Run through the bridge they never return: a live session hung for ten
# minutes on the FLIP ocean-layer tool, and every later command queued behind
# it, until the user noticed and pressed Escape. Two layers catch them: the
# script text for the tools that call hou.ui themselves, and a guard on the
# viewer's selection methods for the many that go through
# soptoolutils.genericTool, whose script names only the node type while the
# prompt happens three modules down ("flipcontainer" takes an input, so the
# tool is a filter, so it asks for geometry).
_INTERACTIVE_MARKERS = (
    "selectGeometry(",
    "selectObjects(",
    "selectPositions(",
    "selectDynamics(",
    "selectSceneGraph(",
    "hou.ui.select",
    "hou.ui.readInput(",
    "hou.ui.readMultiInput(",
    "hou.ui.displayMessage(",
    "hou.ui.displayConfirmation(",
    "hou.ui.displayCustomConfirmation(",
    "hou.ui.selectFile(",
    "sceneViewer().select",
)

_VIEWER_PROMPTS = (
    "selectGeometry",
    "selectObjects",
    "selectPositions",
    "selectDynamics",
    "selectSceneGraph",
    "selectOrientedPositions",
)
_UI_PROMPTS = (
    "readInput",
    "readMultiInput",
    "displayMessage",
    "displayConfirmation",
    "displayCustomConfirmation",
    "selectFile",
    "selectNode",
    "selectParm",
    "selectParmTag",
    "selectFromList",
    "selectFromTree",
)


class InteractivePrompt(RuntimeError):
    """A shelf tool asked for a click."""


class UnusableSelection(InteractivePrompt):
    """The caller's ``selection`` had nothing the tool's prompt accepts.

    Not retried as a Ctrl+click: that builds the default setup, which ignores
    what the caller asked for.
    """


def interactive_markers(script: str) -> list[str]:
    """Which blocking-UI calls a shelf tool script makes, if any."""
    return [m for m in _INTERACTIVE_MARKERS if m in script]


def _object_selection(given: list | None):
    """A stand-in for SceneViewer.selectObjects that answers without a click.

    With use_existing_selection (the default) Houdini hands a tool the objects
    already selected, which is how dynamics_makeflip (FLIP from an object) is
    used: refusing every selectObjects turned it down with /obj/ball selected.
    *given* (the caller's ``selection``) answers in place of the scene's
    selection, which is left as the artist has it. Anything else still
    refuses. The positional order is HOM's: (self, prompt, sel_index,
    allow_drag, quick_select, use_existing_selection, allow_multisel,
    allowed_types, ...). Every prompt gets the same answer: a tool asking
    for several roles in turn (createSculptedFluid: fluid, terrain, obstacles)
    gets *given* for each.
    """

    def select_objects(*args: Any, **kwargs: Any) -> tuple:
        use_existing = kwargs.get("use_existing_selection", args[5] if len(args) > 5 else True)
        multiple = kwargs.get("allow_multisel", args[6] if len(args) > 6 else True)
        allowed = kwargs.get("allowed_types", args[7] if len(args) > 7 else ("*",)) or ("*",)
        candidates = given if given is not None else (hou.selectedNodes() if use_existing else [])
        chosen = [
            node
            for node in candidates
            if isinstance(node, hou.ObjNode)
            and any(fnmatch.fnmatch(node.type().name(), pattern) for pattern in allowed)
        ]
        if not chosen and given:
            raise UnusableSelection(
                f"selection {[n.path() for n in given]} has no object of the types "
                f"its prompt accepts ({', '.join(allowed)})"
            )
        if not chosen:
            raise InteractivePrompt("selectObjects")
        return tuple(chosen if multiple else chosen[:1])

    return select_objects


@contextlib.contextmanager
def _selection_kept() -> Iterator[None]:
    """Put the node selection and each editor's current node back after the block.

    A shelf script selects what it builds, as a click from the artist should,
    and makes it current (toolutils.genericTool: setCurrent), which moves the
    parameter pane. Run by an agent it would take the artist's selection, and
    with it the parameter pane and the next hotkey. Tools leave both as they
    found them (#128).
    """
    selected: list[str] = []
    current: list[tuple[Any, str]] = []
    with contextlib.suppress(Exception):
        selected = [node.path() for node in hou.selectedNodes()]
    with contextlib.suppress(Exception):
        current = [
            (tab, tab.currentNode().path())
            for tab in hou.ui.paneTabs()
            if tab.type() == hou.paneTabType.NetworkEditor and tab.currentNode() is not None
        ]
    try:
        yield
    finally:
        for tab, path in current:
            with contextlib.suppress(Exception):
                node = hou.node(path)
                if node is not None and tab.currentNode() != node:
                    tab.setCurrentNode(node, pick_node=False)
        with contextlib.suppress(Exception):
            if [node.path() for node in hou.selectedNodes()] != selected:
                hou.clearAllSelected()
                for path in selected:
                    node = hou.node(path)
                    if node is not None:
                        node.setSelected(True, clear_all_selected=False)


@contextlib.contextmanager
def _editor_in(network: hou.Node) -> Iterator[hou.Node | None]:
    """A network editor showing *network* for the block, back where it was after.

    A SOP tool places its nodes in the network its pane shows. With no pane,
    toolutils falls back to the Scene Viewer, which asks for a selection, and
    the Ctrl+click retry then built model_popnet's network as a new object
    instead of inside the SOP network given as parent_path. None when there
    is no editor to lend.
    """
    editor = None
    with contextlib.suppress(Exception):
        editor = next(
            tab for tab in hou.ui.paneTabs() if tab.type() == hou.paneTabType.NetworkEditor
        )
    if editor is None:
        yield None
        return
    previous = editor.pwd().path()
    with keep_viewer_state():
        editor.cd(network.path())
    try:
        yield editor
    finally:
        with contextlib.suppress(Exception), keep_viewer_state():
            editor.cd(previous)


@contextlib.contextmanager
def _no_prompts(tool_name: str, selection: list | None = None):
    """Make every viewport selection and dialog raise instead of waiting.

    An object selection is the exception: it is answered with *selection*, or
    with the objects already selected, as Houdini does (_object_selection).
    """

    def refuse(name):
        def _raise(*_a, **_k):
            raise InteractivePrompt(name)

        return _raise

    patched: list[tuple[Any, str, Any]] = []
    targets: list[tuple[Any, tuple[str, ...]]] = []
    if hasattr(hou, "SceneViewer"):
        targets.append((hou.SceneViewer, _VIEWER_PROMPTS))
    if hasattr(hou, "ui"):
        targets.append((hou.ui, _UI_PROMPTS))
    for owner, names in targets:
        for name in names:
            if hasattr(owner, name):
                patched.append((owner, name, getattr(owner, name)))
                stand_in = _object_selection(selection) if name == "selectObjects" else refuse(name)
                with contextlib.suppress(Exception):
                    setattr(owner, name, stand_in)
    try:
        yield
    finally:
        for owner, name, original in patched:
            with contextlib.suppress(Exception):
                setattr(owner, name, original)


def _refusal(tool_name: str, why: str) -> ValueError:
    return ValueError(
        f"Shelf tool '{tool_name}' waits for a viewport selection or a dialog "
        f"({why}). Run through the bridge that never returns and freezes every "
        f"later command. Read it with get_shelf_tool_script and build the same "
        f"nodes with build_network, pointing them at the geometry the tool would "
        f"have asked for."
    )


def _tree(networks: list) -> dict[int, hou.Node]:
    """Every node under *networks*, by session id, not entering locked assets.

    By id, not path: a node the tool renamed or moved is not new, and on a
    refusal must not be destroyed with what the tool built.
    """
    nodes: dict[int, hou.Node] = {}
    for network in networks:
        with contextlib.suppress(Exception):
            for node in network.allSubChildren(recurse_in_locked_nodes=False):
                nodes[node.sessionId()] = node
    return nodes


def _new_by_path(tree: dict[int, hou.Node], before: dict[int, hou.Node]) -> dict[str, hou.Node]:
    """The nodes of *tree* that were not in *before*, by their path now."""
    return {node.path(): node for sid, node in tree.items() if sid not in before}


def _is_sop_tool(tool: Any) -> bool:
    """Whether *tool* is in a SOP tab menu, so it builds in its pane's network.

    An object or DOP tool handed a network editor fails: dynamics_makeflip
    calls sceneviewer.selectObjects on whatever toolutils.activePane returns.
    """
    with contextlib.suppress(Exception):
        sop = hou.sopNodeTypeCategory()
        return any(
            sop in tool.toolMenuCategories(pane)
            for pane in (hou.paneTabType.NetworkEditor, hou.paneTabType.SceneViewer)
        )
    return False


def _current_dop_network() -> str | None:
    """The DOP network DOP shelf tools put their nodes in, or None."""
    with contextlib.suppress(Exception):
        network = hou.currentDopNet()
        return network.path() if network is not None else None
    return None


def run_shelf_tool(
    tool_name: str,
    kwargs: dict | None = None,
    parent_path: str | None = None,
    selection: list | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Run a shelf tool, reporting what it created.

    Most shelf tools reach for ``hou.ui``, because Houdini invokes them from a
    click. That makes them work in a graphical session -- which is where this
    plugin runs -- and fail in hython with a clear message rather than a
    mysterious AttributeError.

    Args:
        tool_name: Internal tool name, as returned by list_shelf_tools.
        kwargs: Overrides merged into the synthetic kwargs dict the script
            reads. Pass e.g. {"nodetypename": "..."} when a tool expects it.
        parent_path: An extra network to watch. /obj, /stage, /out, /mat and
            /img are always watched. A SOP network is also where a SOP tool
            places its nodes: a network editor shows it for the run.
        selection: Object paths the tool takes as its object selection, in
            place of the scene's (which is left alone). Without it a tool that
            asks for objects takes the ones already selected, as in Houdini.
    """
    tools = hou.shelves.tools()
    tool = tools.get(tool_name)
    if tool is None:
        raise ValueError(f"No shelf tool named '{tool_name}'. Try list_shelf_tools(filter=...).")

    script = tool.script() or ""
    if not script.strip():
        raise ValueError(f"Shelf tool '{tool_name}' has an empty script.")
    blocking = interactive_markers(script)
    if blocking:
        raise _refusal(tool_name, ", ".join(blocking[:3]))

    # Watch every top-level network, not just one. largeOcean creates a geo and a
    # procedural in /obj AND a LOP in /stage, and watching only the given parent
    # reported 2 of the 3 -- which left nodes behind that the caller did not know
    # existed. A shelf tool is free to build anywhere.
    watched = [node for node in (hou.node(path) for path in _WATCHED_NETWORKS) if node is not None]
    place_in = None
    if parent_path:
        explicit = hou.node(parent_path)
        if explicit is None:
            raise ValueError(f"parent_path not found: {parent_path}")
        if explicit not in watched:
            watched.append(explicit)
        with contextlib.suppress(Exception):
            if explicit.childTypeCategory() == hou.sopNodeTypeCategory() and _is_sop_tool(tool):
                place_in = explicit
    if "pane" in (kwargs or {}):
        place_in = None  # the caller chose the pane
    chosen = None
    if selection is not None:
        chosen = [hou.node(str(path)) for path in selection]
        missing = [str(path) for path, node in zip(selection, chosen, strict=True) if node is None]
        if missing:
            raise ValueError(f"selection: no such node(s): {missing}")

    call_kwargs = dict(_DEFAULT_KWARGS)
    call_kwargs["toolname"] = tool.name()
    if kwargs:
        call_kwargs.update(kwargs)

    # The whole tree, not only each network's children: dynamics_flipbox run
    # after model_popnet put flipsolver1, fliptank and merge1 into the existing
    # POP network, and a reply listing new top-level nodes never named them.
    before = _tree(watched)
    dop_before = _current_dop_network()
    # A tool that asks for a click is retried once as a Ctrl+click, Houdini's
    # "place immediately": the Crowds Simulate tool then builds its whole
    # default setup (agents, source, DOP states) instead of asking for an
    # object. Only when the caller chose no modifier themselves.
    modifiers = ("ctrlclick", "cmdclick", "shiftclick", "altclick")
    retry_as_ctrl_click = not any((kwargs or {}).get(key) for key in modifiers)
    ran_as_ctrl_click = False
    refused: InteractivePrompt | None = None
    placed_in = None
    try:
        with contextlib.ExitStack() as stack:
            stack.enter_context(_selection_kept())
            editor = stack.enter_context(_editor_in(place_in)) if place_in is not None else None
            if editor is not None:
                call_kwargs["pane"] = editor
                # With a pane and no autoplace, genericTool waits for a click
                # in the editor (nodegraphselectpos).
                call_kwargs["autoplace"] = True
                placed_in = place_in.path()
            while True:
                namespace: dict[str, Any] = {"kwargs": call_kwargs, "hou": hou}
                try:
                    with _no_prompts(tool_name, chosen):
                        exec(script, namespace)  # noqa: S102 - running SideFX's own tool script
                    break
                except InteractivePrompt as exc:
                    # Whatever the tool created before asking is half a setup;
                    # remove it, inside existing networks too.
                    made = _new_by_path(_tree(watched), before)
                    for path in sorted(made):
                        if path.rsplit("/", 1)[0] in made:
                            continue  # goes with its parent
                        with contextlib.suppress(Exception):
                            made[path].destroy()
                    if (
                        isinstance(exc, UnusableSelection)
                        or not retry_as_ctrl_click
                        or ran_as_ctrl_click
                    ):
                        refused = exc
                        break
                    call_kwargs = {**call_kwargs, "ctrlclick": True}
                    ran_as_ctrl_click = True
    except AttributeError as exc:
        if "'hou' has no attribute 'ui'" in str(exc):
            raise hou.OperationFailed(
                f"Shelf tool '{tool_name}' needs a graphical Houdini: it calls "
                f"hou.ui, which does not exist in a headless session. Read its "
                f"recipe with get_shelf_tool_script and build the network "
                f"directly instead."
            ) from exc
        raise
    except Exception as exc:
        raise hou.OperationFailed(
            f"Shelf tool '{tool_name}' failed: {type(exc).__name__}: {str(exc)[:200]}"
        ) from exc

    if isinstance(refused, UnusableSelection):
        raise ValueError(f"Shelf tool '{tool_name}': {refused}.") from refused
    if refused is not None:
        raise _refusal(tool_name, f"{refused}()") from refused

    tree = _tree(watched)
    after = _new_by_path(tree, before)
    existing = {node.path() for sid, node in tree.items() if sid in before}
    new = sorted(after)
    tops = {node.path() for node in watched}
    created = [path for path in new if path.rsplit("/", 1)[0] in tops]
    inside = [path for path in new if path not in created and path.rsplit("/", 1)[0] in existing]
    reply: dict[str, Any] = {
        "tool_name": tool.name(),
        "label": call_kwargs.get("toolname"),
        "watched": [node.path() for node in watched],
        "created": [
            {"path": path, "type": after[path].type().name()} for path in created[:_LIST_CAP]
        ],
        "created_count": len(created),
        "truncated": len(created) > _LIST_CAP,
        "kwargs_used": sorted(call_kwargs),
        **(
            {
                "ran_as_ctrl_click": True,
                "note": "The tool asked for a selection, so it ran as a Ctrl+click "
                "(place immediately) and built its default setup.",
            }
            if ran_as_ctrl_click
            else {}
        ),
    }
    if inside:
        reply["created_in_existing"] = [
            {"path": path, "type": after[path].type().name()} for path in inside[:_LIST_CAP]
        ]
        reply["created_in_existing_count"] = len(inside)
        reply["existing_networks_changed"] = sorted({p.rsplit("/", 1)[0] for p in inside})
    dop_after = _current_dop_network()
    if dop_before or dop_after:
        # DOP tools build into the current DOP network, which an earlier tool
        # may have set; seeing it before the next run saves a surprise.
        reply["current_dop_network"] = {"before": dop_before, "after": dop_after}
    if placed_in is not None:
        reply["placed_in"] = placed_in
    return reply


register_handler("shelf.run_shelf_tool", run_shelf_tool)
