"""update_hda says whether the library file was written.

The reply said "HDA definition updated from node contents" and named the
library file, but nothing in it said the file on disk had changed, so callers
followed it with definition.save() through execute_python "just in case".
updateFromNode() writes the file itself; the reply now carries the file's
mtime and saved_to_disk, and an embedded definition says it lives in the hip.

hou is mocked here; the live check ran on Houdini 22.0.429.
"""

from __future__ import annotations

# Built-in
import os
import sys
from unittest.mock import MagicMock

sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Internal
import fxhoudinimcp_server.handlers.hda_handlers as hda  # noqa: E402


def _asset(monkeypatch, library):
    definition = MagicMock()
    definition.libraryFilePath.return_value = library
    definition.nodeTypeName.return_value = "probe"
    node = MagicMock()
    node.path.return_value = "/obj/probe"
    node.type.return_value.definition.return_value = definition
    monkeypatch.setattr(hda, "_get_node", lambda path: node)
    monkeypatch.setattr(hda, "_get_definition", lambda n: definition)
    return node, definition


class TestUpdateHdaReportsTheWrite:
    def test_a_moved_mtime_means_saved(self, monkeypatch):
        node, definition = _asset(monkeypatch, "/tmp/lib.hda")
        stamps = iter([100.0, 101.0])
        monkeypatch.setattr(hda.os.path, "getmtime", lambda path: next(stamps))

        result = hda.update_hda("/obj/probe")

        definition.updateFromNode.assert_called_once_with(node)
        assert result["saved_to_disk"] is True
        assert result["library_file_mtime"] == 101.0
        assert "written to the library file" in result["message"]
        assert "lazily" in result["note"]

    def test_an_unmoved_mtime_is_reported_as_not_saved(self, monkeypatch):
        _asset(monkeypatch, "/tmp/lib.hda")
        monkeypatch.setattr(hda.os.path, "getmtime", lambda path: 100.0)
        assert hda.update_hda("/obj/probe")["saved_to_disk"] is False

    def test_an_unreadable_file_is_unknown_not_false(self, monkeypatch):
        _asset(monkeypatch, "/nowhere.hda")

        def boom(path):
            raise OSError("no such file")

        monkeypatch.setattr(hda.os.path, "getmtime", boom)
        assert hda.update_hda("/obj/probe")["saved_to_disk"] is None

    def test_an_embedded_definition_says_it_lives_in_the_hip(self, monkeypatch):
        _asset(monkeypatch, "Embedded")
        getmtime = MagicMock()
        monkeypatch.setattr(hda.os.path, "getmtime", getmtime)

        result = hda.update_hda("/obj/probe")

        getmtime.assert_not_called()
        assert result["saved_to_disk"] is None
        assert result["library_file_mtime"] is None
        assert "embedded in the hip file" in result["message"]
