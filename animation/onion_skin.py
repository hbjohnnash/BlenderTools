"""Onion skinning / ghost frames for armatures with child meshes.

Evaluates meshes at past/future frames and draws them as
semi-transparent GPU batches. Camera-independent (world-space cached).
Cache rebuilds only on frame change for efficiency.
"""

import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_active = False
_draw_handle = None
_ghost_batches = {}   # {frame: [batch, ...]}
_ghost_colors = {}    # {frame: (r, g, b, a)}
_last_frame = -1
_last_armature = ""

# Default settings (overridden by scene properties when available)
DEFAULT_COUNT_BEFORE = 3
DEFAULT_COUNT_AFTER = 3
DEFAULT_FRAME_STEP = 1
DEFAULT_OPACITY = 0.25

# Colors
COLOR_PAST = (0.3, 0.5, 1.0)    # blue
COLOR_FUTURE = (1.0, 0.45, 0.15)  # orange


# ---------------------------------------------------------------------------
# Settings access
# ---------------------------------------------------------------------------

def _get_settings(context):
    """Read onion skin settings from scene, with defaults."""
    scene = context.scene
    return {
        'count_before': getattr(scene, 'bt_onion_before', DEFAULT_COUNT_BEFORE),
        'count_after': getattr(scene, 'bt_onion_after', DEFAULT_COUNT_AFTER),
        'frame_step': getattr(scene, 'bt_onion_step', DEFAULT_FRAME_STEP),
        'opacity': getattr(scene, 'bt_onion_opacity', DEFAULT_OPACITY),
        'use_keyframes': getattr(scene, 'bt_onion_use_keyframes', False),
    }


def _get_action_keyframes(armature_obj):
    """Collect all unique keyframe times from the armature's action."""
    if not armature_obj.animation_data or not armature_obj.animation_data.action:
        return []

    action = armature_obj.animation_data.action
    frames = set()
    for layer in action.layers:
        for strip in layer.strips:
            for channelbag in strip.channelbags:
                for fcurve in channelbag.fcurves:
                    for kp in fcurve.keyframe_points:
                        frames.add(int(kp.co.x))
    return sorted(frames)


# ---------------------------------------------------------------------------
# Cache building
# ---------------------------------------------------------------------------

def _build_ghost_cache(context, armature_obj):
    """Evaluate child meshes at ghost frames and create GPU batches."""
    global _ghost_batches, _ghost_colors, _last_frame, _last_armature

    scene = context.scene
    current = scene.frame_current
    _last_frame = current
    _last_armature = armature_obj.name
    _ghost_batches = {}
    _ghost_colors = {}

    settings = _get_settings(context)
    count_before = settings['count_before']
    count_after = settings['count_after']
    step = settings['frame_step']
    opacity = settings['opacity']

    use_keyframes = settings['use_keyframes']

    # Collect ghost frames
    if use_keyframes:
        all_keys = _get_action_keyframes(armature_obj)
        keys_before = [f for f in all_keys if f < current]
        keys_after = [f for f in all_keys if f > current]
        frames_before = keys_before[-count_before:]  # nearest N before
        frames_after = keys_after[:count_after]       # nearest N after
    else:
        frames_before = []
        for i in range(1, count_before + 1):
            f = current - i * step
            if f >= scene.frame_start:
                frames_before.append(f)

        frames_after = []
        for i in range(1, count_after + 1):
            f = current + i * step
            if f <= scene.frame_end:
                frames_after.append(f)

    if not frames_before and not frames_after:
        return

    original_frame = scene.frame_current
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')

    all_ghost_frames = frames_before + frames_after

    for frame in all_ghost_frames:
        scene.frame_set(frame)
        depsgraph = context.evaluated_depsgraph_get()

        batches = []
        for child in armature_obj.children:
            if child.type != 'MESH':
                continue

            eval_obj = child.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()
            if mesh is None or len(mesh.vertices) == 0:
                if mesh:
                    eval_obj.to_mesh_clear()
                continue

            # Extract world-space vertices
            mat = eval_obj.matrix_world
            verts = [(mat @ v.co)[:] for v in mesh.vertices]

            # Triangulate polygons
            indices = []
            for poly in mesh.polygons:
                pv = list(poly.vertices)
                for i in range(1, len(pv) - 1):
                    indices.append((pv[0], pv[i], pv[i + 1]))

            if verts and indices:
                batch = batch_for_shader(shader, 'TRIS',
                                         {"pos": verts}, indices=indices)
                batches.append(batch)

            eval_obj.to_mesh_clear()

        if batches:
            _ghost_batches[frame] = batches

            # Compute color with distance-based fade
            if frame < current:
                idx = frames_before.index(frame)
                dist = (len(frames_before) - idx) / max(1, len(frames_before))
                alpha = opacity * (1.0 - dist * 0.6)
                _ghost_colors[frame] = (*COLOR_PAST, alpha)
            else:
                idx = frames_after.index(frame)
                dist = (idx + 1) / max(1, len(frames_after))
                alpha = opacity * (1.0 - dist * 0.6)
                _ghost_colors[frame] = (*COLOR_FUTURE, alpha)

    scene.frame_set(original_frame)


