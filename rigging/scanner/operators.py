"""Skeleton scanner operators."""

import bpy
from .scan import scan_skeleton
from .wrap_assembly import (
    assemble_wrap_rig, disassemble_wrap_rig, bake_to_def,
    snap_fk_to_ik, snap_ik_to_fk,
)
from .floor_contact import (
    setup_floor_contact, remove_floor_contact, toggle_toe_bend_for_chain,
)


def _scan_data_to_props(armature_obj, scan_data):
    """Populate the bt_scan PropertyGroup from scan_data dict."""
    sd = armature_obj.bt_scan
    sd.skeleton_type = scan_data["skeleton_type"]
    sd.confidence = scan_data["confidence"]
    sd.is_scanned = True

    sd.bones.clear()
    for bone_name, info in scan_data["bones"].items():
        item = sd.bones.add()
        item.bone_name = bone_name
        item.role = info["role"]
        item.side = info["side"]
        item.module_type = info["module_type"]
        item.chain_id = info["chain_id"]
        item.confidence = info["confidence"]
        item.skip = info.get("skip", False)

    sd.chains.clear()
    for chain_id, info in scan_data["chains"].items():
        item = sd.chains.add()
        item.chain_id = chain_id
        item.module_type = info["module_type"]
        item.side = info["side"]
        item.bone_count = info["bone_count"]
        item.ik_enabled = info["module_type"] in ("arm", "leg")
        item.fk_enabled = True
        item.ik_snap = info["module_type"] in ("arm", "leg")

    sd.unmapped_bones = ",".join(scan_data.get("unmapped_bones", []))


def _props_to_scan_data(armature_obj):
    """Reconstruct scan_data dict from bt_scan PropertyGroup."""
    sd = armature_obj.bt_scan

    bones = {}
    for item in sd.bones:
        bones[item.bone_name] = {
            "role": item.role,
            "side": item.side,
            "module_type": item.module_type,
            "chain_id": item.chain_id,
            "confidence": item.confidence,
            "skip": item.skip,
            "source": "user",
        }

    chains = {}
    for item in sd.chains:
        chain_bones = [
            b.bone_name for b in sd.bones
            if b.chain_id == item.chain_id and not b.skip
        ]
        chains[item.chain_id] = {
            "module_type": item.module_type,
            "side": item.side,
            "bones": chain_bones,
            "bone_count": len(chain_bones),
            "ik_enabled": item.ik_enabled,
            "fk_enabled": item.fk_enabled,
            "ik_snap": item.ik_snap,
        }

    unmapped = [s.strip() for s in sd.unmapped_bones.split(",") if s.strip()]

    return {
        "skeleton_type": sd.skeleton_type,
        "confidence": sd.confidence,
        "bones": bones,
        "chains": chains,
        "unmapped_bones": unmapped,
        "generated_bones": [],
    }


class BT_OT_ScanSkeleton(bpy.types.Operator):
    bl_idname = "bt.scan_skeleton"
    bl_label = "Scan Skeleton"
    bl_description = "Analyze the selected armature and detect bone roles"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'ARMATURE'

    def execute(self, context):
        armature = context.active_object
        scan_data = scan_skeleton(armature)
        _scan_data_to_props(armature, scan_data)

        bone_count = len(scan_data["bones"])
        chain_count = len(scan_data["chains"])
        self.report(
            {'INFO'},
            f"Detected {scan_data['skeleton_type']} ({scan_data['confidence']:.0%}): "
            f"{bone_count} bones, {chain_count} chains"
        )
        return {'FINISHED'}


