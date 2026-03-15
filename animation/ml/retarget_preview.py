"""SMPL reference skeleton for retarget validation.

Creates a visual SMPL skeleton next to the user's armature for
side-by-side comparison.  The rest pose shows the 22-joint SMPL
skeleton structure alongside the user's rig.  When motion is generated, FK positions
are computed from the raw rotation data and animated on the
wireframe mesh — bypassing all rotation correction math — to show
the "ground truth" motion the retarget should match.

Usage:
    1. Click "Show SMPL Reference" in the AI Motion panel.
    2. Verify both skeletons face the same way in T-pose.
    3. Generate motion — SMPL reference animates alongside.
    4. Scrub timeline to compare: if SMPL looks right but user
       skeleton doesn't, the issue is in rotation correction.
"""

import bpy
import numpy as np

from . import smpl_skeleton
from .retarget_map import (
    _euler_to_matrix,
    _fractional_rotation,
    _matrix_to_euler_xyz,
    build_default_influence_map,
)

_PREVIEW_NAME = "SMPL_Reference"
_WIREFRAME_NAME = "SMPL_Wireframe"

# Module-level storage for FK animation data (used by frame handler)
_anim_data = {
    "fk_positions": None,   # (n_frames, n_joints, 3)
    "frame_start": 1,
}

# Cache last SMPL motion so the preview can replay it when toggled on
# after generation.  Keys: motion_data, frame_start.
_last_motion_cache = {
    "motion_data": None,
    "frame_start": 1,
}

# Live retarget link data (SMPL pose → user armature in real-time)
_link_data = {
    "active": False,
    "smpl_arm_name": None,
    "user_arm_name": None,
    "influence_map": None,
    "smpl_rest": {},     # {joint_idx: 3x3 ndarray}
    "user_rest": {},     # {bone_name: 3x3 ndarray}
    "_updating": False,
}


# ── Public API ─────────────────────────────────────────────────


def get_smpl_preview():
    """Return the existing SMPL preview armature, or ``None``."""
    return bpy.data.objects.get(_PREVIEW_NAME)


def get_cached_motion():
    """Return cached SMPL motion data from the last generation, or ``None``."""
    return _last_motion_cache.get("motion_data")


def get_cached_frame_start():
    """Return the frame_start from the last cached motion."""
    return _last_motion_cache.get("frame_start", 1)


def is_link_active():
    """Return True if the live retarget link is active."""
    return _link_data.get("active", False)


