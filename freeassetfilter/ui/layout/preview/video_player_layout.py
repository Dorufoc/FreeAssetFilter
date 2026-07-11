"""
视频播放器布局 — 嵌入 MPV + StyledPlayerBar 控制栏
"""

import os
import sys
from pathlib import Path
from typing import Any, Optional

# 独立运行时的 sys.path 引导（在模块级导入前执行）
_this_file = Path(__file__).resolve()
_ui_root = str(_this_file.parent.parent.parent)  # freeassetfilter/ui/
if _ui_root not in sys.path:
    sys.path.insert(0, _ui_root)
_project_root = str(_this_file.parent.parent.parent.parent.parent)  # 项目根
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QApplication,
    QStackedLayout, QPushButton,
)
from PySide6.QtCore import Qt, Signal, QTimer, QRect
from PySide6.QtGui import QFont

from theme import tm
from components.styled_player_bar import StyledPlayerBar
from freeassetfilter.core.managers.mpv_manager import MPVManager, MPVState
from freeassetfilter.core.managers.heartbeat_manager import HeartbeatManager
from freeassetfilter.utils.app_logger import info, debug, warning, error


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

        if not self._is_mpv_embedded:
            self._embed_mpv_window()

        if not self._mpv_manager:
            return False

        self._current_file = file_path
        result = self._mpv_manager.load_file(file_path, component_id=self._component_id)
        if result:
            self._stack.setCurrentIndex(0)  # Show video surface
            self._mpv_manager.play(component_id=self._component_id)
        else:
            self._placeholder.setText("无法加载文件")

        return result

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

        # Stacked layout: 0=video_surface, 1=overlay
        self._stack = QStackedLayout()

        # ── 视频渲染表面（index 0）──
        self._video_surface = QWidget()
        self._video_surface.setAttribute(Qt.WA_DontCreateNativeAncestors)
        self._video_surface.setAttribute(Qt.WA_NativeWindow)
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

        if not self._mpv_manager.initialize():
            error("无法初始化 MPV 播放器")
            return

        # Ensure video surface is current before embedding
        self._stack.setCurrentIndex(0)

        self._video_surface.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
        self._video_surface.setAttribute(Qt.WA_NativeWindow, True)
        if not self._video_surface.isVisible():
            self._video_surface.show()

        win_id = int(self._video_surface.winId())
        if self._mpv_manager.set_window_id(win_id, component_id=self._component_id):
            self._is_mpv_embedded = True
            # 应用初始音量/倍速
            self._mpv_manager.set_volume(70, component_id=self._component_id)
            self._mpv_manager.set_speed(self._current_speed, component_id=self._component_id)

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
                    target_widget=self._video_surface,
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
        """打开文件对话框选择视频文件（仅 standalone 模式）"""
        from PySide6.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择视频文件",
            "",
            "视频文件 (*.mp4 *.avi *.mkv *.mov *.wmv *.flv *.webm *.m4v *.mpg *.mpeg);;所有文件 (*.*)",
        )
        if file_path:
            self.set_file(file_path)

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
            print(f"[HB_SKIP] mpv_manager not initialized", flush=True)
            return
        if self._user_interacting:
            print(f"[HB_SKIP] user interacting", flush=True)
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
    # 配置 sys.path 使导入可工作
    _this_file = Path(__file__).resolve()
    _ui_root = str(_this_file.parent.parent.parent)  # freeassetfilter/ui/ (from preview/)
    if _ui_root not in sys.path:
        sys.path.insert(0, _ui_root)
    _project_root = str(_this_file.parent.parent.parent.parent.parent)  # 项目根
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)

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

    player = VideoPlayerLayout(standalone=True)
    layout = QVBoxLayout(window)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(player)

    if len(sys.argv) > 1:
        player.set_file(sys.argv[1])

    window.show()
    sys.exit(app.exec())
