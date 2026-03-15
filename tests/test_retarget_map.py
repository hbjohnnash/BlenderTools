"""Tests for animation.ml.retarget_map and animation.ml.smpl_skeleton.

Pure-Python tests — no Blender dependency.  Uses mock objects for
scan data and armature.
"""

from math import pi

import numpy as np
import pytest

from animation.ml import smpl_skeleton
from animation.ml.retarget_map import (
    InfluenceMap,
    RetargetRefiner,
    _euler_to_matrix,
    _matrix_to_euler_xyz,
    apply_retarget,
    build_default_influence_map,
)

# ── Mock helpers ───────────────────────────────────────────────

class _MockMatrix4x4:
    """Mock for Blender's 4x4 Matrix with row/column access."""

    def __init__(self, mat3x3=None):
        if mat3x3 is None:
            mat3x3 = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        self._data = [
            [mat3x3[0][0], mat3x3[0][1], mat3x3[0][2], 0],
            [mat3x3[1][0], mat3x3[1][1], mat3x3[1][2], 0],
            [mat3x3[2][0], mat3x3[2][1], mat3x3[2][2], 0],
            [0, 0, 0, 1],
        ]

    def __getitem__(self, row):
        return self._data[row]


class _MockVec3:
    """Minimal mock for Blender Vector — supports .x/.y/.z and [0]/[1]/[2]."""

    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = x, y, z

    def __getitem__(self, i):
        return (self.x, self.y, self.z)[i]


class _MockBone:
    """Minimal mock for ``bpy.types.Bone`` (armature data bone)."""

    def __init__(self, name, length=0.1, head_z=0.0, tail_z=0.1,
                 matrix_local=None, parent=None):
        self.name = name
        self.length = length
        self.head_local = _MockVec3(0.0, 0.0, head_z)
        self.tail_local = _MockVec3(0.0, 0.0, tail_z)
        self.matrix_local = matrix_local or _MockMatrix4x4()
        self.parent = parent


class _MockPoseBone:
    """Minimal mock for ``bpy.types.PoseBone``."""

    def __init__(self, name):
        self.name = name
        self.rotation_mode = 'QUATERNION'
        self.constraints = []


class _MockBoneCollection:
    """Dict-like container that supports ``.get()``."""

    def __init__(self, items):
        self._items = {b.name: b for b in items}

    def get(self, name, default=None):
        return self._items.get(name, default)

    def __iter__(self):
        return iter(self._items.values())


class _MockScanBone:
    def __init__(self, bone_name, chain_id, role, skip=False):
        self.bone_name = bone_name
        self.chain_id = chain_id
        self.role = role
        self.skip = skip


class _MockScanChain:
    def __init__(self, chain_id, module_type, side):
        self.chain_id = chain_id
        self.module_type = module_type
        self.side = side


class _MockScanData:
    def __init__(self, chains, bones, is_scanned=True, has_wrap_rig=True):
        self.chains = chains
        self.bones = bones
        self.is_scanned = is_scanned
        self.has_wrap_rig = has_wrap_rig


def _make_armature(bone_specs):
    """Create a mock armature from a list of (name, length) tuples.

    Creates matching data bones and pose bones.
    """
    data_bones = [_MockBone(n, blen) for n, blen in bone_specs]
    pose_bones = [_MockPoseBone(n) for n, _ in bone_specs]
    arm = type('Armature', (), {
        'data': type('ArmData', (), {
            'bones': _MockBoneCollection(data_bones),
        })(),
        'pose': type('Pose', (), {
            'bones': _MockBoneCollection(pose_bones),
        })(),
    })()
    return arm


# ── SMPL skeleton tests ───────────────────────────────────────

