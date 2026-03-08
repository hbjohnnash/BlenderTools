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

**Chain numbering** allows multiple chains of the same type on the same side (e.g. multiple fingers per hand, multiple legs on an insect). The naming dialog includes a **Chain** field (1–10):
- **Indexed types** (finger, tail, tentacle, generic): Chain number is always embedded in the role — `{chain}_{bone}` (e.g. `BT_Finger_R_1_01`, `BT_Finger_R_2_03`)
- **Named-role types** (arm, leg, spine, etc.): Chain number is only embedded when > 1 to keep biped names clean — `BT_Arm_L_upper_arm` (chain 1), `BT_Arm_L_2_upper_arm` (chain 2)

Examples:

| Name | Type | Side | Chain | Role |
|------|------|------|-------|------|
| `BT_Spine_C_hips` | Spine | C | 1 | hips |
| `BT_Arm_L_upper_arm` | Arm | L | 1 | upper_arm |
| `BT_Arm_L_2_upper_arm` | Arm | L | 2 | upper_arm |
| `BT_Finger_R_1_01` | Finger | R | 1 | 01 |
| `BT_Finger_R_3_02` | Finger | R | 3 | 02 |
| `BT_Leg_L_3_foot` | Leg | L | 3 | foot |

The **Name Bones overlay** (`bt.bone_naming_overlay`) provides an interactive viewport tool: hover over bones to see clickable circles (white=unlabeled, green=BT-named), click to open a dialog with Type/Side/Chain/Role dropdowns that renames the bone automatically.

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

