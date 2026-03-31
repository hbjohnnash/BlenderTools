"""Export armature + meshes to FBX for Unreal Engine."""

import os

import bpy

from .scale_rig import scale_rig

_BT_INTERNAL_COLLECTIONS = {"BT_Shapes", "BT_OnionSkin_Proxy"}
_BT_INTERNAL_PREFIXES = ("BT_Proxy_", "BT_Shape_")


def _is_bt_internal(mesh_obj):
    """Return True if mesh_obj is a BlenderTools internal mesh (not for export).

    Catches: custom bone shapes (BT_Shapes collection), onion skin proxies
    (BT_Proxy_ prefix / BT_OnionSkin_Proxy collection), and any future
    BT-managed utility meshes.
    """
    if mesh_obj.name.startswith(_BT_INTERNAL_PREFIXES):
        return True
    for col_name in _BT_INTERNAL_COLLECTIONS:
        col = bpy.data.collections.get(col_name)
        if col and mesh_obj.name in col.objects:
            return True
    return False


def filter_exportable_meshes(armature_obj):
    """Return mesh children of armature, excluding BT internal meshes."""
    return [c for c in armature_obj.children
            if c.type == 'MESH' and not _is_bt_internal(c)]


def export_to_ue(armature_obj, mesh_objects, output_dir,
                 export_mesh=True, export_anim=True,
                 separate_anim=False, ue_naming=True):
    """Export armature and meshes as UE-ready FBX.

    Duplicates the hierarchy, scales 100x, exports at 0.01 global scale,
    then cleans up duplicates.

    Args:
        armature_obj: Source armature object.
        mesh_objects: List of mesh objects to include.
        output_dir: Directory to write FBX files.
        export_mesh: Export skeletal mesh FBX.
        export_anim: Export animation FBX(s).
        separate_anim: Export each action as a separate FBX.
        ue_naming: Add SK_/A_ prefixes to filenames.

    Returns:
        Dict with exported file paths and stats.
    """
    os.makedirs(output_dir, exist_ok=True)
    base_name = armature_obj.name
    result = {"success": True, "files": [], "stats": {}}

    # Must be in object mode — bpy.ops.object.select_all() fails silently
    # from pose mode, leaving stale selections that leak into the FBX
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    # Filter out any BT internal meshes and non-armature-parented meshes
    mesh_objects = [m for m in mesh_objects
                    if m.parent == armature_obj and not _is_bt_internal(m)]

    # Duplicate hierarchy
    dup_arm, dup_meshes = _duplicate_hierarchy(armature_obj, mesh_objects)

    # Clear custom bone shapes on the duplicate — secondary defense against
    # shape meshes leaking into the FBX via bone.custom_shape references
    _clear_custom_shapes(dup_arm)

    # Isolate actions — copy all matching actions so scale_rig
    # doesn't corrupt the original armature's shared action datablocks
    copied_actions = _isolate_actions(dup_arm)

    try:
        # Scale duplicates 100x (only affects the isolated copies)
        scale_stats = scale_rig(dup_arm, 100.0, actions=copied_actions)
        result["stats"]["scale"] = scale_stats

        if export_mesh:
            mesh_name = f"SK_{base_name}" if ue_naming else base_name
            mesh_path = os.path.join(output_dir, f"{mesh_name}.fbx")
            _export_fbx(dup_arm, dup_meshes, mesh_path,
                        bake_anim=False)
            result["files"].append(mesh_path)

        if export_anim:
            if separate_anim:
                anim_files = _export_separate_anims(
                    dup_arm, dup_meshes, output_dir, base_name, ue_naming,
                    actions=copied_actions
                )
                result["files"].extend(anim_files)
            else:
                anim_name = f"A_{base_name}" if ue_naming else f"{base_name}_anim"
                anim_path = os.path.join(output_dir, f"{anim_name}.fbx")
                _export_fbx(dup_arm, dup_meshes, anim_path,
                            bake_anim=True)
                result["files"].append(anim_path)

    finally:
        _delete_objects(dup_arm, dup_meshes)
        _cleanup_temp_actions(copied_actions)

    return result


