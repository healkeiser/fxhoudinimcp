"""Generate the Technical section: one mkdocstrings page per module.

Writes ``docs/technical/<module>.md`` stubs (each a single ``::: module``
directive) and ``docs/technical/SUMMARY.md`` for literate-nav, then removes any
stale page left from a module that no longer exists. The directory is
gitignored: run this before ``zensical build`` or ``zensical serve``.

    python docs/.scripts/generate_technical_docs.py

This used to be a mkdocs-gen-files script writing into the build's virtual
file tree. Zensical has no gen-files plugin, so the pages are now real files.
"""

from __future__ import annotations

# Built-in
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "python" / "fxhoudinimcp"
OUT = ROOT / "docs" / "technical"


def _nav_lines(entries: list[tuple[tuple[str, ...], str]]) -> list[str]:
    """Render literate-nav's nested bullet list from (parts, page) pairs.

    Mirrors mkdocs_gen_files.Nav.build_literate_nav: a section line for every
    intermediate part the first time it appears, then the page, two spaces per
    depth.
    """
    lines: list[str] = []
    seen: set[tuple[str, ...]] = set()
    for parts, page in entries:
        for depth in range(1, len(parts)):
            section = parts[:depth]
            if section not in seen:
                seen.add(section)
                lines.append(f"{'    ' * (depth - 1)}* {section[-1]}\n")
        # A page also opens its section: the package index is the parent of its
        # modules, not a sibling of a second "fxhoudinimcp" heading.
        seen.add(parts)
        lines.append(f"{'    ' * (len(parts) - 1)}* [{parts[-1]}]({page})\n")
    return lines


def generate() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    wanted: set[Path] = set()
    entries: list[tuple[tuple[str, ...], str]] = []

    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        module_path = path.relative_to(ROOT / "python")
        doc_path = path.relative_to(SRC).with_suffix(".md")
        parts = tuple(module_path.with_suffix("").parts)

        if parts[-1] == "__init__":
            parts = parts[:-1]
            if not parts:
                continue
            doc_path = doc_path.with_name("index.md")
        if parts[-1] == "__main__":
            continue

        nav_parts = tuple(part.lstrip("_") for part in parts)
        entries.append((nav_parts, doc_path.as_posix()))

        target = OUT / doc_path
        target.parent.mkdir(parents=True, exist_ok=True)
        content = f"::: {'.'.join(parts)}\n"
        if not target.exists() or target.read_text(encoding="utf-8") != content:
            target.write_text(content, encoding="utf-8", newline="\n")
        wanted.add(target)

    summary = OUT / "SUMMARY.md"
    summary.write_text("".join(_nav_lines(entries)), encoding="utf-8", newline="\n")
    wanted.add(summary)

    # A module that was deleted or renamed must not leave a page behind that
    # mkdocstrings can no longer resolve.
    removed = 0
    for stale in OUT.rglob("*.md"):
        if stale not in wanted:
            stale.unlink()
            removed += 1

    print(f"technical docs: {len(entries)} pages written to {OUT.relative_to(ROOT)}", end="")
    print(f", {removed} stale removed" if removed else "")
    return 0


if __name__ == "__main__":
    sys.exit(generate())
