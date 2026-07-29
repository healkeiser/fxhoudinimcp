"""Live tests for shelf tool discovery and execution.

Some setups are authored by a shelf tool rather than by node creation: the ocean
procedural's internals come from dopparticlefluidtoolutils.largeOcean, so
build_network structurally cannot produce them. A recorded session spent seven
execute_python calls listing tools, reading their scripts and calling the worker
functions by hand.
"""

from __future__ import annotations

# Third-party
import hou
import pytest

pytestmark = pytest.mark.integration


class TestShelfToolDiscovery:
    def test_filter_finds_the_ocean_tools(self, call):
        result = call("shelf.list_shelf_tools", filter="ocean", limit=20)
        # A full install ships thousands, which is why filtering is mandatory.
        assert result["total_installed"] > 1000, result["total_installed"]
        assert result["matched"] >= 1
        names = {tool["name"] for tool in result["tools"]}
        assert any("ocean" in name for name in names), sorted(names)

    def test_unfiltered_list_is_capped_and_says_so(self, call):
        result = call("shelf.list_shelf_tools", limit=5)
        assert result["returned"] == 5
        assert result["truncated"] is True
        assert result["matched"] == result["total_installed"]

    def test_script_names_the_module_holding_the_recipe(self, call):
        result = call("shelf.get_shelf_tool_script", tool_name="geometry_largeocean")
        assert result["label"]
        assert result["script"]
        # The value is the pointer: three lines that name the toolutils module
        # where SideFX's actual recipe lives.
        assert "dopparticlefluidtoolutils" in result["imports"], result["imports"]

    def test_unknown_tool_suggests_close_matches(self, call):
        error = call(
            "shelf.get_shelf_tool_script", tool_name="geometry_largeocan", expect_error=True
        )
        assert "geometry_largeocean" in error["message"], error["message"]


class TestRunShelfTool:
    def test_missing_tool_is_a_clean_error(self, call):
        error = call("shelf.run_shelf_tool", tool_name="not_a_real_tool", expect_error=True)
        assert "list_shelf_tools" in error["message"]

    def test_ui_dependent_tool_explains_itself_headless(self, call):
        """Most shelf tools call hou.ui, so headless they must say so.

        The old behaviour of that call was AttributeError: module 'hou' has no
        attribute 'ui', which reads like a bug in the server rather than a tool
        that needs a graphical session.
        """
        if hou.isUIAvailable():
            pytest.skip("graphical session: covered by gui_session_check.py instead")
        error = call(
            "shelf.run_shelf_tool",
            tool_name="geometry_largeocean",
            parent_path="/obj",
            expect_error=True,
        )
        message = error["message"]
        assert "graphical Houdini" in message, message
        assert "get_shelf_tool_script" in message, message
