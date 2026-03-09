"""Module registry with @register_module decorator."""

MODULE_REGISTRY = {}


def register_module(cls):
    """Decorator to register a rig module class."""
    MODULE_REGISTRY[cls.module_type] = cls
    return cls


def get_module_class(module_type):
    """Get a module class by type name."""
    return MODULE_REGISTRY.get(module_type)


def get_module_items(self=None, context=None):
    """EnumProperty callback listing available modules."""
    return [
        (key, cls.display_name, f"{cls.display_name} ({cls.category})")
        for key, cls in sorted(MODULE_REGISTRY.items())
    ]


# Import all modules to trigger registration
from . import (
    arm,
    custom_chain,
    eye,
    finger_chain,
    jaw,
    leg,
    neck_head,
    piston,
    spine,
    tail,
    tentacle,
    wheel,
    wing,
)
