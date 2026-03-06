# Rigging

## Concept

BlenderTools uses a **modular rigging system**. Each body part is a self-contained module that creates its own bones, constraints, and controls. Modules are assembled into a complete rig.

**All 13 modules use a universal three-tier architecture: CTRL -> MCH -> DEF.**

- **DEF bones** (deform): Only carry `COPY_TRANSFORMS` from their paired MCH bone. Never carry rig logic. `use_deform=True`.
- **MCH bones** (mechanism): Carry all rig logic (FK copy, IK, DAMPED_TRACK, STRETCH_TO, etc.). Parented to their CTRLs. `use_deform=False`.
- **CTRL bones** (controls): User-facing control bones for animation. `use_deform=False`.

Each module uses its own constraint prefix: `BT_Spine_`, `BT_Arm_`, `BT_Leg_`, `BT_Piston_`, `BT_Wheel_`, etc.

## Four Workflows

### Viewport Module Overlay (Interactive Placement)
1. Select an armature
2. Open BlenderTools > Rigging
3. The viewport overlay shows white circles on bone heads and tails (alpha 0.3 default, 0.9 + thick white outline on hover)
4. Click a circle to open the module picker menu
5. Choose a module type — it is placed at that bone position
6. Modules with bone slots (piston, wheel) show two menu entries: "Add" and "Map Existing Bones"
7. Repeat for all body parts, then "Generate Rig"

The overlay is hidden in pose mode.

### Click-to-Place
1. Select an armature
2. Position the 3D cursor where you want the module
3. Click "Add Rig Module"
4. Choose module type, name, and side
5. Repeat for all body parts
6. Click "Generate Rig"

### Config File
1. Select an armature
2. Click "Load Rig Config"
3. Choose a preset (biped_human, quadruped, mech_walker)
4. Click "Generate Rig"

### Skeleton Scanner (Wrap Existing Bones)
For imported skeletons (Mixamo, UE Mannequin, or any other source) that already have deform bones but no control rig:
1. Select the armature
2. Open Rigging > Skeleton Scanner
3. **(Optional)** Click **"Name Bones"** to label bones with the BT convention via interactive overlay
4. Click **"Scan Skeleton"** — auto-detects bone roles via BT convention (Step 0), name maps, then position heuristics
5. Review chains and bone assignments in the panel — edit module types, roles, or skip bones
6. Click **"Apply Wrap Rig"** — FK/IK controls are generated around original bones
7. Original bones are **never renamed or deleted**

Supported skeleton types:
- **BT Convention** — `BT_{TypeCamel}_{Side}_{Role}` parsing, 100% confidence, instant detection (Step 0)
- **Mixamo** (~55 bone map entries, auto-detected)
- **UE Mannequin** (~55 bone map entries, auto-detected)
- **Unknown** — falls back to position/hierarchy heuristics

### Bone Naming Convention
Bones can be named using the BT convention: `BT_{TypeCamel}_{Side}_{Role}`. CamelCase type names (no underscores) for unambiguous parsing via `name.split('_', 3)`.

Examples: `BT_Spine_C_hips`, `BT_Arm_L_upper_arm`, `BT_NeckHead_C_neck`, `BT_Leg_R_foot`

The **Name Bones overlay** (`bt.bone_naming_overlay`) provides an interactive viewport tool: hover over bones to see clickable circles (white=unlabeled, green=BT-named), click to open a dialog with Type/Side/Role dropdowns that renames the bone automatically.

Generated bone naming:
- `CTRL-Wrap_{chain}_{mode}_{role}` — Control bones (e.g. `CTRL-Wrap_arm_L_FK_upper_arm`)
- `MCH-Wrap_{chain}_{role}` — Mechanism/intermediate bones (e.g. `MCH-Wrap_arm_L_upper_arm`)

All constraints on original bones are prefixed `BT_Wrap_` for clean removal.

