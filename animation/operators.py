"""Animation operators."""

import threading

import bpy

from ..core.utils import create_fcurve


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
            generate_conveyor,
            generate_gear_rotation,
            generate_piston_cycle,
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
            suffix = parts[1] if len(parts) > 1 else "0"
            axis_map = {"x": 0, "y": 1, "z": 2}
            idx = axis_map.get(suffix, int(suffix) if suffix.isdigit() else 0)

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


class BT_OT_InitAnimAI(bpy.types.Operator):
    bl_idname = "bt.init_anim_ai"
    bl_label = "Initialize AI Motion"
    bl_description = (
        "Install PyTorch and download AnyTop + SinMDM models for "
        "AI-powered motion generation and style transfer"
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

                self.report({'INFO'}, "AI Motion initialized — AnyTop + SinMDM ready!")
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
                        self._progress = 0.05 + p * 0.25
                        if msg:
                            self._status_msg = msg

                    dependencies.install_torch(
                        use_gpu=True,
                        progress_callback=on_torch_progress,
                    )

                # Step 2: Download AnyTop (code from GitHub + weights from HF)
                self._progress = 0.35
                self._status_msg = "Downloading AnyTop code..."

                def on_anytop_progress(p, msg=""):
                    self._progress = 0.35 + p * 0.15
                    if msg:
                        self._status_msg = msg

                model_manager.install_model("anytop", progress_callback=on_anytop_progress)

                # AnyTop weights from HuggingFace
                self._progress = 0.5
                self._status_msg = "Downloading AnyTop weights from HuggingFace..."
                from .ml.anytop_adapter import AnyTopAdapter

                def on_anytop_hf(p, msg=""):
                    self._progress = 0.5 + p * 0.15
                    if msg:
                        self._status_msg = msg

                AnyTopAdapter.download_weights(progress_callback=on_anytop_hf)
                # Update status to mark AnyTop as installed
                model_manager._write_status("anytop", {
                    "installed": True,
                    "model_name": "AnyTop",
                    "version": "1.0",
                })

                # Step 3: Download SinMDM (code from GitHub + weights from GDrive)
                self._progress = 0.7
                self._status_msg = "Downloading SinMDM code..."

                def on_sinmdm_progress(p, msg=""):
                    self._progress = 0.7 + p * 0.1
                    if msg:
                        self._status_msg = msg

                model_manager.install_model("sinmdm", progress_callback=on_sinmdm_progress)

                # SinMDM weights from Google Drive
                self._progress = 0.8
                self._status_msg = "Downloading SinMDM weights from Google Drive..."
                from .ml.sinmdm_adapter import SinMDMAdapter

                def on_sinmdm_gd(p, msg=""):
                    self._progress = 0.8 + p * 0.2
                    if msg:
                        self._status_msg = msg

                SinMDMAdapter.download_weights(progress_callback=on_sinmdm_gd)
                # Update status to mark SinMDM as installed
                model_manager._write_status("sinmdm", {
                    "installed": True,
                    "model_name": "SinMDM",
                    "version": "1.0",
                })

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


class BT_OT_RemoveAnimAI(bpy.types.Operator):
    bl_idname = "bt.remove_anim_ai"
    bl_label = "Remove AI Motion Models"
    bl_description = "Delete downloaded AnyTop and SinMDM models to free disk space"

    def execute(self, context):
        from ..core.ml import model_manager

        total = 0.0
        for mid in ("anytop", "sinmdm"):
            total += model_manager.get_cache_size_mb(mid)
            model_manager.remove_model(mid)

        self.report({'INFO'}, f"Removed AI motion models ({total:.0f} MB freed)")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)


