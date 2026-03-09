"""Model download, cache, and lifecycle management.

Models are stored in ``~/.blendertools/models/<model_id>/``.
Each model directory contains:
    weights/   — downloaded checkpoint files
    code/      — downloaded model source code (optional)
    status.json — installation metadata
"""

import json
import shutil
import urllib.request
import zipfile
from pathlib import Path

CACHE_DIR = Path.home() / ".blendertools" / "models"

# ── Adapter registry ──

_registry = {}  # model_id -> adapter class


def register_adapter(adapter_cls):
    """Register a model adapter class."""
    _registry[adapter_cls.MODEL_ID] = adapter_cls


def get_adapter(model_id):
    """Return the adapter class for *model_id*, or None."""
    return _registry.get(model_id)


def get_all_adapters():
    """Return dict of all registered adapters."""
    return dict(_registry)


# ── Path helpers ──

def get_model_dir(model_id):
    """Return the cache directory for a model."""
    return CACHE_DIR / model_id


def _status_path(model_id):
    return get_model_dir(model_id) / "status.json"


# ── Status queries ──

def is_model_installed(model_id):
    """True if the model's weights are downloaded and ready."""
    path = _status_path(model_id)
    if not path.exists():
        return False
    with open(path) as f:
        return json.load(f).get("installed", False)


def get_model_status(model_id):
    """Return the full status dict for a model."""
    path = _status_path(model_id)
    if not path.exists():
        return {"installed": False}
    with open(path) as f:
        return json.load(f)


def _write_status(model_id, status):
    model_dir = get_model_dir(model_id)
    model_dir.mkdir(parents=True, exist_ok=True)
    with open(_status_path(model_id), "w") as f:
        json.dump(status, f, indent=2)


# ── Download helpers ──

def download_file(url, dest_path, progress_callback=None):
    """Download *url* to *dest_path* with optional progress reporting."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "BlenderTools-ModelManager/1.0"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        total = int(resp.headers.get("content-length", 0))
        downloaded = 0
        block = 65536

        with open(dest_path, "wb") as f:
            while True:
                chunk = resp.read(block)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total:
                    progress_callback(downloaded / total)


# ── Install / remove ──

def install_model(model_id, progress_callback=None):
    """Download code and weights for *model_id*.

    Args:
        model_id: Registered adapter MODEL_ID.
        progress_callback: Optional callable(progress_float, message_str).
    """
    adapter_cls = get_adapter(model_id)
    if adapter_cls is None:
        raise ValueError(f"Unknown model: {model_id}")

    model_dir = get_model_dir(model_id)
    weights_dir = model_dir / "weights"
    weights_dir.mkdir(parents=True, exist_ok=True)

    # 1. Download code archive if specified
    if adapter_cls.CODE_URL:
        code_dir = model_dir / "code"
        if not code_dir.exists():
            if progress_callback:
                progress_callback(0.05, f"Downloading {adapter_cls.MODEL_NAME} code...")
            zip_path = model_dir / "code.zip"
            download_file(adapter_cls.CODE_URL, zip_path)
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(code_dir)
            zip_path.unlink()

    # 2. Download weight files
    total_files = len(adapter_cls.WEIGHT_URLS)
    for i, (filename, url) in enumerate(adapter_cls.WEIGHT_URLS.items()):
        dest = weights_dir / filename
        if dest.exists():
            continue

        def _file_progress(p, _i=i):
            if progress_callback:
                overall = (_i + p) / max(total_files, 1)
                progress_callback(overall, f"Downloading {filename}...")

        download_file(url, dest, _file_progress)

    # 3. Install extra pip deps
    if adapter_cls.EXTRA_DEPS:
        if progress_callback:
            progress_callback(0.9, "Installing extra dependencies...")
        from . import dependencies
        dependencies.install_extra_deps(adapter_cls.EXTRA_DEPS)

    # 4. Write success marker
    _write_status(model_id, {
        "installed": True,
        "model_name": adapter_cls.MODEL_NAME,
        "version": adapter_cls.VERSION,
    })

    if progress_callback:
        progress_callback(1.0, "Done")


def remove_model(model_id):
    """Delete all cached data for *model_id*."""
    model_dir = get_model_dir(model_id)
    if model_dir.exists():
        shutil.rmtree(model_dir)
    # Reset singleton
    adapter_cls = get_adapter(model_id)
    if adapter_cls:
        adapter_cls._instance = None
        adapter_cls._model = None


def get_cache_size_mb(model_id):
    """Return total cache size in megabytes for *model_id*."""
    model_dir = get_model_dir(model_id)
    if not model_dir.exists():
        return 0.0
    total = sum(f.stat().st_size for f in model_dir.rglob("*") if f.is_file())
    return total / (1024 * 1024)
