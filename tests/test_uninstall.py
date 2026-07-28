"""Tests for the uninstaller.

An uninstaller is held to a stricter standard than an installer, because its
mistakes are not recoverable by re-running it. So the tests are mostly about
restraint: never delete without saying what and asking first, never assume
consent from a script that cannot be asked, and never touch the parts of a
Claude Desktop config that belong to somebody else's servers.

The one place it is deliberately less cautious than `install` is the choice of
directory. Installing has to know which Houdini you mean. Removing does not:
every fxhoudinimcp.json found is a leftover, and the one left behind is exactly
what silently overrides the next install.
"""

from __future__ import annotations

# Built-in
import json
import re
import subprocess
from pathlib import Path

# Third-party
import pytest

# Internal
from fxhoudinimcp import uninstall as uninst


def _package_file(directory: Path, target: str = "/plugins/somewhere") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "fxhoudinimcp.json"
    path.write_text(
        json.dumps({"env": [{"FXHOUDINIMCP": target}], "path": "$FXHOUDINIMCP"}),
        encoding="utf-8",
    )
    return path


def _answers(monkeypatch, *replies: str) -> None:
    pending = list(replies)

    def fake_input(prompt: str = "") -> str:
        if not pending:
            raise EOFError
        return pending.pop(0)

    monkeypatch.setattr("builtins.input", fake_input)


@pytest.fixture
def no_clients(monkeypatch):
    """No MCP client on the machine, so the Houdini half can be tested alone."""
    monkeypatch.setattr(uninst, "claude_code_available", lambda: False)
    monkeypatch.setattr(uninst, "desktop_config_path", lambda: None)


@pytest.fixture
def interactive(monkeypatch):
    monkeypatch.setattr(uninst, "stdin_is_interactive", lambda: True)


###### Finding what to remove


def test_finds_every_package_file(monkeypatch, tmp_path):
    """The forgotten one is the whole problem, so the default is all of them."""
    first = _package_file(tmp_path / "h21")
    second = _package_file(tmp_path / "h22")
    monkeypatch.setattr(uninst, "existing_packages", lambda: [(first, ""), (second, "")])

    assert uninst.find_package_files(None) == [first, second]


def test_an_explicit_dir_narrows_it_to_one(tmp_path):
    mine = _package_file(tmp_path / "h22")
    _package_file(tmp_path / "h21")

    assert uninst.find_package_files(str(tmp_path / "h22")) == [mine]


def test_an_explicit_dir_with_nothing_in_it_finds_nothing(tmp_path):
    (tmp_path / "empty").mkdir()
    assert uninst.find_package_files(str(tmp_path / "empty")) == []


###### Consent


def test_nothing_is_removed_without_confirmation(
    monkeypatch, no_clients, interactive, tmp_path, capsys
):
    mine = _package_file(tmp_path / "h22")
    monkeypatch.setattr(uninst, "existing_packages", lambda: [(mine, "")])
    _answers(monkeypatch, "n")

    assert uninst.main([]) == 1

    assert mine.is_file()
    assert "Cancelled" in capsys.readouterr().out


def test_a_bare_return_is_not_consent(
    monkeypatch, no_clients, interactive, tmp_path
):
    """The prompt reads [y/N], so the default has to actually be no."""
    mine = _package_file(tmp_path / "h22")
    monkeypatch.setattr(uninst, "existing_packages", lambda: [(mine, "")])
    _answers(monkeypatch, "")

    assert uninst.main([]) == 1
    assert mine.is_file()


def test_a_script_that_cannot_be_asked_is_refused(
    monkeypatch, no_clients, tmp_path, capsys
):
    """No terminal means no consent. --yes is how a script says it meant it."""
    mine = _package_file(tmp_path / "h22")
    monkeypatch.setattr(uninst, "existing_packages", lambda: [(mine, "")])
    monkeypatch.setattr(uninst, "stdin_is_interactive", lambda: False)

    def explode(prompt: str = "") -> str:
        raise AssertionError("must not prompt when stdin is not a terminal")

    monkeypatch.setattr("builtins.input", explode)

    assert uninst.main([]) == 1

    assert mine.is_file()
    assert "--yes" in capsys.readouterr().err


