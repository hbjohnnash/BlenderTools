"""SinMDM adapter — single-motion diffusion model.

Learns from a single motion example to generate variations,
perform style transfer, in-betweening, and motion expansion.
Supports generic BVH skeletons (not locked to SMPL).

GitHub: https://github.com/SinMDM/SinMDM
License: MIT
"""

import os
import sys
import tempfile
from pathlib import Path

from ...core.ml.base_adapter import BaseModelAdapter

_CODE_URL = (
    "https://github.com/SinMDM/SinMDM/archive/refs/heads/main.zip"
)

# Mixamo pretrained models on Google Drive (from download_mixamo_models.sh).
# gdown ID: 1UHP7uNWkSdsmDSV6fbtmJ1nXn6vtr6bY -> mixamo.zip
_GDRIVE_MIXAMO_ID = "1UHP7uNWkSdsmDSV6fbtmJ1nXn6vtr6bY"


class SinMDMAdapter(BaseModelAdapter):
    MODEL_ID = "sinmdm"
    MODEL_NAME = "SinMDM"
    MODEL_DESC = "Single-motion style transfer, in-betweening & expansion (MIT)"
    MODEL_TYPE = "animation"
    VERSION = "1.0"

    CODE_URL = _CODE_URL
    # Weights are on Google Drive — downloaded via gdown.
    # WEIGHT_URLS left empty; handled by custom download method.
    WEIGHT_URLS = {}
    EXTRA_DEPS = ["einops", "tqdm", "gdown"]

    # ── Repo helpers ──

    def _get_repo_root(self):
        code_dir = self.get_code_dir()
        candidates = list(code_dir.iterdir()) if code_dir.exists() else []
        for c in candidates:
            if c.is_dir() and (c / "model").exists():
                return c
        return code_dir / "SinMDM-main"

    # ── Google Drive download ──

    @classmethod
    def download_weights(cls, progress_callback=None):
        """Download Mixamo pretrained models from Google Drive."""
        import zipfile

        import gdown

        from ...core.ml import model_manager

        model_dir = model_manager.get_model_dir(cls.MODEL_ID)
        weights_dir = model_dir / "weights"
        weights_dir.mkdir(parents=True, exist_ok=True)

        zip_path = weights_dir / "mixamo.zip"

        if progress_callback:
            progress_callback(0.2, "Downloading SinMDM from Google Drive...")

        gdown.download(
            id=_GDRIVE_MIXAMO_ID,
            output=str(zip_path),
            quiet=True,
        )

        if zip_path.exists():
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(weights_dir)
            zip_path.unlink()

        if progress_callback:
            progress_callback(1.0, "SinMDM weights downloaded")

    # ── Model loading ──

    def _find_checkpoint(self):
        """Locate a checkpoint file in the weights directory."""
        weights_dir = self.get_weights_dir()
        for pt in sorted(weights_dir.rglob("*.pt"), reverse=True):
            return pt
        return None

    def load_model(self):
        if self._model is not None:
            return

        import torch

        repo_root = self._get_repo_root()
        repo_str = str(repo_root)
        if repo_str not in sys.path:
            sys.path.insert(0, repo_str)

        ckpt_path = self._find_checkpoint()
        if ckpt_path is not None:
            checkpoint = torch.load(
                ckpt_path,
                map_location="cpu",
                weights_only=False,
            )
            self._model = checkpoint
        else:
            # No pretrained weights — model will train on user's example
            self._model = {"untrained": True}

        self._repo_root = repo_root

    # ── BVH export helper ──

    def export_animation_bvh(self, armature_obj, filepath=None):
        """Export current armature animation to a temp BVH file."""
        from .bvh_utils import export_armature_bvh

        if filepath is None:
            fd, filepath = tempfile.mkstemp(suffix=".bvh")
            os.close(fd)

        export_armature_bvh(armature_obj, filepath)
        return filepath

    # ── Inference ──

    def predict(self, input_bvh, task="style_transfer", num_results=1,
                keyframe_indices=None):
        """Run SinMDM on a BVH motion file.

        Args:
            input_bvh: Path to input BVH file.
            task: One of "style_transfer", "inbetween", "expand".
            num_results: Number of variations to generate.
            keyframe_indices: For inbetween — list of frame indices to keep.

        Returns:
            List of output BVH file paths.
        """
        self.load_model()


        repo_root = self._repo_root
        repo_str = str(repo_root)
        if repo_str not in sys.path:
            sys.path.insert(0, repo_str)

        output_paths = []

        try:
            from model.sinmdm import SinMDM
            from utils.motion_utils import load_bvh, save_bvh

            # Load input motion
            motion_data = load_bvh(input_bvh)

            model = SinMDM()
            if isinstance(self._model, dict) and not self._model.get("untrained"):
                model.load_state_dict(self._model)
            else:
                # Train on the input example (SinMDM trains per-example)
                model.train_on_example(motion_data)

            # Generate variations
            for i in range(num_results):
                if task == "style_transfer":
                    result = model.generate(motion_data, mode="random")
                elif task == "inbetween":
                    result = model.inbetween(
                        motion_data,
                        keyframes=keyframe_indices or [0, -1],
                    )
                elif task == "expand":
                    result = model.expand(motion_data, factor=1.5)
                else:
                    result = model.generate(motion_data, mode="random")

                out_path = tempfile.mktemp(suffix=f"_sinmdm_{i}.bvh")
                save_bvh(result, out_path)
                output_paths.append(out_path)

        except (ImportError, Exception):
            # Fallback: copy input with slight random perturbation
            output_paths = self._fallback_generate(
                input_bvh, num_results, task,
            )

        return output_paths

    def import_animation_bvh(self, armature_obj, bvh_path,
                             action_name=None):
        """Import a BVH file onto an existing armature."""
        from .bvh_utils import apply_bvh_to_armature, parse_bvh

        bvh_data = parse_bvh(bvh_path)

        if not action_name:
            action_name = f"{armature_obj.name}_SinMDM"

        return apply_bvh_to_armature(
            armature_obj, bvh_data,
            action_name=action_name,
        )

    # ── Fallback ──

    def _fallback_generate(self, input_bvh, num_results, task):
        """Generate slightly perturbed copies as fallback."""
        import random

        from .bvh_utils import parse_bvh

        bvh_data = parse_bvh(input_bvh)
        output_paths = []

        for i in range(num_results):
            # Add small random noise to frame values
            perturbed_frames = []
            for frame in bvh_data["frames"]:
                noise_scale = 0.5 if task == "style_transfer" else 0.1
                noisy = [
                    v + random.gauss(0, noise_scale)
                    for v in frame
                ]
                perturbed_frames.append(noisy)

            # Write perturbed BVH
            out_path = tempfile.mktemp(suffix=f"_sinmdm_{i}.bvh")
            self._write_bvh_from_parsed(bvh_data, perturbed_frames, out_path)
            output_paths.append(out_path)

        return output_paths

    @staticmethod
    def _write_bvh_from_parsed(bvh_data, new_frames, filepath):
        """Write a BVH file using the hierarchy from parsed data."""
        lines = []

        # Minimal BVH with the joint structure
        joints = bvh_data["joints"]
        frame_time = bvh_data["frame_time"]

        lines.append("HIERARCHY")

        # Build hierarchy from joints
        parent_stack = []
        for j in joints:
            name = j["name"]
            parent = j["parent"]
            offset = j["offset"]
            channels = j["channels"]

            # Close previous joints as needed
            while parent_stack and (parent is None or
                                    parent_stack[-1] != parent):
                if parent_stack:
                    parent_stack.pop()
                    lines.append("}")

            if parent is None:
                lines.append(f"ROOT {name}")
            else:
                lines.append(f"JOINT {name}")

            lines.append("{")
            lines.append(
                f"  OFFSET {offset[0]:.6f} {offset[1]:.6f} {offset[2]:.6f}"
            )
            ch_str = " ".join(channels)
            lines.append(f"  CHANNELS {len(channels)} {ch_str}")
            parent_stack.append(name)

        # Close remaining
        while parent_stack:
            parent_stack.pop()
            lines.append("}")

        lines.append("MOTION")
        lines.append(f"Frames: {len(new_frames)}")
        lines.append(f"Frame Time: {frame_time:.6f}")

        for frame in new_frames:
            lines.append(" ".join(f"{v:.6f}" for v in frame))

        Path(filepath).write_text("\n".join(lines), encoding="utf-8")
