"""Concrete widget classes for the viewport UI framework."""

import time

import gpu

from . import draw_primitives as dp
from . import theme as T
from .widget_base import Container, Widget

# ---------------------------------------------------------------------------
# Label
# ---------------------------------------------------------------------------

class Label(Widget):
    """Single-line text label."""

    __slots__ = ('text', 'size', 'color')

    def __init__(self, text, *, size=None, color=None, **kw):
        super().__init__(**kw)
        self.text = text
        self.size = size or T.FONT_SIZE
        self.color = color or T.TEXT_PRIMARY

    def measure(self, available_w):
        w, h = dp.text_dimensions(self.text, self.size)
        self._measured_w = w
        self._measured_h = max(h, self.size + 4)
        return (self._measured_w, self._measured_h)

    def draw(self, clip=None):
        if not self.visible:
            return
        dp.draw_text(self.text, self.x, self.y + 2, self.size, self.color)


# ---------------------------------------------------------------------------
# Separator
# ---------------------------------------------------------------------------

class Separator(Widget):
    """Horizontal line separator."""

    __slots__ = ('color', 'thickness')

    def __init__(self, *, color=None, thickness=1, **kw):
        super().__init__(**kw)
        self.color = color or T.SECTION_BORDER
        self.thickness = thickness

    def measure(self, available_w):
        self._measured_w = available_w
        self._measured_h = self.thickness + 4
        return (available_w, self._measured_h)

    def draw(self, clip=None):
        if not self.visible:
            return
        mid_y = self.y + self.height / 2
        dp.draw_quad(self.x, mid_y, self.x + self.width, mid_y + self.thickness,
                     self.color)


# ---------------------------------------------------------------------------
# Button
# ---------------------------------------------------------------------------

class Button(Widget):
    """Clickable button with text, hover animation, and style variants."""

    __slots__ = ('text', 'style', 'active', 'icon_text',
                 '_hover_t', '_hover_start', '_is_hovered')

    STYLE_DEFAULT = 'default'
    STYLE_PRIMARY = 'primary'
    STYLE_DANGER = 'danger'

    def __init__(self, text, *, style='default', active=False,
                 icon_text=None, **kw):
        super().__init__(**kw)
        self.text = text
        self.style = style
        self.active = active
        self.icon_text = icon_text  # prepended text/symbol
        self._hover_t = 0.0
        self._hover_start = 0.0
        self._is_hovered = False

    def measure(self, available_w):
        label = self._full_label()
        tw, th = dp.text_dimensions(label, T.FONT_SIZE)
        self._measured_w = tw + 20
        self._measured_h = T.BTN_HEIGHT
        return (self._measured_w, self._measured_h)

    def _full_label(self):
        if self.icon_text:
            return f"{self.icon_text} {self.text}"
        return self.text

    def draw(self, clip=None):
        if not self.visible:
            return
        # Hover animation
        now = time.monotonic()
        if self._is_hovered:
            dt = min(1.0, (now - self._hover_start) / 0.12)
            self._hover_t = dp.smoothstep(dt)
        else:
            self._hover_t = max(0, self._hover_t - 0.08)

        # Background color
        if self.style == self.STYLE_PRIMARY:
            bg = _lerp_color(T.BTN_PRIMARY, T.BTN_PRIMARY_HOVER, self._hover_t)
        elif self.active:
            bg = _lerp_color(T.BTN_ACTIVE, T.BTN_ACTIVE_HOVER, self._hover_t)
        else:
            bg = _lerp_color(T.BTN_BG, T.BTN_HOVER, self._hover_t)

        dp.draw_rounded_rect(self.x, self.y, self.width, self.height,
                             T.CORNER_RADIUS, bg)

        # Border
        if self.style == self.STYLE_DANGER:
            dp.draw_border(self.x, self.y, self.width, self.height,
                           T.BTN_DANGER_BORDER)

        # Text
        label = self._full_label()
        tw, th = dp.text_dimensions(label, T.FONT_SIZE)
        tx = self.x + (self.width - tw) / 2
        ty = self.y + (self.height - th) / 2
        text_color = T.BTN_DANGER_TEXT if self.style == self.STYLE_DANGER else T.TEXT_PRIMARY
        dp.draw_text(label, tx, ty, T.FONT_SIZE, text_color)

    def on_hover(self, mx, my):
        if not self._is_hovered:
            self._is_hovered = True
            self._hover_start = time.monotonic()

    def on_hover_exit(self):
        self._is_hovered = False


# ---------------------------------------------------------------------------
# IconButton
# ---------------------------------------------------------------------------

