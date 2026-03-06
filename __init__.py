"""BlenderTools — Comprehensive seam, rigging, skinning, animation & LLM bridge toolkit."""

import bpy
from .core import preferences


# Subsystem imports — each has register()/unregister()
_subsystems = []

# Per-subsystem definitions: (prop_suffix, label, icon)
_SUBSYSTEM_DEFS = [
    ("seams", "Seams", 'MESH_GRID'),
    ("rigging", "Rigging", 'ARMATURE_DATA'),
    ("skinning", "Skinning", 'MOD_VERTEX_WEIGHT'),
    ("animation", "Animation", 'ACTION'),
    ("bridge", "Bridge", 'PLUGIN'),
    ("export", "Export", 'EXPORT'),
]


class BT_OT_ToggleSubsystem(bpy.types.Operator):
    bl_idname = "bt.toggle_subsystem"
    bl_label = "Toggle Subsystem"
    bl_description = "Show or hide a BlenderTools subsystem panel"

    subsystem: bpy.props.StringProperty()

    def execute(self, context):
        wm = context.window_manager
        prop = f"bt_show_{self.subsystem}"
        setattr(wm, prop, not getattr(wm, prop, True))
        return {'FINISHED'}


class BT_OT_SetAllPanels(bpy.types.Operator):
    bl_idname = "bt.set_all_panels"
    bl_label = "Set All Panels"
    bl_description = "Show or hide all BlenderTools panels"

    show: bpy.props.BoolProperty(default=True)

    def execute(self, context):
        wm = context.window_manager
        for name, _, _ in _SUBSYSTEM_DEFS:
            setattr(wm, f"bt_show_{name}", self.show)
        return {'FINISHED'}


class BT_PT_Header(bpy.types.Panel):
    bl_label = "BlenderTools"
    bl_idname = "BT_PT_Header"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "BlenderTools"
    bl_order = -1

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager

        # Per-subsystem toggle icons
        row = layout.row(align=True)
        row.scale_x = 1.15
        for name, label, icon in _SUBSYSTEM_DEFS:
            is_visible = getattr(wm, f"bt_show_{name}", True)
            op = row.operator(
                "bt.toggle_subsystem", text="",
                icon=icon, depress=is_visible,
            )
            op.subsystem = name

        # Show All / Hide All
        row = layout.row(align=True)
        op = row.operator("bt.set_all_panels", text="Show All", icon='HIDE_OFF')
        op.show = True
        op = row.operator("bt.set_all_panels", text="Hide All", icon='HIDE_ON')
        op.show = False


def _import_subsystems():
    global _subsystems
    from . import seams
    from . import rigging
    from . import skinning
    from . import animation
    from . import bridge
    from . import export

    _subsystems = [seams, rigging, skinning, animation, bridge, export]


def register():
    preferences.register()
    bpy.utils.register_class(BT_OT_ToggleSubsystem)
    bpy.utils.register_class(BT_OT_SetAllPanels)
    bpy.utils.register_class(BT_PT_Header)

    for name, _, _ in _SUBSYSTEM_DEFS:
        setattr(
            bpy.types.WindowManager,
            f"bt_show_{name}",
            bpy.props.BoolProperty(name=f"Show {name.title()}", default=True),
        )

    _import_subsystems()
    for sub in _subsystems:
        sub.register()


def unregister():
    for sub in reversed(_subsystems):
        sub.unregister()
    for name, _, _ in _SUBSYSTEM_DEFS:
        delattr(bpy.types.WindowManager, f"bt_show_{name}")
    bpy.utils.unregister_class(BT_PT_Header)
    bpy.utils.unregister_class(BT_OT_SetAllPanels)
    bpy.utils.unregister_class(BT_OT_ToggleSubsystem)
    preferences.unregister()
