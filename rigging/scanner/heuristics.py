"""Position and hierarchy heuristics for bones not matched by name maps."""

import math
from mathutils import Vector


def analyze_by_heuristics(armature_obj, already_mapped):
    """Analyze unmapped bones using position/hierarchy heuristics.

    Args:
        armature_obj: Blender armature object.
        already_mapped: set of bone names already identified by name maps.

    Returns:
        dict of {bone_name: {role, side, module_type, chain_id, confidence, source}}
    """
    bones = armature_obj.data.bones
    if not bones:
        return {}

    result = {}

    # Build world-space positions
    world_mat = armature_obj.matrix_world
    bone_heads = {}
    bone_tails = {}
    for b in bones:
        bone_heads[b.name] = world_mat @ b.head_local
        bone_tails[b.name] = world_mat @ b.tail_local

    # Adaptive side threshold from skeleton X range
    all_x = [bone_heads[b.name].x for b in bones]
    x_range = max(all_x) - min(all_x) if all_x else 1.0
    side_threshold = max(0.01, x_range * 0.02)

    # Step 1: Find root bone
    root = _find_root(bones)
    if not root:
        return result

    # Step 2: Detect reference root (ground bone at origin with big gap to children)
    root_is_reference = _is_reference_root(root, bones, bone_heads, bone_tails)

    if root_is_reference:
        if root.name not in already_mapped:
            result[root.name] = {
                "role": "root",
                "side": "C",
                "module_type": "root",
                "chain_id": "root_C",
                "confidence": 0.8,
                "source": "heuristic",
            }
        spine_start = _find_spine_start(root, bones, bone_heads)
    else:
        spine_start = root

    # Step 3: Build spine chain (stop before neck/head)
    if spine_start:
        raw_spine = _find_spine_chain(bones, bone_heads, spine_start)
        spine_chain, neck_head_chain = _split_spine_and_neck(raw_spine, bones, bone_heads)
    else:
        spine_chain, neck_head_chain = [], []

    spine_names = {b.name for b in spine_chain}

    # Map spine bones
    for i, b in enumerate(spine_chain):
        if b.name not in already_mapped:
            if i == 0:
                role = "hips"
            elif i == len(spine_chain) - 1:
                role = "chest"
            else:
                role = f"spine_{i:02d}"
            result[b.name] = {
                "role": role, "side": "C", "module_type": "spine",
                "chain_id": "spine_C", "confidence": 0.6, "source": "heuristic",
            }

    # Map neck/head bones
    for i, b in enumerate(neck_head_chain):
        if b.name not in already_mapped:
            if i == len(neck_head_chain) - 1:
                role = "head"
            else:
                role = f"neck_{i:02d}" if i > 0 else "neck"
            result[b.name] = {
                "role": role, "side": "C", "module_type": "neck_head",
                "chain_id": "neck_head_C", "confidence": 0.6, "source": "heuristic",
            }

    # Step 4: Classify direct spine branches
    spine_and_neck = spine_names | {b.name for b in neck_head_chain}
    mapped_set = set(already_mapped) | set(result.keys())

    # Get Z range of spine for arm vs leg classification
    if spine_chain:
        spine_z_min = min(bone_heads[b.name].z for b in spine_chain)
        spine_z_max = max(bone_heads[b.name].z for b in spine_chain)
        spine_z_mid = (spine_z_min + spine_z_max) / 2
    else:
        spine_z_mid = 0

    # Find all direct children of spine/neck bones that aren't part of spine/neck
    branch_bones = []
    for b in bones:
        if b.parent and b.parent.name in spine_and_neck and b.name not in spine_and_neck:
            if b.name not in mapped_set:
                branch_bones.append(b)

    # Process each branch
    generic_chain_counter = 0

    for branch in branch_bones:
        if branch.name in mapped_set:
            continue

        chain = _get_chain_follow_main(branch, bones, bone_heads, bone_tails)
        if not chain:
            continue

        branch_pos = bone_heads[branch.name]

        # Classify by position and direction
        module_type = _classify_branch(
            chain, branch, bones, bone_heads, bone_tails,
            spine_z_mid, side_threshold
        )

        # For side detection, use the chain's average X position (more reliable
        # than the branch point, which may be near center for pelvis bones)
        avg_x = sum(bone_heads[b.name].x for b in chain) / len(chain)
        side = _get_side(avg_x, side_threshold)

        if module_type == "arm":
            chain_id = f"arm_{side}"
            roles = _arm_roles(len(chain))
        elif module_type == "leg":
            # Extend leg chain through multi-child joints (e.g., Lower.Leg has
            # piston/spring children alongside the main Foot continuation)
            chain = _extend_chain_through_branches(chain, bones, bone_heads, bone_tails)
            # Recalculate side with extended chain
            avg_x = sum(bone_heads[b.name].x for b in chain) / len(chain)
            side = _get_side(avg_x, side_threshold)
            chain_id = f"leg_{side}"
            roles = _leg_roles_with_pelvis(len(chain))
        else:
            generic_chain_counter += 1
            chain_id = f"generic_{generic_chain_counter:02d}_{side}"
            roles = [f"bone_{i:02d}" for i in range(len(chain))]

        for i, b in enumerate(chain):
            if b.name not in mapped_set:
                result[b.name] = {
                    "role": roles[i] if i < len(roles) else f"bone_{i:02d}",
                    "side": side,
                    "module_type": module_type,
                    "chain_id": chain_id,
                    "confidence": 0.5,
                    "source": "heuristic",
                }
                mapped_set.add(b.name)

        # Detect fingers at the end of arm chains
        if module_type == "arm":
            last_bone = chain[-1]
            _detect_fingers(
                last_bone, bones, bone_heads, bone_tails,
                side, mapped_set, result, side_threshold
            )

    # Step 5: Detect sub-branches that might be legs (e.g., Spine → Pelvis.L → leg chain)
    # Re-check branches that were classified as non-leg but have leg-like children
    for branch in branch_bones:
        if branch.name not in mapped_set:
            continue
        info = result.get(branch.name)
        if not info or info["module_type"] not in ("generic", "leg"):
            continue
        # Already handled
        if info["module_type"] == "leg":
            continue

        # Check if this branch's children form legs
        for child in bones:
            if child.parent != branch or child.name in mapped_set:
                continue
            child_chain = _get_chain_follow_main(child, bones, bone_heads, bone_tails)
            if len(child_chain) < 2:
                continue

            child_pos = bone_heads[child.name]
            end_pos = bone_tails[child_chain[-1].name]
            if (end_pos - child_pos).z < 0:
                side = _get_side(child_pos.x, side_threshold)
                # Re-classify the parent as pelvis + children as leg
                full_chain = [branch] + child_chain
                roles = _leg_roles_with_pelvis(len(full_chain))
                chain_id = f"leg_{side}"

                # Update the parent bone's classification
                result[branch.name] = {
                    "role": "pelvis", "side": side, "module_type": "leg",
                    "chain_id": chain_id, "confidence": 0.5, "source": "heuristic",
                }

                for i, b in enumerate(child_chain):
                    if b.name not in mapped_set:
                        result[b.name] = {
                            "role": roles[i + 1] if (i + 1) < len(roles) else f"bone_{i:02d}",
                            "side": side, "module_type": "leg",
                            "chain_id": chain_id, "confidence": 0.5, "source": "heuristic",
                        }
                        mapped_set.add(b.name)

    return result


