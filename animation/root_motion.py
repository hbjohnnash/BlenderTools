"""Root motion extraction using reference-object pinning (Pierrick Picaut method).

Workflow:
1. Setup: Pin key controllers to reference empties, extract root travel
2. (Optional) User polishes root curves in Graph Editor
3. Finalize: Bake controllers with visual keying, clean up empties

The animation stays visually identical — only the root bone gains locomotion data.
Non-destructive: original action is preserved; root motion is baked into a copy.
"""

import math

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from mathutils import Vector

from ..core.constants import PANEL_CATEGORY, WRAP_CTRL_PREFIX
from ..core.utils import _BONE_PATH_RE, assign_channel_groups

RM_CONSTRAINT_PREFIX = "BT_RM_"
RM_EMPTY_PREFIX = "RM_ref_"

# Expert-system thresholds (calibrated for humanoid characters at Blender scale)
_XY_THRESHOLD = 0.05        # meters of net XY displacement for locomotion
_Z_ROT_THRESHOLD = 0.26     # radians (~15 deg) of accumulated yaw
_Z_HEIGHT_THRESHOLD = 0.3   # meters of Z range to suggest jump/climb extraction


# ─── PropertyGroups ────────────────────────────────────────────────────────

class BT_RMBoneItem(bpy.types.PropertyGroup):
    bone_name: StringProperty(name="Bone")


class BT_RMSettings(bpy.types.PropertyGroup):
    is_setup: BoolProperty(name="Setup Active", default=False)
    root_bone: StringProperty(name="Root Bone")
    source_bone: StringProperty(name="Source Bone")
    pinned_bones: CollectionProperty(type=BT_RMBoneItem)
    extract_xy: BoolProperty(
        name="XY Translation",
        description="Transfer ground-plane movement to root",
        default=True,
    )
    extract_z_rot: BoolProperty(
        name="Z Rotation (Yaw)",
        description="Transfer facing direction to root",
        default=True,
    )
    extract_z: BoolProperty(
        name="Z Height",
        description="Transfer vertical movement to root (for jumps/climbs)",
        default=False,
    )
    reference_empties: StringProperty(default="")
    created_root: BoolProperty(default=False)
    original_action: StringProperty(default="")
    anim_type: StringProperty(default="")
    anim_analysis: StringProperty(default="")


# ─── Helpers ──────────────────────────────────────────────────────────────

def _get_action_frame_range(armature_obj):
    """Return (frame_start, frame_end) from the active action, or scene range."""
    anim = armature_obj.animation_data
    if anim and anim.action:
        r = anim.action.frame_range
        return int(r[0]), int(r[1])
    scene = bpy.context.scene
    return scene.frame_start, scene.frame_end