def test_yes_removes_without_asking(monkeypatch, no_clients, tmp_path):
    mine = _package_file(tmp_path / "h22")
    monkeypatch.setattr(uninst, "existing_packages", lambda: [(mine, "")])
    monkeypatch.setattr(uninst, "stdin_is_interactive", lambda: False)

    assert uninst.main(["--yes"]) == 0
    assert not mine.exists()


def test_confirming_removes_every_file(
    monkeypatch, no_clients, interactive, tmp_path
):
    first = _package_file(tmp_path / "h21")
    second = _package_file(tmp_path / "h22")
    monkeypatch.setattr(
        uninst, "existing_packages", lambda: [(first, ""), (second, "")]
    )
    _answers(monkeypatch, "y")

    assert uninst.main([]) == 0

    assert not first.exists()
    assert not second.exists()


def test_what_will_be_removed_is_listed_before_the_question(
    monkeypatch, no_clients, interactive, tmp_path, capsys
):
    """Consent to an unseen list is not consent."""
    mine = _package_file(tmp_path / "h22")
    monkeypatch.setattr(uninst, "existing_packages", lambda: [(mine, "")])
    _answers(monkeypatch, "y")

    uninst.main([])

    assert str(mine) in capsys.readouterr().out


###### Dry run


def test_dry_run_removes_nothing_and_never_asks(
    monkeypatch, no_clients, tmp_path, capsys
):
    mine = _package_file(tmp_path / "h22")
    monkeypatch.setattr(uninst, "existing_packages", lambda: [(mine, "")])

    def explode(prompt: str = "") -> str:
        raise AssertionError("--dry-run has nothing to consent to")

    monkeypatch.setattr("builtins.input", explode)

    assert uninst.main(["--dry-run"]) == 0

    assert mine.is_file()
    out = capsys.readouterr().out
    assert "Would remove" in out
    assert "Nothing was changed" in out


def test_nothing_to_do_is_not_an_error(monkeypatch, no_clients, capsys):
    monkeypatch.setattr(uninst, "existing_packages", lambda: [])
    assert uninst.main([]) == 0
    assert "Nothing to do" in capsys.readouterr().out


###### Scope


def test_client_only_leaves_the_package_files(
    monkeypatch, no_clients, interactive, tmp_path, capsys
):
    mine = _package_file(tmp_path / "h22")
    monkeypatch.setattr(uninst, "existing_packages", lambda: [(mine, "")])

    assert uninst.main(["--client-only", "--yes"]) == 0

    assert mine.is_file()
    assert "Skipped (--client-only)" in capsys.readouterr().out


def test_client_only_rejects_a_contradictory_houdini_dir(tmp_path):
    with pytest.raises(SystemExit):
        uninst.main(["--client-only", "--houdini-dir", str(tmp_path)])


def test_client_none_touches_no_config(monkeypatch, tmp_path, capsys):
    mine = _package_file(tmp_path / "h22")
    monkeypatch.setattr(uninst, "existing_packages", lambda: [(mine, "")])
    monkeypatch.setattr(uninst, "stdin_is_interactive", lambda: False)

    def explode() -> bool:
        raise AssertionError("--client none must not look for clients")

    monkeypatch.setattr(uninst, "claude_code_available", explode)

    assert uninst.main(["--yes", "--client", "none"]) == 0

    assert not mine.exists()
    assert "No client config was touched" in capsys.readouterr().out


def test_the_python_package_is_left_alone_and_said_so(
    monkeypatch, no_clients, capsys
):
    """Removing the package from inside itself is how you get a half-install."""
    monkeypatch.setattr(uninst, "existing_packages", lambda: [])

    uninst.main([])

    assert "pip uninstall fxhoudinimcp" in capsys.readouterr().out


###### Claude Desktop config


def test_desktop_removal_preserves_other_servers(tmp_path):
    config = tmp_path / "claude_desktop_config.json"
    config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "other": {"command": "node", "args": ["x.js"]},
                    uninst.SERVER_NAME: {"command": "/py"},
                },
                "someUnrelatedKey": {"keep": True},
            }
        ),
        encoding="utf-8",
    )

    uninst.remove_desktop_entry(config, dry_run=False)

    data = json.loads(config.read_text(encoding="utf-8"))
    assert data["mcpServers"] == {"other": {"command": "node", "args": ["x.js"]}}
    assert data["someUnrelatedKey"] == {"keep": True}


