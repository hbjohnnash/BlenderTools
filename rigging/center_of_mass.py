"""Center of Mass + Base of Support + Balance visualization.

Shows in pose mode:
- CoM marker (crosshair) colored by balance
- Ground projection drop line
- Base of Support polygon from foot/toe bones
- Balance indicator bar
"""

import bpy
import gpu
import blf
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from math import cos, sin, pi
from bpy.props import FloatProperty, StringProperty, BoolProperty, CollectionProperty
from ..core.constants import PANEL_CATEGORY


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

class BT_BoneMassItem(bpy.types.PropertyGroup):
    bone_name: StringProperty(name="Bone")
    auto_mass: FloatProperty(name="Auto", default=1.0, min=0.0)
    custom_mass: FloatProperty(name="Mass", default=1.0, min=0.0, soft_max=10.0)
    use_custom: BoolProperty(name="Override", default=False)

    @property
    def effective_mass(self):
        return self.custom_mass if self.use_custom else self.auto_mass


# ---------------------------------------------------------------------------
# Mass calculation
# ---------------------------------------------------------------------------

def _compute_auto_masses(armature_obj):
    """Estimate per-bone mass from mesh vertex weights."""
    masses = {}
    bone_names = {b.name for b in armature_obj.data.bones if b.use_deform}

    for child in armature_obj.children:
        if child.type != 'MESH':
            continue
        mesh = child.data
        vg_map = {}
        for vg in child.vertex_groups:
            if vg.name in bone_names:
                vg_map[vg.index] = vg.name

        if not vg_map:
            continue

        for vert in mesh.vertices:
            for g in vert.groups:
                bone = vg_map.get(g.group)
                if bone:
                    masses[bone] = masses.get(bone, 0.0) + g.weight

    if masses:
        avg = sum(masses.values()) / len(masses)
        if avg > 0:
            for k in masses:
                masses[k] /= avg

    return masses


def _sync_mass_items(armature_obj):
    """Sync the bone mass collection with current deform bones."""
    items = armature_obj.bt_com_masses
    bone_names = {b.name for b in armature_obj.data.bones if b.use_deform}

    for i in reversed(range(len(items))):
        if items[i].bone_name not in bone_names:
            items.remove(i)

    existing = {item.bone_name for item in items}
    for name in sorted(bone_names):
        if name not in existing:
            item = items.add()
            item.bone_name = name

    auto = _compute_auto_masses(armature_obj)
    for item in items:
        item.auto_mass = auto.get(item.bone_name, 1.0)


def compute_center_of_mass(armature_obj):
    """Calculate world-space center of mass.

    Returns (Vector, total_mass) or (None, 0).
    """
    items = armature_obj.bt_com_masses
    if not items:
        return None, 0.0

    total_mass = 0.0
    weighted_pos = Vector((0, 0, 0))
    mat = armature_obj.matrix_world

    for item in items:
        mass = item.effective_mass
        if mass <= 0:
            continue
        pbone = armature_obj.pose.bones.get(item.bone_name)
        if not pbone:
            continue
        world_pos = mat @ pbone.head
        weighted_pos += world_pos * mass
        total_mass += mass

    if total_mass <= 0:
        return None, 0.0

    return weighted_pos / total_mass, total_mass


# ---------------------------------------------------------------------------
# Base of Support
# ---------------------------------------------------------------------------

_foot_bones = []  # Cached list of foot/toe bone names


