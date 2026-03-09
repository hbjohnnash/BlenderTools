"""Interactive viewport overlay for module placement.

Draws clickable circles on bone heads/tails. Clicking opens a module
selection menu and places the 3D cursor at that bone position.
If the chosen module has bone slots, enters assignment mode where the
user clicks bones sequentially to fill each slot.
Hidden in pose mode.
"""

import re
import time
from math import cos, pi, sin

import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from ..core.constants import (
    CONTROL_PREFIX,
    DEFORM_PREFIX,
    MECHANISM_PREFIX,
    WRAP_CTRL_PREFIX,
    WRAP_MCH_PREFIX,
)
from .modules import MODULE_REGISTRY, get_module_class


def _detect_side(bone_name):
    """Detect L/R/C side from a bone name.

    Handles BT convention (BT_{Type}_{Side}_{Role}), dot-separated (.L, .R),
    and underscore-separated (_L, _R) — only when L/R is a standalone segment,
    not part of a longer word like 'Leg' or 'Lower'.
    """
    # BT convention: 3rd segment is side
    if bone_name.startswith("BT_"):
        parts = bone_name.split('_', 3)
        if len(parts) >= 3 and parts[2] in ('L', 'R', 'C'):
            return parts[2]
    # Standalone _L or .L followed by separator or end-of-string
    if re.search(r'[_.]L(?=[_.]|$)', bone_name):
        return 'L'
    if re.search(r'[_.]R(?=[_.]|$)', bone_name):
        return 'R'
    return 'C'


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_draw_handle = None
_hover_info = {"bone": None, "end": None, "pos": None}
_active = False

# Assignment mode state
_assign_mode = False
_assign_module_type = ""
_assign_slots = []           # [(role, description), ...]
_assign_current = 0          # Index into _assign_slots
_assign_mapping = {}         # {role: bone_name}
_assign_origin_bone = ""     # The bone initially clicked
_assign_origin_pos = None    # World position of initial click

# Hover animation state
_anim_current = None         # (bone_name, end) currently hovered
_anim_current_t = 0.0        # monotonic time when hover started
_anim_prev = None            # (bone_name, end) previously hovered
_anim_prev_t = 0.0           # monotonic time when hover ended

ANIM_DURATION = 0.15         # seconds for hover transition

# Circle geometry (screen-space radius in pixels)
CIRCLE_RADIUS = 10
CIRCLE_SEGMENTS = 24
HOVER_RADIUS = 14
OUTLINE_THICKNESS = 3

# Colors (RGBA)
COLOR_DEFAULT = (1.0, 1.0, 1.0, 0.3)
COLOR_ASSIGNED = (0.2, 1.0, 0.4, 0.85)
COLOR_ASSIGN_OUTLINE = (0.2, 1.0, 0.4, 1.0)


# ---------------------------------------------------------------------------
# Animation helpers
# ---------------------------------------------------------------------------

def _smoothstep(t):
    """Smooth ease-in-ease-out interpolation (Hermite)."""
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _lerp(a, b, t):
    return a + (b - a) * t


def _update_hover_target(bone_name, end):
    """Track hover transitions for animation."""
    global _anim_current, _anim_current_t, _anim_prev, _anim_prev_t

    new_target = (bone_name, end) if bone_name else None
    if new_target == _anim_current:
        return

    now = time.monotonic()
    if _anim_current:
        _anim_prev = _anim_current
        _anim_prev_t = now
    _anim_current = new_target
    if new_target:
        _anim_current_t = now


def _get_hover_factor(bone_name, end):
    """Return 0.0-1.0 indicating how 'hovered' a bone endpoint is."""
    now = time.monotonic()

    if _anim_current and bone_name == _anim_current[0] and end == _anim_current[1]:
        elapsed = now - _anim_current_t
        return _smoothstep(min(1.0, elapsed / ANIM_DURATION))

    if _anim_prev and bone_name == _anim_prev[0] and end == _anim_prev[1]:
        elapsed = now - _anim_prev_t
        return 1.0 - _smoothstep(min(1.0, elapsed / ANIM_DURATION))

    return 0.0


