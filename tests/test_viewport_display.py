"""set_viewport_display could not hide the environment background.

The only setting it had was the shading mode. Hiding a dome light's map from
behind the scene took GeometryViewportSettings
.setDisplayEnvironmentBackgroundImage() through execute_python, once per view,
because the flag lives on each view: a quad layout carries four of them. Now
environment_background sets it on every view of the viewer and the reply reads
each one back; display_mode is optional so either can be set alone.

hou is mocked here; the live check ran on Houdini 22.0.429.
"""

from __future__ import annotations

# Built-in
import os
import sys
from unittest.mock import MagicMock

# Third-party
import pytest

sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Internal
import fxhoudinimcp_server.handlers.viewport_handlers as viewport  # noqa: E402


class _FakeSettings:
    def __init__(self, shown):
        self.shown = shown
        self.display_set = MagicMock()

    def setDisplayEnvironmentBackgroundImage(self, on):
        self.shown = on

    def displayEnvironmentBackgroundImage(self):
        return self.shown

    def displaySet(self, _kind):
        return self.display_set


class _FakeView:
    def __init__(self, name, shown=True):
        self._name = name
        self._settings = _FakeSettings(shown)

    def name(self):
        return self._name

    def settings(self):
        return self._settings


def _viewer(monkeypatch, names=("right1", "front1", "top1", "persp1")):
    views = [_FakeView(name) for name in names]
    viewer = MagicMock()
    viewer.name.return_value = "panetab1"
    viewer.viewports.return_value = views
    viewer.curViewport.return_value = views[-1]
    monkeypatch.setattr(viewport, "_find_scene_viewer", lambda pane_name=None: viewer)
    return viewer, views


class TestEnvironmentBackground:
    def test_every_view_of_a_quad_layout_is_set(self, monkeypatch):
        _, views = _viewer(monkeypatch)
        result = viewport.set_viewport_display(environment_background=False)
        assert result["environment_background"] == {
            "right1": False,
            "front1": False,
            "top1": False,
            "persp1": False,
        }
        assert all(view.settings().shown is False for view in views)

    def test_the_reply_is_read_back_not_echoed(self, monkeypatch):
        _, views = _viewer(monkeypatch, names=("persp1",))
        # A setter that does not take must show up in the reply.
        views[0]._settings.setDisplayEnvironmentBackgroundImage = lambda on: None
        result = viewport.set_viewport_display(environment_background=False)
        assert result["environment_background"] == {"persp1": True}

    def test_alone_it_leaves_the_shading_mode_untouched(self, monkeypatch):
        _, views = _viewer(monkeypatch)
        result = viewport.set_viewport_display(environment_background=True)
        assert "display_mode" not in result
        for view in views:
            view.settings().display_set.setShadedMode.assert_not_called()

    def test_both_are_applied_in_one_call(self, monkeypatch):
        _, views = _viewer(monkeypatch)
        result = viewport.set_viewport_display(display_mode="smooth", environment_background=True)
        assert result["display_mode"] == "smooth"
        assert set(result["environment_background"].values()) == {True}
        views[-1].settings().display_set.setShadedMode.assert_called_once()


class TestDisplayModeAlone:
    def test_reply_keeps_its_keys(self, monkeypatch):
        _viewer(monkeypatch)
        result = viewport.set_viewport_display(display_mode="wireframe")
        assert result == {"success": True, "pane_name": "panetab1", "display_mode": "wireframe"}

    def test_unknown_mode_still_names_the_choices(self, monkeypatch):
        _viewer(monkeypatch)
        with pytest.raises(ValueError, match="Supported modes"):
            viewport.set_viewport_display(display_mode="glossy")

    def test_nothing_to_set_is_refused(self, monkeypatch):
        _viewer(monkeypatch)
        with pytest.raises(ValueError, match="display_mode, environment_background"):
            viewport.set_viewport_display()
