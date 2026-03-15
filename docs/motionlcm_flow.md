# MotionLCM Pipeline Flow

MotionLCM (ECCV 2024) generates humanoid motion from text prompts using
a single-step latent consistency model.  Our adapter wraps the upstream
MotionLCM codebase and integrates it into BlenderTools' dual-model
motion generation system.

GitHub: https://github.com/Dai-Wenxun/MotionLCM


## High-Level Architecture

```
User types prompt          "a person walking forward"
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│  MotionLCMAdapter.generate()                            │
│                                                         │
│  1. predict(prompt, num_frames)                         │
│     ├─ load_model()     ← one-time setup                │
│     ├─ _run_inference() ← the ML pipeline               │
│     └─ _recover_from_263() ← feature → rotation         │
│                                                         │
│  2. Retarget (if wrap rig exists)                       │
│     ├─ build_default_influence_map()                    │
│     ├─ apply_retarget()                                 │
│     └─ scale root positions                             │
│                                                         │
│  3. apply_motion() → Blender Action with FCurves        │
└─────────────────────────────────────────────────────────┘
```


## Components & When They Run

### Stage 0 — Download (one-time, `download_weights()`)

| What               | Source                              | Destination                           |
|--------------------|-------------------------------------|---------------------------------------|
| MotionLCM repo     | GitHub zip                          | `~/.blendertools/models/motionlcm/code/` |
| LCM checkpoint     | GDrive `experiments_t2m.zip`        | `weights/experiments_t2m/`            |
| VAE checkpoint     | GDrive `experiments_recons.zip`     | `weights/experiments_recons/`         |
| Mean.npy / Std.npy | GDrive `tiny_humanml3d.zip`         | `weights/tiny_humanml3d/`             |
| Sentence-T5-Large  | HuggingFace (sentence-transformers) | HuggingFace cache (`~/.cache/...`)    |


### Stage 1 — Model Loading (`load_model()`, one-time)

```
motionlcm_t2m.yaml          Main config (latent dims, guidance, etc.)
        │
        ├── configs/modules/text_encoder.yaml
        │   └─ MldTextEncoder  ← loads Sentence-T5-Large (768-dim embeddings)
        │
        ├── configs/modules/motion_vae.yaml
        │   └─ MldVae          ← encoder/decoder, latent shape [16, 32]
        │
        ├── configs/modules/denoiser.yaml
        │   └─ MldDenoiser     ← transformer, conditioned on text + time
        │
        ├── configs/modules/scheduler_lcm.yaml
        │   └─ LCMScheduler    ← 1-step schedule (timestep 799)
        │
        └── configs/modules/noise_optimizer.yaml
            └─ DNO             ← disabled (optimize: false)
```

**Key detail**: The main YAML's `model.target` lists module names
(`['motion_vae', 'text_encoder', 'denoiser', 'scheduler_lcm',
'noise_optimizer']`).  Each name maps to a YAML in `configs/modules/`
that gets merged into `cfg.model` before the `MLD` constructor runs.

The `MLD` constructor uses `instantiate_from_config()` to create each
component from its `target` (Python class path) and `params`.

**Checkpoint**: All VAE + denoiser weights live in a single `.ckpt` file
loaded via `load_state_dict(strict=False)`.  The text encoder
(Sentence-T5) loads its own weights from HuggingFace cache separately.

**Stub datamodule**: `MLD.__init__` reads `datamodule.feats2joints` to
convert normalised features to joint positions.  Our adapter provides a
minimal stub (`_StubDataModule`) since we capture raw features via
monkey-patch and handle recovery ourselves.


### Stage 2 — Inference (`_run_inference()`, every generation)

```
"a person walking forward"
        │
        ▼
┌─ Text Encoder (Sentence-T5-Large) ──────────────────┐
│  SentenceTransformer.encode(prompt)                  │
│  + empty string for classifier-free guidance         │
│  → text_emb: (2, 1, 768)                            │
└──────────────────────────────────────────────────────┘
        │
        ▼
┌─ Latent Noise ──────────────────────────────────────┐
│  z = randn(1, 16, 32)    ← latent_dim from config   │
└──────────────────────────────────────────────────────┘
        │
        ▼
┌─ LCM 1-Step Denoising ─────────────────────────────┐
│  scheduler.set_timesteps(1)  → timesteps = [799]     │
│  guidance_scale = 8.0 (from cfg_step_map for 1 step) │
│                                                      │
│  1. Duplicate latents for CFG: cat([z, z])           │
│  2. Compute guidance embedding: embed(7.0, dim=256)  │
│  3. Denoiser forward:                                │
│     output = denoiser(z, t=799, cond=text_emb)       │
│  4. CFG: out = uncond + 8.0 * (cond - uncond)        │
│  5. LCM step: z_clean = scheduler.step(out, 799, z)  │
└──────────────────────────────────────────────────────┘
        │
        ▼
┌─ VAE Decode ────────────────────────────────────────┐
│  features = vae.decode(z_clean)                      │
│  → normalised (1, num_frames, 263)                   │
│                                                      │
│  *** monkey-patch captures features here ***         │
└──────────────────────────────────────────────────────┘
        │
        ▼
┌─ Denormalisation (our adapter) ─────────────────────┐
│  features_real = features * Std + Mean               │
│  → (num_frames, 263) in HumanML3D feature space      │
└──────────────────────────────────────────────────────┘
```


