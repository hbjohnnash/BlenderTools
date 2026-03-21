"""Onion skinning / ghost frames for armatures with child meshes.

Evaluates meshes at past/future frames and draws them as
semi-transparent GPU batches. Camera-independent (world-space cached).
Cache rebuilds only on frame change for efficiency.

Proxy meshes (decimated LODs) are created once on activation to speed up
per-frame ghost evaluation.
"""

import bpy
import gpu
from gpu_extras.batch import batch_for_shader

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_active = False
_draw_handle = None
_ghost_batches = {}   # {frame: [batch, ...]}
_ghost_colors = {}    # {frame: (r, g, b, a)}
_last_frame = -1
_last_armature = ""

# Proxy LOD state
_proxy_objects = []
_PROXY_COL_NAME = "BT_OnionSkin_Proxy"

# Default settings (overridden by scene properties when available)
DEFAULT_COUNT_BEFORE = 3
DEFAULT_COUNT_AFTER = 3
DEFAULT_FRAME_STEP = 1
DEFAULT_OPACITY = 0.25
DEFAULT_PROXY_RATIO = 0.25

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
        'selected_keys': getattr(scene, 'bt_onion_selected_keys', False),
        'proxy_ratio': getattr(scene, 'bt_onion_proxy_ratio', DEFAULT_PROXY_RATIO),
    }


def _get_action_keyframes(armature_obj, selected_only=False):
    """Collect unique keyframe times from user-keyed pose bone transforms.

    Only considers location/rotation/scale channels on pose bones —
    ignores constraint influences and other auto-keyed properties so
    ghosts only appear at frames where the user actually posed.

    If *selected_only* is True, only keyframes currently selected in the
    Dope Sheet / Action Editor are included.
    """
    if not armature_obj.animation_data or not armature_obj.animation_data.action:
        return []

    # Pose bone transform data_paths end with one of these suffixes
    _POSE_SUFFIXES = (
        ".location",
        ".rotation_quaternion",
        ".rotation_euler",
        ".rotation_axis_angle",
        ".scale",
    )

    action = armature_obj.animation_data.action
    frames = set()
    for layer in action.layers:
        for strip in layer.strips:
            for channelbag in strip.channelbags:
                for fcurve in channelbag.fcurves:
                    dp = fcurve.data_path
                    if not dp.startswith('pose.bones['):
                        continue
                    if not any(dp.endswith(s) for s in _POSE_SUFFIXES):
                        continue
                    for kp in fcurve.keyframe_points:
                        if selected_only and not kp.select_control_point:
                            continue
                        frames.add(int(kp.co.x))
    return sorted(frames)


# ---------------------------------------------------------------------------
# Proxy mesh management
# ---------------------------------------------------------------------------

def _create_proxy_meshes(context, armature_obj, ratio):
    """Create decimated proxy meshes for fast ghost evaluation.

    Duplicates each child mesh, applies a Decimate modifier to bake
    the low-poly geometry, then adds an Armature modifier so the proxy
    deforms with the rig.  Called once when onion skin is enabled.
    """
    global _proxy_objects
    _destroy_proxy_meshes()

    if ratio >= 1.0:
        return  # full quality, use originals

    mesh_children = [c for c in armature_obj.children if c.type == 'MESH']
    if not mesh_children:
        return

    # Create hidden collection
    proxy_col = bpy.data.collections.new(_PROXY_COL_NAME)
    context.scene.collection.children.link(proxy_col)

    wm = context.window_manager
    total = len(mesh_children)
    wm.progress_begin(0, total)
    context.window.cursor_set('WAIT')

    # Phase 1: create all proxy objects with Decimate modifier
    pending = []
    for i, child in enumerate(mesh_children):
        wm.progress_update(i)

        new_obj = child.copy()
        new_obj.data = child.data.copy()
        new_obj.name = f"BT_Proxy_{child.name}"
        proxy_col.objects.link(new_obj)

        # Strip all modifiers
        for mod in list(new_obj.modifiers):
            new_obj.modifiers.remove(mod)

        # Remove shape keys (required for Decimate to evaluate)
        if new_obj.data.shape_keys:
            new_obj.shape_key_clear()

        # Add Decimate only
        decimate = new_obj.modifiers.new("BT_Decimate", 'DECIMATE')
        decimate.ratio = ratio
        decimate.use_collapse_triangulate = True
        pending.append(new_obj)

    # Phase 2: single depsgraph update to evaluate all Decimate modifiers
    context.view_layer.update()
    depsgraph = context.evaluated_depsgraph_get()

    # Phase 3: bake decimated geometry and swap in Armature modifier
    for new_obj in pending:
        eval_obj = new_obj.evaluated_get(depsgraph)
        temp_mesh = eval_obj.to_mesh()

        if temp_mesh and len(temp_mesh.vertices) > 0:
            final_mesh = temp_mesh.copy()
            final_mesh.name = f"BT_Proxy_{new_obj.data.name}"
            eval_obj.to_mesh_clear()

            old_mesh = new_obj.data
            new_obj.data = final_mesh
            bpy.data.meshes.remove(old_mesh)
        else:
            if temp_mesh:
                eval_obj.to_mesh_clear()

        # Replace Decimate with Armature
        new_obj.modifiers.clear()
        arm_mod = new_obj.modifiers.new("BT_Armature", 'ARMATURE')
        arm_mod.object = armature_obj

        # Hidden but still evaluated by depsgraph
        new_obj.hide_set(True)
        new_obj.hide_render = True

        _proxy_objects.append(new_obj)

    wm.progress_end()
    context.window.cursor_set('DEFAULT')


