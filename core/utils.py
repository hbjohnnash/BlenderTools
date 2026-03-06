"""Shared BMesh/math helpers and Blender 5.0 animation utilities."""

import bpy
import bmesh
import mathutils
import os
import json
from math import radians, degrees
from pathlib import Path



def get_addon_directory():
    """Return the root directory of this addon."""
    return Path(__file__).resolve().parent.parent


def get_presets_directory():
    """Return the presets directory path."""
    return get_addon_directory() / "presets"


def load_json_preset(subdir, name):
    """Load a JSON preset file from presets/<subdir>/<name>.json."""
    path = get_presets_directory() / subdir / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Preset not found: {path}")
    with open(path, "r") as f:
        return json.load(f)


def save_json_preset(subdir, name, data):
    """Save a JSON preset file to presets/<subdir>/<name>.json."""
    path = get_presets_directory() / subdir / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def ensure_edit_mode(obj):
    """Ensure the given object is in edit mode."""
    if bpy.context.active_object != obj:
        bpy.context.view_layer.objects.active = obj
    if obj.mode != 'EDIT':
        bpy.ops.object.mode_set(mode='EDIT')


def ensure_object_mode():
    """Ensure we are in object mode."""
    if bpy.context.active_object and bpy.context.active_object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')


def get_bmesh_from_object(obj):
    """Get a BMesh from a mesh object (must be in edit mode)."""
    ensure_edit_mode(obj)
    return bmesh.from_edit_mesh(obj.data)


def update_bmesh(obj, bm):
    """Update the mesh from BMesh data."""
    bmesh.update_edit_mesh(obj.data)


def mirror_name(name):
    """Mirror a bone/object name (swap L/R)."""
    if "_L_" in name:
        return name.replace("_L_", "_R_")
    elif "_R_" in name:
        return name.replace("_R_", "_L_")
    elif name.endswith("_L"):
        return name[:-2] + "_R"
    elif name.endswith("_R"):
        return name[:-2] + "_L"
    return name


# ---------------------------------------------------------------------------
# Blender 5.0 Channelbag Animation Helper
# ---------------------------------------------------------------------------

def create_fcurve(obj, action_name, data_path, index, keyframes):
    """Create an FCurve using Blender 5.0 channelbag API.

    Args:
        obj: The object to animate.
        action_name: Name for the action.
        data_path: FCurve data path (e.g. 'location').
        index: Array index (0=X, 1=Y, 2=Z).
        keyframes: List of (frame, value) tuples.

    Returns:
        The created FCurve.
    """
    from bpy_extras.anim_utils import action_ensure_channelbag_for_slot

    # Get or create action
    action = bpy.data.actions.get(action_name)
    if action is None:
        action = bpy.data.actions.new(name=action_name)

    # Assign action to object if not already
    if not obj.animation_data:
        obj.animation_data_create()

    obj.animation_data.action = action

    # Get or create slot for this object
    slot = None
    if obj.animation_data and obj.animation_data.action_slot:
        slot = obj.animation_data.action_slot
    if slot is None:
        slot = action.slots.new(for_id=obj)

    obj.animation_data.action_slot = slot

    # Ensure channelbag exists for slot
    channelbag = action_ensure_channelbag_for_slot(action, slot)

    # Create or get fcurve
    fcurve = None
    for fc in channelbag.fcurves:
        if fc.data_path == data_path and fc.array_index == index:
            fcurve = fc
            break
    if fcurve is None:
        fcurve = channelbag.fcurves.new(data_path, index=index)

    # Insert keyframes
    fcurve.keyframe_points.add(len(keyframes))
    for i, (frame, value) in enumerate(keyframes):
        kf = fcurve.keyframe_points[i]
        kf.co = (frame, value)
        kf.interpolation = 'BEZIER'

    fcurve.update()
    return fcurve


def create_bone_fcurve(armature_obj, action_name, bone_name, prop, index, keyframes):
    """Create an FCurve for a pose bone property.

    Args:
        armature_obj: The armature object.
        action_name: Name for the action.
        bone_name: Name of the pose bone.
        prop: Property name (e.g. 'location', 'rotation_euler').
        index: Array index.
        keyframes: List of (frame, value) tuples.
    """
    data_path = f'pose.bones["{bone_name}"].{prop}'
    return create_fcurve(armature_obj, action_name, data_path, index, keyframes)
