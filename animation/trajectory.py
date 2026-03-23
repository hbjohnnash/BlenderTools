"""Bone trajectory visualization and editing.

Shows bone keyframes as 3D points connected by a smooth curve.
Dragging a keyframe dot updates location fcurves for IK/root bones,
or triggers IK-assisted editing for FK bones (temporarily enables IK,
snaps FK on release, keys FK rotations).
"""

from math import cos, pi, sin

import blf
import bpy
import gpu
from bpy_extras.view3d_utils import (
    location_3d_to_region_2d,
    region_2d_to_location_3d,
)
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector

from ..core.constants import (
    WRAP_CTRL_PREFIX,
)

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

# IK-assisted drag state
_ik_drag = False          # True when doing IK-assisted trajectory edit
_ik_chain_id = None
_ik_target_name = None    # IK target bone name
_ik_saved_frame = -1
_ik_saved_constraints = {}  # {mch_name: {con_name: influence}}

# Drawing constants
DOT_RADIUS = 5
KEY_DOT_RADIUS = 7
HIT_RADIUS = 12

COLOR_PAST_LINE = (0.3, 0.5, 1.0, 0.6)
COLOR_FUTURE_LINE = (0.3, 1.0, 0.5, 0.6)
COLOR_KEY_DOT = (1.0, 0.8, 0.2, 0.9)
COLOR_KEY_READONLY = (0.7, 0.7, 0.9, 0.7)  # dimmer dot for view-only keys
COLOR_KEY_IK_EDIT = (0.4, 0.9, 1.0, 0.9)  # cyan dot for IK-editable FK keys
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
    for layer in action.layers:
        for strip in layer.strips:
            for channelbag in strip.channelbags:
                for fcurve in channelbag.fcurves:
                    if fcurve.data_path == data_path:
                        for kp in fcurve.keyframe_points:
                            frames.add(int(kp.co.x))
    return sorted(frames)


def _get_bone_keyframes(armature_obj, bone_name):
    """Get frames that have ANY keyframe for this bone (location, rotation, scale)."""
    if not armature_obj.animation_data or not armature_obj.animation_data.action:
        return []

    action = armature_obj.animation_data.action
    prefix = f'pose.bones["{bone_name}"].'

    frames = set()
    for layer in action.layers:
        for strip in layer.strips:
            for channelbag in strip.channelbags:
                for fcurve in channelbag.fcurves:
                    if fcurve.data_path.startswith(prefix):
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
        # Use any keyframe (rotation, location, scale) for visualization
        key_frames = _get_bone_keyframes(armature_obj, bone_name)
        if not key_frames:
            continue

        # Check editability
        has_loc_keys = bool(_get_location_keyframes(armature_obj, bone_name))

        # Check if FK bone has IK-assisted editing available
        ik_editable = False
        pbone = armature_obj.pose.bones.get(bone_name)
        if pbone and all(pbone.lock_location) and not has_loc_keys:
            chain_id, chain_item = _find_chain_for_fk_bone(armature_obj, bone_name)
            if chain_id and chain_item and chain_item.ik_enabled:
                ik_target = _find_ik_target(armature_obj, chain_id)
                if ik_target:
                    ik_editable = True

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
            'editable': has_loc_keys,
            'ik_editable': ik_editable,
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

    for layer in action.layers:
        for strip in layer.strips:
            for channelbag in strip.channelbags:
                for fcurve in channelbag.fcurves:
                    if fcurve.data_path == data_path:
                        idx = fcurve.array_index
                        for kp in fcurve.keyframe_points:
                            if abs(kp.co.x - frame) < 0.5:
                                kp.co.y = new_location[idx]
                                fcurve.update()
                                break


# ---------------------------------------------------------------------------
# IK-assisted trajectory editing
# ---------------------------------------------------------------------------

