"""Interactive bone naming overlay for the scanner workflow.

Convention: BT_{TypeCamel}_{Side}_{Role}
Examples: BT_Spine_C_hips, BT_Arm_L_upper_arm, BT_NeckHead_C_neck

When bones follow this convention, the scanner detects them instantly
with 100% confidence -- no heuristic analysis needed.
"""

import time
from math import cos, pi, sin

import blf
import bpy
import gpu
from bpy.props import EnumProperty, IntProperty, StringProperty
from gpu_extras.batch import batch_for_shader

from ...core.constants import (
    CONTROL_PREFIX,
    DEFORM_PREFIX,
    MECHANISM_PREFIX,
    WRAP_CTRL_PREFIX,
    WRAP_MCH_PREFIX,
)

# ---------------------------------------------------------------------------
# Naming convention tables
# ---------------------------------------------------------------------------

TYPE_TO_BT = {
    'spine': 'Spine',
    'arm': 'Arm',
    'leg': 'Leg',
    'neck_head': 'NeckHead',
    'tail': 'Tail',
    'jaw': 'Jaw',
    'eye': 'Eye',
    'wing': 'Wing',
    'tentacle': 'Tentacle',
    'finger': 'Finger',
    'generic': 'Generic',
}
BT_TO_TYPE = {v: k for k, v in TYPE_TO_BT.items()}

MODULE_TYPE_ITEMS = [
    ('spine', "Spine", "Spine chain"),
    ('arm', "Arm", "Arm / front leg"),
    ('leg', "Leg", "Leg (FK+IK, floor contact)"),
    ('neck_head', "Neck/Head", "Neck and head"),
    ('tail', "Tail", "Tail chain"),
    ('jaw', "Jaw", "Jaw bone(s)"),
    ('eye', "Eye", "Eye bone"),
    ('wing', "Wing", "Wing chain"),
    ('tentacle', "Tentacle", "Tentacle chain"),
    ('finger', "Finger", "Finger chain"),
    ('generic', "Generic", "Generic FK chain"),
]

SIDE_ITEMS = [
    ('C', "Center", ""),
    ('L', "Left", ""),
    ('R', "Right", ""),
]

ROLES_BY_TYPE = {
    'spine': [
        ('hips', "Hips", "Hip/root bone"),
        ('spine_01', "Spine 01", ""),
        ('spine_02', "Spine 02", ""),
        ('spine_03', "Spine 03", ""),
        ('chest', "Chest", ""),
        ('extra_0', "Extra 0", ""),
        ('extra_1', "Extra 1", ""),
    ],
    'arm': [
        ('clavicle', "Clavicle", ""),
        ('upper_arm', "Upper Arm", ""),
        ('lower_arm', "Lower Arm", ""),
        ('hand', "Hand", ""),
        ('extra_0', "Extra 0", ""),
        ('extra_1', "Extra 1", ""),
    ],
    'leg': [
        ('pelvis', "Pelvis", "Hip joint"),
        ('upper_leg', "Upper Leg", "Thigh"),
        ('lower_leg', "Lower Leg", "Shin"),
        ('foot', "Foot", ""),
        ('toe', "Toe", ""),
        ('extra_0', "Extra 0", ""),
        ('extra_1', "Extra 1", ""),
    ],
    'neck_head': [
        ('neck', "Neck", ""),
        ('head', "Head", ""),
        ('extra_0', "Extra 0", ""),
    ],
    'jaw': [
        ('upper', "Upper Jaw", ""),
        ('lower', "Lower Jaw", ""),
    ],
    'eye': [
        ('eye', "Eye", ""),
    ],
    'wing': [
        ('upper', "Upper Wing", ""),
        ('mid', "Mid Wing", ""),
        ('lower', "Lower Wing", ""),
        ('tip', "Wing Tip", ""),
        ('extra_0', "Extra 0", ""),
    ],
}

INDEXED_TYPES = {'tail', 'tentacle', 'finger', 'generic'}
_INDEX_ITEMS = [(f'{i:02d}', f'{i:02d}', "") for i in range(1, 31)]


# ---------------------------------------------------------------------------
# Convention helpers
# ---------------------------------------------------------------------------