def _is_animating():
    """Check if any hover animation is in progress."""
    now = time.monotonic()
    if _anim_current and (now - _anim_current_t) < ANIM_DURATION:
        return True
    if _anim_prev and (now - _anim_prev_t) < ANIM_DURATION:
        return True
    return False


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _circle_verts_2d(cx, cy, r, segs=CIRCLE_SEGMENTS):
    """Generate 2D triangle-fan vertices for a filled circle."""
    verts = [(cx, cy)]
    for i in range(segs + 1):
        a = 2 * pi * i / segs
        verts.append((cx + r * cos(a), cy + r * sin(a)))
    return verts


def _circle_indices(segs=CIRCLE_SEGMENTS):
    """Triangle-fan indices for a circle with center at index 0."""
    indices = []
    for i in range(1, segs + 1):
        indices.append((0, i, i + 1 if i < segs else 1))
    return indices


def _ring_verts_2d(cx, cy, r_outer, r_inner, segs=CIRCLE_SEGMENTS):
    """Generate vertices for a ring (thick outline)."""
    verts = []
    for i in range(segs + 1):
        a = 2 * pi * i / segs
        verts.append((cx + r_outer * cos(a), cy + r_outer * sin(a)))
        verts.append((cx + r_inner * cos(a), cy + r_inner * sin(a)))
    return verts


def _ring_indices(segs=CIRCLE_SEGMENTS):
    """Triangle-strip indices for a ring."""
    indices = []
    for i in range(segs):
        o1 = i * 2
        i1 = i * 2 + 1
        o2 = (i + 1) * 2
        i2 = (i + 1) * 2 + 1
        indices.append((o1, i1, o2))
        indices.append((i1, i2, o2))
    return indices


# ---------------------------------------------------------------------------
# GPU Drawing
# ---------------------------------------------------------------------------

def _get_bone_endpoints(context):
    """Collect world-space bone head/tail positions for the active armature."""
    obj = context.active_object
    if not obj or obj.type != 'ARMATURE':
        return []

    if obj.mode == 'POSE':
        return []

    mat = obj.matrix_world
    points = []

    for bone in obj.data.bones:
        name = bone.name
        if (name.startswith(DEFORM_PREFIX) or name.startswith(CONTROL_PREFIX) or
                name.startswith(MECHANISM_PREFIX) or name.startswith(WRAP_CTRL_PREFIX) or
                name.startswith(WRAP_MCH_PREFIX)):
            continue

        head_world = mat @ bone.head_local
        tail_world = mat @ bone.tail_local

        points.append((name, "head", head_world))
        points.append((name, "tail", tail_world))

    return points


def _get_bone_midpoints(context):
    """Collect world-space bone midpoints (for assignment mode — one circle per bone)."""
    obj = context.active_object
    if not obj or obj.type != 'ARMATURE':
        return []

    if obj.mode == 'POSE':
        return []

    mat = obj.matrix_world
    points = []

    for bone in obj.data.bones:
        name = bone.name
        if (name.startswith(DEFORM_PREFIX) or name.startswith(CONTROL_PREFIX) or
                name.startswith(MECHANISM_PREFIX) or name.startswith(WRAP_CTRL_PREFIX) or
                name.startswith(WRAP_MCH_PREFIX)):
            continue

        mid_world = mat @ ((bone.head_local + bone.tail_local) / 2)
        points.append((name, "mid", mid_world))

    return points


def _world_to_screen(context, pos):
    """Project a 3D point to screen-space (2D pixel coords)."""
    from bpy_extras.view3d_utils import location_3d_to_region_2d
    region = context.region
    rv3d = context.space_data.region_3d
    if not region or not rv3d:
        return None
    return location_3d_to_region_2d(region, rv3d, pos)


def _draw_filled_circle(shader, sx, sy, radius, color):
    """Draw a filled circle at screen coords."""
    verts = _circle_verts_2d(sx, sy, radius)
    indices = _circle_indices()
    batch = batch_for_shader(shader, 'TRIS', {"pos": verts}, indices=indices)
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _draw_ring(shader, sx, sy, r_outer, r_inner, color):
    """Draw a ring (thick outline) at screen coords."""
    verts = _ring_verts_2d(sx, sy, r_outer, r_inner)
    indices = _ring_indices()
    batch = batch_for_shader(shader, 'TRIS', {"pos": verts}, indices=indices)
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _draw_bone_label(context, sx, sy, text, alpha):
    """Draw a bone name label at screen position with alpha fade."""
    if alpha < 0.05:
        return

    font_id = 0
    blf.size(font_id, 13)
    w, h = blf.dimensions(font_id, text)

    lx = sx - w / 2
    ly = sy

    # Background
    pad = 5
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    bg_verts = [
        (lx - pad, ly - 4),
        (lx + w + pad, ly - 4),
        (lx + w + pad, ly + h + 4),
        (lx - pad, ly + h + 4),
    ]
    bg_indices = [(0, 1, 2), (0, 2, 3)]
    batch = batch_for_shader(shader, 'TRIS', {"pos": bg_verts}, indices=bg_indices)
    shader.bind()
    shader.uniform_float("color", (0.0, 0.0, 0.0, 0.65 * alpha))
    batch.draw(shader)

    # Text
    blf.color(font_id, 1.0, 1.0, 1.0, alpha)
    blf.position(font_id, lx, ly, 0)
    blf.draw(font_id, text)


