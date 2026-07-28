"""Video player layout embedding MPV + StyledPlayerBar controls.

FreeAssetFilter - 多功能文件预览与管理工具
Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.
"""
# allow: SIZE_OK — single UI layout integrating MPV video embedding,
# audio-mode fluid background + music info panel, control-bar signal wiring
# and standalone demo entry as required by the music-previewer-layout plan.

import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

# 独立运行时的 sys.path 引导（在模块级导入前执行）。
# `python -m` 与测试运行器已保证项目根在 sys.path；直接执行时回退到 cwd。
try:
    from freeassetfilter.core._paths import core_dir
except ImportError:  # pragma: no cover
    _cwd = os.getcwd()
    if _cwd not in sys.path:
        sys.path.insert(0, _cwd)
    from freeassetfilter.core._paths import core_dir

_freeassetfilter_dir = core_dir().parent
_ui_root = str(_freeassetfilter_dir / "ui")
_project_root = str(_freeassetfilter_dir.parent)
for __entry in (_ui_root, _project_root):
    if __entry not in sys.path:
        sys.path.insert(0, __entry)

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QApplication,
    QStackedLayout, QPushButton, QGridLayout,
)
from PySide6.QtCore import Qt, Signal, QTimer, QRect, QEvent
from PySide6.QtGui import QFont, QImage, QPixmap, QColor

from theme import tm
from components.styled_player_bar import StyledPlayerBar
from components.styled_fluid_background import StyledFluidBackground
from components.styled_music_info_panel import StyledMusicInfoPanel
from freeassetfilter.core.managers.mpv_manager import MPVManager, MPVState
from freeassetfilter.core.managers.heartbeat_manager import HeartbeatManager
from freeassetfilter.services.media_metadata_service import MediaMetadataService
from freeassetfilter.utils.app_logger import info, debug, warning, error

