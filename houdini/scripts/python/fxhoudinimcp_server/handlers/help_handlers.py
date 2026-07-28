"""Documentation handlers for FXHoudini-MCP.

Full-text search and page retrieval over the documentation that Houdini
itself ships in $HFS/houdini/help (nodes, VEX, expressions, HOM,
Solaris, TOPs, character, general reference). Because everything is
read from the RUNNING Houdini's install, the docs are always
version-exact and need no network — and on builds that ship without
local help, the tools degrade into a clear error instead of guessing.
"""

from __future__ import annotations

# Built-in
import os
import zipfile
from difflib import get_close_matches
from typing import Any

# Third-party
import hou

# Internal
from fxhoudinimcp_server.dispatcher import register_handler

###### Corpus access

# Scopes are discovered from the install, not listed here. Houdini 22.0 ships 47
# help archives and a hardcoded nine served only 27.6 of 34.3 MB of text. What it
# left out was exactly the workflow documentation this server tells the assistant
# to read before improvising: pyro/, fluid/, vellum/, destruction/, model/,
# assets/, copy/ and the rest. Reading the directory also means a corpus SideFX
# adds in a later release is served without a code change.
#
# One entry per archive, so scope names are the archive stems: "pyro", "vellum".
#
# Not every corpus is zipped. Copernicus, MPM, heightfields and the machine
# learning docs ship as plain directories, so a zip-only loader could not reach
# COPs or MPM documentation at all, at any scope. Both layouts are read here.

# Directories under the help root that are not documentation. Serving them is
# not harmful but it is noise: the licence texts alone are 250 pages that match
# ordinary English words and would outrank real pages for common queries.
_NON_DOC_DIRS = frozenset({"files", "images", "videos", "licenses", "licensing"})

# scope -> {entry_path_without_ext: (original_text, lowercase_text)}
_CACHE: dict[str, dict[str, tuple[str, str]]] = {}


def _help_dir() -> str:
    """Help root of the running Houdini (separate function for tests)."""
    # hou.text.expandString, not hou.expandString: the latter is deprecated and
    # emits a DeprecationWarning on every call. Present since well before 20.5.
    return os.path.join(hou.text.expandString("$HFS"), "houdini", "help")


def _available_scopes() -> list[str]:
    """Every documentation corpus the install ships, zipped or loose."""
    root = _help_dir()
    if not os.path.isdir(root):
        return []
    scopes = set()
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if name.endswith(".zip") and os.path.isfile(path):
            scopes.add(name[:-4])
        # Only count a directory if it actually holds pages; several hold images
        # only, and an empty scope in the error message is just noise.
        elif (
            os.path.isdir(path)
            and name not in _NON_DOC_DIRS
            and any(file.endswith(".txt") for _, _, files in os.walk(path) for file in files)
        ):
            scopes.add(name)
    return sorted(scopes)


def _require_help() -> list[str]:
    scopes = _available_scopes()
    if not scopes:
        raise hou.OperationFailed(
            "This Houdini build ships no local help "
            f"({_help_dir()} contains no help archives). Use "
            "get_node_card for live node introspection, or consult "
            "https://www.sidefx.com/docs/houdini/ directly."
        )
    return scopes


def _read_zip(zip_path: str) -> dict[str, tuple[str, str]]:
    pages: dict[str, tuple[str, str]] = {}
    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():
            if not name.endswith(".txt"):
                continue
            text = archive.read(name).decode("utf-8", "replace")
            pages[name[:-4]] = (text, text.lower())
    return pages


def _read_dir(root: str) -> dict[str, tuple[str, str]]:
    """Same shape as _read_zip, for corpora that ship unzipped."""
    pages: dict[str, tuple[str, str]] = {}
    for dirpath, _, files in os.walk(root):
        for name in files:
            if not name.endswith(".txt"):
                continue
            full = os.path.join(dirpath, name)
            # Keys must match the zip convention: forward slashes, relative to
            # the corpus root, no extension. Otherwise a path from search_help
            # would not round-trip through get_help_page on Windows.
            entry = os.path.relpath(full, root).replace(os.sep, "/")[:-4]
            try:
                with open(full, "rb") as handle:
                    text = handle.read().decode("utf-8", "replace")
            except OSError:
                continue
            pages[entry] = (text, text.lower())
    return pages


