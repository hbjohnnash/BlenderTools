"""MeshCNN adapter — edge-based mesh segmentation for seam prediction.

Uses the pretrained human body segmentation model (8 body-part classes).
Segment boundaries are converted to seam edges.

GitHub: https://github.com/ranahanocka/MeshCNN
License: MIT
"""

import sys
import tempfile
from pathlib import Path

from ...core.ml.base_adapter import BaseModelAdapter

# MeshCNN pretrained human-seg checkpoint hosted on Dropbox.
# The get_pretrained.sh script downloads this tar.gz archive.
_WEIGHTS_ARCHIVE_URL = (
    "https://www.dropbox.com/s/8i26y7cpi6st2ra/human_seg_wts.tar.gz"
)


class MeshCNNAdapter(BaseModelAdapter):
    MODEL_ID = "meshcnn"
    MODEL_NAME = "MeshCNN"
    MODEL_DESC = "Edge-based mesh segmentation for automatic seam prediction"
    MODEL_TYPE = "seam"
    VERSION = "1.0"

    CODE_URL = (
        "https://github.com/ranahanocka/MeshCNN/archive/refs/heads/master.zip"
    )
    # Weights are a tar.gz archive — handled specially in install flow.
    WEIGHT_URLS = {
        "human_seg_wts.tar.gz": f"{_WEIGHTS_ARCHIVE_URL}?dl=1",
    }

    # ── Model loading ──

    def _get_repo_root(self):
        """Return the extracted MeshCNN repo root inside our code dir."""
        code_dir = self.get_code_dir()
        # ZIP extracts to MeshCNN-master/
        candidates = list(code_dir.iterdir()) if code_dir.exists() else []
        for c in candidates:
            if c.is_dir() and (c / "models").exists():
                return c
        return code_dir / "MeshCNN-master"

    def _ensure_weights_extracted(self):
        """Extract the tar.gz archive if not already done."""
        import tarfile

        weights_dir = self.get_weights_dir()
        archive = weights_dir / "human_seg_wts.tar.gz"
        marker = weights_dir / ".extracted"

        if marker.exists():
            return

        if not archive.exists():
            raise FileNotFoundError(
                f"Weight archive not found: {archive}. "
                "Re-run 'Initialize AI Seams'."
            )

        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(path=weights_dir)

        marker.touch()

    def _find_weight_file(self):
        """Locate the .pth weight file inside the extracted archive."""
        weights_dir = self.get_weights_dir()
        # The archive may extract into a subdirectory
        for pth in weights_dir.rglob("latest_net.pth"):
            return pth
        for pth in weights_dir.rglob("*.pth"):
            return pth
        raise FileNotFoundError(
            "No .pth file found in extracted weights. "
            "Re-run 'Initialize AI Seams'."
        )

    def load_model(self):
        """Load MeshCNN network with pretrained weights."""
        if self._model is not None:
            return

        import torch

        self._ensure_weights_extracted()

        repo_root = self._get_repo_root()

        # Temporarily add MeshCNN source to sys.path
        repo_str = str(repo_root)
        if repo_str not in sys.path:
            sys.path.insert(0, repo_str)

        try:
            from models.layers.mesh_conv import MeshConv  # noqa: F401
            from models.networks import define_classifier
        except ImportError as e:
            raise RuntimeError(
                f"MeshCNN code not found at {repo_root}. "
                "Re-run 'Initialize AI Seams'."
            ) from e

        # Build network matching the pretrained human_seg config
        net = define_classifier(
            input_nc=5,
            ncf=[32, 64, 128, 256],
            ninput_edges=2250,
            nclasses=8,
            pool_res=[2000, 1000, 500],
            fc_n=100,
            norm="group",
        )

        # Load weights
        weights_path = self._find_weight_file()
        state = torch.load(
            weights_path,
            map_location="cpu",
            weights_only=False,
        )
        net.load_state_dict(state)
        net.eval()

        self._model = net

    # ── Inference ──

    def predict(self, obj_path):
        """Predict seam edges from an OBJ file.

        Args:
            obj_path: Path to a Wavefront OBJ file.

        Returns:
            List of edge indices that should be seams.
        """
        self.load_model()

        import torch

        repo_root = self._get_repo_root()
        repo_str = str(repo_root)
        if repo_str not in sys.path:
            sys.path.insert(0, repo_str)

        from data.classification import ClassificationData

        # MeshCNN expects a specific directory layout:
        #   <root>/test/<class_name>/<file>.obj
        # Create a temp directory matching that structure.
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir) / "test" / "predict"
            test_dir.mkdir(parents=True)

            import shutil
            shutil.copy2(obj_path, test_dir / "input.obj")

            # Prepare dataset
            try:
                dataset = ClassificationData(
                    root=tmpdir,
                    phase="test",
                    ninput_edges=2250,
                    input_nc=5,
                    num_aug=1,
                )
            except Exception:
                # Fallback: return boundary-based seams if MeshCNN data
                # loading fails (e.g., mesh too small or non-manifold).
                return self._fallback_predict(obj_path)

            if len(dataset) == 0:
                return self._fallback_predict(obj_path)

            # Run forward pass
            with torch.no_grad():
                data = dataset[0]
                edge_features = data["edge_features"].unsqueeze(0)
                mesh = data["mesh"]

                out = self._model(edge_features, [mesh])
                pred = out.argmax(dim=1).squeeze().cpu().numpy()

            # Convert segment boundaries to seam edges
            return self._segments_to_seams(mesh, pred)

    # ── Helpers ──

    def _segments_to_seams(self, mesh, predictions):
        """Find edges where the predicted segment label changes.

        An edge whose two adjacent faces have different predicted labels
        is a natural seam boundary.
        """
        seam_indices = []

        try:
            gemm = mesh.gemm_edges  # (num_edges, 4) neighbour indices
        except AttributeError:
            # If the mesh object doesn't expose gemm, fall back to
            # simply marking all edges whose own label differs from a
            # neighbour.
            for i in range(len(predictions) - 1):
                if predictions[i] != predictions[i + 1]:
                    seam_indices.append(i)
            return seam_indices

        for edge_idx in range(len(predictions)):
            label = predictions[edge_idx]
            for nb_idx in gemm[edge_idx]:
                if nb_idx < 0:
                    continue
                if predictions[nb_idx] != label:
                    seam_indices.append(edge_idx)
                    break

        return seam_indices

    def _fallback_predict(self, obj_path):
        """Simple geometry-based fallback when MeshCNN data loading fails.

        Uses dihedral angle > 45 degrees as a seam heuristic.
        """
        import math

        seam_indices = []

        # Parse OBJ for basic topology
        vertices = []
        faces = []
        with open(obj_path) as f:
            for line in f:
                parts = line.strip().split()
                if not parts:
                    continue
                if parts[0] == "v":
                    vertices.append(tuple(float(x) for x in parts[1:4]))
                elif parts[0] == "f":
                    # Handle f v/vt/vn format
                    face = []
                    for p in parts[1:]:
                        face.append(int(p.split("/")[0]) - 1)
                    faces.append(face)

        # Build edge-to-face map
        edge_faces = {}
        for fi, face in enumerate(faces):
            n = len(face)
            for j in range(n):
                e = tuple(sorted((face[j], face[(j + 1) % n])))
                edge_faces.setdefault(e, []).append(fi)

        # Compute face normals
        from mathutils import Vector
        normals = []
        for face in faces:
            if len(face) < 3:
                normals.append(Vector((0, 0, 1)))
                continue
            v0 = Vector(vertices[face[0]])
            v1 = Vector(vertices[face[1]])
            v2 = Vector(vertices[face[2]])
            n = (v1 - v0).cross(v2 - v0)
            n.normalize()
            normals.append(n)

        # Find high-angle edges
        threshold = math.radians(45.0)
        for idx, (edge, flist) in enumerate(edge_faces.items()):
            if len(flist) == 2:
                angle = normals[flist[0]].angle(normals[flist[1]], 0.0)
                if angle > threshold:
                    seam_indices.append(idx)
            elif len(flist) < 2:
                seam_indices.append(idx)  # boundary

        return seam_indices
