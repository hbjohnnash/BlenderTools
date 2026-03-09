"""Smart keyframe insertion for wrap rigs.

Intercepts the "I" key in pose mode. Ensures IK bones are never keyed —
if an IK bone is selected and its chain is in IK mode, FK bones are
snapped to match the IK pose and keyed instead.
"""

import bpy

from ..core.constants import WRAP_CTRL_PREFIX

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _key_rotation(pbone, frame):
    """Insert rotation keyframe respecting the bone's rotation mode."""
    if pbone.rotation_mode == 'QUATERNION':
        pbone.keyframe_insert('rotation_quaternion', frame=frame)
    elif pbone.rotation_mode == 'AXIS_ANGLE':
        pbone.keyframe_insert('rotation_axis_angle', frame=frame)
    else:
        pbone.keyframe_insert('rotation_euler', frame=frame)


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------

class BT_OT_SmartKeyframe(bpy.types.Operator):
    """Insert keyframes intelligently — FK rotation for FK bones,
    snap-and-key for IK bones, location+rotation for COG/root."""
    bl_idname = "bt.smart_keyframe"
    bl_label = "Smart Keyframe"
    bl_description = "Key FK bones; IK bones snap to FK first"
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

        from ..rigging.scanner.wrap_assembly import snap_fk_to_ik

        fk_to_key = []       # bones that get rotation keyed
        loc_to_key = []      # bones that also get location keyed
        snapped_chains = []  # chains where FK was snapped from IK

        for pbone in selected:
            name = pbone.name

            if not name.startswith(WRAP_CTRL_PREFIX):
                # Non-wrap bone (root, original skeleton, etc.)
                fk_to_key.append(pbone)
                if not all(pbone.lock_location):
                    loc_to_key.append(pbone)
                continue

            # --- Wrap CTRL bone ---
            is_ik_target = name.endswith("_IK_target")
            is_ik_pole = name.endswith("_IK_pole")
            is_spline = "_Spline_" in name

            if is_ik_target or is_ik_pole or is_spline:
                # IK bone — snap FK to match, key FK instead
                chain_id = _find_chain_for_ctrl(sd, name)
                if not chain_id:
                    continue

                # Check if chain is actually in IK mode
                chain_item = None
                for c in sd.chains:
                    if c.chain_id == chain_id:
                        chain_item = c
                        break

                if not chain_item or not chain_item.ik_active:
                    self.report({'INFO'},
                                f"Chain '{chain_id}' is in FK mode — "
                                f"IK bone '{name}' skipped")
                    continue

                if chain_id not in snapped_chains:
                    snap_fk_to_ik(armature, chain_id)
                    snapped_chains.append(chain_id)
                    chain_fk = _get_chain_fk_pbones(armature, sd, chain_id)
                    for fk_pb in chain_fk:
                        if fk_pb not in fk_to_key:
                            fk_to_key.append(fk_pb)
                            if not all(fk_pb.lock_location):
                                loc_to_key.append(fk_pb)
            else:
                # FK bone
                fk_to_key.append(pbone)
                if not all(pbone.lock_location):
                    loc_to_key.append(pbone)

        # Deduplicate (preserving order)
        seen = set()
        fk_dedup = []
        for pb in fk_to_key:
            if pb.name not in seen:
                seen.add(pb.name)
                fk_dedup.append(pb)
        fk_to_key = fk_dedup

        loc_seen = set()
        loc_dedup = []
        for pb in loc_to_key:
            if pb.name not in loc_seen:
                loc_seen.add(pb.name)
                loc_dedup.append(pb)
        loc_to_key = loc_dedup

        # Insert keyframes
        keyed = 0
        for pbone in fk_to_key:
            _key_rotation(pbone, frame)
            keyed += 1

        for pbone in loc_to_key:
            pbone.keyframe_insert('location', frame=frame)

        # Report
        msg = f"Keyed {keyed} bone(s)"
        if snapped_chains:
            msg += f" (snapped FK from IK: {', '.join(snapped_chains)})"
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
