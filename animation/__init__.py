"""Animation generators subsystem."""

from . import (
    onion_skin,
    operators,
    panels,
    pose_clipboard,
    root_motion,
    smart_keyframe,
    trajectory,
)


def register():
    operators.register()
    panels.register()
    root_motion.register()
    trajectory.register()
    onion_skin.register()
    smart_keyframe.register()
    pose_clipboard.register()


def unregister():
    pose_clipboard.unregister()
    smart_keyframe.unregister()
    onion_skin.unregister()
    trajectory.unregister()
    root_motion.unregister()
    panels.unregister()
    operators.unregister()
