"""Animation generators subsystem."""

from . import operators
from . import panels
from . import root_motion
from . import trajectory
from . import onion_skin
from . import smart_keyframe


def register():
    operators.register()
    panels.register()
    root_motion.register()
    trajectory.register()
    onion_skin.register()
    smart_keyframe.register()


def unregister():
    smart_keyframe.unregister()
    onion_skin.unregister()
    trajectory.unregister()
    root_motion.unregister()
    panels.unregister()
    operators.unregister()