class BT_OT_AIGenerateMotion(bpy.types.Operator):
    bl_idname = "bt.ai_generate_motion"
    bl_label = "Generate Motion"
    bl_description = "Generate animation from text prompt (auto-selects best model)"
    bl_options = {'REGISTER', 'UNDO'}

    prompt: bpy.props.StringProperty(
        name="Prompt",
        description="Describe the motion (e.g. 'a person walking forward')",
        default="a person walking forward",
    )
    num_frames: bpy.props.IntProperty(
        name="Frames",
        description="Number of frames to generate",
        default=120,
        min=30,
        max=300,
    )
    model: bpy.props.EnumProperty(
        name="Model",
        items=[
            ('AUTO', "Auto", "MotionLCM for humanoid, AnyTop for exotic"),
            ('MOTIONLCM', "MotionLCM", "Fast humanoid motion (~30ms)"),
            ('ANYTOP', "AnyTop", "Any skeleton topology (~5s)"),
        ],
        default='AUTO',
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            return False
        from .retarget import has_wrap_rig
        return has_wrap_rig(obj)

    def _select_adapter(self, armature_obj):
        """Select the best adapter based on model choice and rig type."""
        from ..core.ml import model_manager

        has_lcm = model_manager.is_model_installed("motionlcm")
        has_anytop = model_manager.is_model_installed("anytop")

        if self.model == 'MOTIONLCM':
            if not has_lcm:
                raise RuntimeError("MotionLCM not installed.")
            from .ml.motionlcm_adapter import MotionLCMAdapter
            return MotionLCMAdapter.get_instance()

        if self.model == 'ANYTOP':
            if not has_anytop:
                raise RuntimeError("AnyTop not installed.")
            from .ml.anytop_adapter import AnyTopAdapter
            return AnyTopAdapter.get_instance()

        # AUTO: prefer MotionLCM for humanoid rigs
        is_humanoid = self._is_humanoid(armature_obj)

        if is_humanoid and has_lcm:
            from .ml.motionlcm_adapter import MotionLCMAdapter
            return MotionLCMAdapter.get_instance()

        if has_anytop:
            from .ml.anytop_adapter import AnyTopAdapter
            return AnyTopAdapter.get_instance()

        if has_lcm:
            from .ml.motionlcm_adapter import MotionLCMAdapter
            return MotionLCMAdapter.get_instance()

        raise RuntimeError("No motion model installed")

    @staticmethod
    def _is_humanoid(armature_obj):
        """Check if armature has humanoid topology (spine + arms + legs)."""
        scan = getattr(armature_obj, 'bt_scan', None)
        if scan is None:
            return False
        chains = getattr(scan, 'chains', [])
        types = {getattr(c, 'module_type', '') for c in chains}
        return ('spine' in types
                and 'arm' in types
                and 'leg' in types)

    def execute(self, context):
        arm_obj = context.active_object
        adapter = self._select_adapter(arm_obj)
        model_name = adapter.MODEL_NAME

        try:
            motion_data = adapter.generate(
                arm_obj, self.prompt, self.num_frames,
            )
            adapter.apply_motion(arm_obj, motion_data)

            # Animate SMPL preview if it exists (side-by-side comparison)
            from .ml.retarget_preview import apply_preview_motion
            smpl_data = None
            if motion_data.get('_smpl_rotations'):
                smpl_data = {
                    'rotations': motion_data['_smpl_rotations'],
                    'root_positions': motion_data['_smpl_root_positions'],
                }
            has_preview = apply_preview_motion(
                smpl_data or motion_data, user_armature=arm_obj,
            )
            if has_preview:
                self.report(
                    {'INFO'},
                    f"[{model_name}] Generated {self.num_frames} frames "
                    f"+ SMPL preview: '{self.prompt}'"
                )
            else:
                self.report(
                    {'INFO'},
                    f"[{model_name}] Generated {self.num_frames} frames: "
                    f"'{self.prompt}'"
                )
        except Exception as e:
            self.report({'ERROR'}, f"Motion generation failed: {e}")
            return {'CANCELLED'}

        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)


