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
import threading
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    QWidget, QVBoxLayout, QLabel, QApplication,
    QStackedLayout, QPushButton, QGridLayout,
)
from PySide6.QtCore import QEvent, QObject, QRunnable, QThreadPool, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QImage, QPixmap, QColor

from theme import tm
from components.styled_player_bar import StyledPlayerBar
from components.styled_fluid_background import StyledFluidBackground
from components.styled_loading import StyledLoading
from components.styled_music_info_panel import StyledMusicInfoPanel
from layout.preview.fullscreen_host import PreviewFullscreenHost
from freeassetfilter.core.managers.mpv_manager import MPVManager, MPVState
from freeassetfilter.core.native.bridges.mpv_player_core import MpvEndFileReason
from freeassetfilter.core.managers.heartbeat_manager import HeartbeatManager
from freeassetfilter.services.media_metadata_service import MediaMetadataService
from freeassetfilter.utils.app_logger import info, debug, warning, error
from freeassetfilter.ui.theme.app_stylesheet import register_widget_qss

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


class _AudioMetadataSignals(QObject):
    """音频元数据采集完成信号中转（task 持有，跨线程队列投递到 UI 线程）。"""

    done = Signal(int, object)  # (token, result)


class _AudioMetadataTask(QRunnable):
    """音频元数据 + 封面调色板后台池任务（todo-30，沿 file_info_panel worker 模式）。

    ``run()`` 在 ``QThreadPool.globalInstance()`` 的池线程执行：单次
    ``MediaMetadataService.extract_audio_metadata`` 读取标签/封面/编码参数，
    并在 worker 内完成封面 64x64 Counter 调色板提取（算法与布局的
    ``_extract_palette_from_cover`` 逐字一致，仅移线程）。结果经 ``done``
    信号回主线程，由布局令牌守卫决定是否采纳——快速切换音频时陈旧结果
    直接丢弃，UI 线程绝不执行 mutagen 解析 / 调色板循环。
    """

    def __init__(self, file_path: str, token: int) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._file_path = file_path
        self._token = token
        self._signals = _AudioMetadataSignals()

    @property
    def done(self):
        """采集完成信号 ``(token, result)``（经中转对象）。"""
        return self._signals.done

    def start(self) -> None:
        """投递到全局线程池执行（替代旧 QThread.start()）。"""
        QThreadPool.globalInstance().start(self)

    def run(self) -> None:
        metadata_service = MediaMetadataService()
        metadata_service.initialize()
        try:
            meta: Optional[Dict[str, Any]] = metadata_service.extract_audio_metadata(
                self._file_path
            )
        except Exception:  # noqa: BLE001 — 外部库/损坏文件任意异常，回退空 schema
            meta = None
        finally:
            try:
                metadata_service.dispose()
            except Exception:  # noqa: BLE001
                pass

        if meta is None:
            meta = {}

        cover_data: Optional[bytes] = meta.get("cover_data")
        palette: list = []
        if cover_data:
            # 调色板算法逐字保留，仅移 worker 线程执行（结果经 Signal(object)
            # 跨线程回传，QPixmap 构造仍留主线程）。
            palette = VideoPlayerLayout._extract_palette_from_cover(cover_data)

        result: Dict[str, Any] = {
            "title": meta.get("title", ""),
            "artist": meta.get("artist", ""),
            "album": meta.get("album", ""),
            "cover_data": cover_data,
            "palette": palette,
        }
        self._signals.done.emit(self._token, result)


class _MediaLoadSignals(QObject):
    """媒体加载完成信号中转（任务持有，跨线程队列投递到 UI 线程）。"""

    done = Signal(int, bool, str)  # (token, ok, error_message)


