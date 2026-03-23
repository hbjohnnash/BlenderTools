"""Create and remove wrap control rigs around existing bones.

Architecture: CTRL → MCH → DEF
  - User manipulates CTRL bones (FK controls, IK target/pole)
  - MCH bones are driven by CTRL (COPY_TRANSFORMS for FK, IK constraint for IK)
  - DEF bones follow MCH (COPY_TRANSFORMS, always influence=1.0)
"""

import math

import bpy
from mathutils import Vector

from ...core.constants import (
    WRAP_CONSTRAINT_PREFIX,
    WRAP_CTRL_PREFIX,
    WRAP_MCH_PREFIX,
    WRAP_SPLINE_PREFIX,
)
from ...core.utils import assign_channel_groups


def assemble_wrap_rig(armature_obj, scan_data):
    """Create CTRL and MCH bones that drive the original skeleton.

    Args:
        armature_obj: Blender armature object.
        scan_data: dict from scan_skeleton(), possibly edited by user.

    Returns:
        list of created bone names.
    """
    chains = scan_data.get("chains", {})
    bones_info = scan_data.get("bones", {})
    created = []

    # Maps original bone name → CTRL/MCH bone name (for cross-chain parenting)
    orig_to_ctrl = {}
    orig_to_mch = {}

    # Spline IK data collected during edit mode, processed after
    spline_chains = {}  # chain_id -> spline_info

    # Ensure bone collections exist
    _ensure_collection(armature_obj, "CTRL")
    _ensure_collection(armature_obj, "MCH")

    # Store forward axis for LookAt target placement
    bones_info["_forward_axis"] = getattr(armature_obj.bt_scan, "forward_axis", "-Y")

    # Process chains in dependency order: root → spine → neck/arms/legs → fingers → generic
    chain_order = _sort_chains_by_dependency(chains, bones_info, armature_obj)

    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode='EDIT')
    edit_bones = armature_obj.data.edit_bones

    try:
        for chain_id in chain_order:
            chain_info = chains[chain_id]
            module_type = chain_info["module_type"]
            chain_bones = chain_info["bones"]

            if module_type == "skip":
                continue

            chain_bones = [b for b in chain_bones if not bones_info.get(b, {}).get("skip", False)]
            if not chain_bones:
                continue

            ik_enabled = chain_info.get("ik_enabled")
            ik_type = chain_info.get("ik_type", "STANDARD")
            use_spline = ik_enabled and ik_type == "SPLINE" and module_type not in ("arm", "leg")

            if module_type == "arm":
                new_bones = _create_arm_controls(edit_bones, chain_id, chain_bones, bones_info, orig_to_ctrl, orig_to_mch)
            elif module_type == "leg":
                new_bones = _create_leg_controls(edit_bones, chain_id, chain_bones, bones_info, orig_to_ctrl, orig_to_mch)
            elif module_type == "neck_head" and ik_enabled:
                new_bones = _create_neck_head_controls(edit_bones, chain_id, chain_bones, bones_info, orig_to_ctrl, orig_to_mch)
            elif use_spline:
                new_bones, spline_info = _create_spline_ik_chain(
                    edit_bones, chain_id, chain_bones, bones_info, orig_to_ctrl, orig_to_mch)
                if spline_info:
                    spline_chains[chain_id] = spline_info
            elif ik_enabled and module_type not in ("arm", "leg"):
                new_bones = _create_ik_chain(edit_bones, chain_id, chain_bones, bones_info, orig_to_ctrl, orig_to_mch)
            else:
                new_bones = _create_fk_chain(edit_bones, chain_id, chain_bones, bones_info, orig_to_ctrl, orig_to_mch)

            # Assign collections, colors, and disable deform on generated bones
            # IK target/pole/spline bones get per-chain collections (hidden in FK mode)
            ik_coll_name = f"IK_{chain_id}"
            has_ik_bones = any(
                bn.endswith("_IK_target") or bn.endswith("_IK_pole")
                or bn.endswith("_LookAt_target") or "_Spline_" in bn
                for bn in new_bones
            )
            if has_ik_bones:
                _ensure_collection(armature_obj, ik_coll_name)

            for bn in new_bones:
                eb = edit_bones.get(bn)
                if eb:
                    eb.use_deform = False
                    if bn.startswith(WRAP_CTRL_PREFIX):
                        is_ik_ctrl = (bn.endswith("_IK_target")
                                      or bn.endswith("_IK_pole")
                                      or bn.endswith("_LookAt_target")
                                      or "_Spline_" in bn)
                        if is_ik_ctrl:
                            _assign_collection_exclusive(armature_obj, eb, ik_coll_name)
                            eb.color.palette = 'THEME04'
                        else:
                            _assign_collection_exclusive(armature_obj, eb, "CTRL")
                            eb.color.palette = 'THEME06'
                    elif bn.startswith(WRAP_MCH_PREFIX):
                        _assign_collection_exclusive(armature_obj, eb, "MCH")
                        eb.color.palette = 'THEME09'

            created.extend(new_bones)
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')

    # Create spline curves in Object mode (between edit and pose phases)
    spline_curves = {}  # chain_id -> curve_obj
    for chain_id, spline_info in spline_chains.items():
        curve_obj = _create_spline_curve(armature_obj, chain_id, spline_info)
        spline_curves[chain_id] = curve_obj

    # Now add constraints in pose mode (same order as bone creation)
    bpy.ops.object.mode_set(mode='POSE')
    try:
        for chain_id in chain_order:
            chain_info = chains[chain_id]
            module_type = chain_info["module_type"]
            if module_type == "skip":
                continue
            chain_bones = chain_info["bones"]
            chain_bones = [b for b in chain_bones if not bones_info.get(b, {}).get("skip", False)]
            if not chain_bones:
                continue

            ik_enabled = chain_info.get("ik_enabled")
            ik_type = chain_info.get("ik_type", "STANDARD")
            use_spline = ik_enabled and ik_type == "SPLINE" and module_type not in ("arm", "leg")

            if module_type == "arm":
                _constrain_arm(armature_obj, chain_id, chain_bones, bones_info)
            elif module_type == "leg":
                _constrain_leg(armature_obj, chain_id, chain_bones, bones_info)
            elif module_type == "neck_head" and ik_enabled:
                _constrain_neck_head(armature_obj, chain_id, chain_bones, bones_info)
            elif use_spline and chain_id in spline_curves:
                _constrain_spline_ik_chain(
                    armature_obj, chain_id, chain_bones, bones_info,
                    spline_curves[chain_id])
            elif ik_enabled and module_type not in ("arm", "leg"):
                ik_snap = chain_info.get("ik_snap", False)
                _constrain_ik_chain(armature_obj, chain_id, chain_bones, bones_info, ik_snap)
            else:
                _constrain_fk_chain(armature_obj, chain_id, chain_bones, bones_info)

            # Add sync constraints so inactive system follows active in real-time
            if ik_enabled:
                _add_sync_constraints(armature_obj, chain_id, chain_bones, bones_info)

            # Always write limit values so they're ready to toggle on.
            # IK limits go on MCH bones, FK limits go on CTRL-FK bones.
            if ik_enabled:
                apply_ik_limits(armature_obj, chain_id, chain_bones, bones_info, module_type)
            apply_fk_limits(armature_obj, chain_id, chain_bones, bones_info, module_type)

            # If the user had limits enabled in the scan config, activate them now
            if chain_info.get("ik_limits"):
                toggle_joint_limits(armature_obj, chain_id, True)

        # Calibrate all IK pole angles using the depsgraph.
        # Must happen BEFORE driver setup — calibration temporarily toggles
        # constraint influences directly, which drivers would override.
        _calibrate_pole_angles(armature_obj)

        # Second pass: add ik_switch custom properties + drivers.
        # Done after pole calibration so drivers don't interfere.
        for chain_id in chain_order:
            chain_info = chains[chain_id]
            if chain_info["module_type"] == "skip":
                continue
            if not chain_info.get("ik_enabled"):
                continue
            chain_bones = chain_info["bones"]
            chain_bones = [b for b in chain_bones
                           if not bones_info.get(b, {}).get("skip", False)]
            if not chain_bones:
                continue
            _add_ik_switch_property(armature_obj, chain_id)
            _setup_ik_switch_drivers(armature_obj, chain_id,
                                     chain_bones, bones_info)
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')

    # Manage collection visibility: hide all except CTRL
    sd = armature_obj.bt_scan
    hidden_names = []
    ik_coll_prefix = "IK_"
    for coll in armature_obj.data.collections:
        if coll.name == "CTRL":
            continue
        # Per-chain IK collections start hidden (FK mode)
        if coll.name.startswith(ik_coll_prefix):
            coll.is_visible = False
            continue
        if coll.is_visible:
            hidden_names.append(coll.name)
            coll.is_visible = False
    ctrl_coll = armature_obj.data.collections.get("CTRL")
    if ctrl_coll:
        ctrl_coll.is_visible = True
    sd.hidden_collections = ",".join(hidden_names)

    scan_data["generated_bones"] = created
    return created


def disassemble_wrap_rig(armature_obj, scan_data=None):
    """Remove only generated CTRL/MCH wrap bones and their constraints.

    Identifies generated content by the BT_Wrap_ constraint prefix and
    CTRL-Wrap_ / MCH-Wrap_ bone name prefixes. Original bones are never touched.
    """
    # Remove ik_switch drivers and custom properties before constraints
    _remove_ik_switch_drivers(armature_obj)

    # Restore hidden collections before removing bones
    sd = armature_obj.bt_scan
    if sd.hidden_collections:
        for name in sd.hidden_collections.split(","):
            name = name.strip()
            if name:
                coll = armature_obj.data.collections.get(name)
                if coll:
                    coll.is_visible = True
        sd.hidden_collections = ""

    # Remove constraints first (in pose mode)
    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode='POSE')
    try:
        for pbone in armature_obj.pose.bones:
            to_remove = [c for c in pbone.constraints if c.name.startswith(WRAP_CONSTRAINT_PREFIX)]
            for c in to_remove:
                pbone.constraints.remove(c)
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')

    # Remove spline curve objects (before bone removal)
    spline_curves = [
        obj for obj in bpy.data.objects
        if obj.name.startswith(WRAP_SPLINE_PREFIX) and obj.parent == armature_obj
    ]
    for obj in spline_curves:
        curve_data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if curve_data and curve_data.users == 0:
            bpy.data.curves.remove(curve_data)

    # Remove generated bones (in edit mode)
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        edit_bones = armature_obj.data.edit_bones
        to_remove = [
            eb for eb in edit_bones
            if eb.name.startswith(WRAP_CTRL_PREFIX) or eb.name.startswith(WRAP_MCH_PREFIX)
        ]
        for eb in to_remove:
            edit_bones.remove(eb)
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')

    # Remove empty generated collections (CTRL, MCH, and per-chain IK_*)
    to_remove = []
    for coll in armature_obj.data.collections:
        if coll.name in ("CTRL", "MCH") or coll.name.startswith("IK_"):
            if len(coll.bones) == 0:
                to_remove.append(coll)
    for coll in to_remove:
        armature_obj.data.collections.remove(coll)

    if scan_data:
        scan_data["generated_bones"] = []


def bake_to_def(armature_obj, frame_start=None, frame_end=None):
    """Bake animations from the CTRL→MCH→DEF constraint chain onto DEF bones.

    Uses Blender's visual keying to evaluate the full constraint chain and
    write keyframes directly onto the DEF (original) bones. After baking,
    removes the wrap rig so the DEF bones are self-sufficient for export.

    Args:
        armature_obj: Armature with an active wrap rig.
        frame_start: First frame to bake (defaults to scene start).
        frame_end: Last frame to bake (defaults to scene end).

    Returns:
        Dict with bake stats.
    """
    scene = bpy.context.scene
    if frame_start is None:
        frame_start = scene.frame_start
    if frame_end is None:
        frame_end = scene.frame_end

    bpy.context.view_layer.objects.active = armature_obj

    # Collect DEF bone names (original bones that have BT_Wrap_DEF_ constraints)
    def_bones = []
    for pbone in armature_obj.pose.bones:
        if pbone.bone.name.startswith(WRAP_CTRL_PREFIX) or pbone.bone.name.startswith(WRAP_MCH_PREFIX):
            continue
        for con in pbone.constraints:
            if con.name.startswith(WRAP_CONSTRAINT_PREFIX):
                def_bones.append(pbone.bone.name)
                break

    if not def_bones:
        return {"baked": 0, "frames": 0}

    # Select only DEF bones for baking
    bpy.ops.object.mode_set(mode='POSE')
    bpy.ops.pose.select_all(action='DESELECT')
    for name in def_bones:
        pbone = armature_obj.pose.bones.get(name)
        if pbone:
            pbone.select = True

    # Bake visual keying: evaluates constraints and writes keyframes
    bpy.ops.nla.bake(
        frame_start=frame_start,
        frame_end=frame_end,
        only_selected=True,
        visual_keying=True,
        clear_constraints=False,
        bake_types={'POSE'},
    )
    assign_channel_groups(armature_obj)

    bpy.ops.object.mode_set(mode='OBJECT')

    # Remove the wrap rig now that DEF bones have baked keyframes
    disassemble_wrap_rig(armature_obj)
    armature_obj.bt_scan.has_wrap_rig = False

    return {
        "baked": len(def_bones),
        "frames": frame_end - frame_start + 1,
    }


