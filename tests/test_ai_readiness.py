"""Tests for AI model readiness gating logic.

Ensures that the panel correctly requires BOTH PyTorch deps
AND model files before showing Generate buttons.
"""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _reset_torch_cache():
    """Reset the cached torch availability between tests."""
    from core.ml import dependencies
    old = dependencies._TORCH_AVAILABLE
    dependencies._TORCH_AVAILABLE = None
    yield
    dependencies._TORCH_AVAILABLE = old


class TestGetAiModelReadiness:

    @patch("core.ml.dependencies.check_torch_available", return_value=True)
    @patch("core.ml.model_manager.is_model_installed")
    def test_all_ready(self, mock_installed, mock_torch):
        mock_installed.side_effect = lambda m: m in (
            "motionlcm", "anytop", "sinmdm",
        )
        from animation.panels import get_ai_model_readiness
        lcm, at, sm = get_ai_model_readiness()
        assert lcm is True
        assert at is True
        assert sm is True

    @patch("core.ml.dependencies.check_torch_available", return_value=False)
    @patch("core.ml.model_manager.is_model_installed", return_value=True)
    def test_no_torch_means_not_ready(self, mock_installed, mock_torch):
        """Models on disk but no PyTorch -> show Initialize."""
        from animation.panels import get_ai_model_readiness
        lcm, at, sm = get_ai_model_readiness()
        assert lcm is False
        assert at is False
        assert sm is False

    @patch("core.ml.dependencies.check_torch_available", return_value=True)
    @patch("core.ml.model_manager.is_model_installed", return_value=False)
    def test_no_models_means_not_ready(self, mock_installed, mock_torch):
        """PyTorch present but no models -> show Initialize."""
        from animation.panels import get_ai_model_readiness
        lcm, at, sm = get_ai_model_readiness()
        assert lcm is False
        assert at is False
        assert sm is False

    @patch("core.ml.dependencies.check_torch_available", return_value=False)
    @patch("core.ml.model_manager.is_model_installed", return_value=False)
    def test_nothing_installed(self, mock_installed, mock_torch):
        from animation.panels import get_ai_model_readiness
        lcm, at, sm = get_ai_model_readiness()
        assert lcm is False
        assert at is False
        assert sm is False

    @patch("core.ml.dependencies.check_torch_available", return_value=True)
    @patch("core.ml.model_manager.is_model_installed")
    def test_partial_lcm_only(self, mock_installed, mock_torch):
        """Only MotionLCM installed."""
        mock_installed.side_effect = lambda m: m == "motionlcm"
        from animation.panels import get_ai_model_readiness
        lcm, at, sm = get_ai_model_readiness()
        assert lcm is True
        assert at is False
        assert sm is False

    @patch("core.ml.dependencies.check_torch_available", return_value=True)
    @patch("core.ml.model_manager.is_model_installed")
    def test_partial_anytop_only(self, mock_installed, mock_torch):
        """Only AnyTop installed, not MotionLCM or SinMDM."""
        mock_installed.side_effect = lambda m: m == "anytop"
        from animation.panels import get_ai_model_readiness
        lcm, at, sm = get_ai_model_readiness()
        assert lcm is False
        assert at is True
        assert sm is False