def _analyze_motion(armature_obj, source_bone_name, frame_start, frame_end):
    """Analyze source bone motion to auto-configure extraction settings.

    Stride-samples world-space position/rotation across the frame range
    (max ~120 samples) and classifies the animation type.
    """
    scene = bpy.context.scene
    original_frame = scene.frame_current
    pbone = armature_obj.pose.bones.get(source_bone_name)
    if not pbone or frame_end <= frame_start:
        return {
            'net_xy': 0.0, 'total_z_rot': 0.0, 'z_range': 0.0,
            'extract_xy': True, 'extract_z_rot': True, 'extract_z': False,
            'anim_type': 'unknown', 'summary': '',
        }

    total_frames = frame_end - frame_start
    stride = max(1, total_frames // 120)
    positions = []
    yaw_values = []

    for frame in range(frame_start, frame_end + 1, stride):
        scene.frame_set(frame)
        world_pos = armature_obj.matrix_world @ pbone.head
        positions.append(world_pos.copy())
        world_rot = (armature_obj.matrix_world @ pbone.matrix).to_euler('XYZ')
        yaw_values.append(world_rot.z)

    scene.frame_set(original_frame)

    if len(positions) < 2:
        return {
            'net_xy': 0.0, 'total_z_rot': 0.0, 'z_range': 0.0,
            'extract_xy': True, 'extract_z_rot': True, 'extract_z': False,
            'anim_type': 'unknown', 'summary': '',
        }

    # Net XY displacement (first→last)
    first_xy = Vector((positions[0].x, positions[0].y))
    last_xy = Vector((positions[-1].x, positions[-1].y))
    net_xy = (last_xy - first_xy).length

    # Accumulated absolute yaw delta (handles ±180° wrapping)
    total_z_rot = 0.0
    for i in range(1, len(yaw_values)):
        delta = yaw_values[i] - yaw_values[i - 1]
        delta = math.atan2(math.sin(delta), math.cos(delta))
        total_z_rot += abs(delta)

    # Z height range
    z_values = [p.z for p in positions]
    z_range = max(z_values) - min(z_values)

    # Classification
    has_xy = net_xy > _XY_THRESHOLD
    has_rot = total_z_rot > _Z_ROT_THRESHOLD
    has_z = z_range > _Z_HEIGHT_THRESHOLD

    if has_z:
        anim_type = 'jump'
    elif has_xy and has_rot:
        anim_type = 'locomotion'
    elif has_xy:
        anim_type = 'strafe'
    elif has_rot:
        anim_type = 'turning'
    else:
        anim_type = 'in_place'

    summary = (f"XY: {net_xy:.2f}m, "
               f"Yaw: {math.degrees(total_z_rot):.0f}\u00b0, "
               f"Z: {z_range:.2f}m")

    return {
        'net_xy': net_xy,
        'total_z_rot': total_z_rot,
        'z_range': z_range,
        'extract_xy': has_xy,
        'extract_z_rot': has_rot,
        'extract_z': has_z,
        'anim_type': anim_type,
        'summary': summary,
    }


def _filter_keyed_bones(armature_obj, bone_names, source_bone,
                        frame_start, frame_end):
    """Return only bones from *bone_names* that have keyframes in the action.

    *source_bone* is always kept even if it has no direct keyframes
    (it may be constraint-driven but must still be pinned).
    """
    anim = armature_obj.animation_data
    if not anim or not anim.action:
        return list(bone_names)

    action = anim.action
    keyed = set()
    name_set = set(bone_names)

    for layer in action.layers:
        for strip in layer.strips:
            for cb in strip.channelbags:
                for fc in cb.fcurves:
                    m = _BONE_PATH_RE.search(fc.data_path)
                    if not m:
                        continue
                    bone = m.group(1)
                    if bone in name_set:
                        keyed.add(bone)

    # Always keep source bone
    if source_bone:
        keyed.add(source_bone)

    return [b for b in bone_names if b in keyed]


# ─── Auto Detection ────────────────────────────────────────────────────────

def auto_detect(armature_obj):
    """Detect root, source, and pinned bones from wrap rig or heuristics."""
    sd = getattr(armature_obj, 'bt_scan', None)
    root_bone = ""
    source_bone = ""
    pinned = []

    if sd and sd.has_wrap_rig:
        # Wrap rig: find spine FK controller as source, IK targets as pinned
        for chain in sd.chains:
            if chain.module_type == 'spine':
                chain_bones = [b for b in sd.bones
                               if b.chain_id == chain.chain_id and not b.skip]
                if chain_bones:
                    first = chain_bones[0]
                    ctrl = f"{WRAP_CTRL_PREFIX}{chain.chain_id}_FK_{first.role}"
                    if armature_obj.pose.bones.get(ctrl):
                        source_bone = ctrl
                        pinned.append(ctrl)

            if chain.module_type in ('arm', 'leg') and chain.ik_enabled:
                ik_target = f"{WRAP_CTRL_PREFIX}{chain.chain_id}_IK_target"
                if armature_obj.pose.bones.get(ik_target):
                    pinned.append(ik_target)

        # Root bone from scan data — use CTRL wrap bone, not original/DEF
        for chain in sd.chains:
            if chain.module_type == 'root':
                chain_bones = [b for b in sd.bones
                               if b.chain_id == chain.chain_id and not b.skip]
                if chain_bones:
                    first = chain_bones[0]
                    ctrl = f"{WRAP_CTRL_PREFIX}{chain.chain_id}_FK_{first.role}"
                    if armature_obj.pose.bones.get(ctrl):
                        root_bone = ctrl
                    else:
                        root_bone = first.bone_name
                    break

    # Fallback: heuristic name matching
    if not root_bone:
        for bone in armature_obj.data.bones:
            if bone.name.lower() in ('root', 'root_bone') and not bone.parent:
                root_bone = bone.name
                break

    if not source_bone:
        for name in ('Hips', 'hips', 'pelvis', 'Pelvis', 'mixamorig:Hips',
                      'Bip01', 'Torso', 'torso', 'spine', 'Spine'):
            if armature_obj.data.bones.get(name):
                source_bone = name
                break

    if not pinned and source_bone:
        pinned.append(source_bone)
        # Try to find IK-like bones
        for bone in armature_obj.data.bones:
            nl = bone.name.lower()
            if 'ik' in nl and any(k in nl for k in ('foot', 'hand', 'target')):
                pinned.append(bone.name)

    # ── Motion analysis (expert system) ──
    analysis = None
    frame_start, frame_end = _get_action_frame_range(armature_obj)
    if source_bone:
        analysis = _analyze_motion(armature_obj, source_bone,
                                   frame_start, frame_end)
    if pinned:
        pinned = _filter_keyed_bones(armature_obj, pinned, source_bone,
                                     frame_start, frame_end)

    return {
        'root_bone': root_bone,
        'source_bone': source_bone,
        'pinned_bones': pinned,
        'analysis': analysis,
    }


# ─── Core Logic ────────────────────────────────────────────────────────────

def setup_root_motion(armature_obj):
    """Phase 1: Create empties, bake, flip constraints, extract root motion.

    Non-destructive: copies the active action before baking so the
    original animation data is preserved.
    """
    rm = armature_obj.bt_root_motion
    scene = bpy.context.scene

    pinned = [item.bone_name for item in rm.pinned_bones]
    source = rm.source_bone
    root = rm.root_bone

    # Ensure source is in pinned list
    if source and source not in pinned:
        pinned.append(source)

    # ── 0. Non-destructive action copy ──
    anim = armature_obj.animation_data
    original_action = anim.action if anim else None
    if original_action:
        rm.original_action = original_action.name
        copy = original_action.copy()
        copy.name = f"{original_action.name}_root_motion"
        anim.action = copy

    frame_start, frame_end = _get_action_frame_range(armature_obj)

    # Find or create root bone
    if not armature_obj.data.bones.get(root):
        _create_root_bone(armature_obj, root, source)
        rm.created_root = True

    # ── 1. Create reference empties ──
    empties = []
    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode='OBJECT')

    for bone_name in pinned:
        name = f"{RM_EMPTY_PREFIX}{bone_name}"
        empty = bpy.data.objects.new(name, None)
        empty.empty_display_type = 'PLAIN_AXES'
        empty.empty_display_size = 0.05
        scene.collection.objects.link(empty)

        con = empty.constraints.new('COPY_TRANSFORMS')
        con.target = armature_obj
        con.subtarget = bone_name
        empties.append(empty)

    # ── 2. Bake empties (visual keying, clear constraints) ──
    bpy.ops.object.select_all(action='DESELECT')
    for e in empties:
        e.select_set(True)
    bpy.context.view_layer.objects.active = empties[0]

    bpy.ops.nla.bake(
        frame_start=frame_start,
        frame_end=frame_end,
        visual_keying=True,
        clear_constraints=True,
        bake_types={'OBJECT'},
    )

    # ── 3. Constrain pinned bones → empties ──
    bpy.ops.object.select_all(action='DESELECT')
    armature_obj.select_set(True)
    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode='POSE')

    for bone_name in pinned:
        pbone = armature_obj.pose.bones.get(bone_name)
        empty = bpy.data.objects.get(f"{RM_EMPTY_PREFIX}{bone_name}")
        if pbone and empty:
            con = pbone.constraints.new('COPY_TRANSFORMS')
            con.name = f"{RM_CONSTRAINT_PREFIX}pin"
            con.target = empty

    # ── 4. Extract root motion: constrain root → source empty ──
    root_pbone = armature_obj.pose.bones.get(root)
    source_empty = bpy.data.objects.get(f"{RM_EMPTY_PREFIX}{source}")

    if root_pbone and source_empty:
        if rm.extract_xy:
            con = root_pbone.constraints.new('COPY_LOCATION')
            con.name = f"{RM_CONSTRAINT_PREFIX}loc"
            con.target = source_empty
            con.use_x = True
            con.use_y = True
            con.use_z = False

        if rm.extract_z_rot:
            con = root_pbone.constraints.new('COPY_ROTATION')
            con.name = f"{RM_CONSTRAINT_PREFIX}rot"
            con.target = source_empty
            con.use_x = False
            con.use_y = False
            con.use_z = True

        if rm.extract_z:
            con = root_pbone.constraints.new('COPY_LOCATION')
            con.name = f"{RM_CONSTRAINT_PREFIX}loc_z"
            con.target = source_empty
            con.use_x = False
            con.use_y = False
            con.use_z = True

    # ── 5. Bake root bone ──
    if not root_pbone:
        bpy.ops.object.mode_set(mode='OBJECT')
        return
    bpy.ops.pose.select_all(action='DESELECT')
    root_pbone.select = True
    armature_obj.data.bones.active = root_pbone.bone

    bpy.ops.nla.bake(
        frame_start=frame_start,
        frame_end=frame_end,
        only_selected=True,
        visual_keying=True,
        clear_constraints=True,
        use_current_action=True,
        bake_types={'POSE'},
    )
    assign_channel_groups(armature_obj)

    bpy.ops.object.mode_set(mode='OBJECT')

    rm.is_setup = True
    rm.reference_empties = ",".join(e.name for e in empties)

    return {"empties": len(empties), "pinned": len(pinned)}


