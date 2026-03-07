"""Core scan orchestrator — combines name maps, BT convention, and heuristics."""

from .name_maps import detect_skeleton_type, apply_name_map
from .heuristics import analyze_by_heuristics
from .bone_naming import parse_bt_name, INDEXED_TYPES


def scan_skeleton(armature_obj):
    """Scan an armature and identify bone roles.

    Returns:
        dict with keys:
        - skeleton_type: str (e.g. "mixamo", "ue_mannequin", "bt_convention", "unknown")
        - confidence: float (0.0–1.0)
        - bones: dict {bone_name: {role, side, module_type, chain_id, confidence, source}}
        - chains: dict {chain_id: {module_type, side, bones: [bone_name, ...], bone_count}}
        - unmapped_bones: list of bone names not assigned to any chain
        - generated_bones: list (empty at scan time, populated after wrap)
    """
    bone_names = [b.name for b in armature_obj.data.bones]

    # Step 0: Detect BT-convention bones (instant, 100% confidence)
    bt_bones = _detect_bt_convention(armature_obj)
    if bt_bones:
        bt_names = set(bt_bones.keys())
        remaining = [n for n in bone_names if n not in bt_names]
        # If most bones are BT-named, report as bt_convention type
        if len(bt_bones) > len(remaining):
            skeleton_type = "bt_convention"
            confidence = 1.0
        else:
            skeleton_type, confidence = detect_skeleton_type(bone_names)
    else:
        bt_names = set()
        remaining = bone_names
        skeleton_type, confidence = detect_skeleton_type(bone_names)

    # Step 1: Try name maps on non-BT bones
    mapped_bones = {}
    if skeleton_type not in ("unknown", "bt_convention"):
        mapped_bones = apply_name_map(remaining, skeleton_type)

    # Step 2: Heuristic fallback for remaining unmapped bones
    already_mapped = bt_names | set(mapped_bones.keys())
    heuristic_bones = analyze_by_heuristics(armature_obj, already_mapped)

    # Merge results (BT convention > name map > heuristics)
    all_bones = {}
    all_bones.update(heuristic_bones)
    all_bones.update(mapped_bones)
    all_bones.update(bt_bones)

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


def _normalize_role(role, type_internal):
    """Strip chain-number prefix from roles for non-indexed types.

    For named-role types (arm, leg, etc.), "2_upper_arm" → "upper_arm" so
    that wrap assembly role lookups work regardless of chain numbering.
    For indexed types (finger, tail, etc.), the role is kept as-is since
    the chain number is part of the identity (e.g. "1_01").
    """
    if type_internal in INDEXED_TYPES:
        return role
    parts = role.split('_', 1)
    if len(parts) == 2 and parts[0].isdigit():
        return parts[1]
    return role


def _detect_bt_convention(armature_obj):
    """Detect bones named with the BT_{Type}_{Side}_{Role} convention.

    Groups bones into chains by (type, side). Disconnected sub-chains
    of the same type+side are numbered: type_01_side, type_02_side.
    """
    bone_lookup = {b.name: b for b in armature_obj.data.bones}
    parsed = {}
    for bone in armature_obj.data.bones:
        info = parse_bt_name(bone.name)
        if info:
            parsed[bone.name] = info

    if not parsed:
        return {}

    # Group by (type, side)
    groups = {}
    for name, info in parsed.items():
        key = (info['type'], info['side'])
        groups.setdefault(key, []).append(name)

    # Split disconnected sub-chains within each group
    result = {}
    for (type_internal, side), names in groups.items():
        sub_chains = _split_by_hierarchy(names, bone_lookup)

        if len(sub_chains) == 1:
            chain_id = f"{type_internal}_{side}"
            for name in sub_chains[0]:
                info = parsed[name]
                result[name] = {
                    "role": _normalize_role(info['role'], type_internal),
                    "side": side,
                    "module_type": type_internal,
                    "chain_id": chain_id,
                    "confidence": 1.0,
                    "source": "bt_convention",
                }
        else:
            for idx, chain_names in enumerate(sub_chains):
                chain_id = f"{type_internal}_{idx + 1:02d}_{side}"
                for name in chain_names:
                    info = parsed[name]
                    result[name] = {
                        "role": _normalize_role(info['role'], type_internal),
                        "side": side,
                        "module_type": type_internal,
                        "chain_id": chain_id,
                        "confidence": 1.0,
                        "source": "bt_convention",
                    }

    return result


def _split_by_hierarchy(bone_names, bone_lookup):
    """Split bone names into connected parent-child chains."""
    bone_set = set(bone_names)
    used = set()
    chains = []

    # Sort by depth (roots first)
    sorted_names = sorted(bone_names, key=lambda n: _depth(n, bone_lookup))

    for name in sorted_names:
        if name in used:
            continue
        chain = [name]
        used.add(name)
        _collect_descendants(name, bone_set, bone_lookup, used, chain)
        chains.append(chain)

    return chains


def _collect_descendants(name, bone_set, bone_lookup, used, chain):
    bone = bone_lookup.get(name)
    if not bone:
        return
    for child in bone.children:
        if child.name in bone_set and child.name not in used:
            chain.append(child.name)
            used.add(child.name)
            _collect_descendants(child.name, bone_set, bone_lookup, used, chain)


def _depth(name, bone_lookup):
    b = bone_lookup.get(name)
    d = 0
    if b:
        while b.parent:
            d += 1
            b = b.parent
    return d


def _sort_by_hierarchy(bone_names, bone_lookup):
    """Sort bone names by hierarchy depth (root first)."""
    return sorted(bone_names, key=lambda n: _depth(n, bone_lookup))
