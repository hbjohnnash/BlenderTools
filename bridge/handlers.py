"""Route dispatch for bridge HTTP requests."""


import bpy

from ..core.constants import BRIDGE_PREFIX


def handle_get(path, params):
    """Handle GET requests. Returns (response_dict, error_string)."""

    if path == f"{BRIDGE_PREFIX}/ping":
        return {"success": True, "message": "BlenderTools bridge is running"}, None

    if path == f"{BRIDGE_PREFIX}/scene-summary":
        from .scene_query import get_scene_summary
        return get_scene_summary(), None

    if path == f"{BRIDGE_PREFIX}/object-info":
        name = params.get("name")
        if not name:
            return None, "Missing 'name' parameter"
        from .scene_query import get_object_info
        info = get_object_info(name)
        if info is None:
            return None, f"Object not found: {name}"
        return info, None

    if path == f"{BRIDGE_PREFIX}/screenshot":
        from .screenshot import capture_viewport
        result = capture_viewport()
        return result, None

    return None, None  # 404


def handle_post(path, body):
    """Handle POST requests. Returns (response_dict, error_string)."""

    # --- Seam endpoints ---
    if path == f"{BRIDGE_PREFIX}/seam/by-angle":
        return _seam_by_angle(body)

    if path == f"{BRIDGE_PREFIX}/seam/preset":
        return _seam_preset(body)

    # --- Rig endpoints ---
    if path == f"{BRIDGE_PREFIX}/rig/add-module":
        return _rig_add_module(body)

    if path == f"{BRIDGE_PREFIX}/rig/generate":
        return _rig_generate(body)

    if path == f"{BRIDGE_PREFIX}/rig/load-config":
        return _rig_load_config(body)

    # --- Skin endpoints ---
    if path == f"{BRIDGE_PREFIX}/skin/auto-weight":
        return _skin_auto_weight(body)

    if path == f"{BRIDGE_PREFIX}/skin/rigid-bind":
        return _skin_rigid_bind(body)

    # --- Animation endpoints ---
    if path == f"{BRIDGE_PREFIX}/anim/procedural":
        return _anim_procedural(body)

    if path == f"{BRIDGE_PREFIX}/anim/mechanical":
        return _anim_mechanical(body)

    # --- Export endpoints ---
    if path == f"{BRIDGE_PREFIX}/export/scale-rig":
        return _export_scale_rig(body)

    if path == f"{BRIDGE_PREFIX}/export/to-ue":
        return _export_to_ue(body)

    # --- Scanner endpoints ---
    if path == f"{BRIDGE_PREFIX}/rig/scan-skeleton":
        return _rig_scan_skeleton(body)

    if path == f"{BRIDGE_PREFIX}/rig/apply-wrap":
        return _rig_apply_wrap(body)

    if path == f"{BRIDGE_PREFIX}/rig/clear-wrap":
        return _rig_clear_wrap(body)

    if path == f"{BRIDGE_PREFIX}/rig/toggle-fk-ik":
        return _rig_toggle_fk_ik(body)

    if path == f"{BRIDGE_PREFIX}/rig/bake-to-def":
        return _rig_bake_to_def(body)

    if path == f"{BRIDGE_PREFIX}/rig/floor-contact":
        return _rig_floor_contact(body)

    # --- Root Motion ---
    if path == f"{BRIDGE_PREFIX}/anim/root-motion-setup":
        return _root_motion_setup(body)
    if path == f"{BRIDGE_PREFIX}/anim/root-motion-finalize":
        return _root_motion_finalize(body)
    if path == f"{BRIDGE_PREFIX}/anim/root-motion-cancel":
        return _root_motion_cancel(body)

    # --- Exec endpoint ---
    if path == f"{BRIDGE_PREFIX}/exec":
        return _exec_code(body)

    return None, None  # 404


# --- Implementation functions ---

