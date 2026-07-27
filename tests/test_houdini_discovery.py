"""Tests for locating Houdini installs across platforms.

The real Windows, macOS and Linux layouts differ in both the install root and
where the interpreter sits inside it. Only one of those can ever be exercised on
the machine running these tests, so the layouts are reproduced under tmp_path
and the search patterns are pointed at them. That verifies the part that is
actually easy to get wrong -- the per-platform subpaths, version ordering and
de-duplication -- without needing three machines.
"""

from __future__ import annotations

# Built-in
import os
import sys
from pathlib import Path

# Third-party
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from run_integration import find_all_hython  # noqa: E402

# install directory name -> path of the interpreter inside it
_LAYOUTS = {
    "windows": ("Houdini 21.0.440", "bin/hython.exe"),
    "linux": ("hfs20.5.654", "bin/hython"),
    "macos": (
        "Houdini20.5.487",
        "Frameworks/Houdini.framework/Versions/Current/Resources/bin/hython",
    ),
}


def _make_install(root: Path, layout: str) -> Path:
    directory, subpath = _LAYOUTS[layout]
    hython = root / directory / subpath
    hython.parent.mkdir(parents=True, exist_ok=True)
    hython.write_text("", encoding="utf-8")
    return hython


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Point discovery at tmp_path only, with no $HFS leaking in."""
    monkeypatch.delenv("HFS", raising=False)
    monkeypatch.setattr(
        "run_integration._search_patterns", lambda: [f"{tmp_path.as_posix()}/*"]
    )
    return tmp_path


@pytest.mark.parametrize("layout", sorted(_LAYOUTS))
def test_each_platform_layout_is_found(isolated, layout):
    expected = _make_install(isolated, layout)
    assert find_all_hython() == [expected]


def test_macos_framework_path_is_not_confused_for_a_bin_path(isolated):
    """The macOS interpreter is not at bin/hython, so bin/ must not be assumed."""
    expected = _make_install(isolated, "macos")
    found = find_all_hython()
    assert found == [expected]
    assert "Houdini.framework" in str(found[0])


def test_newest_install_comes_first(isolated):
    for name in ("hfs20.5.278", "hfs22.0.368", "hfs21.0.440"):
        hython = isolated / name / "bin" / "hython"
        hython.parent.mkdir(parents=True, exist_ok=True)
        hython.write_text("", encoding="utf-8")

    found = [path.parent.parent.name for path in find_all_hython()]
    assert found == ["hfs22.0.368", "hfs21.0.440", "hfs20.5.278"]


def test_all_installs_are_returned_not_just_the_newest(isolated):
    _make_install(isolated, "linux")
    _make_install(isolated, "windows")
    assert len(find_all_hython()) == 2


def test_overlapping_patterns_yield_one_entry(monkeypatch, tmp_path):
    """%PROGRAMFILES% and the literal C: fallback can name the same directory."""
    monkeypatch.delenv("HFS", raising=False)
    expected = _make_install(tmp_path, "windows")
    pattern = f"{tmp_path.as_posix()}/*"
    monkeypatch.setattr("run_integration._search_patterns", lambda: [pattern, pattern])

    assert find_all_hython() == [expected]


def test_hfs_is_searched(monkeypatch, tmp_path):
    """A relocated install is reachable through $HFS alone."""
    directory, subpath = _LAYOUTS["linux"]
    hython = tmp_path / "studio_mount" / directory / subpath
    hython.parent.mkdir(parents=True, exist_ok=True)
    hython.write_text("", encoding="utf-8")

    monkeypatch.setenv("HFS", str(hython.parent.parent))
    monkeypatch.setattr("run_integration._search_patterns", lambda: [])

    assert find_all_hython() == [hython]


def test_hfs_does_not_duplicate_a_pattern_hit(monkeypatch, tmp_path):
    expected = _make_install(tmp_path, "linux")
    monkeypatch.setenv("HFS", str(expected.parent.parent))
    monkeypatch.setattr(
        "run_integration._search_patterns", lambda: [f"{tmp_path.as_posix()}/*"]
    )

    assert find_all_hython() == [expected]


def test_directory_without_an_interpreter_is_ignored(isolated):
    (isolated / "Houdini 21.0.440" / "bin").mkdir(parents=True)
    assert find_all_hython() == []


def test_no_installs_returns_empty(isolated):
    assert find_all_hython() == []


def test_programfiles_is_honoured(monkeypatch, tmp_path):
    """A Windows install on another drive must still be found."""
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path / "D_drive"))
    from run_integration import _search_patterns

    patterns = _search_patterns()
    assert any(str(tmp_path / "D_drive").replace("\\", "/") in p for p in patterns)
    # The default location stays in the list as a fallback.
    assert any("C:/Program Files" in p for p in patterns)


def test_every_supported_platform_has_a_pattern():
    from run_integration import _search_patterns

    joined = " ".join(_search_patterns())
    assert "Side Effects Software" in joined, "no Windows pattern"
    assert "/Applications/Houdini" in joined, "no macOS pattern"
    assert "/opt/hfs" in joined, "no Linux pattern"


###### macOS framework layouts
#
# Neither of the maintainers has a Mac, so these reproduce the two layouts
# SideFX's own shipped help documents under ":platform:Mac" rather than relying
# on an assumption about which one is real:
#
#     .../Houdini.framework/Versions/Current/Resources          (x2 in the docs)
#     .../Houdini.framework/Versions/<version>/Resources/bin     (x1, the Mac bin)


def _framework_hython(root: Path, version: str) -> Path:
    hython = (
        root
        / "Houdini20.5.654"
        / "Frameworks"
        / "Houdini.framework"
        / "Versions"
        / version
        / "Resources"
        / "bin"
        / "hython"
    )
    hython.parent.mkdir(parents=True, exist_ok=True)
    hython.write_text("", encoding="utf-8")
    return hython


def test_macos_current_symlink_layout(isolated):
    expected = _framework_hython(isolated, "Current")
    assert find_all_hython() == [expected]


def test_macos_version_numbered_layout(isolated):
    """An install without the Current symlink must still be found."""
    expected = _framework_hython(isolated, "20.5")
    assert find_all_hython() == [expected]


def test_macos_prefers_current_when_both_exist(isolated):
    current = _framework_hython(isolated, "Current")
    _framework_hython(isolated, "20.5")
    assert find_all_hython() == [current], "the exact path should win over the glob"


def test_macos_multiple_framework_versions_pick_deterministically(isolated):
    """Without Current, several versioned dirs must not order randomly."""
    _framework_hython(isolated, "20.5")
    _framework_hython(isolated, "19.5")
    found = find_all_hython()
    assert len(found) == 1
    assert "19.5" in str(found[0]), "expected the sorted-first version"
