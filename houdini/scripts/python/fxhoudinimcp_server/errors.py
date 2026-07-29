"""Turning a Houdini exception into a sentence a caller can act on.

``str()`` on any ``hou.Error`` prepends Houdini's own generic sentence:

    The attempted operation failed.
    Invalid node type name

The first line is the one a caller reads first, and it names nothing. Every error
this server raised through ``hou.OperationFailed`` led with it, and thirty handlers
made it worse by interpolating ``{e}`` into their own message, so the useless
sentence ended up buried in the middle:

    Failed to create render node of type 'notarenderer': The attempted operation
    failed. Invalid node type name

``instanceMessage()`` returns just the part that varies -- for errors this server
raises and for Houdini's internal ones alike -- which is the only part worth
showing.
"""

from __future__ import annotations


def readable_message(exc: BaseException) -> str:
    """What went wrong, without Houdini's generic preamble.

    Falls back to ``str()`` for non-Houdini exceptions, and to the general
    description for a bare ``hou.OperationFailed()`` carrying no message of its
    own. Never raises: a failure to format an error must not replace the error.
    """
    try:
        import hou

        if isinstance(exc, hou.Error):
            specific = (exc.instanceMessage() or "").strip()
            if specific:
                return specific
            general = (exc.description() or "").strip()
            if general:
                return general
    except Exception:  # noqa: BLE001 - formatting must never mask the real error
        pass
    return str(exc)


def as_text(value: object, name: str) -> str:
    """A string argument, or a message that names the argument and its type.

    Handlers that took an optional ``filter`` called ``.lower()`` on it directly, so
    a non-string leaked ``'int' object has no attribute 'lower'`` -- a Python
    internal that names neither the argument nor this server. The MCP tool schema
    type-checks these in normal use, so this is the second line of defence for
    anything reaching the HTTP bridge directly.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    raise ValueError(f"{name} must be a string, not {type(value).__name__}: {value!r}")


def as_int(value: object, name: str) -> int:
    """An integer argument, or a message that names the argument and its type."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{name} must be a number, not {type(value).__name__}: {value!r}")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"{name} must be a whole number, not {type(value).__name__}: {value!r}"
        ) from None
