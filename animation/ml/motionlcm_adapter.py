"""MotionLCM adapter — real-time text-to-motion for humanoid skeletons.

Uses MotionLCM (ECCV 2024) for single-step latent consistency diffusion
on the HumanML3D SMPL 22-joint skeleton.  Outputs feed into the same
retarget pipeline as AnyTop (conjugation + influence map).

Pipeline:
    1. Encode text prompt via Sentence-T5-Large
    2. Run 1-step latent consistency denoising
    3. Decode latent via VAE → 263-dim HumanML3D features
    4. Extract 6D joint rotations + root position from features
    5. Convert Y-up → Z-up for Blender
    6. Retarget via influence map to user armature

GitHub: https://github.com/Dai-Wenxun/MotionLCM
Paper:  ECCV 2024
"""

import inspect
import sys
from math import atan2

import numpy as np

from ...core.ml.base_adapter import BaseModelAdapter

_CODE_URL = (
    "https://github.com/Dai-Wenxun/MotionLCM/archive/refs/heads/main.zip"
)

# Google Drive file IDs for checkpoints
_GDRIVE_IDS = {
    "experiments_t2m": "1U7homKobR2gaDLfL5flS3N0g7e0a_AQd",
    "experiments_recons": "15zFDitcOLhjbQ0CaOoM-QNKQUeyJw-Om",
    "tiny_humanml3d": "1Mg_3RnWmRt0tk_lyLRRiOZg1W-Fu4wLL",
}

# MotionLCM uses the `mld` package internally
_LCM_PKGS = ("mld",)

# HumanML3D 263-dim feature layout
_FEAT_DIM = 263
_N_JOINTS = 22


def _guidance_scale_embedding(w, embedding_dim=512, dtype=None):
    """Sinusoidal embedding for guidance scale (from MotionLCM utils)."""
    import torch
    if dtype is None:
        dtype = torch.float32
    assert len(w.shape) == 1
    w = w * 1000.0
    half_dim = embedding_dim // 2
    emb = np.log(10000.0) / (half_dim - 1)
    emb = torch.exp(
        torch.arange(half_dim, dtype=dtype, device=w.device) * -emb
    )
    emb = w.to(dtype)[:, None] * emb[None, :]
    emb = torch.cat([torch.sin(emb), torch.cos(emb)], dim=1)
    if embedding_dim % 2 == 1:
        emb = torch.nn.functional.pad(emb, (0, 1))
    return emb


# ── Quaternion utilities for position-based IK ──


def _qmul(q1, q2):
    """Hamilton product of quaternions in (w, x, y, z) layout."""
    w1, x1, y1, z1 = q1[..., 0], q1[..., 1], q1[..., 2], q1[..., 3]
    w2, x2, y2, z2 = q2[..., 0], q2[..., 1], q2[..., 2], q2[..., 3]
    return np.stack([
        w1*w2 - x1*x2 - y1*y2 - z1*z2,
        w1*x2 + x1*w2 + y1*z2 - z1*y2,
        w1*y2 - x1*z2 + y1*w2 + z1*x2,
        w1*z2 + x1*y2 - y1*x2 + z1*w2,
    ], axis=-1)


def _qinv(q):
    """Conjugate of unit quaternion (w, x, y, z)."""
    out = q.copy()
    out[..., 1:] *= -1
    return out


def _qrot(q, v):
    """Rotate 3-D vector *v* by unit quaternion *q*."""
    qvec = q[..., 1:]
    uv = np.cross(qvec, v)
    uuv = np.cross(qvec, uv)
    return v + 2.0 * (q[..., 0:1] * uv + uuv)


def _qbetween(v0, v1):
    """Unit quaternion that rotates unit vector *v0* toward *v1*."""
    dot = np.sum(v0 * v1, axis=-1, keepdims=True)
    cross = np.cross(v0, v1)
    q = np.concatenate([1.0 + dot, cross], axis=-1)
    norms = np.linalg.norm(q, axis=-1, keepdims=True)
    # Antiparallel fallback — pick an arbitrary perpendicular axis
    bad = (norms < 1e-6).squeeze(-1)
    if np.any(bad):
        perp = np.zeros_like(v0[bad])
        perp[..., 1] = 1.0
        nearly_y = np.abs(v0[bad][..., 1]) > 0.9
        perp[nearly_y] = [1.0, 0.0, 0.0]
        perp = np.cross(v0[bad], perp)
        perp /= np.linalg.norm(perp, axis=-1, keepdims=True) + 1e-10
        q[bad] = np.concatenate([
            np.zeros((*perp.shape[:-1], 1)), perp,
        ], axis=-1)
        norms[bad] = np.linalg.norm(
            q[bad], axis=-1, keepdims=True,
        )
    return q / (norms + 1e-10)