def _draw_callback(context):
    """GPU draw handler — renders circles at bone endpoints."""
    if not _active:
        return

    obj = context.active_object
    if not obj or obj.type != 'ARMATURE' or obj.mode == 'POSE':
        return

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')

    if _assign_mode:
        _draw_assignment_mode(context, shader)
    else:
        _draw_normal_mode(context, shader)

    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('NONE')

    # Drive animation redraws
    if _is_animating() and context.area:
        context.area.tag_redraw()


def _draw_normal_mode(context, shader):
    """Draw circles on bone head/tail with animated hover."""
    points = _get_bone_endpoints(context)
    if not points:
        return

    for bone_name, end, world_pos in points:
        screen = _world_to_screen(context, world_pos)
        if screen is None:
            continue

        sx, sy = screen
        factor = _get_hover_factor(bone_name, end)

        radius = _lerp(CIRCLE_RADIUS, HOVER_RADIUS, factor)
        fill_alpha = _lerp(0.3, 0.9, factor)
        outline_thickness = OUTLINE_THICKNESS * factor

        # Outline ring (fades in with hover)
        if factor > 0.01:
            _draw_ring(shader, sx, sy,
                       radius + outline_thickness,
                       radius,
                       (1.0, 1.0, 1.0, factor))

        # Fill circle
        _draw_filled_circle(shader, sx, sy, radius, (1.0, 1.0, 1.0, fill_alpha))

        # Bone name label
        if factor > 0.1:
            end_tag = "h" if end == "head" else "t"
            label = f"{bone_name} ({end_tag})"
            label_y = sy + radius + outline_thickness + 8
            _draw_bone_label(context, sx, label_y, label, factor)


def _draw_assignment_mode(context, shader):
    """Draw bone circles in assignment mode — one per bone, assigned ones green."""
    points = _get_bone_midpoints(context)
    if not points:
        return

    assigned_bones = set(_assign_mapping.values())

    for bone_name, end, world_pos in points:
        screen = _world_to_screen(context, world_pos)
        if screen is None:
            continue

        sx, sy = screen
        is_assigned = (bone_name in assigned_bones)
        factor = _get_hover_factor(bone_name, end)

        if is_assigned:
            # Green with solid outline
            _draw_ring(shader, sx, sy,
                       HOVER_RADIUS + OUTLINE_THICKNESS,
                       HOVER_RADIUS,
                       COLOR_ASSIGN_OUTLINE)
            _draw_filled_circle(shader, sx, sy, HOVER_RADIUS, COLOR_ASSIGNED)
            # Always show label for assigned bones
            label_y = sy + HOVER_RADIUS + OUTLINE_THICKNESS + 8
            _draw_bone_label(context, sx, label_y, bone_name, 1.0)
        else:
            radius = _lerp(CIRCLE_RADIUS, HOVER_RADIUS, factor)
            fill_alpha = _lerp(0.3, 0.9, factor)
            outline_thickness = OUTLINE_THICKNESS * factor

            if factor > 0.01:
                _draw_ring(shader, sx, sy,
                           radius + outline_thickness,
                           radius,
                           (1.0, 1.0, 1.0, factor))

            _draw_filled_circle(shader, sx, sy, radius, (1.0, 1.0, 1.0, fill_alpha))

            if factor > 0.1:
                label_y = sy + radius + outline_thickness + 8
                _draw_bone_label(context, sx, label_y, bone_name, factor)

    # Header text showing current slot
    if _assign_current < len(_assign_slots):
        role, desc = _assign_slots[_assign_current]
        slot_num = _assign_current + 1
        total = len(_assign_slots)
        text = f"Click bone for: {role} ({slot_num}/{total}) — {desc}  [RMB skip, ESC cancel]"
    else:
        text = "All slots assigned — press ENTER to confirm or ESC to cancel"

    _draw_header_text(context, text)


