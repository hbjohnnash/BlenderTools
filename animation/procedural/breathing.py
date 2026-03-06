"""Breathing animation generator."""

import math


def generate_breathing(params=None):
    """Generate breathing keyframe data.

    Args:
        params: Dict with keys: rate (breaths per minute), depth, frame_count, fps.

    Returns:
        Dict mapping data descriptions -> [(frame, value), ...]
    """
    p = params or {}
    fps = p.get("fps", 24)
    rate = p.get("rate", 15)  # breaths per minute
    depth = p.get("depth", 0.03)
    frame_count = p.get("frame_count", int(fps * 60 / rate))  # one breath cycle

    keyframes = {}
    freq = 2 * math.pi / frame_count

    # Chest scale (Y axis — depth)
    chest_scale = []
    for f in range(frame_count + 1):
        t = f * freq
        # Inhale is faster than exhale (asymmetric sine)
        val = 1.0 + depth * (0.5 * (1 - math.cos(t)))
        chest_scale.append((f, val))
    keyframes["chest_scale_y"] = chest_scale

    # Chest scale (X axis — expansion)
    chest_scale_x = []
    for f in range(frame_count + 1):
        t = f * freq
        val = 1.0 + depth * 0.5 * (0.5 * (1 - math.cos(t)))
        chest_scale_x.append((f, val))
    keyframes["chest_scale_x"] = chest_scale_x

    # Shoulder rise
    shoulder_rise = []
    for f in range(frame_count + 1):
        t = f * freq
        val = depth * 0.3 * (0.5 * (1 - math.cos(t)))
        shoulder_rise.append((f, val))
    keyframes["shoulder_location_z"] = shoulder_rise

    return keyframes
