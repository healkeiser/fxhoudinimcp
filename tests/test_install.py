"""Tests for the one-shot installer.

This command writes to two places that matter to someone else: a Houdini
packages directory, and an MCP client's config. Both have a failure mode worse
than not running at all, so the tests concentrate on what it must never do --
guess an ambiguous Houdini directory, or damage a config full of other people's
servers.
"""

from __future__ import annotations

# Built-in
import json
import subprocess
import sys
from pathlib import Path

# Third-party
import pytest

# Internal
from fxhoudinimcp import install as inst


def _entry(config: dict) -> dict:
    """Our server's entry out of a merged config."""
    return config["mcpServers"][inst.SERVER_NAME]


@pytest.fixture
def plugin_dir(tmp_path, monkeypatch):
    """A plugin directory that exists, so main() gets past its first guard."""
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    monkeypatch.setattr(inst, "plugin_path", lambda: plugin)
    return plugin


@pytest.fixture
def isolated(monkeypatch):
    """Keep the real machine out of the test: no Houdini dirs, no clients."""
    monkeypatch.setattr(inst, "candidate_package_dirs", lambda: [])
    monkeypatch.setattr(inst, "existing_packages", lambda exclude=None: [])
    monkeypatch.setattr(inst, "claude_code_available", lambda: False)
    monkeypatch.setattr(inst, "desktop_config_path", lambda: None)


###### The command an MCP client is told to run


def test_client_command_uses_absolute_interpreter():
    """A bare "python" is the documented cause of "disconnected" in Desktop.

    Clients start their servers without the user's shell environment, so the
    interpreter must be spelled out rather than resolved against PATH.
    """
    command = inst.client_command()
    assert command[0] == sys.executable
    assert Path(command[0]).is_absolute()
    assert command[1:] == ["-m", "fxhoudinimcp"]


def test_claude_code_argv_separates_options_from_command():
    """Everything after `--` is passed to the server untouched.

    Without the separator, Claude Code would read the interpreter path as one of
    its own arguments.
    """
    argv = inst.claude_code_add_argv()
    assert argv[:3] == ["claude", "mcp", "add"]
    separator = argv.index("--")
    assert argv[separator - 1] == inst.SERVER_NAME
    assert argv[separator + 1 :] == inst.client_command()


###### Choosing the Houdini packages directory


def test_explicit_dir_wins(monkeypatch):
    monkeypatch.setattr(inst, "candidate_package_dirs", lambda: [Path("/ignored")])
    chosen, _, _ = inst.resolve_houdini_dir("~/somewhere")
    assert chosen == Path("~/somewhere").expanduser()


def test_single_candidate_is_used(monkeypatch, tmp_path):
    """One candidate means there is nothing to choose, so do not make the user."""
    monkeypatch.setattr(inst, "candidate_package_dirs", lambda: [tmp_path])
    chosen, candidates, _ = inst.resolve_houdini_dir(None)
    assert chosen == tmp_path
    assert candidates == [tmp_path]


def test_several_candidates_refuse_to_guess(monkeypatch, tmp_path):
    """The OneDrive redirection case. Guessing recreates a silent no-op.

    A desktop-launched Houdini and a shell-launched one can resolve different
    preference directories on Windows, and Houdini reports nothing when it skips
    a package file, so the wrong guess is invisible.
    """
    first, second = tmp_path / "a", tmp_path / "b"
    monkeypatch.setattr(inst, "candidate_package_dirs", lambda: [first, second])
    chosen, candidates, reason = inst.resolve_houdini_dir(None)
    assert chosen is None
    assert candidates == [first, second]
    assert "2 candidates" in reason


def test_ambiguous_dir_exits_nonzero_and_writes_nothing(
    plugin_dir, tmp_path, monkeypatch, capsys
):
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    monkeypatch.setattr(inst, "candidate_package_dirs", lambda: [first, second])
    monkeypatch.setattr(inst, "existing_packages", lambda exclude=None: [])

    assert inst.main([]) == 1
    assert not list(first.iterdir())
    assert not list(second.iterdir())
    assert "Cannot choose for you" in capsys.readouterr().out


