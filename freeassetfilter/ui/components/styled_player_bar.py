"""Styled Player Bar component - matches web player-bar exactly."""

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QApplication, QSizePolicy, QProgressBar, QLayout,
)
from PySide6.QtCore import (
    Qt, Signal, QRect, QRectF, QPoint, QPropertyAnimation,
    QEasingCurve, Property, QTimer, QEvent, QSize,
)
from PySide6.QtGui import (
    QPainter, QColor, QPaintEvent, QFont, QMouseEvent,
    QPen, QFontMetrics, QActionEvent, QCursor,
)
from pathlib import Path
from typing import Optional

from components.styled_button import StyledButton
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
        """Fade + slide popup open, anchored above the given point (centered horizontally)."""
        x = anchor_global.x() - popup_w // 2  # center horizontally on anchor
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


_SPEED_OPTIONS = ["0.5x", "0.75x", "1.0x", "1.25x", "1.5x", "2.0x", "3.0x"]


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
    """Volume popup with vertical slider + mute toggle."""

    volume_changed = Signal(float)   # 0.0-1.0
    mute_toggled = Signal(bool)

    def __init__(self, volume: float = 0.7, muted: bool = False, parent=None):
        super().__init__(parent)
        self._volume = 0.0 if muted else volume
        self._radius = 8
        self._padding = 10
        self._slider_height = 120

        # Vertical slider
        self._slider = StyledSlider(value=self._volume, size="sm", orientation=Qt.Vertical)
        self._slider.setFixedHeight(self._slider_height)
        self._slider.value_changed.connect(self._on_slider_changed)

        # Layout
        # Volume percent button (replaces emoji mute icon)
        self._mute_btn = StyledButton(text=self._format_volume_text(), variant="ghost", size="sm")
        self._mute_btn.setFixedSize(44, 32)
        self._mute_btn.clicked.connect(self._on_mute_clicked)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(self._padding, self._padding, self._padding, self._padding)
        layout.setSpacing(8)
        # 允许窗口在动画期间小于布局最小尺寸，避免被布局强制撑成完整高度而从下方整体平移
        layout.setSizeConstraint(QLayout.SetNoConstraint)
        # 顶部对齐，保证弹窗从底部向上展开时内容与倍速/设置菜单一样从顶部逐行露出
        layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

        # 百分比在上，滑块在下
        layout.addWidget(self._mute_btn, alignment=Qt.AlignCenter)
        layout.addWidget(self._slider, alignment=Qt.AlignCenter)

        # Popup size: 保证能容纳音量百分比按钮，宽度取 slider 与按钮的较大值
        slider_width = self._slider.sizeHint().width()
        content_w = max(slider_width, 44)
        w = content_w + self._padding * 2
        nat_h = self._padding + 32 + 8 + self._slider_height + self._padding
        self.resize(w, nat_h)

    def _format_volume_text(self) -> str:
        return f"{int(round(self._volume * 100))}%"

    def _update_button_text(self):
        self._mute_btn.setText(self._format_volume_text())

    def _on_slider_changed(self, value: float):
        self._volume = value
        self._update_button_text()
        self.volume_changed.emit(value)

    def _on_mute_clicked(self):
        """点击百分比按钮：非 0 时切到 0%，为 0 时切到 100%。"""
        if self._volume > 0:
            self.set_volume(0.0)
            self.mute_toggled.emit(True)
            self.volume_changed.emit(0.0)
        else:
            self.set_volume(1.0)
            self.mute_toggled.emit(False)
            self.volume_changed.emit(1.0)

    def set_volume(self, value: float):
        self._volume = value
        self._slider.value = value
        self._update_button_text()

    def set_muted(self, muted: bool):
        """外部静音状态同步：静音置 0%，取消静音置 100%。"""
        if muted:
            self.set_volume(0.0)
        else:
            self.set_volume(1.0)


# ═══════════════════════════════════════════════════════════════
#  Settings Popup
# ═══════════════════════════════════════════════════════════════


