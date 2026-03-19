"""Seam creation operators."""

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


classes = (
    BT_OT_SeamByAngle,
    BT_OT_SeamByMaterial,
    BT_OT_SeamByHardEdge,
    BT_OT_SeamIslandAware,
    BT_OT_SeamProjection,
    BT_OT_SeamPreset,
    BT_OT_ClearSeams,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
