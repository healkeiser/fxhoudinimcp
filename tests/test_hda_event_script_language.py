"""set_hda_section_content marks an event script Python or HScript.

Houdini runs OnCreated & co. as HScript unless the definition's
ExtraFileOptions say <section>/IsPython: a Python OnCreated written through the
verb silently did nothing.

hou is mocked here; the live check ran on Houdini 22.0.466.
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
import fxhoudinimcp_server.handlers.hda_handlers as hda  # noqa: E402


class _SectionDefinition:
    def __init__(self):
        self.sections_written: dict = {}
        self.options: dict = {}

    def addSection(self, name, content):  # noqa: N802
        self.sections_written[name] = content

    def setExtraFileOption(self, key, value):  # noqa: N802
        self.options[key] = value

    def extraFileOptions(self):  # noqa: N802
        return dict(self.options)

    def nodeTypeName(self):  # noqa: N802
        return "ktest"


class TestEventScriptLanguage:
    @pytest.fixture
    def definition(self, monkeypatch):
        d = _SectionDefinition()
        monkeypatch.setattr(hda, "_get_node", lambda path: MagicMock())
        monkeypatch.setattr(hda, "_get_definition", lambda node: d)
        return d

    def test_python_code_in_on_created_is_marked_python(self, definition):
        result = hda.set_hda_section_content(
            "/obj/k", "OnCreated", 'kwargs["node"].setComment("x")\n'
        )
        assert definition.options == {
            "OnCreated/IsScript": True,
            "OnCreated/IsExpr": False,
            "OnCreated/IsPython": True,
        }
        assert result["script_language"] == "python"

    def test_hscript_stays_hscript_unless_said(self, definition):
        result = hda.set_hda_section_content("/obj/k", "OnLoaded", "opset -d on $arg1\n")
        assert definition.options == {}
        assert result["script_language"] == "hscript"
        hda.set_hda_section_content("/obj/k", "OnLoaded", "opset -d on $arg1\n", language="hscript")
        assert definition.options["OnLoaded/IsPython"] is False

    def test_a_help_section_takes_no_language(self, definition):
        result = hda.set_hda_section_content("/obj/k", "Help", "= K =")
        assert "script_language" not in result and definition.options == {}
        with pytest.raises(ValueError, match="language applies to event scripts"):
            hda.set_hda_section_content("/obj/k", "Help", "= K =", language="python")
        with pytest.raises(ValueError, match="'python' or 'hscript'"):
            hda.set_hda_section_content("/obj/k", "OnCreated", "x", language="vex")