# --- FK Chain (spine, neck_head, finger, generic) ---

def _create_fk_chain(edit_bones, chain_id, chain_bones, bones_info,
                      orig_to_ctrl=None, orig_to_mch=None):
    """Create MCH intermediate + FK control bones co-located with originals."""
    if orig_to_ctrl is None:
        orig_to_ctrl = {}
    if orig_to_mch is None:
        orig_to_mch = {}
    created = []
    chain_bone_set = set(chain_bones)

    for bone_name in chain_bones:
        orig = edit_bones.get(bone_name)
        if not orig:
            continue

        role = bones_info.get(bone_name, {}).get("role", bone_name)

        # MCH bone — intermediate between CTRL and DEF
        mch_name = f"{WRAP_MCH_PREFIX}{chain_id}_{role}"
        mch = edit_bones.new(mch_name)
        mch.head = orig.head.copy()
        mch.tail = orig.tail.copy()
        mch.roll = orig.roll

        # Respect original hierarchy: find parent MCH within same chain,
        # or fall back to cross-chain parent for root bones.
        mch_parent = _find_intra_chain_parent(edit_bones, orig, chain_bone_set, orig_to_mch)
        if mch_parent:
            mch.parent = mch_parent
        else:
            parent_mch = _find_cross_chain_parent(edit_bones, orig, orig_to_mch)
            if parent_mch:
                mch.parent = parent_mch

        # CTRL-FK bone — user-facing control
        ctrl_name = f"{WRAP_CTRL_PREFIX}{chain_id}_FK_{role}"
        ctrl = edit_bones.new(ctrl_name)
        ctrl.head = orig.head.copy()
        ctrl.tail = orig.tail.copy()
        ctrl.roll = orig.roll

        ctrl_parent = _find_intra_chain_parent(edit_bones, orig, chain_bone_set, orig_to_ctrl)
        if ctrl_parent:
            ctrl.parent = ctrl_parent
        else:
            parent_ctrl = _find_cross_chain_parent(edit_bones, orig, orig_to_ctrl)
            if parent_ctrl:
                ctrl.parent = parent_ctrl

        orig_to_ctrl[bone_name] = ctrl_name
        orig_to_mch[bone_name] = mch_name
        created.append(mch_name)
        created.append(ctrl_name)

    return created


def _constrain_fk_chain(armature_obj, chain_id, chain_bones, bones_info):
    """Add constraints: DEF → MCH (always on) and MCH → CTRL-FK (toggled)."""
    for bone_name in chain_bones:
        role = bones_info.get(bone_name, {}).get("role", bone_name)
        mch_name = f"{WRAP_MCH_PREFIX}{chain_id}_{role}"
        ctrl_name = f"{WRAP_CTRL_PREFIX}{chain_id}_FK_{role}"

        pbone = armature_obj.pose.bones.get(bone_name)
        mch_pbone = armature_obj.pose.bones.get(mch_name)
        ctrl_pbone = armature_obj.pose.bones.get(ctrl_name)

        # DEF → MCH (always active, never toggled)
        if pbone and mch_pbone:
            con = pbone.constraints.new('COPY_TRANSFORMS')
            con.name = f"{WRAP_CONSTRAINT_PREFIX}DEF_{role}"
            con.target = armature_obj
            con.subtarget = mch_name
            con.influence = 1.0

        # MCH → CTRL-FK (toggled for FK/IK switching)
        # Use LOCAL space so child chains (e.g. fingers) inherit world-space
        # position from their MCH parent (which follows IK) while copying only
        # the local rotation from CTRL-FK (the user's FK input).
        if mch_pbone and ctrl_pbone:
            con = mch_pbone.constraints.new('COPY_TRANSFORMS')
            con.name = f"{WRAP_CONSTRAINT_PREFIX}FK_{role}"
            con.target = armature_obj
            con.subtarget = ctrl_name
            con.target_space = 'LOCAL'
            con.owner_space = 'LOCAL'
            con.influence = 1.0


# --- Arm Controls ---

def _create_arm_controls(edit_bones, chain_id, chain_bones, bones_info,
                          orig_to_ctrl=None, orig_to_mch=None):
    """Create FK + IK controls for arm chain."""
    created = _create_fk_chain(edit_bones, chain_id, chain_bones, bones_info,
                                orig_to_ctrl, orig_to_mch)

    roles = {bones_info.get(b, {}).get("role", ""): b for b in chain_bones}
    hand_bone = roles.get("hand")
    lower_arm_bone = roles.get("lower_arm")
    upper_arm_bone = roles.get("upper_arm")

    if hand_bone and lower_arm_bone and upper_arm_bone:
        orig_hand = edit_bones.get(hand_bone)
        orig_lower = edit_bones.get(lower_arm_bone)
        orig_upper = edit_bones.get(upper_arm_bone)

        if orig_hand and orig_lower and orig_upper:
            bone_len = max((orig_lower.tail - orig_lower.head).length * 0.3, 0.5)

            # IK target at hand — oriented to match hand bone so that
            # COPY_ROTATION produces correct rest-pose orientation.
            ik_name = f"{WRAP_CTRL_PREFIX}{chain_id}_IK_target"
            ik_bone = edit_bones.new(ik_name)
            ik_bone.head = orig_hand.head.copy()
            hand_dir = (orig_hand.tail - orig_hand.head).normalized()
            ik_bone.tail = orig_hand.head + hand_dir * bone_len
            ik_bone.roll = orig_hand.roll
            created.append(ik_name)

            # IK pole at elbow
            pole_name = f"{WRAP_CTRL_PREFIX}{chain_id}_IK_pole"
            pole_pos = _calculate_pole_position(
                orig_upper.head, orig_lower.head, orig_hand.head,
                module_type="arm",
            )
            pole_bone = edit_bones.new(pole_name)
            pole_bone.head = pole_pos
            pole_bone.tail = pole_pos + Vector((0, -bone_len * 0.5, 0))
            pole_bone.roll = 0
            created.append(pole_name)

    return created


def _constrain_arm(armature_obj, chain_id, chain_bones, bones_info):
    """Add FK + IK constraints for arm chain.

    DEF → MCH and MCH → CTRL-FK via _constrain_fk_chain.
    IK constraint goes on the MCH bone (not DEF).
    chain_count is calculated dynamically from bone positions so that
    arms with intermediate bones (e.g. upper_arm → mid → lower_arm)
    have IK covering the full span.
    Pole angle is set later by _calibrate_pole_angles.
    """
    _constrain_fk_chain(armature_obj, chain_id, chain_bones, bones_info)

    roles = {bones_info.get(b, {}).get("role", ""): b for b in chain_bones}
    lower_arm_bone = roles.get("lower_arm")
    upper_arm_bone = roles.get("upper_arm")

    if lower_arm_bone and upper_arm_bone:
        lower_role = bones_info.get(lower_arm_bone, {}).get("role", lower_arm_bone)
        mch_name = f"{WRAP_MCH_PREFIX}{chain_id}_{lower_role}"
        ik_target = f"{WRAP_CTRL_PREFIX}{chain_id}_IK_target"
        ik_pole = f"{WRAP_CTRL_PREFIX}{chain_id}_IK_pole"

        # Dynamic chain_count: number of bones from upper_arm to lower_arm
        upper_idx = chain_bones.index(upper_arm_bone)
        lower_idx = chain_bones.index(lower_arm_bone)
        chain_count = lower_idx - upper_idx + 1

        mch_pbone = armature_obj.pose.bones.get(mch_name)
        if mch_pbone and armature_obj.pose.bones.get(ik_target):
            con = mch_pbone.constraints.new('IK')
            con.name = f"{WRAP_CONSTRAINT_PREFIX}IK_arm"
            con.target = armature_obj
            con.subtarget = ik_target
            con.chain_count = chain_count
            con.use_stretch = False
            con.influence = 0.0  # Start with FK, user toggles IK

            if armature_obj.pose.bones.get(ik_pole):
                con.pole_target = armature_obj
                con.pole_subtarget = ik_pole

    # Hand rotation from IK target (end-effector control).
    # When IK is active, the hand orientation follows the IK target bone.
    # Influence starts at 0.0 (FK mode) and is toggled by BT_OT_ToggleFKIK.
    hand_bone = {bones_info.get(b, {}).get("role", ""): b for b in chain_bones}.get("hand")
    if hand_bone:
        hand_role = bones_info.get(hand_bone, {}).get("role", hand_bone)
        hand_mch = f"{WRAP_MCH_PREFIX}{chain_id}_{hand_role}"
        ik_target = f"{WRAP_CTRL_PREFIX}{chain_id}_IK_target"
        hand_pbone = armature_obj.pose.bones.get(hand_mch)
        if hand_pbone and armature_obj.pose.bones.get(ik_target):
            con = hand_pbone.constraints.new('COPY_ROTATION')
            con.name = f"{WRAP_CONSTRAINT_PREFIX}IK_Rot"
            con.target = armature_obj
            con.subtarget = ik_target
            con.influence = 0.0  # Start with FK


# --- Neck/Head Controls ---

def _create_neck_head_controls(edit_bones, chain_id, chain_bones, bones_info,
                                orig_to_ctrl=None, orig_to_mch=None):
    """Create FK controls + LookAt target for neck/head chain."""
    created = _create_fk_chain(edit_bones, chain_id, chain_bones, bones_info,
                                orig_to_ctrl, orig_to_mch)

    # Find the head bone by role
    roles = {bones_info.get(b, {}).get("role", ""): b for b in chain_bones}
    head_bone_name = roles.get("head")
    if not head_bone_name:
        return created

    orig_head = edit_bones.get(head_bone_name)
    if not orig_head:
        return created

    head_len = (orig_head.tail - orig_head.head).length
    bone_len = max(head_len * 0.3, 0.02)

    # LookAt target: placed in front of head center.
    # The head bone typically points upward (base→top of skull), so its
    # axis is NOT the gaze direction. Use the user-selected forward axis
    # projected perpendicular to the bone's up axis.
    head_center = (orig_head.head + orig_head.tail) * 0.5
    head_up = (orig_head.tail - orig_head.head).normalized()

    axis_map = {
        '-Y': Vector((0, -1, 0)),
        '+Y': Vector((0, 1, 0)),
        '-X': Vector((-1, 0, 0)),
        '+X': Vector((1, 0, 0)),
        '-Z': Vector((0, 0, -1)),
        '+Z': Vector((0, 0, 1)),
    }
    fwd_axis = bones_info.get("_forward_axis", "-Y")
    world_forward = axis_map.get(fwd_axis, Vector((0, -1, 0)))

    # Project world forward perpendicular to the head bone axis
    forward = world_forward - head_up * head_up.dot(world_forward)
    if forward.length < 0.001:
        # Bone axis is parallel to chosen forward — pick a perpendicular fallback
        fallback = Vector((1, 0, 0)) if abs(head_up.x) < 0.9 else Vector((0, 0, 1))
        forward = fallback - head_up * head_up.dot(fallback)
    forward.normalize()

    # Place target well in front of the head (5x head length)
    target_pos = head_center + forward * head_len * 5.0

    lookat_name = f"{WRAP_CTRL_PREFIX}{chain_id}_LookAt_target"
    lookat = edit_bones.new(lookat_name)
    lookat.head = target_pos
    # Small vertical tail for visibility
    lookat.tail = target_pos + Vector((0, 0, bone_len))
    lookat.roll = 0
    created.append(lookat_name)

    # Store the head role in bones_info so _constrain_neck_head can find it
    bones_info.setdefault("_lookat_head_role", {})[chain_id] = bones_info.get(
        head_bone_name, {}).get("role", head_bone_name)

    return created


