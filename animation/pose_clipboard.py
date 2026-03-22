"""Copy / Paste-Flipped for wrap-rig CTRL bones.

Local-space approach with character-space mirror for center bones.
Paired L/R bones are swapped as-is (mirrored rest poses handle the
visual mirror).  Center bones are converted to world/character space,
mirrored across the sagittal plane, then converted back to bone-local
space — correctly handling any bone roll or orientation.
"""

import bpy
from mathutils import Quaternion

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
        q = Quaternion(transform['rotation_quaternion'])
        axis, angle = q.to_axis_angle()
        pbone.rotation_axis_angle = (angle, *axis)
    else:
        pbone.rotation_euler = transform['rotation_euler']
    pbone.scale = transform['scale']


# ---------------------------------------------------------------------------
# Character-space mirror for center bones
# ---------------------------------------------------------------------------

def _find_bone_local_lateral(armature_obj, bone_name, world_lateral_axis):
    """Find which bone-local axis (0=X,1=Y,2=Z) maps to the world lateral axis.

    Returns (local_axis_index, sign) where sign is +1 or -1 indicating
    whether the bone-local axis points in the same or opposite direction
    as the world lateral axis.
    """
    bone = armature_obj.data.bones.get(bone_name)
    if not bone:
        return world_lateral_axis, 1

    # bone.matrix_local columns give where each bone-local axis ends up
    # in armature space.  Find which column best aligns with world lateral.
    best_axis = 0
    best_dot = 0.0
    for i in range(3):
        # Column i of the 3x3 rotation = image of bone-local axis i
        col = [bone.matrix_local[r][i] for r in range(3)]
        dot = col[world_lateral_axis]  # project onto world lateral
        if abs(dot) > abs(best_dot):
            best_dot = dot
            best_axis = i

    sign = 1 if best_dot > 0 else -1
    return best_axis, sign


def _mirror_center_transform(armature_obj, bone_name, transform, axis):
    """Mirror a center bone by finding its bone-local lateral axis.

    Location: negate the bone-local lateral component.
    Rotation: negate quaternion components perpendicular to bone-local lateral
    (flips yaw/roll, preserves pitch/forward-bend).
    Scale: unchanged.
    """
    local_lat, sign = _find_bone_local_lateral(armature_obj, bone_name, axis)
    perp = [i for i in range(3) if i != local_lat]

    loc = list(transform['location'])
    loc[local_lat] = -loc[local_lat]

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


def _mirror_paired_transform(armature_obj, target_bone_name, partner_transform, axis):
    """Mirror a paired bone's transform for L/R swap.

    Since L and R bones in this rig have the SAME rest-pose axes
    (not mirrored), the same quaternion produces the same world rotation.
    To get the mirror: negate the bone-local LATERAL quaternion component
    (reverses the swing direction) and location component.

    This is opposite from center bones which negate the perpendicular
    components.
    """
    local_lat, sign = _find_bone_local_lateral(
        armature_obj, target_bone_name, axis)

    loc = list(partner_transform['location'])
    loc[local_lat] = -loc[local_lat]

    # Negate only the lateral quaternion component (reverses swing)
    quat = list(partner_transform['rotation_quaternion'])
    quat[local_lat + 1] = -quat[local_lat + 1]

    euler = list(partner_transform['rotation_euler'])
    euler[local_lat] = -euler[local_lat]

    return {
        'location': tuple(loc),
        'rotation_mode': partner_transform['rotation_mode'],
        'rotation_quaternion': tuple(quat),
        'rotation_euler': tuple(euler),
        'scale': partner_transform['scale'],
    }


# ---------------------------------------------------------------------------
# Mirror axis detection
# ---------------------------------------------------------------------------

def _detect_mirror_axis(armature_obj, ctrl_bone_names):
    """Detect the lateral (mirror) axis from rest-pose L/R bone positions."""
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
    """Return set of CTRL bone names ABOVE the center bone in hierarchy."""
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
    """Copy all CTRL bone local transforms."""
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

        if context.area:
            context.area.tag_redraw()
        self.report({'INFO'}, f"Pasted {applied} bones")
        return {'FINISHED'}


class BT_OT_PasteFlipped(bpy.types.Operator):
    """Paste copied pose with L/R flip.

    Paired bones: swapped as-is (mirrored rest poses handle the mirror).
    Center bones: rotation and location mirrored in character/world space
    via rest-pose conversion (handles any bone roll correctly).
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

                # Swap + mirror: each bone gets partner's transform
                # with lateral component negated
                pbone = obj.pose.bones.get(bone_name)
                if pbone:
                    mirrored = _mirror_paired_transform(
                        obj, bone_name, partner_transform, _mirror_axis)
                    _apply_transform(pbone, mirrored)
                    applied += 1

                partner_pbone = obj.pose.bones.get(mirrored_name)
                if partner_pbone:
                    mirrored = _mirror_paired_transform(
                        obj, mirrored_name, transform, _mirror_axis)
                    _apply_transform(partner_pbone, mirrored)
                    applied += 1

                processed.add(bone_name)
                processed.add(mirrored_name)
            else:
                # Center bone: mirror via character-space conversion
                pbone = obj.pose.bones.get(bone_name)
                if pbone:
                    mirrored = _mirror_center_transform(
                        obj, bone_name, transform, _mirror_axis)
                    _apply_transform(pbone, mirrored)
                    applied += 1
                processed.add(bone_name)

        if context.area:
            context.area.tag_redraw()
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
