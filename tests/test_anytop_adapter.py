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

    @staticmethod
    def _make_skeleton(num_joints):
        """Create a minimal skeleton dict for fallback testing."""
        descs = ["spine bone", "left upper leg bone", "right upper leg bone",
                 "left upper arm bone", "right upper arm bone"]
        joints = []
        for i in range(num_joints):
            desc = descs[i] if i < len(descs) else "bone"
            joints.append({
                "name": f"bone_{i}",
                "parent": max(0, i - 1) if i > 0 else -1,
                "offset": [0, 0, 0.1],
                "description": desc,
            })
        return {"joints": joints}

    def test_output_shape(self):
        """Output should be (num_frames) lists of (num_joints) tuples."""
        skeleton = self._make_skeleton(5)
        rots, root_pos = AnyTopAdapter._fallback_generate(skeleton, 30, "walking")
        assert len(rots) == 30
        assert len(rots[0]) == 5
        assert len(rots[0][0]) == 3  # Euler XYZ
        assert len(root_pos) == 30

    def test_idle_near_zero(self):
        """Idle should produce small but non-identity rotations."""
        skeleton = self._make_skeleton(3)
        rots, _ = AnyTopAdapter._fallback_generate(skeleton, 10, "idle")
        # Spine bone (index 0) should have subtle motion
        all_zero = all(
            abs(rots[f][0][0]) < 1e-9 and abs(rots[f][0][1]) < 1e-9
            for f in range(10)
        )
        assert not all_zero, "Idle should produce subtle motion on spine"

    def test_walk_prompt_adds_motion(self):
        """Walk prompt should produce visible rotation on legs."""
        skeleton = self._make_skeleton(5)
        rots, _ = AnyTopAdapter._fallback_generate(skeleton, 60, "a person walking")
        # Left upper leg (index 1) should swing
        vals = [abs(rots[f][1][0]) for f in range(60)]
        assert max(vals) > 0.1, "Walk should produce visible leg swing"
