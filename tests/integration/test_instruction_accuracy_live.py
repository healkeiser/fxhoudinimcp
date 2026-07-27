"""Verify the node names advertised in server_instructions.md exist.

The instructions tell assistants to trust specific built-in node names
(the COMMONLY MISSED NODE DOMAINS lists). Any name that does not exist
in this Houdini version is guidance that makes the assistant hallucinate.

Some names only exist in part of the supported range -- Houdini 21 added a lot
of Copernicus, and 22 renamed the LOP ``instancer`` to ``copytopoints`` and
``layout`` to ``paintinstances`` (per the 22.0 Solaris release notes; neither
was dropped, and Houdini keeps the old names as aliases so old scenes load).
Those carry an inline version annotation in the markdown, e.g.
``colorcorrect (21.0+)`` or ``instancer (20.5-21.0)``, and
this test holds each name to its declared range. The annotation is written for
the assistant to read as well, so the markdown stays the single source of
truth rather than duplicating a table here.
"""

from __future__ import annotations

# Built-in
import re
from pathlib import Path

# Third-party
import hou
import pytest

pytestmark = pytest.mark.integration

# "21.0+" or "20.5-21.0" immediately after a node name.
_VERSION_SPEC = re.compile(
    r"([a-z][a-z0-9_:.]*[a-z0-9])\s*\((\d+\.\d+)(\+|-(\d+\.\d+))\)"
)

_MD = (
    Path(__file__).resolve().parents[2]
    / "python"
    / "fxhoudinimcp"
    / "prompts"
    / "markdown"
    / "server_instructions.md"
)

# Optional packs not shipped with a base install.
_OPTIONAL_PREFIXES = ("labs::", "apex::")

# Markdown sections mapped to hou node type categories.
# Headings emitted by tools/gen_node_domains.py, e.g.
# "### Sop (context='Sop', 663 documented)". Matched with startswith, so Cop2
# MUST come before Cop or every Cop2 name is checked against the Cop category
# and the test fails for the wrong reason.
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


def _parse_spec(low: str, tail: str) -> tuple[tuple[int, int], tuple[int, int] | None]:
    """Turn a matched annotation into (min_version, max_version).

    ``max_version`` is inclusive of that whole minor series, and None means
    "still present in the newest supported build".
    """
    minimum = tuple(int(part) for part in low.split("."))
    if tail == "+":
        return minimum, None  # type: ignore[return-value]
    maximum = tuple(int(part) for part in tail.lstrip("-").split("."))
    return minimum, maximum  # type: ignore[return-value]


def _claimed_names() -> list[tuple[str, str, tuple | None]]:
    """Extract (category, node_type_name, version_range) claims.

    ``version_range`` is None for names expected in every supported version.
    """
    text = _MD.read_text(encoding="utf-8").replace("\\_", "_")
    claims: list[tuple[str, str, tuple | None]] = []
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
        # Node names appear after the colon, comma-separated. Only tokens
        # that look like node type names (identifier characters only).
        _, _, tail = line.partition(":")

        # Pull out version-annotated names first: the prose strip below would
        # otherwise discard the annotation and leave the bare name looking
        # like a claim for every version.
        for match in _VERSION_SPEC.finditer(tail):
            claims.append(
                (
                    category,
                    match.group(1),
                    _parse_spec(match.group(2), match.group(3)),
                )
            )
        tail = _VERSION_SPEC.sub("", tail)

        # Remaining parenthesized fragments are prose, not type names.
        tail = re.sub(r"\([^)]*\)", "", tail)
        for chunk in re.split(r"[,—]", tail):
            token = chunk.strip().rstrip(".")
            # Internal capitals are allowed: MaterialX node types are spelled
            # mtlxLamaAdd, and a lowercase-only pattern silently skipped a whole
            # shading family. Still anchored to a lowercase first character, which
            # is what keeps prose ("Houdini", "SOP") out.
            if re.fullmatch(r"[a-z][A-Za-z0-9_:.]*[A-Za-z0-9]", token) and (
                "_" in token or "::" in token or len(token) >= 4
            ):
                claims.append((category, token, None))
    return claims


def _exists(category_types: dict, name: str) -> bool:
    if name in category_types:
        return True
    prefix = name + "::"
    return any(key.startswith(prefix) for key in category_types)


def _applies(version_range: tuple | None, version: tuple[int, int]) -> bool:
    """Is a name with this annotation expected to exist in *version*?"""
    if version_range is None:
        return True
    minimum, maximum = version_range
    if version < minimum:
        return False
    return maximum is None or version <= maximum


