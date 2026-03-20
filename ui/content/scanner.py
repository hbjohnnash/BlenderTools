"""Scanner area: tabbed layout (Chains / Bones / Skip) + actions."""

from .. import panel_state as state
from .. import theme as T
from ..widget_base import HStack, VStack
from ..widgets import (
    Button,
    Label,
    ScrollView,
    Section,
    SubsectionTitle,
    TabBar,
    TextField,
)


def build_scanner(context):
    """Build the scanner widget tree."""
    obj = context.active_object
    if not obj or obj.type != 'ARMATURE':
        return VStack([
            Label("Select an armature", size=T.FONT_SIZE_SMALL,
                  color=T.TEXT_SECONDARY),
        ])

    sd = obj.bt_scan
    children = []

    # ── Scan bar (always visible) ──
    children.append(HStack([
        Button("Name", icon_text="\u24b6", action_id="bone_naming", flex=1),
        Button("\u2693", action_id="auto_name_chain"),  # link icon
        Button("Scan", icon_text="\U0001f50d", action_id="scan_skeleton",
               style=Button.STYLE_PRIMARY, flex=1),
    ], gap=4, padding=(0, 0, 0, 0)))

    if not sd.is_scanned:
        return VStack(children, gap=T.ITEM_GAP, padding=(0, 0, 0, 0))

    # ── Results subsection ──
    results_content = VStack([
        Section("", [
            HStack([
                Label(f"Type: {sd.skeleton_type}", size=T.FONT_SIZE_SMALL,
                      color=T.TEXT_SECONDARY),
                Label(f"{sd.confidence:.0%}", size=T.FONT_SIZE_SMALL,
                      color=T.TEXT_SECONDARY),
            ], gap=8, padding=(0, 0, 0, 0)),
            Label(f"Chains: {len(sd.chains)}  |  Bones: {len(sd.bones)}",
                  size=T.FONT_SIZE_SMALL, color=T.TEXT_SECONDARY),
        ]),
    ], gap=T.ITEM_GAP, padding=(0, 0, 0, 0))
    children.append(SubsectionTitle("Results", "results", [results_content]))

    # ── Live FK/IK (when wrap rig is active) ──
    if sd.has_wrap_rig:
        active_chain = _find_active_chain(context, sd)
        if active_chain:
            fkik_content = VStack([
                _build_live_fkik(active_chain),
            ], gap=T.ITEM_GAP, padding=(0, 0, 0, 0))
            children.append(SubsectionTitle("Live FK/IK", "fkik",
                                            [fkik_content]))

    # ── Tabbed content (pre-rig config) ──
    if not sd.has_wrap_rig:
        tabs = TabBar(active_tab=state.active_tabs.get("scanner", 0))

        # Chains tab
        chains_content = _build_chains_tab(sd)
        tabs.add_tab("Chains", chains_content)

        # Bones tab
        bones_content = _build_bones_tab(sd)
        tabs.add_tab("Bones", bones_content)

        # Skip tab
        skip_content = _build_skip_tab(sd)
        tabs.add_tab("Skip", skip_content)

        config_content = VStack([tabs], gap=T.ITEM_GAP, padding=(0, 0, 0, 0))
        children.append(SubsectionTitle("Configuration", "config",
                                        [config_content]))

        # Forward axis (when LookAt chain exists)
        if any(ch.ik_enabled and ch.ik_type == 'LOOKAT' for ch in sd.chains):
            children.append(HStack([
                Label("Forward", size=T.FONT_SIZE_SMALL, color=T.TEXT_SECONDARY),
                Label(getattr(sd, 'forward_axis', '-Y'),
                      size=T.FONT_SIZE_SMALL, color=T.TEXT_PRIMARY),
            ], gap=8, padding=(0, 0, 0, 0)))

    # ── Floor contact ──
    if sd.has_wrap_rig and any(ch.module_type == "leg" for ch in sd.chains):
        floor_label = "Floor ON" if sd.floor_enabled else "Floor OFF"
        floor_content = VStack([
            HStack([
                Button(floor_label, active=sd.floor_enabled,
                       icon_text="\u2b1f" if sd.floor_enabled else "\u2b21",
                       action_id="toggle_floor_contact", flex=1),
                Button("\u21bb", action_id="update_floor_level"),
            ], gap=4, padding=(0, 0, 0, 0)),
        ], gap=T.ITEM_GAP, padding=(0, 0, 0, 0))
        children.append(SubsectionTitle("Floor Contact", "floor",
                                        [floor_content]))

    # ── Actions subsection ──
    action_widgets = [
        Button("Apply Wrap Rig", icon_text="\u25b6",
               action_id="apply_wrap_rig",
               style=Button.STYLE_PRIMARY, flex=1),
    ]
    if sd.has_wrap_rig:
        action_widgets.append(Button("Bake to DEF", icon_text="\u23fa",
                                     action_id="bake_to_def"))
        action_widgets.append(HStack([
            Button("Clear Rig", action_id="clear_wrap_rig",
                   style=Button.STYLE_DANGER, flex=1),
            Button("Refresh", icon_text="\u21bb",
                   action_id="refresh_wrap_rig", flex=1),
        ], gap=4, padding=(0, 0, 0, 0)))
    action_widgets.append(Button("Clear Scan Data", action_id="clear_scan_data",
                                 style=Button.STYLE_DANGER))
    actions_content = VStack(action_widgets, gap=T.ITEM_GAP,
                             padding=(0, 0, 0, 0))
    children.append(SubsectionTitle("Actions", "actions", [actions_content]))

    return VStack(children, gap=T.ITEM_GAP, padding=(0, 0, 0, 0))


# ---------------------------------------------------------------------------
# Tab content builders
# ---------------------------------------------------------------------------

