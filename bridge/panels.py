"""Bridge UI panels — Start/Stop button, status."""

import bpy

from ..core.constants import PANEL_CATEGORY


class BT_OT_StartBridge(bpy.types.Operator):
    bl_idname = "bt.start_bridge"
    bl_label = "Start Bridge"
    bl_description = "Start the LLM HTTP bridge server"

    def execute(self, context):
        from .server import start_server
        if start_server():
            self.report({'INFO'}, "Bridge server started")
        else:
            self.report({'WARNING'}, "Bridge server already running or port in use")
        return {'FINISHED'}


class BT_OT_StopBridge(bpy.types.Operator):
    bl_idname = "bt.stop_bridge"
    bl_label = "Stop Bridge"
    bl_description = "Stop the LLM HTTP bridge server"

    def execute(self, context):
        from .server import stop_server
        if stop_server():
            self.report({'INFO'}, "Bridge server stopped")
        else:
            self.report({'WARNING'}, "Bridge server was not running")
        return {'FINISHED'}


class BT_PT_BridgeMain(bpy.types.Panel):
    bl_label = "LLM Bridge"
    bl_idname = "BT_PT_BridgeMain"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = PANEL_CATEGORY
    bl_order = 4
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return getattr(context.window_manager, 'bt_show_bridge', True)

    def draw_header(self, context):
        self.layout.label(text="", icon='PLUGIN')

    def draw(self, context):
        layout = self.layout
        from .server import is_running

        if is_running():
            row = layout.row()
            row.label(text="Running", icon='CHECKMARK')
            try:
                prefs = context.preferences.addons["BlenderTools"].preferences
                port = prefs.bridge_port
            except (KeyError, AttributeError):
                from ..core.constants import BRIDGE_PORT
                port = BRIDGE_PORT
            row.label(text=f":{port}")
            layout.operator("bt.stop_bridge", icon='CANCEL')
        else:
            layout.label(text="Stopped", icon='X')
            layout.operator("bt.start_bridge", icon='PLAY')


classes = (
    BT_OT_StartBridge,
    BT_OT_StopBridge,
    BT_PT_BridgeMain,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        if hasattr(cls, 'bl_rna'):
            bpy.utils.unregister_class(cls)
