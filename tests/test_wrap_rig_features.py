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
# Test: _key_ik_switch (replaced _key_chain_influences)
# ===========================================================================

class TestKeyIkSwitch:
    """Tests for _key_ik_switch — keys the ik_switch custom property.

    In the new system, a single custom property per chain controls all
    constraint influences via drivers.  _key_ik_switch sets the property
    and inserts a keyframe with CONSTANT interpolation.
    """

    def _make_armature_with_prop(self, chain_id, roles, ik_roles=None,
                                  initial_value=0.0):
        """Build a mock armature with an ik_switch custom property."""
        armature, bones, items = _make_armature(chain_id, roles, ik_roles)
        armature.animation_data = None
        # Use a real dict for custom property access (__getitem__/__contains__)
        props = {f"ik_switch_{chain_id}": initial_value}
        armature.__getitem__ = lambda self, key: props[key]
        armature.__setitem__ = lambda self, key, val: props.__setitem__(key, val)
        armature.__contains__ = lambda self, key: key in props
        armature._props = props  # expose for assertions
        return armature, bones, items

    def test_ik_mode_sets_property_to_1(self):
        """In IK mode, ik_switch property should be 1.0."""
        from animation.smart_keyframe import _key_ik_switch

        armature, _, _ = self._make_armature_with_prop(
            "leg_L",
            ["upper_leg", "lower_leg", "foot", "toe"],
            ik_roles={"upper_leg", "lower_leg", "foot"},
            initial_value=0.0,
        )

        _key_ik_switch(armature, "leg_L", use_ik=True, frame=1)

        assert armature._props["ik_switch_leg_L"] == 1.0

    def test_fk_mode_sets_property_to_0(self):
        """In FK mode, ik_switch property should be 0.0."""
        from animation.smart_keyframe import _key_ik_switch

        armature, _, _ = self._make_armature_with_prop(
            "leg_L",
            ["upper_leg", "lower_leg", "foot", "toe"],
            ik_roles={"upper_leg", "lower_leg", "foot"},
            initial_value=1.0,
        )

        _key_ik_switch(armature, "leg_L", use_ik=False, frame=1)

        assert armature._props["ik_switch_leg_L"] == 0.0

    def test_keyframe_insert_called(self):
        """The ik_switch property should be keyframed."""
        from animation.smart_keyframe import _key_ik_switch

        armature, _, _ = self._make_armature_with_prop(
            "leg_L", ["upper_leg", "lower_leg"],
            ik_roles={"upper_leg", "lower_leg"},
        )

        _key_ik_switch(armature, "leg_L", use_ik=True, frame=5)

        assert armature.keyframe_insert.called

    def test_missing_property_is_noop(self):
        """If ik_switch property doesn't exist, _key_ik_switch does nothing."""
        from animation.smart_keyframe import _key_ik_switch

        armature, _, _ = _make_armature(
            "leg_L", ["upper_leg", "lower_leg"],
            ik_roles={"upper_leg", "lower_leg"})
        armature.animation_data = None
        # Mock __contains__ to return False for all keys
        armature.__contains__ = lambda self, key: False

        _key_ik_switch(armature, "leg_L", use_ik=True, frame=1)

        assert not armature.keyframe_insert.called


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

    def test_no_ik_limb_chains_returns_error(self):
        """Should return error if no arm or leg chains found."""
        from rigging.scanner.floor_contact import setup_floor_contact

        armature = MagicMock()
        armature.bt_scan.has_wrap_rig = True
        armature.bt_scan.chains = [_make_chain_item("spine_C", "spine")]

        result = setup_floor_contact(armature)
        assert "error" in result


# ===========================================================================
# Helpers — neck/head chain mock builder
# ===========================================================================

