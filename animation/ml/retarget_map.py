"""Influence map for SMPL-to-user retargeting.

The influence map is a dictionary mapping each SMPL joint index
to a list of ``(target_bone_name, weight)`` tuples.  It controls
how motion generated on the standard SMPL skeleton is distributed
onto the user's actual rig bones.

Default weights are proportional to bone length within each chain.
A hook system allows refiners (e.g. pose-based calibration) to
modify the weights before retargeting is applied.
"""

from math import acos, atan2, cos, sin, sqrt

import numpy as np

from . import smpl_skeleton


class InfluenceMap:
    """SMPL-to-user bone influence mapping with refiner hooks.

    Attributes:
        joint_map: ``{smpl_joint_idx: [(bone_name, weight), ...]}``
        root_bone: name of the bone that receives root position
            keyframes, or ``None``.
    """

    def __init__(self):
        self.joint_map = {}
        self.root_bone = None
        self._refiners = []

    def add_refiner(self, refiner):
        """Register a :class:`RetargetRefiner` to run before use."""
        self._refiners.append(refiner)

    def apply_refiners(self, context=None):
        """Run all registered refiners to update weights."""
        for refiner in self._refiners:
            refiner.update(self, context)

    def get_targets(self, smpl_joint_idx):
        """Return ``[(bone_name, weight), ...]`` for a SMPL joint."""
        return self.joint_map.get(smpl_joint_idx, [])

    def mapped_smpl_joints(self):
        """Return set of SMPL joint indices that have mappings."""
        return set(self.joint_map.keys())

    def is_empty(self):
        """Return True if no joints are mapped."""
        return len(self.joint_map) == 0


class RetargetRefiner:
    """Base class for influence map refiners.

    Subclass and implement :meth:`update` to modify the influence
    map before retargeting is applied.  This is the hook point
    for future enhancements — pose-based calibration, ML-based
    weight estimation, manual user tweaks, etc.
    """

    def update(self, influence_map, context=None):
        """Modify *influence_map* in place.

        Args:
            influence_map: :class:`InfluenceMap` instance.
            context: optional dict with ``armature_obj``,
                ``scan_data``, etc.
        """


# ── Public API ─────────────────────────────────────────────────

def build_default_influence_map(scan_data, armature_obj):
    """Build influence map from wrap rig scan data.

    Auto-matches SMPL chains to user chains by ``module_type``
    and ``side``, then distributes SMPL joints across user bones
    proportionally to bone length.

    Args:
        scan_data: ``BT_ScanData`` property group from armature.
        armature_obj: Blender armature object.

    Returns:
        :class:`InfluenceMap`, or ``None`` if scan data is
        insufficient (no scan or no wrap rig).
    """
    if not scan_data or not getattr(scan_data, 'is_scanned', False):
        return None
    if not getattr(scan_data, 'has_wrap_rig', False):
        return None

    imap = InfluenceMap()

    # Collect user chains grouped by (module_type, side)
    user_chains = _collect_user_chains(scan_data)

    # Match each SMPL chain to user chains and distribute
    for chain_def in smpl_skeleton.CHAINS.values():
        mt = chain_def['module_type']
        side = chain_def['side']
        smpl_joints = chain_def['joints']
        smpl_roles = chain_def['roles']
        user_bones = user_chains.get((mt, side), [])
        if not user_bones:
            continue

        _distribute_chain(
            smpl_joints, smpl_roles, user_bones, armature_obj, imap,
        )

    # Set root bone for position keyframes.
    # SMPL root positions describe the pelvis trajectory, so apply
    # them to the bone mapped to SMPL Pelvis (joint 0).  The user's
    # root bone (at ground level) should stay unanimated — moving it
    # would offset the entire skeleton incorrectly.
    pelvis_targets = imap.get_targets(0)
    if pelvis_targets:
        imap.root_bone = pelvis_targets[0][0]
    else:
        imap.root_bone = _find_root_bone(scan_data, armature_obj)

    return imap