def _clear_cache():
    global _ghost_batches, _ghost_colors, _last_frame, _last_armature
    _ghost_batches = {}
    _ghost_colors = {}
    _last_frame = -1
    _last_armature = ""


# ---------------------------------------------------------------------------
# GPU Drawing
# ---------------------------------------------------------------------------

def _draw_callback(context):
    if not _active or not _ghost_batches:
        return

    obj = context.active_object
    if not obj or obj.type != 'ARMATURE' or context.mode != 'POSE':
        return

    # Rebuild cache on frame change
    if (context.scene.frame_current != _last_frame
            or obj.name != _last_armature):
        _build_ghost_cache(context, obj)

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.depth_mask_set(False)
    gpu.state.face_culling_set('BACK')

    for frame, batches in _ghost_batches.items():
        color = _ghost_colors.get(frame, (0.5, 0.5, 0.5, 0.2))
        shader.bind()
        shader.uniform_float("color", color)
        for batch in batches:
            batch.draw(shader)

    gpu.state.depth_mask_set(True)
    gpu.state.face_culling_set('NONE')
    gpu.state.depth_test_set('NONE')
    gpu.state.blend_set('NONE')


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------

class BT_OT_OnionSkin(bpy.types.Operator):
    """Toggle onion skinning for the active armature."""
    bl_idname = "bt.onion_skin"
    bl_label = "Onion Skin"
    bl_description = "Show ghost frames for armature child meshes"

    def execute(self, context):
        global _active, _draw_handle

        if _active:
            _active = False
            _clear_cache()
            if _draw_handle:
                bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
                _draw_handle = None
            if context.area:
                context.area.tag_redraw()
            self.report({'INFO'}, "Onion skin disabled")
            return {'FINISHED'}

        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Select an armature")
            return {'CANCELLED'}

        has_meshes = any(c.type == 'MESH' for c in obj.children)
        if not has_meshes:
            self.report({'ERROR'}, "Armature has no child meshes")
            return {'CANCELLED'}

        _active = True
        _build_ghost_cache(context, obj)

        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_callback, (context,), 'WINDOW', 'POST_VIEW')

        if context.area:
            context.area.tag_redraw()
        self.report({'INFO'}, "Onion skin enabled")
        return {'FINISHED'}


class BT_OT_OnionSkinRefresh(bpy.types.Operator):
    """Force refresh onion skin cache."""
    bl_idname = "bt.onion_skin_refresh"
    bl_label = "Refresh Onion Skin"

    def execute(self, context):
        if _active and context.active_object:
            _build_ghost_cache(context, context.active_object)
            if context.area:
                context.area.tag_redraw()
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (
    BT_OT_OnionSkin,
    BT_OT_OnionSkinRefresh,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.bt_onion_before = bpy.props.IntProperty(
        name="Ghosts Before", default=3, min=1, max=10,
        description="Number of ghost frames before current",
    )
    bpy.types.Scene.bt_onion_after = bpy.props.IntProperty(
        name="Ghosts After", default=3, min=1, max=10,
        description="Number of ghost frames after current",
    )
    bpy.types.Scene.bt_onion_step = bpy.props.IntProperty(
        name="Frame Step", default=1, min=1, max=10,
        description="Frame interval between ghosts",
    )
    bpy.types.Scene.bt_onion_opacity = bpy.props.FloatProperty(
        name="Opacity", default=0.25, min=0.05, max=1.0,
        description="Ghost frame opacity",
    )
    bpy.types.Scene.bt_onion_use_keyframes = bpy.props.BoolProperty(
        name="Keyframes Only", default=False,
        description="Show ghosts at keyframes instead of fixed intervals",
    )


def unregister():
    global _active, _draw_handle
    if _draw_handle:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None
    _active = False
    _clear_cache()

    for attr in ('bt_onion_before', 'bt_onion_after', 'bt_onion_step', 'bt_onion_opacity', 'bt_onion_use_keyframes'):
        if hasattr(bpy.types.Scene, attr):
            delattr(bpy.types.Scene, attr)

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
