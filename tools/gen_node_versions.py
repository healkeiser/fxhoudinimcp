"""Generate the node-availability table and rewrite the version annotations.

server_instructions.md advertises node type names to the assistant. Some exist
only in part of the supported range: Houdini 21 added most of Copernicus, and
22 renamed the LOP ``instancer`` to ``pointinstancer`` and dropped ``layout``.
Hand-maintaining those markers does not survive a release, so this derives them.

    python tools/gen_node_versions.py            # regenerate, write files
    python tools/gen_node_versions.py --check    # fail if anything is stale

The authoritative signal is presence: every installed Houdini is asked for its
own node type list, and the lists are diffed. That catches removals, which
SideFX's ``#since`` metadata never records, and it covers every node rather
than the ~63% that carry ``#since``. ``#since`` is kept alongside as
corroboration and to describe versions that are not installed locally.

Annotations are only as good as the builds sampled. A name is reported as
present in a minor series only when every sampled build of that series has it,
and a series with a single sampled build is flagged in the JSON so a reader can
see how thin the evidence is.
"""

from __future__ import annotations

# Built-in
import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_INSTRUCTIONS = (
    REPO_ROOT / "python" / "fxhoudinimcp" / "prompts" / "markdown"
    / "server_instructions.md"
)
_TABLE = Path(__file__).resolve().parent / "node_versions.json"
_DUMPER = Path(__file__).resolve().parent / "dump_node_types.py"

# Categories the instructions have sections for. Names outside these are in the
# table but never annotated, because nothing advertises them.
_SECTIONS = {
    "### SOPs": "Sop",
    "### LOPs": "Lop",
    "### DOPs": "Dop",
    "### COPs": "Cop",
    "### CHOPs": "Chop",
    "### TOPs": "Top",
}

# A previously generated annotation, so regeneration is idempotent. Deliberately
# narrow: prose parentheses like "(handles payloads)" must survive untouched.
_ANNOTATION = re.compile(r"\s*\((\d+\.\d+)(?:\+|-\d+\.\d+)\)")

# The same, but capturing the name it belongs to. Used so a name that only
# appears inside prose still counts as a claim and keeps its marker across a
# regeneration, instead of being silently stripped.
_ANNOTATED_NAME = re.compile(
    r"([a-z][a-z0-9_:.]*[a-z0-9])\s*\((\d+\.\d+)(?:\+|-\d+\.\d+)\)"
)

# Red Giant's OpenFX plug-in crashes hou initialisation on 20.5.487 and later,
# so hython cannot even import hou while it is scanned. Nothing to do with this
# repo, but the dump has to survive it on machines that have Universe installed.
_CHILD_ENV = {"HOUDINI_DISABLE_OPENFX_DEFAULT_PATH": "1"}


def _hythons() -> list[Path]:
    sys.path.insert(0, str(REPO_ROOT / "tests"))
    from run_integration import find_all_hython  # noqa: E402

    return find_all_hython()


