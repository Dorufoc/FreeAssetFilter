"""Styled Player Bar component - matches web player-bar exactly."""

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QApplication, QSizePolicy,
)
from PySide6.QtCore import (
    Qt, Signal, QRectF, QPoint, QPropertyAnimation,
    QEasingCurve, Property, QTimer, QEvent, QSize,
)
from PySide6.QtGui import (
    QPainter, QColor, QPaintEvent, QFont, QMouseEvent,
    QPen, QFontMetrics, QActionEvent, QIcon, QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
import re
from pathlib import Path
import math

from components.styled_slider import StyledSlider, SliderTrack
from theme import tm


# ═══════════════════════════════════════════════════════════════
#  Popup Helpers
# ═══════════════════════════════════════════════════════════════


class _PlayerPopup(QWidget):
    """Base popup window for player controls (frameless, dark themed)."""

    def __init__(self, parent=None):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._radius = 8
        self._padding = 8
        self._target_w = 200
        self._target_h = 100
        self._closing_internally = False

        self._fade = QPropertyAnimation(self, b"windowOpacity")
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._slide = QPropertyAnimation(self, b"geometry")
        self._slide.setEasingCurve(QEasingCurve.OutCubic)

    def paintEvent(self, event: QPaintEvent):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = self._radius

        # Background
        p.setPen(Qt.NoPen)
        p.setBrush(tm.alpha_of(tm.surface, 85))
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        # Border
        p.setPen(QPen(tm.alpha_of(tm.mid, 30), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), r, r)
        p.end()

    def show_animated(self, anchor_global: QPoint, popup_w: int, popup_h: int):
        """Fade + slide popup open, anchored above the given point."""
        x = anchor_global.x() - popup_w + 40  # right-aligned to button
        y = anchor_global.y() - popup_h - 8   # above + 8px gap

        # Keep on screen
        screen = QApplication.primaryScreen()
        if screen:
            sg = screen.availableGeometry()
            x = max(sg.x() + 8, min(x, sg.right() - popup_w - 8))
            y = max(sg.y() + 8, y)

        self._target_w = popup_w
        self._target_h = popup_h

        start_h = 10
        self.setGeometry(x, y + popup_h - start_h, popup_w, start_h)
        self.setWindowOpacity(0.0)
        super().show()
        self.raise_()
        self.activateWindow()

        self._fade.stop()
        self._fade.setDuration(180)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)

        self._slide.stop()
        self._slide.setDuration(200)
        self._slide.setStartValue(self.geometry())
        self._slide.setEndValue(QRectF(x, y, popup_w, popup_h))

        self._fade.start()
        self._slide.start()

    def close_animated(self):
        """Slide up + fade out."""
        self._closing_internally = True

        self._fade.stop()
        self._fade.setDuration(120)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)

        self._slide.stop()
        self._slide.setDuration(120)
        self._slide.setStartValue(self.geometry())
        end = QRectF(self.geometry())
        end.setHeight(8)
        self._slide.setEndValue(end.toRect())

        self._slide.finished.connect(self._close_and_reset)
        self._fade.start()
        self._slide.start()

    def _close_and_reset(self):
        self._slide.finished.disconnect(self._close_and_reset)
        self.close()
        self._closing_internally = False

    def hideEvent(self, event):
        super().hideEvent(event)
        self._closing_internally = False


# ═══════════════════════════════════════════════════════════════
#  Speed Popup
# ═══════════════════════════════════════════════════════════════


_SPEED_OPTIONS = ["0.5x", "0.75x", "1.0x", "1.25x", "1.5x", "2.0x"]


