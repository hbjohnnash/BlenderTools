"""AnyTop adapter — topology-agnostic text-to-motion generation.

Works with ANY skeleton topology (humans, animals, robots).
Uses the AnyTop diffusion model (SIGGRAPH 2025) for text-conditioned
motion generation, with automatic skeleton conditioning and T5-based
joint name encoding.

Pipeline:
    1. Extract skeleton topology from Blender armature
    2. Build conditioning (graph topology, T-pose, T5 embeddings)
    3. Run 100-step cosine-schedule diffusion sampling
    4. Recover Euler rotations + root position from 13D features
    5. Apply as keyframes to pose bones (CTRL FK when wrap rig exists)

Falls back to procedural motion when model inference fails.

GitHub: https://github.com/Anytop2025/Anytop
Paper:  SIGGRAPH 2025
"""

import sys
from math import atan2, pi

import bpy
import numpy as np

from ...core.ml.base_adapter import BaseModelAdapter

_CODE_URL = (
    "https://github.com/Anytop2025/Anytop/archive/refs/heads/main.zip"
)

# HuggingFace repo: inbar2344/AnyTop
# Contains checkpoints/ and dataset/ directories.
_HF_REPO = "inbar2344/AnyTop"

# AnyTop uses generic top-level package names that conflict with other
# modules in Blender's Python environment.  We need to isolate imports.
_ANYTOP_PKGS = ("model", "utils", "diffusion", "data_loaders")


