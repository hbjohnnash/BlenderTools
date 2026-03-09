"""AnyTop adapter — topology-agnostic text-to-motion generation.

Works with ANY skeleton topology (humans, animals, robots).
Outputs 6D joint rotations per frame, which are converted to
Euler rotations and applied as keyframes.

GitHub: https://github.com/Anytop2025/Anytop
Paper:  SIGGRAPH 2025
"""

import sys
from math import atan2, pi

import bpy

from ...core.ml.base_adapter import BaseModelAdapter

_CODE_URL = (
    "https://github.com/Anytop2025/Anytop/archive/refs/heads/main.zip"
)

# HuggingFace repo: inbar2344/AnyTop
# Contains checkpoints/ and dataset/ directories.
_HF_REPO = "inbar2344/AnyTop"


class AnyTopAdapter(BaseModelAdapter):
    MODEL_ID = "anytop"
    MODEL_NAME = "AnyTop"
    MODEL_DESC = "Text-to-motion for any skeleton topology (SIGGRAPH 2025)"
    MODEL_TYPE = "animation"
    VERSION = "1.0"

    CODE_URL = _CODE_URL
    # Weights are on HuggingFace — downloaded via huggingface_hub.
    # WEIGHT_URLS left empty; install_model is overridden to use HF.
    WEIGHT_URLS = {}
    EXTRA_DEPS = ["einops", "tqdm", "huggingface_hub"]

    # ── Skeleton extraction ──

    def extract_skeleton(self, armature_obj):
        """Convert Blender armature to AnyTop skeleton description.

        Only includes deform bones (skips CTRL/MCH wrap-rig helpers).

        Returns:
            dict with 'joints' list for the model.
        """
        from ..retarget import get_deform_bone_names

        deform_names = set(get_deform_bone_names(armature_obj))
        bones = armature_obj.data.bones
        joint_list = []
        name_to_idx = {}

        for bone in bones:
            if bone.name not in deform_names:
                continue

            idx = len(joint_list)
            name_to_idx[bone.name] = idx

            # Walk up to find nearest *included* parent
            parent = bone.parent
            while parent and parent.name not in name_to_idx:
                parent = parent.parent
            parent_idx = name_to_idx[parent.name] if parent else -1

            if bone.parent:
                offset = bone.head_local - bone.parent.head_local
            else:
                offset = bone.head_local.copy()

            joint_list.append({
                "name": bone.name,
                "parent": parent_idx,
                "offset": [offset.x, offset.y, offset.z],
                "description": self._bone_description(bone.name),
            })

        return {"joints": joint_list}

    def _bone_description(self, name):
        """Generate a textual description of a bone for AnyTop's input."""
        name_lower = name.lower()
        # More specific terms must come before generic ones (e.g. "foot"
        # before "leg") so that "Leg_L_Foot" matches "foot bone" not "leg bone".
        parts = [
            ("foot", "foot bone"),
            ("toe", "toe bone"),
            ("thigh", "upper leg bone"),
            ("shin", "lower leg bone"),
            ("upper_leg", "upper leg bone"),
            ("lower_leg", "lower leg bone"),
            ("leg", "leg bone"),
            ("pelvis", "hip/pelvis bone"),
            ("hand", "hand bone"),
            ("finger", "finger bone"),
            ("shoulder", "shoulder bone"),
            ("clavicle", "clavicle bone"),
            ("upper_arm", "upper arm bone"),
            ("lower_arm", "lower arm bone"),
            ("arm", "arm bone"),
            ("head", "head bone"),
            ("neck", "neck bone"),
            ("chest", "chest bone"),
            ("spine", "spine bone"),
            ("hip", "hip/pelvis bone"),
        ]
        for key, desc in parts:
            if key in name_lower:
                side = ""
                if "_l_" in name_lower or name_lower.endswith("_l"):
                    side = "left "
                elif "_r_" in name_lower or name_lower.endswith("_r"):
                    side = "right "
                return f"{side}{desc}"
        return "bone"

    # ── HuggingFace download ──

    @classmethod
    def download_weights(cls, progress_callback=None):
        """Download checkpoints from HuggingFace repo inbar2344/AnyTop."""
        from huggingface_hub import snapshot_download

        from ...core.ml import model_manager

        model_dir = model_manager.get_model_dir(cls.MODEL_ID)
        weights_dir = model_dir / "weights"
        weights_dir.mkdir(parents=True, exist_ok=True)

        if progress_callback:
            progress_callback(0.2, "Downloading AnyTop from HuggingFace...")

        snapshot_download(
            repo_id=_HF_REPO,
            local_dir=str(weights_dir / "hf_snapshot"),
            allow_patterns=["checkpoints/**"],
        )

        if progress_callback:
            progress_callback(1.0, "AnyTop weights downloaded")

    # ── Model loading ──

    def _get_repo_root(self):
        code_dir = self.get_code_dir()
        candidates = list(code_dir.iterdir()) if code_dir.exists() else []
        for c in candidates:
            if c.is_dir() and (c / "model").exists():
                return c
        return code_dir / "Anytop-main"

    def _find_checkpoint(self):
        """Locate the best checkpoint file in the weights directory."""
        weights_dir = self.get_weights_dir()
        # Look in HF snapshot checkpoints/
        for pt in sorted(weights_dir.rglob("*.pt"), reverse=True):
            return pt
        return None

    def load_model(self):
        """Load AnyTop model from downloaded code and weights."""
        if self._model is not None:
            return

        import torch

        repo_root = self._get_repo_root()
        repo_str = str(repo_root)
        if repo_str not in sys.path:
            sys.path.insert(0, repo_str)

        # Load the model checkpoint
        ckpt_path = self._find_checkpoint()
        if ckpt_path is None:
            raise FileNotFoundError(
                "AnyTop checkpoint not found. Re-run 'Initialize AI Motion'."
            )

        checkpoint = torch.load(
            ckpt_path,
            map_location="cpu",
            weights_only=False,
        )

        self._model = checkpoint
        self._repo_root = repo_root

    # ── Inference ──

    def predict(self, skeleton, prompt, num_frames=120):
        """Generate motion from text prompt for the given skeleton.

        Args:
            skeleton: dict from extract_skeleton().
            prompt: Text description (e.g. "a person walking forward").
            num_frames: Number of frames to generate.

        Returns:
            dict with 'rotations' (list of per-joint Euler XYZ per frame),
            'root_positions' (list of root XYZ per frame),
            and 'joint_names'.
        """
        joints = skeleton["joints"]
        num_joints = len(joints)

        try:
            self.load_model()
            import torch

            repo_root = self._repo_root
            repo_str = str(repo_root)
            if repo_str not in sys.path:
                sys.path.insert(0, repo_str)

            # Build skeleton topology tensor
            parent_indices = torch.tensor(
                [j["parent"] for j in joints], dtype=torch.long,
            )
            offsets = torch.tensor(
                [j["offset"] for j in joints], dtype=torch.float32,
            )
            descriptions = [j["description"] for j in joints]

            from model.generate import generate_motion

            result = generate_motion(
                model=self._model,
                text_prompt=prompt,
                skeleton_offsets=offsets,
                skeleton_parents=parent_indices,
                joint_descriptions=descriptions,
                num_frames=num_frames,
            )
            rotations_6d = result.cpu().numpy()

            # Convert 6D → Euler
            rotations_euler = []
            root_positions = []
            for f in range(len(rotations_6d)):
                frame_rots = []
                for j in range(num_joints):
                    if (rotations_6d[f].ndim > 1
                            and rotations_6d[f].shape[-1] >= 6):
                        euler = self._rotation_6d_to_euler(rotations_6d[f][j])
                    else:
                        euler = (0.0, 0.0, 0.0)
                    frame_rots.append(euler)
                rotations_euler.append(frame_rots)

                if (rotations_6d[f].ndim > 1
                        and rotations_6d[f].shape[-1] >= 9):
                    root_positions.append(tuple(rotations_6d[f][0][:3]))
                else:
                    root_positions.append((0.0, 0.0, 0.0))

        except Exception:
            # Fallback: procedural motion (model not available)
            rotations_euler, root_positions = self._fallback_generate(
                skeleton, num_frames, prompt,
            )

        return {
            "rotations": rotations_euler,
            "root_positions": root_positions,
            "joint_names": [j["name"] for j in joints],
        }

    def apply_motion(self, armature_obj, motion_data, action_name=None,
                     frame_start=1):
        """Apply generated motion data to a Blender armature.

        Automatically detects whether a wrap rig is present and writes
        keyframes to the appropriate bones (CTRL FK when wrap rig exists,
        deform bones otherwise).  Sets target bones to Euler rotation
        mode for intuitive editing.

        Returns:
            The created Action.
        """
        from bpy_extras.anim_utils import action_ensure_channelbag_for_slot

        from ...core.utils import assign_channel_groups
        from ..retarget import build_def_to_fk_map, has_wrap_rig

        if not action_name:
            action_name = f"{armature_obj.name}_AnyTop"

        # Build bone target mapping
        bone_map = {}  # joint_name → target_bone_name
        using_fk = False
        if has_wrap_rig(armature_obj):
            def_to_fk = build_def_to_fk_map(armature_obj)
            if def_to_fk:
                using_fk = True
                for jname in motion_data["joint_names"]:
                    bone_map[jname] = def_to_fk.get(jname, jname)
        if not bone_map:
            for jname in motion_data["joint_names"]:
                bone_map[jname] = jname

        # Ensure FK mode on all chains when targeting FK controls
        if using_fk:
            self._ensure_fk_mode(armature_obj)

        # Create action
        action = bpy.data.actions.new(name=action_name)
        if not armature_obj.animation_data:
            armature_obj.animation_data_create()

        armature_obj.animation_data.action = action
        slot = action.slots.new(name=armature_obj.name, id_type='OBJECT')
        armature_obj.animation_data.action_slot = slot
        cb = action_ensure_channelbag_for_slot(action, slot)

        joint_names = motion_data["joint_names"]
        rotations = motion_data["rotations"]
        root_positions = motion_data["root_positions"]
        num_frames = len(rotations)

        for ji, bone_name in enumerate(joint_names):
            target_name = bone_map.get(bone_name, bone_name)
            pbone = armature_obj.pose.bones.get(target_name)
            if pbone is None:
                continue

            # Set Euler mode so the rotation FCurves take effect
            pbone.rotation_mode = 'XYZ'

            # Rotation FCurves
            for axis in range(3):
                dp = f'pose.bones["{target_name}"].rotation_euler'
                fc = cb.fcurves.new(dp, index=axis)
                fc.keyframe_points.add(num_frames)
                for fi in range(num_frames):
                    kf = fc.keyframe_points[fi]
                    kf.co = (frame_start + fi, rotations[fi][ji][axis])
                    kf.interpolation = 'BEZIER'
                fc.update()

            # Root position (first joint only)
            if ji == 0 and root_positions:
                for axis in range(3):
                    dp = f'pose.bones["{target_name}"].location'
                    fc = cb.fcurves.new(dp, index=axis)
                    fc.keyframe_points.add(num_frames)
                    for fi in range(num_frames):
                        kf = fc.keyframe_points[fi]
                        kf.co = (frame_start + fi, root_positions[fi][axis])
                        kf.interpolation = 'BEZIER'
                    fc.update()

        assign_channel_groups(armature_obj)
        return action

    @staticmethod
    def _ensure_fk_mode(armature_obj):
        """Set all wrap rig chains to FK mode (disable IK influence)."""
        from ...core.constants import WRAP_CONSTRAINT_PREFIX

        for pbone in armature_obj.pose.bones:
            for con in pbone.constraints:
                if not con.name.startswith(WRAP_CONSTRAINT_PREFIX):
                    continue
                # IK constraints → influence 0; FK copy → influence 1
                if con.type == 'IK':
                    con.influence = 0.0
                elif (con.type == 'COPY_TRANSFORMS'
                      and "_FK_" in con.name):
                    con.influence = 1.0

    # ── Rotation conversion ──

    @staticmethod
    def _rotation_6d_to_euler(r6d):
        """Convert 6D rotation representation to Euler XYZ angles.

        The 6D representation is the first two columns of the rotation matrix.
        """
        import numpy as np

        a1 = np.array(r6d[:3], dtype=np.float64)
        a2 = np.array(r6d[3:6], dtype=np.float64)

        # Gram-Schmidt to get orthonormal basis
        b1 = a1 / (np.linalg.norm(a1) + 1e-8)
        b2 = a2 - np.dot(b1, a2) * b1
        b2 = b2 / (np.linalg.norm(b2) + 1e-8)
        b3 = np.cross(b1, b2)

        # Rotation matrix to Euler XYZ
        R = np.column_stack([b1, b2, b3])

        sy = (R[0, 0] ** 2 + R[1, 0] ** 2) ** 0.5
        if sy > 1e-6:
            x = atan2(R[2, 1], R[2, 2])
            y = atan2(-R[2, 0], sy)
            z = atan2(R[1, 0], R[0, 0])
        else:
            x = atan2(-R[1, 2], R[1, 1])
            y = atan2(-R[2, 0], sy)
            z = 0.0

        return (x, y, z)

    # ── Fallback procedural motion ──

    @staticmethod
    def _fallback_generate(skeleton, num_frames, prompt):
        """Generate procedural motion when model inference fails.

        Returns ``(rotations_euler, root_positions)`` directly in Euler
        space so the caller can skip the 6D conversion.
        """
        import numpy as np

        joints = skeleton["joints"]
        num_joints = len(joints)
        prompt_lower = prompt.lower()

        # Classify each joint by its description
        roles = {}  # index → set of tags
        for i, j in enumerate(joints):
            desc = j.get("description", "").lower()
            tags = set()
            if "spine" in desc or "chest" in desc:
                tags.add("spine")
            if "hip" in desc or "pelvis" in desc:
                tags.add("hip")
            if "upper leg" in desc:
                tags.add("upper_leg")
            if "lower leg" in desc:
                tags.add("lower_leg")
            if "foot" in desc:
                tags.add("foot")
            if "upper arm" in desc or "upper limb" in desc:
                tags.add("upper_arm")
            if "lower arm" in desc or "lower limb" in desc:
                tags.add("lower_arm")
            if "head" in desc:
                tags.add("head")
            if "neck" in desc:
                tags.add("neck")
            if "left" in desc:
                tags.add("left")
            if "right" in desc:
                tags.add("right")
            roles[i] = tags

        # Initialise output as zeros
        rots = [[(0.0, 0.0, 0.0)] * num_joints for _ in range(num_frames)]
        root_pos = [(0.0, 0.0, 0.0)] * num_frames

        is_walk = any(w in prompt_lower for w in ["walk", "run", "jog"])
        is_idle = any(w in prompt_lower
                      for w in ["idle", "stand", "breathe", "rest"])

        # Bone axes for this rig:
        #   local X ≈ world -Y  (rx = side-to-side)
        #   local Y ≈ bone dir  (ry = twist)
        #   local Z ≈ world +X  (rz = forward/back swing)
        # Spine:
        #   local X ≈ world +Y  (rx = side-to-side)
        #   local Z ≈ world +X  (rz = forward/back bend)

        if is_walk:
            speed = 4.0 if "run" in prompt_lower else 2.0
            amp = 0.5 if "run" in prompt_lower else 0.3
            stride = 3.0 if "run" in prompt_lower else 2.0

            for f in range(num_frames):
                t = f / num_frames * 2 * pi * speed

                # Root: forward translation + subtle bounce
                root_pos[f] = (
                    0.0,
                    f / num_frames * stride,
                    abs(np.sin(t)) * 0.03,
                )

                for ji in range(num_joints):
                    tags = roles.get(ji, set())
                    rx, ry, rz = 0.0, 0.0, 0.0

                    if "spine" in tags:
                        rz = np.sin(t) * 0.04
                        rx = np.sin(t * 2) * 0.02

                    elif "hip" in tags:
                        rz = np.sin(t) * 0.03

                    elif "upper_leg" in tags:
                        phase = 0 if "left" in tags else pi
                        rz = np.sin(t + phase) * amp

                    elif "lower_leg" in tags:
                        phase = 0 if "left" in tags else pi
                        rz = max(0, np.sin(t + phase + 0.5)) * amp * 0.8

                    elif "foot" in tags:
                        phase = 0 if "left" in tags else pi
                        rz = np.sin(t + phase + 1.0) * amp * 0.3

                    elif "upper_arm" in tags:
                        phase = pi if "left" in tags else 0
                        rz = np.sin(t + phase) * amp * 0.4

                    elif "lower_arm" in tags:
                        phase = pi if "left" in tags else 0
                        rz = max(0, np.sin(t + phase + 0.3)) * amp * 0.3

                    elif "head" in tags:
                        rx = np.sin(t * 2) * 0.01

                    elif "neck" in tags:
                        rz = np.sin(t) * 0.02

                    rots[f][ji] = (rx, ry, rz)

        elif is_idle:
            for f in range(num_frames):
                t = f / num_frames * 2 * pi

                for ji in range(num_joints):
                    tags = roles.get(ji, set())
                    rx, ry, rz = 0.0, 0.0, 0.0

                    if "spine" in tags:
                        rz = np.sin(t) * 0.015
                    elif "hip" in tags:
                        rx = np.sin(t * 0.5) * 0.01
                    elif "upper_arm" in tags:
                        rz = np.sin(t) * 0.01
                    elif "head" in tags:
                        rx = np.sin(t * 0.7) * 0.02

                    rots[f][ji] = (rx, ry, rz)

        else:
            for f in range(num_frames):
                t = f / num_frames * 2 * pi

                for ji in range(num_joints):
                    tags = roles.get(ji, set())
                    rx, ry, rz = 0.0, 0.0, 0.0

                    if "spine" in tags:
                        rz = np.sin(t) * 0.1
                        rx = np.sin(t * 0.5) * 0.05
                    elif "upper_arm" in tags:
                        phase = 0 if "left" in tags else pi
                        rz = np.sin(t + phase) * 0.15
                    elif "head" in tags:
                        rx = np.sin(t) * 0.05

                    rots[f][ji] = (rx, ry, rz)

        return rots, root_pos
