"""Runtime configuration flags read from environment variables."""

from __future__ import annotations

# Built-in
import os

_FALSY = {"0", "false", "off", "no"}


def auto_layout_enabled() -> bool:
    """Whether tools may auto-arrange nodes in the network editor.

    Controlled by the ``FXHOUDINIMCP_AUTO_LAYOUT`` environment variable.
    Off by default so existing node layouts are never rearranged; set to
    ``1`` to opt in.
    """
    value = os.getenv("FXHOUDINIMCP_AUTO_LAYOUT", "0")
    return value.strip().lower() not in _FALSY
