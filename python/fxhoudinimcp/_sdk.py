"""One import site for the MCP SDK, so a renamed module is a one-line fix.

mcp 2.0.0 removed ``mcp.server.fastmcp``. The server class moved to
``mcp.server.mcpserver`` and was renamed ``FastMCP`` -> ``MCPServer``. Every
tool, resource and prompt in this package imported ``Context`` from the old
path, so a fresh ``pip install`` resolving mcp 2.x produced a server that could
not import at all, with 26 import sites to chase.

The public API this package uses is unchanged between the two: ``MCPServer(name,
instructions)``, the ``tool()``/``prompt()``/``resource(uri)`` decorators, and
``Context``. So supporting both is an import shim rather than a port, and the
dependency does not need pinning to a major version.
"""

from __future__ import annotations

# Built-in
from difflib import get_close_matches

# Third-party
from pydantic import ConfigDict, model_validator

try:
    # mcp >= 2.0
    from mcp.server.mcpserver import Context as Context
    from mcp.server.mcpserver import MCPServer as Server
except ImportError:  # pragma: no cover - depends on the installed mcp
    # mcp 1.x
    from mcp.server.fastmcp import Context as Context
    from mcp.server.fastmcp import FastMCP as Server


def build_server(*, name: str, instructions: str, lifespan, version: str):
    """Construct the SDK server and give it a version, on either major.

    The version is why this is a function rather than a bare class re-export.
    mcp 1.x has no public way to set it, so the only option was poking
    ``server._mcp_server.version``. mcp 2.0 accepts ``version`` on the
    constructor and has no ``_mcp_server`` at all, so the poke raised
    AttributeError at import time -- which is a broken server, not a missing
    version string.
    """
    try:
        return Server(
            name=name,
            instructions=instructions,
            lifespan=lifespan,
            version=version,
        )
    except TypeError:
        # mcp 1.x: no version kwarg, so set it on the wrapped low-level server.
        server = Server(name=name, instructions=instructions, lifespan=lifespan)
        inner = getattr(server, "_mcp_server", None)
        if inner is not None:
            inner.version = version
        return server


def unknown_argument_message(tool: str, unknown: list[str], accepted: set[str]) -> str:
    """The refusal for *unknown* arguments: what each might have meant, and what exists.

    A name that contains an accepted one comes first (``node_name`` ->
    ``name``), then the near spellings (``node_typ`` -> ``node_type``).
    """
    ordered = sorted(accepted)
    parts = []
    for arg in unknown:
        suggestions = [a for a in ordered if arg.startswith(a) or arg.endswith(a)]
        suggestions += [
            close
            for close in get_close_matches(arg, ordered, n=3, cutoff=0.5)
            if close not in suggestions
        ]
        hint = ""
        if suggestions:
            hint = " (did you mean " + " or ".join(f"'{s}'" for s in suggestions[:3]) + "?)"
        parts.append(f"'{arg}'{hint}")
    return f"{tool} does not take {', '.join(parts)}. Accepted arguments: {ordered}."


def forbid_unknown_arguments(server, name: str) -> None:
    """Make tool ``name`` refuse arguments it does not declare.

    The SDK's argument model ignores extra keys, so a misspelled filter
    (``node_typ="geo"``) was dropped and the call answered as if unfiltered,
    which reads as a filter that matched everything. With ``extra="forbid"``
    the call fails, and the advertised schema says
    ``additionalProperties: false``. ``_tool_manager`` and ``fn_metadata`` are
    private but identical on 1.x and 2.x, which is why this lives here.

    pydantic's own refusal ("Extra inputs are not permitted") names the key
    but not the argument meant: ``create_node(node_name=...)`` left the caller
    to find ``name`` in the schema. A before-validator on a subclass of the
    tool's model refuses first, with the closest accepted names and the full
    list (unknown_argument_message).
    """
    tool = server._tool_manager.get_tool(name)
    base = tool.fn_metadata.arg_model
    accepted = set(base.model_fields)
    accepted |= {field.alias for field in base.model_fields.values() if field.alias}

    def refuse_unknown(cls, data):
        if isinstance(data, dict):
            unknown = sorted(key for key in data if key not in accepted)
            if unknown:
                raise ValueError(unknown_argument_message(name, unknown, accepted))
        return data

    model = type(
        base.__name__,
        (base,),
        {
            "__module__": base.__module__,
            "model_config": ConfigDict(extra="forbid"),
            "refuse_unknown": model_validator(mode="before")(classmethod(refuse_unknown)),
        },
    )
    tool.fn_metadata.arg_model = model
    tool.parameters = model.model_json_schema(by_alias=True)


__all__ = [
    "Context",
    "Server",
    "build_server",
    "forbid_unknown_arguments",
    "unknown_argument_message",
]