# 独立入口与文件对话框使用的扩展名白名单。
# 列表保留友好的显示顺序；集合用于快速查找。
_AUDIO_FILTER_ORDER = [".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".opus", ".aiff"]
_VIDEO_FILTER_ORDER = [".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".mpg", ".mpeg"]

AUDIO_EXTENSIONS = set(_AUDIO_FILTER_ORDER)
VIDEO_EXTENSIONS = set(_VIDEO_FILTER_ORDER)
SUPPORTED_MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS

# ``_on_browse_file`` 的文件选择过滤器（音频 + 视频）
_PLAYABLE_SUFFIXES = " ".join(f"*{ext}" for ext in _AUDIO_FILTER_ORDER + _VIDEO_FILTER_ORDER)
PLAYABLE_FILE_FILTER = f"播放文件 ({_PLAYABLE_SUFFIXES});;所有文件 (*.*)"


def _is_audio_file(file_path: str) -> bool:
    """Infer audio mode from the file extension (case-insensitive).

    Args:
        file_path: Path to the candidate file.

    Returns:
        ``True`` when the suffix belongs to :data:`AUDIO_EXTENSIONS`.
    """
    return Path(file_path).suffix.lower() in AUDIO_EXTENSIONS


def _is_supported_media_file(file_path: str) -> bool:
    """Return ``True`` for any audio or video extension known to the layout.

    Args:
        file_path: Path to the candidate file.

    Returns:
        ``True`` when the suffix belongs to :data:`SUPPORTED_MEDIA_EXTENSIONS`.
    """
    return Path(file_path).suffix.lower() in SUPPORTED_MEDIA_EXTENSIONS


class VideoPlayerLayout(QWidget):
    """
    视频播放器布局

    嵌入 MPV 视频渲染窗口，使用 StyledPlayerBar 作为播放控制栏。
    通过 MPVManager 信号实现双向状态同步。

    Signals:
        close_requested: 关闭预览请求信号
    """

    close_requested = Signal()

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        dpi_scale: Optional[float] = None,
        global_font: Optional[QFont] = None,
        settings_manager: Optional[Any] = None,
        standalone: bool = False,
    ) -> None:
        super().__init__(parent)
        # 初始化 DPI/字体/设置管理器
        self._dpi_scale = dpi_scale or 1.0
        self._global_font = global_font or QFont("Segoe UI", 9)
        self._settings_manager = settings_manager
        self._standalone = standalone

        self._init_ui()
        self._init_mpv()
        self._connect_player_signals()
        self._connect_manager_signals()
        self._connect_theme()

        # 注册状态同步心跳回调（每 3 个 tick ~99ms，匹配旧的 100ms QTimer）
        # 用作 positionChanged 信号丢帧时的保底更新
        HeartbeatManager().register_tick_callback(
            f"video_player_layout_sync_{id(self)}",
            self._heartbeat_sync,
            every_n_ticks=3,
            owner=self,
            priority=1,
        )

        # 启动心跳管理器（主线程周期性调度）
        # 在主应用中由 main.py 负责启动，standalone 模式下需要显式启动
        HeartbeatManager().start()

    # ── 公共 API ──

    def set_file(self, file_path: str, is_audio: bool = False) -> bool:
        """加载并播放视频/音频文件

        Args:
            file_path: 文件路径
            is_audio: 是否为音频文件

        Returns:
            bool: 加载是否成功
        """
        if not os.path.exists(file_path):
            warning(f"文件不存在: {file_path}")
            return False

        if is_audio:
            return self._load_audio_file(file_path)

        return self._load_video_file(file_path)

    @property
    def is_audio_mode(self) -> bool:
        """当前是否处于音频预览模式"""
        return self._stack.currentIndex() == self._audio_surface_index

    def _current_preview_widget(self) -> QWidget:
        """返回当前可见的预览控件。

        音频模式下返回 ``_audio_surface``，视频模式下返回 ``_video_surface``，
        用作浮动控制栏的鼠标检测目标。
        """
        return self._audio_surface if self.is_audio_mode else self._video_surface

    def _load_video_file(self, file_path: str) -> bool:
        """加载视频文件并嵌入 MPV 窗口。"""
        if not self._is_mpv_embedded:
            self._embed_mpv_window()

        if not self._mpv_manager:
            return False

        self._current_file = file_path
        result = self._mpv_manager.load_file(file_path, is_audio=False, component_id=self._component_id)
        if result:
            self._stack.setCurrentIndex(0)  # Show video surface
            self._mpv_manager.play(component_id=self._component_id)
        else:
            self._placeholder.setText("无法加载文件")

        return result

    def _load_audio_file(self, file_path: str) -> bool:
        """加载音频文件并显示流体背景 + 音乐信息面板。

        不嵌入 MPV 视频窗口；MPV 只负责音频播放。

        Args:
            file_path: 现有音频文件路径。

        Returns:
            bool: 加载是否成功。
        """
        if not self._mpv_manager:
            return False

        if not self._mpv_manager.is_initialized():
            if not self._mpv_manager.initialize():
                error("无法初始化 MPV 播放器")
                return False

        result = self._mpv_manager.load_file(
            file_path, is_audio=True, component_id=self._component_id
        )
        if not result:
            self._placeholder.setText("无法加载文件")
            return False

        self._current_file = file_path
        self._update_audio_metadata(file_path)

        # 先切换到音频表面，让流体背景所在页面可见后再初始化渲染器，
        # 否则 QOpenGLWidget 无法创建有效的 OpenGL context。
        self._stack.setCurrentIndex(self._audio_surface_index)
        self._fluid_background.load()
        self._mpv_manager.play(component_id=self._component_id)

        return True

    def _update_audio_metadata(self, file_path: str) -> None:
        """读取音频标签并更新流体背景与音乐信息面板。

        Args:
            file_path: 音频文件路径。
        """
        metadata_service = MediaMetadataService()
        metadata_service.initialize()
        try:
            tags = metadata_service.extract_audio_tags(file_path)
            if tags is None:
                tags = {
                    "title": "",
                    "artist": "",
                    "album": "",
                    "cover_data": None,
                }
        finally:
            metadata_service.dispose()

        cover_data: Optional[bytes] = tags.get("cover_data")

        # 流体背景配色：有封面取封面主色，否则使用主题强调色
        if cover_data:
            colors = self._extract_palette_from_cover(cover_data)
            if len(colors) >= 2:
                self._fluid_background.set_custom_colors(colors)
            else:
                self._fluid_background.use_accent_theme()
        else:
            self._fluid_background.use_accent_theme()

        # 音乐信息面板
        self._music_info_panel.set_title(tags.get("title", ""))
        self._music_info_panel.set_artist(tags.get("artist", ""))

        pixmap = QPixmap()
        if cover_data and pixmap.loadFromData(cover_data):
            self._music_info_panel.set_cover_pixmap(pixmap)
        else:
            self._music_info_panel.set_placeholder()

    @staticmethod
    def _extract_palette_from_cover(cover_data: bytes) -> list[QColor]:
        """从封面图像数据中抽取 2-5 个主导色。

        实现为轻量级量化：缩放到 64x64 后按 32 步长对 RGB 分桶，
        返回出现频率最高的颜色。若可抽取颜色少于 2 个则返回空列表，
        让调用方回退到主题强调色。

        Args:
            cover_data: 封面图像二进制数据（JPEG/PNG）。

        Returns:
            2-5 个 QColor 组成的列表；失败时返回空列表。
        """
        image = QImage.fromData(cover_data)
        if image.isNull():
            return []

        image = image.scaled(
            64, 64, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
        )

        buckets: Counter = Counter()
        for y in range(image.height()):
            for x in range(image.width()):
                color = QColor(image.pixel(x, y))
                if color.alpha() <= 0:
                    continue
                key = (
                    (color.red() // 32) * 32,
                    (color.green() // 32) * 32,
                    (color.blue() // 32) * 32,
                )
                buckets[key] += 1

        if not buckets:
            return []

        top_colors = buckets.most_common(5)
        palette = [QColor(r, g, b) for (r, g, b), _ in top_colors]

        if len(palette) == 1:
            # 单主导色时扩展为类 Apple Music 风格的 5 色类比色板。
            palette = StyledFluidBackground._build_from_seed(palette[0])

        return palette if len(palette) >= 2 else []

    def set_section_styles(self, fill_color: str, border_color: str) -> None:
        """应用面板样式（主题切换时由 MainWindow 调用）"""
        self.setStyleSheet(f"""
            VideoPlayerLayout {{
                background-color: {fill_color};
                border: 1px solid {border_color};
                border-radius: 8px;
            }}
        """)

    def cleanup(self) -> None:
        """清理资源，断开所有信号"""
        if self._mpv_manager:
            self._mpv_manager.stop(component_id=self._component_id)
            self._mpv_manager.unregister_component(self._component_id)

        # 注销布局自身的心跳回调
        HeartbeatManager().unregister_tick_callback(
            f"video_player_layout_sync_{id(self)}"
        )

        # 停止流体背景动画并释放其资源
        if self._fluid_background is not None:
            try:
                self._fluid_background.unload()
            except RuntimeError:
                # 允许重复 cleanup 或已释放时忽略
                pass

        # 隐藏音乐信息面板，避免随上层 surface 一起被 dispose 时产生闪烁
        if self._music_info_panel is not None:
            self._music_info_panel.hide()

        if self._mpv_manager:
            # 断开 MPVManager 信号
            try:
                self._mpv_manager.positionChanged.disconnect(self._on_position_changed)
            except (RuntimeError, TypeError):
                pass
            try:
                self._mpv_manager.stateChanged.disconnect(self._on_state_changed)
            except (RuntimeError, TypeError):
                pass
            try:
                self._mpv_manager.volumeChanged.disconnect(self._on_volume_changed)
            except (RuntimeError, TypeError):
                pass
            try:
                self._mpv_manager.mutedChanged.disconnect(self._on_muted_changed)
            except (RuntimeError, TypeError):
                pass
            try:
                self._mpv_manager.speedChanged.disconnect(self._on_speed_changed_from_mpv)
            except (RuntimeError, TypeError):
                pass
            try:
                self._mpv_manager.fileLoaded.disconnect(self._on_file_loaded)
            except (RuntimeError, TypeError):
                pass
            try:
                self._mpv_manager.fileEnded.disconnect(self._on_file_ended)
            except (RuntimeError, TypeError):
                pass

        # 断开主题信号
        try:
            tm.theme_changed.disconnect(self._on_theme_changed)
        except (RuntimeError, TypeError):
            pass

        debug("VideoPlayerLayout cleanup 完成")

    def stop_playback(self) -> None:
        """停止播放"""
        if self._mpv_manager:
            self._mpv_manager.stop(component_id=self._component_id)
        self._player_bar.set_playing(False)
        self._placeholder.setText("拖放视频文件或选择文件以播放")
        self._stack.setCurrentIndex(1)  # Show overlay

    # ── 内部方法 ──

    def _init_ui(self) -> None:
        """构建 UI：视频表面 + 占位覆盖层 + StyledPlayerBar"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Stacked layout: 0=video_surface, 1=overlay, 2=audio_surface
        self._stack = QStackedLayout()

        # ── 视频渲染表面（index 0）──
        self._video_surface = QWidget(self)
        self._video_surface.setStyleSheet("background-color: #000;")
        self._video_surface.setFocusPolicy(Qt.NoFocus)
        self._stack.addWidget(self._video_surface)

        # ── 占位覆盖层（index 1，未播放时显示）──
        self._overlay = QWidget()
        self._overlay.setStyleSheet("background-color: #1a1a1a;")
        overlay_layout = QVBoxLayout(self._overlay)
        overlay_layout.setAlignment(Qt.AlignCenter)
        overlay_layout.setSpacing(16)

        # 提示文字
        self._placeholder = QLabel("拖放视频文件或选择文件以播放")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setStyleSheet(
            "color: #666; font-size: 14px; background: transparent;"
        )
        overlay_layout.addWidget(self._placeholder)

        # 选择文件按钮（仅 standalone 模式）
        self._browse_btn = None
        if self._standalone:
            self._browse_btn = QPushButton("选择文件")
            self._browse_btn.setFixedSize(140, 36)
            self._browse_btn.setCursor(Qt.PointingHandCursor)
            btn_text = tm.mid.name()
            btn_hover_text = tm.text.name()
            btn_bg = tm.fill.name()
            btn_border = tm.alpha_of(tm.mid, 30).name()
            self._browse_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: 1px solid {btn_border};
                    border-radius: 8px;
                    color: {btn_text};
                    font-size: 13px;
                    font-family: 'Microsoft YaHei UI', 'Segoe UI', sans-serif;
                    padding: 0 16px;
                }}
                QPushButton:hover {{
                    background: {btn_bg};
                    color: {btn_hover_text};
                    border: 1px solid {tm.mid.name()};
                }}
                QPushButton:pressed {{
                    background: {btn_bg};
                }}
            """)
            self._browse_btn.clicked.connect(self._on_browse_file)
            overlay_layout.addWidget(self._browse_btn, alignment=Qt.AlignCenter)

        self._stack.addWidget(self._overlay)

        # ── 音频渲染表面（index 2，音频模式时代替视频窗口）──
        self._audio_surface = QWidget()
        self._audio_surface.setStyleSheet("background-color: #000;")
        audio_layout = QGridLayout(self._audio_surface)
        audio_layout.setContentsMargins(0, 0, 0, 0)
        audio_layout.setSpacing(0)

        self._fluid_background = StyledFluidBackground(self._audio_surface)
        self._music_info_panel = StyledMusicInfoPanel(self._audio_surface)

        # 背景与信息面板共享同一单元格，信息面板居中浮于背景之上
        audio_layout.addWidget(self._fluid_background, 0, 0)
        audio_layout.addWidget(self._music_info_panel, 0, 0, alignment=Qt.AlignCenter)

        self._audio_surface_index = self._stack.addWidget(self._audio_surface)

        main_layout.addLayout(self._stack, stretch=1)

        # 初始显示 overlay
        self._stack.setCurrentIndex(1)

        # 播放控制栏（固定 52px 高度）
        self._player_bar = StyledPlayerBar(
            current_time="00:00",
            total_time="00:00",
            progress=0.0,
            volume=0.7,
            current_speed="1.0x",
        )
        main_layout.addWidget(self._player_bar)

    def _init_mpv(self) -> None:
        """初始化 MPV 管理器"""
        self._mpv_manager = MPVManager()
        self._component_id = f"video_player_layout_{id(self)}"
        self._mpv_manager.register_component(self._component_id, "VideoPlayerLayout")
        # MPV 管理器在首次加载文件时惰性初始化
        self._is_mpv_embedded = False
        self._current_file = ""
        self._duration = 0.0
        self._current_position = 0.0
        self._current_speed = 1.0

        # 进度条交互防抖动控制（参考旧 PlayerControlBar 模式）
        self._user_interacting = False
        self._pending_seek_value: Optional[float] = None
        self._seek_debounce_timer = QTimer(self)
        self._seek_debounce_timer.setSingleShot(True)
        self._seek_debounce_timer.setInterval(250)
        self._seek_debounce_timer.timeout.connect(self._flush_pending_seek)

    def _embed_mpv_window(self) -> None:
        """将 MPV 窗口嵌入到 _video_surface"""
        if self._is_mpv_embedded or not self._mpv_manager:
            return

        # Ensure video surface is current before embedding
        self._stack.setCurrentIndex(0)

        self._video_surface.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
        self._video_surface.setAttribute(Qt.WA_NativeWindow, True)

        win_id = int(self._video_surface.winId())
        # 监听自身 WinIdChange：顶层窗口重建（如切换背景效果）会销毁重建
        # 本原生子窗，旧 wid 失效，需标记下次加载时重新嵌入
        self._embedded_win_id = win_id
        self._video_surface.installEventFilter(self)
        if self._mpv_manager.is_initialized():
            embedded = self._mpv_manager.set_window_id(
                win_id, component_id=self._component_id
            )
        else:
            embedded = self._mpv_manager.initialize(initial_window_id=win_id)

        if embedded:
            self._is_mpv_embedded = True
            # 应用初始音量/倍速
            self._mpv_manager.set_volume(70, component_id=self._component_id)
            self._mpv_manager.set_speed(self._current_speed, component_id=self._component_id)

    def eventFilter(self, watched, event) -> bool:
        """检测视频面原生句柄变化（顶层重建导致），失效时重新嵌入 MPV。"""
        if watched is getattr(self, "_video_surface", None) and event.type() == QEvent.Type.WinIdChange:
            new_id = int(self._video_surface.winId()) if self._video_surface.internalWinId() else 0
            if self._is_mpv_embedded and new_id and new_id != getattr(self, "_embedded_win_id", 0):
                self._embedded_win_id = new_id
                if self._mpv_manager and self._mpv_manager.is_initialized():
                    self._mpv_manager.set_window_id(new_id, component_id=self._component_id)
        return super().eventFilter(watched, event)

    def _connect_player_signals(self) -> None:
        """StyledPlayerBar → VideoPlayerLayout → MPVManager"""
        self._player_bar.play_paused.connect(self._on_play_pause)
        self._player_bar.progress_changed.connect(self._on_progress_seek)
        self._player_bar.progress_pressed.connect(self._on_progress_pressed)
        self._player_bar.progress_released.connect(self._on_progress_released)
        self._player_bar.volume_changed.connect(self._on_volume_change)
        self._player_bar.mute_changed.connect(self._on_mute_change)
        self._player_bar.speed_changed.connect(self._on_speed_change)
        self._player_bar.fullscreen_toggled.connect(self._on_fullscreen_toggled)

    def _connect_manager_signals(self) -> None:
        """MPVManager → StyledPlayerBar 状态同步"""
        if not self._mpv_manager:
            return
        self._mpv_manager.positionChanged.connect(self._on_position_changed)
        self._mpv_manager.stateChanged.connect(self._on_state_changed)
        self._mpv_manager.volumeChanged.connect(self._on_volume_changed)
        self._mpv_manager.mutedChanged.connect(self._on_muted_changed)
        self._mpv_manager.speedChanged.connect(self._on_speed_changed_from_mpv)
        self._mpv_manager.fileLoaded.connect(self._on_file_loaded)
        self._mpv_manager.fileEnded.connect(self._on_file_ended)

    def _connect_theme(self) -> None:
        """连接主题切换信号"""
        tm.theme_changed.connect(self._on_theme_changed)

    # ── Signal Handlers ──

    def _on_position_changed(self, position: float, duration: float) -> None:
        """MPV 位置变化 → 更新进度条和时间显示

        参考旧 PlayerControlBar 的模式：用户拖动进度条时不更新进度显示，
        避免 MPV 信号与用户拖动手感冲突。
        """
        self._current_position = position
        self._duration = duration
        if not self._user_interacting:
            self._player_bar.set_current_time(self._format_time(position))
            self._player_bar.set_total_time(self._format_time(duration))
            if duration > 0:
                self._player_bar.set_progress(position / duration)

    def _on_state_changed(self, state: MPVState) -> None:
        """MPV 状态变化 → 更新暂停/播放按钮"""
        is_playing = state.is_playing and not state.is_paused
        self._player_bar.set_playing(is_playing)

    def _on_volume_changed(self, volume: int) -> None:
        """MPV 音量变化 → 更新音量显示"""
        self._player_bar.set_volume(volume / 100.0)

    def _on_muted_changed(self, muted: bool) -> None:
        """MPV 静音变化 → 更新静音显示"""
        self._player_bar.set_muted(muted)

    def _on_speed_changed_from_mpv(self, speed: float) -> None:
        """MPV 倍速变化 → 更新倍速显示"""
        self._current_speed = speed
        speed_str = f"{speed:.1f}x"
        self._player_bar.set_speed(speed_str)

    def _on_play_pause(self, playing: bool) -> None:
        """播放/暂停按钮点击"""
        if playing:
            self._mpv_manager.play(component_id=self._component_id)
        else:
            self._mpv_manager.pause(component_id=self._component_id)

    def _on_progress_seek(self, value: float) -> None:
        """进度条拖动 — 存储值并启动防抖

        参考旧 PlayerControlBar 的 debounce 模式：
        - 拖动期间暂停最后的 seek（防抖 250ms）
        - 释放时立即提交最终的 seek
        """
        self._pending_seek_value = value
        if self._user_interacting and self._duration > 0:
            # 拖动时更新时间显示（进度条位置由 slider 本身控制，无需重复设置）
            position = value * self._duration
            self._player_bar.set_current_time(self._format_time(position))
            if not self._seek_debounce_timer.isActive():
                self._seek_debounce_timer.start()

    def _on_progress_pressed(self) -> None:
        """用户开始拖动进度条"""
        self._user_interacting = True

    def _on_progress_released(self) -> None:
        """用户结束拖动进度条 → 立即提交最终的 seek"""
        self._user_interacting = False
        self._flush_pending_seek()

    def _flush_pending_seek(self) -> None:
        """提交最后一次待处理的 seek"""
        if (
            self._pending_seek_value is None
            or not self._mpv_manager
            or not self._mpv_manager.is_initialized()
        ):
            return
        if self._duration <= 0:
            return

        seek_pos = self._pending_seek_value * self._duration
        self._mpv_manager.seek(seek_pos, component_id=self._component_id)
        self._pending_seek_value = None

    def _on_volume_change(self, value: float) -> None:
        """音量调节"""
        self._mpv_manager.set_volume(int(value * 100), component_id=self._component_id)

    def _on_mute_change(self, muted: bool) -> None:
        """静音切换"""
        self._mpv_manager.set_muted(muted, component_id=self._component_id)

    def _on_speed_change(self, speed_str: str) -> None:
        """倍速切换"""
        speed = float(speed_str.rstrip("x"))
        self._current_speed = speed
        self._mpv_manager.set_speed(speed, component_id=self._component_id)

    def _on_fullscreen_toggled(self, fullscreen: bool) -> None:
        """全屏按钮点击 → 切换父窗口全屏 + 浮动控制栏模式

        Args:
            fullscreen: True=进入全屏, False=退出全屏
        """
        if fullscreen:
            self.window().showFullScreen()
            # 进入全屏后启用浮动控制栏（自动隐藏 + 动画）
            screen = QApplication.primaryScreen()
            if screen:
                self._player_bar.enter_floating_mode(
                    target_widget=self._current_preview_widget(),
                    screen_geometry=screen.geometry(),
                )
        else:
            self._player_bar.exit_floating_mode()
            self.window().showNormal()

    def _on_file_loaded(self, file_path: str) -> None:
        """文件加载完成"""
        info(f"文件加载完成: {file_path}")
        # 参考旧 VideoPlayer._initialize_progress_display，延迟初始化进度显示
        QTimer.singleShot(200, self._initialize_progress_display)
        # 文件加载完成后再设置循环模式（避免与 loadfile 命令竞争）
        if self._mpv_manager:
            self._mpv_manager.set_loop("yes", component_id=self._component_id)

    def _on_file_ended(self, reason: int) -> None:
        """播放结束"""
        self._player_bar.set_playing(False)
        self._placeholder.setText("拖放视频文件或选择文件以播放")
        self._stack.setCurrentIndex(1)  # Show overlay
        debug(f"播放结束, 原因码: {reason}")

    def _on_browse_file(self) -> None:
        """打开文件对话框选择播放文件（仅 standalone 模式）"""
        from PySide6.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择播放文件",
            "",
            PLAYABLE_FILE_FILTER,
        )
        if file_path:
            self.set_file(file_path, is_audio=_is_audio_file(file_path))

    def _on_theme_changed(self, theme_name: str) -> None:
        """主题变更时刷新样式"""
        self._player_bar.update()

    # ── 心跳轮询 ──

    def _heartbeat_sync(self) -> None:
        """心跳轮询：MPV positionChanged 信号丢帧时的保底更新

        每 ~99ms 由 HeartbeatManager 调用，读取 MPV 缓存的位置/时长，
        确保进度条始终平滑更新（参考旧的 VideoPlayer._heartbeat_sync）。
        """
        if not self._mpv_manager or not self._mpv_manager.is_initialized():
            return
        if self._user_interacting:
            return
        duration = self._mpv_manager.get_duration()
        position = self._mpv_manager.get_position()
        if duration is not None and duration > 0:
            self._duration = duration
            self._current_position = position or 0.0
            self._player_bar.set_current_time(self._format_time(position or 0.0))
            self._player_bar.set_total_time(self._format_time(duration))
            self._player_bar.set_progress((position or 0.0) / duration)

    # ── 工具方法 ──

    def _initialize_progress_display(self) -> None:
        """初始化进度显示（参考旧 VideoPlayer._initialize_progress_display）

        文件加载后延迟调用，确保 MPV 已准备好时长信息。
        如果时长尚未就绪，每 200ms 重试直至成功。
        """
        if not self._mpv_manager:
            return

        from shiboken6 import isValid as _isValid
        if not _isValid(self):
            return

        try:
            duration = self._mpv_manager.get_duration()
            position = self._mpv_manager.get_position()
            if duration is not None and duration > 0:
                self._duration = duration
                self._current_position = position or 0
                self._player_bar.set_current_time(self._format_time(position or 0))
                self._player_bar.set_total_time(self._format_time(duration))
                self._player_bar.set_progress((position or 0) / duration)
                debug(f"进度显示已初始化: position={position}, duration={duration}")
            else:
                QTimer.singleShot(200, self._initialize_progress_display)
        except Exception as e:
            warning(f"初始化进度显示失败: {e}")
            QTimer.singleShot(200, self._initialize_progress_display)

    @staticmethod
    def _format_time(seconds: float) -> str:
        """格式化时间显示（秒 → MM:SS）"""
        if seconds < 0:
            seconds = 0
        total_secs = int(seconds)
        mins = total_secs // 60
        secs = total_secs % 60
        return f"{mins:02d}:{secs:02d}"


if __name__ == "__main__":
    # 配置 sys.path 使导入可工作；直接运行时回退到 cwd。
    try:
        from freeassetfilter.core._paths import core_dir
    except ImportError:  # pragma: no cover
        _cwd = os.getcwd()
        if _cwd not in sys.path:
            sys.path.insert(0, _cwd)
        from freeassetfilter.core._paths import core_dir

    _freeassetfilter_dir = core_dir().parent
    _ui_root = str(_freeassetfilter_dir / "ui")
    _project_root = str(_freeassetfilter_dir.parent)
    for __entry in (_ui_root, _project_root):
        if __entry not in sys.path:
            sys.path.insert(0, __entry)

    from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout

    app = QApplication(sys.argv)

    # 原生窗口（无 FramelessWindowHint，无 Mica）
    window = QWidget()
    window.setWindowTitle("视频播放器 (独立测试)")
    window.resize(960, 600)

    # 居中显示
    screen = app.primaryScreen().geometry()
    x = (screen.width() - 960) // 2 + screen.x()
    y = (screen.height() - 600) // 2 + screen.y()
    window.move(x, y)

    player = VideoPlayerLayout(window, standalone=True)
    layout = QVBoxLayout(window)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(player)

    # 先显示宿主窗口，再创建/绑定 native 视频表面，避免隐藏宿主下的
    # WA_NativeWindow 子控件在 Windows 上短暂成为独立顶层窗口。
    window.show()

    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        if not _is_supported_media_file(file_path):
            player._placeholder.setText("不支持的文件格式，请选择音频或视频文件")
            player._stack.setCurrentIndex(1)
        else:
            loaded = player.set_file(file_path, is_audio=_is_audio_file(file_path))
            if not loaded:
                player._placeholder.setText("无法加载文件，请检查路径或格式")
                player._stack.setCurrentIndex(1)
    else:
        player._placeholder.setText("拖放播放文件或选择文件以播放")
        player._stack.setCurrentIndex(1)

    sys.exit(app.exec())
