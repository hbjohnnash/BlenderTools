"""Tests for wrap rig features: sync constraints, joint limits, smart keyframe.

These tests run outside Blender using mocked bpy objects from conftest.py.
They verify the LOGIC of constraint creation, influence toggling, and
keyframe insertion without requiring a live Blender session.
"""

import math
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.constants import WRAP_CONSTRAINT_PREFIX, WRAP_CTRL_PREFIX, WRAP_MCH_PREFIX

# ---------------------------------------------------------------------------
# Helpers — lightweight mock objects for wrap rig testing
# ---------------------------------------------------------------------------

class _ConstraintList(list):
    """List subclass mimicking Blender's constraint collection with .new()."""

    def new(self, ctype):
        c = _make_constraint(ctype, f"new_{ctype}", 0.0)
        self.append(c)
        return c


def _make_constraint(ctype, name, influence=1.0):
    """Create a mock constraint with type, name, and influence."""
    con = MagicMock()
    con.type = ctype
    con.name = name
    con.influence = influence
    return con


def _make_pose_bone(name, constraints=None):
    """Create a mock pose bone with optional constraints."""
    pb = MagicMock()
    pb.name = name
    pb.constraints = _ConstraintList(constraints or [])
    pb.use_ik_limit_x = False
    pb.use_ik_limit_y = False
    pb.use_ik_limit_z = False
    return pb


def _make_bone_item(chain_id, role, skip=False):
    """Create a mock scan bone item."""
    item = SimpleNamespace()
    item.chain_id = chain_id
    item.role = role
    item.skip = skip
    item.bone_name = f"orig_{role}"
    item.side = "L"
    item.module_type = "leg"
    return item


def _make_chain_item(chain_id, module_type="leg", ik_active=False):
    """Create a mock scan chain item."""
    item = SimpleNamespace()
    item.chain_id = chain_id
    item.module_type = module_type
    item.side = "L"
    item.ik_enabled = True
    item.fk_enabled = True
    item.ik_active = ik_active
    item.ik_snap = True
    item.ik_type = "STANDARD"
    item.ik_limits = False
    return item


def _make_armature(chain_id, roles, ik_roles=None):
    """Build a mock armature with MCH, FK CTRL, IK target/pole bones.

    Args:
        chain_id: e.g. "leg_L"
        roles: list of roles e.g. ["upper_leg", "lower_leg", "foot", "toe"]
        ik_roles: roles that have IK constraints on MCH (default: all except last)

    IK constraints are placed on ALL ik_roles' MCH bones (matching the check
    in _get_independent_fk_pbones which looks per-bone).  A chain_count
    attribute is set on each so _add_sync_constraints can find the IK chain.
    """
    if ik_roles is None:
        ik_roles = set(roles[:-1])  # all except toe

    bones = {}
    bone_items = []
    ik_target_name = f"{WRAP_CTRL_PREFIX}{chain_id}_IK_target"

    # Fake positions along Y axis so pole displacement math works
    spacing = 0.3

    for idx, role in enumerate(roles):
        mch_name = f"{WRAP_MCH_PREFIX}{chain_id}_{role}"
        ctrl_name = f"{WRAP_CTRL_PREFIX}{chain_id}_FK_{role}"

        mch_constraints = []
        # FK COPY_TRANSFORMS on MCH (from FK CTRL)
        mch_constraints.append(
            _make_constraint('COPY_TRANSFORMS',
                             f"{WRAP_CONSTRAINT_PREFIX}FK", 1.0))
        # IK constraint on MCH (if this role has IK)
        if role in ik_roles:
            ik_con = _make_constraint(
                'IK', f"{WRAP_CONSTRAINT_PREFIX}IK", 0.0)
            ik_con.chain_count = len(ik_roles)
            ik_con.subtarget = ik_target_name
            ik_con.pole_target = None
            ik_con.pole_subtarget = ""
            mch_constraints.append(ik_con)

        mch_pb = _make_pose_bone(mch_name, mch_constraints)
        # Mock bone.head_local / tail_local with _MockVector for arithmetic
        from conftest import _MockVector
        mch_pb.bone = SimpleNamespace(
            head_local=_MockVector((0, idx * spacing, 0)),
            tail_local=_MockVector((0, (idx + 1) * spacing, 0)),
        )
        mch_pb.parent = None
        bones[mch_name] = mch_pb
        bones[ctrl_name] = _make_pose_bone(ctrl_name)
        bone_items.append(_make_bone_item(chain_id, role))

    # Wire up MCH parent chain
    for i in range(1, len(roles)):
        parent_mch = f"{WRAP_MCH_PREFIX}{chain_id}_{roles[i - 1]}"
        child_mch = f"{WRAP_MCH_PREFIX}{chain_id}_{roles[i]}"
        if child_mch in bones and parent_mch in bones:
            bones[child_mch].parent = bones[parent_mch]

    # IK target and pole
    ik_pole_name = f"{WRAP_CTRL_PREFIX}{chain_id}_IK_pole"
    bones[ik_target_name] = _make_pose_bone(ik_target_name)
    bones[ik_pole_name] = _make_pose_bone(ik_pole_name)

    armature = MagicMock()
    armature.pose.bones.get = lambda name: bones.get(name)
    armature.pose.bones.__iter__ = lambda self: iter(bones.values())

    sd = SimpleNamespace()
    sd.bones = bone_items
    sd.chains = [_make_chain_item(chain_id)]
    sd.has_wrap_rig = True
    sd.floor_enabled = False
    sd.floor_level = 0.0
    armature.bt_scan = sd

    return armature, bones, bone_items