def _find_best_track_axis(armature_obj, head_mch_name, lookat_name):
    """Determine which DAMPED_TRACK axis enum points closest to the target.

    Tests all 6 axis candidates in the bone's rest-pose orientation and
    returns the axis enum string with highest dot product toward the target.
    """
    head_eb = armature_obj.data.bones.get(head_mch_name)
    lookat_eb = armature_obj.data.bones.get(lookat_name)
    if not head_eb or not lookat_eb:
        return 'TRACK_Y'  # fallback

    # Direction from head bone center to target in armature space
    head_center = (head_eb.head_local + head_eb.tail_local) * 0.5
    to_target = (lookat_eb.head_local - head_center).normalized()

    # Bone rest-pose matrix columns give local axes in armature space
    mat = head_eb.matrix_local.to_3x3()
    axis_candidates = [
        ('TRACK_X', mat.col[0].normalized()),
        ('TRACK_NEGATIVE_X', -mat.col[0].normalized()),
        ('TRACK_Y', mat.col[1].normalized()),
        ('TRACK_NEGATIVE_Y', -mat.col[1].normalized()),
        ('TRACK_Z', mat.col[2].normalized()),
        ('TRACK_NEGATIVE_Z', -mat.col[2].normalized()),
    ]

    best_axis = 'TRACK_Y'
    best_dot = -2.0
    for axis_enum, axis_dir in axis_candidates:
        d = axis_dir.dot(to_target)
        if d > best_dot:
            best_dot = d
            best_axis = axis_enum
    return best_axis


def _constrain_neck_head(armature_obj, chain_id, chain_bones, bones_info):
    """Add FK + LookAt constraints for neck/head chain."""
    _constrain_fk_chain(armature_obj, chain_id, chain_bones, bones_info)

    # Find head bone
    roles = {bones_info.get(b, {}).get("role", ""): b for b in chain_bones}
    head_bone_name = roles.get("head")
    if not head_bone_name:
        return

    head_role = bones_info.get(head_bone_name, {}).get("role", head_bone_name)
    head_mch = f"{WRAP_MCH_PREFIX}{chain_id}_{head_role}"
    lookat_name = f"{WRAP_CTRL_PREFIX}{chain_id}_LookAt_target"

    head_pbone = armature_obj.pose.bones.get(head_mch)
    lookat_pbone = armature_obj.pose.bones.get(lookat_name)
    if not head_pbone or not lookat_pbone:
        return

    # Auto-detect best track axis
    track_axis = _find_best_track_axis(armature_obj, head_mch, lookat_name)

    # DAMPED_TRACK constraint on head MCH
    con = head_pbone.constraints.new('DAMPED_TRACK')
    con.name = f"{WRAP_CONSTRAINT_PREFIX}LookAt"
    con.target = armature_obj
    con.subtarget = lookat_name
    con.track_axis = track_axis
    con.influence = 0.0  # Start in FK mode


def snap_lookat_to_fk(armature_obj, chain_id):
    """Position LookAt target where the head is currently facing (FK->LookAt snap).

    Reads the head bone's current world orientation and places the target
    along the tracked axis direction at the current distance.
    """
    sd = armature_obj.bt_scan
    chain_bones = [b for b in sd.bones if b.chain_id == chain_id and not b.skip]

    # Find head MCH bone with DAMPED_TRACK constraint
    head_mch_pb = None
    damped_con = None
    for bone_item in chain_bones:
        mch_name = f"{WRAP_MCH_PREFIX}{chain_id}_{bone_item.role}"
        mch_pb = armature_obj.pose.bones.get(mch_name)
        if not mch_pb:
            continue
        for c in mch_pb.constraints:
            if c.type == 'DAMPED_TRACK' and c.name.startswith(WRAP_CONSTRAINT_PREFIX):
                head_mch_pb = mch_pb
                damped_con = c
                break
        if head_mch_pb:
            break

    if not head_mch_pb or not damped_con:
        return

    lookat_name = f"{WRAP_CTRL_PREFIX}{chain_id}_LookAt_target"
    lookat_pb = armature_obj.pose.bones.get(lookat_name)
    if not lookat_pb:
        return

    # Current distance from head to target
    head_center = (head_mch_pb.head + head_mch_pb.tail) * 0.5
    current_dist = (lookat_pb.head - head_center).length
    if current_dist < 0.001:
        current_dist = (head_mch_pb.tail - head_mch_pb.head).length * 5.0

    # Get the tracked axis direction from the bone's current world matrix
    track_axis = damped_con.track_axis
    mat = head_mch_pb.matrix.to_3x3()

    axis_map = {
        'TRACK_X': mat.col[0].normalized(),
        'TRACK_NEGATIVE_X': -mat.col[0].normalized(),
        'TRACK_Y': mat.col[1].normalized(),
        'TRACK_NEGATIVE_Y': -mat.col[1].normalized(),
        'TRACK_Z': mat.col[2].normalized(),
        'TRACK_NEGATIVE_Z': -mat.col[2].normalized(),
    }
    forward = axis_map.get(track_axis, mat.col[1].normalized())

    # Place target along forward direction at current distance
    from mathutils import Matrix
    target_pos = head_center + forward * current_dist
    mat = Matrix.Translation(target_pos)
    lookat_pb.matrix = mat
    bpy.context.view_layer.update()


def save_lookat_state(armature_obj, chain_id):
    """Snapshot LookAt target position for quick restore."""
    lookat_name = f"{WRAP_CTRL_PREFIX}{chain_id}_LookAt_target"
    lookat_pb = armature_obj.pose.bones.get(lookat_name)
    if not lookat_pb:
        return

    key = _cache_key(armature_obj, chain_id)
    state = _ik_state_cache.get(key, {})
    state['lookat_matrix'] = lookat_pb.matrix.copy()
    _ik_state_cache[key] = state


def restore_lookat_state(armature_obj, chain_id):
    """Restore saved LookAt target position. Returns True if restored."""
    key = _cache_key(armature_obj, chain_id)
    state = _ik_state_cache.get(key)
    if not state or 'lookat_matrix' not in state:
        return False

    lookat_name = f"{WRAP_CTRL_PREFIX}{chain_id}_LookAt_target"
    lookat_pb = armature_obj.pose.bones.get(lookat_name)
    if not lookat_pb:
        return False

    lookat_pb.matrix = state['lookat_matrix']
    bpy.context.view_layer.update()
    return True


# --- Leg Controls ---

def _create_leg_controls(edit_bones, chain_id, chain_bones, bones_info,
                          orig_to_ctrl=None, orig_to_mch=None):
    """Create FK + IK controls for leg chain."""
    created = _create_fk_chain(edit_bones, chain_id, chain_bones, bones_info,
                                orig_to_ctrl, orig_to_mch)

    roles = {bones_info.get(b, {}).get("role", ""): b for b in chain_bones}
    foot_bone = roles.get("foot")
    lower_leg_bone = roles.get("lower_leg")
    upper_leg_bone = roles.get("upper_leg")

    if foot_bone and lower_leg_bone and upper_leg_bone:
        orig_foot = edit_bones.get(foot_bone)
        orig_lower = edit_bones.get(lower_leg_bone)
        orig_upper = edit_bones.get(upper_leg_bone)

        if orig_foot and orig_lower and orig_upper:
            bone_len = max((orig_lower.tail - orig_lower.head).length * 0.3, 0.5)

            # IK target at foot — oriented to match foot bone so that
            # COPY_ROTATION produces correct rest-pose orientation.
            ik_name = f"{WRAP_CTRL_PREFIX}{chain_id}_IK_target"
            ik_bone = edit_bones.new(ik_name)
            ik_bone.head = orig_foot.head.copy()
            foot_dir = (orig_foot.tail - orig_foot.head).normalized()
            ik_bone.tail = orig_foot.head + foot_dir * bone_len
            ik_bone.roll = orig_foot.roll
            created.append(ik_name)

            # IK pole at knee
            pole_name = f"{WRAP_CTRL_PREFIX}{chain_id}_IK_pole"
            pole_pos = _calculate_pole_position(
                orig_upper.head, orig_lower.head, orig_foot.head,
                module_type="leg",
            )
            pole_bone = edit_bones.new(pole_name)
            pole_bone.head = pole_pos
            pole_bone.tail = pole_pos + Vector((0, -bone_len * 0.5, 0))
            pole_bone.roll = 0
            created.append(pole_name)

            # Foot roll MCH bone
            roll_name = f"{WRAP_MCH_PREFIX}{chain_id}_foot_roll"
            roll_bone = edit_bones.new(roll_name)
            roll_bone.head = orig_foot.tail.copy()
            roll_bone.tail = orig_foot.tail + Vector((0, 0, bone_len * 0.3))
            roll_bone.roll = 0
            roll_bone.parent = ik_bone
            created.append(roll_name)

    return created


def _constrain_leg(armature_obj, chain_id, chain_bones, bones_info):
    """Add FK + IK constraints for leg chain.

    DEF → MCH and MCH → CTRL-FK via _constrain_fk_chain.
    IK constraint goes on the MCH bone (not DEF).
    chain_count is calculated dynamically from bone positions.
    Pole angle is set later by _calibrate_pole_angles.
    """
    _constrain_fk_chain(armature_obj, chain_id, chain_bones, bones_info)

    roles = {bones_info.get(b, {}).get("role", ""): b for b in chain_bones}
    lower_leg_bone = roles.get("lower_leg")
    upper_leg_bone = roles.get("upper_leg")

    if lower_leg_bone and upper_leg_bone:
        lower_role = bones_info.get(lower_leg_bone, {}).get("role", lower_leg_bone)
        mch_name = f"{WRAP_MCH_PREFIX}{chain_id}_{lower_role}"
        ik_target = f"{WRAP_CTRL_PREFIX}{chain_id}_IK_target"
        ik_pole = f"{WRAP_CTRL_PREFIX}{chain_id}_IK_pole"

        # Dynamic chain_count: number of bones from upper_leg to lower_leg
        upper_idx = chain_bones.index(upper_leg_bone)
        lower_idx = chain_bones.index(lower_leg_bone)
        chain_count = lower_idx - upper_idx + 1

        mch_pbone = armature_obj.pose.bones.get(mch_name)
        if mch_pbone and armature_obj.pose.bones.get(ik_target):
            con = mch_pbone.constraints.new('IK')
            con.name = f"{WRAP_CONSTRAINT_PREFIX}IK_leg"
            con.target = armature_obj
            con.subtarget = ik_target
            con.chain_count = chain_count
            con.use_stretch = False
            con.influence = 0.0  # Start with FK

            if armature_obj.pose.bones.get(ik_pole):
                con.pole_target = armature_obj
                con.pole_subtarget = ik_pole

    # Foot rotation from IK target (end-effector control).
    # When IK is active, the foot orientation follows the IK target bone.
    # Influence starts at 0.0 (FK mode) and is toggled by BT_OT_ToggleFKIK.
    foot_bone = roles.get("foot")
    if foot_bone:
        foot_role = bones_info.get(foot_bone, {}).get("role", foot_bone)
        foot_mch = f"{WRAP_MCH_PREFIX}{chain_id}_{foot_role}"
        ik_target = f"{WRAP_CTRL_PREFIX}{chain_id}_IK_target"
        foot_pbone = armature_obj.pose.bones.get(foot_mch)
        if foot_pbone and armature_obj.pose.bones.get(ik_target):
            con = foot_pbone.constraints.new('COPY_ROTATION')
            con.name = f"{WRAP_CONSTRAINT_PREFIX}IK_Rot"
            con.target = armature_obj
            con.subtarget = ik_target
            con.influence = 0.0  # Start with FK


# --- Helpers ---

