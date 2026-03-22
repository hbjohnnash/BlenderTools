"""Modal operator for the BlenderTools viewport panel.

Registers a single POST_PIXEL draw handler and modal handler.
Routes all input to the widget tree; passes through events outside
the panel bounds so other Blender interactions remain unaffected.
"""

import bpy

from . import draw_primitives as dp
from . import layout as lay
from . import panel_state as state
from . import theme as T
from .widgets import Dropdown, ScrollView, Slider, TextField

# ---------------------------------------------------------------------------
# Module-level handles
# ---------------------------------------------------------------------------

_draw_handle = None
_widget_tree = None  # root Widget (ScrollView)


def cleanup_panel():
    """Module-level cleanup — called by ui.__init__.unregister()."""
    global _draw_handle, _widget_tree
    if _draw_handle:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None
    _widget_tree = None
    state.reset()


# ---------------------------------------------------------------------------
# Content building (deferred import to avoid circular deps)
# ---------------------------------------------------------------------------

def _build_content(context):
    """Build the full widget tree from content builders."""
    from .content.animation import build_animation
    from .content.bridge import build_bridge
    from .content.export import build_export
    from .content.header import build_header
    from .content.rigging import build_rigging
    from .content.scanner import build_scanner
    from .content.seams import build_seams
    from .content.skinning import build_skinning
    from .widget_base import VStack
    from .widgets import SectionBar

    hidden = state.hidden_sections
    sections = []
    sections.append(SectionBar("Controls", "controls",
                               [build_header(context)]))
    if "seams" not in hidden:
        sections.append(SectionBar("Seams", "seams",
                                   [build_seams(context)]))
    if "rigging" not in hidden:
        sections.append(SectionBar("Rigging", "rigging",
                                   [build_rigging(context)]))
    sections.append(SectionBar("Scanner", "scanner",
                               [build_scanner(context)]))
    if "skinning" not in hidden:
        sections.append(SectionBar("Skinning", "skinning",
                                   [build_skinning(context)]))
    if "animation" not in hidden:
        sections.append(SectionBar("Animation", "animation",
                                   [build_animation(context)]))
    if "bridge" not in hidden:
        sections.append(SectionBar("LLM Bridge", "bridge",
                                   [build_bridge(context)]))
    if "export" not in hidden:
        sections.append(SectionBar("Export", "export",
                                   [build_export(context)]))

    content = VStack(sections, padding=(0, 0, 0, 0), gap=0)
    return ScrollView([content], max_height=500, padding=(0, 0, 0, 0), gap=0)


def _rebuild_if_needed(context):
    """Rebuild the widget tree when state is dirty."""
    global _widget_tree
    if state.dirty or _widget_tree is None:
        _widget_tree = _build_content(context)
        state.dirty = False
        _relayout(context)


def _relayout(context):
    """Measure and position the widget tree."""
    if _widget_tree is None:
        return
    region = context.region
    panel_w = state.width
    title_h = 28

    # Set ScrollView max_height to available viewport space
    max_content_h = region.height - T.PANEL_MARGIN * 2 - title_h
    _widget_tree.max_height = max(100, max_content_h)

    # Measure (ScrollView clamps internally via max_height)
    _, content_h = lay.measure_tree(_widget_tree, panel_w)
    total_h = content_h + title_h

    # Get panel position
    px, top_y = state.get_panel_rect(region)
    panel_y = top_y - total_h

    # Position content below title bar
    lay.position_tree(_widget_tree, px, panel_y, panel_w, content_h)

    # Store computed rect for hit testing
    state._panel_rect = (px, panel_y, panel_w, total_h)
    state._title_rect = (px, top_y - title_h, panel_w, title_h)


# ---------------------------------------------------------------------------
# Draw callback
# ---------------------------------------------------------------------------