# ===========================================================================
# Test: _get_independent_fk_pbones
# ===========================================================================

class TestGetIndependentFKPbones:
    """Tests for _get_independent_fk_pbones (smart_keyframe.py)."""

    def test_toe_is_independent(self):
        """Toe has no IK constraint on MCH → should be returned."""
        from animation.smart_keyframe import _get_independent_fk_pbones

        armature, bones, _ = _make_armature(
            "leg_L",
            ["upper_leg", "lower_leg", "foot", "toe"],
            ik_roles={"upper_leg", "lower_leg", "foot"},
        )

        result = _get_independent_fk_pbones(
            armature, armature.bt_scan, "leg_L")

        names = [pb.name for pb in result]
        assert f"{WRAP_CTRL_PREFIX}leg_L_FK_toe" in names

    def test_ik_bones_excluded(self):
        """Bones with IK constraints should NOT be returned."""
        from animation.smart_keyframe import _get_independent_fk_pbones

        armature, bones, _ = _make_armature(
            "leg_L",
            ["upper_leg", "lower_leg", "foot", "toe"],
            ik_roles={"upper_leg", "lower_leg", "foot"},
        )

        result = _get_independent_fk_pbones(
            armature, armature.bt_scan, "leg_L")

        names = [pb.name for pb in result]
        assert f"{WRAP_CTRL_PREFIX}leg_L_FK_upper_leg" not in names
        assert f"{WRAP_CTRL_PREFIX}leg_L_FK_lower_leg" not in names
        assert f"{WRAP_CTRL_PREFIX}leg_L_FK_foot" not in names

    def test_all_ik_returns_empty(self):
        """If all bones have IK, nothing is independent."""
        from animation.smart_keyframe import _get_independent_fk_pbones

        armature, _, _ = _make_armature(
            "arm_L",
            ["upper_arm", "lower_arm"],
            ik_roles={"upper_arm", "lower_arm"},
        )

        result = _get_independent_fk_pbones(
            armature, armature.bt_scan, "arm_L")
        assert result == []

    def test_skipped_bones_excluded(self):
        """Bones with skip=True should not be returned."""
        from animation.smart_keyframe import _get_independent_fk_pbones

        armature, _, bone_items = _make_armature(
            "leg_L",
            ["upper_leg", "lower_leg", "foot", "toe"],
            ik_roles={"upper_leg", "lower_leg", "foot"},
        )
        # Mark toe as skipped
        bone_items[-1].skip = True

        result = _get_independent_fk_pbones(
            armature, armature.bt_scan, "leg_L")
        assert result == []


# ===========================================================================
# Test: _add_sync_constraints
# ===========================================================================