def link_preview_to_user(user_armature):
    """Link SMPL preview to user armature for live retarget debugging.

    When linked, manually posing SMPL bones in Pose Mode will
    drive the corresponding user armature bones in real-time,
    using the same conjugation math as the retarget pipeline.

    Args:
        user_armature: Blender armature with scan data + wrap rig.

    Returns:
        True if linked, False if prerequisites missing.
    """
    unlink_preview_from_user()

    smpl_arm = get_smpl_preview()
    if smpl_arm is None:
        return False

    scan_data = getattr(user_armature, 'bt_scan', None)
    if scan_data is None or not scan_data.is_scanned:
        return False
    imap = build_default_influence_map(scan_data, user_armature)
    if imap is None or imap.is_empty():
        return False

    # Pre-compute SMPL bone rest orientations (parent-relative)
    smpl_rest = {}
    for j in range(smpl_skeleton.NUM_JOINTS):
        bone = smpl_arm.data.bones.get(smpl_skeleton.JOINT_NAMES[j])
        if not bone:
            continue
        M_j = np.array([
            [bone.matrix_local[r][c] for c in range(3)]
            for r in range(3)
        ])
        p_idx = int(smpl_skeleton.PARENTS[j])
        if p_idx >= 0:
            pbone_data = smpl_arm.data.bones.get(
                smpl_skeleton.JOINT_NAMES[p_idx])
            if pbone_data:
                M_p = np.array([
                    [pbone_data.matrix_local[r][c] for c in range(3)]
                    for r in range(3)
                ])
                smpl_rest[j] = M_p.T @ M_j
            else:
                smpl_rest[j] = M_j
        else:
            smpl_rest[j] = M_j

    # Pre-compute user bone rest orientations (armature space).
    # User armatures have wrap rig hierarchies (CTRL/MCH bones) that
    # don't match SMPL's joint hierarchy, so armature-space conjugation
    # is correct here (same as retarget_map._get_rest_local_rotation).
    user_rest = {}
    for sj in imap.mapped_smpl_joints():
        for bone_name, _ in imap.get_targets(sj):
            if bone_name not in user_rest:
                bone = user_armature.data.bones.get(bone_name)
                if bone:
                    user_rest[bone_name] = np.array([
                        [bone.matrix_local[r][c] for c in range(3)]
                        for r in range(3)
                    ])

    # Object-rotation correction: SMPL preview may have a 180° Z
    # rotation at object level while the user armature may not.
    # bone.matrix_local is in armature space, so we need to map
    # from SMPL armature space → world → user armature space.
    # C = R_obj_user^T @ R_obj_smpl  (maps SMPL arm-space to user arm-space)
    R_obj_s = np.array([
        [smpl_arm.matrix_world[r][c] for c in range(3)]
        for r in range(3)
    ])
    R_obj_u = np.array([
        [user_armature.matrix_world[r][c] for c in range(3)]
        for r in range(3)
    ])
    obj_correction = R_obj_u.T @ R_obj_s

    # Detect if the object rotation flips left/right (X axis negated).
    # This happens with the 180° Z rotation on the SMPL preview.
    # When flipped, visual left on SMPL = R_* bones, so we need to
    # swap L/R joint indices so visual sides match.
    lr_swap = {}
    if obj_correction[0, 0] < 0:
        names = smpl_skeleton.JOINT_NAMES
        for i, name in enumerate(names):
            if name.startswith("L_"):
                partner = "R_" + name[2:]
                if partner in names:
                    j = names.index(partner)
                    lr_swap[i] = j
                    lr_swap[j] = i

    # Store by name (survives undo/redo)
    _link_data.update({
        "active": True,
        "smpl_arm_name": smpl_arm.name,
        "user_arm_name": user_armature.name,
        "influence_map": imap,
        "smpl_rest": smpl_rest,
        "user_rest": user_rest,
        "obj_correction": obj_correction,
        "lr_swap": lr_swap,
        "_updating": False,
    })

    # Set rotation mode on SMPL pose bones so interactive rotation
    # writes to rotation_euler (default is QUATERNION which we can't read)
    for j in range(smpl_skeleton.NUM_JOINTS):
        pbone = smpl_arm.pose.bones.get(smpl_skeleton.JOINT_NAMES[j])
        if pbone:
            pbone.rotation_mode = 'XYZ'

    # Set rotation mode on user pose bones
    for sj in imap.mapped_smpl_joints():
        for bone_name, _ in imap.get_targets(sj):
            pbone = user_armature.pose.bones.get(bone_name)
            if pbone:
                pbone.rotation_mode = 'XYZ'

    _register_link_handler()

    return True


def unlink_preview_from_user():
    """Remove the live retarget link and reset user pose."""
    if not _link_data.get("active"):
        return

    _unregister_link_handler()

    # Reset user bone poses
    user_arm = bpy.data.objects.get(_link_data.get("user_arm_name", ""))
    if user_arm and user_arm.pose:
        imap = _link_data.get("influence_map")
        if imap:
            for sj in imap.mapped_smpl_joints():
                for bone_name, _ in imap.get_targets(sj):
                    pbone = user_arm.pose.bones.get(bone_name)
                    if pbone:
                        pbone.rotation_euler = (0, 0, 0)
                        pbone.location = (0, 0, 0)

    _link_data.update({
        "active": False,
        "smpl_arm_name": None,
        "user_arm_name": None,
        "influence_map": None,
        "smpl_rest": {},
        "user_rest": {},
        "_updating": False,
    })


