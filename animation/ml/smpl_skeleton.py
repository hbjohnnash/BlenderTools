"""Standard SMPL 22-joint humanoid skeleton for AnyTop generation.

Defines the reference skeleton used as the generation target.
Motion is generated on this fixed, known topology and then
retargeted to the user's actual skeleton via an influence map.

Joint ordering follows the HumanML3D 22-joint convention.
Offsets are from the SMPL body model (``SMPL_OFFSETS`` in
AnyTop's ``param_utils.py``).

Kinematic chains (from HumanML3D)::

    Right leg:  0 → 2 → 5 → 8 → 11
    Left leg:   0 → 1 → 4 → 7 → 10
    Spine:      0 → 3 → 6 → 9 → 12 → 15
    Right arm:  9 → 14 → 17 → 19 → 21
    Left arm:   9 → 13 → 16 → 18 → 20
"""

import numpy as np

# Number of joints in our reference skeleton
NUM_JOINTS = 22

# Joint names — human-readable, used for T5 encoding
JOINT_NAMES = [
    "Pelvis",       # 0
    "L_Hip",        # 1
    "R_Hip",        # 2
    "Spine1",       # 3
    "L_Knee",       # 4
    "R_Knee",       # 5
    "Spine2",       # 6  (chest)
    "L_Ankle",      # 7
    "R_Ankle",      # 8
    "Spine3",       # 9  (upper chest — collars and neck branch here)
    "L_Foot",       # 10
    "R_Foot",       # 11
    "Neck",         # 12
    "L_Collar",     # 13
    "R_Collar",     # 14
    "Head",         # 15
    "L_Shoulder",   # 16 (upper arm)
    "R_Shoulder",   # 17
    "L_Elbow",      # 18 (forearm)
    "R_Elbow",      # 19
    "L_Wrist",      # 20
    "R_Wrist",      # 21
]

# Parent indices — standard HumanML3D SMPL hierarchy
PARENTS = np.array([
    -1,   # 0:  Pelvis (root)
     0,   # 1:  L_Hip
     0,   # 2:  R_Hip
     0,   # 3:  Spine1
     1,   # 4:  L_Knee
     2,   # 5:  R_Knee
     3,   # 6:  Spine2 / Chest
     4,   # 7:  L_Ankle
     5,   # 8:  R_Ankle
     6,   # 9:  Spine3 / Upper Chest
     7,   # 10: L_Foot
     8,   # 11: R_Foot
     9,   # 12: Neck       (parent = Spine3)
     9,   # 13: L_Collar   (parent = Spine3)
     9,   # 14: R_Collar   (parent = Spine3)
    12,   # 15: Head       (parent = Neck)
    13,   # 16: L_Shoulder (parent = L_Collar)
    14,   # 17: R_Shoulder (parent = R_Collar)
    16,   # 18: L_Elbow    (parent = L_Shoulder)
    17,   # 19: R_Elbow    (parent = R_Shoulder)
    18,   # 20: L_Wrist    (parent = L_Elbow)
    19,   # 21: R_Wrist    (parent = R_Elbow)
], dtype=np.int64)

# Offsets in Y-up (AnyTop training space) from SMPL body model.
# These are at training scale (mean bone length ≈ HML_AVG_BONELEN).
# Copied from AnyTop's SMPL_OFFSETS in param_utils.py (all 22 joints).
_OFFSETS_YUP = np.array([
    [ 0.0000,  0.0000,  0.0000],   # 0:  Pelvis
    [ 0.1031,  0.0000,  0.0000],   # 1:  L_Hip
    [-0.1099,  0.0000,  0.0000],   # 2:  R_Hip
    [ 0.0000,  0.1316,  0.0000],   # 3:  Spine1
    [ 0.0000, -0.3936,  0.0000],   # 4:  L_Knee
    [ 0.0000, -0.3902,  0.0000],   # 5:  R_Knee
    [ 0.0000,  0.1432,  0.0000],   # 6:  Spine2
    [ 0.0000, -0.4324,  0.0000],   # 7:  L_Ankle
    [ 0.0000, -0.4256,  0.0000],   # 8:  R_Ankle
    [ 0.0000,  0.0300,  0.0000],   # 9:  Spine3
    [ 0.0000,  0.0000,  0.0800],   # 10: L_Foot
    [ 0.0000,  0.0000,  0.0800],   # 11: R_Foot
    [ 0.0000,  0.1100,  0.0000],   # 12: Neck
    [ 0.0500,  0.0500,  0.0000],   # 13: L_Collar
    [-0.0500,  0.0500,  0.0000],   # 14: R_Collar
    [ 0.0000,  0.0500,  0.0000],   # 15: Head
    [ 0.1100, -0.0400,  0.0000],   # 16: L_Shoulder
    [-0.1100, -0.0400,  0.0000],   # 17: R_Shoulder
    [ 0.0000, -0.2568,  0.0000],   # 18: L_Elbow
    [ 0.0000, -0.2631,  0.0000],   # 19: R_Elbow
    [ 0.0000, -0.2660,  0.0000],   # 20: L_Wrist
    [ 0.0000, -0.2699,  0.0000],   # 21: R_Wrist
], dtype=np.float64)