def test_writes_package_into_chosen_dir(plugin_dir, isolated, tmp_path, capsys):
    packages = tmp_path / "packages"
    packages.mkdir()

    assert inst.main(["--houdini-dir", str(packages), "--client", "none"]) == 0

    written = packages / "fxhoudinimcp.json"
    data = json.loads(written.read_text(encoding="utf-8"))
    assert data["env"][0]["FXHOUDINIMCP"] == plugin_dir.as_posix()
    assert "Restart Houdini" in capsys.readouterr().out


def test_dry_run_changes_nothing(plugin_dir, isolated, tmp_path, capsys):
    packages = tmp_path / "packages"
    packages.mkdir()

    assert inst.main(["--houdini-dir", str(packages), "--dry-run"]) == 0

    assert not list(packages.iterdir())
    assert "Nothing was changed" in capsys.readouterr().out


def test_missing_plugin_is_reported(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(inst, "plugin_path", lambda: tmp_path / "absent")
    assert inst.main([]) == 1
    assert "plugin directory is missing" in capsys.readouterr().err


###### Claude Desktop config


def test_desktop_merge_preserves_other_servers():
    """Someone's config is likely to hold servers that took effort to set up."""
    existing = {
        "mcpServers": {"other": {"command": "node", "args": ["x.js"]}},
        "someUnrelatedKey": {"keep": True},
    }
    merged = inst._merge_desktop_config(existing, ["/py", "-m", "fxhoudinimcp"])

    assert merged["mcpServers"]["other"] == {"command": "node", "args": ["x.js"]}
    assert merged["someUnrelatedKey"] == {"keep": True}
    assert merged["mcpServers"][inst.SERVER_NAME] == {
        "command": "/py",
        "args": ["-m", "fxhoudinimcp"],
    }


def test_desktop_merge_preserves_env_inside_our_own_entry():
    """The bug a real config caught: rewriting our entry ate the user's env.

    A live Claude Desktop config had an ``env`` block with HOUDINI_HOST and
    HOUDINI_PORT. Replacing the whole entry deleted those while reporting
    success, which is worse than failing.
    """
    existing = {
        "mcpServers": {
            inst.SERVER_NAME: {
                "command": "python",
                "args": ["-m", "fxhoudinimcp"],
                "env": {"HOUDINI_HOST": "localhost", "HOUDINI_PORT": "8100"},
            }
        }
    }
    merged = _entry(inst._merge_desktop_config(existing, ["/abs/py", "-m", "x"]))

    assert merged["env"] == {"HOUDINI_HOST": "localhost", "HOUDINI_PORT": "8100"}
    assert merged["command"] == "/abs/py"
    assert merged["args"] == ["-m", "x"]


def test_desktop_install_keeps_env_on_disk(tmp_path):
    config = tmp_path / "claude_desktop_config.json"
    config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    inst.SERVER_NAME: {
                        "command": "python",
                        "args": ["-m", "fxhoudinimcp"],
                        "env": {"HOUDINI_PORT": "8100"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    inst.install_desktop(config, ["/abs/py", "-m", "fxhoudinimcp"], dry_run=False)

    entry = json.loads(config.read_text(encoding="utf-8"))["mcpServers"][
        inst.SERVER_NAME
    ]
    assert entry["env"] == {"HOUDINI_PORT": "8100"}
    assert entry["command"] == "/abs/py"


def test_pinned_port_is_reported():
    """Pinning HOUDINI_PORT silently disables the multi-session port scan."""
    warning = inst.pinned_port_warning(
        {"command": "python", "env": {"HOUDINI_PORT": "8100"}}
    )
    assert warning
    assert any("8100" in line for line in warning)
    assert any("second Houdini" in line for line in warning)


def test_no_pinned_port_no_warning():
    assert inst.pinned_port_warning({"command": "python"}) == []
    assert inst.pinned_port_warning(None) == []


def test_desktop_merge_does_not_mutate_input():
    existing = {"mcpServers": {"other": {}}}
    inst._merge_desktop_config(existing, ["/py", "-m", "fxhoudinimcp"])
    assert existing == {"mcpServers": {"other": {}}}


def test_desktop_install_backs_up_before_writing(tmp_path):
    config = tmp_path / "claude_desktop_config.json"
    original = {"mcpServers": {"other": {"command": "node"}}}
    config.write_text(json.dumps(original), encoding="utf-8")

    inst.install_desktop(config, ["/py", "-m", "fxhoudinimcp"], dry_run=False)

    backup = config.with_suffix(config.suffix + ".bak")
    assert json.loads(backup.read_text(encoding="utf-8")) == original
    written = json.loads(config.read_text(encoding="utf-8"))
    assert "other" in written["mcpServers"]
    assert inst.SERVER_NAME in written["mcpServers"]


def test_desktop_install_creates_missing_config(tmp_path):
    config = tmp_path / "nested" / "claude_desktop_config.json"
    inst.install_desktop(config, ["/py", "-m", "fxhoudinimcp"], dry_run=False)
    data = json.loads(config.read_text(encoding="utf-8"))
    assert data["mcpServers"][inst.SERVER_NAME]["command"] == "/py"


def test_desktop_install_leaves_unparseable_config_alone(tmp_path):
    """Better to refuse than to overwrite a file we cannot understand."""
    config = tmp_path / "claude_desktop_config.json"
    config.write_text("{ this is not json", encoding="utf-8")

    lines = inst.install_desktop(config, ["/py", "-m", "fxhoudinimcp"], dry_run=False)

    assert config.read_text(encoding="utf-8") == "{ this is not json"
    assert not config.with_suffix(config.suffix + ".bak").exists()
    assert any("SKIPPED" in line for line in lines)


def test_desktop_install_is_idempotent(tmp_path):
    config = tmp_path / "claude_desktop_config.json"
    command = ["/py", "-m", "fxhoudinimcp"]
    inst.install_desktop(config, command, dry_run=False)
    first = config.read_text(encoding="utf-8")

    lines = inst.install_desktop(config, command, dry_run=False)

    assert config.read_text(encoding="utf-8") == first
    assert any("already points at this install" in line for line in lines)


def test_desktop_dry_run_writes_nothing(tmp_path):
    config = tmp_path / "claude_desktop_config.json"
    lines = inst.install_desktop(config, ["/py", "-m", "fxhoudinimcp"], dry_run=True)
    assert not config.exists()
    assert any("Would update" in line for line in lines)


###### Claude Code registration


def test_claude_code_missing_prints_the_command(monkeypatch):
    monkeypatch.setattr(inst, "claude_code_available", lambda: False)
    lines = inst.install_claude_code(dry_run=False)
    assert any("claude mcp add" in line for line in lines)


def test_claude_code_failure_is_explained(monkeypatch):
    """A duplicate name is the likely failure, so name the way out of it."""
    monkeypatch.setattr(inst, "claude_code_available", lambda: True)

    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(
            argv, 1, stdout="", stderr="server already exists"
        )

    monkeypatch.setattr(inst.subprocess, "run", fake_run)
    lines = inst.install_claude_code(dry_run=False)
    assert any("already exists" in line for line in lines)
    assert any(f"claude mcp remove {inst.SERVER_NAME}" in line for line in lines)


def test_claude_code_dry_run_does_not_shell_out(monkeypatch):
    monkeypatch.setattr(inst, "claude_code_available", lambda: True)

    def explode(*args, **kwargs):
        raise AssertionError("--dry-run must not run the CLI")

    monkeypatch.setattr(inst.subprocess, "run", explode)
    lines = inst.install_claude_code(dry_run=True)
    assert any("Would run" in line for line in lines)


def test_claude_code_success(monkeypatch):
    monkeypatch.setattr(inst, "claude_code_available", lambda: True)
    monkeypatch.setattr(
        inst.subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout="ok", stderr=""),
    )
    lines = inst.install_claude_code(dry_run=False)
    assert any("Registered" in line for line in lines)