def create_smpl_preview(user_armature):
    """Create SMPL reference armature scaled to user skeleton.

    Builds bones with proper parent hierarchy at rest-pose
    positions, grounded at the feet.  Bones are connected in
    chains for clear visualization.  The armature faces the
    same direction as the user armature (SMPL faces +Y by
    default, so it is rotated 180° around Z to face -Y).

    Args:
        user_armature: Blender armature to scale-match.

    Returns:
        The created armature object.
    """
    remove_smpl_preview()

    user_height = _get_armature_height(user_armature)
    smpl_height = smpl_skeleton.SKELETON_HEIGHT
    scale = user_height / smpl_height if smpl_height > 1e-6 else 1.0

    positions = _compute_tpose_positions(scale)

    # Ground: offset so feet (minimum Z) sit at Z=0
    min_z = float(positions[:, 2].min())
    positions[:, 2] -= min_z

    # NOTE: we do NOT flip positions here.  The 180° Z rotation to
    # face the preview toward -Y is applied at the object level
    # (rotation_euler below) so that bone.matrix_local reflects
    # the true SMPL bone orientations and conjugation is correct.

    # Pre-compute children for each joint
    children_map = {i: [] for i in range(smpl_skeleton.NUM_JOINTS)}
    for j in range(smpl_skeleton.NUM_JOINTS):
        p = int(smpl_skeleton.PARENTS[j])
        if p >= 0:
            children_map[p].append(j)

    # Build "primary child" lookup for branching joints.
    # The primary child continues the chain (e.g. Pelvis→Spine1,
    # Spine3→Neck).  Pick the child whose offset goes most upward
    # (+Z in Blender); for joints where all children go down or
    # sideways, pick the one with the smallest horizontal offset
    # (closest to center/vertical continuation).
    primary_child = {}
    for i, kids in children_map.items():
        if len(kids) > 1:
            best = max(
                kids,
                key=lambda c: (positions[c][2] - positions[i][2]),
            )
            primary_child[i] = best

    # ── Create armature ──
    arm_data = bpy.data.armatures.new(_PREVIEW_NAME)
    arm_obj = bpy.data.objects.new(_PREVIEW_NAME, arm_data)
    bpy.context.collection.objects.link(arm_obj)

    # Place next to user armature.  Object rotation 180° Z faces preview
    # toward -Y (matching user armature) while keeping bone.matrix_local
    # in the correct SMPL frame for conjugation.
    import math
    arm_obj.location.x = user_armature.location.x + user_height * 1.5
    arm_obj.rotation_euler = (0, 0, math.pi)

    # ── Context switch ──
    prev_active = bpy.context.view_layer.objects.active
    prev_mode = bpy.context.mode
    if prev_mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for o in bpy.context.selected_objects:
        o.select_set(False)
    arm_obj.select_set(True)
    bpy.context.view_layer.objects.active = arm_obj

    # ── Build bones (edit mode) ──
    bpy.ops.object.mode_set(mode='EDIT')

    bone_refs = []  # indexed by joint index

    for i in range(smpl_skeleton.NUM_JOINTS):
        name = smpl_skeleton.JOINT_NAMES[i]
        eb = arm_data.edit_bones.new(name)
        p_idx = int(smpl_skeleton.PARENTS[i])
        kids = children_map[i]

        # Determine bone head: non-primary branch children start
        # from parent position to show the visual connection
        # (e.g. collar goes FROM spine center TO shoulder area).
        is_branch = (
            p_idx >= 0
            and len(children_map[p_idx]) > 1
            and primary_child.get(p_idx) != i
        )
        if is_branch:
            head = positions[p_idx].copy()
        else:
            head = positions[i]

        # Determine bone tail
        if len(kids) == 1:
            tail = positions[kids[0]]
        elif len(kids) > 1:
            pc = primary_child.get(i, kids[0])
            tail = positions[pc]
        else:
            # Leaf bone: extend from head toward own position
            # (or from parent direction for non-branches)
            own_pos = positions[i]
            direction = own_pos - head if is_branch else (
                head - positions[p_idx] if p_idx >= 0
                else np.array([0.0, 0.0, 1.0])
            )
            d_len = float(np.linalg.norm(direction))
            if d_len > 1e-6:
                tail = own_pos + (direction / d_len) * d_len * 0.4
            else:
                tail = head + np.array([0.0, 0.0, 0.05 * scale])

        eb.head = tuple(head)
        eb.tail = tuple(tail)

        # Set parent and connect
        if p_idx >= 0:
            eb.parent = bone_refs[p_idx]
            # Connect if this bone's head matches parent's tail
            # (primary children and single children)
            parent_kids = children_map[p_idx]
            if (len(parent_kids) == 1
                    or primary_child.get(p_idx) == i):
                eb.use_connect = True

        bone_refs.append(eb)

    # ── Align bone rolls to SMPL world axes ──
    # SMPL uses world-aligned frames at rest (identity rotation for
    # all joints).  Blender bones have local axes determined by
    # head→tail direction + roll.  We set the roll so that each bone's
    # local Z axis is as close as possible to world Z (up), which makes
    # bone local X ≈ world X (lateral) — the natural swing axis.
    # For vertical bones (nearly parallel to Z) we use world Y instead.
    import mathutils
    for eb in arm_data.edit_bones:
        bone_dir = (eb.tail - eb.head).normalized()
        # Choose the reference "up" vector: use world Z unless
        # the bone is nearly vertical, then use world Y.
        if abs(bone_dir.z) > 0.9:
            ref_up = mathutils.Vector((0, 1, 0))
        else:
            ref_up = mathutils.Vector((0, 0, 1))
        # Desired bone local X = perpendicular to bone direction
        # in the plane defined by bone_dir and ref_up
        desired_x = bone_dir.cross(ref_up).normalized()
        if desired_x.length < 1e-6:
            desired_x = mathutils.Vector((1, 0, 0))
        # Desired bone local Z = perpendicular to both
        desired_z = desired_x.cross(bone_dir).normalized()
        # Blender's roll=0 places Z in a default direction.
        # We calculate the roll that aligns bone Z with desired_z.
        # eb.z_axis gives the current Z axis in armature space.
        # The roll angle is measured between the current Z and desired Z
        # around the bone Y axis.
        current_z = eb.z_axis.normalized()
        # Project both onto the plane perpendicular to bone_dir
        proj_current = (current_z - current_z.dot(bone_dir) * bone_dir).normalized()
        proj_desired = (desired_z - desired_z.dot(bone_dir) * bone_dir).normalized()
        if proj_current.length > 1e-6 and proj_desired.length > 1e-6:
            cos_angle = max(-1.0, min(1.0, proj_current.dot(proj_desired)))
            angle = math.acos(cos_angle)
            # Determine sign via cross product
            cross = proj_current.cross(proj_desired)
            if cross.dot(bone_dir) < 0:
                angle = -angle
            eb.roll += angle

    bpy.ops.object.mode_set(mode='OBJECT')

    # Visual settings
    arm_data.display_type = 'STICK'
    arm_obj.show_in_front = True

    # ── Build wireframe mesh for animation ──
    _create_wireframe(arm_obj, positions)

    # ── Restore context ──
    arm_obj.select_set(False)
    if prev_active and prev_active.name in bpy.data.objects:
        bpy.context.view_layer.objects.active = prev_active
        prev_active.select_set(True)
    if prev_mode == 'POSE':
        bpy.ops.object.mode_set(mode='POSE')

    return arm_obj


