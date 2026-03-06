"""Skinning operators — auto-weight, rigid bind, cleanup."""

import bpy
from . import algorithms


class BT_OT_AutoWeight(bpy.types.Operator):
    bl_idname = "bt.auto_weight"
    bl_label = "Auto Weight"
    bl_description = "Automatic weight painting with cleanup"
    bl_options = {'REGISTER', 'UNDO'}

    method: bpy.props.EnumProperty(
        name="Method",
        items=[
            ('HEAT_MAP', "Heat Map", "Heat diffusion based weights"),
            ('ENVELOPE', "Envelope", "Bone envelope based weights"),
            ('HYBRID', "Hybrid", "Heat map with envelope blending"),
        ],
        default='HEAT_MAP',
    )

    @classmethod
    def poll(cls, context):
        sel = context.selected_objects
        return (len(sel) >= 2 and
                any(o.type == 'MESH' for o in sel) and
                any(o.type == 'ARMATURE' for o in sel))

    def execute(self, context):
        mesh_obj = None
        arm_obj = None
        for o in context.selected_objects:
            if o.type == 'MESH' and mesh_obj is None:
                mesh_obj = o
            elif o.type == 'ARMATURE' and arm_obj is None:
                arm_obj = o

        if not mesh_obj or not arm_obj:
            self.report({'ERROR'}, "Select a mesh and an armature")
            return {'CANCELLED'}

        try:
            algorithms.auto_weight(mesh_obj, arm_obj, self.method)
        except Exception as e:
            self.report({'ERROR'}, f"Auto weight failed: {e}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Auto weight ({self.method}) applied to {mesh_obj.name}")
        return {'FINISHED'}


class BT_OT_RigidBind(bpy.types.Operator):
    bl_idname = "bt.rigid_bind"
    bl_label = "Rigid Bind"
    bl_description = "Assign each vertex 100% weight to nearest bone"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        sel = context.selected_objects
        return (len(sel) >= 2 and
                any(o.type == 'MESH' for o in sel) and
                any(o.type == 'ARMATURE' for o in sel))

    def execute(self, context):
        mesh_obj = None
        arm_obj = None
        for o in context.selected_objects:
            if o.type == 'MESH' and mesh_obj is None:
                mesh_obj = o
            elif o.type == 'ARMATURE' and arm_obj is None:
                arm_obj = o

        if not mesh_obj or not arm_obj:
            self.report({'ERROR'}, "Select a mesh and an armature")
            return {'CANCELLED'}

        bpy.ops.object.mode_set(mode='OBJECT')
        count = algorithms.rigid_bind(mesh_obj, arm_obj)
        self.report({'INFO'}, f"Rigid bind: {count} vertices assigned")
        return {'FINISHED'}


class BT_OT_WeightCleanup(bpy.types.Operator):
    bl_idname = "bt.weight_cleanup"
    bl_label = "Weight Cleanup"
    bl_description = "Remove tiny weights, limit influences, normalize"
    bl_options = {'REGISTER', 'UNDO'}

    threshold: bpy.props.FloatProperty(
        name="Threshold",
        description="Remove weights below this value",
        default=0.01,
        min=0.0,
        max=0.5,
    )
    max_influences: bpy.props.IntProperty(
        name="Max Influences",
        description="Maximum vertex groups per vertex",
        default=4,
        min=1,
        max=16,
    )

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None
                and context.active_object.type == 'MESH'
                and len(context.active_object.vertex_groups) > 0)

    def execute(self, context):
        obj = context.active_object
        bpy.ops.object.mode_set(mode='OBJECT')
        algorithms.cleanup_weights(obj, self.threshold, self.max_influences)
        self.report({'INFO'}, f"Weight cleanup complete on {obj.name}")
        return {'FINISHED'}


class BT_OT_MergeVertexGroups(bpy.types.Operator):
    bl_idname = "bt.merge_vertex_groups"
    bl_label = "Merge Vertex Groups"
    bl_description = "Merge one vertex group into another"
    bl_options = {'REGISTER', 'UNDO'}

    source: bpy.props.StringProperty(name="Source Group")
    target: bpy.props.StringProperty(name="Target Group")

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None
                and context.active_object.type == 'MESH'
                and len(context.active_object.vertex_groups) >= 2)

    def execute(self, context):
        if algorithms.merge_vertex_groups(context.active_object, self.source, self.target):
            self.report({'INFO'}, f"Merged '{self.source}' into '{self.target}'")
            return {'FINISHED'}
        self.report({'ERROR'}, "Groups not found")
        return {'CANCELLED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class BT_OT_MirrorVertexGroups(bpy.types.Operator):
    bl_idname = "bt.mirror_vertex_groups"
    bl_label = "Mirror Vertex Groups"
    bl_description = "Create mirrored vertex groups (L↔R)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None
                and context.active_object.type == 'MESH')

    def execute(self, context):
        algorithms.mirror_vertex_groups(context.active_object)
        self.report({'INFO'}, "Mirrored vertex groups")
        return {'FINISHED'}


classes = (
    BT_OT_AutoWeight,
    BT_OT_RigidBind,
    BT_OT_WeightCleanup,
    BT_OT_MergeVertexGroups,
    BT_OT_MirrorVertexGroups,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