def _load_scope(scope: str) -> dict[str, tuple[str, str]]:
    if scope in _CACHE:
        return _CACHE[scope]
    root = _help_dir()
    zip_path = os.path.join(root, f"{scope}.zip")
    dir_path = os.path.join(root, scope)
    if os.path.isfile(zip_path):
        pages = _read_zip(zip_path)
    elif os.path.isdir(dir_path):
        pages = _read_dir(dir_path)
    else:
        pages = {}
    _CACHE[scope] = pages
    return pages


def _title_of(text: str) -> str:
    for line in text.splitlines()[:5]:
        stripped = line.strip()
        if stripped.startswith("=") and stripped.endswith("="):
            return stripped.strip("= ").strip()
    return ""


def _excerpt(text: str, lower: str, token: str, width: int = 220) -> str:
    index = lower.find(token)
    if index < 0:
        index = 0
    start = max(0, index - width // 3)
    snippet = text[start : start + width].replace("\n", " ").strip()
    return ("..." if start else "") + snippet


###### help.search_help


def search_help(
    query: str,
    scope: str = None,
    limit: int = 10,
    **_: Any,
) -> dict:
    """Full-text search over the running Houdini's shipped documentation.

    All query words must appear in a page; pages are ranked by hit
    count with strong boosts for filename and title matches.

    Args:
        query: Search words (e.g. "pyro shaping", "pcfind", "ramp parameter").
        scope: Restrict to one corpus — nodes, vex, expressions, hom,
            solaris, tops, character, ref, shelf. Default: all.
        limit: Max results.
    """
    available = _require_help()
    tokens = [t for t in query.lower().split() if t]
    if not tokens:
        raise ValueError("query must contain at least one word")
    if scope is not None and scope not in available:
        raise ValueError(f"Unknown scope '{scope}'. Available: {available}")
    scopes = [scope] if scope else available

    hits: list[tuple[float, dict]] = []
    for scope_name in scopes:
        if scope_name not in available:
            continue
        for entry, (text, lower) in _load_scope(scope_name).items():
            counts = [lower.count(token) for token in tokens]
            if not all(counts):
                continue
            entry_lower = entry.lower()
            title = _title_of(text)
            title_lower = title.lower()
            score = float(sum(counts))
            score += 50.0 * sum(token in entry_lower for token in tokens)
            score += 20.0 * sum(token in title_lower for token in tokens)
            hits.append(
                (
                    score,
                    {
                        "path": f"{scope_name}/{entry}",
                        "title": title,
                        "score": round(score, 1),
                        "excerpt": _excerpt(text, lower, tokens[0]),
                    },
                )
            )

    hits.sort(key=lambda item: -item[0])
    return {
        "query": query,
        "scopes_searched": scopes,
        "total_matches": len(hits),
        "results": [hit for _, hit in hits[:limit]],
    }


register_handler("help.search_help", search_help)


###### help.get_help_page


def get_help_page(path: str, **_: Any) -> dict:
    """Fetch one documentation page by path (as returned by search_help).

    Args:
        path: "scope/entry", e.g. "nodes/sop/scatter", "vex/functions/noise",
            "expressions/ch". The .txt extension is optional.
    """
    _require_help()
    normalized = path.strip().strip("/")
    if normalized.endswith(".txt"):
        normalized = normalized[:-4]
    scope, _, entry = normalized.partition("/")
    if scope not in _available_scopes():
        raise ValueError(
            f"Unknown scope '{scope}'. Paths look like 'nodes/sop/scatter', "
            f"'vex/functions/noise' or 'pyro/lookdev'. Available scopes: "
            f"{_available_scopes()}"
        )
    pages = _load_scope(scope)
    if entry not in pages:
        lowered = {name.lower(): name for name in pages}
        actual = lowered.get(entry.lower())
        if actual is None:
            close = get_close_matches(entry, sorted(pages), n=5, cutoff=0.4)
            raise ValueError(f"No page '{entry}' in {scope}. Close matches: {close}")
        entry = actual

    text = pages[entry][0]
    _PAGE_CAP = 20_000
    truncated = len(text) > _PAGE_CAP
    return {
        "path": f"{scope}/{entry}",
        "title": _title_of(text),
        "length": len(text),
        "truncated": truncated,
        "text": text[:_PAGE_CAP],
    }


register_handler("help.get_help_page", get_help_page)