def _build_chains_tab(sd):
    """Build the Chains tab content."""
    rows = []
    for chain in sd.chains:
        chain_children = []
        # Title row
        chain_children.append(HStack([
            Label(chain.chain_id, size=T.FONT_SIZE_SMALL, color=T.TEXT_PRIMARY),
            Label(chain.module_type, size=T.FONT_SIZE_SMALL, color=T.TEXT_LABEL),
            Label(chain.side, size=T.FONT_SIZE_SMALL, color=T.TEXT_LABEL),
            Label(f"{chain.bone_count}b", size=T.FONT_SIZE_SMALL,
                  color=T.TEXT_LABEL),
        ], gap=6, padding=(0, 0, 0, 0)))

        # Controls row
        controls = []
        controls.append(Button("FK", active=chain.fk_enabled,
                               action_id=f"chain_fk_{chain.chain_id}"))
        if chain.ik_enabled:
            ik_label = {"STANDARD": "IK", "SPLINE": "Spline",
                        "LOOKAT": "LookAt"}.get(chain.ik_type, "IK")
            controls.append(Button(ik_label, active=chain.ik_enabled,
                                   action_id=f"chain_ik_{chain.chain_id}"))
        chain_children.append(HStack(controls, gap=4, padding=(0, 0, 0, 0)))

        rows.append(Section("", chain_children))

    return VStack(rows, gap=T.ITEM_GAP,
                  padding=(T.PADDING_SMALL, 0, T.PADDING_SMALL, 0))


def _build_bones_tab(sd):
    """Build the Bones tab content — scrollable list."""
    rows = []
    for bone in sd.bones:
        rows.append(HStack([
            Label(bone.bone_name, size=T.FONT_SIZE_SMALL, color=T.TEXT_PRIMARY),
            Label(bone.role, size=T.FONT_SIZE_SMALL, color=T.TEXT_SECONDARY),
            Label(bone.module_type, size=T.FONT_SIZE_SMALL, color=T.TEXT_LABEL),
            Button("\u2717" if bone.skip else "\u2713",
                   active=bone.skip,
                   action_id=f"bone_skip_{bone.bone_name}"),
        ], gap=4, padding=(2, 0, 2, 0)))

    content = VStack(rows, gap=2, padding=(T.PADDING_SMALL, 0, T.PADDING_SMALL, 0))
    return ScrollView([content], max_height=200,
                      padding=(0, 0, 0, 0))


def _build_skip_tab(sd):
    """Build the Skip tab content."""
    skip_count = sum(1 for b in sd.bones if b.skip)
    return VStack([
        Section("Pattern", [
            HStack([
                TextField(placeholder="e.g. twist_*",
                          action_id="skip_pattern_field"),
            ], gap=4, padding=(0, 0, 0, 0)),
            HStack([
                Button("Skip", action_id="skip_pattern_apply", flex=1),
                Button("Unskip", action_id="skip_pattern_unapply", flex=1),
            ], gap=4, padding=(0, 0, 0, 0)),
        ]),
        Section("Selection", [
            HStack([
                Button("Skip Sel.", action_id="skip_selected", flex=1),
                Button("Unskip Sel.", action_id="unskip_selected", flex=1),
            ], gap=4, padding=(0, 0, 0, 0)),
        ]),
        HStack([
            Button("Unskip All", icon_text="\u21b6",
                   action_id="batch_unskip_all", flex=1),
            Label(f"{skip_count} skipped", size=T.FONT_SIZE_SMALL,
                  color=T.TEXT_SECONDARY),
        ], gap=8, padding=(0, 0, 0, 0)),
    ], gap=T.ITEM_GAP, padding=(T.PADDING_SMALL, 0, T.PADDING_SMALL, 0))


# ---------------------------------------------------------------------------
# Live FK/IK toggle (post-rig)
# ---------------------------------------------------------------------------

def _build_live_fkik(chain):
    """Build the live FK/IK toggle for the active chain."""
    cid = chain.chain_id
    controls = [
        Label(cid, size=T.FONT_SIZE, color=T.TEXT_PRIMARY),
    ]

    # FK button
    controls.append(Button("FK", active=not chain.ik_active,
                           action_id=f"fkik_FK_{cid}"))

    # IK/LookAt/Spline button
    if chain.ik_type == 'SPLINE':
        ik_label = "Spline"
    elif chain.ik_type == 'LOOKAT':
        ik_label = "LookAt"
    else:
        ik_label = "IK"
    controls.append(Button(ik_label, active=chain.ik_active,
                           action_id=f"fkik_IK_{cid}"))

    # Limits toggle
    if chain.ik_enabled:
        limits_icon = "\U0001f512" if chain.ik_limits else "\U0001f513"
        controls.append(Button(limits_icon, active=chain.ik_limits,
                               action_id=f"iklimits_{cid}"))

    return Section("", [HStack(controls, gap=4, padding=(0, 0, 0, 0))])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_active_chain(context, sd):
    """Find the IK-capable chain for the active pose bone."""
    from ...core.constants import WRAP_CTRL_PREFIX, WRAP_MCH_PREFIX

    if not context.active_pose_bone:
        return None
    bone_name = context.active_pose_bone.name

    for chain in sd.chains:
        if not chain.ik_enabled:
            continue
        cid = chain.chain_id
        if bone_name.startswith(WRAP_CTRL_PREFIX) or bone_name.startswith(WRAP_MCH_PREFIX):
            prefix = WRAP_CTRL_PREFIX if bone_name.startswith(WRAP_CTRL_PREFIX) else WRAP_MCH_PREFIX
            suffix = bone_name[len(prefix):]
            if suffix.startswith(cid + "_"):
                return chain
        else:
            for b in sd.bones:
                if b.bone_name == bone_name and b.chain_id == cid:
                    return chain
    return None
