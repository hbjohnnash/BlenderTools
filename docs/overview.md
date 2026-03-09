# BlenderTools — Overview

## What is BlenderTools?

A comprehensive Blender 5.0+ addon for seam creation, modular rigging, skinning, animation tools, AI-powered workflows, and LLM bridge integration. You model; BlenderTools handles everything after.

**GitHub:** https://github.com/hbjohnnash/BlenderTools

## Installation

1. Open Blender 5.0.1+
2. Edit > Preferences > Extensions > Install from Disk
3. Select the `BlenderTools.zip` file
4. Enable "BlenderTools" in the extensions list

## UI Location

All panels are in the 3D Viewport sidebar (press `N`) under the **BlenderTools** tab.

### Panel Sections:
- **BlenderTools (Header)** — Subsystem toggles + unified Overlay controls (Module, FK/IK, CoM, Trajectory, Onion Skin)
- **Seams** — UV seam creation tools + AI neural seam prediction (MeshCNN)
- **Rigging** — Modular rig builder + Skeleton Scanner + Center of Mass / Balance + Control Shapes
- **Skinning** — Weight painting tools
- **Animation** — Mechanical animation, path/camera, root motion, trajectory editing, onion skinning, Smart Keyframe (I key override) + AI motion generation (AnyTop, SinMDM)
- **Export** — Rig scaling & UE FBX export
- **LLM Bridge** — HTTP server for Claude Code integration

## Architecture

All 13 rig modules use a universal **three-tier architecture: CTRL -> MCH -> DEF**. DEF bones only carry COPY_TRANSFORMS from MCH. MCH bones carry all rig logic. CTRL bones are user controls. This applies to both the modular rig builder and the skeleton scanner wrap rig.

## Quick Start

### Seam a mesh:
1. Select a mesh object
2. Open BlenderTools > Seams
3. Click "Seams by Angle" (30 default works for most models)
4. Unwrap with Blender's built-in UV unwrap

### Rig a character (viewport overlay):
1. Add an Armature object
2. Open BlenderTools > Rigging
3. Use the viewport overlay — white circles appear on bone heads/tails
4. Click a circle to open the module picker, choose a module type
5. For mechanical modules (piston, wheel), choose "Map Existing Bones" to assign slots to existing skeleton bones
6. Repeat for all body parts
7. Click "Generate Rig"

### Rig a character (config file):
1. Add an Armature object
2. Open BlenderTools > Rigging
3. Click "Load Rig Config" > choose "biped_human"
4. Click "Generate Rig"

### Wrap an imported skeleton (Mixamo, UE Mannequin, etc.):
1. Import your character (FBX)
2. Select the armature
3. Open BlenderTools > Rigging > Skeleton Scanner
4. (Optional) Click **"Name Bones"** to label bones with BT convention via interactive overlay
5. (Optional) Click **"Auto-Name Chain"** to auto-name child bones after naming the root
6. Click **"Scan Skeleton"** — bones are auto-detected
7. Review/edit chain assignments in the panel (configure FK/IK/Snap per chain)
8. Click **"Apply Wrap Rig"** — three-tier rig wraps original bones with FK/IK controls
9. Use the **FK/IK Overlay** at the bottom of the viewport to toggle chains

### Skin:
1. Select both mesh and armature
2. Open BlenderTools > Skinning
3. Click "Auto Weight" (Heat Map method)

### Floor contact (IK legs):
1. Apply a wrap rig with leg chains in IK mode
2. Open Rigging > Skeleton Scanner > Floor Contact section
3. Set floor level, enable toe auto-bend if desired
4. Click "Floor Contact" to toggle on — feet won't go below the floor

### Center of Mass + Balance:
1. Select armature in Pose mode
2. Open Rigging > Center of Mass (or use header Overlays toggle)
3. Click "Show CoM" — crosshair shows center of mass, colored by balance
4. Base of Support polygon from foot/hand contact bones
5. Balance indicator bar (green = stable, yellow = marginal, red = unstable)
6. Edit per-bone masses by pinning individual bones

