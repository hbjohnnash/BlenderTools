"""Animation UI panels."""

import bpy

from ..core.constants import PANEL_CATEGORY


def get_ai_model_readiness():
    """Check readiness of AI motion models.

    Returns:
        tuple[bool, bool, bool]: (lcm_ready, anytop_ready, sinmdm_ready)
    """
    from ..core.ml import model_manager
    from ..core.ml.dependencies import check_torch_available

    torch_ok = check_torch_available()
    lcm_ready = torch_ok and model_manager.is_model_installed("motionlcm")
    anytop_ready = torch_ok and model_manager.is_model_installed("anytop")
    sinmdm_ready = torch_ok and model_manager.is_model_installed("sinmdm")
    return lcm_ready, anytop_ready, sinmdm_ready


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

        # ── AI Motion ──
        is_armature = obj and obj.type == 'ARMATURE'
        box = layout.box()
        box.label(text="AI Motion", icon='OUTLINER_OB_LIGHT')
        box.separator(factor=0.3)

        wm = context.window_manager
        from ..core.ml import model_manager

        if wm.bt_ml_busy and wm.bt_ml_status:
            box.label(text=wm.bt_ml_status, icon='SORTTIME')
            col = box.column(align=True)
            col.scale_y = 0.5
            col.prop(wm, "bt_ml_progress", text="", slider=True)
        else:
            lcm_ready, anytop_ready, sinmdm_ready = get_ai_model_readiness()

            if anytop_ready or sinmdm_ready:
                # SMPL Reference toggle (may fail if numpy not yet installed)
                try:
                    from ..animation.ml.retarget_preview import (
                        get_smpl_preview,
                        is_link_active,
                    )
                    has_preview = get_smpl_preview() is not None
                except Exception:
                    has_preview = False
                    def is_link_active(): return False
                row = box.row(align=True)
                row.operator(
                    "bt.retarget_preview",
                    text="Hide SMPL Reference" if has_preview
                         else "Show SMPL Reference",
                    icon='ARMATURE_DATA',
                    depress=has_preview,
                )
                if has_preview:
                    linked = is_link_active()
                    row.operator(
                        "bt.link_smpl_preview",
                        text="Unlink" if linked else "Link",
                        icon='LINKED' if linked else 'UNLINKED',
                        depress=linked,
                    )

                # Text-to-Motion (auto-selects model)
                if lcm_ready or anytop_ready:
                    sub = box.box()
                    models = []
                    if lcm_ready:
                        models.append("MotionLCM")
                    if anytop_ready:
                        models.append("AnyTop")
                    sub.label(
                        text=f"Text-to-Motion ({' + '.join(models)})",
                        icon='CHECKMARK',
                    )
                    col = sub.column(align=True)
                    col.operator("bt.ai_generate_motion", icon='PLAY')
                    col.operator(
                        "bt.debug_retarget_frame", icon='VIEWZOOM',
                    )

                # SinMDM — Style & In-Between
                if sinmdm_ready:
                    sub = box.box()
                    sub.label(text="Style & In-Between (SinMDM)", icon='CHECKMARK')
                    col = sub.column(align=True)
                    col.operator("bt.ai_style_transfer", icon='BRUSHES_ALL')
                    col.operator("bt.ai_inbetween", icon='IPO_BEZIER')

                # Retarget to FK (visible when wrap rig exists + action)
                from ..animation.retarget import has_wrap_rig
                if (is_armature and has_wrap_rig(obj)
                        and obj.animation_data
                        and obj.animation_data.action):
                    sub = box.box()
                    sub.label(text="Retarget to FK", icon='CON_ARMATURE')
                    col = sub.column(align=True)
                    op = col.operator(
                        "bt.retarget_action_to_fk",
                        text="Active Action → FK",
                        icon='ACTION',
                    )
                    op.all_actions = False
                    op = col.operator(
                        "bt.retarget_action_to_fk",
                        text="All Actions → FK",
                        icon='NLA',
                    )
                    op.all_actions = True

                # Remove button
                total_mb = (model_manager.get_cache_size_mb("anytop")
                            + model_manager.get_cache_size_mb("sinmdm"))
                row = box.row(align=True)
                row.operator(
                    "bt.remove_anim_ai",
                    text=f"Remove Models ({total_mb:.0f} MB)",
                    icon='TRASH',
                )
            else:
                box.operator("bt.init_anim_ai", icon='IMPORT')
                if not is_armature:
                    box.label(text="Select an armature to use AI motion", icon='INFO')


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


classes = (
    BT_PT_AnimationMain,
    BT_PT_TrajectorySettings,
    BT_PT_OnionSkinSettings,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