class TestSMPLSkeleton:

    def test_joint_count(self):
        assert smpl_skeleton.NUM_JOINTS == 22
        assert len(smpl_skeleton.JOINT_NAMES) == 22
        assert len(smpl_skeleton.PARENTS) == 22
        assert len(smpl_skeleton.DESCRIPTIONS) == 22

    def test_root_is_parentless(self):
        assert smpl_skeleton.PARENTS[0] == -1

    def test_all_parents_valid(self):
        for i in range(1, smpl_skeleton.NUM_JOINTS):
            p = smpl_skeleton.PARENTS[i]
            assert 0 <= p < i, f"Joint {i} has invalid parent {p}"

    def test_offsets_zup_shape(self):
        assert smpl_skeleton.OFFSETS_ZUP.shape == (22, 3)

    def test_skeleton_height_positive(self):
        assert smpl_skeleton.SKELETON_HEIGHT > 0

    def test_get_skeleton_structure(self):
        skel = smpl_skeleton.get_skeleton()
        assert "joints" in skel
        assert "height" in skel
        assert len(skel["joints"]) == 22
        j0 = skel["joints"][0]
        assert j0["name"] == "Pelvis"
        assert j0["parent"] == -1

    def test_chains_cover_all_joints(self):
        """Every joint should belong to exactly one chain."""
        covered = set()
        for chain_def in smpl_skeleton.CHAINS.values():
            for j in chain_def['joints']:
                assert j not in covered, f"Joint {j} in multiple chains"
                covered.add(j)
        assert covered == set(range(smpl_skeleton.NUM_JOINTS))

    def test_chain_sides(self):
        for name, chain_def in smpl_skeleton.CHAINS.items():
            if '_l' in name:
                assert chain_def['side'] == 'L'
            elif '_r' in name:
                assert chain_def['side'] == 'R'


# ── InfluenceMap tests ─────────────────────────────────────────

class TestInfluenceMap:

    def test_empty_by_default(self):
        imap = InfluenceMap()
        assert imap.is_empty()
        assert imap.root_bone is None

    def test_add_and_query(self):
        imap = InfluenceMap()
        imap.joint_map[0] = [("BoneA", 1.0)]
        imap.joint_map[1] = [("BoneB", 0.6), ("BoneC", 0.4)]
        assert not imap.is_empty()
        assert imap.get_targets(0) == [("BoneA", 1.0)]
        assert len(imap.get_targets(1)) == 2
        assert imap.get_targets(99) == []

    def test_mapped_joints(self):
        imap = InfluenceMap()
        imap.joint_map[3] = [("X", 1.0)]
        imap.joint_map[6] = [("Y", 1.0)]
        assert imap.mapped_smpl_joints() == {3, 6}


# ── RetargetRefiner hook tests ─────────────────────────────────

class TestRefiner:

    def test_refiner_modifies_map(self):
        class DoubleWeight(RetargetRefiner):
            def update(self, imap, context=None):
                for sj in list(imap.joint_map):
                    imap.joint_map[sj] = [
                        (b, w * 2) for b, w in imap.joint_map[sj]
                    ]

        imap = InfluenceMap()
        imap.joint_map[0] = [("Bone", 0.5)]
        imap.add_refiner(DoubleWeight())
        imap.apply_refiners()
        assert imap.joint_map[0] == [("Bone", 1.0)]

    def test_multiple_refiners_run_in_order(self):
        calls = []

        class First(RetargetRefiner):
            def update(self, imap, ctx=None):
                calls.append("first")

        class Second(RetargetRefiner):
            def update(self, imap, ctx=None):
                calls.append("second")

        imap = InfluenceMap()
        imap.add_refiner(First())
        imap.add_refiner(Second())
        imap.apply_refiners()
        assert calls == ["first", "second"]

    def test_refiner_receives_context(self):
        received = {}

        class CtxRefiner(RetargetRefiner):
            def update(self, imap, context=None):
                received.update(context or {})

        imap = InfluenceMap()
        imap.add_refiner(CtxRefiner())
        imap.apply_refiners(context={"armature_obj": "foo"})
        assert received["armature_obj"] == "foo"


# ── build_default_influence_map tests ──────────────────────────

