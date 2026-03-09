"""BVH file read/write utilities for ML model I/O.

Handles exporting Blender armature animation to BVH format and
importing BVH motion data back onto an existing rig.
"""

from math import degrees, radians
from pathlib import Path

import bpy

# ── BVH Export ──

def export_armature_bvh(armature_obj, filepath, frame_start=None,
                        frame_end=None, bone_filter=None):
    """Export armature animation to BVH file.

    Args:
        armature_obj: Blender armature object.
        filepath: Output BVH file path.
        frame_start: First frame (default: scene start).
        frame_end: Last frame (default: scene end).
        bone_filter: Optional set of bone names to include.

    Returns:
        Path to the written BVH file.
    """
    scene = bpy.context.scene
    if frame_start is None:
        frame_start = scene.frame_start
    if frame_end is None:
        frame_end = scene.frame_end

    bones = _get_bone_hierarchy(armature_obj, bone_filter)
    if not bones:
        raise ValueError("No bones found for BVH export")

    fps = scene.render.fps
    frame_time = 1.0 / fps
    num_frames = frame_end - frame_start + 1

    lines = []
    lines.append("HIERARCHY")

    # Write skeleton hierarchy
    roots = [b for b in bones if b["parent"] is None]
    for root in roots:
        _write_joint(lines, root, bones, indent=0, is_root=True)

    # Write motion data
    lines.append("MOTION")
    lines.append(f"Frames: {num_frames}")
    lines.append(f"Frame Time: {frame_time:.6f}")

    orig_frame = scene.frame_current
    for frame in range(frame_start, frame_end + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()

        values = []
        for bone_info in bones:
            pbone = armature_obj.pose.bones.get(bone_info["name"])
            if pbone is None:
                # Fill with zeros
                n = 6 if bone_info["parent"] is None else 3
                values.extend([0.0] * n)
                continue

            if bone_info["parent"] is None:
                # Root: position + rotation
                loc = pbone.location
                values.extend([loc.x, loc.y, loc.z])

            rot = pbone.rotation_euler
            values.extend([degrees(rot.z), degrees(rot.x), degrees(rot.y)])

        lines.append(" ".join(f"{v:.6f}" for v in values))

    scene.frame_set(orig_frame)

    filepath = Path(filepath)
    filepath.write_text("\n".join(lines), encoding="utf-8")
    return str(filepath)


def _get_bone_hierarchy(armature_obj, bone_filter=None):
    """Build ordered bone list with parent references."""
    bones = []
    name_to_idx = {}

    for bone in armature_obj.data.bones:
        if bone_filter and bone.name not in bone_filter:
            continue
        idx = len(bones)
        parent_name = bone.parent.name if bone.parent else None
        parent_idx = name_to_idx.get(parent_name)
        name_to_idx[bone.name] = idx

        # Compute offset relative to parent
        if bone.parent:
            offset = bone.head_local - bone.parent.head_local
        else:
            offset = bone.head_local.copy()

        bones.append({
            "name": bone.name,
            "index": idx,
            "parent": parent_idx,
            "offset": offset,
            "children": [],
        })

    # Build children lists
    for b in bones:
        if b["parent"] is not None:
            bones[b["parent"]]["children"].append(b["index"])

    return bones


def _write_joint(lines, bone_info, all_bones, indent, is_root=False):
    """Write a single joint to BVH hierarchy."""
    pad = "  " * indent
    name = bone_info["name"]
    off = bone_info["offset"]

    if is_root:
        lines.append(f"{pad}ROOT {name}")
    else:
        lines.append(f"{pad}JOINT {name}")

    lines.append(f"{pad}{{")
    lines.append(f"{pad}  OFFSET {off.x:.6f} {off.y:.6f} {off.z:.6f}")

    if is_root:
        lines.append(
            f"{pad}  CHANNELS 6 Xposition Yposition Zposition "
            "Zrotation Xrotation Yrotation"
        )
    else:
        lines.append(f"{pad}  CHANNELS 3 Zrotation Xrotation Yrotation")

    children = bone_info["children"]
    if children:
        for ci in children:
            _write_joint(lines, all_bones[ci], all_bones, indent + 1)
    else:
        # End site
        lines.append(f"{pad}  End Site")
        lines.append(f"{pad}  {{")
        lines.append(f"{pad}    OFFSET 0.000000 0.100000 0.000000")
        lines.append(f"{pad}  }}")

    lines.append(f"{pad}}}")


# ── BVH Import ──

def parse_bvh(filepath):
    """Parse a BVH file into structured data.

    Returns:
        dict with keys:
            joints: list of {name, parent, offset, channels, channel_indices}
            frames: list of lists (one float-list per frame)
            frame_time: float
    """
    text = Path(filepath).read_text(encoding="utf-8")
    lines = text.strip().split("\n")

    joints = []
    parent_stack = []
    joint_idx = {}
    frames = []
    frame_time = 0.033333

    i = 0
    in_motion = False

    while i < len(lines):
        line = lines[i].strip()
        i += 1

        if not line or line == "{":
            continue

        if line.startswith("ROOT") or line.startswith("JOINT"):
            name = line.split(None, 1)[1]
            parent = parent_stack[-1] if parent_stack else None
            jinfo = {
                "name": name,
                "parent": parent,
                "offset": (0, 0, 0),
                "channels": [],
                "channel_offset": 0,
            }
            joint_idx[name] = len(joints)
            joints.append(jinfo)
            parent_stack.append(name)

        elif line.startswith("End Site"):
            # Skip end site block
            while i < len(lines) and "}" not in lines[i]:
                i += 1
            i += 1  # skip closing brace

        elif line.startswith("OFFSET"):
            parts = line.split()
            offset = (float(parts[1]), float(parts[2]), float(parts[3]))
            if joints:
                joints[-1]["offset"] = offset

        elif line.startswith("CHANNELS"):
            parts = line.split()
            n_channels = int(parts[1])
            channels = parts[2:2 + n_channels]
            if joints:
                joints[-1]["channels"] = channels

        elif line == "}":
            if parent_stack:
                parent_stack.pop()

        elif line == "MOTION":
            in_motion = True

        elif in_motion and line.startswith("Frames:"):
            pass  # We count frames from data

        elif in_motion and line.startswith("Frame Time:"):
            frame_time = float(line.split(":")[1].strip())

        elif in_motion:
            values = [float(x) for x in line.split()]
            frames.append(values)

    # Compute channel offsets
    offset = 0
    for j in joints:
        j["channel_offset"] = offset
        offset += len(j["channels"])

    return {"joints": joints, "frames": frames, "frame_time": frame_time}


def apply_bvh_to_armature(armature_obj, bvh_data, bone_mapping=None,
                          action_name=None, frame_start=1):
    """Apply parsed BVH motion data to an existing armature.

    Args:
        armature_obj: Target Blender armature object.
        bvh_data: Dict from parse_bvh().
        bone_mapping: Optional dict {bvh_joint_name: blender_bone_name}.
        action_name: Name for the new action.
        frame_start: Frame to start importing from.

    Returns:
        The created Action.
    """
    from bpy_extras.anim_utils import action_ensure_channelbag_for_slot

    from ...core.utils import assign_channel_groups

    joints = bvh_data["joints"]
    frames = bvh_data["frames"]

    if not action_name:
        action_name = f"{armature_obj.name}_BVH"

    # Create action
    action = bpy.data.actions.new(name=action_name)
    if not armature_obj.animation_data:
        armature_obj.animation_data_create()

    armature_obj.animation_data.action = action
    slot = action.slots.new(name=armature_obj.name, id_type='OBJECT')
    armature_obj.animation_data.action_slot = slot
    cb = action_ensure_channelbag_for_slot(action, slot)

    # Create FCurves for each joint
    for joint in joints:
        bvh_name = joint["name"]
        bone_name = (bone_mapping or {}).get(bvh_name, bvh_name)

        pbone = armature_obj.pose.bones.get(bone_name)
        if pbone is None:
            continue

        channels = joint["channels"]
        ch_offset = joint["channel_offset"]

        # Determine which channels are position vs rotation
        for ci, ch_name in enumerate(channels):
            ch_lower = ch_name.lower()
            abs_ci = ch_offset + ci

            if "position" in ch_lower:
                axis = {"x": 0, "y": 1, "z": 2}.get(ch_lower[0], 0)
                dp = f'pose.bones["{bone_name}"].location'
                fc = cb.fcurves.new(dp, index=axis)
                fc.keyframe_points.add(len(frames))
                for fi, frame_vals in enumerate(frames):
                    kf = fc.keyframe_points[fi]
                    kf.co = (frame_start + fi, frame_vals[abs_ci])
                    kf.interpolation = 'BEZIER'
                fc.update()

            elif "rotation" in ch_lower:
                axis = {"x": 0, "y": 1, "z": 2}.get(ch_lower[0], 0)
                dp = f'pose.bones["{bone_name}"].rotation_euler'
                fc = cb.fcurves.new(dp, index=axis)
                fc.keyframe_points.add(len(frames))
                for fi, frame_vals in enumerate(frames):
                    kf = fc.keyframe_points[fi]
                    kf.co = (
                        frame_start + fi,
                        radians(frame_vals[abs_ci]),
                    )
                    kf.interpolation = 'BEZIER'
                fc.update()

    assign_channel_groups(armature_obj)
    return action
