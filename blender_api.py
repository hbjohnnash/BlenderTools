#!/usr/bin/env python3
"""External CLI for BlenderTools bridge — zero deps (urllib only).

Usage:
    python blender_api.py ping
    python blender_api.py scene-summary
    python blender_api.py screenshot [--width 960] [--height 540]
    python blender_api.py object-info --name Cube
    python blender_api.py seam --object Cube --method angle --threshold 30
    python blender_api.py seam --object Cube --preset hard_surface
    python blender_api.py rig-add --armature Armature --module arm --side L
    python blender_api.py rig-generate --armature Armature
    python blender_api.py rig-load --armature Armature --config biped_human.json
    python blender_api.py skin --mesh Body --armature Armature [--method heat_map]
    python blender_api.py rigid-bind --mesh Body --armature Armature
    python blender_api.py animate --armature Armature --type walk [--params '{"speed":1.0}']
    python blender_api.py mechanical --object Piston --type piston_cycle
    python blender_api.py exec --code "bpy.ops.mesh.primitive_cube_add()"
    python blender_api.py scale-rig --armature Armature --factor 100.0
    python blender_api.py export-ue --armature Armature [--mesh Body] [--output ./export] [--no-mesh] [--no-anim] [--separate-anim] [--no-ue-naming]
    python blender_api.py rig-scan --armature Armature
    python blender_api.py rig-apply-wrap --armature Armature
    python blender_api.py rig-clear-wrap --armature Armature
    python blender_api.py rig-toggle-fk-ik --armature Armature --chain leg_L --mode IK
"""

import argparse
import json
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_PORT = 19785
BASE = "/blendertools"


def _url(endpoint, port=DEFAULT_PORT):
    return f"http://127.0.0.1:{port}{BASE}/{endpoint}"


def _get_json(endpoint, params=None, port=DEFAULT_PORT):
    """Send GET request, return parsed JSON."""
    url = _url(endpoint, port)
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"success": False, "error": f"HTTP {e.code}: {body}"}
    except urllib.error.URLError as e:
        return {"success": False, "error": f"Connection failed: {e.reason}"}


def _post_json(endpoint, data, port=DEFAULT_PORT):
    """Send POST request with JSON body, return parsed JSON."""
    url = _url(endpoint, port)
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"success": False, "error": f"HTTP {e.code}: {body}"}
    except urllib.error.URLError as e:
        return {"success": False, "error": f"Connection failed: {e.reason}"}


def _print_result(result):
    """Pretty-print JSON result."""
    print(json.dumps(result, indent=2))


def cmd_ping(args):
    _print_result(_get_json("ping", port=args.port))


def cmd_scene_summary(args):
    _print_result(_get_json("scene-summary", port=args.port))


def cmd_screenshot(args):
    params = {}
    if args.width:
        params["width"] = args.width
    if args.height:
        params["height"] = args.height
    result = _get_json("screenshot", params, port=args.port)
    if isinstance(result, list):
        result = result[0]
    if result.get("success") and result.get("data"):
        # Save to file if --output specified
        if args.output:
            import base64
            with open(args.output, "wb") as f:
                f.write(base64.b64decode(result["data"]))
            print(f"Screenshot saved to {args.output}")
        else:
            # Print summary without the huge base64 data
            result["data"] = f"<base64 PNG, {len(result['data'])} chars>"
            _print_result(result)
    else:
        _print_result(result)


def cmd_object_info(args):
    _print_result(_get_json("object-info", {"name": args.name}, port=args.port))


def cmd_seam(args):
    if args.preset:
        data = {"object": args.object, "preset": args.preset}
        _print_result(_post_json("seam/preset", data, port=args.port))
    else:
        data = {"object": args.object, "threshold": args.threshold}
        _print_result(_post_json("seam/by-angle", data, port=args.port))


def cmd_rig_add(args):
    data = {
        "armature": args.armature,
        "module_type": args.module,
        "config": {
            "name": args.name or args.module.title(),
            "side": args.side,
            "position": json.loads(args.position) if args.position else [0, 0, 0],
            "options": json.loads(args.options) if args.options else {},
        },
    }
    _print_result(_post_json("rig/add-module", data, port=args.port))


def cmd_rig_generate(args):
    _print_result(_post_json("rig/generate", {"armature": args.armature}, port=args.port))


def cmd_rig_load(args):
    config_path = args.config
    with open(config_path) as f:
        config = json.load(f)
    data = {"armature": args.armature, "config": config}
    _print_result(_post_json("rig/load-config", data, port=args.port))


def cmd_skin(args):
    data = {
        "mesh": args.mesh,
        "armature": args.armature,
        "method": args.method.upper(),
    }
    _print_result(_post_json("skin/auto-weight", data, port=args.port))


def cmd_rigid_bind(args):
    data = {"mesh": args.mesh, "armature": args.armature}
    _print_result(_post_json("skin/rigid-bind", data, port=args.port))


def cmd_animate(args):
    data = {
        "armature": args.armature,
        "type": args.type,
        "params": json.loads(args.params) if args.params else {},
    }
    _print_result(_post_json("anim/procedural", data, port=args.port))