class IconButton(Widget):
    """Square button showing a single icon character or short text."""

    __slots__ = ('icon', 'active', '_is_hovered', '_hover_t', '_hover_start')

    def __init__(self, icon, *, active=False, **kw):
        super().__init__(**kw)
        self.icon = icon
        self.active = active
        self._is_hovered = False
        self._hover_t = 0.0
        self._hover_start = 0.0

    def measure(self, available_w):
        self._measured_w = T.BTN_ICON_SIZE
        self._measured_h = T.BTN_ICON_SIZE
        return (self._measured_w, self._measured_h)

    def draw(self, clip=None):
        if not self.visible:
            return
        now = time.monotonic()
        if self._is_hovered:
            dt = min(1.0, (now - self._hover_start) / 0.12)
            self._hover_t = dp.smoothstep(dt)
        else:
            self._hover_t = max(0, self._hover_t - 0.08)

        if self.active:
            bg = _lerp_color(T.BTN_ACTIVE, T.BTN_ACTIVE_HOVER, self._hover_t)
        else:
            bg = _lerp_color(T.BTN_BG, T.BTN_HOVER, self._hover_t)

        dp.draw_rounded_rect(self.x, self.y, self.width, self.height,
                             T.CORNER_RADIUS, bg)
        tw, th = dp.text_dimensions(self.icon, T.FONT_SIZE)
        tx = self.x + (self.width - tw) / 2
        ty = self.y + (self.height - th) / 2
        dp.draw_text(self.icon, tx, ty, T.FONT_SIZE, T.TEXT_PRIMARY)

    def on_hover(self, mx, my):
        if not self._is_hovered:
            self._is_hovered = True
            self._hover_start = time.monotonic()

    def on_hover_exit(self):
        self._is_hovered = False


# ---------------------------------------------------------------------------
# Toggle
# ---------------------------------------------------------------------------

class Toggle(Widget):
    """On/off pill toggle switch."""

    __slots__ = ('on', 'label_text')

    def __init__(self, label_text='', *, on=False, **kw):
        super().__init__(**kw)
        self.on = on
        self.label_text = label_text

    def measure(self, available_w):
        w = T.TOGGLE_WIDTH
        if self.label_text:
            tw, _ = dp.text_dimensions(self.label_text, T.FONT_SIZE)
            w += tw + 8
        self._measured_w = w
        self._measured_h = max(T.TOGGLE_HEIGHT, T.FONT_SIZE + 4)
        return (self._measured_w, self._measured_h)

    def draw(self, clip=None):
        if not self.visible:
            return
        # Track
        ty = self.y + (self.height - T.TOGGLE_HEIGHT) / 2
        track_color = T.TOGGLE_ON_BG if self.on else T.TOGGLE_OFF_BG
        dp.draw_rounded_rect(self.x, ty, T.TOGGLE_WIDTH, T.TOGGLE_HEIGHT,
                             T.TOGGLE_HEIGHT / 2, track_color)
        # Knob
        knob_r = T.TOGGLE_KNOB_RADIUS
        knob_x = (self.x + T.TOGGLE_WIDTH - knob_r - 2) if self.on else (self.x + knob_r + 2)
        knob_y = ty + T.TOGGLE_HEIGHT / 2
        knob_color = T.TOGGLE_KNOB_ON if self.on else T.TOGGLE_KNOB
        dp.draw_filled_circle(knob_x, knob_y, knob_r, knob_color)
        # Label
        if self.label_text:
            lx = self.x + T.TOGGLE_WIDTH + 8
            dp.draw_text(self.label_text, lx, self.y + 2, T.FONT_SIZE,
                         T.TEXT_PRIMARY)

    def on_click(self, mx, my):
        self.on = not self.on
        return self.action_id


# ---------------------------------------------------------------------------
# Slider
# ---------------------------------------------------------------------------

