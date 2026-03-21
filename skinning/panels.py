"""Skinning UI panels."""

import bpy

from ..core.constants import PANEL_CATEGORY


class BT_PT_SkinningMain(bpy.types.Panel):
    bl_label = "Skinning"
    bl_idname = "BT_PT_SkinningMain"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = PANEL_CATEGORY
    bl_order = 2
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return getattr(context.window_manager, 'bt_show_skinning', True)

    def draw_header(self, context):
        self.layout.label(text="", icon='MOD_VERTEX_WEIGHT')

    def draw(self, context):
        layout = self.layout

        has_mesh = any(o.type == 'MESH' for o in context.selected_objects)
        has_arm = any(o.type == 'ARMATURE' for o in context.selected_objects)

        if not (has_mesh and has_arm):
            layout.label(text="Select mesh + armature", icon='INFO')
            return

        # Weighting
        box = layout.box()
        box.label(text="Weighting", icon='MOD_VERTEX_WEIGHT')
        box.separator(factor=0.3)
        col = box.column(align=True)
        col.operator("bt.auto_weight", icon='BONE_DATA')
        col.operator("bt.rigid_bind", icon='RIGID_BODY')

        # Cleanup
        box = layout.box()
        box.label(text="Cleanup", icon='BRUSH_DATA')
        box.separator(factor=0.3)
        col = box.column(align=True)
        col.operator("bt.weight_cleanup", icon='BRUSH_DATA')
        col.operator("bt.merge_vertex_groups", icon='AUTOMERGE_ON')
        col.operator("bt.mirror_vertex_groups", icon='MOD_MIRROR')


classes = (
    BT_PT_SkinningMain,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        if hasattr(cls, 'bl_rna'):
            bpy.utils.unregister_class(cls)
