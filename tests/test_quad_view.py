"""render_quad_view must write all four images, not just the visible one.

A flipbook of a viewport the layout hides writes nothing. In the default
Single layout the handler reported four saved files and three never existed.
It now shows the Quad layout for the capture, restores the user's layout and
reports file_exists per image.
"""

from __future__ import annotations

# Built-in
import os
import sys
from unittest.mock import MagicMock, patch

# Third-party
import pytest

sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Internal
import fxhoudinimcp_server.handlers.rendering_handlers as rendering  # noqa: E402


@pytest.fixture(autouse=True)
def _paths_as_written(monkeypatch):
    # The shared hou mock would expand a path into a MagicMock, which
    # os.makedirs then creates as a directory named after the mock.
    for name in ("rendering_handlers", "viewport_handlers"):
        module = sys.modules.get("fxhoudinimcp_server.handlers." + name)
        if module is not None:
            monkeypatch.setattr(module.hou.text, "expandString", lambda s: s)


def _viewer(names, layout):
    viewer = MagicMock()
    viewer.type.return_value = rendering.hou.paneTabType.SceneViewer
    viewer.viewportLayout.return_value = layout
    viewports = []
    for name in names:
        vp = MagicMock()
        vp.name.return_value = name
        viewports.append(vp)
    viewer.viewports.return_value = viewports
    return viewer


def test_quad_layout_during_capture_then_restored(tmp_path):
    single = object()
    viewer = _viewer(["top1", "persp1"], single)
    written = []

    def flipbook(vp, settings):
        # Only a viewport shown by the current layout writes its file.
        if viewer.setViewportLayout.call_args[0][0] is rendering.hou.geometryViewportLayout.Quad:
            path = settings.output.call_args[0][0]
            open(path, "w").close()
            written.append(path)

    viewer.flipbook.side_effect = flipbook
    with (
        patch.object(rendering, "require_ui"),
        patch.object(rendering.hou.ui, "paneTabs", return_value=[viewer]),
    ):
        result = rendering.render_quad_view(str(tmp_path / "quad.png"), resolution=[64, 48])

    assert result["success"] is True
    assert [v["file_exists"] for v in result["viewports"]] == [True, True]
    assert len(written) == 2
    assert viewer.setViewportLayout.call_args_list[-1][0][0] is single


def test_a_missing_image_is_not_reported_as_success(tmp_path):
    viewer = _viewer(["top1"], object())
    with (
        patch.object(rendering, "require_ui"),
        patch.object(rendering.hou.ui, "paneTabs", return_value=[viewer]),
    ):
        result = rendering.render_quad_view(str(tmp_path / "quad.png"))
    assert result["success"] is False
    assert result["viewports"][0]["file_exists"] is False
