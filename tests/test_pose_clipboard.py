"""Tests for animation.pose_clipboard — axis detection and bone naming."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# ===========================================================================
# Test: _detect_mirror_axis
# ===========================================================================

class TestDetectMirrorAxis:
    """Verify auto-detection of the mirror (lateral) axis."""

    def _make_armature(self, bone_positions):
        armature = MagicMock()
        bones_dict = {}
        for name, pos in bone_positions.items():
            bone = SimpleNamespace(head_local=pos)
            bones_dict[name] = bone
        armature.data.bones.get = lambda n: bones_dict.get(n)
        return armature

    def test_x_axis_detected_for_standard_rig(self):
        from animation.pose_clipboard import _detect_mirror_axis

        armature = self._make_armature({
            "CTRL-Wrap_arm_L_FK_upper": (1.0, 0.0, 1.5),
            "CTRL-Wrap_arm_R_FK_upper": (-1.0, 0.0, 1.5),
            "CTRL-Wrap_leg_L_FK_upper": (0.5, 0.0, 0.8),
            "CTRL-Wrap_leg_R_FK_upper": (-0.5, 0.0, 0.8),
        })
        names = ["CTRL-Wrap_arm_L_FK_upper", "CTRL-Wrap_arm_R_FK_upper",
                 "CTRL-Wrap_leg_L_FK_upper", "CTRL-Wrap_leg_R_FK_upper"]
        assert _detect_mirror_axis(armature, names) == 0

    def test_y_axis_detected_when_lateral_is_y(self):
        from animation.pose_clipboard import _detect_mirror_axis

        armature = self._make_armature({
            "CTRL-Wrap_arm_L_FK_upper": (0.0, 1.0, 1.5),
            "CTRL-Wrap_arm_R_FK_upper": (0.0, -1.0, 1.5),
        })
        names = ["CTRL-Wrap_arm_L_FK_upper", "CTRL-Wrap_arm_R_FK_upper"]
        assert _detect_mirror_axis(armature, names) == 1

    def test_default_x_when_no_pairs(self):
        from animation.pose_clipboard import _detect_mirror_axis

        armature = self._make_armature({
            "CTRL-Wrap_spine_C_FK_hips": (0.0, 0.0, 1.0),
        })
        assert _detect_mirror_axis(armature, ["CTRL-Wrap_spine_C_FK_hips"]) == 0

    def test_ignores_missing_bones(self):
        from animation.pose_clipboard import _detect_mirror_axis

        armature = self._make_armature({
            "CTRL-Wrap_arm_L_FK_upper": (1.0, 0.0, 1.5),
        })
        assert _detect_mirror_axis(armature, ["CTRL-Wrap_arm_L_FK_upper"]) == 0


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