def _dump(hython: Path) -> dict | None:
    """Ask one Houdini build for its node types."""
    env = os.environ.copy()
    env.update(_CHILD_ENV)
    try:
        completed = subprocess.run(
            [str(hython), str(_DUMPER)],
            capture_output=True,
            text=True,
            env=env,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        print(f"  ! timed out: {hython}")
        return None

    # hython prints licence and plug-in chatter around our JSON -- Redshift and
    # Universe both announce themselves, and some builds do it *after* the
    # payload. raw_decode stops at the end of the object and ignores the rest,
    # where json.loads would reject the trailing text and lose the build.
    start = completed.stdout.find('{"version"')
    if start < 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        print(f"  ! no JSON from {hython}: {detail[-1] if detail else 'no output'}")
        return None
    try:
        payload, _ = json.JSONDecoder().raw_decode(completed.stdout[start:])
        return payload
    except json.JSONDecodeError as exc:
        print(f"  ! unparseable JSON from {hython}: {exc}")
        return None


def _series(version_tuple: list[int]) -> str:
    return f"{version_tuple[0]}.{version_tuple[1]}"


def build_table(dumps: list[dict]) -> dict:
    """Collapse per-build node lists into per-series availability."""
    builds_by_series: dict[str, list[str]] = defaultdict(list)
    for dump in dumps:
        builds_by_series[_series(dump["version_tuple"])].append(dump["version"])

    # category/name -> series -> present in every sampled build of that series
    present: dict[str, dict[str, bool]] = defaultdict(dict)
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for dump in dumps:
        series = _series(dump["version_tuple"])
        for category, names in dump["node_types"].items():
            for name in names:
                counts[f"{category}/{name}"][series] += 1

    for key, per_series in counts.items():
        for series, seen in per_series.items():
            present[key][series] = seen == len(builds_by_series[series])

    since: dict[str, str] = {}
    for dump in dumps:
        since.update(dump.get("since") or {})

    ordered = sorted(builds_by_series, key=lambda s: tuple(int(p) for p in s.split(".")))
    return {
        "series": ordered,
        "builds": {series: sorted(b) for series, b in builds_by_series.items()},
        "thin_evidence": [s for s in ordered if len(builds_by_series[s]) == 1],
        "availability": {
            key: {series: per.get(series, False) for series in ordered}
            for key, per in sorted(present.items())
        },
        "since": since,
    }


def annotation_for(availability: dict[str, bool], series: list[str]) -> str | None:
    """Return "(21.0+)", "(20.5-21.0)", or None when present throughout.

    Returns None for anything that is not a clean prefix or suffix of the
    sampled range; a gap means the annotation syntax cannot express it and a
    person needs to look.
    """
    flags = [availability.get(s, False) for s in series]
    if all(flags):
        return None
    if not any(flags):
        return None  # absent everywhere: not an annotation problem

    first, last = flags.index(True), len(flags) - 1 - flags[::-1].index(True)
    if not all(flags[first : last + 1]):
        return None  # gap in the middle
    if last == len(flags) - 1:
        return f"({series[first]}+)"
    return f"({series[first]}-{series[last]})"


def _markdown_names(text: str) -> list[tuple[str, str]]:
    """Every (category, name) the instructions advertise, in file order."""
    claims: list[tuple[str, str]] = []
    category = None
    for line in text.splitlines():
        if line.startswith("### "):
            category = next(
                (cat for prefix, cat in _SECTIONS.items() if line.startswith(prefix)),
                None,
            )
            continue
        if category is None or not line.startswith("*"):
            continue
        _, _, tail = line.partition(":")
        unescaped = tail.replace("\\_", "_")

        # Anything already annotated is a claim wherever it sits, including mid
        # sentence, so regenerating does not drop a marker it just stripped.
        for match in _ANNOTATED_NAME.finditer(unescaped):
            claims.append((category, match.group(1)))

        tail = _ANNOTATION.sub("", unescaped)
        tail = re.sub(r"\([^)]*\)", "", tail)
        for chunk in re.split(r"[,—.]", tail):
            token = chunk.strip()
            if re.fullmatch(r"[a-z][a-z0-9_:.]*[a-z0-9]", token) and (
                "_" in token or "::" in token or len(token) >= 4
            ):
                claims.append((category, token))

    # A name reached both branches above when it already carried a marker, so
    # de-duplicate while keeping file order.
    return list(dict.fromkeys(claims))


def rewrite_instructions(text: str, table: dict) -> tuple[str, list[str], list[str]]:
    """Strip old annotations and write the derived ones back in."""
    series = table["series"]
    availability = table["availability"]
    applied: list[str] = []
    unexpressible: list[str] = []

    wanted: dict[str, str] = {}
    for category, name in _markdown_names(text):
        entry = availability.get(f"{category}/{name}")
        if entry is None:
            continue
        marker = annotation_for(entry, series)
        if marker:
            wanted[name] = marker
            applied.append(f"{category}/{name} {marker}")
        elif not all(entry.get(s, False) for s in series) and any(
            entry.get(s, False) for s in series
        ):
            unexpressible.append(f"{category}/{name} {entry}")

    out_lines: list[str] = []
    category = None
    for line in text.splitlines():
        if line.startswith("### "):
            category = next(
                (cat for prefix, cat in _SECTIONS.items() if line.startswith(prefix)),
                None,
            )
            out_lines.append(line)
            continue
        if category is None or not line.startswith("*"):
            out_lines.append(line)
            continue

        head, sep, tail = line.partition(":")
        tail = _ANNOTATION.sub("", tail)
        for name, marker in wanted.items():
            # ``\_`` escapes in the markdown mean the literal name may be
            # spelled with backslashes, so allow one before each underscore.
            escaped = re.escape(name).replace("_", r"\\?_")
            # count=1: a name can legitimately appear again in prose on the same
            # line ("layout ... the layout LOP is gone"), and annotating the
            # sentence occurrence would mangle it. The list position comes first.
            tail = re.sub(
                r"(?<![a-z0-9_\\])(" + escaped + r")(?![a-z0-9_])",
                r"\1 " + marker,
                tail,
                count=1,
            )
        out_lines.append(head + sep + tail)

    return "\n".join(out_lines) + "\n", sorted(applied), sorted(unexpressible)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit non-zero if the committed files are stale",
    )
    args = parser.parse_args()

    hythons = _hythons()
    if len(hythons) < 2:
        print(
            f"Found {len(hythons)} Houdini install(s). Diffing needs at least two "
            "to say anything about availability."
        )
        return 1

    print(f"Sampling {len(hythons)} Houdini installs:")
    dumps = []
    for hython in hythons:
        dump = _dump(hython)
        if dump is None:
            continue
        total = sum(len(v) for v in dump["node_types"].values())
        print(
            f"  {dump['version']:<12} {total:>5} node types, "
            f"{len(dump.get('since') or {})} with #since"
        )
        dumps.append(dump)

    if len(dumps) < 2:
        print("Fewer than two builds responded; refusing to guess.")
        return 1

    table = build_table(dumps)
    text = _INSTRUCTIONS.read_text(encoding="utf-8")
    new_text, applied, unexpressible = rewrite_instructions(text, table)

    print(f"\nseries sampled : {table['series']}")
    if table["thin_evidence"]:
        print(f"single-build   : {table['thin_evidence']} (weaker evidence)")
    print(f"annotations     : {len(applied)}")
    for item in applied:
        print(f"    {item}")

    # Corroborate the derived lower bound against SideFX's own #since, purely as
    # a report. They disagree legitimately: #since records when a node first
    # appeared anywhere in Houdini's history, which can predate the oldest build
    # sampled here, and it never records a removal. Presence stays authoritative.
    agreed, disagreed, absent = 0, [], 0
    for item in applied:
        key = item.split(" ", 1)[0]
        derived = item.split("(", 1)[1].rstrip(")").split("-")[0].rstrip("+")
        documented = table["since"].get(key)
        if documented is None:
            absent += 1
        elif documented == derived:
            agreed += 1
        else:
            disagreed.append(f"{key}: derived {derived}, #since {documented}")
    print(
        f"\n#since check    : {agreed} corroborated, {len(disagreed)} differ, "
        f"{absent} undocumented"
    )
    for item in disagreed:
        print(f"    {item}  (expected when the node predates the oldest build sampled)")
    if unexpressible:
        print(f"\nNOT expressible as a range, look at these {len(unexpressible)}:")
        for item in unexpressible:
            print(f"    {item}")

    new_table = json.dumps(table, indent=2, sort_keys=True) + "\n"
    if args.check:
        stale = []
        if not _TABLE.is_file() or _TABLE.read_text(encoding="utf-8") != new_table:
            stale.append(str(_TABLE.relative_to(REPO_ROOT)))
        if new_text != text:
            stale.append(str(_INSTRUCTIONS.relative_to(REPO_ROOT)))
        if stale:
            print(
                "\nSTALE: " + ", ".join(stale)
                + "\nRun: python tools/gen_node_versions.py"
            )
            return 1
        print("\nUp to date.")
        return 0

    _TABLE.write_text(new_table, encoding="utf-8")
    if new_text != text:
        _INSTRUCTIONS.write_text(new_text, encoding="utf-8")
        print(f"\nrewrote {_INSTRUCTIONS.relative_to(REPO_ROOT)}")
    else:
        print(f"\n{_INSTRUCTIONS.relative_to(REPO_ROOT)} already correct")
    print(f"wrote   {_TABLE.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