class BT_OT_AIStyleTransfer(bpy.types.Operator):
    bl_idname = "bt.ai_style_transfer"
    bl_label = "Style Transfer"
    bl_description = "Generate style variations of current animation using SinMDM"
    bl_options = {'REGISTER', 'UNDO'}

    num_variations: bpy.props.IntProperty(
        name="Variations",
        description="Number of style variations to generate",
        default=1,
        min=1,
        max=5,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            return False
        if not obj.animation_data or not obj.animation_data.action:
            return False
        from ..core.ml import model_manager
        return model_manager.is_model_installed("sinmdm")

    def execute(self, context):
        arm_obj = context.active_object
        from .ml.sinmdm_adapter import SinMDMAdapter

        adapter = SinMDMAdapter.get_instance()

        try:
            bvh_path = adapter.export_animation_bvh(arm_obj)
            result_paths = adapter.predict(
                input_bvh=bvh_path,
                task="style_transfer",
                num_results=self.num_variations,
            )
            if result_paths:
                adapter.import_animation_bvh(arm_obj, result_paths[0])
                self.report(
                    {'INFO'},
                    f"Generated {len(result_paths)} style variation(s)",
                )
            else:
                self.report({'WARNING'}, "No results generated")
                return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"Style transfer failed: {e}")
            return {'CANCELLED'}

        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class BT_OT_AIInbetween(bpy.types.Operator):
    bl_idname = "bt.ai_inbetween"
    bl_label = "AI In-Between"
    bl_description = "Fill in frames between keyframes using SinMDM"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            return False
        if not obj.animation_data or not obj.animation_data.action:
            return False
        from ..core.ml import model_manager
        return model_manager.is_model_installed("sinmdm")

    def execute(self, context):
        arm_obj = context.active_object
        from .ml.sinmdm_adapter import SinMDMAdapter

        adapter = SinMDMAdapter.get_instance()

        try:
            bvh_path = adapter.export_animation_bvh(arm_obj)
            result_paths = adapter.predict(
                input_bvh=bvh_path,
                task="inbetween",
                num_results=1,
            )
            if result_paths:
                adapter.import_animation_bvh(
                    arm_obj, result_paths[0],
                    action_name=f"{arm_obj.name}_Inbetween",
                )
                self.report({'INFO'}, "Generated in-between frames")
            else:
                self.report({'WARNING'}, "No results generated")
                return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"In-betweening failed: {e}")
            return {'CANCELLED'}

        return {'FINISHED'}


