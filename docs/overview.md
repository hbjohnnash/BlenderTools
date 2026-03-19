# BlenderTools — Overview

Comprehensive Blender 5.0+ addon for seam creation, modular rigging, skinning, animation tools, AI-powered workflows, and LLM bridge integration. You model; BlenderTools handles everything after.

**GitHub:** https://github.com/hbjohnnash/BlenderTools

## Installation

Edit > Preferences > Extensions > Install from Disk > select `BlenderTools.zip` > enable "BlenderTools".

## UI Location

3D Viewport sidebar (`N` key) > **BlenderTools** tab:
- **Header** — Subsystem toggles + unified Overlay controls
- **Seams** — UV seam tools + AI neural seams (MeshCNN)
- **Rigging** — Modular builder + Scanner + CoM/Balance + Control Shapes
- **Skinning** — Weight painting tools
- **Animation** — Mechanical, root motion, trajectory, onion skin, Smart Keyframe, AI motion (MotionLCM, AnyTop, SinMDM)
- **Export** — Rig scaling & UE FBX export
- **LLM Bridge** — HTTP server for Claude Code

## Architecture

Three-tier: **CTRL -> MCH -> DEF**. DEF = COPY_TRANSFORMS from MCH. MCH = rig logic. CTRL = user controls. Applies to all 13 modules and wrap rig.

## Quick Start Workflows

**Seam a mesh:** Select mesh > Seams > "Seams by Angle" (default 30) > unwrap.

**Modular rig (overlay):** Select armature > Rigging > click bone circles > pick modules > "Generate Rig".

**Modular rig (config):** Select armature > "Load Rig Config" > pick preset > "Generate Rig".

**Wrap imported skeleton:** Import FBX > select armature > Scanner > (optional) "Name Bones" > "Scan Skeleton" > review chains > "Apply Wrap Rig" > use FK/IK overlay.

**Skin:** Select mesh + armature > Skinning > "Auto Weight" (Heat Map).

**Floor contact:** Wrap rig with IK legs > Rigging > Floor Contact > set level > enable.

**CoM + Balance:** Pose mode > Rigging > "Show CoM" > crosshair + balance bar.

**Bone trajectory:** Pose mode > select bones > enable Trajectory overlay > drag dots to edit.

**Onion skin:** Pose mode > enable Onion Skin > configure ghost count/step/opacity.

**Smart keyframe:** Select bones in Pose mode > press I.

**Root motion:** Select armature > Animation > Root Motion > Auto Detect > Setup > Finalize.

**Export to UE:** Scale rig (factor 100) > "Export to UE".

**AI seams:** Seams > "Initialize AI Seams" > "Neural Seams".

**AI motion:** Animation > "Initialize AI Motion" > select armature > "Generate Motion" + text prompt.

**Claude Code bridge:** "Start Bridge" > `python blender_api.py ping`.

## Development

```bash
pip install -r requirements-dev.txt
ruff check .                    # lint
pytest                          # unit tests (no Blender needed)
blender-launcher --background --python tests/smoke_test_blender.py
```

CI (GitHub Actions): lint+test > smoke-test > build > release (GitHub Release + extension index on GitHub Pages).

## Blender 5.0 APIs

Channelbag API for animation, `mesh.attributes["sharp_edge"]`, `gpu` module (no legacy BGL), `blender_manifest.toml` extension format.
