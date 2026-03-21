"""Seam creation UI panels."""

import bpy

from ..core.constants import PANEL_CATEGORY


class BT_PT_SeamsMain(bpy.types.Panel):
    bl_label = "Seams"
    bl_idname = "BT_PT_SeamsMain"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = PANEL_CATEGORY
    bl_order = 0
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return getattr(context.window_manager, 'bt_show_seams', True)

    def draw_header(self, context):
        self.layout.label(text="", icon='MESH_GRID')

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        if obj is None or obj.type != 'MESH':
            layout.label(text="Select a mesh object", icon='INFO')
            return

        layout.label(text=f"Mesh: {obj.name}", icon='MESH_DATA')

        # Methods
        box = layout.box()
        box.label(text="Methods", icon='TOOL_SETTINGS')
        box.separator(factor=0.3)
        col = box.column(align=True)
        col.operator("bt.seam_by_angle", icon='DRIVER_ROTATIONAL_DIFFERENCE')
        col.operator("bt.seam_by_material", icon='MATERIAL')
        col.operator("bt.seam_by_hard_edge", icon='EDGESEL')
        col.operator("bt.seam_island_aware", icon='UV')
        col.operator("bt.seam_projection", icon='MOD_UVPROJECT')

        # Presets
        box = layout.box()
        box.label(text="Presets", icon='PRESET')
        box.separator(factor=0.3)
        col = box.column(align=True)
        col.operator("bt.seam_preset")
        col.operator("bt.clear_seams", icon='X')



classes = (
    BT_PT_SeamsMain,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        if hasattr(cls, 'bl_rna'):
            bpy.utils.unregister_class(cls)