def apply_retarget(smpl_rotations, smpl_root_positions, influence_map,
                   armature_obj=None, position_scale=1.0,
                   facing_correction=None):
    """Retarget SMPL motion to user bones via influence map.

    Takes per-frame SMPL Euler rotations and root positions,
    distributes them to user bones according to the influence map.

    When *armature_obj* is provided, applies rest-pose correction
    to handle different bone orientations between the SMPL skeleton
    (identity rest rotations) and the user's skeleton.  The SMPL
    local rotation is conjugated by the user bone's armature-space
    rest orientation: ``R_user = R_rest^T @ R_smpl @ R_rest``.

    Args:
        smpl_rotations: list of frames, each frame is a list of
            ``(rx, ry, rz)`` tuples indexed by SMPL joint.
        smpl_root_positions: list of ``(x, y, z)`` per frame.
        influence_map: :class:`InfluenceMap` instance.
        armature_obj: Blender armature for rest-pose correction.
            If ``None``, rotations are transferred without
            correction (useful for testing or identity rigs).
        position_scale: scale factor for root positions (ratio
            of user skeleton height to SMPL skeleton height).
        facing_correction: optional 3x3 numpy matrix to convert
            SMPL rotations from model convention (+Y forward in
            Z-up) to the user armature's convention (-Y forward).
            Typically ``Rot(Z, π)`` = ``[[-1,0,0],[0,-1,0],[0,0,1]]``.
            Applied as ``C @ R_smpl @ C.T`` before rest-pose
            correction.

    Returns:
        dict with ``bone_rotations``, ``root_positions``,
        ``root_bone``, and ``is_retargeted`` flag.
    """
    n_frames = len(smpl_rotations)

    # Pre-compute rest-local rotations for correction
    rest_rots = {}
    if armature_obj is not None:
        for sj in influence_map.mapped_smpl_joints():
            for bone_name, _ in influence_map.get_targets(sj):
                if bone_name not in rest_rots:
                    rest_rots[bone_name] = _get_rest_local_rotation(
                        bone_name, armature_obj,
                    )
    use_correction = bool(rest_rots)

    # Step 1: Accumulate raw SMPL rotations per bone (before correction).
    # This ensures rest-pose correction is applied ONCE per bone even
    # when multiple SMPL joints map to the same user bone (merge case).
    bone_smpl_raw = {}
    for sj in influence_map.mapped_smpl_joints():
        for bone_name, _ in influence_map.get_targets(sj):
            if bone_name not in bone_smpl_raw:
                bone_smpl_raw[bone_name] = [
                    np.eye(3) for _ in range(n_frames)
                ]

    # Pre-compute facing correction transpose (if provided).
    C = facing_correction
    C_T = C.T if C is not None else None

    for f in range(n_frames):
        frame_rots = smpl_rotations[f]
        for sj in influence_map.mapped_smpl_joints():
            if sj >= len(frame_rots):
                continue
            rx, ry, rz = frame_rots[sj]
            R_smpl = _euler_to_matrix(rx, ry, rz)

            # Convert from model convention to user armature convention
            if C is not None:
                R_smpl = C @ R_smpl @ C_T

            for bone_name, weight in influence_map.get_targets(sj):
                # Fractional rotation for weighted distribution
                if abs(weight - 1.0) > 1e-6:
                    R_smpl_w = _fractional_rotation(R_smpl, weight)
                else:
                    R_smpl_w = R_smpl

                # Compose raw SMPL rotation (no correction yet)
                bone_smpl_raw[bone_name][f] = (
                    bone_smpl_raw[bone_name][f] @ R_smpl_w
                )

    # Step 2: Apply rest-pose correction ONCE per bone.
    # SMPL has identity rest rotations.  The user's bones have
    # non-identity rest orientations (R_rest).  We use conjugation
    # to express the SMPL rotation in the bone's local frame:
    #   R_pose = R_rest^T @ R_smpl @ R_rest
    # This ensures: when R_smpl = I, R_pose = I (bone stays at rest).
    bone_rotations = {}
    for bone_name, frames in bone_smpl_raw.items():
        euler_frames = []
        for f in range(n_frames):
            R_combined = frames[f]
            if use_correction and bone_name in rest_rots:
                R_rest = rest_rots[bone_name]
                R_pose = R_rest.T @ R_combined @ R_rest
            else:
                R_pose = R_combined
            euler_frames.append(_matrix_to_euler_xyz(R_pose))
        bone_rotations[bone_name] = euler_frames

    # Scale root positions
    scaled_root = [
        (x * position_scale, y * position_scale, z * position_scale)
        for x, y, z in smpl_root_positions
    ]

    # Convert root positions from world space to bone-local space.
    # pbone.location is interpreted in the bone's local coordinate frame:
    #   world_pos = R_bone @ local_pos + rest_head
    #   local_pos = R_bone^T @ (world_pos - rest_head)
    if armature_obj is not None and influence_map.root_bone:
        bone = armature_obj.data.bones.get(influence_map.root_bone)
        if bone:
            R_bone = np.array([
                [bone.matrix_local[r][c] for c in range(3)]
                for r in range(3)
            ])
            head = np.array([
                bone.head_local[0], bone.head_local[1], bone.head_local[2],
            ])
            R_inv = R_bone.T
            scaled_root = [
                tuple(R_inv @ (np.array(p) - head))
                for p in scaled_root
            ]

    return {
        'bone_rotations': bone_rotations,
        'root_positions': scaled_root,
        'root_bone': influence_map.root_bone,
        'is_retargeted': True,
    }


