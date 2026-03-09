"""Export armature + meshes to FBX for Unreal Engine."""

import os

import bpy

from .scale_rig import scale_rig


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

    # Duplicate hierarchy
    dup_arm, dup_meshes = _duplicate_hierarchy(armature_obj, mesh_objects)

    try:
        # Scale duplicates 100x
        scale_stats = scale_rig(dup_arm, 100.0)
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
                    dup_arm, dup_meshes, output_dir, base_name, ue_naming
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

    return result


def _duplicate_hierarchy(armature_obj, mesh_objects):
    """Duplicate armature and mesh objects, preserving parent relationships."""
    bpy.ops.object.select_all(action='DESELECT')

    armature_obj.select_set(True)
    for mesh in mesh_objects:
        mesh.select_set(True)

    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.duplicate()

    # Find duplicates (they're now selected)
    dup_arm = None
    dup_meshes = []
    for obj in bpy.context.selected_objects:
        if obj.type == 'ARMATURE':
            dup_arm = obj
        elif obj.type == 'MESH':
            dup_meshes.append(obj)

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


def _export_separate_anims(armature, meshes, output_dir, base_name, ue_naming):
    """Export each action targeting the armature as a separate FBX."""
    files = []
    original_action = None

    if armature.animation_data:
        original_action = armature.animation_data.action

    from .scale_rig import _find_armature_actions
    armature_actions = _find_armature_actions(armature)

    for action in armature_actions:

        # Assign this action
        if not armature.animation_data:
            armature.animation_data_create()
        armature.animation_data.action = action

        action_clean = action.name.replace(" ", "_")
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