### Bone Trajectory (Cascadeur-style):
1. Select armature in Pose mode
2. Select any bones (works for all bone types, not just location-keyed)
3. Enable Trajectory overlay (header panel or Animation > Trajectory)
4. Bone positions at keyframes appear as dots connected by a curve
5. Three dot colors: yellow = editable (location-keyed), cyan = IK-assisted (FK bones that can be dragged via IK), gray = read-only
6. Click + drag any yellow or cyan dot to edit position at that frame
7. IK-assisted drag: FK bones use temporary IK to translate drag into rotation
8. FCurve values update in real-time during drag

### Onion Skinning / Ghost Frames:
1. Select armature in Pose mode
2. Enable Onion Skin (header panel or Animation > Onion Skin)
3. Past frames shown in blue, future frames in orange (semi-transparent meshes)
4. Configure ghost count (before/after), frame step, and opacity
5. Keyframes Only mode — show ghosts only at keyframed frames instead of fixed step
6. Ghost Detail — proxy LOD setting to reduce mesh complexity for performance
7. Camera-independent — works in any viewport angle

### Smart Keyframe (I key):
1. Select bones in Pose mode
2. Press I — smart keyframe insertion
3. FK bones are keyed with rotation
4. IK bones are never keyed — FK snaps from IK automatically
5. COG/root bones get location + rotation keyed

### Extract root motion:
1. Select armature with animation
2. Open Animation > Root Motion
3. Click "Auto Detect" or manually configure source/root/pinned bones
4. Click "Setup" — controllers are pinned to reference empties
5. Animate the root bone, then click "Finalize" to bake

### Bake animation to DEF bones (before export):
1. Select the armature with a wrap rig
2. Open BlenderTools > Export > "Bake to DEF"
3. Bakes the current animation onto DEF bones for clean FBX export

### Export to Unreal Engine:
1. Select the armature
2. Open BlenderTools > Export > UE Export
3. Click "Export to UE" — set output directory and options
4. Files export with SK_/A_ naming, scaled for correct UE import

### Scale a rig mid-project:
1. Select the armature
2. Open BlenderTools > Export > Scale Rig
3. Click "Scale Rig", enter factor (e.g. 2.0)
4. Keyframes, constraints, child meshes, and config all update

### Use with Claude Code:
1. Click "Start Bridge" in the LLM Bridge panel
2. From terminal: `python blender_api.py ping`

### AI Seam Prediction:
1. Open BlenderTools > Seams > AI Seams
2. Click "Initialize AI Seams" — downloads PyTorch + MeshCNN (~300MB one-time)
3. Select a mesh, click "Neural Seams"
4. MeshCNN segments mesh into body parts; boundaries become seams

### AI Motion Generation:
1. Open BlenderTools > Animation > AI Motion
2. Click "Initialize AI Motion" — downloads PyTorch + AnyTop + SinMDM
3. Select armature, click "Generate Motion", enter text prompt (e.g. "a person walking")
4. AnyTop generates motion for any skeleton topology

### AI Style Transfer:
1. Initialize AI Motion (above)
2. Select armature with existing animation
3. Click "Style Transfer" — SinMDM learns from the motion and generates variations

## Development

### Testing
```bash
pip install -r requirements-dev.txt
ruff check .                    # lint
pytest                          # 46 unit tests (no Blender needed)
blender-launcher --background --python tests/smoke_test_blender.py  # real Blender check
```

### CI/CD
Every push to `main` triggers GitHub Actions (`.github/workflows/ci.yml`):
1. **lint-and-test** — ruff + pytest
2. **smoke-test** — installs addon in Blender headless, verifies registration
3. **build** — packages `BlenderTools.zip`, downloadable from Actions artifacts

## Blender 5.0 Compatibility

This addon uses Blender 5.0 APIs exclusively:
- Channelbag API for animation (no legacy `action.fcurves`)
- `mesh.attributes["sharp_edge"]` for hard edge detection
- `gpu` module for viewport capture and module overlay (no legacy BGL)
- `blender_manifest.toml` extension format
