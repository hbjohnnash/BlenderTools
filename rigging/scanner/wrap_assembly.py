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
    WRAP_CTRL_PREFIX, WRAP_MCH_PREFIX, WRAP_CONSTRAINT_PREFIX, WRAP_SPLINE_PREFIX,
)


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
                or "_Spline_" in bn
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
            elif use_spline and chain_id in spline_curves:
                _constrain_spline_ik_chain(
                    armature_obj, chain_id, chain_bones, bones_info,
                    spline_curves[chain_id])
            elif ik_enabled and module_type not in ("arm", "leg"):
                ik_snap = chain_info.get("ik_snap", False)
                _constrain_ik_chain(armature_obj, chain_id, chain_bones, bones_info, ik_snap)
            else:
                _constrain_fk_chain(armature_obj, chain_id, chain_bones, bones_info)

            # Apply IK limits if requested
            if chain_info.get("ik_limits") and ik_enabled:
                apply_ik_limits(armature_obj, chain_id, chain_bones, bones_info, module_type)

        # Calibrate all IK pole angles using the depsgraph
        _calibrate_pole_angles(armature_obj)
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
            pbone.bone.select = True

    # Bake visual keying: evaluates constraints and writes keyframes
    bpy.ops.nla.bake(
        frame_start=frame_start,
        frame_end=frame_end,
        only_selected=True,
        visual_keying=True,
        clear_constraints=False,
        bake_types={'POSE'},
    )

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

            # IK target at hand
            ik_name = f"{WRAP_CTRL_PREFIX}{chain_id}_IK_target"
            ik_bone = edit_bones.new(ik_name)
            ik_bone.head = orig_hand.head.copy()
            ik_bone.tail = orig_hand.head + Vector((0, -bone_len, 0))
            ik_bone.roll = 0
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
            con.influence = 0.0  # Start with FK, user toggles IK

            if armature_obj.pose.bones.get(ik_pole):
                con.pole_target = armature_obj
                con.pole_subtarget = ik_pole


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

            # IK target at foot
            ik_name = f"{WRAP_CTRL_PREFIX}{chain_id}_IK_target"
            ik_bone = edit_bones.new(ik_name)
            ik_bone.head = orig_foot.head.copy()
            ik_bone.tail = orig_foot.head + Vector((0, -bone_len, 0))
            ik_bone.roll = 0
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
            con.influence = 0.0  # Start with FK

            if armature_obj.pose.bones.get(ik_pole):
                con.pole_target = armature_obj
                con.pole_subtarget = ik_pole


# --- Helpers ---