class BT_OT_RetargetPreview(bpy.types.Operator):
    bl_idname = "bt.retarget_preview"
    bl_label = "SMPL Reference"
    bl_description = (
        "Toggle SMPL reference skeleton for retarget validation. "
        "Shows the standard 22-joint skeleton next to your armature "
        "so you can verify alignment before generating motion"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'ARMATURE'

    def execute(self, context):
        from .ml.retarget_preview import (
            apply_preview_motion,
            create_smpl_preview,
            get_cached_frame_start,
            get_cached_motion,
            get_smpl_preview,
            remove_smpl_preview,
        )

        if get_smpl_preview():
            remove_smpl_preview()
            self.report({'INFO'}, "Removed SMPL reference skeleton")
        else:
            arm_obj = context.active_object
            create_smpl_preview(arm_obj)

            cached = get_cached_motion()
            if cached is not None:
                apply_preview_motion(
                    cached,
                    user_armature=arm_obj,
                    frame_start=get_cached_frame_start(),
                )
                self.report(
                    {'INFO'},
                    "Created SMPL reference with cached motion",
                )
            else:
                self.report(
                    {'INFO'},
                    "Created SMPL reference — verify both skeletons "
                    "face the same direction in T-pose",
                )
        return {'FINISHED'}


class BT_OT_LinkSMPLPreview(bpy.types.Operator):
    bl_idname = "bt.link_smpl_preview"
    bl_label = "Link SMPL to User"
    bl_description = (
        "Toggle live retarget link: posing SMPL preview bones "
        "drives the user armature in real-time for debugging"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        from .ml.retarget_preview import get_smpl_preview
        obj = context.active_object
        return (
            obj and obj.type == 'ARMATURE'
            and get_smpl_preview() is not None
        )

    def execute(self, context):
        from .ml.retarget_preview import (
            is_link_active,
            link_preview_to_user,
            unlink_preview_from_user,
        )

        if is_link_active():
            unlink_preview_from_user()
            self.report({'INFO'}, "Unlinked SMPL preview from user armature")
        else:
            arm_obj = context.active_object
            if link_preview_to_user(arm_obj):
                self.report(
                    {'INFO'},
                    "Linked — pose SMPL bones to see retarget result",
                )
            else:
                self.report(
                    {'WARNING'},
                    "Could not link — ensure armature has scan + wrap rig",
                )
        return {'FINISHED'}


class BT_OT_DebugRetargetFrame(bpy.types.Operator):
    """Generate motion and compare model output vs SMPL preview bone values."""

    bl_idname = "bt.debug_retarget_frame"
    bl_label = "Debug SMPL Frame"
    bl_description = (
        "Generate a short clip, apply to SMPL preview, then print "
        "model output vs actual bone rotation for every joint"
    )
    bl_options = {'REGISTER', 'UNDO'}

    prompt: bpy.props.StringProperty(
        name="Prompt",
        default="a person walking forward",
    )
    frame_index: bpy.props.IntProperty(
        name="Frame to inspect",
        description="Which frame of the generated motion to inspect (0-based)",
        default=0,
        min=0,
    )

    @classmethod
    def poll(cls, context):
        from .ml.retarget_preview import get_smpl_preview
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            return False
        if get_smpl_preview() is None:
            return False
        from .retarget import has_wrap_rig
        return has_wrap_rig(obj)

    def execute(self, context):
        import math

        import numpy as np

        from .ml import smpl_skeleton
        from .ml.retarget_map import _euler_to_matrix, _matrix_to_euler_xyz
        from .ml.retarget_preview import apply_preview_motion, get_smpl_preview

        arm_obj = context.active_object
        smpl_arm = get_smpl_preview()
        if smpl_arm is None:
            self.report({'ERROR'}, "No SMPL preview — create one first")
            return {'CANCELLED'}

        # ── 1. Generate a short clip ──
        # Select adapter directly (can't use _select_adapter — it's
        # an instance method on BT_OT_AIGenerateMotion that reads self.model)
        from ..core.ml import model_manager

        adapter = None
        if model_manager.is_model_installed("motionlcm"):
            from .ml.motionlcm_adapter import MotionLCMAdapter
            adapter = MotionLCMAdapter.get_instance()
        elif model_manager.is_model_installed("anytop"):
            from .ml.anytop_adapter import AnyTopAdapter
            adapter = AnyTopAdapter.get_instance()

        if adapter is None:
            self.report({'ERROR'}, "No motion model installed")
            return {'CANCELLED'}

        try:
            motion_data = adapter.generate(
                arm_obj, self.prompt, num_frames=30,
            )
        except Exception as e:
            self.report({'ERROR'}, f"Generation failed: {e}")
            return {'CANCELLED'}

        # Get SMPL rotations (MotionLCM stores them in _smpl_rotations)
        smpl_rots = (
            motion_data.get('_smpl_rotations')
            or motion_data.get('rotations')
        )
        smpl_root_pos = (
            motion_data.get('_smpl_root_positions')
            or motion_data.get('root_positions')
        )

        if not smpl_rots:
            self.report({'ERROR'}, "No rotation data in model output")
            return {'CANCELLED'}

        fi = min(self.frame_index, len(smpl_rots) - 1)
        n_joints = min(len(smpl_rots[fi]), smpl_skeleton.NUM_JOINTS)

        # ── 2. Apply animation to SMPL preview ──
        smpl_data = {
            'rotations': smpl_rots,
            'root_positions': smpl_root_pos or [[0, 0, 0]] * len(smpl_rots),
        }
        apply_preview_motion(smpl_data, user_armature=arm_obj, frame_start=1)

        # Set to the target frame so bone eulers are evaluated
        context.scene.frame_set(1 + fi)
        context.view_layer.update()

        # ── 3. Compute expected values (same math as apply_preview_motion) ──
        # Use parent-relative rest orientation for conjugation
        rest_rots_rel = {}
        for j in range(n_joints):
            bone = smpl_arm.data.bones.get(smpl_skeleton.JOINT_NAMES[j])
            if bone is None:
                rest_rots_rel[j] = np.eye(3)
                continue
            M_j = np.array([
                [bone.matrix_local[r][c] for c in range(3)]
                for r in range(3)
            ])
            p_idx = int(smpl_skeleton.PARENTS[j])
            if p_idx >= 0:
                parent_bone = smpl_arm.data.bones.get(
                    smpl_skeleton.JOINT_NAMES[p_idx])
                if parent_bone:
                    M_p = np.array([
                        [parent_bone.matrix_local[r][c] for c in range(3)]
                        for r in range(3)
                    ])
                    rest_rots_rel[j] = M_p.T @ M_j
                else:
                    rest_rots_rel[j] = M_j
            else:
                rest_rots_rel[j] = M_j

        # ── 4. Print comparison table ──
        print("\n" + "=" * 100)
        print(f"DEBUG SMPL PREVIEW — frame {fi} — '{self.prompt}'")
        print("=" * 100)
        print(
            f"{'Joint':<16} "
            f"{'Model Output (deg)':<28} "
            f"{'Expected Conjugated (deg)':<28} "
            f"{'Actual Bone Euler (deg)':<28}"
        )
        print("-" * 100)

        for j in range(n_joints):
            name = smpl_skeleton.JOINT_NAMES[j]
            # Model raw output
            rx, ry, rz = smpl_rots[fi][j]
            raw_deg = (math.degrees(rx), math.degrees(ry), math.degrees(rz))

            # Expected: R_pose = M_rel.T @ R_smpl @ M_rel
            M_rel = rest_rots_rel[j]
            R_smpl = _euler_to_matrix(rx, ry, rz)
            R_pose = M_rel.T @ R_smpl @ M_rel
            exp_euler = _matrix_to_euler_xyz(R_pose)
            exp_deg = tuple(math.degrees(e) for e in exp_euler)

            # Actual bone rotation_euler
            pbone = smpl_arm.pose.bones.get(name)
            if pbone:
                act_deg = tuple(math.degrees(pbone.rotation_euler[a]) for a in range(3))
            else:
                act_deg = (0.0, 0.0, 0.0)

            # Check match between expected and actual
            match_ok = all(
                abs(exp_deg[a] - act_deg[a]) < 0.1 for a in range(3)
            )
            status = "OK" if match_ok else "MISMATCH"

            raw_s = f"({raw_deg[0]:+7.1f},{raw_deg[1]:+7.1f},{raw_deg[2]:+7.1f})"
            exp_s = f"({exp_deg[0]:+7.1f},{exp_deg[1]:+7.1f},{exp_deg[2]:+7.1f})"
            act_s = f"({act_deg[0]:+7.1f},{act_deg[1]:+7.1f},{act_deg[2]:+7.1f})"
            print(f"{name:<16} {raw_s:<28} {exp_s:<28} {act_s:<28} {status}")

        # ── 5. Pelvis height info ──
        # Adapter-side: pelvis_height from SMPL offsets in Y-up
        offsets_yup = smpl_skeleton._OFFSETS_YUP
        parents = smpl_skeleton.PARENTS
        rest_pos_yup = np.zeros((smpl_skeleton.NUM_JOINTS, 3))
        for i in range(smpl_skeleton.NUM_JOINTS):
            p = int(parents[i])
            if p >= 0:
                rest_pos_yup[i] = rest_pos_yup[p] + offsets_yup[i]
        adapter_pelvis_height = -float(rest_pos_yup[:, 1].min())

        # Preview-side: ground_offset from Z-up tpose
        from .ml.retarget_preview import _compute_tpose_positions, _get_armature_height
        user_height = _get_armature_height(arm_obj)
        smpl_height = smpl_skeleton.SKELETON_HEIGHT
        scale = user_height / smpl_height if smpl_height > 1e-6 else 1.0
        tpose = _compute_tpose_positions(scale)
        ground_offset = float(tpose[:, 2].min())
        rest_root_pos = tpose[0].copy()
        rest_root_pos[2] -= ground_offset

        print(f"\n{'─' * 60}")
        print(f"  Adapter pelvis_height (Y-up):  {adapter_pelvis_height:.4f}")
        print(f"  SMPL SKELETON_HEIGHT:          {smpl_height:.4f}")
        print(f"  User armature height:          {user_height:.4f}")
        print(f"  Scale (user/smpl):             {scale:.4f}")
        print(f"  Preview ground_offset (Z-up):  {ground_offset:.4f}")
        print(f"  Preview rest_root_pos:         ({rest_root_pos[0]:+.4f}, {rest_root_pos[1]:+.4f}, {rest_root_pos[2]:+.4f})")
        print(f"{'─' * 60}")

        # Root position
        if smpl_root_pos and fi < len(smpl_root_pos):
            rp = smpl_root_pos[fi]
            pbone = smpl_arm.pose.bones.get(smpl_skeleton.JOINT_NAMES[0])
            if pbone:
                print(f"  Root position (model):  "
                      f"({rp[0]:+.4f}, {rp[1]:+.4f}, {rp[2]:+.4f})")
                rp_scaled = np.array(rp) * scale
                rp_scaled[2] -= ground_offset
                delta = rp_scaled - rest_root_pos
                print(f"  Root scaled+grounded:   "
                      f"({rp_scaled[0]:+.4f}, {rp_scaled[1]:+.4f}, {rp_scaled[2]:+.4f})")
                print(f"  Root delta from rest:   "
                      f"({delta[0]:+.4f}, {delta[1]:+.4f}, {delta[2]:+.4f})")
                print(f"  Actual bone location:   "
                      f"({pbone.location[0]:+.4f}, "
                      f"{pbone.location[1]:+.4f}, "
                      f"{pbone.location[2]:+.4f})")

        print("=" * 100 + "\n")

        self.report(
            {'INFO'},
            f"Debug: frame {fi} applied to SMPL preview — see System Console",
        )
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)


class BT_OT_RetargetActionToFK(bpy.types.Operator):
    bl_idname = "bt.retarget_action_to_fk"
    bl_label = "Retarget Action to FK Controls"
    bl_description = (
        "Transfer the active action's keyframes from deform bones "
        "to wrap rig FK controls so the animation becomes editable"
    )
    bl_options = {'REGISTER', 'UNDO'}

    all_actions: bpy.props.BoolProperty(
        name="All Actions",
        description="Retarget every action that references this armature's bones",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            return False
        from .retarget import has_wrap_rig
        return has_wrap_rig(obj)

    def execute(self, context):
        arm_obj = context.active_object
        from .retarget import retarget_action_to_fk, retarget_all_actions_to_fk

        if self.all_actions:
            count = retarget_all_actions_to_fk(arm_obj)
            self.report({'INFO'}, f"Retargeted {count} FCurves across all actions")
        else:
            ad = arm_obj.animation_data
            if not ad or not ad.action:
                self.report({'WARNING'}, "No active action to retarget")
                return {'CANCELLED'}
            count = retarget_action_to_fk(arm_obj, ad.action)
            self.report(
                {'INFO'},
                f"Retargeted {count} FCurves → FK controls "
                f"({ad.action.name})",
            )

        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


classes = (
    BT_OT_MechanicalAnim,
    BT_OT_FollowPath,
    BT_OT_OrbitCamera,
    BT_OT_CameraShake,
    BT_OT_MatchCycleKeyframes,
    BT_OT_PushToNLA,
    BT_OT_InitAnimAI,
    BT_OT_RemoveAnimAI,
    BT_OT_AIGenerateMotion,
    BT_OT_AIStyleTransfer,
    BT_OT_AIInbetween,
    BT_OT_RetargetPreview,
    BT_OT_LinkSMPLPreview,
    BT_OT_RetargetActionToFK,
    BT_OT_DebugRetargetFrame,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
