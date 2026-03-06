"""Animation UI panels."""

import bpy
from ..core.constants import PANEL_CATEGORY


class BT_PT_AnimationMain(bpy.types.Panel):
    bl_label = "Animation"
    bl_idname = "BT_PT_AnimationMain"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = PANEL_CATEGORY
    bl_order = 3
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return getattr(context.window_manager, 'bt_show_animation', True)

    def draw_header(self, context):
        self.layout.label(text="", icon='ACTION')

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        if not obj:
            layout.label(text="Select an object", icon='INFO')
            return

        layout.label(text=f"Object: {obj.name}", icon='OBJECT_DATA')

        # Procedural
        box = layout.box()
        box.label(text="Procedural", icon='ANIM')
        col = box.column(align=True)
        col.operator("bt.generate_walk_cycle", icon='ANIM')
        col.operator("bt.generate_run_cycle", icon='ANIM')
        col.operator("bt.generate_idle", icon='ANIM')
        col.operator("bt.generate_breathing", icon='ANIM')
        col.separator()
        col.operator("bt.mechanical_anim", icon='SETTINGS')

        # Path & Camera
        box = layout.box()
        box.label(text="Path & Camera", icon='CURVE_PATH')
        col = box.column(align=True)
        col.operator("bt.follow_path", icon='CURVE_PATH')
        col.operator("bt.orbit_camera", icon='CAMERA_DATA')
        col.operator("bt.camera_shake", icon='RNDCURVE')

        # Cycle & NLA
        box = layout.box()
        box.label(text="Cycle & NLA", icon='NLA')
        col = box.column(align=True)
        col.operator("bt.match_cycle_keyframes", icon='FILE_REFRESH')
        col.operator("bt.push_to_nla", icon='NLA')


classes = (
    BT_PT_AnimationMain,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
