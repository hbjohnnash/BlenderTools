"""Floor interaction — LIMIT_LOCATION on leg IK targets to prevent feet below floor."""

import bpy

from ...core.constants import WRAP_CONSTRAINT_PREFIX, WRAP_CTRL_PREFIX

FLOOR_CONSTRAINT = f"{WRAP_CONSTRAINT_PREFIX}Floor"


def setup_floor_contact(armature_obj, floor_level=0.0):
    """Add floor constraints to leg IK targets.

    Adds a LIMIT_LOCATION constraint (min Z = floor_level) on each leg
    chain's IK target so the foot cannot be moved below the floor plane.

    Args:
        armature_obj: Armature with an active wrap rig.
        floor_level: World-space Z value for the floor plane.

    Returns:
        Dict with setup stats.
    """
    sd = armature_obj.bt_scan
    if not sd.has_wrap_rig:
        return {"error": "No wrap rig found"}

    leg_chains = [ch for ch in sd.chains if ch.module_type == "leg"]
    if not leg_chains:
        return {"error": "No leg chains found"}

    # Remove existing first
    remove_floor_contact(armature_obj)

    stats = {"floor_constraints": 0}

    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode='POSE')

    try:
        for chain in leg_chains:
            cid = chain.chain_id

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
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')

    return stats


def remove_floor_contact(armature_obj):
    """Remove all floor constraints."""
    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode='POSE')

    try:
        for pbone in armature_obj.pose.bones:
            to_remove = [
                c for c in pbone.constraints
                if c.name.startswith(FLOOR_CONSTRAINT)
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