def finalize_root_motion(armature_obj):
    """Phase 2: Bake pinned controllers, clean up empties."""
    rm = armature_obj.bt_root_motion
    pinned = [item.bone_name for item in rm.pinned_bones]
    source = rm.source_bone
    if source and source not in pinned:
        pinned.append(source)

    frame_start, frame_end = _get_action_frame_range(armature_obj)
    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode='POSE')

    # Select pinned bones
    bpy.ops.pose.select_all(action='DESELECT')
    for bone_name in pinned:
        pbone = armature_obj.pose.bones.get(bone_name)
        if pbone:
            pbone.select = True

    # Bake with visual keying, overwrite action
    bpy.ops.nla.bake(
        frame_start=frame_start,
        frame_end=frame_end,
        only_selected=True,
        visual_keying=True,
        clear_constraints=False,
        use_current_action=True,
        bake_types={'POSE'},
    )
    assign_channel_groups(armature_obj)

    # Remove only our BT_RM_ constraints
    for bone_name in pinned:
        pbone = armature_obj.pose.bones.get(bone_name)
        if pbone:
            to_remove = [c for c in pbone.constraints
                         if c.name.startswith(RM_CONSTRAINT_PREFIX)]
            for c in to_remove:
                pbone.constraints.remove(c)

    bpy.ops.object.mode_set(mode='OBJECT')
    _cleanup_empties(armature_obj)
    rm.is_setup = False

    return {"finalized": len(pinned)}