# ── Root detection ──

def _find_root(bones):
    """Find the root bone (no parent)."""
    roots = [b for b in bones if b.parent is None]
    if len(roots) == 1:
        return roots[0]
    if roots:
        return max(roots, key=lambda b: b.head_local.z)
    return None


def _is_reference_root(root, bones, bone_heads, bone_tails):
    """Detect if root is a ground reference bone (not part of the actual skeleton)."""
    root_head = bone_heads[root.name]
    root_tail = bone_tails[root.name]
    root_length = (root_tail - root_head).length

    children = [b for b in bones if b.parent == root]
    if not children:
        return False

    # Gap between root tail and closest child head
    min_gap = min((bone_heads[c.name] - root_tail).length for c in children)

    # Large gap relative to bone length → reference bone
    if min_gap > root_length * 0.5 and min_gap > 1.0:
        return True

    # Root at origin with children much higher
    if root_head.length < 1.0:
        child_z = max(bone_heads[c.name].z for c in children)
        if child_z > root_length * 0.5:
            return True

    return False


def _find_spine_start(root, bones, bone_heads):
    """Find the best child of a reference root to start the spine chain."""
    children = [b for b in bones if b.parent == root]
    if not children:
        return None
    # Pick child nearest center X and highest Z
    return max(children, key=lambda c: -abs(bone_heads[c.name].x) + bone_heads[c.name].z * 0.01)