class Slider(Widget):
    """Horizontal slider with label and value display."""

    __slots__ = ('label_text', 'value', 'min_val', 'max_val', 'step',
                 '_dragging')

    def __init__(self, label_text, *, value=0.5, min_val=0.0, max_val=1.0,
                 step=0.01, **kw):
        super().__init__(**kw)
        self.label_text = label_text
        self.value = value
        self.min_val = min_val
        self.max_val = max_val
        self.step = step
        self._dragging = False

    def measure(self, available_w):
        self._measured_w = available_w
        self._measured_h = T.FONT_SIZE + T.SLIDER_TRACK_HEIGHT + 6
        return (available_w, self._measured_h)

    def draw(self, clip=None):
        if not self.visible:
            return
        # Label
        dp.draw_text(self.label_text, self.x, self.y + self.height - T.FONT_SIZE,
                     T.FONT_SIZE_SMALL, T.TEXT_SECONDARY)
        # Value text
        if self.max_val <= 1.0:
            val_text = f"{self.value:.2f}"
        else:
            val_text = f"{self.value:.1f}" if self.step < 1 else str(int(self.value))
        vw, _ = dp.text_dimensions(val_text, T.FONT_SIZE_SMALL)
        dp.draw_text(val_text, self.x + self.width - vw,
                     self.y + self.height - T.FONT_SIZE,
                     T.FONT_SIZE_SMALL, T.TEXT_SECONDARY)
        # Track
        track_y = self.y + 2
        dp.draw_rounded_rect(self.x, track_y, self.width, T.SLIDER_TRACK_HEIGHT,
                             T.SLIDER_TRACK_RADIUS, T.SLIDER_TRACK_BG)
        # Fill
        frac = (self.value - self.min_val) / max(self.max_val - self.min_val, 1e-6)
        fill_w = max(T.SLIDER_TRACK_RADIUS * 2, self.width * frac)
        dp.draw_rounded_rect(self.x, track_y, fill_w, T.SLIDER_TRACK_HEIGHT,
                             T.SLIDER_TRACK_RADIUS, T.SLIDER_FILL)

    def update_from_mouse(self, mx):
        """Update value based on mouse x position."""
        frac = (mx - self.x) / max(self.width, 1)
        frac = max(0.0, min(1.0, frac))
        raw = self.min_val + frac * (self.max_val - self.min_val)
        if self.step >= 1:
            self.value = max(self.min_val, min(self.max_val, round(raw)))
        else:
            self.value = max(self.min_val, min(self.max_val, round(raw / self.step) * self.step))
        return self.action_id


# ---------------------------------------------------------------------------
# TextField
# ---------------------------------------------------------------------------

class TextField(Widget):
    """Single-line text input field."""

    __slots__ = ('text', 'placeholder', 'focused', '_cursor_pos',
                 '_cursor_blink')

    def __init__(self, *, text='', placeholder='', **kw):
        super().__init__(**kw)
        self.text = text
        self.placeholder = placeholder
        self.focused = False
        self._cursor_pos = len(text)
        self._cursor_blink = 0.0

    def measure(self, available_w):
        self._measured_w = available_w
        self._measured_h = T.BTN_HEIGHT
        return (available_w, T.BTN_HEIGHT)

    def draw(self, clip=None):
        if not self.visible:
            return
        # Background
        bg = (0.12, 0.12, 0.12, 1.0) if self.focused else (0.14, 0.14, 0.14, 1.0)
        border = T.TAB_ACTIVE_BORDER if self.focused else T.SECTION_BORDER
        dp.draw_rounded_rect(self.x, self.y, self.width, self.height,
                             T.CORNER_RADIUS, bg)
        dp.draw_border(self.x, self.y, self.width, self.height, border)
        # Text or placeholder
        display = self.text if self.text else self.placeholder
        color = T.TEXT_PRIMARY if self.text else T.TEXT_LABEL
        dp.draw_text(display, self.x + 8, self.y + (self.height - T.FONT_SIZE) / 2,
                     T.FONT_SIZE, color)
        # Cursor
        if self.focused:
            now = time.monotonic()
            if int((now - self._cursor_blink) * 2) % 2 == 0:
                before = self.text[:self._cursor_pos]
                cw, _ = dp.text_dimensions(before, T.FONT_SIZE)
                cx = self.x + 8 + cw
                dp.draw_quad(cx, self.y + 4, cx + 1, self.y + self.height - 4,
                             T.TEXT_PRIMARY)

    def on_click(self, mx, my):
        self.focused = True
        self._cursor_blink = time.monotonic()
        self._cursor_pos = len(self.text)
        return self.action_id

    def handle_key(self, event_type, event_unicode):
        """Process a key event.  Returns True if handled."""
        if event_type == 'BACK_SPACE':
            if self._cursor_pos > 0:
                self.text = self.text[:self._cursor_pos - 1] + self.text[self._cursor_pos:]
                self._cursor_pos -= 1
            return True
        elif event_type == 'DEL':
            if self._cursor_pos < len(self.text):
                self.text = self.text[:self._cursor_pos] + self.text[self._cursor_pos + 1:]
            return True
        elif event_type == 'LEFT_ARROW':
            self._cursor_pos = max(0, self._cursor_pos - 1)
            return True
        elif event_type == 'RIGHT_ARROW':
            self._cursor_pos = min(len(self.text), self._cursor_pos + 1)
            return True
        elif event_type == 'HOME':
            self._cursor_pos = 0
            return True
        elif event_type == 'END':
            self._cursor_pos = len(self.text)
            return True
        elif event_type in ('RET', 'NUMPAD_ENTER'):
            self.focused = False
            return True
        elif event_type == 'ESC':
            self.focused = False
            return True
        elif event_unicode and len(event_unicode) == 1 and event_unicode.isprintable():
            self.text = self.text[:self._cursor_pos] + event_unicode + self.text[self._cursor_pos:]
            self._cursor_pos += 1
            return True
        return False