def _calibrate_pole_angles(armature_obj):
    """Calibrate all IK pole angles using the depsgraph.

    For each IK constraint with a pole target:
    1. Find the joint with maximum perpendicular displacement from the
       root→tip axis (works for 2-bone, 3-bone, N-bone chains)
    2. Temporarily enable IK (disable FK, disable sync constraints)
       with pole_angle = 0
    3. Let the IK solver run via depsgraph update
    4. Measure how much the bend direction twisted from rest pose
    5. Set pole_angle to the signed correction that eliminates the twist

    Robust for any bone roll, mirrored bones, unusual orientations, or
    chain length because it directly measures what the IK solver produces
    and uses the geometrically strongest bend signal.
    """
    import math

    for pbone in armature_obj.pose.bones:
        if not pbone.bone.name.startswith(WRAP_MCH_PREFIX):
            continue

        # Find our IK constraint on this bone
        ik_con = None
        for c in pbone.constraints:
            if c.type == 'IK' and c.name.startswith(WRAP_CONSTRAINT_PREFIX):
                ik_con = c
                break
        if not ik_con or not ik_con.pole_target:
            continue

        chain_count = ik_con.chain_count

        # Walk up to find the upper bone in the IK chain
        upper_pb = pbone
        for _ in range(chain_count - 1):
            if upper_pb.parent:
                upper_pb = upper_pb.parent

        # Collect all MCH bones in the chain (tip to root order)
        chain_pbones = []
        pb = pbone
        for _ in range(chain_count):
            chain_pbones.append(pb)
            if pb.parent:
                pb = pb.parent

        # Collect FK constraints on MCH bones for save/restore
        saved_fk = []
        for cpb in chain_pbones:
            for c in cpb.constraints:
                if c.type == 'COPY_TRANSFORMS' and c.name.startswith(WRAP_CONSTRAINT_PREFIX):
                    saved_fk.append((c, c.influence, c.mute))

        # Disable sync constraints on IK target/pole to prevent circular
        # dependency (IK solver → MCH → sync → IK target → IK solver).
        saved_sync = []
        ik_target_name = ik_con.subtarget if ik_con.target else None
        ik_pole_name = ik_con.pole_subtarget if ik_con.pole_target else None
        for sync_bone_name in (ik_target_name, ik_pole_name):
            if not sync_bone_name:
                continue
            sync_pb = armature_obj.pose.bones.get(sync_bone_name)
            if not sync_pb:
                continue
            for c in sync_pb.constraints:
                if c.name.startswith(WRAP_CONSTRAINT_PREFIX):
                    saved_sync.append((c, c.influence, c.mute))
                    c.influence = 0.0
                    c.mute = True

        # Rest-pose bend direction: find the joint with MAXIMUM
        # perpendicular displacement from the root→tip axis.
        # This is the strongest bend signal and works for any chain length.
        chain_root = upper_pb.bone.head_local
        chain_tip = pbone.bone.tail_local
        chain_axis = (chain_tip - chain_root)
        if chain_axis.length < 0.0001:
            for c, inf, muted in saved_sync:
                c.influence = inf
                c.mute = muted
            continue
        chain_axis_n = chain_axis.normalized()

        best_disp = 0.0
        best_rest_bend = None
        best_joint_idx = -1
        # Check all internal joints (heads of all bones except the root)
        for i, cpb in enumerate(chain_pbones):
            joint = cpb.bone.head_local
            proj = chain_root + chain_axis_n * (joint - chain_root).dot(chain_axis_n)
            disp = joint - proj
            if disp.length > best_disp:
                best_disp = disp.length
                best_rest_bend = disp.copy()
                best_joint_idx = i

        if best_disp < 0.0001 or best_rest_bend is None:
            for c, inf, muted in saved_sync:
                c.influence = inf
                c.mute = muted
            continue
        best_rest_bend.normalize()

        # The pose bone corresponding to the max-displacement joint
        mid_pb = chain_pbones[best_joint_idx]

        # Temporarily enable IK with pole_angle=0, disable FK
        saved_ik_inf = ik_con.influence
        saved_ik_mute = ik_con.mute
        saved_pole = ik_con.pole_angle
        for c, _, _ in saved_fk:
            c.influence = 0.0
            c.mute = True
        ik_con.pole_angle = 0.0
        ik_con.influence = 1.0
        ik_con.mute = False

        bpy.context.view_layer.update()

        # Measure IK-solved bend direction at the same joint
        upper_head_pose = upper_pb.head.copy()
        mid_head_pose = mid_pb.head.copy()
        tip_pose = pbone.tail.copy()
        chain_pose = (tip_pose - upper_head_pose)
        if chain_pose.length < 0.0001:
            ik_con.pole_angle = saved_pole
            ik_con.influence = saved_ik_inf
            ik_con.mute = saved_ik_mute
            for c, inf, muted in saved_fk:
                c.influence = inf
                c.mute = muted
            for c, inf, muted in saved_sync:
                c.influence = inf
                c.mute = muted
            continue
        chain_pose_n = chain_pose.normalized()
        proj_pose = upper_head_pose + chain_pose_n * (mid_head_pose - upper_head_pose).dot(chain_pose_n)
        pose_bend = mid_head_pose - proj_pose
        if pose_bend.length < 0.0001:
            ik_con.pole_angle = saved_pole
            ik_con.influence = saved_ik_inf
            ik_con.mute = saved_ik_mute
            for c, inf, muted in saved_fk:
                c.influence = inf
                c.mute = muted
            for c, inf, muted in saved_sync:
                c.influence = inf
                c.mute = muted
            continue
        pose_bend.normalize()

        # Signed angle from pose_bend to rest_bend around chain_axis
        dot = max(-1.0, min(1.0, pose_bend.dot(best_rest_bend)))
        correction = math.acos(dot)
        cross = pose_bend.cross(best_rest_bend)
        if cross.dot(chain_axis_n) < 0:
            correction = -correction

        # Apply correction and restore FK mode + sync constraints
        ik_con.pole_angle = correction
        ik_con.influence = saved_ik_inf
        ik_con.mute = saved_ik_mute
        for c, inf, muted in saved_fk:
            c.influence = inf
            c.mute = muted
        for c, inf, muted in saved_sync:
            c.influence = inf
            c.mute = muted

    bpy.context.view_layer.update()


# ---------------------------------------------------------------------------
# IK state cache — save/restore for lossless FK↔IK roundtrips
# ---------------------------------------------------------------------------
# Keyed by (armature name, chain_id).  Stores IK control values at the
# moment of IK→FK snap so that FK→IK can restore them exactly if the user
# hasn't modified the FK pose.
_ik_state_cache = {}


def _cache_key(armature_obj, chain_id):
    return (armature_obj.name, chain_id)


def save_ik_state(armature_obj, chain_id):
    """Snapshot IK target/pole positions + pole_angle after IK→FK snap."""
    sd = armature_obj.bt_scan

    ik_target_name = f"{WRAP_CTRL_PREFIX}{chain_id}_IK_target"
    ik_pole_name = f"{WRAP_CTRL_PREFIX}{chain_id}_IK_pole"
    ik_target_pb = armature_obj.pose.bones.get(ik_target_name)
    ik_pole_pb = armature_obj.pose.bones.get(ik_pole_name)

    # Find pole_angle from IK constraint
    pole_angle = None
    chain_bones = [b for b in sd.bones if b.chain_id == chain_id and not b.skip]
    for bone_item in chain_bones:
        mch_name = f"{WRAP_MCH_PREFIX}{chain_id}_{bone_item.role}"
        mch_pb = armature_obj.pose.bones.get(mch_name)
        if mch_pb:
            for c in mch_pb.constraints:
                if c.type == 'IK' and c.name.startswith(WRAP_CONSTRAINT_PREFIX):
                    pole_angle = c.pole_angle
                    break
        if pole_angle is not None:
            break

    state = {
        'target_matrix': ik_target_pb.matrix.copy() if ik_target_pb else None,
        'pole_matrix': ik_pole_pb.matrix.copy() if ik_pole_pb else None,
        'pole_angle': pole_angle,
    }
    _ik_state_cache[_cache_key(armature_obj, chain_id)] = state


def save_fk_snapshot(armature_obj, chain_id):
    """Snapshot FK bone rotations after IK→FK snap for modification detection."""
    sd = armature_obj.bt_scan
    key = _cache_key(armature_obj, chain_id)
    state = _ik_state_cache.get(key)
    if not state:
        return

    fk_snapshot = {}
    chain_bones = [b for b in sd.bones if b.chain_id == chain_id and not b.skip]
    for bone_item in chain_bones:
        ctrl_name = f"{WRAP_CTRL_PREFIX}{chain_id}_FK_{bone_item.role}"
        ctrl_pb = armature_obj.pose.bones.get(ctrl_name)
        if ctrl_pb:
            fk_snapshot[bone_item.role] = ctrl_pb.matrix.copy()
    state['fk_snapshot'] = fk_snapshot


def fk_was_modified(armature_obj, chain_id):
    """Return True if FK bones were changed since the last IK→FK snap."""
    _POS_TOL_SQ = 1e-10   # ~10 nanometre — tighter than visible drift
    _ROT_TOL = 1e-8

    key = _cache_key(armature_obj, chain_id)
    state = _ik_state_cache.get(key)
    if not state or 'fk_snapshot' not in state:
        return True  # No snapshot — assume modified

    sd = armature_obj.bt_scan
    chain_bones = [b for b in sd.bones if b.chain_id == chain_id and not b.skip]
    for bone_item in chain_bones:
        ctrl_name = f"{WRAP_CTRL_PREFIX}{chain_id}_FK_{bone_item.role}"
        ctrl_pb = armature_obj.pose.bones.get(ctrl_name)
        if not ctrl_pb:
            continue
        saved = state['fk_snapshot'].get(bone_item.role)
        if saved is None:
            continue
        pos_err = (saved.translation - ctrl_pb.matrix.translation).length_squared
        if pos_err > _POS_TOL_SQ:
            return True
        saved_q = saved.to_quaternion()
        curr_q = ctrl_pb.matrix.to_quaternion()
        if abs(saved_q.dot(curr_q)) < (1.0 - _ROT_TOL):
            return True
    return False


def restore_ik_state(armature_obj, chain_id):
    """Restore saved IK target/pole/angle.  Returns True if restored."""
    key = _cache_key(armature_obj, chain_id)
    state = _ik_state_cache.get(key)
    if not state:
        return False

    sd = armature_obj.bt_scan

    # Restore IK target
    ik_target_name = f"{WRAP_CTRL_PREFIX}{chain_id}_IK_target"
    ik_target_pb = armature_obj.pose.bones.get(ik_target_name)
    if ik_target_pb and state['target_matrix']:
        ik_target_pb.matrix = state['target_matrix']

    # Restore IK pole
    ik_pole_name = f"{WRAP_CTRL_PREFIX}{chain_id}_IK_pole"
    ik_pole_pb = armature_obj.pose.bones.get(ik_pole_name)
    if ik_pole_pb and state['pole_matrix']:
        ik_pole_pb.matrix = state['pole_matrix']

    # Restore pole_angle
    if state['pole_angle'] is not None:
        chain_bones = [b for b in sd.bones if b.chain_id == chain_id and not b.skip]
        for bone_item in chain_bones:
            mch_name = f"{WRAP_MCH_PREFIX}{chain_id}_{bone_item.role}"
            mch_pb = armature_obj.pose.bones.get(mch_name)
            if mch_pb:
                for c in mch_pb.constraints:
                    if c.type == 'IK' and c.name.startswith(WRAP_CONSTRAINT_PREFIX):
                        c.pole_angle = state['pole_angle']
                        break

    bpy.context.view_layer.update()
    return True


def snap_fk_to_ik(armature_obj, chain_id):
    """Snap FK controls to match the current IK-solved pose.

    Call before switching from IK to FK so the pose is preserved.
    Reads the MCH bone matrices (driven by IK solver) and applies
    them to the CTRL-FK bones.

    Three-phase approach for high precision:
      1. Read all MCH world matrices (prevents constraint feedback).
      2. Initial matrix assignment, parent-first with per-bone update.
      3. Iterative Newton correction with per-bone updates — converges
         quadratically, eliminating visible drift even across keyframes.
    """
    sd = armature_obj.bt_scan
    chain_bones = [b for b in sd.bones if b.chain_id == chain_id and not b.skip]

    # Temporarily disable FK LIMIT_ROTATION constraints so they don't
    # clamp the matrix assignments during snap.
    _saved_fk_limits = []
    for bone_item in chain_bones:
        ctrl_name = f"{WRAP_CTRL_PREFIX}{chain_id}_FK_{bone_item.role}"
        ctrl_pb = armature_obj.pose.bones.get(ctrl_name)
        if not ctrl_pb:
            continue
        for c in ctrl_pb.constraints:
            if (c.type == 'LIMIT_ROTATION'
                    and c.name.startswith(WRAP_CONSTRAINT_PREFIX)):
                _saved_fk_limits.append((c, c.influence))
                c.influence = 0.0

    # Phase 1: Read ALL MCH world matrices before modifying anything.
    # Prevents constraint feedback from corrupting later reads when
    # view_layer.update() triggers re-evaluation of the chain.
    snap_pairs = []
    for bone_item in chain_bones:
        mch_name = f"{WRAP_MCH_PREFIX}{chain_id}_{bone_item.role}"
        ctrl_name = f"{WRAP_CTRL_PREFIX}{chain_id}_FK_{bone_item.role}"
        mch_pb = armature_obj.pose.bones.get(mch_name)
        ctrl_pb = armature_obj.pose.bones.get(ctrl_name)
        if mch_pb and ctrl_pb:
            snap_pairs.append((ctrl_pb, mch_pb.matrix.copy()))

    # Phase 2: Apply transforms parent-first with per-bone update.
    for ctrl_pb, target_matrix in snap_pairs:
        ctrl_pb.matrix = target_matrix
        bpy.context.view_layer.update()

    # Phase 3: Iterative correction — compensate for world-to-local
    # decomposition drift.  The roundtrip set_matrix → evaluate →
    # read_matrix is lossy (matrix ↔ loc/rot/scale decomposition).
    # Each pass applies the residual as a multiplicative Newton
    # correction, converging quadratically.  Per-bone updates ensure
    # that parent corrections propagate to children within the same
    # pass, preventing compounding chain errors.
    _POS_TOL_SQ = 1e-16   # ~0.1 nanometer squared
    _ROT_TOL = 1e-12      # quaternion dot threshold (1 − dot)
    _MAX_ITER = 4

    for _ in range(_MAX_ITER):
        any_corrected = False
        for ctrl_pb, target_matrix in snap_pairs:
            actual = ctrl_pb.matrix
            pos_err = target_matrix.translation - actual.translation
            tgt_q = target_matrix.to_quaternion()
            act_q = actual.to_quaternion()
            rot_dot = abs(tgt_q.dot(act_q))
            if pos_err.length_squared < _POS_TOL_SQ and rot_dot > (1.0 - _ROT_TOL):
                continue
            # Newton step: corrected = target @ actual⁻¹ @ target
            delta = target_matrix @ actual.inverted()
            ctrl_pb.matrix = delta @ target_matrix
            # Per-bone update so child bones see corrected parent
            bpy.context.view_layer.update()
            any_corrected = True
        if not any_corrected:
            break

    # Restore FK limit constraints
    for c, inf in _saved_fk_limits:
        c.influence = inf


