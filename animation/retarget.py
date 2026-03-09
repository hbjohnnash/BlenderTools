"""Animation retargeting helpers.

Includes generic bone-name remapping **and** wrap-rig-aware utilities
that transfer FCurves between DEF bones and CTRL FK bones.
"""

import bpy

from ..core.constants import WRAP_CTRL_PREFIX, WRAP_MCH_PREFIX

# ── Generic mapping tables ──────────────────────────────────────

DEFAULT_MAPPINGS = {
    "mixamo_to_bt": {
        "mixamorig:Hips": "DEF-Spine_C_001",
        "mixamorig:Spine": "DEF-Spine_C_002",
        "mixamorig:Spine1": "DEF-Spine_C_003",
        "mixamorig:Spine2": "DEF-Spine_C_004",
        "mixamorig:Neck": "DEF-NeckHead_C_Neck_01",
        "mixamorig:Head": "DEF-NeckHead_C_Head",
        "mixamorig:LeftShoulder": "DEF-Arm_L_Clavicle",
        "mixamorig:LeftArm": "DEF-Arm_L_Upper",
        "mixamorig:LeftForeArm": "DEF-Arm_L_Lower",
        "mixamorig:LeftHand": "DEF-Arm_L_Hand",
        "mixamorig:RightShoulder": "DEF-Arm_R_Clavicle",
        "mixamorig:RightArm": "DEF-Arm_R_Upper",
        "mixamorig:RightForeArm": "DEF-Arm_R_Lower",
        "mixamorig:RightHand": "DEF-Arm_R_Hand",
        "mixamorig:LeftUpLeg": "DEF-Leg_L_Thigh",
        "mixamorig:LeftLeg": "DEF-Leg_L_Shin",
        "mixamorig:LeftFoot": "DEF-Leg_L_Foot",
        "mixamorig:LeftToeBase": "DEF-Leg_L_Toe",
        "mixamorig:RightUpLeg": "DEF-Leg_R_Thigh",
        "mixamorig:RightLeg": "DEF-Leg_R_Shin",
        "mixamorig:RightFoot": "DEF-Leg_R_Foot",
        "mixamorig:RightToeBase": "DEF-Leg_R_Toe",
    },
}


def get_mapping(mapping_name):
    """Get a bone name mapping by name."""
    return DEFAULT_MAPPINGS.get(mapping_name, {})


# ── Generic action retarget (copy with bone-name remapping) ────

def retarget_action(source_action, target_armature, mapping,
                    new_action_name=None):
    """Copy animation from *source_action* to *target_armature* with
    bone-name remapping.

    Returns the new action, or ``None`` on failure.
    """
    from bpy_extras.anim_utils import action_ensure_channelbag_for_slot

    new_name = new_action_name or f"{source_action.name}_retargeted"
    new_action = bpy.data.actions.new(name=new_name)

    if not target_armature.animation_data:
        target_armature.animation_data_create()

    slot = new_action.slots.new(name=target_armature.name, id_type='OBJECT')
    target_armature.animation_data.action = new_action
    target_armature.animation_data.action_slot = slot
    channelbag = action_ensure_channelbag_for_slot(new_action, slot)

    for src_layer in source_action.layers:
        for src_strip in src_layer.strips:
            for src_cb in src_strip.channelbags:
                for src_fc in src_cb.fcurves:
                    dp = src_fc.data_path
                    if 'pose.bones["' not in dp:
                        continue

                    start = dp.index('pose.bones["') + len('pose.bones["')
                    end = dp.index('"]', start)
                    src_bone = dp[start:end]

                    tgt_bone = mapping.get(src_bone)
                    if not tgt_bone:
                        continue

                    new_dp = dp[:start] + tgt_bone + dp[end:]
                    new_fc = channelbag.fcurves.new(
                        new_dp, index=src_fc.array_index,
                    )

                    new_fc.keyframe_points.add(len(src_fc.keyframe_points))
                    for i, kf in enumerate(src_fc.keyframe_points):
                        new_kf = new_fc.keyframe_points[i]
                        new_kf.co = kf.co
                        new_kf.interpolation = kf.interpolation
                        new_kf.handle_left = kf.handle_left
                        new_kf.handle_right = kf.handle_right

                    new_fc.update()

    return new_action


# ── Wrap-rig helpers ────────────────────────────────────────────