def _quat_to_matrix(q):
    """Single quaternion (w, x, y, z) → 3×3 rotation matrix."""
    w, x, y, z = q
    return np.array([
        [1 - 2*(y*y + z*z), 2*(x*y - w*z),     2*(x*z + w*y)],
        [2*(x*y + w*z),     1 - 2*(x*x + z*z), 2*(y*z - w*x)],
        [2*(x*z - w*y),     2*(y*z + w*x),     1 - 2*(x*x + y*y)],
    ])


class MotionLCMAdapter(BaseModelAdapter):
    MODEL_ID = "motionlcm"
    MODEL_NAME = "MotionLCM"
    MODEL_DESC = "Real-time text-to-motion for humanoid skeletons (ECCV 2024)"
    MODEL_TYPE = "animation"
    VERSION = "1.0"

    CODE_URL = _CODE_URL
    WEIGHT_URLS = {}  # Downloaded via gdown
    EXTRA_DEPS = ["omegaconf", "gdown", "sentence-transformers", "diffusers"]

    # ── High-level generation API ──

    def generate(self, armature_obj, prompt, num_frames=120):
        """Generate humanoid motion and retarget to armature.

        Always generates on SMPL 22-joint skeleton, then retargets
        via influence map when a wrap rig is available.
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

        motion_data = self.predict(prompt, num_frames)

        if use_retarget:
            imap = build_default_influence_map(scan_data, armature_obj)
            if imap and not imap.is_empty():
                imap.apply_refiners({
                    'armature_obj': armature_obj,
                    'scan_data': scan_data,
                })

                user_height = self._get_armature_height(armature_obj)
                smpl_height = smpl_skeleton.SKELETON_HEIGHT
                pos_scale = (user_height / smpl_height
                             if smpl_height > 1e-6 else 1.0)

                # Root positions: Y↔Z swap gives +Y forward, negate
                # X and Y to get Blender -Y forward convention.
                # Rotations already face -Y (proper rotation conversion
                # in _recover_from_263 maps Z→-Y natively).
                pos_blender = [
                    (-x, -y, z)
                    for x, y, z in motion_data['root_positions']
                ]

                retargeted = apply_retarget(
                    motion_data['rotations'],
                    pos_blender,
                    imap,
                    armature_obj=armature_obj,
                    position_scale=pos_scale,
                )
                retargeted['_smpl_rotations'] = motion_data['rotations']
                retargeted['_smpl_root_positions'] = motion_data[
                    'root_positions'
                ]
                return retargeted

        return motion_data

    @staticmethod
    def _get_armature_height(armature_obj):
        z_vals = []
        for bone in armature_obj.data.bones:
            z_vals.append(bone.head_local.z)
            z_vals.append(bone.tail_local.z)
        return (max(z_vals) - min(z_vals)) if z_vals else 1.8

    # ── Download ──

    @classmethod
    def download_weights(cls, progress_callback=None):
        """Download MotionLCM checkpoints from Google Drive."""
        import gdown

        from ...core.ml import model_manager

        model_dir = model_manager.get_model_dir(cls.MODEL_ID)
        weights_dir = model_dir / "weights"
        weights_dir.mkdir(parents=True, exist_ok=True)

        steps = [
            ("experiments_t2m", "Downloading MotionLCM checkpoint..."),
            ("experiments_recons", "Downloading VAE checkpoint..."),
            ("tiny_humanml3d", "Downloading normalization data..."),
        ]

        for i, (key, msg) in enumerate(steps):
            if progress_callback:
                progress_callback(i / len(steps), msg)

            dest_zip = weights_dir / f"{key}.zip"
            dest_dir = weights_dir / key
            if dest_dir.exists():
                continue

            gdrive_url = (
                f"https://drive.google.com/uc?id={_GDRIVE_IDS[key]}"
            )
            gdown.download(gdrive_url, str(dest_zip), quiet=True)

            # Extract
            import zipfile
            with zipfile.ZipFile(dest_zip, "r") as zf:
                zf.extractall(weights_dir)
            dest_zip.unlink(missing_ok=True)

        # Pre-download sentence-T5 text encoder
        if progress_callback:
            progress_callback(0.85, "Downloading Sentence-T5 text encoder...")
        try:
            from sentence_transformers import SentenceTransformer
            SentenceTransformer("sentence-transformers/sentence-t5-large")
        except Exception:
            pass  # Will download on first use

        if progress_callback:
            progress_callback(1.0, "MotionLCM weights downloaded")

    # ── Import isolation ──

    def _get_repo_root(self):
        code_dir = self.get_code_dir()
        candidates = list(code_dir.iterdir()) if code_dir.exists() else []
        for c in candidates:
            if c.is_dir() and (c / "mld").exists():
                return c
        return code_dir / "MotionLCM-main"

    @staticmethod
    def _setup_lcm_imports(repo_root):
        """Fix sys.path for MotionLCM's ``mld`` package."""
        repo_str = str(repo_root)

        evicted = {}
        for name in list(sys.modules.keys()):
            for pkg in _LCM_PKGS:
                if name == pkg or name.startswith(pkg + "."):
                    evicted[name] = sys.modules.pop(name)
                    break

        if repo_str in sys.path:
            sys.path.remove(repo_str)
        sys.path.insert(0, repo_str)

        return evicted

    # ── Model loading ──

    def load_model(self):
        """Load MotionLCM components directly (bypasses heavy MLD class).

        Loads text_encoder, VAE, denoiser, and scheduler individually
        via ``instantiate_from_config`` — the same mechanism the upstream
        MLD class uses, but without pulling in training evaluators,
        metrics, or matplotlib.

        Steps:
            1. Load main YAML config + merge module sub-configs
            2. Override paths for our directory layout
            3. Load checkpoint and detect LCM mode (time_cond_proj_dim)
            4. Instantiate the 4 inference components
            5. Load VAE + denoiser weights from checkpoint
        """
        if self._model is not None:
            return

        import torch
        from omegaconf import OmegaConf

        repo_root = self._get_repo_root()
        self._setup_lcm_imports(repo_root)

        weights_dir = self.get_weights_dir()

        # 1. Load main config + merge module sub-configs
        cfg_path = repo_root / "configs" / "motionlcm_t2m.yaml"
        if not cfg_path.exists():
            raise FileNotFoundError(
                f"MotionLCM config not found at {cfg_path}. "
                "Re-run 'Initialize AI Motion'."
            )
        cfg = OmegaConf.load(cfg_path)

        targets = list(cfg.model.target)
        for module_name in targets:
            module_cfg_path = (
                repo_root / "configs" / "modules" / f"{module_name}.yaml"
            )
            if module_cfg_path.exists():
                module_cfg = OmegaConf.load(module_cfg_path)
                cfg.model = OmegaConf.merge(cfg.model, module_cfg)

        # 2. Fix paths
        self._fix_config_paths(cfg, weights_dir, repo_root)

        device = "cuda" if torch.cuda.is_available() else "cpu"

        # 3. Load checkpoint state dict and detect LCM architecture
        ckpt_path = self._find_checkpoint(weights_dir)
        if ckpt_path is None:
            raise FileNotFoundError(
                "MotionLCM checkpoint not found. "
                "Re-run 'Initialize AI Motion'."
            )

        ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
        state_dict = ckpt.get("state_dict", ckpt)

        # Detect LCM mode: checkpoint has time_cond_proj weights
        lcm_key = "denoiser.time_embedding.cond_proj.weight"
        is_lcm = lcm_key in state_dict
        if is_lcm:
            time_cond_proj_dim = state_dict[lcm_key].shape[1]
            OmegaConf.update(
                cfg, "model.denoiser.params.time_cond_proj_dim",
                int(time_cond_proj_dim), force_add=True,
            )

        # Resolve dynamic guidance scale
        guidance_scale = cfg.model.guidance_scale
        if guidance_scale == "dynamic":
            s_cfg = cfg.model.scheduler
            guidance_scale = s_cfg.cfg_step_map[s_cfg.num_inference_steps]

        # 4. Instantiate the 4 inference components
        from mld.config import instantiate_from_config

        text_encoder = instantiate_from_config(cfg.model.text_encoder)
        vae = instantiate_from_config(cfg.model.motion_vae)
        denoiser = instantiate_from_config(cfg.model.denoiser)
        scheduler = instantiate_from_config(cfg.model.scheduler)

        # 5. Load VAE + denoiser weights from checkpoint
        vae_sd = {
            k.removeprefix("vae."): v
            for k, v in state_dict.items()
            if k.startswith("vae.")
        }
        denoiser_sd = {
            k.removeprefix("denoiser."): v
            for k, v in state_dict.items()
            if k.startswith("denoiser.")
        }
        vae.load_state_dict(vae_sd, strict=False)
        denoiser.load_state_dict(denoiser_sd, strict=False)

        # Move to device and freeze
        text_encoder.to(device).eval()
        vae.to(device).eval()
        denoiser.to(device).eval()

        for m in (text_encoder, vae, denoiser):
            for p in m.parameters():
                p.requires_grad_(False)

        # Load normalization stats
        mean, std = self._load_norm_stats(weights_dir)

        self._model = {
            "text_encoder": text_encoder,
            "vae": vae,
            "denoiser": denoiser,
            "scheduler": scheduler,
            "guidance_scale": float(guidance_scale),
            "latent_dim": list(cfg.model.latent_dim),
            "num_inference_steps": int(cfg.model.scheduler.num_inference_steps),
            "is_lcm": is_lcm,
            "device": device,
            "mean": mean,
            "std": std,
        }
        self._repo_root = repo_root

    def _fix_config_paths(self, cfg, weights_dir, repo_root):
        """Override config paths for our directory layout."""
        from omegaconf import OmegaConf

        OmegaConf.update(
            cfg, "model.t5_path",
            "sentence-transformers/sentence-t5-large",
            force_add=True,
        )
        OmegaConf.update(cfg, "DATASET.NFEATS", 263, force_add=True)
        OmegaConf.update(cfg, "DATASET.NJOINTS", 22, force_add=True)

    def _find_checkpoint(self, weights_dir):
        """Locate the MotionLCM checkpoint."""
        candidates = sorted(
            weights_dir.rglob("motionlcm_humanml*.ckpt"), reverse=True,
        )
        for ckpt in candidates:
            if "_v1" not in ckpt.name:
                return ckpt
        return candidates[0] if candidates else None

    def _load_norm_stats(self, weights_dir):
        """Load Mean.npy and Std.npy for denormalization."""
        for subdir in ["tiny_humanml3d", "humanml3d", "datasets/humanml3d"]:
            mean_path = weights_dir / subdir / "Mean.npy"
            std_path = weights_dir / subdir / "Std.npy"
            if mean_path.exists() and std_path.exists():
                return np.load(mean_path), np.load(std_path)

        for mean_path in weights_dir.rglob("Mean.npy"):
            std_path = mean_path.parent / "Std.npy"
            if std_path.exists():
                return np.load(mean_path), np.load(std_path)

        raise FileNotFoundError(
            "Mean.npy / Std.npy not found. "
            "Re-run 'Initialize AI Motion'."
        )

    def unload_model(self):
        self._model = None
        self._repo_root = None

        for name in list(sys.modules.keys()):
            for pkg in _LCM_PKGS:
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

    def predict(self, prompt, num_frames=120):
        """Generate motion from text prompt on SMPL 22-joint skeleton.

        Returns:
            dict with 'rotations', 'root_positions', 'joint_names',
            '_source' ('LCM' or 'FALLBACK').
        """
        from . import smpl_skeleton

        source = "LCM"
        try:
            self.load_model()
            motion_263 = self._run_inference(prompt, num_frames)
            rotations, root_positions = self._recover_from_263(motion_263)
            print("[MotionLCM] Inference succeeded — using real LCM output")
        except Exception:
            import traceback
            traceback.print_exc()
            print("[MotionLCM] Real inference FAILED — using fallback")
            source = "FALLBACK"
            from .anytop_adapter import AnyTopAdapter
            skeleton = smpl_skeleton.get_skeleton()
            rotations, root_positions = AnyTopAdapter._fallback_generate(
                skeleton, num_frames, prompt,
            )

        return {
            "rotations": rotations,
            "root_positions": root_positions,
            "joint_names": smpl_skeleton.JOINT_NAMES,
            "_source": source,
        }

    def _run_inference(self, prompt, num_frames):
        """Run the MotionLCM pipeline directly on loaded components.

        Implements the same forward pass as MLD.forward() +
        MLD._diffusion_reverse(), but without the heavy MLD class.

        Returns:
            numpy array of shape ``(num_frames, 263)``.
        """
        import torch

        text_encoder = self._model["text_encoder"]
        vae = self._model["vae"]
        denoiser = self._model["denoiser"]
        scheduler = self._model["scheduler"]
        guidance_scale = self._model["guidance_scale"]
        latent_dim = self._model["latent_dim"]
        num_steps = self._model["num_inference_steps"]
        is_lcm = self._model["is_lcm"]
        device = self._model["device"]
        mean = self._model["mean"]
        std = self._model["std"]

        # For LCM (time_cond_proj_dim != None): no classifier-free guidance,
        # guidance scale is embedded as timestep condition instead.
        # For standard MLD (time_cond_proj_dim == None): use CFG.
        use_cfg = (
            guidance_scale > 1
            and not is_lcm
        )

        with torch.no_grad():
            # 1. Encode text
            texts = [prompt]
            if use_cfg:
                texts = texts + [""]  # unconditional for CFG
            text_emb = text_encoder(texts)

            # Ensure text embeddings match denoiser dtype (Sentence-T5
            # may output float16 while denoiser weights are float32)
            text_emb = text_emb.to(dtype=torch.float32, device=device)

            # 2. Create random latent noise
            latents = torch.randn(
                (1, *latent_dim), device=device, dtype=torch.float32,
            )

            # 3. Build frame mask for VAE decode
            lengths = torch.tensor([num_frames], device=device)
            max_len = int(lengths.max())
            mask = (
                torch.arange(max_len, device=device).expand(1, max_len)
                < lengths.unsqueeze(1)
            )

            # 4. Diffusion reverse (1 step for LCM)
            latents = latents * scheduler.init_noise_sigma
            scheduler.set_timesteps(num_steps)
            timesteps = scheduler.timesteps.to(device)

            # LCM guidance embedding
            timestep_cond = None
            if is_lcm and hasattr(denoiser, 'time_cond_proj_dim') and denoiser.time_cond_proj_dim is not None:
                gs_tensor = torch.tensor(
                    [guidance_scale - 1], device=device,
                )
                timestep_cond = _guidance_scale_embedding(
                    gs_tensor,
                    embedding_dim=denoiser.time_cond_proj_dim,
                ).to(device=device, dtype=latents.dtype)

            extra_step_kwargs = {}
            if "eta" in set(
                inspect.signature(scheduler.step).parameters.keys()
            ):
                extra_step_kwargs["eta"] = 0.0

            for t in timesteps:
                if use_cfg:
                    latent_input = torch.cat([latents] * 2)
                else:
                    latent_input = latents
                latent_input = scheduler.scale_model_input(latent_input, t)

                model_output = denoiser(
                    sample=latent_input,
                    timestep=t,
                    timestep_cond=timestep_cond,
                    encoder_hidden_states=text_emb,
                    controlnet_residuals=None,
                )[0]

                if use_cfg:
                    out_text, out_uncond = model_output.chunk(2)
                    model_output = (
                        out_uncond
                        + guidance_scale * (out_text - out_uncond)
                    )

                latents = scheduler.step(
                    model_output, t, latents, **extra_step_kwargs,
                ).prev_sample

            # 5. Decode latent → 263-dim features
            feats = vae.decode(latents, mask)  # (1, num_frames, 263)

            # 6. Denormalize
            mean_t = torch.tensor(
                mean, dtype=feats.dtype, device=feats.device,
            )
            std_t = torch.tensor(
                std, dtype=feats.dtype, device=feats.device,
            )
            denorm_feats = feats * std_t + mean_t
            motion_263 = denorm_feats[0].cpu().numpy()

        # Trim or pad to requested frame count
        actual_frames = motion_263.shape[0]
        if actual_frames > num_frames:
            motion_263 = motion_263[:num_frames]
        elif actual_frames < num_frames:
            pad = np.zeros((num_frames - actual_frames, _FEAT_DIM))
            pad[:] = motion_263[-1]
            motion_263 = np.concatenate([motion_263, pad], axis=0)

        return motion_263

    # ── 263-dim feature recovery (position-based IK) ──

    def _recover_from_263(self, motion_263):
        """Position-based recovery from 263-dim HumanML3D features.

        Instead of decoding the unreliable 6D rotation channels, this
        recovers world joint positions via ``recover_from_ric`` math
        (same as MotionLCM / MoMask visualization) and computes
        parent-local rotations via analytic IK (``between()`` on the
        SMPL kinematic chain).

        Returns:
            ``(rotations_euler, root_positions)`` in Blender Z-up coords.
        """
        from . import smpl_skeleton

        n_frames = motion_263.shape[0]
        parents = smpl_skeleton.PARENTS
        offsets = smpl_skeleton._OFFSETS_YUP

        # ── Step 1: Recover world positions in Y-up ──
        positions = self._recover_positions_yup(motion_263)

        # ── Step 2: Global rotations via between() ──
        global_q = np.zeros((n_frames, _N_JOINTS, 4))
        global_q[..., 0] = 1.0  # identity

        # Root rotation: use r_quat = (cos θ, 0, sin θ, 0) directly.
        # This matches the convention the retarget/preview pipeline expects
        # (same as the old matrix-based code's Ry(facing)).
        root_ang_vel = motion_263[:, 0]
        r_rot_ang = np.zeros(n_frames)
        if n_frames > 1:
            r_rot_ang[1:] = np.cumsum(root_ang_vel[:-1])
        global_q[:, 0, 0] = np.cos(r_rot_ang)
        global_q[:, 0, 2] = -np.sin(r_rot_ang)  # qinv(r_quat) = facing→world

        for j in range(1, _N_JOINTS):
            p = int(parents[j])
            off = offsets[j]
            off_len = np.linalg.norm(off)
            if off_len < 1e-8:
                global_q[:, j] = global_q[:, p]
                continue
            off_dir = off / off_len

            # Expected direction = parent's global rotation applied
            # to the rest-pose offset.  This propagates twist.
            off_batch = np.broadcast_to(
                off_dir, (n_frames, 3),
            ).copy()
            off_global = _qrot(global_q[:, p], off_batch)

            # Actual direction from recovered positions
            bone_vec = positions[:, j] - positions[:, p]
            bone_len = np.linalg.norm(bone_vec, axis=-1, keepdims=True)
            bone_dir = bone_vec / (bone_len + 1e-8)

            # Delta: expected → actual, then compose with parent
            delta_q = _qbetween(off_global, bone_dir)
            global_q[:, j] = _qmul(delta_q, global_q[:, p])

        global_q /= (
            np.linalg.norm(global_q, axis=-1, keepdims=True) + 1e-10
        )

        # ── Step 3: Global → local rotations ──
        local_q = np.zeros_like(global_q)
        local_q[:, 0] = global_q[:, 0]
        for j in range(1, _N_JOINTS):
            p = int(parents[j])
            local_q[:, j] = _qmul(
                _qinv(global_q[:, p]), global_q[:, j],
            )
        local_q /= (
            np.linalg.norm(local_q, axis=-1, keepdims=True) + 1e-10
        )

        # ── Step 4: Y-up → Z-up, then Euler XYZ ──
        # Use proper rotation (det=+1): Rot(X, -90°) maps Y→Z, Z→-Y.
        # This preserves rotation directions (no axis inversions),
        # and the character faces -Y natively in Blender convention.
        _C = np.array(
            [[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=np.float64,
        )
        rotations_euler = []
        for f in range(n_frames):
            frame_euler = []
            for j in range(_N_JOINTS):
                R_yup = _quat_to_matrix(local_q[f, j])
                R_zup = _C @ R_yup @ _C.T
                frame_euler.append(self._matrix_to_euler_xyz(R_zup))
            rotations_euler.append(frame_euler)

        # Compute rest-pose pelvis height above ground (Y-up).
        # HumanML3D root Y is absolute from ground, but the preview/retarget
        # system expects displacement from the SMPL rest position (pelvis
        # at origin).  Subtracting this converts absolute → rest-relative.
        rest_pos_yup = np.zeros((_N_JOINTS, 3))
        for i in range(_N_JOINTS):
            p = int(parents[i])
            if p >= 0:
                rest_pos_yup[i] = rest_pos_yup[p] + offsets[i]
        pelvis_height = -float(rest_pos_yup[:, 1].min())

        root_positions = [
            (float(positions[f, 0, 0]),
             float(positions[f, 0, 2]),            # Blender Y ← Y-up Z
             float(positions[f, 0, 1]) - pelvis_height)  # Blender Z, rest-relative
            for f in range(n_frames)
        ]
        return rotations_euler, root_positions

    @staticmethod
    def _recover_positions_yup(motion_263):
        """Recover world joint positions in Y-up from 263-dim features.

        Implements the reference ``recover_from_ric`` logic from
        MotionLCM / HumanML3D: root rotation/position from shifted
        angular/linear velocity, then rotate root-relative joint
        positions to world frame.
        """
        n_frames = motion_263.shape[0]

        # Root rotation quaternion from angular velocity (shifted)
        root_ang_vel = motion_263[:, 0]
        r_ang = np.zeros(n_frames)
        if n_frames > 1:
            r_ang[1:] = np.cumsum(root_ang_vel[:-1])

        r_quat = np.zeros((n_frames, 4))
        r_quat[:, 0] = np.cos(r_ang)
        r_quat[:, 2] = np.sin(r_ang)

        # Root position from shifted linear velocity
        r_pos = np.zeros((n_frames, 3))
        if n_frames > 1:
            r_pos[1:, 0] = motion_263[:-1, 1]
            r_pos[1:, 2] = motion_263[:-1, 2]

        # Rotate velocity by inverse root quat, then cumsum
        r_pos = _qrot(_qinv(r_quat), r_pos)
        r_pos = np.cumsum(r_pos, axis=0)
        r_pos[:, 1] = motion_263[:, 3]  # absolute Y height

        # Joint positions: 21 joints × 3, root-relative in facing frame
        j_local = motion_263[:, 4:67].reshape(n_frames, 21, 3)

        # Rotate from facing frame to world
        r_inv = _qinv(r_quat)
        r_inv_exp = np.broadcast_to(
            r_inv[:, np.newaxis, :], (n_frames, 21, 4),
        ).copy()
        j_world = _qrot(
            r_inv_exp.reshape(-1, 4),
            j_local.reshape(-1, 3),
        ).reshape(n_frames, 21, 3)

        # Add root XZ only — NOT Y.  HumanML3D positions at [4:67]
        # have absolute Y (height from ground) but root-relative XZ.
        j_world[:, :, 0] += r_pos[:, 0:1]
        j_world[:, :, 2] += r_pos[:, 2:3]

        positions = np.zeros((n_frames, _N_JOINTS, 3))
        positions[:, 0] = r_pos
        positions[:, 1:] = j_world
        return positions

    # ── Rotation utilities ──

    @staticmethod
    def _rotation_6d_to_matrix_rows(r6d):
        """Convert 6D rotation (row convention) to 3x3 matrices.

        HumanML3D / PyTorch3D convention: the 6D representation contains
        the first two ROWS of the rotation matrix.  Gram-Schmidt
        recovers the third row, and the result is stacked as rows
        (``dim=-2`` in PyTorch).

        This differs from AnyTop's column convention used in
        ``AnyTopAdapter._rotation_6d_to_matrix_batch`` (``axis=-1``).
        """
        a1 = r6d[:, :3].astype(np.float64)
        a2 = r6d[:, 3:6].astype(np.float64)

        b1 = a1 / (np.linalg.norm(a1, axis=1, keepdims=True) + 1e-8)
        dot = np.sum(b1 * a2, axis=1, keepdims=True)
        b2 = a2 - dot * b1
        b2 = b2 / (np.linalg.norm(b2, axis=1, keepdims=True) + 1e-8)
        b3 = np.cross(b1, b2)

        # Stack as ROWS (dim=-2) to match PyTorch3D convention
        return np.stack([b1, b2, b3], axis=-2)

    @staticmethod
    def _matrix_to_euler_xyz(R):
        """Convert 3x3 rotation matrix to Euler XYZ angles (radians)."""
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

    # ── Apply motion (delegates to AnyTop's implementation) ──

    def apply_motion(self, armature_obj, motion_data, action_name=None,
                     frame_start=1):
        """Apply generated motion — delegates to AnyTopAdapter."""
        from .anytop_adapter import AnyTopAdapter
        if not action_name:
            action_name = f"{armature_obj.name}_MotionLCM"
        return AnyTopAdapter.get_instance().apply_motion(
            armature_obj, motion_data, action_name, frame_start,
        )