def test_every_advertised_node_type_exists():
    claims = _claimed_names()
    assert len(claims) > 150, f"parser broke, only {len(claims)} claims found"

    version = hou.applicationVersion()[:2]
    categories = hou.nodeTypeCategories()
    missing: list[str] = []
    optional_missing: list[str] = []
    out_of_range: list[str] = []
    for category_name, node_name, version_range in claims:
        category = categories.get(category_name)
        if category is None:
            missing.append(f"{category_name}: category itself missing")
            continue

        exists = _exists(category.nodeTypes(), node_name)
        if not _applies(version_range, version):
            # Not expected here. If it turns up anyway the annotation is too
            # narrow -- worth surfacing, but it is not broken guidance.
            if exists:
                out_of_range.append(f"{category_name}/{node_name}")
            continue
        if exists:
            continue
        if node_name.startswith(_OPTIONAL_PREFIXES):
            optional_missing.append(f"{category_name}/{node_name}")
        else:
            missing.append(f"{category_name}/{node_name}")

    if optional_missing:
        print(f"[info] optional packs not installed: {len(optional_missing)} names")
    if out_of_range:
        print(
            f"[info] present despite a narrower annotation, consider widening: "
            f"{out_of_range}"
        )
    assert not missing, (
        f"server_instructions.md advertises {len(missing)} node types that "
        f"do not exist in {hou.applicationVersionString()}: {missing}"
    )


def test_mixed_case_node_names_are_claimed():
    """A lowercase-only claim pattern silently hid a whole shading family.

    MaterialX VOP types are spelled mtlxLamaAdd. They were being advertised and
    never checked, and the first fix was to stop advertising them, which threw
    away useful nodes to satisfy the parser. Guard the parser instead.
    """
    claims = {name for _, name, _ in _claimed_names()}
    mixed = {name for name in claims if any(char.isupper() for char in name)}
    assert mixed, (
        "no mixed-case node name is claimed; the pattern has regressed to "
        "lowercase-only and MaterialX VOPs would go unverified again"
    )


def test_version_annotations_are_actually_used():
    """Guard the annotation syntax itself.

    A typo in an annotation degrades silently: the name would be read as an
    unconditional claim, which either passes for the wrong reason or fails on
    the versions the annotation was meant to exempt.
    """
    annotated = [claim for claim in _claimed_names() if claim[2] is not None]
    assert annotated, (
        "no version-annotated names parsed from server_instructions.md -- the "
        "'name (21.0+)' syntax or the regex has drifted"
    )
    for _, name, version_range in annotated:
        minimum, maximum = version_range
        assert len(minimum) == 2, f"{name}: bad minimum {minimum}"
        if maximum is not None:
            assert maximum >= minimum, f"{name}: range ends before it starts"


###### Handler node choices


_PLUGIN_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "houdini"
    / "scripts"
    / "python"
    / "fxhoudinimcp_server"
)

# createNode("sometype") with a literal type name. Handlers that build a type
# name dynamically are out of scope: this catches the hardcoded choices, which
# is where a node SideFX has retired actually gets baked in.
_CREATE_NODE = re.compile(r"createNode\(\s*[\"']([^\"']+)[\"']")


def _created_type_names() -> dict[str, set[str]]:
    """Literal node type names the plugin creates -> the files creating them."""
    found: dict[str, set[str]] = {}
    for path in _PLUGIN_SOURCE.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for match in _CREATE_NODE.finditer(text):
            found.setdefault(match.group(1), set()).add(path.name)
    return found


def _is_deprecated(node_type) -> bool:
    flag = node_type.deprecated
    try:
        return bool(flag() if callable(flag) else flag)
    except Exception:
        return False


def test_handlers_do_not_create_deprecated_node_types():
    """Fail if a workflow tool builds a node Houdini marks deprecated.

    Houdini 22.0 deprecated the DOP pyro nodes -- smokeobject and
    smokeconfigureobject -- and the notes say they are "scheduled to be deleted
    in an upcoming revision". setup_pyro_sim's DOP fallback created exactly
    those, so it was set to break on a future Houdini while looking fine here.
    The sparse replacements exist back to 20.5, so there is no version excuse.

    A name is only reported when it is deprecated in *every* category that has
    it. karma is the reason: the LOP is deprecated, the ROP of the same name is
    current, and the ROP is the one setup_render builds.
    """
    categories = hou.nodeTypeCategories()
    offenders = []
    for name, files in sorted(_created_type_names().items()):
        base = name.split("::")[0]
        matches = [
            (category_name, types[base])
            for category_name, category in categories.items()
            for types in (category.nodeTypes(),)
            if base in types
        ]
        if not matches:
            continue  # not in this build; the version tests cover that
        if all(_is_deprecated(node_type) for _, node_type in matches):
            where = ", ".join(category for category, _ in matches)
            offenders.append(f"{name} (deprecated as {where}) in {sorted(files)}")

    assert not offenders, (
        f"the plugin creates {len(offenders)} node type(s) that "
        f"{hou.applicationVersionString()} marks deprecated: {offenders}"
    )
