"""Bone trajectory visualization and editing.

Shows bone location keyframes as 3D points connected by a smooth curve.
Dragging a keyframe dot updates the location fcurve value directly.
Only operates on location channels — no rotation, no new keyframes.
"""

import bpy
import gpu
import blf
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from math import cos, sin, pi
from bpy_extras.view3d_utils import (
    location_3d_to_region_2d,
    region_2d_to_location_3d,
)
from ..core.constants import PANEL_CATEGORY

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_active = False
_draw_handle = None

# Cached trajectory data: {bone_name: {'all': [(frame, Vector)], 'keys': [(frame, Vector)]}}
_cache = {}
_cache_frame = -1  # frame when cache was built
_cache_bones = set()  # bone names in cache

# Drag state
_dragging = False
_drag_bone = None
_drag_frame = -1
_drag_start_mouse = (0, 0)
_drag_start_world = Vector()
_drag_M_rot_inv = None  # cached inverse rotation for location space
_drag_armature_inv = None
_drag_M_translation = Vector()

# Drawing constants
DOT_RADIUS = 5
KEY_DOT_RADIUS = 7
HIT_RADIUS = 12

COLOR_PAST_LINE = (0.3, 0.5, 1.0, 0.6)
COLOR_FUTURE_LINE = (0.3, 1.0, 0.5, 0.6)
COLOR_KEY_DOT = (1.0, 0.8, 0.2, 0.9)
COLOR_KEY_HOVER = (1.0, 1.0, 0.5, 1.0)
COLOR_CURRENT = (1.0, 1.0, 1.0, 1.0)
COLOR_DRAG = (1.0, 0.4, 0.2, 1.0)


# ---------------------------------------------------------------------------
# Trajectory sampling
# ---------------------------------------------------------------------------

def _get_location_keyframes(armature_obj, bone_name):
    """Get frames that have location keyframes for this bone."""
    if not armature_obj.animation_data or not armature_obj.animation_data.action:
        return []

    action = armature_obj.animation_data.action
    data_path = f'pose.bones["{bone_name}"].location'

    frames = set()
    for slot in action.slots:
        for channelbag in slot.channelbags:
            for fcurve in channelbag.fcurves:
                if fcurve.data_path == data_path:
                    for kp in fcurve.keyframe_points:
                        frames.add(int(kp.co.x))
    return sorted(frames)


def _sample_bone_positions(armature_obj, bone_name, frames):
    """Evaluate bone world head position at specific frames."""
    scene = bpy.context.scene
    original_frame = scene.frame_current
    positions = []

    for frame in frames:
        scene.frame_set(frame)
        pbone = armature_obj.pose.bones.get(bone_name)
        if pbone:
            world_pos = armature_obj.matrix_world @ pbone.head
            positions.append((frame, world_pos.copy()))

    scene.frame_set(original_frame)
    return positions


