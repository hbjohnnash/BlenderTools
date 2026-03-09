"""Addon preferences — bridge port, defaults."""

import bpy

from .constants import BRIDGE_PORT


class BlenderToolsPreferences(bpy.types.AddonPreferences):
    bl_idname = "BlenderTools"

    bridge_port: bpy.props.IntProperty(
        name="Bridge Port",
        description="HTTP server port for LLM bridge",
        default=BRIDGE_PORT,
        min=1024,
        max=65535,
    )

    bridge_autostart: bpy.props.BoolProperty(
        name="Auto-Start Bridge",
        description="Automatically start the HTTP bridge on addon load",
        default=False,
    )

    seam_angle_default: bpy.props.FloatProperty(
        name="Default Seam Angle",
        description="Default angle threshold for seam-by-angle",
        default=30.0,
        min=0.0,
        max=180.0,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "bridge_port")
        layout.prop(self, "bridge_autostart")
        layout.separator()
        layout.prop(self, "seam_angle_default")


classes = (BlenderToolsPreferences,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
