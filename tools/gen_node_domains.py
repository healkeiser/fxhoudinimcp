"""Generate the whole node-domain section of server_instructions.md.

Every node name advertised to the assistant is derived here. Nothing in that
section is hand-written, so there is no half-curated, half-generated boundary for
a reader to guess at.

    python tools/gen_node_domains.py            # regenerate
    python tools/gen_node_domains.py --check    # fail if stale

Run it before tools/gen_node_versions.py: this writes the names, that annotates
the ones which do not exist across the whole supported range.

Sources, and why each:

* SideFX's shipped node help (``nodes.zip``) decides which names appear. It is
  the only signal available for "ships with Houdini": the installed node lists
  include whatever plugins are on the generating machine, and advertising one
  studio's Redshift or Octane nodes to every user would manufacture exactly the
  hallucinations this section exists to prevent. Verified: redshift:: and
  octane_ are absent from the help.
* ``#tags`` supply the grouping where SideFX populated them, which in practice
  means SOPs and DOPs. Elsewhere they are near-empty (3 tagged VOPs out of 1257,
  0 COPs, 0 SHOPs), so those contexts fall back to name stems usable as a
  ``filter=`` value, then to a flat list of names.
* ``tools/node_versions.json`` decides what exists at all, from the builds
  contributors have sampled.

Known limitation, stated in the generated text as well: the help documents 3974
nodes against 5566 installed on a full 22.0 install, so real stock nodes SideFX
never documented (surfacedeform, deflate, wrinkledeformer) are absent. The lists
are a floor, not an inventory, which is why the generated preamble points at
list_node_types and search_help.
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

_BEGIN = "<!-- BEGIN GENERATED: node domains -->"
_END = "<!-- END GENERATED: node domains -->"

# SideFX's help #context values mapped to hou node type categories, enumerated
# from the help rather than guessed: "obj" and "out" do not capitalise into
# "Object" and "Driver", which silently produced zero coverage for both.
_HELP_CONTEXT_TO_CATEGORY = {
    "sop": "Sop",
    "vop": "Vop",
    "dop": "Dop",
    "lop": "Lop",
    "cop": "Cop",
    "cop2": "Cop2",
    "chop": "Chop",
    "top": "Top",
    "shop": "Shop",
    "obj": "Object",
    "out": "Driver",
}

# The context= argument the tools take, where it differs from the category name.
_CONTEXT_ARG = {"Object": "Obj"}

_MIN_TYPES = 25
_MIN_TAG_MEMBERS = 4
_MIN_TAGS_TO_GROUP = 4
_MAX_TAGS = 20
_MAX_TAG_NAMES = 16
_MIN_STEM_MEMBERS = 3
_MAX_STEMS = 10
_MAX_STEM_EXAMPLES = 16
_MAX_FLAT_NAMES = 48
_STEM_LEN = 6

_INTERNAL = re.compile(r"^#internal:\s*(\S+)", re.M)
_CONTEXT = re.compile(r"^#context:\s*(\S+)", re.M)
_TAGS = re.compile(r"^#tags:\s*(.+)$", re.M)

# Only emit names test_instruction_accuracy_live can claim, so nothing is
# advertised without being verified. Internal capitals are allowed because
# MaterialX types are spelled mtlxLamaAdd; a lowercase first character is what
# keeps prose out of the claim set.
_VERIFIABLE = re.compile(r"[a-z][A-Za-z0-9_:.]*[A-Za-z0-9]$")


def _verifiable(name: str) -> bool:
    return bool(_VERIFIABLE.match(name)) and (
        "_" in name or "::" in name or len(name) >= 4
    )


def read_help(
    help_zip: Path,
) -> tuple[dict[str, set[str]], dict[str, dict[str, set[str]]]]:
    """Return (category -> documented names, category -> tag -> names)."""
    documented: dict[str, set[str]] = defaultdict(set)
    tagged: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

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
            if not category:
                continue
            name = internal.group(1)
            documented[category].add(name)
            tags = _TAGS.search(text)
            if tags:
                for tag in (part.strip() for part in tags.group(1).split(",")):
                    if tag:
                        tagged[category][tag].add(name)
    return documented, tagged


def existing_names(table: dict) -> set[str]:
    """"Category/name" keys any sampled build reported.

    Deliberately "any", not "every": a name that exists in only part of the range
    still belongs here, and tools/gen_node_versions.py marks it with a version
    range afterwards. Requiring presence everywhere would silently drop
    instancer, pointinstancer and layout, which are precisely the cases the
    version markers exist for.
    """
    return set(table["present"])


def _tag_lines(names: list[str], tagged: dict[str, set[str]]) -> list[str] | None:
    available = set(names)
    groups = {tag: sorted(members & available) for tag, members in tagged.items()}
    groups = {
        tag: found for tag, found in groups.items() if len(found) >= _MIN_TAG_MEMBERS
    }
    if len(groups) < _MIN_TAGS_TO_GROUP:
        return None

    lines = []
    for tag, found in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:_MAX_TAGS]:
        shown = found[:_MAX_TAG_NAMES]
        suffix = ", etc." if len(found) > len(shown) else ""
        lines.append(f"*   {tag}: {', '.join(shown)}{suffix}")
    return lines


def _stem_line(names: list[str]) -> str | None:
    members: dict[str, list[str]] = defaultdict(list)
    for name in names:
        match = re.match(r"[a-z]{3,}", name.split("::")[0])
        if match:
            members[match.group(0)[:_STEM_LEN]].append(name)

    counted = Counter({stem: len(found) for stem, found in members.items()})
    top = [
        stem
        for stem, count in counted.most_common(_MAX_STEMS)
        if count >= _MIN_STEM_MEMBERS
    ]
    if not top:
        return None
    filters = "|".join(f"'{stem}'" for stem in top)
    # Prefer a mixed-case member when the family has one: MaterialX types are
    # spelled mtlxLamaAdd, and always taking the alphabetically first name hid
    # that spelling from both the assistant and the verifier.
    examples = []
    for stem in top[:_MAX_STEM_EXAMPLES]:
        family = sorted(members[stem])
        mixed = next((n for n in family if any(c.isupper() for c in n)), None)
        examples.append(mixed or family[0])
    # The leading label matters: test_instruction_accuracy_live reads names from
    # after the first ":" on a bullet, so a colon-less line advertises names it
    # never verifies. That silently left Vop, Cop, Cop2, Chop and Shop unchecked.
    return f"*   Name prefixes: filter={filters} — e.g. {', '.join(examples)}"


def build_block(
    documented: dict[str, set[str]],
    tagged: dict[str, dict[str, set[str]]],
    existing: set[str],
) -> str:
    lines = [
        "Generated by `tools/gen_node_domains.py` from Houdini's own shipped node",
        "help. Do not hand-edit.",
        "",
        "These lists are a floor, not an inventory: SideFX documents fewer nodes",
        "than ship, and a plugin your studio installs is never listed. Call",
        "`list_node_types(context, filter)` to see what is actually loaded, and",
        "`search_help(query)` to find a node by what it does rather than by name.",
        "",
        "A name followed by a version range exists only in those Houdini versions,",
        "within the 20.5-22.0 range this server supports: `colorcorrect (21.0+)` is",
        "absent before 21.0, and `instancer (20.5-21.0)` is gone from 22.0 onward.",
        "Unannotated names exist throughout. Check `get_scene_info` for the running",
        "version before relying on an annotated name.",
    ]

    def stock(category: str) -> list[str]:
        return sorted(
            name
            for name in documented[category]
            if f"{category}/{name}" in existing and _verifiable(name)
        )

    for category in sorted(documented, key=lambda c: -len(stock(c))):
        names = stock(category)
        if len(names) < _MIN_TYPES:
            continue

        context = _CONTEXT_ARG.get(category, category)
        lines.append("")
        lines.append(f"### {category} (context='{context}', {len(names)} documented)")
        lines.append("")

        grouped = _tag_lines(names, tagged.get(category, {}))
        if grouped:
            lines.extend(grouped)
            continue

        stem = _stem_line(names)
        if stem:
            lines.append(stem)
            continue

        shown = names[:_MAX_FLAT_NAMES]
        suffix = ", etc." if len(names) > len(shown) else ""
        lines.append(f"*   Types: {', '.join(shown)}{suffix}")

    return "\n".join(lines)


def _newest_help_zip() -> Path | None:
    sys.path.insert(0, str(REPO_ROOT / "tests"))
    from run_integration import find_all_hython  # noqa: E402

    for hython in find_all_hython():
        # Walk up rather than index a fixed depth: the interpreter is at
        # <install>/bin on Windows and Linux but six levels into the framework
        # bundle on macOS.
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

    documented, tagged = read_help(help_zip)
    existing = existing_names(json.loads(_TABLE.read_text(encoding="utf-8")))
    block = build_block(documented, tagged, existing)

    text = _INSTRUCTIONS.read_text(encoding="utf-8")
    if _BEGIN not in text or _END not in text:
        print(
            f"Markers missing from {_INSTRUCTIONS.relative_to(REPO_ROOT)}.\n"
            f"    {_BEGIN}\n    {_END}"
        )
        return 1

    start = text.index(_BEGIN) + len(_BEGIN)
    end = text.index(_END)
    updated = text[:start] + "\n" + block + "\n" + text[end:]

    print(f"help source : {help_zip}")
    print(f"contexts    : {block.count(chr(10) + '### ')}")
    print(f"block size  : {len(block)} bytes")

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
