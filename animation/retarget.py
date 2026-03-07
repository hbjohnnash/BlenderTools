"""Animation retargeting helpers."""

import bpy


# Default bone name mappings between common rig formats
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


def retarget_action(source_action, target_armature, mapping, new_action_name=None):
    """Copy animation from source action to target armature with bone remapping.

    Args:
        source_action: Source bpy.types.Action.
        target_armature: Target armature object.
        mapping: Dict mapping source_bone_name -> target_bone_name.
        new_action_name: Name for the new action.

    Returns:
        The new action, or None on failure.
    """
    from bpy_extras.anim_utils import action_ensure_channelbag_for_slot

    new_name = new_action_name or f"{source_action.name}_retargeted"
    new_action = bpy.data.actions.new(name=new_name)

    if not target_armature.animation_data:
        target_armature.animation_data_create()

    # Create slot for target
    slot = new_action.slots.new(name=target_armature.name, id_type='OBJECT')
    target_armature.animation_data.action = new_action
    target_armature.animation_data.action_slot = slot

    channelbag = action_ensure_channelbag_for_slot(new_action, slot)

    # Iterate source fcurves
    for src_slot in source_action.slots:
        for src_cb in src_slot.channelbags:
            for src_fc in src_cb.fcurves:
                # Parse bone name from data path
                dp = src_fc.data_path
                if 'pose.bones["' not in dp:
                    continue

                # Extract bone name
                start = dp.index('pose.bones["') + len('pose.bones["')
                end = dp.index('"]', start)
                src_bone = dp[start:end]

                # Map to target bone
                tgt_bone = mapping.get(src_bone)
                if not tgt_bone:
                    continue

                # Build new data path
                new_dp = dp[:start] + tgt_bone + dp[end:]

                # Create target fcurve
                new_fc = channelbag.fcurves.new(new_dp, index=src_fc.array_index)

                # Copy keyframes
                new_fc.keyframe_points.add(len(src_fc.keyframe_points))
                for i, kf in enumerate(src_fc.keyframe_points):
                    new_kf = new_fc.keyframe_points[i]
                    new_kf.co = kf.co
                    new_kf.interpolation = kf.interpolation
                    new_kf.handle_left = kf.handle_left
                    new_kf.handle_right = kf.handle_right

                new_fc.update()

    return new_action