class AnyTopAdapter(BaseModelAdapter):
    MODEL_ID = "anytop"
    MODEL_NAME = "AnyTop"
    MODEL_DESC = "Text-to-motion for any skeleton topology (SIGGRAPH 2025)"
    MODEL_TYPE = "animation"
    VERSION = "1.0"

    CODE_URL = _CODE_URL
    # Weights are on HuggingFace — downloaded via huggingface_hub.
    # WEIGHT_URLS left empty; download_weights is overridden to use HF.
    WEIGHT_URLS = {}
    EXTRA_DEPS = ["einops", "tqdm", "huggingface_hub", "transformers"]

    # ── High-level generation API ──

    def generate(self, armature_obj, prompt, num_frames=120):
        """Generate motion for *armature_obj*, retargeting when possible.

        When a wrap rig with scan data exists, generates on the
        standard SMPL skeleton and retargets via an influence map.
        Falls back to direct generation on the user's skeleton
        otherwise.

        Args:
            armature_obj: Blender armature.
            prompt: Text description (e.g. "a person walking").
            num_frames: Number of frames to generate.

        Returns:
            Motion data dict — either retargeted format (with
            ``is_retargeted=True``) or legacy format.
        """
        from ..retarget import has_wrap_rig
        from . import smpl_skeleton
        from .retarget_map import apply_retarget, build_default_influence_map

        scan_data = getattr(armature_obj, 'bt_scan', None)
        use_retarget = (
            scan_data
            and getattr(scan_data, 'has_wrap_rig', False)
            and has_wrap_rig(armature_obj)
        )

        if use_retarget:
            # Generate on standard SMPL skeleton
            smpl_skel = smpl_skeleton.get_skeleton()
            motion_data = self.predict(smpl_skel, prompt, num_frames)

            # Build influence map from wrap rig scan data
            imap = build_default_influence_map(scan_data, armature_obj)
            if imap and not imap.is_empty():
                # Run any registered refiners
                imap.apply_refiners({
                    'armature_obj': armature_obj,
                    'scan_data': scan_data,
                })

                # Scale root positions to user skeleton size
                user_height = self._get_armature_height(armature_obj)
                smpl_height = smpl_skeleton.SKELETON_HEIGHT
                pos_scale = (user_height / smpl_height
                             if smpl_height > 1e-6 else 1.0)

                # Root positions: Y↔Z swap gives +Y forward, negate
                # X and Y to get Blender -Y forward convention.
                # Rotations already face -Y (proper rotation conversion).
                pos_corrected = [
                    (-x, -y, z)
                    for x, y, z in motion_data['root_positions']
                ]

                retargeted = apply_retarget(
                    motion_data['rotations'],
                    pos_corrected,
                    imap,
                    armature_obj=armature_obj,
                    position_scale=pos_scale,
                )
                # Preserve raw SMPL data for preview animation
                retargeted['_smpl_rotations'] = motion_data['rotations']
                retargeted['_smpl_root_positions'] = motion_data[
                    'root_positions'
                ]
                return retargeted

        # Fallback: direct generation on user's skeleton
        skeleton = self.extract_skeleton(armature_obj)
        return self.predict(skeleton, prompt, num_frames)

    @staticmethod
    def _get_armature_height(armature_obj):
        """Compute armature height from bone positions (Z-up)."""
        z_vals = []
        for bone in armature_obj.data.bones:
            z_vals.append(bone.head_local.z)
            z_vals.append(bone.tail_local.z)
        return (max(z_vals) - min(z_vals)) if z_vals else 1.8

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

            # Determine which Euler axis produces forward/back swing.
            # World X = (1,0,0) is the rotation axis for YZ-plane motion
            # (forward/back).  Find which bone-local axis aligns with it.
            mat = bone.matrix_local
            best_axis = 0
            best_dot = 0.0
            for col in range(3):
                local_vec = [mat[row][col] for row in range(3)]
                dot = abs(local_vec[0])  # dot with (1,0,0)
                if dot > best_dot:
                    best_dot = dot
                    best_axis = col

            joint_list.append({
                "name": bone.name,
                "parent": parent_idx,
                "offset": [offset.x, offset.y, offset.z],
                "description": self._bone_description(bone.name),
                "swing_axis": best_axis,  # 0=X, 1=Y, 2=Z
            })

        # Compute skeleton height for scale-aware motion
        z_vals = []
        for bone in bones:
            if bone.name in deform_names:
                z_vals.append(bone.head_local.z)
                z_vals.append(bone.tail_local.z)
        skel_height = (max(z_vals) - min(z_vals)) if z_vals else 1.8

        return {"joints": joint_list, "height": skel_height}

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
            progress_callback(0.1, "Downloading AnyTop from HuggingFace...")

        snapshot_download(
            repo_id=_HF_REPO,
            local_dir=str(weights_dir / "hf_snapshot"),
            allow_patterns=["checkpoints/**"],
        )

        if progress_callback:
            progress_callback(0.6, "Downloading T5 text encoder...")

        # Pre-download T5 model so first generation doesn't stall
        try:
            from transformers import T5EncoderModel, T5Tokenizer
            T5Tokenizer.from_pretrained("t5-base")
            T5EncoderModel.from_pretrained("t5-base")
        except Exception:
            pass  # T5 will download on first use if this fails

        if progress_callback:
            progress_callback(1.0, "AnyTop weights downloaded")

    # ── Import isolation ──

    @staticmethod
    def _ensure_anytop_packages(repo_root):
        """Create missing ``__init__.py`` in AnyTop repo directories.

        AnyTop ships without ``__init__.py`` in ``model/``, ``diffusion/``,
        and ``data_loaders/``, relying on implicit-namespace-package
        semantics.  This fails when Blender's Python already has
        cached modules with those generic names.  Creating the files
        converts them to proper packages whose location is unambiguous.
        """
        for pkg in ("model", "diffusion", "data_loaders"):
            init = repo_root / pkg / "__init__.py"
            if not init.exists() and init.parent.exists():
                init.touch()

    @staticmethod
    def _setup_anytop_imports(repo_root):
        """Clear conflicting ``sys.modules`` entries and fix ``sys.path``.

        Returns a dict of evicted modules (kept for diagnostics only —
        we intentionally do **not** restore them because the AnyTop
        model object holds live references to its own module classes).
        """
        repo_str = str(repo_root)

        evicted = {}
        for name in list(sys.modules.keys()):
            for pkg in _ANYTOP_PKGS:
                if name == pkg or name.startswith(pkg + "."):
                    evicted[name] = sys.modules.pop(name)
                    break

        # Ensure repo is *first* so Python finds AnyTop's packages
        if repo_str in sys.path:
            sys.path.remove(repo_str)
        sys.path.insert(0, repo_str)

        return evicted

    # ── Model loading ──

    def _get_repo_root(self):
        code_dir = self.get_code_dir()
        candidates = list(code_dir.iterdir()) if code_dir.exists() else []
        for c in candidates:
            if c.is_dir() and (c / "model").exists():
                return c
        return code_dir / "Anytop-main"

    def _find_checkpoint(self):
        """Locate the best model checkpoint file in the weights directory."""
        weights_dir = self.get_weights_dir()
        candidates = sorted(weights_dir.rglob("model*.pt"), reverse=True)
        # Prefer the all_model checkpoint (trained on all skeleton types)
        for pt in candidates:
            if "all_model" in pt.parent.name:
                return pt
        return candidates[0] if candidates else None

    def load_model(self):
        """Load AnyTop model, diffusion, and T5 conditioner."""
        if self._model is not None:
            return

        import json
        from argparse import Namespace

        import torch

        repo_root = self._get_repo_root()

        # AnyTop uses generic package names (model, utils, diffusion,
        # data_loaders) that collide with other modules in Blender's
        # Python.  Create missing __init__.py and isolate sys.modules.
        self._ensure_anytop_packages(repo_root)
        self._setup_anytop_imports(repo_root)

        # Find checkpoint and load args
        ckpt_path = self._find_checkpoint()
        if ckpt_path is None:
            raise FileNotFoundError(
                "AnyTop checkpoint not found. Re-run 'Initialize AI Motion'."
            )

        args_path = ckpt_path.parent / "args.json"
        with open(args_path) as f:
            args_dict = json.load(f)
        args = Namespace(**args_dict)

        # Create model and diffusion pipeline
        from utils.model_util import create_model_and_diffusion_general_skeleton
        from utils.model_util import load_model as load_weights

        model_net, diffusion = create_model_and_diffusion_general_skeleton(
            args,
        )

        if model_net is None:
            raise RuntimeError(
                "AnyTop model constructor returned None — check "
                "that the checkpoint args.json matches the model code."
            )

        # Load trained weights
        state_dict = torch.load(
            ckpt_path, map_location="cpu", weights_only=False,
        )
        load_weights(model_net, state_dict)

        # Set device and eval mode
        # NOTE: AnyTop's _apply() override forgets to return self,
        # so .to() returns None.  Call without reassignment.
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model_net.to(device)
        model_net.eval()

        # Initialize dist_util for any internal device lookups
        from utils import dist_util
        dist_util.setup_dist(0 if device == "cuda" else -1)

        self._model = {
            "net": model_net,
            "diffusion": diffusion,
            "device": device,
            "temporal_window": getattr(args, "temporal_window", 31),
        }
        self._repo_root = repo_root

    def unload_model(self):
        """Free model from memory."""
        from .anytop_conditioning import _t5_cache
        _t5_cache.clear()
        self._model = None
        self._repo_root = None

        # Remove AnyTop's generic-named modules so they don't linger
        for name in list(sys.modules.keys()):
            for pkg in _ANYTOP_PKGS:
                if name == pkg or name.startswith(pkg + "."):
                    del sys.modules[name]
                    break

        import gc
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    # ── Inference ──

    def predict(self, skeleton, prompt, num_frames=120):
        """Generate motion from text prompt for the given skeleton.

        Uses the full AnyTop diffusion pipeline:
            1. Scale skeleton to training space (HML_AVG_BONELEN)
            2. Build conditioning from skeleton topology
            3. Encode joint names via T5
            4. Run 100-step denoising diffusion
            5. Recover rotations and root position from features
            6. Scale output positions back to Blender units

        Falls back to procedural motion on any failure.

        Args:
            skeleton: dict from extract_skeleton().
            prompt: Text description (e.g. "a person walking forward").
            num_frames: Number of frames to generate.

        Returns:
            dict with 'rotations', 'root_positions', 'joint_names'.
        """
        joints = skeleton["joints"]
        num_joints = len(joints)

        try:
            self.load_model()
            import torch

            model_net = self._model["net"]
            diffusion = self._model["diffusion"]
            device = self._model["device"]
            temporal_window = self._model["temporal_window"]

            # Ensure AnyTop repo is on path for data_loaders import
            self._setup_anytop_imports(self._repo_root)

            from .anytop_conditioning import (
                FEATURE_LEN,
                MAX_JOINTS,
                build_cond_dict,
                create_temporal_mask,
                encode_joint_names_t5,
                scale_and_ground_skeleton,
            )

            # 1. Convert Blender Z-up → AnyTop Y-up: swap Y ↔ Z
            joints_yup = [
                {**j, "offset": [j["offset"][0], j["offset"][2],
                                 j["offset"][1]]}
                for j in joints
            ]

            # 2. Scale to training space + ground (min Y = 0)
            scaled_joints, scale_factor = scale_and_ground_skeleton(
                joints_yup,
            )
            skeleton_scaled = {"joints": scaled_joints}

            # 3. Build conditioning from scaled skeleton
            object_type = "blender_skeleton"
            cond_dict = build_cond_dict(skeleton_scaled, object_type)
            cond = cond_dict[object_type]

            # 4. Encode joint names via T5
            # truebones_batch_collate expects (n_joints, 768) — it handles
            # padding to MAX_JOINTS internally.  Slice off the padding.
            joint_names_embs = encode_joint_names_t5(
                cond["joints_names"], device=device,
            )[:num_joints].detach().cpu().numpy()

            # Normalize T-pose for model input
            tpose_norm = (
                (cond["tpos_first_frame"] - cond["mean"])
                / (cond["std"] + 1e-6)
            )
            tpose_norm = np.nan_to_num(tpose_norm)

            # 5. Build batch in the format expected by truebones_batch_collate
            temporal_mask = create_temporal_mask(temporal_window, num_frames)
            batch = [
                np.zeros((num_frames, num_joints, FEATURE_LEN)),
                num_frames,
                cond["parents"],
                tpose_norm,
                cond["offsets"],
                temporal_mask,
                cond["joints_graph_dist"],
                cond["joint_relations"],
                object_type,
                joint_names_embs,
                0,                  # crop_start_ind
                cond["mean"],
                cond["std"],
                MAX_JOINTS,
            ]

            from data_loaders.tensors import truebones_batch_collate
            _, model_kwargs = truebones_batch_collate([batch])

            # Move tensors to model device
            for k, v in model_kwargs["y"].items():
                if isinstance(v, torch.Tensor):
                    model_kwargs["y"][k] = v.to(device)

            # 6. Run diffusion sampling (100 denoising steps)
            sample = diffusion.p_sample_loop(
                model_net,
                (1, MAX_JOINTS, model_net.feature_len, num_frames),
                clip_denoised=False,
                model_kwargs=model_kwargs,
                skip_timesteps=0,
                init_image=None,
                progress=True,
                dump_steps=None,
                noise=None,
                const_noise=False,
            )

            # 7. Extract and denormalize
            motion = sample[0, :num_joints]  # trim joint padding
            motion = motion.cpu().permute(2, 0, 1).numpy()  # → (F, J, 13)
            mean = cond["mean"][np.newaxis, :]
            std = cond["std"][np.newaxis, :]
            motion = motion * std + mean

            # 8. Recover rotations and root position
            rotations_euler, root_positions = self._recover_motion(
                motion, num_joints, skeleton, scale_factor,
            )

        except Exception:
            import traceback
            traceback.print_exc()
            rotations_euler, root_positions = self._fallback_generate(
                skeleton, num_frames, prompt,
            )

        return {
            "rotations": rotations_euler,
            "root_positions": root_positions,
            "joint_names": [j["name"] for j in joints],
        }

    # ── Motion recovery from 13D features ──

    def _recover_motion(self, motion, num_joints, skeleton, scale_factor):
        """Recover Euler rotations and root position from denormalized features.

        Pipeline:
          1. Extract root rotation from 6D features at joint 0
          2. Integrate local-frame velocity to get root world position
          3. Extract local rotations from 6D features for ALL joints
          4. Convert rotations from AnyTop Y-up to Blender Z-up
          5. Un-scale root positions back to original skeleton units

        Args:
            motion: ``(n_frames, n_joints, 13)`` denormalized features
                    in AnyTop training-space (Y-up, HML_AVG_BONELEN).
            num_joints: actual joint count (unpadded).
            skeleton: dict from ``extract_skeleton()`` (Blender Z-up).
            scale_factor: from ``scale_and_ground_skeleton`` — multiply
                          training-space positions by ``1/scale_factor``
                          to get original Blender units.

        Returns:
            ``(rotations_euler, root_positions)`` — per-frame lists.
        """
        n_frames = motion.shape[0]

        # ── 1. Root rotation from 6D features (Y-up space) ──
        root_6d = motion[:, 0, 3:9]
        root_rot = self._rotation_6d_to_matrix_batch(root_6d)

        # ── 2. Root position from velocity integration (Y-up) ──
        root_pos = np.zeros((n_frames, 3))
        root_pos[1:, 0] = motion[:-1, 0, 9]   # X velocity (local)
        root_pos[1:, 2] = motion[:-1, 0, 11]  # Z velocity (local)
        for f in range(n_frames):
            root_pos[f] = root_rot[f] @ root_pos[f]
        root_pos = np.cumsum(root_pos, axis=0)
        root_pos[:, 1] = motion[:, 0, 1]  # Y = absolute height

        # Un-scale and convert Y-up → Z-up for root positions
        root_pos /= scale_factor
        root_positions = [
            (float(root_pos[f, 0]),
             float(root_pos[f, 2]),   # Blender Y = AnyTop Z
             float(root_pos[f, 1]))   # Blender Z = AnyTop Y
            for f in range(n_frames)
        ]

        # ── 3. Extract local rotations from 6D features (all joints) ──
        # The 6D rotation at indices [3:9] encodes the local rotation
        # of each joint relative to its parent.  Using these directly
        # preserves all 3 DOF including twist, unlike position-based
        # reconstruction which loses the bone-axis rotation.
        all_6d = motion[:, :num_joints, 3:9].reshape(-1, 6)
        all_R_yup = self._rotation_6d_to_matrix_batch(all_6d)
        all_R_yup = all_R_yup.reshape(n_frames, num_joints, 3, 3)

        # ── 4. Convert rotations Y-up → Z-up ──
        # Use proper rotation (det=+1): Rot(X, -90°) maps Y→Z, Z→-Y.
        # Preserves rotation directions (no axis inversions).
        _C = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=np.float64)
        all_R_zup = _C @ all_R_yup @ _C

        # Convert to Euler XYZ
        rotations_euler = []
        for f in range(n_frames):
            frame_euler = []
            for j in range(num_joints):
                frame_euler.append(
                    self._matrix_to_euler_xyz(all_R_zup[f, j]),
                )
            rotations_euler.append(frame_euler)

        return rotations_euler, root_positions

    @staticmethod
    def _matrix_to_euler_xyz(R):
        """Convert 3×3 rotation matrix to Euler XYZ angles (radians)."""
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

    # ── Apply motion to Blender ──

    def apply_motion(self, armature_obj, motion_data, action_name=None,
                     frame_start=1):
        """Apply generated motion data to a Blender armature.

        Handles both retargeted format (``is_retargeted=True``, with
        ``bone_rotations`` dict) and legacy format (``rotations``
        list + ``joint_names``).

        Returns:
            The created Action.
        """
        if motion_data.get('is_retargeted'):
            return self._apply_retargeted_motion(
                armature_obj, motion_data, action_name, frame_start,
            )
        return self._apply_direct_motion(
            armature_obj, motion_data, action_name, frame_start,
        )

    def _apply_retargeted_motion(self, armature_obj, motion_data,
                                 action_name=None, frame_start=1):
        """Apply retargeted motion — bone_rotations dict format."""
        from bpy_extras.anim_utils import action_ensure_channelbag_for_slot

        from ...core.utils import assign_channel_groups

        if not action_name:
            action_name = f"{armature_obj.name}_AnyTop"

        self._ensure_fk_mode(armature_obj)

        action = bpy.data.actions.new(name=action_name)
        if not armature_obj.animation_data:
            armature_obj.animation_data_create()

        armature_obj.animation_data.action = action
        slot = action.slots.new(name=armature_obj.name, id_type='OBJECT')
        armature_obj.animation_data.action_slot = slot
        cb = action_ensure_channelbag_for_slot(action, slot)

        bone_rotations = motion_data['bone_rotations']
        root_positions = motion_data.get('root_positions', [])
        root_bone = motion_data.get('root_bone')

        for bone_name, frame_rots in bone_rotations.items():
            pbone = armature_obj.pose.bones.get(bone_name)
            if pbone is None:
                continue
            pbone.rotation_mode = 'XYZ'

            num_frames = len(frame_rots)
            for axis in range(3):
                dp = f'pose.bones["{bone_name}"].rotation_euler'
                fc = cb.fcurves.new(dp, index=axis)
                fc.keyframe_points.add(num_frames)
                for fi in range(num_frames):
                    kf = fc.keyframe_points[fi]
                    kf.co = (frame_start + fi, frame_rots[fi][axis])
                    kf.interpolation = 'BEZIER'
                fc.update()

        # Root position keyframes
        if root_bone and root_positions:
            pbone = armature_obj.pose.bones.get(root_bone)
            if pbone:
                num_frames = len(root_positions)
                for axis in range(3):
                    dp = f'pose.bones["{root_bone}"].location'
                    fc = cb.fcurves.new(dp, index=axis)
                    fc.keyframe_points.add(num_frames)
                    for fi in range(num_frames):
                        kf = fc.keyframe_points[fi]
                        kf.co = (frame_start + fi,
                                 root_positions[fi][axis])
                        kf.interpolation = 'BEZIER'
                    fc.update()

        assign_channel_groups(armature_obj)
        return action

    def _apply_direct_motion(self, armature_obj, motion_data,
                             action_name=None, frame_start=1):
        """Apply direct (legacy) motion — joint_names + rotations list."""
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
    def _rotation_6d_to_matrix_batch(r6d):
        """Convert batch of 6D rotation representations to 3×3 matrices.

        Uses Gram-Schmidt orthogonalisation (Zhou et al., CVPR 2019).

        Args:
            r6d: ``(N, 6)`` array — two 3D column vectors per rotation.

        Returns:
            ``(N, 3, 3)`` array of rotation matrices.
        """
        a1 = r6d[:, :3].astype(np.float64)
        a2 = r6d[:, 3:6].astype(np.float64)

        b1 = a1 / (np.linalg.norm(a1, axis=1, keepdims=True) + 1e-8)
        dot = np.sum(b1 * a2, axis=1, keepdims=True)
        b2 = a2 - dot * b1
        b2 = b2 / (np.linalg.norm(b2, axis=1, keepdims=True) + 1e-8)
        b3 = np.cross(b1, b2)

        R = np.stack([b1, b2, b3], axis=-1)  # (N, 3, 3)
        return R

    @staticmethod
    def _rotation_6d_to_euler(r6d):
        """Convert 6D rotation representation to Euler XYZ angles.

        The 6D representation is the first two columns of the rotation matrix.
        """
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
        joints = skeleton["joints"]
        num_joints = len(joints)
        prompt_lower = prompt.lower()

        # Classify each joint by its description and read its swing axis
        roles = {}   # index → set of tags
        swing = {}   # index → euler component for fwd/back (0=X, 1=Y, 2=Z)
        for i, j in enumerate(joints):
            desc = j.get("description", "").lower()
            swing[i] = j.get("swing_axis", 2)  # default Z if not set
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

        # Scale factor: root translations scale with skeleton height.
        # A 1.8m human is the baseline; a 4m robot gets ~2.2x larger strides.
        height = skeleton.get("height", 1.8)
        scale = height / 1.8

        # Initialise output as zeros
        rots = [[(0.0, 0.0, 0.0)] * num_joints for _ in range(num_frames)]
        root_pos = [(0.0, 0.0, 0.0)] * num_frames

        is_walk = any(w in prompt_lower for w in ["walk", "run", "jog"])
        is_idle = any(w in prompt_lower
                      for w in ["idle", "stand", "breathe", "rest"])

        def _set_axis(axis_idx, value):
            """Return an (rx, ry, rz) tuple with *value* on *axis_idx*."""
            r = [0.0, 0.0, 0.0]
            r[axis_idx] = value
            return tuple(r)

        def _set_two(axis_a, val_a, axis_b, val_b):
            """Return (rx, ry, rz) with two axes set."""
            r = [0.0, 0.0, 0.0]
            r[axis_a] = val_a
            r[axis_b] = val_b
            return tuple(r)

        if is_walk:
            speed = 4.0 if "run" in prompt_lower else 2.0
            amp = 0.5 if "run" in prompt_lower else 0.3
            stride = 3.0 if "run" in prompt_lower else 2.0

            for f in range(num_frames):
                t = f / num_frames * 2 * pi * speed

                root_pos[f] = (
                    0.0,
                    f / num_frames * stride * scale,
                    abs(np.sin(t)) * 0.03 * scale,
                )

                for ji in range(num_joints):
                    tags = roles.get(ji, set())
                    sa = swing[ji]  # forward/back axis for this bone

                    if "spine" in tags:
                        rots[f][ji] = _set_two(
                            sa, np.sin(t) * 0.04,
                            (sa + 1) % 3, np.sin(t * 2) * 0.02,
                        )

                    elif "hip" in tags:
                        rots[f][ji] = _set_axis(sa, np.sin(t) * 0.03)

                    elif "upper_leg" in tags:
                        phase = 0 if "left" in tags else pi
                        rots[f][ji] = _set_axis(
                            sa, np.sin(t + phase) * amp,
                        )

                    elif "lower_leg" in tags:
                        phase = 0 if "left" in tags else pi
                        rots[f][ji] = _set_axis(
                            sa, max(0, np.sin(t + phase + 0.5)) * amp * 0.8,
                        )

                    elif "foot" in tags:
                        phase = 0 if "left" in tags else pi
                        rots[f][ji] = _set_axis(
                            sa, np.sin(t + phase + 1.0) * amp * 0.3,
                        )

                    elif "upper_arm" in tags:
                        phase = pi if "left" in tags else 0
                        rots[f][ji] = _set_axis(
                            sa, np.sin(t + phase) * amp * 0.4,
                        )

                    elif "lower_arm" in tags:
                        phase = pi if "left" in tags else 0
                        rots[f][ji] = _set_axis(
                            sa, max(0, np.sin(t + phase + 0.3)) * amp * 0.3,
                        )

                    elif "head" in tags:
                        rots[f][ji] = _set_axis(
                            (sa + 1) % 3, np.sin(t * 2) * 0.01,
                        )

                    elif "neck" in tags:
                        rots[f][ji] = _set_axis(sa, np.sin(t) * 0.02)

        elif is_idle:
            for f in range(num_frames):
                t = f / num_frames * 2 * pi

                for ji in range(num_joints):
                    tags = roles.get(ji, set())
                    sa = swing[ji]

                    if "spine" in tags:
                        rots[f][ji] = _set_axis(sa, np.sin(t) * 0.015)
                    elif "hip" in tags:
                        rots[f][ji] = _set_axis(
                            (sa + 1) % 3, np.sin(t * 0.5) * 0.01,
                        )
                    elif "upper_arm" in tags:
                        rots[f][ji] = _set_axis(sa, np.sin(t) * 0.01)
                    elif "head" in tags:
                        rots[f][ji] = _set_axis(
                            (sa + 1) % 3, np.sin(t * 0.7) * 0.02,
                        )

        else:
            for f in range(num_frames):
                t = f / num_frames * 2 * pi

                for ji in range(num_joints):
                    tags = roles.get(ji, set())
                    sa = swing[ji]

                    if "spine" in tags:
                        rots[f][ji] = _set_two(
                            sa, np.sin(t) * 0.1,
                            (sa + 1) % 3, np.sin(t * 0.5) * 0.05,
                        )
                    elif "upper_arm" in tags:
                        phase = 0 if "left" in tags else pi
                        rots[f][ji] = _set_axis(
                            sa, np.sin(t + phase) * 0.15,
                        )
                    elif "head" in tags:
                        rots[f][ji] = _set_axis(
                            (sa + 1) % 3, np.sin(t) * 0.05,
                        )

        return rots, root_pos
