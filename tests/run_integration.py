#!/usr/bin/env python3
"""Launch the integration test suite inside hython on Windows, macOS, or Linux.

Usage:
    python tests/run_integration.py              # whole integration suite
    python tests/run_integration.py -k pyro      # pytest args pass through

Finds the newest installed Houdini (override with the HYTHON environment
variable pointing at the hython executable) and reuses this interpreter's
pytest installation via PYTHONPATH. Requires a Houdini license seat.
"""

from __future__ import annotations

# Built-in
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

def _search_patterns() -> list[str]:
    """Where Houdini installs live, per platform.

    %PROGRAMFILES% rather than a hardcoded C:, because a Windows install on
    another drive is common. The Linux list covers the SideFX default plus the
    two relocations that turn up most often; anything more exotic is reachable
    via $HFS or $HYTHON.
    """
    program_files = os.environ.get("PROGRAMFILES", "C:/Program Files").replace(
        "\\", "/"
    )
    return [
        # Windows
        f"{program_files}/Side Effects Software/Houdini *",
        "C:/Program Files/Side Effects Software/Houdini *",
        # macOS
        "/Applications/Houdini/Houdini*",
        # Linux
        "/opt/hfs*",
        "/opt/sidefx/hfs*",
        "/usr/local/hfs*",
    ]


_HYTHON_SUBPATHS = [
    "bin/hython.exe",
    "bin/hython",
    # macOS keeps the interpreter inside the framework bundle. SideFX document
    # both this and a version-numbered directory, so the glob below covers the
    # case where the Current symlink is absent.
    "Frameworks/Houdini.framework/Versions/Current/Resources/bin/hython",
]

# Tried after the exact paths above. Houdini's own help documents the macOS
# location as ".../Houdini.framework/Versions/<version>/Resources/bin", so
# relying on "Current" alone would miss an install without that symlink.
_HYTHON_GLOBS = [
    "Frameworks/Houdini.framework/Versions/*/Resources/bin/hython",
]


def _version_key(path: Path) -> tuple[int, ...]:
    digits = re.findall(r"\d+", path.name)
    return tuple(int(d) for d in digits) if digits else (0,)


def _hython_in(install: Path) -> Path | None:
    """Find the interpreter inside one install directory.

    Exact paths first because they are the common case and cost one stat each;
    the globs exist so a layout variation degrades to a slower search rather
    than to "no Houdini found".
    """
    for subpath in _HYTHON_SUBPATHS:
        hython = install / subpath
        if hython.is_file():
            return hython

    for pattern in _HYTHON_GLOBS:
        # Sorted so the choice is deterministic when several versions of the
        # framework are present inside one install.
        for hython in sorted(install.glob(pattern)):
            if hython.is_file():
                return hython
    return None


def find_all_hython() -> list[Path]:
    """Return every installed hython executable, newest first.

    Used by tools/gen_node_versions.py, which needs to sample all installs
    rather than just the newest. $HFS is honoured first so a Houdini in a
    non-standard location -- a studio mount, a relocated install -- is still
    found; it is the pointer SideFX's own shell sets.
    """
    installs: list[Path] = []

    hfs = os.environ.get("HFS")
    if hfs:
        candidate = Path(hfs.replace("\\", "/"))
        if candidate.is_dir():
            installs.append(candidate)

    for pattern in _search_patterns():
        # Split on the final separator, not on the "*": the wildcard sits inside
        # the last segment ("Houdini *", "hfs*"), and splitting on it walked one
        # directory too far up for a pattern whose last segment is just "*".
        root, glob = Path(pattern).parent, Path(pattern).name
        if root.is_dir():
            installs.extend(p for p in root.glob(glob) if p.is_dir())

    found: list[Path] = []
    seen: set[Path] = set()
    for install in sorted(installs, key=_version_key, reverse=True):
        hython = _hython_in(install)
        if hython is None:
            continue
        # Two patterns can name the same directory (%PROGRAMFILES% and the
        # literal C: fallback), and $HFS usually duplicates one of them.
        resolved = hython.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        found.append(hython)
    return found


def find_hython() -> Path:
    """Return the hython executable: $HYTHON, newest install, or PATH."""
    env_override = os.environ.get("HYTHON")
    if env_override:
        candidate = Path(env_override)
        if candidate.is_file():
            return candidate
        sys.exit(f"HYTHON is set but does not exist: {env_override}")

    for hython in find_all_hython():
        return hython

    on_path = shutil.which("hython")
    if on_path:
        return Path(on_path)

    sys.exit(
        "No hython executable found. Install Houdini or set the HYTHON "
        "environment variable to the full path of hython."
    )


def main() -> int:
    hython = find_hython()

    try:
        import pytest  # noqa: F401

        site_packages = Path(pytest.__file__).resolve().parent.parent
    except ImportError:
        sys.exit(
            "pytest is not importable from this Python. Install it first: "
            f"{sys.executable} -m pip install pytest"
        )

    env = os.environ.copy()
    python_path = [str(REPO_ROOT / "python"), str(site_packages)]
    if env.get("PYTHONPATH"):
        python_path.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(python_path)

    print(f"Using hython: {hython}")
    command = [
        str(hython),
        "-m",
        "pytest",
        str(REPO_ROOT / "tests" / "integration"),
        "-q",
        "-s",
        "--durations=15",
        *sys.argv[1:],
    ]
    return subprocess.call(command, env=env, cwd=str(REPO_ROOT))


if __name__ == "__main__":
    sys.exit(main())
