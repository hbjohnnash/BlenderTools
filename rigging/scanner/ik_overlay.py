"""FK/IK switch overlay — bottom viewport bar for quick chain toggling.

Shows clickable buttons for each IK-capable chain in pose mode.
Only visible when a wrap rig is active.
"""

import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_draw_handle = None
_active = False
_hover_chain = None  # chain_id currently hovered

# Layout constants
BTN_HEIGHT = 24
BTN_PAD_X = 10
BTN_PAD_Y = 4
BTN_MARGIN = 6
BAR_MARGIN_BOTTOM = 14
TEXT_SIZE = 13

# Colors
COLOR_FK_BG = (0.15, 0.35, 0.65, 0.85)
COLOR_FK_HOVER = (0.2, 0.45, 0.8, 0.9)
COLOR_IK_BG = (0.7, 0.35, 0.1, 0.85)
COLOR_IK_HOVER = (0.85, 0.45, 0.15, 0.9)
COLOR_BAR_BG = (0.0, 0.0, 0.0, 0.4)
COLOR_TEXT = (1.0, 1.0, 1.0, 1.0)


# ---------------------------------------------------------------------------
# Layout calculation
# ---------------------------------------------------------------------------

def _get_chain_buttons(context):
    """Build button layout data for IK-capable chains.

    Returns list of {chain_id, ik_active, label, x, y, w, h}.
    """
    obj = context.active_object
    if not obj or obj.type != 'ARMATURE':
        return []

    sd = obj.bt_scan
    if not sd.has_wrap_rig:
        return []

    region = context.region
    if not region:
        return []

    buttons = []
    font_id = 0
    blf.size(font_id, TEXT_SIZE)

    for chain in sd.chains:
        if not chain.ik_enabled:
            continue
        mode = "IK" if chain.ik_active else "FK"
        label = f"{chain.chain_id}: {mode}"
        w, _ = blf.dimensions(font_id, label)
        buttons.append({
            "chain_id": chain.chain_id,
            "ik_active": chain.ik_active,
            "label": label,
            "w": w + BTN_PAD_X * 2,
            "h": BTN_HEIGHT,
        })

    if not buttons:
        return []

    # Calculate positions — centered horizontally at bottom
    total_w = sum(b["w"] for b in buttons) + BTN_MARGIN * (len(buttons) - 1)
    start_x = (region.width - total_w) / 2
    y = BAR_MARGIN_BOTTOM

    x = start_x
    for b in buttons:
        b["x"] = x
        b["y"] = y
        x += b["w"] + BTN_MARGIN

    return buttons


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def _draw_quad(shader, x1, y1, x2, y2, color):
    verts = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    batch = batch_for_shader(shader, 'TRIS', {"pos": verts},
                             indices=[(0, 1, 2), (0, 2, 3)])
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _draw_ik_overlay_callback(context):
    """GPU draw callback for the IK switch bar."""
    if not _active:
        return

    obj = context.active_object
    if not obj or obj.type != 'ARMATURE' or obj.mode != 'POSE':
        return

    sd = obj.bt_scan
    if not sd.has_wrap_rig:
        return

    buttons = _get_chain_buttons(context)
    if not buttons:
        return

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')

    # Bar background
    bar_x1 = buttons[0]["x"] - BTN_MARGIN
    bar_x2 = buttons[-1]["x"] + buttons[-1]["w"] + BTN_MARGIN
    bar_y1 = BAR_MARGIN_BOTTOM - BTN_PAD_Y
    bar_y2 = BAR_MARGIN_BOTTOM + BTN_HEIGHT + BTN_PAD_Y
    _draw_quad(shader, bar_x1, bar_y1, bar_x2, bar_y2, COLOR_BAR_BG)

    # Buttons
    font_id = 0
    blf.size(font_id, TEXT_SIZE)

    for b in buttons:
        is_hovered = (b["chain_id"] == _hover_chain)
        if b["ik_active"]:
            bg = COLOR_IK_HOVER if is_hovered else COLOR_IK_BG
        else:
            bg = COLOR_FK_HOVER if is_hovered else COLOR_FK_BG

        _draw_quad(shader, b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"], bg)

        # Text centered in button
        tw, th = blf.dimensions(font_id, b["label"])
        tx = b["x"] + (b["w"] - tw) / 2
        ty = b["y"] + (b["h"] - th) / 2
        blf.color(font_id, *COLOR_TEXT)
        blf.position(font_id, tx, ty, 0)
        blf.draw(font_id, b["label"])

    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('NONE')


# ---------------------------------------------------------------------------
# Hit testing
# ---------------------------------------------------------------------------

def _hit_test_button(context, mx, my):
    """Return chain_id of button under mouse, or None."""
    buttons = _get_chain_buttons(context)
    for b in buttons:
        if (b["x"] <= mx <= b["x"] + b["w"] and
                b["y"] <= my <= b["y"] + b["h"]):
            return b["chain_id"]
    return None


# ---------------------------------------------------------------------------
# Modal operator
# ---------------------------------------------------------------------------

class BT_OT_IKOverlay(bpy.types.Operator):
    """FK/IK switch overlay at viewport bottom"""
    bl_idname = "bt.ik_overlay"
    bl_label = "FK/IK Overlay"
    bl_description = "Show clickable FK/IK toggle buttons at the bottom of the viewport"

    def modal(self, context, event):
        global _active, _hover_chain

        if not _active:
            self._cleanup(context)
            return {'CANCELLED'}

        obj = context.active_object
        if not obj or obj.type != 'ARMATURE' or obj.mode != 'POSE':
            _active = False
            self._cleanup(context)
            return {'CANCELLED'}

        if event.type == 'ESC' and event.value == 'PRESS':
            _active = False
            self._cleanup(context)
            self.report({'INFO'}, "FK/IK overlay disabled")
            return {'CANCELLED'}

        if event.type == 'MOUSEMOVE':
            old = _hover_chain
            _hover_chain = _hit_test_button(context, event.mouse_region_x,
                                            event.mouse_region_y)
            if _hover_chain != old and context.area:
                context.area.tag_redraw()
            return {'PASS_THROUGH'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            chain = _hit_test_button(context, event.mouse_region_x,
                                     event.mouse_region_y)
            if chain:
                bpy.ops.bt.toggle_fk_ik(chain_id=chain, mode='TOGGLE')
                if context.area:
                    context.area.tag_redraw()
                return {'RUNNING_MODAL'}

        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        global _draw_handle, _active, _hover_chain

        if _active:
            _active = False
            self._cleanup(context)
            self.report({'INFO'}, "FK/IK overlay disabled")
            return {'CANCELLED'}

        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Select an armature")
            return {'CANCELLED'}

        sd = obj.bt_scan
        if not sd.has_wrap_rig:
            self.report({'WARNING'}, "No wrap rig — scan and apply first")
            return {'CANCELLED'}

        _active = True
        _hover_chain = None

        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_ik_overlay_callback, (context,), 'WINDOW', 'POST_PIXEL'
        )

        context.window_manager.modal_handler_add(self)
        if context.area:
            context.area.tag_redraw()
        self.report({'INFO'}, "FK/IK overlay enabled — click chains to toggle")
        return {'RUNNING_MODAL'}

    def _cleanup(self, context):
        global _draw_handle, _hover_chain
        if _draw_handle:
            bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
            _draw_handle = None
        _hover_chain = None
        if context.area:
            context.area.tag_redraw()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (
    BT_OT_IKOverlay,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    global _active, _draw_handle
    if _draw_handle:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None
    _active = False
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