**Standard IK controls (arm/leg/wing and any chain with standard IK):**
- `CTRL-Wrap_{chain}_IK_target` — IK target at hand/foot position
- `CTRL-Wrap_{chain}_IK_pole` — Pole vector at elbow/knee (calculated from limb geometry)
- IK bone sizes are proportional to the chain (30% of the lower bone's length)
- IK influence starts at 0.0 (FK mode) — user toggles to 1.0 for IK mode

**Dynamic chain_count:** For arms and legs, `chain_count` is calculated from the actual bone span (upper→lower index), not hardcoded to 2. Arms/legs with intermediate bones (e.g. upper_arm → mid_arm → lower_arm → hand) have IK covering the full chain.

### Spline IK (Tails, Tentacles)

For long chains (tail, tentacle), standard IK poorly distributes motion across joints. Spline IK uses a Bezier curve driven by hook control bones for smooth chain deformation.

**How it works:**
1. A Bezier curve (`BT_Wrap_Spline_{chain_id}`) is created along the chain, parented to the armature
2. 3–5 hook control bones (`CTRL-Wrap_{chain}_Spline_{00..04}`) are placed at even intervals along the chain
3. Hook modifiers bind each curve control point to its hook bone
4. A `SPLINE_IK` constraint on the **last** MCH bone drives the chain along the curve (walks up the parent chain, same as regular IK)
5. Moving hook bones reshapes the curve, smoothly deforming the entire chain

**Defaults:** Tail and tentacle chains default to `ik_type='SPLINE'`. This can be changed to `'STANDARD'` in the chain config panel.

**Control point count:** Based on chain length — 3 points for ≤4 bones, 4 for ≤8, 5 for 9+. All hook bones are parented to the cross-chain MCH parent so the entire spline follows the body when parent bones rotate.

**Spline FK/IK snapping:** When switching FK → Spline, hook bones are repositioned along the current FK-posed chain. When switching Spline → FK, FK controls snap to the spline-solved MCH poses. Snapping is always enabled for spline chains (no `ik_snap` requirement).

### IK Rotation Limits (Joint Limits)

Prevents hyperextension and constrains joint range of motion using Blender's IK bone limit properties (`ik_min_x`, `ik_max_x`, `ik_stiffness_x`, etc.). These are evaluated **inside** the IK solver and work with pole targets — unlike `LIMIT_ROTATION` constraints which are ignored by IK.

**Per-module defaults:**
- **Arm/Leg mid-joints** (elbow/knee): Single-axis bend with auto-detected bend axis, no hyperextension (0° to 160°), secondary axes locked with high stiffness
- **Arm/Leg root/end joints** (shoulder/hip, wrist/ankle): Moderate limits (±120° all axes)
- **Tail chains**: ±45° per joint, slight stiffness (0.1)
- **Tentacle chains**: ±60° per joint, slight stiffness (0.05)
- **Generic chains**: ±90° per joint, no stiffness

**Bend axis auto-detection:** The system examines rest-pose bone geometry (cross product of parent/child directions), transforms to bone-local space, and identifies the dominant rotation axis. This works regardless of bone roll.

**Runtime toggle:** The `bt.toggle_ik_limits` operator flips `use_ik_limit_x/y/z` on all MCH bones in a chain. Limit values are preserved so re-enabling restores them instantly.

**Per-bone editing:** The `bt.edit_bone_ik_limits` operator opens a dialog to adjust per-axis min/max angles and stiffness for individual MCH bones. Accessible via the gear icon in the FK/IK panel or right-click context menu in pose mode ("Edit IK Limits"). Works on any selected bone (CTRL, MCH, or DEF) — automatically maps to the corresponding MCH bone.

### FK/IK Build Config vs. Runtime State

- `fk_enabled` / `ik_enabled` — Control whether FK/IK controls are **generated** during build. Build-time settings.
- `ik_type` — `'STANDARD'` or `'SPLINE'`. Default `'SPLINE'` for tail/tentacle, `'STANDARD'` for all others. Build-time.
- `ik_snap` — Per-chain toggle (build-time). When enabled, supports FK/IK snapping and clamps `chain_count` to 2. Default ON for arms/legs. Only available for Standard IK.
- `ik_limits` — Whether to apply joint rotation limits. Default ON for arms/legs/wings. Toggleable at runtime.
- `ik_active` — Tracks which mode is **currently active** at runtime. All chains start in FK.

### FK/IK Toggle with Snapping

FK/IK switching works on **any chain** with IK or Spline IK constraints. The `bt.toggle_fk_ik` operator handles switching.

When `ik_snap` is enabled (Standard IK only):
- **IK -> FK:** FK control bones snap to match the IK-solved pose before switching
- **FK -> IK:** IK target snaps to chain end, pole angle recalibrated to match FK pose
- Snapping only works for 2-bone IK chains (arms/legs)

When toggling (on MCH layer):
- **FK mode** — MCH COPY_TRANSFORMS influence=1.0, MCH IK/SPLINE_IK influence=0.0
- **IK mode** — MCH COPY_TRANSFORMS influence=0.0, MCH IK/SPLINE_IK influence=1.0
- **IK range awareness** — Only bones within the IK `chain_count` range have FK disabled. Bones outside the range (e.g. foot/toe below an IK target) keep FK active in both modes.

### Branching Hierarchy Support

The wrap rig respects the original skeleton's branching hierarchy. If a spine chain branches (e.g. `spine_01` has children `spine_02` and `hips`), the MCH hierarchy mirrors this — `MCH_hips` is parented to `MCH_spine_01`, not to `MCH_chest`. This ensures rotating the chest does not cascade to the hips, tail, or legs.

**IK control visibility:** IK target, pole, and spline hook bones are placed in per-chain bone collections (`IK_arm_L`, `IK_leg_R`, `IK_tail_C`, etc.) that start hidden. Toggling to IK shows the collection; toggling back hides it.

**Panel modes:**
- **Config mode (before wrap rig):** FK/IK/Type/Snap/Limits config, bone mapping, batch skip, unmapped bones sections visible
- **Rig mode (after wrap rig):** FK/IK toggle buttons (showing "Spline" for spline chains). IK limits toggle icon. Appears when any bone in an IK-capable chain is selected.

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

## Control Bone Custom Shapes

Procedural shape library for visual bone representation. Shapes are mesh objects in a hidden `BT_Shapes` collection, reused via `bone.custom_shape`. Sizing uses `custom_shape_scale_xyz` (no mesh duplication).

**Built-in shapes:** circle, cube, diamond, sphere, arrow, square, line

**Auto-assignment (on rig generation):**
- FK controls → circle (scale 0.8)
- IK targets → cube (scale 0.6)
- IK poles → diamond (scale 0.5)
- Spline hooks → sphere (scale 0.4)

**FK location locks:** FK bones have location locked (`lock_location = True, True, True`) during wrap rig generation — they can only rotate. Exception: COG bones (first FK bone of spine/root chains) keep location unlocked for body positioning.

**User extension:** Any mesh can be added to the library via `bt.add_custom_shape`. It moves the active mesh object into the `BT_Shapes` collection.

**Operators:**
- `bt.assign_bone_shape` — Assign a shape from the library to selected bones
- `bt.resize_ctrl_bones` — Scale custom shapes of selected bones
- `bt.clear_bone_shapes` — Remove custom shapes from selected bones
- `bt.add_custom_shape` — Add active mesh to the shape library

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
- `bt.toggle_ik_limits` — Enable/disable IK joint rotation limits per chain at runtime
- `bt.edit_bone_ik_limits` — Per-bone IK limit editor (gear icon or right-click in pose mode)
- `bt.bake_to_def` — Bake animation onto DEF bones for clean export
- `bt.bone_naming_overlay` — Interactive bone naming overlay (BT convention)
- `bt.auto_name_chain` — Auto-name selected child bones based on root bone's BT name
- `bt.set_bone_label` — Dialog to set Type/Side/Role on a bone
- `bt.ik_overlay` — FK/IK toggle overlay at viewport bottom (clickable buttons per chain)
- `bt.toggle_com` — Toggle Center of Mass + Base of Support + Balance visualization
- `bt.recalc_com_masses` — Recalculate auto masses from mesh vertex weights
- `bt.toggle_floor_contact` — Add/remove floor constraints on leg IK targets
- `bt.update_floor_level` — Update floor Z level on existing constraints
- `bt.batch_skip_selected` — Skip/unskip chains by bone selection
- `bt.batch_skip_pattern` — Skip/unskip chains by glob pattern
- `bt.batch_unskip_all` — Unskip all chains at once
- `bt.assign_bone_shape` — Assign custom shape to selected bones
- `bt.resize_ctrl_bones` — Scale custom shapes of selected bones
- `bt.clear_bone_shapes` — Remove custom shapes from selected bones
- `bt.add_custom_shape` — Add active mesh to shape library
- `bt.smart_keyframe` — Smart keyframe: keys FK rotation, snaps FK from IK for IK bones, never keys IK directly

## Auto-Name Chain

After naming one bone with the BT convention, select its descendants and click **"Auto-Name Chain"** (chain link icon). Walks the selection depth-first and assigns incrementing names:
- **Indexed types** (finger, tail, tentacle, generic): increments the bone index (01 → 02 → 03)
- **Named-role types** (arm, leg, etc.): walks the role list (upper_arm → lower_arm → hand)
Unrelated selected bones are deselected.

## FK/IK Overlay

A clickable bar at the bottom of the viewport showing FK/IK state for each IK-capable chain:
- **Blue** = FK mode, **Orange** = IK mode
- Click a button to toggle that chain's FK/IK mode
- Shows "Spline" for spline IK chains
- ESC to dismiss, toggle via panel button or `bt.ik_overlay`

## Center of Mass + Base of Support

Pose-mode visualization for balance analysis:

### Center of Mass (CoM)
- Crosshair marker at the weighted average of all deform bone positions
- Per-bone mass auto-calculated from mesh vertex weights (vertex group influence)
- Users can override individual bone masses via the panel (pin icon)

### Base of Support (BoS)
- Convex hull polygon projected on the ground plane from foot/hand contact bones
- Detection: scan data (leg foot/toe + arm hand for quadrupeds) → name fallback (foot/toe/hand/paw/hoof/claw) → Z-position fallback (leaf deform bones in bottom 15% of skeleton)

### Balance Indicator
- Stability ratio: signed distance from CoM ground projection to nearest BoS edge, normalized
- Color gradient: green (>50% = stable) → yellow (50% = marginal) → red (0% = on edge)
- Bar with needle at bottom-right of viewport

**Operators:** `bt.toggle_com`, `bt.recalc_com_masses`

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
