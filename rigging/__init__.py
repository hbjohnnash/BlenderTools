"""Modular rigging subsystem."""

from . import operators
from . import panels
from . import scanner
from . import viewport_overlay
from . import center_of_mass
from . import shapes


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
