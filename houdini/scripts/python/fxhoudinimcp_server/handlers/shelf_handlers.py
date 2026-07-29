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
from typing import Any

# Third-party
import hou

# Internal
from fxhoudinimcp_server.dispatcher import register_handler

###### Helpers

_LIST_CAP = 60
_SCRIPT_CAP = 20_000

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
    needle = (filter or "").strip().lower()

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


def run_shelf_tool(
    tool_name: str,
    kwargs: dict | None = None,
    parent_path: str | None = None,
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
        parent_path: Network to watch for new nodes. Defaults to /obj.
    """
    tools = hou.shelves.tools()
    tool = tools.get(tool_name)
    if tool is None:
        raise ValueError(f"No shelf tool named '{tool_name}'. Try list_shelf_tools(filter=...).")

    script = tool.script() or ""
    if not script.strip():
        raise ValueError(f"Shelf tool '{tool_name}' has an empty script.")

    watch = hou.node(parent_path or "/obj")
    if watch is None:
        raise ValueError(f"parent_path not found: {parent_path}")

    call_kwargs = dict(_DEFAULT_KWARGS)
    call_kwargs["toolname"] = tool.name()
    if kwargs:
        call_kwargs.update(kwargs)

    before = {child.path() for child in watch.children()}
    namespace: dict[str, Any] = {"kwargs": call_kwargs, "hou": hou}
    try:
        exec(script, namespace)  # noqa: S102 - running SideFX's own tool script
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

    after = {child.path(): child for child in watch.children()}
    created = sorted(set(after) - before)
    return {
        "tool_name": tool.name(),
        "label": call_kwargs.get("toolname"),
        "watched": watch.path(),
        "created": [
            {"path": path, "type": after[path].type().name()} for path in created[:_LIST_CAP]
        ],
        "created_count": len(created),
        "kwargs_used": sorted(call_kwargs),
    }


register_handler("shelf.run_shelf_tool", run_shelf_tool)