def _calibrate_pole_angles(armature_obj):
    """Calibrate all IK pole angles using the depsgraph.

    For each IK constraint with a pole target:
    1. Temporarily enable IK (disable FK) with pole_angle = 0
    2. Let the IK solver run via depsgraph update
    3. Measure how much the bend direction twisted from rest pose
    4. Set pole_angle to the signed correction that eliminates the twist

    This is robust for any bone roll, mirrored bones, or unusual orientations
    because it directly measures what the IK solver produces.
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

        # Collect FK constraints on all MCH bones in the chain for save/restore
        chain_pbones = []
        pb = pbone
        for _ in range(chain_count):
            chain_pbones.append(pb)
            if pb.parent:
                pb = pb.parent

        saved_fk = []
        for cpb in chain_pbones:
            for c in cpb.constraints:
                if c.type == 'COPY_TRANSFORMS' and c.name.startswith(WRAP_CONSTRAINT_PREFIX):
                    saved_fk.append((c, c.influence))

        # Rest-pose bend direction (in armature space)
        chain_axis = (pbone.bone.tail_local - upper_pb.bone.head_local).normalized()
        mid_rest = pbone.bone.head_local
        proj = upper_pb.bone.head_local + chain_axis * (mid_rest - upper_pb.bone.head_local).dot(chain_axis)
        rest_bend = mid_rest - proj
        if rest_bend.length < 0.0001:
            continue
        rest_bend.normalize()

        # Temporarily enable IK with pole_angle=0, disable FK
        saved_ik_inf = ik_con.influence
        saved_pole = ik_con.pole_angle
        for c, _ in saved_fk:
            c.influence = 0.0
        ik_con.pole_angle = 0.0
        ik_con.influence = 1.0

        bpy.context.view_layer.update()

        # Measure IK-solved bend direction
        upper_head_pose = upper_pb.head.copy()
        lower_head_pose = pbone.head.copy()
        lower_tail_pose = pbone.tail.copy()
        chain_pose = (lower_tail_pose - upper_head_pose).normalized()
        proj_pose = upper_head_pose + chain_pose * (lower_head_pose - upper_head_pose).dot(chain_pose)
        pose_bend = lower_head_pose - proj_pose
        if pose_bend.length < 0.0001:
            # Restore and skip
            ik_con.pole_angle = saved_pole
            ik_con.influence = saved_ik_inf
            for c, inf in saved_fk:
                c.influence = inf
            continue
        pose_bend.normalize()

        # Signed angle from pose_bend to rest_bend around chain_axis
        dot = max(-1.0, min(1.0, pose_bend.dot(rest_bend)))
        correction = math.acos(dot)
        cross = pose_bend.cross(rest_bend)
        if cross.dot(chain_axis) < 0:
            correction = -correction

        # Apply correction and restore FK mode
        ik_con.pole_angle = correction
        ik_con.influence = saved_ik_inf
        for c, inf in saved_fk:
            c.influence = inf

    bpy.context.view_layer.update()


def snap_fk_to_ik(armature_obj, chain_id):
    """Snap FK controls to match the current IK-solved pose.

    Call before switching from IK to FK so the pose is preserved.
    Reads the MCH bone matrices (driven by IK solver) and applies
    them to the CTRL-FK bones.
    """
    sd = armature_obj.bt_scan
    chain_bones = [b for b in sd.bones if b.chain_id == chain_id and not b.skip]

    for bone_item in chain_bones:
        mch_name = f"{WRAP_MCH_PREFIX}{chain_id}_{bone_item.role}"
        ctrl_name = f"{WRAP_CTRL_PREFIX}{chain_id}_FK_{bone_item.role}"
        mch_pb = armature_obj.pose.bones.get(mch_name)
        ctrl_pb = armature_obj.pose.bones.get(ctrl_name)
        if mch_pb and ctrl_pb:
            ctrl_pb.matrix = mch_pb.matrix.copy()
            # Update after each bone so children compute correctly
            bpy.context.view_layer.update()


def snap_ik_to_fk(armature_obj, chain_id):
    """Snap IK target and pole to match the current FK pose.

    Call before switching from FK to IK so the pose is preserved.
    1. Records the current FK bend direction from MCH bones
    2. Positions IK target at the chain end, resets pole to rest
    3. Temporarily enables IK, measures the solver's bend direction
    4. Adjusts pole_angle so the IK solution matches the FK pose
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

    # Walk up to find the upper bone of the IK chain
    upper_pb = ik_mch
    for _ in range(ik_chain_count - 1):
        if upper_pb.parent:
            upper_pb = upper_pb.parent

    # Find the actual mid-bone for bend measurement
    mid_steps = ik_chain_count // 2
    mid_pb = ik_mch
    for _ in range(mid_steps):
        if mid_pb.parent:
            mid_pb = mid_pb.parent

    # Snap IK target to the chain end (tail of the IK bone = foot/hand)
    ik_target_name = f"{WRAP_CTRL_PREFIX}{chain_id}_IK_target"
    ik_target_pb = armature_obj.pose.bones.get(ik_target_name)
    if ik_target_pb:
        fk_tip = ik_mch.tail.copy()
        mat = Matrix.Translation(fk_tip)
        ik_target_pb.matrix = mat
        bpy.context.view_layer.update()

    # For 2-bone IK chains (arms/legs), recalibrate pole_angle so
    # the IK solution exactly reproduces the current FK pose.
    # For 3+ bone chains this isn't possible (IK solver distributes
    # rotations differently), so we just reset the pole to rest.
    ik_pole_name = f"{WRAP_CTRL_PREFIX}{chain_id}_IK_pole"
    ik_pole_pb = armature_obj.pose.bones.get(ik_pole_name)
    if ik_pole_pb:
        ik_pole_pb.location = Vector((0, 0, 0))
        ik_pole_pb.rotation_quaternion = (1, 0, 0, 0)
        ik_pole_pb.rotation_euler = (0, 0, 0)
        ik_pole_pb.scale = (1, 1, 1)

    if ik_chain_count == 2 and ik_pole_pb and ik_con.pole_target:
        # Record FK bend direction
        fk_root = upper_pb.head.copy()
        fk_mid = ik_mch.head.copy()
        fk_tip = ik_mch.tail.copy()
        fk_axis = (fk_tip - fk_root)
        if fk_axis.length > 0.0001:
            fk_axis_n = fk_axis.normalized()
            fk_proj = fk_root + fk_axis_n * (fk_mid - fk_root).dot(fk_axis_n)
            fk_bend = fk_mid - fk_proj
            if fk_bend.length > 0.0001:
                fk_bend.normalize()

                # Temporarily enable IK to measure solver result
                saved_fk = []
                walk_pb = ik_mch
                for _ in range(ik_chain_count):
                    for c in walk_pb.constraints:
                        if c.type == 'COPY_TRANSFORMS' and c.name.startswith(WRAP_CONSTRAINT_PREFIX):
                            saved_fk.append((c, c.influence))
                            c.influence = 0.0
                    if walk_pb.parent:
                        walk_pb = walk_pb.parent

                saved_ik_inf = ik_con.influence
                saved_pole = ik_con.pole_angle
                ik_con.influence = 1.0
                bpy.context.view_layer.update()

                ik_root = upper_pb.head.copy()
                ik_mid = ik_mch.head.copy()
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

                # Restore
                ik_con.influence = saved_ik_inf
                for c, inf in saved_fk:
                    c.influence = inf
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
    con.influence = 0.0  # Start with FK, user toggles IK

    if armature_obj.pose.bones.get(ik_pole) and chain_count >= 2:
        con.pole_target = armature_obj
        con.pole_subtarget = ik_pole
        # pole_angle is set later by _calibrate_pole_angles()


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


