"""Base widget classes and container layouts for the viewport UI framework."""

from . import theme as T

# ---------------------------------------------------------------------------
# Widget base
# ---------------------------------------------------------------------------

class Widget:
    """Base class for all viewport UI widgets.

    Lifecycle:
      1. ``measure(available_w)`` — compute natural (width, height).
      2. ``layout(x, y, w, h)``  — assigned position and final size.
      3. ``draw(clip)``          — render via GPU.
      4. ``hit_test(mx, my)``    — return self or child under cursor.
    """

    __slots__ = (
        'x', 'y', 'width', 'height',
        'visible', 'action_id', 'flex', 'tooltip',
        '_measured_w', '_measured_h',
    )

    def __init__(self, *, visible=True, action_id=None, flex=0, tooltip=None):
        self.x = 0.0
        self.y = 0.0
        self.width = 0.0
        self.height = 0.0
        self.visible = visible
        self.action_id = action_id
        self.flex = flex  # grow factor for HStack
        self.tooltip = tooltip
        self._measured_w = 0.0
        self._measured_h = 0.0

    # -- Lifecycle ----------------------------------------------------------

    def measure(self, available_w):
        """Return (width, height) this widget needs."""
        return (0, 0)

    def layout(self, x, y, w, h):
        """Assign final position and size."""
        self.x = x
        self.y = y
        self.width = w
        self.height = h

    def draw(self, clip=None):
        """Render via GPU.  *clip* is (x, y, w, h) or None."""
        pass

    def hit_test(self, mx, my):
        """Return the deepest widget under (mx, my) or None."""
        if not self.visible:
            return None
        if (self.x <= mx <= self.x + self.width
                and self.y <= my <= self.y + self.height):
            return self
        return None

    def on_click(self, mx, my):
        """Handle a click.  Return an action_id string or None."""
        return self.action_id

    def on_hover(self, mx, my):
        """Called every frame the cursor is over this widget."""
        pass


# ---------------------------------------------------------------------------
# Container base
# ---------------------------------------------------------------------------

class Container(Widget):
    """Widget that holds children."""

    __slots__ = ('children', 'padding', 'gap')

    def __init__(self, children=None, *, padding=None, gap=None, **kw):
        super().__init__(**kw)
        self.children = list(children) if children else []
        self.padding = padding if padding is not None else (0, 0, 0, 0)
        self.gap = gap if gap is not None else T.ITEM_GAP

    def _inner_rect(self):
        """Return (x, y, w, h) after subtracting padding."""
        pt, pr, pb, pl = self.padding
        return (self.x + pl, self.y + pb,
                self.width - pl - pr, self.height - pt - pb)

    def hit_test(self, mx, my):
        if not self.visible:
            return None
        if not (self.x <= mx <= self.x + self.width
                and self.y <= my <= self.y + self.height):
            return None
        # Check children in reverse (top-most drawn last)
        for child in reversed(self.children):
            if not child.visible:
                continue
            hit = child.hit_test(mx, my)
            if hit is not None:
                return hit
        return self


# ---------------------------------------------------------------------------
# VStack — vertical stacking (top to bottom)
# ---------------------------------------------------------------------------

class VStack(Container):
    """Stack children vertically, top child first.

    In screen coords the first child is at the top (highest y).
    """

    def measure(self, available_w):
        pt, pr, pb, pl = self.padding
        inner_w = available_w - pl - pr
        total_h = 0
        max_w = 0
        visible_count = 0
        for child in self.children:
            if not child.visible:
                continue
            cw, ch = child.measure(inner_w)
            child._measured_w = cw
            child._measured_h = ch
            max_w = max(max_w, cw)
            total_h += ch
            visible_count += 1
        if visible_count > 1:
            total_h += self.gap * (visible_count - 1)
        self._measured_w = max_w + pl + pr
        self._measured_h = total_h + pt + pb
        return (available_w, self._measured_h)

    def layout(self, x, y, w, h):
        super().layout(x, y, w, h)
        pt, pr, pb, pl = self.padding
        inner_w = w - pl - pr
        # Start from top
        cy = y + h - pt
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
        for child in self.children:
            if child.visible:
                child.draw(clip)


