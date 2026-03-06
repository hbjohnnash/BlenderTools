"""Modular rigging subsystem."""

from . import operators
from . import panels
from . import scanner
from . import viewport_overlay


def register():
    operators.register()
    viewport_overlay.register()
    panels.register()
    scanner.register()


def unregister():
    scanner.unregister()
    panels.unregister()
    viewport_overlay.unregister()
    operators.unregister()
