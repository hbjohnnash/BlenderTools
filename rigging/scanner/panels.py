"""UI panels for skeleton scanner."""

import bpy

from ...core.constants import PANEL_CATEGORY, WRAP_CTRL_PREFIX, WRAP_MCH_PREFIX


def _find_chain_for_bone(sd, bone_name):
    """Map any bone (DEF, MCH, CTRL-FK, IK target/pole) to its IK-capable chain."""
    for chain in sd.chains:
        if not chain.ik_enabled:
            continue
        cid = chain.chain_id
        # CTRL or MCH wrap bone — check chain_id prefix
        if bone_name.startswith(WRAP_CTRL_PREFIX) or bone_name.startswith(WRAP_MCH_PREFIX):
            prefix = WRAP_CTRL_PREFIX if bone_name.startswith(WRAP_CTRL_PREFIX) else WRAP_MCH_PREFIX
            suffix = bone_name[len(prefix):]
            if suffix.startswith(cid + "_"):
                return chain
        else:
            # DEF (original) bone — check bone list
            for b in sd.bones:
                if b.bone_name == bone_name and b.chain_id == cid:
                    return chain
    return None


class BT_PT_SkeletonScanner(bpy.types.Panel):
    bl_label = "Skeleton Scanner"
    bl_idname = "BT_PT_SkeletonScanner"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = PANEL_CATEGORY
    bl_parent_id = "BT_PT_RiggingMain"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.label(text="", icon='VIEWZOOM')

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        if not obj or obj.type != 'ARMATURE':
            layout.label(text="Select an armature", icon='INFO')
            return

        sd = obj.bt_scan

        # Name Bones + Auto-Name Chain + Scan buttons
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator("bt.bone_naming_overlay", icon='SORTALPHA')
        row.operator("bt.auto_name_chain", text="", icon='LINKED')
        row.operator("bt.scan_skeleton", icon='VIEWZOOM')

        if not sd.is_scanned:
            return

        # ── Results ──
        box = layout.box()
        box.label(text=f"Type: {sd.skeleton_type}", icon='ARMATURE_DATA')
        box.separator(factor=0.3)
        box.label(text=f"Confidence: {sd.confidence:.0%}")
        box.label(text=f"Chains: {len(sd.chains)}  |  Bones: {len(sd.bones)}")

        if sd.unmapped_bones:
            unmapped = [s.strip() for s in sd.unmapped_bones.split(",") if s.strip()]
            box.label(text=f"Unmapped: {len(unmapped)}")

        # ── FK/IK ──
        if sd.has_wrap_rig:
            # Live mode — show FK/IK toggle for selected chain
            active_chain = None
            if context.active_pose_bone:
                active_chain = _find_chain_for_bone(sd, context.active_pose_bone.name)

            if active_chain:
                box = layout.box()
                row = box.row()
                row.label(text=active_chain.chain_id, icon='LINKED')
                row = box.row(align=True)
                op = row.operator(
                    "bt.toggle_fk_ik", text="FK",
                    icon='CON_TRANSLIKE',
                    depress=not active_chain.ik_active,
                )
                op.chain_id = active_chain.chain_id
                op.mode = 'FK'
                # Show "Spline", "LookAt", or "IK" based on chain's ik_type
                if active_chain.ik_type == 'SPLINE':
                    ik_label = "Spline"
                    ik_icon = 'CURVE_BEZCURVE'
                elif active_chain.ik_type == 'LOOKAT':
                    ik_label = "LookAt"
                    ik_icon = 'TRACKER'
                else:
                    ik_label = "IK"
                    ik_icon = 'CON_KINEMATIC'
                op = row.operator(
                    "bt.toggle_fk_ik", text=ik_label,
                    icon=ik_icon,
                    depress=active_chain.ik_active,
                )
                op.chain_id = active_chain.chain_id
                op.mode = 'IK'
                # IK Limits toggle + per-bone edit
                if active_chain.ik_enabled:
                    op = row.operator(
                        "bt.toggle_ik_limits",
                        text="",
                        icon='CON_ROTLIMIT' if active_chain.ik_limits else 'UNLOCKED',
                        depress=active_chain.ik_limits,
                    )
                    op.chain_id = active_chain.chain_id
                    row.operator("bt.edit_bone_ik_limits", text="", icon='PREFERENCES')
        else:
            # ── Chain Config ──
            box = layout.box()
            box.label(text="Chains", icon='LINKED')
            box.separator(factor=0.3)
            for chain in sd.chains:
                sub = box.box()
                row = sub.row()
                row.prop(chain, "module_type", text=chain.chain_id)
                row.prop(chain, "side", text="")
                row = sub.row(align=True)
                row.prop(chain, "fk_enabled", text="FK", toggle=True)
                row.prop(chain, "ik_enabled", text="IK", toggle=True)
                if chain.ik_enabled:
                    row.prop(chain, "ik_type", text="")
                    if chain.ik_type == 'STANDARD':
                        row.prop(chain, "ik_snap", text="Snap", toggle=True)
                row.label(text=f"{chain.bone_count} bones")
                if chain.ik_enabled:
                    row = sub.row(align=True)
                    row.prop(chain, "ik_limits", text="Joint Limits", toggle=True, icon='CON_ROTLIMIT')

            # ── Batch Skip ──
            box = layout.box()
            box.label(text="Batch Skip", icon='FILTER')
            box.separator(factor=0.3)

            row = box.row(align=True)
            row.prop(sd, "skip_pattern", text="", icon='SORTALPHA')
            op = row.operator("bt.batch_skip_pattern", text="Skip", icon='CANCEL')
            op.skip_value = True
            op = row.operator("bt.batch_skip_pattern", text="Unskip", icon='CHECKMARK')
            op.skip_value = False

            if context.mode in ('POSE', 'EDIT_ARMATURE'):
                row = box.row(align=True)
                op = row.operator("bt.batch_skip_selected", text="Skip Sel.", icon='RESTRICT_SELECT_OFF')
                op.skip_value = True
                op = row.operator("bt.batch_skip_selected", text="Unskip Sel.", icon='RESTRICT_SELECT_ON')
                op.skip_value = False

            row = box.row(align=True)
            row.operator("bt.batch_unskip_all", icon='LOOP_BACK')
            skip_count = sum(1 for b in sd.bones if b.skip)
            row.label(text=f"{skip_count} skipped")

            # ── Bone Assignments ──
            box = layout.box()
            row = box.row()
            row.label(text="Bone Assignments", icon='BONE_DATA')
            row.label(text=f"{len(sd.bones)}")
            box.separator(factor=0.3)

            col = box.column(align=True)
            for bone_item in sd.bones:
                row = col.row(align=True)
                sub = row.row()
                sub.scale_x = 0.6
                sub.label(text=bone_item.bone_name)
                row.prop(bone_item, "role", text="")
                row.prop(bone_item, "module_type", text="")
                row.prop(bone_item, "skip", text="", icon='CANCEL')

            # Unmapped bones
            if sd.unmapped_bones:
                box = layout.box()
                box.label(text="Unmapped Bones", icon='ERROR')
                unmapped = [s.strip() for s in sd.unmapped_bones.split(",") if s.strip()]
                col = box.column(align=True)
                for name in unmapped[:20]:
                    col.label(text=f"  {name}")
                if len(unmapped) > 20:
                    col.label(text=f"  ... and {len(unmapped) - 20} more")

        # ── Floor Contact ──
        if sd.has_wrap_rig and any(ch.module_type == "leg" for ch in sd.chains):
            box = layout.box()
            row = box.row()
            row.operator(
                "bt.toggle_floor_contact",
                text="Floor Contact",
                icon='SNAP_FACE' if sd.floor_enabled else 'SNAP_OFF',
                depress=sd.floor_enabled,
            )
            col = box.column(align=True)
            if sd.floor_enabled:
                row = col.row(align=True)
                row.prop(sd, "floor_level", text="Level")
                row.operator("bt.update_floor_level", text="", icon='FILE_REFRESH')
            else:
                col.prop(sd, "floor_level", text="Level")

        # ── Forward Axis (shown when a LookAt chain exists) ──
        if not sd.has_wrap_rig and any(
            ch.ik_enabled and ch.ik_type == 'LOOKAT' for ch in sd.chains
        ):
            row = layout.row()
            row.prop(sd, "forward_axis", text="Forward Axis")

        # ── Actions ──
        layout.separator()
        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator("bt.apply_wrap_rig", icon='PLAY')

        col = layout.column(align=True)
        if sd.has_wrap_rig:
            col.operator("bt.bake_to_def", icon='REC')
            row = col.row(align=True)
            row.operator("bt.clear_wrap_rig", icon='X')
            row.operator("bt.refresh_wrap_rig", text="Refresh", icon='FILE_REFRESH')
        col.operator("bt.clear_scan_data", icon='TRASH')


classes = (
    BT_PT_SkeletonScanner,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
