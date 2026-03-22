"""Copy / Paste-Flipped for wrap-rig CTRL bones.

Local-space approach: stores each bone's local transform (location,
rotation, scale).  For paired L/R bones, transforms are swapped as-is
(mirrored rest poses produce the mirror automatically).  For center
bones, the lateral location component and rotation are mirrored.
"""

import bpy

from ..core.constants import WRAP_CTRL_PREFIX
from ..core.utils import mirror_name

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_pose_buffer = {}       # {bone_name: transform_dict}
_mirror_axis = 0        # auto-detected: 0=X, 1=Y, 2=Z
_source_armature = ""


# ---------------------------------------------------------------------------
# Transform helpers
# ---------------------------------------------------------------------------

def _read_bone_transform(pbone):
    """Read all transform channels from a pose bone into a dict."""
    return {
        'location': tuple(pbone.location),
        'rotation_mode': pbone.rotation_mode,
        'rotation_quaternion': tuple(pbone.rotation_quaternion),
        'rotation_euler': tuple(pbone.rotation_euler),
        'scale': tuple(pbone.scale),
    }


def _apply_transform(pbone, transform):
    """Apply a transform dict to a pose bone."""
    pbone.location = transform['location']
    if pbone.rotation_mode == 'QUATERNION':
        pbone.rotation_quaternion = transform['rotation_quaternion']
    elif pbone.rotation_mode == 'AXIS_ANGLE':
        # Stored as euler fallback — convert quat to axis-angle
        from mathutils import Quaternion
        q = Quaternion(transform['rotation_quaternion'])
        axis, angle = q.to_axis_angle()
        pbone.rotation_axis_angle = (angle, *axis)
    else:
        pbone.rotation_euler = transform['rotation_euler']
    pbone.scale = transform['scale']


def _mirror_center_transform(transform, axis):
    """Mirror a center bone's transform across the given axis.

    Location: negate the lateral component.
    Rotation: negate the two quaternion/euler components perpendicular
    to the mirror axis (flips yaw/roll, keeps pitch).
    Scale: unchanged.
    """
    loc = list(transform['location'])
    loc[axis] = -loc[axis]

    perp = [i for i in range(3) if i != axis]

    quat = list(transform['rotation_quaternion'])
    for p in perp:
        quat[p + 1] = -quat[p + 1]

    euler = list(transform['rotation_euler'])
    for p in perp:
        euler[p] = -euler[p]

    return {
        'location': tuple(loc),
        'rotation_mode': transform['rotation_mode'],
        'rotation_quaternion': tuple(quat),
        'rotation_euler': tuple(euler),
        'scale': transform['scale'],
    }


# ---------------------------------------------------------------------------
# Mirror axis detection
# ---------------------------------------------------------------------------

def _detect_mirror_axis(armature_obj, ctrl_bone_names):
    """Detect the lateral (mirror) axis from rest-pose L/R bone positions.

    Compares rest-pose head positions of paired L/R CTRL bones.
    The axis with the greatest total absolute difference is the mirror axis.
    Returns 0 (X), 1 (Y), or 2 (Z). Defaults to 0 if no pairs found.
    """
    axis_diffs = [0.0, 0.0, 0.0]
    seen = set()

    for name in ctrl_bone_names:
        if name in seen:
            continue
        partner = mirror_name(name)
        if partner == name or partner in seen:
            continue
        bone_a = armature_obj.data.bones.get(name)
        bone_b = armature_obj.data.bones.get(partner)
        if not bone_a or not bone_b:
            continue
        seen.add(name)
        seen.add(partner)
        for i in range(3):
            axis_diffs[i] += abs(bone_a.head_local[i] - bone_b.head_local[i])

    if max(axis_diffs) < 1e-6:
        return 0

    return axis_diffs.index(max(axis_diffs))


# ---------------------------------------------------------------------------
# Center bone filtering
# ---------------------------------------------------------------------------

