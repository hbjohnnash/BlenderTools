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

def _get_bone_rest_quat(armature_obj, bone_name):
    """Get the rest-pose rotation quaternion of a bone in armature space."""
    bone = armature_obj.data.bones.get(bone_name)
    if not bone:
        return Quaternion()
    return bone.matrix_local.to_quaternion()


def _mirror_center_transform(armature_obj, bone_name, transform, axis):
    """Mirror a center bone's transform in character/world space.

    Converts the bone's local rotation and location to world space
    (via rest-pose rotation), mirrors across the sagittal plane
    (perpendicular to the lateral axis), then converts back to
    bone-local space.  This correctly handles any bone roll.

    Location: only the lateral component (in world space) is negated.
    Rotation: yaw and roll are negated, pitch is preserved.
    Scale: unchanged.
    """
    rest_q = _get_bone_rest_quat(armature_obj, bone_name)
    rest_q_inv = rest_q.inverted()

    # The two world axes perpendicular to the lateral axis
    perp = [i for i in range(3) if i != axis]

    # --- Mirror rotation ---
    local_q = Quaternion(transform['rotation_quaternion'])
    # Convert to world space
    world_q = rest_q @ local_q
    # Mirror in world space: negate the perpendicular quaternion components
    wq = [world_q.w, world_q.x, world_q.y, world_q.z]
    for p in perp:
        wq[p + 1] = -wq[p + 1]
    mirrored_world_q = Quaternion(wq)
    # Convert back to bone-local
    mirrored_local_q = rest_q_inv @ mirrored_world_q

    # --- Mirror location ---
    local_loc = list(transform['location'])
    # Convert to world space via rest-pose rotation matrix
    rest_mat = rest_q.to_matrix()
    rest_mat_inv = rest_mat.inverted()
    from mathutils import Vector
    world_loc = rest_mat @ Vector(local_loc)
    # Negate only the lateral component
    world_loc[axis] = -world_loc[axis]
    # Convert back to bone-local
    mirrored_loc = rest_mat_inv @ world_loc

    # --- Mirror euler (convert via quaternion for correctness) ---
    if transform['rotation_mode'] not in ('QUATERNION', 'AXIS_ANGLE'):
        mirrored_euler = mirrored_local_q.to_euler(transform['rotation_mode'])
    else:
        mirrored_euler = transform['rotation_euler']

    return {
        'location': tuple(mirrored_loc),
        'rotation_mode': transform['rotation_mode'],
        'rotation_quaternion': tuple(mirrored_local_q),
        'rotation_euler': tuple(mirrored_euler),
        'scale': transform['scale'],
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

        context.view_layer.update()
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
                # Center bone: mirror via character-space conversion
                pbone = obj.pose.bones.get(bone_name)
                if pbone:
                    mirrored = _mirror_center_transform(
                        obj, bone_name, transform, _mirror_axis)
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