# ---------------------------------------------------------------------------
# Section (bordered box with optional header label)
# ---------------------------------------------------------------------------

class Section(Container):
    """Bordered box with optional section label, using VStack layout."""

    __slots__ = ('label_text', 'bg_color', 'border_color')

    def __init__(self, label_text='', children=None, **kw):
        kw.setdefault('padding', (T.PADDING_SMALL, T.PADDING_SMALL,
                                  T.PADDING_SMALL, T.PADDING_SMALL))
        kw.setdefault('gap', T.ITEM_GAP)
        super().__init__(children, **kw)
        self.label_text = label_text
        self.bg_color = T.SECTION_BG
        self.border_color = T.SECTION_BORDER

    def measure(self, available_w):
        pt, pr, pb, pl = self.padding
        inner_w = available_w - pl - pr
        header_h = 0
        if self.label_text:
            _, lh = dp.text_dimensions(self.label_text, T.FONT_SIZE_SECTION_LABEL)
            header_h = lh + 6
        total_h = header_h
        visible_count = 0
        for child in self.children:
            if not child.visible:
                continue
            cw, ch = child.measure(inner_w)
            child._measured_w = cw
            child._measured_h = ch
            total_h += ch
            visible_count += 1
        if visible_count > 0:
            total_h += self.gap * visible_count
        self._measured_w = available_w
        self._measured_h = total_h + pt + pb
        return (available_w, self._measured_h)

    def layout(self, x, y, w, h):
        super().layout(x, y, w, h)
        pt, pr, pb, pl = self.padding
        inner_w = w - pl - pr
        cy = y + h - pt
        if self.label_text:
            _, lh = dp.text_dimensions(self.label_text, T.FONT_SIZE_SECTION_LABEL)
            cy -= lh + 6
        for child in self.children:
            if not child.visible:
                continue
            ch = child._measured_h
            cy -= ch
            child.layout(x + pl, cy, inner_w, ch)
            cy -= self.gap

    def draw(self, clip=None):
        if not self.visible:
            return
        dp.draw_rounded_rect(self.x, self.y, self.width, self.height,
                             T.CORNER_RADIUS, self.bg_color)
        dp.draw_border(self.x, self.y, self.width, self.height,
                       self.border_color)
        if self.label_text:
            pt = self.padding[0]
            pl = self.padding[3]
            dp.draw_text(self.label_text, self.x + pl,
                         self.y + self.height - pt - T.FONT_SIZE_SECTION_LABEL,
                         T.FONT_SIZE_SECTION_LABEL, T.SECTION_LABEL_COLOR)
        for child in self.children:
            if child.visible:
                child.draw(clip)


# ---------------------------------------------------------------------------
# TabBar
# ---------------------------------------------------------------------------