class _MediaLoadTask(QRunnable):
    """后台加载并起播媒体文件（阻塞的 MPVManager 调用移出 UI 线程）。

    ``MPVManager.load_file`` / ``play`` 内部等待操作队列 future（最长
    30s/5s）；在 UI 线程调用会在慢盘/队列繁忙时冻结界面。本任务在池线程
    执行这两个调用，结果经 ``done`` 信号回主线程。``cancel_event`` 用于
    快速切换文件时阻止尚未执行的 load/play。
    """

    def __init__(
        self,
        mpv_manager: Any,
        file_path: str,
        is_audio: bool,
        component_id: str,
        token: int,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._mpv_manager = mpv_manager
        self._file_path = file_path
        self._is_audio = is_audio
        self._component_id = component_id
        self._token = token
        self._cancel_event = threading.Event()
        self._signals = _MediaLoadSignals()

    @property
    def done(self):
        """加载完成信号 ``(token, ok, error)``。"""
        return self._signals.done

    def request_cancel(self) -> None:
        """请求取消：阻止尚未执行的 load/play。"""
        self._cancel_event.set()

    def start(self) -> None:
        """投递到全局线程池执行。"""
        QThreadPool.globalInstance().start(self)

    def run(self) -> None:
        """加载并起播；异常统一转成 ``done(False, error)``。"""
        if self._cancel_event.is_set():
            return
        ok = False
        message = ""
        try:
            ok = bool(
                self._mpv_manager.load_file(
                    self._file_path,
                    is_audio=self._is_audio,
                    component_id=self._component_id,
                )
            )
            if ok and not self._cancel_event.is_set():
                self._mpv_manager.play(component_id=self._component_id)
        except Exception as exc:  # noqa: BLE001 — mpv/驱动任意异常不崩溃
            ok = False
            message = str(exc)
        if not self._cancel_event.is_set():
            self._signals.done.emit(self._token, ok, message)


class _ManagerStopTask(QRunnable):
    """后台停止播放并注销组件（避免 UI 线程等待 MPV 操作 future）。"""

    def __init__(
        self,
        mpv_manager: Any,
        component_id: str,
        unregister: bool = False,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._mpv_manager = mpv_manager
        self._component_id = component_id
        self._unregister = unregister

    def run(self) -> None:
        """停止播放；``unregister`` 为真时随后注销组件。"""
        try:
            self._mpv_manager.stop(component_id=self._component_id)
        except Exception:  # noqa: BLE001 — 关闭路径尽力而为
            pass
        if self._unregister:
            try:
                self._mpv_manager.unregister_component(self._component_id)
            except Exception:  # noqa: BLE001
                pass


class _MediaTracksSignals(QObject):
    """音轨/字幕轨采集完成信号中转（任务持有，跨线程队列投递到 UI 线程）。"""

    done = Signal(int, object, object)  # (token, audio_tracks, subtitle_tracks)


class _MediaTracksTask(QRunnable):
    """音轨/字幕轨后台采集任务（阻塞式 mpv 查询移出 UI 线程）。

    ``get_audio_tracks`` / ``get_subtitle_tracks`` 为阻塞式调用（各最长
    ``timeout`` 秒），在 UI 线程执行会卡顿。任务在
    ``QThreadPool.globalInstance()`` 的池线程顺序查询后经
    ``done(token, audio, subtitle)`` 信号回主线程，由布局令牌守卫决定是否
    采纳——快速切换文件时陈旧结果直接丢弃。
    """

    def __init__(self, mpv_manager: Any, token: int) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._mpv_manager = mpv_manager
        self._token = token
        self._signals = _MediaTracksSignals()

    @property
    def done(self):
        """采集完成信号 ``(token, audio, subtitle)``（经中转对象）。"""
        return self._signals.done

    def start(self) -> None:
        """投递到全局线程池执行。"""
        QThreadPool.globalInstance().start(self)

    def run(self) -> None:
        audio_tracks: List[Dict[str, Any]] = []
        subtitle_tracks: List[Dict[str, Any]] = []
        try:
            audio_tracks = self._mpv_manager.get_audio_tracks()
        except Exception as exc:  # noqa: BLE001 — mpv 查询任意异常不崩溃
            warning(f"获取音轨列表失败: {exc}")
        try:
            subtitle_tracks = self._mpv_manager.get_subtitle_tracks()
        except Exception as exc:  # noqa: BLE001
            warning(f"获取字幕列表失败: {exc}")
        self._signals.done.emit(self._token, audio_tracks, subtitle_tracks)


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

        self._fullscreen: bool = False
        self._fullscreen_host: Optional[PreviewFullscreenHost] = None

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

    def _show_loading(self, text: str) -> None:
        """显示加载覆盖页（圆环 + 状态文本）。"""
        self._placeholder.setText(text)
        self._loading_spinner.setVisible(True)
        self._stack.setCurrentIndex(1)

    def _show_error(self, text: str) -> None:
        """显示错误提示（隐藏圆环）。"""
        self._loading_spinner.setVisible(False)
        self._placeholder.setText(text)
        self._stack.setCurrentIndex(1)

    def _restore_media_surface(self) -> None:
        """根据当前媒体模式恢复视频/音频渲染页（媒体未就绪时保持覆盖页）。"""
        if not self._media_ready:
            self._stack.setCurrentIndex(1)
            return
        if self._current_media_is_audio:
            self._stack.setCurrentIndex(self._audio_surface_index)
        else:
            self._stack.setCurrentIndex(0)

    def _hide_loading(self, restore: bool = True) -> None:
        """隐藏圆环；``restore`` 为真时恢复正确渲染页。"""
        self._loading_spinner.setVisible(False)
        if restore:
            self._restore_media_surface()

    def set_file(self, file_path: str, is_audio: bool = False) -> bool:
        """异步加载并播放视频/音频文件。

        文件加载/起播的阻塞 MPVManager 调用在后台池任务执行；本方法立即返回
        ``True``（请求已受理）。加载失败经覆盖页错误文本异步呈现。

        Args:
            file_path: 文件路径
            is_audio: 是否为音频文件

        Returns:
            bool: 是否受理加载请求（文件缺失/核心不可用返回 False）
        """
        if not file_path or not os.path.exists(file_path):
            warning(f"文件不存在: {file_path}")
            return False

        # 切换文件：令牌递增使在途轨道/加载结果失效
        self._tracks_token += 1
        self._media_load_token += 1
        token = self._media_load_token
        if self._media_load_task is not None:
            self._media_load_task.request_cancel()
            self._media_load_task = None
        self._media_ready = False
        self._current_file = file_path
        self._current_media_is_audio = bool(is_audio)

        # 切换文件时使仍在途的音频元数据任务失效
        self._audio_meta_token += 1

        if self._mpv_manager is None:
            self._show_error("无法初始化播放器")
            return False

        if not self._ensure_core_ready():
            self._show_error("无法初始化播放器")
            return False

        if is_audio:
            self._show_loading("正在加载音频…")
            # 音频元数据/封面异步采集与媒体加载并行，UI 立即返回
            self._update_audio_metadata(file_path)
        else:
            self._show_loading("正在加载视频…")
            if not self._is_mpv_embedded:
                self._embed_mpv_window()
                if not self._is_mpv_embedded:
                    self._show_error("无法初始化播放器")
                    return False
                # 嵌入过程会切到视频表面，重新把加载遮罩置顶
                self._show_loading("正在加载视频…")

        task = _MediaLoadTask(
            self._mpv_manager,
            file_path,
            bool(is_audio),
            self._component_id,
            token,
        )
        task.done.connect(self._on_media_load_done)
        self._media_load_task = task
        task.start()
        return True

    def _on_media_load_done(self, token: int, ok: bool, message: str) -> None:
        """后台加载/起播结果回调（令牌守卫）。

        Args:
            token: 投递时的加载令牌。
            ok: ``load_file`` 是否成功。
            message: 异常消息（成功为空）。
        """
        if token != self._media_load_token:
            return
        self._media_load_task = None
        if not ok:
            self._media_ready = False
            self._show_error(message or "无法加载文件")

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

    def _ensure_core_ready(self) -> bool:
        """确保 MPV 核心可用，死亡时自动重建。

        mpv 核心可能因 stop 命令触发 SHUTDOWN、GPU 驱动崩溃等原因死亡，
        此时 MPVManager 单例中的核心对象虽在但所有命令都会失败。
        检测到不可操作时调用 initialize() 重建 worker，并重置嵌入标记
        （新 mpv 句柄的 wid 必须重新绑定）。

        Returns:
            bool: 核心当前可用（或已成功重建）
        """
        if self._mpv_manager is None:
            return False
        if self._mpv_manager.is_core_operational():
            return True
        warning("MPV 核心不可用，尝试重新初始化...")
        # 核心重建后旧 wid 失效，标记需要重新嵌入
        self._is_mpv_embedded = False
        if not self._mpv_manager.initialize():
            error("MPV 核心重新初始化失败")
            return False
        info("MPV 核心重新初始化成功")
        return True

    def _update_audio_metadata(self, file_path: str) -> None:
        """异步读取音频标签/封面并刷新流体背景与音乐信息面板。

        元数据解析（单次 mutagen 打开）与封面调色板提取移至 QRunnable
        后台任务，携带自增 token 防止快速切换音频时陈旧结果回写覆盖新文件。
        调用立即返回，不阻塞 UI 线程（todo-30）。

        Args:
            file_path: 音频文件路径。
        """
        self._audio_meta_token += 1
        token = self._audio_meta_token
        task = _AudioMetadataTask(file_path, token)
        task.done.connect(lambda t, result: self._on_audio_metadata_done(t, result))
        # 完成后从在途列表移除（信号参数按 signal 签名 (int, object)）
        task.done.connect(lambda _t, _r, tk=task: self._untrack_audio_meta_task(tk))
        self._audio_meta_tasks.append(task)
        task.start()

    def _untrack_audio_meta_task(self, task: "_AudioMetadataTask") -> None:
        """结果回传后从在途任务列表移除（释放引用，允许包装器回收）。"""
        try:
            if task in self._audio_meta_tasks:
                self._audio_meta_tasks.remove(task)
        except RuntimeError:
            pass

    def _on_audio_metadata_done(self, token: int, result: Dict[str, Any]) -> None:
        """后台音频元数据结果回写（主线程）。

        令牌守卫：token 与当前自增值不一致时直接丢弃陈旧结果。QPixmap
        仅在 GUI 线程构造（worker 只产出像素/调色板数据）。

        Args:
            token: 发起任务时的令牌。
            result: worker 回传的 ``{title, artist, album, cover_data, palette}``。
        """
        from shiboken6 import isValid as _isValid
        if not _isValid(self):
            return
        if token != self._audio_meta_token:
            return

        title = str(result.get("title", ""))
        artist = str(result.get("artist", ""))
        cover_data: Optional[bytes] = result.get("cover_data")
        palette = result.get("palette", [])

        # 流体背景配色：worker 已提取主色直接应用，无主色回退主题强调色
        if len(palette) >= 2:
            self._fluid_background.set_custom_colors(palette)
        else:
            self._fluid_background.use_accent_theme()

        # 音乐信息面板
        self._music_info_panel.set_title(title)
        self._music_info_panel.set_artist(artist)

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

        # 单次转换为 RGBA8888 后直接读像素缓冲，避免逐像素 QColor/pixel()
        # 跨界调用（旧实现为 4096 次对象构造）。分桶语义与顺序逐项保持：
        # 行主序遍历、优先出现顺序参与 Counter 平局排序、32 步长分桶、
        # alpha<=0 跳过。输出与旧实现完全一致（见对拍测试）。
        rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
        width, height = rgba.width(), rgba.height()
        stride = rgba.bytesPerLine()
        pixels = memoryview(rgba.constBits()).cast("B")

        buckets: Counter = Counter()
        for y in range(height):
            row_start = y * stride
            for x in range(width):
                i = row_start + x * 4
                if pixels[i + 3] == 0:
                    continue
                key = (
                    (pixels[i] // 32) * 32,
                    (pixels[i + 1] // 32) * 32,
                    (pixels[i + 2] // 32) * 32,
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
        register_widget_qss(self,(f"""
            VideoPlayerLayout {{
                background-color: {fill_color};
                border: 1px solid {border_color};
                border-radius: 8px;
            }}
        """))

    def cleanup(self) -> None:
        """清理资源，断开所有信号（可重复调用，不阻塞 UI 线程）。"""
        if getattr(self, "_cleaned_up", False):
            return
        self._cleaned_up = True
        # 令牌 +1 使仍在途的音频元数据/媒体加载任务全部失效
        self._audio_meta_token += 1
        self._tracks_token += 1
        self._media_load_token += 1
        if self._media_load_task is not None:
            self._media_load_task.request_cancel()
            self._media_load_task = None
        self._media_ready = False
        self._loading_spinner.setVisible(False)
        if self._fullscreen:
            self._exit_fullscreen()
        if self._mpv_manager:
            # 宿主清理顺序为先 stop_playback（异步停止）再 cleanup；这里只做
            # 线程安全的组件注销，避免在 UI 线程等待 MPV 操作 future，也避免
            # 关闭阶段再投递后台任务与 MPV 核心销毁竞态。
            try:
                self._mpv_manager.unregister_component(self._component_id)
            except (RuntimeError, TypeError):
                pass

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
        self._fluid_background_loaded = False

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
                self._mpv_manager.bufferingChanged.disconnect(self._on_buffering_changed)
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
        """停止播放（异步提交，不阻塞 UI 线程）。"""
        self._media_load_token += 1
        if self._media_load_task is not None:
            self._media_load_task.request_cancel()
            self._media_load_task = None
        self._media_ready = False
        if self._mpv_manager:
            QThreadPool.globalInstance().start(
                _ManagerStopTask(self._mpv_manager, self._component_id)
            )
        self._loading_spinner.setVisible(False)
        self._player_bar.set_playing(False)
        self._placeholder.setText("拖放视频文件或选择文件以播放")
        self._stack.setCurrentIndex(1)  # Show overlay

    # ── 内部方法 ──

    def _init_ui(self) -> None:
        """构建 UI：视频表面 + 占位覆盖层 + StyledPlayerBar"""
        # 可聚焦以接收键盘快捷操作（空格/方向键/数字键等）
        self.setFocusPolicy(Qt.StrongFocus)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Stacked layout: 0=video_surface, 1=overlay, 2=audio_surface
        self._stack = QStackedLayout()

        # ── 视频渲染表面（index 0）──
        self._video_surface = QWidget(self)
        register_widget_qss(self._video_surface,("background-color: #000;"))
        self._video_surface.setFocusPolicy(Qt.NoFocus)
        self._stack.addWidget(self._video_surface)

        # ── 占位覆盖层（index 1，未播放/加载中/缓冲中显示）──
        self._overlay = QWidget()
        register_widget_qss(self._overlay,("background-color: #1a1a1a;"))
        overlay_layout = QVBoxLayout(self._overlay)
        overlay_layout.setAlignment(Qt.AlignCenter)
        overlay_layout.setSpacing(16)

        # 加载/缓冲圆环（仅进行中状态显示）
        self._loading_spinner = StyledLoading(size="lg")
        self._loading_spinner.setVisible(False)
        overlay_layout.addWidget(self._loading_spinner, 0, Qt.AlignCenter)

        # 提示文字
        self._placeholder = QLabel("拖放视频文件或选择文件以播放")
        self._placeholder.setAlignment(Qt.AlignCenter)
        register_widget_qss(self._placeholder,(
            f"color: {tm.mid.name()}; font-size: 14px; background: transparent;"
        ))
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
            register_widget_qss(self._browse_btn,(f"""
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
            """))
            self._browse_btn.clicked.connect(self._on_browse_file)
            overlay_layout.addWidget(self._browse_btn, alignment=Qt.AlignCenter)

        self._stack.addWidget(self._overlay)

        # ── 音频渲染表面（index 2，音频模式时代替视频窗口）──
        self._audio_surface = QWidget()
        # 音频表面只承载流体层，不再提供独立的纯色底板，避免流体边缘
        # 未覆盖时露出与流体不一致的白色/黑色线条。
        self._audio_surface.setAttribute(Qt.WA_TranslucentBackground, True)
        self._audio_surface.setAttribute(Qt.WA_NoSystemBackground, True)
        self._audio_surface.setAutoFillBackground(False)
        register_widget_qss(self._audio_surface,("background: transparent;"))
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

        # OSD 默认定位到视频表面顶部居中（音频模式在 _on_file_loaded 中更新目标）
        self._player_bar.set_osd_target(self._video_surface)

    def _init_mpv(self) -> None:
        """初始化 MPV 管理器"""
        self._mpv_manager = MPVManager()
        self._component_id = f"video_player_layout_{id(self)}"
        self._mpv_manager.register_component(self._component_id, "VideoPlayerLayout")
        # MPV 管理器在首次加载文件时惰性初始化
        self._is_mpv_embedded = False
        self._current_file = ""
        # 异步媒体加载状态：token 丢弃陈旧结果；cancel_event 阻止过期 load/play
        self._media_load_token: int = 0
        self._media_load_task: Optional[_MediaLoadTask] = None
        self._media_ready: bool = False
        self._current_media_is_audio = False
        self._fluid_background_loaded: bool = False
        self._duration = 0.0
        self._current_position = 0.0
        self._current_speed = 1.0
        # 进度显示初始化的重试计数（每次文件加载重置，见 _on_file_loaded）
        self._progress_init_attempts = 0

        # 进度条交互防抖动控制（参考旧 PlayerControlBar 模式）
        self._user_interacting = False
        self._pending_seek_value: Optional[float] = None
        self._seek_debounce_timer = QTimer(self)
        self._seek_debounce_timer.setSingleShot(True)
        self._seek_debounce_timer.setInterval(250)
        self._seek_debounce_timer.timeout.connect(self._flush_pending_seek)

        # 音频元数据任务令牌与在途任务引用（todo-30：每次音频加载自增，
        # 陈旧结果丢弃；持有任务引用防止 Python 包装器提前 GC 导致
        # 跨线程 queued 信号被拆除——沿 file_info_panel _tasks 模式）
        self._audio_meta_token = 0
        self._audio_meta_tasks: List["_AudioMetadataTask"] = []

        # 音轨/字幕轨采集任务令牌与在途任务引用（同 audio meta 模式：
        # 文件加载后后台取轨，切歌令牌递增丢弃陈旧结果）
        self._tracks_token = 0
        self._tracks_tasks: List["_MediaTracksTask"] = []

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
        # 点击视频渲染表面时把键盘焦点交还给本组件，保证内嵌模式下
        # 空格/方向键等快捷操作能送达（参考旧版分离窗口的键盘行为）
        if (
            watched is getattr(self, "_video_surface", None)
            and event.type() == QEvent.Type.MouseButtonPress
        ):
            self.setFocus()
        return super().eventFilter(watched, event)

    # ── 键盘快捷操作（移植自旧版 VideoPlayer / DetachedVideoWindow） ──

    def keyPressEvent(self, event) -> None:
        """键盘快捷操作：空格播放/暂停、方向键 seek/音量、数字键倍速。

        Esc 键不在此处理——全屏模式下由 PreviewFullscreenHost 捕获并发出
        escapePressed 退出全屏，与旧版 DetachedVideoWindow 捕获 Esc 后
        reattach 的行为保持一致。
        """
        key = event.key()
        if key == Qt.Key_Space:
            self.toggle_play_pause()
            event.accept()
        elif key == Qt.Key_Left:
            self.seek_backward()
            event.accept()
        elif key == Qt.Key_Right:
            self.seek_forward()
            event.accept()
        elif key == Qt.Key_Up:
            self.volume_up()
            event.accept()
        elif key == Qt.Key_Down:
            self.volume_down()
            event.accept()
        elif key == Qt.Key_1:
            self.set_speed(1.0)
            event.accept()
        elif key == Qt.Key_2:
            self.set_speed(2.0)
            event.accept()
        elif key == Qt.Key_3:
            self.set_speed(3.0)
            event.accept()
        elif key == Qt.Key_QuoteLeft:  # ` 键
            self.set_speed(0.5)
            event.accept()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        """点击预览区域（占位覆盖层等）时获取键盘焦点。"""
        super().mousePressEvent(event)
        self.setFocus()

    def toggle_play_pause(self) -> bool:
        """切换播放/暂停状态（键盘空格键），并显示 OSD 提示。

        Returns:
            bool: 操作是否成功
        """
        if not self._mpv_manager or not self._mpv_manager.is_initialized():
            return False
        if self._mpv_manager.is_paused() or not self._mpv_manager.is_playing():
            result = self._mpv_manager.play(component_id=self._component_id)
            if result:
                self._player_bar.show_osd("播放")
            return result
        result = self._mpv_manager.pause(component_id=self._component_id)
        if result:
            self._player_bar.show_osd("暂停")
        return result

    def seek_forward(self, seconds: float = 5.0) -> bool:
        """向前跳转指定秒数（键盘右方向键），并显示 seek 进度 OSD。

        Args:
            seconds: 跳转秒数，默认为 5 秒

        Returns:
            bool: 操作是否成功
        """
        if not self._mpv_manager or not self._mpv_manager.is_initialized():
            return False
        current_position = self._mpv_manager.get_position() or 0.0
        duration = self._mpv_manager.get_duration() or 0.0
        new_position = min(current_position + seconds, duration)
        result = self._mpv_manager.seek(new_position, component_id=self._component_id)
        if result:
            self._player_bar.show_seek_osd(new_position, duration, "forward")
        return result

    def seek_backward(self, seconds: float = 5.0) -> bool:
        """向后跳转指定秒数（键盘左方向键），并显示 seek 进度 OSD。

        Args:
            seconds: 跳转秒数，默认为 5 秒

        Returns:
            bool: 操作是否成功
        """
        if not self._mpv_manager or not self._mpv_manager.is_initialized():
            return False
        current_position = self._mpv_manager.get_position() or 0.0
        duration = self._mpv_manager.get_duration() or 0.0
        new_position = max(current_position - seconds, 0.0)
        result = self._mpv_manager.seek(new_position, component_id=self._component_id)
        if result:
            self._player_bar.show_seek_osd(new_position, duration, "backward")
        return result

    def volume_up(self, step: int = 5) -> bool:
        """增加音量（键盘上方向键），并显示音量 OSD。

        Args:
            step: 音量步进值，默认为 5

        Returns:
            bool: 操作是否成功
        """
        if not self._mpv_manager or not self._mpv_manager.is_initialized():
            return False
        current_volume = self._mpv_manager.get_volume() or 0
        new_volume = min(current_volume + step, 100)
        result = self._mpv_manager.set_volume(new_volume, component_id=self._component_id)
        if result:
            self._player_bar.show_osd(f"音量 {new_volume}%")
        return result

    def volume_down(self, step: int = 5) -> bool:
        """减少音量（键盘下方向键），并显示音量 OSD。

        Args:
            step: 音量步进值，默认为 5

        Returns:
            bool: 操作是否成功
        """
        if not self._mpv_manager or not self._mpv_manager.is_initialized():
            return False
        current_volume = self._mpv_manager.get_volume() or 0
        new_volume = max(current_volume - step, 0)
        result = self._mpv_manager.set_volume(new_volume, component_id=self._component_id)
        if result:
            self._player_bar.show_osd(f"音量 {new_volume}%")
        return result

    def set_speed(self, speed: float) -> bool:
        """设置播放倍速（键盘 1/2/3/` 键），并显示倍速 OSD。

        Args:
            speed: 播放倍速，如 0.5, 1.0, 2.0, 3.0

        Returns:
            bool: 操作是否成功
        """
        if not self._mpv_manager or not self._mpv_manager.is_initialized():
            return False
        success = self._mpv_manager.set_speed(speed, component_id=self._component_id)
        if success:
            self._current_speed = speed
            self._player_bar.set_speed(f"{speed:.1f}x")
            self._player_bar.show_osd(f"{speed:.1f}x")
        return success

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
        # 设置弹窗：音轨/字幕切换 + 添加外部字幕
        self._player_bar.setting_changed.connect(self._on_player_setting_changed)
        self._player_bar.add_subtitle_requested.connect(
            self._on_add_subtitle_requested
        )

    def _connect_manager_signals(self) -> None:
        """MPVManager → StyledPlayerBar 状态同步"""
        if not self._mpv_manager:
            return
        self._mpv_manager.positionChanged.connect(self._on_position_changed)
        self._mpv_manager.stateChanged.connect(self._on_state_changed)
        self._mpv_manager.bufferingChanged.connect(self._on_buffering_changed)
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

    def _on_buffering_changed(self, is_buffering: bool) -> None:
        """MPV 缓存缓冲状态变化 → 显示/隐藏「正在缓冲…」圆环。

        仅在媒体已就绪后响应（加载阶段由加载遮罩负责）；切页幂等，
        快速抖动时不会反复重建控件。

        Args:
            is_buffering: ``True`` 表示 mpv ``paused-for-cache`` 生效。
        """
        if not self._media_ready:
            return
        if is_buffering:
            self._show_loading("正在缓冲…")
        else:
            self._hide_loading(restore=True)

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

    def _on_player_setting_changed(self, section: str, value: str) -> None:
        """设置弹窗音轨/字幕切换（section: "audio" | "subtitle"）。

        解析 track_id 为 int 后调用 MPVManager 对应接口；失败/异常仅记
        warning 日志不崩溃。切换成功后异步刷新一次轨道列表（选中态变化）。
        """
        if self._mpv_manager is None:
            return
        try:
            track_id = int(value)
        except (TypeError, ValueError):
            warning(f"无效的轨道ID: {value!r}")
            return

        try:
            if section == "audio":
                ok = self._mpv_manager.set_audio_track(
                    track_id, component_id=self._component_id
                )
            elif section == "subtitle":
                ok = self._mpv_manager.set_subtitle_track(
                    track_id, component_id=self._component_id
                )
            else:
                return
        except Exception as exc:  # noqa: BLE001 — mpv 任意异常不崩溃
            warning(f"切换轨道异常: section={section}, id={track_id}, {exc}")
            return

        if not ok:
            warning(f"切换轨道失败: section={section}, id={track_id}")
            return
        # 成功后异步刷新一次轨道列表（选中态/外部字幕可能变化）
        self._refresh_player_tracks()

    def _on_add_subtitle_requested(self) -> None:
        """设置弹窗「+ 添加…」：选择外部字幕文件并加载。"""
        if self._mpv_manager is None:
            return
        from PySide6.QtWidgets import QFileDialog

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "添加字幕文件",
            "",
            "字幕文件 (*.srt *.ass *.ssa *.vtt *.sub *.idx);;所有文件 (*.*)",
        )
        if not file_path:
            return
        try:
            ok = self._mpv_manager.load_subtitle(
                file_path, component_id=self._component_id
            )
        except Exception as exc:  # noqa: BLE001 — mpv 任意异常不崩溃
            warning(f"加载字幕异常: {file_path}, {exc}")
            return
        if not ok:
            warning(f"加载字幕失败: {file_path}")
            return
        # 加载成功后异步刷新字幕轨列表
        self._refresh_player_tracks()

    # ── 音轨/字幕轨异步采集 ─────────────────────────────────────

    def _refresh_player_tracks(self) -> None:
        """异步刷新音轨/字幕轨列表（文件加载后 / 切换轨道后调用）。

        仅在 MPV 核心已初始化且预览器可见时执行；``get_*_tracks`` 是阻塞式
        查询，必须在后台线程取，避免卡 UI。任务携带自增 token，快速切换
        文件时陈旧结果直接丢弃。
        """
        if self._mpv_manager is None or not self._mpv_manager.is_initialized():
            return
        if not self.isVisible():
            return

        self._tracks_token += 1
        token = self._tracks_token
        task = _MediaTracksTask(self._mpv_manager, token)
        task.done.connect(self._on_tracks_loaded)
        task.done.connect(lambda *_: self._untrack_tracks_task(task))
        self._tracks_tasks.append(task)
        task.start()

    def _untrack_tracks_task(self, task: "_MediaTracksTask") -> None:
        """结果回传后从在途任务列表移除（释放引用，允许包装器回收）。"""
        try:
            if task in self._tracks_tasks:
                self._tracks_tasks.remove(task)
        except RuntimeError:
            pass

    def _on_tracks_loaded(
        self,
        token: int,
        audio_tracks: Any,
        subtitle_tracks: Any,
    ) -> None:
        """后台轨道采集结果回写（主线程）。

        令牌守卫：token 与当前自增值不一致时直接丢弃陈旧结果。
        映射为设置弹窗条目后写入 StyledPlayerBar 缓存（弹窗已打开时
        由 bar 立即刷新显示），字幕列表末尾追加「+ 添加…」项。
        """
        from shiboken6 import isValid as _isValid
        if not _isValid(self):
            return
        if token != self._tracks_token:
            return

        audio_items = self._map_track_items(audio_tracks, "音轨")
        subtitle_items = self._map_track_items(subtitle_tracks, "字幕")
        subtitle_items.append({"id": "add", "label": "+ 添加…", "is_add": True})
        self._player_bar.set_audio_tracks(audio_items)
        self._player_bar.set_subtitle_tracks(subtitle_items)

    @staticmethod
    def _format_track_label(track: Dict[str, Any], index: int, fallback_prefix: str) -> str:
        """把 mpv 轨道 dict 转为弹窗条目标签。

        优先 track title；否则用语言 + 编码/声道的可读信息拼接；两者
        皆无时回退 ``f"{fallback_prefix} {index + 1}"``（1 基序号）。
        """
        title = str(track.get("title") or "").strip()
        if title:
            return title
        parts: List[str] = []
        lang = str(track.get("lang") or "").strip()
        if lang:
            parts.append(lang)
        codec = str(track.get("codec") or "").strip()
        if codec:
            parts.append(codec)
        channels = track.get("audio_channels")
        if channels:
            parts.append(str(channels))
        if parts:
            return " ".join(parts)
        return f"{fallback_prefix} {index + 1}"

    @classmethod
    def _map_track_items(
        cls, tracks: Any, fallback_prefix: str
    ) -> List[Dict[str, Any]]:
        """mpv 轨道列表 → 设置弹窗条目列表。

        条目形如 ``{"id": int, "label": str, "selected": bool}``；
        非法/缺 id 的轨道条目跳过，``tracks`` 非列表时返回空列表。
        """
        items: List[Dict[str, Any]] = []
        if not isinstance(tracks, list):
            return items
        for index, track in enumerate(tracks):
            if not isinstance(track, dict):
                continue
            try:
                track_id = int(track.get("id"))
            except (TypeError, ValueError):
                continue
            items.append(
                {
                    "id": track_id,
                    "label": cls._format_track_label(track, index, fallback_prefix),
                    "selected": bool(track.get("selected")),
                }
            )
        return items

    def _on_fullscreen_toggled(self, fullscreen: bool) -> None:
        """全屏按钮点击 → 分离到独立 frameless 全屏窗口 + 浮动控制栏模式

        Args:
            fullscreen: True=进入全屏, False=退出全屏
        """
        if fullscreen:
            self._enter_fullscreen()
        else:
            self._exit_fullscreen()

    def _enter_fullscreen(self) -> None:
        """分离到独立 frameless 全屏窗口。"""
        if self._fullscreen_host is None:
            self._fullscreen_host = PreviewFullscreenHost()
            self._fullscreen_host.escapePressed.connect(
                lambda: self._on_fullscreen_toggled(False)
            )
            # 全屏宿主失焦时立即隐藏已显示的浮动控制栏
            self._fullscreen_host.activated_changed.connect(
                self._on_fullscreen_host_active_changed
            )
        if not self._fullscreen_host.attach(self):
            return
        self._fullscreen_host.show_fullscreen()
        # 同步控制栏全屏按钮状态（进入全屏 → 显示还原图标）
        self._player_bar.set_fullscreen(True)
        # 进入全屏后启用浮动控制栏（自动隐藏 + 动画），目标改为宿主所在屏幕
        screen = self._fullscreen_host.screen() or QApplication.primaryScreen()
        if screen:
            self._player_bar.enter_floating_mode(
                target_widget=self._current_preview_widget(),
                screen_geometry=screen.geometry(),
            )
            # 焦点守卫：全屏宿主失焦时禁止鼠标唤出浮动控制栏
            self._player_bar.set_float_focus_guard(self._allow_floating_bar_show)
        self._fullscreen = True

    def _exit_fullscreen(self) -> None:
        """退出全屏：还原回主窗口内嵌布局。"""
        if self._fullscreen_host is None:
            self._fullscreen = False
            return
        self._player_bar.exit_floating_mode()
        self._player_bar.set_float_focus_guard(None)
        # 同步控制栏全屏按钮状态（退出全屏 → 显示全屏图标），
        # 覆盖 Esc / 宿主关闭等非按钮触发的退出链路（与旧版 set_detached(False) 一致）
        self._player_bar.set_fullscreen(False)
        self._fullscreen_host.exit_fullscreen()
        self._fullscreen_host.deleteLater()
        self._fullscreen_host = None
        self._fullscreen = False

    def _allow_floating_bar_show(self) -> bool:
        """浮动控制栏可见性守卫回调。

        全屏宿主激活时允许显示；宿主失焦后禁止显示，仅当光标正在
        控制栏或其弹出菜单上操作时放行（点击控制栏按钮会使焦点短暂
        转移到 Tool 窗口，需避免误隐藏）。

        Returns:
            bool: True 允许显示，False 禁止显示
        """
        host = self._fullscreen_host
        if host is None or not host.isVisible():
            return False
        if host.isActiveWindow():
            return True
        if self._player_bar.is_float_cursor_in_bar_area():
            return True
        return False

    def _on_fullscreen_host_active_changed(self, active: bool) -> None:
        """全屏宿主激活状态变化：失焦时立即隐藏已显示的浮动控制栏。

        Args:
            active: 宿主是否获得激活
        """
        if active or not self._fullscreen:
            return
        # 正在控制栏/弹窗上操作时不打断交互（点击控制栏按钮会短暂抢走焦点）
        if not self._player_bar.is_float_cursor_in_bar_area():
            self._player_bar.hide_float_bar()

    def _on_file_loaded(self, file_path: str) -> None:
        """文件加载完成 → 撤下加载圆环并切换到对应渲染表面。"""
        expected = os.path.normcase(os.path.abspath(self._current_file)) if self._current_file else ""
        actual = os.path.normcase(os.path.abspath(file_path)) if file_path else ""
        if expected and actual and expected != actual:
            debug(f"忽略过期 FILE_LOADED: {file_path}")
            return
        info(f"文件加载完成: {file_path}")
        self._media_ready = True
        self._hide_loading(restore=False)
        # 文件加载成功后，确保 stack 切到对应的渲染表面。
        # 切换文件时 mpv 会先触发旧文件的 END_FILE，可能导致 stack 被切到 overlay，
        # 这里在 FILE_LOADED 时主动纠正，确保视频/音频表面可见。
        if self._current_media_is_audio:
            self._stack.setCurrentIndex(self._audio_surface_index)
            # 音频表面可见后再初始化流体背景（隐藏时无有效 GL context）
            if not self._fluid_background_loaded:
                self._fluid_background.load()
                self._fluid_background_loaded = True
        else:
            self._stack.setCurrentIndex(0)  # 视频表面
        # OSD 定位目标跟随当前渲染表面（音频模式 → 音频表面，视频模式 → 视频表面）
        self._player_bar.set_osd_target(self._current_preview_widget())
        # 参考旧 VideoPlayer._initialize_progress_display，延迟初始化进度显示
        # 每次新文件加载重置重试计数（上一文件耗尽的计数不影响本文件）
        self._progress_init_attempts = 0
        QTimer.singleShot(200, self._initialize_progress_display)
        # 文件加载完成后再设置循环模式（避免与 loadfile 命令竞争）
        if self._mpv_manager:
            self._mpv_manager.set_loop("yes", component_id=self._component_id)
        # 后台采集音轨/字幕轨并填充设置弹窗（阻塞式查询，不进 UI 线程）
        self._refresh_player_tracks()

    def _on_file_ended(self, reason: int) -> None:
        """播放结束"""
        # REDIRECT 表示 loadfile 替换了当前文件（切换到下一个视频），
        # 新文件的 FILE_LOADED 事件会随后到达并刷新 UI。
        if reason == MpvEndFileReason.REDIRECT:
            debug(f"文件被 loadfile 替换（REDIRECT），跳过 overlay 切换")
            return
        self._player_bar.set_playing(False)
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
        时长尚未就绪时每 200ms 重试，最多 ``_PROGRESS_INIT_MAX_ATTEMPTS``
        次（5s）后放弃——修复此前无限重试在文件永不就绪时持续挂任务的
        问题（审查 3.1#25）；放弃后进度更新由 ``_heartbeat_sync`` 轮询兜底。
        """
        if not self._mpv_manager:
            return

        from shiboken6 import isValid as _isValid
        if not _isValid(self):
            return

        attempts = self._progress_init_attempts + 1
        self._progress_init_attempts = attempts

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
            elif attempts < self._PROGRESS_INIT_MAX_ATTEMPTS:
                QTimer.singleShot(200, self._initialize_progress_display)
            else:
                debug(
                    f"进度显示初始化放弃：{attempts} 次重试后仍未拿到有效时长，"
                    "交由心跳轮询兜底"
                )
        except Exception as e:
            warning(f"初始化进度显示失败: {e}")
            if attempts < self._PROGRESS_INIT_MAX_ATTEMPTS:
                QTimer.singleShot(200, self._initialize_progress_display)

    #: 进度显示初始化最大重试次数（25 × 200ms = 5s，超时放弃；见审查 3.1#25）
    _PROGRESS_INIT_MAX_ATTEMPTS = 25

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
