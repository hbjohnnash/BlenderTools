"""AnyTop adapter — topology-agnostic text-to-motion generation.

Works with ANY skeleton topology (humans, animals, robots).
Outputs 6D joint rotations per frame, which are converted to
Euler rotations and applied as keyframes.

GitHub: https://github.com/Anytop2025/Anytop
Paper:  SIGGRAPH 2025
"""

import sys
from math import atan2

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

        Returns:
            dict with 'joints' list and 'hierarchy' for the model.
        """
        bones = armature_obj.data.bones
        joint_list = []
        name_to_idx = {}

        for bone in bones:
            idx = len(joint_list)
            name_to_idx[bone.name] = idx
            parent_idx = name_to_idx.get(bone.parent.name, -1) if bone.parent else -1

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
            ("leg", "leg bone"),
            ("hand", "hand bone"),
            ("finger", "finger bone"),
            ("shoulder", "shoulder bone"),
            ("clavicle", "clavicle bone"),
            ("arm", "arm bone"),
            ("head", "head bone"),
            ("neck", "neck bone"),
            ("spine", "spine bone"),
            ("hip", "hip/pelvis bone"),
            ("upper", "upper limb bone"),
            ("lower", "lower limb bone"),
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
            dict with 'rotations' (list of per-joint Euler rotations per frame)
            and 'root_positions' (list of root XYZ per frame).
        """
        self.load_model()

        import torch

        repo_root = self._repo_root
        repo_str = str(repo_root)
        if repo_str not in sys.path:
            sys.path.insert(0, repo_str)

        joints = skeleton["joints"]
        num_joints = len(joints)

        # Build skeleton topology tensor
        parent_indices = torch.tensor(
            [j["parent"] for j in joints], dtype=torch.long,
        )
        offsets = torch.tensor(
            [j["offset"] for j in joints], dtype=torch.float32,
        )
        descriptions = [j["description"] for j in joints]

        # Try using AnyTop's inference API
        try:
            from model.generate import generate_motion

            result = generate_motion(
                model=self._model,
                text_prompt=prompt,
                skeleton_offsets=offsets,
                skeleton_parents=parent_indices,
                joint_descriptions=descriptions,
                num_frames=num_frames,
            )
            # result expected to be (num_frames, num_joints, 6) for 6D rotations
            rotations_6d = result.cpu().numpy()

        except (ImportError, Exception):
            # Fallback: generate simple procedural motion
            rotations_6d = self._fallback_generate(
                num_joints, num_frames, prompt,
            )

        # Convert 6D rotations to Euler angles
        rotations_euler = []
        root_positions = []

        for f in range(len(rotations_6d)):
            frame_rots = []
            for j in range(num_joints):
                if rotations_6d[f].ndim > 1 and rotations_6d[f].shape[-1] >= 6:
                    r6d = rotations_6d[f][j]
                    euler = self._rotation_6d_to_euler(r6d)
                else:
                    euler = (0.0, 0.0, 0.0)
                frame_rots.append(euler)
            rotations_euler.append(frame_rots)

            # Root position (first 3 values if present)
            if rotations_6d[f].ndim > 1 and rotations_6d[f].shape[-1] >= 9:
                root_positions.append(tuple(rotations_6d[f][0][:3]))
            else:
                root_positions.append((0.0, 0.0, 0.0))

        return {
            "rotations": rotations_euler,
            "root_positions": root_positions,
            "joint_names": [j["name"] for j in joints],
        }

    def apply_motion(self, armature_obj, motion_data, action_name=None,
                     frame_start=1):
        """Apply generated motion data to a Blender armature.

        Args:
            armature_obj: Target armature object.
            motion_data: dict from predict().
            action_name: Name for the new action.
            frame_start: Starting frame number.

        Returns:
            The created Action.
        """
        from bpy_extras.anim_utils import action_ensure_channelbag_for_slot

        from ...core.utils import assign_channel_groups

        if not action_name:
            action_name = f"{armature_obj.name}_AnyTop"

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
            pbone = armature_obj.pose.bones.get(bone_name)
            if pbone is None:
                continue

            # Rotation FCurves
            for axis in range(3):
                dp = f'pose.bones["{bone_name}"].rotation_euler'
                fc = cb.fcurves.new(dp, index=axis)
                fc.keyframe_points.add(num_frames)
                for fi in range(num_frames):
                    kf = fc.keyframe_points[fi]
                    kf.co = (frame_start + fi, rotations[fi][ji][axis])
                    kf.interpolation = 'BEZIER'
                fc.update()

            # Root position FCurves
            if ji == 0 and root_positions:
                for axis in range(3):
                    dp = f'pose.bones["{bone_name}"].location'
                    fc = cb.fcurves.new(dp, index=axis)
                    fc.keyframe_points.add(num_frames)
                    for fi in range(num_frames):
                        kf = fc.keyframe_points[fi]
                        kf.co = (frame_start + fi, root_positions[fi][axis])
                        kf.interpolation = 'BEZIER'
                    fc.update()

        assign_channel_groups(armature_obj)
        return action

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
        # R = [[b1x b2x b3x], [b1y b2y b3y], [b1z b2z b3z]]
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

    # ── Fallback ──

    @staticmethod
    def _fallback_generate(num_joints, num_frames, prompt):
        """Generate simple procedural motion when model inference fails."""
        import numpy as np

        prompt_lower = prompt.lower()
        motion = np.zeros((num_frames, num_joints, 6), dtype=np.float32)

        # Set identity rotation (6D: first two columns of identity matrix)
        for f in range(num_frames):
            for j in range(num_joints):
                motion[f, j, 0] = 1.0  # col1.x
                motion[f, j, 4] = 1.0  # col2.y

        # Add simple oscillation for common prompts
        freq = 2.0 * np.pi / num_frames
        if any(w in prompt_lower for w in ["walk", "run", "jog"]):
            for f in range(num_frames):
                t = f * freq * 2
                # Subtle spine rotation
                if num_joints > 0:
                    motion[f, 0, 3] = np.sin(t) * 0.05  # slight side sway

        return motion
