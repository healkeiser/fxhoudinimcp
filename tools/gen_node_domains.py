"""Generate search hints for the node contexts nobody had written up.

The hand-written "COMMONLY MISSED NODE DOMAINS" lists cover six contexts. The
other categories had no entry at all, and Vop is the second largest in Houdini:

    Vop 1501, Data 539, Object 237, Shop 230, Cop2 178, Driver 99

That is a large fraction of Houdini invisible to the assistant. Writing those
lists by hand would be the same curation problem one level down, and worse here,
since picking which of 1501 VOPs to mention is pure editorial judgement. So this
derives them.

    python tools/gen_node_domains.py            # regenerate
    python tools/gen_node_domains.py --check    # fail if stale

Two sources, intersected:

* SideFX's shipped node help, for what is *stock*. The installed node lists
  include whatever plugins happen to be on the generating machine, and advertising
  another studio's Redshift or Octane nodes to every user would be wrong.
  Verified: redshift:: and octane_ nodes are absent from SideFX's help.
* tools/node_versions.json, for what actually *exists* across the sampled
  builds. Only names present in every sampled series are emitted, so generated
  hints never need a version annotation.

What gets emitted is a usable ``filter=`` value plus real node names, because
``list_node_types(context, filter)`` matches names and labels rather than SideFX's
help tags. Advertising a tag would send the assistant looking for something the
filter cannot find.
"""

from __future__ import annotations

# Built-in
import argparse
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_INSTRUCTIONS = (
    REPO_ROOT / "python" / "fxhoudinimcp" / "prompts" / "markdown"
    / "server_instructions.md"
)
_TABLE = Path(__file__).resolve().parent / "node_versions.json"

_BEGIN = "<!-- BEGIN GENERATED: additional node contexts -->"
_END = "<!-- END GENERATED: additional node contexts -->"

# SideFX's help #context values mapped to hou node type categories. Enumerated
# from the shipped help rather than guessed: "obj" and "out" do not capitalise
# into "Object" and "Driver", which silently produced zero coverage for both.
_HELP_CONTEXT_TO_CATEGORY = {
    "vop": "Vop",
    "sop": "Sop",
    "dop": "Dop",
    "shop": "Shop",
    "lop": "Lop",
    "cop2": "Cop2",
    "cop": "Cop",
    "chop": "Chop",
    "obj": "Object",
    "out": "Driver",
    "top": "Top",
}

# Categories the hand-written sections already cover; these are left alone.
_ALREADY_COVERED = {"Sop", "Lop", "Dop", "Cop", "Chop", "Top"}

# The context= argument each category needs, which is not always the category
# name: hou calls them Object and Driver, the tools take Obj and Driver.
_CONTEXT_ARG = {"Object": "Obj", "Driver": "Driver"}

_MIN_TYPES = 25  # below this a context is not worth a line
_MIN_STEM_MEMBERS = 3
_MAX_STEMS = 10
_MAX_NAMES = 6
_STEM_LEN = 6

# Some contexts have no naming families at all: Cop2 and Driver names are
# diverse single words (colorcorrect, blend / geometry, alembic, karma), so
# stem-grouping finds nothing and the names themselves are the vocabulary.
_MAX_FLAT_NAMES = 24

_INTERNAL = re.compile(r"^#internal:\s*(\S+)", re.M)
_CONTEXT = re.compile(r"^#context:\s*(\S+)", re.M)

# Only emit names test_instruction_accuracy_live can actually claim, so nothing
# is advertised without being verified. Its pattern allows internal capitals,
# because MaterialX types are spelled mtlxLamaAdd and dropping them would hide a
# whole shading family; it still requires a lowercase first character, which is
# what keeps prose out.
_VERIFIABLE = re.compile(r"[a-z][A-Za-z0-9_:.]*[A-Za-z0-9]$")


def _verifiable(name: str) -> bool:
    return bool(_VERIFIABLE.match(name)) and ("_" in name or "::" in name or len(name) >= 4)


def documented_nodes(help_zip: Path) -> dict[str, set[str]]:
    """Category -> node names SideFX documents, i.e. the stock ones."""
    found: dict[str, set[str]] = defaultdict(set)
    with zipfile.ZipFile(help_zip) as archive:
        for entry in archive.namelist():
            if not entry.endswith(".txt"):
                continue
            text = archive.read(entry).decode("utf-8", "replace")
            if "#type: node" not in text:
                continue
            internal, context = _INTERNAL.search(text), _CONTEXT.search(text)
            if not (internal and context):
                continue
            category = _HELP_CONTEXT_TO_CATEGORY.get(context.group(1))
            if category:
                found[category].add(internal.group(1))
    return found