def parse_bt_name(name):
    """Parse a BT-convention bone name.

    Returns dict {type, side, role} or None.
    """
    if not name.startswith('BT_'):
        return None
    parts = name.split('_', 3)
    if len(parts) < 4:
        return None
    _, bt_type, side, role = parts
    if side not in ('C', 'L', 'R'):
        return None
    type_internal = BT_TO_TYPE.get(bt_type)
    if not type_internal:
        return None
    return {'type': type_internal, 'side': side, 'role': role}


def build_bt_name(type_internal, side, role):
    """Build a BT-convention bone name."""
    bt_type = TYPE_TO_BT.get(type_internal, type_internal.title())
    return f"BT_{bt_type}_{side}_{role}"


# ---------------------------------------------------------------------------
# Dynamic enum callback
# ---------------------------------------------------------------------------

def _role_items(self, context):
    if self.bt_type in INDEXED_TYPES:
        return _INDEX_ITEMS
    items = ROLES_BY_TYPE.get(self.bt_type)
    if items:
        return items
    return [('01', '01', '')]


# ---------------------------------------------------------------------------
# Label operator (popup dialog)
# ---------------------------------------------------------------------------

class BT_OT_SetBoneLabel(bpy.types.Operator):
    """Set bone name following the BT convention"""
    bl_idname = "bt.set_bone_label"
    bl_label = "Label Bone"
    bl_options = {'REGISTER', 'UNDO'}

    bone_name: StringProperty(name="Original Bone")
    bt_type: EnumProperty(name="Type", items=MODULE_TYPE_ITEMS, default='generic')
    bt_side: EnumProperty(name="Side", items=SIDE_ITEMS, default='C')
    bt_role: EnumProperty(name="Role", items=_role_items)
    bt_chain_num: IntProperty(name="Chain", min=1, max=10, default=1)

    def _effective_role(self):
        """Compose the full role string, prepending chain number when needed.

        Indexed types (finger, tail, etc.): always compound — ``{chain}_{bone}``
        Named-role types (arm, leg, etc.): only prepend when chain > 1 to
        keep biped names clean (``upper_arm`` vs ``2_upper_arm``).
        """
        if self.bt_type in INDEXED_TYPES:
            return f"{self.bt_chain_num}_{self.bt_role}"
        if self.bt_chain_num > 1:
            return f"{self.bt_chain_num}_{self.bt_role}"
        return self.bt_role

    def invoke(self, context, event):
        # Pre-fill from existing BT name
        parsed = parse_bt_name(self.bone_name)
        if parsed:
            self.bt_type = parsed['type']
            self.bt_side = parsed['side']
            role = parsed['role']
            # Extract chain number from compound role (e.g. "2_01", "2_upper_arm")
            parts = role.split('_', 1)
            if len(parts) == 2 and parts[0].isdigit():
                chain = int(parts[0])
                remainder = parts[1]
                if parsed['type'] in INDEXED_TYPES:
                    # Indexed: always compound
                    self.bt_chain_num = chain
                    role = remainder
                else:
                    # Named-role: compound only when chain > 1
                    self.bt_chain_num = chain
                    role = remainder
            try:
                self.bt_role = role
            except TypeError:
                pass
        else:
            # Auto-detect side from bone X position
            arm = context.active_object
            if arm and arm.type == 'ARMATURE':
                bone = arm.data.bones.get(self.bone_name)
                if bone:
                    x = bone.head_local.x
                    if x > 0.01:
                        self.bt_side = 'L'
                    elif x < -0.01:
                        self.bt_side = 'R'
                    else:
                        self.bt_side = 'C'

        wm = context.window_manager
        return wm.invoke_props_dialog(self, width=300)

    def draw(self, context):
        layout = self.layout
        layout.label(text=f"Bone: {self.bone_name}", icon='BONE_DATA')
        layout.separator()
        layout.prop(self, "bt_type")
        layout.prop(self, "bt_side")
        layout.prop(self, "bt_chain_num")
        if self.bt_type in INDEXED_TYPES:
            layout.prop(self, "bt_role", text="Bone")
        else:
            layout.prop(self, "bt_role")
        # Preview
        new_name = build_bt_name(self.bt_type, self.bt_side, self._effective_role())
        layout.separator()
        box = layout.box()
        box.label(text=new_name, icon='FORWARD')

    def execute(self, context):
        arm = context.active_object
        if not arm or arm.type != 'ARMATURE':
            self.report({'ERROR'}, "No armature selected")
            return {'CANCELLED'}

        new_name = build_bt_name(self.bt_type, self.bt_side, self._effective_role())

        # Check collision
        if arm.data.bones.get(new_name) and new_name != self.bone_name:
            self.report({'ERROR'}, f"Bone '{new_name}' already exists")
            return {'CANCELLED'}

        # Rename in edit mode
        was_mode = arm.mode
        if was_mode != 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')
        eb = arm.data.edit_bones.get(self.bone_name)
        if eb:
            eb.name = new_name
            self.report({'INFO'}, f"{self.bone_name} -> {new_name}")
        else:
            self.report({'WARNING'}, f"Bone '{self.bone_name}' not found")
        if was_mode != 'EDIT':
            bpy.ops.object.mode_set(mode=was_mode)

        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Auto-name chain operator
