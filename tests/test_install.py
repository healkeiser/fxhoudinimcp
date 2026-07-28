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
import re
import subprocess
import sys
from pathlib import Path

# Third-party
import pytest

# Internal
from fxhoudinimcp import houdini_package as hp
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
    chosen, _ = inst.resolve_houdini_dirs("~/somewhere")
    assert chosen == [Path("~/somewhere").expanduser()]


def test_single_candidate_is_used(monkeypatch, tmp_path):
    monkeypatch.setattr(inst, "candidate_package_dirs", lambda: [tmp_path])
    chosen, _ = inst.resolve_houdini_dirs(None)
    assert chosen == [tmp_path]


def test_several_candidates_all_get_written(monkeypatch, tmp_path):
    """The OneDrive case stops being a question once the answer is "both".

    A desktop-launched Houdini and a shell-launched one can resolve different
    preference directories on Windows, and Houdini reports nothing when it skips
    a package file, so a wrong single choice is invisible. Writing the same file
    into every candidate cannot be wrong: they are byte-identical and point at
    the same plugin, so whichever one Houdini reads is correct.
    """
    first, second = tmp_path / "a", tmp_path / "b"
    monkeypatch.setattr(inst, "candidate_package_dirs", lambda: [first, second])

    chosen, reason = inst.resolve_houdini_dirs(None)

    assert chosen == [first, second]
    assert "every candidate" in reason


def test_several_candidates_install_into_all_of_them(
    plugin_dir, tmp_path, monkeypatch, capsys
):
    """End to end: no prompt, no refusal, both files written."""
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    monkeypatch.setattr(inst, "candidate_package_dirs", lambda: [first, second])
    monkeypatch.setattr(inst, "existing_packages", lambda exclude=None: [])

    assert inst.main(["--client", "none"]) == 0

    assert (first / "fxhoudinimcp.json").is_file()
    assert (second / "fxhoudinimcp.json").is_file()
    assert "Cannot choose for you" not in capsys.readouterr().out


def test_installing_never_reads_stdin(plugin_dir, tmp_path, monkeypatch):
    """The whole command must work with no terminal attached.

    It is run from Houdini's MCP menu, from setup scripts and from CI, and an
    earlier version that stopped to ask made all three impossible. Reaching
    input() at all is the failure.
    """
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    monkeypatch.setattr(inst, "candidate_package_dirs", lambda: [first, second])
    monkeypatch.setattr(inst, "existing_packages", lambda exclude=None: [])
    monkeypatch.setattr(inst, "claude_code_available", lambda: False)
    monkeypatch.setattr(inst, "desktop_config_path", lambda: None)

    def explode(prompt: str = "") -> str:
        raise AssertionError("install must never block on input()")

    monkeypatch.setattr("builtins.input", explode)

    assert inst.main([]) == 0


def test_no_candidates_is_still_refused(plugin_dir, isolated, capsys):
    """The one thing left that genuinely cannot be worked out.

    Inventing a directory would put the package file somewhere Houdini never
    reads, which is the silent no-op the command exists to prevent.
    """
    assert inst.main([]) == 1
    assert "no houdini packages directory exists yet" in capsys.readouterr().out.lower()


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


def test_client_only_skips_the_houdini_half(plugin_dir, isolated, tmp_path, capsys):
    """What the MCP menu recommends, so it must not need a packages directory.

    The menu cannot know which of several candidates is the right one, and a
    command that stops to ask would be useless coming from a dialog.
    """
    packages = tmp_path / "packages"
    packages.mkdir()

    assert inst.main(["--client-only"]) == 0

    assert not list(packages.iterdir())
    out = capsys.readouterr().out
    assert "Skipped (--client-only)" in out
    assert "Restart your MCP client" in out


def test_client_only_survives_ambiguous_candidates(
    plugin_dir, monkeypatch, tmp_path, capsys
):
    """Several candidates block a normal install but must not block this one."""
    monkeypatch.setattr(
        inst, "candidate_package_dirs", lambda: [tmp_path / "a", tmp_path / "b"]
    )
    monkeypatch.setattr(inst, "claude_code_available", lambda: False)
    monkeypatch.setattr(inst, "desktop_config_path", lambda: None)

    assert inst.main(["--client-only", "--client", "none"]) == 0
    assert "Cannot choose for you" not in capsys.readouterr().out


