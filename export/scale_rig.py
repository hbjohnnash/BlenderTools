"""Scale an armature rig and update all related data."""

import json

import bpy


def scale_rig(armature_obj, factor, actions=None):
    """Scale an armature and all associated data by a factor.

    Args:
        armature_obj: The armature object to scale.
        factor: Scale multiplier (e.g. 100.0 for Blender→UE prep).
        actions: Optional explicit set of actions to scale. If provided,
                 only these actions are modified (skips auto-discovery).
                 Use this when scaling a duplicate to avoid corrupting
                 shared action datablocks on the original armature.

    Returns:
        Dict with stats: bones_scaled, actions_scaled, constraints_scaled,
        meshes_scaled, config_updated.
    """
    stats = {
        "bones_scaled": 0,
        "actions_scaled": 0,
        "fcurves_scaled": 0,
        "constraints_scaled": 0,
        "meshes_scaled": 0,
        "config_updated": False,
    }

    # 1. Scale armature object and apply
    armature_obj.scale *= factor
    prev_mode = bpy.context.mode
    if prev_mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    bpy.context.view_layer.objects.active = armature_obj
    armature_obj.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    stats["bones_scaled"] = len(armature_obj.data.bones)

    # 2. Scale child mesh objects (before armature apply propagates weirdly)
    stats["meshes_scaled"] = _scale_child_meshes(armature_obj, factor)

    # 3. Scale location keyframes in actions targeting this armature
    stats["actions_scaled"], stats["fcurves_scaled"] = _scale_actions(
        armature_obj, factor, actions
    )

    # 4. Scale constraint distance values
    stats["constraints_scaled"] = _scale_constraints(armature_obj, factor)

    # 5. Update bt_rig_config custom property
    stats["config_updated"] = _scale_rig_config(armature_obj, factor)

    # Restore original mode
    if prev_mode == 'POSE':
        bpy.ops.object.mode_set(mode='POSE')
    elif prev_mode.startswith('EDIT'):
        bpy.ops.object.mode_set(mode='EDIT')

    return stats


def _get_channelbag(action, slot):
    """Get channelbag for a slot using Blender 5.0 layers API.

    Path: action.layers[0].strips[0].channelbag(slot)
    Returns None if no layers/strips exist.
    """
    if not action.layers:
        return None
    layer = action.layers[0]
    if not layer.strips:
        return None
    strip = layer.strips[0]
    try:
        return strip.channelbag(slot)
    except Exception:
        return None


def _scale_actions(armature_obj, factor, actions=None):
    """Scale location keyframe values in actions for this armature.

    Uses Blender 5.0 API: action.layers[0].strips[0].channelbag(slot).fcurves.

    Args:
        armature_obj: The armature whose actions to scale.
        factor: Scale multiplier for location keyframe values.
        actions: Optional explicit set of actions to scale. If None,
                 auto-discovers via _find_armature_actions (global scan).
    """
    actions_count = 0
    fcurves_count = 0

    armature_actions = actions if actions is not None else _find_armature_actions(armature_obj)

    for action in armature_actions:
        action_scaled = False

        for slot in action.slots:
            channelbag = _get_channelbag(action, slot)
            if channelbag is None:
                continue

            for fc in channelbag.fcurves:
                if not _is_location_fcurve(fc.data_path):
                    continue

                action_scaled = True
                fcurves_count += 1
                for kp in fc.keyframe_points:
                    kp.co.y *= factor
                    kp.handle_left.y *= factor
                    kp.handle_right.y *= factor
                fc.update()

        if action_scaled:
            actions_count += 1

    return actions_count, fcurves_count


def _find_armature_actions(armature_obj):
    """Find all actions that target this armature.

    Checks: current action, NLA strips, and actions with fcurves
    referencing bones in this armature.
    """
    actions = set()
    bone_names = {b.name for b in armature_obj.data.bones}

    anim_data = armature_obj.animation_data
    if anim_data:
        if anim_data.action:
            actions.add(anim_data.action)

        for track in anim_data.nla_tracks:
            for strip in track.strips:
                if strip.action:
                    actions.add(strip.action)

    # Scan all actions for pose bone fcurves matching our bones
    for action in bpy.data.actions:
        if action in actions:
            continue
        found = False
        for slot in action.slots:
            channelbag = _get_channelbag(action, slot)
            if channelbag is None:
                continue
            for fc in channelbag.fcurves:
                dp = fc.data_path
                if dp.startswith('pose.bones["'):
                    bone_name = dp.split('"')[1]
                    if bone_name in bone_names:
                        actions.add(action)
                        found = True
                        break
            if found:
                break

    return actions


def _is_location_fcurve(data_path):
    """Check if an fcurve data_path is a location channel."""
    return data_path == "location" or data_path.endswith(".location")


_DISTANCE_CONSTRAINT_TYPES = {
    'LIMIT_DISTANCE': ['distance'],
    'STRETCH_TO': ['rest_length'],
    'FLOOR': ['offset'],
    'LIMIT_LOCATION': [
        'min_x', 'max_x', 'min_y', 'max_y', 'min_z', 'max_z'
    ],
}


def _scale_constraints(armature_obj, factor):
    """Scale distance-related constraint values on pose bones."""
    count = 0

    for pbone in armature_obj.pose.bones:
        for con in pbone.constraints:
            con_type = con.type
            if con_type not in _DISTANCE_CONSTRAINT_TYPES:
                continue

            for attr in _DISTANCE_CONSTRAINT_TYPES[con_type]:
                if hasattr(con, attr):
                    setattr(con, attr, getattr(con, attr) * factor)
                    count += 1

    return count


def _scale_child_meshes(armature_obj, factor):
    """Scale child mesh objects and apply their scale.

    Explicitly sets scale to the factor on each child mesh then applies,
    ensuring clean (1,1,1) scale regardless of parenting type.
    """
    count = 0

    for child in armature_obj.children:
        if child.type != 'MESH':
            continue

        child.scale = (factor, factor, factor)
        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        child.select_set(True)
        bpy.context.view_layer.objects.active = child
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        count += 1

    # Restore armature as active
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    armature_obj.select_set(True)
    bpy.context.view_layer.objects.active = armature_obj

    return count


_DISTANCE_KEYS = {"length", "distance", "radius", "offset", "height"}


def _scale_rig_config(armature_obj, factor):
    """Update bt_rig_config custom property: scale positions and distance options."""
    config_str = armature_obj.get("bt_rig_config")
    if not config_str:
        return False

    try:
        config = json.loads(config_str)
    except (json.JSONDecodeError, TypeError):
        return False

    for module in config.get("modules", []):
        if "position" in module:
            module["position"] = [v * factor for v in module["position"]]

        options = module.get("options", {})
        for key, value in options.items():
            if isinstance(value, (int, float)):
                key_lower = key.lower()
                if any(dk in key_lower for dk in _DISTANCE_KEYS):
                    options[key] = value * factor

    armature_obj["bt_rig_config"] = json.dumps(config, indent=2)
    return True