def _make_neck_head_armature(chain_id="neck_head_C", roles=None):
    """Build a mock armature for a neck/head chain with DAMPED_TRACK.

    Returns (armature, bones, bone_items).
    The head MCH gets a DAMPED_TRACK constraint (LookAt) instead of IK.
    """
    if roles is None:
        roles = ["neck", "head"]

    from conftest import _MockVector

    bones = {}
    bone_items = []
    lookat_name = f"{WRAP_CTRL_PREFIX}{chain_id}_LookAt_target"

    spacing = 0.3

    for idx, role in enumerate(roles):
        mch_name = f"{WRAP_MCH_PREFIX}{chain_id}_{role}"
        ctrl_name = f"{WRAP_CTRL_PREFIX}{chain_id}_FK_{role}"

        mch_constraints = []
        # FK COPY_TRANSFORMS on MCH
        mch_constraints.append(
            _make_constraint('COPY_TRANSFORMS',
                             f"{WRAP_CONSTRAINT_PREFIX}FK", 1.0))

        # DAMPED_TRACK on head MCH only
        if role == "head":
            dt_con = _make_constraint(
                'DAMPED_TRACK', f"{WRAP_CONSTRAINT_PREFIX}LookAt", 0.0)
            dt_con.target = MagicMock()
            dt_con.subtarget = lookat_name
            dt_con.track_axis = 'TRACK_Y'
            mch_constraints.append(dt_con)

        mch_pb = _make_pose_bone(mch_name, mch_constraints)
        mch_pb.bone = SimpleNamespace(
            head_local=_MockVector((0, idx * spacing, 1.6)),
            tail_local=_MockVector((0, (idx + 1) * spacing, 1.6)),
        )
        mch_pb.head = _MockVector((0, idx * spacing, 1.6))
        mch_pb.tail = _MockVector((0, (idx + 1) * spacing, 1.6))
        mch_pb.parent = None
        bones[mch_name] = mch_pb

        ctrl_pb = _make_pose_bone(ctrl_name)
        bones[ctrl_name] = ctrl_pb

        item = _make_bone_item(chain_id, role)
        item.module_type = "neck_head"
        bone_items.append(item)

    # Wire up parent chain
    for i in range(1, len(roles)):
        parent_mch = f"{WRAP_MCH_PREFIX}{chain_id}_{roles[i - 1]}"
        child_mch = f"{WRAP_MCH_PREFIX}{chain_id}_{roles[i]}"
        if child_mch in bones and parent_mch in bones:
            bones[child_mch].parent = bones[parent_mch]

    # LookAt target bone
    lookat_pb = _make_pose_bone(lookat_name)
    lookat_pb.head = _MockVector((0, 2.0, 1.6))
    lookat_pb.tail = _MockVector((0, 2.0, 1.8))
    lookat_pb.matrix = MagicMock()
    lookat_pb.matrix.copy = MagicMock(return_value="saved_matrix")
    bones[lookat_name] = lookat_pb

    armature = MagicMock()
    armature.name = "TestArmature"
    armature.pose.bones.get = lambda name: bones.get(name)
    armature.pose.bones.__iter__ = lambda self: iter(bones.values())

    sd = SimpleNamespace()
    sd.bones = bone_items
    chain_item = _make_chain_item(chain_id, module_type="neck_head")
    chain_item.ik_type = "LOOKAT"
    sd.chains = [chain_item]
    sd.has_wrap_rig = True
    sd.floor_enabled = False
    sd.floor_level = 0.0
    armature.bt_scan = sd

    return armature, bones, bone_items


# ===========================================================================
# Test: LookAt — _add_sync_constraints with DAMPED_TRACK
# ===========================================================================

class TestLookAtSyncConstraints:
    """Tests for _add_sync_constraints with DAMPED_TRACK (neck/head chain)."""

    def test_fk_sync_added_to_head_with_damped_track(self):
        """Head MCH has DAMPED_TRACK → FK CTRL should get FK_sync."""
        from rigging.scanner.wrap_assembly import _add_sync_constraints

        armature, bones, _ = _make_neck_head_armature()

        chain_bones = ["orig_neck", "orig_head"]
        bones_info = {
            "orig_neck": {"role": "neck"},
            "orig_head": {"role": "head"},
        }

        _add_sync_constraints(armature, "neck_head_C", chain_bones, bones_info)

        head_ctrl = bones[f"{WRAP_CTRL_PREFIX}neck_head_C_FK_head"]
        sync_cons = [c for c in head_ctrl.constraints
                     if hasattr(c, 'name')
                     and c.name == f"{WRAP_CONSTRAINT_PREFIX}FK_sync"]
        assert len(sync_cons) >= 1, "Head FK should have FK_sync (DAMPED_TRACK)"

    def test_no_fk_sync_on_neck_without_damped_track(self):
        """Neck MCH has no DAMPED_TRACK → should NOT get FK_sync."""
        from rigging.scanner.wrap_assembly import _add_sync_constraints

        armature, bones, _ = _make_neck_head_armature()

        chain_bones = ["orig_neck", "orig_head"]
        bones_info = {
            "orig_neck": {"role": "neck"},
            "orig_head": {"role": "head"},
        }

        _add_sync_constraints(armature, "neck_head_C", chain_bones, bones_info)

        neck_ctrl = bones[f"{WRAP_CTRL_PREFIX}neck_head_C_FK_neck"]
        sync_cons = [c for c in neck_ctrl.constraints
                     if hasattr(c, 'name')
                     and c.name == f"{WRAP_CONSTRAINT_PREFIX}FK_sync"]
        assert len(sync_cons) == 0, "Neck has no IK alternative — no sync"


