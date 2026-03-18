"""Tests for MotionLCM position-based recovery from 263-dim features.

Pure-Python tests — no Blender or ML dependencies.
"""

from math import pi

import numpy as np
import pytest

from animation.ml import smpl_skeleton
from animation.ml.motionlcm_adapter import MotionLCMAdapter

_adapter = MotionLCMAdapter.__new__(MotionLCMAdapter)


def _smpl_rest_positions_yup():
    """Compute SMPL rest-pose joint positions in Y-up."""
    pos = np.zeros((22, 3))
    for i in range(22):
        p = int(smpl_skeleton.PARENTS[i])
        if p >= 0:
            pos[i] = pos[p] + smpl_skeleton._OFFSETS_YUP[i]
    return pos


# Rest-pose pelvis height above ground (subtracted from root Z output)
_PELVIS_HEIGHT = -float(_smpl_rest_positions_yup()[:, 1].min())


class TestRecoverFrom263:
    """Tests for the position-based 263-dim recovery."""

    @staticmethod
    def _make_features(n_frames, ang_vel=0.0, lin_vel=(0.0, 0.0),
                       height=0.9):
        """Create 263-dim features matching HumanML3D format.

        Joint positions at [4:67] have root-relative XZ but
        **absolute Y** (height from ground).
        """
        feat = np.zeros((n_frames, 263))
        feat[:, 0] = ang_vel
        feat[:, 1] = lin_vel[0]
        feat[:, 2] = lin_vel[1]
        feat[:, 3] = height
        # SMPL rest positions accumulated from root (root at origin)
        rest_pos = _smpl_rest_positions_yup()
        joint_feat = rest_pos[1:].copy()  # (21, 3)
        # XZ stays root-relative (already is, since root XZ = 0)
        # Y becomes absolute: offset_Y + pelvis_height
        joint_feat[:, 1] += height
        feat[:, 4:67] = joint_feat.reshape(63)
        return feat

    def test_frame_zero_at_origin(self):
        """Frame 0 should start at origin with no rotation."""
        feat = self._make_features(5, ang_vel=0.1, lin_vel=(1.0, 0.0))
        rots, pos = _adapter._recover_from_263(feat)
        assert pos[0] == pytest.approx(
            (0.0, 0.0, 0.9 - _PELVIS_HEIGHT), abs=1e-6,
        )
        assert rots[0][0] == pytest.approx((0.0, 0.0, 0.0), abs=1e-6)

    def test_frame_shift(self):
        """Frame 1 position uses frame 0's velocity, not frame 1's."""
        feat = self._make_features(3, ang_vel=0.0, lin_vel=(0.0, 0.0))
        feat[0, 1] = 2.0
        feat[1, 1] = 99.0
        rots, pos = _adapter._recover_from_263(feat)
        assert pos[0][0] == pytest.approx(0.0)
        assert pos[1][0] == pytest.approx(2.0, abs=1e-6)
        assert pos[2][0] == pytest.approx(2.0 + 99.0, abs=1e-6)

    def test_no_turning_straight_walk(self):
        """Zero angular velocity → straight-line trajectory."""
        feat = self._make_features(10, ang_vel=0.0, lin_vel=(1.0, 0.0),
                                   height=0.0)
        rots, pos = _adapter._recover_from_263(feat)
        for f in range(1, 10):
            assert pos[f][0] == pytest.approx(float(f), abs=1e-4)
            assert abs(pos[f][1]) < 1e-4

    def test_rest_pose_gives_identity_rotations(self):
        """Rest-pose positions with identity root → zero Euler angles."""
        feat = self._make_features(2)
        rots, pos = _adapter._recover_from_263(feat)
        for j in range(22):
            rx, ry, rz = rots[0][j]
            assert abs(rx) < 1e-4, f"Joint {j} rx={rx}"
            assert abs(ry) < 1e-4, f"Joint {j} ry={ry}"
            assert abs(rz) < 1e-4, f"Joint {j} rz={rz}"

    def test_root_facing_accumulates(self):
        """Root facing angle should accumulate angular velocity."""
        feat = self._make_features(4, ang_vel=0.1)
        rots, pos = _adapter._recover_from_263(feat)
        # Root global = qinv(r_quat) = facing→world.  After Y↔Z
        # conjugation, Ry(−2θ) → Rz(+2θ), so Z Euler increases.
        z_angles = [rots[f][0][2] for f in range(4)]
        assert abs(z_angles[0]) < 1e-6
        # Facing accumulates: each frame's |z_angle| grows
        assert abs(z_angles[1]) > abs(z_angles[0])
        assert abs(z_angles[2]) > abs(z_angles[1])
        # Frame 1: r_rot_ang=0.1 → magnitude ≈ 0.2
        assert abs(z_angles[1]) == pytest.approx(0.2, abs=1e-3)

    def test_positions_yup_matches_reference(self):
        """Position recovery should match the reference recover_from_ric."""
        feat = self._make_features(5, ang_vel=0.0, lin_vel=(1.0, 0.5),
                                   height=1.0)
        pos = _adapter._recover_positions_yup(feat)
        assert pos.shape == (5, 22, 3)
        # Frame 0: root at origin with height
        assert pos[0, 0] == pytest.approx([0.0, 1.0, 0.0], abs=1e-6)
        # With zero angular velocity, X velocity integrates directly
        assert pos[1, 0, 0] == pytest.approx(1.0, abs=1e-6)

    def test_child_rotations_identity_under_root_turn(self):
        """When only the root turns, child local rotations stay identity."""
        feat = self._make_features(3, ang_vel=0.2)
        rots, pos = _adapter._recover_from_263(feat)
        # Non-root joints should have near-zero local rotations
        for j in range(1, 22):
            rx, ry, rz = rots[1][j]
            assert abs(rx) < 0.05, f"Joint {j} rx={rx}"
            assert abs(ry) < 0.05, f"Joint {j} ry={ry}"
            assert abs(rz) < 0.05, f"Joint {j} rz={rz}"


class TestRotation6DRows:
    """Tests for the row-convention 6D → matrix decoder (kept for utility)."""

    def test_identity_roundtrip(self):
        r6d = np.array([[1, 0, 0, 0, 1, 0]], dtype=np.float64)
        R = _adapter._rotation_6d_to_matrix_rows(r6d)
        np.testing.assert_allclose(R[0], np.eye(3), atol=1e-6)

    def test_90_degree_y_rotation(self):
        r6d = np.array([[0, 0, 1, 0, 1, 0]], dtype=np.float64)
        R = _adapter._rotation_6d_to_matrix_rows(r6d)
        expected = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]],
                            dtype=np.float64)
        np.testing.assert_allclose(R[0], expected, atol=1e-6)

    def test_batch_processing(self):
        r6d = np.array([
            [1, 0, 0, 0, 1, 0],
            [0, 0, 1, 0, 1, 0],
        ], dtype=np.float64)
        R = _adapter._rotation_6d_to_matrix_rows(r6d)
        assert R.shape == (2, 3, 3)
        np.testing.assert_allclose(R[0], np.eye(3), atol=1e-6)
