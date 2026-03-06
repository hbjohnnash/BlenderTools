"""Abstract base class for rig modules."""

from abc import ABC, abstractmethod


class RigModule(ABC):
    """Base class for all rig modules.

    Each module knows how to create its bones, set up constraints,
    and build control shapes. Modules are assembled by assembly.py.
    """

    module_type = ""        # e.g. "spine", "arm", "leg"
    display_name = ""       # e.g. "Spine", "Arm"
    category = "organic"    # "organic" or "mechanical"

    def __init__(self, config):
        """Initialize from a config dict.

        Args:
            config: Dict with keys: name, side, parent_bone, position, options
        """
        self.name = config.get("name", self.display_name)
        self.side = config.get("side", "C")
        self.parent_bone = config.get("parent_bone", "")
        self.position = config.get("position", [0, 0, 0])
        self.options = config.get("options", {})

    def bone_name(self, prefix, part):
        """Generate a bone name following naming convention.

        Returns: {prefix}{ModuleName}_{side}_{part}
        e.g. DEF-Arm_L_Upper
        """
        return f"{prefix}{self.name}_{self.side}_{part}"

    def def_name(self, part):
        from ..core.constants import DEFORM_PREFIX
        return self.bone_name(DEFORM_PREFIX, part)

    def ctrl_name(self, part):
        from ..core.constants import CONTROL_PREFIX
        return self.bone_name(CONTROL_PREFIX, part)

    def mch_name(self, part):
        from ..core.constants import MECHANISM_PREFIX
        return self.bone_name(MECHANISM_PREFIX, part)

    @abstractmethod
    def create_bones(self, armature, edit_bones):
        """Create bones in edit mode.

        Args:
            armature: The armature data.
            edit_bones: armature.edit_bones collection.

        Returns:
            List of created bone names.
        """
        pass

    @abstractmethod
    def setup_constraints(self, armature_obj, pose_bones):
        """Set up constraints in pose mode.

        Args:
            armature_obj: The armature object.
            pose_bones: armature_obj.pose.bones collection.
        """
        pass

    def create_controls(self, armature_obj):
        """Create custom bone shapes for controls. Override if needed."""
        pass

    @abstractmethod
    def get_connection_points(self):
        """Return named connection points for other modules to attach to.

        Returns:
            Dict mapping point names to bone names.
            e.g. {"hip": "DEF-Spine_C_001", "chest": "DEF-Spine_C_004"}
        """
        pass

    def get_bone_slots(self):
        """Return bone slots that can be mapped to existing bones.

        Override in modules that can wrap existing skeleton bones.
        When bone_mapping is provided in options, the module uses
        existing bones instead of creating new DEF bones.

        Returns:
            List of (role, description) tuples.
            e.g. [("Cylinder", "Main piston body"), ("Rod", "Sliding rod")]
        """
        return []

    def mapped_bone(self, role):
        """Get the existing bone name mapped to a role, or None."""
        mapping = self.options.get("bone_mapping", {})
        return mapping.get(role)

    def get_ui_properties(self):
        """Return custom properties for the rig control panel.

        Returns:
            List of dicts: [{"name": "ik_fk", "type": "float", "default": 0.0, ...}]
        """
        return []

    def to_config(self):
        """Serialize module back to config dict."""
        return {
            "type": self.module_type,
            "name": self.name,
            "side": self.side,
            "parent_bone": self.parent_bone,
            "position": list(self.position),
            "options": dict(self.options),
        }
