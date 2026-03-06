# Animation

## Procedural Generators

### Walk Cycle
Generates sine-wave based locomotion with hip bounce, leg stride, and arm swing.

**Parameters:**
- `Speed` (0.1-5.0) — Animation speed multiplier
- `Stride` (0.1-2.0) — Step length
- `Arm Swing` (0.0-1.0) — Arm rotation amplitude
- `Frame Count` (8-120) — Cycle duration

### Run Cycle
Faster walk with aerial phase. Same parameters, higher defaults.

### Idle
Subtle body sway animation for standing poses.

### Breathing
Chest scale + shoulder rise animation.

**Parameters:**
- `Breaths/Min` (5-40) — Breathing rate
- `Depth` (0.005-0.1) — Breath intensity

### Mechanical
Three types of mechanical animation:
- **Piston** — Linear stroke cycle
- **Gear** — Continuous rotation with ratio
- **Conveyor** — Repeating linear offset

## Path & Camera

### Follow Path
Attach any object to follow a curve path.
1. Select object + curve
2. Set duration and banking
3. Object follows curve over specified frames

### Orbit Camera
Creates a new camera that orbits around the 3D cursor.
- Automatically creates a target empty
- Track-To constraint for look-at

### Camera Shake
Adds procedural noise-based shake to a camera.
- Intensity and frequency controls
- Seed for reproducible results

### Focus Pull
Animate depth of field focus distance (requires DOF enabled).

## Cycle & NLA

### Match Cycle Start/End
Sets the last keyframe of each FCurve to match the first — essential for seamless loops.

### Push to NLA
Converts the active action into an NLA strip with optional repeat count.

## Root Motion Extraction

One-click workflow for extracting root motion from animations, based on the reference-object pinning method.

**Concept:** Pin key controllers (IK targets, spine FK) to baked reference empties, freeing the root bone for motion extraction. After animating root movement, finalize bakes controllers with visual keying and cleans up.

**Key concepts:**
- **Pinned bones** — All controllers that must hold their world-space position when the root moves. Each gets a reference empty baked to its current motion, then a COPY_TRANSFORMS constraint back to that empty. Typically IK targets (hands/feet) + the COG/torso. The source bone is always included.
- **Source bone** — One of the pinned bones (the COG/hips/torso) whose XY translation and Z rotation are additionally extracted to the root bone. This defines the character's travel path. Auto-detected from the lowest spine FK controller or by name heuristic (Hips, pelvis, mixamorig:Hips, etc.)
- **Root bone** — The bone that receives the extracted locomotion data. Created at origin if missing, with all top-level bones reparented to it.

**Workflow:**
1. Select armature with animation
2. Open Animation > Root Motion panel
3. Auto-detect (or manually configure) source bone, root bone, and pinned bones
4. Click **Setup** — creates reference empties, pins controllers, creates/reparents root bone
5. Optionally polish root curves in the Graph Editor
6. Click **Finalize** — bakes all controllers, removes empties and constraints
7. Or click **Cancel** to restore the original state

**Operators:**
- `bt.rm_auto_detect` — Auto-detect source/root/pinned bones from scan data or heuristics
- `bt.rm_add_selected` / `bt.rm_remove_bone` — Manually manage pinned bone list
- `bt.rm_setup` — Create empties + pin controllers
- `bt.rm_finalize` — Bake controllers with visual keying + cleanup
- `bt.rm_cancel` — Undo setup, restore original state

**Options:**
- `extract_xy` — Extract XY translation to root (default: true)
- `extract_z_rot` — Extract Z rotation (yaw) to root (default: true)

## Animation Data Flow

All procedural generators output pure math data (bone name -> keyframe list). The `create_fcurve` helper in `core/utils.py` handles Blender 5.0's channelbag API:

1. Get/create Action
2. Get/create Slot for the object
3. Ensure Channelbag for the slot
4. Create FCurve in the channelbag
5. Insert keyframe points

## Bridge API

```bash
python blender_api.py animate --armature Rig --type walk --params '{"speed":1.5}'
python blender_api.py mechanical --object Piston --type piston_cycle

# Root motion extraction
python blender_api.py root-motion-setup --armature Armature
python blender_api.py root-motion-finalize --armature Armature
python blender_api.py root-motion-cancel --armature Armature
```