# ── Rotation math ─────────────────────────────────────────────

def _euler_to_matrix(rx, ry, rz):
    """Convert XYZ Euler angles (radians) to 3x3 rotation matrix.

    Rotation order: intrinsic XYZ (R = Rz @ Ry @ Rx).
    """
    cx, sx = cos(rx), sin(rx)
    cy, sy = cos(ry), sin(ry)
    cz, sz = cos(rz), sin(rz)
    return np.array([
        [cy * cz, sx * sy * cz - cx * sz, cx * sy * cz + sx * sz],
        [cy * sz, sx * sy * sz + cx * cz, cx * sy * sz - sx * cz],
        [-sy,     sx * cy,                cx * cy],
    ])


def _matrix_to_euler_xyz(R):
    """Convert 3x3 rotation matrix to XYZ Euler angles (radians)."""
    sy = -R[2, 0]
    cy = sqrt(max(0.0, 1.0 - sy * sy))
    if cy > 1e-6:
        rx = atan2(R[2, 1], R[2, 2])
        ry = atan2(sy, cy)
        rz = atan2(R[1, 0], R[0, 0])
    else:
        # Gimbal lock
        rx = atan2(-R[1, 2], R[1, 1])
        ry = atan2(sy, cy)
        rz = 0.0
    return (rx, ry, rz)


def _fractional_rotation(R, t):
    """Take fraction *t* of rotation *R* via axis-angle scaling."""
    trace = R[0, 0] + R[1, 1] + R[2, 2]
    cos_angle = max(-1.0, min(1.0, (trace - 1.0) / 2.0))
    angle = acos(cos_angle)
    if abs(angle) < 1e-8:
        return np.eye(3)

    # Extract axis from skew-symmetric part
    axis = np.array([
        R[2, 1] - R[1, 2],
        R[0, 2] - R[2, 0],
        R[1, 0] - R[0, 1],
    ])
    axis_norm = np.linalg.norm(axis)
    if axis_norm < 1e-8:
        return np.eye(3)
    axis /= axis_norm

    # Rodrigues' rotation formula with scaled angle
    angle *= t
    K = np.array([
        [0, -axis[2], axis[1]],
        [axis[2], 0, -axis[0]],
        [-axis[1], axis[0], 0],
    ])
    return np.eye(3) + sin(angle) * K + (1 - cos(angle)) * (K @ K)


def _get_rest_local_rotation(bone_name, armature_obj):
    """Get the bone's rest orientation in armature space as 3x3.

    Uses ``bone.matrix_local`` which is the bone's rest orientation
    in armature space.  For user armatures with wrap rigs, the Blender
    bone hierarchy (CTRL/MCH bones) differs from SMPL's joint
    hierarchy, so armature-space conjugation is correct:

        ``R_pose = R_rest^T @ R_smpl @ R_rest``

    (Parent-relative conjugation is used separately for the SMPL
    preview where the Blender hierarchy matches SMPL's joint hierarchy.)
    """
    bone = armature_obj.data.bones.get(bone_name)
    if bone is None:
        return np.eye(3)

    return np.array([
        [bone.matrix_local[r][c] for c in range(3)]
        for r in range(3)
    ])


# ── Internals ──────────────────────────────────────────────────

def _find_root_bone(scan_data, armature_obj):
    """Find the root/COG CTRL FK bone from scan data.

    Looks for a chain with ``module_type='root'`` and returns
    the corresponding CTRL FK bone name.
    """
    for chain in scan_data.chains:
        if chain.module_type != 'root':
            continue
        # Find the first non-skipped bone in this chain
        for bone_item in scan_data.bones:
            if bone_item.chain_id != chain.chain_id or bone_item.skip:
                continue
            ctrl_name = (
                f"CTRL-Wrap_{bone_item.chain_id}_FK_{bone_item.role}"
            )
            if armature_obj.pose.bones.get(ctrl_name):
                return ctrl_name
            # Fallback to the original bone name
            if armature_obj.pose.bones.get(bone_item.bone_name):
                return bone_item.bone_name
    return None


