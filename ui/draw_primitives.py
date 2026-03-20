"""Shared GPU drawing primitives for the viewport UI framework.

Consolidates drawing helpers previously duplicated across ik_overlay,
viewport_overlay, trajectory, center_of_mass, bone_naming, and onion_skin.
"""

import math

import blf
import gpu
from gpu_extras.batch import batch_for_shader

# Cache the shader — created once per Blender session.
_shader = None


def _get_shader():
    global _shader
    if _shader is None:
        _shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    return _shader


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------

def smoothstep(t):
    """Hermite smoothstep interpolation, clamped to [0, 1]."""
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def lerp(a, b, t):
    """Linear interpolation between *a* and *b*."""
    return a + (b - a) * t


# ---------------------------------------------------------------------------
# Quad / Rectangle
# ---------------------------------------------------------------------------

def draw_quad(x1, y1, x2, y2, color, shader=None):
    """Draw a filled axis-aligned rectangle."""
    sh = shader or _get_shader()
    verts = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    batch = batch_for_shader(sh, 'TRIS', {"pos": verts},
                             indices=[(0, 1, 2), (0, 2, 3)])
    sh.bind()
    sh.uniform_float("color", color)
    batch.draw(sh)


def draw_rounded_rect(x, y, w, h, radius, color, shader=None):
    """Draw a filled rectangle with rounded corners.

    *x*, *y* is the bottom-left corner.  *radius* is clamped so it
    never exceeds half the width or height.
    """
    sh = shader or _get_shader()
    r = min(radius, w / 2, h / 2)
    if r < 1:
        draw_quad(x, y, x + w, y + h, color, sh)
        return

    segments = 6  # per corner
    verts = []

    # Corner centres (bottom-left, bottom-right, top-right, top-left)
    corners = [
        (x + r, y + r),
        (x + w - r, y + r),
        (x + w - r, y + h - r),
        (x + r, y + h - r),
    ]
    start_angles = [math.pi, 1.5 * math.pi, 0, 0.5 * math.pi]

    for ci, (cx, cy) in enumerate(corners):
        a0 = start_angles[ci]
        for i in range(segments + 1):
            a = a0 + (math.pi / 2) * i / segments
            verts.append((cx + r * math.cos(a), cy + r * math.sin(a)))

    # Centre point for triangle fan
    cx = x + w / 2
    cy = y + h / 2
    center_idx = len(verts)
    verts.append((cx, cy))

    n = len(verts) - 1  # last perimeter index
    indices = []
    for i in range(n):
        indices.append((center_idx, i, (i + 1) % n))

    batch = batch_for_shader(sh, 'TRIS', {"pos": verts}, indices=indices)
    sh.bind()
    sh.uniform_float("color", color)
    batch.draw(sh)


def draw_border(x, y, w, h, color, thickness=1, shader=None):
    """Draw a rectangular border (outline only)."""
    t = thickness
    # bottom
    draw_quad(x, y, x + w, y + t, color, shader)
    # top
    draw_quad(x, y + h - t, x + w, y + h, color, shader)
    # left
    draw_quad(x, y + t, x + t, y + h - t, color, shader)
    # right
    draw_quad(x + w - t, y + t, x + w, y + h - t, color, shader)


# ---------------------------------------------------------------------------
# Circle / Ring
# ---------------------------------------------------------------------------

def circle_verts_2d(cx, cy, r, segments=24):
    """Generate triangle-fan vertices for a filled 2-D circle."""
    verts = [(cx, cy)]
    for i in range(segments + 1):
        a = 2 * math.pi * i / segments
        verts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return verts


def circle_indices(segments=24):
    """Triangle-fan indices for a circle with *segments* edges."""
    return [(0, i, i + 1) for i in range(1, segments + 1)]


def draw_filled_circle(cx, cy, radius, color, segments=24, shader=None):
    """Draw a filled circle centred at *(cx, cy)*."""
    sh = shader or _get_shader()
    verts = circle_verts_2d(cx, cy, radius, segments)
    indices = circle_indices(segments)
    batch = batch_for_shader(sh, 'TRIS', {"pos": verts}, indices=indices)
    sh.bind()
    sh.uniform_float("color", color)
    batch.draw(sh)


def ring_verts_2d(cx, cy, r_outer, r_inner, segments=24):
    """Generate triangle-strip vertices for a ring (thick outline)."""
    verts = []
    for i in range(segments + 1):
        a = 2 * math.pi * i / segments
        cos_a = math.cos(a)
        sin_a = math.sin(a)
        verts.append((cx + r_outer * cos_a, cy + r_outer * sin_a))
        verts.append((cx + r_inner * cos_a, cy + r_inner * sin_a))
    return verts


def ring_indices(segments=24):
    """Triangle-strip indices for a ring."""
    indices = []
    for i in range(segments):
        j = i * 2
        indices.append((j, j + 1, j + 2))
        indices.append((j + 1, j + 3, j + 2))
    return indices


def draw_ring(cx, cy, r_outer, r_inner, color, segments=24, shader=None):
    """Draw a ring (thick circle outline)."""
    sh = shader or _get_shader()
    verts = ring_verts_2d(cx, cy, r_outer, r_inner, segments)
    indices = ring_indices(segments)
    batch = batch_for_shader(sh, 'TRIS', {"pos": verts}, indices=indices)
    sh.bind()
    sh.uniform_float("color", color)
    batch.draw(sh)


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

def text_dimensions(text, size=12):
    """Measure text width and height at the given *size* (points)."""
    font_id = 0
    blf.size(font_id, size)
    return blf.dimensions(font_id, text)


def draw_text(text, x, y, size=12, color=(1, 1, 1, 1)):
    """Draw a text string at *(x, y)* with the given size and colour."""
    font_id = 0
    blf.size(font_id, size)
    blf.color(font_id, *color)
    blf.position(font_id, x, y, 0)
    blf.draw(font_id, text)


def draw_text_with_bg(text, x, y, size=12, text_color=(1, 1, 1, 1),
                      bg_color=(0, 0, 0, 0.5), padding=5, shader=None):
    """Draw text with a background rectangle behind it."""
    w, h = text_dimensions(text, size)
    draw_quad(x - padding, y - 4,
              x + w + padding, y + h + 4,
              bg_color, shader)
    draw_text(text, x, y, size, text_color)


# ---------------------------------------------------------------------------
# Lines
# ---------------------------------------------------------------------------

def draw_line(x1, y1, x2, y2, color, width=1.0, shader=None):
    """Draw a line segment between two points."""
    sh = shader or _get_shader()
    gpu.state.line_width_set(width)
    batch = batch_for_shader(sh, 'LINES', {"pos": [(x1, y1), (x2, y2)]})
    sh.bind()
    sh.uniform_float("color", color)
    batch.draw(sh)
    gpu.state.line_width_set(1.0)


# ---------------------------------------------------------------------------
# GPU state helpers
# ---------------------------------------------------------------------------

def setup_gpu_state():
    """Set standard GPU state for 2-D overlay drawing."""
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')


def restore_gpu_state():
    """Restore GPU state after overlay drawing."""
    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('NONE')


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------

def world_to_screen(context, world_pos):
    """Project a 3-D world position to 2-D screen coordinates.

    Returns *(x, y)* in pixels or *None* if the point is behind the camera.
    """
    from bpy_extras.view3d_utils import location_3d_to_region_2d
    region = context.region
    rv3d = context.region_data
    if not region or not rv3d:
        return None
    return location_3d_to_region_2d(region, rv3d, world_pos)
