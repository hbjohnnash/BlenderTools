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

Pin controllers (IK targets, spine FK) to baked reference empties, freeing the root bone for motion extraction. Source bone's XY translation + Z rotation extracted to root.

- **Source bone** — COG/hips/torso. Auto-detected from lowest spine FK or name heuristic
- **Root bone** — Receives locomotion data. For wrap rigs, uses CTRL wrap bone. Created at origin if missing
- **Pinned bones** — All controllers holding world-space position. Each gets reference empty + COPY_TRANSFORMS back

Workflow: Auto-detect > Setup > (polish root curves) > Finalize (bakes + cleanup) or Cancel.

Options: `extract_xy` (default true), `extract_z_rot` (default true).

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

IK bones never keyed directly. Per-bone behavior:
- **IK bone + IK mode**: snap FK from IK, key FK rotations for chain
- **FK bone**: key rotation
- **COG/root**: key location + rotation
- **Non-wrap bones**: key rotation + location if unlocked
- **IK bone + FK mode**: skipped

Fallback (no wrap rig): all selected keyed with rotation + location. Operator: `bt.smart_keyframe`

## AI Motion Generation

Model selection is automatic: humanoid skeletons (spine+arm+leg chains) use MotionLCM; exotic topologies use AnyTop. User can override via Model enum (AUTO/MOTIONLCM/ANYTOP).

### MotionLCM (humanoid text-to-motion, ECCV 2024)
1-step latent consistency model on SMPL 22 joints (~30ms). Outputs HumanML3D 263-dim features, recovered to rotations via position-based IK. Retargeted to user armature via influence map. See `docs/motionlcm_flow.md` for full pipeline.

### AnyTop (any-topology text-to-motion, SIGGRAPH 2025)
Any skeleton topology. Extracts topology from armature, sends to model, outputs 6D joint rotations, converts to Euler via Gram-Schmidt, applies as keyframes. HF: `inbar2344/AnyTop`.

### SinMDM (style transfer)
Tasks: style transfer, inbetween, expand. Single-motion diffusion, MIT license, generic BVH input.

Operators: `bt.init_anim_ai`, `bt.remove_anim_ai`, `bt.ai_generate_motion`, `bt.ai_style_transfer`, `bt.ai_inbetween`

Models cached at `~/.blendertools/models/<model_id>/`.

## Animation Data Flow

Uses `create_fcurve` helper (in `core/utils.py`) for Blender 5.0 channelbag API: Action > Slot > Channelbag > FCurve > Keyframes. Reading: `action.layers[].strips[].channelbags[].fcurves`.

Channel groups: `assign_channel_groups(armature_obj)` after `nla.bake` (auto-called by root motion and bake-to-DEF).

## Bridge API

```bash
mechanical --object X --type piston_cycle|gear_rotation|conveyor
root-motion-setup --armature X
root-motion-finalize --armature X
root-motion-cancel --armature X
```
