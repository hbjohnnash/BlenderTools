"""Skeleton scanner operators."""

import math

import bpy

from ...core.constants import (
    WRAP_CONSTRAINT_PREFIX,
    WRAP_CTRL_PREFIX,
    WRAP_MCH_PREFIX,
)
from .floor_contact import (
    remove_floor_contact,
    setup_floor_contact,
)
from .scan import scan_skeleton
from .wrap_assembly import (
    _has_ik_switch,
    _ik_switch_prop_name,
    assemble_wrap_rig,
    bake_to_def,
    disassemble_wrap_rig,
    ensure_fk_sync,
    fk_was_modified,
    migrate_action_ik_switch,
    restore_ik_state,
    restore_lookat_state,
    save_fk_snapshot,
    save_ik_state,
    save_lookat_state,
    snap_fk_to_ik,
    snap_ik_to_fk,
    snap_lookat_to_fk,
    snap_spline_to_fk,
    toggle_ik_limits,
    upgrade_ik_switch,
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
        item.ik_enabled = info["module_type"] in ("arm", "leg", "wing", "neck_head")
        item.fk_enabled = True
        item.ik_snap = info["module_type"] in ("arm", "leg", "wing", "neck_head")
        if info["module_type"] == "neck_head":
            item.ik_type = 'LOOKAT'
        elif info["module_type"] in ("tail", "tentacle"):
            item.ik_type = 'SPLINE'
        else:
            item.ik_type = 'STANDARD'
        item.ik_limits = False

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
            "ik_type": item.ik_type,
            "ik_limits": item.ik_limits,
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
                scan_data["chains"][cid]["ik_type"] = chain_item.ik_type
                scan_data["chains"][cid]["ik_limits"] = chain_item.ik_limits
                # Update bone module_types to match chain override
                for bone_name in scan_data["chains"][cid]["bones"]:
                    if bone_name in scan_data["bones"]:
                        scan_data["bones"][bone_name]["module_type"] = chain_item.module_type

        created = assemble_wrap_rig(armature, scan_data)
        armature.bt_scan.has_wrap_rig = True

        # Assign custom shapes to control bones
        from ..shapes import assign_shapes_for_wrap_rig
        assign_shapes_for_wrap_rig(armature)

        # Reset runtime FK/IK state (all chains start in FK mode)
        for chain_item in armature.bt_scan.chains:
            chain_item.ik_active = False

        # Auto-enable overlays: switch to pose mode, start FK/IK + CoM
        bpy.ops.object.mode_set(mode='POSE')
        try:
            from .ik_overlay import _active as ik_active
            if not ik_active:
                bpy.ops.bt.ik_overlay('INVOKE_DEFAULT')
        except Exception:
            pass
        try:
            from ..center_of_mass import _active as com_active
            if not com_active:
                bpy.ops.bt.toggle_com()
        except Exception:
            pass

        self.report({'INFO'}, f"Created {len(created)} control bones")
        return {'FINISHED'}


def _mute_bone_fcurves(armature, pbones):
    """Temporarily mute all fcurves for the given pose bones.

    Returns a list of fcurves that were muted so they can be unmuted later.
    This prevents view_layer.update() from overwriting snapped bone
    transforms with keyframed values while still allowing drivers and
    constraints to evaluate correctly.
    """
    action = armature.animation_data and armature.animation_data.action
    if not action:
        return []
    from ...animation.smart_keyframe import _iter_fcurves
    bone_prefixes = [f'pose.bones["{pb.name}"]' for pb in pbones]
    muted = []
    for fc in _iter_fcurves(action):
        if fc.mute:
            continue
        for prefix in bone_prefixes:
            if fc.data_path.startswith(prefix):
                fc.mute = True
                muted.append(fc)
                break
    return muted


def _unmute_fcurves(fcurves):
    """Unmute previously muted fcurves."""
    for fc in fcurves:
        fc.mute = False


# ---------------------------------------------------------------------------
# Persistent mute: keep fcurves muted across viewport redraws until the user
# changes frame, keyframes, or plays the animation.
# ---------------------------------------------------------------------------

_pending_muted_fcs = []


def _on_frame_change_unmute(scene):
    """Unmute pending fcurves on frame change (scrub, arrow, playback)."""
    global _pending_muted_fcs
    for fc in _pending_muted_fcs:
        try:
            fc.mute = False
        except (ReferenceError, AttributeError):
            pass  # fcurve was deleted or invalidated
    _pending_muted_fcs.clear()


def _ensure_unmute_handler():
    """Register the frame_change_pre handler if not already registered."""
    if _on_frame_change_unmute not in bpy.app.handlers.frame_change_pre:
        bpy.app.handlers.frame_change_pre.append(_on_frame_change_unmute)


def unmute_pending_toggle_fcurves():
    """Public: unmute fcurves kept muted by IK/FK toggle.

    Called by smart_keyframe after inserting keyframes, so the new keyframes
    become the source of truth and animation evaluation produces correct values.
    """
    _on_frame_change_unmute(None)


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

        # Auto-repair: ensure FK_sync constraints exist (repairs old rigs)
        if chain_item.ik_enabled:
            ensure_fk_sync(armature, self.chain_id)

        # Auto-upgrade: migrate old rigs to custom-property + driver system.
        # Upgrade ALL chains at once so the user doesn't have to toggle each one.
        if chain_item.ik_enabled and not _has_ik_switch(armature, self.chain_id):
            for ch in sd.chains:
                if ch.ik_enabled and not _has_ik_switch(armature, ch.chain_id):
                    ensure_fk_sync(armature, ch.chain_id)
                    upgrade_ik_switch(armature, ch.chain_id)
        elif chain_item.ik_enabled:
            # Property+drivers exist but current action may have old fcurves.
            # Migrate all chains in the current action.
            for ch in sd.chains:
                if ch.ik_enabled:
                    migrate_action_ik_switch(armature, ch.chain_id)

        # Temporarily disable IK limits during snap so the solver can
        # reproduce the FK pose without being blocked by joint limits.
        # Save per-bone states so user customizations are preserved.
        saved_limit_states = {}
        if chain_item.ik_limits and use_ik:
            chain_bones_list = [b for b in sd.bones if b.chain_id == self.chain_id and not b.skip]
            for bone_item in chain_bones_list:
                mch_name = f"{WRAP_MCH_PREFIX}{self.chain_id}_{bone_item.role}"
                mch_pb = armature.pose.bones.get(mch_name)
                if mch_pb:
                    saved_limit_states[mch_name] = (
                        mch_pb.use_ik_limit_x, mch_pb.use_ik_limit_y, mch_pb.use_ik_limit_z,
                    )
                    mch_pb.use_ik_limit_x = False
                    mch_pb.use_ik_limit_y = False
                    mch_pb.use_ik_limit_z = False

        # --- Mute ALL relevant fcurves BEFORE snap ---
        # Mute bone fcurves so snap functions' internal view_layer.update()
        # calls don't overwrite snapped/edited transforms with keyframed
        # values.  Also mute the ik_switch fcurve so the runtime property
        # value persists through animation evaluation.
        # NO automatic keyframing — the user keyframes when ready.
        # If they change frame without keyframing, edits are lost (same as
        # normal Blender bone editing).
        from ...animation.smart_keyframe import (
            _get_chain_fk_pbones,
            _get_chain_ik_pbones,
            _iter_fcurves,
        )
        fk_pbones = _get_chain_fk_pbones(armature, sd, self.chain_id)
        ik_pbones = (_get_chain_ik_pbones(armature, self.chain_id)
                     if chain_item.ik_snap else [])
        # Always mute both FK and IK bones — FK edits must persist when
        # switching to IK, and FK snap must persist when switching to FK.
        muted_fcs = _mute_bone_fcurves(armature, fk_pbones + ik_pbones)

        # Mute the ik_switch fcurve so the runtime property isn't overridden
        prop_name = _ik_switch_prop_name(self.chain_id)
        data_path = f'["{prop_name}"]'
        action = armature.animation_data and armature.animation_data.action
        if action:
            for fc in _iter_fcurves(action):
                if fc.data_path == data_path and not fc.mute:
                    fc.mute = True
                    muted_fcs.append(fc)
                    break

        # Save MCH target matrices before snap (for post-toggle FK correction).
        fk_snap_targets = {}
        if not use_ik and chain_item.ik_snap:
            for bone_item in (b for b in sd.bones
                              if b.chain_id == self.chain_id and not b.skip):
                mch_name = f"{WRAP_MCH_PREFIX}{self.chain_id}_{bone_item.role}"
                ctrl_name = f"{WRAP_CTRL_PREFIX}{self.chain_id}_FK_{bone_item.role}"
                mch_pb = armature.pose.bones.get(mch_name)
                ctrl_pb = armature.pose.bones.get(ctrl_name)
                if mch_pb and ctrl_pb:
                    fk_snap_targets[ctrl_name] = mch_pb.matrix.copy()

        # Snap controls BEFORE switching so the pose is preserved.
        if chain_item.ik_type == 'LOOKAT':
            if use_ik:
                if not fk_was_modified(armature, self.chain_id):
                    restore_lookat_state(armature, self.chain_id)
                else:
                    snap_lookat_to_fk(armature, self.chain_id)
            else:
                save_lookat_state(armature, self.chain_id)
                snap_fk_to_ik(armature, self.chain_id)
                save_fk_snapshot(armature, self.chain_id)
        elif chain_item.ik_type == 'SPLINE':
            if use_ik:
                snap_spline_to_fk(armature, self.chain_id)
            else:
                snap_fk_to_ik(armature, self.chain_id)
        elif chain_item.ik_snap:
            if use_ik:
                if not fk_was_modified(armature, self.chain_id):
                    restore_ik_state(armature, self.chain_id)
                else:
                    snap_ik_to_fk(armature, self.chain_id)
            else:
                save_ik_state(armature, self.chain_id)
                snap_fk_to_ik(armature, self.chain_id)
                save_fk_snapshot(armature, self.chain_id)

        # --- Set the custom property (runtime only, no keyframe) ---
        # Drivers read this value and set correct constraint influences.
        # The muted ik_switch fcurve prevents animation from overriding it.
        armature[prop_name] = 1.0 if use_ik else 0.0

        # Restore per-bone limit states (preserves user customizations)
        if saved_limit_states:
            bpy.context.view_layer.update()
            for mch_name, (lx, ly, lz) in saved_limit_states.items():
                mch_pb = armature.pose.bones.get(mch_name)
                if mch_pb:
                    mch_pb.use_ik_limit_x = lx
                    mch_pb.use_ik_limit_y = ly
                    mch_pb.use_ik_limit_z = lz

        # Tag armature dirty so depsgraph re-evaluates bone transforms
        # (Python property changes don't auto-tag like interactive edits do)
        armature.update_tag()
        # Depsgraph update — all fcurves muted, so:
        # - Drivers read ik_switch runtime value → correct constraint influences
        # - Bone transforms stay at snapped/edited values (muted)
        # - Constraints evaluate with correct influences + snapped bones
        bpy.context.view_layer.update()

        # --- Newton correction for IK target (fcurves still muted) ---
        chain_bones = [b for b in sd.bones if b.chain_id == self.chain_id and not b.skip]
        if use_ik and chain_item.ik_snap and chain_item.ik_type != 'LOOKAT':
            ik_mch = None
            for bone_item in chain_bones:
                mch_name = f"{WRAP_MCH_PREFIX}{self.chain_id}_{bone_item.role}"
                mch_pb = armature.pose.bones.get(mch_name)
                if mch_pb:
                    for c in mch_pb.constraints:
                        if c.type == 'IK' and c.name.startswith(
                                WRAP_CONSTRAINT_PREFIX):
                            ik_mch = mch_pb
                            break
                if ik_mch:
                    break

            ik_target_name = f"{WRAP_CTRL_PREFIX}{self.chain_id}_IK_target"
            ik_target_pb = armature.pose.bones.get(ik_target_name)

            if ik_mch and ik_target_pb:
                _IK_POS_TOL_SQ = 1e-16
                for _ in range(4):
                    desired = ik_target_pb.head.copy()
                    actual = ik_mch.tail.copy()
                    err = desired - actual
                    if err.length_squared < _IK_POS_TOL_SQ:
                        break
                    mat = ik_target_pb.matrix.copy()
                    mat.translation += err
                    ik_target_pb.matrix = mat
                    bpy.context.view_layer.update()

        # --- Post-toggle FK precision correction (fcurves still muted) ---
        # FK_sync is now off, so ctrl_pb.matrix reflects the true FK result.
        # Compare against saved IK-posed MCH matrices and correct drift.
        if fk_snap_targets:
            _POS_TOL_SQ = 1e-16
            _ROT_TOL = 1e-12
            for _ in range(4):
                any_corrected = False
                for ctrl_name, target_matrix in fk_snap_targets.items():
                    ctrl_pb = armature.pose.bones.get(ctrl_name)
                    if not ctrl_pb:
                        continue
                    actual = ctrl_pb.matrix
                    pos_err = target_matrix.translation - actual.translation
                    tgt_q = target_matrix.to_quaternion()
                    act_q = actual.to_quaternion()
                    rot_dot = abs(tgt_q.dot(act_q))
                    if (pos_err.length_squared < _POS_TOL_SQ
                            and rot_dot > (1.0 - _ROT_TOL)):
                        continue
                    delta = target_matrix @ actual.inverted()
                    ctrl_pb.matrix = delta @ target_matrix
                    bpy.context.view_layer.update()
                    any_corrected = True
                if not any_corrected:
                    break

        # --- Keep fcurves muted until frame change or smart keyframe ---
        # This lets the snap/edit persist across viewport redraws on the
        # current frame.  The frame_change_pre handler or smart keyframe
        # will unmute when the user moves on or commits the pose.
        _pending_muted_fcs.extend(muted_fcs)
        _ensure_unmute_handler()

        # Update runtime state
        chain_item.ik_active = use_ik

        # Show/hide per-chain IK collection based on mode
        ik_coll = armature.data.collections.get(f"IK_{self.chain_id}")
        if ik_coll:
            ik_coll.is_visible = use_ik

        if chain_item.ik_type == 'LOOKAT':
            mode_name = "LookAt" if use_ik else "FK"
        else:
            mode_name = "IK" if use_ik else "FK"
        self.report({'INFO'}, f"{self.chain_id}: switched to {mode_name}")
        return {'FINISHED'}


class BT_OT_ToggleIKLimits(bpy.types.Operator):
    bl_idname = "bt.toggle_ik_limits"
    bl_label = "Toggle IK Limits"
    bl_description = "Enable or disable IK rotation limits for a chain"
    bl_options = {'REGISTER', 'UNDO'}

    chain_id: bpy.props.StringProperty(name="Chain ID")

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'ARMATURE' and obj.bt_scan.has_wrap_rig

    def execute(self, context):
        armature = context.active_object
        sd = armature.bt_scan

        chain_item = None
        for ch in sd.chains:
            if ch.chain_id == self.chain_id:
                chain_item = ch
                break

        if not chain_item:
            self.report({'WARNING'}, f"Chain '{self.chain_id}' not found")
            return {'CANCELLED'}

        new_state = not chain_item.ik_limits
        toggle_ik_limits(armature, self.chain_id, new_state)
        chain_item.ik_limits = new_state

        state = "enabled" if new_state else "disabled"
        self.report({'INFO'}, f"{self.chain_id}: IK limits {state}")
        return {'FINISHED'}


def _find_mch_for_selected(context):
    """Map the active pose bone to its MCH counterpart. Returns (mch_pbone, role) or (None, None)."""
    obj = context.active_object
    if not obj or obj.type != 'ARMATURE' or not obj.bt_scan.has_wrap_rig:
        return None, None
    pb = context.active_pose_bone
    if not pb:
        return None, None

    sd = obj.bt_scan
    name = pb.name

    # Direct MCH bone selected
    if name.startswith(WRAP_MCH_PREFIX):
        return pb, name[len(WRAP_MCH_PREFIX):]

    # CTRL-Wrap bone — extract chain_id + role suffix, map to MCH
    if name.startswith(WRAP_CTRL_PREFIX):
        suffix = name[len(WRAP_CTRL_PREFIX):]
        # Strip FK_ or IK_ or Spline_ prefix from suffix to get chain_role
        for tag in ("FK_", "IK_", "Spline_"):
            if tag in suffix:
                idx = suffix.index(tag)
                chain_part = suffix[:idx].rstrip("_")
                role_part = suffix[idx + len(tag):]
                mch_name = f"{WRAP_MCH_PREFIX}{chain_part}_{role_part}"
                mch_pb = obj.pose.bones.get(mch_name)
                if mch_pb:
                    return mch_pb, f"{chain_part}_{role_part}"
        return None, None

    # DEF (original) bone — find MCH via scan data
    for bi in sd.bones:
        if bi.bone_name == name and not bi.skip:
            mch_name = f"{WRAP_MCH_PREFIX}{bi.chain_id}_{bi.role}"
            mch_pb = obj.pose.bones.get(mch_name)
            if mch_pb:
                return mch_pb, f"{bi.chain_id}_{bi.role}"
    return None, None


class BT_OT_EditBoneIKLimits(bpy.types.Operator):
    bl_idname = "bt.edit_bone_ik_limits"
    bl_label = "Edit IK Limits"
    bl_description = "Adjust IK rotation limits for the selected bone"
    bl_options = {'REGISTER', 'UNDO'}

    # Per-axis limits (stored in radians, displayed as degrees via ANGLE subtype)
    min_x: bpy.props.FloatProperty(name="Min X", default=0.0, min=-math.pi, max=0.0, subtype='ANGLE')
    max_x: bpy.props.FloatProperty(name="Max X", default=0.0, min=0.0, max=math.pi, subtype='ANGLE')
    min_y: bpy.props.FloatProperty(name="Min Y", default=0.0, min=-math.pi, max=0.0, subtype='ANGLE')
    max_y: bpy.props.FloatProperty(name="Max Y", default=0.0, min=0.0, max=math.pi, subtype='ANGLE')
    min_z: bpy.props.FloatProperty(name="Min Z", default=0.0, min=-math.pi, max=0.0, subtype='ANGLE')
    max_z: bpy.props.FloatProperty(name="Max Z", default=0.0, min=0.0, max=math.pi, subtype='ANGLE')
    stiffness_x: bpy.props.FloatProperty(name="Stiffness X", default=0.0, min=0.0, max=0.999)
    stiffness_y: bpy.props.FloatProperty(name="Stiffness Y", default=0.0, min=0.0, max=0.999)
    stiffness_z: bpy.props.FloatProperty(name="Stiffness Z", default=0.0, min=0.0, max=0.999)
    use_limit_x: bpy.props.BoolProperty(name="Limit X", default=False)
    use_limit_y: bpy.props.BoolProperty(name="Limit Y", default=False)
    use_limit_z: bpy.props.BoolProperty(name="Limit Z", default=False)

    mch_name: bpy.props.StringProperty(name="MCH Bone", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj and obj.type == 'ARMATURE' and obj.bt_scan.has_wrap_rig
                and context.active_pose_bone is not None)

    def invoke(self, context, event):
        mch_pb, label = _find_mch_for_selected(context)
        if not mch_pb:
            self.report({'WARNING'}, "No MCH bone found for selected bone")
            return {'CANCELLED'}

        self.mch_name = mch_pb.name
        # Read current values from MCH bone
        self.min_x = mch_pb.ik_min_x
        self.max_x = mch_pb.ik_max_x
        self.min_y = mch_pb.ik_min_y
        self.max_y = mch_pb.ik_max_y
        self.min_z = mch_pb.ik_min_z
        self.max_z = mch_pb.ik_max_z
        self.stiffness_x = mch_pb.ik_stiffness_x
        self.stiffness_y = mch_pb.ik_stiffness_y
        self.stiffness_z = mch_pb.ik_stiffness_z
        self.use_limit_x = mch_pb.use_ik_limit_x
        self.use_limit_y = mch_pb.use_ik_limit_y
        self.use_limit_z = mch_pb.use_ik_limit_z

        return context.window_manager.invoke_props_popup(self, event)

    def draw(self, context):
        layout = self.layout
        layout.label(text=self.mch_name, icon='BONE_DATA')

        for axis in ("x", "y", "z"):
            box = layout.box()
            row = box.row()
            row.prop(self, f"use_limit_{axis}")
            row.label(text=f"{axis.upper()} Axis")
            if getattr(self, f"use_limit_{axis}"):
                row = box.row(align=True)
                row.prop(self, f"min_{axis}", text="Min")
                row.prop(self, f"max_{axis}", text="Max")
                box.prop(self, f"stiffness_{axis}", slider=True)

    def execute(self, context):
        armature = context.active_object
        mch_pb = armature.pose.bones.get(self.mch_name) if self.mch_name else None
        if not mch_pb:
            mch_pb, _ = _find_mch_for_selected(context)
        if not mch_pb:
            self.report({'WARNING'}, "No MCH bone found for selected bone")
            return {'CANCELLED'}

        mch_pb.ik_min_x = self.min_x
        mch_pb.ik_max_x = self.max_x
        mch_pb.ik_min_y = self.min_y
        mch_pb.ik_max_y = self.max_y
        mch_pb.ik_min_z = self.min_z
        mch_pb.ik_max_z = self.max_z
        mch_pb.ik_stiffness_x = self.stiffness_x
        mch_pb.ik_stiffness_y = self.stiffness_y
        mch_pb.ik_stiffness_z = self.stiffness_z
        mch_pb.use_ik_limit_x = self.use_limit_x
        mch_pb.use_ik_limit_y = self.use_limit_y
        mch_pb.use_ik_limit_z = self.use_limit_z

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


class BT_OT_RefreshWrapRig(bpy.types.Operator):
    bl_idname = "bt.refresh_wrap_rig"
    bl_label = "Refresh Wrap Rig"
    bl_description = (
        "Re-scan skeleton and re-apply wrap rig, preserving user settings"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj and obj.type == 'ARMATURE'
                and obj.bt_scan.is_scanned and obj.bt_scan.has_wrap_rig)

    def execute(self, context):
        armature = context.active_object
        sd = armature.bt_scan

        # 1. Snapshot user-configured chain settings keyed by chain_id
        saved_chains = {}
        for ch in sd.chains:
            saved_chains[ch.chain_id] = {
                "module_type": ch.module_type,
                "side": ch.side,
                "ik_enabled": ch.ik_enabled,
                "fk_enabled": ch.fk_enabled,
                "ik_type": ch.ik_type,
                "ik_snap": ch.ik_snap,
                "ik_limits": ch.ik_limits,
            }

        # Snapshot per-bone overrides keyed by bone_name
        saved_bones = {}
        for b in sd.bones:
            saved_bones[b.bone_name] = {
                "role": b.role,
                "module_type": b.module_type,
                "skip": b.skip,
            }

        # Save forward axis
        saved_forward = sd.forward_axis

        # 2. Clear wrap rig
        if sd.floor_enabled:
            remove_floor_contact(armature)
            sd.floor_enabled = False
        disassemble_wrap_rig(armature)
        sd.has_wrap_rig = False

        # 3. Clear scan data
        sd.bones.clear()
        sd.chains.clear()
        sd.unmapped_bones = ""
        sd.skeleton_type = ""
        sd.confidence = 0.0
        sd.is_scanned = False

        # 4. Re-scan
        scan_data = scan_skeleton(armature)
        _scan_data_to_props(armature, scan_data)

        # 5. Restore saved settings onto matching chains
        sd.forward_axis = saved_forward
        for ch in sd.chains:
            if ch.chain_id in saved_chains:
                prev = saved_chains[ch.chain_id]
                ch.module_type = prev["module_type"]
                ch.side = prev["side"]
                ch.ik_enabled = prev["ik_enabled"]
                ch.fk_enabled = prev["fk_enabled"]
                ch.ik_type = prev["ik_type"]
                ch.ik_snap = prev["ik_snap"]
                ch.ik_limits = prev["ik_limits"]

        # Restore per-bone overrides
        for b in sd.bones:
            if b.bone_name in saved_bones:
                prev = saved_bones[b.bone_name]
                b.role = prev["role"]
                b.module_type = prev["module_type"]
                b.skip = prev["skip"]

        # 6. Apply wrap rig (reuse ApplyWrapRig logic)
        scan_data = _props_to_scan_data(armature)
        for chain_item in sd.chains:
            cid = chain_item.chain_id
            if cid in scan_data["chains"]:
                scan_data["chains"][cid]["module_type"] = chain_item.module_type
                scan_data["chains"][cid]["ik_enabled"] = chain_item.ik_enabled
                scan_data["chains"][cid]["fk_enabled"] = chain_item.fk_enabled
                scan_data["chains"][cid]["ik_type"] = chain_item.ik_type
                scan_data["chains"][cid]["ik_limits"] = chain_item.ik_limits
                for bone_name in scan_data["chains"][cid]["bones"]:
                    if bone_name in scan_data["bones"]:
                        scan_data["bones"][bone_name]["module_type"] = chain_item.module_type

        created = assemble_wrap_rig(armature, scan_data)
        sd.has_wrap_rig = True

        from ..shapes import assign_shapes_for_wrap_rig
        assign_shapes_for_wrap_rig(armature)

        for chain_item in sd.chains:
            chain_item.ik_active = False

        bpy.ops.object.mode_set(mode='POSE')
        try:
            from .ik_overlay import _active as ik_active
            if not ik_active:
                bpy.ops.bt.ik_overlay('INVOKE_DEFAULT')
        except Exception:
            pass
        try:
            from ..center_of_mass import _active as com_active
            if not com_active:
                bpy.ops.bt.toggle_com()
        except Exception:
            pass

        new_chains = [ch.chain_id for ch in sd.chains
                      if ch.chain_id not in saved_chains]
        msg = f"Refreshed: {len(created)} control bones"
        if new_chains:
            msg += f" (new chains: {', '.join(new_chains)})"
        self.report({'INFO'}, msg)
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
            )
            if "error" in result:
                self.report({'WARNING'}, result["error"])
                return {'CANCELLED'}
            sd.floor_enabled = True
            self.report({'INFO'},
                        f"Floor contact: {result['floor_constraints']} legs")

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
    BT_OT_ToggleIKLimits,
    BT_OT_EditBoneIKLimits,
    BT_OT_ClearWrapRig,
    BT_OT_ClearScanData,
    BT_OT_RefreshWrapRig,
    BT_OT_BatchSkipSelected,
    BT_OT_BatchSkipByPattern,
    BT_OT_BatchUnskipAll,
    BT_OT_BakeToDef,
    BT_OT_ToggleFloorContact,
    BT_OT_UpdateFloorLevel,
)


def _draw_pose_context_menu(self, context):
    """Append 'Edit IK Limits' to the pose mode right-click menu."""
    obj = context.active_object
    if (obj and obj.type == 'ARMATURE' and obj.bt_scan.has_wrap_rig
            and context.active_pose_bone):
        self.layout.separator()
        self.layout.operator_context = 'INVOKE_DEFAULT'
        self.layout.operator("bt.edit_bone_ik_limits", icon='CON_ROTLIMIT')


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_pose_context_menu.append(_draw_pose_context_menu)


def unregister():
    # Clean up persistent mute handler
    if _on_frame_change_unmute in bpy.app.handlers.frame_change_pre:
        bpy.app.handlers.frame_change_pre.remove(_on_frame_change_unmute)
    # Unmute any lingering fcurves
    _on_frame_change_unmute(None)

    bpy.types.VIEW3D_MT_pose_context_menu.remove(_draw_pose_context_menu)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
