# LLM Bridge

HTTP server inside Blender for external tool integration (Claude Code, etc.).

## Setup

- **UI:** BlenderTools tab > LLM Bridge > "Start Bridge"
- **Auto-start:** Edit > Preferences > Add-ons > BlenderTools > "Auto-Start Bridge"
- **Port:** 19785 (configurable in preferences)
- **CLI:** `python blender_api.py <command> [options]` (no dependencies, uses urllib)

## GET Endpoints

| Endpoint | Description |
|----------|-------------|
| `/blendertools/ping` | Health check |
| `/blendertools/scene-summary` | Compact scene JSON |
| `/blendertools/object-info?name=X` | Detailed object info |
| `/blendertools/screenshot` | Viewport capture (base64 PNG) |

## POST Endpoints

| Endpoint | Body | Description |
|----------|------|-------------|
| `/blendertools/seam/by-angle` | `{"object":"X","threshold":30}` | Seams by angle |
| `/blendertools/seam/preset` | `{"object":"X","preset":"hard_surface"}` | Seam preset |
| `/blendertools/rig/add-module` | `{"armature":"X","module_type":"arm","config":{...}}` | Add rig module |
| `/blendertools/rig/generate` | `{"armature":"X"}` | Generate rig |
| `/blendertools/rig/load-config` | `{"armature":"X","config":{...}}` | Load full config |
| `/blendertools/rig/scan-skeleton` | `{"armature":"X"}` | Scan skeleton |
| `/blendertools/rig/apply-wrap` | `{"armature":"X"}` | Apply wrap rig |
| `/blendertools/rig/clear-wrap` | `{"armature":"X"}` | Remove wrap rig |
| `/blendertools/rig/toggle-fk-ik` | `{"armature":"X","chain_id":"leg_L","mode":"IK"}` | Toggle FK/IK |
| `/blendertools/rig/bake-to-def` | `{"armature":"X"}` | Bake animation to DEF |
| `/blendertools/rig/floor-contact` | `{"armature":"X","action":"toggle"}` | Floor constraints |
| `/blendertools/skin/auto-weight` | `{"mesh":"X","armature":"Y","method":"heat_map"}` | Auto weight |
| `/blendertools/skin/rigid-bind` | `{"mesh":"X","armature":"Y"}` | Rigid bind |
| `/blendertools/anim/mechanical` | `{"object":"X","type":"piston_cycle","params":{}}` | Mechanical anim |
| `/blendertools/anim/root-motion-setup` | `{"armature":"X"}` | Root motion setup |
| `/blendertools/anim/root-motion-finalize` | `{"armature":"X"}` | Root motion finalize |
| `/blendertools/anim/root-motion-cancel` | `{"armature":"X"}` | Root motion cancel |
| `/blendertools/export/scale-rig` | `{"armature":"X","factor":100.0}` | Scale rig |
| `/blendertools/export/to-ue` | `{"armature":"X","output":"./export"}` | UE FBX export |
| `/blendertools/exec` | `{"code":"bpy.ops..."}` | Execute Python |

## Thread Safety

Operations dispatched to main thread via `bpy.app.timers.register()`. HTTP thread blocks until completion (30s timeout).

## Response Format

All JSON: `{"success": true, ...}` or `{"success": false, "error": "..."}`.

Scene summary is token-efficient: object name/type/location, mesh vertex/face counts, armature bone/module counts, camera/light details.
