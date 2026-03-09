"""Animation ML adapters — motion generation and style transfer models."""

from ...core.ml import model_manager
from .anytop_adapter import AnyTopAdapter
from .sinmdm_adapter import SinMDMAdapter


def register():
    model_manager.register_adapter(AnyTopAdapter)
    model_manager.register_adapter(SinMDMAdapter)


def unregister():
    pass