class TestAddSyncConstraints:
    """Tests for _add_sync_constraints (wrap_assembly.py)."""

    def test_fk_sync_added_to_ik_bones(self):
        """FK CTRL bones with IK alternative get a sync constraint."""
        from rigging.scanner.wrap_assembly import _add_sync_constraints

        armature, bones, _ = _make_armature(
            "leg_L",
            ["upper_leg", "lower_leg", "foot", "toe"],
            ik_roles={"upper_leg", "lower_leg", "foot"},
        )

        chain_bones = ["orig_upper_leg", "orig_lower_leg",
                        "orig_foot", "orig_toe"]
        bones_info = {
            "orig_upper_leg": {"role": "upper_leg"},
            "orig_lower_leg": {"role": "lower_leg"},
            "orig_foot": {"role": "foot"},
            "orig_toe": {"role": "toe"},
        }

        _add_sync_constraints(armature, "leg_L", chain_bones, bones_info)

        # FK bones with IK should have FK_sync constraint
        for role in ["upper_leg", "lower_leg", "foot"]:
            ctrl = bones[f"{WRAP_CTRL_PREFIX}leg_L_FK_{role}"]
            sync_cons = [c for c in ctrl.constraints
                         if hasattr(c, 'name')
                         and c.name == f"{WRAP_CONSTRAINT_PREFIX}FK_sync"]
            assert len(sync_cons) >= 1, f"Missing FK_sync on {role}"

    def test_no_fk_sync_on_toe(self):
        """Toe (no IK alternative) should NOT get a sync constraint."""
        from rigging.scanner.wrap_assembly import _add_sync_constraints

        armature, bones, _ = _make_armature(
            "leg_L",
            ["upper_leg", "lower_leg", "foot", "toe"],
            ik_roles={"upper_leg", "lower_leg", "foot"},
        )

        chain_bones = ["orig_upper_leg", "orig_lower_leg",
                        "orig_foot", "orig_toe"]
        bones_info = {
            "orig_upper_leg": {"role": "upper_leg"},
            "orig_lower_leg": {"role": "lower_leg"},
            "orig_foot": {"role": "foot"},
            "orig_toe": {"role": "toe"},
        }

        _add_sync_constraints(armature, "leg_L", chain_bones, bones_info)

        toe_ctrl = bones[f"{WRAP_CTRL_PREFIX}leg_L_FK_toe"]
        sync_cons = [c for c in toe_ctrl.constraints
                     if hasattr(c, 'name')
                     and c.name == f"{WRAP_CONSTRAINT_PREFIX}FK_sync"]
        assert len(sync_cons) == 0, "Toe should not have FK_sync"

    def test_no_ik_sync_on_target(self):
        """IK target must NOT get an IK_sync constraint (avoids depsgraph cycle)."""
        from rigging.scanner.wrap_assembly import _add_sync_constraints

        armature, bones, _ = _make_armature(
            "leg_L",
            ["upper_leg", "lower_leg", "foot", "toe"],
        )

        chain_bones = ["orig_upper_leg", "orig_lower_leg",
                        "orig_foot", "orig_toe"]
        bones_info = {
            "orig_upper_leg": {"role": "upper_leg"},
            "orig_lower_leg": {"role": "lower_leg"},
            "orig_foot": {"role": "foot"},
            "orig_toe": {"role": "toe"},
        }

        _add_sync_constraints(armature, "leg_L", chain_bones, bones_info)

        ik_target = bones[f"{WRAP_CTRL_PREFIX}leg_L_IK_target"]
        sync_cons = [c for c in ik_target.constraints
                     if hasattr(c, 'name')
                     and c.name == f"{WRAP_CONSTRAINT_PREFIX}IK_sync"]
        assert len(sync_cons) == 0, "IK target must not have IK_sync"

    def test_no_ik_pole_sync(self):
        """IK pole must NOT get an IK_pole_sync constraint (avoids depsgraph cycle)."""
        from rigging.scanner.wrap_assembly import _add_sync_constraints

        armature, bones, _ = _make_armature(
            "leg_L",
            ["upper_leg", "lower_leg", "foot", "toe"],
        )

        chain_bones = ["orig_upper_leg", "orig_lower_leg",
                        "orig_foot", "orig_toe"]
        bones_info = {
            "orig_upper_leg": {"role": "upper_leg"},
            "orig_lower_leg": {"role": "lower_leg"},
            "orig_foot": {"role": "foot"},
            "orig_toe": {"role": "toe"},
        }

        _add_sync_constraints(armature, "leg_L", chain_bones, bones_info)

        ik_pole = bones[f"{WRAP_CTRL_PREFIX}leg_L_IK_pole"]
        sync_cons = [c for c in ik_pole.constraints
                     if hasattr(c, 'name')
                     and c.name == f"{WRAP_CONSTRAINT_PREFIX}IK_pole_sync"]
        assert len(sync_cons) == 0, "IK pole must not have IK_pole_sync"

    def test_fk_sync_starts_disabled(self):
        """FK_sync should start at influence=0 (FK mode default)."""
        from rigging.scanner.wrap_assembly import _add_sync_constraints

        armature, bones, _ = _make_armature(
            "leg_L",
            ["upper_leg", "lower_leg"],
            ik_roles={"upper_leg", "lower_leg"},
        )

        chain_bones = ["orig_upper_leg", "orig_lower_leg"]
        bones_info = {
            "orig_upper_leg": {"role": "upper_leg"},
            "orig_lower_leg": {"role": "lower_leg"},
        }

        _add_sync_constraints(armature, "leg_L", chain_bones, bones_info)

        ctrl = bones[f"{WRAP_CTRL_PREFIX}leg_L_FK_upper_leg"]
        sync_con = [c for c in ctrl.constraints
                    if hasattr(c, 'name')
                    and c.name == f"{WRAP_CONSTRAINT_PREFIX}FK_sync"]
        assert sync_con[0].influence == 0.0


