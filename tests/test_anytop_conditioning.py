"""Tests for animation.ml.anytop_conditioning — pure utility functions.

Tests topology computation, T-pose feature generation, normalization
statistics, bone name cleaning, and temporal mask creation.
No Blender or PyTorch model dependencies.
"""

import math

import numpy as np
import pytest

from animation.ml.anytop_conditioning import (
    FEATURE_LEN,
    MAX_JOINTS,
    build_cond_dict,
    clean_bone_name,
    compute_tpose_features,
    create_topology_edge_relations,
    estimate_mean_std,
)


def _make_skeleton(num_joints=5):
    """Create a minimal skeleton dict for testing."""
    descs = [
        "spine bone", "left upper leg bone", "right upper leg bone",
        "left upper arm bone", "right upper arm bone",
    ]
    joints = []
    for i in range(num_joints):
        desc = descs[i] if i < len(descs) else "bone"
        joints.append({
            "name": f"DEF-Bone_{i}",
            "parent": max(0, i - 1) if i > 0 else -1,
            "offset": [0.0, 0.0, 0.1 * (i + 1)],
            "description": desc,
            "swing_axis": 2,
        })
    return {"joints": joints, "height": 1.8}


class TestTopologyEdgeRelations:
    """Test create_topology_edge_relations."""

    def test_single_joint(self):
        parents = np.array([-1])
        edge, dist = create_topology_edge_relations(parents)
        assert edge.shape == (1, 1)
        # Single joint with no children → end effector (5)
        assert edge[0, 0] == 5

    def test_chain_topology(self):
        """Linear chain: 0 → 1 → 2."""
        parents = np.array([-1, 0, 1])
        edge, dist = create_topology_edge_relations(parents)

        assert edge[0, 0] == 0  # self (has children so not EE)
        assert edge[0, 1] == 2  # 0→1 is child
        assert edge[1, 0] == 1  # 1→0 is parent
        assert edge[1, 2] == 2  # 1→2 is child
        assert edge[2, 1] == 1  # 2→1 is parent
        assert edge[2, 2] == 5  # 2 is end effector (no children)

        assert dist[0, 1] == 1
        assert dist[0, 2] == 2
        assert dist[1, 2] == 1

    def test_sibling_detection(self):
        """Two children of root: 0 → 1, 0 → 2."""
        parents = np.array([-1, 0, 0])
        edge, _ = create_topology_edge_relations(parents)
        assert edge[1, 2] == 3  # sibling
        assert edge[2, 1] == 3  # sibling

    def test_max_path_clamp(self):
        """Distances beyond max_path_len get clamped."""
        parents = np.array([-1, 0, 1, 2, 3, 4, 5])
        _, dist = create_topology_edge_relations(parents, max_path_len=3)
        assert dist[0, 6] == 3  # clamped from 6


class TestTposeFeatures:
    """Test compute_tpose_features."""

    def test_shape(self):
        skeleton = _make_skeleton(5)
        feat = compute_tpose_features(skeleton["joints"], 5)
        assert feat.shape == (5, FEATURE_LEN)

    def test_identity_rotation(self):
        """T-pose should have identity 6D rotation [1,0,0,0,1,0]."""
        skeleton = _make_skeleton(3)
        feat = compute_tpose_features(skeleton["joints"], 3)
        for i in range(3):
            np.testing.assert_allclose(
                feat[i, 3:9], [1, 0, 0, 0, 1, 0], atol=1e-10,
            )

    def test_zero_velocity(self):
        """T-pose should have zero velocity."""
        skeleton = _make_skeleton(3)
        feat = compute_tpose_features(skeleton["joints"], 3)
        np.testing.assert_allclose(feat[:, 9:12], 0.0)

    def test_root_centered_xz(self):
        """Root RIC position should be zero in X and Z."""
        skeleton = _make_skeleton(3)
        feat = compute_tpose_features(skeleton["joints"], 3)
        assert feat[0, 0] == 0.0  # root X
        assert feat[0, 2] == 0.0  # root Z

    def test_foot_contact(self):
        """Joints with 'foot' in description should have contact=1."""
        joints = [
            {"name": "root", "parent": -1, "offset": [0, 0, 0],
             "description": "spine bone"},
            {"name": "foot_L", "parent": 0, "offset": [0, -1, 0],
             "description": "left foot bone"},
        ]
        feat = compute_tpose_features(joints, 2)
        assert feat[0, 12] == 0.0  # spine → no contact
        assert feat[1, 12] == 1.0  # foot → contact