def _detect_foot_bones(armature_obj):
    """Find foot and toe bones from scan data or name matching."""
    global _foot_bones
    _foot_bones = []

    sd = getattr(armature_obj, 'bt_scan', None)
    if sd and sd.is_scanned:
        # Ground contact roles per module type
        contact_roles = {
            "leg": ("foot", "toe"),
            "arm": ("hand",),  # quadruped front legs
        }
        for bone_item in sd.bones:
            roles = contact_roles.get(bone_item.module_type)
            if roles and bone_item.role in roles:
                _foot_bones.append(bone_item.bone_name)

    if not _foot_bones:
        # Fallback 1: name-based detection (expanded for quadrupeds)
        for b in armature_obj.data.bones:
            name_l = b.name.lower()
            if any(kw in name_l for kw in ("foot", "toe", "hoof", "paw", "hand", "palm", "claw")):
                _foot_bones.append(b.name)

    if not _foot_bones:
        # Fallback 2: Z-position — find leaf deform bones near the ground
        deform_bones = [b for b in armature_obj.data.bones if b.use_deform]
        if deform_bones:
            mat = armature_obj.matrix_world
            deform_children = set()
            for b in deform_bones:
                if b.parent and b.parent.use_deform:
                    deform_children.add(b.parent.name)
            leaf_bones = [b for b in deform_bones if b.name not in deform_children]

            if leaf_bones:
                # Find Z range from all deform bones to set threshold
                all_z = []
                for b in deform_bones:
                    pbone = armature_obj.pose.bones.get(b.name)
                    if pbone:
                        all_z.append((mat @ pbone.head).z)
                if all_z:
                    min_z = min(all_z)
                    max_z = max(all_z)
                    height = max_z - min_z
                    threshold = min_z + height * 0.15 if height > 0 else min_z + 0.1
                    for b in leaf_bones:
                        pbone = armature_obj.pose.bones.get(b.name)
                        if pbone and (mat @ pbone.head).z <= threshold:
                            _foot_bones.append(b.name)


def _get_bos_points(armature_obj, floor_z=0.0):
    """Get ground-projected contact points from foot bones.

    Returns list of (x, y) tuples on the ground plane.
    """
    if not _foot_bones:
        return []

    mat = armature_obj.matrix_world
    points = []

    for name in _foot_bones:
        pbone = armature_obj.pose.bones.get(name)
        if not pbone:
            continue
        head = mat @ pbone.head
        tail = mat @ pbone.tail
        points.append((head.x, head.y))
        points.append((tail.x, tail.y))

    return points


