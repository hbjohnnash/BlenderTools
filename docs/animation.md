# Animation

## Mechanical Animation

Three types of mechanical animation for rigged mechanical parts:
- **Piston** — Linear stroke cycle along the bone's axis
- **Gear** — Continuous rotation with configurable ratio
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

## Bone Trajectory

Interactive 3D visualization and editing of bone location keyframes. Inspired by Cascadeur's trajectory system.

**How it works:**
- Evaluates selected bone's world-space position at each keyframe and intermediate frames
- Draws a smooth curve through the positions (past=blue, future=green)
- Keyframe positions shown as yellow draggable dots, current frame as white
- Non-keyframe positions shown as small gray dots

**Editing:**
- Click a keyframe dot to grab it, drag to move
- World-space delta is inverse-transformed to bone-local location using the bone's location-space matrix (accounts for parent chain + rest pose)
- FCurve values update in real-time during drag
- Location channels only — no rotation editing, no new keyframes created

**Operators:** `bt.trajectory` (modal toggle, ESC to exit)

## Onion Skinning

Camera-independent ghost frame display for armatures with child meshes.

**How it works:**
- Evaluates child meshes at past/future frames via depsgraph
- Caches GPU batches in world space — drawing is just `batch.draw()` (very fast)
- Past ghosts: blue tint with decreasing opacity
- Future ghosts: orange tint with decreasing opacity
- Cache rebuilds only on frame change (survives viewport rotation)

**Settings (Scene properties):**
- `bt_onion_before` — Ghost count before current frame (default 3)
- `bt_onion_after` — Ghost count after current frame (default 3)
- `bt_onion_step` — Frame interval between ghosts (default 1)
- `bt_onion_opacity` — Base opacity (default 0.25)

**Operators:** `bt.onion_skin` (toggle), `bt.onion_skin_refresh` (force recache)

## Animation Data Flow

All animation output uses the `create_fcurve` helper in `core/utils.py` which handles Blender 5.0's channelbag API:

1. Get/create Action
2. Get/create Slot for the object (`slots.new(name=obj.name, id_type='OBJECT')`)
3. Ensure Channelbag for the slot
4. Create FCurve in the channelbag
5. Insert keyframe points

## Bridge API

```bash
python blender_api.py mechanical --object Piston --type piston_cycle

# Root motion extraction
python blender_api.py root-motion-setup --armature Armature
python blender_api.py root-motion-finalize --armature Armature
python blender_api.py root-motion-cancel --armature Armature
```
