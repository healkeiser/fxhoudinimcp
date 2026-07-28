"""One command that wires up both halves.

Installing used to be four steps across two worlds: pip install, work out which
Houdini packages directory is the real one, write a JSON file there, then hand
your MCP client a command line whose Python path you had to discover yourself.
Every one of those steps fails quietly. Houdini skips a package file it cannot
resolve without saying so, and Claude Desktop does not inherit your PATH, so a
bare ``python`` in its config reads as "disconnected" with no explanation.

    python -m fxhoudinimcp install                    # do both halves
    python -m fxhoudinimcp install --dry-run          # say what it would do
    python -m fxhoudinimcp install --houdini-dir DIR  # just this one directory
    python -m fxhoudinimcp install --client none      # wire the client yourself

It asks nothing and it finishes. Two earlier versions did neither, in ways worth
recording because both looked reasonable:

- It refused to choose between candidate packages directories, and exited. The
  reasoning was sound, that a wrong choice is silent, and the conclusion was
  wrong, because writing the same file into all of them is never a wrong choice.
- It reported a Claude Code entry pointing somewhere else, printed the two
  commands to repair it, and stopped. It knew both values and had already been
  told to install. Printing homework is not finishing.

What remains genuinely undecidable is still refused, not guessed: if no Houdini
packages directory exists at all, this says so rather than inventing one, since
a package file in a directory Houdini never reads is the silent no-op the whole
command exists to prevent.
"""

from __future__ import annotations

# Built-in
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# Internal
from fxhoudinimcp.houdini_package import (
    CLI,
    PACKAGE_NAME,
    candidate_package_dirs,
    existing_packages,
    plugin_path,
    write_package,
)

# The name the server is registered under with MCP clients.
SERVER_NAME = "fxhoudini"


def client_command() -> list[str]:
    """The argv an MCP client should run to start this server.

    sys.executable, never a bare "python". Claude Desktop launches its servers
    without the user's shell environment, so a bare interpreter name resolves
    against a PATH that may not contain the Python this package is installed
    into. That failure surfaces only as "disconnected", which is why the README
    had to explain it; an absolute path removes the class of problem.
    """
    return [sys.executable, "-m", "fxhoudinimcp"]


def desktop_config_path() -> Path | None:
    """Claude Desktop's config file for this platform, whether or not it exists."""
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("APPDATA")
        if not base:
            return None
        return Path(base) / "Claude" / "claude_desktop_config.json"
    if system == "Darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json"
        )
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def claude_code_available() -> bool:
    return shutil.which("claude") is not None


def claude_code_add_argv(scope: str = "user") -> list[str]:
    """The `claude mcp add` invocation, for running or for printing verbatim."""
    return [
        "claude",
        "mcp",
        "add",
        "--scope",
        scope,
        SERVER_NAME,
        "--",
        *client_command(),
    ]


def claude_code_remove_argv(scope: str = "user") -> list[str]:
    """The `claude mcp remove` invocation, for running or for printing.

    Lives next to its counterpart because `install` needs it too: `claude mcp
    add` cannot update an entry in place, so repointing one means removing it
    first. `uninstall` imports it from here.
    """
    return ["claude", "mcp", "remove", SERVER_NAME, "-s", scope]


def printable_argv(argv: list[str]) -> str:
    """An argv a person can paste back into a shell."""
    return " ".join(f'"{part}"' if " " in part else part for part in argv)


def resolve_houdini_dirs(explicit: str | None) -> tuple[list[Path], str]:
    """Where the package file goes. An empty list means there is nowhere yet.

    Every candidate, not one of them. This went through two wrong answers before
    landing here, and the reasoning matters because it looks like carelessness.

    The original code refused to choose, on the grounds that choosing wrongly is
    invisible: Houdini skips a package file it cannot resolve without a word, so
    the wrong directory produces silence rather than an error. True, and it made
    the command exit rather than finish. The second answer was to ask, which
    only moved the decision without removing it, and made the whole thing depend
    on there being a terminal.

    Both missed that the premise does not apply to "all of them". The files are
    byte-identical and point at the same plugin, so whichever directory Houdini
    reads, it finds a correct one. There is no last-one-wins hazard between
    copies of the same file, which is the only reason ambiguity was dangerous.
    OneDrive's Documents redirection stops being a question to answer and
    becomes two paths that both work.

    The cost is an MCP menu in a Houdini version you may not use, removable in
    one `uninstall`. That is a much smaller price than a command that stops.
    """
    if explicit:
        return [Path(explicit).expanduser()], "given on the command line"

    candidates = candidate_package_dirs()
    if not candidates:
        return [], "no Houdini packages directory exists yet"
    if len(candidates) == 1:
        return candidates, "the only candidate on this machine"
    return candidates, f"every candidate on this machine ({len(candidates)})"