def _draw_callback(context):
    """GPU draw callback — renders the panel and widget tree."""
    if not state.visible:
        return

    # Only draw in the area where the panel was invoked
    if state.invoke_area and context.area != state.invoke_area:
        return

    _rebuild_if_needed(context)

    if _widget_tree is None:
        return

    dp.setup_gpu_state()

    px, py, pw, ph = state._panel_rect
    tx, ty, tw, th = state._title_rect

    # Panel background
    dp.draw_rounded_rect(px, py, pw, ph, T.PANEL_CORNER_RADIUS, T.PANEL_BG)
    dp.draw_border(px, py, pw, ph, T.PANEL_BORDER)

    # Title bar
    dp.draw_rounded_rect(tx, ty, tw, th, T.PANEL_CORNER_RADIUS,
                         T.PANEL_HEADER_BG)
    # Title text
    dp.draw_text("BlenderTools", tx + 10, ty + (th - T.FONT_SIZE_HEADER) / 2,
                 T.FONT_SIZE_HEADER, T.PANEL_TITLE_COLOR)

    # Close button (X) in title bar
    close_x = tx + tw - T.CLOSE_BTN_SIZE - 4
    close_y = ty + (th - T.CLOSE_BTN_SIZE) / 2
    close_hovered = _is_in_rect(
        state._mouse_x, state._mouse_y,
        close_x, close_y, T.CLOSE_BTN_SIZE, T.CLOSE_BTN_SIZE
    ) if hasattr(state, '_mouse_x') else False
    close_color = T.CLOSE_BTN_HOVER if close_hovered else T.CLOSE_BTN_COLOR
    # Draw X
    cx = close_x + T.CLOSE_BTN_SIZE / 2
    cy = close_y + T.CLOSE_BTN_SIZE / 2
    s = 5  # half-size of X
    dp.draw_line(cx - s, cy - s, cx + s, cy + s, close_color, 2.0)
    dp.draw_line(cx - s, cy + s, cx + s, cy - s, close_color, 2.0)

    # Draw widget tree
    _widget_tree.draw()

    # Tooltip
    hw = state.hover_widget
    if hw and getattr(hw, 'tooltip', None):
        _draw_tooltip(hw.tooltip, state._mouse_x, state._mouse_y)

    dp.restore_gpu_state()


# ---------------------------------------------------------------------------
# Tooltip
# ---------------------------------------------------------------------------

def _draw_tooltip(text, mx, my):
    """Draw a small tooltip box near the cursor."""
    tw, th = dp.text_dimensions(text, T.FONT_SIZE_SMALL)
    pad = 5
    box_w = tw + pad * 2
    box_h = th + pad * 2
    x = mx + 15
    y = my - box_h - 5
    dp.draw_rounded_rect(x, y, box_w, box_h, 3, (0.1, 0.1, 0.1, 0.95))
    dp.draw_border(x, y, box_w, box_h, (0.3, 0.3, 0.3, 0.8))
    dp.draw_text(text, x + pad, y + pad, T.FONT_SIZE_SMALL, T.TEXT_PRIMARY)


# ---------------------------------------------------------------------------
# Action dispatcher
# ---------------------------------------------------------------------------

