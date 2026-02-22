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
    "node_handlers",
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
