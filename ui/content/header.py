"""Header area: subsystem toggles + overlay buttons with inline settings."""

from .. import panel_state as state
from .. import theme as T
from ..widget_base import HStack, VStack
from ..widgets import (
    Button,
    Collapsible,
    IconButton,
    Label,
    Slider,
    SubsectionTitle,
    Toggle,
)

# Subsystem definitions: (prop_suffix, icon_char, tooltip)
_SUBSYSTEMS = [
    ("seams", "\u25a6", "Seams"),
    ("rigging", "\u2699", "Rigging"),
    ("skinning", "\u25c6", "Skinning"),
    ("animation", "\u25b6", "Animation"),
    ("bridge", "\u2601", "LLM Bridge"),
    ("export", "\u21e7", "Export"),
]


def build_header(context):
    """Build the header widget tree."""
    obj = context.active_object
    is_armature = obj and obj.type == 'ARMATURE'

    children = []

    # ── Subsystem icon row ──
    icons = []
    for name, icon_char, label in _SUBSYSTEMS:
        is_on = name not in state.hidden_sections
        icons.append(IconButton(
            icon_char, active=is_on,
            action_id=f"toggle_sub_{name}",
            tooltip=label,
        ))
    children.append(HStack(icons, gap=4, padding=(0, 0, 0, 0)))

    # Show/Hide All
    children.append(HStack([
        Button("Show All", action_id="show_all", flex=1),
        Button("Hide All", action_id="hide_all", flex=1),
    ], gap=4, padding=(0, 0, 0, 0)))

    # ── Overlays (only when armature is active) ──
    if is_armature:
        overlay_children = []

        # Module overlay (not in pose mode)
        if obj.mode != 'POSE':
            try:
                from ...rigging.viewport_overlay import _active as mod_active
            except Exception:
                mod_active = False
            overlay_children.append(Button(
                "Module Overlay", active=mod_active,
                icon_text="\u25ce", action_id="toggle_module_overlay",
            ))

        # FK/IK overlay
        sd = getattr(obj, 'bt_scan', None)
        if sd and sd.has_wrap_rig:
            try:
                from ...rigging.scanner.ik_overlay import _active as ik_active
            except Exception:
                ik_active = False
            overlay_children.append(Button(
                "FK/IK Overlay", active=ik_active,
                icon_text="\u25cf", action_id="toggle_ik_overlay",
            ))

        # Center of Mass + gear
        try:
            from ...rigging.center_of_mass import _active as com_active
        except Exception:
            com_active = False
        overlay_children.append(HStack([
            Button("Center of Mass", active=com_active,
                   icon_text="\u2295", action_id="toggle_com", flex=1),
            IconButton("\u2699", action_id="gear_com"),
        ], gap=4, padding=(0, 0, 0, 0)))

        # CoM collapsible settings
        com_expanded = "com" in state.expanded_gears
        com_children = [
            Button("Recalculate Masses", action_id="recalc_com_masses"),
            Slider("BoS Threshold",
                   value=getattr(obj, 'bt_bos_threshold', 0.1),
                   min_val=0.0, max_val=1.0, step=0.01,
                   action_id="slider_bos_threshold"),
        ]
        com_settings = Collapsible("CoM Settings", com_children,
                                   expanded=com_expanded)
        overlay_children.append(com_settings)

        # Trajectory + gear (pose mode)
        if obj.mode == 'POSE':
            try:
                from ...animation.trajectory import _active as traj_active
            except Exception:
                traj_active = False
            overlay_children.append(HStack([
                Button("Trajectory", active=traj_active,
                       icon_text="\u2026", action_id="toggle_trajectory", flex=1),
                IconButton("\u2699", action_id="gear_traj"),
            ], gap=4, padding=(0, 0, 0, 0)))

            traj_expanded = "traj" in state.expanded_gears
            traj_settings = Collapsible("Trajectory Settings", [
                Label("Select bones to see trajectory", size=T.FONT_SIZE_SMALL,
                      color=T.TEXT_SECONDARY),
            ], expanded=traj_expanded)
            overlay_children.append(traj_settings)

            # Onion Skin + gear
            try:
                from ...animation.onion_skin import _active as onion_active
            except Exception:
                onion_active = False

            onion_icon = "\u25c9" if onion_active else "\u25cb"
            overlay_children.append(HStack([
                Button("Onion Skin", active=onion_active,
                       icon_text=onion_icon, action_id="toggle_onion", flex=1),
                IconButton("\u2699", action_id="gear_onion"),
            ], gap=4, padding=(0, 0, 0, 0)))

            onion_expanded = "onion" in state.expanded_gears
            scene = context.scene
            onion_settings = Collapsible("Onion Skin Settings", [
                Toggle("Keyframes Only",
                       on=getattr(scene, 'bt_onion_use_keyframes', False),
                       action_id="slider_onion_keyframes"),
                Slider("Before",
                       value=getattr(scene, 'bt_onion_before', 3),
                       min_val=1, max_val=10, step=1,
                       action_id="slider_onion_before"),
                Slider("After",
                       value=getattr(scene, 'bt_onion_after', 3),
                       min_val=1, max_val=10, step=1,
                       action_id="slider_onion_after"),
                Slider("Opacity",
                       value=getattr(scene, 'bt_onion_opacity', 0.25),
                       min_val=0.05, max_val=1.0, step=0.05,
                       action_id="slider_onion_opacity"),
                Slider("Detail",
                       value=getattr(scene, 'bt_onion_proxy_ratio', 0.25),
                       min_val=0.05, max_val=1.0, step=0.05,
                       action_id="slider_onion_detail"),
                Button("Refresh", action_id="onion_refresh"),
            ], expanded=onion_expanded)
            overlay_children.append(onion_settings)

        children.append(SubsectionTitle(
            "Overlays", "overlays",
            [VStack(overlay_children, gap=T.ITEM_GAP, padding=(0, 0, 0, 0))],
        ))

    return VStack(children, gap=T.ITEM_GAP, padding=(0, 0, 0, 0))
