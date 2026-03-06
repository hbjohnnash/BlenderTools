"""JSON config parser for rig configurations."""

import json
from ..core.utils import load_json_preset, save_json_preset
from ..core.constants import RIG_CONFIG_DIR
from .modules import get_module_class


def load_rig_config(name):
    """Load a rig config from presets/rig_configs/.

    Args:
        name: Config name (without .json).

    Returns:
        Parsed config dict.
    """
    return load_json_preset(RIG_CONFIG_DIR, name)


def save_rig_config(name, config):
    """Save a rig config to presets/rig_configs/."""
    save_json_preset(RIG_CONFIG_DIR, name, config)


def instantiate_modules(config):
    """Create module instances from a config dict.

    Args:
        config: Full rig config with "modules" list.

    Returns:
        List of RigModule instances.
    """
    modules = []
    global_options = config.get("global_options", {})

    for mod_config in config.get("modules", []):
        module_type = mod_config.get("type")
        cls = get_module_class(module_type)
        if cls is None:
            raise ValueError(f"Unknown module type: {module_type}")

        # Merge global options into module options
        merged = dict(mod_config)
        opts = dict(global_options)
        opts.update(mod_config.get("options", {}))
        merged["options"] = opts

        modules.append(cls(merged))

    return modules


def config_from_armature(armature_obj):
    """Read stored config JSON from armature custom property.

    Args:
        armature_obj: Armature object.

    Returns:
        Config dict, or None if not stored.
    """
    config_str = armature_obj.get("bt_rig_config")
    if config_str:
        return json.loads(config_str)
    return None


def store_config_on_armature(armature_obj, config):
    """Store config JSON as a custom property on the armature."""
    armature_obj["bt_rig_config"] = json.dumps(config, indent=2)


def list_rig_configs():
    """List available rig config presets."""
    from ..core.utils import get_presets_directory
    config_dir = get_presets_directory() / RIG_CONFIG_DIR
    if not config_dir.exists():
        return []
    return [p.stem for p in config_dir.glob("*.json")]
