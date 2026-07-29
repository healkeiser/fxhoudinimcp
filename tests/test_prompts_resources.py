"""Tests for MCP prompt templates and resources.

Prompts must render with no leftover {placeholders}; resources must
delegate to the right bridge commands with valid arguments.
"""

from __future__ import annotations

# Built-in
import re
from pathlib import Path

# Third-party
import pytest

# Internal
from fxhoudinimcp.prompts.workflows import (
    debug_scene,
    hda_development,
    pdg_pipeline,
    procedural_modeling_workflow,
    simulation_setup,
    usd_scene_assembly,
)
from fxhoudinimcp.resources.geo_resources import geo_summary
from fxhoudinimcp.resources.scene_resources import (
    installed_hdas,
    node_info,
    node_types,
    scene_errors,
    scene_info,
    scene_tree,
)
from fxhoudinimcp.resources.usd_resources import usd_stage

_PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


class TestPromptTemplates:
    @pytest.mark.parametrize(
        ("render", "marker"),
        [
            (lambda: procedural_modeling_workflow("a rocky cliff"), "rocky cliff"),
            (lambda: usd_scene_assembly("a desert at dusk"), "desert at dusk"),
            (lambda: simulation_setup("pyro", "a campfire"), "campfire"),
            (lambda: pdg_pipeline("wedge 10 variants"), "wedge 10 variants"),
            (lambda: hda_development("a rock generator"), "rock generator"),
            (lambda: debug_scene("slow cooking"), "slow cooking"),
        ],
        ids=["procedural", "usd", "simulation", "pdg", "hda", "debug"],
    )
    def test_prompt_renders_completely(self, render, marker):
        text = render()
        assert marker in text
        leftovers = _PLACEHOLDER.findall(text)
        assert not leftovers, f"unrendered placeholders: {leftovers}"

    def test_housekeeping_block_is_injected(self):
        text = procedural_modeling_workflow("anything")
        assert "log_status" in text
        assert "{network_housekeeping}" not in text


class TestSimulationDispatch:
    """simulation_setup serves a solver-specific guide where one exists.

    The generic file had to cover pyro, FLIP, Vellum, RBD and MPM at once, so it
    could not say more than a table row about any of them, while Houdini ships a
    whole manual per solver. A wrong dispatch silently serves the shallow file.
    """

    def test_pyro_gets_the_pyro_guide(self):
        text = simulation_setup("pyro", "a campfire")
        assert "campfire" in text
        # Content only the specialised file carries.
        assert "Voxel Size" in text
        assert "pyro/lookdev" in text

    def test_case_and_whitespace_do_not_defeat_dispatch(self):
        assert "Voxel Size" in simulation_setup("  PYRO  ", "x")

    def test_unknown_solver_falls_back_to_the_generic_guide(self):
        text = simulation_setup("ripple", "a pond")
        assert "pond" in text
        assert "DOP-level nodes" in text
        assert "Voxel Size" not in text

    @pytest.mark.parametrize(
        ("sim_type", "marker"),
        [
            ("flip", "particle separation"),
            ("liquid", "particle separation"),
            ("rbd", "rbdmaterialfracture"),
            ("fracture", "rbdmaterialfracture"),
            ("cloth", "pscale"),
            ("vellum", "pscale"),
            ("mpm", "Particle Separation"),
            ("sand", "Particle Separation"),
            ("smoke", "Voxel Size"),
        ],
    )
    def test_aliases_reach_the_corpus_that_documents_them(self, sim_type, marker):
        """SideFX files FLIP under fluid/ and RBD under destruction/.

        Users say "flip" and "rbd", so the alias map has to hold, or the request
        silently gets the shallow generic guide instead.
        """
        text = simulation_setup(sim_type, "x")
        assert marker.lower() in text.lower(), sim_type

    def test_no_dispatch_leaves_placeholders_unrendered(self):
        for sim_type in ("pyro", "ripple", "flip"):
            text = simulation_setup(sim_type, "x")
            assert not re.findall(r"\{[a-z_]+\}", text), sim_type


class TestResources:
    @pytest.mark.asyncio
    async def test_scene_resources_delegate(self, process_bridge, mock_bridge):
        await scene_info()
        mock_bridge.execute.assert_called_with("scene.get_scene_info", {})

        await node_info("obj/geo1")
        mock_bridge.execute.assert_called_with("nodes.get_node_info", {"node_path": "/obj/geo1"})

        await scene_tree()
        # "/" is a real node path; the old "all" value crashed the handler.
        mock_bridge.execute.assert_called_with("scene.get_context_info", {"context": "/"})

        await scene_errors()
        mock_bridge.execute.assert_called_with("viewport.find_error_nodes", {"root_path": "/"})

        await node_types("Sop")
        mock_bridge.execute.assert_called_with("nodes.list_node_types", {"context": "Sop"})

        await installed_hdas()
        mock_bridge.execute.assert_called_with("hda.list_installed_hdas", {})

    @pytest.mark.asyncio
    async def test_geo_and_usd_resources_delegate(self, process_bridge, mock_bridge):
        await geo_summary("obj/geo1/box1")
        command, params = mock_bridge.execute.call_args.args
        assert command == "geometry.get_geometry_info"
        assert params["node_path"].startswith("/")

        await usd_stage("obj/lopnet1/sphere1")
        command, params = mock_bridge.execute.call_args.args
        assert command == "lops.get_stage_info"
        assert params["node_path"].startswith("/")


class TestInstructionHeaderCounts:
    """The instructions open by stating how many tools the server exposes.

    It said "177 tools across 21 categories" while the server actually registered
    179 across 22, because the sentence is hand-written and nothing checked it.
    An undercount is not harmless: it is the first thing a model reads, and it
    invites the conclusion that a tool it cannot see simply does not exist.
    """

    _HEADER = re.compile(r"(\d+) tools across (\d+) categories")

    @pytest.mark.asyncio
    async def test_header_matches_registered_tools(self):
        # Importing fxhoudinimcp.tools is what registers them on mcp; without it
        # list_tools() is empty and this test would compare against zero.
        import fxhoudinimcp.tools  # noqa: F401
        from fxhoudinimcp._loader import load_markdown
        from fxhoudinimcp.server import mcp

        text = load_markdown("instructions/server_instructions.md")
        match = self._HEADER.search(text)
        assert match, "the 'N tools across M categories' sentence has gone missing"

        claimed_tools, claimed_categories = int(match.group(1)), int(match.group(2))
        actual_tools = len(await mcp.list_tools())

        modules = {
            path.stem
            for path in Path(fxhoudinimcp.tools.__file__).resolve().parent.glob("*.py")
            if path.stem != "__init__"
        }

        assert claimed_tools == actual_tools, (
            f"server_instructions.md claims {claimed_tools} tools but the server "
            f"registers {actual_tools}"
        )
        assert claimed_categories == len(modules), (
            f"server_instructions.md claims {claimed_categories} categories but "
            f"fxhoudinimcp/tools has {len(modules)}: {sorted(modules)}"
        )
