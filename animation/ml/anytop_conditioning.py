"""Build AnyTop-compatible conditioning from any Blender armature.

Creates the conditioning dictionary (skeleton topology, T-pose features,
normalization statistics, T5 joint-name embeddings) that AnyTop's diffusion
model requires for inference on arbitrary skeleton topologies.

This avoids importing AnyTop's ``model.conditioners`` module, which has
heavy dependencies (spacy, num2words) that are unnecessary for inference.
"""

import re
import statistics

import numpy as np

# ── Constants matching AnyTop's training configuration ──────────

MAX_JOINTS = 143
FEATURE_LEN = 13
MAX_PATH_LEN = 5
T5_NAME = "t5-base"
T5_DIM = 768

# Mean bone length of SMPL skeleton — AnyTop scales all training
# skeletons so their mean bone length matches this value.
_SMPL_OFFSETS = np.array([
    [0.0, 0.0, 0.0], [0.1031, 0.0, 0.0], [-0.1099, 0.0, 0.0],
    [0.0, 0.1316, 0.0], [0.0, -0.3936, 0.0], [0.0, -0.3902, 0.0],
    [0.0, 0.1432, 0.0], [0.0, -0.4324, 0.0], [0.0, -0.4256, 0.0],
    [0.0, 0.03, 0.0], [0.0, 0.0, 0.0800], [0.0, 0.0, 0.0800],
    [0.0, 0.11, 0.0], [0.05, 0.05, 0.0], [-0.05, 0.05, 0.0],
    [0.0, 0.05, 0.0], [0.11, -0.04, 0.0], [-0.11, -0.04, 0.0],
    [0.0, -0.2568, 0.0], [0.0, -0.2631, 0.0], [0.0, -0.2660, 0.0],
    [0.0, -0.2699, 0.0],
])
HML_AVG_BONELEN = statistics.mean(
    np.linalg.norm(_SMPL_OFFSETS[1:], axis=1).tolist()
)


# ── Public API ──────────────────────────────────────────────────

def scale_and_ground_skeleton(joints):
    """Scale skeleton to AnyTop training space and ground it.

    AnyTop's training pipeline normalises every skeleton so its mean bone
    length equals ``HML_AVG_BONELEN`` (≈ 0.209) and the lowest joint
    touches ``Y = 0``.  This function replicates that for a novel skeleton.

    Args:
        joints: list of joint dicts **already in Y-up coordinates**.

    Returns:
        ``(scaled_joints, scale_factor)`` — use ``1 / scale_factor``
        to convert recovered positions back to original units.
    """
    offsets = np.array([j["offset"] for j in joints], dtype=np.float64)
    bone_lengths = np.linalg.norm(offsets[1:], axis=1)
    valid = bone_lengths[bone_lengths > 1e-8]
    mean_bone_len = float(np.mean(valid)) if len(valid) > 0 else 1.0
    scale_factor = HML_AVG_BONELEN / mean_bone_len

    # Scale all offsets
    scaled_offsets = offsets * scale_factor

    # Compute global positions to find ground level
    parents = [j["parent"] for j in joints]
    positions = np.zeros((len(joints), 3))
    for i in range(len(joints)):
        p = parents[i]
        if p >= 0:
            positions[i] = positions[p] + scaled_offsets[i]
        else:
            positions[i] = scaled_offsets[i]

    # Ground the skeleton: shift root so lowest Y = 0
    min_y = positions[:, 1].min()
    scaled_offsets[0, 1] -= min_y

    scaled_joints = []
    for i, j in enumerate(joints):
        scaled_joints.append({**j, "offset": scaled_offsets[i].tolist()})

    return scaled_joints, scale_factor


