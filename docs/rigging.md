# Rigging

## Architecture

**Three-tier: CTRL -> MCH -> DEF** (all 13 modules).
- **DEF** — `COPY_TRANSFORMS` from MCH, `use_deform=True`
- **MCH** — All rig logic (FK copy, IK, DAMPED_TRACK, STRETCH_TO), `use_deform=False`
- **CTRL** — User controls, `use_deform=False`

Constraint prefixes: `BT_Spine_`, `BT_Arm_`, `BT_Leg_`, `BT_Piston_`, `BT_Wheel_`, etc.

## Workflows

### Viewport Module Overlay
Select armature > white circles on bone heads/tails > click to pick module > "Generate Rig". Modules with bone slots (piston, wheel) offer "Map Existing Bones" for assignment mode.

### Click-to-Place
Position 3D cursor > "Add Rig Module" > choose type/name/side > "Generate Rig".

### Config File
"Load Rig Config" > choose preset (biped_human, quadruped, mech_walker) > "Generate Rig".

### Skeleton Scanner (Wrap Existing Bones)
For imported skeletons (Mixamo, UE Mannequin, etc.):
1. (Optional) **"Name Bones"** — interactive BT convention overlay
2. **"Scan Skeleton"** — auto-detects via BT convention (Step 0), name maps, or heuristics
3. Review/edit chains in panel
4. **"Apply Wrap Rig"** — FK/IK controls wrap original bones (never renamed/deleted)

Supported: BT Convention (100%), Mixamo (~55 entries), UE Mannequin (~55 entries), Unknown (heuristics).

## Bone Naming

Format: `BT_{TypeCamel}_{Side}_{Role}` — parsed via `split('_', 3)`.

Chain numbering for multiple same-type chains:
- **Indexed types** (finger, tail, tentacle, generic): `{chain}_{bone}` always (e.g. `BT_Finger_R_1_01`)
- **Named-role types**: chain number only when > 1 (e.g. `BT_Arm_L_upper_arm` vs `BT_Arm_L_2_upper_arm`)

Generated wrap bones: `CTRL-Wrap_{chain}_{mode}_{role}`, `MCH-Wrap_{chain}_{role}`. Constraints prefixed `BT_Wrap_`.

## Wrap Rig Details

- **DEF** (originals): `COPY_TRANSFORMS` from MCH (influence=1.0, never toggled)
- **MCH**: `COPY_TRANSFORMS` from CTRL-FK (LOCAL space, toggled for FK) + `IK` constraint (toggled for IK)
- **CTRL**: FK controls + IK target/pole bones

FK/IK switching happens on MCH layer. MCH->CTRL-FK uses LOCAL space so child chains inherit world-space movement from MCH parent in IK mode.

**Cross-chain hierarchy:** Processed in dependency order (root > spine > neck/head > arm/leg > finger > generic). First CTRL in each chain auto-parents to nearest ancestor CTRL.

**FK location locks:** FK bones locked to rotation-only. COG (first spine/root FK) keeps location unlocked.

## Bone Slot Mapping

For piston/wheel: "Map Existing Bones" > click bones to fill slots > assigned bones get `COPY_TRANSFORMS` from MCH. Module skips DEF creation, uses existing bones instead.

## IK Controls

**Standard IK** (arm/leg/wing): target + pole. Sizes proportional (30% of lower bone). IK influence starts at 0.0 (FK mode). Dynamic `chain_count` from actual bone span.

**Spline IK** (tail/tentacle default): Bezier curve + 3-5 hook bones. `SPLINE_IK` on last MCH bone. Control point count: 3 for <=4 bones, 4 for <=8, 5 for 9+.

**IK Rotation Limits:** Uses Blender's `ik_min_x`/`ik_max_x`/`ik_stiffness_x` (evaluated inside IK solver). Per-module defaults:
- Arm/Leg mid-joints: single-axis, 0-160deg, auto-detected bend axis
- Arm/Leg root/end: +/-120deg all axes
- Tail: +/-45deg, stiffness 0.1
- Tentacle: +/-60deg, stiffness 0.05
- Generic: +/-90deg

### FK/IK Toggle

MCH layer switching: FK mode = COPY_TRANSFORMS on, IK off. IK mode = reverse. Bones outside IK chain_count keep FK active.

When `ik_snap` enabled (Standard IK, 2-bone chains): IK->FK snaps FK to IK pose. FK->IK snaps target to chain end + recalibrates pole. Spline snapping always enabled.

### Build Config vs Runtime

