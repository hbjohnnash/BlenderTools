"""Skeleton scanner — wrap control rig around existing bones."""

from . import properties
from . import bone_naming
from . import operators
from . import panels


def register():
    properties.register()
    bone_naming.register()
    operators.register()
    panels.register()


def unregister():
    panels.unregister()
    operators.unregister()
    bone_naming.unregister()
    properties.unregister()
