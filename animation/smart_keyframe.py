"""Smart keyframe insertion for wrap rigs.

Intercepts the "I" key in pose mode.  Keys the ACTIVE system's controls
(IK targets when in IK mode, FK bones when in FK mode) plus any
independently-controlled bones (e.g. toe FK in IK mode).  The chain's
ik_switch custom property is keyed with CONSTANT interpolation so IK/FK
switches are instantaneous during playback — no blending drift.

Snapping between IK and FK is NOT done here — it belongs in the toggle
operator, which runs when the user explicitly switches modes.
"""

import bpy

from ..core.constants import (
    WRAP_CONSTRAINT_PREFIX,
    WRAP_CTRL_PREFIX,
    WRAP_MCH_PREFIX,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assign_ik_switch_group(action, fc):
    """Best-effort fcurve grouping. No-op if the API doesn't support it."""
    try:
        if hasattr(action, 'groups') and hasattr(fc, 'group'):
            group = action.groups.get("IK/FK Switches")
            if not group:
                group = action.groups.new(name="IK/FK Switches")
            fc.group = group
    except (AttributeError, TypeError, RuntimeError):
        pass  # Blender 5.0+ layered actions may not support legacy groups


def _find_chain_for_ctrl(sd, ctrl_name):
    """Return the chain_id a CTRL bone belongs to, or None."""
    suffix = ctrl_name[len(WRAP_CTRL_PREFIX):]
    # Try longest chain_id first (handles IDs with underscores like arm_L)
    for chain in sorted(sd.chains, key=lambda c: len(c.chain_id), reverse=True):
        cid = chain.chain_id
        if suffix.startswith(cid + "_"):
            return cid
    return None


def _get_chain_fk_pbones(armature_obj, sd, chain_id):
    """Return pose bones for all FK CTRLs in a chain."""
    fk_bones = []
    for bone_item in sd.bones:
        if bone_item.chain_id != chain_id or bone_item.skip:
            continue
        ctrl_name = f"{WRAP_CTRL_PREFIX}{chain_id}_FK_{bone_item.role}"
        pb = armature_obj.pose.bones.get(ctrl_name)
        if pb:
            fk_bones.append(pb)
    return fk_bones


def _get_independent_fk_pbones(armature_obj, sd, chain_id):
    """Return FK CTRL bones that have no IK alternative (e.g. toe).

    These bones are always FK-driven regardless of the chain's IK/FK mode,
    so they must be keyed even when the chain is in IK mode.
    """
    fk_bones = []
    for bone_item in sd.bones:
        if bone_item.chain_id != chain_id or bone_item.skip:
            continue
        mch_name = f"{WRAP_MCH_PREFIX}{chain_id}_{bone_item.role}"
        mch_pb = armature_obj.pose.bones.get(mch_name)
        if not mch_pb:
            continue
        has_ik = any(
            c.type in ('IK', 'SPLINE_IK', 'COPY_ROTATION')
            and c.name.startswith(WRAP_CONSTRAINT_PREFIX)
            for c in mch_pb.constraints
        )
        if not has_ik:
            ctrl_name = f"{WRAP_CTRL_PREFIX}{chain_id}_FK_{bone_item.role}"
            pb = armature_obj.pose.bones.get(ctrl_name)
            if pb:
                fk_bones.append(pb)
    return fk_bones


def _get_chain_ik_pbones(armature_obj, chain_id):
    """Return IK control pose bones (target and/or pole) for a chain."""
    ik_bones = []
    for suffix in ("_IK_target", "_IK_pole"):
        name = f"{WRAP_CTRL_PREFIX}{chain_id}{suffix}"
        pb = armature_obj.pose.bones.get(name)
        if pb:
            ik_bones.append(pb)
    return ik_bones


def _iter_fcurves(action):
    """Yield all FCurves from an Action, supporting both legacy and Blender 5.0+ API.

    Blender 5.0 moved fcurves into action.layers[].strips[].channelbags[].fcurves.
    Legacy Blender (< 5.0) uses action.fcurves directly.
    """
    if hasattr(action, 'fcurves'):
        yield from action.fcurves
    else:
        for layer in getattr(action, 'layers', ()):
            for strip in getattr(layer, 'strips', ()):
                for channelbag in getattr(strip, 'channelbags', ()):
                    yield from getattr(channelbag, 'fcurves', ())


def _key_rotation(pbone, frame):
    """Insert rotation keyframe respecting the bone's rotation mode."""
    if pbone.rotation_mode == 'QUATERNION':
        pbone.keyframe_insert('rotation_quaternion', frame=frame)
    elif pbone.rotation_mode == 'AXIS_ANGLE':
        pbone.keyframe_insert('rotation_axis_angle', frame=frame)
    else:
        pbone.keyframe_insert('rotation_euler', frame=frame)


def _key_bones(pbones, frame):
    """Key rotation (+ location where unlocked) on pose bones."""
    for pb in pbones:
        _key_rotation(pb, frame)
        if not all(pb.lock_location):
            pb.keyframe_insert('location', frame=frame)


def _key_ik_controls(ik_pbones, frame):
    """Key location + rotation on IK target/pole pose bones."""
    for pb in ik_pbones:
        pb.keyframe_insert('location', frame=frame)
        _key_rotation(pb, frame)


def _key_ik_switch(armature_obj, chain_id, use_ik, frame):
    """Key the ik_switch custom property with CONSTANT interpolation.

    This is the single keyframe that controls all constraint influences
    via drivers — replacing the old per-constraint keyframing approach.
    """
    from ..rigging.scanner.wrap_assembly import _ik_switch_prop_name
    prop_name = _ik_switch_prop_name(chain_id)

    # Ensure the property exists (safety for old rigs)
    if prop_name not in armature_obj:
        return

    value = 1.0 if use_ik else 0.0
    armature_obj[prop_name] = value
    data_path = f'["{prop_name}"]'
    armature_obj.keyframe_insert(data_path, frame=frame)

    # Set CONSTANT interpolation and group the fcurve
    action = armature_obj.animation_data and armature_obj.animation_data.action
    if action:
        for fc in _iter_fcurves(action):
            if fc.data_path == data_path:
                for kp in fc.keyframe_points:
                    kp.interpolation = 'CONSTANT'
                _assign_ik_switch_group(action, fc)
                break


def _update_existing_keyframe(armature_obj, prop_name, frame, value):
    """Ensure the toggle persists through animation evaluation.

    If an animation curve exists for this property, the animation system
    will override the runtime value on the next depsgraph update.  In that
    case we MUST insert/update a keyframe so the toggle sticks.

    If there is no animation curve at all, the runtime value is sufficient
    and no keyframe is created — the user keyframes when they choose.
    """
    action = (armature_obj.animation_data
              and armature_obj.animation_data.action)
    if not action:
        return

    data_path = f'["{prop_name}"]'
    for fc in _iter_fcurves(action):
        if fc.data_path == data_path:
            # An animation curve exists — we must keyframe to override it.
            # Check if there's already a keyframe at this frame.
            for kp in fc.keyframe_points:
                if abs(kp.co[0] - frame) < 0.5:
                    kp.co[1] = value
                    kp.interpolation = 'CONSTANT'
                    fc.update()
                    return
            # No keyframe at this frame — insert one so the toggle
            # isn't immediately undone by animation evaluation.
            armature_obj[prop_name] = value
            armature_obj.keyframe_insert(data_path, frame=frame)
            # Set CONSTANT interpolation on ALL keyframes for this curve
            # (new keyframe may have inherited a different default).
            for kp in fc.keyframe_points:
                kp.interpolation = 'CONSTANT'
            fc.update()
            return
    # No animation curve — runtime value is sufficient, no keyframe needed.


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------

class BT_OT_SmartKeyframe(bpy.types.Operator):
    """Insert keyframes for the active control system.

    IK mode: keys IK targets/poles + independently-controlled FK (e.g. toe).
    FK mode: keys all FK controls.
    The ik_switch custom property is keyed with CONSTANT interpolation so
    mode switches are instant during playback."""
    bl_idname = "bt.smart_keyframe"
    bl_label = "Smart Keyframe"
    bl_description = "Key active control system (IK or FK) with instant mode switching"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.active_object
                and context.active_object.type == 'ARMATURE'
                and context.mode == 'POSE'
                and context.selected_pose_bones)

    def execute(self, context):
        armature = context.active_object
        sd = getattr(armature, 'bt_scan', None)
        frame = context.scene.frame_current

        selected = list(context.selected_pose_bones)
        if not selected:
            self.report({'WARNING'}, "No bones selected")
            return {'CANCELLED'}

        # If no wrap rig, fall through to default keyframe behavior
        if not sd or not sd.has_wrap_rig:
            return self._key_plain(selected, frame)

        # Ensure animation data exists
        if not armature.animation_data:
            armature.animation_data_create()
        if not armature.animation_data.action:
            armature.animation_data.action = bpy.data.actions.new(
                name=f"{armature.name}_Action")

        # Track what we've processed so chains aren't handled twice
        processed_chains = set()
        plain_bones = []  # non-wrap bones keyed normally

        for pbone in selected:
            name = pbone.name

            if not name.startswith(WRAP_CTRL_PREFIX):
                # Non-wrap bone (root, COG, original skeleton, etc.)
                plain_bones.append(pbone)
                continue

            # --- Wrap CTRL bone ---
            chain_id = _find_chain_for_ctrl(sd, name)
            if not chain_id or chain_id in processed_chains:
                continue

            # Find chain config
            chain_item = None
            for c in sd.chains:
                if c.chain_id == chain_id:
                    chain_item = c
                    break
            if not chain_item:
                continue

            processed_chains.add(chain_id)
            use_ik = chain_item.ik_active

            if use_ik:
                # IK mode: key IK controls + independently-controlled FK
                ik_pbones = _get_chain_ik_pbones(armature, chain_id)
                _key_ik_controls(ik_pbones, frame)
                indie_fk = _get_independent_fk_pbones(armature, sd, chain_id)
                if indie_fk:
                    _key_bones(indie_fk, frame)
            else:
                # FK mode: key all FK controls
                fk_pbones = _get_chain_fk_pbones(armature, sd, chain_id)
                _key_bones(fk_pbones, frame)

            # Key the ik_switch custom property with CONSTANT interpolation
            _key_ik_switch(armature, chain_id, use_ik, frame)

        # Key non-wrap bones normally
        for pbone in plain_bones:
            _key_rotation(pbone, frame)
            if not all(pbone.lock_location):
                pbone.keyframe_insert('location', frame=frame)

        # Unmute any fcurves kept muted by the IK/FK toggle.
        # Now that keyframes are inserted with the snapped/edited values,
        # animation evaluation will produce the same values — safe to unmute.
        from ..rigging.scanner.operators import unmute_pending_toggle_fcurves
        unmute_pending_toggle_fcurves()

        # Report
        msg = f"Keyed {len(processed_chains)} chain(s)"
        if plain_bones:
            msg += f", {len(plain_bones)} other bone(s)"
        modes = []
        for cid in sorted(processed_chains):
            for c in sd.chains:
                if c.chain_id == cid:
                    modes.append(f"{cid}={'IK' if c.ik_active else 'FK'}")
                    break
        if modes:
            msg += f" [{', '.join(modes)}]"
        self.report({'INFO'}, msg)
        return {'FINISHED'}

    def _key_plain(self, selected, frame):
        """Fallback: key all selected bones without wrap rig logic."""
        for pbone in selected:
            _key_rotation(pbone, frame)
            if not all(pbone.lock_location):
                pbone.keyframe_insert('location', frame=frame)
        self.report({'INFO'}, f"Keyed {len(selected)} bone(s)")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Keymap
# ---------------------------------------------------------------------------

_addon_keymaps = []


def register():
    bpy.utils.register_class(BT_OT_SmartKeyframe)

    # Override "I" in pose mode to use smart keyframe
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name='Pose', space_type='EMPTY')
        kmi = km.keymap_items.new('bt.smart_keyframe', 'I', 'PRESS')
        _addon_keymaps.append((km, kmi))


def unregister():
    for km, kmi in _addon_keymaps:
        km.keymap_items.remove(kmi)
    _addon_keymaps.clear()

    bpy.utils.unregister_class(BT_OT_SmartKeyframe)
