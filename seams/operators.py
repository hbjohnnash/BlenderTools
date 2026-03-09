"""Seam creation operators."""

import threading

import bmesh
import bpy

from . import algorithms
from .presets import get_preset_items


class BT_OT_SeamByAngle(bpy.types.Operator):
    bl_idname = "bt.seam_by_angle"
    bl_label = "Seams by Angle"
    bl_description = "Mark seams where face angle exceeds threshold"
    bl_options = {'REGISTER', 'UNDO'}

    threshold: bpy.props.FloatProperty(
        name="Angle Threshold",
        description="Edges sharper than this angle become seams",
        default=30.0,
        min=0.0,
        max=180.0,
        subtype='ANGLE',
    )
    clear_existing: bpy.props.BoolProperty(
        name="Clear Existing",
        description="Clear existing seams before marking",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None
                and context.active_object.type == 'MESH')

    def execute(self, context):
        obj = context.active_object
        bpy.ops.object.mode_set(mode='EDIT')
        bm = bmesh.from_edit_mesh(obj.data)

        if self.clear_existing:
            algorithms.clear_all_seams(bm)

        count = algorithms.mark_seams_by_angle(bm, self.threshold)
        bmesh.update_edit_mesh(obj.data)

        self.report({'INFO'}, f"Marked {count} seam edges by angle")
        return {'FINISHED'}


class BT_OT_SeamByMaterial(bpy.types.Operator):
    bl_idname = "bt.seam_by_material"
    bl_label = "Seams by Material"
    bl_description = "Mark seams at material boundaries"
    bl_options = {'REGISTER', 'UNDO'}

    clear_existing: bpy.props.BoolProperty(
        name="Clear Existing",
        description="Clear existing seams before marking",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None
                and context.active_object.type == 'MESH')

    def execute(self, context):
        obj = context.active_object
        bpy.ops.object.mode_set(mode='EDIT')
        bm = bmesh.from_edit_mesh(obj.data)

        if self.clear_existing:
            algorithms.clear_all_seams(bm)

        count = algorithms.mark_seams_by_material(bm)
        bmesh.update_edit_mesh(obj.data)

        self.report({'INFO'}, f"Marked {count} seam edges by material")
        return {'FINISHED'}


class BT_OT_SeamByHardEdge(bpy.types.Operator):
    bl_idname = "bt.seam_by_hard_edge"
    bl_label = "Seams by Hard Edge"
    bl_description = "Mark seams at sharp/hard edges (Blender 5.0 attributes)"
    bl_options = {'REGISTER', 'UNDO'}

    clear_existing: bpy.props.BoolProperty(
        name="Clear Existing",
        description="Clear existing seams before marking",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None
                and context.active_object.type == 'MESH')

    def execute(self, context):
        obj = context.active_object
        mesh = obj.data

        bpy.ops.object.mode_set(mode='EDIT')
        bm = bmesh.from_edit_mesh(mesh)

        if self.clear_existing:
            algorithms.clear_all_seams(bm)

        count = algorithms.mark_seams_by_hard_edge(bm, mesh)
        bmesh.update_edit_mesh(mesh)

        if count == 0:
            self.report({'WARNING'}, "No sharp edges found (no sharp_edge attribute)")
        else:
            self.report({'INFO'}, f"Marked {count} seam edges from hard edges")
        return {'FINISHED'}


class BT_OT_SeamIslandAware(bpy.types.Operator):
    bl_idname = "bt.seam_island_aware"
    bl_label = "Island-Aware Seams"
    bl_description = "Mark seams with UV island count and stretch control"
    bl_options = {'REGISTER', 'UNDO'}

    max_islands: bpy.props.IntProperty(
        name="Max Islands",
        description="Maximum UV island count (0 = no limit)",
        default=0,
        min=0,
    )
    max_stretch: bpy.props.FloatProperty(
        name="Max Stretch",
        description="Maximum acceptable UV stretch",
        default=0.5,
        min=0.0,
        max=1.0,
    )
    clear_existing: bpy.props.BoolProperty(
        name="Clear Existing",
        description="Clear existing seams before marking",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None
                and context.active_object.type == 'MESH')

    def execute(self, context):
        obj = context.active_object
        bpy.ops.object.mode_set(mode='EDIT')
        bm = bmesh.from_edit_mesh(obj.data)

        if self.clear_existing:
            algorithms.clear_all_seams(bm)

        count = algorithms.mark_seams_island_aware(bm, self.max_islands, self.max_stretch)
        bmesh.update_edit_mesh(obj.data)

        self.report({'INFO'}, f"Marked {count} seam edges (island-aware)")
        return {'FINISHED'}