def _find_chain_for_fk_bone(armature_obj, bone_name):
    """Find the chain_id an FK CTRL bone belongs to, and whether it has IK."""
    sd = getattr(armature_obj, 'bt_scan', None)
    if not sd or not sd.has_wrap_rig:
        return None, None

    if not bone_name.startswith(WRAP_CTRL_PREFIX):
        return None, None

    suffix = bone_name[len(WRAP_CTRL_PREFIX):]
    if "_FK_" not in suffix:
        return None, None

    # Match against known chain IDs (longest first for IDs with underscores)
    for chain in sorted(sd.chains, key=lambda c: len(c.chain_id), reverse=True):
        cid = chain.chain_id
        if suffix.startswith(cid + "_FK_"):
            return cid, chain
    return None, None


def _temp_enable_ik(armature_obj, chain_id):
    """Temporarily enable IK via the custom property. Returns saved state."""
    from ..rigging.scanner.wrap_assembly import _ik_switch_prop_name
    prop_name = _ik_switch_prop_name(chain_id)
    saved = {
        '_prop_name': prop_name,
        '_prop_value': armature_obj.get(prop_name, 0.0),
    }
    armature_obj[prop_name] = 1.0
    return saved


def _restore_constraints(armature_obj, saved):
    """Restore the ik_switch property from saved state."""
    prop_name = saved.get('_prop_name')
    prop_value = saved.get('_prop_value', 0.0)
    if prop_name:
        armature_obj[prop_name] = prop_value
        return

    # Legacy fallback: restore individual constraint influences
    for mch_name, cons in saved.items():
        if mch_name.startswith('_'):
            continue
        mch_pb = armature_obj.pose.bones.get(mch_name)
        if not mch_pb:
            continue
        for con in mch_pb.constraints:
            if con.name in cons:
                con.influence = cons[con.name]