def _handle_action(action_id, context, widget=None):
    """Dispatch widget action_id strings to actual operations."""
    if not action_id:
        return

    # Section/subsection collapse toggles
    if action_id.startswith("section_toggle_"):
        key = action_id[15:]
        if key in state.collapsed_sections:
            state.collapsed_sections.discard(key)
        else:
            state.collapsed_sections.add(key)
        state.dirty = True
        return

    # Gear toggles
    if action_id.startswith("gear_"):
        key = action_id[5:]  # e.g. "gear_onion" -> "onion"
        if key in state.expanded_gears:
            state.expanded_gears.discard(key)
        else:
            state.expanded_gears.add(key)
        state.dirty = True
        return

    # Subsystem toggles — show/hide sections in the panel
    if action_id.startswith("toggle_sub_"):
        name = action_id[11:]
        if name in state.hidden_sections:
            state.hidden_sections.discard(name)
        else:
            state.hidden_sections.add(name)
        state.dirty = True
        return

    # Show/Hide All
    if action_id == "show_all":
        _set_all_panels(context, True)
        return
    if action_id == "hide_all":
        _set_all_panels(context, False)
        return

    # Overlay toggles
    overlay_ops = {
        "toggle_module_overlay": "bt.module_overlay",
        "toggle_ik_overlay": "bt.ik_overlay",
        "toggle_com": "bt.toggle_com",
        "toggle_trajectory": "bt.trajectory",
        "toggle_onion": "bt.onion_skin",
    }
    if action_id in overlay_ops:
        try:
            op_id = overlay_ops[action_id]
            parts = op_id.split('.')
            op = getattr(getattr(bpy.ops, parts[0]), parts[1])
            op('INVOKE_DEFAULT')
        except Exception:
            pass
        state.dirty = True
        return

    # Scanner operations
    scanner_ops = {
        "scan_skeleton": "bt.scan_skeleton",
        "apply_wrap_rig": "bt.apply_wrap_rig",
        "clear_wrap_rig": "bt.clear_wrap_rig",
        "refresh_wrap_rig": "bt.refresh_wrap_rig",
        "clear_scan_data": "bt.clear_scan_data",
        "bake_to_def": "bt.bake_to_def",
        "bone_naming": "bt.bone_naming_overlay",
        "auto_name_chain": "bt.auto_name_chain",
        "toggle_floor_contact": "bt.toggle_floor_contact",
        "update_floor_level": "bt.update_floor_level",
        "batch_unskip_all": "bt.batch_unskip_all",
        "onion_refresh": "bt.onion_skin_refresh",
    }
    if action_id in scanner_ops:
        try:
            op_id = scanner_ops[action_id]
            parts = op_id.split('.')
            op = getattr(getattr(bpy.ops, parts[0]), parts[1])
            op()
        except Exception:
            pass
        state.dirty = True
        return

    # FK/IK toggle
    if action_id.startswith("fkik_"):
        parts = action_id.split("_", 2)  # fkik_FK_chainid or fkik_IK_chainid
        if len(parts) >= 3:
            mode = parts[1]
            chain_id = parts[2]
            try:
                bpy.ops.bt.toggle_fk_ik(chain_id=chain_id, mode=mode)
            except Exception:
                pass
            state.dirty = True
        return

    # IK limits toggle
    if action_id.startswith("iklimits_"):
        chain_id = action_id[9:]
        try:
            bpy.ops.bt.toggle_ik_limits(chain_id=chain_id)
        except Exception:
            pass
        state.dirty = True
        return

    # Seam operators
    seam_ops = {
        "seam_by_angle": "bt.seam_by_angle",
        "seam_by_material": "bt.seam_by_material",
        "seam_by_hard_edge": "bt.seam_by_hard_edge",
        "seam_island_aware": "bt.seam_island_aware",
        "seam_projection": "bt.seam_projection",
        "seam_preset": "bt.seam_preset",
        "clear_seams": "bt.clear_seams",
    }
    if action_id in seam_ops:
        try:
            op_id = seam_ops[action_id]
            parts = op_id.split('.')
            op = getattr(getattr(bpy.ops, parts[0]), parts[1])
            op()
        except Exception:
            pass
        state.dirty = True
        return

    # Rigging operators
    rig_ops = {
        "add_rig_module": "bt.add_rig_module",
        "remove_rig_module": "bt.remove_rig_module",
        "generate_rig": "bt.generate_rig",
        "load_rig_config": "bt.load_rig_config",
        "save_rig_config": "bt.save_rig_config",
        "clear_rig": "bt.clear_rig",
        "assign_bone_shape": "bt.assign_bone_shape",
        "resize_ctrl_bones": "bt.resize_ctrl_bones",
        "clear_bone_shapes": "bt.clear_bone_shapes",
        "add_custom_shape": "bt.add_custom_shape",
    }
    if action_id in rig_ops:
        try:
            op_id = rig_ops[action_id]
            parts = op_id.split('.')
            op = getattr(getattr(bpy.ops, parts[0]), parts[1])
            op()
        except Exception:
            pass
        state.dirty = True
        return

    # Skinning operators
    skin_ops = {
        "auto_weight": "bt.auto_weight",
        "rigid_bind": "bt.rigid_bind",
        "weight_cleanup": "bt.weight_cleanup",
        "merge_vertex_groups": "bt.merge_vertex_groups",
        "mirror_vertex_groups": "bt.mirror_vertex_groups",
    }
    if action_id in skin_ops:
        try:
            op_id = skin_ops[action_id]
            parts = op_id.split('.')
            op = getattr(getattr(bpy.ops, parts[0]), parts[1])
            op()
        except Exception:
            pass
        state.dirty = True
        return

    # Bridge operators
    bridge_ops = {
        "start_bridge": "bt.start_bridge",
        "stop_bridge": "bt.stop_bridge",
    }
    if action_id in bridge_ops:
        try:
            op_id = bridge_ops[action_id]
            parts = op_id.split('.')
            op = getattr(getattr(bpy.ops, parts[0]), parts[1])
            op()
        except Exception:
            pass
        state.dirty = True
        return

    # Export operators
    export_ops = {
        "scale_rig": "bt.scale_rig",
        "export_to_ue": "bt.export_to_ue",
    }
    if action_id in export_ops:
        try:
            op_id = export_ops[action_id]
            parts = op_id.split('.')
            op = getattr(getattr(bpy.ops, parts[0]), parts[1])
            op()
        except Exception:
            pass
        state.dirty = True
        return

    # Animation operators
    anim_ops = {
        "mechanical_anim": "bt.mechanical_anim",
        "follow_path": "bt.follow_path",
        "orbit_camera": "bt.orbit_camera",
        "camera_shake": "bt.camera_shake",
        "match_cycle": "bt.match_cycle",
        "push_to_nla": "bt.push_to_nla",
        "retarget_active": "bt.retarget_to_fk",
        "retarget_all": "bt.retarget_all_to_fk",
        "rm_setup": "bt.rm_setup",
        "rm_finalize": "bt.rm_finalize",
        "rm_cancel": "bt.rm_cancel",
        "rm_add_selected": "bt.rm_add_selected",
        "rm_auto_detect": "bt.rm_auto_detect",
        "recalc_com_masses": "bt.recalc_com_masses",
        "copy_pose": "bt.copy_pose",
        "paste_pose": "bt.paste_pose",
        "paste_pose_flipped": "bt.paste_pose_flipped",
    }
    if action_id in anim_ops:
        try:
            op_id = anim_ops[action_id]
            parts = op_id.split('.')
            op = getattr(getattr(bpy.ops, parts[0]), parts[1])
            op()
        except Exception:
            pass
        state.dirty = True
        return

    # Tab switch
    if action_id.startswith("tab_switch_"):
        state.dirty = True
        return

    # Slider / toggle / text field / dropdown property writes
    if (action_id.startswith("slider_") or action_id.startswith("rm_extract_")
            or action_id.startswith("tf_") or action_id.startswith("dd_")):
        _write_widget_property(action_id, context, widget)
        state.dirty = True
        return

    # Skip pattern actions
    if action_id.startswith("skip_"):
        state.dirty = True
        return