# ── Spine chain ──

def _find_spine_chain(bones, bone_heads, start):
    """Find the vertical chain starting from a bone, staying near X=0."""
    chain = [start]
    current = start
    while True:
        children = [b for b in bones if b.parent == current]
        if not children:
            break
        best = None
        best_score = -1
        for c in children:
            pos = bone_heads[c.name]
            x_score = max(0, 1.0 - abs(pos.x) * 0.1)
            z_score = 1.0 if pos.z >= bone_heads[current.name].z else 0.0
            score = x_score + z_score
            if score > best_score:
                best_score = score
                best = c
        if best and best_score > 0.5:
            chain.append(best)
            current = best
        else:
            break
    return chain


def _split_spine_and_neck(raw_chain, bones, bone_heads):
    """Split a raw spine chain into spine + neck_head at the branch point.

    The split happens where the upper spine has branches going outward (shoulders)
    but the chain continues upward as neck/head.
    """
    if len(raw_chain) <= 2:
        return raw_chain, []

    # Find the highest bone that has lateral branches (shoulders)
    split_idx = len(raw_chain)  # default: everything is spine
    for i in range(len(raw_chain) - 1, 0, -1):
        bone = raw_chain[i]
        children = [b for b in bones if b.parent == bone]
        lateral_children = [
            c for c in children
            if c not in raw_chain and abs(bone_heads[c.name].x) > abs(bone_heads[bone.name].x) + 1.0
        ]
        if lateral_children:
            # This bone has lateral branches — it's the last spine bone (chest)
            split_idx = i + 1
            break

    spine = raw_chain[:split_idx]
    neck_head = raw_chain[split_idx:]
    return spine, neck_head


# ── Chain following ──

def _get_chain_follow_main(bone, bones, bone_heads, bone_tails):
    """Follow a chain from a bone, picking the 'main' child at branches.

    At 2-child nodes, picks the child that best continues the bone's direction.
    Stops at 3+ children (likely a hand/foot with finger/toe branches).
    """
    chain = [bone]
    current = bone
    while True:
        children = [b for b in bones if b.parent == current]
        if not children:
            break
        if len(children) == 1:
            chain.append(children[0])
            current = children[0]
            continue
        if len(children) >= 3:
            # Too many branches — this is likely a hand/foot endpoint, stop here
            break

        # 2 children: pick the one closest to the current bone's direction
        cur_dir = (bone_tails[current.name] - bone_heads[current.name]).normalized()
        best = None
        best_dot = -2
        for c in children:
            c_dir = (bone_tails[c.name] - bone_heads[c.name]).normalized()
            dot = cur_dir.dot(c_dir)
            if dot > best_dot:
                best_dot = dot
                best = c

        if best and best_dot > 0.0:
            chain.append(best)
            current = best
        else:
            break
    return chain


