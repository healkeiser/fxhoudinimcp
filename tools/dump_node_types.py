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

_SINCE = re.compile(r"^#since:\s*([0-9.]+)", re.M)
_INTERNAL = re.compile(r"^#internal:\s*(\S+)", re.M)
_CONTEXT = re.compile(r"^#context:\s*(\S+)", re.M)


def _node_types() -> dict[str, list[str]]:
    return {
        name: sorted(category.nodeTypes())
        for name, category in hou.nodeTypeCategories().items()
    }


def _since_from_help() -> dict[str, str]:
    """Map "Category/nodename" to the #since version SideFX documents."""
    help_zip = os.path.join(hou.expandString("$HFS"), "houdini", "help", "nodes.zip")
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
            if "#type: node" not in text:
                continue
            version = _SINCE.search(text)
            internal = _INTERNAL.search(text)
            context = _CONTEXT.search(text)
            if not (version and internal and context):
                continue
            # Help contexts are lowercase ("sop"); node type categories are
            # capitalised ("Sop").
            since[f"{context.group(1).capitalize()}/{internal.group(1)}"] = (
                version.group(1)
            )
    return since


def main() -> int:
    json.dump(
        {
            "version": hou.applicationVersionString(),
            "version_tuple": list(hou.applicationVersion()),
            "node_types": _node_types(),
            "since": _since_from_help(),
        },
        sys.stdout,
    )
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