class BT_OT_ApplyWrapRig(bpy.types.Operator):
    bl_idname = "bt.apply_wrap_rig"
    bl_label = "Apply Wrap Rig"
    bl_description = "Generate control bones around the existing skeleton"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'ARMATURE' and obj.bt_scan.is_scanned

    def execute(self, context):
        armature = context.active_object

        # Clear existing wrap rig first
        if armature.bt_scan.has_wrap_rig:
            disassemble_wrap_rig(armature)

        scan_data = _props_to_scan_data(armature)

        # Apply chain overrides from UI
        for chain_item in armature.bt_scan.chains:
            cid = chain_item.chain_id
            if cid in scan_data["chains"]:
                scan_data["chains"][cid]["module_type"] = chain_item.module_type
                scan_data["chains"][cid]["ik_enabled"] = chain_item.ik_enabled
                scan_data["chains"][cid]["fk_enabled"] = chain_item.fk_enabled
                # Update bone module_types to match chain override
                for bone_name in scan_data["chains"][cid]["bones"]:
                    if bone_name in scan_data["bones"]:
                        scan_data["bones"][bone_name]["module_type"] = chain_item.module_type

        created = assemble_wrap_rig(armature, scan_data)
        armature.bt_scan.has_wrap_rig = True

        # Reset runtime FK/IK state (all chains start in FK mode)
        for chain_item in armature.bt_scan.chains:
            chain_item.ik_active = False

        self.report({'INFO'}, f"Created {len(created)} control bones")
        return {'FINISHED'}