def apply_preview_motion(motion_data, user_armature=None, frame_start=1):
    """Create a Blender action on the SMPL preview armature.

    Keyframes bone rotations and root position using the standard
    Blender action/FCurve system.  This is robust across addon
    reloads unlike the old frame_change handler approach.

    Rest-pose correction uses conjugation so the SMPL skeleton
    stays in its rest pose when the SMPL motion is identity:
    ``R_pose = R_rest^T @ R_smpl @ R_rest``.

    Args:
        motion_data: dict with ``rotations`` and ``root_positions``
            (Z-up Euler format from ``_recover_motion``).
        user_armature: for height scaling (optional).
        frame_start: first keyframe number.

    Returns:
        True if preview was animated, False if no preview exists.
    """
    from bpy_extras.anim_utils import action_ensure_channelbag_for_slot

    from .retarget_map import _matrix_to_euler_xyz

    # Cache for later replay (toggle preview on after generation)
    _last_motion_cache["motion_data"] = motion_data
    _last_motion_cache["frame_start"] = frame_start

    smpl_arm = get_smpl_preview()
    if smpl_arm is None:
        return False

    rotations = motion_data['rotations']
    root_positions = motion_data['root_positions']
    n_frames = len(rotations)
    n_joints = min(len(rotations[0]), smpl_skeleton.NUM_JOINTS)

    # Scale factor to match user armature height
    if user_armature:
        user_height = _get_armature_height(user_armature)
        smpl_height = smpl_skeleton.SKELETON_HEIGHT
        scale = user_height / smpl_height if smpl_height > 1e-6 else 1.0
    else:
        scale = 1.0

    # Ground offset at user scale (same as create_smpl_preview)
    tpose = _compute_tpose_positions(scale)
    ground_offset = float(tpose[:, 2].min())
    rest_root_pos = tpose[0].copy()
    rest_root_pos[2] -= ground_offset  # grounded rest root

    # ── Rest orientations relative to parent ──
    # SMPL local rotations are in the parent joint's frame (which at
    # rest = world/armature frame for all joints).  Blender bones have
    # non-trivial rest orientations (from head→tail direction + roll),
    # so we must conjugate by the bone's orientation RELATIVE TO ITS
    # PARENT — not the armature-space orientation.
    #
    # M_j_rel = M_parent^T @ M_j   (parent-relative rest orientation)
    # R_delta = M_j_rel^T @ R_smpl @ M_j_rel
    #
    # For the root bone (no parent), M_j_rel = M_j.
    rest_rots_rel = {}
    for j in range(n_joints):
        bone = smpl_arm.data.bones.get(smpl_skeleton.JOINT_NAMES[j])
        if bone is None:
            rest_rots_rel[j] = np.eye(3)
            continue
        M_j = np.array([
            [bone.matrix_local[r][c] for c in range(3)]
            for r in range(3)
        ])
        p_idx = int(smpl_skeleton.PARENTS[j])
        if p_idx >= 0:
            parent_bone = smpl_arm.data.bones.get(
                smpl_skeleton.JOINT_NAMES[p_idx])
            if parent_bone:
                M_p = np.array([
                    [parent_bone.matrix_local[r][c] for c in range(3)]
                    for r in range(3)
                ])
                rest_rots_rel[j] = M_p.T @ M_j
            else:
                rest_rots_rel[j] = M_j
        else:
            rest_rots_rel[j] = M_j

    # ── Pose rotations per frame (conjugation with parent-relative rest) ──
    bone_eulers = {}
    for j in range(n_joints):
        M_rel = rest_rots_rel[j]
        frames = []
        for f in range(n_frames):
            if j < len(rotations[f]):
                rx, ry, rz = rotations[f][j]
            else:
                rx = ry = rz = 0.0
            R_smpl = _euler_to_matrix(rx, ry, rz)
            R_pose = M_rel.T @ R_smpl @ M_rel
            frames.append(_matrix_to_euler_xyz(R_pose))
        bone_eulers[j] = frames

    # ── Root position keyframes ──
    root_bone = smpl_arm.data.bones.get(smpl_skeleton.JOINT_NAMES[0])
    root_locations = []
    if root_bone:
        R_bone = np.array([
            [root_bone.matrix_local[r][c] for c in range(3)]
            for r in range(3)
        ])
        for f in range(n_frames):
            # Scale to user scale and ground
            rp = np.array(root_positions[f]) * scale
            rp[2] -= ground_offset
            # Use unrotated positions so preview moves in the same
            # direction as the user armature retarget (both get raw
            # SMPL trajectory in world space).
            delta = rp - rest_root_pos
            root_locations.append(tuple(R_bone.T @ delta))

    # ── Create action ──
    action_name = "SMPL_Preview_Motion"
    old_action = bpy.data.actions.get(action_name)
    if old_action:
        bpy.data.actions.remove(old_action)

    action = bpy.data.actions.new(name=action_name)
    if not smpl_arm.animation_data:
        smpl_arm.animation_data_create()

    smpl_arm.animation_data.action = action
    slot = action.slots.new(name=smpl_arm.name, id_type='OBJECT')
    smpl_arm.animation_data.action_slot = slot
    cb = action_ensure_channelbag_for_slot(action, slot)

    # Set rotation mode on pose bones
    for j in range(n_joints):
        pbone = smpl_arm.pose.bones.get(smpl_skeleton.JOINT_NAMES[j])
        if pbone:
            pbone.rotation_mode = 'XYZ'

    # ── Keyframe rotations ──
    for j in range(n_joints):
        bone_name = smpl_skeleton.JOINT_NAMES[j]
        eulers = bone_eulers[j]
        for axis in range(3):
            dp = f'pose.bones["{bone_name}"].rotation_euler'
            fc = cb.fcurves.new(dp, index=axis)
            fc.keyframe_points.add(n_frames)
            for fi in range(n_frames):
                kf = fc.keyframe_points[fi]
                kf.co = (frame_start + fi, eulers[fi][axis])
                kf.interpolation = 'BEZIER'
            fc.update()

    # ── Keyframe root location ──
    if root_locations:
        bone_name = smpl_skeleton.JOINT_NAMES[0]
        for axis in range(3):
            dp = f'pose.bones["{bone_name}"].location'
            fc = cb.fcurves.new(dp, index=axis)
            fc.keyframe_points.add(n_frames)
            for fi in range(n_frames):
                kf = fc.keyframe_points[fi]
                kf.co = (frame_start + fi, root_locations[fi][axis])
                kf.interpolation = 'BEZIER'
            fc.update()

    return True


