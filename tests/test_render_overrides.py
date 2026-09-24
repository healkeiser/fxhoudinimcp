"""start_render(overrides=...) and a Karma LOP that returns before husk is done.

- A draft of a finished setup meant set, render, put back by hand through
  execute_python; a failed render left the draft values in the scene.
  overrides are set for the one render and restored in a finally, the
  expressions and keyframes they replaced included.
- A fresh Karma LOP has "Wait for Render to Complete" (soho_foreground) off on
  22.0.429: execute returns while husk is still rendering, and the verdict on
  the files came before the files did. It is switched on for the call.
"""

from __future__ import annotations

# Built-in
import contextlib
import os
import sys
from unittest.mock import MagicMock

# Third-party
import pytest

sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Internal
import fxhoudinimcp_server.handlers.rendering_handlers as rendering  # noqa: E402


class _HouError(Exception):
    """Stands in for hou.Error (hou.PermissionError among them), which the stub lacks."""


class _OperationFailed(_HouError):
    """Stands in for hou.OperationFailed."""


class _Parm:
    """Enough of hou.Parm to set, read back and restore."""

    def __init__(self, value, keys=(), string=False, locked=False):
        self.value = value
        self.keys = list(keys)
        self.string = string
        self.locked = locked

    def keyframes(self):
        return tuple(self.keys)

    def deleteAllKeyframes(self):  # noqa: N802 -- HOM spelling
        if self.locked:
            raise _HouError("The parameter is locked.")
        self.keys = []

    def setKeyframe(self, key):  # noqa: N802 -- HOM spelling
        self.keys.append(key)

    def parmTemplate(self):  # noqa: N802 -- HOM spelling
        kind = rendering.hou.parmTemplateType.String if self.string else "Int"
        return MagicMock(**{"type.return_value": kind})

    def unexpandedString(self):  # noqa: N802 -- HOM spelling
        return self.value

    def eval(self):
        return self.value

    def set(self, value):
        if self.locked:
            raise _HouError("The parameter is locked.")
        self.value = value

    def node(self):
        return MagicMock(**{"path.return_value": "/stage/karma1"})


@pytest.fixture
def karma(monkeypatch):
    """A Karma LOP whose render() records the parm values it rendered with."""
    monkeypatch.setattr(rendering.hou, "Error", _HouError, raising=False)
    monkeypatch.setattr(rendering.hou, "OperationFailed", _OperationFailed, raising=False)
    parms = {
        "soho_foreground": _Parm(0),
        "resolutionx": _Parm(1280, keys=["640*2"]),
        "resolutiony": _Parm(720),
        "picture": _Parm("$HIP/render/$F4.exr", string=True),
    }
    node = MagicMock()
    node.path.return_value = "/stage/karma1"
    node.parm.side_effect = parms.get
    node.parmTuple.return_value = None
    seen = {}

    def render(**_):
        seen.update({name: parm.value for name, parm in parms.items()})
        seen["resolutionx_keys"] = list(parms["resolutionx"].keys)

    node.render.side_effect = render
    monkeypatch.setattr(rendering, "_renderable", lambda p: (node, "Lop", True))
    monkeypatch.setattr(rendering, "at_frame", lambda frame: contextlib.nullcontext())
    monkeypatch.setattr(rendering, "reported_outputs", lambda n: [])
    monkeypatch.setattr(
        rendering, "write_verdict", lambda *a, **k: {"success": True, "wrote_files": True}
    )
    return node, parms, seen


