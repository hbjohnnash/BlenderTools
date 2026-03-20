"""BlenderTools viewport UI framework — registration."""

import bpy

from .panel_operator import BT_OT_ViewportPanel

# Old sidebar panel classes to unregister (replaced by viewport panel)
_OLD_PANELS = [
    "BT_PT_Header",
    "BT_PT_SeamsMain",
    "BT_PT_RiggingMain",
    "BT_PT_SkeletonScanner",
    "BT_PT_CenterOfMass",
    "BT_PT_SkinningMain",
    "BT_PT_AnimationMain",
    "BT_PT_TrajectorySettings",
    "BT_PT_OnionSkinSettings",
    "BT_PT_RootMotion",
    "BT_PT_BridgeMain",
    "BT_PT_ExportMain",
]


def _draw_header_button(self, context):
    """Append a 'BlenderTools' button to the 3D viewport header."""
    from . import panel_state as state
    self.layout.separator()
    self.layout.operator(
        "bt.viewport_panel",
        text="BlenderTools",
        icon='TOOL_SETTINGS',
        depress=state.visible,
    )


def _unregister_old_panels():
    """Remove old sidebar panels — they are replaced by the viewport panel."""
    for name in _OLD_PANELS:
        cls = getattr(bpy.types, name, None)
        if cls is not None:
            try:
                bpy.utils.unregister_class(cls)
            except RuntimeError:
                pass


def register():
    bpy.utils.register_class(BT_OT_ViewportPanel)
    bpy.types.VIEW3D_HT_header.append(_draw_header_button)
    _unregister_old_panels()


def unregister():
    from .panel_operator import cleanup_panel
    cleanup_panel()
    bpy.types.VIEW3D_HT_header.remove(_draw_header_button)
    bpy.utils.unregister_class(BT_OT_ViewportPanel)