class _SettingsPopup(_PlayerPopup):
    """Settings popup with collapsible submenus for audio/subtitle tracks."""

    setting_changed = Signal(str, str)  # section ("audio"|"subtitle"), track_id
    add_subtitle_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._radius = 8
        self._padding = 6
        # Dynamic sections: audio track (index 0) and subtitle track (index 1)
        self._sections = [
            {"label": "音轨", "type": "audio", "items": [], "selected_id": None, "selected_label": ""},
            {"label": "字幕", "type": "subtitle", "items": [], "selected_id": None, "selected_label": ""},
        ]
        self._open_section = None  # currently expanded section label
        self._item_h = 32
        self._sub_item_h = 28
        header_count = 2
        content_h = header_count * self._item_h + self._padding * 2
        self.resize(200, content_h)

        # Geometry animation for smooth expand/collapse
        self._expand_anim = QPropertyAnimation(self, b"geometry")
        self._expand_anim.setDuration(180)
        self._expand_anim.setEasingCurve(QEasingCurve.OutCubic)

    def show_animated(self, anchor_global: QPoint, popup_w: int, popup_h: int):
        """设置弹窗以锚点为右边缘水平右对齐、上方弹出。"""
        x = anchor_global.x() - popup_w  # 弹窗右边缘与锚点对齐
        y = anchor_global.y() - popup_h - 8  # 上方 + 8px 间隙

        # Keep on screen
        screen = QApplication.primaryScreen()
        if screen:
            sg = screen.availableGeometry()
            x = max(sg.x() + 8, x)
            y = max(sg.y() + 8, y)

        self._target_w = popup_w
        self._target_h = popup_h

        start_h = 10
        self.setGeometry(x, y + popup_h - start_h, popup_w, start_h)
        self.setWindowOpacity(0.0)
        super(_PlayerPopup, self).show()
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

    def set_audio_tracks(self, tracks: list[dict]) -> None:
        """设置音轨列表

        tracks = [{"id": 1, "label": "中文 2.0", "selected": True}, ...]
        """
        section = self._sections[0]
        section["items"] = tracks
        section["selected_id"] = None
        section["selected_label"] = ""
        for t in tracks:
            if t.get("selected"):
                section["selected_id"] = t["id"]
                section["selected_label"] = t["label"]
                break
        self.update()

    def set_subtitle_tracks(self, tracks: list[dict]) -> None:
        """设置字幕列表

        tracks = [{"id": 1, "label": "中文", "selected": True}, ...,
                  {"id": "add", "label": "+ 添加…", "is_add": True}]
        """
        section = self._sections[1]
        section["items"] = tracks
        section["selected_id"] = None
        section["selected_label"] = ""
        for t in tracks:
            if t.get("selected"):
                section["selected_id"] = t["id"]
                section["selected_label"] = t["label"]
                break
        self.update()

    def paintEvent(self, event: QPaintEvent):
        super().paintEvent(event)

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        y = self._padding
        w = self.width()

        for section in self._sections:
            label = section["label"]
            value = section["selected_label"]
            is_open = (self._open_section == label)

            # Section header
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
                    is_sel = (item["id"] == section["selected_id"])

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
                        item["label"],
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
        for section in self._sections:
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
                        # "+ 添加…" handler
                        if item.get("is_add"):
                            self.add_subtitle_requested.emit()
                            self._open_section = None
                            self._resize_to_fit()
                            self.update()
                            return

                        section["selected_id"] = item["id"]
                        section["selected_label"] = item["label"]
                        self.setting_changed.emit(section["type"], item["id"])
                        self.update()
                        return

            acc_y += section_h

        super().mousePressEvent(event)

    def _resize_to_fit(self):
        """Recalculate height and expand UPWARD (bottom edge stays fixed)."""
        new_h = self._padding * 2
        for section in self._sections:
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
#  OSD Widget
# ═══════════════════════════════════════════════════════════════


