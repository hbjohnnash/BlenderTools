# Seams

## Methods

### Seams by Angle
Marks edges as seams where the dihedral angle between adjacent faces exceeds a threshold.

**When to use:** General-purpose, good first pass for any model.

**Parameters:**
- `Angle Threshold` (0-180°, default 30°) — Lower = more seams
- `Clear Existing` — Remove existing seams first

### Seams by Material
Marks edges where adjacent faces have different material assignments.

**When to use:** Models with distinct material regions (skin vs clothing, metal vs rubber).

### Seams by Hard Edge
Marks seams at sharp/hard edges using Blender 5.0's `sharp_edge` attribute.

**When to use:** Hard-surface models where you've already marked sharp edges for shading.

### Island-Aware Seams
Iterative algorithm that starts with angle-based seams and adds more at high-distortion edges.

**When to use:** When you need control over UV island count and stretch.

**Parameters:**
- `Max Islands` (0 = unlimited) — Cap on island count
- `Max Stretch` (0-1) — Target distortion threshold

### Seams by Projection
Marks seams based on projection mapping directions.

**When to use:** Simple shapes that map well to box/cylinder/sphere projections.

**Modes:**
- `BOX` — Seams where face normals change dominant axis
- `CYLINDER` — Seams at cap transitions + one vertical cut
- `SPHERE` — Single longitude cut

### Seam Presets
Apply a predefined combination of seam methods.

**Built-in presets:**
- `character_body` — Angle (60°) + Material + Hard Edge
- `hard_surface` — Hard Edge + Angle (35°) + Material
- `organic` — Island-Aware + Material

### Clear All Seams
Removes all seams from the active mesh.

## Bridge API

```bash
python blender_api.py seam --object Cube --threshold 30
python blender_api.py seam --object Cube --preset hard_surface
```
