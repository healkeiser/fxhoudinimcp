"""Handler modules for FXHoudini-MCP.

Importing this package registers all command handlers with the dispatcher.
Each submodule calls register_handler() at import time.
"""

from __future__ import annotations

# Built-in
import importlib
import logging
import traceback

logger = logging.getLogger(__name__)

###### Handler module loading

_HANDLER_MODULES = [
    "scene_handlers",
    "shelf_handlers",
    "node_handlers",
    "graph_handlers",
    "help_handlers",
    "parameter_handlers",
    "code_handlers",
    "dop_handlers",
    "animation_handlers",
    "rendering_handlers",
    "viewport_handlers",
    "geometry_handlers",
    "lops_handlers",
    "top_handlers",
    "cop_handlers",
    "hda_handlers",
    "vex_handlers",
    "context_handlers",
    "workflow_handlers",
    "material_handlers",
    "chop_handlers",
    "cache_handlers",
    "take_handlers",
]

_loaded = []
_failed = []

for _module_name in _HANDLER_MODULES:
    try:
        importlib.import_module(f".{_module_name}", __package__)
        _loaded.append(_module_name)
    except Exception:
        _failed.append(_module_name)
        logger.warning(
            "Failed to load handler module '%s':\n%s",
            _module_name,
            traceback.format_exc(),
        )

# Internal
from fxhoudinimcp_server.dispatcher import list_commands  # noqa: E402

_total = len(_HANDLER_MODULES)
_command_count = len(list_commands())

print(
    f"[fxhoudinimcp] Loaded {len(_loaded)}/{_total} handler modules "
    f"({_command_count} commands registered)"
)

if _failed:
    print(f"[fxhoudinimcp] Failed modules: {', '.join(_failed)}")


###### code.reload_plugin

# Shared helpers first, then the handler modules others import names from,
# then the rest: a module that did `from x import f` keeps the old f unless
# x was reloaded before it. The dispatcher is never reloaded, since it holds
# the registry the reloaded modules register into.
_HELPER_MODULES = ["errors", "serialize", "config", "ui", "outputs"]
# dop_handlers first: node, parameter and graph handlers import dop_cache_note.
_IMPORTED_FROM = ["dop_handlers", "node_handlers", "parameter_handlers", "viewport_handlers"]


def reload_plugin(**_):
    """Re-import the plugin's Houdini-side code without restarting Houdini."""
    import sys

    reloaded, failed = [], {}
    order = [f"fxhoudinimcp_server.{name}" for name in _HELPER_MODULES]
    order += [f"{__package__}.{name}" for name in _IMPORTED_FROM]
    order += [f"{__package__}.{n}" for n in _HANDLER_MODULES if n not in _IMPORTED_FROM]
    for name in order:
        module = sys.modules.get(name)
        if module is None:
            continue
        try:
            importlib.reload(module)
            reloaded.append(name.rsplit(".", 1)[-1])
        except Exception as exc:
            failed[name.rsplit(".", 1)[-1]] = f"{type(exc).__name__}: {exc}"
    return {
        "success": not failed,
        "reloaded": reloaded,
        "failed": failed,
        "commands_registered": len(list_commands()),
        "note": (
            "Houdini-side code only. The MCP server's own tool definitions load "
            "when its process starts: reconnect the client (/mcp) for those."
        ),
    }


from fxhoudinimcp_server.dispatcher import register_handler  # noqa: E402

register_handler("code.reload_plugin", reload_plugin)