# ---------------------------------------------------------------------------
# HStack — horizontal stacking with optional auto-wrap
# ---------------------------------------------------------------------------

class HStack(Container):
    """Stack children horizontally.  If ``wrap=True``, wraps to the
    next row when children exceed available width."""

    __slots__ = ('wrap', 'align')

    def __init__(self, children=None, *, wrap=False, align='center', **kw):
        super().__init__(children, **kw)
        self.wrap = wrap
        self.align = align  # 'top', 'center', 'bottom'

    def measure(self, available_w):
        pt, pr, pb, pl = self.padding
        inner_w = available_w - pl - pr

        if self.wrap:
            return self._measure_wrap(inner_w, pl, pr, pt, pb, available_w)

        total_w = 0
        max_h = 0
        visible = [c for c in self.children if c.visible]
        flex_total = 0
        for child in visible:
            cw, ch = child.measure(inner_w)
            child._measured_w = cw
            child._measured_h = ch
            total_w += cw
            max_h = max(max_h, ch)
            flex_total += child.flex
        if len(visible) > 1:
            total_w += self.gap * (len(visible) - 1)
        self._measured_w = total_w + pl + pr
        self._measured_h = max_h + pt + pb
        return (available_w, self._measured_h)

    def _measure_wrap(self, inner_w, pl, pr, pt, pb, available_w):
        row_w = 0
        row_h = 0
        total_h = 0
        row_count = 0
        for child in self.children:
            if not child.visible:
                continue
            cw, ch = child.measure(inner_w)
            child._measured_w = cw
            child._measured_h = ch
            if row_w > 0 and row_w + self.gap + cw > inner_w:
                # Wrap
                total_h += row_h + self.gap
                row_w = cw
                row_h = ch
                row_count += 1
            else:
                if row_w > 0:
                    row_w += self.gap
                row_w += cw
                row_h = max(row_h, ch)
                if row_count == 0:
                    row_count = 1
        total_h += row_h
        self._measured_w = available_w
        self._measured_h = total_h + pt + pb
        return (available_w, self._measured_h)

    def layout(self, x, y, w, h):
        super().layout(x, y, w, h)
        pt, pr, pb, pl = self.padding
        inner_w = w - pl - pr

        if self.wrap:
            self._layout_wrap(x + pl, y, inner_w, h, pt, pb)
            return

        visible = [c for c in self.children if c.visible]
        if not visible:
            return

        # Distribute flex space
        fixed_w = sum(c._measured_w for c in visible)
        gap_total = self.gap * max(0, len(visible) - 1)
        remaining = inner_w - fixed_w - gap_total
        flex_total = sum(c.flex for c in visible)

        cx = x + pl
        row_h = h - pt - pb
        for child in visible:
            cw = child._measured_w
            if flex_total > 0 and child.flex > 0 and remaining > 0:
                cw += remaining * (child.flex / flex_total)
            ch = child._measured_h
            # Vertical alignment
            if self.align == 'top':
                cy = y + h - pt - ch
            elif self.align == 'bottom':
                cy = y + pb
            else:
                cy = y + pb + (row_h - ch) / 2
            child.layout(cx, cy, cw, ch)
            cx += cw + self.gap

    def _layout_wrap(self, start_x, y, inner_w, h, pt, pb):
        rows = []
        row = []
        row_w = 0
        row_h = 0
        for child in self.children:
            if not child.visible:
                continue
            cw = child._measured_w
            if row and row_w + self.gap + cw > inner_w:
                rows.append((row, row_h))
                row = [child]
                row_w = cw
                row_h = child._measured_h
            else:
                if row:
                    row_w += self.gap
                row.append(child)
                row_w += cw
                row_h = max(row_h, child._measured_h)
        if row:
            rows.append((row, row_h))

        # Layout from top
        cy = y + h - pt
        for row_children, rh in rows:
            cy -= rh
            cx = start_x
            for child in row_children:
                child.layout(cx, cy, child._measured_w, rh)
                cx += child._measured_w + self.gap
            cy -= self.gap

    def draw(self, clip=None):
        if not self.visible:
            return
        for child in self.children:
            if child.visible:
                child.draw(clip)