def _cross_2d(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _convex_hull(points):
    """Andrew's monotone chain convex hull."""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    lower = []
    for p in pts:
        while len(lower) >= 2 and _cross_2d(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and _cross_2d(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


def _point_in_polygon(px, py, polygon):
    """Ray-casting point-in-polygon test."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _point_to_segment_dist(px, py, ax, ay, bx, by):
    """Distance from point to line segment."""
    dx, dy = bx - ax, by - ay
    len_sq = dx * dx + dy * dy
    if len_sq == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / len_sq))
    proj_x = ax + t * dx
    proj_y = ay + t * dy
    return ((px - proj_x) ** 2 + (py - proj_y) ** 2) ** 0.5


def compute_balance(com, bos_hull):
    """Compute stability ratio.

    Returns float: 1.0 = centered, 0.0 = on edge, <0 = outside.
    """
    if not bos_hull or len(bos_hull) < 3 or com is None:
        return 0.0

    cx, cy = com.x, com.y

    # Min distance to any edge
    n = len(bos_hull)
    min_dist = float('inf')
    for i in range(n):
        j = (i + 1) % n
        d = _point_to_segment_dist(cx, cy, *bos_hull[i], *bos_hull[j])
        min_dist = min(min_dist, d)

    inside = _point_in_polygon(cx, cy, bos_hull)
    signed_dist = min_dist if inside else -min_dist

    # Normalize by max inscribed distance (centroid to nearest edge)
    centroid_x = sum(p[0] for p in bos_hull) / n
    centroid_y = sum(p[1] for p in bos_hull) / n
    max_dist = float('inf')
    for i in range(n):
        j = (i + 1) % n
        d = _point_to_segment_dist(centroid_x, centroid_y, *bos_hull[i], *bos_hull[j])
        max_dist = min(max_dist, d)

    if max_dist <= 0:
        return 0.0

    return max(min(signed_dist / max_dist, 1.0), -0.5)


def _balance_color(stability, alpha=0.8):
    """Map stability [0,1] to green->yellow->red gradient."""
    t = max(0.0, min(1.0, stability))
    if t > 0.5:
        r = (1.0 - t) * 2
        g = 1.0
    else:
        r = 1.0
        g = t * 2
    return (r, g, 0.0, alpha)


# ---------------------------------------------------------------------------
# GPU drawing
# ---------------------------------------------------------------------------

_draw_handle = None
_active = False

COM_RADIUS = 8
COM_SEGMENTS = 20
GROUND_RADIUS = 6
BALANCE_BAR_W = 120
BALANCE_BAR_H = 12


def _circle_verts_2d(cx, cy, r, segs=COM_SEGMENTS):
    verts = [(cx, cy)]
    for i in range(segs + 1):
        a = 2 * pi * i / segs
        verts.append((cx + r * cos(a), cy + r * sin(a)))
    return verts


def _circle_indices(segs=COM_SEGMENTS):
    return [(0, i, i + 1 if i < segs else 1) for i in range(1, segs + 1)]


def _ring_verts(cx, cy, r_out, r_in, segs=COM_SEGMENTS):
    verts = []
    for i in range(segs + 1):
        a = 2 * pi * i / segs
        verts.append((cx + r_out * cos(a), cy + r_out * sin(a)))
        verts.append((cx + r_in * cos(a), cy + r_in * sin(a)))
    return verts


def _ring_indices(segs=COM_SEGMENTS):
    indices = []
    for i in range(segs):
        o1, i1, o2, i2 = i * 2, i * 2 + 1, (i + 1) * 2, (i + 1) * 2 + 1
        indices.append((o1, i1, o2))
        indices.append((i1, i2, o2))
    return indices


def _world_to_screen(context, pos):
    from bpy_extras.view3d_utils import location_3d_to_region_2d
    region = context.region
    rv3d = context.space_data.region_3d
    if not region or not rv3d:
        return None
    return location_3d_to_region_2d(region, rv3d, pos)


def _draw_quad(shader, x1, y1, x2, y2, color):
    verts = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    batch = batch_for_shader(shader, 'TRIS', {"pos": verts},
                             indices=[(0, 1, 2), (0, 2, 3)])
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _draw_dashed_line(shader, sx, sy, ex, ey, color, dash=6, gap=4):
    total_len = ((ex - sx) ** 2 + (ey - sy) ** 2) ** 0.5
    if total_len < 2:
        return
    dx = (ex - sx) / total_len
    dy = (ey - sy) / total_len
    nx, ny = -dy * 1.0, dx * 1.0
    pos = 0
    while pos < total_len:
        end = min(pos + dash, total_len)
        x1 = sx + dx * pos
        y1 = sy + dy * pos
        x2 = sx + dx * end
        y2 = sy + dy * end
        verts = [(x1 + nx, y1 + ny), (x1 - nx, y1 - ny),
                 (x2 - nx, y2 - ny), (x2 + nx, y2 + ny)]
        batch = batch_for_shader(shader, 'TRIS', {"pos": verts},
                                 indices=[(0, 1, 2), (0, 2, 3)])
        shader.bind()
        shader.uniform_float("color", color)
        batch.draw(shader)
        pos += dash + gap


def _draw_com_callback(context):
    """GPU draw callback — CoM + BoS + balance."""
    if not _active:
        return

    obj = context.active_object
    if not obj or obj.type != 'ARMATURE' or obj.mode != 'POSE':
        return

    com, total = compute_center_of_mass(obj)
    if com is None:
        return

    # Get floor level from scan data if available
    sd = getattr(obj, 'bt_scan', None)
    floor_z = sd.floor_level if sd and hasattr(sd, 'floor_level') else 0.0

    # BoS
    bos_points = _get_bos_points(obj, floor_z)
    bos_hull = _convex_hull(bos_points) if len(bos_points) >= 3 else []

    # Balance
    stability = compute_balance(com, bos_hull) if bos_hull else 0.5
    bal_color = _balance_color(stability)
    bal_color_dim = _balance_color(stability, 0.15)

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')

    # --- Draw BoS polygon on ground plane ---
    if bos_hull and len(bos_hull) >= 3:
        hull_screen = []
        for hx, hy in bos_hull:
            s = _world_to_screen(context, Vector((hx, hy, floor_z)))
            if s:
                hull_screen.append(s)

        if len(hull_screen) >= 3:
            # Triangle fan from centroid
            cx_s = sum(p[0] for p in hull_screen) / len(hull_screen)
            cy_s = sum(p[1] for p in hull_screen) / len(hull_screen)
            fan_verts = [(cx_s, cy_s)]
            for p in hull_screen:
                fan_verts.append(p)
            fan_verts.append(hull_screen[0])  # close

            fan_indices = []
            for i in range(1, len(fan_verts) - 1):
                fan_indices.append((0, i, i + 1))

            batch = batch_for_shader(shader, 'TRIS', {"pos": fan_verts},
                                     indices=fan_indices)
            shader.bind()
            shader.uniform_float("color", bal_color_dim)
            batch.draw(shader)

            # BoS outline
            for i in range(len(hull_screen)):
                j = (i + 1) % len(hull_screen)
                sx1, sy1 = hull_screen[i]
                sx2, sy2 = hull_screen[j]
                _draw_dashed_line(shader, sx1, sy1, sx2, sy2,
                                  _balance_color(stability, 0.5), dash=8, gap=3)

    # --- Ground projection ---
    com_ground = Vector((com.x, com.y, floor_z))
    ground_screen = _world_to_screen(context, com_ground)
    com_screen = _world_to_screen(context, com)

    if not com_screen:
        gpu.state.blend_set('NONE')
        return

    sx, sy = com_screen

    # Drop line
    if ground_screen:
        gx, gy = ground_screen
        _draw_dashed_line(shader, sx, sy, gx, gy, _balance_color(stability, 0.3))

        # Ground projection dot
        verts = _circle_verts_2d(gx, gy, GROUND_RADIUS)
        batch = batch_for_shader(shader, 'TRIS', {"pos": verts},
                                 indices=_circle_indices())
        shader.bind()
        shader.uniform_float("color", _balance_color(stability, 0.5))
        batch.draw(shader)

    # --- CoM crosshair ---
    # Ring
    rv = _ring_verts(sx, sy, COM_RADIUS + 2, COM_RADIUS)
    batch = batch_for_shader(shader, 'TRIS', {"pos": rv},
                             indices=_ring_indices())
    shader.bind()
    shader.uniform_float("color", bal_color)
    batch.draw(shader)

    # Fill
    fv = _circle_verts_2d(sx, sy, COM_RADIUS)
    batch = batch_for_shader(shader, 'TRIS', {"pos": fv},
                             indices=_circle_indices())
    shader.bind()
    shader.uniform_float("color", _balance_color(stability, 0.5))
    batch.draw(shader)

    # Crosshair lines
    line_len = COM_RADIUS + 6
    for angle in (0, pi / 2, pi, 3 * pi / 2):
        x1 = sx + cos(angle) * (COM_RADIUS + 2)
        y1 = sy + sin(angle) * (COM_RADIUS + 2)
        x2 = sx + cos(angle) * line_len
        y2 = sy + sin(angle) * line_len
        nx = -sin(angle) * 1.0
        ny = cos(angle) * 1.0
        verts = [(x1 + nx, y1 + ny), (x1 - nx, y1 - ny),
                 (x2 - nx, y2 - ny), (x2 + nx, y2 + ny)]
        batch = batch_for_shader(shader, 'TRIS', {"pos": verts},
                                 indices=[(0, 1, 2), (0, 2, 3)])
        shader.bind()
        shader.uniform_float("color", bal_color)
        batch.draw(shader)

    # --- Balance indicator bar ---
    region = context.region
    if region:
        bar_x = region.width - BALANCE_BAR_W - 20
        bar_y = 20

        # Background
        _draw_quad(shader, bar_x - 2, bar_y - 2,
                   bar_x + BALANCE_BAR_W + 2, bar_y + BALANCE_BAR_H + 2,
                   (0, 0, 0, 0.5))

        # Gradient bar (10 segments)
        seg_w = BALANCE_BAR_W / 10
        for i in range(10):
            t = (i + 0.5) / 10
            c = _balance_color(t, 0.4)
            _draw_quad(shader, bar_x + i * seg_w, bar_y,
                       bar_x + (i + 1) * seg_w, bar_y + BALANCE_BAR_H, c)

        # Stability needle
        needle_t = max(0.0, min(1.0, stability))
        needle_x = bar_x + needle_t * BALANCE_BAR_W
        _draw_quad(shader, needle_x - 2, bar_y - 3,
                   needle_x + 2, bar_y + BALANCE_BAR_H + 3, (1, 1, 1, 0.9))

        # Label
        font_id = 0
        blf.size(font_id, 11)
        pct = max(0, int(stability * 100))
        label = f"Balance: {pct}%"
        w, _ = blf.dimensions(font_id, label)
        r, g, b, _ = bal_color
        blf.color(font_id, r, g, b, 1.0)
        blf.position(font_id, bar_x + BALANCE_BAR_W / 2 - w / 2,
                     bar_y + BALANCE_BAR_H + 6, 0)
        blf.draw(font_id, label)

    # CoM label
    font_id = 0
    blf.size(font_id, 12)
    label = "CoM"
    w, _ = blf.dimensions(font_id, label)
    r, g, b, _ = bal_color
    blf.color(font_id, r, g, b, 0.9)
    blf.position(font_id, sx - w / 2, sy + COM_RADIUS + 10, 0)
    blf.draw(font_id, label)

    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('NONE')

    if context.area:
        context.area.tag_redraw()


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class BT_OT_ToggleCOM(bpy.types.Operator):
    """Toggle Center of Mass + Balance visualization"""
    bl_idname = "bt.toggle_com"
    bl_label = "Center of Mass"
    bl_description = "Show/hide center of mass, base of support, and balance indicator"

    def execute(self, context):
        global _active, _draw_handle

        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Select an armature")
            return {'CANCELLED'}

        if _active:
            _active = False
            if _draw_handle:
                bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
                _draw_handle = None
            if context.area:
                context.area.tag_redraw()
            self.report({'INFO'}, "CoM display disabled")
        else:
            _sync_mass_items(obj)
            _detect_foot_bones(obj)
            _active = True
            _draw_handle = bpy.types.SpaceView3D.draw_handler_add(
                _draw_com_callback, (context,), 'WINDOW', 'POST_PIXEL'
            )
            if context.area:
                context.area.tag_redraw()
            self.report({'INFO'}, "CoM + Balance display enabled")

        return {'FINISHED'}


class BT_OT_RecalcCOMMasses(bpy.types.Operator):
    """Recalculate auto masses from mesh vertex weights"""
    bl_idname = "bt.recalc_com_masses"
    bl_label = "Recalculate Masses"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.active_object and context.active_object.type == 'ARMATURE')

    def execute(self, context):
        obj = context.active_object
        _sync_mass_items(obj)
        _detect_foot_bones(obj)
        self.report({'INFO'}, "Recalculated bone masses and foot bones")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class BT_PT_CenterOfMass(bpy.types.Panel):
    bl_label = "Center of Mass"
    bl_idname = "BT_PT_CenterOfMass"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = PANEL_CATEGORY
    bl_parent_id = "BT_PT_RiggingMain"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'ARMATURE'

    def draw_header(self, context):
        self.layout.label(text="", icon='ORIENTATION_CURSOR')

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        row = layout.row()
        row.operator(
            "bt.toggle_com",
            text="Show CoM" if not _active else "Hide CoM",
            icon='ORIENTATION_CURSOR',
            depress=_active,
        )

        if not _active:
            return

        row = layout.row()
        row.operator("bt.recalc_com_masses", icon='FILE_REFRESH')

        # Foot bones info
        if _foot_bones:
            box = layout.box()
            box.label(text=f"BoS: {len(_foot_bones)} contact bones", icon='SNAP_FACE')

        # Current CoM position
        com, total = compute_center_of_mass(obj)
        if com:
            box = layout.box()
            box.label(text=f"X: {com.x:.2f}  Y: {com.y:.2f}  Z: {com.z:.2f}")

        # Per-bone mass list
        items = obj.bt_com_masses
        if items:
            box = layout.box()
            box.label(text="Bone Masses", icon='BONE_DATA')
            box.separator(factor=0.3)
            col = box.column(align=True)
            for item in items:
                row = col.row(align=True)
                sub = row.row()
                sub.scale_x = 0.5
                sub.label(text=item.bone_name)
                row.prop(item, "use_custom", text="",
                         icon='PINNED' if item.use_custom else 'UNPINNED')
                if item.use_custom:
                    row.prop(item, "custom_mass", text="")
                else:
                    sub = row.row()
                    sub.enabled = False
                    sub.prop(item, "auto_mass", text="")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (
    BT_BoneMassItem,
    BT_OT_ToggleCOM,
    BT_OT_RecalcCOMMasses,
    BT_PT_CenterOfMass,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Object.bt_com_masses = CollectionProperty(type=BT_BoneMassItem)


def unregister():
    global _active, _draw_handle
    if _draw_handle:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None
    _active = False
    del bpy.types.Object.bt_com_masses
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