def _merge_desktop_config(existing: dict, command: list[str]) -> dict:
    """Point our entry at *command* while preserving everything else.

    Someone's Desktop config is likely to hold servers that took effort to set
    up, so this merges rather than writing a fresh document, and never reorders
    or drops what it does not understand.

    That care has to extend inside our own entry, not just around it. Replacing
    the whole entry looked correct until it met a real config, which carried an
    ``env`` block with HOUDINI_HOST and HOUDINI_PORT: rewriting the entry
    wholesale would have deleted the user's settings while reporting success.
    Only ``command`` and ``args`` are ours to set.
    """
    merged = dict(existing)
    servers = dict(merged.get("mcpServers") or {})
    entry = dict(servers.get(SERVER_NAME) or {})
    entry["command"] = command[0]
    entry["args"] = list(command[1:])
    servers[SERVER_NAME] = entry
    merged["mcpServers"] = servers
    return merged


def pinned_port_warning(entry: dict | None) -> list[str]:
    """Warn when a config pins HOUDINI_PORT, which disables port discovery.

    An explicit HOUDINI_PORT is honoured deliberately by the server: it means
    "this session, not whichever answers first". But it also switches off the
    scan of 8100-8115, so a second Houdini that moved itself to 8101 becomes
    unreachable. Worth saying out loud, since the value is usually left over
    from an older config rather than chosen.
    """
    port = ((entry or {}).get("env") or {}).get("HOUDINI_PORT")
    if not port:
        return []
    return [
        f"  NOTE: this entry pins HOUDINI_PORT={port}, so the client will not scan",
        "        for other Houdini sessions. A second Houdini moves itself to the",
        "        next free port and would be unreachable. Remove it from 'env' to",
        "        let the client find whichever session is serving.",
    ]


def install_desktop(config: Path, command: list[str], dry_run: bool) -> list[str]:
    """Register the server in Claude Desktop's config. Returns report lines."""
    lines: list[str] = []
    existing: dict = {}
    if config.is_file():
        try:
            existing = json.loads(config.read_text(encoding="utf-8-sig")) or {}
        except Exception as exc:
            return [
                f"  SKIPPED Claude Desktop: {config} is not readable JSON ({exc}).",
                "          Fix or remove it, then re-run. It was left untouched.",
            ]
        if not isinstance(existing, dict):
            return [
                f"  SKIPPED Claude Desktop: {config} is not a JSON object.",
                "          It was left untouched.",
            ]

    already = (existing.get("mcpServers") or {}).get(SERVER_NAME)
    merged = _merge_desktop_config(existing, command)
    if already == merged["mcpServers"][SERVER_NAME]:
        return [
            f"  Claude Desktop already points at this install ({config}).",
            *pinned_port_warning(already),
        ]

    if dry_run:
        lines.append(f"  Would update {config}")
        if already is not None:
            old = already.get("command")
            lines.append(f"          repointing command from {old!r} to {command[0]!r}")
            lines.append("          keeping every other key in the entry")
        lines += pinned_port_warning(already)
        return lines

    config.parent.mkdir(parents=True, exist_ok=True)
    if config.is_file():
        # Keep a copy. This file can hold hand-built server entries, and an
        # installer that eats them is worse than one that never ran.
        backup = config.with_suffix(config.suffix + ".bak")
        shutil.copy2(config, backup)
        lines.append(f"  Backed up {backup.name}")
    config.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8", newline="\n")
    lines.append(f"  Registered '{SERVER_NAME}' in {config}")
    lines += pinned_port_warning(already)
    lines.append("  Fully quit Claude Desktop (tray > Quit) and relaunch.")
    return lines


