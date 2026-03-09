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

        # AI Seams
        box = layout.box()
        box.label(text="AI Seams", icon='OUTLINER_OB_LIGHT')
        box.separator(factor=0.3)

        wm = context.window_manager
        from ..core.ml import model_manager

        if wm.bt_ml_busy and wm.bt_ml_status:
            box.label(text=wm.bt_ml_status, icon='SORTTIME')
            col = box.column(align=True)
            col.scale_y = 0.5
            col.prop(wm, "bt_ml_progress", text="", slider=True)
        elif model_manager.is_model_installed("meshcnn"):
            col = box.column(align=True)
            col.label(text="MeshCNN: Ready", icon='CHECKMARK')
            col.operator("bt.seam_neural", icon='OUTLINER_OB_LIGHT')
            row = col.row(align=True)
            size = model_manager.get_cache_size_mb("meshcnn")
            row.operator(
                "bt.remove_seam_ai",
                text=f"Remove ({size:.0f} MB)",
                icon='TRASH',
            )
        else:
            box.operator("bt.init_seam_ai", icon='IMPORT')


classes = (
    BT_PT_SeamsMain,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
