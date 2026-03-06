"""Pre-built bone name dictionaries for common skeleton standards."""


# Each entry maps bone_name -> (role, side, module_type, chain_id)
# role: semantic name within the chain (hips, spine_01, upper_arm, etc.)
# side: C/L/R
# module_type: spine/arm/leg/neck_head/finger/etc.
# chain_id: grouping key like "spine_C", "arm_L", "leg_R"

MIXAMO_MAP = {
    # Spine
    "mixamorig:Hips": ("hips", "C", "spine", "spine_C"),
    "mixamorig:Spine": ("spine_01", "C", "spine", "spine_C"),
    "mixamorig:Spine1": ("spine_02", "C", "spine", "spine_C"),
    "mixamorig:Spine2": ("chest", "C", "spine", "spine_C"),
    # Neck/Head
    "mixamorig:Neck": ("neck", "C", "neck_head", "neck_head_C"),
    "mixamorig:Head": ("head", "C", "neck_head", "neck_head_C"),
    # Left Arm
    "mixamorig:LeftShoulder": ("clavicle", "L", "arm", "arm_L"),
    "mixamorig:LeftArm": ("upper_arm", "L", "arm", "arm_L"),
    "mixamorig:LeftForeArm": ("lower_arm", "L", "arm", "arm_L"),
    "mixamorig:LeftHand": ("hand", "L", "arm", "arm_L"),
    # Right Arm
    "mixamorig:RightShoulder": ("clavicle", "R", "arm", "arm_R"),
    "mixamorig:RightArm": ("upper_arm", "R", "arm", "arm_R"),
    "mixamorig:RightForeArm": ("lower_arm", "R", "arm", "arm_R"),
    "mixamorig:RightHand": ("hand", "R", "arm", "arm_R"),
    # Left Leg
    "mixamorig:LeftUpLeg": ("upper_leg", "L", "leg", "leg_L"),
    "mixamorig:LeftLeg": ("lower_leg", "L", "leg", "leg_L"),
    "mixamorig:LeftFoot": ("foot", "L", "leg", "leg_L"),
    "mixamorig:LeftToeBase": ("toe", "L", "leg", "leg_L"),
    # Right Leg
    "mixamorig:RightUpLeg": ("upper_leg", "R", "leg", "leg_R"),
    "mixamorig:RightLeg": ("lower_leg", "R", "leg", "leg_R"),
    "mixamorig:RightFoot": ("foot", "R", "leg", "leg_R"),
    "mixamorig:RightToeBase": ("toe", "R", "leg", "leg_R"),
    # Left Fingers
    "mixamorig:LeftHandThumb1": ("thumb_01", "L", "finger", "thumb_L"),
    "mixamorig:LeftHandThumb2": ("thumb_02", "L", "finger", "thumb_L"),
    "mixamorig:LeftHandThumb3": ("thumb_03", "L", "finger", "thumb_L"),
    "mixamorig:LeftHandIndex1": ("index_01", "L", "finger", "index_L"),
    "mixamorig:LeftHandIndex2": ("index_02", "L", "finger", "index_L"),
    "mixamorig:LeftHandIndex3": ("index_03", "L", "finger", "index_L"),
    "mixamorig:LeftHandMiddle1": ("middle_01", "L", "finger", "middle_L"),
    "mixamorig:LeftHandMiddle2": ("middle_02", "L", "finger", "middle_L"),
    "mixamorig:LeftHandMiddle3": ("middle_03", "L", "finger", "middle_L"),
    "mixamorig:LeftHandRing1": ("ring_01", "L", "finger", "ring_L"),
    "mixamorig:LeftHandRing2": ("ring_02", "L", "finger", "ring_L"),
    "mixamorig:LeftHandRing3": ("ring_03", "L", "finger", "ring_L"),
    "mixamorig:LeftHandPinky1": ("pinky_01", "L", "finger", "pinky_L"),
    "mixamorig:LeftHandPinky2": ("pinky_02", "L", "finger", "pinky_L"),
    "mixamorig:LeftHandPinky3": ("pinky_03", "L", "finger", "pinky_L"),
    # Right Fingers
    "mixamorig:RightHandThumb1": ("thumb_01", "R", "finger", "thumb_R"),
    "mixamorig:RightHandThumb2": ("thumb_02", "R", "finger", "thumb_R"),
    "mixamorig:RightHandThumb3": ("thumb_03", "R", "finger", "thumb_R"),
    "mixamorig:RightHandIndex1": ("index_01", "R", "finger", "index_R"),
    "mixamorig:RightHandIndex2": ("index_02", "R", "finger", "index_R"),
    "mixamorig:RightHandIndex3": ("index_03", "R", "finger", "index_R"),
    "mixamorig:RightHandMiddle1": ("middle_01", "R", "finger", "middle_R"),
    "mixamorig:RightHandMiddle2": ("middle_02", "R", "finger", "middle_R"),
    "mixamorig:RightHandMiddle3": ("middle_03", "R", "finger", "middle_R"),
    "mixamorig:RightHandRing1": ("ring_01", "R", "finger", "ring_R"),
    "mixamorig:RightHandRing2": ("ring_02", "R", "finger", "ring_R"),
    "mixamorig:RightHandRing3": ("ring_03", "R", "finger", "ring_R"),
    "mixamorig:RightHandPinky1": ("pinky_01", "R", "finger", "pinky_R"),
    "mixamorig:RightHandPinky2": ("pinky_02", "R", "finger", "pinky_R"),
    "mixamorig:RightHandPinky3": ("pinky_03", "R", "finger", "pinky_R"),
}