def _extend_chain_through_branches(chain, bones, bone_heads, bone_tails):
    """Continue a chain past multi-child joints by following the main direction.

    When a chain ends because the last bone has 3+ children, try to find
    the child that best continues the chain direction and recurse.
    """
    extended = list(chain)
    current = extended[-1]
    while True:
        children = [b for b in bones if b.parent == current]
        if len(children) < 2:
            if len(children) == 1:
                extended.append(children[0])
                current = children[0]
                continue
            break

        # Pick the child that best continues the chain direction
        cur_dir = (bone_tails[current.name] - bone_heads[current.name]).normalized()
        best = None
        best_dot = -2
        for c in children:
            c_dir = (bone_tails[c.name] - bone_heads[c.name]).normalized()
            dot = cur_dir.dot(c_dir)
            if dot > best_dot:
                best_dot = dot
                best = c

        if best and best_dot > 0.3:
            extended.append(best)
            current = best
        else:
            break
    return extended


# ── Classification ──

def _classify_branch(chain, branch, bones, bone_heads, bone_tails,
                     spine_z_mid, side_threshold):
    """Classify a branch chain as arm, leg, or generic.

    Uses the branch point's Z position relative to spine center and
    the overall chain direction.
    """
    branch_z = bone_heads[branch.name].z
    branch_x = abs(bone_heads[branch.name].x)

    # Chain direction from first to last bone
    start = bone_heads[chain[0].name]
    end = bone_tails[chain[-1].name]
    delta = end - start

    # Branch from upper spine + significant lateral offset → arm
    # Must have meaningful X offset (not just wires/pipes near center)
    if branch_z > spine_z_mid and branch_x > side_threshold * 5:
        return "arm"

    # Branch from lower spine + goes downward → leg
    if branch_z <= spine_z_mid and delta.z < 0:
        return "leg"

    # Check if it continues downward significantly → leg regardless of branch point
    if delta.z < 0 and abs(delta.z) > abs(delta.x) * 2:
        # Strongly downward from lower spine area
        if branch_z < spine_z_mid + (spine_z_mid * 0.2):
            return "leg"

    return "generic"


def _get_side(x_pos, threshold=0.01):
    """Determine side from X position."""
    if x_pos > threshold:
        return "L"
    elif x_pos < -threshold:
        return "R"
    return "C"


# ── Finger detection ──

def _detect_fingers(hand_bone, bones, bone_heads, bone_tails,
                    side, mapped_set, result, side_threshold):
    """Detect finger chains branching from a hand/end-of-arm bone."""
    direct_children = [b for b in bones if b.parent == hand_bone and b.name not in mapped_set]
    if len(direct_children) < 2:
        return

    finger_idx = 0
    for child in direct_children:
        if child.name in mapped_set:
            continue

        finger_chain = _get_chain_follow_main(child, bones, bone_heads, bone_tails)
        if len(finger_chain) < 2:
            continue

        finger_idx += 1
        chain_id = f"finger_{finger_idx:02d}_{side}"

        for i, b in enumerate(finger_chain):
            if b.name not in mapped_set:
                result[b.name] = {
                    "role": f"finger_{finger_idx:02d}_bone_{i:02d}",
                    "side": side,
                    "module_type": "finger",
                    "chain_id": chain_id,
                    "confidence": 0.4,
                    "source": "heuristic",
                }
                mapped_set.add(b.name)


# ── Role generators ──

def _arm_roles(count):
    roles = ["clavicle", "upper_arm", "lower_arm", "hand"]
    if count <= len(roles):
        return roles[:count]
    return roles + [f"extra_{i}" for i in range(count - len(roles))]


def _leg_roles(count):
    roles = ["upper_leg", "lower_leg", "foot", "toe"]
    if count <= len(roles):
        return roles[:count]
    return roles + [f"extra_{i}" for i in range(count - len(roles))]


def _leg_roles_with_pelvis(count):
    roles = ["pelvis", "upper_leg", "lower_leg", "foot", "toe"]
    if count <= len(roles):
        return roles[:count]
    return roles + [f"extra_{i}" for i in range(count - len(roles))]
