"""Root motion extraction using reference-object pinning (Pierrick Picaut method).

Workflow:
1. Setup: Pin key controllers to reference empties, extract root travel
2. (Optional) User polishes root curves in Graph Editor
3. Finalize: Bake controllers with visual keying, clean up empties

The animation stays visually identical — only the root bone gains locomotion data.
"""

import bpy
from mathutils import Vector
from bpy.props import (
    StringProperty, BoolProperty, CollectionProperty, PointerProperty, IntProperty,
)
from ..core.constants import PANEL_CATEGORY, WRAP_CTRL_PREFIX

RM_CONSTRAINT_PREFIX = "BT_RM_"
RM_EMPTY_PREFIX = "RM_ref_"


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
    reference_empties: StringProperty(default="")
    created_root: BoolProperty(default=False)


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

        # Root bone from scan data
        for chain in sd.chains:
            if chain.module_type == 'root':
                chain_bones = [b for b in sd.bones
                               if b.chain_id == chain.chain_id and not b.skip]
                if chain_bones:
                    root_bone = chain_bones[0].bone_name
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

    return {'root_bone': root_bone, 'source_bone': source_bone, 'pinned_bones': pinned}


# ─── Core Logic ────────────────────────────────────────────────────────────

def setup_root_motion(armature_obj):
    """Phase 1: Create empties, bake, flip constraints, extract root motion."""
    rm = armature_obj.bt_root_motion
    scene = bpy.context.scene

    pinned = [item.bone_name for item in rm.pinned_bones]
    source = rm.source_bone
    root = rm.root_bone

    # Ensure source is in pinned list
    if source and source not in pinned:
        pinned.append(source)

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
        frame_start=scene.frame_start,
        frame_end=scene.frame_end,
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

    # ── 5. Bake root bone ──
    if not root_pbone:
        bpy.ops.object.mode_set(mode='OBJECT')
        return
    bpy.ops.pose.select_all(action='DESELECT')
    root_pbone.bone.select = True
    armature_obj.data.bones.active = root_pbone.bone

    bpy.ops.nla.bake(
        frame_start=scene.frame_start,
        frame_end=scene.frame_end,
        only_selected=True,
        visual_keying=True,
        clear_constraints=True,
        use_current_action=True,
        bake_types={'POSE'},
    )

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

    scene = bpy.context.scene
    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode='POSE')

    # Select pinned bones
    bpy.ops.pose.select_all(action='DESELECT')
    for bone_name in pinned:
        pbone = armature_obj.pose.bones.get(bone_name)
        if pbone:
            pbone.bone.select = True

    # Bake with visual keying, overwrite action
    bpy.ops.nla.bake(
        frame_start=scene.frame_start,
        frame_end=scene.frame_end,
        only_selected=True,
        visual_keying=True,
        clear_constraints=False,
        use_current_action=True,
        bake_types={'POSE'},
    )

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
    """Cancel: remove pin constraints and empties. Root keyframes are kept."""
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
    rm.is_setup = False


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
    """Remove reference empties."""
    rm = armature_obj.bt_root_motion
    if rm.reference_empties:
        for name in rm.reference_empties.split(","):
            name = name.strip()
            obj = bpy.data.objects.get(name)
            if obj:
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

        found = len(result['pinned_bones'])
        if not result['root_bone']:
            self.report({'INFO'},
                        f"No root bone found — one will be created. "
                        f"Detected {found} controllers.")
        else:
            self.report({'INFO'},
                        f"Detected root='{result['root_bone']}', "
                        f"source='{result['source_bone']}', "
                        f"{found} pinned controllers.")
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
