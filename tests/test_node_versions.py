"""Tests for the shipped sampled-version record and its staleness signal.

The version markers in server_instructions.md cannot describe a Houdini nobody
has sampled. Read literally, "(21.0+)" includes a future 23.0, so a node dropped
there would still be advertised. These tests cover the code that notices that.
"""

from __future__ import annotations

# Built-in
import json
import re

# Third-party
import pytest

# Internal
from fxhoudinimcp import node_versions


@pytest.fixture(autouse=True)
def clear_cache():
    node_versions.load_table.cache_clear()
    yield
    node_versions.load_table.cache_clear()


@pytest.fixture
def table(monkeypatch, tmp_path):
    """Point the loader at a table covering 20.5 through 22.0."""
    path = tmp_path / "node_versions.json"
    path.write_text(
        json.dumps(
            {
                "builds": {
                    "20.5.278": "20.5",
                    "21.0.440": "21.0",
                    "22.0.368": "22.0",
                },
                "series": ["20.5", "21.0", "22.0"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(node_versions, "_TABLE", path)
    return path


###### The table that actually ships


class TestShippedTable:
    def test_the_real_table_is_readable(self):
        loaded = node_versions.load_table()
        assert loaded["builds"], "no builds in the shipped record"
        assert loaded["series"], "no series in the shipped record"

    def test_the_shipped_record_stays_small(self):
        """The per-node evidence must not leak into the package."""
        size = node_versions._TABLE.stat().st_size
        assert size < 20_000, f"shipped record grew to {size} bytes"

    def test_the_real_table_covers_more_than_one_series(self):
        """A single series cannot support any range annotation."""
        assert len(node_versions.sampled_series()) >= 2

    def test_series_are_ordered_oldest_first(self):
        series = node_versions.sampled_series()
        assert series == sorted(series, key=lambda s: tuple(int(p) for p in s.split(".")))

    def test_supported_versions_are_not_flagged(self):
        for series in node_versions.sampled_series():
            assert node_versions.staleness_warning(f"{series}.100") is None


###### Version parsing


class TestSeriesOf:
    @pytest.mark.parametrize(
        ("version", "expected"),
        [
            ("22.0.368", "22.0"),
            ("20.5.278", "20.5"),
            ("21.0", "21.0"),
            ("22.0.368.1", "22.0"),
        ],
    )
    def test_reduces_to_minor_series(self, version, expected):
        assert node_versions.series_of(version) == expected

    @pytest.mark.parametrize("version", [None, "", "unknown", "22", "abc.def", "x.y.z"])
    def test_unusable_versions_give_none(self, version):
        assert node_versions.series_of(version) is None


###### The staleness signal


class TestStalenessWarning:
    def test_covered_version_is_silent(self, table):
        assert node_versions.staleness_warning("21.0.440") is None

    def test_newer_version_warns_and_says_why(self, table):
        warning = node_versions.staleness_warning("23.0.100")
        assert warning is not None
        assert "23.0" in warning
        assert "newer" in warning
        # Must point at the live check, which is the actual guarantee.
        assert "build_network" in warning or "list_node_types" in warning

    def test_older_version_warns(self, table):
        warning = node_versions.staleness_warning("19.5.400")
        assert warning is not None
        assert "older" in warning

    def test_warning_names_what_is_covered(self, table):
        warning = node_versions.staleness_warning("23.0.100")
        for series in ("20.5", "21.0", "22.0"):
            assert series in warning

    @pytest.mark.parametrize("version", [None, "unknown", ""])
    def test_unknown_version_is_not_warned_about(self, table, version):
        """health reports "unknown" when it cannot tell; do not cry wolf."""
        assert node_versions.staleness_warning(version) is None

    def test_no_table_means_no_opinion(self, monkeypatch, tmp_path):
        monkeypatch.setattr(node_versions, "_TABLE", tmp_path / "absent.json")
        assert node_versions.staleness_warning("23.0.100") is None


###### Degradation


class TestDegradation:
    def test_missing_table_returns_empty_structures(self, monkeypatch, tmp_path):
        monkeypatch.setattr(node_versions, "_TABLE", tmp_path / "absent.json")
        loaded = node_versions.load_table()
        assert loaded == {"builds": {}, "series": []}

    def test_corrupt_table_does_not_raise(self, monkeypatch, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(node_versions, "_TABLE", path)
        assert node_versions.load_table() == {"builds": {}, "series": []}

    def test_table_missing_keys_is_tolerated(self, monkeypatch, tmp_path):
        path = tmp_path / "partial.json"
        path.write_text(json.dumps({"builds": {"22.0.368": "22.0"}}), encoding="utf-8")
        monkeypatch.setattr(node_versions, "_TABLE", path)
        loaded = node_versions.load_table()
        assert loaded["series"] == []
        assert loaded["builds"] == {"22.0.368": "22.0"}


class TestInstructionAnnotationsSurvive:
    """The generated node block must keep its version markers.

    tools/gen_node_domains.py emits the markers itself now, so a single run
    leaves a correct file. It used to emit bare names and depend on
    tools/gen_node_versions.py running afterwards, and running the first alone
    stripped every "(21.0+)" and "(20.5-21.0)": names stayed correct, so nothing
    caught it, while a 20.5 user was told about nodes that only exist in 22.0.

    This guards the fix rather than the old hazard. Losing the annotations again
    would be silent in exactly the same way.
    """

    _MARKER = re.compile(r"\(\d+\.\d+(?:\+|-\d+\.\d+)\)")

    def test_generated_block_still_carries_version_markers(self):
        from fxhoudinimcp._loader import load_markdown

        text = load_markdown("instructions/server_instructions.md")
        begin = text.index("<!-- BEGIN GENERATED: node domains -->")
        end = text.index("<!-- END GENERATED: node domains -->")
        block = text[begin:end]
        markers = self._MARKER.findall(block)
        assert len(markers) > 10, (
            "the node domain block has lost its version annotations; run "
            "python tools/gen_node_versions.py to restore them "
            f"(found {len(markers)})"
        )
