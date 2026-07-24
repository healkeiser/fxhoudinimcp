"""Tests for MCP tool wrappers: validate bridge delegation."""

from __future__ import annotations

# Third-party
import pytest

# Internal
from fxhoudinimcp.errors import ConnectionError as HoudiniConnectionError
from fxhoudinimcp.tools.code import execute_python
from fxhoudinimcp.tools.materials import list_materials
from fxhoudinimcp.tools.nodes import create_node
from fxhoudinimcp.tools.scene import (
    get_houdini_connection_status,
    get_scene_info,
    new_scene,
)
from fxhoudinimcp.tools.workflows import setup_pyro_sim


class TestSceneTools:
    @pytest.mark.asyncio
    async def test_get_scene_info(self, mock_ctx, mock_bridge):
        mock_bridge.execute.return_value = {"hip_file": "/tmp/test.hip"}
        result = await get_scene_info(mock_ctx)
        mock_bridge.execute.assert_called_once_with("scene.get_scene_info")
        assert result == {"hip_file": "/tmp/test.hip"}

    @pytest.mark.asyncio
    async def test_new_scene(self, mock_ctx, mock_bridge):
        mock_bridge.execute.return_value = {"created": True}
        result = await new_scene(mock_ctx, save_current=True)
        mock_bridge.execute.assert_called_once_with("scene.new_scene", {"save_current": True})

    @pytest.mark.asyncio
    async def test_connection_status_success(self, mock_ctx, mock_bridge):
        mock_bridge.base_url = "http://localhost:8100"
        mock_bridge.health_check.return_value = {"status": "ok", "pid": 123}
        result = await get_houdini_connection_status(mock_ctx)
        assert result == {
            "connected": True,
            "base_url": "http://localhost:8100",
            "health": {"status": "ok", "pid": 123},
        }

    @pytest.mark.asyncio
    async def test_connection_status_disconnect(self, mock_ctx, mock_bridge):
        mock_bridge.base_url = "http://localhost:8100"
        mock_bridge.health_check.side_effect = HoudiniConnectionError(
            "Cannot connect",
            details={"url": "http://localhost:8100"},
        )
        result = await get_houdini_connection_status(mock_ctx)
        assert result["connected"] is False
        assert result["base_url"] == "http://localhost:8100"
        assert result["details"] == {"url": "http://localhost:8100"}


class TestNodeTools:
    @pytest.mark.asyncio
    async def test_create_node_required_params(self, mock_ctx, mock_bridge):
        mock_bridge.execute.return_value = {"path": "/obj/geo1/box1"}
        result = await create_node(mock_ctx, parent_path="/obj/geo1", node_type="box")
        mock_bridge.execute.assert_called_once_with(
            "nodes.create_node",
            {"parent_path": "/obj/geo1", "node_type": "box"},
        )

    @pytest.mark.asyncio
    async def test_create_node_all_params(self, mock_ctx, mock_bridge):
        await create_node(
            mock_ctx,
            parent_path="/obj",
            node_type="geo",
            name="my_geo",
            position=[0, 0],
        )
        mock_bridge.execute.assert_called_once_with(
            "nodes.create_node",
            {"parent_path": "/obj", "node_type": "geo", "name": "my_geo", "position": [0, 0]},
        )


class TestCodeTools:
    @pytest.mark.asyncio
    async def test_execute_python_code_only(self, mock_ctx, mock_bridge):
        result = await execute_python(
            mock_ctx,
            code="print('hi')",
            justification="no dedicated tool prints to the console",
        )
        mock_bridge.execute.assert_called_once_with(
            "code.execute_python",
            {"code": "print('hi')"},
        )
        # The justification is echoed back, never forwarded to Houdini.
        assert result["justification"]

    @pytest.mark.asyncio
    async def test_execute_python_with_return(self, mock_ctx, mock_bridge):
        await execute_python(
            mock_ctx,
            code="x = 1 + 1",
            justification="no dedicated tool evaluates arbitrary Python",
            return_expression="x",
        )
        mock_bridge.execute.assert_called_once_with(
            "code.execute_python",
            {"code": "x = 1 + 1", "return_expression": "x"},
        )

    @pytest.mark.asyncio
    async def test_justification_required_in_schemas(self):
        """The schema must force clients to articulate why VEX/Python."""
        from fxhoudinimcp.server import mcp

        tools = {t.name: t for t in await mcp.list_tools()}
        for tool_name in ("execute_python", "create_wrangle"):
            schema = tools[tool_name].inputSchema
            assert "justification" in schema["required"], (
                f"{tool_name} must require a justification"
            )


class TestWorkflowTools:
    @pytest.mark.asyncio
    async def test_setup_pyro_defaults(self, mock_ctx, mock_bridge):
        await setup_pyro_sim(mock_ctx)
        mock_bridge.execute.assert_called_once_with(
            "workflow.setup_pyro_sim",
            {
                "source_geo": "/obj/geo1/sphere1",
                "container": "box",
                "res_scale": 1.0,
                "substeps": 1,
                "name": "pyro_sim",
            },
        )


class TestMaterialTools:
    @pytest.mark.asyncio
    async def test_list_materials_default(self, mock_ctx, mock_bridge):
        await list_materials(mock_ctx)
        mock_bridge.execute.assert_called_once_with(
            "materials.list_materials",
            {"root_path": "/mat"},
        )


class TestGateControlToolsAreNotAgentReachable:
    """ADR-0007 Phase 2 — the authority-escalation gate tools must NOT be exposed as agent tools.

    An agent that can set_permission_mode (change its own tier) or approve_pending_call (approve its
    own queued call) defeats the gate. This is the fence that lets a Codex child (no CLI
    --disallowed-tools) be added to the panel safely; the panel/operator reach these via a DIRECT
    bridge call, not the FastMCP wrapper, so removing the wrappers does not affect them.
    """

    @pytest.mark.asyncio
    async def test_escalation_gate_tools_are_not_registered(self):
        from fxhoudinimcp.server import mcp

        names = {t.name for t in await mcp.list_tools()}
        assert "set_permission_mode" not in names, (
            "set_permission_mode must NOT be an agent tool — it is authority escalation (ADR-0007 P2)"
        )
        assert "approve_pending_call" not in names, (
            "approve_pending_call must NOT be an agent tool — it is a self-approval bypass (ADR-0007 P2)"
        )

    @pytest.mark.asyncio
    async def test_readonly_gate_introspection_tools_are_still_registered(self):
        # The fence is surgical: the agent may still SEE the mode and the queue, just not change them.
        from fxhoudinimcp.server import mcp

        names = {t.name for t in await mcp.list_tools()}
        assert "get_permission_mode" in names
        assert "list_pending_calls" in names

    @pytest.mark.asyncio
    async def test_the_removed_tool_symbols_are_gone_from_the_module(self):
        # Belt-and-suspenders: a re-added @mcp.tool() would re-register it, so also pin the symbols.
        import fxhoudinimcp.tools.gate as gate_tools

        assert not hasattr(gate_tools, "set_permission_mode")
        assert not hasattr(gate_tools, "approve_pending_call")
