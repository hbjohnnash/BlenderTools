"""Mechanical animation generators — piston, gear, conveyor."""

import math


def generate_piston_cycle(params=None):
    """Generate piston stroke animation.

    Args:
        params: Dict with keys: stroke, speed, frame_count, fps.

    Returns:
        Dict mapping data descriptions -> [(frame, value), ...]
    """
    p = params or {}
    fps = p.get("fps", 24)
    frame_count = p.get("frame_count", fps)
    stroke = p.get("stroke", 0.3)
    speed = p.get("speed", 1.0)

    keyframes = {}
    freq = speed * 2 * math.pi / frame_count

    piston_z = []
    for f in range(frame_count + 1):
        t = f * freq
        piston_z.append((f, stroke * 0.5 * (1 - math.cos(t))))
    keyframes["piston_location_z"] = piston_z

    return keyframes


def generate_gear_rotation(params=None):
    """Generate gear rotation animation.

    Args:
        params: Dict with keys: ratio, speed, frame_count, fps, axis.

    Returns:
        Dict mapping data descriptions -> [(frame, value), ...]
    """
    p = params or {}
    fps = p.get("fps", 24)
    frame_count = p.get("frame_count", fps * 2)
    ratio = p.get("ratio", 1.0)
    speed = p.get("speed", 1.0)
    axis = p.get("axis", "z")

    keyframes = {}
    axis_map = {"x": 0, "y": 1, "z": 2}
    idx = axis_map.get(axis, 2)

    rotation = []
    for f in range(frame_count + 1):
        angle = speed * ratio * 2 * math.pi * f / frame_count
        rotation.append((f, angle))
    keyframes[f"rotation_euler_{idx}"] = rotation

    return keyframes


def generate_conveyor(params=None):
    """Generate conveyor belt / repeating offset animation.

    Args:
        params: Dict with keys: distance, speed, frame_count, fps, axis.

    Returns:
        Dict mapping data descriptions -> [(frame, value), ...]
    """
    p = params or {}
    fps = p.get("fps", 24)
    frame_count = p.get("frame_count", fps * 2)
    distance = p.get("distance", 1.0)
    speed = p.get("speed", 1.0)
    axis = p.get("axis", "y")

    keyframes = {}
    axis_map = {"x": 0, "y": 1, "z": 2}
    idx = axis_map.get(axis, 1)

    offset = []
    for f in range(frame_count + 1):
        val = (speed * distance * f / frame_count) % distance
        offset.append((f, val))
    keyframes[f"location_{idx}"] = offset

    return keyframes
