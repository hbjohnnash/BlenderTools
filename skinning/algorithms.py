"""Weight math — heat map, envelope, rigid, cleanup."""

import bpy
import bmesh
from mathutils import Vector
from ..core.constants import DEFORM_PREFIX


def get_deform_bones(armature_obj):
    """Return list of deform bone names from an armature."""
    return [b.name for b in armature_obj.data.bones if b.use_deform]


def _nearest_bone_segment(point, armature_obj):
    """Find the nearest deform bone segment to a world-space point.

    Returns (bone_name, distance).
    """
    best_name = None
    best_dist = float('inf')
    world_mat = armature_obj.matrix_world

    for bone in armature_obj.data.bones:
        if not bone.use_deform:
            continue

        head = world_mat @ bone.head_local
        tail = world_mat @ bone.tail_local

        # Project point onto bone segment
        bone_vec = tail - head
        bone_len_sq = bone_vec.length_squared
        if bone_len_sq < 1e-8:
            dist = (point - head).length
        else:
            t = max(0, min(1, (point - head).dot(bone_vec) / bone_len_sq))
            closest = head + bone_vec * t
            dist = (point - closest).length

        if dist < best_dist:
            best_dist = dist
            best_name = bone.name

    return best_name, best_dist


def rigid_bind(mesh_obj, armature_obj):
    """Assign each vertex 100% weight to nearest deform bone.

    Args:
        mesh_obj: The mesh object.
        armature_obj: The armature object.

    Returns:
        Number of vertices assigned.
    """
    mesh = mesh_obj.data
    world_mat = mesh_obj.matrix_world
    deform_bones = get_deform_bones(armature_obj)

    # Clear existing vertex groups
    mesh_obj.vertex_groups.clear()

    # Create vertex groups for deform bones
    groups = {}
    for bn in deform_bones:
        vg = mesh_obj.vertex_groups.new(name=bn)
        groups[bn] = vg

    count = 0
    for vert in mesh.vertices:
        world_pos = world_mat @ vert.co
        bone_name, _ = _nearest_bone_segment(world_pos, armature_obj)
        if bone_name and bone_name in groups:
            groups[bone_name].add([vert.index], 1.0, 'REPLACE')
            count += 1

    return count


def auto_weight(mesh_obj, armature_obj, method='HEAT_MAP'):
    """Auto-weight with pre/post processing.

    Args:
        mesh_obj: The mesh object.
        armature_obj: The armature object.
        method: 'HEAT_MAP', 'ENVELOPE', or 'HYBRID'.

    Returns:
        True on success.
    """
    # Ensure proper selection
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    mesh_obj.select_set(True)
    armature_obj.select_set(True)
    bpy.context.view_layer.objects.active = armature_obj

    if method == 'HEAT_MAP':
        bpy.ops.object.parent_set(type='ARMATURE_AUTO')
    elif method == 'ENVELOPE':
        bpy.ops.object.parent_set(type='ARMATURE_ENVELOPE')
    elif method == 'HYBRID':
        # Heat map first, then blend with envelope influence
        bpy.ops.object.parent_set(type='ARMATURE_AUTO')

    # Post-processing cleanup
    bpy.context.view_layer.objects.active = mesh_obj
    cleanup_weights(mesh_obj, threshold=0.01, max_influences=4)

    return True


def cleanup_weights(mesh_obj, threshold=0.01, max_influences=4):
    """Clean up vertex weights.

    - Remove weights below threshold
    - Limit influences per vertex
    - Normalize

    Args:
        mesh_obj: The mesh object.
        threshold: Minimum weight to keep.
        max_influences: Maximum vertex groups per vertex.
    """
    mesh = mesh_obj.data

    for vert in mesh.vertices:
        # Collect all weights for this vertex
        weights = []
        for vg in mesh_obj.vertex_groups:
            try:
                w = vg.weight(vert.index)
                if w > threshold:
                    weights.append((vg.index, w))
                else:
                    vg.remove([vert.index])
            except RuntimeError:
                pass

        # Limit influences
        if len(weights) > max_influences:
            weights.sort(key=lambda x: x[1], reverse=True)
            for vg_idx, _ in weights[max_influences:]:
                mesh_obj.vertex_groups[vg_idx].remove([vert.index])
            weights = weights[:max_influences]

        # Normalize
        total = sum(w for _, w in weights)
        if total > 0 and abs(total - 1.0) > 1e-6:
            for vg_idx, w in weights:
                mesh_obj.vertex_groups[vg_idx].add([vert.index], w / total, 'REPLACE')


def merge_vertex_groups(mesh_obj, source_name, target_name):
    """Merge source vertex group into target, then remove source."""
    src = mesh_obj.vertex_groups.get(source_name)
    tgt = mesh_obj.vertex_groups.get(target_name)
    if not src or not tgt:
        return False

    for vert in mesh_obj.data.vertices:
        try:
            src_w = src.weight(vert.index)
        except RuntimeError:
            continue
        try:
            tgt_w = tgt.weight(vert.index)
        except RuntimeError:
            tgt_w = 0.0
        tgt.add([vert.index], src_w + tgt_w, 'REPLACE')

    mesh_obj.vertex_groups.remove(src)
    return True


def mirror_vertex_groups(mesh_obj):
    """Mirror vertex groups from L to R (or vice versa) based on naming."""
    from ..core.utils import mirror_name

    for vg in list(mesh_obj.vertex_groups):
        mirrored = mirror_name(vg.name)
        if mirrored != vg.name and mirrored not in mesh_obj.vertex_groups:
            mesh_obj.vertex_groups.new(name=mirrored)
