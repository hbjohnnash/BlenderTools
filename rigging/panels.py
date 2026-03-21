"""Rigging UI panels."""

import bpy

from ..core.constants import PANEL_CATEGORY
from .config_loader import config_from_armature


class BT_PT_RiggingMain(bpy.types.Panel):
    bl_label = "Rigging"
    bl_idname = "BT_PT_RiggingMain"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = PANEL_CATEGORY
    bl_order = 1
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return getattr(context.window_manager, 'bt_show_rigging', True)

    def draw_header(self, context):
        self.layout.label(text="", icon='ARMATURE_DATA')

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        if obj is None or obj.type != 'ARMATURE':
            layout.label(text="Select an armature", icon='INFO')
            return

        layout.label(text=f"Armature: {obj.name}", icon='ARMATURE_DATA')

        config = config_from_armature(obj)
        modules = config.get("modules", []) if config else []

        # ── Modules ──
        box = layout.box()
        row = box.row()
        row.label(text="Modules", icon='GROUP_BONE')
        row.label(text=str(len(modules)))
        box.separator(factor=0.3)

        col = box.column(align=True)
        col.operator("bt.add_rig_module", icon='ADD')
        col.operator("bt.remove_rig_module", icon='REMOVE')

        if modules:
            box.separator(factor=0.3)
            col = box.column(align=True)
            for i, mod in enumerate(modules):
                col.label(text=f"{i+1}. {mod.get('name', mod['type'])} ({mod.get('side', 'C')})")

        # ── Generation ──
        box = layout.box()
        box.label(text="Generation", icon='SYSTEM')
        box.separator(factor=0.3)

        col = box.column(align=True)
        col.scale_y = 1.3
        col.operator("bt.generate_rig", icon='PLAY')

        row = box.row(align=True)
        row.operator("bt.load_rig_config", icon='IMPORT')
        row.operator("bt.save_rig_config", icon='EXPORT')

        box.operator("bt.clear_rig", icon='TRASH')

        # ── Control Shapes ──
        if obj.mode == 'POSE':
            box = layout.box()
            box.label(text="Control Shapes", icon='MESH_CIRCLE')
            box.separator(factor=0.3)
            col = box.column(align=True)
            col.operator("bt.assign_bone_shape", icon='MESH_CIRCLE')
            col.operator("bt.resize_ctrl_bones", icon='FULLSCREEN_ENTER')
            row = box.row(align=True)
            row.operator("bt.clear_bone_shapes", icon='X')
            row.operator("bt.add_custom_shape", text="Add to Library", icon='ADD')


classes = (
    BT_PT_RiggingMain,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        if hasattr(cls, 'bl_rna'):
            bpy.utils.unregister_class(cls)