# ===========================================================================
# Test: toggle_joint_limits
# ===========================================================================

class TestToggleJointLimits:
    """Tests for toggle_joint_limits (wrap_assembly.py)."""

    def test_enable_sets_ik_limits(self):
        """Enabling limits should set use_ik_limit_x/y/z to True on MCH."""
        from rigging.scanner.wrap_assembly import toggle_joint_limits

        armature, bones, _ = _make_armature(
            "leg_L", ["upper_leg", "lower_leg"])

        toggle_joint_limits(armature, "leg_L", True)

        for role in ["upper_leg", "lower_leg"]:
            mch = bones[f"{WRAP_MCH_PREFIX}leg_L_{role}"]
            assert mch.use_ik_limit_x is True
            assert mch.use_ik_limit_y is True
            assert mch.use_ik_limit_z is True

    def test_disable_clears_ik_limits(self):
        """Disabling limits should set use_ik_limit_x/y/z to False."""
        from rigging.scanner.wrap_assembly import toggle_joint_limits

        armature, bones, _ = _make_armature(
            "leg_L", ["upper_leg", "lower_leg"])

        # Enable then disable
        toggle_joint_limits(armature, "leg_L", True)
        toggle_joint_limits(armature, "leg_L", False)

        for role in ["upper_leg", "lower_leg"]:
            mch = bones[f"{WRAP_MCH_PREFIX}leg_L_{role}"]
            assert mch.use_ik_limit_x is False
            assert mch.use_ik_limit_y is False
            assert mch.use_ik_limit_z is False

    def test_enable_sets_fk_limit_constraint(self):
        """Enabling limits should set FK LIMIT_ROTATION to influence=1."""
        from rigging.scanner.wrap_assembly import toggle_joint_limits

        armature, bones, _ = _make_armature(
            "leg_L", ["upper_leg", "lower_leg"])

        # Add a LIMIT_ROTATION constraint to FK CTRL
        for role in ["upper_leg", "lower_leg"]:
            ctrl = bones[f"{WRAP_CTRL_PREFIX}leg_L_FK_{role}"]
            limit_con = _make_constraint(
                'LIMIT_ROTATION',
                f"{WRAP_CONSTRAINT_PREFIX}FK_limit", 0.0)
            ctrl.constraints.append(limit_con)

        toggle_joint_limits(armature, "leg_L", True)

        for role in ["upper_leg", "lower_leg"]:
            ctrl = bones[f"{WRAP_CTRL_PREFIX}leg_L_FK_{role}"]
            for c in ctrl.constraints:
                if (c.type == 'LIMIT_ROTATION'
                        and c.name.startswith(WRAP_CONSTRAINT_PREFIX)):
                    assert c.influence == 1.0


# ===========================================================================
# Test: _compute_joint_limits
# ===========================================================================

