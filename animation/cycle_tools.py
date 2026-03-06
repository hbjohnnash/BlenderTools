"""Animation cycle tools — loop cleanup, NLA management."""

import bpy


def match_first_last_keyframe(action):
    """Ensure the last keyframe matches the first for seamless looping.

    Args:
        action: bpy.types.Action.
    """
    for slot in action.slots:
        for channelbag in slot.channelbags:
            for fcurve in channelbag.fcurves:
                points = fcurve.keyframe_points
                if len(points) >= 2:
                    # Set last keyframe value = first keyframe value
                    points[-1].co.y = points[0].co.y
                    points[-1].handle_left_type = points[0].handle_left_type
                    points[-1].handle_right_type = points[0].handle_right_type
                fcurve.update()


def push_to_nla(armature_obj, action_name=None, strip_name=None, repeat=1):
    """Push the current action to an NLA strip.

    Args:
        armature_obj: The armature object.
        action_name: Action name to push (None = current).
        strip_name: Name for the NLA strip.
        repeat: Number of repeats.

    Returns:
        The NLA strip, or None.
    """
    if not armature_obj.animation_data:
        return None

    action = None
    if action_name:
        action = bpy.data.actions.get(action_name)
    else:
        action = armature_obj.animation_data.action

    if not action:
        return None

    # Create NLA track
    track = armature_obj.animation_data.nla_tracks.new()
    track.name = strip_name or action.name

    # Get action frame range
    frame_start = action.frame_range[0]
    frame_end = action.frame_range[1]

    # Create strip
    strip = track.strips.new(strip_name or action.name, int(frame_start), action)
    strip.action_frame_start = frame_start
    strip.action_frame_end = frame_end
    strip.repeat = repeat
    strip.use_animated_influence = False

    # Clear the action from the object (it's now in NLA)
    armature_obj.animation_data.action = None

    return strip


def blend_nla_strips(armature_obj, strip_a_name, strip_b_name, blend_frames=10):
    """Set up blending between two NLA strips.

    Args:
        armature_obj: The armature object.
        strip_a_name: First strip name.
        strip_b_name: Second strip name.
        blend_frames: Number of frames for the blend transition.
    """
    if not armature_obj.animation_data:
        return

    strip_a = None
    strip_b = None

    for track in armature_obj.animation_data.nla_tracks:
        for strip in track.strips:
            if strip.name == strip_a_name:
                strip_a = strip
            elif strip.name == strip_b_name:
                strip_b = strip

    if strip_a and strip_b:
        # Set blend in/out
        strip_b.blend_in = blend_frames
        strip_a.blend_out = blend_frames
