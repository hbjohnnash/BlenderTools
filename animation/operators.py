"""Animation operators."""

import bpy
from ..core.utils import create_bone_fcurve, create_fcurve


class BT_OT_GenerateWalkCycle(bpy.types.Operator):
    bl_idname = "bt.generate_walk_cycle"
    bl_label = "Generate Walk Cycle"
    bl_description = "Generate a procedural walk cycle animation"
    bl_options = {'REGISTER', 'UNDO'}

    speed: bpy.props.FloatProperty(name="Speed", default=1.0, min=0.1, max=5.0)
    stride: bpy.props.FloatProperty(name="Stride", default=0.4, min=0.1, max=2.0)
    arm_swing: bpy.props.FloatProperty(name="Arm Swing", default=0.3, min=0.0, max=1.0)
    frame_count: bpy.props.IntProperty(name="Frame Count", default=24, min=8, max=120)

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None
                and context.active_object.type == 'ARMATURE')

    def execute(self, context):
        from .procedural.locomotion import generate_walk_cycle

        arm_obj = context.active_object
        params = {
            "speed": self.speed,
            "stride": self.stride,
            "arm_swing": self.arm_swing,
            "frame_count": self.frame_count,
        }
        keyframe_data = generate_walk_cycle(params)
        self._apply_keyframes(arm_obj, keyframe_data, "WalkCycle")
        self.report({'INFO'}, "Generated walk cycle")
        return {'FINISHED'}

    def _apply_keyframes(self, arm_obj, keyframe_data, action_name):
        """Map generic keyframe data to actual bone FCurves."""
        bone_map = self._build_bone_map(arm_obj)
        full_action = f"{arm_obj.name}_{action_name}"

        for key, frames in keyframe_data.items():
            parts = key.rsplit("_", 2)
            if len(parts) < 3:
                continue

            bone_key = "_".join(parts[:-2])
            prop_name = parts[-2]
            axis = parts[-1]

            axis_map = {"x": 0, "y": 1, "z": 2}
            idx = axis_map.get(axis, 0)

            prop_map = {"location": "location", "rotation": "rotation_euler", "scale": "scale"}
            data_prop = prop_map.get(prop_name, prop_name)

            bone_name = bone_map.get(bone_key)
            if bone_name:
                create_bone_fcurve(arm_obj, full_action, bone_name, data_prop, idx, frames)

    def _build_bone_map(self, arm_obj):
        """Build a mapping from generic names to actual bone names."""
        bones = arm_obj.data.bones
        mapping = {}

        for b in bones:
            name = b.name.lower()
            if "hip" in name or "spine" in name and "001" in name:
                mapping["hip"] = b.name
            if "foot" in name and "_l" in name.lower():
                mapping["foot_L"] = b.name
            if "foot" in name and "_r" in name.lower():
                mapping["foot_R"] = b.name
            if "arm" in name and "upper" in name and "_l" in name.lower():
                mapping["arm_L"] = b.name
            if "arm" in name and "upper" in name and "_r" in name.lower():
                mapping["arm_R"] = b.name

        return mapping

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class BT_OT_GenerateRunCycle(bpy.types.Operator):
    bl_idname = "bt.generate_run_cycle"
    bl_label = "Generate Run Cycle"
    bl_description = "Generate a procedural run cycle animation"
    bl_options = {'REGISTER', 'UNDO'}

    speed: bpy.props.FloatProperty(name="Speed", default=2.0, min=0.5, max=5.0)
    stride: bpy.props.FloatProperty(name="Stride", default=0.6, min=0.2, max=3.0)

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None
                and context.active_object.type == 'ARMATURE')

    def execute(self, context):
        from .procedural.locomotion import generate_run_cycle
        arm_obj = context.active_object
        keyframe_data = generate_run_cycle({"speed": self.speed, "stride": self.stride})
        BT_OT_GenerateWalkCycle._apply_keyframes(self, arm_obj, keyframe_data, "RunCycle")
        self.report({'INFO'}, "Generated run cycle")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class BT_OT_GenerateIdle(bpy.types.Operator):
    bl_idname = "bt.generate_idle"
    bl_label = "Generate Idle"
    bl_description = "Generate a subtle idle breathing/sway animation"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None
                and context.active_object.type == 'ARMATURE')

    def execute(self, context):
        from .procedural.locomotion import generate_idle
        arm_obj = context.active_object
        keyframe_data = generate_idle()
        BT_OT_GenerateWalkCycle._apply_keyframes(self, arm_obj, keyframe_data, "Idle")
        self.report({'INFO'}, "Generated idle animation")
        return {'FINISHED'}


