"""Global state for the viewport panel."""

# Panel visibility and position
visible = False
position = None   # (x, y) top-left in screen coords when floating
docked = True     # True = attached to right-center; False = floating (user-dragged)
width = 300

# Interaction state
hover_widget = None
prev_hover_widget = None
focus_widget = None     # TextField currently focused
dragging_panel = False
drag_offset = (0, 0)
dragging_slider = None      # Slider widget being dragged
dragging_scrollbar = None   # ScrollView being scrollbar-dragged

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
    global visible, position, docked, hover_widget, prev_hover_widget
    global focus_widget, dragging_panel, drag_offset, dragging_slider, dragging_scrollbar
    global expanded_gears, active_tabs, collapsed_sections, hidden_sections
    global active_dropdown, dirty, invoke_area

    visible = False
    position = None
    docked = True
    hover_widget = None
    prev_hover_widget = None
    focus_widget = None
    dragging_panel = False
    drag_offset = (0, 0)
    dragging_slider = None
    dragging_scrollbar = None
    expanded_gears = set()
    active_tabs = {}
    collapsed_sections = set()
    hidden_sections = set()
    active_dropdown = None
    dirty = True
    invoke_area = None


def get_panel_rect(region, total_h):
    """Return (x, top_y) for the panel top-left corner.

    When docked, computes right-center position every frame.
    When floating, uses stored position clamped to viewport bounds.
    """
    from . import theme as T

    top_limit = region.height - T.PANEL_MARGIN_TOP
    bot_limit = total_h + T.PANEL_MARGIN

    if docked:
        # Right-center anchor — centered in usable area, recalculated every frame
        px = region.width - width - T.PANEL_MARGIN
        usable_center = T.PANEL_MARGIN + (region.height - T.PANEL_MARGIN_TOP - T.PANEL_MARGIN) / 2
        top_y = min(max(usable_center + total_h / 2, bot_limit), top_limit)
        return px, top_y

    # Floating — use stored position, clamped to viewport bounds
    if position is None:
        px = region.width - width - T.PANEL_MARGIN
        top_y = region.height / 2 + total_h / 2
    else:
        px, top_y = position
    top_y = min(max(top_y, bot_limit), top_limit)
    px = max(T.PANEL_MARGIN, min(px, region.width - width - T.PANEL_MARGIN))
    return px, top_y
