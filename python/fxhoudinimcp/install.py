"""One command that wires up both halves.

Installing used to be four steps across two worlds: pip install, work out which
Houdini packages directory is the real one, write a JSON file there, then hand
your MCP client a command line whose Python path you had to discover yourself.
Every one of those steps fails quietly. Houdini skips a package file it cannot
resolve without saying so, and Claude Desktop does not inherit your PATH, so a
bare ``python`` in its config reads as "disconnected" with no explanation.

    fxhoudinimcp install                      # do both halves
    fxhoudinimcp install --dry-run            # say what it would do, change nothing
    fxhoudinimcp install --houdini-dir DIR    # when the packages directory is ambiguous
    fxhoudinimcp install --client none        # plugin only, wire the client yourself

The Houdini destination is still not guessed when it is genuinely ambiguous. One
candidate means there is nothing to choose and it is used; several means the
operator picks, because choosing wrongly on Windows with OneDrive's Documents
redirection recreates the silent no-op this command exists to prevent.
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


def resolve_houdini_dir(explicit: str | None) -> tuple[Path | None, list[Path], str]:
    """Decide where the package file goes.

    Returns (chosen, candidates, reason). *chosen* is None when the operator has
    to decide, with *reason* explaining why rather than making it up.
    """
    if explicit:
        return Path(explicit).expanduser(), [], "given on the command line"

    candidates = candidate_package_dirs()
    if not candidates:
        return None, [], "no Houdini packages directory exists yet"
    if len(candidates) == 1:
        return candidates[0], candidates, "the only candidate on this machine"
    return None, candidates, f"{len(candidates)} candidates, so the choice is yours"


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
            lines.append(
                f"          repointing command from {old!r} to {command[0]!r}"
            )
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
    config.write_text(
        json.dumps(merged, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
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


def install_claude_code(dry_run: bool) -> list[str]:
    """Register with Claude Code via its own CLI. Returns report lines."""
    argv = claude_code_add_argv()
    printable = " ".join(f'"{part}"' if " " in part else part for part in argv)

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
        return [f"  Registered '{SERVER_NAME}' with Claude Code (user scope)."]

    output = (result.stderr or "") + (result.stdout or "")
    detail = output.strip().splitlines()
    first = detail[0] if detail else f"exit code {result.returncode}"

    # `claude mcp add` has no --force, so re-running over an existing entry is
    # an error rather than an update. That is not a problem when the entry is
    # already correct, and reporting "failed" there sends people chasing a
    # non-issue, so check what is actually registered before saying anything.
    if "already exists" in output.lower():
        current = claude_code_current_command()
        wanted = client_command()[0]
        if current == wanted:
            return ["  Claude Code already points at this Python. Nothing to do."]
        return [
            f"  Claude Code already has '{SERVER_NAME}', pointing at:",
            f"      {current or '<could not read it>'}",
            "  This install is:",
            f"      {wanted}",
            "  It cannot be updated in place, so repoint it with:",
            f"      claude mcp remove {SERVER_NAME} -s user",
            "      fxhoudinimcp install --client-only",
        ]

    return [
        f"  Claude Code registration failed: {first}",
        f"  Run it yourself to see the whole error: {printable}",
    ]


def build_parser() -> argparse.ArgumentParser:
    """The argument parser, exposed so the README's flag table can be checked.

    The table in the README is the first thing anyone reads, so a flag that is
    renamed here and not there is a documented lie. tests/test_install.py
    compares the two.
    """
    parser = argparse.ArgumentParser(
        prog="fxhoudinimcp install",
        description="Install the Houdini plugin and register this server "
        "with your MCP client.",
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


def _install_plugin_half(args, plugin: Path) -> int:
    """Write the Houdini package file. Returns an exit code."""
    chosen, candidates, reason = resolve_houdini_dir(args.houdini_dir)
    print("Houdini plugin")
    if chosen is None:
        if candidates:
            print(f"  Cannot choose for you: {reason}.")
            for candidate in candidates:
                print(f"      {candidate}")
            print("\n  Re-run with the one your Houdini actually reads:")
            print(f'      fxhoudinimcp install --houdini-dir "{candidates[0]}"')
            print(
                "\n  On Windows with OneDrive redirecting Documents, a "
                "desktop-launched\n  Houdini and a shell-launched one can "
                "disagree. Start Houdini with\n  HOUDINI_PACKAGE_VERBOSE=1 to "
                "see which it reads."
            )
        else:
            print(f"  {reason.capitalize()}.")
            print(
                "  Create one inside your Houdini preferences directory, for "
                "example\n      Documents/houdini22.0/packages\n"
                "  then re-run this command."
            )
        return 1

    if args.dry_run:
        print(f"  Would write fxhoudinimcp.json into {chosen} ({reason})")
    else:
        try:
            written = write_package(chosen, plugin)
        except NotADirectoryError:
            print(f"  Not a directory: {chosen}", file=sys.stderr)
            print(
                "  Create it first, or pass a different --houdini-dir.",
                file=sys.stderr,
            )
            return 1
        print(f"  Wrote {written} ({reason})")

    others = existing_packages(exclude=chosen / "fxhoudinimcp.json")
    if others:
        print(
            f"\n  WARNING: {len(others)} other fxhoudinimcp.json exists. Houdini "
            "processes every\n  packages directory and the last one wins, so a "
            "leftover file can silently\n  override this install:"
        )
        for path, points_at in others:
            print(f"      {path}\n          -> {points_at}")
        print("  Delete the ones you do not want.")

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