UE_MANNEQUIN_MAP = {
    # Spine
    "pelvis": ("hips", "C", "spine", "spine_C"),
    "spine_01": ("spine_01", "C", "spine", "spine_C"),
    "spine_02": ("spine_02", "C", "spine", "spine_C"),
    "spine_03": ("chest", "C", "spine", "spine_C"),
    # Neck/Head
    "neck_01": ("neck", "C", "neck_head", "neck_head_C"),
    "head": ("head", "C", "neck_head", "neck_head_C"),
    # Left Arm
    "clavicle_l": ("clavicle", "L", "arm", "arm_L"),
    "upperarm_l": ("upper_arm", "L", "arm", "arm_L"),
    "lowerarm_l": ("lower_arm", "L", "arm", "arm_L"),
    "hand_l": ("hand", "L", "arm", "arm_L"),
    # Right Arm
    "clavicle_r": ("clavicle", "R", "arm", "arm_R"),
    "upperarm_r": ("upper_arm", "R", "arm", "arm_R"),
    "lowerarm_r": ("lower_arm", "R", "arm", "arm_R"),
    "hand_r": ("hand", "R", "arm", "arm_R"),
    # Left Leg
    "thigh_l": ("upper_leg", "L", "leg", "leg_L"),
    "calf_l": ("lower_leg", "L", "leg", "leg_L"),
    "foot_l": ("foot", "L", "leg", "leg_L"),
    "ball_l": ("toe", "L", "leg", "leg_L"),
    # Right Leg
    "thigh_r": ("upper_leg", "R", "leg", "leg_R"),
    "calf_r": ("lower_leg", "R", "leg", "leg_R"),
    "foot_r": ("foot", "R", "leg", "leg_R"),
    "ball_r": ("toe", "R", "leg", "leg_R"),
    # Left Fingers
    "thumb_01_l": ("thumb_01", "L", "finger", "thumb_L"),
    "thumb_02_l": ("thumb_02", "L", "finger", "thumb_L"),
    "thumb_03_l": ("thumb_03", "L", "finger", "thumb_L"),
    "index_01_l": ("index_01", "L", "finger", "index_L"),
    "index_02_l": ("index_02", "L", "finger", "index_L"),
    "index_03_l": ("index_03", "L", "finger", "index_L"),
    "middle_01_l": ("middle_01", "L", "finger", "middle_L"),
    "middle_02_l": ("middle_02", "L", "finger", "middle_L"),
    "middle_03_l": ("middle_03", "L", "finger", "middle_L"),
    "ring_01_l": ("ring_01", "L", "finger", "ring_L"),
    "ring_02_l": ("ring_02", "L", "finger", "ring_L"),
    "ring_03_l": ("ring_03", "L", "finger", "ring_L"),
    "pinky_01_l": ("pinky_01", "L", "finger", "pinky_L"),
    "pinky_02_l": ("pinky_02", "L", "finger", "pinky_L"),
    "pinky_03_l": ("pinky_03", "L", "finger", "pinky_L"),
    # Right Fingers
    "thumb_01_r": ("thumb_01", "R", "finger", "thumb_R"),
    "thumb_02_r": ("thumb_02", "R", "finger", "thumb_R"),
    "thumb_03_r": ("thumb_03", "R", "finger", "thumb_R"),
    "index_01_r": ("index_01", "R", "finger", "index_R"),
    "index_02_r": ("index_02", "R", "finger", "index_R"),
    "index_03_r": ("index_03", "R", "finger", "index_R"),
    "middle_01_r": ("middle_01", "R", "finger", "middle_R"),
    "middle_02_r": ("middle_02", "R", "finger", "middle_R"),
    "middle_03_r": ("middle_03", "R", "finger", "middle_R"),
    "ring_01_r": ("ring_01", "R", "finger", "ring_R"),
    "ring_02_r": ("ring_02", "R", "finger", "ring_R"),
    "ring_03_r": ("ring_03", "R", "finger", "ring_R"),
    "pinky_01_r": ("pinky_01", "R", "finger", "pinky_R"),
    "pinky_02_r": ("pinky_02", "R", "finger", "pinky_R"),
    "pinky_03_r": ("pinky_03", "R", "finger", "pinky_R"),
}

ALL_MAPS = {
    "mixamo": MIXAMO_MAP,
    "ue_mannequin": UE_MANNEQUIN_MAP,
}


def detect_skeleton_type(bone_names):
    """Score each name map by match ratio. Returns (type_str, confidence_float).

    Threshold: 40% of map entries must match for a positive detection.
    Returns ("unknown", 0.0) if no map meets the threshold.
    """
    bone_set = set(bone_names)
    best_type = "unknown"
    best_score = 0.0

    for skel_type, name_map in ALL_MAPS.items():
        matched = sum(1 for k in name_map if k in bone_set)
        total = len(name_map)
        if total == 0:
            continue
        score = matched / total
        if score > best_score:
            best_score = score
            best_type = skel_type

    if best_score < 0.4:
        return ("unknown", best_score)
    return (best_type, best_score)


def apply_name_map(bone_names, skeleton_type):
    """Apply the appropriate name map to a list of bone names.

    Returns dict of {bone_name: {role, side, module_type, chain_id, confidence, source}}.
    Only bones found in the map are included.
    """
    name_map = ALL_MAPS.get(skeleton_type, {})
    result = {}

    for bone_name in bone_names:
        if bone_name in name_map:
            role, side, module_type, chain_id = name_map[bone_name]
            result[bone_name] = {
                "role": role,
                "side": side,
                "module_type": module_type,
                "chain_id": chain_id,
                "confidence": 1.0,
                "source": "name_map",
            }

    return result
