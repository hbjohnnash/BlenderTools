"""Compact scene summary for LLM consumption (token-efficient)."""

import bpy


def get_scene_summary():
    """Return a compact JSON-friendly scene summary."""
    scene = bpy.context.scene
    objects = []

    for obj in scene.objects:
        entry = {
            "name": obj.name,
            "type": obj.type,
            "location": [round(v, 3) for v in obj.location],
        }

        if obj.type == 'MESH':
            mesh = obj.data
            entry["vertices"] = len(mesh.vertices)
            entry["faces"] = len(mesh.polygons)
            entry["materials"] = [m.name for m in mesh.materials if m]
            entry["vertex_groups"] = len(obj.vertex_groups)
            if mesh.shape_keys:
                entry["shape_keys"] = [kb.name for kb in mesh.shape_keys.key_blocks]

        elif obj.type == 'ARMATURE':
            arm = obj.data
            entry["bones"] = len(arm.bones)
            entry["bone_names"] = [b.name for b in arm.bones]
            if obj.get("bt_rig_config"):
                import json
                config = json.loads(obj["bt_rig_config"])
                entry["rig_modules"] = len(config.get("modules", []))

        elif obj.type == 'CAMERA':
            cam = obj.data
            entry["lens"] = round(cam.lens, 1)
            entry["clip_start"] = cam.clip_start
            entry["clip_end"] = cam.clip_end

        elif obj.type == 'LIGHT':
            light = obj.data
            entry["light_type"] = light.type
            entry["energy"] = light.energy

        if obj.parent:
            entry["parent"] = obj.parent.name

        if obj.animation_data and obj.animation_data.action:
            entry["action"] = obj.animation_data.action.name

        objects.append(entry)

    return {
        "success": True,
        "scene": scene.name,
        "frame_current": scene.frame_current,
        "frame_range": [scene.frame_start, scene.frame_end],
        "objects": objects,
        "object_count": len(objects),
    }


def get_object_info(name):
    """Return detailed info for a specific object."""
    obj = bpy.data.objects.get(name)
    if not obj:
        return None

    info = {
        "success": True,
        "name": obj.name,
        "type": obj.type,
        "location": list(obj.location),
        "rotation_euler": list(obj.rotation_euler),
        "scale": list(obj.scale),
        "dimensions": list(obj.dimensions),
        "parent": obj.parent.name if obj.parent else None,
        "children": [c.name for c in obj.children],
        "visible": obj.visible_get(),
    }

    # Constraints
    if obj.constraints:
        info["constraints"] = [
            {"type": c.type, "name": c.name, "enabled": c.enabled}
            for c in obj.constraints
        ]

    # Modifiers
    if obj.modifiers:
        info["modifiers"] = [
            {"type": m.type, "name": m.name}
            for m in obj.modifiers
        ]

    # Mesh specifics
    if obj.type == 'MESH':
        mesh = obj.data
        info["vertices"] = len(mesh.vertices)
        info["edges"] = len(mesh.edges)
        info["faces"] = len(mesh.polygons)
        info["materials"] = [m.name for m in mesh.materials if m]
        info["uv_layers"] = [uv.name for uv in mesh.uv_layers]
        info["vertex_groups"] = [vg.name for vg in obj.vertex_groups]

        # Seam count
        seam_count = sum(1 for e in mesh.edges if e.use_seam)
        info["seam_edges"] = seam_count

    # Armature specifics
    elif obj.type == 'ARMATURE':
        arm = obj.data
        info["bones"] = [
            {
                "name": b.name,
                "parent": b.parent.name if b.parent else None,
                "head": list(b.head_local),
                "tail": list(b.tail_local),
                "deform": b.use_deform,
            }
            for b in arm.bones
        ]
        info["collections"] = [c.name for c in arm.collections]

    # Custom properties
    custom_props = {}
    for key in obj.keys():
        if key.startswith("_"):
            continue
        val = obj[key]
        if isinstance(val, (int, float, str, bool)):
            custom_props[key] = val
        elif isinstance(val, str) and len(val) < 200:
            custom_props[key] = val
    if custom_props:
        info["custom_properties"] = custom_props

    return info
