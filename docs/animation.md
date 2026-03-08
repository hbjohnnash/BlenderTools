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
- **Root bone** — The bone that receives the extracted locomotion data. For wrap rigs, auto-detect selects the CTRL wrap bone (e.g. `CTRL-Wrap_generic_C_FK_1_01`), not the original/DEF bone, to avoid constraint conflicts with the wrap rig. Created at origin if missing, with all top-level bones reparented to it.

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

Interactive 3D visualization and editing of bone trajectories. Inspired by Cascadeur's trajectory system.

**How it works:**
- Works for **all bone types** — any bone with keyframes (rotation, location, scale) gets a trajectory
- Evaluates selected bone's world-space position at each keyframe and intermediate frames
- Draws a smooth curve through the positions (past=blue, future=green)
- Non-keyframe positions shown as small gray dots

**Dot colors:**
- **Yellow** — directly editable (bone has location keyframes with unlocked location)
- **Cyan** — IK-assisted editing available (FK bone whose chain has IK enabled)
- **Dim gray** — read-only (rotation/scale-only keyframes, no editing path)
- **White** — current frame marker

**Editing — direct (yellow dots):**
- Click a yellow keyframe dot to grab it, drag to move
- World-space delta is inverse-transformed to bone-local location using the bone's location-space matrix (accounts for parent chain + rest pose)
- FCurve values update in real-time during drag

**Editing — IK-assisted (cyan dots):**
1. Click a cyan dot on an FK bone
2. System snaps the IK target/pole to match the current FK pose
3. IK constraints are temporarily enabled on the chain
4. Drag the IK target — the FK chain follows via the IK solver in real-time
5. On mouse release: FK bones are snapped to match the IK-solved pose, FK rotations are keyed at that frame, and constraints are restored to their original state

**Header hint** updates dynamically based on available edit modes (direct drag, IK-assisted, or view-only).

**Operators:** `bt.trajectory` (modal toggle, ESC to exit or cancel drag)

## Onion Skinning

Camera-independent ghost frame display for armatures with child meshes.

**How it works:**
- Evaluates child meshes at past/future frames via depsgraph
- Caches GPU batches in world space — drawing is just `batch.draw()` (very fast)
- Past ghosts: blue tint with decreasing opacity
- Future ghosts: orange tint with decreasing opacity
- Cache rebuilds only on frame change (survives viewport rotation)

**Proxy LOD system:**
- On activation, decimated proxy meshes are created for each child mesh to speed up per-frame ghost evaluation
- Uses a Decimate modifier (COLLAPSE mode) to bake low-poly geometry, then replaces it with an Armature modifier so the proxy deforms with the rig
- Vertex groups are preserved through decimation so skinning remains correct
- Proxy ratio controls detail level: lower values = faster evaluation, `1.0` = full quality (no proxies created)
- Proxies are stored in a hidden `BT_OnionSkin_Proxy` collection and destroyed when onion skin is disabled

**Keyframes Only mode:**
- When `bt_onion_use_keyframes` is enabled, ghosts appear at actual keyframe positions instead of fixed frame intervals
- Selects the nearest N keyframes before/after the current frame (respecting `bt_onion_before`/`bt_onion_after` counts)
- Keyframes are collected from all FCurves in the armature's action

**Settings (Scene properties):**
- `bt_onion_before` — Ghost count before current frame (default 3)
- `bt_onion_after` — Ghost count after current frame (default 3)
- `bt_onion_step` — Frame interval between ghosts (default 1)
- `bt_onion_opacity` — Base opacity (default 0.25)
- `bt_onion_use_keyframes` — Show ghosts at keyframes instead of fixed intervals (default false)
- `bt_onion_proxy_ratio` — Proxy mesh detail level, 0.05–1.0 (default 0.25, `FACTOR` subtype)

**Operators:**
- `bt.onion_skin` — Toggle onion skinning on/off (creates/destroys proxy meshes)
- `bt.onion_skin_refresh` — Force rebuild proxy meshes and recache ghost frames

## Smart Keyframe

Intelligent keyframe insertion for wrap rigs. Overrides the **I** key in Pose mode.

**Core rule:** IK bones are never keyed directly. Instead, FK rotations are always the keyed data — ensuring clean curves and predictable playback.

**Per-bone behavior:**
- **IK bone selected** (target, pole, or spline hook) + chain is in IK mode: snaps FK bones to match the current IK-solved pose, then keys FK rotations for the entire chain
- **FK bone selected**: keys rotation (respects the bone's rotation mode — euler, quaternion, or axis-angle)
- **COG / root bone** (has unlocked location channels): keys location + rotation
- **Non-wrap bones** (original skeleton, custom bones): keys rotation, plus location if any location channel is unlocked
- **IK bone selected but chain is in FK mode**: skipped with an info message

**Fallback:** If no wrap rig is detected on the armature, all selected bones are keyed with rotation + location (when unlocked) — standard Blender behavior.

**Operator:** `bt.smart_keyframe`

## Animation Data Flow

All animation output uses the `create_fcurve` helper in `core/utils.py` which handles Blender 5.0's channelbag API:

1. Get/create Action
2. Get/create Slot for the object (`slots.new(name=obj.name, id_type='OBJECT')`)
3. Ensure Channelbag for the slot (`action_ensure_channelbag_for_slot(action, slot)`)
4. Create FCurve in the channelbag
5. Insert keyframe points

When reading FCurves (e.g. trajectory, onion skin keyframe detection), the access path is `action.layers[].strips[].channelbags[].fcurves` — not `slot.channelbags`.

**Channel groups:** After `nla.bake`, FCurves are ungrouped by default. Call `assign_channel_groups(armature_obj)` (from `core/utils.py`) to assign each FCurve to a bone-named channel group via `channelbag.groups`. This is done automatically by root motion setup/finalize and bake-to-DEF.

## Bridge API

```bash
python blender_api.py mechanical --object Piston --type piston_cycle

# Root motion extraction
python blender_api.py root-motion-setup --armature Armature
python blender_api.py root-motion-finalize --armature Armature
python blender_api.py root-motion-cancel --armature Armature
```