# ===========================================================================
# Test: LookAt — _key_ik_switch with LOOKAT chain
# ===========================================================================

class TestLookAtKeyIkSwitch:
    """Tests for _key_ik_switch with LookAt (DAMPED_TRACK) chains.

    In the new system, the ik_switch property controls all constraint
    influences via drivers — same mechanism for LookAt as for IK.
    """

    def _make_lookat_with_prop(self, initial_value=0.0):
        armature, bones, items = _make_neck_head_armature()
        armature.animation_data = None
        props = {"ik_switch_neck_head_C": initial_value}
        armature.__getitem__ = lambda self, key: props[key]
        armature.__setitem__ = lambda self, key, val: props.__setitem__(key, val)
        armature.__contains__ = lambda self, key: key in props
        armature._props = props
        return armature, bones, items

    def test_lookat_mode_sets_property_to_1(self):
        """In LookAt mode, ik_switch should be 1.0."""
        from animation.smart_keyframe import _key_ik_switch

        armature, _, _ = self._make_lookat_with_prop(initial_value=0.0)

        _key_ik_switch(armature, "neck_head_C", use_ik=True, frame=1)

        assert armature._props["ik_switch_neck_head_C"] == 1.0

    def test_fk_mode_sets_property_to_0(self):
        """In FK mode, ik_switch should be 0.0."""
        from animation.smart_keyframe import _key_ik_switch

        armature, _, _ = self._make_lookat_with_prop(initial_value=1.0)

        _key_ik_switch(armature, "neck_head_C", use_ik=False, frame=1)

        assert armature._props["ik_switch_neck_head_C"] == 0.0


# ===========================================================================
# Test: LookAt — save / restore state
# ===========================================================================

class TestLookAtStateCaching:
    """Tests for save_lookat_state / restore_lookat_state."""

    def test_save_and_restore_lookat(self):
        """save_lookat_state should cache matrix, restore should apply it."""
        from rigging.scanner.wrap_assembly import (
            _ik_state_cache,
            restore_lookat_state,
            save_lookat_state,
        )

        armature, bones, _ = _make_neck_head_armature()

        # Clear cache before test
        cache_key = (armature.name, "neck_head_C")
        _ik_state_cache.pop(cache_key, None)

        save_lookat_state(armature, "neck_head_C")

        # Should have saved
        assert cache_key in _ik_state_cache
        assert 'lookat_matrix' in _ik_state_cache[cache_key]
        assert _ik_state_cache[cache_key]['lookat_matrix'] == "saved_matrix"

        # Restore should apply it back
        result = restore_lookat_state(armature, "neck_head_C")
        assert result is True

        # Clean up
        _ik_state_cache.pop(cache_key, None)

    def test_restore_without_save_returns_false(self):
        """restore_lookat_state should return False if no cached state."""
        from rigging.scanner.wrap_assembly import (
            _ik_state_cache,
            restore_lookat_state,
        )

        armature, _, _ = _make_neck_head_armature()

        # Ensure cache is empty
        cache_key = (armature.name, "neck_head_C")
        _ik_state_cache.pop(cache_key, None)

        result = restore_lookat_state(armature, "neck_head_C")
        assert result is False

    def test_save_without_target_bone_is_noop(self):
        """save_lookat_state should be no-op if LookAt target bone missing."""
        from rigging.scanner.wrap_assembly import (
            _ik_state_cache,
            save_lookat_state,
        )

        armature, bones, _ = _make_neck_head_armature()
        cache_key = (armature.name, "neck_head_C")
        _ik_state_cache.pop(cache_key, None)

        # Remove the LookAt target from bones lookup
        lookat_name = f"{WRAP_CTRL_PREFIX}neck_head_C_LookAt_target"
        del bones[lookat_name]
        armature.pose.bones.get = lambda name: bones.get(name)

        save_lookat_state(armature, "neck_head_C")
        assert cache_key not in _ik_state_cache