def snap_ik_to_fk(armature_obj, chain_id):
    """Snap IK target and pole to match the current FK pose.

    Call before switching from FK to IK so the pose is preserved.
    Works for any chain_count (2-bone, 3-bone, N-bone):

    1. Read the FK-posed chain geometry (root, mid, tip from MCH bones)
    2. Position IK target at the chain tip
    3. Reset pole to rest, then calibrate pole_angle to match FK bend plane
    4. For 2-bone: exact match. For 3+: approximate (IK distributes differently)

    Hierarchy during IK mode:
      MCH bones inside chain_count → driven by IK solver (FK off)
      MCH bones outside (foot/toe) → keep FK active, inherit IK-solved parent
    """
    import math

    from mathutils import Matrix

    sd = armature_obj.bt_scan

    # Find the MCH bone that has the IK constraint
    chain_bones = [b for b in sd.bones if b.chain_id == chain_id and not b.skip]
    ik_mch = None
    ik_con = None
    ik_chain_count = 0
    for bone_item in chain_bones:
        mch_name = f"{WRAP_MCH_PREFIX}{chain_id}_{bone_item.role}"
        mch_pb = armature_obj.pose.bones.get(mch_name)
        if mch_pb:
            for c in mch_pb.constraints:
                if c.type == 'IK' and c.name.startswith(WRAP_CONSTRAINT_PREFIX):
                    ik_mch = mch_pb
                    ik_con = c
                    ik_chain_count = c.chain_count
                    break
        if ik_mch:
            break

    if not ik_mch or not ik_con:
        return

    # Walk up to find the root bone of the IK chain and collect chain bones
    upper_pb = ik_mch
    ik_chain_pbones = [ik_mch]
    for _ in range(ik_chain_count - 1):
        if upper_pb.parent:
            upper_pb = upper_pb.parent
            ik_chain_pbones.append(upper_pb)

    # Find the mid bone for bend-plane measurement.
    # Use the joint with MAXIMUM perpendicular displacement from the
    # root→tip axis — this is the strongest bend signal for any chain length.
    def _find_max_disp_bone():
        """Return the pose bone whose head is most displaced from chain axis."""
        root_pos = upper_pb.head.copy()
        tip_pos = ik_mch.tail.copy()
        axis = tip_pos - root_pos
        if axis.length < 0.0001:
            return ik_mch  # fallback
        axis_n = axis.normalized()
        best_bone = ik_mch
        best_disp = 0.0
        for cpb in ik_chain_pbones:
            joint = cpb.head.copy()
            proj = root_pos + axis_n * (joint - root_pos).dot(axis_n)
            disp = (joint - proj).length
            if disp > best_disp:
                best_disp = disp
                best_bone = cpb
        return best_bone

    def mid_point_getter():
        return _find_max_disp_bone().head.copy()

    # Snap IK target to the chain tip (tail of the IK bone = foot/hand).
    # Also snap rotation to match the FK-posed end effector (hand/foot).
    ik_target_name = f"{WRAP_CTRL_PREFIX}{chain_id}_IK_target"
    ik_target_pb = armature_obj.pose.bones.get(ik_target_name)
    if ik_target_pb:
        fk_tip = ik_mch.tail.copy()

        # Find the end-effector MCH bone (has COPY_ROTATION from IK target)
        effector_pb = None
        for bone_item in chain_bones:
            eff_mch = f"{WRAP_MCH_PREFIX}{chain_id}_{bone_item.role}"
            eff_pb = armature_obj.pose.bones.get(eff_mch)
            if not eff_pb:
                continue
            for c in eff_pb.constraints:
                if (c.type == 'COPY_ROTATION'
                        and c.name.startswith(WRAP_CONSTRAINT_PREFIX)
                        and c.subtarget == ik_target_name):
                    effector_pb = eff_pb
                    break
            if effector_pb:
                break

        if effector_pb:
            # Build matrix with position at chain tip + rotation from effector
            rot = effector_pb.matrix.to_3x3()
            mat = rot.to_4x4()
            mat.translation = fk_tip
        else:
            mat = Matrix.Translation(fk_tip)

        ik_target_pb.matrix = mat
        bpy.context.view_layer.update()

    # Position pole at the FK bend direction so it visually tracks the bend
    # and gives the IK solver an accurate spatial hint (reduces drift).
    ik_pole_name = f"{WRAP_CTRL_PREFIX}{chain_id}_IK_pole"
    ik_pole_pb = armature_obj.pose.bones.get(ik_pole_name)
    if ik_pole_pb:
        fk_root_pos = upper_pb.head.copy()
        fk_mid_pos = mid_point_getter()
        fk_tip_pos = ik_mch.tail.copy()
        fk_axis = fk_tip_pos - fk_root_pos
        pole_placed = False
        if fk_axis.length > 0.0001:
            fk_axis_n = fk_axis.normalized()
            proj = fk_root_pos + fk_axis_n * (fk_mid_pos - fk_root_pos).dot(fk_axis_n)
            bend_dir = fk_mid_pos - proj
            if bend_dir.length > 0.0001:
                bend_dir.normalize()
                chain_length = fk_axis.length
                pole_pos = fk_mid_pos + bend_dir * chain_length * 0.5
                ik_pole_pb.matrix = Matrix.Translation(pole_pos)
                bpy.context.view_layer.update()
                pole_placed = True
        if not pole_placed:
            # Chain is nearly straight — fall back to rest position
            ik_pole_pb.location = Vector((0, 0, 0))
            ik_pole_pb.rotation_quaternion = (1, 0, 0, 0)
            ik_pole_pb.rotation_euler = (0, 0, 0)
            ik_pole_pb.scale = (1, 1, 1)

    # Calibrate pole_angle so IK bend plane matches FK bend plane.
    # Uses max-displacement joint for robust N-bone support.
    # Temporarily enables IK via the custom property so drivers propagate
    # constraint influences correctly.
    if ik_chain_count >= 2 and ik_pole_pb and ik_con.pole_target:
        # Record FK bend direction (MCH bones currently driven by FK)
        fk_root = upper_pb.head.copy()
        fk_mid = mid_point_getter()
        fk_tip = ik_mch.tail.copy()
        fk_axis = (fk_tip - fk_root)
        if fk_axis.length > 0.0001:
            fk_axis_n = fk_axis.normalized()
            fk_proj = fk_root + fk_axis_n * (fk_mid - fk_root).dot(fk_axis_n)
            fk_bend = fk_mid - fk_proj
            if fk_bend.length > 0.0001:
                fk_bend.normalize()

                # Temporarily enable IK via custom property — drivers
                # handle all FK/IK constraint toggling automatically.
                prop_name = _ik_switch_prop_name(chain_id)
                saved_prop = armature_obj.get(prop_name, 0.0)
                saved_pole = ik_con.pole_angle
                armature_obj[prop_name] = 1.0
                bpy.context.view_layer.update()

                # Measure IK solver's bend direction at the same mid bone
                ik_root = upper_pb.head.copy()
                ik_mid = mid_point_getter()
                ik_tip = ik_mch.tail.copy()
                ik_axis = (ik_tip - ik_root)
                if ik_axis.length > 0.0001:
                    ik_axis_n = ik_axis.normalized()
                    ik_proj = ik_root + ik_axis_n * (ik_mid - ik_root).dot(ik_axis_n)
                    ik_bend = ik_mid - ik_proj
                    if ik_bend.length > 0.0001:
                        ik_bend.normalize()
                        dot = max(-1.0, min(1.0, ik_bend.dot(fk_bend)))
                        correction = math.acos(dot)
                        cross = ik_bend.cross(fk_bend)
                        if cross.dot(ik_axis_n) < 0:
                            correction = -correction
                        ik_con.pole_angle = saved_pole + correction

                        # Iterative pole angle refinement — reduce residual
                        # bend error that the single-pass correction leaves.
                        _ANGLE_TOL = 1e-7  # radians (~0.006 millidegrees)
                        for _ in range(3):
                            bpy.context.view_layer.update()
                            ik_mid2 = mid_point_getter()
                            ik_root2 = upper_pb.head.copy()
                            ik_tip2 = ik_mch.tail.copy()
                            ik_axis2 = ik_tip2 - ik_root2
                            if ik_axis2.length < 0.0001:
                                break
                            ik_axis2_n = ik_axis2.normalized()
                            ik_proj2 = ik_root2 + ik_axis2_n * (ik_mid2 - ik_root2).dot(ik_axis2_n)
                            ik_bend2 = ik_mid2 - ik_proj2
                            if ik_bend2.length < 0.0001:
                                break
                            ik_bend2.normalize()
                            dot2 = max(-1.0, min(1.0, ik_bend2.dot(fk_bend)))
                            residual = math.acos(dot2)
                            if residual < _ANGLE_TOL:
                                break
                            cross2 = ik_bend2.cross(fk_bend)
                            if cross2.dot(ik_axis2_n) < 0:
                                residual = -residual
                            ik_con.pole_angle += residual

                # Restore property to FK state (toggle operator sets IK later)
                armature_obj[prop_name] = saved_prop
                bpy.context.view_layer.update()

    # --- Newton correction: pre-compensate IK target for solver residual ---
    # After pole positioning + angle calibration, temporarily enable IK and
    # verify the chain tip actually reaches the desired position.  If the
    # solver has any residual (IK limits, 3+ bone iterative solving, bone
    # roll interactions), shift the IK target to cancel the offset.
    if ik_target_pb and ik_chain_count >= 2:
        desired_tip = ik_mch.tail.copy()  # FK-posed tip (still in FK mode)

        # Temporarily enable IK via custom property
        prop_name = _ik_switch_prop_name(chain_id)
        saved_prop = armature_obj.get(prop_name, 0.0)
        armature_obj[prop_name] = 1.0
        bpy.context.view_layer.update()

        _POS_TOL_SQ = 1e-16   # ~0.1 nanometre squared
        for _ in range(4):
            actual_tip = ik_mch.tail.copy()
            err = desired_tip - actual_tip
            if err.length_squared < _POS_TOL_SQ:
                break
            cur = ik_target_pb.matrix.copy()
            cur.translation += err
            ik_target_pb.matrix = cur
            bpy.context.view_layer.update()

        # Restore to FK state (toggle operator switches to IK later)
        armature_obj[prop_name] = saved_prop
        bpy.context.view_layer.update()


def snap_spline_to_fk(armature_obj, chain_id):
    """Snap spline hook bones to match the current FK pose.

    Call before switching from FK to Spline IK so the curve follows the FK pose.
    Reads the posed MCH bone positions and places each hook control bone at
    its parametric position along the chain.
    """
    from mathutils import Matrix

    sd = armature_obj.bt_scan
    chain_bones = [b for b in sd.bones if b.chain_id == chain_id and not b.skip]
    if len(chain_bones) < 2:
        return

    # Collect posed MCH bone head/tail positions
    segments = []  # list of (head, tail, length)
    for bone_item in chain_bones:
        mch_name = f"{WRAP_MCH_PREFIX}{chain_id}_{bone_item.role}"
        mch_pb = armature_obj.pose.bones.get(mch_name)
        if not mch_pb:
            continue
        h = mch_pb.head.copy()
        t = mch_pb.tail.copy()
        segments.append((h, t, (t - h).length))

    if not segments:
        return

    total_len = sum(s[2] for s in segments)
    if total_len < 0.0001:
        return

    # Find all spline hook bones for this chain
    hook_bones = []
    for i in range(10):  # max 5 hooks, but be safe
        ctrl_name = f"{WRAP_CTRL_PREFIX}{chain_id}_Spline_{i:02d}"
        pb = armature_obj.pose.bones.get(ctrl_name)
        if pb:
            hook_bones.append(pb)
        else:
            break

    if not hook_bones:
        return

    n_hooks = len(hook_bones)

    for idx, hook_pb in enumerate(hook_bones):
        t = idx / (n_hooks - 1) if n_hooks > 1 else 0.0

        if t <= 0.0:
            pos = segments[0][0]
        elif t >= 1.0:
            pos = segments[-1][1]
        else:
            target_len = t * total_len
            accum = 0.0
            pos = segments[-1][1]  # fallback
            for head, tail, seg_len in segments:
                if accum + seg_len >= target_len:
                    frac = (target_len - accum) / seg_len if seg_len > 0 else 0
                    pos = head.lerp(tail, frac)
                    break
                accum += seg_len

        hook_pb.matrix = Matrix.Translation(pos)
        bpy.context.view_layer.update()


