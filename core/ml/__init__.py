"""Core ML infrastructure — model management, dependencies, adapter base."""

import bpy


def register():
    bpy.types.WindowManager.bt_ml_busy = bpy.props.BoolProperty(default=False)
    bpy.types.WindowManager.bt_ml_progress = bpy.props.FloatProperty(
        default=0.0, min=0.0, max=1.0,
    )
    bpy.types.WindowManager.bt_ml_status = bpy.props.StringProperty(default="")


def unregister():
    del bpy.types.WindowManager.bt_ml_status
    del bpy.types.WindowManager.bt_ml_progress
    del bpy.types.WindowManager.bt_ml_busy