class _SpeedPopup(_PlayerPopup):
    """Flat speed selection popup (reuses select-item style from web)."""

    speed_selected = Signal(str)

    def __init__(self, current_speed: str = "1.0x", parent=None):
        super().__init__(parent)
        self._current_speed = current_speed
        self._item_h = 34
        self._item_count = len(_SPEED_OPTIONS)
        self._radius = 8

        w = 120
        h = self._item_count * self._item_h + self._padding * 2
        self.resize(w, h)

    def paintEvent(self, event: QPaintEvent):
        super().paintEvent(event)
        # Draw each speed item
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        for i, speed in enumerate(_SPEED_OPTIONS):
            y = self._padding + i * self._item_h
            selected = (speed == self._current_speed)

            # Selection highlight
            if selected:
                p.setPen(Qt.NoPen)
                p.setBrush(tm.alpha_of(tm.accent, 12))
                p.drawRoundedRect(
                    QRectF(4, y, self.width() - 8, self._item_h - 2), 4, 4
                )

            # Text
            font = QFont("Microsoft YaHei UI", 13)
            p.setFont(font)
            if selected:
                p.setPen(tm.accent)
            else:
                p.setPen(tm.mid)

            p.drawText(
                QRectF(0, y, self.width(), self._item_h),
                Qt.AlignCenter,
                speed,
            )

        p.end()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            idx = int((event.pos().y() - self._padding) // self._item_h)
            if 0 <= idx < len(_SPEED_OPTIONS):
                self._current_speed = _SPEED_OPTIONS[idx]
                self.speed_selected.emit(self._current_speed)
                self.update()
                self.close_animated()
        super().mousePressEvent(event)


# ═══════════════════════════════════════════════════════════════
#  Volume Popup
# ═══════════════════════════════════════════════════════════════


class _VolumePopup(_PlayerPopup):
    """Volume popup with mute toggle + slider."""

    volume_changed = Signal(float)   # 0.0-1.0
    mute_toggled = Signal(bool)

    def __init__(self, volume: float = 0.7, muted: bool = False, parent=None):
        super().__init__(parent)
        self._volume = volume
        self._muted = muted
        self._radius = 8
        self._padding = 10

        # Slider
        self._slider = StyledSlider(value=volume, size="sm")
        self._slider.setFixedWidth(140)
        self._slider.value_changed.connect(self._on_slider_changed)

        # Layout
        layout = QHBoxLayout(self)
        layout.setContentsMargins(self._padding, self._padding, self._padding, self._padding)
        layout.setSpacing(8)

        # Mute button
        self._mute_btn = QPushButton("🔊" if not muted else "🔇")
        self._mute_btn.setFixedSize(32, 32)
        muted_color = tm.mid.name()
        hover_bg = tm.surface.name()
        self._mute_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 4px;
                color: {muted_color};
                font-size: 16px;
            }}
            QPushButton:hover {{
                background: {hover_bg};
            }}
            QPushButton:pressed {{
                background: {hover_bg};
                transform: scale(0.92);
            }}
        """)
        self._mute_btn.clicked.connect(self._on_mute_clicked)

        layout.addWidget(self._mute_btn)
        layout.addWidget(self._slider, alignment=Qt.AlignVCenter)
        layout.addStretch()

        w = 32 + 8 + 140 + self._padding * 2 + 8
        # Natural height: top-padding + max(mute_btn, slider) + bottom-padding
        nat_h = self._padding + 32 + self._padding
        self.resize(w, nat_h)

    def _on_slider_changed(self, value: float):
        self._volume = value
        self.volume_changed.emit(value)

    def _on_mute_clicked(self):
        self._muted = not self._muted
        self._mute_btn.setText("🔇" if self._muted else "🔊")
        self.mute_toggled.emit(self._muted)

    def set_volume(self, value: float):
        self._volume = value
        self._slider.value = value

    def set_muted(self, muted: bool):
        self._muted = muted
        self._mute_btn.setText("🔇" if muted else "🔊")


# ═══════════════════════════════════════════════════════════════
#  Settings Popup
# ═══════════════════════════════════════════════════════════════


class _SettingsPopup(_PlayerPopup):
    """Settings popup with collapsible submenus."""

    setting_changed = Signal(str, str)  # section, value

    MENU_SECTIONS = [
        {
            "label": "音轨",
            "items": ["中文 2.0", "English 5.1", "日本語 2.0"],
            "default": "中文 2.0",
        },
        {
            "label": "字幕",
            "items": ["关闭", "中文", "English"],
            "default": "关闭",
        },
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._radius = 8
        self._padding = 6
        self._values = {s["label"]: s["default"] for s in self.MENU_SECTIONS}
        self._open_section = None  # currently expanded section label
        # Calculate height
        self._item_h = 32
        self._sub_item_h = 28
        header_count = len(self.MENU_SECTIONS)
        content_h = header_count * self._item_h + self._padding * 2
        self.resize(200, content_h)

        # Geometry animation for smooth expand/collapse
        self._expand_anim = QPropertyAnimation(self, b"geometry")
        self._expand_anim.setDuration(180)
        self._expand_anim.setEasingCurve(QEasingCurve.OutCubic)

    def paintEvent(self, event: QPaintEvent):
        super().paintEvent(event)

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        y = self._padding
        w = self.width()

        for section in self.MENU_SECTIONS:
            label = section["label"]
            value = self._values.get(label, "")
            is_open = (self._open_section == label)

            # Section header
            header_rect = QRectF(4, y, w - 8, self._item_h)

            # Hover highlight (always drawn when open or not)
            p.setPen(Qt.NoPen)
            p.setBrush(Qt.NoBrush)

            # Label
            font = QFont("Microsoft YaHei UI", 12, 500)
            p.setFont(font)
            p.setPen(tm.text)
            p.drawText(
                QRectF(12, y, w - 80, self._item_h),
                Qt.AlignVCenter,
                label,
            )

            # Value
            font_val = QFont("Microsoft YaHei UI", 11)
            p.setFont(font_val)
            p.setPen(tm.alpha_of(tm.mid, 60))
            p.drawText(
                QRectF(w - 80, y, 50, self._item_h),
                Qt.AlignVCenter | Qt.AlignRight,
                value,
            )

            # Arrow
            arrow = "▶" if not is_open else "▼"
            p.setPen(tm.alpha_of(tm.mid, 60))
            font_arr = QFont("Segoe UI Symbol", 10)
            p.setFont(font_arr)
            p.drawText(
                QRectF(w - 28, y, 20, self._item_h),
                Qt.AlignVCenter | Qt.AlignRight,
                arrow,
            )

            y += self._item_h

            # Sub-items (if open)
            if is_open:
                p.setPen(Qt.NoPen)
                p.setBrush(tm.alpha_of(tm.surface, 85))
                for item in section["items"]:
                    sub_rect = QRectF(8, y, w - 16, self._sub_item_h)
                    is_sel = (item == value)

                    if is_sel:
                        p.setPen(Qt.NoPen)
                        p.setBrush(tm.alpha_of(tm.accent, 10))
                        p.drawRoundedRect(
                            QRectF(16, y, w - 32, self._sub_item_h - 2), 4, 4
                        )

                    font_sub = QFont("Microsoft YaHei UI", 12)
                    p.setFont(font_sub)
                    if is_sel:
                        p.setPen(tm.accent)
                    else:
                        p.setPen(tm.mid)
                    p.drawText(
                        QRectF(24, y, w - 48, self._sub_item_h),
                        Qt.AlignVCenter,
                        item,
                    )

                    y += self._sub_item_h

        p.end()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)

        y = event.pos().y() - self._padding
        w = self.width()

        # Check section headers
        acc_y = 0
        for section in self.MENU_SECTIONS:
            header_h = self._item_h
            sub_count = len(section["items"]) if self._open_section == section["label"] else 0
            section_h = header_h + sub_count * self._sub_item_h

            if acc_y <= y < acc_y + header_h:
                # Clicked header
                if self._open_section == section["label"]:
                    self._open_section = None
                else:
                    self._open_section = section["label"]
                self._resize_to_fit()
                self.update()
                return

            # Check sub-items
            if self._open_section == section["label"]:
                sub_start = acc_y + header_h
                for i, item in enumerate(section["items"]):
                    if sub_start + i * self._sub_item_h <= y < sub_start + (i + 1) * self._sub_item_h:
                        self._values[section["label"]] = item
                        self.setting_changed.emit(section["label"], item)
                        self.update()
                        return

            acc_y += section_h

        super().mousePressEvent(event)

    def _resize_to_fit(self):
        """Recalculate height and expand UPWARD (bottom edge stays fixed)."""
        new_h = self._padding * 2
        for section in self.MENU_SECTIONS:
            new_h += self._item_h
            if self._open_section == section["label"]:
                new_h += len(section["items"]) * self._sub_item_h

        old_geo = self.geometry()
        old_h = old_geo.height()
        if new_h == old_h:
            return

        # Keep bottom edge fixed → move top up by (new_h - old_h)
        new_y = old_geo.y() - (new_h - old_h)

        self._expand_anim.stop()
        self._expand_anim.setStartValue(old_geo)
        self._expand_anim.setEndValue(QRectF(old_geo.x(), new_y, old_geo.width(), new_h))
        self._expand_anim.start()


# ═══════════════════════════════════════════════════════════════
#  Player Bar
# ═══════════════════════════════════════════════════════════════


class StyledPlayerBar(QWidget):
    """Styled player control bar matching the web component.

    Features:
    - Play/pause toggle
    - Progress slider with time labels
    - Volume popup (mute + slider)
    - Speed popup (flat speed list)
    - Settings popup (track/subtitle submenus)
    - Fullscreen toggle
    """

    # Signals for external integration
    play_paused = Signal(bool)          # True=playing
    progress_changed = Signal(float)    # 0.0-1.0
    progress_pressed = Signal()         # 用户开始拖动进度条
    progress_released = Signal()        # 用户结束拖动进度条
    volume_changed = Signal(float)      # 0.0-1.0
    mute_changed = Signal(bool)
    speed_changed = Signal(str)
    fullscreen_toggled = Signal(bool)
    setting_changed = Signal(str, str)  # section, value

    # Appearance constants
    BAR_COLOR = tm.alpha_of(tm.surface, 95)
    BAR_BORDER = tm.alpha_of(tm.mid, 30)
    BORDER_RADIUS = 0
    BTN_SIZE = 36
    BTN_RADIUS = 4

    def __init__(
        self,
        parent=None,
        current_time: str = "00:00",
        total_time: str = "00:00",
        progress: float = 0.0,
        volume: float = 0.7,
        muted: bool = False,
        current_speed: str = "1.0x",
        playing: bool = False,
    ):
        super().__init__(parent)

        self._playing = playing
        self._current_time = current_time
        self._total_time = total_time
        self._progress = progress
        self._volume = volume
        self._muted = muted
        self._current_speed = current_speed
        self._fullscreen = False

        # Popup references
        self._volume_popup = None
        self._speed_popup = None
        self._settings_popup = None

        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setFixedHeight(52)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Pre-create SVG icons
        self._play_icon = self._create_svg_icon("play.svg")
        self._pause_icon = self._create_svg_icon("pause.svg")
        self._speaker_icon = self._create_svg_icon("speaker.svg")
        self._speaker_slash_icon = self._create_svg_icon("speaker_slash.svg")
        self._speed_icon = self._create_svg_icon("speed.svg")
        self._more_icon = self._create_svg_icon("more.svg")
        self._maxsize_icon = self._create_svg_icon("maxsize.svg")

        self._setup_ui()

        # Regenerate icons on theme change
        tm.theme_changed.connect(self._on_theme_changed_icons)

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        # ===== Left Group =====
        left_group = QWidget()
        left_group.setAttribute(Qt.WA_StyledBackground, False)
        left_layout = QHBoxLayout(left_group)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        # Play/Pause
        self._play_btn = QPushButton()
        self._play_btn.setIcon(self._play_icon)
        self._play_btn.setIconSize(QSize(20, 20))
        self._play_btn.setFixedSize(self.BTN_SIZE, self.BTN_SIZE)
        self._play_btn.setStyleSheet(self._btn_style())
        self._play_btn.clicked.connect(self._on_play_clicked)
        left_layout.addWidget(self._play_btn)

        # Progress area
        progress_wrap = QWidget()
        progress_wrap.setAttribute(Qt.WA_StyledBackground, False)
        prog_layout = QHBoxLayout(progress_wrap)
        prog_layout.setContentsMargins(0, 0, 0, 0)
        prog_layout.setSpacing(8)

        # Current time
        time_color = tm.mid.name()
        self._time_current = QLabel(self._current_time)
        self._time_current.setStyleSheet(
            f"color: {time_color}; font-size: 12px; font-family: 'Consolas', 'Courier New', monospace;"
            "background: transparent; min-width: 40px;"
        )
        self._time_current.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        # Progress slider（自适应宽度）
        self._progress_slider = StyledSlider(value=self._progress, size="sm")
        self._progress_slider.value_changed.connect(self._on_progress_changed)
        self._progress_slider.pressed.connect(self.progress_pressed.emit)
        self._progress_slider.released.connect(self.progress_released.emit)

        # Total time
        self._time_total = QLabel(self._total_time)
        self._time_total.setStyleSheet(
            f"color: {time_color}; font-size: 12px; font-family: 'Consolas', 'Courier New', monospace;"
            "background: transparent; min-width: 40px;"
        )
        self._time_total.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        prog_layout.addWidget(self._time_current)
        prog_layout.addWidget(self._progress_slider, stretch=1)  # 滑动条自适应拉伸
        prog_layout.addWidget(self._time_total)

        left_layout.addWidget(progress_wrap, stretch=1)

        layout.addWidget(left_group, stretch=1)

        # ===== Right Group =====
        right_group = QWidget()
        right_group.setAttribute(Qt.WA_StyledBackground, False)
        right_layout = QHBoxLayout(right_group)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(2)

        self.BTN_STYLE = self._btn_style()
        BTN_HOVER = self._btn_style(hover=True)

        # Volume
        self._vol_btn = QPushButton()
        self._vol_btn.setIcon(self._speaker_icon)
        self._vol_btn.setIconSize(QSize(20, 20))
        self._vol_btn.setFixedSize(self.BTN_SIZE, self.BTN_SIZE)
        self._vol_btn.setStyleSheet(self._btn_style())
        self._vol_btn.clicked.connect(self._on_volume_clicked)
        right_layout.addWidget(self._vol_btn)

        # Speed
        self._speed_btn = QPushButton()
        self._speed_btn.setIcon(self._speed_icon)
        self._speed_btn.setIconSize(QSize(20, 20))
        self._speed_btn.setFixedSize(self.BTN_SIZE, self.BTN_SIZE)
        self._speed_btn.setStyleSheet(self._btn_style())
        self._speed_btn.clicked.connect(self._on_speed_clicked)
        right_layout.addWidget(self._speed_btn)

        # Settings
        self._settings_btn = QPushButton()
        self._settings_btn.setIcon(self._more_icon)
        self._settings_btn.setIconSize(QSize(20, 20))
        self._settings_btn.setFixedSize(self.BTN_SIZE, self.BTN_SIZE)
        self._settings_btn.setStyleSheet(self._btn_style())
        self._settings_btn.clicked.connect(self._on_settings_clicked)
        right_layout.addWidget(self._settings_btn)

        # Fullscreen
        self._fs_btn = QPushButton()
        self._fs_btn.setIcon(self._maxsize_icon)
        self._fs_btn.setIconSize(QSize(20, 20))
        self._fs_btn.setFixedSize(self.BTN_SIZE, self.BTN_SIZE)
        self._fs_btn.setStyleSheet(self._btn_style())
        self._fs_btn.clicked.connect(self._on_fullscreen_clicked)
        right_layout.addWidget(self._fs_btn)

        layout.addWidget(right_group)

    def _btn_style(self, hover: bool = False) -> str:
        text_sec = tm.mid.name()
        text_pri = tm.text.name()
        hover_bg = tm.surface.name()
        base = f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: {self.BTN_RADIUS}px;
                color: {text_sec if not hover else text_pri};
                font-size: 16px;
            }}
        """
        if hover:
            base = base.replace("background: transparent;", f"background: {hover_bg};")
        base += f"""
            QPushButton:hover {{
                background: {hover_bg};
                color: {text_pri};
            }}
            QPushButton:pressed {{
                background: {hover_bg};
            }}
        """
        return base

    # ── Event handlers ─────────────────────────────────────────

    def _on_play_clicked(self):
        self._playing = not self._playing
        self._play_btn.setIcon(self._pause_icon if self._playing else self._play_icon)
        self.play_paused.emit(self._playing)

    def _on_progress_changed(self, value: float):
        self._progress = value
        self.progress_changed.emit(value)

    def _on_volume_clicked(self):
        self._close_other_popups("volume")
        if self._volume_popup and self._volume_popup.isVisible():
            self._volume_popup.close_animated()
            return

        self._volume_popup = _VolumePopup(
            volume=self._volume,
            muted=self._muted,
        )
        self._volume_popup.volume_changed.connect(self._on_volume_slider)
        self._volume_popup.mute_toggled.connect(self._on_mute_toggle)

        btn_global = self._vol_btn.mapToGlobal(QPoint(0, 0))
        pw, ph = self._volume_popup.width(), self._volume_popup.height()
        self._volume_popup.show_animated(btn_global, pw, ph)

    def _on_speed_clicked(self):
        self._close_other_popups("speed")
        if self._speed_popup and self._speed_popup.isVisible():
            self._speed_popup.close_animated()
            return

        self._speed_popup = _SpeedPopup(current_speed=self._current_speed)
        self._speed_popup.speed_selected.connect(self._on_speed_selected)

        btn_global = self._speed_btn.mapToGlobal(QPoint(0, 0))
        pw, ph = self._speed_popup.width(), self._speed_popup.height()
        self._speed_popup.show_animated(btn_global, pw, ph)

    def _on_settings_clicked(self):
        self._close_other_popups("settings")
        if self._settings_popup and self._settings_popup.isVisible():
            self._settings_popup.close_animated()
            return

        self._settings_popup = _SettingsPopup()
        self._settings_popup.setting_changed.connect(self._on_popup_setting)

        btn_global = self._settings_btn.mapToGlobal(QPoint(0, 0))
        pw = max(self._settings_popup.width(), 220)
        ph = self._settings_popup.height()
        self._settings_popup.show_animated(btn_global, pw, ph)

    def _on_fullscreen_clicked(self):
        self._fullscreen = not self._fullscreen
        self._fs_btn.setStyleSheet(self._btn_style(hover=self._fullscreen))
        self.fullscreen_toggled.emit(self._fullscreen)

    # ── Popup callbacks ────────────────────────────────────────

    def _on_volume_slider(self, value: float):
        self._volume = value
        self.volume_changed.emit(value)
        self._muted = (value < 0.01)
        self._vol_btn.setIcon(self._speaker_slash_icon if self._muted else self._speaker_icon)

    def _on_mute_toggle(self, muted: bool):
        self._muted = muted
        self._vol_btn.setIcon(self._speaker_slash_icon if muted else self._speaker_icon)
        self.mute_changed.emit(muted)

    def _on_speed_selected(self, speed: str):
        self._current_speed = speed
        self.speed_changed.emit(speed)

    def _on_popup_setting(self, section: str, value: str):
        self.setting_changed.emit(section, value)

    def _close_other_popups(self, exclude: str = ""):
        if exclude != "volume" and self._volume_popup and self._volume_popup.isVisible():
            self._volume_popup.close_animated()
        if exclude != "speed" and self._speed_popup and self._speed_popup.isVisible():
            self._speed_popup.close_animated()
        if exclude != "settings" and self._settings_popup and self._settings_popup.isVisible():
            self._settings_popup.close_animated()

    def _on_theme_changed_icons(self):
        """主题切换时重新生成 SVG 图标"""
        self._play_icon = self._create_svg_icon("play.svg")
        self._pause_icon = self._create_svg_icon("pause.svg")
        self._speaker_icon = self._create_svg_icon("speaker.svg")
        self._speaker_slash_icon = self._create_svg_icon("speaker_slash.svg")
        self._speed_icon = self._create_svg_icon("speed.svg")
        self._more_icon = self._create_svg_icon("more.svg")
        self._maxsize_icon = self._create_svg_icon("maxsize.svg")

        # Update current button icons
        self._play_btn.setIcon(self._pause_icon if self._playing else self._play_icon)
        self._vol_btn.setIcon(self._speaker_slash_icon if self._muted else self._speaker_icon)
        self._speed_btn.setIcon(self._speed_icon)
        self._settings_btn.setIcon(self._more_icon)
        self._fs_btn.setIcon(self._maxsize_icon)

    # ── Paint ──────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        if not painter.isActive():
            return

        try:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(self.BAR_COLOR)
            painter.drawRoundedRect(
                QRectF(0, 0, self.width(), self.height()),
                self.BORDER_RADIUS,
                self.BORDER_RADIUS,
            )

            # Top border line
            painter.setPen(QPen(self.BAR_BORDER, 1))
            painter.drawLine(0, 0, int(self.width()), 0)

        finally:
            if painter.isActive():
                painter.end()

    # ── Public API ─────────────────────────────────────────────

    def set_current_time(self, text: str):
        self._current_time = text
        self._time_current.setText(text)

    def set_total_time(self, text: str):
        self._total_time = text
        self._time_total.setText(text)

    def set_progress(self, value: float):
        self._progress = value
        self._progress_slider.value = value

    def set_volume(self, value: float):
        self._volume = value
        if self._volume_popup:
            self._volume_popup.set_volume(value)

    def set_muted(self, muted: bool):
        self._muted = muted
        self._vol_btn.setIcon(self._speaker_slash_icon if muted else self._speaker_icon)
        if self._volume_popup:
            self._volume_popup.set_muted(muted)

    def set_speed(self, speed_str: str) -> None:
        """从外部同步播放速度显示

        Args:
            speed_str: 速度字符串，如 "1.0x", "1.5x", "2.0x"
        """
        self._current_speed = speed_str
        if hasattr(self, '_speed_popup') and self._speed_popup and self._speed_popup.isVisible():
            self._speed_popup._current_speed = speed_str
            self._speed_popup.update()

    def _create_svg_icon(self, svg_name: str) -> QIcon:
        """从 SVG 文件创建主题感知的 QIcon

        1. 读取 SVG 文件
        2. 通过 tm.process_svg() 将 #FFF/#000 替换为 surface/text 色
        3. 为无 fill 属性的 SVG 根元素添加 tm.text 作为默认 fill
        4. 通过 QSvgRenderer 渲染为 QPixmap → QIcon

        Args:
            svg_name: SVG 文件名，如 "play.svg"

        Returns:
            QIcon: 主题适配后的图标
        """
        icons_dir = Path(__file__).resolve().parent.parent.parent / "icons"
        svg_path = icons_dir / svg_name
        if not svg_path.exists():
            return QIcon()

        try:
            with open(svg_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()

            # 1. ThemeManager 预处理 (替换 #FFF→surface, #000→text)
            svg_content = tm.process_svg(svg_content)

            # 2. 对没有 fill 属性的 SVG 根元素添加 tm.text 作为默认 fill
            color_hex = tm.text.name()
            svg_content = re.sub(
                r'(<svg\b[^>]*)(>)',
                lambda m: f'{m.group(1)} fill="{color_hex}"{m.group(2)}'
                if 'fill=' not in m.group(1) else m.group(0),
                svg_content,
                count=1
            )

            # 3. 渲染到 QPixmap
            pixmap = QPixmap(20, 20)
            pixmap.fill(Qt.transparent)
            renderer = QSvgRenderer(svg_content.encode('utf-8'))
            painter = QPainter(pixmap)
            if renderer.isValid():
                renderer.render(painter)
            painter.end()
            return QIcon(pixmap)
        except Exception:
            return QIcon()

    def set_playing(self, playing: bool):
        self._playing = playing
        self._play_btn.setIcon(self._pause_icon if playing else self._play_icon)