def remove_smpl_preview():
    """Remove the SMPL preview armature, wireframe, action, and handler."""
    unlink_preview_from_user()
    _unregister_frame_handler()
    _anim_data["fk_positions"] = None

    for name in (_WIREFRAME_NAME, _PREVIEW_NAME):
        obj = bpy.data.objects.get(name)
        if obj:
            bpy.data.objects.remove(obj, do_unlink=True)
    # Clean up orphaned data
    for arm in list(bpy.data.armatures):
        if arm.name.startswith(_PREVIEW_NAME) and arm.users == 0:
            bpy.data.armatures.remove(arm)
    for mesh in list(bpy.data.meshes):
        if mesh.name.startswith(_WIREFRAME_NAME) and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    # Remove the SMPL preview action
    action = bpy.data.actions.get("SMPL_Preview_Motion")
    if action and action.users == 0:
        bpy.data.actions.remove(action)


# ── Frame handler for animation ───────────────────────────────


def _on_frame_change(scene, depsgraph=None):
    """Update wireframe vertex positions from FK data each frame."""
    _update_wireframe_positions(scene.frame_current)


def _update_wireframe_positions(frame):
    """Move wireframe vertices to FK positions for the given frame."""
    fk_pos = _anim_data.get("fk_positions")
    if fk_pos is None:
        return

    wire = bpy.data.objects.get(_WIREFRAME_NAME)
    if wire is None:
        return

    frame_start = _anim_data.get("frame_start", 1)
    fi = frame - frame_start
    n_frames = fk_pos.shape[0]
    n_joints = fk_pos.shape[1]

    # Clamp to valid range
    fi = max(0, min(fi, n_frames - 1))

    mesh = wire.data
    n_verts = min(len(mesh.vertices), n_joints)
    for i in range(n_verts):
        mesh.vertices[i].co = fk_pos[fi, i].tolist()
    mesh.update()