def _collect_user_chains(scan_data):
    """Group scan bones by ``(module_type, side)``.

    Returns:
        dict mapping ``(module_type, side)`` → list of bone items,
        preserving the order from the scan (root-to-tip within
        each chain).
    """
    # Build chain_id → (module_type, side) lookup
    chain_info = {}
    for chain in scan_data.chains:
        chain_info[chain.chain_id] = (chain.module_type, chain.side)

    # Group bones by chain key
    chain_bones = {}
    for bone_item in scan_data.bones:
        if bone_item.skip:
            continue
        cid = bone_item.chain_id
        if cid not in chain_info:
            continue
        key = chain_info[cid]
        if key not in chain_bones:
            chain_bones[key] = []
        chain_bones[key].append(bone_item)

    return chain_bones


def _distribute_chain(smpl_joints, smpl_roles, user_bones, armature_obj,
                      imap):
    """Distribute SMPL chain joints across user chain bones.

    Uses role-based matching to align SMPL joints with user bones
    semantically (e.g. SMPL THIGH → user upper_leg, not pelvis).
    Falls back to index-based distribution when no roles match.

    Strategy:
        1. Find role anchors — matched (smpl_pos, user_pos) pairs.
        2. Build segments from anchors.
        3. Within each segment, apply 1:1 / split / merge as needed.
    """
    # Build CTRL FK bone names from scan data
    ctrl_names = []
    ctrl_roles = []
    for bone_item in user_bones:
        ctrl_name = f"CTRL-Wrap_{bone_item.chain_id}_FK_{bone_item.role}"
        pbone = armature_obj.pose.bones.get(ctrl_name)
        if pbone:
            ctrl_names.append(ctrl_name)
        else:
            ctrl_names.append(bone_item.bone_name)
        ctrl_roles.append(bone_item.role)

    if not ctrl_names:
        return

    # Try role-based matching
    anchors = _find_role_anchors(smpl_roles, ctrl_roles)
    if not anchors:
        # No role matches — fall back to index-based distribution
        _distribute_by_index(smpl_joints, ctrl_names, armature_obj, imap)
        return

    # Build segments from anchors
    segments = _build_segments(
        len(smpl_joints), len(ctrl_names), anchors,
    )

    # Create mappings per segment
    for smpl_indices, user_indices in segments:
        seg_smpl = [smpl_joints[si] for si in smpl_indices]
        seg_ctrl = [ctrl_names[ui] for ui in user_indices]

        if not seg_smpl or not seg_ctrl:
            continue

        if len(seg_smpl) == 1 and len(seg_ctrl) == 1:
            # 1:1
            imap.joint_map[seg_smpl[0]] = [(seg_ctrl[0], 1.0)]

        elif len(seg_smpl) >= 1 and len(seg_ctrl) == 1:
            # Merge: multiple SMPL → 1 user bone
            for sj in seg_smpl:
                imap.joint_map[sj] = [(seg_ctrl[0], 1.0)]

        elif len(seg_smpl) == 1 and len(seg_ctrl) >= 1:
            # Split: 1 SMPL → multiple user bones (weighted)
            bone_lengths = _get_bone_lengths(seg_ctrl, armature_obj)
            total_len = sum(bone_lengths)
            sj = seg_smpl[0]
            if total_len < 1e-8:
                w = 1.0 / len(seg_ctrl)
                imap.joint_map[sj] = [(b, w) for b in seg_ctrl]
            else:
                imap.joint_map[sj] = [
                    (b, blen / total_len)
                    for b, blen in zip(seg_ctrl, bone_lengths)
                ]

        else:
            # Multiple:multiple — 1:1 as far as possible, then merge
            n = min(len(seg_smpl), len(seg_ctrl))
            for i in range(n):
                imap.joint_map[seg_smpl[i]] = [(seg_ctrl[i], 1.0)]
            for i in range(n, len(seg_smpl)):
                imap.joint_map[seg_smpl[i]] = [(seg_ctrl[-1], 1.0)]