# ===========================================================================
# Test: LookAt — _scan_data_to_props
# ===========================================================================

class TestScanDataToPropsLookAt:
    """Tests for _scan_data_to_props neck_head auto-config."""

    def test_neck_head_gets_lookat_type(self):
        """neck_head chain should auto-get ik_type=LOOKAT."""
        from rigging.scanner.operators import _scan_data_to_props

        armature = MagicMock()
        sd = armature.bt_scan
        sd.bones = MagicMock()
        sd.bones.clear = MagicMock()
        sd.chains = MagicMock()
        sd.chains.clear = MagicMock()

        # Collect items added to chains
        chain_items = []

        def chain_add():
            item = SimpleNamespace()
            chain_items.append(item)
            return item

        sd.chains.add = chain_add
        sd.bones.add = lambda: SimpleNamespace()

        scan_data = {
            "skeleton_type": "humanoid",
            "confidence": 0.9,
            "bones": {},
            "chains": {
                "neck_head_C": {
                    "module_type": "neck_head",
                    "side": "C",
                    "bone_count": 2,
                },
            },
            "unmapped_bones": [],
        }

        _scan_data_to_props(armature, scan_data)

        assert len(chain_items) == 1
        item = chain_items[0]
        assert item.ik_type == 'LOOKAT'
        assert item.ik_enabled is True
        assert item.ik_snap is True

    def test_arm_still_gets_standard_type(self):
        """arm chain should still get ik_type=STANDARD (regression check)."""
        from rigging.scanner.operators import _scan_data_to_props

        armature = MagicMock()
        sd = armature.bt_scan
        sd.bones = MagicMock()
        sd.bones.clear = MagicMock()
        sd.chains = MagicMock()
        sd.chains.clear = MagicMock()

        chain_items = []

        def chain_add():
            item = SimpleNamespace()
            chain_items.append(item)
            return item

        sd.chains.add = chain_add
        sd.bones.add = lambda: SimpleNamespace()

        scan_data = {
            "skeleton_type": "humanoid",
            "confidence": 0.9,
            "bones": {},
            "chains": {
                "arm_L": {
                    "module_type": "arm",
                    "side": "L",
                    "bone_count": 3,
                },
            },
            "unmapped_bones": [],
        }

        _scan_data_to_props(armature, scan_data)

        item = chain_items[0]
        assert item.ik_type == 'STANDARD'

    def test_tail_still_gets_spline_type(self):
        """tail chain should still get ik_type=SPLINE (regression check)."""
        from rigging.scanner.operators import _scan_data_to_props

        armature = MagicMock()
        sd = armature.bt_scan
        sd.bones = MagicMock()
        sd.bones.clear = MagicMock()
        sd.chains = MagicMock()
        sd.chains.clear = MagicMock()

        chain_items = []

        def chain_add():
            item = SimpleNamespace()
            chain_items.append(item)
            return item

        sd.chains.add = chain_add
        sd.bones.add = lambda: SimpleNamespace()

        scan_data = {
            "skeleton_type": "creature",
            "confidence": 0.8,
            "bones": {},
            "chains": {
                "tail_C": {
                    "module_type": "tail",
                    "side": "C",
                    "bone_count": 5,
                },
            },
            "unmapped_bones": [],
        }

        _scan_data_to_props(armature, scan_data)

        item = chain_items[0]
        assert item.ik_type == 'SPLINE'


# ===========================================================================
# Test: LookAt — ensure_fk_sync with DAMPED_TRACK
# ===========================================================================

