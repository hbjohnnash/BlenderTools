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
    # Left Fingers (1=thumb, 2=index, 3=middle, 4=ring, 5=pinky)
    "mixamorig:LeftHandThumb1": ("1_01", "L", "finger", "finger_01_L"),
    "mixamorig:LeftHandThumb2": ("1_02", "L", "finger", "finger_01_L"),
    "mixamorig:LeftHandThumb3": ("1_03", "L", "finger", "finger_01_L"),
    "mixamorig:LeftHandIndex1": ("2_01", "L", "finger", "finger_02_L"),
    "mixamorig:LeftHandIndex2": ("2_02", "L", "finger", "finger_02_L"),
    "mixamorig:LeftHandIndex3": ("2_03", "L", "finger", "finger_02_L"),
    "mixamorig:LeftHandMiddle1": ("3_01", "L", "finger", "finger_03_L"),
    "mixamorig:LeftHandMiddle2": ("3_02", "L", "finger", "finger_03_L"),
    "mixamorig:LeftHandMiddle3": ("3_03", "L", "finger", "finger_03_L"),
    "mixamorig:LeftHandRing1": ("4_01", "L", "finger", "finger_04_L"),
    "mixamorig:LeftHandRing2": ("4_02", "L", "finger", "finger_04_L"),
    "mixamorig:LeftHandRing3": ("4_03", "L", "finger", "finger_04_L"),
    "mixamorig:LeftHandPinky1": ("5_01", "L", "finger", "finger_05_L"),
    "mixamorig:LeftHandPinky2": ("5_02", "L", "finger", "finger_05_L"),
    "mixamorig:LeftHandPinky3": ("5_03", "L", "finger", "finger_05_L"),
    # Right Fingers (1=thumb, 2=index, 3=middle, 4=ring, 5=pinky)
    "mixamorig:RightHandThumb1": ("1_01", "R", "finger", "finger_01_R"),
    "mixamorig:RightHandThumb2": ("1_02", "R", "finger", "finger_01_R"),
    "mixamorig:RightHandThumb3": ("1_03", "R", "finger", "finger_01_R"),
    "mixamorig:RightHandIndex1": ("2_01", "R", "finger", "finger_02_R"),
    "mixamorig:RightHandIndex2": ("2_02", "R", "finger", "finger_02_R"),
    "mixamorig:RightHandIndex3": ("2_03", "R", "finger", "finger_02_R"),
    "mixamorig:RightHandMiddle1": ("3_01", "R", "finger", "finger_03_R"),
    "mixamorig:RightHandMiddle2": ("3_02", "R", "finger", "finger_03_R"),
    "mixamorig:RightHandMiddle3": ("3_03", "R", "finger", "finger_03_R"),
    "mixamorig:RightHandRing1": ("4_01", "R", "finger", "finger_04_R"),
    "mixamorig:RightHandRing2": ("4_02", "R", "finger", "finger_04_R"),
    "mixamorig:RightHandRing3": ("4_03", "R", "finger", "finger_04_R"),
    "mixamorig:RightHandPinky1": ("5_01", "R", "finger", "finger_05_R"),
    "mixamorig:RightHandPinky2": ("5_02", "R", "finger", "finger_05_R"),
    "mixamorig:RightHandPinky3": ("5_03", "R", "finger", "finger_05_R"),
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
    # Left Fingers (1=thumb, 2=index, 3=middle, 4=ring, 5=pinky)
    "thumb_01_l": ("1_01", "L", "finger", "finger_01_L"),
    "thumb_02_l": ("1_02", "L", "finger", "finger_01_L"),
    "thumb_03_l": ("1_03", "L", "finger", "finger_01_L"),
    "index_01_l": ("2_01", "L", "finger", "finger_02_L"),
    "index_02_l": ("2_02", "L", "finger", "finger_02_L"),
    "index_03_l": ("2_03", "L", "finger", "finger_02_L"),
    "middle_01_l": ("3_01", "L", "finger", "finger_03_L"),
    "middle_02_l": ("3_02", "L", "finger", "finger_03_L"),
    "middle_03_l": ("3_03", "L", "finger", "finger_03_L"),
    "ring_01_l": ("4_01", "L", "finger", "finger_04_L"),
    "ring_02_l": ("4_02", "L", "finger", "finger_04_L"),
    "ring_03_l": ("4_03", "L", "finger", "finger_04_L"),
    "pinky_01_l": ("5_01", "L", "finger", "finger_05_L"),
    "pinky_02_l": ("5_02", "L", "finger", "finger_05_L"),
    "pinky_03_l": ("5_03", "L", "finger", "finger_05_L"),
    # Right Fingers (1=thumb, 2=index, 3=middle, 4=ring, 5=pinky)
    "thumb_01_r": ("1_01", "R", "finger", "finger_01_R"),
    "thumb_02_r": ("1_02", "R", "finger", "finger_01_R"),
    "thumb_03_r": ("1_03", "R", "finger", "finger_01_R"),
    "index_01_r": ("2_01", "R", "finger", "finger_02_R"),
    "index_02_r": ("2_02", "R", "finger", "finger_02_R"),
    "index_03_r": ("2_03", "R", "finger", "finger_02_R"),
    "middle_01_r": ("3_01", "R", "finger", "finger_03_R"),
    "middle_02_r": ("3_02", "R", "finger", "finger_03_R"),
    "middle_03_r": ("3_03", "R", "finger", "finger_03_R"),
    "ring_01_r": ("4_01", "R", "finger", "finger_04_R"),
    "ring_02_r": ("4_02", "R", "finger", "finger_04_R"),
    "ring_03_r": ("4_03", "R", "finger", "finger_04_R"),
    "pinky_01_r": ("5_01", "R", "finger", "finger_05_R"),
    "pinky_02_r": ("5_02", "R", "finger", "finger_05_R"),
    "pinky_03_r": ("5_03", "R", "finger", "finger_05_R"),
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