def _draw_header_text(context, text):
    """Draw text centered at the top of the viewport."""
    region = context.region
    if not region:
        return

    font_id = 0
    blf.size(font_id, 16)
    w, h = blf.dimensions(font_id, text)
    x = (region.width - w) / 2
    y = region.height - 40

    # Background bar
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    pad = 10
    bar_verts = [
        (x - pad, y - 6),
        (x + w + pad, y - 6),
        (x + w + pad, y + h + 6),
        (x - pad, y + h + 6),
    ]
    bar_indices = [(0, 1, 2), (0, 2, 3)]
    batch = batch_for_shader(shader, 'TRIS', {"pos": bar_verts}, indices=bar_indices)
    shader.bind()
    shader.uniform_float("color", (0.0, 0.0, 0.0, 0.7))
    batch.draw(shader)

    # Text
    blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
    blf.position(font_id, x, y, 0)
    blf.draw(font_id, text)


# ---------------------------------------------------------------------------
# Hit Testing
# ---------------------------------------------------------------------------

def _hit_test(context, mouse_x, mouse_y):
    """Find the closest bone endpoint under the mouse cursor."""
    points = _get_bone_endpoints(context)
    best = None
    best_dist = HOVER_RADIUS + OUTLINE_THICKNESS + 2

    for bone_name, end, world_pos in points:
        screen = _world_to_screen(context, world_pos)
        if screen is None:
            continue
        dx = mouse_x - screen[0]
        dy = mouse_y - screen[1]
        dist = (dx * dx + dy * dy) ** 0.5
        if dist < best_dist:
            best_dist = dist
            best = (bone_name, end, world_pos)

    return best


def _hit_test_bone(context, mouse_x, mouse_y):
    """Find the closest bone (midpoint) under mouse — for assignment mode."""
    points = _get_bone_midpoints(context)
    best = None
    best_dist = HOVER_RADIUS + OUTLINE_THICKNESS + 2

    for bone_name, end, world_pos in points:
        screen = _world_to_screen(context, world_pos)
        if screen is None:
            continue
        dx = mouse_x - screen[0]
        dy = mouse_y - screen[1]
        dist = (dx * dx + dy * dy) ** 0.5
        if dist < best_dist:
            best_dist = dist
            best = (bone_name, end, world_pos)

    return best


# ---------------------------------------------------------------------------
# Assignment mode helpers
# ---------------------------------------------------------------------------

def _start_assignment(module_type, origin_bone, origin_pos):
    """Enter assignment mode for a module that has bone slots."""
    global _assign_mode, _assign_module_type, _assign_slots
    global _assign_current, _assign_mapping, _assign_origin_bone, _assign_origin_pos

    cls = get_module_class(module_type)
    if not cls:
        return False

    dummy_config = {"options": {}}
    instance = cls(dummy_config)
    slots = instance.get_bone_slots()
    if not slots:
        return False

    _assign_mode = True
    _assign_module_type = module_type
    _assign_slots = list(slots)
    _assign_current = 0
    _assign_mapping = {}
    _assign_origin_bone = origin_bone
    _assign_origin_pos = origin_pos
    return True


def _finish_assignment(context):
    """Finalize assignment — create the module config with bone_mapping."""
    global _assign_mode
    from .config_loader import config_from_armature, store_config_on_armature

    arm_obj = context.active_object
    cls = get_module_class(_assign_module_type)
    if not arm_obj or not cls:
        _assign_mode = False
        return

    # Detect side from origin bone
    side = _detect_side(_assign_origin_bone)

    cursor_pos = list(_assign_origin_pos) if _assign_origin_pos else [0, 0, 0]

    config_entry = {
        "type": _assign_module_type,
        "name": cls.display_name,
        "side": side,
        "parent_bone": _assign_origin_bone,
        "position": cursor_pos,
        "options": {"bone_mapping": dict(_assign_mapping)} if _assign_mapping else {},
    }

    existing = config_from_armature(arm_obj) or {
        "name": "Rig", "modules": [], "global_options": {}
    }
    existing["modules"].append(config_entry)
    store_config_on_armature(arm_obj, existing)

    mapped_count = len(_assign_mapping)
    total = len(_assign_slots)
    _assign_mode = False
    return f"Added {cls.display_name} ({mapped_count}/{total} bones mapped)"