def build_cond_dict(skeleton, object_type="blender_skeleton"):
    """Build a conditioning dict entry for one Blender skeleton.

    The skeleton must already be in Y-up coordinates and scaled to
    AnyTop training space (via ``scale_and_ground_skeleton``).

    Args:
        skeleton: dict with ``joints`` and ``height``.
        object_type: key name used inside the dict.

    Returns:
        dict mapping *object_type* to the conditioning arrays.
    """
    joints = skeleton["joints"]
    n_joints = len(joints)
    parents = np.array([j["parent"] for j in joints], dtype=np.int64)
    offsets = np.array([j["offset"] for j in joints], dtype=np.float64)

    joint_names = [j["name"] for j in joints]
    padded_names = joint_names + [None] * (MAX_JOINTS - n_joints)

    edge_rel, graph_dist = create_topology_edge_relations(parents)
    tpose = compute_tpose_features(joints, n_joints)
    mean, std = estimate_mean_std(tpose, n_joints)

    return {
        object_type: {
            "parents": parents,
            "offsets": offsets,
            "joints_names": padded_names,
            "joint_relations": edge_rel,
            "joints_graph_dist": graph_dist,
            "tpos_first_frame": tpose,
            "mean": mean,
            "std": std,
        }
    }


# ── Skeleton topology ──────────────────────────────────────────

def create_topology_edge_relations(parents, max_path_len=MAX_PATH_LEN):
    """Compute edge-type and topological-distance matrices.

    Edge types: self (0), parent (1), child (2), sibling (3),
    no_relation (4), end_effector (5).

    Returns ``(edge_rel, graph_dist)``, each shaped ``(n, n)``.
    """
    SELF, PARENT, CHILD, SIBLING, NO_REL, EE = 0, 1, 2, 3, 4, 5
    n = len(parents)
    topo = np.zeros((n, n))
    edge = np.full((n, n), NO_REL, dtype=np.float64)

    for i in range(n):
        pi = parents[i]
        is_ee = True
        for j in range(n):
            pj = parents[j]
            # Edge type
            if i == j:
                edge[i, j] = SELF
            elif pj == i:
                is_ee = False
                edge[i, j] = CHILD
            elif j == pi:
                edge[i, j] = PARENT
            elif pj == pi and pi >= 0:
                edge[i, j] = SIBLING
            # Graph distance
            if i == j:
                topo[i, j] = 0
            elif j < i:
                topo[i, j] = topo[j, i]
            elif pj == i:
                topo[i, j] = 1
            else:
                topo[i, j] = topo[i, pj] + 1
        if is_ee:
            edge[i, i] = EE

    topo[topo > max_path_len] = max_path_len
    return edge, topo


# ── T-pose features ────────────────────────────────────────────

def compute_tpose_features(joints, n_joints):
    """Compute 13-dim T-pose feature vector for each joint.

    Feature layout per joint (same as AnyTop training data)::

        [0:3]   RIC position (root-relative, in root frame)
        [3:9]   6D rotation (identity columns for T-pose)
        [9:12]  velocity (zero for static T-pose)
        [12]    foot contact binary
    """
    feat = np.zeros((n_joints, FEATURE_LEN), dtype=np.float64)

    # Global positions from cumulative offsets
    positions = np.zeros((n_joints, 3))
    for i, j in enumerate(joints):
        offset = np.array(j["offset"])
        p_idx = j["parent"]
        positions[i] = (positions[p_idx] + offset) if p_idx >= 0 else offset

    root = positions[0].copy()

    # Root: RIC = [0, height, 0]
    feat[0, 1] = root[1]
    # Non-root: position relative to root (root frame ≡ world in T-pose)
    for i in range(1, n_joints):
        feat[i, :3] = positions[i] - root

    # Identity 6D rotation: first two columns of I₃ → [1,0,0, 0,1,0]
    feat[:, 3] = 1.0
    feat[:, 7] = 1.0

    # Foot contact
    for i, j in enumerate(joints):
        desc = j.get("description", "").lower()
        if "foot" in desc or "toe" in desc:
            feat[i, 12] = 1.0

    return feat


# ── Normalization statistics ───────────────────────────────────

