"""Walk/run/idle procedural animation generators."""

import math


def generate_walk_cycle(params=None):
    """Generate walk cycle keyframe data.

    Args:
        params: Dict with keys: speed, stride, sway, arm_swing, frame_count, fps.

    Returns:
        Dict mapping bone_data_path -> [(frame, value), ...]
    """
    p = params or {}
    fps = p.get("fps", 24)
    frame_count = p.get("frame_count", fps)  # One cycle
    speed = p.get("speed", 1.0)
    stride = p.get("stride", 0.4)
    sway = p.get("sway", 0.02)
    arm_swing = p.get("arm_swing", 0.3)
    hip_bounce = p.get("hip_bounce", 0.02)

    keyframes = {}
    freq = speed * 2 * math.pi / frame_count

    # Hip vertical bounce (double frequency)
    hip_z = []
    hip_x = []
    for f in range(frame_count + 1):
        t = f * freq
        hip_z.append((f, hip_bounce * abs(math.sin(t))))
        hip_x.append((f, sway * math.sin(t / 2)))

    keyframes["hip_location_z"] = hip_z
    keyframes["hip_location_x"] = hip_x

    # Leg IK targets (opposite phase)
    for side, phase in [("L", 0), ("R", math.pi)]:
        foot_y = []
        foot_z = []
        for f in range(frame_count + 1):
            t = f * freq + phase
            foot_y.append((f, stride * math.sin(t)))
            foot_z.append((f, max(0, stride * 0.3 * math.sin(t))))
        keyframes[f"foot_{side}_location_y"] = foot_y
        keyframes[f"foot_{side}_location_z"] = foot_z

    # Arm swing (opposite to legs)
    for side, phase in [("L", math.pi), ("R", 0)]:
        arm_rot = []
        for f in range(frame_count + 1):
            t = f * freq + phase
            arm_rot.append((f, arm_swing * math.sin(t)))
        keyframes[f"arm_{side}_rotation_x"] = arm_rot

    return keyframes


def generate_run_cycle(params=None):
    """Generate run cycle — faster with aerial phase."""
    p = params or {}
    fps = p.get("fps", 24)
    frame_count = p.get("frame_count", int(fps * 0.75))
    speed = p.get("speed", 2.0)
    stride = p.get("stride", 0.6)

    p2 = dict(p)
    p2.update({
        "frame_count": frame_count,
        "speed": speed,
        "stride": stride,
        "hip_bounce": 0.04,
        "arm_swing": 0.5,
        "sway": 0.01,
    })
    return generate_walk_cycle(p2)


def generate_idle(params=None):
    """Generate idle breathing/sway animation."""
    p = params or {}
    fps = p.get("fps", 24)
    frame_count = p.get("frame_count", fps * 3)  # 3 second cycle
    sway = p.get("sway", 0.005)

    keyframes = {}
    freq = 2 * math.pi / frame_count

    # Subtle body sway
    body_x = []
    body_z = []
    for f in range(frame_count + 1):
        t = f * freq
        body_x.append((f, sway * math.sin(t * 0.7)))
        body_z.append((f, sway * 0.5 * math.sin(t)))
    keyframes["hip_location_x"] = body_x
    keyframes["hip_location_z"] = body_z

    return keyframes
