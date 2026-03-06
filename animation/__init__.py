"""Animation generators subsystem."""

from . import operators
from . import panels
from . import root_motion


def register():
    operators.register()
    panels.register()
    root_motion.register()


def unregister():
    root_motion.unregister()
    panels.unregister()
    operators.unregister()
