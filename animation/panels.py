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

        # ── Mechanical ──
        box = layout.box()
        box.label(text="Mechanical", icon='SETTINGS')
        box.separator(factor=0.3)
        col = box.column(align=True)
        col.operator("bt.mechanical_anim", icon='SETTINGS')

        # ── Path & Camera ──
        box = layout.box()
        box.label(text="Path & Camera", icon='CURVE_PATH')
        box.separator(factor=0.3)
        col = box.column(align=True)
        col.operator("bt.follow_path", icon='CURVE_PATH')
        col.operator("bt.orbit_camera", icon='CAMERA_DATA')
        col.operator("bt.camera_shake", icon='RNDCURVE')

        # ── Cycle & NLA ──
        box = layout.box()
        box.label(text="Cycle & NLA", icon='NLA')
        box.separator(factor=0.3)
        col = box.column(align=True)
        col.operator("bt.match_cycle_keyframes", icon='FILE_REFRESH')
        col.operator("bt.push_to_nla", icon='NLA')

        # ── Retarget to FK ──
        is_armature = obj and obj.type == 'ARMATURE'
        if is_armature:
            from .retarget import has_wrap_rig
            if (has_wrap_rig(obj)
                    and obj.animation_data
                    and obj.animation_data.action):
                box = layout.box()
                box.label(text="Retarget to FK", icon='CON_ARMATURE')
                col = box.column(align=True)
                op = col.operator(
                    "bt.retarget_action_to_fk",
                    text="Active Action \u2192 FK",
                    icon='ACTION',
                )
                op.all_actions = False
                op = col.operator(
                    "bt.retarget_action_to_fk",
                    text="All Actions \u2192 FK",
                    icon='NLA',
                )
                op.all_actions = True


class BT_PT_TrajectorySettings(bpy.types.Panel):
    bl_label = "Trajectory"
    bl_idname = "BT_PT_TrajectorySettings"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = PANEL_CATEGORY
    bl_parent_id = "BT_PT_AnimationMain"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'ARMATURE' and context.mode == 'POSE'

    def draw_header(self, context):
        self.layout.label(text="", icon='ANIM_DATA')

    def draw(self, context):
        layout = self.layout
        from .trajectory import _active as traj_active

        row = layout.row()
        row.operator(
            "bt.trajectory",
            text="Trajectory" if not traj_active else "Disable Trajectory",
            icon='ANIM_DATA',
            depress=traj_active,
        )

        col = layout.column()
        col.label(text="Select bones and enable to view", icon='INFO')
        col.label(text="Click + drag keyframe dots to edit")


class BT_PT_OnionSkinSettings(bpy.types.Panel):
    bl_label = "Onion Skin"
    bl_idname = "BT_PT_OnionSkinSettings"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = PANEL_CATEGORY
    bl_parent_id = "BT_PT_AnimationMain"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'ARMATURE'

    def draw_header(self, context):
        from .onion_skin import _active as onion_active
        self.layout.label(text="",
                          icon='ONIONSKIN_ON' if onion_active else 'ONIONSKIN_OFF')

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        from .onion_skin import _active as onion_active

        row = layout.row()
        row.operator(
            "bt.onion_skin",
            text="Onion Skin" if not onion_active else "Disable Onion Skin",
            icon='ONIONSKIN_ON' if onion_active else 'ONIONSKIN_OFF',
            depress=onion_active,
        )

        box = layout.box()
        box.label(text="Settings", icon='PREFERENCES')
        box.separator(factor=0.3)
        col = box.column(align=True)
        col.prop(scene, "bt_onion_use_keyframes", text="Keyframes Only")
        col.prop(scene, "bt_onion_before", text="Before")
        col.prop(scene, "bt_onion_after", text="After")
        if not scene.bt_onion_use_keyframes:
            col.prop(scene, "bt_onion_step", text="Step")
        col.prop(scene, "bt_onion_opacity", text="Opacity", slider=True)
        col.prop(scene, "bt_onion_proxy_ratio", text="Ghost Detail", slider=True)
        if onion_active:
            layout.separator(factor=0.3)
            layout.operator("bt.onion_skin_refresh", icon='FILE_REFRESH')


class BT_PT_PoseClipboard(bpy.types.Panel):
    bl_label = "Pose Clipboard"
    bl_idname = "BT_PT_PoseClipboard"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = PANEL_CATEGORY
    bl_parent_id = "BT_PT_AnimationMain"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj and obj.type == 'ARMATURE'
                and context.mode == 'POSE')

    def draw_header(self, context):
        self.layout.label(text="", icon='PASTEDOWN')

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        obj = context.active_object

        col = layout.column(align=True)
        col.operator("bt.copy_pose", icon='COPYDOWN')

        from .pose_clipboard import _pose_buffer
        if _pose_buffer:
            col.operator("bt.paste_pose", icon='PASTEDOWN')

            box = layout.box()
            box.label(text="Paste Flipped", icon='MOD_MIRROR')
            box.separator(factor=0.3)
            inner = box.column(align=True)
            inner.label(text="Center Bone:")
            inner.prop_search(scene, "bt_flip_center_bone",
                              obj.data, "bones", text="")
            inner.separator(factor=0.5)
            inner.operator("bt.paste_pose_flipped", icon='PASTEFLIPDOWN')


classes = (
    BT_PT_AnimationMain,
    BT_PT_TrajectorySettings,
    BT_PT_OnionSkinSettings,
    BT_PT_PoseClipboard,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        if hasattr(cls, 'bl_rna'):
            bpy.utils.unregister_class(cls)
