"""Copy / Paste-Flipped for wrap-rig CTRL bones.

World-space mirror approach: reads each bone's world matrix, reflects it
across the auto-detected mirror plane, then converts back to the target
bone's local space.  Works regardless of bone rolls or rest orientations.
"""

import bpy
from mathutils import Matrix

from ..core.constants import WRAP_CTRL_PREFIX
from ..core.utils import mirror_name

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_pose_buffer = {}       # {bone_name: 4x4 world Matrix}
_mirror_axis = 0        # auto-detected: 0=X, 1=Y, 2=Z
_source_armature = ""


# ---------------------------------------------------------------------------
# World-space helpers
# ---------------------------------------------------------------------------

def _bone_world_matrix(armature_obj, pbone):
    """Return the bone's world-space matrix (armature object @ pose matrix)."""
    return armature_obj.matrix_world @ pbone.matrix


def _bone_rest_world_matrix(armature_obj, bone_name):
    """Return a bone's rest-pose world-space matrix."""
    bone = armature_obj.data.bones.get(bone_name)
    if not bone:
        return Matrix.Identity(4)
    return armature_obj.matrix_world @ bone.matrix_local


def _mirror_matrix(mat, axis):
    """Mirror a 4x4 matrix across the plane perpendicular to *axis*.

    Negates the axis column and the axis row of the rotation part,
    and negates the axis component of the translation.  This produces
    the reflection of the transform across the YZ/XZ/XY plane.
    """
    m = mat.copy()
    # Negate the axis column of the 3x3 rotation block
    for row in range(3):
        m[row][axis] = -m[row][axis]
    # Negate the axis row of the 3x3 rotation block
    for col in range(3):
        m[axis][col] = -m[axis][col]
    # Negate the axis component of translation
    m[axis][3] = -m[axis][3]
    return m


def _world_to_pose_bone(armature_obj, pbone, world_mat):
    """Convert a world-space matrix to a pose bone's local (basis) matrix.

    Strips out the armature object transform, the bone's rest matrix,
    and the parent's posed transform to yield the bone-local delta
    that Blender stores as matrix_basis.
    """
    # armature-space = inverse(object) @ world
    arm_space = armature_obj.matrix_world.inverted() @ world_mat

    # Rest matrix of this bone in armature space
    rest = pbone.bone.matrix_local

    if pbone.parent:
        # Parent's posed armature-space matrix
        parent_posed = pbone.parent.matrix
        # The bone's local space is relative to parent posed @ rest offset
        parent_rest = pbone.parent.bone.matrix_local
        rest_offset = parent_rest.inverted() @ rest
        local_space = parent_posed @ rest_offset
        basis = local_space.inverted() @ arm_space
    else:
        basis = rest.inverted() @ arm_space

    return basis


def _apply_basis(pbone, basis_mat):
    """Apply a basis (local) matrix to a pose bone, decomposing into
    location + rotation + scale channels."""
    loc, rot, sca = basis_mat.decompose()
    pbone.location = loc
    if pbone.rotation_mode == 'QUATERNION':
        pbone.rotation_quaternion = rot
    elif pbone.rotation_mode == 'AXIS_ANGLE':
        # Convert quaternion to axis-angle
        axis, angle = rot.to_axis_angle()
        pbone.rotation_axis_angle = (angle, *axis)
    else:
        pbone.rotation_euler = rot.to_euler(pbone.rotation_mode)
    pbone.scale = sca


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
    """Copy all CTRL bone world-space matrices for paste-flipped."""
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
                _pose_buffer[pbone.name] = _bone_world_matrix(obj, pbone).copy()

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
        for bone_name, world_mat in _pose_buffer.items():
            pbone = obj.pose.bones.get(bone_name)
            if not pbone:
                continue
            basis = _world_to_pose_bone(obj, pbone, world_mat)
            _apply_basis(pbone, basis)
            applied += 1

        context.view_layer.update()
        self.report({'INFO'}, f"Pasted {applied} bones")
        return {'FINISHED'}


class BT_OT_PasteFlipped(bpy.types.Operator):
    """Paste copied pose with world-space L/R mirror."""
    bl_idname = "bt.paste_pose_flipped"
    bl_label = "Paste Flipped"
    bl_description = "Paste pose with L/R mirrored via world-space reflection"
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

        for bone_name, world_mat in _pose_buffer.items():
            if bone_name in processed:
                continue
            if bone_name in above:
                continue

            mirrored_name = mirror_name(bone_name)
            is_paired = (mirrored_name != bone_name
                         and mirrored_name in _pose_buffer)

            if is_paired:
                partner_mat = _pose_buffer[mirrored_name]

                # Mirror partner's world matrix → apply to this bone
                pbone = obj.pose.bones.get(bone_name)
                if pbone:
                    mirrored_world = _mirror_matrix(partner_mat, _mirror_axis)
                    basis = _world_to_pose_bone(obj, pbone, mirrored_world)
                    _apply_basis(pbone, basis)
                    applied += 1

                # Mirror this bone's world matrix → apply to partner
                partner_pbone = obj.pose.bones.get(mirrored_name)
                if partner_pbone:
                    mirrored_world = _mirror_matrix(world_mat, _mirror_axis)
                    basis = _world_to_pose_bone(obj, partner_pbone, mirrored_world)
                    _apply_basis(partner_pbone, basis)
                    applied += 1

                processed.add(bone_name)
                processed.add(mirrored_name)
            else:
                # Center bone: mirror in-place
                pbone = obj.pose.bones.get(bone_name)
                if pbone:
                    mirrored_world = _mirror_matrix(world_mat, _mirror_axis)
                    basis = _world_to_pose_bone(obj, pbone, mirrored_world)
                    _apply_basis(pbone, basis)
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