class TestEnsureFkSyncDampedTrack:
    """Tests for ensure_fk_sync recognizing DAMPED_TRACK."""

    def test_ensure_fk_sync_adds_sync_for_damped_track(self):
        """ensure_fk_sync should add FK_sync to head with DAMPED_TRACK."""
        from rigging.scanner.wrap_assembly import ensure_fk_sync

        armature, bones, _ = _make_neck_head_armature()

        ensure_fk_sync(armature, "neck_head_C")

        head_ctrl = bones[f"{WRAP_CTRL_PREFIX}neck_head_C_FK_head"]
        sync_cons = [c for c in head_ctrl.constraints
                     if hasattr(c, 'name')
                     and c.name == f"{WRAP_CONSTRAINT_PREFIX}FK_sync"]
        assert len(sync_cons) >= 1

    def test_ensure_fk_sync_idempotent(self):
        """Calling ensure_fk_sync twice should not duplicate FK_sync."""
        from rigging.scanner.wrap_assembly import ensure_fk_sync

        armature, bones, _ = _make_neck_head_armature()

        ensure_fk_sync(armature, "neck_head_C")
        ensure_fk_sync(armature, "neck_head_C")

        head_ctrl = bones[f"{WRAP_CTRL_PREFIX}neck_head_C_FK_head"]
        sync_cons = [c for c in head_ctrl.constraints
                     if hasattr(c, 'name')
                     and c.name == f"{WRAP_CONSTRAINT_PREFIX}FK_sync"]
        assert len(sync_cons) == 1, "FK_sync should not be duplicated"


# ===========================================================================
# Helpers — mock Blender 5.0 layered action for onion skin tests
# ===========================================================================

def _make_keyframe_point(frame, selected=True):
    """Create a mock keyframe point with frame and selection state."""
    kp = SimpleNamespace()
    kp.co = SimpleNamespace(x=float(frame))
    kp.select_control_point = selected
    return kp


def _make_fcurve(data_path, keyframes):
    """Create a mock FCurve with data_path and keyframe_points list."""
    fc = SimpleNamespace()
    fc.data_path = data_path
    fc.keyframe_points = keyframes
    return fc


def _make_action_with_keyframes(fcurves):
    """Build a mock Blender 5.0 layered action from a list of FCurves.

    Structure: action.layers[0].strips[0].channelbags[0].fcurves = fcurves
    """
    channelbag = SimpleNamespace(fcurves=fcurves)
    strip = SimpleNamespace(channelbags=[channelbag])
    layer = SimpleNamespace(strips=[strip])
    action = SimpleNamespace(layers=[layer])
    return action


def _make_armature_with_action(action):
    """Build a mock armature with animation_data pointing to the action."""
    anim_data = SimpleNamespace(action=action)
    armature = MagicMock()
    armature.animation_data = anim_data
    return armature


# ===========================================================================
# Test: Onion skin — _get_action_keyframes with selected_only
# ===========================================================================