def _distribute_by_index(smpl_joints, ctrl_names, armature_obj, imap):
    """Legacy index-based chain distribution (fallback)."""
    n_smpl = len(smpl_joints)
    n_ctrl = len(ctrl_names)

    if n_smpl == n_ctrl:
        for i, sj in enumerate(smpl_joints):
            imap.joint_map[sj] = [(ctrl_names[i], 1.0)]

    elif n_smpl > n_ctrl:
        ratio = n_smpl / n_ctrl
        for si, sj in enumerate(smpl_joints):
            user_idx = min(int(si / ratio), n_ctrl - 1)
            imap.joint_map[sj] = [(ctrl_names[user_idx], 1.0)]

    else:
        bone_lengths = _get_bone_lengths(ctrl_names, armature_obj)
        ratio = n_ctrl / n_smpl
        for si, sj in enumerate(smpl_joints):
            start = int(si * ratio)
            end = int((si + 1) * ratio)
            targets = ctrl_names[start:end]
            lengths = bone_lengths[start:end]
            total_len = sum(lengths)

            if total_len < 1e-8:
                w = 1.0 / len(targets) if targets else 1.0
                imap.joint_map[sj] = [(b, w) for b in targets]
            else:
                imap.joint_map[sj] = [
                    (b, blen / total_len)
                    for b, blen in zip(targets, lengths)
                ]


def _get_bone_lengths(bone_names, armature_obj):
    """Get bone lengths for a list of bone names.

    Falls back to 0.1 for bones not found in the armature.
    """
    lengths = []
    for name in bone_names:
        bone = armature_obj.data.bones.get(name)
        if bone:
            lengths.append(bone.length)
        else:
            lengths.append(0.1)
    return lengths


# ── Role-based chain matching ─────────────────────────────────

# SMPL role → tuple of compatible user role prefixes (lowercase).
# Checked with ``startswith`` for prefix matching (e.g. "neck1"
# matches prefix "neck").
_ROLE_COMPAT = {
    'HIP': ('hip', 'hips'),
    'SPINE': ('spine',),
    'CHEST': ('chest',),
    'UPPER_CHEST': ('upper_chest', 'upperchest'),
    'NECK': ('neck',),
    'HEAD': ('head',),
    'THIGH': ('thigh', 'upper_leg', 'upperleg', 'upleg'),
    'SHIN': ('shin', 'lower_leg', 'lowerleg', 'calf'),
    'FOOT': ('foot', 'ankle'),
    'TOE': ('toe', 'ball'),
    'CLAVICLE': ('clavicle', 'collar'),
    'UPPER': ('upper_arm', 'upperarm'),
    'LOWER': ('lower_arm', 'lowerarm', 'forearm'),
    'HAND': ('hand', 'wrist'),
}


def _roles_compatible(smpl_role, user_role):
    """Check if an SMPL role and a user role are semantically compatible."""
    sr_norm = smpl_role.lower().replace('_', '')
    ur_norm = user_role.lower().replace('_', '')

    # Direct match (covers cases like UPPER↔UPPER)
    if sr_norm == ur_norm:
        return True

    # Check compatibility table
    prefixes = _ROLE_COMPAT.get(smpl_role.upper(), ())
    for prefix in prefixes:
        p_norm = prefix.replace('_', '')
        if ur_norm.startswith(p_norm):
            return True

    return False


def _find_role_anchors(smpl_roles, user_roles):
    """Find role-based anchor pairs between SMPL and user chains.

    Greedy matching in order, ensuring monotonically increasing
    indices on both sides (no crossing anchors).

    Returns:
        List of ``(smpl_pos, user_pos)`` tuples.
    """
    anchors = []
    min_user_idx = 0

    for si, sr in enumerate(smpl_roles):
        for ui in range(min_user_idx, len(user_roles)):
            if _roles_compatible(sr, user_roles[ui]):
                anchors.append((si, ui))
                min_user_idx = ui + 1
                break

    return anchors


def _build_segments(n_smpl, n_user, anchors):
    """Build aligned (smpl_indices, user_indices) segments from anchors.

    User bones before the first anchor are excluded (they stay at
    rest pose).  Unmatched user bones between anchors are assigned
    to the preceding anchor's segment.  Remaining SMPL joints and
    user bones after the last anchor extend the last segment.

    Returns:
        List of ``(smpl_indices, user_indices)`` tuples.
    """
    segments = []
    prev_si = -1

    for ai, (si, ui) in enumerate(anchors):
        # SMPL: from previous anchor + 1 to this anchor (inclusive)
        smpl_range = list(range(prev_si + 1, si + 1))

        # User: from this anchor to next anchor (exclusive) or end
        if ai + 1 < len(anchors):
            next_ui = anchors[ai + 1][1]
            user_range = list(range(ui, next_ui))
        else:
            user_range = list(range(ui, n_user))

        segments.append((smpl_range, user_range))
        prev_si = si

    # Remaining SMPL joints after last anchor → append to last segment
    if segments:
        remaining_smpl = list(range(prev_si + 1, n_smpl))
        if remaining_smpl:
            last_s, last_u = segments[-1]
            segments[-1] = (last_s + remaining_smpl, last_u)

    return segments
