"""Tests for the command that emits the Houdini package file.

The plugin ships inside the package, so its path depends on which Python it was
installed into. Nobody should type that by hand: it is easy to get wrong, and
Houdini silently skips a package whose path does not resolve, which is the
confusion behind issue #11.
"""

from __future__ import annotations

# Built-in
import json
from pathlib import Path

# Third-party
import pytest

# Internal
from fxhoudinimcp import houdini_package as hp


@pytest.fixture
def no_candidates(monkeypatch):
    """Stop the real machine's Houdini directories leaking into a test."""
    monkeypatch.setattr(hp, "candidate_package_dirs", lambda: [])


###### Locating the plugin


class TestPluginPath:
    def test_prefers_the_packaged_location(self, monkeypatch, tmp_path):
        """An installed user must not pick up a clone that happens to be near."""
        module = tmp_path / "pkg" / "fxhoudinimcp"
        (module / "houdini").mkdir(parents=True)
        (tmp_path / "pkg" / "houdini").mkdir()
        monkeypatch.setattr(hp, "__file__", str(module / "houdini_package.py"))

        assert hp.plugin_path() == module / "houdini"

    def test_falls_back_to_the_repository_layout(self, monkeypatch, tmp_path):
        """A source checkout keeps the plugin at the repository root."""
        module = tmp_path / "repo" / "python" / "fxhoudinimcp"
        module.mkdir(parents=True)
        (tmp_path / "repo" / "houdini").mkdir()
        monkeypatch.setattr(hp, "__file__", str(module / "houdini_package.py"))

        assert hp.plugin_path() == tmp_path / "repo" / "houdini"

    def test_the_real_install_resolves_somewhere(self):
        assert hp.plugin_path().is_dir(), "neither layout found the plugin"


###### The JSON


class TestPackageJson:
    def test_is_valid_json_with_the_expected_shape(self, tmp_path):
        data = json.loads(hp.package_json(tmp_path / "plug"))
        assert data["path"] == "$FXHOUDINIMCP"
        assert data["env"][0]["FXHOUDINIMCP"].endswith("plug")

    def test_uses_forward_slashes(self, tmp_path):
        """Backslashes in JSON need escaping, a common way to break this file."""
        text = hp.package_json(tmp_path / "a" / "b")
        assert "\\\\" not in text
        assert "/a/b" in text.replace("\\", "/")

    def test_no_method_key(self):
        """"method": "default" is unsupported and warns in Houdini."""
        assert "method" not in hp.package_json()

    def test_uses_the_resolved_plugin_path_by_default(self):
        data = json.loads(hp.package_json())
        assert data["env"][0]["FXHOUDINIMCP"] == hp.plugin_path().as_posix()


###### Candidate directories


class TestCandidateDirs:
    def test_only_reports_directories_that_exist(self, monkeypatch, tmp_path):
        monkeypatch.setattr(hp.Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr(hp.platform, "system", lambda: "Linux")
        (tmp_path / "houdini22.0" / "packages").mkdir(parents=True)
        (tmp_path / "houdini21.0").mkdir()  # no packages/ inside

        found = hp.candidate_package_dirs()

        assert found == [tmp_path / "houdini22.0" / "packages"]

    def test_no_houdini_at_all_is_empty(self, monkeypatch, tmp_path):
        monkeypatch.setattr(hp.Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr(hp.platform, "system", lambda: "Linux")
        assert hp.candidate_package_dirs() == []


###### Detecting a conflicting install


class TestExistingPackages:
    def _write(self, directory: Path, target: str, wrapped: bool = False) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        value = {"value": target, "method": "default"} if wrapped else target
        path = directory / "fxhoudinimcp.json"
        path.write_text(
            json.dumps({"env": [{"FXHOUDINIMCP": value}], "path": "$FXHOUDINIMCP"}),
            encoding="utf-8",
        )
        return path

    def test_reports_the_path_each_one_points_at(self, monkeypatch, tmp_path):
        one = self._write(tmp_path / "a", "/plugins/old")
        monkeypatch.setattr(hp, "candidate_package_dirs", lambda: [tmp_path / "a"])

        assert hp.existing_packages() == [(one, "/plugins/old")]

    def test_reads_the_legacy_wrapped_env_form(self, monkeypatch, tmp_path):
        self._write(tmp_path / "a", "/plugins/legacy", wrapped=True)
        monkeypatch.setattr(hp, "candidate_package_dirs", lambda: [tmp_path / "a"])

        assert hp.existing_packages()[0][1] == "/plugins/legacy"

    def test_excludes_the_file_just_written(self, monkeypatch, tmp_path):
        mine = self._write(tmp_path / "a", "/plugins/mine")
        monkeypatch.setattr(hp, "candidate_package_dirs", lambda: [tmp_path / "a"])

        assert hp.existing_packages(exclude=mine) == []

    def test_a_corrupt_file_is_reported_not_fatal(self, monkeypatch, tmp_path):
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "fxhoudinimcp.json").write_text("{broken", encoding="utf-8")
        monkeypatch.setattr(hp, "candidate_package_dirs", lambda: [tmp_path / "a"])

        found = hp.existing_packages()

        assert len(found) == 1 and found[0][1] == "<unreadable>"


###### The command


class TestMain:
    def test_path_only_prints_just_the_path(self, capsys):
        assert hp.main(["--path-only"]) == 0
        assert capsys.readouterr().out.strip() == hp.plugin_path().as_posix()

    def test_default_prints_the_json(self, capsys, no_candidates):
        assert hp.main([]) == 0
        out = capsys.readouterr().out
        assert "$FXHOUDINIMCP" in out
        assert "HOUDINI_PACKAGE_VERBOSE" in out, "should say how to verify"

    def test_write_produces_a_bom_free_lf_file(self, tmp_path, capsys, no_candidates):
        assert hp.main(["--write", str(tmp_path)]) == 0

        raw = (tmp_path / "fxhoudinimcp.json").read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), "a BOM makes Houdini skip it"
        assert b"\r\n" not in raw
        assert json.loads(raw.decode("utf-8"))["path"] == "$FXHOUDINIMCP"

    def test_write_to_a_missing_directory_fails_clearly(self, tmp_path, capsys):
        assert hp.main(["--write", str(tmp_path / "nope")]) == 1
        assert "Not a directory" in capsys.readouterr().err

    def test_write_warns_about_a_conflicting_package(
        self, monkeypatch, tmp_path, capsys
    ):
        """Houdini lets the last packages directory win, silently."""
        other = tmp_path / "other"
        other.mkdir()
        (other / "fxhoudinimcp.json").write_text(
            json.dumps({"env": [{"FXHOUDINIMCP": "/plugins/stale"}]}), encoding="utf-8"
        )
        monkeypatch.setattr(hp, "candidate_package_dirs", lambda: [other])
        destination = tmp_path / "dest"
        destination.mkdir()

        assert hp.main(["--write", str(destination)]) == 0

        out = capsys.readouterr().out
        assert "WARNING" in out
        assert "/plugins/stale" in out

    def test_missing_plugin_directory_fails(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(hp, "plugin_path", lambda: tmp_path / "absent")
        assert hp.main([]) == 1
        assert "missing" in capsys.readouterr().err