def _calculate_pole_position(head_a, head_b, head_c, module_type="generic"):
    """Calculate IK pole position from 3-bone geometry with anatomical validation.

    Projects the middle joint outward perpendicular to the plane
    formed by the three joint positions. For arms/legs, validates
    the direction against anatomical expectations and uses defaults
    when the geometric bend is too weak or points the wrong way.

    Args:
        head_a: Root joint position (e.g. upper arm/leg head).
        head_b: Middle joint position (e.g. elbow/knee head).
        head_c: End joint position (e.g. hand/foot head).
        module_type: "arm", "leg", or "generic" -- guides anatomical fallback.
    """
    mid = head_b
    chain_length = (head_a - head_c).length
    a_to_c = (head_c - head_a).normalized()
    a_to_b = head_b - head_a
    projection = head_a + a_to_c * a_to_b.dot(a_to_c)
    pole_dir = (mid - projection)
    bend_magnitude = pole_dir.length

    # Anatomical expected directions (Blender: -Y = forward, +Y = backward)
    anatomical_defaults = {
        "leg": Vector((0, -1, 0)),   # Knee bends forward
        "arm": Vector((0, 1, 0)),    # Elbow bends backward
    }

    if module_type in anatomical_defaults:
        expected = anatomical_defaults[module_type]
        # Nearly straight chain: bend too small to trust geometry
        if bend_magnitude < chain_length * 0.01:
            pole_dir = expected.copy()
        else:
            pole_dir.normalize()
            # Weak bend that opposes expectation -- don't trust it
            if bend_magnitude < chain_length * 0.10 and pole_dir.dot(expected) < 0:
                pole_dir = expected.copy()
    else:
        if bend_magnitude < 0.001:
            pole_dir = Vector((0, -1, 0))
        else:
            pole_dir.normalize()

    # Place pole at a reasonable distance from the mid joint
    distance = chain_length * 0.5
    return mid + pole_dir * distance


# --- Generic IK Chain (finger, generic with ik_enabled) ---