class TestMeanStd:
    """Test estimate_mean_std."""

    def test_shape(self):
        skeleton = _make_skeleton(5)
        tpose = compute_tpose_features(skeleton["joints"], 5)
        mean, std = estimate_mean_std(tpose, 5, 1.8)
        assert mean.shape == (5, FEATURE_LEN)
        assert std.shape == (5, FEATURE_LEN)

    def test_std_positive(self):
        """All std values must be positive."""
        skeleton = _make_skeleton(5)
        tpose = compute_tpose_features(skeleton["joints"], 5)
        _, std = estimate_mean_std(tpose, 5, 1.8)
        assert np.all(std > 0)

    def test_height_scaling(self):
        """Taller skeleton should have larger position std."""
        skeleton = _make_skeleton(3)
        tpose = compute_tpose_features(skeleton["joints"], 3)
        _, std_small = estimate_mean_std(tpose, 3, 1.0)
        _, std_large = estimate_mean_std(tpose, 3, 4.0)
        # Position std for non-root should be larger for taller skeleton
        assert std_large[1, 0] > std_small[1, 0]


class TestTemporalMask:
    """Test create_temporal_mask (requires torch, skipped if unavailable)."""

    @pytest.fixture(autouse=True)
    def _skip_no_torch(self):
        pytest.importorskip("torch")

    def test_shape(self):
        from animation.ml.anytop_conditioning import create_temporal_mask
        mask = create_temporal_mask(window=31, max_len=60)
        assert mask.shape == (61, 61)  # max_len + 1

    def test_first_column_always_one(self):
        """All frames should attend to the T-pose (column 0)."""
        import torch

        from animation.ml.anytop_conditioning import create_temporal_mask
        mask = create_temporal_mask(window=11, max_len=30)
        assert torch.all(mask[:, 0] == 1)

    def test_self_attention(self):
        """Each frame should attend to itself."""
        from animation.ml.anytop_conditioning import create_temporal_mask
        mask = create_temporal_mask(window=5, max_len=20)
        for i in range(21):
            assert mask[i, i] == 1


class TestCleanBoneName:
    """Test clean_bone_name."""

    def test_def_prefix_removed(self):
        result = clean_bone_name("DEF-Spine_C_002")
        assert "DEF" not in result

    def test_side_replacement(self):
        result = clean_bone_name("DEF-Arm_L_Upper")
        assert "Left" in result

    def test_right_side(self):
        result = clean_bone_name("DEF-Leg_R_Thigh")
        assert "Right" in result

    def test_camelcase_split(self):
        result = clean_bone_name("NeckHead")
        assert "Neck" in result
        assert "Head" in result

    def test_numbers_removed(self):
        result = clean_bone_name("DEF-Spine_C_002")
        assert "002" not in result
        assert "2" not in result


class TestBuildCondDict:
    """Test the full build_cond_dict pipeline."""

    def test_structure(self):
        skeleton = _make_skeleton(5)
        cond = build_cond_dict(skeleton, "test_skel")
        assert "test_skel" in cond
        entry = cond["test_skel"]
        assert "parents" in entry
        assert "offsets" in entry
        assert "joints_names" in entry
        assert "joint_relations" in entry
        assert "joints_graph_dist" in entry
        assert "tpos_first_frame" in entry
        assert "mean" in entry
        assert "std" in entry

    def test_padded_names_length(self):
        skeleton = _make_skeleton(5)
        cond = build_cond_dict(skeleton)
        names = cond["blender_skeleton"]["joints_names"]
        assert len(names) == MAX_JOINTS
        # First 5 should be actual names, rest None
        assert all(n is not None for n in names[:5])
        assert all(n is None for n in names[5:])

    def test_parents_array(self):
        skeleton = _make_skeleton(3)
        cond = build_cond_dict(skeleton)
        parents = cond["blender_skeleton"]["parents"]
        assert parents[0] == -1  # root has no parent


class TestRotation6dBatch:
    """Test batch 6D → matrix conversion."""

    def test_identity_batch(self):
        from animation.ml.anytop_adapter import AnyTopAdapter
        r6d = np.array([[1, 0, 0, 0, 1, 0], [1, 0, 0, 0, 1, 0]])
        mats = AnyTopAdapter._rotation_6d_to_matrix_batch(r6d)
        assert mats.shape == (2, 3, 3)
        np.testing.assert_allclose(mats[0], np.eye(3), atol=1e-6)

    def test_orthogonal_output(self):
        """Resulting matrices should be orthogonal (R^T R = I)."""
        from animation.ml.anytop_adapter import AnyTopAdapter
        r6d = np.array([[0.7, 0.7, 0, -0.7, 0.7, 0]])
        mats = AnyTopAdapter._rotation_6d_to_matrix_batch(r6d)
        product = mats[0].T @ mats[0]
        np.testing.assert_allclose(product, np.eye(3), atol=1e-6)
