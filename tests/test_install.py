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


def test_already_registered_and_correct_is_not_reported_as_failure(monkeypatch):
    """`claude mcp add` has no --force, so re-running is an error.

    That is not a problem when the entry already points at this Python, and
    calling it a failure sends people chasing a non-issue.
    """
    monkeypatch.setattr(inst, "claude_code_available", lambda: True)
    monkeypatch.setattr(
        inst.subprocess, "run", _fails_with("MCP server fxhoudini already exists")
    )
    monkeypatch.setattr(
        inst, "claude_code_current_command", lambda: inst.client_command()[0]
    )

    lines = inst.install_claude_code(dry_run=False)

    assert any("Nothing to do" in line for line in lines)
    assert not any("failed" in line.lower() for line in lines)


def test_already_registered_elsewhere_shows_both_paths(monkeypatch):
    """Repointing needs remove-then-add, and the user needs to see why."""
    monkeypatch.setattr(inst, "claude_code_available", lambda: True)
    monkeypatch.setattr(
        inst.subprocess, "run", _fails_with("MCP server fxhoudini already exists")
    )
    monkeypatch.setattr(inst, "claude_code_current_command", lambda: "/other/python")

    lines = inst.install_claude_code(dry_run=False)
    joined = "\n".join(lines)

    assert "/other/python" in joined
    assert inst.client_command()[0] in joined
    assert f"claude mcp remove {inst.SERVER_NAME}" in joined


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


###### Choosing between several candidates, at the prompt


def _answers(monkeypatch, *replies: str) -> None:
    """Feed *replies* to input() in order, then behave like a closed stdin."""
    pending = list(replies)

    def fake_input(prompt: str = "") -> str:
        if not pending:
            raise EOFError
        return pending.pop(0)

    monkeypatch.setattr("builtins.input", fake_input)


@pytest.fixture
def interactive(monkeypatch):
    """A terminal on the other end, so the installer is allowed to ask."""
    monkeypatch.setattr(inst, "stdin_is_interactive", lambda: True)


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


def test_prompt_lists_every_candidate(monkeypatch, tmp_path, capsys):
    first, second = tmp_path / "a", tmp_path / "b"
    _answers(monkeypatch, "1")

    assert inst.prompt_for_package_dirs([first, second]) == [first]

    out = capsys.readouterr().out
    assert str(first) in out
    assert str(second) in out