def _build_cache(context, armature_obj, bone_names):
    """Build trajectory cache for given bones."""
    global _cache, _cache_frame, _cache_bones

    scene = context.scene
    _cache_frame = scene.frame_current
    _cache_bones = set(bone_names)
    _cache = {}

    for bone_name in bone_names:
        key_frames = _get_location_keyframes(armature_obj, bone_name)
        if not key_frames:
            continue

        # Sample at keyframes
        key_positions = _sample_bone_positions(armature_obj, bone_name, key_frames)

        # Sample intermediate frames for smooth curve
        f_start = max(key_frames[0], scene.frame_start)
        f_end = min(key_frames[-1], scene.frame_end)
        step = max(1, (f_end - f_start) // 100)  # ~100 samples max
        all_frames = sorted(set(
            list(range(f_start, f_end + 1, max(step, 1))) + key_frames
        ))
        all_positions = _sample_bone_positions(armature_obj, bone_name, all_frames)

        _cache[bone_name] = {
            'all': all_positions,
            'keys': key_positions,
        }


def _invalidate_cache():
    global _cache, _cache_frame, _cache_bones
    _cache = {}
    _cache_frame = -1
    _cache_bones = set()


# ---------------------------------------------------------------------------
# Inverse transform: world position -> bone location value
# ---------------------------------------------------------------------------

def _compute_location_space(armature_obj, pose_bone):
    """Compute the matrix mapping bone-local location to armature space.

    Returns (M_rot_3x3_inverted, M_translation, armature_world_inverted).
    """
    bone = pose_bone.bone

    if pose_bone.parent:
        parent_matrix = pose_bone.parent.matrix
        parent_rest = pose_bone.parent.bone.matrix_local
        bone_rest = bone.matrix_local
        rest_relative = parent_rest.inverted() @ bone_rest
        M = parent_matrix @ rest_relative
    else:
        M = bone.matrix_local.copy()

    M_rot_inv = M.to_3x3().inverted()
    M_trans = M.translation.copy()
    arm_inv = armature_obj.matrix_world.inverted()

    return M_rot_inv, M_trans, arm_inv


def _world_to_bone_location(M_rot_inv, M_trans, arm_inv, world_pos):
    """Convert world position to bone-local location value."""
    armature_pos = arm_inv @ world_pos
    return M_rot_inv @ (armature_pos - M_trans)


def _update_location_fcurves(armature_obj, bone_name, frame, new_location):
    """Write new location values into the fcurves at the given frame."""
    action = armature_obj.animation_data.action
    data_path = f'pose.bones["{bone_name}"].location'

    for slot in action.slots:
        for channelbag in slot.channelbags:
            for fcurve in channelbag.fcurves:
                if fcurve.data_path == data_path:
                    idx = fcurve.array_index
                    for kp in fcurve.keyframe_points:
                        if abs(kp.co.x - frame) < 0.5:
                            kp.co.y = new_location[idx]
                            fcurve.update()
                            break


# ---------------------------------------------------------------------------
# GPU Drawing
# ---------------------------------------------------------------------------

def _world_to_screen(context, pos):
    region = context.region
    rv3d = context.space_data.region_3d
    if not region or not rv3d:
        return None
    return location_3d_to_region_2d(region, rv3d, pos)


def _draw_circle_2d(shader, cx, cy, radius, color, segments=16):
    verts = [(cx, cy)]
    for i in range(segments + 1):
        a = 2 * pi * i / segments
        verts.append((cx + radius * cos(a), cy + radius * sin(a)))
    indices = [(0, i, i + 1) for i in range(1, segments + 1)]
    indices[-1] = (0, segments, 1)
    batch = batch_for_shader(shader, 'TRIS', {"pos": verts}, indices=indices)
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _draw_trajectory(context, shader, bone_name, data):
    """Draw trajectory curve and keyframe dots for one bone."""
    current_frame = context.scene.frame_current
    all_pts = data['all']
    key_pts = data['keys']

    if len(all_pts) < 2:
        return

    # Draw connecting lines (past=blue, future=green)
    for i in range(len(all_pts) - 1):
        f1, p1 = all_pts[i]
        f2, p2 = all_pts[i + 1]
        s1 = _world_to_screen(context, p1)
        s2 = _world_to_screen(context, p2)
        if s1 is None or s2 is None:
            continue

        mid_frame = (f1 + f2) / 2
        if mid_frame <= current_frame:
            color = COLOR_PAST_LINE
        else:
            color = COLOR_FUTURE_LINE

        line_verts = [s1, s2]
        batch = batch_for_shader(shader, 'LINES', {"pos": line_verts})
        shader.bind()
        shader.uniform_float("color", color)
        batch.draw(shader)

    # Draw keyframe dots
    key_frames_set = {f for f, _ in key_pts}
    for frame, world_pos in key_pts:
        screen = _world_to_screen(context, world_pos)
        if screen is None:
            continue

        if _dragging and _drag_bone == bone_name and _drag_frame == frame:
            color = COLOR_DRAG
            radius = KEY_DOT_RADIUS + 2
        elif frame == current_frame:
            color = COLOR_CURRENT
            radius = KEY_DOT_RADIUS + 1
        else:
            color = COLOR_KEY_DOT
            radius = KEY_DOT_RADIUS

        _draw_circle_2d(shader, screen[0], screen[1], radius, color)

    # Draw small dots on non-keyframe positions
    for frame, world_pos in all_pts:
        if frame in key_frames_set:
            continue
        screen = _world_to_screen(context, world_pos)
        if screen is None:
            continue
        alpha = 0.3
        _draw_circle_2d(shader, screen[0], screen[1], DOT_RADIUS - 2,
                        (0.7, 0.7, 0.7, alpha))


def _draw_callback(context):
    if not _active or not _cache:
        return

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    gpu.state.line_width_set(2.0)

    for bone_name, data in _cache.items():
        _draw_trajectory(context, shader, bone_name, data)

    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')

    # Header hint
    if _dragging:
        _draw_header_hint(context, f"Dragging {_drag_bone} @ frame {_drag_frame}")
    elif _cache:
        names = ", ".join(_cache.keys())
        _draw_header_hint(context, f"Trajectory: {names}  [ESC to exit, click keyframe dots to drag]")


def _draw_header_hint(context, text):
    region = context.region
    if not region:
        return
    font_id = 0
    blf.size(font_id, 13)
    w, h = blf.dimensions(font_id, text)
    x = (region.width - w) / 2
    y = region.height - 30

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    pad = 8
    bg = [(x - pad, y - 4), (x + w + pad, y - 4),
          (x + w + pad, y + h + 4), (x - pad, y + h + 4)]
    batch = batch_for_shader(shader, 'TRIS', {"pos": bg},
                             indices=[(0, 1, 2), (0, 2, 3)])
    shader.bind()
    shader.uniform_float("color", (0.0, 0.0, 0.0, 0.6))
    batch.draw(shader)

    blf.color(font_id, 1.0, 1.0, 1.0, 0.9)
    blf.position(font_id, x, y, 0)
    blf.draw(font_id, text)


# ---------------------------------------------------------------------------
# Hit testing
# ---------------------------------------------------------------------------

def _hit_test_keyframe(context, mouse_x, mouse_y):
    """Find closest keyframe dot under mouse. Returns (bone_name, frame, world_pos) or None."""
    best = None
    best_dist = HIT_RADIUS

    for bone_name, data in _cache.items():
        for frame, world_pos in data['keys']:
            screen = _world_to_screen(context, world_pos)
            if screen is None:
                continue
            dx = mouse_x - screen[0]
            dy = mouse_y - screen[1]
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < best_dist:
                best_dist = dist
                best = (bone_name, frame, world_pos)

    return best


# ---------------------------------------------------------------------------
# Modal operator
# ---------------------------------------------------------------------------

class BT_OT_Trajectory(bpy.types.Operator):
    """Toggle bone trajectory display and editing."""
    bl_idname = "bt.trajectory"
    bl_label = "Bone Trajectory"
    bl_description = "Show/edit trajectory for selected bones"

    def modal(self, context, event):
        global _active, _dragging, _drag_bone, _drag_frame
        global _drag_start_mouse, _drag_start_world
        global _drag_M_rot_inv, _drag_armature_inv, _drag_M_translation

        if not _active:
            self._cleanup(context)
            return {'CANCELLED'}

        obj = context.active_object
        if not obj or obj.type != 'ARMATURE' or context.mode != 'POSE':
            _active = False
            self._cleanup(context)
            return {'CANCELLED'}

        # ESC exits trajectory mode
        if event.type == 'ESC' and event.value == 'PRESS':
            if _dragging:
                _dragging = False
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}
            _active = False
            self._cleanup(context)
            self.report({'INFO'}, "Trajectory disabled")
            return {'CANCELLED'}

        # Rebuild cache when selection changes or frame changes
        current_bones = {pb.name for pb in context.selected_pose_bones or []}
        if current_bones != _cache_bones or context.scene.frame_current != _cache_frame:
            if current_bones and not _dragging:
                _build_cache(context, obj, current_bones)
                context.area.tag_redraw()

        # --- Drag handling ---
        if _dragging:
            if event.type == 'MOUSEMOVE':
                # Compute new world position from mouse
                depth_ref = _drag_start_world
                new_world = region_2d_to_location_3d(
                    context.region, context.space_data.region_3d,
                    (event.mouse_region_x, event.mouse_region_y), depth_ref)

                # Convert to bone-local location
                new_loc = _world_to_bone_location(
                    _drag_M_rot_inv, _drag_M_translation,
                    _drag_armature_inv, new_world)

                _update_location_fcurves(obj, _drag_bone, _drag_frame, new_loc)
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}

            if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
                _dragging = False
                # Rebuild cache with updated positions
                _build_cache(context, obj, _cache_bones)
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}

            return {'RUNNING_MODAL'}

        # --- Click to start drag ---
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            hit = _hit_test_keyframe(context, event.mouse_region_x, event.mouse_region_y)
            if hit:
                bone_name, frame, world_pos = hit

                # Evaluate at target frame to get correct parent matrices
                scene = context.scene
                original_frame = scene.frame_current
                scene.frame_set(frame)

                pbone = obj.pose.bones.get(bone_name)
                if pbone:
                    M_rot_inv, M_trans, arm_inv = _compute_location_space(obj, pbone)
                    _dragging = True
                    _drag_bone = bone_name
                    _drag_frame = frame
                    _drag_start_mouse = (event.mouse_region_x, event.mouse_region_y)
                    _drag_start_world = world_pos.copy()
                    _drag_M_rot_inv = M_rot_inv
                    _drag_M_translation = M_trans
                    _drag_armature_inv = arm_inv

                scene.frame_set(original_frame)
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}

        # Redraw on mouse move (for hover feedback)
        if event.type == 'MOUSEMOVE':
            context.area.tag_redraw()

        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        global _active, _draw_handle

        if _active:
            _active = False
            self._cleanup(context)
            self.report({'INFO'}, "Trajectory disabled")
            return {'CANCELLED'}

        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Select an armature")
            return {'CANCELLED'}

        if context.mode != 'POSE':
            self.report({'ERROR'}, "Enter pose mode first")
            return {'CANCELLED'}

        selected = context.selected_pose_bones
        if not selected:
            self.report({'WARNING'}, "Select at least one bone")
            return {'CANCELLED'}

        _active = True
        bone_names = {pb.name for pb in selected}
        _build_cache(context, obj, bone_names)

        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_callback, (context,), 'WINDOW', 'POST_PIXEL')

        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        self.report({'INFO'}, "Trajectory enabled — click keyframe dots to drag")
        return {'RUNNING_MODAL'}

    def _cleanup(self, context):
        global _draw_handle, _dragging
        _dragging = False
        _invalidate_cache()
        if _draw_handle:
            bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
            _draw_handle = None
        if context.area:
            context.area.tag_redraw()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (
    BT_OT_Trajectory,
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
