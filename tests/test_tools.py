"""Tests for MCP tool wrappers: validate bridge delegation."""

from __future__ import annotations

# Third-party
import pytest
from support import tool_input_schema

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
        await new_scene(mock_ctx, save_current=True)
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
    async def test_connection_status_backfills_hip_file(self, mock_ctx, mock_bridge):
        """mcp.health is HOM-free, so hip_file comes from the scene handler.

        Callers read health["hip_file"], so the key has to keep appearing even
        though the health endpoint no longer knows it.
        """
        mock_bridge.base_url = "http://localhost:8100"
        mock_bridge.health_check.return_value = {"status": "ok", "pid": 123}
        mock_bridge.execute.return_value = {
            "hip_file": "/tmp/shot.hip",
            "houdini_version": "22.0.368",
        }

        result = await get_houdini_connection_status(mock_ctx)

        assert result["connected"] is True
        assert result["health"]["hip_file"] == "/tmp/shot.hip"
        assert result["health"]["houdini_version"] == "22.0.368"
        assert result["health"]["pid"] == 123

    @pytest.mark.asyncio
    async def test_connection_status_survives_scene_lookup_failure(self, mock_ctx, mock_bridge):
        """A busy or wedged Houdini must not stop this reporting connected."""
        mock_bridge.base_url = "http://localhost:8100"
        mock_bridge.health_check.return_value = {"status": "ok", "pid": 123}
        mock_bridge.execute.side_effect = HoudiniConnectionError("timed out")

        result = await get_houdini_connection_status(mock_ctx)

        assert result["connected"] is True
        assert result["health"] == {"status": "ok", "pid": 123}

    @pytest.mark.asyncio
    async def test_connection_status_keeps_health_hip_file(self, mock_ctx, mock_bridge):
        """An older plugin still reporting hip_file must not be second-guessed."""
        mock_bridge.base_url = "http://localhost:8100"
        mock_bridge.health_check.return_value = {
            "status": "ok",
            "pid": 123,
            "hip_file": "/from/health.hip",
        }

        result = await get_houdini_connection_status(mock_ctx)

        assert result["health"]["hip_file"] == "/from/health.hip"
        mock_bridge.execute.assert_not_called()

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
        await create_node(mock_ctx, parent_path="/obj/geo1", node_type="box")
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
            schema = tool_input_schema(tools[tool_name])
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