class TabBar(Container):
    """Horizontal tab headers + content switching.

    Children should be added via ``add_tab(label, content_widget)``.
    """

    __slots__ = ('tabs', 'active_tab')

    def __init__(self, *, active_tab=0, **kw):
        super().__init__(**kw)
        self.tabs = []   # [(label, content_widget)]
        self.active_tab = active_tab

    def add_tab(self, label, content):
        """Add a tab with *label* and *content* widget."""
        self.tabs.append((label, content))
        self.children.append(content)

    def measure(self, available_w):
        # Tab headers
        header_h = T.TAB_HEIGHT
        # Measure active content
        content_h = 0
        for i, (_, content) in enumerate(self.tabs):
            content.visible = (i == self.active_tab)
            if i == self.active_tab:
                cw, ch = content.measure(available_w)
                content._measured_w = cw
                content._measured_h = ch
                content_h = ch
        self._measured_w = available_w
        self._measured_h = header_h + content_h + 2  # 2px border
        return (available_w, self._measured_h)

    def layout(self, x, y, w, h):
        super().layout(x, y, w, h)
        header_h = T.TAB_HEIGHT
        # Layout active content below headers
        content_y = y
        content_h = h - header_h - 2
        for i, (_, content) in enumerate(self.tabs):
            if i == self.active_tab:
                content.layout(x, content_y, w, content_h)
            else:
                content.visible = False

    def draw(self, clip=None):
        if not self.visible:
            return
        # Draw tab headers
        header_y = self.y + self.height - T.TAB_HEIGHT
        tab_count = len(self.tabs)
        if tab_count == 0:
            return
        tab_w = self.width / tab_count
        for i, (label, _) in enumerate(self.tabs):
            tx = self.x + i * tab_w
            is_active = (i == self.active_tab)
            # Tab background
            bg = (0.19, 0.19, 0.19, 1.0) if is_active else T.TAB_BG
            dp.draw_quad(tx, header_y, tx + tab_w, header_y + T.TAB_HEIGHT, bg)
            # Active indicator
            if is_active:
                dp.draw_quad(tx, header_y, tx + tab_w, header_y + 2,
                             T.TAB_ACTIVE_BORDER)
            # Label
            text_color = T.TAB_ACTIVE_TEXT if is_active else T.TAB_INACTIVE_TEXT
            tw, th = dp.text_dimensions(label, T.FONT_SIZE)
            lx = tx + (tab_w - tw) / 2
            ly = header_y + (T.TAB_HEIGHT - th) / 2
            dp.draw_text(label, lx, ly, T.FONT_SIZE, text_color)
        # Bottom border
        dp.draw_quad(self.x, header_y, self.x + self.width, header_y + 1,
                     T.TAB_BORDER)
        # Active content
        for i, (_, content) in enumerate(self.tabs):
            if i == self.active_tab and content.visible:
                content.draw(clip)

    def hit_test(self, mx, my):
        if not self.visible:
            return None
        if not (self.x <= mx <= self.x + self.width
                and self.y <= my <= self.y + self.height):
            return None
        # Check if click is in header area
        header_y = self.y + self.height - T.TAB_HEIGHT
        if my >= header_y:
            return self  # TabBar handles header clicks itself
        # Otherwise check active content
        for i, (_, content) in enumerate(self.tabs):
            if i == self.active_tab and content.visible:
                hit = content.hit_test(mx, my)
                if hit is not None:
                    return hit
        return self

    def on_click(self, mx, my):
        header_y = self.y + self.height - T.TAB_HEIGHT
        if my >= header_y and self.tabs:
            tab_w = self.width / len(self.tabs)
            idx = int((mx - self.x) / tab_w)
            idx = max(0, min(len(self.tabs) - 1, idx))
            self.active_tab = idx
            return f"tab_switch_{idx}"
        return None


# ---------------------------------------------------------------------------
# ScrollView
# ---------------------------------------------------------------------------

class ScrollView(Container):
    """Scrollable container that clips children to its bounds."""

    __slots__ = ('scroll_offset', 'content_height', 'max_height')

    def __init__(self, children=None, *, max_height=300, **kw):
        super().__init__(children, **kw)
        self.scroll_offset = 0.0
        self.content_height = 0.0
        self.max_height = max_height

    def measure(self, available_w):
        pt, pr, pb, pl = self.padding
        inner_w = available_w - pl - pr - T.SCROLLBAR_WIDTH
        total_h = 0
        visible_count = 0
        for child in self.children:
            if not child.visible:
                continue
            cw, ch = child.measure(inner_w)
            child._measured_w = cw
            child._measured_h = ch
            total_h += ch
            visible_count += 1
        if visible_count > 1:
            total_h += self.gap * (visible_count - 1)
        self.content_height = total_h + pt + pb
        display_h = min(self.max_height, self.content_height)
        self._measured_w = available_w
        self._measured_h = display_h
        return (available_w, display_h)

    def layout(self, x, y, w, h):
        super().layout(x, y, w, h)
        pt, pr, pb, pl = self.padding
        inner_w = w - pl - pr - T.SCROLLBAR_WIDTH
        # Clamp scroll
        max_scroll = max(0, self.content_height - h)
        self.scroll_offset = max(0, min(self.scroll_offset, max_scroll))
        # Layout children from top, offset by scroll
        cy = y + h - pt + self.scroll_offset
        for child in self.children:
            if not child.visible:
                continue
            ch = child._measured_h
            cy -= ch
            child.layout(x + pl, cy, inner_w, ch)
            cy -= self.gap

    def draw(self, clip=None):
        if not self.visible:
            return
        # Scissor clip
        gpu.state.scissor_test_set(True)
        gpu.state.scissor_set(int(self.x), int(self.y),
                              int(self.width), int(self.height))
        for child in self.children:
            if child.visible:
                # Skip children entirely outside view
                if child.y + child.height < self.y or child.y > self.y + self.height:
                    continue
                child.draw()
        gpu.state.scissor_test_set(False)
        # Scrollbar
        if self.content_height > self.height:
            self._draw_scrollbar()

    def _draw_scrollbar(self):
        sb_x = self.x + self.width - T.SCROLLBAR_WIDTH
        dp.draw_quad(sb_x, self.y, sb_x + T.SCROLLBAR_WIDTH,
                     self.y + self.height, T.SCROLLBAR_BG)
        # Thumb
        view_frac = self.height / max(self.content_height, 1)
        thumb_h = max(20, self.height * view_frac)
        scroll_frac = self.scroll_offset / max(self.content_height - self.height, 1)
        thumb_y = self.y + (self.height - thumb_h) * (1 - scroll_frac)
        dp.draw_rounded_rect(sb_x, thumb_y, T.SCROLLBAR_WIDTH, thumb_h,
                             T.SCROLLBAR_WIDTH / 2, T.SCROLLBAR_THUMB)

    def on_scroll(self, delta):
        """Handle scroll wheel.  *delta* is positive for scroll-up."""
        self.scroll_offset -= delta * 20
        max_scroll = max(0, self.content_height - self.height)
        self.scroll_offset = max(0, min(self.scroll_offset, max_scroll))

    def hit_test(self, mx, my):
        if not self.visible:
            return None
        if not (self.x <= mx <= self.x + self.width
                and self.y <= my <= self.y + self.height):
            return None
        for child in reversed(self.children):
            if not child.visible:
                continue
            hit = child.hit_test(mx, my)
            if hit is not None:
                return hit
        return self