def estimate_mean_std(tpose, n_joints):
    """Estimate mean / std for a novel skeleton in training space.

    The skeleton **must** already be scaled to AnyTop's training
    space (mean bone length ≈ 0.209) before calling this.

    Uses the T-pose as the mean and standard deviations calibrated
    from the actual ``cond.npy`` training statistics of AnyTop's
    Truebones dataset (70 skeleton types, median values).

    Calibration source (median across all 70 training skeletons):
        root pos   median=0.050
        root rot   median=0.073
        root vel   median=0.010
        nr   pos   median=0.179
        nr   rot   median=0.146
        nr   vel   median=0.020
    """
    mean = tpose.copy()
    std = np.ones((n_joints, FEATURE_LEN), dtype=np.float64)

    # Root (joint 0) — median values from cond.npy
    std[0, :3] = 0.050    # RIC position (height + horizontal)
    std[0, 3:9] = 0.073   # global facing rotation (6D)
    std[0, 9:12] = 0.010  # local-frame velocity
    std[0, 12] = 1.0

    # Non-root joints — median values from cond.npy
    std[1:, :3] = 0.179   # RIC positions
    std[1:, 3:9] = 0.146  # joint rotations (6D)
    std[1:, 9:12] = 0.020 # local velocity
    std[1:, 12] = 1.0

    return mean, std


# ── Temporal attention mask ────────────────────────────────────

def create_temporal_mask(window, max_len):
    """Create windowed temporal attention mask for the diffusion model.

    Each frame attends to neighbours within ``±window // 2`` and
    always to the first frame (T-pose conditioning slot).
    """
    import torch

    margin = window // 2
    mask = torch.zeros(max_len + 1, max_len + 1)
    mask[:, 0] = 1
    for i in range(max_len + 1):
        lo = max(0, i - margin)
        hi = min(max_len + 1, i + margin + 2)
        mask[i, lo:hi] = 1
    return mask


# ── T5 joint name encoding ────────────────────────────────────

_t5_cache = {}


def encode_joint_names_t5(joint_names, device="cpu"):
    """Encode a padded list of joint names using T5-base.

    Args:
        joint_names: list of ``str | None``, length ``MAX_JOINTS``.
        device: torch device string.

    Returns:
        Tensor of shape ``(MAX_JOINTS, 768)`` — T5 embeddings.
    """
    import torch
    from transformers import T5EncoderModel, T5Tokenizer

    if "model" not in _t5_cache:
        _t5_cache["tokenizer"] = T5Tokenizer.from_pretrained(T5_NAME)
        _t5_cache["model"] = (
            T5EncoderModel.from_pretrained(T5_NAME).eval()
        )
    tokenizer = _t5_cache["tokenizer"]
    t5 = _t5_cache["model"].to(device)

    entries = [
        clean_bone_name(n) if n is not None else ""
        for n in joint_names
    ]

    inputs = tokenizer(entries, return_tensors="pt", padding=True).to(device)
    mask = inputs["attention_mask"]
    empty_idx = [i for i, e in enumerate(entries) if e == ""]
    if empty_idx:
        mask[torch.LongTensor(empty_idx), :] = 0

    with torch.no_grad():
        hidden = t5(**inputs).last_hidden_state
        denom = mask.sum(dim=-1).unsqueeze(-1).clamp(min=1)
        pooled = (hidden * mask.unsqueeze(-1)).sum(dim=-2) / denom

    return pooled


def clean_bone_name(name):
    """Clean a bone name for T5 encoding.

    Removes prefixes (DEF-, CTRL-, BN_, etc.), splits CamelCase,
    replaces side markers (L → Left, R → Right).
    """
    for prefix in (
        "DEF-", "CTRL-", "MCH-", "BN_Bip01", "Bip01_",
        "BN_", "NPC_", "jt_", "Sabrecat",
    ):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break

    parts = re.split(r"(?=[A-Z])|_", name)
    result = []
    for part in parts:
        clean = re.sub(r"\d+", "", part).strip()
        if not clean:
            continue
        if clean in ("L", "l"):
            result.append("Left")
        elif clean in ("R", "r"):
            result.append("Right")
        elif clean in ("C", "c"):
            result.append("Center")
        elif len(clean) == 1:
            continue
        else:
            result.append(clean)
    return " ".join(result)
