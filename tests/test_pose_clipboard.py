"""Tests for animation.pose_clipboard — mirror math and axis detection."""

import math
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# ===========================================================================
# Test: _mirror_transform
# ===========================================================================

class TestMirrorTransform:
    """Verify transform mirroring for location, quaternion, and euler."""

    def _make_transform(self, loc=(0, 0, 0), quat=(1, 0, 0, 0),
                        euler=(0, 0, 0), rot_mode='QUATERNION'):
        return {
            'location': loc,
            'rotation_mode': rot_mode,
            'rotation_quaternion': quat,
            'rotation_euler': euler,
            'scale': (1, 1, 1),
        }

    def test_mirror_location_x_axis(self):
        """Mirror across X: negate X component of location."""
        from animation.pose_clipboard import _mirror_transform

        t = self._make_transform(loc=(1.0, 2.0, 3.0))
        result = _mirror_transform(t, axis=0)
        assert result['location'] == (-1.0, 2.0, 3.0)

    def test_mirror_location_y_axis(self):
        """Mirror across Y: negate Y component of location."""
        from animation.pose_clipboard import _mirror_transform

        t = self._make_transform(loc=(1.0, 2.0, 3.0))
        result = _mirror_transform(t, axis=1)
        assert result['location'] == (1.0, -2.0, 3.0)

    def test_mirror_location_z_axis(self):
        """Mirror across Z: negate Z component of location."""
        from animation.pose_clipboard import _mirror_transform

        t = self._make_transform(loc=(1.0, 2.0, 3.0))
        result = _mirror_transform(t, axis=2)
        assert result['location'] == (1.0, 2.0, -3.0)

    def test_mirror_quaternion_x_axis(self):
        """Mirror across X: negate Y and Z components of quaternion."""
        from animation.pose_clipboard import _mirror_transform

        t = self._make_transform(quat=(0.7, 0.1, 0.3, 0.5))
        result = _mirror_transform(t, axis=0)
        w, x, y, z = result['rotation_quaternion']
        assert (w, x) == (0.7, 0.1)
        assert y == pytest.approx(-0.3)
        assert z == pytest.approx(-0.5)

    def test_mirror_quaternion_y_axis(self):
        """Mirror across Y: negate X and Z components of quaternion."""
        from animation.pose_clipboard import _mirror_transform

        t = self._make_transform(quat=(0.7, 0.1, 0.3, 0.5))
        result = _mirror_transform(t, axis=1)
        w, x, y, z = result['rotation_quaternion']
        assert (w, y) == (0.7, 0.3)
        assert x == pytest.approx(-0.1)
        assert z == pytest.approx(-0.5)

    def test_mirror_quaternion_z_axis(self):
        """Mirror across Z: negate X and Y components of quaternion."""
        from animation.pose_clipboard import _mirror_transform

        t = self._make_transform(quat=(0.7, 0.1, 0.3, 0.5))
        result = _mirror_transform(t, axis=2)
        w, x, y, z = result['rotation_quaternion']
        assert (w, z) == (0.7, 0.5)
        assert x == pytest.approx(-0.1)
        assert y == pytest.approx(-0.3)

    def test_mirror_euler_x_axis(self):
        """Mirror across X: negate Y and Z euler components."""
        from animation.pose_clipboard import _mirror_transform

        t = self._make_transform(euler=(0.5, 0.3, 0.1), rot_mode='XYZ')
        result = _mirror_transform(t, axis=0)
        ex, ey, ez = result['rotation_euler']
        assert ex == 0.5
        assert ey == pytest.approx(-0.3)
        assert ez == pytest.approx(-0.1)

    def test_mirror_preserves_scale(self):
        """Scale should never be modified by mirror."""
        from animation.pose_clipboard import _mirror_transform

        t = self._make_transform()
        t['scale'] = (2.0, 3.0, 4.0)
        result = _mirror_transform(t, axis=0)
        assert result['scale'] == (2.0, 3.0, 4.0)

    def test_mirror_preserves_rotation_mode(self):
        """rotation_mode should pass through unchanged."""
        from animation.pose_clipboard import _mirror_transform

        t = self._make_transform(rot_mode='XYZ')
        result = _mirror_transform(t, axis=0)
        assert result['rotation_mode'] == 'XYZ'

    def test_double_mirror_is_identity(self):
        """Mirroring twice should return the original transform."""
        from animation.pose_clipboard import _mirror_transform

        t = self._make_transform(
            loc=(1.5, -2.3, 0.7),
            quat=(0.7, 0.1, 0.3, 0.5),
            euler=(0.5, -0.3, 0.1),
        )
        result = _mirror_transform(_mirror_transform(t, axis=0), axis=0)
        for i in range(3):
            assert result['location'][i] == pytest.approx(t['location'][i])
        for i in range(4):
            assert result['rotation_quaternion'][i] == pytest.approx(
                t['rotation_quaternion'][i])
        for i in range(3):
            assert result['rotation_euler'][i] == pytest.approx(
                t['rotation_euler'][i])