def _register_frame_handler():
    """Register the frame-change handler (idempotent)."""
    _unregister_frame_handler()
    bpy.app.handlers.frame_change_post.append(_on_frame_change)


def _unregister_frame_handler():
    """Remove the frame-change handler if registered."""
    handlers = bpy.app.handlers.frame_change_post
    to_remove = [h for h in handlers if h is _on_frame_change]
    for h in to_remove:
        handlers.remove(h)


# ── Live retarget link handler ─────────────────────────────────


def _on_smpl_pose_update(scene, depsgraph=None):
    """Live retarget: read SMPL poses, apply conjugation to user armature."""
    if not _link_data.get("active"):
        return
    if _link_data.get("_updating"):
        return

    smpl_arm = bpy.data.objects.get(_link_data.get("smpl_arm_name", ""))
    user_arm = bpy.data.objects.get(_link_data.get("user_arm_name", ""))
    if not smpl_arm or not user_arm:
        return

    imap = _link_data["influence_map"]
    smpl_rest = _link_data["smpl_rest"]
    user_rest = _link_data["user_rest"]
    # C maps SMPL armature-space → user armature-space (handles 180° Z flip etc.)
    C = _link_data["obj_correction"]
    C_T = C.T
    # L/R swap: when object rotation flips X, visual left on SMPL
    # corresponds to R_* bones, so swap indices for correct visual mapping.
    lr_swap = _link_data.get("lr_swap", {})

    _link_data["_updating"] = True
    try:
        # Read SMPL pose bone rotations, un-conjugate to raw space,
        # then apply object-rotation correction to user armature space.
        raw_rotations = {}
        for j in range(smpl_skeleton.NUM_JOINTS):
            name = smpl_skeleton.JOINT_NAMES[j]
            pbone = smpl_arm.pose.bones.get(name)
            if not pbone or j not in smpl_rest:
                continue
            rx, ry, rz = pbone.rotation_euler
            if abs(rx) < 1e-8 and abs(ry) < 1e-8 and abs(rz) < 1e-8:
                continue  # skip identity — no pose change
            R_pose = _euler_to_matrix(rx, ry, rz)
            R_rest_s = smpl_rest[j]
            # Un-conjugate to SMPL armature raw, then correct for
            # object rotation difference:
            #   R_raw_smpl = R_rest_s @ R_pose @ R_rest_s.T
            #   R_raw_user = C @ R_raw_smpl @ C.T
            R_raw = C @ R_rest_s @ R_pose @ R_rest_s.T @ C_T
            raw_rotations[j] = R_raw

        # Accumulate and apply retarget to user bones.
        # Use lr_swap: for each influence-map slot sj, read the
        # rotation from the visually-corresponding SMPL bone.
        bone_accum = {}
        for sj in imap.mapped_smpl_joints():
            source_j = lr_swap.get(sj, sj)
            if source_j not in raw_rotations:
                continue
            R_raw = raw_rotations[source_j]
            for bone_name, weight in imap.get_targets(sj):
                if bone_name not in user_rest:
                    continue
                R_w = _fractional_rotation(R_raw, weight) if abs(weight - 1.0) > 1e-6 else R_raw
                if bone_name not in bone_accum:
                    bone_accum[bone_name] = R_w
                else:
                    bone_accum[bone_name] = bone_accum[bone_name] @ R_w

        # Apply conjugated rotations to user pose bones
        for bone_name, R_raw in bone_accum.items():
            pbone = user_arm.pose.bones.get(bone_name)
            if not pbone:
                continue
            R_rest_u = user_rest[bone_name]
            R_user_pose = R_rest_u.T @ R_raw @ R_rest_u
            pbone.rotation_euler = _matrix_to_euler_xyz(R_user_pose)

        # Root position (also correct for object rotation)
        pelvis = smpl_arm.pose.bones.get("Pelvis")
        root_name = imap.root_bone
        if pelvis and root_name:
            user_root = user_arm.pose.bones.get(root_name)
            if user_root:
                loc = np.array(pelvis.location)
                user_root.location = tuple(C @ loc)

    finally:
        _link_data["_updating"] = False


