"""Modular rigging subsystem."""

from . import center_of_mass, operators, panels, scanner, shapes, viewport_overlay


def register():
    operators.register()
    viewport_overlay.register()
    shapes.register()
    panels.register()
    center_of_mass.register()
    scanner.register()


def unregister():
    scanner.unregister()
    center_of_mass.unregister()
    panels.unregister()
    shapes.unregister()
    viewport_overlay.unregister()
    operators.unregister()
