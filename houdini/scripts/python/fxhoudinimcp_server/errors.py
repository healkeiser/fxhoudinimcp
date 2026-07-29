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