def _cancel_assignment():
    """Cancel assignment mode without creating anything."""
    global _assign_mode
    _assign_mode = False


# ---------------------------------------------------------------------------
# Module Selection Menu
# ---------------------------------------------------------------------------

def _draw_module_entries(layout, key, cls):
    """Draw menu entries for a module. Adds a 'Map Existing' option if it has slots."""
    dummy = cls({"options": {}})
    slots = dummy.get_bone_slots()

    op = layout.operator("bt.add_module_at_point", text=cls.display_name, icon='ADD')
    op.module_type = key
    op.use_existing = False

    if slots:
        op = layout.operator(
            "bt.add_module_at_point",
            text=f"    {cls.display_name} — Map Existing Bones",
            icon='BONE_DATA',
        )
        op.module_type = key
        op.use_existing = True


class BT_MT_ModulePickerMenu(bpy.types.Menu):
    bl_idname = "BT_MT_ModulePickerMenu"
    bl_label = "Add Module"

    def draw(self, context):
        layout = self.layout

        organic = []
        mechanical = []
        for key, cls in sorted(MODULE_REGISTRY.items()):
            if cls.category == "mechanical":
                mechanical.append((key, cls))
            else:
                organic.append((key, cls))

        if organic:
            layout.label(text="Organic", icon='ARMATURE_DATA')
            for key, cls in organic:
                _draw_module_entries(layout, key, cls)

        if mechanical:
            layout.separator()
            layout.label(text="Mechanical", icon='SETTINGS')
            for key, cls in mechanical:
                _draw_module_entries(layout, key, cls)


class BT_OT_AddModuleAtPoint(bpy.types.Operator):
    """Add a rig module at the stored bone position."""
    bl_idname = "bt.add_module_at_point"
    bl_label = "Add Module At Point"
    bl_options = {'REGISTER', 'UNDO'}

    module_type: bpy.props.StringProperty()
    use_existing: bpy.props.BoolProperty(default=False)

    def execute(self, context):
        from .config_loader import config_from_armature, store_config_on_armature
        from .modules import get_module_class

        arm_obj = context.active_object
        if not arm_obj or arm_obj.type != 'ARMATURE':
            self.report({'ERROR'}, "No armature selected")
            return {'CANCELLED'}

        cls = get_module_class(self.module_type)
        if cls is None:
            self.report({'ERROR'}, f"Unknown module: {self.module_type}")
            return {'CANCELLED'}

        bone_name = context.window_manager.get("bt_overlay_bone", "")
        bone_pos_list = context.window_manager.get("bt_overlay_pos", None)
        bone_pos = Vector(bone_pos_list) if bone_pos_list else context.scene.cursor.location.copy()

        # "Map Existing Bones" — enter assignment mode
        if self.use_existing:
            if _start_assignment(self.module_type, bone_name, bone_pos):
                self.report({'INFO'}, f"Assignment mode: click bones to fill {cls.display_name} slots")
                return {'FINISHED'}

        # Direct add — create fresh bones
        cursor_pos = list(context.scene.cursor.location)
        side = _detect_side(bone_name)

        config_entry = {
            "type": self.module_type,
            "name": cls.display_name,
            "side": side,
            "parent_bone": bone_name,
            "position": cursor_pos,
            "options": {},
        }

        existing = config_from_armature(arm_obj) or {
            "name": "Rig", "modules": [], "global_options": {}
        }
        existing["modules"].append(config_entry)
        store_config_on_armature(arm_obj, existing)

        self.report({'INFO'}, f"Added {cls.display_name} at {bone_name} ({side})")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Modal Operator
# ---------------------------------------------------------------------------

