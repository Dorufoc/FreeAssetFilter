"""Styled InfoCard component - matches web info-card exactly."""

from __future__ import annotations

from typing import Optional

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
from components.styled_button import StyledButton


class StyledInfoCard(QWidget):
    """A styled info card matching the web component exactly.

    Layout modes:
    - horizontal: media left, text body right
    - vertical: media top, text body bottom

    Features: hover scale on media, press scale on card,
    hover overlay with action buttons, disabled state.
    """

    clicked = Signal(str)  # emitted on left-button release, passes file_path

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

    def __init__(
        self,
        layout_mode: str = "horizontal",
        title: str = "",
        subtitle: str = "",
        desc: str = "",
        disabled: bool = False,
        media_icon: str = "",
        overlay_enabled: bool = False,
        size_overrides: dict | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._layout_mode = layout_mode if layout_mode in self.LAYOUT_MODES else "horizontal"
        self._title = title
        self._subtitle = subtitle
        self._desc = desc
        self._disabled = disabled
        self._media_icon = media_icon
        self._media_pixmap = None  # optional QPixmap override for media area
        self._overlay_enabled = overlay_enabled
        self._file_path = ""  # identifier for clicked signal
        self._size_overrides = size_overrides or {}
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

        # Repaint automatically when the global theme changes.
        tm.colors_updated.connect(self._on_theme_changed)

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

    def _on_theme_changed(self, _colors: dict) -> None:
        """Slot for ThemeManager.colors_updated: repaint with new theme colors."""
        self.update()

    # ── Config ────────────────────────────────────────────────

    def _get_config(self) -> dict:
        """获取当前布局配置，合并 size_overrides 覆盖项。"""
        base = dict(self.SIZE_CONFIG[self._layout_mode])
        if self._size_overrides:
            base.update(self._size_overrides)
        return base

    def _get_colors(self) -> dict:
        """获取当前主题颜色（每次绘制时重新读取，支持深色/浅色模式切换）。"""
        return {
            "bg": tm.alpha_of(tm.surface, 85),
            "bg_hover": tm.alpha_of(tm.surface, 90),
            "border": tm.alpha_of(tm.mid, 30),
            "media_bg": tm.alpha_of(tm.mid, 40),
            "title": tm.text,
            "subtitle": tm.mid,
            "desc": tm.alpha_of(tm.mid, 60),
            "icon": tm.mid,
            "overlay_bg": QColor(0, 0, 0, 127),
            "shadow": QColor(0, 0, 0, 40),
        }

    # ── Public API ────────────────────────────────────────────

    def add_action(
        self,
        text: str,
        icon: str = "",
        variant: str = "secondary",
        size: str = "sm",
        callback=None,
    ):
        """Add an action button to the hover overlay.

        Args:
            text: 按钮文本。
            icon: 图标（文本字符或 SVG 文件路径）。
            variant: 按钮变体（primary/secondary/ghost/danger/info），传给 StyledButton。
            size: 按钮尺寸（sm/default/lg），传给 StyledButton。
            callback: 点击回调。
        """
        self._actions.append((text, icon, variant, size, callback))
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
        self._media_pixmap = None
        self.update()

    def set_media_pixmap(self, pixmap):
        """Set a QPixmap to draw in the media area (overrides text icon)."""
        self._media_pixmap = pixmap
        self.update()

    def set_file_path(self, path: str):
        """Set identifier string emitted with the clicked signal."""
        self._file_path = path

    def set_overlay_enabled(self, enabled: bool):
        self._overlay_enabled = enabled
        self._rebuild_overlay()
        self.update()

    # 仅这些尺寸键参与缩放；weight/radius 等键原样保留，
    # 避免 title_weight=700 被放大为非法字重或在缩放后回落为默认值。
    _SCALABLE_SIZE_KEYS = ("padding", "gap", "media_size", "icon_size",
                           "title_size", "subtitle_size", "desc_size")

    def set_scale(self, scale: float, base_overrides: dict | None = None) -> None:
        """动态缩放卡片所有尺寸因子（0.5 ~ 2.0），匹配文件选择器 Ctrl+滚轮行为。

        Args:
            scale: 缩放系数。
            base_overrides: 缩放基准字典。传入时，尺寸键从该字典的 base 值乘以 scale
                计算新尺寸，非尺寸键（weight/radius 等）原样保留；缺省时使用
                ``SIZE_CONFIG`` 的默认值。这让调用方可以在缩放时保留自己的
                "设计值"（如紧凑型标题 10px），保证已存在卡片与新增卡片尺寸一致。
        """
        scale = max(0.5, min(2.0, scale))
        source = base_overrides if base_overrides else self.SIZE_CONFIG[self._layout_mode]
        overrides = {}
        for key, value in source.items():
            if key in self._SCALABLE_SIZE_KEYS:
                overrides[key] = max(1, int(value * scale))
            else:
                overrides[key] = value
        self._size_overrides = overrides
        self._apply_size()
        self.update()

    def update_overlay(self) -> None:
        """强制 overlay 子控件重绘（修复 QGraphicsEffect 缓存导致的不同步问题）。

        原理：overlay 使用了 QGraphicsOpacityEffect，Qt 内部会缓存 sourcePixmap。
        当父容器（QScrollArea）滚动时，子 widget 的几何位置已经跟随父容器更新，
        但 graphics effect 的缓存 pixmap 仍是滚动前的版本，导致 overlay 视觉上
        "跟不上"滚动。手动调用 update() 触发重新 grab pixmap 即可解决。
        """
        if self._overlay_widget is not None and self._overlay_widget.isVisible():
            self._overlay_widget.update()

    # ── Internal ──────────────────────────────────────────────

    def _calc_text_height(self, config: dict) -> int:
        """计算文字块（标题+副标题+描述）的实际总高度。

        供 _apply_size（卡片定高）与 paintEvent（文字块垂直居中）共用，
        保证两处对文字高度的度量一致。
        """
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
        return title_h + subtitle_h + desc_h + text_gap * (text_lines - 1)

    def _apply_size(self):
        config = self._get_config()
        padding = config["padding"]

        text_height = self._calc_text_height(config)

        if self._layout_mode == "horizontal":
            media_size = config["media_size"]
            total_height = padding * 2 + max(media_size, text_height)
            total_width = padding * 2 + media_size + config["gap"] + 200
        else:
            media_size = config["media_size"]
            total_height = padding * 2 + media_size + config["gap"] + text_height
            total_width = padding * 2 + max(media_size, 200)

        self.setFixedHeight(total_height)
        self.setMinimumWidth(total_width)
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

        config = self._get_config()
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

            for i, (text, icon, variant, size, callback) in enumerate(self._actions):
                btn = StyledButton(text, variant=variant, size=size, icon=icon)
                if callback:
                    # QPushButton.clicked 携带 bool 参数，连接到一个丢弃多余参数的 lambda，
                    # 避免 bool 被透传给仅接受 file_path 字符串的回调函数。
                    btn.clicked.connect(lambda *args, cb=callback: cb())
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

        for text, icon, variant, size, callback in self._actions:
            btn = StyledButton(text, variant=variant, size=size, icon=icon)
            if callback:
                # QPushButton.clicked 携带 bool 参数，连接到一个丢弃多余参数的 lambda，
                # 避免 bool 被透传给仅接受 file_path 字符串的回调函数。
                btn.clicked.connect(lambda *args, cb=callback: cb())
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
            if self.rect().contains(event.position().toPoint()) and not self._disabled:
                self.clicked.emit(self._file_path)
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

            config = self._get_config()
            colors = self._get_colors()
            padding = config["padding"]
            radius = config["radius"]
            gap = config["gap"]

            w = self.width()
            h = self.height()

            opacity = 0.5 if self._disabled else 1.0
            painter.setOpacity(opacity)

            # Card background
            if self._hovered and not self._disabled:
                bg_color = colors["bg_hover"]
            else:
                bg_color = colors["bg"]

            painter.setBrush(bg_color)
            card_rect = QRectF(0, 0, w, h)
            painter.drawRoundedRect(card_rect, radius, radius)

            # Card border
            painter.setBrush(Qt.NoBrush)
            pen = QPen(colors["border"], 1)
            painter.setPen(pen)
            painter.drawRoundedRect(card_rect, radius, radius)

            painter.setPen(Qt.NoPen)

            # Shadow on hover
            if self._hovered and not self._disabled:
                painter.setBrush(colors["shadow"])
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
                painter.setBrush(colors["media_bg"])

            media_rect = QRectF(media_x, media_y, media_size, media_size)
            painter.drawRoundedRect(media_rect, 4, 4)

            # Media content — 精确匹配 FileCardDelegate._draw_icon_pixmap
            if self._media_pixmap and not self._media_pixmap.isNull():
                # DPR 感知：QPixmap.width() 返回物理像素，除以 DPR 得逻辑尺寸
                pix = self._media_pixmap
                dpr = pix.devicePixelRatio()
                lw = pix.width() / dpr if dpr > 0 else pix.width()
                lh = pix.height() / dpr if dpr > 0 else pix.height()
                if lw > 0 and lh > 0:
                    display_size = int(media_size)
                    if lw > display_size or lh > display_size:
                        pix = pix.scaled(display_size, display_size,
                                         Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        dpr = pix.devicePixelRatio()
                        lw = pix.width() / dpr
                        lh = pix.height() / dpr
                    offset_x = int(media_rect.x() + (media_size - lw) / 2.0)
                    offset_y = int(media_rect.y() + (media_size - lh) / 2.0)
                    painter.drawPixmap(offset_x, offset_y, pix)
            elif self._media_icon:
                icon_font = QFont("Segoe UI Symbol", icon_size, QFont.Normal)
                painter.setFont(icon_font)
                if self._disabled:
                    painter.setPen(tm.alpha_of(tm.mid, 60))
                else:
                    painter.setPen(colors["icon"])
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
                # 文字块整体垂直居中，与文件选择器 list 模式卡片排列一致
                text_block_h = self._calc_text_height(config)
                text_y = (h - text_block_h) / 2.0
                text_w = w - text_x - padding
                text_h = text_block_h
            else:
                text_x = padding
                text_y = media_y + media_size + gap
                text_w = w - padding * 2
                text_h = h - text_y - padding

            text_rect = QRectF(text_x, text_y, text_w, text_h)
            self._draw_text(painter, text_rect, config, colors)

            # Grayscale filter for disabled
            if self._disabled:
                painter.setOpacity(0.5)

        finally:
            if painter.isActive():
                painter.end()

    def _draw_text(self, painter: QPainter, rect: QRectF, config: dict, colors: dict):
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
                painter.setPen(colors["title"])
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
                painter.setPen(colors["subtitle"])
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
                painter.setPen(colors["desc"])
            fm = QFontMetrics(font)
            # Word wrap the description
            text_rect = QRectF(x, y, max_w, rect.bottom() - y)
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, self._desc)