class BT_OT_SeamProjection(bpy.types.Operator):
    bl_idname = "bt.seam_projection"
    bl_label = "Seams by Projection"
    bl_description = "Mark seams based on projection mapping (box/cylinder/sphere)"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(
        name="Projection Mode",
        description="Type of projection mapping",
        items=[
            ('BOX', "Box", "Box projection seams"),
            ('CYLINDER', "Cylinder", "Cylindrical projection seams"),
            ('SPHERE', "Sphere", "Spherical projection seams"),
        ],
        default='BOX',
    )
    clear_existing: bpy.props.BoolProperty(
        name="Clear Existing",
        description="Clear existing seams before marking",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None
                and context.active_object.type == 'MESH')

    def execute(self, context):
        obj = context.active_object
        bpy.ops.object.mode_set(mode='EDIT')
        bm = bmesh.from_edit_mesh(obj.data)

        if self.clear_existing:
            algorithms.clear_all_seams(bm)

        count = algorithms.mark_seams_projection(bm, obj, self.mode)
        bmesh.update_edit_mesh(obj.data)

        self.report({'INFO'}, f"Marked {count} seam edges ({self.mode} projection)")
        return {'FINISHED'}


class BT_OT_SeamPreset(bpy.types.Operator):
    bl_idname = "bt.seam_preset"
    bl_label = "Apply Seam Preset"
    bl_description = "Apply a predefined seam preset combination"
    bl_options = {'REGISTER', 'UNDO'}

    preset: bpy.props.EnumProperty(
        name="Preset",
        description="Seam preset to apply",
        items=get_preset_items,
    )

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None
                and context.active_object.type == 'MESH')

    def execute(self, context):
        if self.preset == 'NONE':
            self.report({'WARNING'}, "No presets available")
            return {'CANCELLED'}

        obj = context.active_object
        bpy.ops.object.mode_set(mode='EDIT')
        bm = bmesh.from_edit_mesh(obj.data)

        try:
            count = algorithms.apply_seam_preset(bm, obj, self.preset)
        except FileNotFoundError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        bmesh.update_edit_mesh(obj.data)
        self.report({'INFO'}, f"Applied preset '{self.preset}': {count} seam edges")
        return {'FINISHED'}


class BT_OT_ClearSeams(bpy.types.Operator):
    bl_idname = "bt.clear_seams"
    bl_label = "Clear All Seams"
    bl_description = "Remove all seams from the active mesh"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None
                and context.active_object.type == 'MESH')

    def execute(self, context):
        obj = context.active_object
        bpy.ops.object.mode_set(mode='EDIT')
        bm = bmesh.from_edit_mesh(obj.data)
        algorithms.clear_all_seams(bm)
        bmesh.update_edit_mesh(obj.data)
        self.report({'INFO'}, "Cleared all seams")
        return {'FINISHED'}


