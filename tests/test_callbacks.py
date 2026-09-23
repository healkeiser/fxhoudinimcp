"""Tests for callbacks.press: a parameter is pressed without Houdini's modal error window.

pressButton() answers a Python callback that raises with a modal "Error
running callback" window in a GUI session, and the bridge hangs until someone
clicks OK. callbacks.press runs a Python callback itself, with what
pressButton() hands it (measured on 22.0.429), and turns its exception into
CallbackError; a built-in action or an HScript callback, which open no such
window (measured), still go through pressButton(). The handlers that press a
parameter on the caller's behalf -- write_cache, start_render, import_file --
go through it too.

hou is mocked here; the live path was checked on Houdini 22.0.429.
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
import fxhoudinimcp_server.callbacks as callbacks  # noqa: E402
import fxhoudinimcp_server.handlers.cache_handlers as cache_handlers  # noqa: E402
import fxhoudinimcp_server.handlers.rendering_handlers as rendering  # noqa: E402
import fxhoudinimcp_server.handlers.scene_handlers as scene  # noqa: E402

hou = callbacks.hou


class _Parm:
    """A parm with a callback script in a given language; records presses."""

    def __init__(self, script="", language=None, value="0", name="probe"):
        self._script = script
        self._language = language if language is not None else hou.scriptLanguage.Python
        self._value = value
        self._name = name
        self.pressed: list = []
        self.node_ = MagicMock()
        self.node_.path.return_value = "/obj/geo1/btn"
        self.node_.type.return_value.nameWithCategory.return_value = "Sop/null"

    def parmTemplate(self):  # noqa: N802 -- HOM spelling
        template = MagicMock()
        template.scriptCallback.return_value = self._script
        template.scriptCallbackLanguage.return_value = self._language
        return template

    def node(self):
        return self.node_

    def name(self):
        return self._name

    def evalAsString(self):  # noqa: N802 -- HOM spelling
        return self._value

    def tuple(self):
        return [self]

    def multiParmInstanceIndices(self):  # noqa: N802 -- HOM spelling
        return ()

    def pressButton(self, *args):  # noqa: N802 -- HOM spelling
        self.pressed.append(args)


class _OperationFailed(Exception):
    """Stands in for hou.OperationFailed, which the hou stub does not define."""


@pytest.fixture
def pwd(monkeypatch):
    """hou.pwd()/setPwd as a single slot, so restoring is observable.

    hou.undos is replaced too: the hou stub is shared, and another module's
    test leaves an undo group that raises on it.
    """
    monkeypatch.setattr(hou, "undos", MagicMock())
    state = {"pwd": "ROOT"}
    monkeypatch.setattr(hou, "pwd", lambda: state["pwd"])
    monkeypatch.setattr(hou, "setPwd", lambda node: state.update(pwd=node))
    return state


class TestRoutes:
    def test_a_built_in_action_is_pressed(self):
        parm = _Parm(script="")
        assert callbacks.press(parm) == "native"
        assert parm.pressed == [()]

    def test_an_hscript_callback_is_pressed_with_its_arguments(self):
        parm = _Parm(script="opparm . tx 1", language=hou.scriptLanguage.Hscript)
        assert callbacks.press(parm, {"extra": 5}) == "hscript"
        assert parm.pressed == [({"extra": 5},)]

    def test_a_python_callback_is_run_here_not_pressed(self, pwd):
        parm = _Parm(script="pass")
        assert callbacks.press(parm) == "python"
        assert parm.pressed == []

    def test_a_non_string_script_reads_as_no_script(self):
        parm = _Parm()
        parm.parmTemplate = MagicMock()  # scriptCallback() answers a mock, not a str
        assert callbacks.callback_script(parm) == ""


class TestPythonCallbackRunsAsPressButtonWould:
    def test_kwargs_globals_and_pwd(self, monkeypatch, pwd):
        monkeypatch.setattr(hou, "session", MagicMock(), raising=False)
        script = (
            "import sys\n"
            "hou.session.seen = (dict(kwargs), sorted(k for k in globals() if not k.startswith('__')),"
            " hou.pwd())"
        )
        parm = _Parm(script=script, value="b", name="mode")
        callbacks.press(parm, {"extra": 5})
        seen, names, during = hou.session.seen
        assert seen["node"] is parm.node_ and seen["parm"] is parm
        assert seen["parm_name"] == seen["script_parm"] == "mode"
        assert seen["script_value"] == seen["script_value0"] == "b"
        # Strings, as pressButton() passes them (measured).
        assert seen["script_multiparm_index"] == "-1"
        assert seen["script_multiparm_nesting"] == "0"
        assert seen["extra"] == 5
        assert names == ["hou", "kwargs", "sys"]
        assert during is parm.node_
        assert pwd["pwd"] == "ROOT"  # restored

    def test_a_multiparm_instance_names_its_index_and_nesting(self, monkeypatch, pwd):
        monkeypatch.setattr(hou, "session", MagicMock(), raising=False)
        parm = _Parm(script="hou.session.seen = dict(kwargs)")
        parm.multiParmInstanceIndices = lambda: (2, 3)
        callbacks.press(parm)
        assert hou.session.seen["script_multiparm_index"] == "3"
        assert hou.session.seen["script_multiparm_nesting"] == "2"

    def test_a_raising_callback_is_a_callback_error(self, pwd):
        parm = _Parm(script="raise PermissionError('locked')")
        with pytest.raises(callbacks.CallbackError) as caught:
            callbacks.press(parm)
        message = str(caught.value)
        assert message.startswith("Callback of /obj/geo1/btn/probe raised PermissionError: locked")
        assert "Sop/null/probe" in message  # the traceback names the script as Houdini does
        assert "callbacks.py" not in message  # the bridge's own frame is not part of it
        assert pwd["pwd"] == "ROOT"


class TestHandlersPressThroughCallbacks:
    """A raising Save to Disk / Build Hierarchy is a reply, not a modal window."""

    def test_write_cache_reports_a_raising_save_to_disk_as_a_failed_write(self, monkeypatch, pwd):
        monkeypatch.setattr(cache_handlers.hou.hipFile, "isNewFile", lambda: False)
        execute = _Parm(script="raise RuntimeError('disk full')", name="execute")
        parms = {"execute": execute, "cookoutputnode": None, "trange": None, "loadfromdisk": None}
        node = MagicMock()
        node.parm.side_effect = parms.get
        monkeypatch.setattr(cache_handlers, "_get_node", lambda p: node)
        monkeypatch.setattr(cache_handlers, "reported_outputs", lambda n: [])
        seen = {}

        def failure_verdict(node, before, failure, action):
            seen["failure"] = failure
            return {"success": False, "wrote_files": False, "message": str(failure), "errors": []}

        monkeypatch.setattr(cache_handlers, "failure_verdict", failure_verdict)

        result = cache_handlers._write_cache(node_path="/obj/g/c")
        assert execute.pressed == []
        assert isinstance(seen["failure"], callbacks.CallbackError)
        assert result["success"] is False
        assert "disk full" in result["message"]

    def test_start_render_reports_a_raising_file_cache_as_a_failed_render(self, monkeypatch, pwd):
        # The hou stub has no OperationFailed; a class of its own keeps it
        # from catching the CallbackError by accident.
        monkeypatch.setattr(rendering.hou, "OperationFailed", _OperationFailed, raising=False)
        execute = _Parm(script="raise RuntimeError('disk full')", name="execute")
        node = MagicMock()
        node.parm.side_effect = {"execute": execute}.get
        monkeypatch.setattr(rendering, "_renderable", lambda p: (node, "Sop", False))
        monkeypatch.setattr(rendering, "reported_outputs", lambda n: [])
        monkeypatch.setattr(
            rendering,
            "failure_verdict",
            lambda node, before, e: {"success": False, "message": str(e)},
        )

        result = rendering.start_render("/obj/g/filecache1")
        assert execute.pressed == []
        assert result["success"] is False
        assert result["method"] == "execute button"
        assert "raised RuntimeError: disk full" in result["message"]

    def test_import_file_builds_an_alembic_hierarchy_through_press(self, monkeypatch, tmp_path):
        abc = tmp_path / "shot.abc"
        abc.write_bytes(b"")
        parent = MagicMock()
        parent.childTypeCategory.return_value.name.return_value = "Object"
        container = parent.createNode.return_value
        container.path.return_value = "/obj/alembic_import"
        monkeypatch.setattr(scene.hou, "node", lambda path: parent)
        pressed = []
        monkeypatch.setattr(scene, "press", pressed.append)

        scene.import_file(str(abc))
        assert pressed == [container.parm.return_value]
        container.parm.assert_any_call("buildHierarchy")