# ---------------------------------------------------------------------------
# Collapsible
# ---------------------------------------------------------------------------

class Collapsible(Container):
    """Content that can be expanded/collapsed, triggered by a gear icon."""

    __slots__ = ('expanded', 'label_text')

    def __init__(self, label_text='', children=None, *, expanded=False, **kw):
        kw.setdefault('padding', (T.PADDING_SMALL, T.PADDING_SMALL,
                                  T.PADDING_SMALL, T.PADDING_SMALL))
        super().__init__(children, **kw)
        self.expanded = expanded
        self.label_text = label_text

    def measure(self, available_w):
        if not self.expanded:
            self._measured_w = 0
            self._measured_h = 0
            return (0, 0)
        pt, pr, pb, pl = self.padding
        inner_w = available_w - pl - pr
        header_h = 0
        if self.label_text:
            _, lh = dp.text_dimensions(self.label_text, T.FONT_SIZE_SECTION_LABEL)
            header_h = lh + 6
        total_h = header_h
        visible_count = 0
        for child in self.children:
            if not child.visible:
                continue
            cw, ch = child.measure(inner_w)
            child._measured_w = cw
            child._measured_h = ch
            total_h += ch
            visible_count += 1
        if visible_count > 0:
            total_h += self.gap * visible_count
        self._measured_w = available_w
        self._measured_h = total_h + pt + pb
        return (available_w, self._measured_h)

    def layout(self, x, y, w, h):
        if not self.expanded:
            self.x = x
            self.y = y
            self.width = 0
            self.height = 0
            return
        super().layout(x, y, w, h)
        pt, pr, pb, pl = self.padding
        inner_w = w - pl - pr
        cy = y + h - pt
        if self.label_text:
            _, lh = dp.text_dimensions(self.label_text, T.FONT_SIZE_SECTION_LABEL)
            cy -= lh + 6
        for child in self.children:
            if not child.visible:
                continue
            ch = child._measured_h
            cy -= ch
            child.layout(x + pl, cy, inner_w, ch)
            cy -= self.gap

    def draw(self, clip=None):
        if not self.expanded or not self.visible:
            return
        dp.draw_rounded_rect(self.x, self.y, self.width, self.height,
                             T.CORNER_RADIUS, T.SECTION_BG)
        dp.draw_border(self.x, self.y, self.width, self.height,
                       T.SECTION_BORDER)
        if self.label_text:
            pt = self.padding[0]
            pl = self.padding[3]
            dp.draw_text(self.label_text, self.x + pl,
                         self.y + self.height - pt - T.FONT_SIZE_SECTION_LABEL,
                         T.FONT_SIZE_SECTION_LABEL, T.SECTION_LABEL_COLOR)
        for child in self.children:
            if child.visible:
                child.draw(clip)

    def toggle(self):
        self.expanded = not self.expanded