class _OSDWidget(QWidget):
    """浮动 OSD 叠加层（用于显示播放状态消息和进度信息）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)

        # OSD 容器布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 文本模式（显示纯文本消息，如"播放"、"暂停"、"1.0x"）
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet("""
            QLabel {
                background-color: rgba(0, 0, 0, 180);
                color: white;
                padding: 8px 16px;
                border-radius: 6px;
                font-size: 16px;
                font-weight: 500;
            }
        """)
        layout.addWidget(self._label)

        # 进度模式（显示 seek 进度：时间 + 进度条 + 总时长）
        self._progress_widget = QWidget(self)
        self._progress_widget.setStyleSheet("""
            QWidget {
                background-color: rgba(0, 0, 0, 180);
                border-radius: 6px;
            }
        """)
        self._progress_widget.hide()
        progress_layout = QHBoxLayout(self._progress_widget)
        progress_layout.setContentsMargins(12, 8, 12, 8)
        progress_layout.setSpacing(10)

        self._time_label = QLabel(self._progress_widget)
        self._time_label.setStyleSheet("color: white; font-size: 14px; background: transparent;")
        self._time_label.setMinimumWidth(60)
        progress_layout.addWidget(self._time_label)

        # 进度条（QProgressBar 简化版）
        self._progress_bar = QProgressBar(self._progress_widget)
        self._progress_bar.setRange(0, 1000)
        self._progress_bar.setFixedHeight(4)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: rgba(255, 255, 255, 128);
                border: none;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background-color: white;
                border-radius: 2px;
            }
        """)
        progress_layout.addWidget(self._progress_bar, 1)

        self._duration_label = QLabel(self._progress_widget)
        self._duration_label.setStyleSheet("color: white; font-size: 14px; background: transparent;")
        self._duration_label.setMinimumWidth(60)
        self._duration_label.setAlignment(Qt.AlignRight)
        progress_layout.addWidget(self._duration_label)

        layout.addWidget(self._progress_widget)

        # 自动隐藏定时器
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide)

        # 目标控件（OSD 相对于此控件定位）
        self._target_widget: Optional[QWidget] = None

        self.adjustSize()

    def set_target_widget(self, widget: QWidget):
        """设置 OSD 定位的目标控件"""
        self._target_widget = widget

    def show_message(self, message: str, duration: int = 2000):
        """显示纯文本 OSD 消息

        Args:
            message: 显示文本，如"播放"、"暂停"、"1.0x"、"音量 70%"
            duration: 显示时间（毫秒）
        """
        self._progress_widget.hide()
        self._label.setText(message)
        self._label.show()
        self._reposition_and_show(duration)

    def show_seek(self, current_time: float, total_duration: float, direction: str, duration: int = 2000):
        """显示跳转进度 OSD

        Args:
            current_time: 当前播放位置（秒）
            total_duration: 总时长（秒）
            direction: "forward" 或 "backward"
            duration: 显示时间（毫秒）
        """
        self._label.hide()

        current_str = self._format_time(current_time)
        duration_str = self._format_time(total_duration)

        direction_text = "+5s" if direction == "forward" else "-5s"
        self._time_label.setText(f"{direction_text}  {current_str}")
        self._duration_label.setText(duration_str)

        if total_duration > 0:
            progress = int((current_time / total_duration) * 1000)
            self._progress_bar.setValue(progress)
        else:
            self._progress_bar.setValue(0)

        self._progress_widget.show()
        self._reposition_and_show(duration)

    def _reposition_and_show(self, duration: int):
        """根据目标控件重新定位 OSD 并显示"""
        self.adjustSize()

        if self._target_widget:
            # 相对于目标控件顶部居中（使用全局坐标）
            global_pos = self._target_widget.mapToGlobal(QPoint(0, 0))
            target_size = self._target_widget.size()
            x = global_pos.x() + (target_size.width() - self.width()) // 2
            y = global_pos.y() + int(30 * getattr(self._target_widget, '_dpi_scale', 1.0))
        else:
            # 备用：屏幕居中
            screen = QApplication.primaryScreen()
            if screen:
                screen_geo = screen.geometry()
                x = (screen_geo.width() - self.width()) // 2
                y = int(30 * getattr(self, '_dpi_scale', 1.0))
            else:
                x, y = 0, 30

        self.move(x, y)
        self.show()
        self.raise_()
        self._hide_timer.start(duration)

    def _hide(self):
        """隐藏 OSD"""
        self.hide()
        self._label.show()
        self._progress_widget.hide()

    @staticmethod
    def _format_time(seconds: float) -> str:
        if seconds <= 0:
            return "00:00"
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes:02d}:{secs:02d}"


# ═══════════════════════════════════════════════════════════════
#  Float Container
# ═══════════════════════════════════════════════════════════════


