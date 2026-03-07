# LLM Bridge

## Overview

The LLM Bridge is an HTTP server running inside Blender that allows external tools (like Claude Code) to query scene state and execute operations.

## Starting the Server

### From Blender UI:
BlenderTools tab > LLM Bridge > "Start Bridge"

### Auto-start:
Edit > Preferences > Add-ons > BlenderTools > Enable "Auto-Start Bridge"

## Port

Default: **19785** (continues the 1978x convention from UE tools)

Configurable in addon preferences.

## External CLI

```bash
# Install: no dependencies needed (uses urllib only)
python blender_api.py <command> [options]
```

## Endpoints

### GET Endpoints

| Endpoint | Description |
|----------|-------------|
| `/blendertools/ping` | Health check |
| `/blendertools/scene-summary` | Compact scene JSON |
| `/blendertools/object-info?name=X` | Detailed object info |
| `/blendertools/screenshot` | Viewport capture (base64 PNG) |

### POST Endpoints

| Endpoint | Body | Description |
|----------|------|-------------|
| `/blendertools/seam/by-angle` | `{"object":"X","threshold":30}` | Mark seams by angle |
| `/blendertools/seam/preset` | `{"object":"X","preset":"hard_surface"}` | Apply seam preset |
| `/blendertools/rig/add-module` | `{"armature":"X","module_type":"arm","config":{...}}` | Add rig module |
| `/blendertools/rig/generate` | `{"armature":"X"}` | Generate rig |
| `/blendertools/rig/load-config` | `{"armature":"X","config":{...}}` | Load full config |
| `/blendertools/rig/scan-skeleton` | `{"armature":"X"}` | Scan skeleton, detect bone roles |
| `/blendertools/rig/apply-wrap` | `{"armature":"X"}` | Apply wrap rig from scan data (applies chain module_type overrides, resets ik_active to FK) |
| `/blendertools/rig/clear-wrap` | `{"armature":"X"}` | Remove wrap rig |
| `/blendertools/rig/toggle-fk-ik` | `{"armature":"X","chain_id":"leg_L","mode":"IK"}` | Toggle FK/IK mode on any IK-capable chain (with snap if enabled) |
| `/blendertools/rig/bake-to-def` | `{"armature":"X"}` | Bake animation onto DEF bones for export |
| `/blendertools/rig/floor-contact` | `{"armature":"X","action":"toggle"}` | Toggle floor constraints on leg IK targets |
| `/blendertools/skin/auto-weight` | `{"mesh":"X","armature":"Y","method":"heat_map"}` | Auto weight |
| `/blendertools/skin/rigid-bind` | `{"mesh":"X","armature":"Y"}` | Rigid bind |
| `/blendertools/anim/mechanical` | `{"object":"X","type":"piston_cycle","params":{}}` | Mechanical anim |
| `/blendertools/export/scale-rig` | `{"armature":"X","factor":100.0}` | Scale rig + keyframes |
| `/blendertools/anim/root-motion-setup` | `{"armature":"X"}` | Setup root motion extraction |
| `/blendertools/anim/root-motion-finalize` | `{"armature":"X"}` | Finalize root motion (bake + cleanup) |
| `/blendertools/anim/root-motion-cancel` | `{"armature":"X"}` | Cancel root motion setup |
| `/blendertools/export/to-ue` | `{"armature":"X","output":"./export","export_mesh":true,"export_anim":true}` | UE FBX export |
| `/blendertools/exec` | `{"code":"bpy.ops..."}` | Execute Python |

## Thread Safety

All Blender operations are dispatched to the main thread via `bpy.app.timers.register()`. The HTTP thread blocks until the main thread completes the operation (30s timeout).

## Response Format

All responses are JSON:
```json
{"success": true, ...}
{"success": false, "error": "description"}
```

## Scene Summary Format

The scene summary is designed to be token-efficient for LLM consumption:
- Object name, type, location
- Mesh: vertex/face count, materials, vertex groups
- Armature: bone count, module count
- Camera: lens, clip range
- Light: type, energy

## CLI Examples

```bash
# Check connection
python blender_api.py ping

# Get scene overview
python blender_api.py scene-summary

# Save viewport screenshot
python blender_api.py screenshot -o viewport.png

# Full rigging workflow
python blender_api.py rig-load --armature Armature --config presets/rig_configs/biped_human.json
python blender_api.py rig-generate --armature Armature
python blender_api.py skin --mesh Body --armature Armature

# Scale rig and export to UE
python blender_api.py scale-rig --armature Armature --factor 100.0
python blender_api.py export-ue --armature Armature --output ./export
python blender_api.py export-ue --armature Armature --no-mesh --separate-anim

# Skeleton scanner — wrap imported skeleton with controls
python blender_api.py rig-scan --armature Armature
python blender_api.py rig-apply-wrap --armature Armature
python blender_api.py rig-clear-wrap --armature Armature

# FK/IK toggle on any chain with IK constraints (snaps pose if ik_snap enabled)
python blender_api.py rig-toggle-fk-ik --armature Armature --chain leg_L --mode IK
python blender_api.py rig-toggle-fk-ik --armature Armature --chain arm_R --mode TOGGLE
python blender_api.py rig-toggle-fk-ik --armature Armature --chain tail_C --mode TOGGLE

# Bake animation to DEF bones before export
python blender_api.py rig-bake-to-def --armature Armature

# Floor contact on leg IK targets
python blender_api.py floor-contact --armature Armature --action enable --level 0
python blender_api.py floor-contact --armature Armature --action disable

# Root motion extraction
python blender_api.py root-motion-setup --armature Armature --root root --source hips
python blender_api.py root-motion-finalize --armature Armature
python blender_api.py root-motion-cancel --armature Armature
```
