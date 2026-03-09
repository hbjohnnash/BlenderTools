"""Floor interaction — floor constraint on leg IK targets + auto toe bend."""

import math

import bpy

from ...core.constants import WRAP_CONSTRAINT_PREFIX, WRAP_CTRL_PREFIX, WRAP_MCH_PREFIX

FLOOR_CONSTRAINT = f"{WRAP_CONSTRAINT_PREFIX}Floor"
FLOOR_TOE_CONSTRAINT = f"{WRAP_CONSTRAINT_PREFIX}FloorToe"

# Distance above floor where toe bend starts (Blender units)
_TOE_THRESHOLD = 0.5


def setup_floor_contact(armature_obj, floor_level=0.0,
                         toe_bend=True, toe_bend_max_rad=None):
    """Add floor constraints to leg IK targets and optional toe auto-bend.

    Args:
        armature_obj: Armature with an active wrap rig.
        floor_level: World-space Z value for the floor plane.
        toe_bend: Whether to add auto toe bend on floor contact.
        toe_bend_max_rad: Maximum toe bend angle in radians (default 45 deg).

    Returns:
        Dict with setup stats.
    """
    if toe_bend_max_rad is None:
        toe_bend_max_rad = math.radians(45.0)

    sd = armature_obj.bt_scan
    if not sd.has_wrap_rig:
        return {"error": "No wrap rig found"}

    leg_chains = [ch for ch in sd.chains if ch.module_type == "leg"]
    if not leg_chains:
        return {"error": "No leg chains found"}

    # Remove existing first
    remove_floor_contact(armature_obj)

    stats = {"floor_constraints": 0, "toe_bends": 0}

    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode='POSE')

    try:
        for chain in leg_chains:
            cid = chain.chain_id

            # 1. LIMIT_LOCATION on IK target — prevents foot below floor
            ik_target_name = f"{WRAP_CTRL_PREFIX}{cid}_IK_target"
            ik_pb = armature_obj.pose.bones.get(ik_target_name)
            if not ik_pb:
                continue

            con = ik_pb.constraints.new('LIMIT_LOCATION')
            con.name = f"{FLOOR_CONSTRAINT}_{cid}"
            con.use_min_z = True
            con.min_z = floor_level
            con.use_transform_limit = True
            con.owner_space = 'WORLD'
            stats["floor_constraints"] += 1

            # 2. Auto toe bend via TRANSFORM constraint
            if toe_bend:
                toe_name = _find_toe_bone(armature_obj, sd, chain)
                if toe_name:
                    ok = _add_toe_bend(
                        armature_obj, sd, chain, toe_name,
                        floor_level, toe_bend_max_rad,
                    )
                    if ok:
                        stats["toe_bends"] += 1
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')

    return stats


def remove_floor_contact(armature_obj):
    """Remove all floor constraints and toe bend constraints."""
    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode='POSE')

    try:
        for pbone in armature_obj.pose.bones:
            to_remove = [
                c for c in pbone.constraints
                if c.name.startswith(FLOOR_CONSTRAINT)
                or c.name.startswith(FLOOR_TOE_CONSTRAINT)
            ]
            for c in to_remove:
                pbone.constraints.remove(c)
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')


def update_floor_level(armature_obj, floor_level):
    """Update the floor level on existing floor constraints."""
    for pbone in armature_obj.pose.bones:
        for con in pbone.constraints:
            if con.name.startswith(FLOOR_CONSTRAINT) and con.type == 'LIMIT_LOCATION':
                con.min_z = floor_level
            elif con.name.startswith(FLOOR_TOE_CONSTRAINT) and con.type == 'TRANSFORM':
                con.from_min_z = floor_level
                con.from_max_z = floor_level + _TOE_THRESHOLD


def toggle_toe_bend_for_chain(armature_obj, chain_id, use_ik):
    """Set toe bend constraint influence based on FK/IK mode.

    Called by the FK/IK toggle operator so toe bend is only active in IK mode.
    """
    target_name = f"{FLOOR_TOE_CONSTRAINT}_{chain_id}"
    for pbone in armature_obj.pose.bones:
        for con in pbone.constraints:
            if con.name == target_name:
                con.influence = 1.0 if use_ik else 0.0
                return


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_toe_bone(armature_obj, sd, leg_chain):
    """Find the toe bone for a leg chain.

    Search order:
    1. Bone with role 'toe' in the same chain
    2. Bone with role 'toe' matching the same side
    3. Child of foot bone with 'toe' or 'ball' in name
    """
    cid = leg_chain.chain_id
    side = leg_chain.side

    for b in sd.bones:
        if b.chain_id == cid and b.role == "toe" and not b.skip:
            return b.bone_name

    for b in sd.bones:
        if b.role == "toe" and b.side == side and not b.skip:
            return b.bone_name

    # Heuristic: child of foot bone
    foot_bone = None
    for b in sd.bones:
        if b.chain_id == cid and b.role == "foot" and not b.skip:
            foot_bone = b.bone_name
            break

    if foot_bone:
        pb = armature_obj.pose.bones.get(foot_bone)
        if pb:
            for child in pb.children:
                lower = child.name.lower()
                if "toe" in lower or "ball" in lower:
                    return child.name

    return None


def _add_toe_bend(armature_obj, sd, leg_chain, toe_bone_name,
                   floor_level, max_angle_rad):
    """Add a TRANSFORM constraint to the toe bone for auto-bend near floor.

    Maps the leg IK target's world Z position to local X rotation on the
    toe bone: at floor_level the toe bends up by max_angle_rad; above
    floor_level + threshold, no bend.

    The constraint is placed on the MCH toe bone if it exists (toe is in
    the leg chain), otherwise on the DEF toe bone directly.
    """
    cid = leg_chain.chain_id
    ik_target_name = f"{WRAP_CTRL_PREFIX}{cid}_IK_target"

    # Determine which bone to constrain
    target_bone_name = toe_bone_name  # DEF by default
    for b in sd.bones:
        if b.bone_name == toe_bone_name:
            mch_name = f"{WRAP_MCH_PREFIX}{b.chain_id}_{b.role}"
            if armature_obj.pose.bones.get(mch_name):
                target_bone_name = mch_name
            break

    target_pb = armature_obj.pose.bones.get(target_bone_name)
    ik_pb = armature_obj.pose.bones.get(ik_target_name)
    if not target_pb or not ik_pb:
        return False

    con = target_pb.constraints.new('TRANSFORM')
    con.name = f"{FLOOR_TOE_CONSTRAINT}_{cid}"
    con.target = armature_obj
    con.subtarget = ik_target_name
    con.target_space = 'WORLD'
    con.owner_space = 'LOCAL'

    # Input: IK target Z location
    con.map_from = 'LOCATION'
    con.from_min_z = floor_level
    con.from_max_z = floor_level + _TOE_THRESHOLD

    # Output: toe local X rotation (negative = bend upward for standard rigs)
    con.map_to = 'ROTATION'
    con.map_to_x_from = 'Z'
    con.to_min_x_rot = -max_angle_rad  # At floor → bend up
    con.to_max_x_rot = 0.0             # Above threshold → no bend
    con.use_motion_extrapolate = False  # Clamp outside range

    # Only active in IK mode
    con.influence = 1.0 if leg_chain.ik_active else 0.0

    return True