class TestBuildDefaultMap:

    @staticmethod
    def _make_leg_setup():
        """Create scan data + armature for a 1:1 leg chain mapping."""
        chains = [_MockScanChain("LEG_L", "leg", "L")]
        bones = [
            _MockScanBone("DEF-Thigh_L", "LEG_L", "THIGH"),
            _MockScanBone("DEF-Shin_L", "LEG_L", "SHIN"),
            _MockScanBone("DEF-Foot_L", "LEG_L", "FOOT"),
            _MockScanBone("DEF-Toe_L", "LEG_L", "TOE"),
        ]
        scan = _MockScanData(chains, bones)
        arm = _make_armature([
            ("CTRL-Wrap_LEG_L_FK_THIGH", 0.4),
            ("CTRL-Wrap_LEG_L_FK_SHIN", 0.35),
            ("CTRL-Wrap_LEG_L_FK_FOOT", 0.1),
            ("CTRL-Wrap_LEG_L_FK_TOE", 0.05),
        ])
        return scan, arm

    def test_returns_none_without_scan(self):
        arm = _make_armature([])
        assert build_default_influence_map(None, arm) is None

    def test_returns_none_without_wrap_rig(self):
        scan = _MockScanData([], [], has_wrap_rig=False)
        arm = _make_armature([])
        assert build_default_influence_map(scan, arm) is None

    def test_1to1_leg_mapping(self):
        """4-bone SMPL leg → 4-bone user leg = 1:1."""
        scan, arm = self._make_leg_setup()
        imap = build_default_influence_map(scan, arm)
        assert imap is not None

        # SMPL leg_l joints are [1, 4, 7, 10]
        assert imap.get_targets(1) == [
            ("CTRL-Wrap_LEG_L_FK_THIGH", 1.0),
        ]
        assert imap.get_targets(4) == [
            ("CTRL-Wrap_LEG_L_FK_SHIN", 1.0),
        ]

    def test_root_bone_set_from_pelvis(self):
        """Root bone should be set from SMPL Pelvis mapping."""
        chains = [_MockScanChain("SPINE_C", "spine", "C")]
        bones = [
            _MockScanBone("DEF-Pelvis", "SPINE_C", "HIP"),
            _MockScanBone("DEF-Spine1", "SPINE_C", "SPINE1"),
            _MockScanBone("DEF-Chest", "SPINE_C", "CHEST"),
        ]
        scan = _MockScanData(chains, bones)
        arm = _make_armature([
            ("CTRL-Wrap_SPINE_C_FK_HIP", 0.1),
            ("CTRL-Wrap_SPINE_C_FK_SPINE1", 0.15),
            ("CTRL-Wrap_SPINE_C_FK_CHEST", 0.1),
        ])
        imap = build_default_influence_map(scan, arm)
        assert imap.root_bone == "CTRL-Wrap_SPINE_C_FK_HIP"

    def test_split_chain_uses_bone_length_weights(self):
        """2 SMPL joints → 4 user bones: should split with weights."""
        chains = [_MockScanChain("NECK_HEAD_C", "neck_head", "C")]
        bones = [
            _MockScanBone("DEF-Neck1", "NECK_HEAD_C", "NECK1"),
            _MockScanBone("DEF-Neck2", "NECK_HEAD_C", "NECK2"),
            _MockScanBone("DEF-Head1", "NECK_HEAD_C", "HEAD1"),
            _MockScanBone("DEF-Head2", "NECK_HEAD_C", "HEAD2"),
        ]
        scan = _MockScanData(chains, bones)
        arm = _make_armature([
            ("CTRL-Wrap_NECK_HEAD_C_FK_NECK1", 0.1),
            ("CTRL-Wrap_NECK_HEAD_C_FK_NECK2", 0.1),
            ("CTRL-Wrap_NECK_HEAD_C_FK_HEAD1", 0.15),
            ("CTRL-Wrap_NECK_HEAD_C_FK_HEAD2", 0.05),
        ])
        imap = build_default_influence_map(scan, arm)

        # SMPL neck_head joints are [12, 15]
        # 2 SMPL → 4 user = ratio 2.0
        # Joint 12 → bones[0:2], Joint 15 → bones[2:4]
        targets_12 = imap.get_targets(12)
        assert len(targets_12) == 2
        # Weights should be proportional to bone length
        total = 0.1 + 0.1
        assert abs(targets_12[0][1] - 0.1 / total) < 1e-6
        assert abs(targets_12[1][1] - 0.1 / total) < 1e-6

        targets_15 = imap.get_targets(15)
        assert len(targets_15) == 2
        total2 = 0.15 + 0.05
        assert abs(targets_15[0][1] - 0.15 / total2) < 1e-6

    def test_merge_chain(self):
        """4 SMPL joints → 2 user bones: should merge."""
        chains = [_MockScanChain("ARM_R", "arm", "R")]
        bones = [
            _MockScanBone("DEF-Arm_R_Upper", "ARM_R", "UPPER"),
            _MockScanBone("DEF-Arm_R_Lower", "ARM_R", "LOWER"),
        ]
        scan = _MockScanData(chains, bones)
        arm = _make_armature([
            ("CTRL-Wrap_ARM_R_FK_UPPER", 0.3),
            ("CTRL-Wrap_ARM_R_FK_LOWER", 0.25),
        ])
        imap = build_default_influence_map(scan, arm)

        # SMPL arm_r joints are [14, 17, 19, 21]
        # 4 SMPL → 2 user = ratio 2.0
        # Joints 14,17 → UPPER, joints 19,21 → LOWER
        assert imap.get_targets(14)[0][0] == "CTRL-Wrap_ARM_R_FK_UPPER"
        assert imap.get_targets(17)[0][0] == "CTRL-Wrap_ARM_R_FK_UPPER"
        assert imap.get_targets(19)[0][0] == "CTRL-Wrap_ARM_R_FK_LOWER"
        assert imap.get_targets(21)[0][0] == "CTRL-Wrap_ARM_R_FK_LOWER"

    def test_skipped_bones_excluded(self):
        chains = [_MockScanChain("LEG_L", "leg", "L")]
        bones = [
            _MockScanBone("DEF-Thigh_L", "LEG_L", "THIGH"),
            _MockScanBone("DEF-Extra", "LEG_L", "EXTRA", skip=True),
            _MockScanBone("DEF-Shin_L", "LEG_L", "SHIN"),
            _MockScanBone("DEF-Foot_L", "LEG_L", "FOOT"),
            _MockScanBone("DEF-Toe_L", "LEG_L", "TOE"),
        ]
        scan = _MockScanData(chains, bones)
        arm = _make_armature([
            ("CTRL-Wrap_LEG_L_FK_THIGH", 0.4),
            ("CTRL-Wrap_LEG_L_FK_SHIN", 0.35),
            ("CTRL-Wrap_LEG_L_FK_FOOT", 0.1),
            ("CTRL-Wrap_LEG_L_FK_TOE", 0.05),
        ])
        imap = build_default_influence_map(scan, arm)
        # 4 SMPL → 4 user (skipped bone excluded) = 1:1
        assert imap.get_targets(1) == [
            ("CTRL-Wrap_LEG_L_FK_THIGH", 1.0),
        ]

    def test_missing_ctrl_bone_falls_back_to_def(self):
        """When CTRL FK bone doesn't exist, use DEF bone name."""
        chains = [_MockScanChain("NECK_HEAD_C", "neck_head", "C")]
        bones = [
            _MockScanBone("DEF-Neck", "NECK_HEAD_C", "NECK"),
            _MockScanBone("DEF-Head", "NECK_HEAD_C", "HEAD"),
        ]
        scan = _MockScanData(chains, bones)
        # Armature has DEF bones but NOT CTRL FK bones
        arm = _make_armature([
            ("DEF-Neck", 0.1),
            ("DEF-Head", 0.2),
        ])
        imap = build_default_influence_map(scan, arm)
        targets = imap.get_targets(12)
        assert targets[0][0] == "DEF-Neck"

    def test_role_matching_extra_user_bone(self):
        """5 user bones (with extra pelvis) vs 4 SMPL joints.

        Role matching should skip the extra pelvis bone and align
        THIGH→upper_leg, SHIN→lower_leg, FOOT→foot, TOE→toe.
        """
        chains = [_MockScanChain("leg_L", "leg", "L")]
        bones = [
            _MockScanBone("DEF-Pelvis_L", "leg_L", "pelvis"),
            _MockScanBone("DEF-Thigh_L", "leg_L", "upper_leg"),
            _MockScanBone("DEF-Shin_L", "leg_L", "lower_leg"),
            _MockScanBone("DEF-Foot_L", "leg_L", "foot"),
            _MockScanBone("DEF-Toe_L", "leg_L", "toe"),
        ]
        scan = _MockScanData(chains, bones)
        arm = _make_armature([
            ("CTRL-Wrap_leg_L_FK_pelvis", 0.05),
            ("CTRL-Wrap_leg_L_FK_upper_leg", 0.4),
            ("CTRL-Wrap_leg_L_FK_lower_leg", 0.35),
            ("CTRL-Wrap_leg_L_FK_foot", 0.1),
            ("CTRL-Wrap_leg_L_FK_toe", 0.05),
        ])
        imap = build_default_influence_map(scan, arm)

        # SMPL leg_l joints [1, 4, 7, 10]
        # pelvis bone should NOT receive any SMPL joint
        assert imap.get_targets(1) == [
            ("CTRL-Wrap_leg_L_FK_upper_leg", 1.0),
        ]
        assert imap.get_targets(4) == [
            ("CTRL-Wrap_leg_L_FK_lower_leg", 1.0),
        ]
        assert imap.get_targets(7) == [
            ("CTRL-Wrap_leg_L_FK_foot", 1.0),
        ]
        assert imap.get_targets(10) == [
            ("CTRL-Wrap_leg_L_FK_toe", 1.0),
        ]

    def test_role_matching_spine_merge(self):
        """3 user spine bones vs 4 SMPL spine joints.

        HIP→hips, SPINE→spine_01, CHEST+UPPER_CHEST→chest (merge).
        """
        chains = [_MockScanChain("spine_C", "spine", "C")]
        bones = [
            _MockScanBone("DEF-Hips", "spine_C", "hips"),
            _MockScanBone("DEF-Spine1", "spine_C", "spine_01"),
            _MockScanBone("DEF-Chest", "spine_C", "chest"),
        ]
        scan = _MockScanData(chains, bones)
        arm = _make_armature([
            ("CTRL-Wrap_spine_C_FK_hips", 0.1),
            ("CTRL-Wrap_spine_C_FK_spine_01", 0.15),
            ("CTRL-Wrap_spine_C_FK_chest", 0.1),
        ])
        imap = build_default_influence_map(scan, arm)

        # SMPL spine joints [0, 3, 6, 9]
        # HIP→hips (1:1)
        assert imap.get_targets(0) == [
            ("CTRL-Wrap_spine_C_FK_hips", 1.0),
        ]
        # SPINE→spine_01 (1:1)
        assert imap.get_targets(3) == [
            ("CTRL-Wrap_spine_C_FK_spine_01", 1.0),
        ]
        # CHEST→chest, UPPER_CHEST also→chest (merge)
        assert imap.get_targets(6) == [
            ("CTRL-Wrap_spine_C_FK_chest", 1.0),
        ]
        assert imap.get_targets(9) == [
            ("CTRL-Wrap_spine_C_FK_chest", 1.0),
        ]