class _FloatContainer(QWidget):
    """轻量浮动容器——包裹 StyledPlayerBar 实现底部悬浮"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)

        self._content: Optional[QWidget] = None

        # 淡入淡出动画
        self._fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_anim.setDuration(200)
        self._fade_anim.finished.connect(self._on_fade_finished)
        self._fade_pending_hide = False

        # 布局
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setAlignment(Qt.AlignBottom)

    def set_content(self, widget: QWidget) -> None:
        """设置容器内容"""
        if self._content:
            self._layout.removeWidget(self._content)
        self._content = widget
        widget.setParent(self)
        self._layout.addWidget(widget)

    def clear_content(self) -> None:
        """移除内容"""
        if self._content:
            self._content.setParent(None)
            self._content = None

    def _on_fade_finished(self) -> None:
        """动画完成回调：根据标志执行操作"""
        if self._fade_pending_hide:
            self._fade_pending_hide = False
            self.hide()

    def show_with_animation(self) -> None:
        """淡入显示"""
        self._fade_pending_hide = False
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._fade_anim.stop()
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

    def hide_with_animation(self) -> None:
        """淡出隐藏"""
        self._fade_pending_hide = True
        self._fade_anim.stop()
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.start()


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
    - Floating auto-hide mode (fullscreen)
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
    add_subtitle_requested = Signal()

    # Floating mode signals (fullscreen auto-hide)
    floating_bar_shown = Signal()
    floating_bar_hidden = Signal()

    # Appearance constants
    BAR_COLOR = tm.alpha_of(tm.surface, 95)
    BAR_BORDER = tm.alpha_of(tm.mid, 30)
    BORDER_RADIUS = 0

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

        # 缓存音轨/字幕数据（用于新弹窗创建时填充）
        self._last_audio_tracks: list[dict] = []
        self._last_subtitle_tracks: list[dict] = []

        # ── 浮动模式状态（全屏自动隐藏） ──
        self._float_container: Optional[_FloatContainer] = None
        self._float_target_widget: Optional[QWidget] = None
        self._float_target_rect: Optional[QRect] = None
        self._float_parent: Optional[QWidget] = None
        self._float_parent_layout = None
        self._float_hide_timer: Optional[QTimer] = None
        self._float_mouse_timer: Optional[QTimer] = None
        self._float_bar_visible = True
        self._float_popup_open = False
        self._float_popup_widgets: set[QWidget] = set()

        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setFixedHeight(52)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._setup_ui()

        # Regenerate icons on theme change
        tm.theme_changed.connect(self._on_theme_changed_icons)

        # OSD overlay
        self._osd_widget = _OSDWidget(self)

    @property
    def _icons_dir(self) -> str:
        return str(Path(__file__).resolve().parent.parent.parent / "icons")

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
        self._play_btn = StyledButton(icon=f"{self._icons_dir}/play.svg", variant="ghost", size="default")
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

        # Volume
        self._vol_btn = StyledButton(icon=f"{self._icons_dir}/speaker.svg", variant="ghost", size="default")
        self._vol_btn.clicked.connect(self._on_volume_clicked)
        right_layout.addWidget(self._vol_btn)

        # Speed
        self._speed_btn = StyledButton(icon=f"{self._icons_dir}/speed.svg", variant="ghost", size="default")
        self._speed_btn.clicked.connect(self._on_speed_clicked)
        right_layout.addWidget(self._speed_btn)

        # Settings
        self._settings_btn = StyledButton(icon=f"{self._icons_dir}/more.svg", variant="ghost", size="default")
        self._settings_btn.clicked.connect(self._on_settings_clicked)
        right_layout.addWidget(self._settings_btn)

        # Fullscreen
        self._fs_btn = StyledButton(icon=f"{self._icons_dir}/maxsize.svg", variant="ghost", size="default")
        self._fs_btn.clicked.connect(self._on_fullscreen_clicked)
        right_layout.addWidget(self._fs_btn)

        layout.addWidget(right_group)

    # ── Event handlers ─────────────────────────────────────────

    def _on_play_clicked(self):
        self._playing = not self._playing
        self._play_btn.set_svg_icon(f"{self._icons_dir}/{'pause.svg' if self._playing else 'play.svg'}")
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

        # 打开弹窗时通知浮动模式（防止在浮动模式下控制栏被自动隐藏）
        self._float_popup_open = True
        if self._float_hide_timer:
            self._float_hide_timer.stop()
        self._float_popup_widgets.add(self._volume_popup)
        # 以音量按钮底边中点为锚点，使纵向弹窗居中显示
        anchor = QPoint(btn_global.x() + self._vol_btn.width() // 2, btn_global.y())
        self._volume_popup.show_animated(anchor, pw, ph)

    def _on_speed_clicked(self):
        self._close_other_popups("speed")
        if self._speed_popup and self._speed_popup.isVisible():
            self._speed_popup.close_animated()
            return

        self._speed_popup = _SpeedPopup(current_speed=self._current_speed)
        self._speed_popup.speed_selected.connect(self._on_speed_selected)

        btn_global = self._speed_btn.mapToGlobal(QPoint(0, 0))
        pw, ph = self._speed_popup.width(), self._speed_popup.height()

        self._float_popup_open = True
        if self._float_hide_timer:
            self._float_hide_timer.stop()
        self._float_popup_widgets.add(self._speed_popup)
        # 以倍速按钮底边中点为锚点，使弹窗居中显示
        anchor = QPoint(btn_global.x() + self._speed_btn.width() // 2, btn_global.y())
        self._speed_popup.show_animated(anchor, pw, ph)

    def _on_settings_clicked(self):
        self._close_other_popups("settings")
        if self._settings_popup and self._settings_popup.isVisible():
            self._settings_popup.close_animated()
            return

        self._settings_popup = _SettingsPopup()
        self._settings_popup.setting_changed.connect(self._on_popup_setting)
        self._settings_popup.add_subtitle_requested.connect(self.add_subtitle_requested.emit)
        # 用缓存数据填充新弹窗
        if self._last_audio_tracks:
            self._settings_popup.set_audio_tracks(self._last_audio_tracks)
        if self._last_subtitle_tracks:
            self._settings_popup.set_subtitle_tracks(self._last_subtitle_tracks)

        btn_global = self._settings_btn.mapToGlobal(QPoint(0, 0))
        pw = max(self._settings_popup.width(), 220)
        ph = self._settings_popup.height()

        self._float_popup_open = True
        if self._float_hide_timer:
            self._float_hide_timer.stop()
        self._float_popup_widgets.add(self._settings_popup)
        # 以设置按钮右下角为锚点，使弹窗右对齐显示
        anchor = QPoint(btn_global.x() + self._settings_btn.width(), btn_global.y())
        self._settings_popup.show_animated(anchor, pw, ph)

    def _on_fullscreen_clicked(self):
        self._fullscreen = not self._fullscreen
        self._fs_btn.set_svg_icon(f"{self._icons_dir}/{'minisize.svg' if self._fullscreen else 'maxsize.svg'}")
        self.fullscreen_toggled.emit(self._fullscreen)

    # ── Popup callbacks ────────────────────────────────────────

    def _on_volume_slider(self, value: float):
        self._volume = value
        self.volume_changed.emit(value)
        self._muted = (value < 0.01)
        self._vol_btn.set_svg_icon(f"{self._icons_dir}/{'speaker_slash.svg' if self._muted else 'speaker.svg'}")

    def _on_mute_toggle(self, muted: bool):
        self._muted = muted
        self._vol_btn.set_svg_icon(f"{self._icons_dir}/{'speaker_slash.svg' if muted else 'speaker.svg'}")
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
        """Theme changed → clear SVG caches and repaint all StyledButtons"""
        for btn in [self._play_btn, self._vol_btn, self._speed_btn, self._settings_btn, self._fs_btn]:
            btn._svg_content_cache.clear()
            btn.update()

    # ── Event overrides ───────────────────────────────────────

    def enterEvent(self, event):
        """鼠标进入控制栏 → 重置空闲定时器"""
        super().enterEvent(event)
        if self._float_container is not None:
            if not self._float_popup_open:
                if self._float_hide_timer:
                    self._float_hide_timer.start(6000)

    def leaveEvent(self, event):
        """鼠标离开控制栏 → 可能移到了弹窗上"""
        super().leaveEvent(event)
        if self._float_container is not None:
            if not self._is_float_cursor_in_bar_area() and not self._float_popup_open:
                if self._float_hide_timer and self._float_container.isVisible():
                    self._float_hide_timer.start(3000)

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
        self._vol_btn.set_svg_icon(f"{self._icons_dir}/{'speaker_slash.svg' if muted else 'speaker.svg'}")
        if self._volume_popup:
            self._volume_popup.set_muted(muted)

    def set_audio_tracks(self, tracks: list[dict]) -> None:
        """设置音轨列表并缓存（弹窗已打开时立即更新）"""
        self._last_audio_tracks = tracks
        if self._settings_popup and self._settings_popup.isVisible():
            self._settings_popup.set_audio_tracks(tracks)

    def set_subtitle_tracks(self, tracks: list[dict]) -> None:
        """设置字幕列表并缓存（弹窗已打开时立即更新）"""
        self._last_subtitle_tracks = tracks
        if self._settings_popup and self._settings_popup.isVisible():
            self._settings_popup.set_subtitle_tracks(tracks)

    def set_osd_target(self, target_widget: QWidget) -> None:
        """设置 OSD 定位目标控件

        Args:
            target_widget: OSD 相对于此控件顶部居中
        """
        if not hasattr(self, '_osd_widget'):
            return
        self._osd_widget.set_target_widget(target_widget)

    def show_osd(self, message: str, duration: int = 2000) -> None:
        """显示 OSD 文本消息

        Args:
            message: 文本消息，如"播放"、"暂停"、"1.0x"
            duration: 显示时间（毫秒）
        """
        if not hasattr(self, '_osd_widget'):
            return
        self._osd_widget.show_message(message, duration)

    def show_seek_osd(self, current_time: float, total_duration: float, direction: str, duration: int = 2000) -> None:
        """显示 OSD seek 进度

        Args:
            current_time: 当前播放位置（秒）
            total_duration: 总时长（秒）
            direction: "forward" 或 "backward"
            duration: 显示时间（毫秒）
        """
        if not hasattr(self, '_osd_widget'):
            return
        self._osd_widget.show_seek(current_time, total_duration, direction, duration)

    def set_speed(self, speed_str: str) -> None:
        """从外部同步播放速度显示

        Args:
            speed_str: 速度字符串，如 "1.0x", "1.5x", "2.0x"
        """
        self._current_speed = speed_str
        if hasattr(self, '_speed_popup') and self._speed_popup and self._speed_popup.isVisible():
            self._speed_popup._current_speed = speed_str
            self._speed_popup.update()

    def set_playing(self, playing: bool):
        self._playing = playing
        self._play_btn.set_svg_icon(f"{self._icons_dir}/{'pause.svg' if playing else 'play.svg'}")

    # ── 浮动模式（全屏自动隐藏控制栏） ──────────────────────────

    def enter_floating_mode(self, target_widget: QWidget, screen_geometry: QRect) -> None:
        """进入浮动模式（全屏时调用）

        Args:
            target_widget: 鼠标检测目标控件（全屏视频表面）
            screen_geometry: 屏幕几何尺寸（用于定位和底部区域检测）
        """
        if self._float_container is not None:
            return

        # 1. 记下当前父控件，用于退出时恢复
        self._float_parent = self.parentWidget()
        self._float_parent_layout = None
        parent = self._float_parent
        if parent and parent.layout():
            self._float_parent_layout = parent.layout()

        # 2. 从当前 layout 移除
        if self._float_parent_layout:
            self._float_parent_layout.removeWidget(self)

        # 3. 创建浮动容器
        self._float_container = _FloatContainer()
        self._float_container.set_content(self)

        # 4. 设置位置：底部居中，margin=30，底部留 20px 间距
        bar_height = self.height()
        margin = 30
        container_width = screen_geometry.width() - margin * 2
        container_x = screen_geometry.x() + margin
        container_y = screen_geometry.bottom() - bar_height - 20
        self._float_container.setGeometry(
            container_x, container_y, container_width, bar_height + 10
        )

        # 5. 设置目标区域（用于鼠标检测）
        self._float_target_widget = target_widget
        self._float_target_rect = screen_geometry

        # 6. 启动自动隐藏
        self._start_float_auto_hide()

        # 7. 淡入显示
        self._float_container.show_with_animation()

    def exit_floating_mode(self) -> None:
        """退出浮动模式，恢复正常布局"""
        if self._float_container is None:
            return

        # 1. 停止自动隐藏
        self._stop_float_auto_hide()

        # 2. 从容器中取出内容
        self._float_container.clear_content()

        # 3. 销毁容器
        self._float_container.hide()
        self._float_container.deleteLater()
        self._float_container = None

        # 4. 恢复到原父控件
        if self._float_parent_layout:
            self.setParent(self._float_parent)
            self._float_parent_layout.addWidget(self)
        elif self._float_parent:
            self.setParent(self._float_parent)

        self._float_parent = None
        self._float_parent_layout = None
        self._float_target_widget = None
        self.show()

    def _start_float_auto_hide(self) -> None:
        """启动自动隐藏：鼠标跟踪 + 空闲定时器"""
        # 空闲检测定时器（3秒无鼠标到底部则隐藏）
        self._float_hide_timer = QTimer(self)
        self._float_hide_timer.setSingleShot(True)
        self._float_hide_timer.setInterval(3000)
        self._float_hide_timer.timeout.connect(self._on_float_idle_timeout)

        # 显示状态（默认显示）
        self._float_bar_visible = True

        # 启动鼠标检测定时器（每 200ms 检测一次鼠标位置）
        self._float_mouse_timer = QTimer(self)
        self._float_mouse_timer.setInterval(200)
        self._float_mouse_timer.timeout.connect(self._check_float_mouse_position)
        self._float_mouse_timer.start()

        # 先显示控制栏，启动隐藏计时
        self._float_hide_timer.start()

        # 跟踪控制栏弹出菜单可见性（防止菜单打开时隐藏）
        self._float_popup_open = False

    def _stop_float_auto_hide(self) -> None:
        """停止自动隐藏"""
        if self._float_mouse_timer:
            self._float_mouse_timer.stop()
            self._float_mouse_timer.deleteLater()
            self._float_mouse_timer = None
        if self._float_hide_timer:
            self._float_hide_timer.stop()
            self._float_hide_timer.deleteLater()
            self._float_hide_timer = None
        self._float_bar_visible = True
        self._float_popup_open = False

    def _is_float_cursor_in_bar_area(self) -> bool:
        """检查光标是否在控制栏自身或已注册弹窗上"""
        if not self._float_container or not self._float_container.isVisible():
            return False
        cursor_pos = QCursor.pos()

        # 检查控制栏自身（通过 _FloatContainer 的全局几何）
        container_geo = self._float_container.frameGeometry()
        if container_geo.contains(cursor_pos):
            return True

        # 检查所有已注册弹窗
        for popup in list(self._float_popup_widgets):
            try:
                if popup and popup.isVisible():
                    if popup.frameGeometry().contains(cursor_pos):
                        return True
            except RuntimeError:
                self._float_popup_widgets.discard(popup)

        return False

    def _update_float_popup_state(self) -> bool:
        """轮询所有已注册弹窗的可见性，更新 _float_popup_open"""
        for popup in list(self._float_popup_widgets):
            try:
                if popup and popup.isVisible():
                    return True
            except RuntimeError:
                self._float_popup_widgets.discard(popup)
        return False

    def _check_float_mouse_position(self) -> None:
        """检查鼠标位置：控制栏区域或底部 100px → 显示/保持控制栏"""
        if not self._float_container or not self._float_target_widget:
            return

        cursor_pos = QCursor.pos()
        target_geo = self._float_target_rect
        if target_geo is None:
            return

        # 轮询弹窗可见性（替代不存在的 visibilityChanged 信号）
        popup_open = self._update_float_popup_state()
        if popup_open:
            self._float_popup_open = True
            # 弹窗打开时暂停隐藏
            if self._float_hide_timer:
                self._float_hide_timer.stop()
            return

        # 弹窗全部关闭后重置状态
        if self._float_popup_open:
            self._float_popup_open = False

        # 光标是否在控制栏自身或弹窗上
        is_in_bar = self._is_float_cursor_in_bar_area()

        # 底部检测区域：底部 100px（用于从外部唤醒控制栏）
        bottom_zone_bottom = target_geo.bottom()
        bottom_zone_top = bottom_zone_bottom - 100
        is_in_bottom_zone = (
            cursor_pos.x() >= target_geo.left()
            and cursor_pos.x() <= target_geo.right()
            and cursor_pos.y() >= bottom_zone_top
            and cursor_pos.y() <= bottom_zone_bottom
        )

        if is_in_bar or is_in_bottom_zone:
            # 显示控制栏（如果隐藏）
            if not self._float_bar_visible:
                self._float_bar_visible = True
                self._float_container.show_with_animation()
                self.floating_bar_shown.emit()

            # 根据位置决定超时策略
            if is_in_bar:
                self._float_hide_timer.start(6000)   # 光标在栏上 → 6s 后隐藏
            else:
                self._float_hide_timer.start(3000)   # 光标在底部区域但不在栏上 → 3s
        # 光标既不在栏也不在底部 → 让空闲定时器到期后隐藏

    def _on_float_idle_timeout(self) -> None:
        """空闲超时 → 隐藏控制栏"""
        if self._float_popup_open:
            # 有弹出菜单打开，延迟隐藏
            self._float_hide_timer.start(1000)
            return
        self._float_bar_visible = False
        self._float_container.hide_with_animation()
        self.floating_bar_hidden.emit()