class BT_OT_InitSeamAI(bpy.types.Operator):
    bl_idname = "bt.init_seam_ai"
    bl_label = "Initialize AI Seams"
    bl_description = (
        "Install PyTorch and download MeshCNN for neural seam prediction"
    )

    _timer = None
    _thread = None
    _finished = False
    _error = ""
    _status_msg = "Starting..."
    _progress = 0.0

    def modal(self, context, event):
        if event.type == 'TIMER':
            wm = context.window_manager
            wm.bt_ml_progress = self._progress
            wm.bt_ml_status = self._status_msg

            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()

            if self._finished:
                wm.event_timer_remove(self._timer)
                wm.bt_ml_busy = False
                wm.bt_ml_progress = 0.0
                wm.bt_ml_status = ""

                if self._error:
                    self.report({'ERROR'}, f"Initialization failed: {self._error}")
                    return {'CANCELLED'}

                self.report({'INFO'}, "AI Seams initialized — MeshCNN ready!")
                return {'FINISHED'}

        return {'PASS_THROUGH'}

    def execute(self, context):
        wm = context.window_manager
        if wm.bt_ml_busy:
            self.report({'WARNING'}, "Another ML operation is in progress")
            return {'CANCELLED'}

        wm.bt_ml_busy = True
        wm.bt_ml_progress = 0.0
        wm.bt_ml_status = "Starting initialization..."

        # Reset state for this invocation
        self._finished = False
        self._error = ""
        self._progress = 0.0
        self._status_msg = "Starting..."

        def _worker():
            try:
                from ..core.ml import dependencies, model_manager

                # Step 1: Install PyTorch if needed
                if not dependencies.check_torch_available():
                    self._status_msg = "Installing PyTorch..."
                    self._progress = 0.05

                    def on_torch_progress(p, msg=""):
                        self._progress = 0.05 + p * 0.4
                        if msg:
                            self._status_msg = msg

                    dependencies.install_torch(
                        use_gpu=True,
                        progress_callback=on_torch_progress,
                    )

                self._progress = 0.5
                self._status_msg = "Downloading MeshCNN..."

                # Step 2: Download model
                def on_progress(p, msg=""):
                    self._progress = 0.5 + p * 0.5
                    if msg:
                        self._status_msg = msg

                model_manager.install_model("meshcnn", progress_callback=on_progress)

                self._progress = 1.0
                self._status_msg = "Done!"
                self._finished = True

            except Exception as e:
                self._error = str(e)
                self._finished = True

        self._thread = threading.Thread(target=_worker, daemon=True)
        self._thread.start()

        self._timer = wm.event_timer_add(0.5, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}


class BT_OT_RemoveSeamAI(bpy.types.Operator):
    bl_idname = "bt.remove_seam_ai"
    bl_label = "Remove AI Seams Model"
    bl_description = "Delete downloaded MeshCNN model to free disk space"

    def execute(self, context):
        from ..core.ml import model_manager

        size = model_manager.get_cache_size_mb("meshcnn")
        model_manager.remove_model("meshcnn")
        self.report({'INFO'}, f"Removed MeshCNN ({size:.0f} MB freed)")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)


class BT_OT_SeamNeural(bpy.types.Operator):
    bl_idname = "bt.seam_neural"
    bl_label = "Neural Seams"
    bl_description = "AI-powered seam prediction using MeshCNN body segmentation"
    bl_options = {'REGISTER', 'UNDO'}

    clear_existing: bpy.props.BoolProperty(
        name="Clear Existing",
        description="Clear existing seams before neural prediction",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        if not (context.active_object and context.active_object.type == 'MESH'):
            return False
        from ..core.ml import model_manager
        return model_manager.is_model_installed("meshcnn")

    def execute(self, context):
        obj = context.active_object

        if self.clear_existing:
            bpy.ops.object.mode_set(mode='EDIT')
            bm = bmesh.from_edit_mesh(obj.data)
            algorithms.clear_all_seams(bm)
            bmesh.update_edit_mesh(obj.data)
            bpy.ops.object.mode_set(mode='OBJECT')

        try:
            count = algorithms.mark_seams_neural(obj)
        except Exception as e:
            self.report({'ERROR'}, f"Neural seam prediction failed: {e}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Marked {count} neural seam edges")
        return {'FINISHED'}


classes = (
    BT_OT_SeamByAngle,
    BT_OT_SeamByMaterial,
    BT_OT_SeamByHardEdge,
    BT_OT_SeamIslandAware,
    BT_OT_SeamProjection,
    BT_OT_SeamPreset,
    BT_OT_ClearSeams,
    BT_OT_InitSeamAI,
    BT_OT_RemoveSeamAI,
    BT_OT_SeamNeural,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
