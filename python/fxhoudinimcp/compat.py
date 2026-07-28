"""Detect a Houdini plugin that is out of step with this MCP server.

The two halves ship separately: the server from PyPI, the plugin from the
repository. Upgrading one and not the other is easy to do and, until now,
invisible. A plugin older than the server is missing commands the server's tools
call, and the only symptom is one tool failing with "No handler registered for
command", which reads like a bug rather than a version mismatch.

The check compares capability rather than version numbers. ``list_commands``
already exists on the plugin, and ``data/required_commands.json`` is generated
from the client's own ``execute()`` call sites, so nothing has to remember to
bump a version constant when a command is added.
"""

from __future__ import annotations

# Built-in
import json
import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_MANIFEST = Path(__file__).parent / "data" / "required_commands.json"

# Enough names to identify the gap without turning a log line into a wall.
_MAX_NAMED = 6


@lru_cache(maxsize=1)
def required_commands() -> frozenset[str]:
    """Commands this server's tools call, or empty when unreadable.

    Never raises: an unreadable manifest degrades the check to "no opinion",
    which is the right outcome for a diagnostic.
    """
    try:
        payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.debug("No required-commands manifest shipped at %s", _MANIFEST)
        return frozenset()
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read the required-commands manifest: %s", exc)
        return frozenset()

    commands = payload.get("commands") if isinstance(payload, dict) else None
    return frozenset(commands) if isinstance(commands, list) else frozenset()


def missing_commands(available: list[str] | None) -> list[str]:
    """Commands this server needs that the connected plugin does not have."""
    required = required_commands()
    if not required or not available:
        # No manifest, or the plugin reported nothing: cannot conclude anything.
        # An empty list from a plugin that genuinely has no commands would be
        # indistinguishable from a failed call, and guessing is worse than
        # staying quiet.
        return []
    if not isinstance(available, (list, tuple, set, frozenset)) or not all(
        isinstance(name, str) for name in available
    ):
        # Anything else means we did not get a command list. Treating it as one
        # would report every command as missing, which is a loud, wrong warning
        # about a version gap that does not exist.
        logger.debug("Ignoring an unusable command list: %r", type(available))
        return []
    return sorted(required - set(available))


def compatibility_warning(available: list[str] | None) -> str | None:
    """Return a warning when the plugin is missing commands, else None."""
    missing = missing_commands(available)
    if not missing:
        return None

    shown = ", ".join(missing[:_MAX_NAMED])
    if len(missing) > _MAX_NAMED:
        shown += f", and {len(missing) - _MAX_NAMED} more"
    return (
        f"The Houdini plugin is missing {len(missing)} command(s) this server "
        f"expects ({shown}), so it is older than the MCP server and tools that "
        f"need those commands will fail. The packaged plugin travels with this "
        f"install, so the likely cause is a Houdini package file pointing "
        f"somewhere else, for example an older clone. Run "
        f"'python -m fxhoudinimcp houdini-package' to see the path this install "
        f"expects "
        f"and to be warned about competing package files."
    )
