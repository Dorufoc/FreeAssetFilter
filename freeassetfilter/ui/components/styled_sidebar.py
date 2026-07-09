"""Styled Sidebar component - matches web sidebar exactly."""

from theme import tm
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QFrame, QScrollBar,
    QGraphicsOpacityEffect, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QPoint, QSize, Property, QParallelAnimationGroup, QAbstractAnimation
from PySide6.QtGui import QPainter, QColor, QPaintEvent, QMouseEvent, QPen, QPolygonF
from PySide6.QtCore import QPropertyAnimation, QEasingCurve
import math


class SidebarScrollBar(QScrollBar):
    """Custom drawn scrollbar with rounded corners."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setSingleStep(20)
        self.setPageStep(100)
        self._hovered = False

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def sizeHint(self):
        return QSize(4, 100)

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)

            if self.orientation() == Qt.Vertical:
                # Calculate handle rect manually
                if self.maximum() > 0:
                    ratio = self.pageStep() / (self.maximum() + self.pageStep())
                    handle_height = max(30, int(self.height() * ratio))
                    handle_y = int(self.height() * self.sliderPosition() / self.maximum())
                    handle_y = min(handle_y, self.height() - handle_height)
                else:
                    handle_height = self.height()
                    handle_y = 0

                handle_rect = QRectF(0, float(handle_y), 4.0, float(handle_height))

                # Draw rounded handle
                painter.setBrush(tm.alpha_of(tm.mid, 40))
                r = 2.0
                painter.drawRoundedRect(handle_rect, r, r)
        finally:
            painter.end()


class ContentScrollBar(QScrollBar):
    """Custom scrollbar that expands on hover with rounded corners.
    
    Default width: 2px (barely visible thin line)
    Hover width: 8px (fully visible for interaction)
    
    Always reserves 8px space so mouse can trigger hover events.
    """

    DEFAULT_WIDTH = 2.0
    HOVER_WIDTH = 8.0
    RESERVED_WIDTH = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self._hovered = False
        self.setMouseTracking(True)

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def sizeHint(self):
        return QSize(self.RESERVED_WIDTH, 100)

    def _get_handle_rect(self):
        """Get the visual handle rect in widget coordinates."""
        if self.maximum() > 0:
            ratio = self.pageStep() / (self.maximum() + self.pageStep())
            handle_height = max(30, int(self.height() * ratio))
            handle_y = int(self.height() * self.sliderPosition() / self.maximum())
            handle_y = min(handle_y, self.height() - handle_height)
        else:
            handle_height = self.height()
            handle_y = 0

        width = self.HOVER_WIDTH if self._hovered else self.DEFAULT_WIDTH
        x_offset = self.RESERVED_WIDTH - width
        return QRectF(float(x_offset), float(handle_y), width, float(handle_height))

    def _value_from_pos(self, y):
        """Convert mouse y position to scrollbar value."""
        if self.maximum() <= 0:
            return 0
        ratio = self.pageStep() / (self.maximum() + self.pageStep())
        handle_height = max(30, int(self.height() * ratio))
        # Position the center of handle at the click point
        value = (y - handle_height / 2) / (self.height() - handle_height)
        return max(0.0, min(1.0, value)) * self.maximum()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            handle_rect = self._get_handle_rect()
            if handle_rect.contains(event.pos()):
                # Click on handle - start drag, record offset within handle
                self._drag_offset = event.pos().y() - handle_rect.y()
                self._dragging = True
                self.grabMouse()
            else:
                # Click on track - jump to position
                new_value = self._value_from_pos(event.pos().y())
                self.setSliderPosition(int(new_value))
                self.update()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if hasattr(self, '_dragging') and self._dragging:
            if self.maximum() > 0:
                ratio = self.pageStep() / (self.maximum() + self.pageStep())
                handle_height = max(30, int(self.height() * ratio))
                # Calculate position based on mouse y minus the grab offset
                new_y = event.pos().y() - self._drag_offset
                pixel_range = self.height() - handle_height
                if pixel_range > 0:
                    new_value = (new_y / pixel_range) * self.maximum()
                    self.setSliderPosition(max(0, min(int(new_value), self.maximum())))
                    self.update()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if hasattr(self, '_dragging'):
            self._dragging = False
        if self.underMouse():
            self.releaseMouse()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)

            width = self.HOVER_WIDTH if self._hovered else self.DEFAULT_WIDTH
            color = tm.alpha_of(tm.mid, 50) if self._hovered else tm.alpha_of(tm.mid, 40)

            if self.orientation() == Qt.Vertical:
                handle_rect = self._get_handle_rect()

                painter.setBrush(color)
                r = width / 2
                painter.drawRoundedRect(handle_rect, r, r)
        finally:
            painter.end()


class SidebarIconWidget(QWidget):
    """Renders sidebar icons using simple QPainter primitives only."""

    def __init__(self, icon_name: str = "", parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self.setFixedSize(20, 20)
        self._color = tm.mid

    def set_color(self, color: QColor):
        if self._color != color:
            self._color = color
            self.update()

    def _draw_line(self, painter, x1, y1, x2, y2, offset, scale):
        """Draw a line with coordinate transformation."""
        ax = offset + x1 * scale
        ay = offset + y1 * scale
        bx = offset + x2 * scale
        by = offset + y2 * scale
        painter.drawLine(ax, ay, bx, by)

    def _draw_circle(self, painter, cx, cy, r, offset, scale):
        """Draw a circle with coordinate transformation."""
        x = offset + cx * scale
        y = offset + cy * scale
        radius = r * scale
        painter.drawEllipse(QRectF(x - radius, y - radius, radius * 2, radius * 2))

    def _draw_dot(self, painter, cx, cy, r, offset, scale):
        """Draw a filled dot with coordinate transformation."""
        x = offset + cx * scale
        y = offset + cy * scale
        radius = r * scale
        painter.drawEllipse(QRectF(x - radius, y - radius, radius * 2, radius * 2))

    def paintEvent(self, event: QPaintEvent):
        scale = 18.0 / 24.0
        offset = 1.0
        icon = self._icon_name
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(self._color, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.setBrush(Qt.NoBrush)
        
            if icon == "user":
                # Head circle
                self._draw_circle(painter, 12, 8, 4, offset, scale)
                # Body - simple arc using lines
                self._draw_line(painter, 6, 21, 8, 17, offset, scale)
                self._draw_line(painter, 8, 17, 16, 17, offset, scale)
                self._draw_line(painter, 16, 17, 18, 21, offset, scale)
                
            elif icon == "gear":
                # Center circle
                self._draw_circle(painter, 12, 12, 3, offset, scale)
                # Gear teeth (8 lines radiating out)
                for i in range(8):
                    angle = (2 * math.pi * i) / 8
                    cos_a = math.cos(angle)
                    sin_a = math.sin(angle)
                    cx = offset + 12 * scale
                    cy = offset + 12 * scale
                    x1 = cx + cos_a * 6.5 * scale
                    y1 = cy + sin_a * 6.5 * scale
                    x2 = cx + cos_a * 9.5 * scale
                    y2 = cy + sin_a * 9.5 * scale
                    painter.drawLine(x1, y1, x2, y2)
    
            elif icon == "keyboard":
                # Keyboard outline
                rx = offset + 2 * scale
                ry = offset + 4 * scale
                rw = 20 * scale
                rh = 16 * scale
                painter.drawRoundedRect(QRectF(rx, ry, rw, rh), 2 * scale, 2 * scale)
                # Key dots
                dots = [(6,8),(10,8),(14,8),(18,8),(6,12),(10,12),(14,12),(18,12)]
                painter.setBrush(self._color)
                for dx, dy in dots:
                    self._draw_dot(painter, dx, dy, 0.6, offset, scale)
                painter.setBrush(Qt.NoBrush)
                # Space bar line
                self._draw_line(painter, 8, 16, 16, 16, offset, scale)
    
            elif icon == "bell":
                # Bell shape using simple lines
                self._draw_line(painter, 12, 3, 6, 9, offset, scale)
                self._draw_line(painter, 6, 9, 8, 17, offset, scale)
                self._draw_line(painter, 8, 17, 16, 17, offset, scale)
                self._draw_line(painter, 16, 17, 18, 9, offset, scale)
                self._draw_line(painter, 18, 9, 12, 3, offset, scale)
                # Clapper
                self._draw_line(painter, 13.7, 21, 10.3, 21, offset, scale)
    
            elif icon == "plugins":
                # Top diamond
                self._draw_line(painter, 12, 2, 2, 7, offset, scale)
                self._draw_line(painter, 2, 7, 12, 12, offset, scale)
                self._draw_line(painter, 12, 12, 22, 7, offset, scale)
                self._draw_line(painter, 22, 7, 12, 2, offset, scale)
                # Middle layer
                self._draw_line(painter, 2, 17, 12, 22, offset, scale)
                self._draw_line(painter, 12, 22, 22, 17, offset, scale)
                # Bottom layer  
                self._draw_line(painter, 2, 12, 12, 17, offset, scale)
                self._draw_line(painter, 12, 17, 22, 12, offset, scale)
    
            elif icon == "info":
                # Outer circle
                self._draw_circle(painter, 12, 12, 10, offset, scale)
                # Vertical line (i stem)
                self._draw_line(painter, 12, 16, 12, 12, offset, scale)
                # Dot (i dot)
                painter.setBrush(self._color)
                self._draw_dot(painter, 12, 8, 0.8, offset, scale)
                painter.setBrush(Qt.NoBrush)

            elif icon == "collapse":
                # Panel body (left rectangle outline)
                rx = offset + 3 * scale
                ry = offset + 4 * scale
                rw = 12 * scale
                rh = 16 * scale
                painter.drawRoundedRect(QRectF(rx, ry, rw, rh), 2 * scale, 2 * scale)
                # Divider line between panel and arrow
                self._draw_line(painter, 11, 4, 11, 20, offset, scale)
                # Right chevron pointing left (to collapse the panel)
                self._draw_line(painter, 20, 8, 16, 12, offset, scale)
                self._draw_line(painter, 16, 12, 20, 16, offset, scale)

            elif icon == "expand":
                # Slim panel body (narrow left rectangle outline)
                rx = offset + 3 * scale
                ry = offset + 4 * scale
                rw = 6 * scale
                rh = 16 * scale
                painter.drawRoundedRect(QRectF(rx, ry, rw, rh), 2 * scale, 2 * scale)
                # Divider line between panel and arrow
                self._draw_line(painter, 9, 4, 9, 20, offset, scale)
                # Right chevron pointing right (to expand the panel)
                self._draw_line(painter, 14, 8, 18, 12, offset, scale)
                self._draw_line(painter, 18, 12, 14, 16, offset, scale)
        finally:
            painter.end()


class SidebarItem(QWidget):
    """A sidebar navigation item matching the web component exactly."""
    clicked = Signal()

    def __init__(self, label="", icon_svg="", active=False, compact=False, parent=None, badge=""):
        super().__init__(parent)
        self._label = label
        self._icon_svg = icon_svg
        self._active = active
        self._compact = compact
        self._badge = badge
        self._hovered = False
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 10, 14, 10)
        layout.setSpacing(12)
        
        # Set widget background to transparent, we'll draw it manually
        self.setStyleSheet("background-color: transparent;")

        self._icon_widget = SidebarIconWidget(icon_svg)
        layout.addWidget(self._icon_widget, 0, Qt.AlignVCenter)

        self._label_widget = QLabel(label)
        self._update_label_style()
        layout.addWidget(self._label_widget, 1, Qt.AlignVCenter)

        # Badge indicator (small number badge)
        if badge:
            self._badge_label = QLabel(badge)
            self._badge_label.setFixedHeight(18)
            self._badge_label.setMinimumWidth(18)
            self._badge_label.setAlignment(Qt.AlignCenter)
            self._badge_label.setStyleSheet(f"""
                background-color: {tm.danger.name()};
                color: {tm.text.name()};
                font-size: 11px;
                font-weight: 600;
                border-radius: 9px;
                padding: 0 5px;
            """)
            layout.addWidget(self._badge_label, 0, Qt.AlignVCenter)
        else:
            self._badge_label = None

        if active:
            self._set_active(True)

    def _update_label_style(self):
        if self._active:
            self._label_widget.setStyleSheet(f"font-size:13.5px;font-weight:600;color:{tm.text.name()};")
        else:
            self._label_widget.setStyleSheet(f"font-size:13.5px;font-weight:500;color:{tm.mid.name()};")

    def set_compact(self, compact: bool):
        """Toggle compact mode - hide label, reduce margins."""
        self._compact = compact
        layout = self.layout()
        if compact:
            # Hide label so only the icon remains.
            # widget with stretch=0, Qt centers it within the available
            # content area, which shifts the icon off the left margin.
            self._label_widget.setSizePolicy(
                QSizePolicy.Ignored, QSizePolicy.Ignored)
            self._label_widget.setFixedWidth(0)
            self._label_widget.setVisible(False)
            # Hide badge in compact mode
            if self._badge_label:
                self._badge_label.setVisible(False)
            # Icon centers in the compact width — no AlignLeft so space
            # is distributed evenly on both sides.
            layout.removeWidget(self._icon_widget)
            layout.insertWidget(0, self._icon_widget, 0, Qt.AlignVCenter)
            layout.setContentsMargins(17, 10, 17, 10)
            layout.setSpacing(0)
        else:
            self._label_widget.setSizePolicy(
                QSizePolicy.Preferred, QSizePolicy.Preferred)
            self._label_widget.setMinimumWidth(0)
            self._label_widget.setMaximumWidth(16777215)
            self._label_widget.setVisible(True)
            # Show badge again if it exists
            if self._badge_label:
                self._badge_label.setVisible(True)
            layout.removeWidget(self._icon_widget)
            layout.insertWidget(0, self._icon_widget, 0, Qt.AlignVCenter)
            layout.setContentsMargins(7, 10, 14, 10)
            layout.setSpacing(12)

    def set_icon(self, icon_svg: str):
        """Swap the icon at runtime (used by the collapse/expand toggle)."""
        self._icon_svg = icon_svg
        self._icon_widget._icon_name = icon_svg
        self._icon_widget.update()

    def set_label_text(self, text: str):
        """Update the label text at runtime."""
        self._label = text
        self._label_widget.setText(text)

    def ensure_opacity_effect(self):
        """Attach a QGraphicsOpacityEffect to the label so it can fade in/out.
        QGraphicsOpacityEffect defaults to opacity 0.7, which would dim the
        label the first time we attach the effect — explicitly set 1.0."""
        if getattr(self, '_opacity_effect', None) is None:
            self._opacity_effect = QGraphicsOpacityEffect(self._label_widget)
            self._label_widget.setGraphicsEffect(self._opacity_effect)
            self._opacity_effect.setOpacity(1.0)
        return self._opacity_effect

    def set_label_opacity(self, opacity: float):
        """Set the label's opacity (0.0 = invisible, 1.0 = fully visible)."""
        effect = self.ensure_opacity_effect()
        effect.setOpacity(opacity)

    def _set_active(self, active):
        self._active = active
        self._update_label_style()
        self._icon_widget.set_color(tm.text if active else tm.mid)
        self.update()

    @property
    def active(self):
        return self._active

    @active.setter
    def active(self, v):
        self._set_active(v)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
        else:
            super().mousePressEvent(event)

    def enterEvent(self, event):
        self._hovered = True
        if not self._active:
            self._icon_widget.set_color(tm.accent)
            self._label_widget.setStyleSheet(f"font-size:13.5px;font-weight:500;color:{tm.text.name()};")
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        if not self._active:
            self._icon_widget.set_color(tm.mid)
            self._label_widget.setStyleSheet(f"font-size:13.5px;font-weight:500;color:{tm.mid.name()};")
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            if self._hovered:
                painter.setPen(Qt.NoPen)
                painter.setBrush(Qt.transparent)
                painter.drawRoundedRect(QRectF(0, 0, self.width() - 2, self.height()), 10, 10)
        finally:
            painter.end()


