"""Generate the list of plugin commands this MCP server depends on.

The MCP server and the Houdini plugin are two halves that ship separately: the
server comes from PyPI, the plugin from the repository. Nothing stops a user
upgrading one and not the other, and a plugin older than the server is missing
commands the server's tools call. The symptom is a single tool failing with
"No handler registered for command", which reads like a bug rather than a
version mismatch.

This extracts every ``bridge.execute("namespace.command")`` literal from the
client and writes it to ``data/required_commands.json``, which ships. At
startup the server compares that against the plugin's own ``mcp.list_commands``
and names anything missing.

    python tools/gen_required_commands.py            # regenerate
    python tools/gen_required_commands.py --check    # fail if stale

Extraction is by AST rather than regex so multi-line calls are not missed, and
it fails loudly if any call site passes a non-literal: a computed command name
would be invisible here, which would make the manifest quietly incomplete.
"""

from __future__ import annotations

# Built-in
import argparse
import ast
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_CLIENT = REPO_ROOT / "python" / "fxhoudinimcp"
_MANIFEST = _CLIENT / "data" / "required_commands.json"


def collect(root: Path = _CLIENT) -> tuple[set[str], list[str]]:
    """Return (command names, non-literal call sites) found under *root*."""
    commands: set[str] = set()
    dynamic: list[str] = []

    for path in sorted(root.rglob("*.py")):
        if "/tests/" in path.as_posix():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name != "execute":
                continue

            relative = path.relative_to(REPO_ROOT).as_posix()
            if not node.args:
                # execute(command=...) would hide the name from this scan.
                dynamic.append(f"{relative}:{node.lineno} (no positional argument)")
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                commands.add(first.value)
            else:
                dynamic.append(f"{relative}:{node.lineno} ({type(first).__name__})")

    return commands, dynamic


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit non-zero if the committed manifest is stale",
    )
    args = parser.parse_args()

    commands, dynamic = collect()
    if dynamic:
        print(f"Non-literal execute() call sites ({len(dynamic)}):")
        for site in dynamic:
            print(f"    {site}")
        print(
            "\nEvery command name must be a string literal, or the manifest is "
            "incomplete and the compatibility check silently weakens."
        )
        return 1

    if not commands:
        print("No commands found. The extractor or the client layout changed.")
        return 1

    payload = json.dumps({"commands": sorted(commands)}, indent=2, sort_keys=True) + "\n"

    if args.check:
        current = _MANIFEST.read_text(encoding="utf-8") if _MANIFEST.is_file() else ""
        if current != payload:
            print(
                f"STALE: {_MANIFEST.relative_to(REPO_ROOT)}\n"
                "Run: python tools/gen_required_commands.py"
            )
            return 1
        print(f"Up to date: {len(commands)} commands.")
        return 0

    _MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    _MANIFEST.write_text(payload, encoding="utf-8")
    print(f"wrote {_MANIFEST.relative_to(REPO_ROOT)} ({len(commands)} commands)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
