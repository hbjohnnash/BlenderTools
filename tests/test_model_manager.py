"""Tests for core.ml.model_manager — download, cache, status management.

These tests use a temporary directory instead of the real ~/.blendertools/
so they never touch your actual model cache.
"""

import json
from unittest.mock import patch

from core.ml import model_manager
from core.ml.base_adapter import BaseModelAdapter

# ── A dummy adapter for testing ──

class FakeAdapter(BaseModelAdapter):
    MODEL_ID = "fake_model"
    MODEL_NAME = "Fake Model"
    MODEL_DESC = "A fake model for testing"
    MODEL_TYPE = "seam"
    WEIGHT_URLS = {}  # No actual downloads
    VERSION = "1.0"

    def load_model(self):
        self._model = "loaded"

    def predict(self, *args, **kwargs):
        return [0, 1, 2]


class TestAdapterRegistry:
    """Test that adapters can be registered and retrieved."""

    def test_register_adapter(self):
        model_manager.register_adapter(FakeAdapter)
        assert model_manager.get_adapter("fake_model") is FakeAdapter

    def test_get_unknown_adapter_returns_none(self):
        assert model_manager.get_adapter("nonexistent_model_xyz") is None

    def test_get_all_adapters_includes_registered(self):
        model_manager.register_adapter(FakeAdapter)
        all_adapters = model_manager.get_all_adapters()
        assert "fake_model" in all_adapters


class TestModelStatus:
    """Test install status tracking via status.json files."""

    def test_not_installed_by_default(self, tmp_model_dir):
        """A model that was never installed should report as not installed."""
        with patch.object(model_manager, "CACHE_DIR", tmp_model_dir):
            assert model_manager.is_model_installed("fake_model") is False

    def test_write_and_read_status(self, tmp_model_dir):
        """Writing a status file should make is_model_installed return True."""
        with patch.object(model_manager, "CACHE_DIR", tmp_model_dir):
            model_manager._write_status("fake_model", {
                "installed": True,
                "model_name": "Fake Model",
                "version": "1.0",
            })
            assert model_manager.is_model_installed("fake_model") is True

    def test_get_model_status_returns_dict(self, tmp_model_dir):
        """get_model_status should return the full status dict."""
        with patch.object(model_manager, "CACHE_DIR", tmp_model_dir):
            model_manager._write_status("fake_model", {
                "installed": True,
                "version": "2.0",
            })
            status = model_manager.get_model_status("fake_model")
            assert status["version"] == "2.0"
            assert status["installed"] is True

    def test_status_not_found_returns_not_installed(self, tmp_model_dir):
        """Missing status file should return {installed: False}."""
        with patch.object(model_manager, "CACHE_DIR", tmp_model_dir):
            status = model_manager.get_model_status("never_installed")
            assert status == {"installed": False}


class TestModelPaths:
    """Test cache directory path generation."""

    def test_get_model_dir(self, tmp_model_dir):
        with patch.object(model_manager, "CACHE_DIR", tmp_model_dir):
            path = model_manager.get_model_dir("meshcnn")
            assert path == tmp_model_dir / "meshcnn"

    def test_cache_size_zero_for_missing(self, tmp_model_dir):
        with patch.object(model_manager, "CACHE_DIR", tmp_model_dir):
            size = model_manager.get_cache_size_mb("nonexistent")
            assert size == 0.0

    def test_cache_size_counts_files(self, tmp_model_dir):
        """Cache size should sum all file sizes in the model dir."""
        with patch.object(model_manager, "CACHE_DIR", tmp_model_dir):
            model_dir = tmp_model_dir / "fake_model" / "weights"
            model_dir.mkdir(parents=True)
            # Create a 1024-byte file
            (model_dir / "weights.bin").write_bytes(b"x" * 1024)
            size = model_manager.get_cache_size_mb("fake_model")
            assert abs(size - 0.001) < 0.001  # ~0.001 MB


class TestModelRemove:
    """Test model removal."""

    def test_remove_deletes_directory(self, tmp_model_dir):
        with patch.object(model_manager, "CACHE_DIR", tmp_model_dir):
            # Create model dir with a file
            model_dir = tmp_model_dir / "fake_model"
            model_dir.mkdir(parents=True)
            (model_dir / "data.bin").write_bytes(b"data")

            model_manager.register_adapter(FakeAdapter)
            model_manager.remove_model("fake_model")

            assert not model_dir.exists()

    def test_remove_nonexistent_does_not_crash(self, tmp_model_dir):
        """Removing a model that doesn't exist should not raise."""
        with patch.object(model_manager, "CACHE_DIR", tmp_model_dir):
            model_manager.remove_model("never_existed")  # Should not raise


class TestInstallModel:
    """Test the install flow (without actual downloads)."""

    def test_install_unknown_model_raises(self, tmp_model_dir):
        with patch.object(model_manager, "CACHE_DIR", tmp_model_dir):
            import pytest
            with pytest.raises(ValueError, match="Unknown model"):
                model_manager.install_model("totally_unknown_model")

    def test_install_with_no_weights_writes_status(self, tmp_model_dir):
        """An adapter with empty WEIGHT_URLS should still mark as installed."""
        with patch.object(model_manager, "CACHE_DIR", tmp_model_dir):
            model_manager.register_adapter(FakeAdapter)
            model_manager.install_model("fake_model")
            assert model_manager.is_model_installed("fake_model") is True