- `fk_enabled`/`ik_enabled` — whether controls are generated (build-time)
- `ik_type` — `STANDARD` or `SPLINE` (build-time)
- `ik_snap` — per-chain, clamps chain_count to 2 (build-time). Standard IK only
- `ik_limits` — joint rotation limits, toggleable at runtime
- `ik_active` — current mode (runtime, starts FK)

**IK bone visibility:** Per-chain bone collections (`IK_arm_L`, etc.), hidden in FK, shown in IK.

**Pole angle calibration:** Depsgraph-based — set 0, let IK solve, measure twist, apply correction.

## Module Types

### Organic
| Module | Description | Key Options |
|--------|-------------|-------------|
| `spine` | FK chain + optional IK spline | `bone_count`, `ik_spline` |
| `arm` | IK/FK with clavicle | `twist_bones`, `clavicle` |
| `leg` | IK/FK with foot roll | `twist_bones`, `foot_roll` |
| `neck_head` | Neck chain + head | `neck_bones` |
| `tail` | FK chain + optional IK tip | `bone_count`, `ik_tip`, `direction` |
| `wing` | Multi-segment + feathers | `segments`, `feather_bones` |
| `tentacle` | Long chain with taper | `bone_count`, `taper` |
| `finger_chain` | Individual finger | `bone_count`, `finger_name` |
| `jaw` | Hinge + optional upper | `upper_jaw` |
| `eye` | Aim-based + eyelids | `eyelids`, `target_distance` |
| `custom_chain` | Generic FK/IK | `bone_count`, `ik`, `direction` |

### Mechanical
| Module | Description | Bone Slots |
|--------|-------------|------------|
| `piston` | DAMPED_TRACK (default) or STRETCH_TO. `stretch_mode`: none/cylinder/rod/both | Cylinder, Rod, Rod_Parent |
| `wheel` | Rotation-based + axle | Wheel, Axle |

## Naming Convention

`{prefix}{ModuleName}_{side}_{part}` — e.g. `DEF-Arm_L_Upper`, `CTRL-Arm_L_FK_Upper`, `MCH-Leg_L_HeelPivot`.

## Bone Collections

- **DEF** — deform, hidden when wrap rig built
- **CTRL** — FK controls (blue/THEME06)
- **IK_{chain_id}** — per-chain IK bones (green/THEME04), hidden in FK
- **MCH** — mechanism (hidden, purple/THEME09)

## Control Shapes

Procedural shapes in hidden `BT_Shapes` collection. Sizing via `custom_shape_scale_xyz`.

Built-in: circle, cube, diamond, sphere, arrow, square, line. Auto-assigned: FK=circle, IK target=cube, IK pole=diamond, spline hook=sphere.

## Floor Contact

IK legs only. `LIMIT_LOCATION` on IK targets (min Z = floor level). Optional `TRANSFORM` on toes for auto-bend. Properties on `bt_scan`: `floor_enabled`, `floor_level`, `floor_toe_bend`, `floor_toe_angle`.

## Center of Mass + Balance

- **CoM**: Weighted bone position average. Per-bone mass from mesh vertex weights, user-overridable
- **BoS**: Convex hull from foot/hand contact bones (scan data > name fallback > Z-position fallback)
- **Balance**: Stability ratio, green (>50%) > yellow > red (0%)

## Connection Points

`Spine.hip/chest/mid`, `Arm.hand/shoulder/clavicle`, `Leg.hip/foot/toe`, `NeckHead.neck_base/head`. Use in `parent_bone`.

## Operators

`bt.scan_skeleton`, `bt.apply_wrap_rig`, `bt.clear_wrap_rig`, `bt.clear_scan_data`, `bt.toggle_fk_ik`, `bt.toggle_ik_limits`, `bt.edit_bone_ik_limits`, `bt.bake_to_def`, `bt.bone_naming_overlay`, `bt.auto_name_chain`, `bt.set_bone_label`, `bt.ik_overlay`, `bt.toggle_com`, `bt.recalc_com_masses`, `bt.toggle_floor_contact`, `bt.update_floor_level`, `bt.batch_skip_selected`, `bt.batch_skip_pattern`, `bt.batch_unskip_all`, `bt.assign_bone_shape`, `bt.resize_ctrl_bones`, `bt.clear_bone_shapes`, `bt.add_custom_shape`, `bt.smart_keyframe`

## Bridge API

```bash
rig-add --armature X --module arm --side L
rig-generate --armature X
rig-load --armature X --config path/to/biped.json
rig-scan --armature X
rig-apply-wrap --armature X
rig-clear-wrap --armature X
rig-toggle-fk-ik --armature X --chain leg_L --mode IK|FK|TOGGLE
rig-bake-to-def --armature X
floor-contact --armature X --action enable|disable|toggle --level 0
```