**Wrap Rig Three-Tier Details:**
- **DEF bones** (original skeleton): Have `COPY_TRANSFORMS` from their paired MCH bone (always influence=1.0, never toggled)
- **MCH bones** (intermediate layer): Have `COPY_TRANSFORMS` from CTRL-FK bone (LOCAL space, toggled for FK) + `IK` constraint (toggled for IK)
- **CTRL bones** (user-facing): FK controls that animators manipulate, plus IK target/pole bones

DEF bones always follow MCH. FK/IK switching happens entirely on the MCH layer. The MCH->CTRL-FK constraint uses LOCAL space so that child chains (e.g. fingers parented to hand MCH) correctly inherit world-space movement from their MCH parent when the parent chain is in IK mode.

**Cross-chain hierarchy:** Chains are processed in dependency order (root -> spine -> neck/head -> arm/leg -> finger -> generic). The first CTRL bone in each chain is automatically parented to the nearest ancestor's CTRL from a previously processed chain. Example: arm FK clavicle CTRL parents to spine chest CTRL, finger CTRLs parent to arm hand CTRL.

## Bone Slot Mapping

Modules with bone slots (piston, wheel) support mapping to existing bones rather than creating new DEF bones. This is accessed via the viewport overlay's "Map Existing Bones" menu entry.

**Assignment mode workflow:**
1. Click "Map Existing Bones" in the overlay menu
2. Header text appears in the viewport showing which slot to fill
3. Click bones to assign them sequentially to each slot
4. Assigned bones turn green
5. RMB to skip a slot, Enter to confirm early, ESC to cancel