def test_client_only_works_without_a_plugin_directory(monkeypatch, tmp_path, capsys):
    """Registering a client says nothing about the plugin being present."""
    monkeypatch.setattr(inst, "plugin_path", lambda: tmp_path / "absent")
    monkeypatch.setattr(inst, "claude_code_available", lambda: False)
    monkeypatch.setattr(inst, "desktop_config_path", lambda: None)

    assert inst.main(["--client-only", "--client", "none"]) == 0


def test_client_only_rejects_a_contradictory_houdini_dir(plugin_dir, tmp_path):
    with pytest.raises(SystemExit):
        inst.main(["--client-only", "--houdini-dir", str(tmp_path)])


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


def _fails_with(message: str):
    """A `claude mcp add` that fails with *message*."""

    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr=message)

    return fake_run


def test_genuine_failure_is_reported(monkeypatch):
    monkeypatch.setattr(inst, "claude_code_available", lambda: True)
    monkeypatch.setattr(inst.subprocess, "run", _fails_with("disk on fire"))

    lines = inst.install_claude_code(dry_run=False)

    assert any("disk on fire" in line for line in lines)
    assert any("failed" in line.lower() for line in lines)


def test_current_command_parses_the_human_output(monkeypatch):
    """`claude mcp get` prints for humans, so only the Command: line is read."""
    output = (
        "fxhoudini:\n"
        "  Scope: User config\n"
        "  Status: Connected\n"
        "  Command: C:\\Program Files\\Python311\\python.exe\n"
        "  Args: -m fxhoudinimcp\n"
    )
    monkeypatch.setattr(
        inst.subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout=output),
    )
    assert (
        inst.claude_code_current_command() == "C:\\Program Files\\Python311\\python.exe"
    )


def test_current_command_none_when_not_registered(monkeypatch):
    monkeypatch.setattr(
        inst.subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 1, stdout=""),
    )
    assert inst.claude_code_current_command() is None


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


###### Repointing a client entry instead of reporting it


@pytest.fixture
def two_candidates(monkeypatch, tmp_path):
    """Two real packages directories, the shape of a 21.0 + 22.0 machine."""
    first, second = tmp_path / "houdini21.0", tmp_path / "houdini22.0"
    first.mkdir()
    second.mkdir()
    monkeypatch.setattr(inst, "candidate_package_dirs", lambda: [first, second])
    monkeypatch.setattr(inst, "existing_packages", lambda exclude=None: [])
    monkeypatch.setattr(inst, "claude_code_available", lambda: False)
    monkeypatch.setattr(inst, "desktop_config_path", lambda: None)
    return first, second


def _runs(monkeypatch, *results: int) -> list[list[str]]:
    """Record every subprocess argv, returning *results* in order."""
    calls: list[list[str]] = []
    codes = list(results)

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        code = codes.pop(0) if codes else 0
        stderr = "MCP server fxhoudini already exists" if code == 1 else ""
        return subprocess.CompletedProcess(argv, code, stdout="", stderr=stderr)

    monkeypatch.setattr(inst.subprocess, "run", fake_run)
    return calls


def test_a_stale_entry_is_repointed_not_reported(monkeypatch, capsys):
    """The defect this replaces: it printed two commands and made you run them.

    `claude mcp add` has no --force, so an existing entry is an error rather
    than an update. The installer knows the old value, knows the new one, and
    was told to install. Handing back homework is not finishing the job.
    """
    monkeypatch.setattr(inst, "claude_code_available", lambda: True)
    monkeypatch.setattr(inst, "claude_code_current_command", lambda: "python")
    calls = _runs(monkeypatch, 1, 0, 0)  # add fails, remove works, add works

    lines = inst.install_claude_code(dry_run=False)

    assert calls[0][:3] == ["claude", "mcp", "add"]
    assert calls[1][:3] == ["claude", "mcp", "remove"]
    assert calls[2][:3] == ["claude", "mcp", "add"]
    joined = " ".join(lines)
    assert "Repointed" in joined
    assert "python" in joined  # the old value is named, not silently dropped
    assert inst.client_command()[0] in joined