# ---------------------------------------------------------------------------

class BT_OT_AutoNameChain(bpy.types.Operator):
    """Auto-name selected child bones based on the BT-named bone in the selection"""
    bl_idname = "bt.auto_name_chain"
    bl_label = "Auto-Name Chain"
    bl_description = "Name children of a BT-named bone, incrementing role index automatically"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj and obj.type == 'ARMATURE' and obj.mode == 'EDIT'
                and sum(1 for b in obj.data.edit_bones if b.select) >= 2)

    def execute(self, context):
        arm = context.active_object
        edit_bones = arm.data.edit_bones
        selected = [b for b in edit_bones if b.select]

        # Find source: prefer active bone if BT-named, else first BT-named
        active = edit_bones.active
        if active and active.select and parse_bt_name(active.name):
            source = active
            source_parsed = parse_bt_name(active.name)
        else:
            source = None
            source_parsed = None
            for bone in selected:
                parsed = parse_bt_name(bone.name)
                if parsed:
                    source = bone
                    source_parsed = parsed
                    break

        if not source:
            self.report({'WARNING'}, "No BT-named bone in selection")
            return {'CANCELLED'}

        # Walk selected descendants depth-first
        selected_names = {b.name for b in selected}
        children = []
        self._walk_children(source, selected_names, children)

        if not children:
            self.report({'WARNING'}, "No selected descendants of the named bone")
            return {'CANCELLED'}

        bt_type = source_parsed['type']
        side = source_parsed['side']
        role = source_parsed['role']

        # Extract chain number from compound role
        chain_num = 1
        role_parts = role.split('_', 1)
        if len(role_parts) == 2 and role_parts[0].isdigit():
            chain_num = int(role_parts[0])
            role = role_parts[1]

        renamed = 0
        if bt_type in INDEXED_TYPES:
            # Increment bone index: 01 → 02, 03, ...
            try:
                start_idx = int(role)
            except ValueError:
                start_idx = 1
            for i, child in enumerate(children):
                new_role = f"{chain_num}_{start_idx + i + 1:02d}"
                new_name = build_bt_name(bt_type, side, new_role)
                if edit_bones.get(new_name) and new_name != child.name:
                    self.report({'WARNING'}, f"Skipped: '{new_name}' already exists")
                    continue
                child.name = new_name
                renamed += 1
        else:
            # Walk role list: upper_arm → lower_arm → hand → ...
            roles_list = ROLES_BY_TYPE.get(bt_type, [])
            role_names = [r[0] for r in roles_list]
            try:
                start_pos = role_names.index(role)
            except ValueError:
                self.report({'WARNING'}, f"Role '{role}' not found in {bt_type} roles")
                return {'CANCELLED'}
            for i, child in enumerate(children):
                pos = start_pos + i + 1
                if pos >= len(role_names):
                    break
                child_role = role_names[pos]
                if chain_num > 1:
                    child_role = f"{chain_num}_{child_role}"
                new_name = build_bt_name(bt_type, side, child_role)
                if edit_bones.get(new_name) and new_name != child.name:
                    self.report({'WARNING'}, f"Skipped: '{new_name}' already exists")
                    continue
                child.name = new_name
                renamed += 1

        # Deselect unrelated bones
        chain_set = {source.name} | {c.name for c in children}
        for bone in selected:
            if bone.name not in chain_set:
                bone.select = False
                bone.select_head = False
                bone.select_tail = False

        self.report({'INFO'}, f"Auto-named {renamed} bones in chain")
        return {'FINISHED'}

    def _walk_children(self, parent, selected_names, result):
        """Depth-first walk of selected children."""
        for child in parent.children:
            if child.name in selected_names:
                result.append(child)
                self._walk_children(child, selected_names, result)


