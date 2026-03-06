"""Rigging operators — add module, remove module, generate rig, load/save config."""

import bpy
import json
from .modules import get_module_items, get_module_class, MODULE_REGISTRY
from .config_loader import (
    instantiate_modules, load_rig_config, save_rig_config,
    config_from_armature, store_config_on_armature, list_rig_configs,
)
from .assembly import assemble_rig, disassemble_rig


class BT_OT_AddRigModule(bpy.types.Operator):
    bl_idname = "bt.add_rig_module"
    bl_label = "Add Rig Module"
    bl_description = "Add a rig module at the 3D cursor position"
    bl_options = {'REGISTER', 'UNDO'}

    module_type: bpy.props.EnumProperty(
        name="Module Type",
        items=get_module_items,
    )
    name: bpy.props.StringProperty(
        name="Module Name",
        default="",
        description="Custom name for this module instance",
    )
    side: bpy.props.EnumProperty(
        name="Side",
        items=[
            ('C', "Center", "Center"),
            ('L', "Left", "Left"),
            ('R', "Right", "Right"),
        ],
        default='C',
    )

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None
                and context.active_object.type == 'ARMATURE')

    def execute(self, context):
        arm_obj = context.active_object
        cursor_pos = list(context.scene.cursor.location)

        # Build module config
        cls = get_module_class(self.module_type)
        if cls is None:
            self.report({'ERROR'}, f"Unknown module type: {self.module_type}")
            return {'CANCELLED'}

        config = {
            "type": self.module_type,
            "name": self.name or cls.display_name,
            "side": self.side,
            "parent_bone": "",
            "position": cursor_pos,
            "options": {},
        }

        # Load existing config or create new
        existing = config_from_armature(arm_obj) or {"name": "Rig", "modules": [], "global_options": {}}
        existing["modules"].append(config)
        store_config_on_armature(arm_obj, existing)

        self.report({'INFO'}, f"Added {cls.display_name} module ({self.side})")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class BT_OT_RemoveRigModule(bpy.types.Operator):
    bl_idname = "bt.remove_rig_module"
    bl_label = "Remove Last Module"
    bl_description = "Remove the last added rig module"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.active_object and context.active_object.type == 'ARMATURE':
            config = config_from_armature(context.active_object)
            return config and len(config.get("modules", [])) > 0
        return False

    def execute(self, context):
        arm_obj = context.active_object
        config = config_from_armature(arm_obj)
        removed = config["modules"].pop()
        store_config_on_armature(arm_obj, config)
        self.report({'INFO'}, f"Removed module: {removed.get('name', removed.get('type'))}")
        return {'FINISHED'}


class BT_OT_GenerateRig(bpy.types.Operator):
    bl_idname = "bt.generate_rig"
    bl_label = "Generate Rig"
    bl_description = "Generate the full rig from stored module configuration"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.active_object and context.active_object.type == 'ARMATURE':
            config = config_from_armature(context.active_object)
            return config and len(config.get("modules", [])) > 0
        return False

    def execute(self, context):
        arm_obj = context.active_object
        config = config_from_armature(arm_obj)

        # Clear existing generated bones
        disassemble_rig(arm_obj)

        # Instantiate and assemble
        try:
            modules = instantiate_modules(config)
            bone_names = assemble_rig(arm_obj, modules)
        except Exception as e:
            self.report({'ERROR'}, f"Rig generation failed: {e}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Generated rig: {len(bone_names)} bones from {len(modules)} modules")
        return {'FINISHED'}


class BT_OT_LoadRigConfig(bpy.types.Operator):
    bl_idname = "bt.load_rig_config"
    bl_label = "Load Rig Config"
    bl_description = "Load a rig configuration from a preset file"
    bl_options = {'REGISTER', 'UNDO'}

    config_name: bpy.props.EnumProperty(
        name="Config",
        items=lambda self, ctx: [(n, n.replace("_", " ").title(), "") for n in list_rig_configs()] or [('NONE', "None", "")],
    )

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None
                and context.active_object.type == 'ARMATURE')

    def execute(self, context):
        if self.config_name == 'NONE':
            self.report({'WARNING'}, "No configs available")
            return {'CANCELLED'}

        arm_obj = context.active_object
        try:
            config = load_rig_config(self.config_name)
        except FileNotFoundError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        store_config_on_armature(arm_obj, config)
        self.report({'INFO'}, f"Loaded config: {self.config_name}")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class BT_OT_SaveRigConfig(bpy.types.Operator):
    bl_idname = "bt.save_rig_config"
    bl_label = "Save Rig Config"
    bl_description = "Save current rig configuration to a preset file"
    bl_options = {'REGISTER'}

    config_name: bpy.props.StringProperty(
        name="Config Name",
        default="my_rig",
    )

    @classmethod
    def poll(cls, context):
        if context.active_object and context.active_object.type == 'ARMATURE':
            return config_from_armature(context.active_object) is not None
        return False

    def execute(self, context):
        arm_obj = context.active_object
        config = config_from_armature(arm_obj)
        save_rig_config(self.config_name, config)
        self.report({'INFO'}, f"Saved config: {self.config_name}")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class BT_OT_ClearRig(bpy.types.Operator):
    bl_idname = "bt.clear_rig"
    bl_label = "Clear Generated Rig"
    bl_description = "Remove all generated rig bones (DEF/CTRL/MCH)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None
                and context.active_object.type == 'ARMATURE')

    def execute(self, context):
        removed = disassemble_rig(context.active_object)
        self.report({'INFO'}, f"Removed {len(removed)} generated bones")
        return {'FINISHED'}


classes = (
    BT_OT_AddRigModule,
    BT_OT_RemoveRigModule,
    BT_OT_GenerateRig,
    BT_OT_LoadRigConfig,
    BT_OT_SaveRigConfig,
    BT_OT_ClearRig,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
