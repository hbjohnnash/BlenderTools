"""Seam ML adapters — neural seam prediction models."""

from ...core.ml import model_manager
from .mesh_cnn_adapter import MeshCNNAdapter


def register():
    model_manager.register_adapter(MeshCNNAdapter)


def unregister():
    pass