def _register_link_handler():
    """Register the depsgraph update handler for live retarget."""
    _unregister_link_handler()
    bpy.app.handlers.depsgraph_update_post.append(_on_smpl_pose_update)


def _unregister_link_handler():
    """Remove the depsgraph update handler."""
    handlers = bpy.app.handlers.depsgraph_update_post
    to_remove = [h for h in handlers if h is _on_smpl_pose_update]
    for h in to_remove:
        handlers.remove(h)


# ── Internals ──────────────────────────────────────────────────


def _get_armature_height(armature_obj):
    """Compute armature height from bone Z extents."""
    z_vals = []
    for bone in armature_obj.data.bones:
        z_vals.append(bone.head_local.z)
        z_vals.append(bone.tail_local.z)
    return (max(z_vals) - min(z_vals)) if z_vals else 1.8


def _compute_tpose_positions(scale):
    """Compute T-pose joint world positions (Z-up, scaled)."""
    positions = np.zeros((smpl_skeleton.NUM_JOINTS, 3))
    for i in range(smpl_skeleton.NUM_JOINTS):
        p = int(smpl_skeleton.PARENTS[i])
        if p >= 0:
            positions[i] = positions[p] + smpl_skeleton.OFFSETS_ZUP[i] * scale
        else:
            positions[i] = smpl_skeleton.OFFSETS_ZUP[i] * scale
    return positions


def _create_wireframe(arm_obj, positions):
    """Create a mesh with edges connecting SMPL parent-child joints.

    The wireframe is parented to the armature object so it moves
    with it.  Vertex positions are updated per-frame by the
    frame_change handler during animation.
    """
    import bmesh

    bm = bmesh.new()

    verts = []
    for i in range(smpl_skeleton.NUM_JOINTS):
        v = bm.verts.new(positions[i])
        verts.append(v)

    bm.verts.ensure_lookup_table()

    for i in range(smpl_skeleton.NUM_JOINTS):
        p = int(smpl_skeleton.PARENTS[i])
        if p >= 0:
            bm.edges.new((verts[p], verts[i]))

    mesh_data = bpy.data.meshes.new(_WIREFRAME_NAME)
    bm.to_mesh(mesh_data)
    bm.free()

    wire_obj = bpy.data.objects.new(_WIREFRAME_NAME, mesh_data)
    bpy.context.collection.objects.link(wire_obj)
    wire_obj.parent = arm_obj
    wire_obj.display_type = 'WIRE'
    wire_obj.show_in_front = True

    return wire_obj
