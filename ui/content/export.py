"""Export area content builder."""

from .. import theme as T
from ..widget_base import VStack
from ..widgets import Button, Label


def build_export(context):
    """Build the export widget tree."""
    obj = context.active_object
    if not obj or obj.type != 'ARMATURE':
        return VStack([
            Label("Select an armature", size=T.FONT_SIZE_SMALL,
                  color=T.TEXT_SECONDARY),
        ])

    children = []
    children.append(Label(f"Armature: {obj.name}", size=T.FONT_SIZE_SMALL,
                          color=T.TEXT_SECONDARY))

    child_meshes = [c for c in obj.children if c.type == 'MESH']
    children.append(Label(f"Child meshes: {len(child_meshes)}",
                          size=T.FONT_SIZE_SMALL, color=T.TEXT_SECONDARY))

    children.append(Button("Scale Rig", action_id="scale_rig"))
    children.append(Button("Export to UE", action_id="export_to_ue",
                           style=Button.STYLE_PRIMARY))

    return VStack(children, gap=T.ITEM_GAP, padding=(0, 0, 0, 0))
