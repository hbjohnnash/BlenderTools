"""Tests for animation.ml.anytop_adapter — pure utility functions.

Tests the 6D rotation conversion and bone description generator,
which are pure math/string operations with no Blender dependency.
"""

import math

import numpy as np
import pytest

from animation.ml.anytop_adapter import AnyTopAdapter


class TestRotation6dToEuler:
    """Test 6D rotation representation → Euler angle conversion."""

    def test_identity_rotation(self):
        """Identity matrix columns [1,0,0, 0,1,0] should give ~zero Euler."""
        r6d = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        euler = AnyTopAdapter._rotation_6d_to_euler(r6d)
        for angle in euler:
            assert abs(angle) < 1e-6, f"Expected ~0, got {angle}"

    def test_90_degree_z_rotation(self):
        """90° around Z: col1=[0,1,0], col2=[-1,0,0]."""
        r6d = [0.0, 1.0, 0.0, -1.0, 0.0, 0.0]
        euler = AnyTopAdapter._rotation_6d_to_euler(r6d)
        # Z rotation should be ~90° (pi/2)
        assert abs(euler[2] - math.pi / 2) < 0.01

    def test_output_is_three_floats(self):
        """Should always return a tuple of 3 floats."""
        r6d = [0.7, 0.7, 0.0, -0.7, 0.7, 0.0]
        euler = AnyTopAdapter._rotation_6d_to_euler(r6d)
        assert len(euler) == 3
        for v in euler:
            assert isinstance(v, float)

    def test_non_orthogonal_input_gets_normalized(self):
        """Gram-Schmidt should handle non-orthogonal input gracefully."""
        # These vectors are NOT orthogonal — Gram-Schmidt should fix them
        r6d = [1.0, 0.5, 0.0, 0.5, 1.0, 0.0]
        euler = AnyTopAdapter._rotation_6d_to_euler(r6d)
        # Should not crash, and should return finite values
        for v in euler:
            assert math.isfinite(v)


class TestBoneDescription:
    """Test the automatic bone description generator."""

    def setup_method(self):
        self.adapter = AnyTopAdapter()

    def test_spine_bone(self):
        desc = self.adapter._bone_description("DEF-Spine_C_002")
        assert "spine" in desc

    def test_left_arm(self):
        desc = self.adapter._bone_description("DEF-Arm_L_Upper")
        assert "left" in desc
        assert "arm" in desc

    def test_right_leg(self):
        desc = self.adapter._bone_description("DEF-Leg_R_Thigh")
        assert "right" in desc

    def test_head_bone(self):
        desc = self.adapter._bone_description("DEF-NeckHead_C_Head")
        assert "head" in desc

    def test_unknown_bone_returns_generic(self):
        desc = self.adapter._bone_description("DEF-CustomThing_C_001")
        assert desc == "bone"

    def test_foot_bone(self):
        desc = self.adapter._bone_description("DEF-Leg_L_Foot")
        assert "foot" in desc


class TestFallbackGenerate:
    """Test the procedural fallback motion generator."""

    def test_output_shape(self):
        """Output should be (num_frames, num_joints, 6)."""
        result = AnyTopAdapter._fallback_generate(5, 30, "walking")
        assert result.shape == (30, 5, 6)

    def test_identity_rotation_by_default(self):
        """Default should set identity-like 6D rotation."""
        result = AnyTopAdapter._fallback_generate(3, 10, "idle")
        # First column X should be 1.0 (identity)
        assert result[0, 0, 0] == 1.0
        # Second column Y should be 1.0 (identity)
        assert result[0, 0, 4] == 1.0

    def test_walk_prompt_adds_motion(self):
        """Walk prompt should produce non-zero variation."""
        result = AnyTopAdapter._fallback_generate(3, 60, "a person walking")
        # Frame 0 and frame 30 should differ (oscillation)
        diff = np.abs(result[0] - result[30]).sum()
        assert diff > 0.0, "Walk should produce some motion"