class BT_OT_GenerateBreathing(bpy.types.Operator):
    bl_idname = "bt.generate_breathing"
    bl_label = "Generate Breathing"
    bl_description = "Generate procedural breathing animation"
    bl_options = {'REGISTER', 'UNDO'}

    rate: bpy.props.FloatProperty(name="Breaths/Min", default=15.0, min=5.0, max=40.0)
    depth: bpy.props.FloatProperty(name="Depth", default=0.03, min=0.005, max=0.1)

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None
                and context.active_object.type == 'ARMATURE')

    def execute(self, context):
        from .procedural.breathing import generate_breathing
        arm_obj = context.active_object
        keyframe_data = generate_breathing({"rate": self.rate, "depth": self.depth})
        BT_OT_GenerateWalkCycle._apply_keyframes(self, arm_obj, keyframe_data, "Breathing")
        self.report({'INFO'}, "Generated breathing animation")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class BT_OT_MechanicalAnim(bpy.types.Operator):
    bl_idname = "bt.mechanical_anim"
    bl_label = "Mechanical Animation"
    bl_description = "Generate mechanical animation (piston/gear/conveyor)"
    bl_options = {'REGISTER', 'UNDO'}

    anim_type: bpy.props.EnumProperty(
        name="Type",
        items=[
            ('PISTON', "Piston", "Linear piston stroke"),
            ('GEAR', "Gear", "Rotating gear"),
            ('CONVEYOR', "Conveyor", "Repeating offset"),
        ],
    )
    speed: bpy.props.FloatProperty(name="Speed", default=1.0, min=0.1, max=10.0)
    frame_count: bpy.props.IntProperty(name="Frames", default=48, min=8, max=240)

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        from .procedural.mechanical import (
            generate_piston_cycle, generate_gear_rotation, generate_conveyor
        )

        obj = context.active_object
        params = {"speed": self.speed, "frame_count": self.frame_count}

        if self.anim_type == 'PISTON':
            data = generate_piston_cycle(params)
        elif self.anim_type == 'GEAR':
            data = generate_gear_rotation(params)
        else:
            data = generate_conveyor(params)

        action_name = f"{obj.name}_{self.anim_type}"

        for key, frames in data.items():
            parts = key.rsplit("_", 1)
            prop = parts[0]
            idx = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0

            prop_map = {
                "piston_location": "location",
                "rotation_euler": "rotation_euler",
                "location": "location",
            }
            data_path = prop_map.get(prop, prop)
            create_fcurve(obj, action_name, data_path, idx, frames)

        self.report({'INFO'}, f"Generated {self.anim_type} animation")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class BT_OT_FollowPath(bpy.types.Operator):
    bl_idname = "bt.follow_path"
    bl_label = "Follow Path"
    bl_description = "Set up object to follow a curve path"
    bl_options = {'REGISTER', 'UNDO'}

    duration: bpy.props.IntProperty(name="Duration", default=100, min=10, max=1000)
    banking: bpy.props.BoolProperty(name="Banking", default=True)

    @classmethod
    def poll(cls, context):
        sel = context.selected_objects
        return (len(sel) >= 2 and
                any(o.type == 'CURVE' for o in sel))

    def execute(self, context):
        from .path_anim import setup_follow_path

        obj = context.active_object
        curve = None
        for o in context.selected_objects:
            if o.type == 'CURVE' and o != obj:
                curve = o
                break

        if not curve:
            self.report({'ERROR'}, "Select a curve object")
            return {'CANCELLED'}

        setup_follow_path(obj, curve, self.duration, self.banking)
        self.report({'INFO'}, f"{obj.name} follows {curve.name}")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class BT_OT_OrbitCamera(bpy.types.Operator):
    bl_idname = "bt.orbit_camera"
    bl_label = "Create Orbit Camera"
    bl_description = "Create a camera that orbits around the 3D cursor"
    bl_options = {'REGISTER', 'UNDO'}

    radius: bpy.props.FloatProperty(name="Radius", default=5.0, min=0.5, max=50.0)
    height: bpy.props.FloatProperty(name="Height", default=2.0, min=-10.0, max=20.0)
    frames: bpy.props.IntProperty(name="Frames", default=120, min=24, max=600)

    def execute(self, context):
        from .camera_tools import create_orbit_camera
        center = list(context.scene.cursor.location)
        cam = create_orbit_camera(center, self.radius, self.height, frame_count=self.frames)
        self.report({'INFO'}, f"Created orbit camera: {cam.name}")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class BT_OT_CameraShake(bpy.types.Operator):
    bl_idname = "bt.camera_shake"
    bl_label = "Add Camera Shake"
    bl_description = "Add procedural shake to active camera"
    bl_options = {'REGISTER', 'UNDO'}

    intensity: bpy.props.FloatProperty(name="Intensity", default=0.02, min=0.001, max=0.5)
    frequency: bpy.props.FloatProperty(name="Frequency", default=3.0, min=0.5, max=20.0)
    frame_count: bpy.props.IntProperty(name="Duration", default=60, min=10, max=500)

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None
                and context.active_object.type == 'CAMERA')

    def execute(self, context):
        from .camera_tools import add_camera_shake
        cam = context.active_object
        frame_start = context.scene.frame_current
        add_camera_shake(cam, self.intensity, self.frequency, frame_start, self.frame_count)
        self.report({'INFO'}, f"Added shake to {cam.name}")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class BT_OT_MatchCycleKeyframes(bpy.types.Operator):
    bl_idname = "bt.match_cycle_keyframes"
    bl_label = "Match Cycle Start/End"
    bl_description = "Match first and last keyframes for seamless looping"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj and obj.animation_data and obj.animation_data.action)

    def execute(self, context):
        from .cycle_tools import match_first_last_keyframe
        action = context.active_object.animation_data.action
        match_first_last_keyframe(action)
        self.report({'INFO'}, f"Matched cycle keyframes for {action.name}")
        return {'FINISHED'}


class BT_OT_PushToNLA(bpy.types.Operator):
    bl_idname = "bt.push_to_nla"
    bl_label = "Push to NLA"
    bl_description = "Push current action to NLA strip"
    bl_options = {'REGISTER', 'UNDO'}

    repeat: bpy.props.IntProperty(name="Repeat", default=1, min=1, max=100)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj and obj.animation_data and obj.animation_data.action)

    def execute(self, context):
        from .cycle_tools import push_to_nla
        obj = context.active_object
        strip = push_to_nla(obj, repeat=self.repeat)
        if strip:
            self.report({'INFO'}, f"Pushed to NLA: {strip.name}")
            return {'FINISHED'}
        self.report({'ERROR'}, "Failed to push to NLA")
        return {'CANCELLED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


classes = (
    BT_OT_GenerateWalkCycle,
    BT_OT_GenerateRunCycle,
    BT_OT_GenerateIdle,
    BT_OT_GenerateBreathing,
    BT_OT_MechanicalAnim,
    BT_OT_FollowPath,
    BT_OT_OrbitCamera,
    BT_OT_CameraShake,
    BT_OT_MatchCycleKeyframes,
    BT_OT_PushToNLA,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
