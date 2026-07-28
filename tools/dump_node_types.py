"""Dump every node type in this Houdini build as JSON on stdout.

Runs inside hython. Driven by tools/gen_node_versions.py; not useful alone.

Also carries SideFX's own ``#since`` metadata from the shipped node help,
which records the version a node was introduced. That covers roughly two
thirds of nodes and never records removals, so the generator treats it as
corroboration rather than the source of truth -- the authoritative signal is
which names are actually present in each build.
"""

from __future__ import annotations

# Built-in
import json
import os
import re
import sys
import zipfile

# Third-party
import hou

# SideFX aligns these header values, so the run of whitespace after the colon
# varies from page to page ("#type: node" and "#type:     node" both occur).
# A literal string test skipped 829 of 4780 node pages, losing their #since.
_TYPE_NODE = re.compile(r"^#type:\s*node\s*$", re.M)
_SINCE = re.compile(r"^#since:\s*([0-9.]+)", re.M)
_INTERNAL = re.compile(r"^#internal:\s*(\S+)", re.M)
_CONTEXT = re.compile(r"^#context:\s*(\S+)", re.M)


def _node_types() -> dict[str, list[str]]:
    return {
        name: sorted(category.nodeTypes()) for name, category in hou.nodeTypeCategories().items()
    }


def _deprecated() -> list[str]:
    """ "Category/name" for every node type Houdini marks deprecated.

    Authoritative and machine-readable, unlike guessing from docs. Without this
    the generated hints advertise superseded nodes: Sop/group when groupcreate
    replaced it, Sop/copy when copytopoints did, Sop/point when attribexpression
    did. 29 of 605 advertised names were deprecated before this existed.
    """
    found = []
    for category_name, category in hou.nodeTypeCategories().items():
        for name, node_type in category.nodeTypes().items():
            flag = node_type.deprecated
            try:
                is_deprecated = flag() if callable(flag) else bool(flag)
            except Exception:
                continue
            if is_deprecated:
                found.append(f"{category_name}/{name}")
    return sorted(found)


def _aliases() -> dict[str, str]:
    """Old node name -> current name, as "Category/old": "Category/new".

    Houdini keeps these so old scene files still load, which makes it the one
    authoritative rename map. SideFX renamed the Instancer LOP to Copy to Points
    and the Layout LOP to Paint Instances in 22.0, and aliases() reports exactly
    that without anyone reading release notes.
    """
    mapping = {}
    for category_name, category in hou.nodeTypeCategories().items():
        for name, node_type in category.nodeTypes().items():
            try:
                for old in node_type.aliases() or ():
                    mapping[f"{category_name}/{old}"] = f"{category_name}/{name}"
            except Exception:
                continue
    return dict(sorted(mapping.items()))


def _since_from_help() -> dict[str, str]:
    """Map "Category/nodename" to the #since version SideFX documents."""
    # hou.text.expandString, not the deprecated hou.expandString.
    help_zip = os.path.join(hou.text.expandString("$HFS"), "houdini", "help", "nodes.zip")
    if not os.path.isfile(help_zip):
        return {}

    since: dict[str, str] = {}
    with zipfile.ZipFile(help_zip) as archive:
        for entry in archive.namelist():
            if not entry.endswith(".txt"):
                continue
            try:
                text = archive.read(entry).decode("utf-8", "replace")
            except Exception:
                continue
            if not _TYPE_NODE.search(text):
                continue
            version = _SINCE.search(text)
            internal = _INTERNAL.search(text)
            context = _CONTEXT.search(text)
            if not (version and internal and context):
                continue
            # Help contexts are lowercase ("sop"); node type categories are
            # capitalised ("Sop").
            since[f"{context.group(1).capitalize()}/{internal.group(1)}"] = version.group(1)
    return since


def main() -> int:
    json.dump(
        {
            "version": hou.applicationVersionString(),
            "version_tuple": list(hou.applicationVersion()),
            "node_types": _node_types(),
            "deprecated": _deprecated(),
            "aliases": _aliases(),
            "since": _since_from_help(),
        },
        sys.stdout,
    )
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
