"""Saying "this needs a graphical Houdini" instead of crashing about it.

``hou.ui`` does not exist in hython or hbatch. Ten handlers reached for it without
checking, so asking for a viewport screenshot in a headless session answered:

    module 'hou' has no attribute 'ui'

which reads as a broken plugin and sends the caller debugging the server. The real
answer is that the operation needs a graphical session -- a different thing to know,
because it tells them to stop retrying and either open Houdini or pick a tool that
works without one.

Kept separate from the pane-finding helpers because it is the *first* question, not
a detail of the search: with no UI at all there are no panes to look through.
"""

from __future__ import annotations

# Third-party
import hou


def ui_available() -> bool:
    """Whether this Houdini has a UI at all.

    ``hou.isUIAvailable`` is itself missing in some headless builds, so the
    attribute check comes first.
    """
    try:
        return bool(hou.isUIAvailable())
    except AttributeError:
        return hasattr(hou, "ui")


def require_ui(operation: str, *, alternative: str = "") -> None:
    """Raise a readable error when *operation* needs a UI and there is none.

    Args:
        operation: What was being attempted, named as the caller would name it
            ("capture a viewport screenshot").
        alternative: Optional pointer to something that does work headlessly.
            Worth giving whenever one exists -- a refusal that names the way
            forward saves the round trip that a bare refusal costs.
    """
    if ui_available():
        return
    message = (
        f"Cannot {operation}: this Houdini session has no UI (hython/hbatch), "
        f"so there are no panes or viewports. It needs a graphical Houdini."
    )
    if alternative:
        message += f" {alternative}"
    raise hou.OperationFailed(message)


def panes():
    """``hou.ui.paneTabs()``, but explaining itself when there is no UI."""
    require_ui("look at Houdini's panes")
    return hou.ui.paneTabs()