def cancel_root_motion(armature_obj):
    """Cancel: remove pin constraints, empties, and restore original action."""
    rm = armature_obj.bt_root_motion
    pinned = [item.bone_name for item in rm.pinned_bones]
    source = rm.source_bone
    if source and source not in pinned:
        pinned.append(source)

    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode='POSE')

    all_bones = set(pinned) | {rm.root_bone}
    for bone_name in all_bones:
        pbone = armature_obj.pose.bones.get(bone_name)
        if pbone:
            to_remove = [c for c in pbone.constraints
                         if c.name.startswith(RM_CONSTRAINT_PREFIX)]
            for c in to_remove:
                pbone.constraints.remove(c)

    bpy.ops.object.mode_set(mode='OBJECT')
    _cleanup_empties(armature_obj)

    # Restore original action, remove the root motion copy
    anim = armature_obj.animation_data
    if rm.original_action and anim:
        original = bpy.data.actions.get(rm.original_action)
        rm_copy = anim.action
        if original:
            anim.action = original
        if (rm_copy and rm_copy != original
                and rm_copy.name.endswith("_root_motion")):
            bpy.data.actions.remove(rm_copy, do_unlink=True)

    rm.is_setup = False
    rm.original_action = ""
    rm.anim_type = ""
    rm.anim_analysis = ""


def _create_root_bone(armature_obj, root_name, source_name):
    """Create a root bone at origin and reparent all top-level bones to it."""
    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode='EDIT')
    eb = armature_obj.data.edit_bones

    root_eb = eb.new(root_name)
    root_eb.head = Vector((0, 0, 0))
    root_eb.tail = Vector((0, 0, 0.1))
    root_eb.roll = 0
    root_eb.use_deform = True  # Must export to FBX for UE root motion

    # Reparent all top-level bones to root
    for bone in eb:
        if bone != root_eb and bone.parent is None:
            bone.parent = root_eb

    bpy.ops.object.mode_set(mode='OBJECT')