class TestComputeJointLimits:
    """Tests for _compute_joint_limits (wrap_assembly.py)."""

    @patch("rigging.scanner.wrap_assembly._detect_bend_axis",
           return_value=('X', 1))
    def test_mid_joint_bend_axis(self, mock_bend):
        """Mid-joint (elbow/knee) should get 160° on bend axis."""
        from rigging.scanner.wrap_assembly import _compute_joint_limits

        armature = MagicMock()
        limits = _compute_joint_limits(
            armature, "MCH-Wrap_leg_L_lower_leg", "lower_leg", "leg")

        assert 'X' in limits
        lo, hi, stiff = limits['X']
        assert lo == pytest.approx(0.0)
        assert hi == pytest.approx(math.radians(160))

    @patch("rigging.scanner.wrap_assembly._detect_bend_axis",
           return_value=('X', -1))
    def test_mid_joint_negative_bend(self, mock_bend):
        """Negative bend sign should flip the range."""
        from rigging.scanner.wrap_assembly import _compute_joint_limits

        armature = MagicMock()
        limits = _compute_joint_limits(
            armature, "MCH-Wrap_leg_L_lower_leg", "lower_leg", "leg")

        lo, hi, _ = limits['X']
        assert lo == pytest.approx(math.radians(-160))
        assert hi == pytest.approx(0.0)

    @patch("rigging.scanner.wrap_assembly._detect_bend_axis",
           return_value=('X', 1))
    def test_mid_joint_secondary_axes_locked(self, mock_bend):
        """Non-bend axes should be tightly constrained (±5°)."""
        from rigging.scanner.wrap_assembly import _compute_joint_limits

        armature = MagicMock()
        limits = _compute_joint_limits(
            armature, "MCH-Wrap_leg_L_lower_leg", "lower_leg", "leg")

        for axis in ('Y', 'Z'):
            lo, hi, stiff = limits[axis]
            assert lo == pytest.approx(math.radians(-5))
            assert hi == pytest.approx(math.radians(5))
            assert stiff == pytest.approx(0.9)

    def test_tail_limits(self):
        """Tail module should get ±45° on all axes."""
        from rigging.scanner.wrap_assembly import _compute_joint_limits

        armature = MagicMock()
        limits = _compute_joint_limits(
            armature, "MCH-Wrap_tail_C_bone1", "bone1", "tail")

        for axis in ('X', 'Y', 'Z'):
            lo, hi, stiff = limits[axis]
            assert lo == pytest.approx(math.radians(-45))
            assert hi == pytest.approx(math.radians(45))
            assert stiff == pytest.approx(0.1)

    def test_tentacle_limits(self):
        """Tentacle module should get ±60° on all axes."""
        from rigging.scanner.wrap_assembly import _compute_joint_limits

        armature = MagicMock()
        limits = _compute_joint_limits(
            armature, "MCH-Wrap_tentacle_L_seg1", "seg1", "tentacle")

        for axis in ('X', 'Y', 'Z'):
            lo, hi, _ = limits[axis]
            assert lo == pytest.approx(math.radians(-60))
            assert hi == pytest.approx(math.radians(60))

    def test_generic_limits(self):
        """Generic module should get ±90° on all axes."""
        from rigging.scanner.wrap_assembly import _compute_joint_limits

        armature = MagicMock()
        limits = _compute_joint_limits(
            armature, "MCH-Wrap_spine_C_chest", "chest", "spine")

        for axis in ('X', 'Y', 'Z'):
            lo, hi, stiff = limits[axis]
            assert lo == pytest.approx(math.radians(-90))
            assert hi == pytest.approx(math.radians(90))
            assert stiff == pytest.approx(0.0)


# ===========================================================================
# Test: _key_chain_influences
# ===========================================================================

