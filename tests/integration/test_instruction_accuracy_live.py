"""Verify the node names advertised in server_instructions.md exist.

The instructions tell assistants to trust specific built-in node names
(the COMMONLY MISSED NODE DOMAINS lists). Any name that does not exist
in this Houdini version is guidance that makes the assistant hallucinate.
"""

from __future__ import annotations

# Built-in
import re
from pathlib import Path

# Third-party
import hou
import pytest

pytestmark = pytest.mark.integration

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
_SECTIONS = {
    "### SOPs": "Sop",
    "### LOPs": "Lop",
    "### DOPs": "Dop",
    "### COPs": "Cop",
    "### CHOPs": "Chop",
    "### TOPs": "Top",
}


def _claimed_names() -> list[tuple[str, str]]:
    """Extract (category, node_type_name) claims from the instructions."""
    text = _MD.read_text(encoding="utf-8").replace("\\_", "_")
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
        # Node names appear after the colon, comma-separated. Only tokens
        # that look like node type names (identifier characters only).
        # Parenthesized fragments are prose, not type names.
        _, _, tail = line.partition(":")
        tail = re.sub(r"\([^)]*\)", "", tail)
        for chunk in re.split(r"[,—]", tail):
            token = chunk.strip().rstrip(".")
            if re.fullmatch(r"[a-z][a-z0-9_:.]*[a-z0-9]", token) and (
                "_" in token or "::" in token or len(token) >= 4
            ):
                claims.append((category, token))
    return claims


def _exists(category_types: dict, name: str) -> bool:
    if name in category_types:
        return True
    prefix = name + "::"
    return any(key.startswith(prefix) for key in category_types)


def test_every_advertised_node_type_exists():
    claims = _claimed_names()
    assert len(claims) > 150, f"parser broke, only {len(claims)} claims found"

    categories = hou.nodeTypeCategories()
    missing: list[str] = []
    optional_missing: list[str] = []
    for category_name, node_name in claims:
        category = categories.get(category_name)
        if category is None:
            missing.append(f"{category_name}: category itself missing")
            continue
        if _exists(category.nodeTypes(), node_name):
            continue
        if node_name.startswith(_OPTIONAL_PREFIXES):
            optional_missing.append(f"{category_name}/{node_name}")
        else:
            missing.append(f"{category_name}/{node_name}")

    if optional_missing:
        print(f"[info] optional packs not installed: {len(optional_missing)} names")
    assert not missing, (
        f"server_instructions.md advertises {len(missing)} node types that "
        f"do not exist in {hou.applicationVersionString()}: {missing}"
    )