**What happens when mapping existing bones:**
- Module creates MCH bones at mapped bone positions (parented to their CTRLs)
- Module creates CTRL bones (parented to mapped bone's skeleton parent)
- Module **skips creating DEF bones** — uses the existing bones instead
- Existing bones get `COPY_TRANSFORMS` from MCH (clean, non-destructive)

**Disassembly:** `disassemble_rig()` preserves wrap rig bones (`CTRL-Wrap_*`, `MCH-Wrap_*`) when removing modular rig components.

## IK Controls

**IK controls (any chain with IK):**
- `CTRL-Wrap_{chain}_IK_target` — IK target at hand/foot position
- `CTRL-Wrap_{chain}_IK_pole` — Pole vector at elbow/knee (calculated from limb geometry)
- IK bone sizes are proportional to the chain (30% of the lower bone's length)
- IK influence starts at 0.0 (FK mode) — user toggles to 1.0 for IK mode

**FK/IK Build Config vs. Runtime State:**
- `fk_enabled` / `ik_enabled` — Control whether FK/IK controls are **generated** during build. Build-time settings.
- `ik_snap` — Per-chain toggle (build-time). When enabled, supports FK/IK snapping and clamps `chain_count` to 2. Default ON for arms/legs.
- `ik_active` — Tracks which mode is **currently active** at runtime. All chains start in FK.

**FK/IK Toggle with Snapping:**
FK/IK switching works on **any chain** with IK constraints. The `bt.toggle_fk_ik` operator handles switching.

When `ik_snap` is enabled:
- **IK -> FK:** FK control bones snap to match the IK-solved pose before switching
- **FK -> IK:** IK target snaps to chain end, pole angle recalibrated to match FK pose
- Snapping only works for 2-bone IK chains (arms/legs)

When toggling (on MCH layer):
- **FK mode** — MCH COPY_TRANSFORMS influence=1.0, MCH IK influence=0.0
- **IK mode** — MCH COPY_TRANSFORMS influence=0.0, MCH IK influence=1.0

**IK control visibility:** IK target and pole bones are placed in per-chain bone collections (`IK_arm_L`, `IK_leg_R`, etc.) that start hidden. Toggling to IK shows the collection; toggling back hides it.

**Panel modes:**
- **Config mode (before wrap rig):** FK/IK/Snap checkboxes, bone mapping, batch skip, unmapped bones sections visible
- **Rig mode (after wrap rig):** FK/IK toggle buttons replace checkboxes. Toggle appears when any bone in an IK-capable chain is selected.

**Pole Angle Calibration:**
IK pole angles are automatically calibrated using a depsgraph-based approach: set `pole_angle=0`, let the IK solver run via depsgraph evaluation, measure the twist, apply correction. Works universally for any bone roll or orientation.

## Module Types

### Organic
| Module | Description | Key Options | Architecture |
|--------|-------------|-------------|--------------|
| `spine` | FK chain + optional IK spline | `bone_count`, `ik_spline` | CTRL -> MCH -> DEF |
| `arm` | IK/FK arm with clavicle | `twist_bones`, `clavicle` | CTRL -> MCH -> DEF |
| `leg` | IK/FK leg with foot roll | `twist_bones`, `foot_roll` | CTRL -> MCH -> DEF |
| `neck_head` | Neck chain + head | `neck_bones` | CTRL -> MCH -> DEF |
| `tail` | FK chain + optional IK tip | `bone_count`, `ik_tip`, `direction` | CTRL -> MCH -> DEF |
| `wing` | Multi-segment + feather bones | `segments`, `feather_bones` | CTRL -> MCH -> DEF |
| `tentacle` | Long chain with taper | `bone_count`, `taper` | CTRL -> MCH -> DEF |
| `finger_chain` | Individual finger | `bone_count`, `finger_name` | CTRL -> MCH -> DEF |
| `jaw` | Hinge jaw + optional upper | `upper_jaw` | CTRL -> MCH -> DEF |
| `eye` | Aim-based + eyelids | `eyelids`, `target_distance` | CTRL -> MCH -> DEF |
| `custom_chain` | Generic FK/IK chain | `bone_count`, `ik`, `direction` | CTRL -> MCH -> DEF |

### Mechanical
| Module | Description | Key Options | Bone Slots |
|--------|-------------|-------------|------------|
| `piston` | Linear piston with DAMPED_TRACK (rigid) or STRETCH_TO | `stroke_length`, `direction`, `stretch_mode` | Cylinder, Rod, Rod_Parent |
| `wheel` | Rotation-based wheel + axle | `radius` | Wheel, Axle |

### Piston Architecture
Default constraint is **DAMPED_TRACK** (rotation only, rigid). Configurable `stretch_mode`: `"none"` (default), `"cylinder"`, `"rod"`, or `"both"` (uses STRETCH_TO).
```
CTRL-Base (inherits cylinder's parent)
   +-- MCH-Cylinder --DAMPED_TRACK--> CTRL-Target
CTRL-Target (inherits rod_parent's parent)
   +-- MCH-Rod --DAMPED_TRACK--> CTRL-Base
DEF-Cylinder <-- COPY_TRANSFORMS <-- MCH-Cylinder
DEF-Rod      <-- COPY_TRANSFORMS <-- MCH-Rod
```
Works generically: same-parent (decorative), cross-joint (shock absorber), or free-standing. Bone slots: Cylinder (outer body), Rod (inner shaft), Rod_Parent (explicit parent for CTRL-Target).

### Wheel Architecture
```
CTRL-Position (inherits axle's parent)
   +-- CTRL-Rotation
   |      +-- MCH-Wheel (COPY_ROTATION from CTRL-Rotation)
   +-- MCH-Axle (COPY_LOCATION from CTRL-Position)
DEF-Axle  <-- COPY_TRANSFORMS <-- MCH-Axle
DEF-Wheel <-- COPY_TRANSFORMS <-- MCH-Wheel
```

## Naming Convention

All bones follow: `{prefix}{ModuleName}_{side}_{part}`

- `DEF-Arm_L_Upper` — Deform bone
- `CTRL-Arm_L_FK_Upper` — Control bone
- `MCH-Leg_L_HeelPivot` — Mechanism bone (hidden)

## Bone Collections

- **DEF** — Deform bones (for skinning, `use_deform=True`). Hidden when wrap rig is built, restored on clear.
- **CTRL** — FK control bones (visible, blue/THEME06, `use_deform=False`).
- **IK_{chain_id}** — Per-chain IK target/pole bones (green/THEME04, `use_deform=False`). Hidden in FK mode, shown in IK.
- **MCH** — Mechanism bones (hidden, purple/THEME09, `use_deform=False`).

The `hidden_collections` property tracks which collections were hidden during rig creation for proper restoration on clear.

## Connection Points

Modules expose named connection points for parenting:
- `Spine.hip`, `Spine.chest`, `Spine.mid`
- `Arm.hand`, `Arm.shoulder`, `Arm.clavicle`
- `Leg.hip`, `Leg.foot`, `Leg.toe`
- `NeckHead.neck_base`, `NeckHead.head`

Use dot notation in `parent_bone`: `"parent_bone": "Spine.chest"`

## Saving/Loading Configs

- "Save Rig Config" saves current modules to `presets/rig_configs/`
- "Load Rig Config" loads from the same directory
- Config is also stored on the armature as a custom property

## Batch Skip Tools

Three operators for quickly skipping/unskipping chains during scan review:
- `bt.batch_skip_selected` — Select bones, then Skip/Unskip Selected
- `bt.batch_skip_pattern` — Glob-based pattern matching (e.g. `Automatic*`, `*Piston*`)
- `bt.batch_unskip_all` — Quick reset, unskips all chains

## Floor Contact

When using IK legs, the floor contact system prevents feet from going below a configurable floor level and optionally auto-bends toes on ground contact.

**Components:**
- `LIMIT_LOCATION` constraint on each leg IK target (min Z = floor level, world space)
- `TRANSFORM` constraint on toe MCH/DEF bones — maps IK target Z to toe X rotation
- Toe bend influence toggled by FK/IK switch: active in IK, inactive in FK

**Properties (on `bt_scan`):**
- `floor_enabled` — Whether floor constraints are active
- `floor_level` — World-space Z for the floor plane
- `floor_toe_bend` — Enable auto toe bend
- `floor_toe_angle` — Maximum toe bend angle (radians, displayed as degrees)

## Operators

- `bt.scan_skeleton` — Analyze armature, populate scan data
- `bt.apply_wrap_rig` — Generate wrap controls from scan data
- `bt.clear_wrap_rig` — Remove only generated bones + constraints (restores hidden bone collections)
- `bt.clear_scan_data` — Clear wrap rig + all scan data
- `bt.toggle_fk_ik` — Switch any IK-capable chain between FK and IK mode (with optional snapping)
- `bt.bake_to_def` — Bake animation onto DEF bones for clean export
- `bt.bone_naming_overlay` — Interactive bone naming overlay (BT convention)
- `bt.set_bone_label` — Dialog to set Type/Side/Role on a bone
- `bt.toggle_floor_contact` — Add/remove floor constraints on leg IK targets
- `bt.update_floor_level` — Update floor Z level on existing constraints
- `bt.batch_skip_selected` — Skip/unskip chains by bone selection
- `bt.batch_skip_pattern` — Skip/unskip chains by glob pattern
- `bt.batch_unskip_all` — Unskip all chains at once

## Bridge API

```bash
# Modular rigging
python blender_api.py rig-add --armature Armature --module arm --side L
python blender_api.py rig-generate --armature Armature
python blender_api.py rig-load --armature Armature --config path/to/biped.json

# Skeleton scanner
python blender_api.py rig-scan --armature Armature
python blender_api.py rig-apply-wrap --armature Armature
python blender_api.py rig-clear-wrap --armature Armature

# FK/IK toggle (works on any chain with IK constraints, snaps pose if ik_snap enabled)
python blender_api.py rig-toggle-fk-ik --armature Armature --chain leg_L --mode IK
python blender_api.py rig-toggle-fk-ik --armature Armature --chain arm_R --mode TOGGLE
python blender_api.py rig-toggle-fk-ik --armature Armature --chain tail_C --mode TOGGLE

# Bake animation to DEF bones for clean export
python blender_api.py rig-bake-to-def --armature Armature

# Floor contact — prevent feet from going below floor level
python blender_api.py floor-contact --armature Armature --action enable --level 0
python blender_api.py floor-contact --armature Armature --action disable
```
