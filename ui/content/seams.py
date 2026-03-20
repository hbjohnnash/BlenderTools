"""Seams area content builder."""

from .. import theme as T
from ..widget_base import VStack
from ..widgets import Button, Label, SubsectionTitle


def build_seams(context):
    """Build the seams widget tree."""
    obj = context.active_object
    if not obj or obj.type != 'MESH':
        return VStack([
            Label("Select a mesh object", size=T.FONT_SIZE_SMALL,
                  color=T.TEXT_SECONDARY),
        ])

    children = []
    children.append(Label(f"Mesh: {obj.name}", size=T.FONT_SIZE_SMALL,
                          color=T.TEXT_SECONDARY))

    # ── Methods ──
    children.append(SubsectionTitle("Methods", "seam_methods", [
        VStack([
            Button("Seam by Angle", action_id="seam_by_angle"),
            Button("Seam by Material", action_id="seam_by_material"),
            Button("Seam by Hard Edge", action_id="seam_by_hard_edge"),
            Button("Island Aware", action_id="seam_island_aware"),
            Button("Projection", action_id="seam_projection"),
        ], gap=T.ITEM_GAP, padding=(0, 0, 0, 0)),
    ]))

    # ── Presets ──
    children.append(SubsectionTitle("Presets", "seam_presets", [
        VStack([
            Button("Apply Preset", action_id="seam_preset"),
            Button("Clear Seams", action_id="clear_seams",
                   style=Button.STYLE_DANGER),
        ], gap=T.ITEM_GAP, padding=(0, 0, 0, 0)),
    ]))

    return VStack(children, gap=T.ITEM_GAP, padding=(0, 0, 0, 0))
