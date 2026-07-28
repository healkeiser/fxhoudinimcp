"""Take both halves back out again.

``install`` writes into two places that outlive the Python package: a Houdini
packages directory, and an MCP client's config. ``pip uninstall`` moves neither,
so removing this used to mean knowing where both live and editing them by hand.

The leftovers are not harmless, and they fail in the quiet way this project
keeps running into. A package file pointing at a plugin directory that no longer
exists is skipped by Houdini without a word. A client entry pointing at a
removed interpreter surfaces only as "disconnected". And a forgotten
``fxhoudinimcp.json`` in a second packages directory silently overrides the next
install, because Houdini processes every packages directory and the last one
wins.

    fxhoudinimcp uninstall                    # remove both halves, after asking
    fxhoudinimcp uninstall --dry-run          # list what it would remove
    fxhoudinimcp uninstall --yes              # do not ask
    fxhoudinimcp uninstall --houdini-dir DIR  # only this packages directory
    fxhoudinimcp uninstall --client none      # leave client configs alone

Unlike ``install``, this does not have to pick between candidate directories.
Installing has to know which Houdini you mean; removing does not, because every
``fxhoudinimcp.json`` found is a leftover and leaving one behind is the hazard
above. So the default is all of them, listed in full before anything is deleted.

The Python package is deliberately left alone. That is ``pip uninstall
fxhoudinimcp``, and running it on someone's behalf from inside the package being
removed is a good way to produce a half-deleted install.
"""

from __future__ import annotations

# Built-in
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

# Internal
from fxhoudinimcp.houdini_package import CLI, PACKAGE_NAME, existing_packages
from fxhoudinimcp.install import (
    SERVER_NAME,
    claude_code_available,
    claude_code_remove_argv,
    desktop_config_path,
)


def stdin_is_interactive() -> bool:
    """Whether there is a person on the other end who can answer a question.

    This lives here rather than in ``install`` because deleting files is now the
    only question left worth asking. ``install`` used to ask which Houdini
    packages directory to use and no longer does, having concluded the question
    was avoidable; this one is not.
    """
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except ValueError:  # stdin closed underneath us
        return False


def find_package_files(houdini_dir: str | None) -> list[Path]:
    """Every ``fxhoudinimcp.json`` this uninstall would remove.

    With ``--houdini-dir`` only that one directory is considered, so a machine
    with several Houdini versions can have one cleaned without touching the
    rest. Without it, every candidate directory is searched, which is the point:
    the file you forget is the one that breaks the next install.
    """
    if houdini_dir:
        candidate = Path(houdini_dir).expanduser() / PACKAGE_NAME
        return [candidate] if candidate.is_file() else []
    return [path for path, _ in existing_packages()]


def confirm(question: str) -> bool:
    """Ask before deleting. Anything but an explicit yes is no."""
    try:
        return input(f"  {question} [y/N]: ").strip().lower() in ("y", "yes")
    except EOFError:
        print()
        return False


def remove_package_files(paths: list[Path], dry_run: bool) -> list[str]:
    """Delete the Houdini package files. Returns report lines."""
    lines: list[str] = []
    for path in paths:
        if dry_run:
            lines.append(f"  Would remove {path}")
            continue
        try:
            path.unlink()
        except OSError as exc:
            lines.append(f"  Could not remove {path}: {exc}")
            continue
        lines.append(f"  Removed {path}")
    return lines