def claude_code_current_command() -> str | None:
    """The command Claude Code has registered for us, if any.

    Read with `claude mcp get`, whose output is meant for humans, so this only
    looks for the "Command:" line rather than trying to parse the whole thing.
    Returns None when the server is not registered or the output is unfamiliar.
    """
    try:
        result = subprocess.run(
            ["claude", "mcp", "get", SERVER_NAME], capture_output=True, text=True
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    for line in (result.stdout or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("Command:"):
            return stripped.split(":", 1)[1].strip()
    return None


def _first_line(result: subprocess.CompletedProcess) -> str:
    """The most useful single line out of a failed subprocess."""
    output = (result.stderr or "") + (result.stdout or "")
    detail = output.strip().splitlines()
    return detail[0] if detail else f"exit code {result.returncode}"


def config_file_note(result: subprocess.CompletedProcess) -> list[str]:
    """Name the config file the Claude Code CLI actually wrote.

    It already prints ``File modified: <path>`` and we were swallowing it, in
    favour of "registered with Claude Code (user scope)". That reads as complete
    and is not, because "user scope" is not one place: CLAUDE_CONFIG_DIR decides
    which profile is user scope, and a machine can have several. On one with a
    second profile, a correct, connected registration was invisible to every
    `claude mcp get` run from the other one, and looked like a failed install
    for an afternoon.

    Naming the file costs one line and removes the ambiguity, so a report of
    success can be checked rather than believed.
    """
    output = (result.stdout or "") + (result.stderr or "")
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("file modified:"):
            return [f"      in {stripped.split(':', 1)[1].strip()}"]

    # Older CLIs may not print it. Naming the profile is still better than
    # silence, and it is read from the environment rather than guessed.
    profile = os.environ.get("CLAUDE_CONFIG_DIR")
    if profile:
        return [f"      in the Claude Code profile at {profile}"]
    return []


def repoint_claude_code() -> list[str]:
    """Replace a Claude Code entry that points at a different interpreter.

    `claude mcp add` has no --force, so an existing entry is an error rather
    than an update. This used to be reported back with the two commands needed
    to fix it, which was the installer declining to finish its own job: it knows
    the value that is there, it knows the one that should be, and the operator
    consented by running `install`. Printing homework instead is the same "four
    steps across two worlds" this command exists to remove.

    Removing first is safe in a way a blind overwrite would not be, because the
    old value is read and reported before anything changes.
    """
    current = claude_code_current_command()
    wanted = client_command()[0]
    if current == wanted:
        return ["  Claude Code already points at this Python. Nothing to do."]

    removal = claude_code_remove_argv()
    result = subprocess.run(removal, capture_output=True, text=True)
    if result.returncode != 0:
        return [
            f"  Claude Code has '{SERVER_NAME}' pointing at {current or '<could not read it>'},",
            f"  and it could not be replaced: {_first_line(result)}",
            f"  Remove it by hand, then re-run: {printable_argv(removal)}",
        ]

    argv = claude_code_add_argv()
    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode != 0:
        return [
            f"  Removed the old '{SERVER_NAME}' entry, but re-registering "
            f"failed: {_first_line(result)}",
            f"  Finish it with: {printable_argv(argv)}",
        ]

    return [
        f"  Repointed '{SERVER_NAME}' in Claude Code (user scope):",
        f"      was: {current or '<could not read it>'}",
        f"      now: {wanted}",
        *config_file_note(result),
    ]


def install_claude_code(dry_run: bool) -> list[str]:
    """Register with Claude Code via its own CLI. Returns report lines."""
    argv = claude_code_add_argv()
    printable = printable_argv(argv)

    if not claude_code_available():
        return [
            "  Claude Code CLI not on PATH, so nothing was changed. Run this",
            "  yourself if you use Claude Code:",
            f"      {printable}",
        ]
    if dry_run:
        return [f"  Would run: {printable}"]

    # Its own CLI owns the config schema, so shell out rather than editing
    # ~/.claude.json directly and risking a shape this version does not expect.
    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode == 0:
        return [
            f"  Registered '{SERVER_NAME}' with Claude Code (user scope).",
            *config_file_note(result),
        ]

    output = (result.stderr or "") + (result.stdout or "")
    if "already exists" in output.lower():
        return repoint_claude_code()

    return [
        f"  Claude Code registration failed: {_first_line(result)}",
        f"  Run it yourself to see the whole error: {printable}",
    ]


def build_parser() -> argparse.ArgumentParser:
    """The argument parser, exposed so the README's flag table can be checked.

    The table in the README is the first thing anyone reads, so a flag that is
    renamed here and not there is a documented lie. tests/test_install.py
    compares the two.
    """
    parser = argparse.ArgumentParser(
        prog=f"{CLI} install",
        description="Install the Houdini plugin and register this server with your MCP client.",
    )
    parser.add_argument(
        "--houdini-dir",
        metavar="DIR",
        help="Houdini packages directory to write into (required only when "
        "several candidates exist)",
    )
    parser.add_argument(
        "--client",
        choices=("auto", "claude-code", "claude-desktop", "both", "none"),
        default="auto",
        help="which MCP client to register with (default: auto, meaning "
        "whichever of the two is present)",
    )
    parser.add_argument(
        "--client-only",
        action="store_true",
        help="skip the Houdini plugin and only register with the MCP client; "
        "needs no --houdini-dir, so it works when several candidates exist",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change without changing anything",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.client_only and args.houdini_dir:
        parser.error("--client-only and --houdini-dir contradict each other")

    plugin = plugin_path()
    if not plugin.is_dir() and not args.client_only:
        print(
            f"The plugin directory is missing: {plugin}\n"
            "This install predates the plugin shipping inside the package "
            "(2.1.0), or came from a source tree without it.",
            file=sys.stderr,
        )
        return 1

    prefix = "Would install" if args.dry_run else "Installing"
    print(f"{prefix} FXHoudini-MCP")
    print(f"  Python : {sys.executable}")
    if not args.client_only:
        print(f"  Plugin : {plugin.as_posix()}")
    print()

    # -- Half one: the Houdini plugin
    if args.client_only:
        print("Houdini plugin")
        print("  Skipped (--client-only). The plugin already installed is left")
        print("  exactly as it is.")
    else:
        result = _install_plugin_half(args, plugin)
        if result != 0:
            return result

    _install_client_half(args)

    if args.dry_run:
        print("\nNothing was changed (--dry-run).")
    elif args.client_only:
        print("\nRestart your MCP client to pick up the change.")
    else:
        print("\nRestart Houdini, then check the MCP menu.")
        print(
            "MCP > Connect a Client... prints the command again, with the port "
            "the\nserver actually ended up on."
        )
    return 0


def _report_missing_directory(destination: Path) -> None:
    print(f"  Not a directory: {destination}", file=sys.stderr)
    print("  Create it first, or pass a different --houdini-dir.", file=sys.stderr)


def _install_plugin_half(args, plugin: Path) -> int:
    """Write the Houdini package file. Returns an exit code."""
    print("Houdini plugin")

    destinations, reason = resolve_houdini_dirs(args.houdini_dir)
    if not destinations:
        print(f"  {reason.capitalize()}.")
        print(
            "  Create one inside your Houdini preferences directory, for "
            "example\n      Documents/houdini22.0/packages\n"
            "  then re-run this command."
        )
        return 1

    # Every destination is checked before any is written, so a typo in the
    # second one cannot leave the first half-installed. It also keeps --dry-run
    # honest: it used to report "Would write" for a directory that does not
    # exist, and then the real run refused.
    for destination in destinations:
        if not destination.is_dir():
            _report_missing_directory(destination)
            return 1

    for destination in destinations:
        if args.dry_run:
            print(f"  Would write {PACKAGE_NAME} into {destination} ({reason})")
            continue
        try:
            written = write_package(destination, plugin)
        except NotADirectoryError:  # pragma: no cover - lost a race with rmdir
            _report_missing_directory(destination)
            return 1
        print(f"  Wrote {written} ({reason})")

    others = existing_packages(exclude=[destination / PACKAGE_NAME for destination in destinations])
    if others:
        print(
            f"\n  WARNING: {len(others)} other {PACKAGE_NAME} exists. Houdini "
            "processes every\n  packages directory and the last one wins, so a "
            "leftover file can silently\n  override this install:"
        )
        for path, points_at in others:
            print(f"      {path}\n          -> {points_at}")
        print("  Delete the ones you do not want, or run:")
        print("      python -m fxhoudinimcp uninstall")

    return 0


def _install_client_half(args) -> None:
    """Register the server with whichever MCP clients are in scope."""
    print("\nMCP client")
    wanted = args.client
    if wanted == "auto":
        targets = []
        if claude_code_available():
            targets.append("claude-code")
        config = desktop_config_path()
        if config is not None and config.parent.is_dir():
            targets.append("claude-desktop")
        if not targets:
            print("  Neither Claude Code nor Claude Desktop was detected.")
            printable = " ".join(claude_code_add_argv())
            print(f"  For Claude Code:  {printable}")
            print(f"  For anything else, run: {' '.join(client_command())}")
            targets = []
    elif wanted == "both":
        targets = ["claude-code", "claude-desktop"]
    elif wanted == "none":
        print("  Skipped (--client none). Start the server with:")
        print(f"      {' '.join(client_command())}")
        targets = []
    else:
        targets = [wanted]

    for target in targets:
        if target == "claude-code":
            for line in install_claude_code(args.dry_run):
                print(line)
        else:
            config = desktop_config_path()
            if config is None:
                print("  Could not locate Claude Desktop's config on this platform.")
                continue
            for line in install_desktop(config, client_command(), args.dry_run):
                print(line)