def _isolate_actions(armature_obj):
    """Copy all actions targeting this armature so originals aren't modified.

    bpy.ops.object.duplicate() shares action datablocks between original
    and duplicate. Without isolation, scale_rig would corrupt the originals.

    Returns:
        Set of copied action datablocks (pass to scale_rig and cleanup).
    """
    from .scale_rig import _find_armature_actions

    original_actions = _find_armature_actions(armature_obj)
    action_map = {}  # original -> copy

    for action in original_actions:
        copy = action.copy()
        copy.name = action.name + "__export_tmp"
        action_map[action] = copy

    # Re-link the armature's animation data to the copies
    anim_data = armature_obj.animation_data
    if anim_data:
        if anim_data.action in action_map:
            anim_data.action = action_map[anim_data.action]
        for track in anim_data.nla_tracks:
            for strip in track.strips:
                if strip.action in action_map:
                    strip.action = action_map[strip.action]

    return set(action_map.values())


def _clear_custom_shapes(armature_obj):
    """Remove custom_shape references from all pose bones.

    The FBX exporter includes custom_shape mesh objects even when
    use_selection=True. Clearing them on the duplicate prevents
    BT_Shape_* meshes from leaking into the exported FBX.
    """
    for pbone in armature_obj.pose.bones:
        pbone.custom_shape = None


def _cleanup_temp_actions(actions):
    """Remove temporary action copies created by _isolate_actions."""
    for action in actions:
        if action and action.name in {a.name for a in bpy.data.actions}:
            bpy.data.actions.remove(action)


def _duplicate_hierarchy(armature_obj, mesh_objects):
    """Duplicate armature and mesh objects, preserving parent relationships."""
    bpy.ops.object.select_all(action='DESELECT')

    armature_obj.select_set(True)
    for mesh in mesh_objects:
        mesh.select_set(True)

    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.duplicate()

    # Find duplicates (they're now selected), excluding bone shape meshes
    dup_arm = None
    dup_meshes = []
    dup_shapes = []
    for obj in bpy.context.selected_objects:
        if obj.type == 'ARMATURE':
            dup_arm = obj
        elif obj.type == 'MESH':
            if _is_bt_internal(obj):
                dup_shapes.append(obj)
            else:
                dup_meshes.append(obj)

    # Clean up any duplicated bone shape meshes immediately
    if dup_shapes:
        bpy.ops.object.select_all(action='DESELECT')
        for s in dup_shapes:
            s.select_set(True)
        bpy.ops.object.delete()

    return dup_arm, dup_meshes


def _delete_objects(armature, meshes):
    """Delete temporary duplicate objects."""
    bpy.ops.object.select_all(action='DESELECT')

    for mesh in meshes:
        if mesh and mesh.name in bpy.data.objects:
            mesh.select_set(True)
    if armature and armature.name in bpy.data.objects:
        armature.select_set(True)

    bpy.ops.object.delete()


def _export_fbx(armature, meshes, filepath, bake_anim=True):
    """Export selected objects as FBX with UE-compatible settings."""
    bpy.ops.object.select_all(action='DESELECT')

    armature.select_set(True)
    for mesh in meshes:
        mesh.select_set(True)

    bpy.context.view_layer.objects.active = armature

    bpy.ops.export_scene.fbx(
        filepath=filepath,
        use_selection=True,
        global_scale=0.01,
        apply_unit_scale=False,
        apply_scale_options='FBX_SCALE_NONE',
        axis_forward='-Y',
        axis_up='Z',
        object_types={'ARMATURE', 'MESH'},
        use_armature_deform_only=True,
        add_leaf_bones=False,
        bake_anim=bake_anim,
        bake_anim_use_all_bones=True,
        bake_anim_use_nla_strips=False,
        bake_anim_use_all_actions=not bake_anim,  # single action when baking
        bake_anim_force_startend_keying=True,
        mesh_smooth_type='FACE',
        use_mesh_modifiers=True,
    )


def _export_separate_anims(armature, meshes, output_dir, base_name, ue_naming,
                           actions=None):
    """Export each action targeting the armature as a separate FBX."""
    files = []
    original_action = None

    if armature.animation_data:
        original_action = armature.animation_data.action

    if actions is not None:
        armature_actions = actions
    else:
        from .scale_rig import _find_armature_actions
        armature_actions = _find_armature_actions(armature)

    for action in armature_actions:

        # Assign this action
        if not armature.animation_data:
            armature.animation_data_create()
        armature.animation_data.action = action

        action_clean = action.name.removesuffix("__export_tmp").replace(" ", "_")
        if ue_naming:
            fname = f"A_{base_name}_{action_clean}.fbx"
        else:
            fname = f"{base_name}_{action_clean}.fbx"

        fpath = os.path.join(output_dir, fname)
        _export_fbx(armature, meshes, fpath, bake_anim=True)
        files.append(fpath)

    # Restore original action
    if armature.animation_data and original_action:
        armature.animation_data.action = original_action

    return files
