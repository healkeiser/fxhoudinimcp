"""Emit the Houdini package file that points at the installed plugin.

The plugin now ships inside this package, so its path depends on which Python
you installed into. That path is easy to get wrong and easy to break: recreate a
venv, switch to uv or pipx, move from 3.11 to 3.12, and a hand-typed path
silently stops resolving. Houdini says nothing when a package path is missing, it
just skips the file, which is what made issue #11 so confusing.

So nobody should type it. This resolves the path from the running interpreter and
prints, or writes, the JSON.

    fxhoudinimcp houdini-package                 # print the JSON and where to put it
    fxhoudinimcp houdini-package --write DIR     # write it into DIR

The destination is not guessed. Houdini's preference directory is genuinely
ambiguous on Windows, where OneDrive's Documents redirection means a
desktop-launched Houdini and a shell-launched one can disagree, so candidates are
listed and the choice is left to the operator.
"""

from __future__ import annotations

# Built-in
import argparse
import json
import platform
import sys
from pathlib import Path

_PACKAGE_NAME = "fxhoudinimcp.json"


def plugin_path() -> Path:
    """Absolute path to the Houdini plugin directory.

    Two layouts are valid. An installed wheel relocates the plugin to
    ``fxhoudinimcp/houdini``; a source tree or editable install keeps it at the
    repository root. Preferring the packaged location means an installed user
    never picks up a stale clone that happens to sit nearby, while a contributor
    working from a checkout still gets a working command.
    """
    here = Path(__file__).resolve().parent
    packaged = here / "houdini"
    if packaged.is_dir():
        return packaged
    return here.parents[1] / "houdini"


def package_json(path: Path | None = None) -> str:
    """The Houdini package file contents pointing at *path*.

    Forward slashes on every platform: Houdini accepts them, and backslashes in
    JSON need escaping, which is a common way to break this file by hand.
    """
    target = (path or plugin_path()).as_posix()
    return json.dumps(
        {"env": [{"FXHOUDINIMCP": target}], "path": "$FXHOUDINIMCP"}, indent=4
    ) + "\n"


def candidate_package_dirs() -> list[Path]:
    """Plausible Houdini packages directories that already exist.

    Only reports directories present on disk, and never picks one: on Windows
    with OneDrive's Documents redirection, a desktop-launched Houdini and a
    shell-launched one resolve different preference directories, and choosing
    wrongly reproduces the silent no-op this command exists to prevent.
    """
    home = Path.home()
    roots: list[Path] = []
    system = platform.system()
    if system == "Windows":
        roots += [home / "Documents", home / "OneDrive" / "Documents", home]
    elif system == "Darwin":
        roots += [home / "Library" / "Preferences" / "houdini"]
    else:
        roots += [home]

    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for entry in sorted(root.glob("houdini*")):
            packages = entry / "packages"
            if entry.is_dir() and packages.is_dir():
                found.append(packages)
    return found


def existing_packages(exclude: Path | None = None) -> list[tuple[Path, str]]:
    """Find already-installed package files and the plugin path each points at.

    Two of these is a real hazard rather than a tidiness issue. Houdini processes
    every packages directory and lets the last one win, so a leftover file
    pointing at an old clone can silently override a fresh install. Houdini says
    so only under HOUDINI_PACKAGE_VERBOSE:

        WARNING: var FXHOUDINIMCP overwritten with ...

    Reported so the operator can delete the stale one.
    """
    found: list[tuple[Path, str]] = []
    for directory in candidate_package_dirs():
        candidate = directory / _PACKAGE_NAME
        if not candidate.is_file():
            continue
        if exclude is not None and candidate == exclude:
            continue
        target = "<unreadable>"
        try:
            data = json.loads(candidate.read_text(encoding="utf-8-sig"))
            for entry in data.get("env") or []:
                if "FXHOUDINIMCP" in entry:
                    value = entry["FXHOUDINIMCP"]
                    target = (
                        value if isinstance(value, str) else value.get("value", target)
                    )
        except Exception:
            pass
        found.append((candidate, target))
    return found


def write_package(destination: Path, path: Path | None = None) -> Path:
    """Write ``fxhoudinimcp.json`` into *destination* and return the file written.

    Shared with ``fxhoudinimcp install`` so there is one place that knows the
    encoding rules. utf-8 *without* a BOM: Houdini's JSON parser rejects a BOM
    and skips the whole package silently, which is the trap behind issue #11.

    Raises NotADirectoryError if *destination* does not exist, rather than
    creating it: a typo'd path would otherwise produce a package file in a
    directory Houdini never reads, and Houdini reports nothing when that happens.
    """
    if not destination.is_dir():
        raise NotADirectoryError(destination)
    target = destination / _PACKAGE_NAME
    target.write_text(package_json(path), encoding="utf-8", newline="\n")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fxhoudinimcp houdini-package",
        description="Print or write the Houdini package file for this install.",
    )
    parser.add_argument(
        "--write",
        metavar="DIR",
        help="write fxhoudinimcp.json into DIR (a Houdini packages directory)",
    )
    parser.add_argument(
        "--path-only",
        action="store_true",
        help="print just the plugin directory, for scripting",
    )
    args = parser.parse_args(argv)

    plugin = plugin_path()
    if args.path_only:
        print(plugin.as_posix())
        return 0

    if not plugin.is_dir():
        print(
            f"The plugin directory is missing: {plugin}\n"
            "This install predates the plugin being shipped in the package "
            "(added in 2.1.0), or it was installed from a source tree without "
            "it. Upgrade, or point FXHOUDINIMCP at a clone of the repository.",
            file=sys.stderr,
        )
        return 1

    contents = package_json(plugin)

    if args.write:
        destination = Path(args.write).expanduser()
        try:
            target = write_package(destination, plugin)
        except NotADirectoryError:
            print(
                f"Not a directory: {destination}\n"
                "Create it first, or pick one of the candidates listed by "
                "running this command without --write.",
                file=sys.stderr,
            )
            return 1
        print(f"Wrote {target}")

        others = existing_packages(exclude=target)
        if others:
            print(
                f"\nWARNING: {len(others)} other {_PACKAGE_NAME} also exists. "
                "Houdini processes every packages directory and the last one "
                "wins, so a leftover file can silently override this install:"
            )
            for path, points_at in others:
                print(f"    {path}\n        -> {points_at}")
            print("Delete the ones you do not want.")

        print("\nRestart Houdini, then check the MCP menu.")
        return 0

    print(f"Plugin directory:\n    {plugin.as_posix()}\n")
    print(f"Put this in a Houdini packages directory as {_PACKAGE_NAME}:\n")
    print(contents)

    candidates = candidate_package_dirs()
    if candidates:
        print("Candidate packages directories found on this machine:")
        for candidate in candidates:
            print(f"    {candidate}")
        print(
            f"\nWrite it with:\n"
            f"    fxhoudinimcp houdini-package --write \"{candidates[0]}\""
        )
    else:
        print(
            "No Houdini packages directory found. Create one inside your Houdini\n"
            "preferences directory (for example Documents/houdini22.0/packages)."
        )
    print(
        "\nTo verify Houdini picked it up, start Houdini with "
        "HOUDINI_PACKAGE_VERBOSE=1\nand look for a 'Processing:' line for "
        f"{_PACKAGE_NAME}."
    )
    return 0