def _write_widget_property(action_id, context, widget):
    """Write a slider, toggle, or text field value back to its Blender property."""
    if widget is None:
        return
    # Read the current value from the widget
    if hasattr(widget, 'value'):
        val = widget.value
    elif hasattr(widget, 'on'):
        val = widget.on
    elif hasattr(widget, 'selected'):
        val = widget.selected
    elif hasattr(widget, 'text'):
        val = widget.text
    else:
        return

    obj = context.active_object
    scene = context.scene

    # Static mappings: action_id -> (target, property_name, type_cast)
    targets = {
        "slider_bos_threshold": (obj, 'bt_bos_threshold', float),
        "slider_onion_keyframes": (scene, 'bt_onion_use_keyframes', bool),
        "slider_onion_selected": (scene, 'bt_onion_selected_keys', bool),
        "slider_onion_before": (scene, 'bt_onion_before', int),
        "slider_onion_after": (scene, 'bt_onion_after', int),
        "slider_onion_opacity": (scene, 'bt_onion_opacity', float),
        "slider_onion_detail": (scene, 'bt_onion_proxy_ratio', float),
        "dd_flip_center_bone": (scene, 'bt_flip_center_bone', str),
    }

    # Root motion toggles (dynamic — need armature with bt_root_motion)
    if obj and obj.type == 'ARMATURE':
        rm = getattr(obj, 'bt_root_motion', None)
        if rm is not None:
            targets["rm_extract_xy"] = (rm, 'extract_xy', bool)
            targets["rm_extract_z_rot"] = (rm, 'extract_z_rot', bool)

    entry = targets.get(action_id)
    if entry:
        target, prop_name, cast = entry
        if target is not None:
            try:
                setattr(target, prop_name, cast(val))
            except Exception:
                pass


