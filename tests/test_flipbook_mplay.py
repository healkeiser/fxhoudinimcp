"""A flipbook capture must not launch MPlay.

MPlay is a child process of Houdini and inherits its file descriptors, the
hwebserver listening socket included. After Houdini exited, port 8101 stayed
open in mplay-bin (same fd number as houdini-bin had) and the next session's
auto-start reported "an existing server is running on port 8101"; the plugin
loaded, but nothing answered. Every flipbook site switches MPlay off.
"""

from __future__ import annotations

# Built-in
import os
import re
import sys
from unittest.mock import MagicMock

sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Internal
import fxhoudinimcp_server.handlers.viewport_handlers as viewport  # noqa: E402

_HANDLER_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "houdini",
    "scripts",
    "python",
    "fxhoudinimcp_server",
    "handlers",
)


class TestFlipbooksDoNotOpenMPlay:
    def test_flipbook_settings_are_told_not_to(self):
        settings = MagicMock()
        viewport._no_mplay(settings)
        settings.outputToMPlay.assert_called_once_with(False)

    def test_a_build_without_the_setter_is_tolerated(self):
        settings = MagicMock()
        settings.outputToMPlay.side_effect = AttributeError("no such method")
        viewport._no_mplay(settings)  # must not raise

    def test_every_flipbook_site_switches_mplay_off(self):
        for name in ("viewport_handlers.py", "rendering_handlers.py"):
            with open(os.path.join(_HANDLER_DIR, name), encoding="utf-8") as fh:
                source = fh.read()
            stashes = source.count("flipbookSettings().stash()")
            assert stashes > 0
            calls = len(re.findall(r"^\s+_no_mplay\(settings\)$", source, flags=re.M))
            assert calls == stashes, name
