"""Export subsystem UI panels."""

import bpy
from ..core.constants import PANEL_CATEGORY


class BT_PT_ExportMain(bpy.types.Panel):
    bl_label = "Export"
    bl_idname = "BT_PT_ExportMain"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = PANEL_CATEGORY
    bl_order = 5
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return getattr(context.window_manager, 'bt_show_export', True)

    def draw_header(self, context):
        self.layout.label(text="", icon='EXPORT')

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        if obj is None or obj.type != 'ARMATURE':
            layout.label(text="Select an armature", icon='INFO')
            return

        layout.label(text=f"Armature: {obj.name}", icon='ARMATURE_DATA')
        child_meshes = [c for c in obj.children if c.type == 'MESH']
        layout.label(text=f"Child meshes: {len(child_meshes)}")

        col = layout.column(align=True)
        col.operator("bt.scale_rig", icon='FULLSCREEN_ENTER')

        layout.separator()

        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator("bt.export_to_ue", icon='EXPORT')


classes = (
    BT_PT_ExportMain,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
