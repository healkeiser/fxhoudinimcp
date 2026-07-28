"""Tests for the module entry point.

This file exists because of one bug, and the bug is worth writing down. The
entry point used to match its subcommands by name and let everything else fall
through to ``mcp.run(transport="stdio")``. So on any version predating a given
subcommand, typing it started an MCP server instead:

    $ python -m fxhoudinimcp install
    WARNING:fxhoudinimcp.server:Cannot reach Houdini at startup: ...
    WARNING:fxhoudinimcp.server:Tools will attempt to connect on first use.

Nothing was installed, nothing said so, and the process sat there holding stdin.
It reads as a hung installer, and the two warnings send you looking at Houdini,
which is the one part that was never involved. A typo produced the same thing.

So the contract is now explicit in both directions, and both directions are
tested: no arguments starts the server, because every MCP client depends on
that, and anything unrecognised exits non-zero without importing the server.
"""

from __future__ import annotations

# Built-in
import sys

# Third-party
import pytest

# Internal
from fxhoudinimcp import __main__ as entry


def _run(monkeypatch, *argv: str) -> int:
    """Run the entry point with *argv* and return its exit code."""
    monkeypatch.setattr(sys, "argv", ["fxhoudinimcp", *argv])
    with pytest.raises(SystemExit) as exit_info:
        entry.main()
    code = exit_info.value.code
    return 0 if code is None else int(code)


###### The contract an MCP client relies on


def test_no_arguments_runs_the_server_on_stdio(monkeypatch):
    """The default, and the only behaviour a client ever asks for."""
    # Internal
    from fxhoudinimcp import server

    started: dict[str, str] = {}
    monkeypatch.setattr(
        server.mcp, "run", lambda transport: started.update(transport=transport)
    )
    monkeypatch.setattr(sys, "argv", ["fxhoudinimcp"])

    entry.main()

    assert started == {"transport": "stdio"}


def test_transport_is_still_overridable(monkeypatch):
    # Internal
    from fxhoudinimcp import server

    started: dict[str, str] = {}
    monkeypatch.setattr(
        server.mcp, "run", lambda transport: started.update(transport=transport)
    )
    monkeypatch.setattr(sys, "argv", ["fxhoudinimcp"])
    monkeypatch.setenv("MCP_TRANSPORT", "sse")

    entry.main()

    assert started == {"transport": "sse"}


###### Unrecognised arguments


def test_unknown_command_exits_nonzero(monkeypatch, capsys):
    assert _run(monkeypatch, "definitely-not-a-command") == 2
    assert "unknown command" in capsys.readouterr().err


def test_a_mistyped_subcommand_does_not_start_a_server(monkeypatch, capsys):
    """The exact shape of the original report, one keystroke away."""
    assert _run(monkeypatch, "instal") == 2
    assert "instal" in capsys.readouterr().err


def test_unknown_command_shows_what_is_accepted(monkeypatch, capsys):
    """Being told "no" is only half of it, since the whole failure was silence."""
    _run(monkeypatch, "nope")

    err = capsys.readouterr().err
    for command in entry.SUBCOMMANDS:
        assert command in err


def test_an_unknown_option_is_rejected_too(monkeypatch, capsys):
    """Options and subcommands fall through identically, so both are checked."""
    assert _run(monkeypatch, "--houdini-dir", "/somewhere") == 2
    assert "unknown command" in capsys.readouterr().err


###### Help and version


def test_help_exits_zero_and_lists_every_subcommand(monkeypatch, capsys):
    assert _run(monkeypatch, "--help") == 0

    out = capsys.readouterr().out
    for command in entry.SUBCOMMANDS:
        assert command in out


def test_help_is_available_as_dash_h(monkeypatch, capsys):
    assert _run(monkeypatch, "-h") == 0
    assert "usage:" in capsys.readouterr().out


def test_usage_describes_every_subcommand(monkeypatch, capsys):
    """The usage text is built from the table, so it cannot drift out of date."""
    _run(monkeypatch, "--help")

    out = capsys.readouterr().out
    for command, (_, summary) in entry.SUBCOMMANDS.items():
        assert command in out
        assert summary in out


def test_version_reports_the_installed_version(monkeypatch, capsys):
    """The question nobody could answer during the original report.

    An editable install carries the version it was created at, so the answer
    here is what distinguishes "the command is broken" from "this checkout
    predates the command".
    """
    # Internal
    from fxhoudinimcp import __version__

    assert _run(monkeypatch, "--version") == 0
    assert capsys.readouterr().out.strip() == __version__


def test_version_is_not_the_placeholder():
    """__init__ used to hardcode 0.1.0, which was wrong for every release."""
    # Internal
    from fxhoudinimcp import __version__

    assert __version__ != "0.1.0"


###### Dispatch


@pytest.mark.parametrize("command", sorted(entry.SUBCOMMANDS))
def test_subcommand_is_dispatched_with_its_own_arguments(
    monkeypatch, command: str
) -> None:
    """Everything after the subcommand belongs to the subcommand, untouched."""
    seen: dict[str, list[str]] = {}
    _, summary = entry.SUBCOMMANDS[command]
    monkeypatch.setitem(
        entry.SUBCOMMANDS,
        command,
        (lambda argv: seen.update(argv=argv) or 0, summary),
    )

    assert _run(monkeypatch, command, "--dry-run", "--client", "none") == 0
    assert seen["argv"] == ["--dry-run", "--client", "none"]


def test_subcommand_exit_code_is_propagated(monkeypatch):
    """`install` returns 1 when it refuses to guess, and that must reach the shell."""
    _, summary = entry.SUBCOMMANDS["install"]
    monkeypatch.setitem(entry.SUBCOMMANDS, "install", (lambda argv: 1, summary))

    assert _run(monkeypatch, "install") == 1
