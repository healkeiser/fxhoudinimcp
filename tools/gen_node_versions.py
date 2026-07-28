"""Generate the node-availability table and rewrite the version annotations.

server_instructions.md advertises node type names to the assistant. Some exist
only in part of the supported range: Houdini 21 added most of Copernicus, and
22 renamed the LOP ``instancer`` to ``pointinstancer`` and dropped ``layout``.
Hand-maintaining those markers does not survive a release, so this derives them.

    python tools/gen_node_versions.py            # contribute this machine, regenerate
    python tools/gen_node_versions.py --check    # verify the committed table here

The table accumulates. ``node_versions.json`` records which builds have been
sampled and which node types each one had, so a contributor with a single
Houdini installed adds their build to the shared evidence and still gets correct
annotations from everything sampled before them. Nobody needs six installs.

The authoritative signal is presence: each Houdini is asked for its own node
type list, and the lists are diffed. That catches removals, which SideFX's
``#since`` metadata never records, and it covers every node rather than the
~63% carrying ``#since``. ``#since`` is kept alongside as corroboration.

Annotations are only as good as the builds sampled. A name counts as present in
a minor series only when every sampled build of that series has it, and series
resting on a single build are flagged so a reader can see how thin the evidence
is. A range bounded by the oldest sampled build says nothing about Houdini
versions older than that.
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
    REPO_ROOT
    / "python"
    / "fxhoudinimcp"
    / "prompts"
    / "markdown"
    / "instructions"
    / "server_instructions.md"
)
# The full evidence: every sampled build and the node types it had. Big,
# diffable, and deliberately NOT shipped -- nothing at runtime reads it.
_TABLE = Path(__file__).resolve().parent / "node_versions.json"

# What does ship: only which versions have been sampled, so the server can warn
# that a Houdini nobody has checked may have stale version markers. Derived from
# _TABLE and kept separate because the evidence is ~1 MB against a few hundred
# bytes here, and there is no reason to put the former in every install.
_SAMPLED = REPO_ROOT / "python" / "fxhoudinimcp" / "data" / "sampled_versions.json"
_DUMPER = Path(__file__).resolve().parent / "dump_node_types.py"

# Categories the instructions have sections for. Names outside these are in the
# table but never annotated, because nothing advertises them.
# Headings emitted by tools/gen_node_domains.py, e.g. "### Sop (context='Sop',
# 663 documented)". These must track that generator: they previously read
# "### SOPs" and silently matched nothing after the section became generated,
# which produced zero annotations and looked like there was nothing to annotate.
_SECTIONS = {
    "### Sop": "Sop",
    "### Lop": "Lop",
    "### Dop": "Dop",
    "### Cop2": "Cop2",
    "### Cop": "Cop",
    "### Chop": "Chop",
    "### Top": "Top",
    "### Vop": "Vop",
    "### Shop": "Shop",
    "### Object": "Object",
    "### Driver": "Driver",
}

# A previously generated annotation, so regeneration is idempotent. Deliberately
# narrow: prose parentheses like "(handles payloads)" must survive untouched.
_ANNOTATION = re.compile(r"\s*\((\d+\.\d+)(?:\+|-\d+\.\d+)\)")

# The same, but capturing the name it belongs to. Used so a name that only
# appears inside prose still counts as a claim and keeps its marker across a
# regeneration, instead of being silently stripped.
_ANNOTATED_NAME = re.compile(r"([a-z][a-z0-9_:.]*[a-z0-9])\s*\((\d+\.\d+)(?:\+|-\d+\.\d+)\)")

# Red Giant's OpenFX plug-in crashes hou initialisation on 20.5.487 and later,
# so hython cannot even import hou while it is scanned. Nothing to do with this
# repo, but the dump has to survive it on machines that have Universe installed.
_CHILD_ENV = {"HOUDINI_DISABLE_OPENFX_DEFAULT_PATH": "1"}


###### Sampling


def _hythons() -> list[Path]:
    """Every installed hython, or just $HYTHON when it is set.

    Honouring HYTHON matches tests/run_integration.py and lets a contributor
    sample one specific build deliberately.
    """
    override = os.environ.get("HYTHON")
    if override:
        candidate = Path(override)
        if not candidate.is_file():
            print(f"HYTHON is set but does not exist: {override}")
            return []
        return [candidate]

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


def _series_of(version_tuple: list[int]) -> str:
    return f"{version_tuple[0]}.{version_tuple[1]}"


def _series_key(series: str) -> tuple[int, ...]:
    return tuple(int(part) for part in series.split("."))


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version))


###### The accumulated table


def load_table() -> dict:
    if not _TABLE.is_file():
        return {"builds": {}, "present": {}, "since": {}}
    table = json.loads(_TABLE.read_text(encoding="utf-8"))
    table.setdefault("builds", {})
    table.setdefault("present", {})
    table.setdefault("since", {})
    table.setdefault("deprecated", {})
    table.setdefault("aliases", {})
    return table


def merge(table: dict, dumps: list[dict]) -> dict:
    """Fold this machine's builds into the accumulated evidence.

    Re-sampling a build already in the table replaces its column rather than
    adding to it, so a corrected dump supersedes a stale one.
    """
    builds = dict(table["builds"])
    present: dict[str, set[str]] = {key: set(values) for key, values in table["present"].items()}
    since = dict(table["since"])
    deprecated = dict(table.get("deprecated") or {})
    aliases = dict(table.get("aliases") or {})

    for dump in dumps:
        build = dump["version"]
        builds[build] = _series_of(dump["version_tuple"])
        # Drop any previous record of this build before re-adding it.
        for values in present.values():
            values.discard(build)
        for category, names in dump["node_types"].items():
            for name in names:
                present.setdefault(f"{category}/{name}", set()).add(build)

        # Keep the earliest version any build documents, not whichever was
        # merged last. Builds disagree (a node's help page can be rewritten),
        # and last-write-wins would make the committed file depend on the order
        # contributors happened to sample in.
        for key, value in (dump.get("since") or {}).items():
            prior = since.get(key)
            if prior is None or _version_key(value) < _version_key(prior):
                since[key] = value

        # Kept per build rather than merged: a node deprecated in 22.0 was
        # perfectly current in 20.5, and collapsing the two would misreport the
        # older version. Same for renames, which happen at a specific release.
        deprecated[build] = sorted(dump.get("deprecated") or [])
        aliases[build] = dict(sorted((dump.get("aliases") or {}).items()))

    # A name nothing has ever reported is dead weight.
    present = {key: values for key, values in present.items() if values}

    return {
        "builds": dict(sorted(builds.items())),
        "present": {key: sorted(values) for key, values in sorted(present.items())},
        "since": dict(sorted(since.items())),
        "deprecated": dict(sorted(deprecated.items())),
        "aliases": dict(sorted(aliases.items())),
    }


def availability(table: dict) -> tuple[list[str], dict[str, dict[str, bool]]]:
    """Collapse per-build evidence into per-series presence.

    A series is only credited when every sampled build of that series has the
    name, so one build lagging a release does not create a false positive.
    """
    builds_by_series: dict[str, list[str]] = defaultdict(list)
    for build, series in table["builds"].items():
        builds_by_series[series].append(build)

    series = sorted(builds_by_series, key=_series_key)
    result: dict[str, dict[str, bool]] = {}
    for key, builds in table["present"].items():
        seen = set(builds)
        result[key] = {
            name: all(build in seen for build in builds_by_series[name]) for name in series
        }
    return series, result


def thin_evidence(table: dict) -> list[str]:
    counts: dict[str, int] = defaultdict(int)
    for series in table["builds"].values():
        counts[series] += 1
    return sorted((s for s, n in counts.items() if n == 1), key=_series_key)


def annotation_for(per_series: dict[str, bool], series: list[str]) -> str | None:
    """Return "(21.0+)", "(20.5-21.0)", or None when present throughout.

    Returns None for anything that is not a clean prefix or suffix of the
    sampled range; a gap means the annotation syntax cannot express it and a
    person needs to look.
    """
    flags = [per_series.get(name, False) for name in series]
    if all(flags) or not any(flags):
        return None

    first, last = flags.index(True), len(flags) - 1 - flags[::-1].index(True)
    if not all(flags[first : last + 1]):
        return None  # gap in the middle
    if last == len(flags) - 1:
        return f"({series[first]}+)"
    return f"({series[first]}-{series[last]})"


def _write_table(merged: dict) -> None:
    """Persist the evidence, and the small summary that ships with the package."""
    _TABLE.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _SAMPLED.parent.mkdir(parents=True, exist_ok=True)
    _SAMPLED.write_text(
        json.dumps(
            {
                "builds": merged["builds"],
                "series": sorted(set(merged["builds"].values()), key=_series_key),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


###### The instructions


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
    series, avail = availability(table)
    applied: list[str] = []
    unexpressible: list[str] = []

    # Keyed by (category, name), not name alone: several names exist in more than
    # one category with different histories -- testgeometry_capybara is 22.0+ as a
    # COP but has been a SOP since 20.5. Keying by name applied the COP's marker
    # to the SOP line, telling the model a node it can use is unavailable.
    wanted: dict[tuple[str, str], str] = {}
    for category, name in _markdown_names(text):
        per_series = avail.get(f"{category}/{name}")
        if per_series is None:
            continue
        marker = annotation_for(per_series, series)
        if marker:
            wanted[(category, name)] = marker
            applied.append(f"{category}/{name} {marker}")
        elif not all(per_series.get(s, False) for s in series) and any(
            per_series.get(s, False) for s in series
        ):
            unexpressible.append(f"{category}/{name} {per_series}")

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
        for (name_category, name), marker in wanted.items():
            if name_category != category:
                continue
            # ``\_`` escapes in the markdown mean the literal name may be
            # spelled with backslashes, so allow one before each underscore.
            escaped = re.escape(name).replace("_", r"\\?_")
            # count=1: a name can legitimately appear again in prose on the same
            # line ("layout ... the layout LOP is gone"), and annotating the
            # sentence occurrence would mangle it. The list position comes first.
            #
            # The quote exclusions skip the "Name prefixes: filter='pyro'|..."
            # tokens, which are six-character prefixes rather than node names. A
            # prefix that happens to spell a whole name ('camera') otherwise
            # swallowed the count=1 substitution, producing the meaningless
            # "'camera (22.0+)'" and leaving the actual example unannotated.
            tail = re.sub(
                r"(?<![a-z0-9_\\'])(" + escaped + r")(?![a-z0-9_'])",
                r"\1 " + marker,
                tail,
                count=1,
            )
        out_lines.append(head + sep + tail)

    return "\n".join(out_lines) + "\n", sorted(applied), sorted(unexpressible)


###### Reporting


def _report_since(table: dict, applied: list[str]) -> None:
    """Corroborate derived lower bounds against SideFX's own #since.

    They disagree legitimately: #since records when a node first appeared
    anywhere in Houdini's history, which can predate the oldest build sampled
    here, and it never records a removal. Presence stays authoritative.
    """
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
        f"\n#since check    : {agreed} corroborated, {len(disagreed)} differ, {absent} undocumented"
    )
    for item in disagreed:
        print(f"    {item}  (expected when the node predates the oldest build sampled)")


def check(dumps: list[dict], table: dict, text: str) -> int:
    """Verify the committed annotations against the builds on this machine.

    Deliberately not "would a regeneration produce identical files": with one
    Houdini installed that would always look stale, which would make the check
    useless to most contributors. This asks the narrower, answerable question --
    does the committed table contradict what this machine actually has?
    """
    annotated = {
        match.group(1): (match.group(2), match.group(0))
        for match in _ANNOTATED_NAME.finditer(text.replace("\\_", "_"))
    }
    series, avail = availability(table)

    contradictions: list[str] = []
    unsampled: list[str] = []
    for dump in dumps:
        build = dump["version"]
        this_series = _series_of(dump["version_tuple"])
        if build not in table["builds"]:
            unsampled.append(build)
        here = {
            f"{category}/{name}" for category, names in dump["node_types"].items() for name in names
        }
        for key, per_series in avail.items():
            name = key.split("/", 1)[1]
            if name not in annotated or this_series not in series:
                continue
            marker = annotated[name][1].strip()
            expected = per_series.get(this_series, False)
            actual = key in here
            if expected != actual:
                contradictions.append(
                    f"{build}: {key} {marker} says "
                    f"{'present' if expected else 'absent'}, build says "
                    f"{'present' if actual else 'absent'}"
                )

    print(f"\nannotated names checked : {len(annotated)}")
    print(f"builds available here   : {[d['version'] for d in dumps]}")
    if unsampled:
        print(f"not yet in the table    : {unsampled}\n    Run without --check to contribute them.")
    if contradictions:
        print(f"\nCONTRADICTIONS ({len(contradictions)}):")
        for item in contradictions:
            print(f"    {item}")
        return 1
    print("\nNo contradictions with the builds installed here.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed table against this machine's Houdini(s)",
    )
    args = parser.parse_args()

    hythons = _hythons()
    if not hythons:
        print("No Houdini install found. Set HYTHON or install Houdini.")
        return 1

    print(f"Sampling {len(hythons)} Houdini install(s):")
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

    if not dumps:
        print("No build responded; nothing to do.")
        return 1

    table = load_table()
    text = _INSTRUCTIONS.read_text(encoding="utf-8")

    if args.check:
        return check(dumps, table, text)

    merged = merge(table, dumps)
    series, _ = availability(merged)
    new_builds = [d["version"] for d in dumps if d["version"] not in table["builds"]]

    print(f"\nbuilds in table : {len(merged['builds'])} ({', '.join(series)})")
    if new_builds:
        print(f"newly added     : {', '.join(new_builds)}")
    thin = thin_evidence(merged)
    if thin:
        print(f"single-build    : {thin} (weaker evidence)")

    if len(series) < 2:
        print(
            f"\nOnly one series ({series[0]}) has ever been sampled, so nothing can "
            "be said about when a node appeared or vanished.\n"
            f"Wrote the evidence to {_TABLE.relative_to(REPO_ROOT)} anyway -- commit "
            "it and the annotations will follow once another version is contributed."
        )
        _write_table(merged)
        return 0

    new_text, applied, unexpressible = rewrite_instructions(text, merged)
    print(f"annotations     : {len(applied)}")
    for item in applied:
        print(f"    {item}")
    if unexpressible:
        print(f"\nNOT expressible as a range, look at these {len(unexpressible)}:")
        for item in unexpressible:
            print(f"    {item}")
    _report_since(merged, applied)

    _write_table(merged)
    if new_text != text:
        _INSTRUCTIONS.write_text(new_text, encoding="utf-8")
        print(f"\nrewrote {_INSTRUCTIONS.relative_to(REPO_ROOT)}")
    else:
        print(f"\n{_INSTRUCTIONS.relative_to(REPO_ROOT)} already correct")
    print(f"wrote   {_TABLE.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
