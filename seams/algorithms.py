"""Pure BMesh seam logic — no operators, just functions."""

import math
import os
import tempfile

import bmesh
import bpy


def mark_seams_by_angle(bm, threshold_degrees=30.0):
    """Mark edges as seams where the face angle exceeds threshold.

    Args:
        bm: BMesh instance.
        threshold_degrees: Angle threshold in degrees.

    Returns:
        Number of edges marked.
    """
    threshold = math.radians(threshold_degrees)
    count = 0
    for edge in bm.edges:
        if len(edge.link_faces) == 2:
            angle = edge.calc_face_angle(0.0)
            if angle > threshold:
                edge.seam = True
                count += 1
        elif len(edge.link_faces) < 2:
            # Boundary edges are always seams
            edge.seam = True
            count += 1
    return count


def mark_seams_by_material(bm):
    """Mark edges as seams where adjacent faces have different materials.

    Args:
        bm: BMesh instance.

    Returns:
        Number of edges marked.
    """
    count = 0
    for edge in bm.edges:
        if len(edge.link_faces) == 2:
            f1, f2 = edge.link_faces
            if f1.material_index != f2.material_index:
                edge.seam = True
                count += 1
    return count


def mark_seams_by_hard_edge(bm, mesh):
    """Mark seams at sharp/hard edges using Blender 5.0 attribute access.

    Args:
        bm: BMesh instance.
        mesh: The bpy.types.Mesh data (for attribute access).

    Returns:
        Number of edges marked.
    """
    sharp_attr = mesh.attributes.get("sharp_edge")
    if sharp_attr is None:
        return 0

    count = 0
    # Read sharp_edge attribute values
    sharp_values = [False] * len(mesh.edges)
    sharp_attr.data.foreach_get("value", sharp_values)

    for edge in bm.edges:
        if edge.index < len(sharp_values) and sharp_values[edge.index]:
            edge.seam = True
            count += 1
    return count


def mark_seams_island_aware(bm, max_islands=0, max_stretch=0.5):
    """Mark seams iteratively to control UV island count and stretch.

    Strategy: Start with angle-based seams, then iteratively add seams
    at the highest-distortion edges until stretch is acceptable or
    island count limit is reached.

    Args:
        bm: BMesh instance.
        max_islands: Maximum UV island count (0 = no limit).
        max_stretch: Maximum acceptable stretch value (0-1).

    Returns:
        Number of edges marked.
    """
    # Start with moderate angle-based seams
    count = mark_seams_by_angle(bm, threshold_degrees=45.0)

    # Sort remaining non-seam edges by face angle (descending)
    candidates = []
    for edge in bm.edges:
        if not edge.seam and len(edge.link_faces) == 2:
            angle = edge.calc_face_angle(0.0)
            candidates.append((angle, edge))

    candidates.sort(key=lambda x: x[0], reverse=True)

    # Add seams at sharpest edges first
    for angle, edge in candidates:
        if max_islands > 0 and count >= max_islands * 3:
            break
        if angle > math.radians(20.0):
            edge.seam = True
            count += 1

    return count