# ---------------------------------------------------------------------------
# Overlay state
# ---------------------------------------------------------------------------

_draw_handle = None
_hover_info = {"bone": None, "pos": None}
_active = False

_anim_current = None
_anim_current_t = 0.0
_anim_prev = None
_anim_prev_t = 0.0

ANIM_DURATION = 0.15
CIRCLE_RADIUS = 10
CIRCLE_SEGMENTS = 24
HOVER_RADIUS = 14
OUTLINE_THICKNESS = 3

COLOR_BT_NAMED = (0.2, 1.0, 0.4, 0.7)
COLOR_BT_OUTLINE = (0.2, 1.0, 0.4, 1.0)


# ---------------------------------------------------------------------------
# Animation helpers
# ---------------------------------------------------------------------------

def _smoothstep(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _lerp(a, b, t):
    return a + (b - a) * t


def _update_hover(bone_name):
    global _anim_current, _anim_current_t, _anim_prev, _anim_prev_t
    if bone_name == _anim_current:
        return
    now = time.monotonic()
    if _anim_current:
        _anim_prev = _anim_current
        _anim_prev_t = now
    _anim_current = bone_name
    if bone_name:
        _anim_current_t = now


def _hover_factor(bone_name):
    now = time.monotonic()
    if _anim_current and bone_name == _anim_current:
        return _smoothstep(min(1.0, (now - _anim_current_t) / ANIM_DURATION))
    if _anim_prev and bone_name == _anim_prev:
        return 1.0 - _smoothstep(min(1.0, (now - _anim_prev_t) / ANIM_DURATION))
    return 0.0


def _is_animating():
    now = time.monotonic()
    if _anim_current and (now - _anim_current_t) < ANIM_DURATION:
        return True
    if _anim_prev and (now - _anim_prev_t) < ANIM_DURATION:
        return True
    return False


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def _circle_verts(cx, cy, r, segs=CIRCLE_SEGMENTS):
    verts = [(cx, cy)]
    for i in range(segs + 1):
        a = 2 * pi * i / segs
        verts.append((cx + r * cos(a), cy + r * sin(a)))
    return verts


def _circle_indices(segs=CIRCLE_SEGMENTS):
    return [(0, i, i + 1 if i < segs else 1) for i in range(1, segs + 1)]


def _ring_verts(cx, cy, r_out, r_in, segs=CIRCLE_SEGMENTS):
    verts = []
    for i in range(segs + 1):
        a = 2 * pi * i / segs
        verts.append((cx + r_out * cos(a), cy + r_out * sin(a)))
        verts.append((cx + r_in * cos(a), cy + r_in * sin(a)))
    return verts


def _ring_indices(segs=CIRCLE_SEGMENTS):
    indices = []
    for i in range(segs):
        o1, i1, o2, i2 = i * 2, i * 2 + 1, (i + 1) * 2, (i + 1) * 2 + 1
        indices.append((o1, i1, o2))
        indices.append((i1, i2, o2))
    return indices


def _draw_circle(shader, sx, sy, radius, color):
    verts = _circle_verts(sx, sy, radius)
    batch = batch_for_shader(shader, 'TRIS', {"pos": verts}, indices=_circle_indices())
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _draw_ring(shader, sx, sy, r_out, r_in, color):
    verts = _ring_verts(sx, sy, r_out, r_in)
    batch = batch_for_shader(shader, 'TRIS', {"pos": verts}, indices=_ring_indices())
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _draw_label(sx, sy, text, alpha):
    if alpha < 0.05:
        return
    font_id = 0
    blf.size(font_id, 13)
    w, h = blf.dimensions(font_id, text)
    lx, ly = sx - w / 2, sy
    pad = 5
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    bg = [(lx - pad, ly - 4), (lx + w + pad, ly - 4),
          (lx + w + pad, ly + h + 4), (lx - pad, ly + h + 4)]
    batch = batch_for_shader(shader, 'TRIS', {"pos": bg}, indices=[(0, 1, 2), (0, 2, 3)])
    shader.bind()
    shader.uniform_float("color", (0.0, 0.0, 0.0, 0.65 * alpha))
    batch.draw(shader)
    blf.color(font_id, 1.0, 1.0, 1.0, alpha)
    blf.position(font_id, lx, ly, 0)
    blf.draw(font_id, text)


def _draw_header(context, text):
    region = context.region
    if not region:
        return
    font_id = 0
    blf.size(font_id, 16)
    w, h = blf.dimensions(font_id, text)
    x, y = (region.width - w) / 2, region.height - 40
    pad = 10
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    bar = [(x - pad, y - 6), (x + w + pad, y - 6),
           (x + w + pad, y + h + 6), (x - pad, y + h + 6)]
    batch = batch_for_shader(shader, 'TRIS', {"pos": bar}, indices=[(0, 1, 2), (0, 2, 3)])
    shader.bind()
    shader.uniform_float("color", (0.0, 0.0, 0.0, 0.7))
    batch.draw(shader)
    blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
    blf.position(font_id, x, y, 0)
    blf.draw(font_id, text)


def _world_to_screen(context, pos):
    from bpy_extras.view3d_utils import location_3d_to_region_2d
    region = context.region
    rv3d = context.space_data.region_3d
    if not region or not rv3d:
        return None
    return location_3d_to_region_2d(region, rv3d, pos)


# ---------------------------------------------------------------------------
# Bone data
# ---------------------------------------------------------------------------

def _get_bone_points(context):
    """Get bone center screen-projectable points, skipping generated bones."""
    obj = context.active_object
    if not obj or obj.type != 'ARMATURE' or obj.mode == 'POSE':
        return []

    mat = obj.matrix_world
    points = []
    for bone in obj.data.bones:
        name = bone.name
        if (name.startswith(DEFORM_PREFIX) or name.startswith(CONTROL_PREFIX) or
                name.startswith(MECHANISM_PREFIX) or name.startswith(WRAP_CTRL_PREFIX) or
                name.startswith(WRAP_MCH_PREFIX)):
            continue
        center = (bone.head_local + bone.tail_local) / 2
        points.append((name, mat @ center))
    return points


# ---------------------------------------------------------------------------
# Draw callback
# ---------------------------------------------------------------------------

def _draw_callback(context):
    if not _active:
        return
    obj = context.active_object
    if not obj or obj.type != 'ARMATURE' or obj.mode == 'POSE':
        return

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')

    points = _get_bone_points(context)
    bt_count = 0
    total = len(points)

    for bone_name, world_pos in points:
        screen = _world_to_screen(context, world_pos)
        if screen is None:
            continue

        sx, sy = screen
        is_bt = bone_name.startswith('BT_')
        factor = _hover_factor(bone_name)

        if is_bt:
            bt_count += 1
            # Green for BT-named bones
            _draw_ring(shader, sx, sy,
                       CIRCLE_RADIUS + 2, CIRCLE_RADIUS, COLOR_BT_OUTLINE)
            _draw_circle(shader, sx, sy, CIRCLE_RADIUS, COLOR_BT_NAMED)
            if factor > 0.01:
                extra_r = _lerp(0, 4, factor)
                _draw_ring(shader, sx, sy,
                           CIRCLE_RADIUS + 2 + extra_r,
                           CIRCLE_RADIUS + 2,
                           (0.2, 1.0, 0.4, factor))
        else:
            # White for unlabeled bones
            radius = _lerp(CIRCLE_RADIUS, HOVER_RADIUS, factor)
            fill_alpha = _lerp(0.3, 0.9, factor)
            if factor > 0.01:
                _draw_ring(shader, sx, sy,
                           radius + OUTLINE_THICKNESS * factor,
                           radius, (1.0, 1.0, 1.0, factor))
            _draw_circle(shader, sx, sy, radius, (1.0, 1.0, 1.0, fill_alpha))

        # Label on hover
        if factor > 0.1:
            r = CIRCLE_RADIUS + 2 if is_bt else _lerp(CIRCLE_RADIUS, HOVER_RADIUS, factor)
            _draw_label(sx, sy + r + 8, bone_name, factor)

    # Header
    _draw_header(context,
                 f"Name Bones: click to label  |  {bt_count}/{total} named  |  ESC to exit")

    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('NONE')

    if _is_animating() and context.area:
        context.area.tag_redraw()


# ---------------------------------------------------------------------------
# Hit testing
# ---------------------------------------------------------------------------

def _hit_test(context, mx, my):
    points = _get_bone_points(context)
    best = None
    best_dist = HOVER_RADIUS + OUTLINE_THICKNESS + 2

    for bone_name, world_pos in points:
        screen = _world_to_screen(context, world_pos)
        if screen is None:
            continue
        dx, dy = mx - screen[0], my - screen[1]
        dist = (dx * dx + dy * dy) ** 0.5
        if dist < best_dist:
            best_dist = dist
            best = (bone_name, world_pos)
    return best


# ---------------------------------------------------------------------------
# Modal operator
# ---------------------------------------------------------------------------

class BT_OT_BoneNamingOverlay(bpy.types.Operator):
    """Interactive overlay for naming bones with the BT convention"""
    bl_idname = "bt.bone_naming_overlay"
    bl_label = "Name Bones"
    bl_description = "Click bones to label them with BT_{Type}_{Side}_{Role}"

    def modal(self, context, event):
        global _active

        if not _active:
            self._cleanup(context)
            return {'CANCELLED'}

        obj = context.active_object
        if not obj or obj.type != 'ARMATURE' or obj.mode == 'POSE':
            _active = False
            self._cleanup(context)
            return {'CANCELLED'}

        if event.type == 'ESC':
            _active = False
            self._cleanup(context)
            self.report({'INFO'}, "Bone naming overlay disabled")
            return {'CANCELLED'}

        if event.type == 'MOUSEMOVE':
            hit = _hit_test(context, event.mouse_region_x, event.mouse_region_y)
            if hit:
                _hover_info["bone"] = hit[0]
                _hover_info["pos"] = hit[1]
                _update_hover(hit[0])
            else:
                _hover_info["bone"] = None
                _hover_info["pos"] = None
                _update_hover(None)
            context.area.tag_redraw()
            return {'PASS_THROUGH'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            hit = _hit_test(context, event.mouse_region_x, event.mouse_region_y)
            if hit:
                bpy.ops.bt.set_bone_label('INVOKE_DEFAULT', bone_name=hit[0])
                return {'RUNNING_MODAL'}

        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        global _draw_handle, _active, _anim_current, _anim_prev

        if _active:
            _active = False
            self._cleanup(context)
            self.report({'INFO'}, "Bone naming overlay disabled")
            return {'CANCELLED'}

        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Select an armature first")
            return {'CANCELLED'}

        if obj.mode == 'POSE':
            self.report({'WARNING'}, "Not available in pose mode")
            return {'CANCELLED'}

        _active = True
        _hover_info["bone"] = None
        _hover_info["pos"] = None
        _anim_current = None
        _anim_prev = None

        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_callback, (context,), 'WINDOW', 'POST_PIXEL'
        )

        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        self.report({'INFO'}, "Bone naming overlay — click bones to label them")
        return {'RUNNING_MODAL'}

    def _cleanup(self, context):
        global _draw_handle
        if _draw_handle:
            bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
            _draw_handle = None
        if context.area:
            context.area.tag_redraw()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (
    BT_OT_SetBoneLabel,
    BT_OT_AutoNameChain,
    BT_OT_BoneNamingOverlay,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    global _active, _draw_handle
    if _draw_handle:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None
    _active = False
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
