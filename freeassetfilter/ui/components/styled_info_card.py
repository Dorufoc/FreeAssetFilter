"""Styled InfoCard component - matches web info-card exactly."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy, QGraphicsOpacityEffect,
)
from PySide6.QtCore import (
    Qt, Signal, QRectF, QPropertyAnimation, QEasingCurve,
    Property, QPoint, QEvent,
)
from PySide6.QtGui import (
    QPainter, QColor, QPaintEvent, QFont, QFontMetrics,
    QPen, QBrush, QMouseEvent, QActionEvent,
)
import math

from theme import tm


class StyledInfoCard(QWidget):
    """A styled info card matching the web component exactly.

    Layout modes:
    - horizontal: media left, text body right
    - vertical: media top, text body bottom

    Features: hover scale on media, press scale on card,
    hover overlay with action buttons, disabled state.
    """

    LAYOUT_MODES = ["horizontal", "vertical"]

    SIZE_CONFIG = {
        "horizontal": {
            "padding": 16,
            "gap": 14,
            "radius": 6,
            "media_size": 52,
            "icon_size": 24,
            "title_size": 14,
            "title_weight": 600,
            "subtitle_size": 13,
            "subtitle_weight": 500,
            "desc_size": 12,
            "desc_weight": 400,
        },
        "vertical": {
            "padding": 20,
            "gap": 12,
            "radius": 6,
            "media_size": 64,
            "icon_size": 28,
            "title_size": 14,
            "title_weight": 600,
            "subtitle_size": 13,
            "subtitle_weight": 500,
            "desc_size": 12,
            "desc_weight": 400,
        },
    }

    COLORS = {
        "bg": tm.alpha_of(tm.surface, 85),              # --bg-card
        "bg_hover": tm.alpha_of(tm.surface, 90),  # --bg-card-hover
        "border": tm.alpha_of(tm.mid, 30),      # --border-light
        "media_bg": tm.alpha_of(tm.mid, 40),  # --bg-input
        "title": tm.text,        # --text-primary
        "subtitle": tm.mid,  # --text-secondary
        "desc": tm.alpha_of(tm.mid, 60),          # --text-tertiary
        "icon": tm.mid,          # --text-secondary
        "overlay_bg": QColor(0, 0, 0, 127),              # rgba(0,0,0,0.5) — no theme token
        "shadow": QColor(0, 0, 0, 40),                   # no theme token
    }

    def __init__(
        self,
        layout_mode: str = "horizontal",
        title: str = "",
        subtitle: str = "",
        desc: str = "",
        disabled: bool = False,
        media_icon: str = "",
        overlay_enabled: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._layout_mode = layout_mode if layout_mode in self.LAYOUT_MODES else "horizontal"
        self._title = title
        self._subtitle = subtitle
        self._desc = desc
        self._disabled = disabled
        self._media_icon = media_icon
        self._overlay_enabled = overlay_enabled
        self._actions = []  # list of (text, icon, callback)

        # Animation states
        self._hovered = False
        self._pressed = False
        self._overlay_opacity = 0.0
        self._card_scale = 1.0
        self._media_scale = 1.0

        # Shadow offset for depth
        self._shadow_offset = 0.0

        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setMouseTracking(False)

        # Hover animation (media scale + overlay fade)
        self._hover_anim = QPropertyAnimation(self, b"overlay_opacity")
        self._hover_anim.setDuration(250)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)

        # Media scale animation — OutBack gives a subtle spring overshoot (non-linear)
        self._media_scale_anim = QPropertyAnimation(self, b"media_scale")
        self._media_scale_anim.setDuration(300)
        self._media_scale_anim.setEasingCurve(QEasingCurve.OutBack)

        # Card press scale animation
        self._card_scale_anim = QPropertyAnimation(self, b"card_scale")
        self._card_scale_anim.setDuration(120)
        self._card_scale_anim.setEasingCurve(QEasingCurve.OutBack)

        # Overlay buttons (created as child widgets, hidden by default)
        self._overlay_widget = None
        self._overlay_buttons = []

        self._apply_size()
        self.update()

    # ── Properties ────────────────────────────────────────────

    @Property(float)
    def overlay_opacity(self):
        return self._overlay_opacity

    @overlay_opacity.setter
    def overlay_opacity(self, value: float):
        self._overlay_opacity = value
        self._update_overlay_visibility()
        self.update()

    @Property(float)
    def media_scale(self):
        return self._media_scale

    @media_scale.setter
    def media_scale(self, value: float):
        self._media_scale = value
        self.update()

    @Property(float)
    def card_scale(self):
        return self._card_scale

    @card_scale.setter
    def card_scale(self, value: float):
        self._card_scale = value
        self.update()

    # ── Public API ────────────────────────────────────────────

    def add_action(self, text: str, icon: str = "", callback=None):
        """Add an action button to the hover overlay."""
        self._actions.append((text, icon, callback))
        self._rebuild_overlay()

    def clear_actions(self):
        """Remove all action buttons from the overlay."""
        self._actions.clear()
        self._rebuild_overlay()

    def set_title(self, text: str):
        self._title = text
        self.update()

    def set_subtitle(self, text: str):
        self._subtitle = text
        self.update()

    def set_desc(self, text: str):
        self._desc = text
        self.update()

    def set_media_icon(self, icon: str):
        self._media_icon = icon
        self.update()

    def set_overlay_enabled(self, enabled: bool):
        self._overlay_enabled = enabled
        self._rebuild_overlay()
        self.update()

    # ── Internal ──────────────────────────────────────────────

    def _apply_size(self):
        config = self.SIZE_CONFIG[self._layout_mode]
        padding = config["padding"]

        # Calculate text height for sizing
        font_title = QFont("Microsoft YaHei UI", config["title_size"], config["title_weight"])
        fm = QFontMetrics(font_title)
        title_h = fm.height()

        subtitle_h = 0
        if self._subtitle:
            font_sub = QFont("Microsoft YaHei UI", config["subtitle_size"], config["subtitle_weight"])
            fm2 = QFontMetrics(font_sub)
            subtitle_h = fm2.height()

        desc_h = 0
        if self._desc:
            font_desc = QFont("Microsoft YaHei UI", config["desc_size"], config["desc_weight"])
            fm3 = QFontMetrics(font_desc)
            desc_h = fm3.height()

        text_gap = 4  # gap between text lines
        text_lines = 1 + (1 if self._subtitle else 0) + (1 if self._desc else 0)
        text_height = title_h + subtitle_h + desc_h + text_gap * (text_lines - 1)

        if self._layout_mode == "horizontal":
            media_size = config["media_size"]
            total_height = padding * 2 + max(media_size, text_height)
            total_width = padding * 2 + media_size + config["gap"] + 200
        else:
            media_size = config["media_size"]
            total_height = padding * 2 + media_size + config["gap"] + text_height
            total_width = padding * 2 + max(media_size, 200)

        self.setMinimumSize(total_width, total_height)
        self.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed)

    def _rebuild_overlay(self):
        """Create or update the overlay widget and its action buttons.

        Uses QGraphicsOpacityEffect so the entire overlay (background + buttons)
        fades in/out synchronously.
        """
        # Remove old overlay
        if self._overlay_widget:
            self._overlay_widget.deleteLater()
            self._overlay_widget = None
            self._overlay_buttons.clear()

        if not self._overlay_enabled or not self._actions:
            return

        # Create overlay widget
        self._overlay_widget = QWidget(self)
        self._overlay_widget.setAttribute(Qt.WA_StyledBackground, False)
        self._overlay_widget.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self._overlay_widget.raise_()
        self._overlay_widget.setGeometry(self.rect())

        config = self.SIZE_CONFIG[self._layout_mode]
        radius = config["radius"]

        # QGraphicsOpacityEffect — whole widget (bg + buttons) fades together
        self._opacity_effect = QGraphicsOpacityEffect()
        self._opacity_effect.setOpacity(0.0)
        self._overlay_widget.setGraphicsEffect(self._opacity_effect)

        # Solid semi-transparent background; the opacity effect handles the fade
        self._overlay_widget.setStyleSheet(
            f"background: rgba(0,0,0,128);"
            f"border-radius: {radius}px;"
        )

        if self._layout_mode == "horizontal":
            # Horizontal row — buttons right-aligned
            layout = QHBoxLayout(self._overlay_widget)
            layout.setContentsMargins(16, 0, 16, 0)
            layout.setSpacing(8)
            layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        else:
            # Vertical: 2x2 grid
            layout = QVBoxLayout(self._overlay_widget)
            layout.setContentsMargins(16, 16, 16, 16)
            layout.setSpacing(8)

            top_row = QHBoxLayout()
            top_row.setSpacing(8)
            bottom_row = QHBoxLayout()
            bottom_row.setSpacing(8)

            for i, (text, icon, callback) in enumerate(self._actions):
                btn = _OverlayButton(text, icon)
                if callback:
                    btn.clicked.connect(callback)
                self._overlay_buttons.append(btn)
                if i < 2:
                    top_row.addWidget(btn, stretch=1)
                else:
                    bottom_row.addWidget(btn, stretch=1)

            layout.addLayout(top_row)
            if self._actions and len(self._actions) > 2:
                layout.addLayout(bottom_row)
            layout.addStretch()
            return

        for text, icon, callback in self._actions:
            btn = _OverlayButton(text, icon)
            if callback:
                btn.clicked.connect(callback)
            self._overlay_buttons.append(btn)
            layout.addWidget(btn)

        # Initially hidden (opacity effect = 0, but we must keep visible so the
        # effect can animate from 0 → 1 on hover)
        self._overlay_widget.setVisible(False)

    def _update_overlay_visibility(self):
        """Sync the overlay widget's opacity effect + visibility with _overlay_opacity."""
        if not self._overlay_widget or not self._opacity_effect:
            return
        visible = self._overlay_opacity > 0.01 and not self._disabled
        self._overlay_widget.setVisible(visible)
        if visible:
            self._opacity_effect.setOpacity(min(1.0, self._overlay_opacity))

    # ── Event handling ────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._overlay_widget:
            self._overlay_widget.setGeometry(self.rect())

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and not self._disabled:
            self._pressed = True
            self._animate_card_scale(0.97, 80, QEasingCurve.OutBack)
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._pressed = False
            self._animate_card_scale(1.0, 120, QEasingCurve.OutCubic)
            self.update()
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        self._hovered = True
        if not self._disabled:
            self._animate_overlay(1.0)
            self._animate_media_scale(1.05)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._pressed = False
        self._animate_overlay(0.0)
        self._animate_media_scale(1.0)
        self._animate_card_scale(1.0)
        super().leaveEvent(event)

    # ── Animations ────────────────────────────────────────────

    def _animate_overlay(self, target: float):
        self._hover_anim.stop()
        d = abs(target - self._overlay_opacity)
        self._hover_anim.setDuration(max(50, int(250 * d)))
        self._hover_anim.setStartValue(self._overlay_opacity)
        self._hover_anim.setEndValue(target)
        self._hover_anim.start()

    def _animate_media_scale(self, target: float):
        self._media_scale_anim.stop()
        d = abs(target - self._media_scale)
        self._media_scale_anim.setDuration(max(50, int(250 * d)))
        self._media_scale_anim.setStartValue(self._media_scale)
        self._media_scale_anim.setEndValue(target)
        self._media_scale_anim.start()

    def _animate_card_scale(self, target: float, duration: int = 120, easing=QEasingCurve.OutCubic):
        self._card_scale_anim.stop()
        self._card_scale_anim.setDuration(duration)
        self._card_scale_anim.setEasingCurve(easing)
        self._card_scale_anim.setStartValue(self._card_scale)
        self._card_scale_anim.setEndValue(target)
        self._card_scale_anim.start()

    # ── Paint ─────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        if not painter.isActive():
            return

        try:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setRenderHint(QPainter.TextAntialiasing)
            painter.setPen(Qt.NoPen)

            config = self.SIZE_CONFIG[self._layout_mode]
            padding = config["padding"]
            radius = config["radius"]
            gap = config["gap"]

            w = self.width()
            h = self.height()

            opacity = 0.5 if self._disabled else 1.0
            painter.setOpacity(opacity)

            # Card background
            if self._hovered and not self._disabled:
                bg_color = self.COLORS["bg_hover"]
            else:
                bg_color = self.COLORS["bg"]

            painter.setBrush(bg_color)
            card_rect = QRectF(0, 0, w, h)
            painter.drawRoundedRect(card_rect, radius, radius)

            # Card border
            painter.setBrush(Qt.NoBrush)
            pen = QPen(self.COLORS["border"], 1)
            painter.setPen(pen)
            painter.drawRoundedRect(card_rect, radius, radius)

            painter.setPen(Qt.NoPen)

            # Shadow on hover
            if self._hovered and not self._disabled:
                painter.setBrush(self.COLORS["shadow"])
                shadow_rect = QRectF(0, 2, w, h)
                painter.drawRoundedRect(shadow_rect, radius, radius)

            # ── Media Area ──
            media_size = config["media_size"]
            icon_size = config["icon_size"]

            if self._layout_mode == "horizontal":
                media_x = padding
                media_y = (h - media_size) / 2.0
            else:
                media_x = (w - media_size) / 2.0
                media_y = padding

            # Scale media on hover
            current_media_scale = self._media_scale
            if current_media_scale != 1.0:
                painter.save()
                cx = media_x + media_size / 2.0
                cy = media_y + media_size / 2.0
                painter.translate(cx, cy)
                painter.scale(current_media_scale, current_media_scale)
                painter.translate(-cx, -cy)

            # Media background
            if self._disabled:
                painter.setBrush(tm.alpha_of(tm.mid, 50))
            else:
                painter.setBrush(self.COLORS["media_bg"])

            media_rect = QRectF(media_x, media_y, media_size, media_size)
            painter.drawRoundedRect(media_rect, 4, 4)

            # Media icon
            if self._media_icon:
                icon_font = QFont("Segoe UI Symbol", icon_size, QFont.Normal)
                painter.setFont(icon_font)
            if self._disabled:
                painter.setPen(tm.alpha_of(tm.mid, 60))
            else:
                painter.setPen(self.COLORS["icon"])
                painter.drawText(
                    media_rect,
                    Qt.AlignCenter,
                    self._media_icon,
                )

            if current_media_scale != 1.0:
                painter.restore()

            # ── Text Area ──
            if self._layout_mode == "horizontal":
                text_x = media_x + media_size + gap
                text_y = padding
                text_w = w - text_x - padding
                text_h = h - padding * 2
            else:
                text_x = padding
                text_y = media_y + media_size + gap
                text_w = w - padding * 2
                text_h = h - text_y - padding

            text_rect = QRectF(text_x, text_y, text_w, text_h)
            self._draw_text(painter, text_rect, config)

            # Grayscale filter for disabled
            if self._disabled:
                painter.setOpacity(0.5)

        finally:
            if painter.isActive():
                painter.end()

    def _draw_text(self, painter: QPainter, rect: QRectF, config: dict):
        """Draw title, subtitle, and description text lines."""
        y = rect.y()
        x = rect.x()
        max_w = rect.width()
        line_gap = 4

        # Title
        if self._title:
            font = QFont("Microsoft YaHei UI", config["title_size"], config["title_weight"])
            painter.setFont(font)
            if self._disabled:
                painter.setPen(tm.alpha_of(tm.mid, 60))
            else:
                painter.setPen(self.COLORS["title"])
            fm = QFontMetrics(font)
            elided = fm.elidedText(self._title, Qt.ElideRight, int(max_w))
            painter.drawText(QRectF(x, y, max_w, fm.height()), Qt.AlignLeft | Qt.AlignTop, elided)
            y += fm.height() + line_gap

        # Subtitle
        if self._subtitle:
            font = QFont("Microsoft YaHei UI", config["subtitle_size"], config["subtitle_weight"])
            painter.setFont(font)
            if self._disabled:
                painter.setPen(tm.alpha_of(tm.mid, 60))
            else:
                painter.setPen(self.COLORS["subtitle"])
            fm = QFontMetrics(font)
            elided = fm.elidedText(self._subtitle, Qt.ElideRight, int(max_w))
            painter.drawText(QRectF(x, y, max_w, fm.height()), Qt.AlignLeft | Qt.AlignTop, elided)
            y += fm.height() + line_gap

        # Description
        if self._desc:
            font = QFont("Microsoft YaHei UI", config["desc_size"], config["desc_weight"])
            painter.setFont(font)
            if self._disabled:
                painter.setPen(tm.alpha_of(tm.mid, 60))
            else:
                painter.setPen(self.COLORS["desc"])
            fm = QFontMetrics(font)
            # Word wrap the description
            text_rect = QRectF(x, y, max_w, rect.bottom() - y)
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, self._desc)