# ---------------------------------------------------------------------------
# SectionBar (collapsible major section heading)
# ---------------------------------------------------------------------------

class SectionBar(Container):
    """Colored topbar with white title text — click to collapse/expand children.

    *section_key* identifies this section in ``panel_state.collapsed_sections``.
    Children are the content widgets shown below the bar when expanded.
    """

    __slots__ = ('section_key', 'label_text', '_is_hovered', '_hover_t',
                 '_hover_start')

    def __init__(self, label_text, section_key, children=None, **kw):
        kw.setdefault('padding', (0, 0, 0, 0))
        kw.setdefault('gap', T.ITEM_GAP)
        super().__init__(children, **kw)
        self.label_text = label_text
        self.section_key = section_key
        self._is_hovered = False
        self._hover_t = 0.0
        self._hover_start = 0.0

    @property
    def collapsed(self):
        from . import panel_state as state
        return self.section_key in state.collapsed_sections

    def measure(self, available_w):
        bar_h = T.SECTION_TOPBAR_HEIGHT
        if self.collapsed:
            self._measured_w = available_w
            self._measured_h = bar_h
            return (available_w, bar_h)
        # Measure children with body padding
        body_pad = T.PADDING
        inner_w = available_w - body_pad * 2
        total_h = bar_h + T.PADDING_SMALL  # top padding for body
        visible_count = 0
        for child in self.children:
            if not child.visible:
                continue
            cw, ch = child.measure(inner_w)
            child._measured_w = cw
            child._measured_h = ch
            total_h += ch
            visible_count += 1
        if visible_count > 0:
            total_h += self.gap * visible_count
        total_h += T.PADDING_SMALL  # bottom padding for body
        self._measured_w = available_w
        self._measured_h = total_h
        return (available_w, total_h)

    def layout(self, x, y, w, h):
        super().layout(x, y, w, h)
        if self.collapsed:
            return
        bar_h = T.SECTION_TOPBAR_HEIGHT
        body_pad = T.PADDING
        inner_w = w - body_pad * 2
        cy = y + h - bar_h - T.PADDING_SMALL
        for child in self.children:
            if not child.visible:
                continue
            ch = child._measured_h
            cy -= ch
            child.layout(x + body_pad, cy, inner_w, ch)
            cy -= self.gap

    def draw(self, clip=None):
        if not self.visible:
            return
        bar_h = T.SECTION_TOPBAR_HEIGHT
        bar_y = self.y + self.height - bar_h

        # Bar background with hover
        now = time.monotonic()
        if self._is_hovered:
            dt = min(1.0, (now - self._hover_start) / 0.12)
            self._hover_t = dp.smoothstep(dt)
        else:
            self._hover_t = max(0, self._hover_t - 0.08)
        bg = _lerp_color(T.SECTION_TOPBAR_BG, T.SECTION_TOPBAR_HOVER,
                         self._hover_t)
        dp.draw_quad(self.x, bar_y, self.x + self.width, bar_y + bar_h, bg)
        # Bottom border
        dp.draw_quad(self.x, bar_y, self.x + self.width, bar_y + 1,
                     T.SECTION_TOPBAR_BORDER)

        # Title text
        dp.draw_text(self.label_text, self.x + 12,
                     bar_y + (bar_h - T.FONT_SIZE) / 2,
                     T.FONT_SIZE, T.SECTION_TOPBAR_TEXT)

        # Collapse arrow
        arrow = "\u25B6" if self.collapsed else "\u25BC"  # right or down
        aw, _ = dp.text_dimensions(arrow, T.FONT_SIZE_SMALL)
        dp.draw_text(arrow, self.x + self.width - aw - 10,
                     bar_y + (bar_h - T.FONT_SIZE_SMALL) / 2,
                     T.FONT_SIZE_SMALL, T.SECTION_TOPBAR_ARROW)

        # Draw children if expanded
        if not self.collapsed:
            for child in self.children:
                if child.visible:
                    child.draw(clip)

    def hit_test(self, mx, my):
        if not self.visible:
            return None
        if not (self.x <= mx <= self.x + self.width
                and self.y <= my <= self.y + self.height):
            return None
        bar_h = T.SECTION_TOPBAR_HEIGHT
        bar_y = self.y + self.height - bar_h
        # Click on bar itself
        if my >= bar_y:
            return self
        # Check children
        if not self.collapsed:
            for child in reversed(self.children):
                if not child.visible:
                    continue
                hit = child.hit_test(mx, my)
                if hit is not None:
                    return hit
        return self

    def on_click(self, mx, my):
        bar_h = T.SECTION_TOPBAR_HEIGHT
        bar_y = self.y + self.height - bar_h
        if my >= bar_y:
            return f"section_toggle_{self.section_key}"
        return None

    def on_hover(self, mx, my):
        bar_h = T.SECTION_TOPBAR_HEIGHT
        bar_y = self.y + self.height - bar_h
        if my >= bar_y and not self._is_hovered:
            self._is_hovered = True
            self._hover_start = time.monotonic()

    def on_hover_exit(self):
        self._is_hovered = False