class AnimatedHighlightBar(QWidget):
    """Animated highlight bar that stretches between sidebar items during selection changes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFixedWidth(3)
        self._top_y = 0.0
        self._bottom_y = 0.0
        self._visible = False

    def get_top_y(self):
        return self._top_y

    def set_top_y(self, value):
        self._top_y = value
        self.update()

    def get_bottom_y(self):
        return self._bottom_y

    def set_bottom_y(self, value):
        self._bottom_y = value
        self.update()

    top_y = Property(float, get_top_y, set_top_y)
    bottom_y = Property(float, get_bottom_y, set_bottom_y)

    def set_bar_geometry(self, top_y: float, bottom_y: float):
        """Set the bar geometry directly without animation."""
        self._top_y = top_y
        self._bottom_y = bottom_y
        self._visible = True
        self.update()

    def show_bar(self):
        self._visible = True
        self.update()

    def hide_bar(self):
        self._visible = False
        self.update()

    def paintEvent(self, event: QPaintEvent):
        if not self._visible:
            return
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(tm.accent)
            height = self._bottom_y - self._top_y
            rect = QRectF(0.0, self._top_y, 3.0, height)
            painter.drawRoundedRect(rect, 0, 0)
            # Rounded caps
            r = 1.0
            painter.drawEllipse(QRectF(1.5 - r/2, self._top_y, r, r))
            painter.drawEllipse(QRectF(1.5 - r/2, self._bottom_y - r, r, r))
        finally:
            painter.end()


class StyledSidebar(QWidget):
    """Styled sidebar matching the web component exactly."""
    item_selected = Signal(int, str)

    COMPACT_WIDTH = 58

    def __init__(self, title="", width=220, compact=False, transparent=False, parent=None):
        super().__init__(parent)
        self._title = title
        self._width = width
        self._compact = compact
        self._transparent = transparent
        self._active_index = -1
        self._items = []
        self._animating = False
        self.setFixedWidth(self.COMPACT_WIDTH if compact else width)
        # 支持透明背景以显示Mica效果，否则使用默认深色背景
        self.setStyleSheet(f"background-color: transparent;" if transparent else f"background-color:{tm.surface.name()};")

        ml = QVBoxLayout(self)
        ml.setContentsMargins(0, 20, 0, 20)
        ml.setSpacing(0)

        self._title_label = None
        # Always reserve the 62px header area so item positions are stable
        # between expanded and compact modes; only the header content changes.
        if title or compact:
            tl = QLabel(title)
            tl.setFixedHeight(62)
            tl.setContentsMargins(24, 0, 24, 0)
            ml.addWidget(tl)
            self._title_label = tl
        self._apply_title_style(compact)

        scroll = QScrollArea()
        scroll.setObjectName("SidebarScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # Use custom scrollbar
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBar(SidebarScrollBar(scroll))
        scroll.setStyleSheet(
            "#SidebarScroll { border:none; background:transparent; }")
        scroll.viewport().setStyleSheet("background: transparent;")

        nc = QWidget()
        nc.setStyleSheet("background: transparent;")
        nl = QVBoxLayout(nc)
        nl.setContentsMargins(12, 8, 12, 8)
        nl.setSpacing(2)
        nl.addStretch()
        scroll.setWidget(nc)
        ml.addWidget(scroll, 1)
        self._nav_layout = nl
        self._nav_container = nc

        # Bottom toggle button: always anchored to the bottom, not in the scroll
        # area, so it stays visible regardless of how many items the user has.
        # Wrap it in a container with the same 12px left/right margin as the
        # nav container, so it visually aligns with the items above.
        self._toggle_btn = SidebarItem(
            label="收起侧边栏",
            icon_svg="expand" if compact else "collapse",
            compact=compact,
        )
        # Top divider so the button is visually separated from the scroll list.
        self._toggle_btn.setStyleSheet(
            f"SidebarItem {{ background-color: transparent; "
            f"border-top: 1px solid {tm.alpha_of(tm.surface, 90).name()}; }}"
        )
        self._toggle_btn.clicked.connect(self._on_toggle_clicked)
        self._toggle_btn_wrap = QWidget()
        self._toggle_btn_wrap.setStyleSheet("background: transparent;")
        btn_layout = QHBoxLayout(self._toggle_btn_wrap)
        btn_layout.setContentsMargins(12, 0, 12, 0)
        btn_layout.setSpacing(0)
        btn_layout.addWidget(self._toggle_btn)
        ml.addWidget(self._toggle_btn_wrap)

        # Animated highlight bar - positioned as overlay on the sidebar
        self._highlight_bar = AnimatedHighlightBar(self)
        self._highlight_bar.move(0, 0)
        self._highlight_bar.resize(3, self.height())
        self._highlight_bar.hide_bar()

        # Store initial highlight state (first item active)
        self._highlight_top = 0.0
        self._highlight_bottom = 0.0

    def add_item(self, label, icon_svg="", badge=""):
        item = SidebarItem(
            label=label, icon_svg=icon_svg, active=False, compact=self._compact, badge=badge
        )
        item.clicked.connect(lambda it=item: self._on_item_clicked(it))
        self._items.append(item)
        self._nav_layout.insertWidget(self._nav_layout.count() - 1, item)
        if self._active_index < 0:
            self._active_index = 0
            item._set_active(True)
            # Set initial highlight bar position for the first item
            self._highlight_bar.show_bar()
        return item

    def _get_item_bar_rect(self, index: int) -> tuple:
        """Get the (x, top_y, bottom_y) of the highlight bar for an item, relative to sidebar."""
        if index < 0 or index >= len(self._items):
            return (0.0, 0.0, 0.0)
        item = self._items[index]
        # Use global coordinates then map to sidebar for reliability
        global_pos = item.mapToGlobal(QPoint(0, 0))
        item_top = self.mapFromGlobal(global_pos).y()
        item_left = self.mapFromGlobal(global_pos).x()
        bar_height = 20.0
        bar_top = item_top + (item.height() - bar_height) / 2
        bar_bottom = bar_top + bar_height
        bar_x = 5.0  # Fixed at collapsed mode position (nav 2 + 3px bar width)
        return (bar_x, bar_top, bar_bottom)

    def _set_bar(self, x: float, top: float, bottom: float):
        """Set highlight bar geometry."""
        self._highlight_top = top
        self._highlight_bottom = bottom
        self._highlight_bar.move(int(x), 0)
        self._highlight_bar.set_bar_geometry(top, bottom)

    def _animate_highlight(self, old_index: int, new_index: int):
        """Two-phase animation: stretch (ease-in) → restore (ease-out)."""
        if old_index == new_index:
            return
        if old_index < 0 or new_index < 0:
            bar_x, bar_top, bar_bottom = self._get_item_bar_rect(new_index)
            self._set_bar(bar_x, bar_top, bar_bottom)
            return

        self._animating = True
        old_x, old_top, old_bottom = self._get_item_bar_rect(old_index)
        new_x, new_top, new_bottom = self._get_item_bar_rect(new_index)
        going_down = new_index > old_index

        # Use the new item's x position
        bar_x = new_x

        # --- Phase 1: Stretch (ease-in) ---
        if going_down:
            # Top fixed, bottom stretches down
            s1_top_start, s1_top_end = old_top, old_top
            s1_bottom_start, s1_bottom_end = old_bottom, new_bottom
        else:
            # Bottom fixed, top stretches up
            s1_top_start, s1_top_end = old_top, new_top
            s1_bottom_start, s1_bottom_end = old_bottom, old_bottom

        self._highlight_bar.show_bar()
        self._highlight_bar.move(int(bar_x), 0)
        self._set_bar(bar_x, s1_top_start, s1_bottom_start)

        anim_t = QPropertyAnimation(self._highlight_bar, b"top_y", self._highlight_bar)
        anim_t.setDuration(180)
        anim_t.setStartValue(s1_top_start)
        anim_t.setEndValue(s1_top_end)
        anim_t.setEasingCurve(QEasingCurve.InCubic)

        anim_b = QPropertyAnimation(self._highlight_bar, b"bottom_y", self._highlight_bar)
        anim_b.setDuration(180)
        anim_b.setStartValue(s1_bottom_start)
        anim_b.setEndValue(s1_bottom_end)
        anim_b.setEasingCurve(QEasingCurve.InCubic)

        phase1 = QParallelAnimationGroup(self._highlight_bar)
        phase1.addAnimation(anim_t)
        phase1.addAnimation(anim_b)

        # --- Phase 2: Restore (ease-out) ---
        def start_phase2():
            self._highlight_bar.hide_bar()
            # Start from slightly stretched state at new position
            overshoot = 5.0
            if going_down:
                # New bar: bottom fixed, top starts slightly above (overshoot)
                start_t, end_t = new_top - overshoot, new_top
                start_b, end_b = new_bottom, new_bottom
            else:
                # New bar: top fixed, bottom starts slightly below (overshoot)
                start_t, end_t = new_top, new_top
                start_b, end_b = new_bottom + overshoot, new_bottom

            self._highlight_bar.show_bar()
            self._highlight_bar.move(int(bar_x), 0)
            self._set_bar(bar_x, start_t, start_b)

            r_anim_t = QPropertyAnimation(self._highlight_bar, b"top_y", self._highlight_bar)
            r_anim_t.setDuration(180)
            r_anim_t.setStartValue(start_t)
            r_anim_t.setEndValue(end_t)
            r_anim_t.setEasingCurve(QEasingCurve.OutCubic)

            r_anim_b = QPropertyAnimation(self._highlight_bar, b"bottom_y", self._highlight_bar)
            r_anim_b.setDuration(180)
            r_anim_b.setStartValue(start_b)
            r_anim_b.setEndValue(end_b)
            r_anim_b.setEasingCurve(QEasingCurve.OutCubic)

            phase2 = QParallelAnimationGroup(self._highlight_bar)
            phase2.addAnimation(r_anim_t)
            phase2.addAnimation(r_anim_b)
            phase2.finished.connect(lambda: setattr(self, '_animating', False))
            phase2.start()

        phase1.finished.connect(start_phase2)
        phase1.start()

    def _on_item_clicked(self, ci):
        old_index = self._active_index
        for i, item in enumerate(self._items):
            item._set_active(item is ci)
            if item is ci:
                self._active_index = i
                self.item_selected.emit(i, item._label)
        
        if old_index != self._active_index and not self._animating:
            self._animate_highlight(old_index, self._active_index)

    def set_compact(self, compact):
        self._compact = compact
        # Always reserve the 62px header area; only the header content changes.
        self._apply_title_style(compact)
        # Bottom toggle button mirrors the state: icon and label flip to
        # advertise the action the click will perform.
        if hasattr(self, '_toggle_btn'):
            self._toggle_btn.set_icon("expand" if compact else "collapse")
            self._toggle_btn.set_label_text(
                "展开侧边栏" if compact else "收起侧边栏"
            )
        # Adjust nav container margins for compact width
        margin = 2 if compact else 12
        self._nav_layout.setContentsMargins(margin, 8, margin, 8)
        # Adjust toggle button wrap margins
        if hasattr(self, '_toggle_btn_wrap'):
            self._toggle_btn_wrap.layout().setContentsMargins(margin, 0, margin, 0)
        target_width = self.COMPACT_WIDTH if compact else self._width

        # Build the list of items whose label needs to fade (regular items +
        # the bottom toggle button). Doing this in parallel with the width
        # animation means the user only ever sees a smooth width + fade, never
        # the abrupt "icon jumps to center while sidebar is still wide" snap.
        fade_targets = list(self._items)
        if hasattr(self, '_toggle_btn'):
            fade_targets.append(self._toggle_btn)

        if compact:
            # Collapse: set item margins to compact value (17) immediately so
            # icon left position (nav 2 + item 17 = 19px) stays stable during
            # the entire animation. Label fade + width shrink happen in
            # parallel; only label visibility/spacing waits for _finalize.
            for it in fade_targets:
                it.layout().setContentsMargins(17, 10, 17, 10)
                it.ensure_opacity_effect()
            self._animate_label_opacity(fade_targets, target=0.0,
                                         on_finished=self._finalize_collapse)
        else:
            # Expand: restore expanded layout first (with labels invisible),
            # then fade them in as the width grows.
            for it in self._items:
                it.set_compact(False)
            for it in fade_targets:
                it.ensure_opacity_effect()
                it.set_label_opacity(0.0)
            if hasattr(self, '_toggle_btn'):
                self._toggle_btn.set_compact(False)
            self._animate_label_opacity(fade_targets, target=1.0)

        self._animate_width(target_width)

    def _finalize_collapse(self):
        """Swap items to compact layout after labels have fully faded out.
        Guarded by the current compact state so rapid toggling can't fire
        the swap after the user has already switched back to expanded."""
        if not self._compact:
            return
        for it in self._items:
            it.set_compact(True)
        if hasattr(self, '_toggle_btn'):
            self._toggle_btn.set_compact(True)

    def _animate_label_opacity(self, items, target: float, on_finished=None):
        """Fade all given items' labels in parallel over the same duration
        as the width animation, so the transitions stay in lockstep."""
        duration = 260
        if not hasattr(self, '_label_anims'):
            self._label_anims = []
        for old in self._label_anims:
            old.stop()
        self._label_anims = []
        for it in items:
            effect = it.ensure_opacity_effect()
            anim = QPropertyAnimation(effect, b"opacity", self)
            anim.setDuration(duration)
            anim.setStartValue(effect.opacity())
            anim.setEndValue(target)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            if on_finished is not None:
                anim.finished.connect(on_finished)
            anim.start()
            self._label_anims.append(anim)

    def _on_toggle_clicked(self):
        """Bottom toggle button: flip the compact state."""
        self.set_compact(not self._compact)

    def _apply_title_style(self, compact: bool):
        """Style the header label: full title in expanded, logo/empty in compact."""
        if self._title_label is None:
            return
        if compact:
            # In compact mode, show the first character of the title centered
            # (acts as a small logo) so the header isn't dead space.
            logo = (self._title[:1] or "").upper()
            self._title_label.setText(logo)
            self._title_label.setAlignment(Qt.AlignCenter)
            self._title_label.setStyleSheet(
                f"font-size:18px;font-weight:700;color:{tm.accent.name()};")
            self._title_label.setContentsMargins(0, 0, 0, 0)
        else:
            self._title_label.setText(self._title)
            self._title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self._title_label.setStyleSheet(
                f"font-size:16px;font-weight:600;color:{tm.text.name()};letter-spacing:0.5px;")
            self._title_label.setContentsMargins(24, 0, 24, 0)

    def _animate_width(self, target_width: int):
        """Animate sidebar width with a non-linear easing curve."""
        # Drop fixed-width constraint so animation can drive min/max width.
        if self.minimumWidth() == self.maximumWidth():
            self.setMinimumWidth(self.width())
            self.setMaximumWidth(16777215)
        # If a previous animation is running, stop it and jump to its end value
        # so we don't fight with a stale tween.
        if hasattr(self, '_width_anims'):
            for old in self._width_anims:
                old.stop()
        self._width_anims = []
        start_width = self.width()
        for prop in (b"minimumWidth", b"maximumWidth"):
            anim = QPropertyAnimation(self, prop, self)
            anim.setDuration(260)
            anim.setStartValue(start_width)
            anim.setEndValue(target_width)
            # Expand uses OutCubic (decelerate into final width),
            # collapse uses InOutCubic for a snappier, more natural feel.
            anim.setEasingCurve(
                QEasingCurve.OutCubic if target_width > start_width
                else QEasingCurve.InOutCubic
            )
            anim.finished.connect(self._on_width_anim_finished)
            self._width_anims.append(anim)
            anim.start()

    def _on_width_anim_finished(self):
        # Re-apply fixed-width at the final value so the sidebar stays rigid.
        self.setFixedWidth(self.width())
        if hasattr(self, '_width_anims'):
            self._width_anims.clear()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._highlight_bar.resize(3, self.height())
        if self._active_index >= 0 and self._active_index < len(self._items):
            bar_x, top, bottom = self._get_item_bar_rect(self._active_index)
            self._highlight_bar.move(int(bar_x), 0)
            self._highlight_bar.set_bar_geometry(top, bottom)

    def showEvent(self, event):
        super().showEvent(event)
        if self._active_index >= 0 and self._active_index < len(self._items):
            bar_x, top, bottom = self._get_item_bar_rect(self._active_index)
            self._highlight_bar.move(int(bar_x), 0)
            self._highlight_bar.set_bar_geometry(top, bottom)
