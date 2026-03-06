# BlenderTools — Overview

## What is BlenderTools?

A comprehensive Blender 5.0+ addon for seam creation, modular rigging, skinning, animation generation, and LLM bridge integration. You model; BlenderTools handles everything after.

## Installation

1. Open Blender 5.0.1+
2. Edit > Preferences > Extensions > Install from Disk
3. Select the `BlenderTools.zip` file
4. Enable "BlenderTools" in the extensions list

## UI Location

All panels are in the 3D Viewport sidebar (press `N`) under the **BlenderTools** tab.

### Panel Sections:
- **Seams** — UV seam creation tools
- **Rigging** — Modular rig builder + Skeleton Scanner + Viewport Module Overlay
- **Skinning** — Weight painting tools
- **Animation** — Procedural generators + root motion extraction
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
4. Click "Scan Skeleton" — bones are auto-detected
5. Review/edit chain assignments in the panel (configure FK/IK/Snap per chain)
6. Click "Apply Wrap Rig" — three-tier rig (CTRL/MCH/DEF) wraps original bones with FK/IK controls

### Skin:
1. Select both mesh and armature
2. Open BlenderTools > Skinning
3. Click "Auto Weight" (Heat Map method)

### Animate:
1. Select the armature
2. Open BlenderTools > Animation
3. Click "Generate Walk Cycle"

### Floor contact (IK legs):
1. Apply a wrap rig with leg chains in IK mode
2. Open Rigging > Skeleton Scanner > Floor Contact section
3. Set floor level, enable toe auto-bend if desired
4. Click "Floor Contact" to toggle on — feet won't go below the floor

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

## Blender 5.0 Compatibility

This addon uses Blender 5.0 APIs exclusively:
- Channelbag API for animation (no legacy `action.fcurves`)
- `mesh.attributes["sharp_edge"]` for hard edge detection
- `gpu` module for viewport capture and module overlay (no legacy BGL)
- `blender_manifest.toml` extension format