def _find_ik_target(armature_obj, chain_id):
    """Return the IK target pose bone name for a chain, or None."""
    name = f"{WRAP_CTRL_PREFIX}{chain_id}_IK_target"
    if armature_obj.pose.bones.get(name):
        return name
    return None


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
    editable = data.get('editable', False)

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
    ik_editable = data.get('ik_editable', False)
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
        elif editable:
            color = COLOR_KEY_DOT
            radius = KEY_DOT_RADIUS
        elif ik_editable:
            color = COLOR_KEY_IK_EDIT
            radius = KEY_DOT_RADIUS
        else:
            color = COLOR_KEY_READONLY
            radius = KEY_DOT_RADIUS - 1

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
        has_editable = any(d.get('editable') for d in _cache.values())
        has_ik_editable = any(d.get('ik_editable') for d in _cache.values())
        hint = f"Trajectory: {names}  [ESC to exit"
        if has_editable:
            hint += ", drag dots to edit"
        if has_ik_editable:
            hint += ", drag cyan dots for IK-assisted edit"
        hint += "]"
        _draw_header_hint(context, hint)


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
        global _ik_drag, _ik_chain_id, _ik_target_name
        global _ik_saved_frame, _ik_saved_constraints

        if not _active:
            self._cleanup(context)
            return {'CANCELLED'}

        obj = context.active_object
        if not obj or obj.type != 'ARMATURE' or context.mode != 'POSE':
            _active = False
            self._cleanup(context)
            return {'CANCELLED'}

        # ESC exits trajectory mode (or cancels drag)
        if event.type == 'ESC' and event.value == 'PRESS':
            if _dragging:
                if _ik_drag:
                    # Cancel IK-assisted drag: restore everything
                    _restore_constraints(obj, _ik_saved_constraints)
                    context.scene.frame_set(_ik_saved_frame)
                    context.view_layer.update()
                    _ik_drag = False
                    _ik_saved_constraints = {}
                _dragging = False
                _build_cache(context, obj, _cache_bones)
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
                depth_ref = _drag_start_world
                new_world = region_2d_to_location_3d(
                    context.region, context.space_data.region_3d,
                    (event.mouse_region_x, event.mouse_region_y), depth_ref)

                if _ik_drag:
                    # IK-assisted: move IK target, let solver update in real-time
                    ik_pb = obj.pose.bones.get(_ik_target_name)
                    if ik_pb:
                        ik_pb.matrix = Matrix.Translation(new_world)
                        context.view_layer.update()
                else:
                    # Direct location edit
                    new_loc = _world_to_bone_location(
                        _drag_M_rot_inv, _drag_M_translation,
                        _drag_armature_inv, new_world)
                    _update_location_fcurves(obj, _drag_bone, _drag_frame, new_loc)

                context.area.tag_redraw()
                return {'RUNNING_MODAL'}

            if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
                if _ik_drag:
                    # Finalize IK-assisted drag: snap FK, key FK, restore
                    self._finalize_ik_drag(context, obj)
                _dragging = False
                _ik_drag = False
                _build_cache(context, obj, _cache_bones)
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}

            return {'RUNNING_MODAL'}

        # --- Click to start drag ---
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            hit = _hit_test_keyframe(context, event.mouse_region_x, event.mouse_region_y)
            if hit:
                bone_name, frame, world_pos = hit
                pbone = obj.pose.bones.get(bone_name)
                if not pbone:
                    return {'RUNNING_MODAL'}

                if all(pbone.lock_location):
                    # FK bone — try IK-assisted drag
                    return self._start_ik_drag(
                        context, obj, pbone, bone_name, frame, world_pos)

                # Direct location drag (IK targets, root, COG)
                scene = context.scene
                original_frame = scene.frame_current
                scene.frame_set(frame)

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

    def _start_ik_drag(self, context, obj, pbone, bone_name, frame, world_pos):
        """Start an IK-assisted trajectory drag for an FK bone."""
        global _dragging, _drag_bone, _drag_frame, _drag_start_world
        global _ik_drag, _ik_chain_id, _ik_target_name
        global _ik_saved_frame, _ik_saved_constraints

        chain_id, chain_item = _find_chain_for_fk_bone(obj, bone_name)
        if not chain_id or not chain_item or not chain_item.ik_enabled:
            self.report({'INFO'}, f"{bone_name}: no IK available for this chain")
            return {'RUNNING_MODAL'}

        ik_target = _find_ik_target(obj, chain_id)
        if not ik_target:
            self.report({'INFO'}, f"{bone_name}: no IK target found")
            return {'RUNNING_MODAL'}

        # Save state and set up
        scene = context.scene
        _ik_saved_frame = scene.frame_current
        scene.frame_set(frame)

        # Snap IK to current FK pose before enabling IK
        from ..rigging.scanner.wrap_assembly import snap_ik_to_fk
        snap_ik_to_fk(obj, chain_id)

        # Temporarily enable IK constraints
        _ik_saved_constraints = _temp_enable_ik(obj, chain_id)
        context.view_layer.update()

        _dragging = True
        _ik_drag = True
        _ik_chain_id = chain_id
        _ik_target_name = ik_target
        _drag_bone = bone_name
        _drag_frame = frame
        _drag_start_world = world_pos.copy()

        self.report({'INFO'}, f"IK-assisted drag on {bone_name}")
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def _finalize_ik_drag(self, context, obj):
        """Finalize IK-assisted drag: snap FK to IK, key FK, restore."""
        global _ik_saved_constraints

        from ..rigging.scanner.wrap_assembly import snap_fk_to_ik
        from .smart_keyframe import _get_chain_fk_pbones, _key_rotation

        sd = obj.bt_scan
        frame = _drag_frame

        # Snap FK bones to match the IK-solved pose
        snap_fk_to_ik(obj, _ik_chain_id)

        # Key FK rotations (and location for COG bones)
        chain_fk = _get_chain_fk_pbones(obj, sd, _ik_chain_id)
        for fk_pb in chain_fk:
            _key_rotation(fk_pb, frame)
            if not all(fk_pb.lock_location):
                fk_pb.keyframe_insert('location', frame=frame)

        # Restore constraints to original state (back to FK mode)
        _restore_constraints(obj, _ik_saved_constraints)
        _ik_saved_constraints = {}

        # Restore original frame
        context.scene.frame_set(_ik_saved_frame)
        context.view_layer.update()

        self.report({'INFO'},
                    f"Keyed FK on {_ik_chain_id} @ frame {frame}")

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
        global _ik_drag, _ik_chain_id, _ik_target_name
        global _ik_saved_frame, _ik_saved_constraints
        _dragging = False
        _ik_drag = False
        _ik_chain_id = None
        _ik_target_name = None
        _ik_saved_frame = -1
        _ik_saved_constraints = {}
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