class _OverlayButton(QWidget):
    """Internal action button used inside the info-card overlay."""

    clicked = Signal()

    SIZE_CONFIG = {
        "padding_h": 12,
        "padding_v": 8,
        "font_size": 12,
        "radius": 4,
        "icon_size": 14,
    }

    COLORS = {
        "bg": tm.surface,
        "bg_hover": tm.mid,
        "border": tm.alpha_of(tm.mid, 40),
        "text": tm.mid,
        "text_hover": tm.text,
    }

    def __init__(self, text: str = "", icon: str = "", parent=None):
        super().__init__(parent)
        self._text = text
        self._icon = icon
        self._hovered = False
        self._pressed = False

        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setCursor(Qt.PointingHandCursor)

        cfg = self.SIZE_CONFIG
        fm = QFontMetrics(QFont("Microsoft YaHei UI", cfg["font_size"]))
        text_w = fm.horizontalAdvance(text) if text else 0
        icon_w = cfg["icon_size"] if icon else 0
        gap = 6 if text and icon else 0
        content_w = icon_w + gap + text_w
        btn_w = content_w + cfg["padding_h"] * 2
        btn_h = cfg["padding_v"] * 2 + max(cfg["icon_size"], fm.height())
        self.setFixedSize(int(btn_w), int(btn_h))

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._pressed = True
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self._pressed:
            self._pressed = False
            self.clicked.emit()
            self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        if not painter.isActive():
            return

        try:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)

            w = self.width()
            h = self.height()
            cfg = self.SIZE_CONFIG
            radius = cfg["radius"]

            # Background
            if self._pressed:
                bg = tm.surface
            elif self._hovered:
                bg = self.COLORS["bg_hover"]
            else:
                bg = self.COLORS["bg"]

            painter.setBrush(bg)
            painter.drawRoundedRect(QRectF(0, 0, w, h), radius, radius)

            # Border
            pen = QPen(self.COLORS["border"], 1)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), radius, radius)

            # Text / Icon
            text_color = self.COLORS["text_hover"] if self._hovered else self.COLORS["text"]
            icon_size = cfg["icon_size"]
            font_size = cfg["font_size"]

            if self._icon and self._text:
                # Icon + text
                icon_font = QFont("Segoe UI Symbol", icon_size)
                painter.setFont(icon_font)
                painter.setPen(text_color)
                fm = QFontMetrics(icon_font)
                icon_w = fm.horizontalAdvance(self._icon)

                text_font = QFont("Microsoft YaHei UI", font_size, 500)
                painter.setFont(text_font)
                fm2 = QFontMetrics(text_font)
                text_w = fm2.horizontalAdvance(self._text)
                gap = 6
                total_w = icon_w + gap + text_w
                start_x = (w - total_w) / 2.0
                center_y = h / 2.0

                painter.setFont(icon_font)
                painter.drawText(QRectF(start_x, 0, icon_w, h), Qt.AlignCenter, self._icon)
                painter.setFont(text_font)
                painter.drawText(QRectF(start_x + icon_w + gap, 0, text_w, h), Qt.AlignCenter, self._text)

            elif self._icon:
                icon_font = QFont("Segoe UI Symbol", icon_size)
                painter.setFont(icon_font)
                painter.setPen(text_color)
                painter.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, self._icon)

            elif self._text:
                text_font = QFont("Microsoft YaHei UI", font_size, 500)
                painter.setFont(text_font)
                painter.setPen(text_color)
                painter.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, self._text)

        finally:
            if painter.isActive():
                painter.end()
