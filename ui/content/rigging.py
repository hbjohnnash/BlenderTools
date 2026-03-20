"""Rigging area content builder (modules, generation, control shapes)."""

from .. import theme as T
from ..widget_base import HStack, VStack
from ..widgets import Button, Label, SubsectionTitle


def build_rigging(context):
    """Build the rigging widget tree."""
    obj = context.active_object
    if not obj or obj.type != 'ARMATURE':
        return VStack([
            Label("Select an armature", size=T.FONT_SIZE_SMALL,
                  color=T.TEXT_SECONDARY),
        ])

    children = []
    children.append(Label(f"Armature: {obj.name}", size=T.FONT_SIZE_SMALL,
                          color=T.TEXT_SECONDARY))

    # ── Modules ──
    children.append(SubsectionTitle("Modules", "rig_modules", [
        VStack([
            HStack([
                Button("Add Module", action_id="add_rig_module", flex=1),
                Button("Remove Module", action_id="remove_rig_module", flex=1),
            ], gap=4, padding=(0, 0, 0, 0)),
        ], gap=T.ITEM_GAP, padding=(0, 0, 0, 0)),
    ]))

    # ── Generation ──
    children.append(SubsectionTitle("Generation", "rig_generation", [
        VStack([
            Button("Generate Rig", action_id="generate_rig",
                   style=Button.STYLE_PRIMARY),
            HStack([
                Button("Load Config", action_id="load_rig_config", flex=1),
                Button("Save Config", action_id="save_rig_config", flex=1),
            ], gap=4, padding=(0, 0, 0, 0)),
            Button("Clear Rig", action_id="clear_rig",
                   style=Button.STYLE_DANGER),
        ], gap=T.ITEM_GAP, padding=(0, 0, 0, 0)),
    ]))

    # ── Control Shapes (pose mode only) ──
    if obj.mode == 'POSE':
        children.append(SubsectionTitle("Control Shapes", "ctrl_shapes", [
            VStack([
                Button("Assign Shape", action_id="assign_bone_shape"),
                Button("Resize Controls", action_id="resize_ctrl_bones"),
                HStack([
                    Button("Clear Shapes", action_id="clear_bone_shapes",
                           flex=1),
                    Button("Add to Library", action_id="add_custom_shape",
                           flex=1),
                ], gap=4, padding=(0, 0, 0, 0)),
            ], gap=T.ITEM_GAP, padding=(0, 0, 0, 0)),
        ]))

    return VStack(children, gap=T.ITEM_GAP, padding=(0, 0, 0, 0))