class TestRenderOverrides:
    def test_values_hold_during_the_render_and_come_back(self, karma):
        _, parms, seen = karma
        reply = rendering.start_render(
            "/stage/karma1",
            overrides={"resolutionx": 160, "resolutiony": 90, "picture": "/tmp/draft.exr"},
        )
        assert seen["resolutionx"] == 160 and seen["resolutiony"] == 90
        assert seen["resolutionx_keys"] == []  # the literal took, not the expression
        assert seen["picture"] == "/tmp/draft.exr"
        assert parms["resolutionx"].keys == ["640*2"]  # the expression is back
        assert parms["resolutiony"].value == 720
        assert parms["picture"].value == "$HIP/render/$F4.exr"  # unexpanded
        assert set(reply["overrides_applied"]) == set(reply["overrides_restored"])
        assert "resolutionx" in reply["overrides_restored"]
        assert "overrides_not_restored" not in reply

    def test_wait_for_render_is_on_for_the_call_and_off_again(self, karma):
        _, parms, seen = karma
        reply = rendering.start_render("/stage/karma1")
        assert seen["soho_foreground"] == 1
        assert parms["soho_foreground"].value == 0
        assert "Wait for Render to Complete" in reply["foreground_forced"]

    def test_wait_for_render_already_on_is_left_alone(self, karma):
        _, parms, _ = karma
        parms["soho_foreground"].value = 1
        reply = rendering.start_render("/stage/karma1")
        assert "foreground_forced" not in reply
        assert "overrides_applied" not in reply

    def test_a_failing_render_still_restores(self, karma):
        node, parms, _ = karma
        node.render.side_effect = RuntimeError("husk exited with code 1")
        with pytest.raises(RuntimeError, match="husk"):
            rendering.start_render("/stage/karma1", overrides={"resolutionx": 160})
        assert parms["resolutionx"].keys == ["640*2"]
        assert parms["soho_foreground"].value == 0

    def test_a_render_houdini_reports_as_failed_restores_and_says_so(self, karma, monkeypatch):
        node, parms, _ = karma
        node.render.side_effect = _OperationFailed("husk exited with code 1")
        monkeypatch.setattr(
            rendering, "failure_verdict", lambda *a: {"success": False, "wrote_files": False}
        )
        reply = rendering.start_render("/stage/karma1", overrides={"resolutionx": 160})
        assert reply["success"] is False
        assert parms["resolutionx"].keys == ["640*2"]
        assert "resolutionx" in reply["overrides_restored"]

    def test_a_missing_parm_is_refused_before_anything_is_set(self, karma):
        node, parms, _ = karma
        node.parms.return_value = []  # the did-you-mean labels
        with pytest.raises(ValueError, match="resolution_typo"):
            rendering.start_render(
                "/stage/karma1", overrides={"resolutionx": 160, "resolution_typo": 1}
            )
        assert parms["resolutionx"].keys == ["640*2"]
        assert parms["soho_foreground"].value == 0
        node.render.assert_not_called()

    def test_a_refused_write_names_the_parm_and_puts_back_the_rest(self, karma):
        node, parms, _ = karma
        parms["resolutiony"].locked = True
        with pytest.raises(ValueError, match="'resolutiony'.*locked.*put back"):
            rendering.start_render(
                "/stage/karma1", overrides={"resolutionx": 160, "resolutiony": 90}
            )
        assert parms["resolutionx"].keys == ["640*2"]
        assert parms["resolutiony"].value == 720
        assert parms["soho_foreground"].value == 0
        node.render.assert_not_called()

    def test_a_parm_tuple_takes_a_list(self, karma):
        node, _, seen = karma
        size = [_Parm(1), _Parm(1)]
        node.parmTuple.side_effect = lambda name: size if name == "res" else None
        reply = rendering.start_render("/stage/karma1", overrides={"res": [320, 180]})
        assert [p.value for p in size] == [1, 1]
        assert {"res[0]", "res[1]"} <= set(reply["overrides_restored"])

    def test_a_parm_tuple_given_one_value_is_refused(self, karma):
        node, _, _ = karma
        node.parmTuple.side_effect = lambda name: [_Parm(1), _Parm(1)]
        with pytest.raises(ValueError, match="2 components"):
            rendering.start_render("/stage/karma1", overrides={"res": 320})

    def test_overrides_with_background_are_refused(self, karma):
        with pytest.raises(ValueError, match="foreground render only"):
            rendering.start_render("/stage/karma1", background=True, overrides={"resolutionx": 1})


class TestStartRenderToolForwardsOverrides:
    async def test_overrides_reach_the_handler(self, mock_ctx, mock_bridge):
        from fxhoudinimcp.tools.rendering import start_render

        mock_bridge.execute.return_value = {"success": True, "wrote_files": True}
        await start_render(mock_ctx, "/stage/karma1", overrides={"resolutionx": 160})
        params = mock_bridge.execute.call_args.args[1]
        assert params["overrides"] == {"resolutionx": 160}

    async def test_no_overrides_sends_none(self, mock_ctx, mock_bridge):
        from fxhoudinimcp.tools.rendering import start_render

        mock_bridge.execute.return_value = {"success": True, "wrote_files": True}
        await start_render(mock_ctx, "/stage/karma1")
        assert "overrides" not in mock_bridge.execute.call_args.args[1]


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