def _destroy_proxy_meshes():
    """Remove all proxy objects and their mesh data."""
    global _proxy_objects

    for obj in _proxy_objects:
        mesh = obj.data
        bpy.data.objects.remove(obj)
        if mesh and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    _proxy_objects = []

    col = bpy.data.collections.get(_PROXY_COL_NAME)
    if col:
        bpy.data.collections.remove(col)


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
        selected_only = settings['selected_keys']
        all_keys = _get_action_keyframes(armature_obj,
                                         selected_only=selected_only)
        keys_before = [f for f in all_keys if f < current]
        keys_after = [f for f in all_keys if f > current]
        if selected_only:
            # Show ALL selected keyframes — no count limits
            frames_before = keys_before
            frames_after = keys_after
        else:
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

    # Use proxy meshes if available, otherwise originals
    ghost_meshes = (_proxy_objects if _proxy_objects
                    else [c for c in armature_obj.children if c.type == 'MESH'])

    all_ghost_frames = frames_before + frames_after

    for frame in all_ghost_frames:
        scene.frame_set(frame)
        depsgraph = context.evaluated_depsgraph_get()

        batches = []
        for child in ghost_meshes:
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
            _destroy_proxy_meshes()
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

        # Create proxy LODs (shows progress bar + wait cursor)
        settings = _get_settings(context)
        _create_proxy_meshes(context, obj, settings['proxy_ratio'])

        _build_ghost_cache(context, obj)

        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_callback, (context,), 'WINDOW', 'POST_VIEW')

        if context.area:
            context.area.tag_redraw()

        n_proxies = len(_proxy_objects)
        if n_proxies:
            self.report({'INFO'}, f"Onion skin enabled ({n_proxies} proxy meshes)")
        else:
            self.report({'INFO'}, "Onion skin enabled (full quality)")
        return {'FINISHED'}


class BT_OT_OnionSkinRefresh(bpy.types.Operator):
    """Force refresh onion skin cache and rebuild proxy meshes."""
    bl_idname = "bt.onion_skin_refresh"
    bl_label = "Refresh Onion Skin"

    def execute(self, context):
        if _active and context.active_object:
            obj = context.active_object
            settings = _get_settings(context)
            _create_proxy_meshes(context, obj, settings['proxy_ratio'])
            _build_ghost_cache(context, obj)
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
    bpy.types.Scene.bt_onion_selected_keys = bpy.props.BoolProperty(
        name="Selected Only", default=False,
        description="Show ghosts only at keyframes selected in the Dope Sheet",
    )
    bpy.types.Scene.bt_onion_proxy_ratio = bpy.props.FloatProperty(
        name="Ghost Detail", default=0.25, min=0.05, max=1.0,
        description="Proxy mesh detail (lower = faster, 1.0 = full quality)",
        subtype='FACTOR',
    )


def unregister():
    global _active, _draw_handle
    if _draw_handle:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None
    _active = False
    _clear_cache()

    _destroy_proxy_meshes()

    for attr in ('bt_onion_before', 'bt_onion_after', 'bt_onion_step', 'bt_onion_opacity',
                 'bt_onion_use_keyframes', 'bt_onion_selected_keys', 'bt_onion_proxy_ratio'):
        if hasattr(bpy.types.Scene, attr):
            delattr(bpy.types.Scene, attr)

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