def _create_ik_chain(edit_bones, chain_id, chain_bones, bones_info,
                      orig_to_ctrl=None, orig_to_mch=None):
    """Create FK controls + IK target/pole for any chain with IK enabled."""
    created = _create_fk_chain(edit_bones, chain_id, chain_bones, bones_info,
                                orig_to_ctrl, orig_to_mch)

    if len(chain_bones) < 2:
        return created

    # IK target at the tail of the last bone
    last_bone_name = chain_bones[-1]
    orig_last = edit_bones.get(last_bone_name)
    if not orig_last:
        return created

    bone_len = max((orig_last.tail - orig_last.head).length * 0.3, 0.5)

    ik_name = f"{WRAP_CTRL_PREFIX}{chain_id}_IK_target"
    ik_bone = edit_bones.new(ik_name)
    ik_bone.head = orig_last.tail.copy()
    ik_bone.tail = orig_last.tail + Vector((0, -bone_len, 0))
    ik_bone.roll = 0
    created.append(ik_name)

    # Pole target for chains with 3+ bones
    if len(chain_bones) >= 3:
        first_bone = edit_bones.get(chain_bones[0])
        mid_bone = edit_bones.get(chain_bones[len(chain_bones) // 2])
        if first_bone and mid_bone:
            pole_name = f"{WRAP_CTRL_PREFIX}{chain_id}_IK_pole"
            pole_pos = _calculate_pole_position(
                first_bone.head, mid_bone.head, orig_last.tail,
            )
            pole_bone = edit_bones.new(pole_name)
            pole_bone.head = pole_pos
            pole_bone.tail = pole_pos + Vector((0, -bone_len * 0.5, 0))
            pole_bone.roll = 0
            created.append(pole_name)

    return created


def _constrain_ik_chain(armature_obj, chain_id, chain_bones, bones_info,
                        ik_snap=False):
    """Add FK + IK constraints for a generic IK chain.

    IK constraint goes on the MCH bone of the last chain bone.
    If ik_snap is True, chain_count is clamped to 2 for stable FK/IK switching.
    """
    _constrain_fk_chain(armature_obj, chain_id, chain_bones, bones_info)

    if len(chain_bones) < 2:
        return

    chain_count = 2 if ik_snap else len(chain_bones)

    last_bone_name = chain_bones[-1]
    last_role = bones_info.get(last_bone_name, {}).get("role", last_bone_name)
    mch_name = f"{WRAP_MCH_PREFIX}{chain_id}_{last_role}"
    ik_target = f"{WRAP_CTRL_PREFIX}{chain_id}_IK_target"
    ik_pole = f"{WRAP_CTRL_PREFIX}{chain_id}_IK_pole"

    mch_pbone = armature_obj.pose.bones.get(mch_name)
    if not mch_pbone or not armature_obj.pose.bones.get(ik_target):
        return

    con = mch_pbone.constraints.new('IK')
    con.name = f"{WRAP_CONSTRAINT_PREFIX}IK_{chain_id}"
    con.target = armature_obj
    con.subtarget = ik_target
    con.chain_count = chain_count
    con.use_stretch = False
    con.influence = 0.0  # Start with FK, user toggles IK

    if armature_obj.pose.bones.get(ik_pole) and chain_count >= 2:
        con.pole_target = armature_obj
        con.pole_subtarget = ik_pole
        # pole_angle is set later by _calibrate_pole_angles()

    # End-effector rotation from IK target.
    # When IK is active, the tip bone orientation follows the IK target.
    # Influence starts at 0.0 (FK mode) and is toggled by BT_OT_ToggleFKIK.
    # For chains where IK doesn't cover the last bone (ik_snap / chain_count < len),
    # add COPY_ROTATION so the end effector tracks the IK target rotation.
    if chain_count < len(chain_bones):
        tip_bone_name = chain_bones[-1]
        tip_role = bones_info.get(tip_bone_name, {}).get("role", tip_bone_name)
        tip_mch = f"{WRAP_MCH_PREFIX}{chain_id}_{tip_role}"
        tip_pbone = armature_obj.pose.bones.get(tip_mch)
        if tip_pbone and armature_obj.pose.bones.get(ik_target):
            rot_con = tip_pbone.constraints.new('COPY_ROTATION')
            rot_con.name = f"{WRAP_CONSTRAINT_PREFIX}IK_Rot"
            rot_con.target = armature_obj
            rot_con.subtarget = ik_target
            rot_con.influence = 0.0  # Start with FK


# --- Spline IK Chain ---

def _create_spline_ik_chain(edit_bones, chain_id, chain_bones, bones_info,
                             orig_to_ctrl=None, orig_to_mch=None):
    """Create FK controls + spline hook bones for a Spline IK chain.

    Returns (created_bone_names, spline_info) where spline_info is a dict
    with control point positions and hook bone names for curve creation.
    """
    created = _create_fk_chain(edit_bones, chain_id, chain_bones, bones_info,
                                orig_to_ctrl, orig_to_mch)

    if len(chain_bones) < 2:
        return created, None

    # Determine number of control points (3–5 based on chain length)
    n_bones = len(chain_bones)
    if n_bones <= 4:
        n_controls = 3
    elif n_bones <= 8:
        n_controls = 4
    else:
        n_controls = 5

    # Calculate control point positions evenly along the chain
    positions = []
    for i in range(n_controls):
        t = i / (n_controls - 1)
        if t == 0.0:
            bone = edit_bones.get(chain_bones[0])
            pos = bone.head.copy() if bone else Vector((0, 0, 0))
        elif t >= 1.0:
            bone = edit_bones.get(chain_bones[-1])
            pos = bone.tail.copy() if bone else Vector((0, 0, 0))
        else:
            # Walk along cumulative bone lengths
            bone_lengths = []
            for bn in chain_bones:
                b = edit_bones.get(bn)
                bone_lengths.append((b.tail - b.head).length if b else 0.0)
            total_len = sum(bone_lengths)
            target_len = t * total_len
            accum = 0.0
            pos = Vector((0, 0, 0))
            for j, bn in enumerate(chain_bones):
                b = edit_bones.get(bn)
                if not b:
                    continue
                seg_len = bone_lengths[j]
                if accum + seg_len >= target_len:
                    frac = (target_len - accum) / seg_len if seg_len > 0 else 0
                    pos = b.head.lerp(b.tail, frac)
                    break
                accum += seg_len
        positions.append(pos)

    # Create CTRL hook bones at each control point
    hook_names = []
    first_bone = edit_bones.get(chain_bones[0])
    bone_len = 0.5
    if first_bone:
        bone_len = max((first_bone.tail - first_bone.head).length * 0.4, 0.3)

    for i, pos in enumerate(positions):
        ctrl_name = f"{WRAP_CTRL_PREFIX}{chain_id}_Spline_{i:02d}"
        ctrl = edit_bones.new(ctrl_name)
        ctrl.head = pos
        ctrl.tail = pos + Vector((0, 0, bone_len))
        ctrl.roll = 0
        # Parent ALL hooks to cross-chain parent so the whole spline
        # follows the body when parent bones rotate
        if first_bone and orig_to_mch:
            parent_mch = _find_cross_chain_parent(edit_bones, first_bone, orig_to_mch)
            if parent_mch:
                ctrl.parent = parent_mch
        created.append(ctrl_name)
        hook_names.append(ctrl_name)

    spline_info = {
        "positions": positions,
        "hook_names": hook_names,
        "n_bones": n_bones,
    }
    return created, spline_info


def _create_spline_curve(armature_obj, chain_id, spline_info):
    """Create a Bezier curve object and hook it to the spline control bones.

    Called in Object mode after bones have been created.
    """
    positions = spline_info["positions"]
    hook_names = spline_info["hook_names"]

    curve_name = f"{WRAP_SPLINE_PREFIX}{chain_id}"
    curve_data = bpy.data.curves.new(name=curve_name, type='CURVE')
    curve_data.dimensions = '3D'
    curve_data.resolution_u = 24

    spline = curve_data.splines.new('BEZIER')
    spline.bezier_points.add(len(positions) - 1)  # Already has 1 point

    for i, pt in enumerate(spline.bezier_points):
        pt.co = positions[i]
        pt.handle_left_type = 'AUTO'
        pt.handle_right_type = 'AUTO'

    curve_obj = bpy.data.objects.new(curve_name, curve_data)
    bpy.context.collection.objects.link(curve_obj)
    curve_obj.parent = armature_obj
    curve_obj.hide_viewport = False
    curve_obj.hide_render = True

    # Hook each control point to its bone
    for i, hook_bone_name in enumerate(hook_names):
        hook_mod = curve_obj.modifiers.new(name=f"Hook_{i:02d}", type='HOOK')
        hook_mod.object = armature_obj
        hook_mod.subtarget = hook_bone_name
        # Each bezier point has 3 vertices: left_handle, knot, right_handle
        vertex_indices = [3 * i, 3 * i + 1, 3 * i + 2]
        hook_mod.vertex_indices_set(vertex_indices)

    return curve_obj


def _constrain_spline_ik_chain(armature_obj, chain_id, chain_bones, bones_info,
                                curve_obj):
    """Add FK + Spline IK constraints for a chain.

    SPLINE_IK constraint goes on the LAST MCH bone (walks UP the parent chain,
    same as regular IK in Blender).
    FK COPY_TRANSFORMS are set up on all MCH bones (toggled for FK/IK switching).
    """
    _constrain_fk_chain(armature_obj, chain_id, chain_bones, bones_info)

    if len(chain_bones) < 2 or not curve_obj:
        return

    # SPLINE_IK goes on the LAST MCH bone (walks up the chain like regular IK)
    last_role = bones_info.get(chain_bones[-1], {}).get("role", chain_bones[-1])
    mch_name = f"{WRAP_MCH_PREFIX}{chain_id}_{last_role}"
    mch_pbone = armature_obj.pose.bones.get(mch_name)
    if not mch_pbone:
        return

    con = mch_pbone.constraints.new('SPLINE_IK')
    con.name = f"{WRAP_CONSTRAINT_PREFIX}SplineIK_{chain_id}"
    con.target = curve_obj
    con.chain_count = len(chain_bones)
    con.use_chain_offset = False
    con.y_scale_mode = 'BONE_ORIGINAL'
    con.xz_scale_mode = 'BONE_ORIGINAL'
    con.influence = 0.0  # Start in FK mode


# --- IK Rotation Limits ---

def _detect_bend_axis(armature_obj, bone_name):
    """Detect the primary bend axis for a bone by examining rest-pose geometry.

    Returns ('X', 'Y', or 'Z') and the sign (+1 or -1) of the natural bend.
    """
    pbone = armature_obj.pose.bones.get(bone_name)
    if not pbone or not pbone.parent:
        return 'X', 1

    parent = pbone.parent
    parent_dir = (parent.bone.tail_local - parent.bone.head_local).normalized()
    child_dir = (pbone.bone.tail_local - pbone.bone.head_local).normalized()

    # Cross product gives the rotation axis in armature space
    bend_axis_world = parent_dir.cross(child_dir)
    if bend_axis_world.length < 0.0001:
        return 'X', 1

    # Transform to bone-local space
    bone_matrix = pbone.bone.matrix_local.to_3x3()
    bend_axis_local = bone_matrix.inverted() @ bend_axis_world
    bend_axis_local.normalize()

    # Find dominant axis
    components = [
        ('X', bend_axis_local.x),
        ('Y', bend_axis_local.y),
        ('Z', bend_axis_local.z),
    ]
    axis, value = max(components, key=lambda c: abs(c[1]))
    return axis, (1 if value >= 0 else -1)


def _compute_joint_limits(armature_obj, mch_name, role, module_type):
    """Compute rotation limits for a joint.

    Returns a dict: {axis: (min_rad, max_rad, stiffness)} for X, Y, Z.
    This is the single source of truth used by both IK limits (on MCH)
    and FK LIMIT_ROTATION constraints (on CTRL-FK).
    """
    limits = {}

    if module_type in ("arm", "leg"):
        bend_axis, bend_sign = _detect_bend_axis(armature_obj, mch_name)
        is_mid_joint = role in ("lower_arm", "lower_leg")

        if is_mid_joint:
            for axis in ('X', 'Y', 'Z'):
                if axis == bend_axis:
                    if bend_sign > 0:
                        limits[axis] = (0.0, math.radians(160), 0.0)
                    else:
                        limits[axis] = (math.radians(-160), 0.0, 0.0)
                else:
                    limits[axis] = (math.radians(-5), math.radians(5), 0.9)
        else:
            for axis in ('X', 'Y', 'Z'):
                limits[axis] = (math.radians(-120), math.radians(120), 0.0)

    elif module_type == "tail":
        lim = math.radians(45)
        for axis in ('X', 'Y', 'Z'):
            limits[axis] = (-lim, lim, 0.1)
    elif module_type == "tentacle":
        lim = math.radians(60)
        for axis in ('X', 'Y', 'Z'):
            limits[axis] = (-lim, lim, 0.05)
    else:
        lim = math.radians(90)
        for axis in ('X', 'Y', 'Z'):
            limits[axis] = (-lim, lim, 0.0)

    return limits


def _add_sync_constraints(armature_obj, chain_id, chain_bones, bones_info):
    """Add FK sync constraints so FK controls mirror the IK-driven pose.

    FK sync (on FK CTRL bones):
        COPY_TRANSFORMS from MCH → FK bones mirror IK-driven MCH in real-time.
        Active in IK mode (influence=1), off in FK mode (influence=0).
        Added LAST in the constraint stack so it overrides joint limits.

    IK target/pole do NOT get sync constraints.  Adding them would create a
    circular dependency in Blender's depsgraph (MCH reads IK target via
    COPY_ROTATION, IK target reads MCH via sync → cycle).  Instead, IK
    controls are positioned by the snap operators at toggle time.
    """
    # --- FK sync: each FK CTRL copies its MCH counterpart ---
    for bone_name in chain_bones:
        role = bones_info.get(bone_name, {}).get("role", bone_name)
        mch_name = f"{WRAP_MCH_PREFIX}{chain_id}_{role}"
        ctrl_name = f"{WRAP_CTRL_PREFIX}{chain_id}_FK_{role}"
        mch_pb = armature_obj.pose.bones.get(mch_name)
        ctrl_pb = armature_obj.pose.bones.get(ctrl_name)
        if not mch_pb or not ctrl_pb:
            continue

        # Only add sync to bones that have an IK alternative (not toe etc.)
        has_ik = any(
            c.type in ('IK', 'SPLINE_IK', 'COPY_ROTATION', 'DAMPED_TRACK')
            and c.name.startswith(WRAP_CONSTRAINT_PREFIX)
            for c in mch_pb.constraints
        )
        if not has_ik:
            continue

        # Skip if FK_sync already exists on this bone
        sync_name = f"{WRAP_CONSTRAINT_PREFIX}FK_sync"
        if any(c.name == sync_name for c in ctrl_pb.constraints):
            continue

        con = ctrl_pb.constraints.new('COPY_TRANSFORMS')
        con.name = sync_name
        con.target = armature_obj
        con.subtarget = mch_name
        # Start at 0 — FK mode is default; toggle operator activates in IK mode
        con.influence = 0.0


# ---------------------------------------------------------------------------
# IK/FK custom property + drivers
# ---------------------------------------------------------------------------
# One float property per chain (0.0=FK, 1.0=IK) on the armature object.
# Drivers on all MCH constraint influences + FK_sync reference this property.
# The toggle operator sets the property — animation only touches it when the
# user explicitly keyframes via smart_keyframe.
# ---------------------------------------------------------------------------

IK_SWITCH_PROP_PREFIX = "ik_switch_"


def _ik_switch_prop_name(chain_id):
    """Return the custom property name for a chain's IK/FK switch."""
    return f"{IK_SWITCH_PROP_PREFIX}{chain_id}"


def _add_ik_switch_property(armature_obj, chain_id):
    """Add a custom float property for IK/FK switching on this chain.

    The property lives on the armature object (not bone) so drivers can
    reference it via ``self["ik_switch_{chain_id}"]``.
    """
    prop_name = _ik_switch_prop_name(chain_id)
    # Default 0.0 = FK mode
    armature_obj[prop_name] = 0.0

    # Register the property UI metadata so it shows in the properties panel
    id_props = armature_obj.id_properties_ui(prop_name)
    id_props.update(min=0.0, max=1.0, soft_min=0.0, soft_max=1.0,
                    description=f"IK/FK blend for {chain_id} (0=FK, 1=IK)")


def _add_influence_driver(armature_obj, data_path, prop_name, invert=False):
    """Add a driver on a constraint influence that reads the custom property.

    Args:
        armature_obj: The armature object.
        data_path: Full data path to the constraint influence.
        prop_name: Name of the custom property to read (e.g. 'ik_switch_arm_L').
        invert: If True, influence = 1 - property (for FK constraints that
                are active when IK is off).
    """
    fc = armature_obj.driver_add(data_path)
    driver = fc.driver
    driver.type = 'SCRIPTED'

    var = driver.variables.new()
    var.name = "ik"
    var.type = 'SINGLE_PROP'
    target = var.targets[0]
    target.id_type = 'OBJECT'
    target.id = armature_obj
    target.data_path = f'["{prop_name}"]'

    if invert:
        driver.expression = "1.0 - ik"
    else:
        driver.expression = "ik"

    return fc


def _setup_ik_switch_drivers(armature_obj, chain_id, chain_bones, bones_info):
    """Wire drivers from ik_switch_{chain_id} to all constraint influences.

    Replaces static influence values with drivers so the toggle operator
    only needs to set one custom property — all constraints follow via deps.
    """
    prop_name = _ik_switch_prop_name(chain_id)

    for bone_name in chain_bones:
        role = bones_info.get(bone_name, {}).get("role", bone_name)
        mch_name = f"{WRAP_MCH_PREFIX}{chain_id}_{role}"
        mch_pb = armature_obj.pose.bones.get(mch_name)
        if not mch_pb:
            continue

        # Check if this bone has any IK-related constraint
        has_ik_constraint = any(
            c.type in ('IK', 'SPLINE_IK', 'COPY_ROTATION', 'DAMPED_TRACK')
            and c.name.startswith(WRAP_CONSTRAINT_PREFIX)
            for c in mch_pb.constraints
        )

        for con in mch_pb.constraints:
            if not con.name.startswith(WRAP_CONSTRAINT_PREFIX):
                continue

            data_path = f'pose.bones["{mch_name}"].constraints["{con.name}"].influence'

            if con.type == 'COPY_TRANSFORMS':
                if has_ik_constraint:
                    # FK constraint: active when property is 0 (FK mode)
                    _add_influence_driver(armature_obj, data_path, prop_name,
                                         invert=True)
                # else: no IK alternative — FK stays at 1.0, no driver needed

            elif con.type in ('IK', 'SPLINE_IK', 'COPY_ROTATION',
                              'DAMPED_TRACK'):
                # IK constraint: active when property is 1 (IK mode)
                _add_influence_driver(armature_obj, data_path, prop_name,
                                     invert=False)

        # FK_sync on CTRL-FK bones
        ctrl_name = f"{WRAP_CTRL_PREFIX}{chain_id}_FK_{role}"
        ctrl_pb = armature_obj.pose.bones.get(ctrl_name)
        if not ctrl_pb:
            continue

        for con in ctrl_pb.constraints:
            if (con.name == f"{WRAP_CONSTRAINT_PREFIX}FK_sync"
                    and con.type == 'COPY_TRANSFORMS'):
                data_path = (f'pose.bones["{ctrl_name}"]'
                             f'.constraints["{con.name}"].influence')
                # FK_sync: active in IK mode (property = 1)
                _add_influence_driver(armature_obj, data_path, prop_name,
                                     invert=False)


def _remove_ik_switch_drivers(armature_obj):
    """Remove all ik_switch drivers and custom properties.

    Called during disassembly to clean up.
    """
    # Remove drivers on constraint influences that reference ik_switch
    if armature_obj.animation_data:
        drivers_to_remove = []
        for fc in armature_obj.animation_data.drivers:
            for var in fc.driver.variables:
                for target in var.targets:
                    if (target.data_path
                            and target.data_path.startswith(
                                f'["{IK_SWITCH_PROP_PREFIX}')):
                        drivers_to_remove.append(fc.data_path)
                        break
        for dp in drivers_to_remove:
            try:
                armature_obj.driver_remove(dp)
            except TypeError:
                pass

    # Remove custom properties
    keys_to_remove = [k for k in armature_obj.keys()
                      if k.startswith(IK_SWITCH_PROP_PREFIX)]
    for k in keys_to_remove:
        del armature_obj[k]


def _try_assign_group(action, fc, group_name="IK/FK Switches"):
    """Best-effort fcurve grouping. No-op if the API doesn't support it."""
    try:
        if hasattr(action, 'groups') and hasattr(fc, 'group'):
            group = action.groups.get(group_name)
            if not group:
                group = action.groups.new(name=group_name)
            fc.group = group
    except (AttributeError, TypeError, RuntimeError):
        pass  # Blender 5.0+ layered actions may not support legacy groups


def _has_ik_switch(armature_obj, chain_id):
    """Return True if the ik_switch custom property exists for this chain."""
    return _ik_switch_prop_name(chain_id) in armature_obj


def _remove_old_influence_fcurves(action, chain_id, chain_bones):
    """Remove old constraint influence fcurves for a chain after migration.

    Drivers now control these influences, so the old keyframes are dead weight.
    Removes fcurves for both MCH constraints and FK_sync constraints.
    Uses channelbag API for Blender 5.0+, falls back to legacy action.fcurves.
    """
    from ...animation.smart_keyframe import _iter_fcurves

    # Collect data paths to remove
    paths_to_remove = set()
    for bone_item in chain_bones:
        mch_name = f"{WRAP_MCH_PREFIX}{chain_id}_{bone_item.role}"
        ctrl_name = f"{WRAP_CTRL_PREFIX}{chain_id}_FK_{bone_item.role}"
        for prefix in (f'pose.bones["{mch_name}"].constraints["{WRAP_CONSTRAINT_PREFIX}',
                       f'pose.bones["{ctrl_name}"].constraints["{WRAP_CONSTRAINT_PREFIX}'):
            for fc in _iter_fcurves(action):
                if fc.data_path.startswith(prefix) and fc.data_path.endswith('.influence'):
                    paths_to_remove.add(fc.data_path)

    if not paths_to_remove:
        return

    # Blender 5.0+ channelbag API (layered actions)
    for layer in getattr(action, 'layers', ()):
        for strip in getattr(layer, 'strips', ()):
            for channelbag in getattr(strip, 'channelbags', ()):
                fcurves = getattr(channelbag, 'fcurves', None)
                if fcurves and hasattr(fcurves, 'remove'):
                    for fc in list(fcurves):
                        if fc.data_path in paths_to_remove:
                            fcurves.remove(fc)
                    return  # Done via channelbag API

    # Legacy fallback (Blender < 5.0)
    if hasattr(action, 'fcurves') and hasattr(action.fcurves, 'remove'):
        for fc in list(action.fcurves):
            if fc.data_path in paths_to_remove:
                action.fcurves.remove(fc)


def _migrate_action_keyframes(armature_obj, chain_id, chain_bones, action):
    """Migrate old constraint influence keyframes to ik_switch property in one action.

    Finds a representative IK constraint influence fcurve, copies its keyframes
    to the ik_switch property, sets CONSTANT interpolation, then removes the
    old influence fcurves.  Safe to call multiple times — no-ops if the action
    already has an ik_switch fcurve or no old influence fcurves.
    """
    from ...animation.smart_keyframe import _iter_fcurves

    prop_name = _ik_switch_prop_name(chain_id)
    data_path = f'["{prop_name}"]'

    # Skip if this action already has an ik_switch fcurve for this chain
    for fc in _iter_fcurves(action):
        if fc.data_path == data_path:
            # Already migrated — just clean up any leftover old fcurves
            _remove_old_influence_fcurves(action, chain_id, chain_bones)
            return

    # Find a representative IK constraint influence fcurve (all keyed together)
    source_fc = None
    for bone_item in chain_bones:
        mch_name = f"{WRAP_MCH_PREFIX}{chain_id}_{bone_item.role}"
        mch_pb = armature_obj.pose.bones.get(mch_name)
        if not mch_pb:
            continue
        for con in mch_pb.constraints:
            if (con.type in ('IK', 'SPLINE_IK', 'DAMPED_TRACK')
                    and con.name.startswith(WRAP_CONSTRAINT_PREFIX)):
                dp = (f'pose.bones["{mch_name}"]'
                      f'.constraints["{con.name}"].influence')
                for fc in _iter_fcurves(action):
                    if fc.data_path == dp:
                        source_fc = fc
                        break
            if source_fc:
                break
        if source_fc:
            break

    if source_fc:
        # Copy keyframes from constraint influence to the ik_switch property
        for kp in source_fc.keyframe_points:
            armature_obj[prop_name] = kp.co[1]
            armature_obj.keyframe_insert(data_path, frame=kp.co[0])

        # Set CONSTANT interpolation on all copied keyframes
        for fc in _iter_fcurves(action):
            if fc.data_path == data_path:
                for kp in fc.keyframe_points:
                    kp.interpolation = 'CONSTANT'
                _try_assign_group(action, fc)
                break

    # Remove old constraint influence fcurves — drivers replace them
    _remove_old_influence_fcurves(action, chain_id, chain_bones)


def upgrade_ik_switch(armature_obj, chain_id):
    """Migrate an old-style rig (direct constraint keyframing) to the new
    custom-property + driver system.

    1. Creates the ik_switch custom property + drivers (one-time).
    2. Migrates keyframes in the CURRENT action.

    For additional actions, call migrate_action_ik_switch() when they become active.
    Returns True if the property+driver setup was performed (first time).
    """
    prop_name = _ik_switch_prop_name(chain_id)
    first_time = prop_name not in armature_obj

    sd = armature_obj.bt_scan
    chain_bones = [b for b in sd.bones if b.chain_id == chain_id and not b.skip]
    if not chain_bones:
        return False

    if first_time:
        # --- Detect current IK state from constraint influences ---
        current_ik = 0.0
        for bone_item in chain_bones:
            mch_name = f"{WRAP_MCH_PREFIX}{chain_id}_{bone_item.role}"
            mch_pb = armature_obj.pose.bones.get(mch_name)
            if not mch_pb:
                continue
            for con in mch_pb.constraints:
                if (con.type in ('IK', 'SPLINE_IK', 'DAMPED_TRACK')
                        and con.name.startswith(WRAP_CONSTRAINT_PREFIX)):
                    current_ik = con.influence
                    break
            if current_ik > 0.5:
                break

        # --- Create property + drivers ---
        _add_ik_switch_property(armature_obj, chain_id)
        armature_obj[prop_name] = current_ik

        bones_info = {}
        for bone_item in chain_bones:
            bones_info[bone_item.bone_name] = {"role": bone_item.role}
        _setup_ik_switch_drivers(armature_obj, chain_id,
                                  [b.bone_name for b in chain_bones],
                                  bones_info)

    # --- Migrate keyframes in the current action ---
    action = (armature_obj.animation_data
              and armature_obj.animation_data.action)
    if action:
        _migrate_action_keyframes(armature_obj, chain_id, chain_bones, action)

    return first_time


def migrate_action_ik_switch(armature_obj, chain_id):
    """Migrate old influence keyframes in the CURRENT action for one chain.

    Call this when the user switches to a different action that may still
    have old-style constraint influence keyframes.  Safe to call on actions
    that are already migrated (no-ops).
    """
    prop_name = _ik_switch_prop_name(chain_id)
    if prop_name not in armature_obj:
        return  # Property+drivers not set up yet — need full upgrade first

    sd = armature_obj.bt_scan
    chain_bones = [b for b in sd.bones if b.chain_id == chain_id and not b.skip]
    if not chain_bones:
        return

    action = (armature_obj.animation_data
              and armature_obj.animation_data.action)
    if action:
        _migrate_action_keyframes(armature_obj, chain_id, chain_bones, action)


def ensure_fk_sync(armature_obj, chain_id):
    """Ensure FK_sync constraints exist for a chain. Repairs old rigs.

    Safe to call repeatedly — skips bones that already have FK_sync.
    Returns the number of constraints added.
    """
    sd = armature_obj.bt_scan
    chain_bones = [b for b in sd.bones if b.chain_id == chain_id and not b.skip]
    added = 0

    for bone_item in chain_bones:
        mch_name = f"{WRAP_MCH_PREFIX}{chain_id}_{bone_item.role}"
        ctrl_name = f"{WRAP_CTRL_PREFIX}{chain_id}_FK_{bone_item.role}"
        mch_pb = armature_obj.pose.bones.get(mch_name)
        ctrl_pb = armature_obj.pose.bones.get(ctrl_name)
        if not mch_pb or not ctrl_pb:
            continue

        # Only add sync to bones that have an IK alternative
        has_ik = any(
            c.type in ('IK', 'SPLINE_IK', 'COPY_ROTATION', 'DAMPED_TRACK')
            and c.name.startswith(WRAP_CONSTRAINT_PREFIX)
            for c in mch_pb.constraints
        )
        if not has_ik:
            continue

        sync_name = f"{WRAP_CONSTRAINT_PREFIX}FK_sync"
        if any(c.name == sync_name for c in ctrl_pb.constraints):
            continue

        con = ctrl_pb.constraints.new('COPY_TRANSFORMS')
        con.name = sync_name
        con.target = armature_obj
        con.subtarget = mch_name
        con.influence = 0.0
        added += 1

    return added


def apply_ik_limits(armature_obj, chain_id, chain_bones, bones_info, module_type):
    """Apply IK solver limits to MCH bones based on module type.

    Uses bone-local IK limit properties (ik_min_x/max_x etc.) which are
    evaluated INSIDE the IK solver — these work with pole targets, unlike
    LIMIT_ROTATION constraints which are ignored by IK.

    Limits are written but start disabled (use_ik_limit=False) so they
    are ready to be toggled on by the user.
    """
    for bone_name in chain_bones:
        role = bones_info.get(bone_name, {}).get("role", bone_name)
        mch_name = f"{WRAP_MCH_PREFIX}{chain_id}_{role}"
        mch_pb = armature_obj.pose.bones.get(mch_name)
        if not mch_pb:
            continue

        limits = _compute_joint_limits(armature_obj, mch_name, role, module_type)
        for axis, (lo, hi, stiff) in limits.items():
            a = axis.lower()
            setattr(mch_pb, f"ik_min_{a}", lo)
            setattr(mch_pb, f"ik_max_{a}", hi)
            setattr(mch_pb, f"ik_stiffness_{a}", stiff)
            # Start disabled — user toggles on via Joint Limits button
            setattr(mch_pb, f"use_ik_limit_{a}", False)


def apply_fk_limits(armature_obj, chain_id, chain_bones, bones_info, module_type):
    """Add LIMIT_ROTATION constraints to CTRL-FK bones.

    Uses the same limit values as IK (via _compute_joint_limits) so both
    modes enforce identical ranges. Constraints start with influence=0
    (disabled) and are toggled by the Joint Limits button.
    """
    for bone_name in chain_bones:
        role = bones_info.get(bone_name, {}).get("role", bone_name)
        mch_name = f"{WRAP_MCH_PREFIX}{chain_id}_{role}"
        ctrl_name = f"{WRAP_CTRL_PREFIX}{chain_id}_FK_{role}"
        ctrl_pb = armature_obj.pose.bones.get(ctrl_name)
        if not ctrl_pb:
            continue

        limits = _compute_joint_limits(armature_obj, mch_name, role, module_type)

        con = ctrl_pb.constraints.new('LIMIT_ROTATION')
        con.name = f"{WRAP_CONSTRAINT_PREFIX}FK_limit"
        con.owner_space = 'LOCAL'

        for axis, (lo, hi, _stiff) in limits.items():
            a = axis.lower()
            setattr(con, f"use_limit_{a}", True)
            setattr(con, f"min_{a}", lo)
            setattr(con, f"max_{a}", hi)

        # Start disabled — user toggles on via Joint Limits button
        con.influence = 0.0


def toggle_joint_limits(armature_obj, chain_id, enable):
    """Toggle joint rotation limits on/off for a chain at runtime.

    Flips both IK limits (use_ik_limit on MCH bones) and FK limits
    (LIMIT_ROTATION constraint influence on CTRL-FK bones) so both
    modes are kept in sync by one toggle.
    """
    sd = armature_obj.bt_scan
    chain_bones = [b for b in sd.bones if b.chain_id == chain_id and not b.skip]

    for bone_item in chain_bones:
        mch_name = f"{WRAP_MCH_PREFIX}{chain_id}_{bone_item.role}"
        mch_pb = armature_obj.pose.bones.get(mch_name)
        if mch_pb:
            mch_pb.use_ik_limit_x = enable
            mch_pb.use_ik_limit_y = enable
            mch_pb.use_ik_limit_z = enable

        ctrl_name = f"{WRAP_CTRL_PREFIX}{chain_id}_FK_{bone_item.role}"
        ctrl_pb = armature_obj.pose.bones.get(ctrl_name)
        if ctrl_pb:
            for c in ctrl_pb.constraints:
                if (c.type == 'LIMIT_ROTATION'
                        and c.name.startswith(WRAP_CONSTRAINT_PREFIX)):
                    c.influence = 1.0 if enable else 0.0


# Keep old name as alias for backward compatibility
toggle_ik_limits = toggle_joint_limits


def _find_intra_chain_parent(edit_bones, orig_bone, chain_bone_set, orig_to_name):
    """Walk up the original hierarchy to find the nearest parent within the same chain.

    Respects branching hierarchies: if bone A and bone B are both children
    of bone C (all in the same chain), A's MCH parent will be C's MCH — not B's.
    Returns None if no in-chain parent exists (bone is the chain root).
    """
    parent = orig_bone.parent
    while parent:
        if parent.name in chain_bone_set:
            mapped_name = orig_to_name.get(parent.name)
            if mapped_name:
                eb = edit_bones.get(mapped_name)
                if eb:
                    return eb
            return None  # Parent is in chain but not yet mapped — shouldn't happen
        parent = parent.parent
    return None


def _find_cross_chain_parent(edit_bones, orig_bone, orig_to_name):
    """Walk up the original hierarchy to find the nearest mapped bone parent.

    Used for both CTRL and MCH cross-chain parenting.
    """
    parent = orig_bone.parent
    while parent:
        mapped_name = orig_to_name.get(parent.name)
        if mapped_name:
            eb = edit_bones.get(mapped_name)
            if eb:
                return eb
        parent = parent.parent
    return None


def _sort_chains_by_dependency(chains, bones_info, armature_obj):
    """Sort chain IDs so parent chains are processed before children.

    Order: root -> spine -> neck_head -> arm/leg -> finger -> generic.
    Within same priority, sort by hierarchy depth of first bone.
    """
    priority = {
        "root": 0, "spine": 1, "neck_head": 2,
        "arm": 3, "leg": 3, "wing": 3, "jaw": 3, "eye": 3,
        "tail": 4, "tentacle": 4, "finger": 4, "generic": 5, "skip": 6,
    }
    bone_lookup = {b.name: b for b in armature_obj.data.bones}

    def chain_sort_key(chain_id):
        info = chains[chain_id]
        p = priority.get(info["module_type"], 5)
        first_bone = info["bones"][0] if info["bones"] else ""
        depth = 0
        b = bone_lookup.get(first_bone)
        while b and b.parent:
            depth += 1
            b = b.parent
        return (p, depth, chain_id)

    return sorted(chains.keys(), key=chain_sort_key)


def _ensure_collection(armature_obj, name):
    """Ensure a bone collection exists on the armature."""
    colls = armature_obj.data.collections
    if name not in colls:
        colls.new(name)


def _assign_collection_exclusive(armature_obj, edit_bone, collection_name):
    """Assign an edit bone to a collection and remove it from all others."""
    # Unassign from all collections first
    for coll in armature_obj.data.collections:
        coll.unassign(edit_bone)
    # Assign to target collection
    coll = armature_obj.data.collections.get(collection_name)
    if coll:
        coll.assign(edit_bone)