def test_prompt_returns_the_numbered_choice(monkeypatch, tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    _answers(monkeypatch, "2")
    assert inst.prompt_for_package_dirs([first, second]) == [second]


def test_prompt_can_take_all_of_them(monkeypatch, tmp_path):
    """Several candidates is usually several Houdini versions, not ambiguity.

    Someone running 21.0 and 22.0 side by side wants the menu in both, and
    making them run the command twice invites doing it once and forgetting.
    """
    first, second = tmp_path / "a", tmp_path / "b"
    _answers(monkeypatch, "a")
    assert inst.prompt_for_package_dirs([first, second]) == [first, second]


def test_prompt_can_be_cancelled(monkeypatch, tmp_path):
    _answers(monkeypatch, "q")
    assert inst.prompt_for_package_dirs([tmp_path / "a", tmp_path / "b"]) == []


def test_prompt_treats_end_of_input_as_cancel(monkeypatch, tmp_path):
    """A piped stdin that runs dry must not loop forever."""
    _answers(monkeypatch)
    assert inst.prompt_for_package_dirs([tmp_path / "a", tmp_path / "b"]) == []


def test_prompt_re_asks_rather_than_guessing(monkeypatch, tmp_path, capsys):
    """Out of range, not a number, and empty are all re-asked, never rounded."""
    first, second = tmp_path / "a", tmp_path / "b"
    _answers(monkeypatch, "3", "yes", "", "1")

    assert inst.prompt_for_package_dirs([first, second]) == [first]

    out = capsys.readouterr().out
    assert out.count("Not one of the choices") == 3
    assert "nothing was entered" in out  # a bare Return is rejected, not defaulted


def test_ambiguous_dir_prompts_and_writes_only_the_choice(
    plugin_dir, interactive, two_candidates, monkeypatch
):
    first, second = two_candidates
    _answers(monkeypatch, "2")

    assert inst.main(["--client", "none"]) == 0

    assert not list(first.iterdir())
    assert (second / "fxhoudinimcp.json").is_file()


def test_choosing_all_writes_into_every_candidate(
    plugin_dir, interactive, two_candidates, monkeypatch
):
    first, second = two_candidates
    _answers(monkeypatch, "a")

    assert inst.main(["--client", "none"]) == 0

    assert (first / "fxhoudinimcp.json").is_file()
    assert (second / "fxhoudinimcp.json").is_file()


def test_cancelling_writes_nothing_and_exits_nonzero(
    plugin_dir, interactive, two_candidates, monkeypatch, capsys
):
    first, second = two_candidates
    _answers(monkeypatch, "q")

    assert inst.main(["--client", "none"]) == 1

    assert not list(first.iterdir())
    assert not list(second.iterdir())
    assert "Cancelled" in capsys.readouterr().out


def test_a_non_interactive_run_never_stops_to_ask(
    plugin_dir, two_candidates, monkeypatch, capsys
):
    """The MCP menu and any script run this with no terminal attached.

    input() there either raises immediately or blocks forever, and a Houdini
    menu item that hangs on a prompt nobody can see is worse than one that
    prints instructions. So the old list-and-refuse behaviour is kept, and
    reaching input() at all is treated as the failure it would be.
    """
    monkeypatch.setattr(inst, "stdin_is_interactive", lambda: False)

    def explode(prompt: str = "") -> str:
        raise AssertionError("a non-interactive install must not call input()")

    monkeypatch.setattr("builtins.input", explode)
    first, second = two_candidates

    assert inst.main(["--client", "none"]) == 1

    assert not list(first.iterdir())
    assert not list(second.iterdir())
    assert "Cannot choose for you" in capsys.readouterr().out


def test_an_explicit_dir_never_prompts(plugin_dir, interactive, tmp_path, monkeypatch):
    """--houdini-dir already answered the question."""
    packages = tmp_path / "packages"
    packages.mkdir()
    monkeypatch.setattr(inst, "existing_packages", lambda exclude=None: [])
    monkeypatch.setattr(inst, "claude_code_available", lambda: False)
    monkeypatch.setattr(inst, "desktop_config_path", lambda: None)

    def explode(prompt: str = "") -> str:
        raise AssertionError("--houdini-dir must not be second-guessed")

    monkeypatch.setattr("builtins.input", explode)

    assert inst.main(["--houdini-dir", str(packages), "--client", "none"]) == 0
    assert (packages / "fxhoudinimcp.json").is_file()


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
    plugin_dir, interactive, monkeypatch, tmp_path
):
    """Every destination is checked before the first one is written."""
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()  # second is never created
    monkeypatch.setattr(inst, "candidate_package_dirs", lambda: [first, second])
    monkeypatch.setattr(inst, "existing_packages", lambda exclude=None: [])
    monkeypatch.setattr(inst, "claude_code_available", lambda: False)
    monkeypatch.setattr(inst, "desktop_config_path", lambda: None)
    _answers(monkeypatch, "a")

    assert inst.main(["--client", "none"]) == 1
    assert not list(first.iterdir())


def test_the_files_just_written_are_not_reported_as_leftovers(
    plugin_dir, interactive, two_candidates, monkeypatch, capsys
):
    """Writing both and then warning about both would be self-contradictory.

    Runs the real detector rather than the stub, because the whole question is
    whether it recognises the files this run has just created.
    """
    first, second = two_candidates
    monkeypatch.setattr(inst, "existing_packages", hp.existing_packages)
    monkeypatch.setattr(hp, "candidate_package_dirs", lambda: [first, second])
    _answers(monkeypatch, "a")

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
