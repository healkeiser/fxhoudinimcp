"""MCP tool definitions for DOP (dynamics/simulation) operations."""

from __future__ import annotations

# Built-in
from typing import Any

# Third-party
from mcp.server.fastmcp import Context

# Internal
from fxhoudinimcp.server import mcp, _get_bridge


@mcp.tool()
async def get_simulation_info(ctx: Context, node_path: str) -> dict:
    """Get DOP network simulation state.

    Args:
        node_path: DOP network node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "dops.get_simulation_info", {"node_path": node_path}
    )


@mcp.tool()
async def list_dop_objects(ctx: Context, node_path: str) -> dict:
    """List all DOP objects in a simulation.

    Args:
        node_path: DOP network node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "dops.list_dop_objects", {"node_path": node_path}
    )


@mcp.tool()
async def get_dop_object(
    ctx: Context, node_path: str, object_name: str
) -> dict:
    """Get detailed data for a specific DOP object.

    Args:
        node_path: DOP network node path.
        object_name: DOP object name.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "dops.get_dop_object",
        {"node_path": node_path, "object_name": object_name},
    )


@mcp.tool()
async def get_dop_field(
    ctx: Context,
    node_path: str,
    object_name: str,
    data_path: str,
    field_name: str,
) -> dict:
    """Read a specific field value from a DOP record.

    Args:
        node_path: DOP network node path.
        object_name: DOP object name.
        data_path: Dot-separated subdata path (e.g. "Geometry", "Forces/Gravity").
        field_name: Field name to read.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "dops.get_dop_field",
        {
            "node_path": node_path,
            "object_name": object_name,
            "data_path": data_path,
            "field_name": field_name,
        },
    )


@mcp.tool()
async def get_dop_relationships(ctx: Context, node_path: str) -> dict:
    """List all relationships between DOP objects.

    Args:
        node_path: DOP network node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "dops.get_dop_relationships", {"node_path": node_path}
    )


@mcp.tool()
async def step_simulation(ctx: Context, node_path: str, steps: int = 1) -> dict:
    """Advance the simulation by a number of frames.

    Args:
        node_path: DOP network node path.
        steps: Number of frames to advance.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "dops.step_simulation",
        {"node_path": node_path, "steps": steps},
    )


@mcp.tool()
async def reset_simulation(ctx: Context, node_path: str) -> dict:
    """Reset the simulation to its initial state.

    Args:
        node_path: DOP network node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "dops.reset_simulation", {"node_path": node_path}
    )


@mcp.tool()
async def get_sim_memory_usage(ctx: Context, node_path: str) -> dict:
    """Get detailed memory breakdown for the simulation.

    Args:
        node_path: DOP network node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "dops.get_sim_memory_usage", {"node_path": node_path}
    )
