"""get_hda_info reports a toggle's and a menu's default as their value.

A toggle answers defaultValue() with a bool and a menu with an int, so
list() raised and the fallback listed the default expression: a built-in
toggle read ['o', 'n'], a user toggle and a menu read []. The live check
ran on Houdini 22.0.368.
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


def _template(default, expression):
    template = MagicMock()
    template.defaultValue.return_value = default
    # What Houdini answers: "on"/"off" for a built-in toggle, ("",) per component.
    template.defaultExpression.return_value = expression
    return template


@pytest.mark.parametrize(
    ("default", "expression", "expected"),
    [
        (True, "on", True),
        (False, "off", False),
        (True, "", True),
        (0, "", 0),
        ((1.0, 2.0), ("", ""), [1.0, 2.0]),
        (("",), ("",), [""]),
    ],
)
def test_the_default_is_the_value(default, expression, expected):
    assert hda._parm_template_to_dict(_template(default, expression))["default_value"] == expected


def test_a_template_without_a_default_reports_none():
    template = MagicMock()
    template.defaultValue.side_effect = AttributeError("FolderParmTemplate")
    assert hda._parm_template_to_dict(template)["default_value"] is None