def cmd_mechanical(args):
    data = {
        "object": args.object,
        "type": args.type,
        "params": json.loads(args.params) if args.params else {},
    }
    _print_result(_post_json("anim/mechanical", data, port=args.port))


def cmd_exec(args):
    _print_result(_post_json("exec", {"code": args.code}, port=args.port))


def cmd_scale_rig(args):
    data = {"armature": args.armature, "factor": args.factor}
    _print_result(_post_json("export/scale-rig", data, port=args.port))


def cmd_export_ue(args):
    data = {
        "armature": args.armature,
        "export_mesh": not args.no_mesh,
        "export_anim": not args.no_anim,
        "separate_anim": args.separate_anim,
        "ue_naming": not args.no_ue_naming,
    }
    if args.mesh:
        data["meshes"] = args.mesh
    if args.output:
        data["output"] = args.output
    _print_result(_post_json("export/to-ue", data, port=args.port))


def cmd_rig_scan(args):
    _print_result(_post_json("rig/scan-skeleton", {"armature": args.armature}, port=args.port))


def cmd_rig_apply_wrap(args):
    data = {"armature": args.armature}
    _print_result(_post_json("rig/apply-wrap", data, port=args.port))


def cmd_rig_clear_wrap(args):
    _print_result(_post_json("rig/clear-wrap", {"armature": args.armature}, port=args.port))


def cmd_rig_toggle_fk_ik(args):
    data = {
        "armature": args.armature,
        "chain_id": args.chain,
        "mode": args.mode.upper(),
    }
    _print_result(_post_json("rig/toggle-fk-ik", data, port=args.port))


def cmd_root_motion_setup(args):
    data = {"armature": args.armature}
    if args.root:
        data["root_bone"] = args.root
    if args.source:
        data["source_bone"] = args.source
    if args.no_xy:
        data["extract_xy"] = False
    if args.no_z_rot:
        data["extract_z_rot"] = False
    if args.extract_z:
        data["extract_z"] = True
    _print_result(_post_json("anim/root-motion-setup", data, port=args.port))


def cmd_root_motion_finalize(args):
    _print_result(_post_json("anim/root-motion-finalize",
                             {"armature": args.armature}, port=args.port))


def cmd_root_motion_cancel(args):
    _print_result(_post_json("anim/root-motion-cancel",
                             {"armature": args.armature}, port=args.port))


def cmd_floor_contact(args):
    data = {"armature": args.armature, "action": args.action}
    if args.level is not None:
        data["floor_level"] = args.level
    if args.no_toe_bend:
        data["toe_bend"] = False
    if args.toe_angle is not None:
        data["toe_angle_deg"] = args.toe_angle
    _print_result(_post_json("rig/floor-contact", data, port=args.port))