class TestGetActionKeyframes:
    """Tests for _get_action_keyframes selected_only filtering."""

    def test_all_keyframes_returned_by_default(self):
        """Without selected_only, all pose bone keyframes are returned."""
        from animation.onion_skin import _get_action_keyframes

        fcurves = [
            _make_fcurve('pose.bones["Spine"].rotation_euler', [
                _make_keyframe_point(1, selected=False),
                _make_keyframe_point(10, selected=True),
                _make_keyframe_point(20, selected=False),
            ]),
        ]
        armature = _make_armature_with_action(_make_action_with_keyframes(fcurves))

        result = _get_action_keyframes(armature, selected_only=False)
        assert result == [1, 10, 20]

    def test_selected_only_filters_to_selected(self):
        """With selected_only=True, only selected keyframes are returned."""
        from animation.onion_skin import _get_action_keyframes

        fcurves = [
            _make_fcurve('pose.bones["Spine"].rotation_euler', [
                _make_keyframe_point(1, selected=False),
                _make_keyframe_point(10, selected=True),
                _make_keyframe_point(20, selected=False),
                _make_keyframe_point(30, selected=True),
            ]),
        ]
        armature = _make_armature_with_action(_make_action_with_keyframes(fcurves))

        result = _get_action_keyframes(armature, selected_only=True)
        assert result == [10, 30]

    def test_selected_only_no_selection_returns_empty(self):
        """selected_only=True with nothing selected returns empty list."""
        from animation.onion_skin import _get_action_keyframes

        fcurves = [
            _make_fcurve('pose.bones["Arm"].location', [
                _make_keyframe_point(5, selected=False),
                _make_keyframe_point(15, selected=False),
            ]),
        ]
        armature = _make_armature_with_action(_make_action_with_keyframes(fcurves))

        result = _get_action_keyframes(armature, selected_only=True)
        assert result == []

    def test_ignores_non_pose_bone_channels(self):
        """Constraint and object channels should be excluded."""
        from animation.onion_skin import _get_action_keyframes

        fcurves = [
            # Pose bone transform — should be included
            _make_fcurve('pose.bones["Leg"].rotation_euler', [
                _make_keyframe_point(1, selected=True),
            ]),
            # Constraint influence — should be excluded
            _make_fcurve(
                'pose.bones["Leg"].constraints["BT_Wrap_IK"].influence', [
                    _make_keyframe_point(1, selected=True),
                    _make_keyframe_point(5, selected=True),
                ]),
            # Object-level channel — should be excluded
            _make_fcurve('location', [
                _make_keyframe_point(10, selected=True),
            ]),
        ]
        armature = _make_armature_with_action(_make_action_with_keyframes(fcurves))

        result = _get_action_keyframes(armature, selected_only=True)
        assert result == [1]

    def test_deduplicates_across_channels(self):
        """Same frame from multiple FCurves should appear once."""
        from animation.onion_skin import _get_action_keyframes

        fcurves = [
            _make_fcurve('pose.bones["Spine"].rotation_euler', [
                _make_keyframe_point(10, selected=True),
            ]),
            _make_fcurve('pose.bones["Spine"].location', [
                _make_keyframe_point(10, selected=True),
                _make_keyframe_point(20, selected=True),
            ]),
        ]
        armature = _make_armature_with_action(_make_action_with_keyframes(fcurves))

        result = _get_action_keyframes(armature, selected_only=True)
        assert result == [10, 20]

    def test_no_action_returns_empty(self):
        """No animation data should return empty list."""
        from animation.onion_skin import _get_action_keyframes

        armature = MagicMock()
        armature.animation_data = None

        result = _get_action_keyframes(armature, selected_only=True)
        assert result == []

    def test_mixed_selection_across_channels(self):
        """A frame selected on one channel but not another still counts."""
        from animation.onion_skin import _get_action_keyframes

        fcurves = [
            _make_fcurve('pose.bones["Hip"].rotation_euler', [
                _make_keyframe_point(5, selected=True),
                _make_keyframe_point(15, selected=False),
            ]),
            _make_fcurve('pose.bones["Hip"].location', [
                _make_keyframe_point(5, selected=False),
                _make_keyframe_point(15, selected=True),
            ]),
        ]
        armature = _make_armature_with_action(_make_action_with_keyframes(fcurves))

        result = _get_action_keyframes(armature, selected_only=True)
        # Frame 5 selected on rotation, frame 15 selected on location
        assert result == [5, 15]


# ===========================================================================
# Test: Onion skin — _build_ghost_cache selected_only bypasses count limits
# ===========================================================================