def _cleanup_empties(armature_obj):
    """Remove reference empties and their baked actions."""
    rm = armature_obj.bt_root_motion
    if rm.reference_empties:
        for name in rm.reference_empties.split(","):
            name = name.strip()
            obj = bpy.data.objects.get(name)
            if obj:
                # Remove the action created by nla.bake on this empty
                if obj.animation_data and obj.animation_data.action:
                    bpy.data.actions.remove(obj.animation_data.action,
                                            do_unlink=True)
                bpy.data.objects.remove(obj, do_unlink=True)
        rm.reference_empties = ""


# ─── Operators ─────────────────────────────────────────────────────────────

class BT_OT_RMAutoDetect(bpy.types.Operator):
    bl_idname = "bt.rm_auto_detect"
    bl_label = "Auto Detect"
    bl_description = "Detect root, source, and pinned bones automatically"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'ARMATURE'

    def execute(self, context):
        armature = context.active_object
        rm = armature.bt_root_motion
        result = auto_detect(armature)

        rm.root_bone = result['root_bone']
        rm.source_bone = result['source_bone']
        rm.pinned_bones.clear()
        for name in result['pinned_bones']:
            item = rm.pinned_bones.add()
            item.bone_name = name

        # Apply motion analysis
        analysis = result.get('analysis')
        if analysis:
            rm.extract_xy = analysis['extract_xy']
            rm.extract_z_rot = analysis['extract_z_rot']
            rm.extract_z = analysis['extract_z']
            rm.anim_type = analysis['anim_type']
            rm.anim_analysis = analysis['summary']

        found = len(result['pinned_bones'])
        anim_tag = f" [{rm.anim_type}]" if rm.anim_type else ""
        if not result['root_bone']:
            self.report({'INFO'},
                        f"No root bone found — one will be created. "
                        f"Detected {found} controllers.{anim_tag}")
        else:
            self.report({'INFO'},
                        f"Detected root='{result['root_bone']}', "
                        f"source='{result['source_bone']}', "
                        f"{found} pinned controllers.{anim_tag}")
        return {'FINISHED'}


class BT_OT_RMAddSelected(bpy.types.Operator):
    bl_idname = "bt.rm_add_selected"
    bl_label = "Add Selected"
    bl_description = "Add selected pose bones to pinned controllers"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.active_object and context.active_object.type == 'ARMATURE'
                and context.mode == 'POSE' and context.selected_pose_bones)

    def execute(self, context):
        rm = context.active_object.bt_root_motion
        existing = {item.bone_name for item in rm.pinned_bones}
        added = 0
        for pbone in context.selected_pose_bones:
            if pbone.name not in existing:
                item = rm.pinned_bones.add()
                item.bone_name = pbone.name
                added += 1
        self.report({'INFO'}, f"Added {added} bone(s)")
        return {'FINISHED'}


class BT_OT_RMRemoveBone(bpy.types.Operator):
    bl_idname = "bt.rm_remove_bone"
    bl_label = "Remove"
    bl_description = "Remove bone from pinned controllers"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty()

    def execute(self, context):
        rm = context.active_object.bt_root_motion
        if 0 <= self.index < len(rm.pinned_bones):
            rm.pinned_bones.remove(self.index)
        return {'FINISHED'}


class BT_OT_RMSetup(bpy.types.Operator):
    bl_idname = "bt.rm_setup"
    bl_label = "Setup Root Motion"
    bl_description = ("Create reference empties, pin controllers, "
                      "and extract root travel. Edit root curves in Graph Editor "
                      "before finalizing")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            return False
        rm = obj.bt_root_motion
        return (not rm.is_setup and rm.source_bone
                and len(rm.pinned_bones) > 0)

    def execute(self, context):
        armature = context.active_object
        rm = armature.bt_root_motion

        if not rm.extract_xy and not rm.extract_z_rot and not rm.extract_z:
            self.report({'WARNING'}, "No extraction enabled — enable at "
                        "least one of XY, Z Rot, or Z Height.")
            return {'CANCELLED'}

        if rm.anim_type == 'in_place':
            self.report({'INFO'}, "Animation appears to be in-place "
                        "(no significant travel detected).")

        if not rm.root_bone:
            rm.root_bone = "root"

        try:
            stats = setup_root_motion(armature)
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        self.report({'INFO'},
                    f"Root motion setup complete. "
                    f"{stats['pinned']} controllers pinned. "
                    f"Edit root curves, then Finalize.")
        return {'FINISHED'}