def remove_desktop_entry(config: Path, dry_run: bool) -> list[str]:
    """Drop our entry from Claude Desktop's config, keeping everything else.

    The same care ``install`` takes, for the same reason: this file is likely to
    hold servers that took someone effort to set up, and an uninstaller that
    eats them is worse than one that never ran.
    """
    if not config.is_file():
        return [f"  Claude Desktop has no config at {config}. Nothing to remove."]

    try:
        existing = json.loads(config.read_text(encoding="utf-8-sig")) or {}
    except Exception as exc:
        return [
            f"  SKIPPED Claude Desktop: {config} is not readable JSON ({exc}).",
            "          Fix or remove it by hand. It was left untouched.",
        ]
    if not isinstance(existing, dict):
        return [
            f"  SKIPPED Claude Desktop: {config} is not a JSON object.",
            "          It was left untouched.",
        ]

    servers = existing.get("mcpServers") or {}
    if SERVER_NAME not in servers:
        return [f"  Claude Desktop has no '{SERVER_NAME}' entry. Nothing to remove."]

    if dry_run:
        return [f"  Would remove '{SERVER_NAME}' from {config}"]

    backup = config.with_suffix(config.suffix + ".bak")
    shutil.copy2(config, backup)
    remaining = dict(servers)
    del remaining[SERVER_NAME]
    updated = dict(existing)
    updated["mcpServers"] = remaining
    config.write_text(
        json.dumps(updated, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return [
        f"  Backed up {backup.name}",
        f"  Removed '{SERVER_NAME}' from {config}",
        "  Fully quit Claude Desktop (tray > Quit) and relaunch.",
    ]


def remove_claude_code(dry_run: bool) -> list[str]:
    """Unregister from Claude Code via its own CLI. Returns report lines."""
    argv = claude_code_remove_argv()
    printable = " ".join(argv)

    if not claude_code_available():
        return [
            "  Claude Code CLI not on PATH, so nothing was changed. Run this",
            "  yourself if you use Claude Code:",
            f"      {printable}",
        ]
    if dry_run:
        return [f"  Would run: {printable}"]

    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode == 0:
        return [f"  Removed '{SERVER_NAME}' from Claude Code (user scope)."]

    output = (result.stderr or "") + (result.stdout or "")
    # Removing something that is not there is the desired end state, not a
    # failure, and reporting it as one sends people looking for a problem.
    if "no mcp server" in output.lower() or "not found" in output.lower():
        return [f"  Claude Code has no '{SERVER_NAME}' entry. Nothing to remove."]

    detail = output.strip().splitlines()
    first = detail[0] if detail else f"exit code {result.returncode}"
    return [
        f"  Claude Code removal failed: {first}",
        f"  Run it yourself to see the whole error: {printable}",
    ]


def build_parser() -> argparse.ArgumentParser:
    """The argument parser, exposed so the README's flag table can be checked."""
    parser = argparse.ArgumentParser(
        prog=f"{CLI} uninstall",
        description="Remove the Houdini package file and the MCP client "
        "registration written by `fxhoudinimcp install`.",
    )
    parser.add_argument(
        "--houdini-dir",
        metavar="DIR",
        help="only clean this packages directory (default: every one found)",
    )
    parser.add_argument(
        "--client",
        choices=("auto", "claude-code", "claude-desktop", "both", "none"),
        default="auto",
        help="which MCP client to unregister from (default: auto, meaning "
        "whichever of the two is present)",
    )
    parser.add_argument(
        "--client-only",
        action="store_true",
        help="unregister the client and leave the Houdini package files alone",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be removed without removing anything",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="do not ask for confirmation; required when stdin is not a terminal",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.client_only and args.houdini_dir:
        parser.error("--client-only and --houdini-dir contradict each other")

    prefix = "Would remove" if args.dry_run else "Removing"
    print(f"{prefix} FXHoudini-MCP")
    print(f"  Python : {sys.executable}")
    print()

    package_files = [] if args.client_only else find_package_files(args.houdini_dir)

    print("Houdini plugin")
    if args.client_only:
        print("  Skipped (--client-only). Package files were left in place.")
    elif not package_files:
        where = args.houdini_dir or "any Houdini packages directory found"
        print(f"  No {PACKAGE_NAME} in {where}. Nothing to remove.")
    else:
        for path in package_files:
            print(f"      {path}")

    targets = _client_targets(args)

    if not package_files and not targets:
        print("\nNothing to do.")
        _report_python_package()
        return 0

    if not args.dry_run and not args.yes and not _confirmed(package_files, targets):
        return 1

    if package_files:
        print()
        for line in remove_package_files(package_files, args.dry_run):
            print(line)

    print("\nMCP client")
    if not targets:
        print("  Skipped. No client config was touched.")
    for target in targets:
        if target == "claude-code":
            lines = remove_claude_code(args.dry_run)
        else:
            config = desktop_config_path()
            if config is None:
                print("  Could not locate Claude Desktop's config on this platform.")
                continue
            lines = remove_desktop_entry(config, args.dry_run)
        for line in lines:
            print(line)

    if args.dry_run:
        print("\nNothing was changed (--dry-run).")
    else:
        print("\nRestart Houdini and your MCP client to pick up the change.")
    _report_python_package()
    return 0


def _client_targets(args) -> list[str]:
    """Which client configs are in scope, mirroring `install`'s --client."""
    if args.client == "none":
        return []
    if args.client == "both":
        return ["claude-code", "claude-desktop"]
    if args.client != "auto":
        return [args.client]

    targets = []
    if claude_code_available():
        targets.append("claude-code")
    config = desktop_config_path()
    if config is not None and config.is_file():
        targets.append("claude-desktop")
    return targets


def _confirmed(package_files: list[Path], targets: list[str]) -> bool:
    """Ask before deleting, and refuse to assume when nobody can be asked.

    A script that pipes this command nothing gets a refusal rather than a
    deletion. --yes is how a script says it meant it.
    """
    if not stdin_is_interactive():
        print(
            "\nRefusing to remove anything without confirmation. Re-run with "
            "--yes,\nor with --dry-run to see the full list first.",
            file=sys.stderr,
        )
        return False

    count = len(package_files) + len(targets)
    print()
    if not confirm(f"Remove {count} item(s) listed above?"):
        print("  Cancelled. Nothing was removed.")
        return False
    return True


def _report_python_package() -> None:
    print(
        "\nThe Python package is still installed. Remove it with:\n"
        "    pip uninstall fxhoudinimcp"
    )
