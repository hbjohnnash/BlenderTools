"""PyTorch dependency management for Blender's bundled Python."""

import importlib
import subprocess
import sys

_TORCH_AVAILABLE = None


def get_blender_python():
    """Return the path to Blender's Python executable."""
    return sys.executable


def check_torch_available():
    """Check if PyTorch is importable in the current environment."""
    global _TORCH_AVAILABLE
    if _TORCH_AVAILABLE is not None:
        return _TORCH_AVAILABLE
    try:
        import torch  # noqa: F401
        _TORCH_AVAILABLE = True
    except ImportError:
        _TORCH_AVAILABLE = False
    return _TORCH_AVAILABLE


def check_torch_gpu():
    """Check if CUDA GPU acceleration is available."""
    if not check_torch_available():
        return False
    import torch
    return torch.cuda.is_available()


def install_torch(use_gpu=True, progress_callback=None):
    """Install PyTorch into Blender's Python via pip.

    Args:
        use_gpu: If True, install CUDA-enabled build.
        progress_callback: Optional callable(progress_float, message_str).

    Returns:
        True on success.

    Raises:
        RuntimeError: If installation fails.
    """
    global _TORCH_AVAILABLE
    python = get_blender_python()

    if progress_callback:
        progress_callback(0.05, "Ensuring pip is available...")

    # Ensure pip exists
    subprocess.run(
        [python, "-m", "ensurepip", "--default-pip"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if progress_callback:
        progress_callback(0.1, "Installing PyTorch (this may take several minutes)...")

    cmd = [python, "-m", "pip", "install", "--upgrade"]

    if use_gpu:
        cmd.extend([
            "torch",
            "--index-url", "https://download.pytorch.org/whl/cu121",
        ])
    else:
        cmd.extend([
            "torch",
            "--index-url", "https://download.pytorch.org/whl/cpu",
        ])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        raise RuntimeError(f"pip install torch failed:\n{result.stderr[-500:]}")

    # Make newly installed package importable without restart
    importlib.invalidate_caches()

    _TORCH_AVAILABLE = True

    if progress_callback:
        progress_callback(1.0, "PyTorch installed successfully")

    return True


def install_extra_deps(packages, progress_callback=None):
    """Install additional pip packages into Blender's Python."""
    if not packages:
        return True

    python = get_blender_python()
    cmd = [python, "-m", "pip", "install"] + list(packages)

    if progress_callback:
        progress_callback(0.5, f"Installing {', '.join(packages)}...")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to install {packages}:\n{result.stderr[-500:]}"
        )

    importlib.invalidate_caches()
    return True