class TestBuildGhostCacheSelectedOnly:
    """Verify selected_only shows all selected keyframes, capped by before/after."""

    def test_selected_within_limit_shows_all(self):
        """When selected count <= before/after, all selected keyframes appear."""
        from animation.onion_skin import _get_action_keyframes, _get_settings

        # 2 selected before, 2 after — limits are 3 each → all 4 shown
        fcurves = [
            _make_fcurve('pose.bones["Spine"].rotation_euler', [
                _make_keyframe_point(5, selected=True),
                _make_keyframe_point(10, selected=True),
                _make_keyframe_point(25, selected=True),
                _make_keyframe_point(30, selected=True),
            ]),
        ]
        armature = _make_armature_with_action(_make_action_with_keyframes(fcurves))
        scene = SimpleNamespace(
            bt_onion_before=3, bt_onion_after=3, bt_onion_step=1,
            bt_onion_opacity=0.25, bt_onion_use_keyframes=True,
            bt_onion_selected_keys=True, bt_onion_proxy_ratio=1.0,
        )
        context = SimpleNamespace(scene=scene)
        settings = _get_settings(context)

        all_keys = _get_action_keyframes(armature, selected_only=True)
        current = 20
        keys_before = [f for f in all_keys if f < current]
        keys_after = [f for f in all_keys if f > current]

        count_before = settings['count_before']
        count_after = settings['count_after']
        frames_before = keys_before[-count_before:] if len(keys_before) > count_before else keys_before
        frames_after = keys_after[:count_after] if len(keys_after) > count_after else keys_after

        assert frames_before == [5, 10], "Both selected before-frames shown"
        assert frames_after == [25, 30], "Both selected after-frames shown"

    def test_selected_exceeding_limit_gets_capped(self):
        """When selected count > before/after, cap to nearest N."""
        from animation.onion_skin import _get_action_keyframes, _get_settings

        # 5 selected before, 4 after — limits are 2 each → capped
        fcurves = [
            _make_fcurve('pose.bones["Spine"].rotation_euler', [
                _make_keyframe_point(1, selected=True),
                _make_keyframe_point(3, selected=True),
                _make_keyframe_point(6, selected=True),
                _make_keyframe_point(10, selected=True),
                _make_keyframe_point(15, selected=True),
                _make_keyframe_point(25, selected=True),
                _make_keyframe_point(30, selected=True),
                _make_keyframe_point(35, selected=True),
                _make_keyframe_point(40, selected=True),
            ]),
        ]
        armature = _make_armature_with_action(_make_action_with_keyframes(fcurves))
        scene = SimpleNamespace(
            bt_onion_before=2, bt_onion_after=2, bt_onion_step=1,
            bt_onion_opacity=0.25, bt_onion_use_keyframes=True,
            bt_onion_selected_keys=True, bt_onion_proxy_ratio=1.0,
        )
        context = SimpleNamespace(scene=scene)
        settings = _get_settings(context)

        all_keys = _get_action_keyframes(armature, selected_only=True)
        current = 20
        keys_before = [f for f in all_keys if f < current]
        keys_after = [f for f in all_keys if f > current]

        count_before = settings['count_before']
        count_after = settings['count_after']
        frames_before = keys_before[-count_before:] if len(keys_before) > count_before else keys_before
        frames_after = keys_after[:count_after] if len(keys_after) > count_after else keys_after

        assert frames_before == [10, 15], "Capped to nearest 2 before"
        assert frames_after == [25, 30], "Capped to nearest 2 after"


# ===========================================================================
# Test: Onion skin — _get_selected_key_hash tracks selection changes
# ===========================================================================

class TestGetSelectedKeyHash:
    """Tests for _get_selected_key_hash selection change detection."""

    def test_hash_changes_when_selection_changes(self):
        """Hash should differ when different keyframes are selected."""
        from animation.onion_skin import _get_selected_key_hash

        fcurves = [
            _make_fcurve('pose.bones["Spine"].rotation_euler', [
                _make_keyframe_point(1, selected=True),
                _make_keyframe_point(10, selected=False),
                _make_keyframe_point(20, selected=True),
            ]),
        ]
        armature = _make_armature_with_action(_make_action_with_keyframes(fcurves))
        hash_a = _get_selected_key_hash(armature)

        # Change selection: deselect frame 1, select frame 10
        fcurves[0].keyframe_points[0].select_control_point = False
        fcurves[0].keyframe_points[1].select_control_point = True
        hash_b = _get_selected_key_hash(armature)

        assert hash_a != hash_b

    def test_hash_stable_for_same_selection(self):
        """Hash should be identical for the same selection state."""
        from animation.onion_skin import _get_selected_key_hash

        fcurves = [
            _make_fcurve('pose.bones["Leg"].location', [
                _make_keyframe_point(5, selected=True),
                _make_keyframe_point(15, selected=False),
            ]),
        ]
        armature = _make_armature_with_action(_make_action_with_keyframes(fcurves))

        assert _get_selected_key_hash(armature) == _get_selected_key_hash(armature)

    def test_hash_empty_selection(self):
        """Hash should be consistent for empty selection."""
        from animation.onion_skin import _get_selected_key_hash

        fcurves = [
            _make_fcurve('pose.bones["Arm"].rotation_euler', [
                _make_keyframe_point(1, selected=False),
                _make_keyframe_point(10, selected=False),
            ]),
        ]
        armature = _make_armature_with_action(_make_action_with_keyframes(fcurves))
        hash_empty = _get_selected_key_hash(armature)

        # Same hash for same empty state
        assert hash_empty == _get_selected_key_hash(armature)
