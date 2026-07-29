"""Live tests for the shipped-documentation tools."""

from __future__ import annotations

# Third-party
import pytest

pytestmark = pytest.mark.integration


class TestSearchHelp:
    def test_concept_search_finds_relevant_pages(self, call):
        result = call("help.search_help", query="pyro shaping", limit=5)
        assert result["total_matches"] > 0
        top = result["results"][0]
        assert top["path"] and top["excerpt"]
        # The top result must be retrievable.
        page = call("help.get_help_page", path=top["path"])
        assert "pyro" in page["text"].lower()

    def test_vex_function_lookup(self, call):
        result = call("help.search_help", query="noise", scope="vex", limit=10)
        paths = [r["path"] for r in result["results"]]
        assert any("noise" in p for p in paths), paths

    def test_all_words_must_match(self, call):
        result = call(
            "help.search_help",
            query="qzxvfk_definitely_not_a_word",
            limit=3,
        )
        assert result["total_matches"] == 0

    def test_unknown_scope_is_clean_error(self, call):
        error = call("help.search_help", query="noise", scope="cookbook", expect_error=True)
        assert "cookbook" in error["message"]
        assert "vex" in error["message"]


class TestGetHelpPage:
    def test_expression_function_page(self, call):
        page = call("help.get_help_page", path="expressions/ch")
        assert page["title"], page
        assert "channel" in page["text"].lower()

    def test_extension_and_slashes_are_forgiven(self, call):
        page = call("help.get_help_page", path="/nodes/sop/scatter.txt")
        assert page["path"] == "nodes/sop/scatter"
        assert "scatter" in page["text"].lower()

    def test_unknown_page_suggests_close_matches(self, call):
        error = call("help.get_help_page", path="nodes/sop/scatterr", expect_error=True)
        assert "scatter" in error["message"]


class TestStrippedBuildDegradation:
    def test_missing_help_dir_yields_actionable_error(self, tmp_path, monkeypatch):
        """A Houdini build without local help must say so, not crash."""
        import hou
        from fxhoudinimcp_server.handlers import help_handlers

        monkeypatch.setattr(help_handlers, "_help_dir", lambda: str(tmp_path / "no_help_here"))
        with pytest.raises(hou.OperationFailed) as excinfo:
            help_handlers.search_help(query="anything")
        message = str(excinfo.value)
        assert "no local help" in message
        assert "get_node_card" in message
