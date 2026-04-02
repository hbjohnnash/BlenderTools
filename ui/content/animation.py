"""Animation area content builder."""

from ...core.utils import mirror_name
from .. import theme as T
from ..widget_base import HStack, VStack
from ..widgets import Button, Dropdown, Label, Slider, SubsectionTitle, Toggle


def _get_center_bone_options(armature_obj):
    """Return bone names that are center (non-L/R) candidates for flip pivot."""
    options = []
    for bone in armature_obj.data.bones:
        if mirror_name(bone.name) == bone.name:
            options.append(bone.name)
    return options


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
            bone_options = _get_center_bone_options(obj)
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
                    Dropdown(selected=center_bone, options=bone_options,
                             placeholder="Select center bone...",
                             action_id="dd_flip_center_bone"),
                ], gap=T.ITEM_GAP, padding=(0, 0, 0, 0)),
            ]))

    # ── Trajectory (pose mode + armature) ──
    if obj.type == 'ARMATURE' and context.mode == 'POSE':
        from ...animation.trajectory import _active as traj_active
        traj_label = "Disable Trajectory" if traj_active else "Trajectory"
        children.append(SubsectionTitle("Trajectory", "trajectory", [
            VStack([
                Button(traj_label, active=traj_active,
                       action_id="toggle_trajectory"),
                Label("Select bones and enable to view",
                      size=T.FONT_SIZE_SMALL, color=T.TEXT_SECONDARY),
                Label("Click + drag keyframe dots to edit",
                      size=T.FONT_SIZE_SMALL, color=T.TEXT_SECONDARY),
            ], gap=T.ITEM_GAP, padding=(0, 0, 0, 0)),
        ]))

    # ── Onion Skin (armature) ──
    if obj.type == 'ARMATURE':
        from ...animation.onion_skin import _active as onion_active
        scene = context.scene
        onion_label = "Disable Onion Skin" if onion_active else "Onion Skin"
        onion_widgets = [
            Button(onion_label, active=onion_active,
                   action_id="toggle_onion"),
            Toggle("Keyframes Only",
                   on=getattr(scene, 'bt_onion_use_keyframes', False),
                   action_id="slider_onion_keyframes"),
            Toggle("Selected Only",
                   on=getattr(scene, 'bt_onion_selected_keys', False),
                   action_id="slider_onion_selected"),
            Slider("Before", value=getattr(scene, 'bt_onion_before', 3),
                   min_val=1, max_val=10, step=1,
                   action_id="slider_onion_before"),
            Slider("After", value=getattr(scene, 'bt_onion_after', 3),
                   min_val=1, max_val=10, step=1,
                   action_id="slider_onion_after"),
            Slider("Opacity", value=getattr(scene, 'bt_onion_opacity', 0.3),
                   min_val=0.05, max_val=1.0, step=0.05,
                   action_id="slider_onion_opacity"),
            Slider("Ghost Detail",
                   value=getattr(scene, 'bt_onion_proxy_ratio', 0.5),
                   min_val=0.1, max_val=1.0, step=0.1,
                   action_id="slider_onion_detail"),
        ]
        if onion_active:
            onion_widgets.append(Button("Refresh",
                                        action_id="onion_refresh"))
        children.append(SubsectionTitle("Onion Skin", "onion_skin", [
            VStack(onion_widgets, gap=T.ITEM_GAP, padding=(0, 0, 0, 0)),
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


def _get_bone_options(obj):
    """Return all bone names for the armature."""
    if not obj or obj.type != 'ARMATURE' or not obj.data:
        return []
    return [bone.name for bone in obj.data.bones]


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
        bone_options = _get_bone_options(obj)

        # Source bone (COG/hips)
        children.append(Label("Locomotion Source (COG/hips):",
                              size=T.FONT_SIZE_SMALL, color=T.TEXT_LABEL))
        children.append(Dropdown(
            selected=rm.source_bone or '',
            options=bone_options,
            placeholder="Select source bone...",
            action_id="dd_rm_source_bone",
        ))

        # Root bone
        children.append(Label("Root bone:",
                              size=T.FONT_SIZE_SMALL, color=T.TEXT_LABEL))
        root_label = rm.root_bone if rm.root_bone else ''
        children.append(HStack([
            Dropdown(
                selected=root_label,
                options=bone_options,
                placeholder="(will create)",
                action_id="dd_rm_root_bone",
                flex=1,
            ),
        ], gap=4, padding=(0, 0, 0, 0)))

        # Pinned controllers
        children.append(Label("Pinned Controllers:",
                              size=T.FONT_SIZE_SMALL, color=T.TEXT_LABEL))
        pin_count = len(rm.pinned_bones) if hasattr(rm, 'pinned_bones') else 0
        if pin_count == 0:
            children.append(Label("None \u2014 use Auto Detect or Add Selected",
                                  size=T.FONT_SIZE_SMALL,
                                  color=T.TEXT_SECONDARY))
        else:
            pin_rows = []
            for i, item in enumerate(rm.pinned_bones):
                pin_rows.append(HStack([
                    Label(item.bone_name, size=T.FONT_SIZE_SMALL,
                          color=T.TEXT_PRIMARY, flex=1),
                    Button("\u2717", action_id=f"rm_remove_pin_{i}"),
                ], gap=4, padding=(2, 0, 2, 0)))
            children.append(VStack(pin_rows, gap=2, padding=(0, 0, 0, 0)))

        children.append(HStack([
            Button("Add Selected", action_id="rm_add_selected", flex=1),
            Button("Auto Detect", action_id="rm_auto_detect", flex=1),
        ], gap=4, padding=(0, 0, 0, 0)))

        # Options
        children.append(Label("Extract to Root:",
                              size=T.FONT_SIZE_SMALL, color=T.TEXT_LABEL))
        children.append(HStack([
            Toggle("XY",
                   on=getattr(rm, 'extract_xy', True),
                   action_id="rm_extract_xy"),
            Toggle("Z Rot",
                   on=getattr(rm, 'extract_z_rot', True),
                   action_id="rm_extract_z_rot"),
            Toggle("Z",
                   on=getattr(rm, 'extract_z', False),
                   action_id="rm_extract_z"),
        ], gap=8, padding=(0, 0, 0, 0)))

        # Analysis summary (shown after Auto Detect)
        analysis = getattr(rm, 'anim_analysis', '')
        if analysis:
            children.append(Label(analysis,
                                  size=T.FONT_SIZE_SMALL,
                                  color=T.TEXT_LABEL))

        children.append(Button("Setup Root Motion", action_id="rm_setup",
                               style=Button.STYLE_PRIMARY))

    return VStack(children, gap=T.ITEM_GAP, padding=(0, 0, 0, 0))
