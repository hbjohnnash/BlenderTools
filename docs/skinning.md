# Skinning

## Methods

### Auto Weight
Wraps Blender's built-in automatic weighting with pre/post processing.

**Methods:**
- **Heat Map** (default) — Diffusion-based, best for organic meshes
- **Envelope** — Bone envelope proximity, good for simple shapes
- **Hybrid** — Heat map with envelope blending

**Post-processing automatically applied:**
- Remove weights below 0.01
- Limit to 4 influences per vertex
- Normalize all weights

### Rigid Bind
Assigns each vertex 100% weight to the nearest deform bone segment. No blending.

**When to use:** Mechanical/hard-surface models where each face belongs entirely to one bone (robot limbs, armor plates, vehicle parts).

## Cleanup Tools

### Weight Cleanup
- **Threshold** — Remove weights below this value (default 0.01)
- **Max Influences** — Limit vertex groups per vertex (default 4)
- Automatically normalizes after cleanup

### Merge Vertex Groups
Combine two vertex groups into one (adds weights, removes source).

### Mirror Vertex Groups
Creates mirrored vertex groups based on L/R naming convention.

## Workflow

1. **Organic character:**
   - Select mesh + armature
   - Auto Weight (Heat Map)
   - Test deformation in Pose mode
   - Weight Cleanup if needed

2. **Mechanical model:**
   - Select mesh + armature
   - Rigid Bind
   - Verify each part moves with correct bone

3. **Mixed (organic + armor):**
   - Auto Weight the body mesh
   - Rigid Bind the armor pieces
   - Cleanup weights on body

## Bridge API

```bash
python blender_api.py skin --mesh Body --armature Armature --method heat_map
python blender_api.py rigid-bind --mesh ArmorPlate --armature Armature
```