def has_wrap_rig(armature_obj):
    """Return True if the armature has a wrap rig applied."""
    for bone in armature_obj.pose.bones:
        if bone.name.startswith(WRAP_CTRL_PREFIX):
            return True
    return False


def build_def_to_fk_map(armature_obj):
    """Build ``{def_bone_name: ctrl_fk_bone_name}`` from *bt_scan* data.

    Returns an empty dict when the armature has no scan data or no
    wrap-rig CTRL bones.
    """
    scan_data = getattr(armature_obj, "bt_scan", None)
    if scan_data is None:
        return {}

    bones_col = getattr(scan_data, "bones", None)
    if not bones_col:
        return {}

    mapping = {}
    for bone_item in bones_col:
        if bone_item.skip:
            continue

        chain_id = bone_item.chain_id
        role = bone_item.role
        def_name = bone_item.bone_name
        ctrl_name = f"CTRL-Wrap_{chain_id}_FK_{role}"

        if armature_obj.pose.bones.get(ctrl_name):
            mapping[def_name] = ctrl_name

    return mapping


def get_deform_bone_names(armature_obj):
    """Return names of deform bones, excluding CTRL/MCH wrap bones.

    Falls back to all non-wrap bones when none are marked deform.
    """
    deform = []
    for bone in armature_obj.data.bones:
        if (bone.name.startswith(WRAP_CTRL_PREFIX)
                or bone.name.startswith(WRAP_MCH_PREFIX)):
            continue
        if bone.use_deform:
            deform.append(bone.name)

    if not deform:
        deform = [
            b.name for b in armature_obj.data.bones
            if not b.name.startswith(WRAP_CTRL_PREFIX)
            and not b.name.startswith(WRAP_MCH_PREFIX)
        ]
    return deform


# ── In-place action retarget (DEF → FK) ────────────────────────

def retarget_action_to_fk(armature_obj, action=None):
    """Retarget *action*'s FCurves from DEF bones to CTRL FK bones **in-place**.

    Modifies ``data_path`` on each matching FCurve and sets the target
    FK bone's rotation mode to match the keyed property.

    Returns the number of FCurves remapped.
    """
    if action is None:
        ad = armature_obj.animation_data
        if not ad or not ad.action:
            return 0
        action = ad.action

    mapping = build_def_to_fk_map(armature_obj)
    if not mapping:
        return 0

    remapped = 0
    rotation_modes = {}  # ctrl_bone_name -> mode string

    for layer in action.layers:
        for strip in layer.strips:
            for cb in strip.channelbags:
                for fc in cb.fcurves:
                    if not fc.data_path.startswith('pose.bones["'):
                        continue

                    bone_name = fc.data_path.split('"')[1]
                    if bone_name not in mapping:
                        continue

                    ctrl_name = mapping[bone_name]
                    prop = fc.data_path.split('"].')[1]

                    if "rotation_euler" in prop:
                        rotation_modes[ctrl_name] = 'XYZ'
                    elif "rotation_quaternion" in prop:
                        rotation_modes[ctrl_name] = 'QUATERNION'

                    fc.data_path = f'pose.bones["{ctrl_name}"].{prop}'
                    remapped += 1

    # Align rotation modes so Blender reads the FCurves
    for ctrl_name, mode in rotation_modes.items():
        pbone = armature_obj.pose.bones.get(ctrl_name)
        if pbone:
            pbone.rotation_mode = mode

    return remapped


def retarget_all_actions_to_fk(armature_obj):
    """Retarget every action that references this armature's DEF bones.

    Returns total FCurves remapped across all actions.
    """
    mapping = build_def_to_fk_map(armature_obj)
    if not mapping:
        return 0

    def_names = set(mapping.keys())
    total = 0

    for action in bpy.data.actions:
        has_def_curves = False
        for layer in action.layers:
            if has_def_curves:
                break
            for strip in layer.strips:
                if has_def_curves:
                    break
                for cb in strip.channelbags:
                    if has_def_curves:
                        break
                    for fc in cb.fcurves:
                        if fc.data_path.startswith('pose.bones["'):
                            name = fc.data_path.split('"')[1]
                            if name in def_names:
                                has_def_curves = True
                                break

        if has_def_curves:
            total += retarget_action_to_fk(armature_obj, action)

    return total