class BT_OT_RMFinalize(bpy.types.Operator):
    bl_idname = "bt.rm_finalize"
    bl_label = "Finalize Root Motion"
    bl_description = "Bake pinned controllers and clean up reference objects"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj and obj.type == 'ARMATURE'
                and obj.bt_root_motion.is_setup)

    def execute(self, context):
        armature = context.active_object
        try:
            stats = finalize_root_motion(armature)
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        self.report({'INFO'},
                    f"Root motion finalized. {stats['finalized']} controllers baked.")
        return {'FINISHED'}


class BT_OT_RMCancel(bpy.types.Operator):
    bl_idname = "bt.rm_cancel"
    bl_label = "Cancel Root Motion"
    bl_description = "Remove pin constraints and empties (root keyframes are kept)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj and obj.type == 'ARMATURE'
                and obj.bt_root_motion.is_setup)

    def execute(self, context):
        cancel_root_motion(context.active_object)
        self.report({'INFO'}, "Root motion setup cancelled.")
        return {'FINISHED'}


# ─── Panel ─────────────────────────────────────────────────────────────────

class BT_PT_RootMotion(bpy.types.Panel):
    bl_label = "Root Motion"
    bl_idname = "BT_PT_RootMotion"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = PANEL_CATEGORY
    bl_parent_id = "BT_PT_AnimationMain"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'ARMATURE'

    def draw(self, context):
        layout = self.layout
        armature = context.active_object
        rm = armature.bt_root_motion

        if rm.is_setup:
            # ── Active phase: polish root curves, then finalize ──
            box = layout.box()
            box.label(text="Root motion is active.", icon='CHECKMARK')
            box.label(text="Edit root curves in Graph Editor.")
            box.label(text=f"Root: {rm.root_bone}")

            col = layout.column(align=True)
            col.scale_y = 1.3
            col.operator("bt.rm_finalize", icon='CHECKMARK')
            col.operator("bt.rm_cancel", icon='CANCEL')
            return

        # ── Config phase ──

        # Source bone (whose XY travel drives the root bone)
        layout.label(text="Locomotion Source (COG/hips):", icon='BONE_DATA')
        layout.prop_search(rm, "source_bone", armature.data, "bones", text="")

        # Root bone
        layout.label(text="Root bone:", icon='BONE_DATA')
        row = layout.row(align=True)
        row.prop_search(rm, "root_bone", armature.data, "bones", text="")
        if not rm.root_bone:
            row.label(text="(will create)", icon='ADD')

        layout.separator()

        # Pinned controllers
        layout.label(text="Pinned Controllers:", icon='PINNED')
        box = layout.box()
        if len(rm.pinned_bones) == 0:
            box.label(text="None — use Auto Detect or Add Selected", icon='INFO')
        else:
            for i, item in enumerate(rm.pinned_bones):
                row = box.row(align=True)
                row.label(text=item.bone_name)
                op = row.operator("bt.rm_remove_bone", text="", icon='X')
                op.index = i

        row = layout.row(align=True)
        row.operator("bt.rm_add_selected", icon='ADD')
        row.operator("bt.rm_auto_detect", icon='VIEWZOOM')

        layout.separator()

        # Options
        layout.label(text="Extract to Root:", icon='EXPORT')
        row = layout.row(align=True)
        row.prop(rm, "extract_xy", toggle=True)
        row.prop(rm, "extract_z_rot", toggle=True)
        row.prop(rm, "extract_z", toggle=True)

        # Analysis summary (shown after Auto Detect)
        if rm.anim_analysis:
            box = layout.box()
            box.label(text=rm.anim_analysis, icon='INFO')
            if rm.anim_type:
                box.label(text=f"Type: {rm.anim_type}")

        layout.separator()

        # Setup button
        col = layout.column()
        col.scale_y = 1.3
        col.operator("bt.rm_setup", icon='PLAY')


# ─── Registration ──────────────────────────────────────────────────────────

classes = (
    BT_RMBoneItem,
    BT_RMSettings,
    BT_OT_RMAutoDetect,
    BT_OT_RMAddSelected,
    BT_OT_RMRemoveBone,
    BT_OT_RMSetup,
    BT_OT_RMFinalize,
    BT_OT_RMCancel,
    BT_PT_RootMotion,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Object.bt_root_motion = PointerProperty(type=BT_RMSettings)


def unregister():
    del bpy.types.Object.bt_root_motion
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