def test_an_already_correct_entry_is_left_alone(monkeypatch):
    """Nothing to repoint, and nothing removed: no churn on a good config."""
    monkeypatch.setattr(inst, "claude_code_available", lambda: True)
    monkeypatch.setattr(
        inst, "claude_code_current_command", lambda: inst.client_command()[0]
    )
    calls = _runs(monkeypatch, 1)

    lines = inst.install_claude_code(dry_run=False)

    assert [c[:3] for c in calls] == [["claude", "mcp", "add"]]
    assert any("Nothing to do" in line for line in lines)


def test_a_failed_removal_does_not_claim_success(monkeypatch):
    monkeypatch.setattr(inst, "claude_code_available", lambda: True)
    monkeypatch.setattr(inst, "claude_code_current_command", lambda: "python")

    def fake_run(argv, **kwargs):
        # The add has to fail the way Claude Code actually fails, or the
        # repoint branch is never reached and the test proves nothing.
        if "remove" in argv:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="denied")
        return subprocess.CompletedProcess(
            argv, 1, stdout="", stderr="MCP server fxhoudini already exists"
        )

    monkeypatch.setattr(inst.subprocess, "run", fake_run)

    lines = inst.install_claude_code(dry_run=False)

    joined = " ".join(lines)
    assert "could not be replaced" in joined
    assert "Repointed" not in joined


def test_a_failed_re_add_says_the_entry_is_gone(monkeypatch):
    """Worst case, and the one that must not be silent: removed, not re-added."""
    monkeypatch.setattr(inst, "claude_code_available", lambda: True)
    monkeypatch.setattr(inst, "claude_code_current_command", lambda: "python")
    _runs(monkeypatch, 1, 0, 1)  # add fails, remove works, re-add fails

    lines = inst.install_claude_code(dry_run=False)

    joined = " ".join(lines)
    assert "Removed the old" in joined
    assert "Finish it with" in joined


def test_no_message_recommends_the_bare_console_script(monkeypatch):
    """The README says use the module form; our errors used to contradict it."""
    monkeypatch.setattr(inst, "claude_code_available", lambda: False)

    for line in inst.install_claude_code(dry_run=False):
        assert not line.strip().startswith("fxhoudinimcp ")


###### Saying which config was written


_MODIFIED = "Added stdio MCP server fxhoudini\nFile modified: C:\\Users\\me\\.claude.json\n"


def test_success_names_the_config_file(monkeypatch):
    """"Registered with Claude Code (user scope)" is not a checkable claim.

    CLAUDE_CONFIG_DIR decides which profile is user scope, and a machine can
    have several. A correct, connected registration in one was invisible to
    every `claude mcp get` run from the other, and read as a failed install.
    The CLI already prints the path; swallowing it was the whole problem.
    """
    monkeypatch.setattr(inst, "claude_code_available", lambda: True)
    monkeypatch.setattr(
        inst.subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout=_MODIFIED),
    )

    lines = inst.install_claude_code(dry_run=False)

    assert any("C:\\Users\\me\\.claude.json" in line for line in lines)


def test_a_windows_drive_letter_survives_the_parse():
    """The path has a colon in it, so splitting on every colon would truncate."""
    result = subprocess.CompletedProcess([], 0, stdout=_MODIFIED)
    assert inst.config_file_note(result) == ["      in C:\\Users\\me\\.claude.json"]


def test_repointing_names_the_config_file(monkeypatch):
    monkeypatch.setattr(inst, "claude_code_available", lambda: True)
    monkeypatch.setattr(inst, "claude_code_current_command", lambda: "python")

    adds: list[int] = []

    def fake_run(argv, **kwargs):
        if "remove" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout="")
        adds.append(1)
        if len(adds) > 1:  # the re-add, after the removal
            return subprocess.CompletedProcess(argv, 0, stdout=_MODIFIED)
        return subprocess.CompletedProcess(
            argv, 1, stderr="MCP server fxhoudini already exists"
        )

    monkeypatch.setattr(inst.subprocess, "run", fake_run)

    lines = inst.install_claude_code(dry_run=False)

    assert any("Repointed" in line for line in lines)
    assert any("C:\\Users\\me\\.claude.json" in line for line in lines)