def _get_bones_above_center(armature_obj, center_bone_name):
    """Return set of CTRL bone names ABOVE the center bone in hierarchy.

    These bones are excluded from flipping.  Returns empty set if center
    bone is the root or not found (meaning: flip everything).
    """
    bone = armature_obj.data.bones.get(center_bone_name)
    if not bone:
        return set()

    ancestors = set()
    parent = bone.parent
    while parent:
        ancestors.add(parent.name)
        parent = parent.parent

    above = set()
    for pb in armature_obj.pose.bones:
        if not pb.name.startswith(WRAP_CTRL_PREFIX):
            continue
        data_bone = armature_obj.data.bones.get(pb.name)
        if data_bone:
            check = data_bone.parent
            while check:
                if check.name in ancestors and check.name != center_bone_name:
                    above.add(pb.name)
                    break
                if check.name == center_bone_name:
                    break
                check = check.parent

    return above


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class BT_OT_CopyPose(bpy.types.Operator):
    """Copy all CTRL bone local transforms for paste-flipped."""
    bl_idname = "bt.copy_pose"
    bl_label = "Copy Pose"
    bl_description = "Copy all CTRL bone transforms for paste or paste-flipped"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj and obj.type == 'ARMATURE'
                and context.mode == 'POSE')

    def execute(self, context):
        global _pose_buffer, _mirror_axis, _source_armature
        obj = context.active_object

        _pose_buffer = {}
        for pbone in obj.pose.bones:
            if pbone.name.startswith(WRAP_CTRL_PREFIX):
                _pose_buffer[pbone.name] = _read_bone_transform(pbone)

        if not _pose_buffer:
            self.report({'WARNING'}, "No CTRL bones found")
            return {'CANCELLED'}

        _mirror_axis = _detect_mirror_axis(obj, list(_pose_buffer.keys()))
        _source_armature = obj.name

        self.report({'INFO'},
                    f"Copied {len(_pose_buffer)} bones (mirror={'XYZ'[_mirror_axis]})")
        return {'FINISHED'}


class BT_OT_PastePose(bpy.types.Operator):
    """Paste copied pose without flipping."""
    bl_idname = "bt.paste_pose"
    bl_label = "Paste Pose"
    bl_description = "Paste previously copied CTRL bone transforms"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj and obj.type == 'ARMATURE'
                and context.mode == 'POSE'
                and bool(_pose_buffer))

    def execute(self, context):
        obj = context.active_object
        applied = 0
        for bone_name, transform in _pose_buffer.items():
            pbone = obj.pose.bones.get(bone_name)
            if pbone:
                _apply_transform(pbone, transform)
                applied += 1

        context.view_layer.update()
        self.report({'INFO'}, f"Pasted {applied} bones")
        return {'FINISHED'}


class BT_OT_PasteFlipped(bpy.types.Operator):
    """Paste copied pose with L/R flip.

    Paired bones (L/R): transforms are swapped as-is.  Since L and R
    bones have mirrored rest poses, the same local rotation on the
    opposite bone produces the mirrored world-space result naturally.

    Center bones: lateral location negated, rotation Y/Z negated
    (flips yaw and roll, keeps pitch/forward bend).
    """
    bl_idname = "bt.paste_pose_flipped"
    bl_label = "Paste Flipped"
    bl_description = "Paste pose with L/R mirrored"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj and obj.type == 'ARMATURE'
                and context.mode == 'POSE'
                and bool(_pose_buffer))

    def execute(self, context):
        obj = context.active_object
        center_bone = getattr(context.scene, 'bt_flip_center_bone', '')

        above = (_get_bones_above_center(obj, center_bone)
                 if center_bone else set())

        processed = set()
        applied = 0

        for bone_name, transform in _pose_buffer.items():
            if bone_name in processed:
                continue
            if bone_name in above:
                continue

            mirrored_name = mirror_name(bone_name)
            is_paired = (mirrored_name != bone_name
                         and mirrored_name in _pose_buffer)

            if is_paired:
                partner_transform = _pose_buffer[mirrored_name]

                # Swap as-is: L gets R's exact local transform, and vice versa
                pbone = obj.pose.bones.get(bone_name)
                if pbone:
                    _apply_transform(pbone, partner_transform)
                    applied += 1

                partner_pbone = obj.pose.bones.get(mirrored_name)
                if partner_pbone:
                    _apply_transform(partner_pbone, transform)
                    applied += 1

                processed.add(bone_name)
                processed.add(mirrored_name)
            else:
                # Center bone: mirror location + rotation
                pbone = obj.pose.bones.get(bone_name)
                if pbone:
                    mirrored = _mirror_center_transform(transform, _mirror_axis)
                    _apply_transform(pbone, mirrored)
                    applied += 1
                processed.add(bone_name)

        context.view_layer.update()
        self.report({'INFO'}, f"Pasted flipped {applied} bones")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (
    BT_OT_CopyPose,
    BT_OT_PastePose,
    BT_OT_PasteFlipped,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.bt_flip_center_bone = bpy.props.StringProperty(
        name="Center Bone",
        description="Pivot bone for paste-flipped (e.g. root or hips). "
                    "Everything below this bone is flipped",
        default="",
    )


def unregister():
    if hasattr(bpy.types.Scene, 'bt_flip_center_bone'):
        delattr(bpy.types.Scene, 'bt_flip_center_bone')

    for cls in reversed(classes):
        if hasattr(cls, 'bl_rna'):
            bpy.utils.unregister_class(cls)