### Stage 3 — Feature Recovery (`_recover_from_263()`)

The 263-dim HumanML3D feature vector encodes one frame of motion:

```
Index       Dim   Content
─────────────────────────────────────────────
[0]           1   Root angular velocity (Y-axis rotation rate)
[1:3]         2   Root linear velocity (X, Z in facing frame)
[3]           1   Root height (absolute Y position)
[4:67]       63   Joint positions (21 joints × 3, relative)
[67:193]    126   Joint 6D rotations (21 joints × 6)
[193:259]    66   Joint velocities (22 joints × 3)
[259:263]     4   Foot contact labels (binary)
─────────────────────────────────────────────
Total       263
```

Recovery steps:
1. **Root facing angle** — cumulative sum of angular velocity `[0]`
2. **Root position** — rotate local velocity `[1:3]` by facing angle,
   cumulative sum for XZ, absolute height from `[3]`
3. **Root rotation** — build Y-axis rotation matrix from facing angle
4. **Joint rotations** — Gram-Schmidt on 6D features `[67:193]` → 3×3
   matrices for 21 non-root joints
5. **Y-up → Z-up** — conjugate all rotations by the Y↔Z swap matrix;
   swap Y,Z in root positions
6. **To Euler** — convert 3×3 matrices to XYZ Euler angles

Output: `(rotations_euler, root_positions)` — per-frame lists in
Blender's Z-up coordinate system.


### Stage 4 — Retarget (`retarget_map.py`)

When the user's armature has a wrap rig with scan data:

```
SMPL 22-joint motion              User's skeleton
─────────────────────             ─────────────────
Pelvis (0)            ──┐
L_Hip (1)               │
R_Hip (2)                │
Spine1 (3)               │
  ...                    ├──→  InfluenceMap  ──→  bone_rotations dict
Neck (12)                │       joint_map:        {bone_name: [(rx,ry,rz), ...]}
Head (15)                │       {smpl_idx: [(bone, weight), ...]}
L_Shoulder (16)          │
  ...                    │
R_Wrist (21)          ──┘
```

**Influence map construction** (`build_default_influence_map()`):
1. Group scan bones by `(module_type, side)` — e.g. `('arm', 'L')`
2. Match each SMPL chain to user chains by module type + side
3. Role-based anchoring (THIGH↔upper_leg, SHIN↔lower_leg, etc.)
4. Distribute joints across bones: 1:1, split (weighted by bone
   length), or merge

**Retarget application** (`apply_retarget()`):
1. For each frame, accumulate weighted SMPL rotations per user bone
2. Apply rest-pose correction: `R_pose = R_rest^T @ R_smpl @ R_rest`
   (correction applied ONCE per bone even with multi-source merge)
3. Scale root positions by `user_height / smpl_height`
4. Convert root positions to bone-local space

### Stage 5 — Apply to Blender (`apply_motion()`)

Delegates to `AnyTopAdapter.apply_motion()` which:
1. Creates a Blender Action with channelbag (Blender 5.0 API)
2. Sets all wrap rig chains to FK mode (IK influence → 0)
3. Keyframes `rotation_euler` per bone per frame
4. Keyframes `location` on the root bone
5. Assigns channel groups for timeline organisation


## File Map

| File | Responsibility |
|------|---------------|
| `motionlcm_adapter.py` | Adapter class — download, load, infer, recover features |
| `retarget_map.py` | Influence map construction + retarget application |
| `retarget_preview.py` | SMPL reference armature + wireframe for visual debugging |
| `smpl_skeleton.py` | SMPL 22-joint definition (names, parents, offsets, chains) |
| `anytop_adapter.py` | AnyTop model + `apply_motion()` (shared by both adapters) |
| `anytop_conditioning.py` | AnyTop-specific conditioning (T5 encoding, graph features) |


## Model Selection (Auto-Detect)

```
Armature scan data
        │
        ├─ Has spine + arm + leg chains?
        │   YES → MotionLCM (humanoid, fast, ~30ms)
        │   NO  → AnyTop (any topology, 100-step diffusion, ~5s)
        │
        └─ User can override via Model enum in operator dialog:
           AUTO / MOTIONLCM / ANYTOP
```


## Config Path Resolution

The main config YAML uses OmegaConf interpolation.  Module configs
reference values like `${model.t5_path}` and `${DATASET.NFEATS}` which
resolve from the root config.  Our `_fix_config_paths()` overrides:

| Config Key | Original Value | Our Override |
|------------|---------------|-------------|
| `model.t5_path` | `./deps/sentence-t5-large` | `sentence-transformers/sentence-t5-large` (HF ID) |
| `DATASET.NFEATS` | (from dataset) | `263` |
| `DATASET.NJOINTS` | (from dataset) | `22` |
| `DATASET.HUMANML3D.ROOT` | `./datasets/humanml3d` | `<weights_dir>/tiny_humanml3d` |
| `model.is_controlnet` | (may not exist) | `False` |


## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `torch` | ≥2.0 | Core ML framework |
| `omegaconf` | any | Config system (YAML + interpolation) |
| `sentence-transformers` | any | Sentence-T5-Large text encoder |
| `gdown` | any | Google Drive checkpoint download |
| `numpy` | any | Feature recovery math |
