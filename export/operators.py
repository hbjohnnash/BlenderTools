"""Export subsystem operators."""

import bpy
from bpy.props import BoolProperty, FloatProperty, StringProperty


class BT_OT_ScaleRig(bpy.types.Operator):
    """Scale an armature rig and update keyframes, constraints, and config"""
    bl_idname = "bt.scale_rig"
    bl_label = "Scale Rig"
    bl_options = {'REGISTER', 'UNDO'}

    factor: FloatProperty(
        name="Scale Factor",
        description="Multiply all distances by this factor",
        default=1.0,
        min=0.001,
        soft_min=0.01,
        soft_max=1000.0,
    )

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None and
                context.active_object.type == 'ARMATURE')

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        from .scale_rig import scale_rig

        armature = context.active_object
        stats = scale_rig(armature, self.factor)

        self.report({'INFO'},
                    f"Scaled {stats['bones_scaled']} bones, "
                    f"{stats['actions_scaled']} actions, "
                    f"{stats['meshes_scaled']} meshes by {self.factor}x")
        return {'FINISHED'}


class BT_OT_ExportToUE(bpy.types.Operator):
    """Export armature and meshes as UE-ready FBX (100x scale, 0.01 export)"""
    bl_idname = "bt.export_to_ue"
    bl_label = "Export to UE"
    bl_options = {'REGISTER'}

    output_dir: StringProperty(
        name="Output Directory",
        description="Directory to save FBX files",
        subtype='DIR_PATH',
        default="//export/",
    )

    export_mesh: BoolProperty(
        name="Export Mesh",
        description="Export skeletal mesh FBX",
        default=True,
    )

    export_anim: BoolProperty(
        name="Export Animation",
        description="Export animation FBX",
        default=True,
    )

    separate_anim: BoolProperty(
        name="Separate Animations",
        description="Export each action as a separate FBX file",
        default=False,
    )

    ue_naming: BoolProperty(
        name="UE Naming",
        description="Add SK_/A_ prefixes to filenames",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None and
                context.active_object.type == 'ARMATURE')

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def execute(self, context):
        from .ue_export import export_to_ue

        armature = context.active_object
        meshes = [c for c in armature.children if c.type == 'MESH']

        output_dir = bpy.path.abspath(self.output_dir)

        result = export_to_ue(
            armature, meshes, output_dir,
            export_mesh=self.export_mesh,
            export_anim=self.export_anim,
            separate_anim=self.separate_anim,
            ue_naming=self.ue_naming,
        )

        file_count = len(result.get("files", []))
        self.report({'INFO'}, f"Exported {file_count} FBX file(s) to {output_dir}")
        return {'FINISHED'}


classes = (
    BT_OT_ScaleRig,
    BT_OT_ExportToUE,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
