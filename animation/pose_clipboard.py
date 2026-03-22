"""Copy / Paste-Flipped for wrap-rig CTRL bones.

Stores all CTRL bone transforms on copy, auto-detects the mirror axis
from rest-pose L/R bone positions, and pastes with L/R swap + lateral
negate relative to a user-chosen center bone.
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


def _apply_transform(armature_obj, bone_name, transform):
    """Apply a transform dict to a pose bone."""
    pbone = armature_obj.pose.bones.get(bone_name)
    if not pbone:
        return
    pbone.location = transform['location']
    pbone.rotation_mode = transform['rotation_mode']
    if transform['rotation_mode'] == 'QUATERNION':
        pbone.rotation_quaternion = transform['rotation_quaternion']
    elif transform['rotation_mode'] == 'AXIS_ANGLE':
        pbone.rotation_quaternion = transform['rotation_quaternion']
    else:
        pbone.rotation_euler = transform['rotation_euler']
    pbone.scale = transform['scale']


def _mirror_transform(transform, axis):
    """Mirror a transform across the given axis (0=X, 1=Y, 2=Z).

    Location: negate the component on the mirror axis.
    Quaternion: negate the two components perpendicular to the mirror axis.
    Euler: negate the two components perpendicular to the mirror axis.
    Scale: unchanged.
    """
    # Mirror location
    loc = list(transform['location'])
    loc[axis] = -loc[axis]

    # The two axes perpendicular to the mirror axis
    perp = [i for i in range(3) if i != axis]

    # Mirror quaternion (w, x, y, z) — negate perpendicular components
    quat = list(transform['rotation_quaternion'])
    # Quaternion indices: 0=w, 1=x, 2=y, 3=z
    # For axis=0 (X mirror): negate y(2) and z(3)
    # For axis=1 (Y mirror): negate x(1) and z(3)
    # For axis=2 (Z mirror): negate x(1) and y(2)
    for p in perp:
        quat[p + 1] = -quat[p + 1]

    # Mirror euler — negate perpendicular components
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
        # Both bones must exist in the armature
        bone_a = armature_obj.data.bones.get(name)
        bone_b = armature_obj.data.bones.get(partner)
        if not bone_a or not bone_b:
            continue
        seen.add(name)
        seen.add(partner)
        for i in range(3):
            axis_diffs[i] += abs(bone_a.head_local[i] - bone_b.head_local[i])

    if max(axis_diffs) < 1e-6:
        return 0  # default to X

    return axis_diffs.index(max(axis_diffs))


# ---------------------------------------------------------------------------
# Subtree detection
# ---------------------------------------------------------------------------

def _get_ctrl_subtree(armature_obj, center_bone_name):
    """Return set of CTRL bone names at or below center bone in hierarchy."""
    bone = armature_obj.data.bones.get(center_bone_name)
    if not bone:
        # Fallback: include all CTRL bones
        return {pb.name for pb in armature_obj.pose.bones
                if pb.name.startswith(WRAP_CTRL_PREFIX)}

    # Collect all descendant bone names (any type)
    subtree_names = {bone.name}
    for child in bone.children_recursive:
        subtree_names.add(child.name)

    # Filter to CTRL bones
    return {name for name in subtree_names
            if name.startswith(WRAP_CTRL_PREFIX)}


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class BT_OT_CopyPose(bpy.types.Operator):
    """Copy all CTRL bone transforms for paste-flipped."""
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
                _apply_transform(obj, bone_name, transform)
                applied += 1

        context.view_layer.update()
        self.report({'INFO'}, f"Pasted {applied} bones")
        return {'FINISHED'}


class BT_OT_PasteFlipped(bpy.types.Operator):
    """Paste copied pose with L/R flip relative to a center bone."""
    bl_idname = "bt.paste_pose_flipped"
    bl_label = "Paste Flipped"
    bl_description = "Paste pose with L/R mirrored, using center bone as pivot"
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

        # Determine which CTRL bones are in the flip subtree
        if center_bone:
            subtree = _get_ctrl_subtree(obj, center_bone)
        else:
            subtree = {pb.name for pb in obj.pose.bones
                       if pb.name.startswith(WRAP_CTRL_PREFIX)}

        # Track processed bones to avoid double-applying L/R pairs
        processed = set()
        applied = 0

        for bone_name, transform in _pose_buffer.items():
            if bone_name in processed:
                continue
            if bone_name not in subtree:
                continue

            mirrored_name = mirror_name(bone_name)
            is_paired = (mirrored_name != bone_name
                         and mirrored_name in _pose_buffer)

            if is_paired:
                # L/R pair: swap + mirror
                partner_transform = _pose_buffer[mirrored_name]

                # Apply mirrored partner transform to this bone
                _apply_transform(obj, bone_name,
                                 _mirror_transform(partner_transform, _mirror_axis))
                # Apply mirrored this transform to partner bone
                _apply_transform(obj, mirrored_name,
                                 _mirror_transform(transform, _mirror_axis))

                processed.add(bone_name)
                processed.add(mirrored_name)
                applied += 2
            else:
                # Center bone: mirror in-place
                _apply_transform(obj, bone_name,
                                 _mirror_transform(transform, _mirror_axis))
                processed.add(bone_name)
                applied += 1

        context.view_layer.update()
        self.report({'INFO'}, f"Pasted flipped {applied} bones")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Keymap
# ---------------------------------------------------------------------------

_addon_keymaps = []


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

    # Keymap: Ctrl+Shift+V for paste flipped in pose mode
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name='Pose', space_type='EMPTY')
        kmi = km.keymap_items.new('bt.paste_pose_flipped', 'V', 'PRESS',
                                   ctrl=True, shift=True)
        _addon_keymaps.append((km, kmi))


def unregister():
    for km, kmi in _addon_keymaps:
        km.keymap_items.remove(kmi)
    _addon_keymaps.clear()

    if hasattr(bpy.types.Scene, 'bt_flip_center_bone'):
        delattr(bpy.types.Scene, 'bt_flip_center_bone')

    for cls in reversed(classes):
        if hasattr(cls, 'bl_rna'):
            bpy.utils.unregister_class(cls)