def present_everywhere(table: dict) -> dict[str, set[str]]:
    """Category -> names present in every sampled series.

    Restricting to names that exist throughout keeps generated hints free of
    version annotations, which the annotation generator would otherwise have to
    add to text it does not own.
    """
    builds_by_series: dict[str, set[str]] = defaultdict(set)
    for build, series in table["builds"].items():
        builds_by_series[series].add(build)

    everywhere: dict[str, set[str]] = defaultdict(set)
    for key, builds in table["present"].items():
        seen = set(builds)
        if all(series_builds <= seen for series_builds in builds_by_series.values()):
            category, _, name = key.partition("/")
            everywhere[category].add(name)
    return everywhere


def _stems(names: list[str]) -> list[tuple[str, list[str]]]:
    """Group names by a leading-letters stem usable as a `filter=` value."""
    members: dict[str, list[str]] = defaultdict(list)
    for name in names:
        match = re.match(r"[a-z]{3,}", name.split("::")[0])
        if match:
            members[match.group(0)[:_STEM_LEN]].append(name)

    counted = Counter({stem: len(found) for stem, found in members.items()})
    return [
        (stem, sorted(members[stem]))
        for stem, count in counted.most_common(_MAX_STEMS)
        if count >= _MIN_STEM_MEMBERS
    ]


def build_block(documented: dict[str, set[str]], everywhere: dict[str, set[str]]) -> str:
    # A heading per context, so test_instruction_accuracy_live verifies these
    # names per Houdini version exactly as it does the hand-written sections.
    # Generated coverage that nothing checks would be worth little.
    lines = [
        "Counts are stock nodes only: a plugin your studio installs will not",
        "appear here, so use `list_node_types` to see everything actually loaded.",
    ]
    for category in sorted(
        documented, key=lambda c: -len(documented[c] & everywhere.get(c, set()))
    ):
        if category in _ALREADY_COVERED:
            continue
        stock = sorted(documented[category] & everywhere.get(category, set()))
        if len(stock) < _MIN_TYPES:
            continue

        context = _CONTEXT_ARG.get(category, category)
        lines.append("")
        lines.append(f"### {category} (context='{context}')")
        lines.append("")

        grouped = _stems(stock)
        if grouped:
            filters = "|".join(f"'{stem}'" for stem, _ in grouped)
            examples = []
            for _, found in grouped:
                usable = next((n for n in found if _verifiable(n)), None)
                if usable:
                    examples.append(usable)
            examples = examples[:_MAX_NAMES]
            lines.append(
                f"*   {len(stock)} stock types: filter={filters} "
                f"— e.g. {', '.join(examples)}"
            )
            continue

        # No naming families, so list the names instead: they are the vocabulary.
        shown = [n for n in stock if _verifiable(n)][:_MAX_FLAT_NAMES]
        suffix = ", etc." if len(stock) > len(shown) else ""  # count is of all stock
        lines.append(f"*   {len(stock)} stock types: {', '.join(shown)}{suffix}")
    return "\n".join(lines)


def _newest_help_zip() -> Path | None:
    sys.path.insert(0, str(REPO_ROOT / "tests"))
    from run_integration import find_all_hython  # noqa: E402

    for hython in find_all_hython():
        # Walk up rather than index a fixed depth: the interpreter sits at
        # <install>/bin on Windows and Linux but six levels down inside the
        # framework bundle on macOS, and a hardcoded index silently found
        # nothing.
        for parent in hython.parents:
            candidate = parent / "houdini" / "help" / "nodes.zip"
            if candidate.is_file():
                return candidate
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if stale")
    args = parser.parse_args()

    help_zip = _newest_help_zip()
    if help_zip is None:
        print("No Houdini node help found; cannot tell stock nodes from plugins.")
        return 1
    if not _TABLE.is_file():
        print(
            f"{_TABLE.relative_to(REPO_ROOT)} is missing. Run "
            "tools/gen_node_versions.py first."
        )
        return 1

    documented = documented_nodes(help_zip)
    everywhere = present_everywhere(json.loads(_TABLE.read_text(encoding="utf-8")))
    block = build_block(documented, everywhere)

    text = _INSTRUCTIONS.read_text(encoding="utf-8")
    if _BEGIN not in text or _END not in text:
        print(
            f"Markers missing from {_INSTRUCTIONS.relative_to(REPO_ROOT)}.\n"
            f"Add these two lines where the generated block belongs:\n"
            f"    {_BEGIN}\n    {_END}"
        )
        return 1

    start = text.index(_BEGIN) + len(_BEGIN)
    end = text.index(_END)
    updated = text[:start] + "\n" + block + "\n" + text[end:]

    print(f"help source : {help_zip}")
    print(block)

    if args.check:
        if updated != text:
            print(
                f"\nSTALE: {_INSTRUCTIONS.relative_to(REPO_ROOT)}\n"
                "Run: python tools/gen_node_domains.py"
            )
            return 1
        print("\nUp to date.")
        return 0

    if updated != text:
        _INSTRUCTIONS.write_text(updated, encoding="utf-8")
        print(f"\nrewrote {_INSTRUCTIONS.relative_to(REPO_ROOT)}")
    else:
        print(f"\n{_INSTRUCTIONS.relative_to(REPO_ROOT)} already correct")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
