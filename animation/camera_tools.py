"""Camera animation tools — orbit, dolly, shake, focus pull."""

import math
import random

import bpy

from ..core.utils import create_fcurve


def create_orbit_camera(center=(0, 0, 0), radius=5.0, height=2.0,
                        frame_start=1, frame_count=120, name="OrbitCam"):
    """Create a camera that orbits around a point.

    Args:
        center: World-space orbit center.
        radius: Orbit radius.
        height: Camera height above center.
        frame_start: Start frame.
        frame_count: Duration in frames.
        name: Camera name.

    Returns:
        The camera object.
    """
    cam_data = bpy.data.cameras.new(name)
    cam_obj = bpy.data.objects.new(name, cam_data)
    bpy.context.collection.objects.link(cam_obj)

    # Create empty at center for tracking
    empty = bpy.data.objects.new(f"{name}_Target", None)
    empty.location = center
    bpy.context.collection.objects.link(empty)

    # Add track-to constraint
    track = cam_obj.constraints.new('TRACK_TO')
    track.target = empty
    track.track_axis = 'TRACK_NEGATIVE_Z'
    track.up_axis = 'UP_Y'

    # Keyframe orbit path
    action_name = f"{name}_Orbit"
    for axis, idx in [("x", 0), ("y", 1), ("z", 2)]:
        keyframes = []
        for f in range(frame_count + 1):
            angle = 2 * math.pi * f / frame_count
            if idx == 0:
                val = center[0] + radius * math.cos(angle)
            elif idx == 1:
                val = center[1] + radius * math.sin(angle)
            else:
                val = center[2] + height
            keyframes.append((frame_start + f, val))
        create_fcurve(cam_obj, action_name, "location", idx, keyframes)

    return cam_obj


def create_dolly_move(camera_obj, start_pos, end_pos,
                      frame_start=1, frame_count=60):
    """Animate a camera dolly move between two positions.

    Args:
        camera_obj: Existing camera object.
        start_pos: Start position (x,y,z).
        end_pos: End position (x,y,z).
        frame_start: Start frame.
        frame_count: Duration.
    """
    action_name = f"{camera_obj.name}_Dolly"
    for idx in range(3):
        keyframes = [
            (frame_start, start_pos[idx]),
            (frame_start + frame_count, end_pos[idx]),
        ]
        create_fcurve(camera_obj, action_name, "location", idx, keyframes)


def add_camera_shake(camera_obj, intensity=0.02, frequency=3.0,
                     frame_start=1, frame_count=60, seed=42):
    """Add procedural camera shake via noise keyframes.

    Args:
        camera_obj: Camera object.
        intensity: Shake magnitude.
        frequency: Shake frequency multiplier.
        frame_start: Start frame.
        frame_count: Duration.
        seed: Random seed.
    """
    rng = random.Random(seed)
    action_name = f"{camera_obj.name}_Shake"

    for idx in range(3):
        keyframes = []
        for f in range(frame_count + 1):
            noise = intensity * (rng.random() * 2 - 1)
            # Higher frequency = more keyframes
            if f % max(1, int(24 / frequency)) == 0 or f == 0 or f == frame_count:
                keyframes.append((frame_start + f, noise))
        if keyframes:
            create_fcurve(camera_obj, action_name, "delta_location", idx, keyframes)


def create_focus_pull(camera_obj, distances, frames):
    """Animate depth of field focus distance.

    Args:
        camera_obj: Camera object with DOF enabled.
        distances: List of focus distances.
        frames: List of frame numbers (same length as distances).
    """
    camera_obj.data.dof.use_dof = True
    action_name = f"{camera_obj.name}_FocusPull"
    keyframes = list(zip(frames, distances))
    create_fcurve(camera_obj, action_name, "data.dof.focus_distance", 0, keyframes)