# ===========================================================================
# Test: _detect_mirror_axis
# ===========================================================================

class TestDetectMirrorAxis:
    """Verify auto-detection of the mirror (lateral) axis."""

    def _make_armature(self, bone_positions):
        """Create mock armature with data.bones.get() returning bones with head_local."""
        armature = MagicMock()
        bones_dict = {}
        for name, pos in bone_positions.items():
            bone = SimpleNamespace(head_local=pos)
            bones_dict[name] = bone
        armature.data.bones.get = lambda n: bones_dict.get(n)
        return armature

    def test_x_axis_detected_for_standard_rig(self):
        """L/R bones offset on X should yield axis=0."""
        from animation.pose_clipboard import _detect_mirror_axis

        armature = self._make_armature({
            "CTRL-Wrap_arm_L_FK_upper": (1.0, 0.0, 1.5),
            "CTRL-Wrap_arm_R_FK_upper": (-1.0, 0.0, 1.5),
            "CTRL-Wrap_leg_L_FK_upper": (0.5, 0.0, 0.8),
            "CTRL-Wrap_leg_R_FK_upper": (-0.5, 0.0, 0.8),
        })
        names = list(armature.data.bones.get("CTRL-Wrap_arm_L_FK_upper") and
                     ["CTRL-Wrap_arm_L_FK_upper", "CTRL-Wrap_arm_R_FK_upper",
                      "CTRL-Wrap_leg_L_FK_upper", "CTRL-Wrap_leg_R_FK_upper"])
        result = _detect_mirror_axis(armature, names)
        assert result == 0

    def test_y_axis_detected_when_lateral_is_y(self):
        """L/R bones offset on Y should yield axis=1."""
        from animation.pose_clipboard import _detect_mirror_axis

        armature = self._make_armature({
            "CTRL-Wrap_arm_L_FK_upper": (0.0, 1.0, 1.5),
            "CTRL-Wrap_arm_R_FK_upper": (0.0, -1.0, 1.5),
        })
        names = ["CTRL-Wrap_arm_L_FK_upper", "CTRL-Wrap_arm_R_FK_upper"]
        result = _detect_mirror_axis(armature, names)
        assert result == 1

    def test_default_x_when_no_pairs(self):
        """With no L/R pairs, default to axis=0 (X)."""
        from animation.pose_clipboard import _detect_mirror_axis

        armature = self._make_armature({
            "CTRL-Wrap_spine_C_FK_hips": (0.0, 0.0, 1.0),
        })
        names = ["CTRL-Wrap_spine_C_FK_hips"]
        result = _detect_mirror_axis(armature, names)
        assert result == 0

    def test_ignores_bones_missing_from_armature(self):
        """Pairs where one bone doesn't exist should be skipped."""
        from animation.pose_clipboard import _detect_mirror_axis

        armature = self._make_armature({
            "CTRL-Wrap_arm_L_FK_upper": (1.0, 0.0, 1.5),
            # R bone missing
        })
        names = ["CTRL-Wrap_arm_L_FK_upper"]
        result = _detect_mirror_axis(armature, names)
        assert result == 0  # default


# ===========================================================================
# Test: mirror_name on CTRL bones
# ===========================================================================

class TestMirrorNameCtrlBones:
    """Verify mirror_name works correctly with CTRL-Wrap_ naming."""

    def test_swap_l_to_r(self):
        from core.utils import mirror_name
        assert mirror_name("CTRL-Wrap_arm_L_FK_upper_arm") == "CTRL-Wrap_arm_R_FK_upper_arm"

    def test_swap_r_to_l(self):
        from core.utils import mirror_name
        assert mirror_name("CTRL-Wrap_leg_R_IK_target") == "CTRL-Wrap_leg_L_IK_target"

    def test_center_bone_unchanged(self):
        from core.utils import mirror_name
        assert mirror_name("CTRL-Wrap_spine_C_FK_hips") == "CTRL-Wrap_spine_C_FK_hips"

    def test_ik_pole_swap(self):
        from core.utils import mirror_name
        assert mirror_name("CTRL-Wrap_arm_L_IK_pole") == "CTRL-Wrap_arm_R_IK_pole"
