"""Facial expression shape key presets."""

import bpy

# Expression preset definitions: name -> {shape_key_name: value}
EXPRESSION_PRESETS = {
    "smile": {
        "MouthCornerUp_L": 1.0,
        "MouthCornerUp_R": 1.0,
        "CheekPuff_L": 0.3,
        "CheekPuff_R": 0.3,
    },
    "frown": {
        "MouthCornerDown_L": 1.0,
        "MouthCornerDown_R": 1.0,
        "BrowDown_L": 0.5,
        "BrowDown_R": 0.5,
    },
    "blink": {
        "EyeClose_L": 1.0,
        "EyeClose_R": 1.0,
    },
    "surprise": {
        "BrowUp_L": 1.0,
        "BrowUp_R": 1.0,
        "MouthOpen": 0.6,
        "EyeWide_L": 0.8,
        "EyeWide_R": 0.8,
    },
    "angry": {
        "BrowDown_L": 1.0,
        "BrowDown_R": 1.0,
        "BrowSqueeze": 0.7,
        "NoseWrinkle": 0.5,
        "MouthCornerDown_L": 0.3,
        "MouthCornerDown_R": 0.3,
    },
}


def ensure_shape_keys(mesh_obj, key_names):
    """Ensure shape keys exist on a mesh object.

    Args:
        mesh_obj: The mesh object.
        key_names: List of shape key names to create.

    Returns:
        The shape key block.
    """
    if mesh_obj.data.shape_keys is None:
        mesh_obj.shape_key_add(name="Basis")

    for name in key_names:
        if name not in mesh_obj.data.shape_keys.key_blocks:
            mesh_obj.shape_key_add(name=name)

    return mesh_obj.data.shape_keys


def apply_expression_preset(mesh_obj, preset_name, value=1.0):
    """Set shape key values for a named expression preset.

    Args:
        mesh_obj: Mesh with shape keys.
        preset_name: One of the EXPRESSION_PRESETS keys.
        value: Overall expression intensity (0-1).
    """
    preset = EXPRESSION_PRESETS.get(preset_name)
    if not preset:
        return False

    if mesh_obj.data.shape_keys is None:
        return False

    for key_name, key_val in preset.items():
        sk = mesh_obj.data.shape_keys.key_blocks.get(key_name)
        if sk:
            sk.value = key_val * value

    return True


def keyframe_expression(mesh_obj, preset_name, frame, value=1.0):
    """Keyframe an expression preset at a given frame.

    Args:
        mesh_obj: Mesh with shape keys.
        preset_name: Expression preset name.
        frame: Frame number.
        value: Expression intensity.
    """
    preset = EXPRESSION_PRESETS.get(preset_name)
    if not preset or mesh_obj.data.shape_keys is None:
        return False

    for key_name, key_val in preset.items():
        sk = mesh_obj.data.shape_keys.key_blocks.get(key_name)
        if sk:
            sk.value = key_val * value
            sk.keyframe_insert(data_path="value", frame=frame)

    return True


def create_expression_drivers(mesh_obj, control_bone_name, armature_obj):
    """Create drivers linking shape keys to a control bone's properties.

    Maps control bone custom properties to shape key values.

    Args:
        mesh_obj: Mesh with shape keys.
        control_bone_name: Pose bone name with custom props.
        armature_obj: The armature object.
    """
    if mesh_obj.data.shape_keys is None:
        return

    for kb in mesh_obj.data.shape_keys.key_blocks:
        if kb.name == "Basis":
            continue

        # Create driver
        driver = kb.driver_add("value").driver
        driver.type = 'SCRIPTED'

        var = driver.variables.new()
        var.name = "ctrl"
        var.type = 'SINGLE_PROP'

        target = var.targets[0]
        target.id = armature_obj
        target.data_path = f'pose.bones["{control_bone_name}"]["{kb.name}"]'

        driver.expression = "ctrl"