# ── apply_retarget tests ──────────────────────────────────────

class TestApplyRetarget:

    def test_basic_retarget(self):
        """Single frame, 1:1 mapping, weight 1.0."""
        imap = InfluenceMap()
        imap.joint_map[0] = [("Root", 1.0)]
        imap.joint_map[1] = [("Leg", 1.0)]
        imap.root_bone = "Root"

        rotations = [[(0.1, 0.2, 0.3), (0.4, 0.5, 0.6)]]
        root_pos = [(1.0, 2.0, 3.0)]

        result = apply_retarget(rotations, root_pos, imap)
        assert result['is_retargeted'] is True
        assert result['root_bone'] == "Root"
        assert result['bone_rotations']['Root'][0] == pytest.approx(
            (0.1, 0.2, 0.3),
        )
        assert result['bone_rotations']['Leg'][0] == pytest.approx(
            (0.4, 0.5, 0.6),
        )

    def test_weighted_distribution(self):
        """Split one SMPL joint across two bones with weights."""
        imap = InfluenceMap()
        imap.joint_map[0] = [("A", 0.6), ("B", 0.4)]

        rotations = [[(1.0, 0.0, 0.0)]]
        root_pos = [(0.0, 0.0, 0.0)]

        result = apply_retarget(rotations, root_pos, imap)
        assert result['bone_rotations']['A'][0] == pytest.approx(
            (0.6, 0.0, 0.0),
        )
        assert result['bone_rotations']['B'][0] == pytest.approx(
            (0.4, 0.0, 0.0),
        )

    def test_position_scaling(self):
        """Root positions should be scaled by position_scale."""
        imap = InfluenceMap()
        imap.joint_map[0] = [("Root", 1.0)]
        imap.root_bone = "Root"

        rotations = [[(0.0, 0.0, 0.0)]]
        root_pos = [(1.0, 2.0, 3.0)]

        result = apply_retarget(rotations, root_pos, imap,
                                position_scale=2.0)
        assert result['root_positions'][0] == pytest.approx(
            (2.0, 4.0, 6.0),
        )

    def test_multiple_frames(self):
        """Multi-frame output should have correct length."""
        imap = InfluenceMap()
        imap.joint_map[0] = [("Bone", 1.0)]

        rotations = [
            [(0.1, 0.0, 0.0)],
            [(0.2, 0.0, 0.0)],
            [(0.3, 0.0, 0.0)],
        ]
        root_pos = [(0, 0, 0), (1, 0, 0), (2, 0, 0)]

        result = apply_retarget(rotations, root_pos, imap)
        assert len(result['bone_rotations']['Bone']) == 3
        assert result['bone_rotations']['Bone'][2][0] == pytest.approx(0.3)

    def test_unmapped_joints_ignored(self):
        """SMPL joints not in the map should not produce output."""
        imap = InfluenceMap()
        imap.joint_map[0] = [("Root", 1.0)]
        # Joint 1 is NOT mapped

        rotations = [[(0.1, 0.0, 0.0), (0.5, 0.5, 0.5)]]
        root_pos = [(0, 0, 0)]

        result = apply_retarget(rotations, root_pos, imap)
        assert "Root" in result['bone_rotations']
        assert len(result['bone_rotations']) == 1

    def test_composition_from_multiple_sources(self):
        """Two SMPL joints mapping to same bone should compose rotations."""
        imap = InfluenceMap()
        imap.joint_map[0] = [("Shared", 1.0)]
        imap.joint_map[1] = [("Shared", 1.0)]

        rotations = [[(0.1, 0.2, 0.3), (0.01, 0.02, 0.03)]]
        root_pos = [(0, 0, 0)]

        result = apply_retarget(rotations, root_pos, imap)
        rx, ry, rz = result['bone_rotations']['Shared'][0]
        # Matrix composition of small rotations ≈ sum of Euler angles
        assert abs(rx - 0.11) < 0.01
        assert abs(ry - 0.22) < 0.01
        assert abs(rz - 0.33) < 0.01

    def test_rest_pose_correction_identity(self):
        """Identity rest-local rotation should not change the result."""
        imap = InfluenceMap()
        imap.joint_map[0] = [("Bone", 1.0)]

        rotations = [[(0.3, 0.5, 0.1)]]
        root_pos = [(0, 0, 0)]

        # Identity matrix_local → identity rest-local rotation
        bone = _MockBone("Bone", matrix_local=_MockMatrix4x4())
        arm = type('Armature', (), {
            'data': type('D', (), {
                'bones': _MockBoneCollection([bone]),
            })(),
        })()

        result = apply_retarget(rotations, root_pos, imap,
                                armature_obj=arm)
        assert result['bone_rotations']['Bone'][0] == pytest.approx(
            (0.3, 0.5, 0.1), abs=1e-6,
        )

    def test_rest_pose_correction_rotated_bone(self):
        """Conjugation: R_pose = R_world_rest^T @ R_smpl @ R_world_rest.

        SMPL rotations are in world-aligned frames (identity rest), so
        we conjugate by the bone's full world rest orientation
        (bone.matrix_local) to express the rotation in bone-local space.
        """
        imap = InfluenceMap()
        imap.joint_map[0] = [("Bone", 1.0)]

        angle = pi / 6  # 30°
        rotations = [[(angle, 0.0, 0.0)]]  # Rx(30°) in SMPL space
        root_pos = [(0, 0, 0)]

        # Bone world rest orientation: 90° around Y
        ry90 = [[0, 0, 1], [0, 1, 0], [-1, 0, 0]]
        bone = _MockBone("Bone", matrix_local=_MockMatrix4x4(ry90))
        arm = type('Armature', (), {
            'data': type('D', (), {
                'bones': _MockBoneCollection([bone]),
            })(),
        })()

        result = apply_retarget(rotations, root_pos, imap,
                                armature_obj=arm)
        rx, ry, rz = result['bone_rotations']['Bone'][0]

        # R_pose = R_world^T @ R_smpl @ R_world
        # The bone's final world orientation (rest @ pose) should
        # equal R_smpl @ R_world (SMPL chain @ rest orientation).
        R_world_rest = np.array(ry90)
        R_pose = _euler_to_matrix(rx, ry, rz)
        R_final = R_world_rest @ R_pose
        R_smpl = _euler_to_matrix(angle, 0.0, 0.0)
        np.testing.assert_allclose(R_final, R_smpl @ R_world_rest, atol=1e-6)

    def test_conjugation_identity_gives_identity(self):
        """When SMPL rotation is identity, pose should be identity."""
        imap = InfluenceMap()
        imap.joint_map[0] = [("Bone", 1.0)]

        rotations = [[(0.0, 0.0, 0.0)]]
        root_pos = [(0, 0, 0)]

        # Non-trivial rest rotation: 90° around Y
        ry90 = [[0, 0, 1], [0, 1, 0], [-1, 0, 0]]
        bone = _MockBone("Bone", matrix_local=_MockMatrix4x4(ry90))
        arm = type('Armature', (), {
            'data': type('D', (), {
                'bones': _MockBoneCollection([bone]),
            })(),
        })()

        result = apply_retarget(rotations, root_pos, imap,
                                armature_obj=arm)
        rx, ry, rz = result['bone_rotations']['Bone'][0]
        # Identity SMPL → identity pose (bone stays at rest)
        assert abs(rx) < 1e-6
        assert abs(ry) < 1e-6
        assert abs(rz) < 1e-6

    def test_world_rest_with_intermediate_parent(self):
        """Child bone with non-identity parent must use world rest.

        Simulates: SMPL Pelvis → robot hips with an intermediate parent
        bone between them.  The intermediate parent has a non-trivial
        orientation, so parent-relative rest != world rest.
        """
        imap = InfluenceMap()
        imap.joint_map[0] = [("Child", 1.0)]

        angle = pi / 4  # 45° Rx in SMPL space
        rotations = [[(angle, 0.0, 0.0)]]
        root_pos = [(0, 0, 0)]

        # Parent bone: 90° around Z
        rz90 = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
        parent_bone = _MockBone(
            "Parent", matrix_local=_MockMatrix4x4(rz90),
        )
        # Child bone: 90° around Z then 90° around Y = compound orientation
        # matrix_local is the bone's WORLD rest orientation (armature space)
        child_world = np.array(rz90) @ np.array(
            [[0, 0, 1], [0, 1, 0], [-1, 0, 0]],
        )
        child_bone = _MockBone(
            "Child",
            matrix_local=_MockMatrix4x4(child_world.tolist()),
            parent=parent_bone,
        )
        arm = type('Armature', (), {
            'data': type('D', (), {
                'bones': _MockBoneCollection([parent_bone, child_bone]),
            })(),
        })()

        result = apply_retarget(rotations, root_pos, imap,
                                armature_obj=arm)
        rx, ry, rz = result['bone_rotations']['Child'][0]

        # Verify: bone_final = R_smpl @ R_world_rest
        R_world_rest = child_world
        R_pose = _euler_to_matrix(rx, ry, rz)
        R_final = R_world_rest @ R_pose
        R_smpl = _euler_to_matrix(angle, 0.0, 0.0)
        np.testing.assert_allclose(R_final, R_smpl @ R_world_rest, atol=1e-6)

    def test_root_positions_converted_to_bone_local(self):
        """Root positions should be in bone-local space when armature given.

        For a bone with rest matrix R, world = R @ local + head,
        so local = R^T @ (world - head).
        """
        # Root bone with non-identity rest: Rz(90°)
        rz90 = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
        bone = _MockBone("Root", matrix_local=_MockMatrix4x4(rz90))
        arm = type('Armature', (), {
            'data': type('D', (), {
                'bones': _MockBoneCollection([bone]),
            })(),
        })()

        imap = InfluenceMap()
        imap.joint_map[0] = [("Root", 1.0)]
        imap.root_bone = "Root"

        # World position (1, 0, 0) — moving in +X
        rotations = [[(0.0, 0.0, 0.0)]]
        root_pos = [(1.0, 0.0, 0.0)]

        result = apply_retarget(rotations, root_pos, imap,
                                armature_obj=arm)
        # Rz(90°)^T @ (1,0,0) = [[0,1,0],[-1,0,0],[0,0,1]] @ (1,0,0)
        #                      = (0, -1, 0)
        assert result['root_positions'][0] == pytest.approx(
            (0.0, -1.0, 0.0), abs=1e-6,
        )
