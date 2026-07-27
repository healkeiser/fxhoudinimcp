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


def _run_item(item_id: str, port: int = 8100, running: bool = True) -> dict:
    """Execute a menu item against fake hou/startup modules, capturing the dialog.

    The menu only ever runs in a GUI Houdini, where hou.ui exists; hython has no
    hou.ui at all, so the alternative is shipping this code untested. Faking the
    two modules it touches exercises the real branching.
    """
    import sys
    import types

    captured: dict = {}

    class FakeUI:
        def copyTextToClipboard(self, text):
            captured["clipboard"] = text

        def displayMessage(self, text, **kwargs):
            captured["text"] = text
            captured.update(kwargs)

    hou = types.ModuleType("hou")
    hou.ui = FakeUI()
    hou.severityType = types.SimpleNamespace(Error="error")

    startup = types.ModuleType("fxhoudinimcp_server.startup")
    startup.get_port = lambda: port
    startup.is_running = lambda: running
    startup.is_starting = lambda: False
    startup.start = lambda *a, **k: None
    startup.stop = lambda: None
    package = types.ModuleType("fxhoudinimcp_server")
    package.startup = startup

    code = dict(_script_items())[item_id]
    saved = {name: sys.modules.get(name) for name in ("hou", "fxhoudinimcp_server")}
    sys.modules["hou"] = hou
    sys.modules["fxhoudinimcp_server"] = package
    sys.modules["fxhoudinimcp_server.startup"] = startup
    try:
        exec(compile(code, item_id, "exec"), {})
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        sys.modules.pop("fxhoudinimcp_server.startup", None)
    return captured


def test_connect_dialog_recommends_the_self_correcting_command():
    """It must not hand out a bare `python` in a `claude mcp add` line.

    From inside Houdini there is no way to find the external Python that has
    fxhoudinimcp installed, so a ready-to-paste `claude mcp add` would carry a
    bare `python` -- the documented cause of a client reporting "disconnected",
    and worse, pasting it over a working registration would replace a correct
    absolute path with that bare name.
    """
    dialog = _run_item("fxhoudinimcp_connect")

    assert dialog["clipboard"] == "python -m fxhoudinimcp install --client-only"
    assert "claude mcp add" not in dialog["clipboard"]
    assert "claude mcp add" in dialog["details"], (
        "the manual route should still be documented, just not handed over "
        "ready to paste"
    )


def test_connect_dialog_details_are_expanded_and_explain_the_command():
    """The details pane is what makes the commands selectable, so it must be open."""
    dialog = _run_item("fxhoudinimcp_connect")

    assert dialog["details_expanded"] is True
    assert dialog["details_label"]
    # Naming the command is not enough: it has to say where to run it and what
    # it will do, which is the part that was confusing.
    assert "terminal" in dialog["details"].lower()
    assert "What it does" in dialog["details"]
    assert "No module named fxhoudinimcp" in dialog["details"]


def test_connect_dialog_reports_the_real_port():
    default = _run_item("fxhoudinimcp_connect", port=8100)
    moved = _run_item("fxhoudinimcp_connect", port=8103)

    assert "8100" in default["text"]
    assert "8103" in moved["text"]
    # A moved port needs explaining, since the client scans and takes the lowest.
    assert "8103" in moved["details"]
    assert "HOUDINI_PORT=8103" in moved["details"]
    assert "HOUDINI_PORT" not in default["details"]


def test_connect_dialog_warns_when_the_server_is_stopped():
    stopped = _run_item("fxhoudinimcp_connect", running=False)
    assert "NOT running" in stopped["text"]


def test_connect_dialog_survives_a_broken_clipboard():
    """Failing to copy must never stop the commands being shown."""
    import sys
    import types

    captured: dict = {}

    class FakeUI:
        def copyTextToClipboard(self, text):
            raise RuntimeError("no clipboard on this display")

        def displayMessage(self, text, **kwargs):
            captured["text"] = text
            captured.update(kwargs)

    hou = types.ModuleType("hou")
    hou.ui = FakeUI()
    startup = types.ModuleType("fxhoudinimcp_server.startup")
    startup.get_port = lambda: 8100
    startup.is_running = lambda: True
    package = types.ModuleType("fxhoudinimcp_server")
    package.startup = startup

    code = dict(_script_items())["fxhoudinimcp_connect"]
    sys.modules["hou"] = hou
    sys.modules["fxhoudinimcp_server"] = package
    sys.modules["fxhoudinimcp_server.startup"] = startup
    try:
        exec(compile(code, "connect", "exec"), {})
    finally:
        for name in ("hou", "fxhoudinimcp_server", "fxhoudinimcp_server.startup"):
            sys.modules.pop(name, None)

    assert captured["details"]
    assert "clipboard" not in captured["text"].lower()


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