def apply_ik_limits(armature_obj, chain_id, chain_bones, bones_info, module_type):
    """Apply IK solver limits to MCH bones based on module type.

    Uses bone-local IK limit properties (ik_min_x/max_x etc.) which are
    evaluated INSIDE the IK solver — these work with pole targets, unlike
    LIMIT_ROTATION constraints which are ignored by IK.
    """
    for i, bone_name in enumerate(chain_bones):
        role = bones_info.get(bone_name, {}).get("role", bone_name)
        mch_name = f"{WRAP_MCH_PREFIX}{chain_id}_{role}"
        mch_pb = armature_obj.pose.bones.get(mch_name)
        if not mch_pb:
            continue

        if module_type in ("arm", "leg"):
            _apply_limb_limits(armature_obj, mch_pb, role, module_type)
        elif module_type in ("tail", "tentacle"):
            _apply_chain_limits(mch_pb, module_type)
        else:
            _apply_chain_limits(mch_pb, "generic")


def _apply_limb_limits(armature_obj, mch_pb, role, module_type):
    """Apply anatomical IK limits for arm/leg joints."""
    bend_axis, bend_sign = _detect_bend_axis(armature_obj, mch_pb.name)

    is_mid_joint = role in ("lower_arm", "lower_leg")

    if is_mid_joint:
        # Mid-joint (elbow/knee): single-axis bend, no hyperextension
        for axis in ('X', 'Y', 'Z'):
            use_attr = f"use_ik_limit_{axis.lower()}"
            min_attr = f"ik_min_{axis.lower()}"
            max_attr = f"ik_max_{axis.lower()}"
            stiff_attr = f"ik_stiffness_{axis.lower()}"

            if axis == bend_axis:
                setattr(mch_pb, use_attr, True)
                if bend_sign > 0:
                    setattr(mch_pb, min_attr, 0.0)
                    setattr(mch_pb, max_attr, math.radians(160))
                else:
                    setattr(mch_pb, min_attr, math.radians(-160))
                    setattr(mch_pb, max_attr, 0.0)
                setattr(mch_pb, stiff_attr, 0.0)
            else:
                # Lock secondary axes
                setattr(mch_pb, use_attr, True)
                setattr(mch_pb, min_attr, math.radians(-5))
                setattr(mch_pb, max_attr, math.radians(5))
                setattr(mch_pb, stiff_attr, 0.9)
    else:
        # Root/end joints (shoulder/hip, wrist/ankle): moderate limits
        for axis in ('X', 'Y', 'Z'):
            use_attr = f"use_ik_limit_{axis.lower()}"
            min_attr = f"ik_min_{axis.lower()}"
            max_attr = f"ik_max_{axis.lower()}"
            stiff_attr = f"ik_stiffness_{axis.lower()}"
            setattr(mch_pb, use_attr, True)
            setattr(mch_pb, min_attr, math.radians(-120))
            setattr(mch_pb, max_attr, math.radians(120))
            setattr(mch_pb, stiff_attr, 0.0)


def _apply_chain_limits(mch_pb, module_type):
    """Apply IK limits for chain-type modules (tail, tentacle, generic)."""
    if module_type == "tail":
        limit = math.radians(45)
        stiffness = 0.1
    elif module_type == "tentacle":
        limit = math.radians(60)
        stiffness = 0.05
    else:
        limit = math.radians(90)
        stiffness = 0.0

    for axis in ('x', 'y', 'z'):
        setattr(mch_pb, f"use_ik_limit_{axis}", True)
        setattr(mch_pb, f"ik_min_{axis}", -limit)
        setattr(mch_pb, f"ik_max_{axis}", limit)
        setattr(mch_pb, f"ik_stiffness_{axis}", stiffness)


def toggle_ik_limits(armature_obj, chain_id, enable):
    """Toggle IK rotation limits on/off for a chain at runtime.

    Simply flips the use_ik_limit_x/y/z flags on all MCH bones in the chain.
    The actual limit values are preserved so re-enabling restores them.
    """
    sd = armature_obj.bt_scan
    chain_bones = [b for b in sd.bones if b.chain_id == chain_id and not b.skip]

    for bone_item in chain_bones:
        mch_name = f"{WRAP_MCH_PREFIX}{chain_id}_{bone_item.role}"
        mch_pb = armature_obj.pose.bones.get(mch_name)
        if not mch_pb:
            continue
        mch_pb.use_ik_limit_x = enable
        mch_pb.use_ik_limit_y = enable
        mch_pb.use_ik_limit_z = enable


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