def test_desktop_removal_backs_up_first(tmp_path):
    config = tmp_path / "claude_desktop_config.json"
    original = {"mcpServers": {uninst.SERVER_NAME: {"command": "/py"}}}
    config.write_text(json.dumps(original), encoding="utf-8")

    uninst.remove_desktop_entry(config, dry_run=False)

    backup = config.with_suffix(config.suffix + ".bak")
    assert json.loads(backup.read_text(encoding="utf-8")) == original


def test_desktop_removal_leaves_an_unparseable_config_alone(tmp_path):
    config = tmp_path / "claude_desktop_config.json"
    config.write_text("{ this is not json", encoding="utf-8")

    lines = uninst.remove_desktop_entry(config, dry_run=False)

    assert config.read_text(encoding="utf-8") == "{ this is not json"
    assert any("SKIPPED" in line for line in lines)


def test_desktop_removal_is_quiet_when_there_is_nothing_to_remove(tmp_path):
    config = tmp_path / "claude_desktop_config.json"
    config.write_text(json.dumps({"mcpServers": {"other": {}}}), encoding="utf-8")

    lines = uninst.remove_desktop_entry(config, dry_run=False)

    assert any("Nothing to remove" in line for line in lines)
    assert not config.with_suffix(config.suffix + ".bak").exists()


def test_desktop_dry_run_writes_nothing(tmp_path):
    config = tmp_path / "claude_desktop_config.json"
    config.write_text(
        json.dumps({"mcpServers": {uninst.SERVER_NAME: {"command": "/py"}}}),
        encoding="utf-8",
    )
    before = config.read_text(encoding="utf-8")

    lines = uninst.remove_desktop_entry(config, dry_run=True)

    assert config.read_text(encoding="utf-8") == before
    assert any("Would remove" in line for line in lines)


###### Claude Code


def test_claude_code_missing_prints_the_command(monkeypatch):
    monkeypatch.setattr(uninst, "claude_code_available", lambda: False)
    lines = uninst.remove_claude_code(dry_run=False)
    assert any("claude mcp remove" in line for line in lines)


def test_removing_something_absent_is_not_a_failure(monkeypatch):
    """The desired end state was already true, which is not an error."""
    monkeypatch.setattr(uninst, "claude_code_available", lambda: True)
    monkeypatch.setattr(
        uninst.subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(
            argv, 1, stdout="", stderr="No MCP server found with name: fxhoudini"
        ),
    )

    lines = uninst.remove_claude_code(dry_run=False)

    assert any("Nothing to remove" in line for line in lines)
    assert not any("failed" in line.lower() for line in lines)


def test_a_genuine_failure_is_reported(monkeypatch):
    monkeypatch.setattr(uninst, "claude_code_available", lambda: True)
    monkeypatch.setattr(
        uninst.subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(
            argv, 1, stdout="", stderr="disk on fire"
        ),
    )

    lines = uninst.remove_claude_code(dry_run=False)

    assert any("disk on fire" in line for line in lines)
    assert any("failed" in line.lower() for line in lines)


def test_removal_argv_targets_the_user_scope(monkeypatch):
    """install registers at user scope, so uninstall has to look there."""
    assert uninst.claude_code_remove_argv() == [
        "claude",
        "mcp",
        "remove",
        uninst.SERVER_NAME,
        "-s",
        "user",
    ]


###### The README's flag table


_README = Path(__file__).resolve().parents[1] / "README.md"


def test_readme_flag_table_matches_the_cli():
    """Same drift check the installer's table gets, for the same reason."""
    text = _README.read_text(encoding="utf-8")
    table = re.search(r"\n\| Flag \| What it removes \|\n(.+?)\n\n", text, re.S)
    assert table, "the uninstall flag table has moved or been removed from README.md"
    documented = set(re.findall(r"`(--[a-z-]+)", table.group(1)))

    parser = uninst.build_parser()
    real = {
        option
        for action in parser._actions
        for option in action.option_strings
        if option.startswith("--") and option != "--help"
    }

    assert documented == real, (
        f"README and CLI disagree.\n"
        f"  documented but gone: {sorted(documented - real)}\n"
        f"  real but undocumented: {sorted(real - documented)}"
    )
