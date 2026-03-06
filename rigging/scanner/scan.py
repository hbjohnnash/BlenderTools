"""Core scan orchestrator — combines name maps and heuristics."""

from .name_maps import detect_skeleton_type, apply_name_map
from .heuristics import analyze_by_heuristics


def scan_skeleton(armature_obj):
    """Scan an armature and identify bone roles.

    Returns:
        dict with keys:
        - skeleton_type: str (e.g. "mixamo", "ue_mannequin", "unknown")
        - confidence: float (0.0–1.0)
        - bones: dict {bone_name: {role, side, module_type, chain_id, confidence, source}}
        - chains: dict {chain_id: {module_type, side, bones: [bone_name, ...], bone_count}}
        - unmapped_bones: list of bone names not assigned to any chain
        - generated_bones: list (empty at scan time, populated after wrap)
    """
    bone_names = [b.name for b in armature_obj.data.bones]

    # Step 1: Try name maps
    skeleton_type, confidence = detect_skeleton_type(bone_names)
    mapped_bones = {}
    if skeleton_type != "unknown":
        mapped_bones = apply_name_map(bone_names, skeleton_type)

    # Step 2: Heuristic fallback for unmapped bones
    heuristic_bones = analyze_by_heuristics(armature_obj, set(mapped_bones.keys()))

    # Merge results (name map takes priority)
    all_bones = {}
    all_bones.update(heuristic_bones)
    all_bones.update(mapped_bones)

    # Step 3: Build chain summaries
    chains = {}
    for bone_name, info in all_bones.items():
        cid = info["chain_id"]
        if cid not in chains:
            chains[cid] = {
                "module_type": info["module_type"],
                "side": info["side"],
                "bones": [],
                "bone_count": 0,
            }
        chains[cid]["bones"].append(bone_name)
        chains[cid]["bone_count"] += 1

    # Sort bones within each chain by hierarchy order
    bone_lookup = {b.name: b for b in armature_obj.data.bones}
    for cid, chain_info in chains.items():
        chain_info["bones"] = _sort_by_hierarchy(chain_info["bones"], bone_lookup)

    # Step 4: Unmapped bones
    unmapped = [n for n in bone_names if n not in all_bones]

    return {
        "skeleton_type": skeleton_type,
        "confidence": confidence,
        "bones": all_bones,
        "chains": chains,
        "unmapped_bones": unmapped,
        "generated_bones": [],
    }


def _sort_by_hierarchy(bone_names, bone_lookup):
    """Sort bone names by hierarchy depth (root first)."""
    def depth(name):
        b = bone_lookup.get(name)
        if not b:
            return 0
        d = 0
        while b.parent:
            d += 1
            b = b.parent
        return d
    return sorted(bone_names, key=depth)
