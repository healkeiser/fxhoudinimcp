"""Tests for detecting a Houdini plugin older than this MCP server.

The two halves ship separately, so a user can upgrade the PyPI package and leave
the plugin behind. Without a check the only symptom is one tool failing with
"No handler registered for command", which reads like a bug.
"""

from __future__ import annotations

# Built-in
import json
import os
import sys
from pathlib import Path

# Third-party
import pytest

# Internal
from fxhoudinimcp import compat

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))


@pytest.fixture(autouse=True)
def clear_cache():
    compat.required_commands.cache_clear()
    yield
    compat.required_commands.cache_clear()


@pytest.fixture
def manifest(monkeypatch, tmp_path):
    path = tmp_path / "required_commands.json"
    path.write_text(
        json.dumps({"commands": ["scene.get_scene_info", "nodes.create_node"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(compat, "_MANIFEST", path)
    return path


###### The manifest that ships


class TestShippedManifest:
    def test_is_readable_and_populated(self):
        assert len(compat.required_commands()) > 150

    def test_matches_the_client_source(self):
        """The whole point is that nobody has to maintain this by hand.

        If a tool gains an execute() call and the manifest is not regenerated,
        the compatibility check silently stops covering that command.
        """
        from gen_required_commands import collect

        commands, dynamic = collect()
        assert not dynamic, f"non-literal execute() call sites: {dynamic}"
        assert commands == set(compat.required_commands()), (
            "required_commands.json is stale. Run: "
            "python tools/gen_required_commands.py"
        )

    def test_every_command_is_namespaced(self):
        for command in compat.required_commands():
            assert "." in command, f"{command!r} has no namespace"


###### Detecting the gap


class TestMissingCommands:
    def test_none_missing_when_plugin_has_everything(self, manifest):
        available = ["scene.get_scene_info", "nodes.create_node", "extra.thing"]
        assert compat.missing_commands(available) == []

    def test_reports_what_the_plugin_lacks(self, manifest):
        assert compat.missing_commands(["scene.get_scene_info"]) == [
            "nodes.create_node"
        ]

    def test_result_is_sorted(self, monkeypatch, tmp_path):
        path = tmp_path / "m.json"
        path.write_text(json.dumps({"commands": ["c.z", "a.a", "b.m"]}), "utf-8")
        monkeypatch.setattr(compat, "_MANIFEST", path)
        assert compat.missing_commands(["x.y"]) == ["a.a", "b.m", "c.z"]

    @pytest.mark.parametrize("available", [None, []])
    def test_no_conclusion_without_a_plugin_answer(self, manifest, available):
        """An empty reply is indistinguishable from a failed call."""
        assert compat.missing_commands(available) == []

    def test_no_conclusion_without_a_manifest(self, monkeypatch, tmp_path):
        monkeypatch.setattr(compat, "_MANIFEST", tmp_path / "absent.json")
        assert compat.missing_commands(["anything"]) == []


###### The warning


class TestCompatibilityWarning:
    def test_silent_when_compatible(self, manifest):
        available = ["scene.get_scene_info", "nodes.create_node"]
        assert compat.compatibility_warning(available) is None

    def test_names_the_missing_command(self, manifest):
        warning = compat.compatibility_warning(["scene.get_scene_info"])
        assert warning is not None
        assert "nodes.create_node" in warning

    def test_truncates_a_long_list(self, monkeypatch, tmp_path):
        many = [f"ns.cmd{i:02d}" for i in range(30)]
        path = tmp_path / "m.json"
        path.write_text(json.dumps({"commands": many}), encoding="utf-8")
        monkeypatch.setattr(compat, "_MANIFEST", path)

        warning = compat.compatibility_warning(["ns.other"])

        assert "30 command(s)" in warning
        assert "and 24 more" in warning
        assert warning.count("ns.cmd") == compat._MAX_NAMED

    def test_points_at_the_command_that_diagnoses_it(self, manifest):
        """A warning the reader cannot act on is only half useful."""
        warning = compat.compatibility_warning(["scene.get_scene_info"])
        assert "houdini-package" in warning


###### Degradation


class TestDegradation:
    def test_missing_manifest_is_empty(self, monkeypatch, tmp_path):
        monkeypatch.setattr(compat, "_MANIFEST", tmp_path / "absent.json")
        assert compat.required_commands() == frozenset()

    def test_corrupt_manifest_does_not_raise(self, monkeypatch, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(compat, "_MANIFEST", path)
        assert compat.required_commands() == frozenset()

    def test_unexpected_shape_is_tolerated(self, monkeypatch, tmp_path):
        path = tmp_path / "odd.json"
        path.write_text(json.dumps({"commands": "not a list"}), encoding="utf-8")
        monkeypatch.setattr(compat, "_MANIFEST", path)
        assert compat.required_commands() == frozenset()


###### The manifest ships


def test_manifest_is_inside_the_package():
    """It has to ship, or an installed server cannot run the check."""
    package_root = Path(compat.__file__).parent
    assert compat._MANIFEST.is_file()
    assert package_root in compat._MANIFEST.parents


class TestUnusableReplies:
    """A reply that is not a command list must not look like a version gap.

    Reporting every command as missing would be a loud, wrong warning, which is
    worse than staying quiet. Found by a mock returning a MagicMock.
    """

    @pytest.mark.parametrize(
        "available",
        [object(), 42, "scene.get_scene_info", {"commands": []}, [1, 2, 3], ["a", 7]],
    )
    def test_no_false_positive(self, manifest, available):
        assert compat.missing_commands(available) == []
        assert compat.compatibility_warning(available) is None

    def test_a_real_list_still_works(self, manifest):
        assert compat.missing_commands(["scene.get_scene_info"]) == [
            "nodes.create_node"
        ]
