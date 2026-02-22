"""Animation handlers for FXHoudini-MCP.

Provides tools for keyframing, frame control, playback range, and
playbar control.
"""

from __future__ import annotations

# Third-party
import hou

# Internal
from fxhoudinimcp_server.dispatcher import register_handler


###### Helpers

def _get_parm(node_path: str, parm_name: str) -> hou.Parm:
    """Return a parameter object or raise if the node/parm is not found."""
    node = hou.node(node_path)
    if node is None:
        raise hou.NodeError(f"Node not found: {node_path}")
    parm = node.parm(parm_name)
    if parm is None:
        raise hou.OperationFailed(
            f"Parameter '{parm_name}' not found on node '{node_path}'. "
            f"Available parameters: {[p.name() for p in node.parms()[:30]]}"
        )
    return parm


def _keyframe_to_dict(key: hou.Keyframe) -> dict:
    """Convert a hou.Keyframe to a plain Python dict."""
    result = {
        "frame": key.frame(),
        "value": key.value(),
    }
    try:
        result["slope"] = key.slope()
    except Exception:
        result["slope"] = None
    try:
        result["accel"] = key.accel()
    except Exception:
        result["accel"] = None
    try:
        expr = key.expression()
        result["expression"] = expr if expr else None
    except Exception:
        result["expression"] = None
    try:
        result["in_slope"] = key.inSlope()
    except Exception:
        result["in_slope"] = None
    try:
        result["in_accel"] = key.inAccel()
    except Exception:
        result["in_accel"] = None
    return result


###### Handlers

def _set_keyframe(
    node_path: str,
    parm_name: str,
    frame: float,
    value: float,
    slope: float | None = None,
    accel: float | None = None,
) -> dict:
    """Set a single keyframe on a parameter."""
    parm = _get_parm(node_path, parm_name)

    key = hou.Keyframe()
    key.setFrame(frame)
    key.setValue(value)
    if slope is not None:
        key.setSlope(slope)
    if accel is not None:
        key.setAccel(accel)

    parm.setKeyframe(key)

    return {
        "node_path": node_path,
        "parm_name": parm_name,
        "frame": frame,
        "value": value,
        "slope": slope,
        "accel": accel,
        "status": "keyframe_set",
    }


def _set_keyframes(
    node_path: str,
    parm_name: str,
    keyframes: list,
) -> dict:
    """Batch-set multiple keyframes on a parameter.

    Each entry in keyframes is a dict with keys: frame, value, and
    optionally slope and accel.
    """
    parm = _get_parm(node_path, parm_name)

    if not keyframes:
        raise hou.OperationFailed("keyframes list must not be empty.")

    set_count = 0
    for kf_data in keyframes:
        frame = kf_data.get("frame")
        value = kf_data.get("value")
        if frame is None or value is None:
            raise hou.OperationFailed(
                f"Each keyframe must have 'frame' and 'value'. Got: {kf_data}"
            )

        key = hou.Keyframe()
        key.setFrame(float(frame))
        key.setValue(float(value))

        kf_slope = kf_data.get("slope")
        if kf_slope is not None:
            key.setSlope(float(kf_slope))

        kf_accel = kf_data.get("accel")
        if kf_accel is not None:
            key.setAccel(float(kf_accel))

        parm.setKeyframe(key)
        set_count += 1

    return {
        "node_path": node_path,
        "parm_name": parm_name,
        "keyframes_set": set_count,
        "status": "keyframes_set",
    }


def _delete_keyframe(
    node_path: str,
    parm_name: str,
    frame: float,
) -> dict:
    """Delete a keyframe at the specified frame."""
    parm = _get_parm(node_path, parm_name)

    # Find the keyframe at the given frame
    existing_keys = parm.keyframes()
    found = False
    for key in existing_keys:
        if abs(key.frame() - frame) < 0.0001:
            parm.deleteKeyframeAtFrame(key.frame())
            found = True
            break

    if not found:
        raise hou.OperationFailed(
            f"No keyframe found at frame {frame} on parameter "
            f"'{parm_name}' of node '{node_path}'."
        )

    return {
        "node_path": node_path,
        "parm_name": parm_name,
        "deleted_frame": frame,
        "remaining_keyframes": len(parm.keyframes()),
        "status": "keyframe_deleted",
    }


def _get_keyframes(
    node_path: str,
    parm_name: str,
) -> dict:
    """Get all keyframes on a parameter."""
    parm = _get_parm(node_path, parm_name)

    keys = parm.keyframes()
    keyframe_list = [_keyframe_to_dict(k) for k in keys]

    return {
        "node_path": node_path,
        "parm_name": parm_name,
        "keyframe_count": len(keyframe_list),
        "keyframes": keyframe_list,
    }


def _set_frame(frame: float) -> dict:
    """Set the current frame."""
    hou.setFrame(frame)
    return {
        "frame": hou.frame(),
        "status": "frame_set",
    }


def _get_frame() -> dict:
    """Get the current frame."""
    return {
        "frame": hou.frame(),
        "fps": hou.fps(),
    }


def _set_frame_range(start: float, end: float) -> dict:
    """Set the global frame range."""
    if start >= end:
        raise hou.OperationFailed(
            f"start ({start}) must be less than end ({end})."
        )
    hou.playbar.setFrameRange(start, end)

    # Read back actual values
    actual_start, actual_end = hou.playbar.frameRange()
    return {
        "start": actual_start,
        "end": actual_end,
        "status": "frame_range_set",
    }


def _set_playback_range(start: float, end: float) -> dict:
    """Set the playback range (subset of global range)."""
    if start >= end:
        raise hou.OperationFailed(
            f"start ({start}) must be less than end ({end})."
        )
    hou.playbar.setPlaybackRange(start, end)

    actual_start, actual_end = hou.playbar.playbackRange()
    return {
        "start": actual_start,
        "end": actual_end,
        "status": "playback_range_set",
    }


def _playbar_control(
    action: str,
    real_time: bool | None = None,
    fps: float | None = None,
) -> dict:
    """Control playback: play, stop, or reverse."""
    action = action.lower().strip()
    valid_actions = ("play", "stop", "reverse")
    if action not in valid_actions:
        raise hou.OperationFailed(
            f"Invalid action '{action}'. Must be one of: {valid_actions}"
        )

    # Apply optional settings before acting
    if real_time is not None:
        hou.playbar.setRealTime(real_time)

    if fps is not None:
        if fps <= 0:
            raise hou.OperationFailed(f"fps must be positive, got {fps}")
        hou.setFps(fps)

    if action == "play":
        hou.playbar.play()
    elif action == "stop":
        hou.playbar.stop()
    elif action == "reverse":
        hou.playbar.reverse()

    return {
        "action": action,
        "current_frame": hou.frame(),
        "is_playing": hou.playbar.isPlaying(),
        "real_time": hou.playbar.isRealTime(),
        "fps": hou.fps(),
        "status": "playbar_action_executed",
    }


###### Registration

register_handler("animation.set_keyframe", _set_keyframe)
register_handler("animation.set_keyframes", _set_keyframes)
register_handler("animation.delete_keyframe", _delete_keyframe)
register_handler("animation.get_keyframes", _get_keyframes)
register_handler("animation.set_frame", _set_frame)
register_handler("animation.get_frame", _get_frame)
register_handler("animation.set_frame_range", _set_frame_range)
register_handler("animation.set_playback_range", _set_playback_range)
register_handler("animation.playbar_control", _playbar_control)