# ---------------------------------------------------------------------------
# SubsectionTitle (collapsible sub-heading with indented content)
# ---------------------------------------------------------------------------

class SubsectionTitle(Container):
    """Clickable subsection heading — content underneath is indented.

    *section_key* identifies this subsection in
    ``panel_state.collapsed_sections``.
    """

    __slots__ = ('section_key', 'label_text', '_is_hovered')

    def __init__(self, label_text, section_key, children=None, **kw):
        kw.setdefault('padding', (0, 0, 0, 0))
        kw.setdefault('gap', T.ITEM_GAP)
        super().__init__(children, **kw)
        self.label_text = label_text
        self.section_key = section_key
        self._is_hovered = False

    @property
    def collapsed(self):
        from . import panel_state as state
        return self.section_key in state.collapsed_sections

    def measure(self, available_w):
        header_h = T.SUBSECTION_HEIGHT
        if self.collapsed:
            self._measured_w = available_w
            self._measured_h = header_h
            return (available_w, header_h)
        indent = T.SUBSECTION_INDENT
        inner_w = available_w - indent
        total_h = header_h
        visible_count = 0
        for child in self.children:
            if not child.visible:
                continue
            cw, ch = child.measure(inner_w)
            child._measured_w = cw
            child._measured_h = ch
            total_h += ch
            visible_count += 1
        if visible_count > 0:
            total_h += self.gap * visible_count
        self._measured_w = available_w
        self._measured_h = total_h
        return (available_w, total_h)

    def layout(self, x, y, w, h):
        super().layout(x, y, w, h)
        if self.collapsed:
            return
        header_h = T.SUBSECTION_HEIGHT
        indent = T.SUBSECTION_INDENT
        inner_w = w - indent
        cy = y + h - header_h
        for child in self.children:
            if not child.visible:
                continue
            ch = child._measured_h
            cy -= ch
            child.layout(x + indent, cy, inner_w, ch)
            cy -= self.gap

    def draw(self, clip=None):
        if not self.visible:
            return
        header_h = T.SUBSECTION_HEIGHT
        header_y = self.y + self.height - header_h

        # Arrow
        arrow = "\u25B6" if self.collapsed else "\u25BC"
        text_color = T.SUBSECTION_HOVER if self._is_hovered else T.SUBSECTION_TEXT
        dp.draw_text(arrow, self.x, header_y + (header_h - T.FONT_SIZE_SMALL) / 2,
                     T.FONT_SIZE_SMALL - 1, T.SUBSECTION_ARROW)
        # Label
        dp.draw_text(self.label_text.upper(), self.x + 14,
                     header_y + (header_h - T.FONT_SIZE_SMALL) / 2,
                     T.FONT_SIZE_SMALL, text_color)

        # Draw children if expanded
        if not self.collapsed:
            for child in self.children:
                if child.visible:
                    child.draw(clip)

    def hit_test(self, mx, my):
        if not self.visible:
            return None
        if not (self.x <= mx <= self.x + self.width
                and self.y <= my <= self.y + self.height):
            return None
        header_h = T.SUBSECTION_HEIGHT
        header_y = self.y + self.height - header_h
        if my >= header_y:
            return self
        if not self.collapsed:
            for child in reversed(self.children):
                if not child.visible:
                    continue
                hit = child.hit_test(mx, my)
                if hit is not None:
                    return hit
        return self

    def on_click(self, mx, my):
        header_h = T.SUBSECTION_HEIGHT
        header_y = self.y + self.height - header_h
        if my >= header_y:
            return f"section_toggle_{self.section_key}"
        return None

    def on_hover(self, mx, my):
        header_h = T.SUBSECTION_HEIGHT
        header_y = self.y + self.height - header_h
        if my >= header_y:
            self._is_hovered = True

    def on_hover_exit(self):
        self._is_hovered = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lerp_color(c1, c2, t):
    """Linearly interpolate between two RGBA colour tuples."""
    return tuple(dp.lerp(a, b, t) for a, b in zip(c1, c2))
