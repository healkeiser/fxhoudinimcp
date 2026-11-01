"""A viewport capture is the viewport's size, not the flipbook stash's 1280x720.

flipbookSettings().stash() carries the flipbook's own default, Use Resolution
on at 1280x720, whatever the viewport's shape. capture_screenshot,
render_viewport and render_quad_view wrote that: an 897x853 viewport came out
cropped top and bottom (a top view framed to a 2020x2360 box showed 1550 of
its 2360, so frame_all looked wrong), and through an 800x400 camera the whole
view was squeezed into 16:9. Without a resolution asked for, Use Resolution
is now off and the frame is the viewport's own size; an asked resolution is
written as before.

hou is mocked here; the live check ran on Houdini 22.0.466.
"""

from __future__ import annotations

# Built-in
import os
import re
import sys
from unittest.mock import MagicMock, patch

sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Internal
import fxhoudinimcp_server.handlers.rendering_handlers as rendering  # noqa: E402
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


class TestSizeFlipbook:
    def test_no_resolution_turns_the_stashed_one_off(self):
        settings = MagicMock()
        rendering._size_flipbook(settings, None)
        settings.useResolution.assert_called_once_with(False)
        settings.resolution.assert_not_called()

    def test_an_asked_resolution_is_written(self):
        settings = MagicMock()
        rendering._size_flipbook(settings, [640, 360])
        settings.useResolution.assert_called_once_with(True)
        settings.resolution.assert_called_once_with((640, 360))

    def test_every_flipbook_site_sizes_its_frame(self):
        for name in ("viewport_handlers.py", "rendering_handlers.py"):
            with open(os.path.join(_HANDLER_DIR, name), encoding="utf-8") as fh:
                source = fh.read()
            stashes = source.count("flipbookSettings().stash()")
            assert stashes > 0
            calls = len(re.findall(r"^\s+_size_flipbook\(settings, ", source, flags=re.M))
            assert calls == stashes, name


def _scene_viewer():
    viewer = MagicMock()
    viewer.type.return_value = rendering.hou.paneTabType.SceneViewer
    return viewer


def test_capture_screenshot_is_the_viewports_size(tmp_path):
    viewer = _scene_viewer()
    settings = viewer.flipbookSettings.return_value.stash.return_value
    with (
        patch.object(viewport, "_find_scene_viewer", return_value=viewer),
        patch.object(viewport, "viewer_context", return_value={}),
    ):
        viewport.capture_screenshot(str(tmp_path / "shot.png"))
    settings.useResolution.assert_called_once_with(False)
    settings.resolution.assert_not_called()


def test_render_viewport_without_a_resolution_is_the_viewports_size(tmp_path):
    viewer = _scene_viewer()
    settings = viewer.flipbookSettings.return_value.stash.return_value
    with (
        patch.object(rendering, "require_ui"),
        patch.object(rendering, "viewer_context", return_value={}),
        patch.object(rendering.hou.ui, "paneTabs", return_value=[viewer]),
    ):
        rendering.render_viewport(str(tmp_path / "vp.png"))
    settings.useResolution.assert_called_once_with(False)
