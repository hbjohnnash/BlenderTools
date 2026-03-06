# Rig Config Format

## JSON Schema

```json
{
  "name": "string — Display name for the rig",
  "modules": [
    {
      "type": "string — Module type (spine, arm, leg, etc.)",
      "name": "string — Instance name (used in bone naming)",
      "side": "string — C, L, or R",
      "parent_bone": "string — Parent reference (empty or ModuleName.point)",
      "position": [0.0, 0.0, 0.0],
      "options": {}
    }
  ],
  "global_options": {
    "deform_prefix": "DEF-",
    "control_prefix": "CTRL-",
    "mechanism_prefix": "MCH-"
  }
}
```

## Module Options Reference

### spine
- `bone_count` (int, default 4) — Number of spine segments
- `ik_spline` (bool, default false) — Add IK spline controls

### arm
- `twist_bones` (int, default 1) — Upper arm twist bone count
- `clavicle` (bool, default true) — Include clavicle bone

### leg
- `twist_bones` (int, default 1) — Thigh twist bone count
- `foot_roll` (bool, default true) — Add foot roll mechanism

### neck_head
- `neck_bones` (int, default 2) — Number of neck segments

### tail
- `bone_count` (int, default 6) — Tail segments
- `ik_tip` (bool, default false) — IK control at tip
- `direction` ([x,y,z], default [0,1,-0.2]) — Growth direction
- `segment_length` (float, default 0.1) — Bone length

### wing
- `segments` (int, default 3) — Wing bone segments
- `feather_bones` (int, default 3) — Feathers per segment

### tentacle
- `bone_count` (int, default 8) — Tentacle segments
- `taper` (bool, default true) — Taper segment lengths
- `direction` ([x,y,z]) — Growth direction
- `segment_length` (float, default 0.08)

### finger_chain
- `bone_count` (int, default 3) — Phalanx count
- `finger_name` (string, default "Index") — Finger identifier
- `direction` ([x,y,z]) — Growth direction
- `segment_length` (float, default 0.03)

### piston
- `stroke_length` (float, default 0.3) — Piston stroke distance
- `direction` ([x,y,z], default [0,0,1]) — Stroke axis

### wheel
- `radius` (float, default 0.3) — Wheel radius

### jaw
- `upper_jaw` (bool, default false) — Include upper jaw bone

### eye
- `eyelids` (bool, default true) — Include eyelid bones
- `target_distance` (float, default 1.0) — Aim target distance

### custom_chain
- `bone_count` (int, default 4) — Chain length
- `ik` (bool, default false) — Add IK target
- `direction` ([x,y,z], default [0,0,1]) — Chain direction
- `segment_length` (float, default 0.1)

## Parent Bone References

Use dot notation to reference connection points:
- `"Spine.hip"` — Root of spine
- `"Spine.chest"` — Top of spine
- `"Spine.mid"` — Middle of spine
- `"Arm.hand"` — Hand bone
- `"NeckHead.head"` — Head bone

Empty string `""` means no parent (root module).

## Example: Biped Human

```json
{
  "name": "Biped Human",
  "modules": [
    {"type": "spine", "name": "Spine", "side": "C", "parent_bone": "", "position": [0,0,1.0], "options": {"bone_count": 4}},
    {"type": "neck_head", "name": "NeckHead", "side": "C", "parent_bone": "Spine.chest", "position": [0,0,1.6]},
    {"type": "arm", "name": "Arm", "side": "L", "parent_bone": "Spine.chest", "position": [0,0,1.55], "options": {"clavicle": true}},
    {"type": "arm", "name": "Arm", "side": "R", "parent_bone": "Spine.chest", "position": [0,0,1.55], "options": {"clavicle": true}},
    {"type": "leg", "name": "Leg", "side": "L", "parent_bone": "Spine.hip", "position": [0,0,1.0]},
    {"type": "leg", "name": "Leg", "side": "R", "parent_bone": "Spine.hip", "position": [0,0,1.0]}
  ]
}
```

## Example: Quadruped

```json
{
  "name": "Quadruped",
  "modules": [
    {"type": "spine", "name": "Spine", "side": "C", "parent_bone": "", "position": [0,0,0.8], "options": {"bone_count": 5, "ik_spline": true}},
    {"type": "neck_head", "name": "NeckHead", "side": "C", "parent_bone": "Spine.chest", "position": [0,-0.3,0.85], "options": {"neck_bones": 3}},
    {"type": "leg", "name": "FrontLeg", "side": "L", "parent_bone": "Spine.chest", "position": [0.12,-0.2,0.8]},
    {"type": "leg", "name": "FrontLeg", "side": "R", "parent_bone": "Spine.chest", "position": [-0.12,-0.2,0.8]},
    {"type": "leg", "name": "HindLeg", "side": "L", "parent_bone": "Spine.hip", "position": [0.12,0.3,0.8]},
    {"type": "leg", "name": "HindLeg", "side": "R", "parent_bone": "Spine.hip", "position": [-0.12,0.3,0.8]},
    {"type": "tail", "name": "Tail", "side": "C", "parent_bone": "Spine.hip", "position": [0,0.5,0.75], "options": {"bone_count": 6}}
  ]
}
```
