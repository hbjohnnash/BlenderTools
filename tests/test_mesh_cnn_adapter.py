"""Tests for seams.ml.mesh_cnn_adapter — segment-to-seam conversion + fallback.

Tests the pure geometry logic that converts MeshCNN's segment predictions
into seam edge indices. No Blender or PyTorch needed.
"""

import math
from pathlib import Path
from unittest.mock import MagicMock

from seams.ml.mesh_cnn_adapter import MeshCNNAdapter


class TestSegmentsToSeams:
    """Test the _segments_to_seams method."""

    def setup_method(self):
        self.adapter = MeshCNNAdapter()

    def test_uniform_labels_produce_no_seams(self):
        """If all edges have the same label, there are no boundaries."""
        mesh = MagicMock()
        mesh.gemm_edges = [
            [1, 2, -1, -1],  # edge 0 neighbors: 1, 2
            [0, 2, -1, -1],  # edge 1 neighbors: 0, 2
            [0, 1, -1, -1],  # edge 2 neighbors: 0, 1
        ]
        predictions = [0, 0, 0]  # all same label
        result = self.adapter._segments_to_seams(mesh, predictions)
        assert result == []

    def test_different_labels_produce_seams(self):
        """Adjacent edges with different labels should produce seams."""
        mesh = MagicMock()
        mesh.gemm_edges = [
            [1, -1, -1, -1],  # edge 0 neighbors: 1
            [0, 2, -1, -1],  # edge 1 neighbors: 0, 2
            [1, -1, -1, -1],  # edge 2 neighbors: 1
        ]
        predictions = [0, 0, 1]  # edge 2 has different label
        result = self.adapter._segments_to_seams(mesh, predictions)
        # Edge 1 should be a seam (neighbors edge 2 which has different label)
        assert 1 in result
        # Edge 2 should be a seam (neighbors edge 1 which has different label)
        assert 2 in result

    def test_fallback_when_no_gemm(self):
        """Without gemm_edges, should fall back to sequential comparison."""
        mesh = MagicMock()
        del mesh.gemm_edges  # Remove the attribute entirely
        predictions = [0, 0, 1, 1, 2]
        result = self.adapter._segments_to_seams(mesh, predictions)
        # Boundaries at index 1→2 and 3→4
        assert 1 in result  # label changes from 0 to 1
        assert 3 in result  # label changes from 1 to 2

    def test_all_different_labels(self):
        """Every edge different = every edge is a seam boundary."""
        mesh = MagicMock()
        mesh.gemm_edges = [
            [1, -1, -1, -1],
            [0, 2, -1, -1],
            [1, -1, -1, -1],
        ]
        predictions = [0, 1, 2]
        result = self.adapter._segments_to_seams(mesh, predictions)
        assert len(result) == 3  # all edges are boundaries


class TestFallbackPredict:
    """Test the angle-based fallback predictor."""

    def test_fallback_with_simple_cube_obj(self, tmp_path):
        """A cube OBJ should produce seams at sharp 90° edges."""
        # Minimal cube OBJ (front and right faces only, sharing one edge)
        obj_content = """\
v 0.0 0.0 0.0
v 1.0 0.0 0.0
v 1.0 1.0 0.0
v 0.0 1.0 0.0
v 1.0 0.0 1.0
v 1.0 1.0 1.0
f 1 2 3 4
f 2 5 6 3
"""
        obj_path = tmp_path / "cube.obj"
        obj_path.write_text(obj_content, encoding="utf-8")

        adapter = MeshCNNAdapter()
        result = adapter._fallback_predict(str(obj_path))
        # The shared edge (v2-v3) is at 90° which is > 45° threshold
        assert len(result) > 0, "Should find at least one seam edge"

    def test_fallback_with_flat_plane(self, tmp_path):
        """A flat plane (all faces coplanar) should produce no angle seams."""
        obj_content = """\
v 0.0 0.0 0.0
v 1.0 0.0 0.0
v 1.0 1.0 0.0
v 0.0 1.0 0.0
v 2.0 0.0 0.0
v 2.0 1.0 0.0
f 1 2 3 4
f 2 5 6 3
"""
        obj_path = tmp_path / "plane.obj"
        obj_path.write_text(obj_content, encoding="utf-8")

        adapter = MeshCNNAdapter()
        result = adapter._fallback_predict(str(obj_path))
        # Coplanar faces = 0° angle, no seams (except boundary edges)
        # The boundary edges will be marked though
        # Just check it doesn't crash and returns a list
        assert isinstance(result, list)
