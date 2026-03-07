"""Module → final rig assembly."""

import bpy
from ..core.constants import COL_DEFORM, COL_CONTROL, COL_MECHANISM
from ..core.constants import DEFORM_PREFIX, CONTROL_PREFIX, MECHANISM_PREFIX
from ..core.constants import WRAP_CTRL_PREFIX, WRAP_MCH_PREFIX


def _ensure_bone_collections(armature):
    """Create DEF, CTRL, MCH bone collections if they don't exist."""
    for col_name in (COL_DEFORM, COL_CONTROL, COL_MECHANISM):
        if col_name not in armature.collections:
            armature.collections.new(name=col_name)


def _assign_bone_to_collection(armature, bone_name):
    """Assign a bone to the appropriate collection based on prefix."""
    bone = armature.bones.get(bone_name)
    if bone is None:
        return

    if bone_name.startswith(DEFORM_PREFIX):
        col_name = COL_DEFORM
    elif bone_name.startswith(CONTROL_PREFIX):
        col_name = COL_CONTROL
    elif bone_name.startswith(MECHANISM_PREFIX):
        col_name = COL_MECHANISM
    else:
        col_name = COL_DEFORM  # Default to deform

    col = armature.collections.get(col_name)
    if col:
        col.assign(bone)


def _resolve_parent_bone(modules, parent_ref, all_bone_names, armature=None):
    """Resolve a parent_bone reference like 'Spine.chest'.

    Args:
        modules: List of instantiated modules.
        parent_ref: String like 'Spine.chest' or direct bone name.
        all_bone_names: Set of all created bone names.
        armature: Optional armature data for resolving existing bone names.

    Returns:
        Bone name string, or None.
    """
    if not parent_ref:
        return None

    # Direct bone name — check created bones first, then existing bones
    if parent_ref in all_bone_names:
        return parent_ref
    if armature and parent_ref in armature.edit_bones:
        return parent_ref

    # Module.connection_point format
    if "." in parent_ref:
        module_name, point_name = parent_ref.split(".", 1)
        for mod in modules:
            if mod.name == module_name:
                points = mod.get_connection_points()
                return points.get(point_name)

    return None


def _topological_sort(modules):
    """Sort modules so parents come before children.

    Modules with no parent_bone come first, then those referencing
    already-placed modules.
    """
    sorted_modules = []
    remaining = list(modules)
    placed_names = set()

    # Safety limit to prevent infinite loops
    max_iterations = len(remaining) * 2
    iterations = 0

    while remaining and iterations < max_iterations:
        iterations += 1
        progress = False
        for mod in list(remaining):
            parent_ref = mod.parent_bone
            if not parent_ref:
                sorted_modules.append(mod)
                remaining.remove(mod)
                placed_names.add(mod.name)
                progress = True
            elif "." in parent_ref:
                module_name = parent_ref.split(".")[0]
                if module_name in placed_names:
                    sorted_modules.append(mod)
                    remaining.remove(mod)
                    placed_names.add(mod.name)
                    progress = True

        if not progress:
            # Break cycle: add remaining modules as-is
            sorted_modules.extend(remaining)
            break

    return sorted_modules


def _deduplicate_module_names(modules):
    """Ensure unique (name, side) combinations to prevent bone name clashes.

    When multiple modules share the same name and side, Blender silently
    renames duplicate bones with .001 suffixes, breaking constraint
    subtarget references.  This appends a numeric suffix to disambiguate.
    """
    counts = {}
    for mod in modules:
        key = (mod.name, mod.side)
        counts[key] = counts.get(key, 0) + 1

    used = {}
    for mod in modules:
        key = (mod.name, mod.side)
        if counts[key] > 1:
            idx = used.get(key, 0) + 1
            used[key] = idx
            mod.name = f"{mod.name}{idx}"


def assemble_rig(armature_obj, modules):
    """Assemble a complete rig from module instances.

    Args:
        armature_obj: The armature object.
        modules: List of RigModule instances.

    Returns:
        List of all created bone names.
    """
    armature = armature_obj.data
    all_bone_names = set()

    # Deduplicate modules that share (name, side) to prevent bone name clashes
    _deduplicate_module_names(modules)

    # Sort modules by dependency
    sorted_modules = _topological_sort(modules)

    # --- Edit Mode: Create all bones ---
    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode='EDIT')

    _ensure_bone_collections(armature)

    for mod in sorted_modules:
        bone_names = mod.create_bones(armature, armature.edit_bones)
        all_bone_names.update(bone_names)

    # Resolve parent bones — only reparent newly created bones, not mapped ones
    for mod in sorted_modules:
        parent_name = _resolve_parent_bone(sorted_modules, mod.parent_bone, all_bone_names, armature)
        if parent_name:
            connection_points = mod.get_connection_points()
            root_point = connection_points.get("root")
            # Only reparent if the root bone was created by this assembly (in all_bone_names)
            if root_point and root_point in all_bone_names and root_point in armature.edit_bones:
                parent_eb = armature.edit_bones.get(parent_name)
                if parent_eb:
                    armature.edit_bones[root_point].parent = parent_eb

    # --- Object Mode briefly to refresh ---
    bpy.ops.object.mode_set(mode='OBJECT')

    # Assign bone collections — only for newly created bones
    for bone_name in all_bone_names:
        _assign_bone_to_collection(armature, bone_name)

    # Note: mapped existing bones (from bone_mapping) are NOT in all_bone_names
    # so they keep their original collections and properties

    # Hide mechanism bones
    mch_col = armature.collections.get(COL_MECHANISM)
    if mch_col:
        mch_col.is_visible = False

    # --- Pose Mode: Constraints + Controls ---
    bpy.ops.object.mode_set(mode='POSE')

    for mod in sorted_modules:
        mod.setup_constraints(armature_obj, armature_obj.pose.bones)
        mod.create_controls(armature_obj)

    bpy.ops.object.mode_set(mode='OBJECT')

    return list(all_bone_names)


def disassemble_rig(armature_obj):
    """Remove modular rig bones (DEF-/CTRL-/MCH-), preserving wrap rig bones."""
    armature = armature_obj.data
    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode='EDIT')

    to_remove = []
    for eb in armature.edit_bones:
        name = eb.name
        # Never touch wrap rig bones
        if name.startswith(WRAP_CTRL_PREFIX) or name.startswith(WRAP_MCH_PREFIX):
            continue
        if (name.startswith(DEFORM_PREFIX) or
                name.startswith(CONTROL_PREFIX) or
                name.startswith(MECHANISM_PREFIX)):
            to_remove.append(name)

    for name in to_remove:
        eb = armature.edit_bones.get(name)
        if eb:
            armature.edit_bones.remove(eb)

    bpy.ops.object.mode_set(mode='OBJECT')
    return to_remove
