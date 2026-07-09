"""Standalone demo for the StyledPlayerBar component."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QPushButton,
)
from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QLinearGradient, QBrush, QPen, QPainterPath

from theme import tm

from components.styled_player_bar import StyledPlayerBar
from components.styled_slider import StyledSlider


def make_separator():
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet(f"QFrame {{ color: {tm.alpha_of(tm.mid, 40).name()}; }}")
    line.setFixedHeight(1)
    return line


def make_section_header(text):
    label = QLabel(text)
    label.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {tm.text.name()}; margin-top: 12px;")
    return label


def make_section_desc(text):
    label = QLabel(text)
    label.setStyleSheet(f"font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()}; margin-bottom: 8px;")
    return label


class SimulatedVideoArea(QWidget):
    """Simulated video area with gradient background."""

    def __init__(self, badge_text="LIVE · 示例视频", parent=None):
        super().__init__(parent)
        self._badge_text = badge_text
        self.setMinimumHeight(280)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Gradient background
        grad = QLinearGradient(0, 0, self.width(), self.height())
        grad.setColorAt(0, QColor("#0d0d0d"))
        grad.setColorAt(0.3, QColor("#1a1a2e"))
        grad.setColorAt(0.6, QColor("#16213e"))
        grad.setColorAt(1.0, QColor("#0f3460"))

        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(self.rect(), 8, 8)

        # Center play icon
        cx = self.width() / 2
        cy = self.height() / 2
        r = 32

        p.setBrush(QColor(7, 193, 96, 38))
        p.setPen(QPen(QColor(7, 193, 96, 77), 2))
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # Play triangle
        p.setPen(Qt.NoPen)
        p.setBrush(tm.accent)
        tri = [
            (cx - 8, cy - 12),
            (cx - 8, cy + 12),
            (cx + 14, cy),
        ]
        path = QPainterPath()
        path.moveTo(tri[0][0], tri[0][1])
        path.lineTo(tri[1][0], tri[1][1])
        path.lineTo(tri[2][0], tri[2][1])
        path.closeSubpath()
        p.drawPath(path)

        # Badge
        badge_x = 16
        badge_y = 16
        badge_w = 140
        badge_h = 28
        p.setBrush(QColor(0, 0, 0, 153))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(badge_x, badge_y, badge_w, badge_h), 4, 4)

        # Badge dot
        dot_r = 4
        p.setBrush(tm.accent)
        p.drawEllipse(QPointF(badge_x + 14, badge_y + badge_h / 2), dot_r, dot_r)

        # Badge text
        font = p.font()
        font.setPointSize(9)
        font.setFamily("Microsoft YaHei UI")
        p.setFont(font)
        p.setPen(tm.mid)
        p.drawText(QRectF(badge_x + 24, badge_y, badge_w - 28, badge_h), Qt.AlignVCenter, self._badge_text)

        p.end()


class StyledPlayerBarDemo(QWidget):
    """Main demo window for StyledPlayerBar."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledPlayerBar Demo")
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowTitleHint)
        self.resize(900, 680)

        self.setStyleSheet(
            f'QWidget {{ background-color: {tm.surface.name()}; color: {tm.text.name()}; font-family: "Microsoft YaHei", sans-serif; }}'
            f'QLabel {{ color: {tm.mid.name()}; font-size: 12px; }}'
        )

        self._setup_ui()
        self._setup_timer()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(6)
        main_layout.setContentsMargins(24, 24, 24, 24)

        # ── Header ──
        header = QLabel("StyledPlayerBar 播放控制栏")
        header.setStyleSheet(f"font-size: 22px; font-weight: 600; color: {tm.text.name()}; margin-bottom: 4px;")
        main_layout.addWidget(header)
        main_layout.addWidget(make_section_desc(
            "Video player control bar with play/pause, progress scrubbing, volume popup, speed popup, settings submenus, "
            "and fullscreen toggle."
        ))
        main_layout.addWidget(make_separator())

        # ── Main player with bar ──
        main_layout.addWidget(make_section_header("默认状态"))
        player_container = QWidget()
        player_container.setStyleSheet("background: transparent;")

        player_layout = QVBoxLayout(player_container)
        player_layout.setContentsMargins(0, 0, 0, 0)
        player_layout.setSpacing(0)

        # Video area
        self._video_area = SimulatedVideoArea()
        player_layout.addWidget(self._video_area)

        # Player bar
        self._player_bar = StyledPlayerBar(
            current_time="01:23",
            total_time="10:00",
            progress=0.35,
            volume=0.7,
            current_speed="1.0x",
        )
        self._player_bar.play_paused.connect(self._on_play_paused)
        self._player_bar.progress_changed.connect(self._on_progress)
        self._player_bar.volume_changed.connect(self._on_volume)
        self._player_bar.speed_changed.connect(self._on_speed)
        self._player_bar.fullscreen_toggled.connect(self._on_fullscreen)
        self._player_bar.setting_changed.connect(self._on_setting)
        player_layout.addWidget(self._player_bar)

        main_layout.addWidget(player_container)

        # ── Status panel ──
        main_layout.addWidget(make_section_header("状态面板"))
        main_layout.addWidget(make_section_desc("实时显示播放器状态"))

        status_card = QWidget()
        status_card.setStyleSheet(f"""
            background: {tm.surface.name()};
            border: 1px solid {tm.alpha_of(tm.mid, 30).name()};
            border-radius: 8px;
            padding: 8px;
        """)
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(16, 12, 16, 12)
        status_layout.setSpacing(8)

        self._status_labels = {}
        for key in ["播放状态", "进度", "音量", "倍速", "设置"]:
            row = QHBoxLayout()
            row.setSpacing(8)
            label = QLabel(key)
            label.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 60).name()}; font-size: 12px; min-width: 60px;")
            value = QLabel("—")
            value.setStyleSheet(f"color: {tm.mid.name()}; font-size: 12px;")
            value.setObjectName(f"status_{key}")
            row.addWidget(label)
            row.addWidget(value)
            row.addStretch()
            status_layout.addLayout(row)
            self._status_labels[key] = value

        main_layout.addWidget(status_card)

        # ── Scenario buttons ──
        main_layout.addWidget(make_section_header("场景切换"))
        main_layout.addWidget(make_section_desc("快速切换到不同的播放器状态"))

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        scenarios = [
            ("默认状态", self._scenario_default),
            ("静音状态", self._scenario_muted),
            ("设置弹窗", self._scenario_settings),
            ("倍速弹窗", self._scenario_speed),
        ]

        for label, callback in scenarios:
            btn = QPushButton(label)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {tm.surface.name()};
                    border: 1px solid {tm.alpha_of(tm.mid, 40).name()};
                    border-radius: 4px;
                    padding: 6px 16px;
                    color: {tm.mid.name()};
                    font-size: 12px;
                    font-family: 'Microsoft YaHei UI', sans-serif;
                }}
                QPushButton:hover {{
                    background: {tm.alpha_of(tm.mid, 40).name()};
                    color: {tm.text.name()};
                }}
                QPushButton:pressed {{
                    background: {tm.surface.name()};
                }}
            """)
            btn.clicked.connect(callback)
            btn_row.addWidget(btn)

        btn_row.addStretch()
        main_layout.addLayout(btn_row)

        main_layout.addStretch()

        # Apply initial status
        self._update_status()

    def _setup_timer(self):
        """Simulate a progress timer for demo."""
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick_progress)
        self._timer.start(3000)  # tick every 3 seconds

    def _tick_progress(self):
        """Increment progress a bit to demonstrate live feel."""
        if hasattr(self, '_player_bar') and self._player_bar._playing:
            new_prog = min(1.0, self._player_bar._progress + 0.02)
            self._player_bar.set_progress(new_prog)
            # Update displayed time roughly
            total_secs = 600  # 10:00
            current_secs = int(total_secs * new_prog)
            mins = current_secs // 60
            secs = current_secs % 60
            self._player_bar.set_current_time(f"{mins:02d}:{secs:02d}")
            self._update_status()

    # ── Signal handlers ──

    def _on_play_paused(self, playing: bool):
        self._update_status("播放状态", "▶ 播放中" if playing else "⏸ 已暂停")

    def _on_progress(self, value: float):
        self._update_status("进度", f"{int(value * 100)}%")

    def _on_volume(self, value: float):
        self._update_status("音量", f"{int(value * 100)}%")

    def _on_speed(self, speed: str):
        self._update_status("倍速", speed)

    def _on_fullscreen(self, fs: bool):
        print(f"{'进入' if fs else '退出'}全屏模式")

    def _on_setting(self, section: str, value: str):
        self._update_status("设置", f"{section}: {value}")

    def _update_status(self, key: str = None, value: str = None):
        """Update status display."""
        if key and value and key in self._status_labels:
            self._status_labels[key].setText(value)

        # Default values
        if hasattr(self, '_player_bar'):
            if "播放状态" in self._status_labels:
                state = "▶ 播放中" if self._player_bar._playing else "⏸ 已暂停"
                self._status_labels["播放状态"].setText(state)
            if "进度" in self._status_labels:
                self._status_labels["进度"].setText(f"{int(self._player_bar._progress * 100)}%")
            if "音量" in self._status_labels:
                self._status_labels["音量"].setText(f"{int(self._player_bar._volume * 100)}%")
            if "倍速" in self._status_labels:
                self._status_labels["倍速"].setText(self._player_bar._current_speed)

    # ── Scenario callbacks ──

    def _scenario_default(self):
        self._player_bar.set_progress(0.35)
        self._player_bar.set_current_time("01:23")
        self._player_bar.set_volume(0.7)
        self._player_bar.set_muted(False)
        self._player_bar.set_playing(False)
        self._update_status()

    def _scenario_muted(self):
        self._player_bar.set_progress(0.55)
        self._player_bar.set_current_time("03:45")
        self._player_bar.set_volume(0.0)
        self._player_bar.set_muted(True)
        self._player_bar.set_playing(True)
        self._update_status()

    def _scenario_settings(self):
        self._player_bar.set_progress(0.72)
        self._player_bar.set_current_time("05:12")
        self._player_bar.set_volume(0.5)
        self._player_bar.set_muted(False)
        self._player_bar.set_playing(True)
        self._player_bar._on_settings_clicked()
        self._update_status()

    def _scenario_speed(self):
        self._player_bar.set_progress(0.88)
        self._player_bar.set_current_time("07:30")
        self._player_bar.set_volume(0.7)
        self._player_bar.set_muted(False)
        self._player_bar.set_playing(True)
        self._player_bar._on_speed_clicked()
        self._update_status()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = StyledPlayerBarDemo()
    window.show()
    sys.exit(app.exec())