class BT_OT_ModuleOverlay(bpy.types.Operator):
    """Interactive viewport overlay for module placement."""
    bl_idname = "bt.module_overlay"
    bl_label = "Module Overlay"
    bl_description = "Show clickable circles on bones for module placement"

    def modal(self, context, event):
        global _hover_info, _active

        if not _active:
            self._cleanup(context)
            return {'CANCELLED'}

        obj = context.active_object

        # ESC handling
        if event.type == 'ESC':
            if _assign_mode:
                _cancel_assignment()
                self.report({'INFO'}, "Assignment cancelled")
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}
            else:
                _active = False
                self._cleanup(context)
                self.report({'INFO'}, "Module overlay disabled")
                return {'CANCELLED'}

        # Deactivate on pose mode or armature deselect
        if (obj and obj.mode == 'POSE') or not obj or obj.type != 'ARMATURE':
            if _assign_mode:
                _cancel_assignment()
            _active = False
            self._cleanup(context)
            return {'CANCELLED'}

        # --- Assignment mode ---
        if _assign_mode:
            return self._handle_assignment(context, event)

        # --- Normal mode ---
        if event.type == 'MOUSEMOVE':
            hit = _hit_test(context, event.mouse_region_x, event.mouse_region_y)
            if hit:
                _hover_info["bone"] = hit[0]
                _hover_info["end"] = hit[1]
                _hover_info["pos"] = hit[2]
                _update_hover_target(hit[0], hit[1])
            else:
                _hover_info["bone"] = None
                _hover_info["end"] = None
                _hover_info["pos"] = None
                _update_hover_target(None, None)
            context.area.tag_redraw()
            return {'PASS_THROUGH'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            hit = _hit_test(context, event.mouse_region_x, event.mouse_region_y)
            if hit:
                bone_name, end, world_pos = hit
                context.scene.cursor.location = world_pos
                context.window_manager["bt_overlay_bone"] = bone_name
                context.window_manager["bt_overlay_end"] = end
                context.window_manager["bt_overlay_pos"] = list(world_pos)
                bpy.ops.wm.call_menu(name="BT_MT_ModulePickerMenu")
                return {'RUNNING_MODAL'}

        return {'PASS_THROUGH'}

    def _handle_assignment(self, context, event):
        """Handle events during bone slot assignment mode."""
        global _assign_current, _hover_info

        if event.type == 'MOUSEMOVE':
            hit = _hit_test_bone(context, event.mouse_region_x, event.mouse_region_y)
            if hit:
                _hover_info["bone"] = hit[0]
                _hover_info["end"] = hit[1]
                _hover_info["pos"] = hit[2]
                _update_hover_target(hit[0], hit[1])
            else:
                _hover_info["bone"] = None
                _hover_info["end"] = None
                _hover_info["pos"] = None
                _update_hover_target(None, None)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Left click — assign bone to current slot
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            hit = _hit_test_bone(context, event.mouse_region_x, event.mouse_region_y)
            if hit and _assign_current < len(_assign_slots):
                bone_name = hit[0]
                role = _assign_slots[_assign_current][0]
                _assign_mapping[role] = bone_name
                _assign_current += 1

                if _assign_current >= len(_assign_slots):
                    # All slots filled — auto-finish
                    msg = _finish_assignment(context)
                    self.report({'INFO'}, msg or "Module added")

                context.area.tag_redraw()
                return {'RUNNING_MODAL'}

        # Right click — skip current slot
        if event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
            if _assign_current < len(_assign_slots):
                _assign_current += 1
                if _assign_current >= len(_assign_slots):
                    msg = _finish_assignment(context)
                    self.report({'INFO'}, msg or "Module added")
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}

        # Enter — confirm early (finish with partial mapping)
        if event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            msg = _finish_assignment(context)
            self.report({'INFO'}, msg or "Module added")
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        global _draw_handle, _active, _anim_current, _anim_prev

        if _active:
            if _assign_mode:
                _cancel_assignment()
            _active = False
            self._cleanup(context)
            self.report({'INFO'}, "Module overlay disabled")
            return {'CANCELLED'}

        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Select an armature first")
            return {'CANCELLED'}

        if obj.mode == 'POSE':
            self.report({'WARNING'}, "Module overlay not available in pose mode")
            return {'CANCELLED'}

        _active = True
        _hover_info["bone"] = None
        _hover_info["end"] = None
        _hover_info["pos"] = None
        _anim_current = None
        _anim_prev = None

        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_callback, (context,), 'WINDOW', 'POST_PIXEL'
        )

        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        self.report({'INFO'}, "Module overlay enabled — click bone circles to add modules")
        return {'RUNNING_MODAL'}

    def _cleanup(self, context):
        global _draw_handle, _hover_info
        if _draw_handle:
            bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
            _draw_handle = None
        _hover_info = {"bone": None, "end": None, "pos": None}
        if context.area:
            context.area.tag_redraw()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (
    BT_MT_ModulePickerMenu,
    BT_OT_AddModuleAtPoint,
    BT_OT_ModuleOverlay,
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