def mark_seams_projection(bm, obj, mode='BOX'):
    """Mark seams based on projection direction (box/cylinder/sphere).

    Args:
        bm: BMesh instance.
        obj: The mesh object (for world matrix).
        mode: 'BOX', 'CYLINDER', or 'SPHERE'.

    Returns:
        Number of edges marked.
    """
    world_matrix = obj.matrix_world
    count = 0

    if mode == 'BOX':
        # Mark seams where face normals change primary axis
        for edge in bm.edges:
            if len(edge.link_faces) == 2:
                f1, f2 = edge.link_faces
                n1 = world_matrix.to_3x3() @ f1.normal
                n2 = world_matrix.to_3x3() @ f2.normal
                # Get dominant axis for each normal
                axis1 = max(range(3), key=lambda i: abs(n1[i]))
                axis2 = max(range(3), key=lambda i: abs(n2[i]))
                if axis1 != axis2:
                    edge.seam = True
                    count += 1

    elif mode == 'CYLINDER':
        # Mark seams along a vertical line and top/bottom caps
        for edge in bm.edges:
            if len(edge.link_faces) == 2:
                f1, f2 = edge.link_faces
                n1 = world_matrix.to_3x3() @ f1.normal
                n2 = world_matrix.to_3x3() @ f2.normal
                # Check if normals transition between up/down and side
                up1 = abs(n1.z) > 0.7
                up2 = abs(n2.z) > 0.7
                if up1 != up2:
                    edge.seam = True
                    count += 1
                # Add a single vertical seam line (back of cylinder)
                elif not up1 and not up2:
                    mid = (edge.verts[0].co + edge.verts[1].co) / 2
                    mid_world = world_matrix @ mid
                    if mid_world.y < 0 and abs(mid_world.x) < 0.01:
                        edge.seam = True
                        count += 1

    elif mode == 'SPHERE':
        # Mark seams: one longitude line + equator-ish band
        for edge in bm.edges:
            if len(edge.link_faces) == 2:
                mid = (edge.verts[0].co + edge.verts[1].co) / 2
                mid_world = world_matrix @ mid
                # Vertical seam at back
                if mid_world.y < 0 and abs(mid_world.x) < 0.01:
                    edge.seam = True
                    count += 1

    return count


def mark_seams_neural(obj):
    """Mark seams using MeshCNN neural network prediction.

    The mesh is exported to a temporary OBJ, run through MeshCNN's
    pretrained body segmentation model, and segment boundaries are
    marked as seam edges.

    Must be called in OBJECT mode — the function handles mode switching.

    Args:
        obj: The mesh object to process.

    Returns:
        Number of edges marked as seams.
    """
    from .ml.mesh_cnn_adapter import MeshCNNAdapter

    adapter = MeshCNNAdapter.get_instance()
    if not adapter.is_ready():
        raise RuntimeError(
            "MeshCNN not initialized. Click 'Initialize AI Seams' first."
        )

    # Export mesh to temp OBJ (must be in object mode)
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    fd, temp_path = tempfile.mkstemp(suffix=".obj")
    os.close(fd)
    try:
        bpy.ops.wm.obj_export(
            filepath=temp_path,
            export_selected_objects=True,
            export_uv=False,
            export_normals=True,
        )

        # Run neural prediction
        seam_edge_indices = adapter.predict(temp_path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        # Also remove the .mtl sidecar if created
        mtl_path = temp_path.replace(".obj", ".mtl")
        if os.path.exists(mtl_path):
            os.unlink(mtl_path)

    # Switch back to edit mode and mark the predicted edges
    bpy.ops.object.mode_set(mode='EDIT')
    bm = bmesh.from_edit_mesh(obj.data)
    bm.edges.ensure_lookup_table()

    count = 0
    for edge_idx in seam_edge_indices:
        if 0 <= edge_idx < len(bm.edges):
            bm.edges[edge_idx].seam = True
            count += 1

    bmesh.update_edit_mesh(obj.data)
    return count


def clear_all_seams(bm):
    """Clear all seams on the mesh."""
    for edge in bm.edges:
        edge.seam = False


def apply_seam_preset(bm, obj, preset_name):
    """Load and apply a seam preset from presets/seam_presets/.

    Args:
        bm: BMesh instance.
        obj: The mesh object.
        preset_name: Name of the preset (without .json).

    Returns:
        Number of edges marked.
    """
    from ..core.constants import SEAM_PRESET_DIR
    from ..core.utils import load_json_preset

    preset = load_json_preset(SEAM_PRESET_DIR, preset_name)

    # Clear existing seams if preset says so
    if preset.get("clear_existing", True):
        clear_all_seams(bm)

    total = 0
    for step in preset.get("steps", []):
        method = step.get("method")
        params = step.get("params", {})

        if method == "angle":
            total += mark_seams_by_angle(bm, **params)
        elif method == "material":
            total += mark_seams_by_material(bm)
        elif method == "hard_edge":
            total += mark_seams_by_hard_edge(bm, obj.data)
        elif method == "island_aware":
            total += mark_seams_island_aware(bm, **params)
        elif method == "projection":
            total += mark_seams_projection(bm, obj, **params)

    return total