def _get_object(name, obj_type=None):
    """Get an object by name, optionally checking type."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None, f"Object not found: {name}"
    if obj_type and obj.type != obj_type:
        return None, f"Object '{name}' is not a {obj_type}"
    return obj, None


def _seam_by_angle(body):
    obj_name = body.get("object")
    threshold = body.get("threshold", 30.0)

    obj, err = _get_object(obj_name, 'MESH')
    if err:
        return None, err

    import bmesh

    from ..seams.algorithms import clear_all_seams, mark_seams_by_angle

    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    bm = bmesh.from_edit_mesh(obj.data)
    clear_all_seams(bm)
    count = mark_seams_by_angle(bm, threshold)
    bmesh.update_edit_mesh(obj.data)
    bpy.ops.object.mode_set(mode='OBJECT')

    return {"success": True, "seams_marked": count}, None


def _seam_preset(body):
    obj_name = body.get("object")
    preset = body.get("preset")

    obj, err = _get_object(obj_name, 'MESH')
    if err:
        return None, err

    import bmesh

    from ..seams.algorithms import apply_seam_preset

    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    bm = bmesh.from_edit_mesh(obj.data)
    count = apply_seam_preset(bm, obj, preset)
    bmesh.update_edit_mesh(obj.data)
    bpy.ops.object.mode_set(mode='OBJECT')

    return {"success": True, "seams_marked": count}, None


def _rig_add_module(body):
    arm_name = body.get("armature")
    arm, err = _get_object(arm_name, 'ARMATURE')
    if err:
        return None, err

    from ..rigging.config_loader import config_from_armature, store_config_on_armature

    config = config_from_armature(arm) or {"name": "Rig", "modules": [], "global_options": {}}
    module_config = body.get("config", {})
    module_config["type"] = body.get("module_type", module_config.get("type"))
    config["modules"].append(module_config)
    store_config_on_armature(arm, config)

    return {"success": True, "module_count": len(config["modules"])}, None


def _rig_generate(body):
    arm_name = body.get("armature")
    arm, err = _get_object(arm_name, 'ARMATURE')
    if err:
        return None, err

    from ..rigging.assembly import assemble_rig, disassemble_rig
    from ..rigging.config_loader import config_from_armature, instantiate_modules

    config = config_from_armature(arm)
    if not config:
        return None, "No rig config on armature"

    disassemble_rig(arm)
    modules = instantiate_modules(config)
    bone_names = assemble_rig(arm, modules)

    return {"success": True, "bones_created": len(bone_names)}, None


def _rig_load_config(body):
    arm_name = body.get("armature")
    arm, err = _get_object(arm_name, 'ARMATURE')
    if err:
        return None, err

    config = body.get("config")
    if not config:
        return None, "Missing 'config' in body"

    from ..rigging.config_loader import store_config_on_armature
    store_config_on_armature(arm, config)

    return {"success": True, "modules": len(config.get("modules", []))}, None


def _skin_auto_weight(body):
    mesh_name = body.get("mesh")
    arm_name = body.get("armature")
    method = body.get("method", "HEAT_MAP").upper()

    mesh, err = _get_object(mesh_name, 'MESH')
    if err:
        return None, err
    arm, err = _get_object(arm_name, 'ARMATURE')
    if err:
        return None, err

    from ..skinning.algorithms import auto_weight
    auto_weight(mesh, arm, method)

    return {"success": True}, None


def _skin_rigid_bind(body):
    mesh_name = body.get("mesh")
    arm_name = body.get("armature")

    mesh, err = _get_object(mesh_name, 'MESH')
    if err:
        return None, err
    arm, err = _get_object(arm_name, 'ARMATURE')
    if err:
        return None, err

    from ..skinning.algorithms import rigid_bind
    count = rigid_bind(mesh, arm)

    return {"success": True, "vertices_assigned": count}, None


def _anim_procedural(body):
    arm_name = body.get("armature")
    arm, err = _get_object(arm_name, 'ARMATURE')
    if err:
        return None, err

    anim_type = body.get("type", "walk")
    params = body.get("params", {})

    if anim_type == "walk":
        from ..animation.procedural.locomotion import generate_walk_cycle
        data = generate_walk_cycle(params)
    elif anim_type == "run":
        from ..animation.procedural.locomotion import generate_run_cycle
        data = generate_run_cycle(params)
    elif anim_type == "idle":
        from ..animation.procedural.locomotion import generate_idle
        data = generate_idle(params)
    elif anim_type == "breathing":
        from ..animation.procedural.breathing import generate_breathing
        data = generate_breathing(params)
    else:
        return None, f"Unknown procedural type: {anim_type}"

    return {"success": True, "channels": len(data)}, None


def _anim_mechanical(body):
    obj_name = body.get("object")
    obj, err = _get_object(obj_name)
    if err:
        return None, err

    anim_type = body.get("type", "piston_cycle")
    params = body.get("params", {})

    from ..animation.procedural.mechanical import (
        generate_conveyor,
        generate_gear_rotation,
        generate_piston_cycle,
    )

    if anim_type == "piston_cycle":
        data = generate_piston_cycle(params)
    elif anim_type == "gear_rotation":
        data = generate_gear_rotation(params)
    elif anim_type == "conveyor":
        data = generate_conveyor(params)
    else:
        return None, f"Unknown mechanical type: {anim_type}"

    return {"success": True, "channels": len(data)}, None


def _export_scale_rig(body):
    arm_name = body.get("armature")
    factor = body.get("factor", 1.0)

    arm, err = _get_object(arm_name, 'ARMATURE')
    if err:
        return None, err

    from ..export.scale_rig import scale_rig
    stats = scale_rig(arm, factor)

    return {"success": True, **stats}, None


def _export_to_ue(body):
    arm_name = body.get("armature")
    arm, err = _get_object(arm_name, 'ARMATURE')
    if err:
        return None, err

    mesh_names = body.get("meshes", [])
    if mesh_names:
        meshes = []
        for name in mesh_names:
            m, merr = _get_object(name, 'MESH')
            if merr:
                return None, merr
            meshes.append(m)
    else:
        from ..export.ue_export import filter_exportable_meshes
        meshes = filter_exportable_meshes(arm)

    output_dir = body.get("output", "//export/")
    import bpy as _bpy
    output_dir = _bpy.path.abspath(output_dir)

    from ..export.ue_export import export_to_ue
    result = export_to_ue(
        arm, meshes, output_dir,
        export_mesh=body.get("export_mesh", True),
        export_anim=body.get("export_anim", True),
        separate_anim=body.get("separate_anim", False),
        ue_naming=body.get("ue_naming", True),
    )

    return result, None


def _rig_scan_skeleton(body):
    arm_name = body.get("armature")
    arm, err = _get_object(arm_name, 'ARMATURE')
    if err:
        return None, err

    from ..rigging.scanner.operators import _scan_data_to_props
    from ..rigging.scanner.scan import scan_skeleton
    scan_data = scan_skeleton(arm)
    _scan_data_to_props(arm, scan_data)

    return {
        "success": True,
        "skeleton_type": scan_data["skeleton_type"],
        "confidence": scan_data["confidence"],
        "chains": len(scan_data["chains"]),
        "bones_mapped": len(scan_data["bones"]),
        "unmapped": len(scan_data["unmapped_bones"]),
    }, None


def _rig_apply_wrap(body):
    arm_name = body.get("armature")
    arm, err = _get_object(arm_name, 'ARMATURE')
    if err:
        return None, err

    if not arm.bt_scan.is_scanned:
        return None, "Armature has not been scanned yet"

    from ..rigging.scanner.operators import _props_to_scan_data
    from ..rigging.scanner.wrap_assembly import assemble_wrap_rig, disassemble_wrap_rig

    if arm.bt_scan.has_wrap_rig:
        disassemble_wrap_rig(arm)

    scan_data = _props_to_scan_data(arm)

    # Apply chain overrides from UI (same as operator)
    for chain_item in arm.bt_scan.chains:
        cid = chain_item.chain_id
        if cid in scan_data["chains"]:
            scan_data["chains"][cid]["module_type"] = chain_item.module_type
            scan_data["chains"][cid]["ik_enabled"] = chain_item.ik_enabled
            scan_data["chains"][cid]["fk_enabled"] = chain_item.fk_enabled
            scan_data["chains"][cid]["ik_type"] = chain_item.ik_type
            scan_data["chains"][cid]["ik_limits"] = chain_item.ik_limits
            for bone_name in scan_data["chains"][cid]["bones"]:
                if bone_name in scan_data["bones"]:
                    scan_data["bones"][bone_name]["module_type"] = chain_item.module_type

    created = assemble_wrap_rig(arm, scan_data)
    arm.bt_scan.has_wrap_rig = True

    # Reset runtime FK/IK state (all chains start in FK mode)
    for chain_item in arm.bt_scan.chains:
        chain_item.ik_active = False

    return {"success": True, "bones_created": len(created)}, None


def _rig_clear_wrap(body):
    arm_name = body.get("armature")
    arm, err = _get_object(arm_name, 'ARMATURE')
    if err:
        return None, err

    if not arm.bt_scan.has_wrap_rig:
        return None, "No wrap rig to clear"

    from ..rigging.scanner.wrap_assembly import disassemble_wrap_rig
    disassemble_wrap_rig(arm)
    arm.bt_scan.has_wrap_rig = False

    return {"success": True}, None


def _rig_toggle_fk_ik(body):
    arm_name = body.get("armature")
    arm, err = _get_object(arm_name, 'ARMATURE')
    if err:
        return None, err

    chain_id = body.get("chain_id")
    if not chain_id:
        return None, "Missing 'chain_id'"

    mode = body.get("mode", "TOGGLE").upper()
    if mode not in ("FK", "IK", "TOGGLE"):
        return None, f"Invalid mode: {mode}. Use FK, IK, or TOGGLE"

    from ..core.constants import WRAP_MCH_PREFIX
    sd = arm.bt_scan

    chain_item = None
    for ch in sd.chains:
        if ch.chain_id == chain_id:
            chain_item = ch
            break

    if not chain_item:
        return None, f"Chain '{chain_id}' not found"

    if mode == 'TOGGLE':
        use_ik = not chain_item.ik_active
    else:
        use_ik = (mode == 'IK')

    # Already in the requested mode — nothing to do
    if use_ik == chain_item.ik_active:
        mode_name = "IK" if use_ik else "FK"
        return {"success": True, "chain_id": chain_id, "mode": mode_name}, None

    # Temporarily disable IK limits during snap so solver can reproduce FK pose.
    # Save per-bone states so user customizations are preserved.
    saved_limit_states = {}
    if chain_item.ik_limits and use_ik:
        for bone_item in [b for b in sd.bones if b.chain_id == chain_id and not b.skip]:
            mch_name = f"{WRAP_MCH_PREFIX}{chain_id}_{bone_item.role}"
            mch_pb = arm.pose.bones.get(mch_name)
            if mch_pb:
                saved_limit_states[mch_name] = (
                    mch_pb.use_ik_limit_x, mch_pb.use_ik_limit_y, mch_pb.use_ik_limit_z,
                )
                mch_pb.use_ik_limit_x = False
                mch_pb.use_ik_limit_y = False
                mch_pb.use_ik_limit_z = False

    # Snap controls before switching so the pose is preserved
    if chain_item.ik_type == 'SPLINE':
        from ..rigging.scanner.wrap_assembly import snap_fk_to_ik, snap_spline_to_fk
        if use_ik:
            snap_spline_to_fk(arm, chain_id)
        else:
            snap_fk_to_ik(arm, chain_id)
    elif chain_item.ik_snap:
        from ..rigging.scanner.wrap_assembly import snap_fk_to_ik, snap_ik_to_fk
        if use_ik:
            snap_ik_to_fk(arm, chain_id)
        else:
            snap_fk_to_ik(arm, chain_id)

    # Auto-upgrade old rigs to custom-property + driver system
    from ..rigging.scanner.wrap_assembly import (
        _has_ik_switch,
        _ik_switch_prop_name,
        upgrade_ik_switch,
    )
    if not _has_ik_switch(arm, chain_id):
        upgrade_ik_switch(arm, chain_id)

    # Set the custom property — drivers handle all constraint toggling
    prop_name = _ik_switch_prop_name(chain_id)
    arm[prop_name] = 1.0 if use_ik else 0.0

    # Restore per-bone limit states (preserves user customizations)
    if saved_limit_states:
        import bpy
        bpy.context.view_layer.update()
        for mch_name, (lx, ly, lz) in saved_limit_states.items():
            mch_pb = arm.pose.bones.get(mch_name)
            if mch_pb:
                mch_pb.use_ik_limit_x = lx
                mch_pb.use_ik_limit_y = ly
                mch_pb.use_ik_limit_z = lz

    chain_item.ik_active = use_ik

    # Show/hide per-chain IK collection based on mode
    ik_coll = arm.data.collections.get(f"IK_{chain_id}")
    if ik_coll:
        ik_coll.is_visible = use_ik

    # Force depsgraph update so drivers propagate
    import bpy
    bpy.context.view_layer.update()

    mode_name = "IK" if use_ik else "FK"
    return {"success": True, "chain_id": chain_id, "mode": mode_name}, None


def _rig_bake_to_def(body):
    arm_name = body.get("armature")
    arm, err = _get_object(arm_name, 'ARMATURE')
    if err:
        return None, err

    if not arm.bt_scan.has_wrap_rig:
        return None, "No wrap rig to bake"

    frame_start = body.get("frame_start")
    frame_end = body.get("frame_end")

    from ..rigging.scanner.wrap_assembly import bake_to_def
    stats = bake_to_def(arm, frame_start, frame_end)

    return {"success": True, **stats}, None


def _rig_floor_contact(body):
    arm_name = body.get("armature")
    arm, err = _get_object(arm_name, 'ARMATURE')
    if err:
        return None, err

    if not arm.bt_scan.has_wrap_rig:
        return None, "No wrap rig found"

    action = body.get("action", "toggle")  # toggle, enable, disable

    if action == "disable" or (action == "toggle" and arm.bt_scan.floor_enabled):
        from ..rigging.scanner.floor_contact import remove_floor_contact
        remove_floor_contact(arm)
        arm.bt_scan.floor_enabled = False
        return {"success": True, "enabled": False}, None

    floor_level = body.get("floor_level", arm.bt_scan.floor_level)

    from ..rigging.scanner.floor_contact import setup_floor_contact
    result = setup_floor_contact(
        arm,
        floor_level=floor_level,
    )
    if "error" in result:
        return None, result["error"]

    arm.bt_scan.floor_enabled = True
    arm.bt_scan.floor_level = floor_level

    return {"success": True, "enabled": True, **result}, None


def _root_motion_setup(body):
    arm_name = body.get("armature")
    arm, err = _get_object(arm_name, 'ARMATURE')
    if err:
        return None, err

    from ..animation.root_motion import auto_detect, setup_root_motion
    rm = arm.bt_root_motion

    # Auto-detect if not configured
    if not rm.source_bone or len(rm.pinned_bones) == 0:
        result = auto_detect(arm)
        rm.root_bone = body.get("root_bone", result['root_bone']) or "root"
        rm.source_bone = body.get("source_bone", result['source_bone'])
        rm.pinned_bones.clear()
        for name in result['pinned_bones']:
            item = rm.pinned_bones.add()
            item.bone_name = name
    else:
        if body.get("root_bone"):
            rm.root_bone = body["root_bone"]
        if body.get("source_bone"):
            rm.source_bone = body["source_bone"]

    if not rm.root_bone:
        rm.root_bone = "root"

    rm.extract_xy = body.get("extract_xy", True)
    rm.extract_z_rot = body.get("extract_z_rot", True)
    rm.extract_z = body.get("extract_z", False)

    stats = setup_root_motion(arm)
    return {"success": True, **stats,
            "anim_type": rm.anim_type,
            "extract_xy": rm.extract_xy,
            "extract_z_rot": rm.extract_z_rot,
            "extract_z": rm.extract_z}, None


def _root_motion_finalize(body):
    arm_name = body.get("armature")
    arm, err = _get_object(arm_name, 'ARMATURE')
    if err:
        return None, err
    if not arm.bt_root_motion.is_setup:
        return None, "Root motion not set up"

    from ..animation.root_motion import finalize_root_motion
    stats = finalize_root_motion(arm)
    return {"success": True, **stats}, None


def _root_motion_cancel(body):
    arm_name = body.get("armature")
    arm, err = _get_object(arm_name, 'ARMATURE')
    if err:
        return None, err
    if not arm.bt_root_motion.is_setup:
        return None, "Root motion not set up"

    from ..animation.root_motion import cancel_root_motion
    cancel_root_motion(arm)
    return {"success": True}, None


def _exec_code(body):
    code = body.get("code")
    if not code:
        return None, "Missing 'code' in body"

    # Basic safety check — no os, subprocess, sys, etc.
    for dangerous in ["import os", "import sys", "import subprocess",
                       "__import__", "eval(", "exec(", "open(",
                       "shutil", "pathlib"]:
        if dangerous in code:
            return None, f"Blocked: '{dangerous}' not allowed in exec"

    namespace = {"bpy": bpy}
    try:
        exec(code, namespace)
        result = namespace.get("result", "OK")
        return {"success": True, "result": str(result)}, None
    except Exception as e:
        return None, f"Exec error: {e}"