class BT_OT_ToggleFKIK(bpy.types.Operator):
    bl_idname = "bt.toggle_fk_ik"
    bl_label = "Toggle FK/IK"
    bl_description = "Switch a limb chain between FK and IK mode"
    bl_options = {'REGISTER', 'UNDO'}

    chain_id: bpy.props.StringProperty(name="Chain ID")
    mode: bpy.props.EnumProperty(
        name="Mode",
        items=[
            ('FK', "FK", "FK mode (COPY_TRANSFORMS)"),
            ('IK', "IK", "IK mode"),
            ('TOGGLE', "Toggle", "Toggle between FK and IK"),
        ],
        default='TOGGLE',
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'ARMATURE' and obj.bt_scan.has_wrap_rig

    def execute(self, context):
        from ...core.constants import WRAP_CONSTRAINT_PREFIX, WRAP_MCH_PREFIX
        armature = context.active_object
        sd = armature.bt_scan

        # Find the chain
        chain_item = None
        for ch in sd.chains:
            if ch.chain_id == self.chain_id:
                chain_item = ch
                break

        if not chain_item:
            self.report({'WARNING'}, f"Chain '{self.chain_id}' not found")
            return {'CANCELLED'}

        # Determine target mode
        if self.mode == 'TOGGLE':
            use_ik = not chain_item.ik_active
        else:
            use_ik = (self.mode == 'IK')

        # Already in the requested mode — nothing to do
        if use_ik == chain_item.ik_active:
            return {'FINISHED'}

        # Snap controls BEFORE switching so the pose is preserved
        # Only snap for chains with ik_snap enabled (stable 2-bone IK)
        if chain_item.ik_snap:
            if use_ik:
                snap_ik_to_fk(armature, self.chain_id)
            else:
                snap_fk_to_ik(armature, self.chain_id)

        # Toggle constraints on MCH bones (not DEF bones)
        chain_bones = [b for b in sd.bones if b.chain_id == self.chain_id and not b.skip]

        for bone_item in chain_bones:
            mch_name = f"{WRAP_MCH_PREFIX}{self.chain_id}_{bone_item.role}"
            mch_pbone = armature.pose.bones.get(mch_name)
            if not mch_pbone:
                continue
            for con in mch_pbone.constraints:
                if not con.name.startswith(WRAP_CONSTRAINT_PREFIX):
                    continue
                if con.type == 'COPY_TRANSFORMS':
                    con.influence = 0.0 if use_ik else 1.0
                elif con.type == 'IK':
                    con.influence = 1.0 if use_ik else 0.0

        # Update runtime state (build config fk_enabled/ik_enabled stays untouched)
        chain_item.ik_active = use_ik

        # Show/hide per-chain IK collection based on mode
        ik_coll = armature.data.collections.get(f"IK_{self.chain_id}")
        if ik_coll:
            ik_coll.is_visible = use_ik

        # Toggle floor toe bend constraint if floor contact is active
        if armature.bt_scan.floor_enabled:
            toggle_toe_bend_for_chain(armature, self.chain_id, use_ik)

        mode_name = "IK" if use_ik else "FK"
        self.report({'INFO'}, f"{self.chain_id}: switched to {mode_name}")
        return {'FINISHED'}


class BT_OT_ClearWrapRig(bpy.types.Operator):
    bl_idname = "bt.clear_wrap_rig"
    bl_label = "Clear Wrap Rig"
    bl_description = "Remove generated control bones (keeps original skeleton)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'ARMATURE' and obj.bt_scan.has_wrap_rig

    def execute(self, context):
        armature = context.active_object
        if armature.bt_scan.floor_enabled:
            remove_floor_contact(armature)
            armature.bt_scan.floor_enabled = False
        disassemble_wrap_rig(armature)
        armature.bt_scan.has_wrap_rig = False
        self.report({'INFO'}, "Wrap rig removed")
        return {'FINISHED'}


class BT_OT_ClearScanData(bpy.types.Operator):
    bl_idname = "bt.clear_scan_data"
    bl_label = "Clear Scan Data"
    bl_description = "Remove wrap rig and all scan data"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'ARMATURE' and obj.bt_scan.is_scanned

    def execute(self, context):
        armature = context.active_object

        if armature.bt_scan.has_wrap_rig:
            disassemble_wrap_rig(armature)

        sd = armature.bt_scan
        sd.bones.clear()
        sd.chains.clear()
        sd.unmapped_bones = ""
        sd.skeleton_type = ""
        sd.confidence = 0.0
        sd.is_scanned = False
        sd.has_wrap_rig = False

        self.report({'INFO'}, "Scan data cleared")
        return {'FINISHED'}


class BT_OT_BatchSkipSelected(bpy.types.Operator):
    bl_idname = "bt.batch_skip_selected"
    bl_label = "Skip Selected"
    bl_description = "Mark currently selected bones as skip"
    bl_options = {'REGISTER', 'UNDO'}

    skip_value: bpy.props.BoolProperty(name="Skip", default=True)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj and obj.type == 'ARMATURE' and obj.bt_scan.is_scanned
                and context.mode in ('POSE', 'EDIT_ARMATURE'))

    def execute(self, context):
        armature = context.active_object
        sd = armature.bt_scan

        # Get selected bone names from pose or edit mode
        if context.mode == 'POSE':
            selected = {b.name for b in context.selected_pose_bones or []}
        else:
            selected = {b.name for b in armature.data.edit_bones if b.select}

        count = 0
        for item in sd.bones:
            if item.bone_name in selected:
                item.skip = self.skip_value
                count += 1

        action = "Skipped" if self.skip_value else "Unskipped"
        self.report({'INFO'}, f"{action} {count} bones")
        return {'FINISHED'}


class BT_OT_BatchSkipByPattern(bpy.types.Operator):
    bl_idname = "bt.batch_skip_pattern"
    bl_label = "Skip by Pattern"
    bl_description = "Mark bones matching the name pattern as skip"
    bl_options = {'REGISTER', 'UNDO'}

    skip_value: bpy.props.BoolProperty(name="Skip", default=True)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'ARMATURE' and obj.bt_scan.is_scanned

    def execute(self, context):
        import fnmatch
        armature = context.active_object
        sd = armature.bt_scan
        pattern = sd.skip_pattern.strip()

        if not pattern:
            self.report({'WARNING'}, "Enter a pattern first")
            return {'CANCELLED'}

        count = 0
        for item in sd.bones:
            if fnmatch.fnmatch(item.bone_name, pattern):
                item.skip = self.skip_value
                count += 1

        action = "Skipped" if self.skip_value else "Unskipped"
        self.report({'INFO'}, f"{action} {count} bones matching '{pattern}'")
        return {'FINISHED'}


