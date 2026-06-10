"""Tests for MCP prompt templates and resources.

Prompts must render with no leftover {placeholders}; resources must
delegate to the right bridge commands with valid arguments.
"""

from __future__ import annotations

# Built-in
import re

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


class TestResources:
    @pytest.mark.asyncio
    async def test_scene_resources_delegate(self, mock_ctx, mock_bridge):
        await scene_info(mock_ctx)
        mock_bridge.execute.assert_called_with("scene.get_scene_info", {})

        await node_info("obj/geo1", mock_ctx)
        mock_bridge.execute.assert_called_with(
            "nodes.get_node_info", {"node_path": "/obj/geo1"}
        )

        await scene_tree(mock_ctx)
        # "/" is a real node path; the old "all" value crashed the handler.
        mock_bridge.execute.assert_called_with(
            "scene.get_context_info", {"context": "/"}
        )

        await scene_errors(mock_ctx)
        mock_bridge.execute.assert_called_with(
            "viewport.find_error_nodes", {"root_path": "/"}
        )

        await node_types("Sop", mock_ctx)
        mock_bridge.execute.assert_called_with(
            "nodes.list_node_types", {"context": "Sop"}
        )

        await installed_hdas(mock_ctx)
        mock_bridge.execute.assert_called_with("hda.list_installed_hdas", {})

    @pytest.mark.asyncio
    async def test_geo_and_usd_resources_delegate(self, mock_ctx, mock_bridge):
        await geo_summary("obj/geo1/box1", mock_ctx)
        command, params = mock_bridge.execute.call_args.args
        assert command == "geometry.get_geometry_info"
        assert params["node_path"].startswith("/")

        await usd_stage("obj/lopnet1/sphere1", mock_ctx)
        command, params = mock_bridge.execute.call_args.args
        assert command == "lops.get_stage_info"
        assert params["node_path"].startswith("/")
