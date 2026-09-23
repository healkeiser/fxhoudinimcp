"""A locked parameter is named before anything is written; run_callbacks runs what the UI runs.

On a karmarendersettings, res_mode = autoheight (the default) locks
resolutiony (Parm.isLocked() is true), and only the callback of res_mode
clears it. hou.Parm.set() does not run callbacks, so writing res_mode through
the bridge left the lock in place, and every write to resolutiony -- set(),
setExpression(), revertToDefaults() -- failed with Houdini's generic
"permission error ... locked assets, takes". build_network rolled back the
whole graph on it, its dry run passed, set_parameters reported the raw
permission error, and the #41 hint sent callers to revert_parameter, which
fails the same way.

Now: a write to a locked parm is refused before it is tried, naming the menu
whose callback sets the lock; run_callbacks runs a parm's callback after its
write (through callbacks.press, so a raising Python callback is a reply, not
Houdini's modal error window); build_network refuses such a spec at
validation, nothing created.

hou is mocked here; the live checks ran on Houdini 22.0.429.
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
import fxhoudinimcp_server.callbacks as callbacks_module  # noqa: E402
import fxhoudinimcp_server.handlers.graph_handlers as graph  # noqa: E402
import fxhoudinimcp_server.handlers.parameter_handlers as parameters  # noqa: E402

hou = parameters.hou


class _PermissionError(Exception):
    """Stands in for hou.PermissionError, which the hou stub does not define."""


class _OperationFailed(Exception):
    """Stands in for hou.OperationFailed, which the hou stub does not define."""


class _Template:
    def __init__(self, kind=None, callback="", menu=(), language=None):
        self._kind = kind if kind is not None else hou.parmTemplateType.Float
        self._callback = callback
        self._menu = list(menu)
        self._language = language if language is not None else hou.scriptLanguage.Python

    def type(self):
        return self._kind

    def scriptCallback(self):  # noqa: N802 -- HOM spelling
        return self._callback

    def scriptCallbackLanguage(self):  # noqa: N802 -- HOM spelling
        return self._language


class _Parm:
    """A parm with a lock, an expression and a callback, logging what is done to it."""

    def __init__(self, name, node, value=0, locked=False, expression=None, template=None):
        self._name = name
        self._node = node
        self._value = value
        self._locked = locked
        self._expression = expression
        self._template = template or _Template()
        self.calls: list = []
        self.tuple_name = name

    def name(self):
        return self._name

    def node(self):
        return self._node

    def path(self):
        return f"{self._node.path()}/{self._name}"

    def tuple(self):
        parm_tuple = MagicMock()
        parm_tuple.name.return_value = self.tuple_name
        return parm_tuple

    def parmTemplate(self):  # noqa: N802 -- HOM spelling
        return self._template

    def isLocked(self):  # noqa: N802 -- HOM spelling
        return self._locked

    def expression(self):
        if self._expression is None:
            raise hou.OperationFailed("no expression")
        return self._expression

    def getReferencedParm(self):  # noqa: N802 -- HOM spelling
        return self

    def deleteAllKeyframes(self):  # noqa: N802 -- HOM spelling
        if self._locked:
            raise hou.PermissionError("permission error")
        self.calls.append(("deleteAllKeyframes",))
        self._expression = None

    def set(self, value):
        if self._locked:
            raise hou.PermissionError("permission error ... locked assets, takes")
        self.calls.append(("set", value))
        self._value = value
        self._expression = None

    def eval(self):
        return self._value

    def evalAsString(self):  # noqa: N802 -- HOM spelling
        return str(self._value)

    def menuItems(self):  # noqa: N802 -- HOM spelling
        return tuple(self._template._menu)

    def pressButton(self, *args):  # noqa: N802 -- HOM spelling
        self.calls.append(("pressButton",))
        self._node.on_callback(self)

    def revertToDefaults(self):  # noqa: N802 -- HOM spelling
        if self._locked:
            raise hou.PermissionError("permission error")
        self.calls.append(("revert",))


class _ParmTuple(list):
    def __init__(self, name, components):
        super().__init__(components)
        self._name = name

    def name(self):
        return self._name

    def set(self, values):
        for component, value in zip(self, values, strict=True):
            component.set(value)


class _KarmaSettings:
    """A karmarendersettings: res_mode's callback (un)locks the resolution pair.

    res_mode is a String parm with a menu, not a Menu parm (measured on
    22.0.429); the HScript preset button next to it names the same tuple.
    """

    def __init__(self, path="/stage/krs"):
        self._path = path
        menu = _Template(
            hou.parmTemplateType.String,
            callback="__import__('loputils').updateResolutionParameters(hou.pwd(),True)",
            menu=("manual", "autowidth", "autoheight"),
        )
        self.res_mode = _Parm("res_mode", self, "autoheight", template=menu)
        self.resx = _Parm("resolutionx", self, 1280)
        self.resy = _Parm(
            "resolutiony",
            self,
            720,
            locked=True,
            expression="pythonexprf(loputils.computeResolutionParameter(True, True))",
        )
        self.resx.tuple_name = self.resy.tuple_name = "resolution"
        self.plain = _Parm("samples", self, 8)
        preset = _Template(
            hou.parmTemplateType.Button,
            callback='opparm . resolution ( `arg("$script_value", 0)` )',
            language=hou.scriptLanguage.Hscript,
        )
        self.preset = _Parm("resolutionMenu", self, 0, template=preset)
        self.callback_raises = False

    def path(self):
        return self._path

    def parms(self):
        return [self.res_mode, self.resx, self.resy, self.plain, self.preset]

    def parm(self, name):
        return {p.name(): p for p in self.parms()}.get(name)

    def parmTuple(self, name):  # noqa: N802 -- HOM spelling
        if name == "resolution":
            return _ParmTuple("resolution", [self.resx, self.resy])
        return None

    def destroy(self):
        pass

    def on_callback(self, parm):
        if parm is self.res_mode:
            mode = self.res_mode._value
            self.resx._locked = mode == "autowidth"
            self.resy._locked = mode == "autoheight"
            if not self.resy._locked:
                self.resy._expression = None


@pytest.fixture(autouse=True)
def hom(monkeypatch):
    """HOM's exception classes, and callbacks run by the stand-in node.

    A Python callback goes through callbacks.press, which executes the
    script; here the stand-in node plays loputils instead.
    """
    monkeypatch.setattr(hou, "PermissionError", _PermissionError, raising=False)
    monkeypatch.setattr(hou, "OperationFailed", _OperationFailed, raising=False)
    monkeypatch.setattr(hou, "undos", MagicMock())
    monkeypatch.setattr(parameters, "_serialize_value", lambda value: value)
    ran: list[str] = []

    def run(parm, script, kwargs):
        node = parm.node()
        ran.append(kwargs["parm_name"])
        if getattr(node, "callback_raises", False):
            raise callbacks_module.CallbackError(
                f"Callback of {node.path()}/{parm.name()} raised RuntimeError: callback failed\ntb"
            )
        node.on_callback(kwargs["parm"])

    monkeypatch.setattr(callbacks_module, "exec_python_callback", run)
    return ran


class TestALockedParmIsNamed:
    def test_the_message_names_the_lock_and_the_menu_that_sets_it(self):
        message = parameters.locked_message(_KarmaSettings().resy)
        assert "'resolutiony' on /stage/krs is locked" in message
        assert "res_mode (now 'autoheight', menu ['manual', 'autowidth', 'autoheight'])" in message
        assert "run_callbacks=true" in message
        # The HScript preset button also names the tuple, but does not set the lock.
        assert "resolutionMenu" not in message
        assert "revert_parameter do not help" in message

    def test_an_unlocked_parm_has_no_message(self):
        assert parameters.locked_message(_KarmaSettings().resx) is None

    def test_a_stand_in_is_not_a_lock(self):
        assert parameters.locked_message(MagicMock()) is None

    def test_no_controller_found_says_where_to_look(self):
        node = _KarmaSettings()
        node.res_mode._template._callback = ""
        message = parameters.locked_message(node.resy)
        assert "get_parm_template_tree" in message

    def test_the_expression_hint_gives_way_to_the_lock(self):
        # The #41 hint says "remove the expression with revert_parameter first",
        # which a lock refuses exactly like the write.
        message = parameters._expression_driven([_KarmaSettings().resy])
        assert "is locked" in message and "revert_parameter first" not in message


class TestWritesToALockedParm:
    def test_set_parameter_refuses_before_writing(self, monkeypatch):
        node = _KarmaSettings()
        monkeypatch.setattr(parameters, "_resolve_parm", lambda path, name: node.resy)
        with pytest.raises(parameters.LockedParmError, match="res_mode"):
            parameters._set_parameter("/stage/krs", "resolutiony", 1080)
        assert node.resy.calls == []

    def test_override_expression_does_not_touch_it_either(self):
        node = _KarmaSettings()
        with pytest.raises(parameters.LockedParmError):
            parameters._write_parm(node.resy, 1080, override_expression=True)
        assert node.resy.calls == []

    def test_a_tuple_with_a_locked_component_writes_nothing(self):
        node = _KarmaSettings()
        with pytest.raises(parameters.LockedParmError):
            parameters._set_tuple(node, "resolution", [1920, 1080])
        assert node.resx.calls == [] and node.resy.calls == []

    def test_the_batch_marks_it_locked(self, monkeypatch):
        node = _KarmaSettings()
        monkeypatch.setattr(parameters, "_resolve_node", lambda path: node)
        reply = parameters._set_parameters("/stage/krs", {"resolutionx": 1920, "resolutiony": 1080})
        assert [e["parm_name"] for e in reply["set"]] == ["resolutionx"]
        assert reply["errors"][0]["locked"] is True
        assert "res_mode" in reply["errors"][0]["error"]
        assert reply["locked_parms"] == ["resolutiony"]

    def test_run_callbacks_unlocks_it_in_order(self, monkeypatch, hom):
        node = _KarmaSettings()
        monkeypatch.setattr(parameters, "_resolve_node", lambda path: node)
        reply = parameters._set_parameters(
            "/stage/krs", {"res_mode": "manual", "resolutiony": 1080}, run_callbacks=True
        )
        assert reply["errors"] == []
        assert reply["set"][0]["callback_run"] is True
        assert node.resy._value == 1080
        assert hom == ["res_mode"]
        # Not through pressButton(): that is what opens the modal error window.
        assert ("pressButton",) not in node.res_mode.calls

    def test_a_parm_without_a_callback_reports_nothing_about_one(self, monkeypatch):
        node = _KarmaSettings()
        monkeypatch.setattr(parameters, "_resolve_node", lambda path: node)
        reply = parameters._set_parameters("/stage/krs", {"samples": 16}, run_callbacks=True)
        assert "callback_run" not in reply["set"][0]

    def test_without_run_callbacks_the_menu_alone_does_not_unlock(self, monkeypatch):
        node = _KarmaSettings()
        monkeypatch.setattr(parameters, "_resolve_node", lambda path: node)
        reply = parameters._set_parameters(
            "/stage/krs", {"res_mode": "manual", "resolutiony": 1080}
        )
        assert reply["locked_parms"] == ["resolutiony"]
        assert "callback_run" not in reply["set"][0]

    def test_a_tuple_write_runs_its_callback_too(self, hom):
        node = _KarmaSettings()
        node.resy._locked = False
        node.resx._template = node.resy._template = _Template(callback="resolution cb")
        new_value, report = parameters._set_tuple(
            node, "resolution", [1920, 1080], run_callbacks=True
        )
        assert new_value == [1920, 1080]
        assert report["callback_run"] is True and hom == ["resolutionx"]

    def test_a_failing_callback_is_reported_not_shown(self, monkeypatch):
        node = _KarmaSettings()
        node.callback_raises = True
        monkeypatch.setattr(parameters, "_resolve_node", lambda path: node)
        reply = parameters._set_parameters("/stage/krs", {"res_mode": "manual"}, run_callbacks=True)
        entry = reply["set"][0]
        assert entry["callback_run"] is False
        assert "callback failed" in entry["callback_error"]
        assert reply["callbacks_not_run"] == {
            "res_mode": "Callback of /stage/krs/res_mode raised RuntimeError: callback failed"
        }
        assert ("pressButton",) not in node.res_mode.calls

    def test_an_hscript_callback_goes_through_press_button(self, hom):
        # A failing HScript callback opens no window (measured), so pressButton() is safe.
        node = _KarmaSettings()
        node.res_mode._template._language = hou.scriptLanguage.Hscript
        info = parameters._write_parm(node.res_mode, "manual", run_callbacks=True)
        assert info["callback_run"] is True
        assert ("pressButton",) in node.res_mode.calls and hom == []

    def test_revert_refuses_with_the_same_explanation(self, monkeypatch):
        node = _KarmaSettings()
        monkeypatch.setattr(parameters, "_resolve_parm", lambda path, name: node.resy)
        with pytest.raises(parameters.LockedParmError, match="res_mode"):
            parameters._revert_parameter("/stage/krs", "resolutiony")
        assert node.resy.calls == []


class TestBuildNetworkRefusesALockedParmUpFront:
    @pytest.fixture
    def build(self, monkeypatch):
        """build_network over a stand-in parent whose createNode makes karmarendersettings."""
        node_type = MagicMock()
        node_type.name.return_value = "karmarendersettings"
        node_type.maxNumInputs.return_value = 1
        created: list = []

        def create_node(type_name, name=None):
            created.append(name)
            node = _KarmaSettings(f"/stage/{name or 'probe'}")
            node.name = lambda: name or "probe"
            return node

        parent = MagicMock()
        parent.children.return_value = []
        parent.createNode.side_effect = create_node
        monkeypatch.setattr(graph.hou, "node", lambda path: parent)
        monkeypatch.setattr(graph, "_resolve_node_type", lambda cat, name: node_type)

        def knowledge(scratch, resolved, parm_types=None, factory_expressions=None, locked=None):
            if locked is not None:
                locked.update({"resolution": ["resolutiony"], "resolutiony": ["resolutiony"]})
            names = {"res_mode", "resolutionx", "resolutiony", "samples"}
            return names, {"resolution"}, {}, [], {"inputs": [], "outputs": []}

        monkeypatch.setattr(graph, "_parm_names_for_type", knowledge)
        return created

    _SPEC = [{"type": "karmarendersettings", "name": "krs", "parms": {"resolution": [1920, 1080]}}]

    def test_the_spec_is_refused_and_nothing_is_built(self, build):
        result = graph.build_network("/stage", self._SPEC)
        assert result["success"] is False and result["created"] == []
        assert "resolution" in result["locked_parms"]["krs"]
        assert "res_mode" in result["errors"][0]
        # Only the validation replay's probe was made -- no node of the build.
        assert build == [None]

    def test_the_dry_run_says_the_same(self, build):
        result = graph.build_network("/stage", self._SPEC, dry_run=True)
        assert result["valid"] is False and "krs" in result["locked_parms"]
        assert "expressions_in_the_way" not in result

    def test_run_callbacks_on_the_menu_first_passes(self, build):
        spec = [
            {
                "type": "karmarendersettings",
                "name": "krs",
                "parms": {"res_mode": "manual", "resolution": [1920, 1080]},
                "run_callbacks": True,
            }
        ]
        assert graph.build_network("/stage", spec, dry_run=True)["valid"] is True

    def test_the_menu_after_the_locked_parm_is_too_late(self, build):
        spec = [
            {
                "type": "karmarendersettings",
                "name": "krs",
                "parms": {"resolution": [1920, 1080], "res_mode": "manual"},
                "run_callbacks": True,
            }
        ]
        result = graph.build_network("/stage", spec, dry_run=True)
        assert result["valid"] is False and list(result["locked_parms"]["krs"]) == ["resolution"]

    def test_a_spec_that_leaves_locked_parms_alone_is_not_replayed(self, build):
        spec = [{"type": "karmarendersettings", "name": "krs", "parms": {"samples": 16}}]
        assert graph.build_network("/stage", spec, dry_run=True)["valid"] is True
        assert build == []  # no replay probe


class TestApplyParm:
    def test_a_locked_component_raises_before_the_write(self):
        node = _KarmaSettings()
        with pytest.raises(parameters.LockedParmError):
            graph._apply_parm(node, "resolution", [1920, 1080])
        assert node.resx.calls == []

    def test_run_callbacks_is_reported_per_parm(self, hom):
        node = _KarmaSettings()
        report = graph._apply_parm(node, "res_mode", "manual", run_callbacks=True)
        assert report["callbacks_run"] == {"res_mode": True}
        assert node.resy._locked is False

    def test_a_raising_callback_is_reported_not_raised(self):
        node = _KarmaSettings()
        node.callback_raises = True
        report = graph._apply_parm(node, "res_mode", "manual", run_callbacks=True)
        assert "callback failed" in report["callbacks_not_run"]["res_mode"]

    def test_the_type_probe_records_locked_components(self):
        node = _KarmaSettings()
        node.parmTuples = lambda: [
            node.parmTuple("resolution"),
            _ParmTuple("samples", [node.plain]),
        ]
        node.parms = lambda: [node.res_mode, node.resx, node.resy, node.plain]
        scratch = MagicMock()
        scratch.createNode.return_value = node
        locked: dict = {}
        graph._parm_names_for_type(scratch, MagicMock(), locked=locked)
        assert locked == {"resolution": ["resolutiony"], "resolutiony": ["resolutiony"]}
