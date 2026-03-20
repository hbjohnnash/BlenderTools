"""Layout engine — measure, position, and draw a widget tree."""

import gpu


def measure_tree(root, available_w):
    """Recursively compute natural sizes for the entire widget tree."""
    return root.measure(available_w)


def position_tree(root, x, y, w, h):
    """Recursively assign positions to the entire widget tree."""
    root.layout(x, y, w, h)


def draw_tree(root, clip=None):
    """Recursively draw the widget tree with optional scissor clipping."""
    if clip:
        _draw_clipped(root, clip)
    else:
        root.draw()


def _draw_clipped(root, clip):
    """Draw with GPU scissor test for the given clip rect."""
    x, y, w, h = clip
    # Scissor coords are in framebuffer pixels (may differ from region pixels
    # on HiDPI).  For simplicity we pass through — Blender's POST_PIXEL
    # callback already maps 1:1 on most setups.
    gpu.state.scissor_test_set(True)
    gpu.state.scissor_set(int(x), int(y), int(w), int(h))
    root.draw(clip)
    gpu.state.scissor_test_set(False)