def _set_all_panels(context, show):
    if show:
        state.hidden_sections.clear()
    else:
        state.hidden_sections = {
            "seams", "rigging", "skinning", "animation", "bridge", "export",
        }
    state.dirty = True


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _is_in_rect(mx, my, rx, ry, rw, rh):
    return rx <= mx <= rx + rw and ry <= my <= ry + rh


def _find_scroll_view(widget):
    """Walk up/down tree to find a ScrollView ancestor or self."""
    if isinstance(widget, ScrollView):
        return widget
    return None


def _find_scroll_at(mx, my, widget):
    """Find a scrollable widget (ScrollView or expanded Dropdown) under cursor."""
    if not widget.visible:
        return None
    if isinstance(widget, ScrollView):
        if _is_in_rect(mx, my, widget.x, widget.y, widget.width, widget.height):
            return widget
    if isinstance(widget, Dropdown) and widget.expanded:
        if _is_in_rect(mx, my, widget.x, widget.y, widget.width, widget.height):
            return widget
    if hasattr(widget, 'children'):
        for child in widget.children:
            result = _find_scroll_at(mx, my, child)
            if result:
                return result
    return None


# ---------------------------------------------------------------------------
# Modal operator
# ---------------------------------------------------------------------------

class BT_OT_ViewportPanel(bpy.types.Operator):
    bl_idname = "bt.viewport_panel"
    bl_label = "BlenderTools Panel"
    bl_description = "Toggle the BlenderTools viewport panel"

    def invoke(self, context, event):
        global _draw_handle

        if state.visible:
            # Toggle off
            self._cleanup(context)
            return {'FINISHED'}

        state.visible = True
        state.dirty = True
        state.invoke_area = context.area
        state.position = None  # reset to auto-anchor
        state._mouse_x = event.mouse_region_x
        state._mouse_y = event.mouse_region_y

        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_callback, (context,), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if not state.visible:
            self._cleanup(context)
            return {'CANCELLED'}

        # Track mouse position
        mx = event.mouse_region_x
        my = event.mouse_region_y
        state._mouse_x = mx
        state._mouse_y = my

        # Check if we have a valid panel rect yet
        if not hasattr(state, '_panel_rect'):
            return {'PASS_THROUGH'}

        px, py, pw, ph = state._panel_rect
        tx, ty, tw, th = state._title_rect

        in_panel = _is_in_rect(mx, my, px, py, pw, ph)
        in_title = _is_in_rect(mx, my, tx, ty, tw, th)

        # --- Panel dragging ---
        if state.dragging_panel:
            if event.type == 'MOUSEMOVE':
                dx, dy = state.drag_offset
                state.position = (mx - dx, my - dy + state._title_rect[3])
                state.dirty = True
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}
            if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
                state.dragging_panel = False
                return {'RUNNING_MODAL'}
            return {'RUNNING_MODAL'}

        # --- Slider dragging ---
        if state.dragging_slider:
            slider = state.dragging_slider
            if event.type == 'MOUSEMOVE':
                action = slider.update_from_mouse(mx)
                _handle_action(action, context, widget=slider)
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}
            if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
                state.dragging_slider = None
                return {'RUNNING_MODAL'}
            return {'RUNNING_MODAL'}

        # --- Text field focused ---
        if state.focus_widget and isinstance(state.focus_widget, TextField):
            if event.type in ('ESC', 'RET', 'NUMPAD_ENTER') and event.value == 'PRESS':
                # Write text value back on confirm (Enter)
                if event.type in ('RET', 'NUMPAD_ENTER'):
                    aid = getattr(state.focus_widget, 'action_id', None)
                    if aid:
                        _handle_action(aid, context, widget=state.focus_widget)
                state.focus_widget.focused = False
                state.focus_widget = None
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}
            if event.value == 'PRESS':
                handled = state.focus_widget.handle_key(
                    event.type, getattr(event, 'unicode', ''))
                if handled:
                    context.area.tag_redraw()
                    return {'RUNNING_MODAL'}
            # Block all keyboard events while text field is focused
            if event.type not in ('MOUSEMOVE', 'LEFTMOUSE', 'RIGHTMOUSE',
                                  'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE',
                                  'TIMER', 'TIMER_REPORT', 'INBETWEEN_MOUSEMOVE'):
                return {'RUNNING_MODAL'}

        # --- Events outside panel ---
        if not in_panel and not in_title:
            # Unfocus text field on click outside
            if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
                if state.focus_widget:
                    state.focus_widget.focused = False
                    state.focus_widget = None
                    context.area.tag_redraw()
            return {'PASS_THROUGH'}

        # --- ESC closes panel ---
        if event.type == 'ESC' and event.value == 'PRESS':
            self._cleanup(context)
            return {'FINISHED'}

        # --- Title bar interactions ---
        if in_title and event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            # Check close button
            close_x = tx + tw - T.CLOSE_BTN_SIZE - 4
            close_y = ty + (th - T.CLOSE_BTN_SIZE) / 2
            if _is_in_rect(mx, my, close_x, close_y,
                           T.CLOSE_BTN_SIZE, T.CLOSE_BTN_SIZE):
                self._cleanup(context)
                return {'FINISHED'}
            # Start dragging
            state.dragging_panel = True
            state.drag_offset = (mx - tx, my - ty)
            return {'RUNNING_MODAL'}

        # --- MOUSEMOVE: hover ---
        if event.type in ('MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'):
            if _widget_tree:
                hit = _widget_tree.hit_test(mx, my)
                # Exit previous hover
                if state.hover_widget and state.hover_widget != hit:
                    if hasattr(state.hover_widget, 'on_hover_exit'):
                        state.hover_widget.on_hover_exit()
                state.hover_widget = hit
                if hit:
                    hit.on_hover(mx, my)
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # --- LEFTMOUSE: click ---
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS' and in_panel:
            if _widget_tree:
                hit = _widget_tree.hit_test(mx, my)
                if hit:
                    # Unfocus previous text field
                    if state.focus_widget and state.focus_widget != hit:
                        state.focus_widget.focused = False
                        state.focus_widget = None

                    # Slider drag
                    if isinstance(hit, Slider):
                        state.dragging_slider = hit
                        action = hit.update_from_mouse(mx)
                        _handle_action(action, context, widget=hit)
                        context.area.tag_redraw()
                        return {'RUNNING_MODAL'}

                    # Text field focus
                    if isinstance(hit, TextField):
                        state.focus_widget = hit

                    action = hit.on_click(mx, my)
                    _handle_action(action, context, widget=hit)
                    context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # --- Scroll wheel ---
        if event.type in ('WHEELUPMOUSE', 'WHEELDOWNMOUSE') and in_panel:
            if _widget_tree:
                sv = _find_scroll_at(mx, my, _widget_tree)
                if sv:
                    delta = 1 if event.type == 'WHEELUPMOUSE' else -1
                    sv.on_scroll(delta)
                    # Re-layout children at new scroll offset
                    sv.layout(sv.x, sv.y, sv.width, sv.height)
                    context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Block other events in panel area
        if in_panel:
            return {'RUNNING_MODAL'}

        return {'PASS_THROUGH'}

    def _cleanup(self, context):
        global _draw_handle, _widget_tree
        state.visible = False
        state.hover_widget = None
        state.focus_widget = None
        state.dragging_panel = False
        state.dragging_slider = None
        if _draw_handle:
            bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
            _draw_handle = None
        _widget_tree = None
        if context.area:
            context.area.tag_redraw()
