"""MCP tool definitions for animation operations."""

from __future__ import annotations

# Built-in
from typing import Any

# Third-party
from mcp.server.fastmcp import Context

# Internal
from fxhoudinimcp.server import mcp, _get_bridge


@mcp.tool()
async def set_keyframe(
    ctx: Context,
    node_path: str,
    parm_name: str,
    frame: float,
    value: float,
    slope: float | None = None,
    accel: float | None = None,
) -> dict:
    """Set a single keyframe on a node parameter.

    Args:
        node_path: Path to the node (e.g. "/obj/geo1").
        parm_name: Parameter name (e.g. "tx", "sy").
        frame: Frame number for the keyframe.
        value: Value at this keyframe.
        slope: Optional tangent slope.
        accel: Optional acceleration.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {
        "node_path": node_path,
        "parm_name": parm_name,
        "frame": frame,
        "value": value,
    }
    if slope is not None:
        params["slope"] = slope
    if accel is not None:
        params["accel"] = accel
    return await bridge.execute("animation.set_keyframe", params)


@mcp.tool()
async def set_keyframes(
    ctx: Context,
    node_path: str,
    parm_name: str,
    keyframes: list[dict],
) -> dict:
    """Batch-set multiple keyframes on a node parameter.

    Args:
        node_path: Path to the node.
        parm_name: Parameter name.
        keyframes: List of keyframe dicts, each with "frame" and "value",
            and optionally "slope" and "accel".
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "animation.set_keyframes",
        {
            "node_path": node_path,
            "parm_name": parm_name,
            "keyframes": keyframes,
        },
    )


@mcp.tool()
async def delete_keyframe(
    ctx: Context,
    node_path: str,
    parm_name: str,
    frame: float,
) -> dict:
    """Delete a keyframe at a specific frame on a parameter.

    Args:
        node_path: Path to the node.
        parm_name: Parameter name.
        frame: Frame number of the keyframe to delete.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "animation.delete_keyframe",
        {"node_path": node_path, "parm_name": parm_name, "frame": frame},
    )


@mcp.tool()
async def get_keyframes(
    ctx: Context,
    node_path: str,
    parm_name: str,
) -> dict:
    """Get all keyframes on a parameter, including frame, value, slope,
    acceleration, and expression for each.

    Args:
        node_path: Path to the node.
        parm_name: Parameter name.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "animation.get_keyframes",
        {"node_path": node_path, "parm_name": parm_name},
    )


@mcp.tool()
async def set_frame(ctx: Context, frame: float) -> dict:
    """Set the current frame in the Houdini timeline.

    Args:
        frame: The frame number to set.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("animation.set_frame", {"frame": frame})


@mcp.tool()
async def get_frame(ctx: Context) -> dict:
    """Get the current frame number and FPS."""
    bridge = _get_bridge(ctx)
    return await bridge.execute("animation.get_frame", {})


@mcp.tool()
async def set_frame_range(ctx: Context, start: float, end: float) -> dict:
    """Set the global frame range for the scene.

    Args:
        start: Start frame number.
        end: End frame number.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "animation.set_frame_range",
        {"start": start, "end": end},
    )


@mcp.tool()
async def set_playback_range(ctx: Context, start: float, end: float) -> dict:
    """Set the playback range (the green range in the timeline).

    Args:
        start: Start frame number.
        end: End frame number.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "animation.set_playback_range",
        {"start": start, "end": end},
    )


@mcp.tool()
async def playbar_control(
    ctx: Context,
    action: str,
    real_time: bool | None = None,
    fps: float | None = None,
) -> dict:
    """Control Houdini playback: play, stop, or reverse.

    Args:
        action: One of "play", "stop", or "reverse".
        real_time: If provided, enable or disable real-time playback.
        fps: If provided, set the frames per second.
    """
    bridge = _get_bridge(ctx)
    params: dict[str, Any] = {"action": action}
    if real_time is not None:
        params["real_time"] = real_time
    if fps is not None:
        params["fps"] = fps
    return await bridge.execute("animation.playbar_control", params)
