"""Animation area content builder."""

from .. import theme as T
from ..widget_base import HStack, VStack
from ..widgets import Button, Label, SubsectionTitle, TextField, Toggle


def build_animation(context):
    """Build the animation widget tree."""
    obj = context.active_object
    if not obj:
        return VStack([])

    children = []

    # ── Pose Clipboard (only in pose mode with wrap rig) ──
    if obj.type == 'ARMATURE' and context.mode == 'POSE':
        sd = getattr(obj, 'bt_scan', None)
        if sd and sd.has_wrap_rig:
            center_bone = getattr(context.scene, 'bt_flip_center_bone', '')
            children.append(SubsectionTitle("Pose Clipboard", "pose_clipboard", [
                VStack([
                    Button("Copy Pose", action_id="copy_pose"),
                    HStack([
                        Button("Paste", action_id="paste_pose", flex=1),
                        Button("Paste Flipped", action_id="paste_pose_flipped",
                               flex=1),
                    ], gap=4, padding=(0, 0, 0, 0)),
                    Label("Center Bone:",
                          size=T.FONT_SIZE_SMALL, color=T.TEXT_LABEL),
                    TextField(text=center_bone, placeholder="e.g. root or hips",
                              action_id="tf_flip_center_bone"),
                ], gap=T.ITEM_GAP, padding=(0, 0, 0, 0)),
            ]))

    # ── Mechanical ──
    children.append(SubsectionTitle("Mechanical", "mechanical", [
        Button("Mechanical Anim", action_id="mechanical_anim"),
    ]))

    # ── Path & Camera ──
    children.append(SubsectionTitle("Path & Camera", "pathcam", [
        VStack([
            Button("Follow Path", action_id="follow_path"),
            Button("Orbit Camera", action_id="orbit_camera"),
            Button("Camera Shake", action_id="camera_shake"),
        ], gap=T.ITEM_GAP, padding=(0, 0, 0, 0)),
    ]))

    # ── Cycle & NLA ──
    children.append(SubsectionTitle("Cycle & NLA", "cyclenla", [
        VStack([
            Button("Match Cycle", action_id="match_cycle"),
            Button("Push to NLA", action_id="push_to_nla"),
        ], gap=T.ITEM_GAP, padding=(0, 0, 0, 0)),
    ]))

    # ── Retarget (only with wrap rig + action) ──
    if obj.type == 'ARMATURE':
        sd = getattr(obj, 'bt_scan', None)
        has_action = (obj.animation_data and obj.animation_data.action)
        if sd and sd.has_wrap_rig and has_action:
            children.append(SubsectionTitle("Retarget", "retarget", [
                VStack([
                    Button("Retarget Active", action_id="retarget_active"),
                    Button("Retarget All", action_id="retarget_all"),
                ], gap=T.ITEM_GAP, padding=(0, 0, 0, 0)),
            ]))

        # ── Root Motion ──
        rm = getattr(obj, 'bt_root_motion', None)
        if rm is not None:
            children.append(SubsectionTitle("Root Motion", "root_motion",
                                            [_build_root_motion(obj, rm)]))

    return VStack(children, gap=T.ITEM_GAP, padding=(0, 0, 0, 0))


def _build_root_motion(obj, rm):
    """Build root motion content."""
    children = []

    if rm.is_setup:
        # Active phase
        children.append(Label("Root motion is active.",
                              size=T.FONT_SIZE_SMALL, color=T.TEXT_PRIMARY))
        children.append(Label("Edit root curves in Graph Editor.",
                              size=T.FONT_SIZE_SMALL, color=T.TEXT_SECONDARY))
        if rm.root_bone:
            children.append(Label(f"Root: {rm.root_bone}",
                                  size=T.FONT_SIZE_SMALL,
                                  color=T.TEXT_SECONDARY))
        children.append(Button("Finalize", action_id="rm_finalize",
                               style=Button.STYLE_PRIMARY))
        children.append(Button("Cancel", action_id="rm_cancel",
                               style=Button.STYLE_DANGER))
    else:
        # Config phase
        if rm.source_bone:
            children.append(Label(f"Source: {rm.source_bone}",
                                  size=T.FONT_SIZE_SMALL,
                                  color=T.TEXT_SECONDARY))
        else:
            children.append(Label("Source: (not set)",
                                  size=T.FONT_SIZE_SMALL,
                                  color=T.TEXT_LABEL))
        if rm.root_bone:
            children.append(Label(f"Root: {rm.root_bone}",
                                  size=T.FONT_SIZE_SMALL,
                                  color=T.TEXT_SECONDARY))
        else:
            children.append(Label("Root: (will create)",
                                  size=T.FONT_SIZE_SMALL,
                                  color=T.TEXT_LABEL))

        # Pinned controllers
        pin_count = len(rm.pinned_bones) if hasattr(rm, 'pinned_bones') else 0
        children.append(Label(f"Pinned: {pin_count} bones",
                              size=T.FONT_SIZE_SMALL, color=T.TEXT_SECONDARY))
        children.append(HStack([
            Button("Add Selected", action_id="rm_add_selected", flex=1),
            Button("Auto Detect", action_id="rm_auto_detect", flex=1),
        ], gap=4, padding=(0, 0, 0, 0)))

        # Options
        children.append(HStack([
            Toggle("XY",
                   on=getattr(rm, 'extract_xy', True),
                   action_id="rm_extract_xy"),
            Toggle("Z Rot",
                   on=getattr(rm, 'extract_z_rot', True),
                   action_id="rm_extract_z_rot"),
        ], gap=8, padding=(0, 0, 0, 0)))

        children.append(Button("Setup Root Motion", action_id="rm_setup",
                               style=Button.STYLE_PRIMARY))

    return VStack(children, gap=T.ITEM_GAP, padding=(0, 0, 0, 0))