def main():
    parser = argparse.ArgumentParser(description="BlenderTools Bridge CLI")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Bridge port")
    sub = parser.add_subparsers(dest="command", required=True)

    # ping
    sub.add_parser("ping", help="Health check")

    # scene-summary
    sub.add_parser("scene-summary", help="Get scene summary")

    # screenshot
    p = sub.add_parser("screenshot", help="Capture viewport")
    p.add_argument("--width", type=int, default=960)
    p.add_argument("--height", type=int, default=540)
    p.add_argument("--output", "-o", help="Save PNG to file path")

    # object-info
    p = sub.add_parser("object-info", help="Get object details")
    p.add_argument("--name", required=True)

    # seam
    p = sub.add_parser("seam", help="Mark seams")
    p.add_argument("--object", required=True)
    p.add_argument("--method", default="angle")
    p.add_argument("--threshold", type=float, default=30.0)
    p.add_argument("--preset", help="Use a seam preset instead")

    # rig-add
    p = sub.add_parser("rig-add", help="Add rig module")
    p.add_argument("--armature", required=True)
    p.add_argument("--module", required=True)
    p.add_argument("--side", default="C")
    p.add_argument("--name", default="")
    p.add_argument("--position", default=None, help="JSON [x,y,z]")
    p.add_argument("--options", default=None, help="JSON options")

    # rig-generate
    p = sub.add_parser("rig-generate", help="Generate rig")
    p.add_argument("--armature", required=True)

    # rig-load
    p = sub.add_parser("rig-load", help="Load rig config from file")
    p.add_argument("--armature", required=True)
    p.add_argument("--config", required=True, help="Path to JSON config file")

    # skin
    p = sub.add_parser("skin", help="Auto-weight skinning")
    p.add_argument("--mesh", required=True)
    p.add_argument("--armature", required=True)
    p.add_argument("--method", default="heat_map")

    # rigid-bind
    p = sub.add_parser("rigid-bind", help="Rigid bind skinning")
    p.add_argument("--mesh", required=True)
    p.add_argument("--armature", required=True)

    # animate
    p = sub.add_parser("animate", help="Generate procedural animation")
    p.add_argument("--armature", required=True)
    p.add_argument("--type", required=True, help="walk/run/idle/breathing")
    p.add_argument("--params", default=None, help="JSON params")

    # mechanical
    p = sub.add_parser("mechanical", help="Generate mechanical animation")
    p.add_argument("--object", required=True)
    p.add_argument("--type", required=True, help="piston_cycle/gear_rotation/conveyor")
    p.add_argument("--params", default=None, help="JSON params")

    # exec
    p = sub.add_parser("exec", help="Execute Python code in Blender")
    p.add_argument("--code", required=True)

    # scale-rig
    p = sub.add_parser("scale-rig", help="Scale rig and update keyframes/constraints")
    p.add_argument("--armature", required=True)
    p.add_argument("--factor", type=float, required=True, help="Scale multiplier")

    # export-ue
    p = sub.add_parser("export-ue", help="Export armature+meshes as UE-ready FBX")
    p.add_argument("--armature", required=True)
    p.add_argument("--mesh", action="append", help="Mesh name (repeatable, default: all children)")
    p.add_argument("--output", default=None, help="Output directory")
    p.add_argument("--no-mesh", action="store_true", help="Skip mesh export")
    p.add_argument("--no-anim", action="store_true", help="Skip animation export")
    p.add_argument("--separate-anim", action="store_true", help="Each action as separate FBX")
    p.add_argument("--no-ue-naming", action="store_true", help="Disable SK_/A_ prefixes")

    # rig-scan
    p = sub.add_parser("rig-scan", help="Scan armature and detect bone roles")
    p.add_argument("--armature", required=True)

    # rig-apply-wrap
    p = sub.add_parser("rig-apply-wrap", help="Apply wrap control rig to scanned armature")
    p.add_argument("--armature", required=True)

    # rig-clear-wrap
    p = sub.add_parser("rig-clear-wrap", help="Remove wrap rig (keep original bones)")
    p.add_argument("--armature", required=True)

    # rig-toggle-fk-ik
    p = sub.add_parser("rig-toggle-fk-ik", help="Toggle FK/IK mode on arm/leg chain")
    p.add_argument("--armature", required=True)
    p.add_argument("--chain", required=True, help="Chain ID (e.g. arm_L, leg_R)")
    p.add_argument("--mode", required=True, choices=["FK", "IK", "TOGGLE", "fk", "ik", "toggle"],
                    help="FK, IK, or TOGGLE")

    # floor-contact
    p = sub.add_parser("floor-contact", help="Toggle floor contact on leg IK targets")
    p.add_argument("--armature", required=True)
    p.add_argument("--action", choices=["toggle", "enable", "disable"], default="toggle")
    p.add_argument("--level", type=float, help="Floor Z level (default 0)")
    p.add_argument("--no-toe-bend", action="store_true", help="Disable auto toe bend")
    p.add_argument("--toe-angle", type=float, help="Max toe bend angle in degrees")

    # root-motion-setup
    p = sub.add_parser("root-motion-setup", help="Setup root motion extraction")
    p.add_argument("--armature", required=True)
    p.add_argument("--root", help="Root bone name (default: auto-detect or 'root')")
    p.add_argument("--source", help="Source bone for locomotion (default: auto-detect)")
    p.add_argument("--no-xy", action="store_true", help="Skip XY translation extraction")
    p.add_argument("--no-z-rot", action="store_true", help="Skip Z rotation extraction")
    p.add_argument("--extract-z", action="store_true",
                   help="Extract Z height to root (for jumps/climbs)")

    # root-motion-finalize
    p = sub.add_parser("root-motion-finalize", help="Finalize root motion (bake controllers)")
    p.add_argument("--armature", required=True)

    # root-motion-cancel
    p = sub.add_parser("root-motion-cancel", help="Cancel root motion setup")
    p.add_argument("--armature", required=True)

    args = parser.parse_args()

    cmd_map = {
        "ping": cmd_ping,
        "scene-summary": cmd_scene_summary,
        "screenshot": cmd_screenshot,
        "object-info": cmd_object_info,
        "seam": cmd_seam,
        "rig-add": cmd_rig_add,
        "rig-generate": cmd_rig_generate,
        "rig-load": cmd_rig_load,
        "skin": cmd_skin,
        "rigid-bind": cmd_rigid_bind,
        "animate": cmd_animate,
        "mechanical": cmd_mechanical,
        "exec": cmd_exec,
        "scale-rig": cmd_scale_rig,
        "export-ue": cmd_export_ue,
        "rig-scan": cmd_rig_scan,
        "rig-apply-wrap": cmd_rig_apply_wrap,
        "rig-clear-wrap": cmd_rig_clear_wrap,
        "rig-toggle-fk-ik": cmd_rig_toggle_fk_ik,
        "floor-contact": cmd_floor_contact,
        "root-motion-setup": cmd_root_motion_setup,
        "root-motion-finalize": cmd_root_motion_finalize,
        "root-motion-cancel": cmd_root_motion_cancel,
    }

    cmd_map[args.command](args)


if __name__ == "__main__":
    main()