# Offsets in Z-up (Blender space) — swap Y ↔ Z
OFFSETS_ZUP = np.empty_like(_OFFSETS_YUP)
OFFSETS_ZUP[:, 0] = _OFFSETS_YUP[:, 0]
OFFSETS_ZUP[:, 1] = _OFFSETS_YUP[:, 2]   # Blender Y = AnyTop Z
OFFSETS_ZUP[:, 2] = _OFFSETS_YUP[:, 1]   # Blender Z = AnyTop Y

# Descriptions for T5 encoding — clean, descriptive names
DESCRIPTIONS = [
    "hip pelvis bone",           # 0
    "left upper leg bone",       # 1
    "right upper leg bone",      # 2
    "lower spine bone",          # 3
    "left lower leg bone",       # 4
    "right lower leg bone",      # 5
    "upper spine chest bone",    # 6
    "left ankle bone",           # 7
    "right ankle bone",          # 8
    "upper chest bone",          # 9
    "left foot bone",            # 10
    "right foot bone",           # 11
    "neck bone",                 # 12
    "left clavicle bone",        # 13
    "right clavicle bone",       # 14
    "head bone",                 # 15
    "left upper arm bone",       # 16
    "right upper arm bone",      # 17
    "left forearm bone",         # 18
    "right forearm bone",        # 19
    "left hand bone",            # 20
    "right hand bone",           # 21
]

# Semantic chain definitions — SMPL joint indices grouped root-to-tip.
# module_type and side match the wrap rig scanner's BT_ScanChainItem.
CHAINS = {
    'spine': {
        'joints': [0, 3, 6, 9],
        'module_type': 'spine',
        'side': 'C',
        'roles': ['HIP', 'SPINE', 'CHEST', 'UPPER_CHEST'],
    },
    'neck_head': {
        'joints': [12, 15],
        'module_type': 'neck_head',
        'side': 'C',
        'roles': ['NECK', 'HEAD'],
    },
    'leg_l': {
        'joints': [1, 4, 7, 10],
        'module_type': 'leg',
        'side': 'L',
        'roles': ['THIGH', 'SHIN', 'FOOT', 'TOE'],
    },
    'leg_r': {
        'joints': [2, 5, 8, 11],
        'module_type': 'leg',
        'side': 'R',
        'roles': ['THIGH', 'SHIN', 'FOOT', 'TOE'],
    },
    'arm_l': {
        'joints': [13, 16, 18, 20],
        'module_type': 'arm',
        'side': 'L',
        'roles': ['CLAVICLE', 'UPPER', 'LOWER', 'HAND'],
    },
    'arm_r': {
        'joints': [14, 17, 19, 21],
        'module_type': 'arm',
        'side': 'R',
        'roles': ['CLAVICLE', 'UPPER', 'LOWER', 'HAND'],
    },
}


def _compute_skeleton_height():
    """Compute SMPL skeleton height in Z-up from offsets."""
    positions = np.zeros((NUM_JOINTS, 3))
    for i in range(NUM_JOINTS):
        p = int(PARENTS[i])
        if p >= 0:
            positions[i] = positions[p] + OFFSETS_ZUP[i]
        else:
            positions[i] = OFFSETS_ZUP[i]
    return float(positions[:, 2].max() - positions[:, 2].min())


# Pre-computed skeleton height (Z-up, training scale)
SKELETON_HEIGHT = _compute_skeleton_height()


def get_skeleton():
    """Return the SMPL skeleton dict in Blender Z-up format.

    Compatible with ``AnyTopAdapter.predict()``'s expected input.
    The predict pipeline converts Z-up → Y-up and handles scaling
    internally.

    Since these offsets are already at training scale (mean bone
    length ≈ HML_AVG_BONELEN), the scale factor computed by
    ``scale_and_ground_skeleton()`` will be ≈ 1.0.
    """
    joints = []
    for i in range(NUM_JOINTS):
        joints.append({
            "name": JOINT_NAMES[i],
            "parent": int(PARENTS[i]),
            "offset": OFFSETS_ZUP[i].tolist(),
            "description": DESCRIPTIONS[i],
            "swing_axis": 0,  # X-axis for humanoid forward/back swing
        })

    return {"joints": joints, "height": SKELETON_HEIGHT}