class BT_OT_BatchUnskipAll(bpy.types.Operator):
    bl_idname = "bt.batch_unskip_all"
    bl_label = "Unskip All"
    bl_description = "Clear skip flag on all bones"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'ARMATURE' and obj.bt_scan.is_scanned

    def execute(self, context):
        armature = context.active_object
        count = 0
        for item in armature.bt_scan.bones:
            if item.skip:
                item.skip = False
                count += 1
        self.report({'INFO'}, f"Unskipped {count} bones")
        return {'FINISHED'}


class BT_OT_BakeToDef(bpy.types.Operator):
    bl_idname = "bt.bake_to_def"
    bl_label = "Bake to DEF"
    bl_description = "Bake animations from CTRL/MCH chain onto DEF bones, then remove wrap rig"
    bl_options = {'REGISTER', 'UNDO'}

    frame_start: bpy.props.IntProperty(name="Start Frame", default=0)
    frame_end: bpy.props.IntProperty(name="End Frame", default=0)
    use_scene_range: bpy.props.BoolProperty(name="Use Scene Range", default=True)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'ARMATURE' and obj.bt_scan.has_wrap_rig

    def execute(self, context):
        armature = context.active_object
        start = None if self.use_scene_range else self.frame_start
        end = None if self.use_scene_range else self.frame_end

        stats = bake_to_def(armature, start, end)
        self.report(
            {'INFO'},
            f"Baked {stats['baked']} bones over {stats['frames']} frames. Wrap rig removed."
        )
        return {'FINISHED'}


class BT_OT_ToggleFloorContact(bpy.types.Operator):
    bl_idname = "bt.toggle_floor_contact"
    bl_label = "Toggle Floor Contact"
    bl_description = "Add or remove floor constraints on leg IK targets"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE' or not obj.bt_scan.has_wrap_rig:
            return False
        return any(ch.module_type == "leg" for ch in obj.bt_scan.chains)

    def execute(self, context):
        armature = context.active_object
        sd = armature.bt_scan

        if sd.floor_enabled:
            remove_floor_contact(armature)
            sd.floor_enabled = False
            self.report({'INFO'}, "Floor contact removed")
        else:
            result = setup_floor_contact(
                armature,
                floor_level=sd.floor_level,
                toe_bend=sd.floor_toe_bend,
                toe_bend_max_rad=sd.floor_toe_angle,
            )
            if "error" in result:
                self.report({'WARNING'}, result["error"])
                return {'CANCELLED'}
            sd.floor_enabled = True
            msg = f"Floor contact: {result['floor_constraints']} legs"
            if result.get("toe_bends"):
                msg += f", {result['toe_bends']} toe bends"
            self.report({'INFO'}, msg)

        return {'FINISHED'}


class BT_OT_UpdateFloorLevel(bpy.types.Operator):
    bl_idname = "bt.update_floor_level"
    bl_label = "Update Floor Level"
    bl_description = "Apply the current floor level to existing floor constraints"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj and obj.type == 'ARMATURE'
                and obj.bt_scan.has_wrap_rig and obj.bt_scan.floor_enabled)

    def execute(self, context):
        from .floor_contact import update_floor_level
        armature = context.active_object
        update_floor_level(armature, armature.bt_scan.floor_level)
        self.report({'INFO'}, f"Floor level updated to {armature.bt_scan.floor_level:.3f}")
        return {'FINISHED'}


classes = (
    BT_OT_ScanSkeleton,
    BT_OT_ApplyWrapRig,
    BT_OT_ToggleFKIK,
    BT_OT_ClearWrapRig,
    BT_OT_ClearScanData,
    BT_OT_BatchSkipSelected,
    BT_OT_BatchSkipByPattern,
    BT_OT_BatchUnskipAll,
    BT_OT_BakeToDef,
    BT_OT_ToggleFloorContact,
    BT_OT_UpdateFloorLevel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