class TestKeyChainInfluences:
    """Tests for _key_chain_influences (smart_keyframe.py)."""

    def test_ik_mode_disables_fk_on_ik_bones(self):
        """In IK mode, COPY_TRANSFORMS on MCH bones with IK should go to 0."""
        from animation.smart_keyframe import _key_chain_influences

        armature, bones, _ = _make_armature(
            "leg_L",
            ["upper_leg", "lower_leg", "foot", "toe"],
            ik_roles={"upper_leg", "lower_leg", "foot"},
        )
        armature.animation_data = None

        _key_chain_influences(
            armature, armature.bt_scan, "leg_L", use_ik=True, frame=1)

        # MCH bones with IK: COPY_TRANSFORMS should be 0
        for role in ["upper_leg", "lower_leg", "foot"]:
            mch = bones[f"{WRAP_MCH_PREFIX}leg_L_{role}"]
            fk_con = mch.constraints[0]  # First constraint is FK
            assert fk_con.type == 'COPY_TRANSFORMS'
            assert fk_con.influence == 0.0

    def test_ik_mode_keeps_fk_on_toe(self):
        """In IK mode, toe (no IK) should keep FK at 1.0."""
        from animation.smart_keyframe import _key_chain_influences

        armature, bones, _ = _make_armature(
            "leg_L",
            ["upper_leg", "lower_leg", "foot", "toe"],
            ik_roles={"upper_leg", "lower_leg", "foot"},
        )
        armature.animation_data = None

        _key_chain_influences(
            armature, armature.bt_scan, "leg_L", use_ik=True, frame=1)

        toe_mch = bones[f"{WRAP_MCH_PREFIX}leg_L_toe"]
        fk_con = toe_mch.constraints[0]
        assert fk_con.type == 'COPY_TRANSFORMS'
        assert fk_con.influence == 1.0

    def test_fk_mode_enables_fk(self):
        """In FK mode, COPY_TRANSFORMS on all MCH bones should be 1.0."""
        from animation.smart_keyframe import _key_chain_influences

        armature, bones, _ = _make_armature(
            "leg_L",
            ["upper_leg", "lower_leg", "foot", "toe"],
            ik_roles={"upper_leg", "lower_leg", "foot"},
        )
        armature.animation_data = None

        _key_chain_influences(
            armature, armature.bt_scan, "leg_L", use_ik=False, frame=1)

        for role in ["upper_leg", "lower_leg", "foot", "toe"]:
            mch = bones[f"{WRAP_MCH_PREFIX}leg_L_{role}"]
            fk_con = mch.constraints[0]
            assert fk_con.influence == 1.0

    def test_ik_mode_enables_ik_constraints(self):
        """In IK mode, IK constraints should be set to 1.0."""
        from animation.smart_keyframe import _key_chain_influences

        armature, bones, _ = _make_armature(
            "leg_L",
            ["upper_leg", "lower_leg", "foot"],
            ik_roles={"upper_leg", "lower_leg", "foot"},
        )
        armature.animation_data = None

        _key_chain_influences(
            armature, armature.bt_scan, "leg_L", use_ik=True, frame=1)

        for role in ["upper_leg", "lower_leg", "foot"]:
            mch = bones[f"{WRAP_MCH_PREFIX}leg_L_{role}"]
            ik_con = mch.constraints[1]  # Second constraint is IK
            assert ik_con.type == 'IK'
            assert ik_con.influence == 1.0

    def test_keyframe_insert_called(self):
        """Constraint influences should be keyframed."""
        from animation.smart_keyframe import _key_chain_influences

        armature, bones, _ = _make_armature(
            "leg_L", ["upper_leg", "lower_leg"],
            ik_roles={"upper_leg", "lower_leg"})
        armature.animation_data = None

        _key_chain_influences(
            armature, armature.bt_scan, "leg_L", use_ik=True, frame=5)

        # Check that keyframe_insert was called
        assert armature.keyframe_insert.called

    def test_fk_sync_influence_keyed_in_ik_mode(self):
        """FK_sync constraints on CTRL bones should be keyed in IK mode."""
        from animation.smart_keyframe import _key_chain_influences

        armature, bones, _ = _make_armature(
            "leg_L", ["upper_leg", "lower_leg"],
            ik_roles={"upper_leg", "lower_leg"})
        armature.animation_data = None

        # Add FK_sync constraint to FK CTRL bones
        for role in ["upper_leg", "lower_leg"]:
            ctrl = bones[f"{WRAP_CTRL_PREFIX}leg_L_FK_{role}"]
            sync_con = _make_constraint(
                'COPY_TRANSFORMS',
                f"{WRAP_CONSTRAINT_PREFIX}FK_sync", 0.0)
            ctrl.constraints.append(sync_con)

        _key_chain_influences(
            armature, armature.bt_scan, "leg_L", use_ik=True, frame=1)

        # FK_sync should be set to 1.0 in IK mode
        for role in ["upper_leg", "lower_leg"]:
            ctrl = bones[f"{WRAP_CTRL_PREFIX}leg_L_FK_{role}"]
            for c in ctrl.constraints:
                if (hasattr(c, 'name')
                        and c.name == f"{WRAP_CONSTRAINT_PREFIX}FK_sync"):
                    assert c.influence == 1.0


# ===========================================================================
# Test: floor contact (simplified)
# ===========================================================================

class TestFloorContact:
    """Tests for simplified floor contact (LIMIT_LOCATION only)."""

    def test_no_wrap_rig_returns_error(self):
        """Should return error if no wrap rig."""
        from rigging.scanner.floor_contact import setup_floor_contact

        armature = MagicMock()
        armature.bt_scan.has_wrap_rig = False

        result = setup_floor_contact(armature)
        assert "error" in result

    def test_no_leg_chains_returns_error(self):
        """Should return error if no leg chains found."""
        from rigging.scanner.floor_contact import setup_floor_contact

        armature = MagicMock()
        armature.bt_scan.has_wrap_rig = True
        armature.bt_scan.chains = [_make_chain_item("arm_L", "arm")]

        result = setup_floor_contact(armature)
        assert "error" in result
