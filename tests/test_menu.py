"""Tests for the Houdini MCP menu definition.

Menu items are Python embedded in XML, which nothing imports and no linter
reads. A syntax error or a renamed function surfaces only as a menu entry that
does nothing when clicked, in a GUI session, with the traceback buried in the
console. These checks are cheap and catch that class of breakage without Houdini.
"""

from __future__ import annotations

# Built-in
import ast
import xml.etree.ElementTree as ET
from pathlib import Path

# Third-party
import pytest

_MENU = Path(__file__).resolve().parents[1] / "houdini" / "MainMenuCommon.xml"

# What the menu is allowed to call on the startup module. Kept explicit so
# renaming one of these in startup.py fails here instead of in the GUI.
_STARTUP_API = {
    "start",
    "stop",
    "is_running",
    "is_starting",
    "get_port",
    "ensure_running",
}


def _script_items() -> list[tuple[str, str]]:
    root = ET.parse(_MENU).getroot()
    items = []
    for item in root.iter("scriptItem"):
        code = item.find("scriptCode")
        assert code is not None and code.text, f"{item.get('id')} has no scriptCode"
        items.append((item.get("id") or "<unnamed>", code.text))
    return items


def test_menu_is_well_formed_xml():
    ET.parse(_MENU)


def test_every_script_item_compiles():
    items = _script_items()
    assert items, "no scriptItem found; the menu file has changed shape"
    for name, code in items:
        try:
            compile(code, name, "exec")
        except SyntaxError as exc:
            pytest.fail(f"{name} does not compile: {exc}")


def test_expected_items_exist():
    """Guard against an item being dropped by an unrelated edit."""
    ids = {name for name, _ in _script_items()}
    assert {
        "fxhoudinimcp_start",
        "fxhoudinimcp_stop",
        "fxhoudinimcp_connect",
        "fxhoudinimcp_status",
    } <= ids


def test_startup_calls_exist_on_the_real_module():
    """Every mcp.<name>() the menu calls must exist in startup.py.

    The menu imports fxhoudinimcp_server.startup as ``mcp``, which lives on the
    Houdini side of the repo and is not importable here without hou. So the
    module is parsed rather than imported, and the calls are compared by name.
    """
    startup = (
        _MENU.parent
        / "scripts"
        / "python"
        / "fxhoudinimcp_server"
        / "startup.py"
    )
    defined = {
        node.name
        for node in ast.parse(startup.read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef)
    }

    for name, code in _script_items():
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "mcp"
            ):
                assert func.attr in defined, (
                    f"{name} calls mcp.{func.attr}(), which startup.py does not "
                    f"define. Defined: {sorted(defined)}"
                )
                assert func.attr in _STARTUP_API, (
                    f"{name} calls mcp.{func.attr}(), which is not part of the "
                    "API the menu is meant to use"
                )
