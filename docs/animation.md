# Animation

## Mechanical Animation

- **Piston** — Linear stroke cycle along bone axis
- **Gear** — Continuous rotation with configurable ratio
- **Conveyor** — Repeating linear offset

## Path & Camera

- **Follow Path** — Attach object to curve, set duration/banking
- **Orbit Camera** — Creates camera orbiting 3D cursor with Track-To
- **Camera Shake** — Procedural noise (intensity, frequency, seed)
- **Focus Pull** — Animate DOF focus distance

## Cycle & NLA

- **Match Cycle Start/End** — Last keyframe matches first for seamless loops
- **Push to NLA** — Active action to NLA strip with optional repeat count

## Root Motion Extraction

Pin controllers (IK targets, spine FK) to baked reference empties, freeing the root bone for motion extraction. Non-destructive: original action is preserved; root motion is baked into a `_root_motion` copy.

- **Source bone** — COG/hips/torso. Auto-detected from lowest spine FK or name heuristic
- **Root bone** — Receives locomotion data. For wrap rigs, uses CTRL wrap bone. Created at origin if missing (`use_deform=True` for UE FBX export)
- **Pinned bones** — Controllers holding world-space position. Filtered to only bones with keyframes in the action

Workflow: Auto-detect > Setup > (polish root curves) > Finalize (bakes + cleanup) or Cancel (restores original action).

**Auto-detection** analyzes the animation to classify motion type (locomotion/strafe/turning/in-place/jump) and auto-configures extraction options. Uses the action's frame range, not the scene range.

Options: `extract_xy` (default true), `extract_z_rot` (default true), `extract_z` (default false, for jumps/climbs).

## Bone Trajectory

Interactive 3D trajectory visualization and editing for any bone with keyframes.

Dot colors: **yellow** = directly editable (location keys), **cyan** = IK-assisted (FK bone with IK available), **gray** = read-only, **white** = current frame.

- Yellow dots: click-drag moves bone, FCurves update in real-time
- Cyan dots: temporary IK enabled, drag IK target, on release FK snaps + keys rotations

Operator: `bt.trajectory` (modal, ESC to exit)

## Onion Skinning

Ghost frames for armatures with child meshes. Past=blue, future=orange. GPU-batched, cache rebuilds on frame change.

**Proxy LOD**: Decimated proxies per child mesh, stored in hidden `BT_OnionSkin_Proxy` collection. Ratio 0.05-1.0.

**Keyframes Only**: Ghosts at keyframe positions instead of fixed intervals.

Settings: `bt_onion_before/after` (3), `bt_onion_step` (1), `bt_onion_opacity` (0.25), `bt_onion_use_keyframes`, `bt_onion_proxy_ratio` (0.25).

Operators: `bt.onion_skin` (toggle), `bt.onion_skin_refresh` (rebuild proxies/cache)

## Smart Keyframe (I key override)

IK bones never keyed directly. In addition to bone channels, Smart Keyframe keys the chain's `ik_switch_{chain_id}` custom property with **CONSTANT interpolation**, locking the FK/IK state to the frame. After keying, any pending muted fcurves (from toggle or paste) are unmuted.

Per-bone behavior:
- **IK bone + IK mode**: snap FK from IK, key FK rotations for chain, key `ik_switch` = 1.0 (CONSTANT)
- **FK bone**: key rotation, key `ik_switch` = 0.0 (CONSTANT)
- **COG/root**: key location + rotation
- **Non-wrap bones**: key rotation + location if unlocked
- **IK bone + FK mode**: skipped

Fallback (no wrap rig): all selected keyed with rotation + location. Operator: `bt.smart_keyframe`

## Animation Data Flow

Uses `create_fcurve` helper (in `core/utils.py`) for Blender 5.0 channelbag API: Action > Slot > Channelbag > FCurve > Keyframes. Reading: `action.layers[].strips[].channelbags[].fcurves`.

Channel groups: `assign_channel_groups(armature_obj)` after `nla.bake` (auto-called by root motion and bake-to-DEF).

## Bridge API

```bash
mechanical --object X --type piston_cycle|gear_rotation|conveyor
root-motion-setup --armature X [--extract-z]
root-motion-finalize --armature X
root-motion-cancel --armature X
```
