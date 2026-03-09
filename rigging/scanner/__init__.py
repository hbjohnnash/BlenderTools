"""Skeleton scanner — wrap control rig around existing bones."""

from . import bone_naming, ik_overlay, operators, panels, properties


def register():
    properties.register()
    bone_naming.register()
    operators.register()
    ik_overlay.register()
    panels.register()


def unregister():
    panels.unregister()
    ik_overlay.unregister()
    operators.unregister()
    bone_naming.unregister()
    properties.unregister()