def test_falls_back_to_naming_the_profile(monkeypatch):
    """An older CLI may not print the path. The profile still beats silence."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", r"C:\Users\me\.claude-work")
    result = subprocess.CompletedProcess([], 0, stdout="Added stdio MCP server\n")

    assert inst.config_file_note(result) == [
        r"      in the Claude Code profile at C:\Users\me\.claude-work"
    ]


def test_says_nothing_when_there_is_nothing_to_say(monkeypatch):
    """One profile and a quiet CLI: do not invent a path."""
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    result = subprocess.CompletedProcess([], 0, stdout="Added stdio MCP server\n")

    assert inst.config_file_note(result) == []


def test_every_parser_spells_itself_the_module_way():
    # Internal
    from fxhoudinimcp import houdini_package as hp_mod
    from fxhoudinimcp import uninstall as uninst

    for parser in (inst.build_parser(), uninst.build_parser()):
        assert parser.prog.startswith("python -m fxhoudinimcp")
    assert hp_mod.CLI == "python -m fxhoudinimcp"


###### A dry run has to be honest about what would fail


def test_dry_run_rejects_a_directory_that_does_not_exist(
    plugin_dir, isolated, tmp_path, capsys
):
    """A dry run that reports success for a write that would fail is worthless.

    It was reporting "Would write ... into C:\\nowhere" and exiting 0, while the
    real run refused. The whole point of --dry-run is to be believed.
    """
    missing = tmp_path / "not-created"

    assert inst.main(["--houdini-dir", str(missing), "--dry-run"]) == 1
    assert "Not a directory" in capsys.readouterr().err


def test_nothing_is_written_when_one_destination_is_missing(
    plugin_dir, monkeypatch, tmp_path
):
    """Every destination is checked before the first one is written."""
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()  # second is never created
    monkeypatch.setattr(inst, "candidate_package_dirs", lambda: [first, second])
    monkeypatch.setattr(inst, "existing_packages", lambda exclude=None: [])
    monkeypatch.setattr(inst, "claude_code_available", lambda: False)
    monkeypatch.setattr(inst, "desktop_config_path", lambda: None)
    assert inst.main(["--client", "none"]) == 1
    assert not list(first.iterdir())


def test_the_files_just_written_are_not_reported_as_leftovers(
    plugin_dir, two_candidates, monkeypatch, capsys
):
    """Writing both and then warning about both would be self-contradictory.

    Runs the real detector rather than the stub, because the whole question is
    whether it recognises the files this run has just created.
    """
    first, second = two_candidates
    monkeypatch.setattr(inst, "existing_packages", hp.existing_packages)
    monkeypatch.setattr(hp, "candidate_package_dirs", lambda: [first, second])
    assert inst.main(["--client", "none"]) == 0
    assert "WARNING" not in capsys.readouterr().out


###### The README's flag table


_README = Path(__file__).resolve().parents[1] / "README.md"


def _documented_flags() -> set[str]:
    """Long options named in the README's install flag table."""
    text = _README.read_text(encoding="utf-8")
    table = re.search(r"\n\| Flag \| What it does \|\n(.+?)\n\n", text, re.S)
    assert table, "the install flag table has moved or been removed from README.md"
    return set(re.findall(r"`(--[a-z-]+)", table.group(1)))


def test_readme_flag_table_matches_the_cli():
    """The table is the first thing anyone reads, so drift there is a lie.

    Checked in both directions: a flag renamed in code and not in the README, and
    a flag added to the code that the README never mentions.
    """
    parser = inst.build_parser()
    real = {
        option
        for action in parser._actions
        for option in action.option_strings
        if option.startswith("--") and option != "--help"
    }
    documented = _documented_flags()

    assert documented == real, (
        f"README and CLI disagree.\n"
        f"  documented but gone: {sorted(documented - real)}\n"
        f"  real but undocumented: {sorted(real - documented)}"
    )


def test_readme_recommends_the_self_correcting_install_form():
    """`python -m fxhoudinimcp install` registers the interpreter that runs it."""
    text = _README.read_text(encoding="utf-8")
    assert "python -m fxhoudinimcp install" in text


def test_readme_never_shows_a_bare_python_client_entry():
    """A bare `python` in a client config is the documented "disconnected" bug.

    The README used to show exactly that and then explain the fix in a tip below,
    which meant copying the broken form was the path of least resistance.
    """
    text = _README.read_text(encoding="utf-8")
    assert '"command": "python"' not in text
    assert "fxhoudini -- python -m fxhoudinimcp" not in text
