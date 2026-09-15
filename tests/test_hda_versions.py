"""list_hda_versions listed one NodeType's definitions, not the type's version family.

Houdini keeps the version in the type name: brick::1.1 is a different NodeType
from brick, so allInstalledDefinitions() of the instance's type showed one row
and a freshly installed ::1.1 was invisible. The handler now walks the category
for every type sharing scope, namespace and name.

hou is mocked here; the live check ran on Houdini 22.0.429.
"""

from __future__ import annotations

# Built-in
import os
import sys
from unittest.mock import MagicMock

# Third-party
import pytest

sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Internal
import fxhoudinimcp_server.handlers.hda_handlers as hda  # noqa: E402


@pytest.fixture
def hou_env(monkeypatch):
    monkeypatch.setattr(hda.hou, "hda", MagicMock(), raising=False)
    return hda.hou


def _type(name, versions):
    node_type = MagicMock()
    node_type.name.return_value = name
    defs = []
    for version, current in versions:
        d = MagicMock()
        d.version.return_value = version
        d.libraryFilePath.return_value = f"/tmp/{name}.hda"
        d.isCurrent.return_value = current
        d.isPreferred.return_value = current
        defs.append(d)
    node_type.allInstalledDefinitions.return_value = defs
    return node_type


class TestListHdaVersions:
    def test_every_version_of_the_name_is_listed(self, hou_env, monkeypatch):
        base = _type("brick", [("1.0", True)])
        v11 = _type("brick::1.1", [("1.1", True)])
        other = _type("brick_other", [("", True)])
        base.category.return_value.nodeTypes.return_value = {
            "brick": base,
            "brick::1.1": v11,
            "brick_other": other,
        }
        hou_env.hda.componentsFromFullNodeTypeName.side_effect = lambda n: (
            ("", "", n.split("::")[0], n.split("::")[1] if "::" in n else "")
        )
        node = MagicMock()
        node.path.return_value = "/obj/asset"
        node.type.return_value = base
        monkeypatch.setattr(hda, "_get_node", lambda path: node)

        result = hda.list_hda_versions("/obj/asset")

        assert [
            (v["type_name"], v["version"], v["is_instance_type"]) for v in result["versions"]
        ] == [
            ("brick", "1.0", True),
            ("brick::1.1", "1.1", False),
        ]
        assert result["family"] == {"scope": "", "namespace": "", "name": "brick"}

    def test_versions_sort_numerically(self):
        rows = ["1.10", None, "1.2", "2.0"]
        assert sorted(rows, key=hda._version_key) == [None, "1.2", "1.10", "2.0"]
