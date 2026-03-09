"""Abstract base class for ML model adapters."""

from abc import ABC, abstractmethod


class BaseModelAdapter(ABC):
    """Base class for all ML model adapters.

    Subclasses must define class attributes and implement load_model/predict.
    """

    MODEL_ID = ""          # Unique identifier (e.g. "meshcnn")
    MODEL_NAME = ""        # Display name (e.g. "MeshCNN")
    MODEL_DESC = ""        # Short description
    MODEL_TYPE = ""        # "seam" or "animation"
    WEIGHT_URLS = {}       # {filename: download_url}
    CODE_URL = ""          # GitHub ZIP download URL (optional)
    EXTRA_DEPS = []        # Additional pip packages beyond torch
    VERSION = "1.0"

    _instance = None
    _model = None

    @classmethod
    def get_instance(cls):
        """Get or create singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_weights_dir(self):
        from . import model_manager
        return model_manager.get_model_dir(self.MODEL_ID) / "weights"

    def get_code_dir(self):
        from . import model_manager
        return model_manager.get_model_dir(self.MODEL_ID) / "code"

    def is_ready(self):
        """Check if model is installed and dependencies are met."""
        from . import dependencies, model_manager
        return (dependencies.check_torch_available()
                and model_manager.is_model_installed(self.MODEL_ID))

    @abstractmethod
    def load_model(self):
        """Load model weights into memory."""
        pass

    @abstractmethod
    def predict(self, *args, **kwargs):
        """Run inference. Signature varies by subclass."""
        pass

    def unload_model(self):
        """Free model from memory."""
        self._model = None
        import gc
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
