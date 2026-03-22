"""Global state for the viewport panel."""

# Panel visibility and position
visible = False
position = None   # (x, y) top-left in screen coords; None = auto-anchor
width = 300

# Interaction state
hover_widget = None
prev_hover_widget = None
focus_widget = None     # TextField currently focused
dragging_panel = False
drag_offset = (0, 0)
dragging_slider = None  # Slider widget being dragged

# Content state
expanded_gears = set()       # action_ids of expanded collapsible sections
active_tabs = {}             # {tab_bar_id: int}
collapsed_sections = set()   # section keys that are collapsed (default: expanded)
hidden_sections = set()      # subsystem names hidden via Controls icon toggles

# Dropdown overlay state — when a Dropdown is expanded, its popup renders here
active_dropdown = None  # Dropdown widget reference (or None)

# Rebuild flag — set True when Blender state changes require content rebuild
dirty = True

# The area where the panel was invoked (render only in this area)
invoke_area = None


def reset():
    """Reset all state to defaults."""
    global visible, position, hover_widget, prev_hover_widget
    global focus_widget, dragging_panel, drag_offset, dragging_slider
    global expanded_gears, active_tabs, collapsed_sections, hidden_sections
    global active_dropdown, dirty, invoke_area

    visible = False
    position = None
    hover_widget = None
    prev_hover_widget = None
    focus_widget = None
    dragging_panel = False
    drag_offset = (0, 0)
    dragging_slider = None
    expanded_gears = set()
    active_tabs = {}
    collapsed_sections = set()
    hidden_sections = set()
    active_dropdown = None
    dirty = True
    invoke_area = None


def get_panel_rect(region):
    """Return (x, y, w, h) for the panel — y is bottom edge."""
    global position
    if position is None:
        # Auto-anchor: top-right
        from . import theme as T
        px = region.width - width - T.PANEL_MARGIN
        py = region.height - T.PANEL_MARGIN
        position = (px, py)
    x, top_y = position
    # top_y is the top of the panel; we need height to compute bottom y
    # but height depends on content — return x and top_y for now
    return x, top_y
