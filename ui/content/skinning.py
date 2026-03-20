"""Skinning area content builder."""

from .. import theme as T
from ..widget_base import VStack
from ..widgets import Button, Label, SubsectionTitle


def build_skinning(context):
    """Build the skinning widget tree."""
    has_mesh = any(o.type == 'MESH' for o in context.selected_objects)
    has_arm = any(o.type == 'ARMATURE' for o in context.selected_objects)

    if not (has_mesh and has_arm):
        return VStack([
            Label("Select mesh + armature", size=T.FONT_SIZE_SMALL,
                  color=T.TEXT_SECONDARY),
        ])

    children = []

    # ── Weighting ──
    children.append(SubsectionTitle("Weighting", "skin_weighting", [
        VStack([
            Button("Auto Weight", action_id="auto_weight"),
            Button("Rigid Bind", action_id="rigid_bind"),
        ], gap=T.ITEM_GAP, padding=(0, 0, 0, 0)),
    ]))

    # ── Cleanup ──
    children.append(SubsectionTitle("Cleanup", "skin_cleanup", [
        VStack([
            Button("Weight Cleanup", action_id="weight_cleanup"),
            Button("Merge Groups", action_id="merge_vertex_groups"),
            Button("Mirror Groups", action_id="mirror_vertex_groups"),
        ], gap=T.ITEM_GAP, padding=(0, 0, 0, 0)),
    ]))

    return VStack(children, gap=T.ITEM_GAP, padding=(0, 0, 0, 0))
