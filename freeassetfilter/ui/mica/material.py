"""Mica 材质层（Qt 门面）—— 把 ``ui.mica`` 的纯数据烘焙管线接到窗口绘制上。

本模块是「无 DWM、纯自主渲染」Mica 的最后一段：它持有壁纸源与烘焙引擎，在后台
线程里把「窗口矩形 + 参数 + 壁纸」变成一小块色调场，再把这块色调场以 QPixmap 的
形式铺满背景控件。它刻意**不依赖任何 DWM 原生 API**，与背景控件通过绘制回调
（``paint`` / ``paint_gpu``）解耦。

与旧版 ``components.mica_material`` 的关键差异
--------------------------------------------
* 重活（采壁纸 + 色调场管线）全部在 :mod:`ui.mica.engine` / :mod:`ui.mica.source`
  里完成，且天然可放进后台线程；本层只负责线程调度、QPixmap 转换、淡入淡出、
  焦点感知、噪声颗粒与绘制。
* 烘焙产物是**已经按窗口尺寸生成的色调场**（网格 ≤192 长边），因此绘制时只需
  把它平滑放大铺满即可，**不再需要旧版那种「整块虚拟桌面模糊图 + 按窗口位置取子矩形」
  的复杂几何**——这正是「亮度锁死、只留低频色度」带来的简化红利。
* 坐标空间统一为 Win32 物理像素：窗口矩形取自 ``winapi.window_rect``，与壁纸源
  画布（``winapi.virtual_screen_rect``）同坐标系，HiDPI 下也严格对齐。

线程模型
--------
* 首次（非 lazy）与同步降级走 :meth:`MicaMaterial.refresh` —— 主线程直接烘焙，
  启动期一次性卡顿可接受。
* 交互 / 参数变更走 :meth:`MicaMaterial.refresh_async` —— 在后台 ``QThread`` 里跑
  ``provider.acquire() + gpu_bake``，配看门狗 + 有界退避重试（见 ``config`` 的
  ``BAKE_WATCHDOG_MS`` / ``BAKE_MAX_RETRIES`` / ``BAKE_RETRY_DELAY_MS``）。
  壁纸采集只用 COM（``ensure_com`` 每线程幂等初始化），numpy 在后台线程释放 GIL，
  因此不阻塞 UI。

拖动期的实时跟随
----------------
重烘焙天然是"按次计费"的（一次完整管线），无法逐帧承担。因此拖拽走的是
:mod:`ui.mica.drag` 的**偏移采样**：拖到一半时烘一块**比窗口大一圈**的色调场，
之后每个 ``moveEvent`` 只从这块场里按位移取一个子矩形做 blit —— 零重计算，
逐帧成本恒为一次子矩形绘制。

``moveEvent`` → :meth:`MicaMaterial.begin_interaction` 的调用链因此承担三件事：
估计运动速度、按需申请拖动场、请求重绘。绘制路径见 :meth:`MicaMaterial.paint`。
余量与画质由 :class:`~ui.mica.drag.DragSampler` 按实测烘焙延迟自适应调节，
设备跟不上时自动冻结并退回"保持上一块色调场"的旧行为。
"""

from __future__ import annotations

import logging
import threading
import time
import weakref
from typing import Optional, Tuple, Union

import numpy as np
from PySide6.QtCore import (
    QElapsedTimer,
    QEvent,
    QObject,
    QPoint,
    QRect,
    QRectF,
    QRunnable,
    QThread,
    QThreadPool,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QImage,
    QPaintEvent,
    QPainter,
    QPixmap,
    QResizeEvent,
    QMoveEvent,
)
from PySide6.QtWidgets import QApplication, QWidget

from . import winapi
from .config import (
    BAKE_MAX_RETRIES,
    BAKE_RETRY_DELAY_MS,
    BAKE_WATCHDOG_MS,
    DEACTIVATE_DEBOUNCE_MS,
    FADE_DURATION_MS,
    G1_DARK,
    G1_LIGHT,
    NOISE_OPACITY,
    NOISE_SEED,
    NOISE_TILE_SIZE,
    SETTLE_INTERVAL_MS,
)
from .drag import (
    DRAG_REQUEST_COOLDOWN_MS,
    DRAG_VELOCITY_SMOOTHING,
    DragField,
    DragPlan,
    DragSampler,
)
from .engine import BakeRequest
from .gpu import gpu_bake
from .source import WallpaperProvider

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 模块级工具
# ---------------------------------------------------------------------------


def _parse_color(value: Union[str, QColor, None], fallback: QColor) -> QColor:
    """解析 hex 字符串或 ``QColor`` 为 ``QColor``；``None`` / 非法值回退 ``fallback``。

    Args:
        value: ``"#RGB"`` / ``"#RGBA"`` / ``"#RRGGBB"`` / ``"#RRGGBBAA"`` / ``QColor`` / ``None``。
        fallback: 解析失败时的兜底色。

    Returns:
        解析后的 :class:`QColor`。
    """
    if value is None:
        return fallback
    if isinstance(value, QColor):
        return value
    if isinstance(value, str):
        s = value.lstrip("#")
        try:
            if len(s) == 3:
                r, g, b = int(s[0] * 2, 16), int(s[1] * 2, 16), int(s[2] * 2, 16)
                return QColor(r, g, b)
            if len(s) == 4:
                r, g, b = int(s[0] * 2, 16), int(s[1] * 2, 16), int(s[2] * 2, 16)
                return QColor(r, g, b, int(s[3] * 2, 16))
            if len(s) == 6:
                return QColor("#" + s)
            if len(s) == 8:
                r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
                return QColor(r, g, b, int(s[6:8], 16))
        except ValueError:
            pass
    return fallback


def _is_dark_color(color: QColor) -> bool:
    """按感知亮度判断颜色是否为「深色」（用于推导 Mica 主题模式）。

    Args:
        color: 待判断的颜色。

    Returns:
        感知亮度 < 128（0–255 标度）视为深色，返回 ``True``。
    """
    lum = color.red() * 0.299 + color.green() * 0.587 + color.blue() * 0.114
    return lum < 128


# ---------------------------------------------------------------------------
# 后台烘焙 worker
# ---------------------------------------------------------------------------


class _BakeWorker(QObject):
    """后台烘焙任务：在独立线程里跑 ``provider.acquire() + engine.bake``。

    只消费 numpy / COM（无 Qt 控件访问），结果以信号把 :class:`~ui.mica.engine.BakedField`
    回传主线程。``BakeRequest`` 所需的窗口矩形已在主线程算好（Qt 几何非线程安全），
    经 ``job`` 传入。
    """

    done = Signal(object)  # BakedField
    failed = Signal()

    def __init__(
        self,
        provider: WallpaperProvider,
        window_rect: Tuple[int, int, int, int],
        params,  # MicaParams（不可变 dataclass，跨线程只读安全）
        dark: bool,
    ) -> None:
        super().__init__()
        self._provider = provider
        self._window_rect = window_rect
        self._params = params
        self._dark = dark

    def run(self) -> None:
        """执行一次烘焙；任何异常都按失败上报，绝不抛出到线程之外。"""
        try:
            source = self._provider.acquire()
            if source.pixels.size == 0:
                self.failed.emit()
                return
            request = BakeRequest(
                self._window_rect, self._params, self._dark, source.signature
            )
            field = gpu_bake(request, source)
            if field is None:
                self.failed.emit()
                return
            self.done.emit(field)
        except Exception as exc:  # pragma: no cover - 防御性兜底
            _LOG.debug("后台烘焙异常：%s", exc)
            self.failed.emit()


# ---------------------------------------------------------------------------
# 拖动场烘焙任务（线程池；与上面的 QThread 通道互不干扰）
# ---------------------------------------------------------------------------


class _DragSignals(QObject):
    """拖动场任务的结果桥（跨线程信号必须挂在 QObject 上）。"""

    #: 参数为 :class:`~ui.mica.drag.DragField` 或 ``None``（失败）。
    finished = Signal(object)


class _DragTask(QRunnable):
    """在线程池里烘焙一块放大色调场，供拖动期逐帧偏移取样。

    与 :class:`_BakeWorker` 的区别：本任务**不做**重试与看门狗。拖动场是纯
    加速用的投机产物，失败最坏情况是这一帧回退到旧色调场，不值得为它维护
    一套重试状态机；真正的正确性由运动停止后的常规烘焙保证。

    线程安全：``provider`` 的缓存由 ``lock`` 保护（与主线程同步烘焙互斥）。
    """

    def __init__(
        self,
        provider: WallpaperProvider,
        plan: DragPlan,
        params,  # MicaParams（不可变 dataclass，跨线程只读安全）
        dark: bool,
        lock: threading.Lock,
        signals: _DragSignals,
    ) -> None:
        """初始化任务。

        Args:
            provider: 壁纸源提供者。
            plan: 拖动场规划（区域 + 网格尺寸）。
            params: 用户参数。
            dark: 是否深色模式。
            lock: 保护 ``provider`` 缓存的锁。
            signals: 结果桥。
        """
        super().__init__()
        self._provider = provider
        self._plan = plan
        self._params = params
        self._dark = dark
        self._lock = lock
        self._signals = signals

    def run(self) -> None:
        """执行烘焙并回传结果；任何异常都按 ``None`` 上报，绝不抛出。"""
        started = time.perf_counter()
        try:
            with self._lock:
                source = self._provider.acquire()
                if source.pixels.size == 0:
                    self._signals.finished.emit(None)
                    return
                request = BakeRequest(
                    self._plan.region, self._params, self._dark, source.signature
                )
                field = gpu_bake(request, source, grid_size=self._plan.grid)
                if field is None:
                    self._signals.finished.emit(None)
                    return

            duration = (time.perf_counter() - started) * 1000.0
            self._signals.finished.emit(
                DragField(
                    image=field.image,
                    region=self._plan.region,
                    grid=self._plan.grid,
                    win_size=self._plan.win_size,
                    key=(self._params, self._dark, request.source_signature),
                    backend=field.backend,
                    duration_ms=duration,
                    cover=self._plan.cover,
                    quality=self._plan.quality,
                )
            )
        except Exception as exc:  # pragma: no cover - 防御性兜底
            _LOG.debug("拖动场烘焙异常：%s", exc)
            self._signals.finished.emit(None)


# ---------------------------------------------------------------------------
# MicaMaterial —— 对外门面
# ---------------------------------------------------------------------------


class MicaMaterial(QObject):
    """窗口级 Mica 背景材质。

    用法::

        mica = MicaMaterial(parent, blur_radius=200, surface_color="#000000",
                            luminosity=0.65, contrast=1.5, saturation=4.5,
                            overlay_opacity=0.7, lazy=True)
        # 在控件的 paintEvent 里：
        mica.paint(painter, event)
        # 壁纸变化 / 焦点切换 / 参数调整时调用对应方法。

    兼容旧版 ``components.mica_material.MicaMaterial`` 的公开契约：``__init__``、
    ``paint``、``paint_gpu``、``set_effect_parameters``、``set_theme``、``refresh``、
    ``begin_interaction``、``invalidate_cache``、``dispose``、``set_active`` 均保持
    同样的签名与语义。
    """

    def __init__(
        self,
        widget: QWidget,
        blur_radius: int = 200,
        surface_color: Union[str, QColor, None] = None,
        luminosity: float = 0.65,
        contrast: float = 1.5,
        saturation: float = 4.5,
        overlay_opacity: float = 0.7,
        lazy: bool = False,
    ) -> None:
        """初始化材质层。

        Args:
            widget: 应用 Mica 效果的控件（背景控件）。
            blur_radius: 色度低通强度（映射为烘焙网格像素 σ），0–300。
            surface_color: 实色兜底层颜色；默认按主题深浅取纯黑 / 纯白。
            luminosity: 旧版亮度系数（新模型已把亮度锁进 G1，仅保留以兼容签名）。
            contrast: 色度上限倍率，0–3。
            saturation: 色度增益，0–8。
            overlay_opacity: 色调场绘制不透明度（0–1），仅绘制期生效，改它不重烘焙。
            lazy: 为 ``True`` 时延迟到显式 ``refresh()`` 才做首次烘焙。
        """
        super().__init__()
        self._widget = widget

        # 颜色 / 主题
        self._surface_color = _parse_color(
            surface_color, QColor("#000000")
        )
        self._dark = _is_dark_color(self._surface_color)
        self._luminosity = max(0.0, min(1.0, float(luminosity)))
        self._overlay_opacity = max(0.0, min(1.0, float(overlay_opacity)))

        # 烘焙参数：tint_opacity 固定为 100（色度在烘焙期全量融合进图像），
        # 可见强度完全由绘制期 overlay_opacity 控制，避免双重衰减、也更贴近
        # 「滑块 = Mica 强度」的直觉。
        from .config import MicaParams

        self._params = MicaParams(
            saturation=max(0.0, float(saturation)),
            contrast=max(0.0, float(contrast)),
            blur_radius=max(0.0, float(blur_radius)),
            tint_opacity=100.0,
        )

        # 壁纸源（持有缓存；fallback 随主题更新）
        self._provider = WallpaperProvider(fallback_rgb=G1_DARK if self._dark else G1_LIGHT)
        self._bake_lock = threading.Lock()

        # 噪声颗粒（掩盖 8-bit 渐变条带，肉眼几乎不可见）
        self._noise_tile = self._make_noise_tile()

        # 烘焙产物
        self._pixmap: Optional[QPixmap] = None
        self._last_req: Optional[BakeRequest] = None
        self._has_shown = False

        # 交互状态
        self._interacting = False
        self._settle_timer = QTimer(self._widget)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(SETTLE_INTERVAL_MS)
        self._settle_timer.timeout.connect(self._on_settle)

        # 后台线程生命周期状态
        self._worker_thread: Optional[QThread] = None
        self._worker: Optional[_BakeWorker] = None
        self._refresh_retries = 0
        self._refresh_outcome: Optional[str] = None
        self._rebuild_pending = False
        self._watchdog = QTimer(self._widget)
        self._watchdog.setSingleShot(True)
        self._watchdog.setInterval(BAKE_WATCHDOG_MS)
        self._watchdog.timeout.connect(self._on_bake_timeout)

        # 拖动期偏移采样（详见 ui.mica.drag）
        self._disposed = False
        self._drag_sampler = DragSampler()
        self._drag_field: Optional[DragField] = None
        self._drag_pixmap: Optional[QPixmap] = None
        self._drag_pending: bool = False
        self._drag_requested_at: float = 0.0
        self._drag_signals = _DragSignals()
        self._drag_signals.finished.connect(self._on_drag_field_ready)
        self._motion_last: Optional[Tuple[float, int, int]] = None
        self._motion_size: Optional[Tuple[int, int]] = None
        self._velocity: Tuple[float, float] = (0.0, 0.0)
        self._resizing: bool = False

        # 淡入淡出
        self._fade_alpha = 1.0
        self._fade_from = 1.0
        self._fade_to = 1.0
        self._fade_clock = QElapsedTimer()
        self._fade_timer = QTimer(self._widget)
        self._fade_timer.setInterval(16)
        self._fade_timer.timeout.connect(self._on_fade_tick)
        self._active = True
        self._paused = False

        # 焦点感知（失焦淡出并暂停绘制）
        self._focus_whitelist: set = set()
        self._deactivate_timer = QTimer(self._widget)
        self._deactivate_timer.setSingleShot(True)
        self._deactivate_timer.setInterval(DEACTIVATE_DEBOUNCE_MS)
        self._deactivate_timer.timeout.connect(self._on_deactivate_check)
        top = self._widget.window()
        if top is not None:
            top.installEventFilter(self)

        if not lazy:
            self.refresh()

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """同步（主线程）重载壁纸并烘焙。用作初始化与后台失败时的降级路径。

        若已有后台烘焙在途则直接返回（由 worker 交付结果），避免重复烘焙。
        """
        if self._worker_thread is not None:
            return
        field = self._bake_sync()
        if field is not None:
            was_shown = self._has_shown
            self._apply_field(field)
            if self._active:
                self._start_fade_in(reset=not was_shown)
            else:
                self._hide_immediately()

    def refresh_async(self) -> None:
        """在后台线程异步烘焙（非阻塞）。

        有界重试：失败 / 超时累计超过 :data:`~ui.mica.config.BAKE_MAX_RETRIES` 后
        放弃并保留上一块有效色调场（或纯色兜底）。已有在途任务时忽略。
        """
        if self._worker_thread is not None:
            return
        if self._refresh_retries > BAKE_MAX_RETRIES:
            return
        job = (self._window_rect_tuple(), self._params, self._dark)
        self._worker = _BakeWorker(self._provider, job[0], job[1], job[2])
        self._worker_thread = QThread()
        self._worker.moveToThread(self._worker_thread)
        self._worker.done.connect(self._on_bake_done)
        self._worker.failed.connect(self._on_bake_failed)
        self._worker_thread.finished.connect(self._cleanup_worker)
        self._worker_thread.started.connect(self._worker.run)
        self._watchdog.start(BAKE_WATCHDOG_MS)
        self._worker_thread.start()

    def paint(
        self,
        painter: Optional[QPainter] = None,
        event: Optional[QPaintEvent] = None,
    ) -> None:
        """把 Mica 背景绘制到控件。

        交互期优先走**偏移采样**：从缓存的放大色调场里按当前窗口位置取一个
        浮点子矩形做一次 blit，不重跑任何管线。取不到（场未就绪 / 越界 /
        缩放中）时自动退回"上一块整窗色调场"。

        Args:
            painter: 复用传入的画笔；为 ``None`` 时自建（调用方负责生命周期）。
            event: 保留以兼容旧签名，本实现不使用。
        """
        widget = self._widget
        if painter is None:
            painter = QPainter(widget)

        rect = widget.rect()
        if self._paused:
            painter.fillRect(rect, self._surface_color)
            return

        # 实色兜底层 + 线性淡入：透明度 = 淡入 × overlay，实现 surface→Mica 过渡
        painter.fillRect(rect, self._surface_color)

        source = self._drag_source_rect() if self._interacting else None
        pixmap = self._drag_pixmap if source is not None else self._pixmap
        if pixmap is None or pixmap.isNull():
            return

        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setOpacity(self._fade_alpha * self._overlay_opacity)
        if source is None:
            painter.drawPixmap(rect, pixmap)
        else:
            # 源矩形用 QRectF：让双线性取样落在亚像素位置，避免取整导致的
            # 台阶式跳动（1 个网格像素放大到窗口就是若干个屏幕像素）。
            painter.drawPixmap(QRectF(rect), pixmap, QRectF(*source))
        painter.setOpacity(1.0)

        # 薄膜颗粒：仅以极低不透明度叠加，消除大渐变上的色带
        if self._noise_tile is not None:
            painter.setOpacity(self._fade_alpha * NOISE_OPACITY)
            painter.drawTiledPixmap(rect, self._noise_tile)
            painter.setOpacity(1.0)

    def paint_gpu(self, painter: QPainter) -> None:
        """在 GPU 画笔画笔（``QOpenGLWidget``）上绘制 Mica 背景。

        Args:
            painter: 来自 ``paintGL`` 的画笔画笔。
        """
        rect = self._widget.rect()
        if self._paused or self._pixmap is None or self._pixmap.isNull():
            painter.fillRect(rect, self._surface_color)
            return
        painter.fillRect(rect, self._surface_color)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setOpacity(self._fade_alpha * self._overlay_opacity)
        painter.drawPixmap(rect, self._pixmap)
        painter.setOpacity(1.0)
        if self._noise_tile is not None:
            painter.setOpacity(self._fade_alpha * NOISE_OPACITY)
            painter.drawTiledPixmap(rect, self._noise_tile)
            painter.setOpacity(1.0)

    def set_theme(self, surface_color: Union[str, QColor, None], luminosity: float) -> None:
        """切换主题：更新实色层与深浅模式，并触发热重烘焙（G1 基色随主题变化）。

        Args:
            surface_color: 新的实色层颜色。
            luminosity: 旧版亮度系数（仅保留签名兼容，新模型不消费）。
        """
        self._surface_color = _parse_color(surface_color, self._surface_color)
        self._luminosity = max(0.0, min(1.0, float(luminosity)))
        self._dark = _is_dark_color(self._surface_color)
        self._provider._fallback_rgb = G1_DARK if self._dark else G1_LIGHT
        self._request_rebuild()
        self._widget.update()

    def set_effect_parameters(
        self,
        blur_radius: Optional[int] = None,
        overlay_opacity: Optional[float] = None,
        saturation: Optional[float] = None,
        contrast: Optional[float] = None,
    ) -> None:
        """更新用户可调的 Mica 参数。

        * ``overlay_opacity``：仅绘制期生效 → 直接重绘，不重烘焙（拖动滑块零成本）。
        * ``blur_radius`` / ``saturation`` / ``contrast``：影响烘焙 → 在后台线程重建。

        Args:
            blur_radius: 色度低通强度（px），或 ``None`` 保持。
            overlay_opacity: 色调场绘制不透明度（0–1），或 ``None`` 保持。
            saturation: 色度增益，或 ``None`` 保持。
            contrast: 色度上限倍率，或 ``None`` 保持。
        """
        needs_rebuild = False
        opacity_changed = False

        if blur_radius is not None:
            new_v = max(0.0, float(blur_radius))
            if new_v != self._params.blur_radius:
                self._params = self._params.replace(blur_radius=new_v)
                needs_rebuild = True
        if saturation is not None:
            new_v = max(0.0, float(saturation))
            if new_v != self._params.saturation:
                self._params = self._params.replace(saturation=new_v)
                needs_rebuild = True
        if contrast is not None:
            new_v = max(0.0, float(contrast))
            if new_v != self._params.contrast:
                self._params = self._params.replace(contrast=new_v)
                needs_rebuild = True
        if overlay_opacity is not None:
            new_v = max(0.0, min(1.0, float(overlay_opacity)))
            if new_v != self._overlay_opacity:
                self._overlay_opacity = new_v
                opacity_changed = True

        if needs_rebuild:
            self._request_rebuild()
        elif opacity_changed:
            self._widget.update()

    def begin_interaction(self) -> None:
        """标记窗口拖拽 / 缩放开始或持续。

        与旧实现的差别：不再只是"保持旧图 + 等运动停止"，而是顺带推进
        :mod:`ui.mica.drag` 的偏移采样 —— 估计速度、按需申请 / 续接拖动场、
        请求重绘。于是拖拽过程中每一帧的背景都是按当前位置重新取样的，
        而非停在那里等稳定定时器。

        运动停止后仍由 :meth:`_on_settle` 触发一次全质量常规烘焙，保证静止
        时的画质不受拖动期任何降级影响。
        """
        self._interacting = True
        self._track_motion()
        self._ensure_drag_field()
        self._settle_timer.start()
        self._widget.update()

    def invalidate_cache(self) -> None:
        """使缓存失效：下次绘制前强制重烘焙。"""
        self._last_req = None
        self._pixmap = None
        self._maybe_rebake(force=True)

    def dispose(self) -> None:
        """释放资源：阻止重试、移除焦点过滤器、回收在途线程。窗口关闭时调用。"""
        self._disposed = True
        # 先断连，防止线程池里在途的任务在我们析构后回传结果
        try:
            self._drag_signals.finished.disconnect(self._on_drag_field_ready)
        except (TypeError, RuntimeError):
            pass
        self._drag_field = None
        self._drag_pixmap = None
        self._drag_pending = False
        self._refresh_retries = BAKE_MAX_RETRIES + 1
        self._refresh_outcome = "fail"
        self._rebuild_pending = False
        top = self._widget.window()
        if top is not None:
            try:
                top.removeEventFilter(self)
            except (TypeError, RuntimeError):
                pass
        self._active = False
        self._paused = True
        self._stop_fade()
        self._settle_timer.stop()
        self._deactivate_timer.stop()
        self._watchdog.stop()
        if self._worker_thread is not None:
            thread = self._worker_thread
            worker = self._worker
            self._worker_thread = None
            self._worker = None
            thread.quit()
            if not thread.wait(0) and not thread.isFinished():
                thread.terminate()
            if worker is not None:
                worker.deleteLater()
            thread.deleteLater()

    def set_active(self, active: bool) -> None:
        """设置主窗口焦点状态：失焦淡出隐藏并暂停绘制，回焦淡入恢复。

        Args:
            active: 是否处于焦点。
        """
        if active == self._active:
            return
        self._active = active
        if active:
            self._start_fade_in()
        else:
            self._start_fade_out()

    def add_focus_whitelist(self, window: QWidget) -> None:
        """把应用自身拉起的窗口登记为失焦白名单（弱引用）。"""
        try:
            self._focus_whitelist.add(weakref.ref(window))
        except TypeError:
            pass

    def remove_focus_whitelist(self, window: QWidget) -> None:
        """从失焦白名单移除指定窗口。"""
        self._focus_whitelist = {
            w for w in self._focus_whitelist if w() is not None and w() is not window
        }

    # ------------------------------------------------------------------
    # 事件过滤（焦点感知）
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt 命名)
        """顶层窗口激活 / 失焦事件：驱动 Mica 淡入恢复 / 淡出隐藏。"""
        top = self._widget.window()
        if obj is top:
            etype = event.type()
            if etype == QEvent.Type.WindowActivate:
                if self._deactivate_timer.isActive():
                    self._deactivate_timer.stop()
                self.set_active(True)
            elif etype == QEvent.Type.WindowDeactivate:
                if not self._deactivate_timer.isActive():
                    self._deactivate_timer.start()
        return False

    def _is_in_focus_whitelist(self, window: QWidget) -> bool:
        """判断窗口是否落在失焦白名单（含作为主窗口子对话框的父链归属）。"""
        if window is None:
            return False
        if window in self._focus_whitelist:
            return True
        top = self._widget.window()
        p = window.parent()
        while p is not None:
            if p is top:
                return True
            p = p.parent()
        return False

    def _on_deactivate_check(self) -> None:
        """失焦防抖复查：仅当焦点真正离开整个应用时才隐藏；若仍在应用内（含白名单
        窗口）则保持显示。"""
        active = QApplication.activeWindow()
        if active is None:
            self.set_active(False)
        elif not self._is_in_focus_whitelist(active):
            self.set_active(True)

    # ------------------------------------------------------------------
    # 烘焙调度
    # ------------------------------------------------------------------

    def _window_rect_tuple(self) -> Tuple[int, int, int, int]:
        """取得窗口矩形（Win32 物理像素，与壁纸源画布同坐标系）。

        Returns:
            ``(x, y, w, h)``。失败时回退到 Qt 逻辑几何（非 Windows / 无句柄时）。
        """
        hwnd = 0
        try:
            # 必须取顶层窗口句柄：对子控件调 winId() 会强制它原生化，
            # 并连带原生化全部兄弟控件（未设 AA_DontCreateNativeWidgetSiblings
            # 时），原生子窗口位置同步出错会导致整窗内容偏移/黑边。
            top = self._widget.window()
            hwnd = int(top.winId()) if top is not None else 0
        except (TypeError, RuntimeError, ValueError):
            hwnd = 0
        if winapi.IS_WINDOWS and hwnd:
            r = winapi.window_rect(hwnd)
            if r[2] > 0 and r[3] > 0:
                return r
        w = self._widget.window()
        geo = w.geometry() if w is not None else self._widget.geometry()
        return (geo.x(), geo.y(), geo.width(), geo.height())

    def _bake_sync(self):
        """主线程同步烘焙（带锁，防止与后台 worker 并发访问 provider 缓存）。"""
        with self._bake_lock:
            try:
                source = self._provider.acquire()
                if source.pixels.size == 0:
                    return None
                request = BakeRequest(
                    self._window_rect_tuple(), self._params, self._dark, source.signature
                )
                return gpu_bake(request, source)
            except Exception as exc:  # pragma: no cover - 防御性兜底
                _LOG.debug("同步烘焙失败：%s", exc)
                return None

    def _maybe_rebake(self, force: bool = False) -> None:
        """按需触发热重烘焙：仅当相对上一次请求确有变化（尺寸 / 位移 / 参数 / 壁纸）时。

        Args:
            force: 强制重烘焙（忽略 ``needs_rebake`` 判据）。
        """
        if self._worker_thread is not None:
            self._rebuild_pending = True
            return
        candidate = BakeRequest(
            self._window_rect_tuple(),
            self._params,
            self._dark,
            self._provider.probe().signature(),
        )
        if not force and self._last_req is not None and not candidate.needs_rebake(self._last_req):
            return
        self.refresh_async()

    def _request_rebuild(self) -> None:
        """使相对上一次请求的判据失效并触发热重烘焙。"""
        self._last_req = None
        self._maybe_rebake(force=True)

    def _on_settle(self) -> None:
        """交互停止：退出偏移采样路径，按当前位置决定是否重烘焙。

        这里触发的是**全质量**常规烘焙，因此拖动期可能发生的画质降级
        （见 :data:`ui.mica.drag.DRAG_QUALITY_LEVELS`）不会残留到静止状态。
        """
        self._interacting = False
        self._resizing = False
        self._velocity = (0.0, 0.0)
        self._motion_last = None
        self._drag_sampler.reset()
        self._maybe_rebake(force=False)

    # ------------------------------------------------------------------
    # 拖动期偏移采样
    # ------------------------------------------------------------------

    def _active_key(self) -> Tuple[object, ...]:
        """当前有效性判据 ``(params, dark, source_signature)``。

        三者任一变化，缓存的拖动场即作废。首次烘焙完成前签名为空串，此时
        任何已有拖动场都会被判为失效 —— 这是刻意的，避免出现"拖动场与常规
        场来自不同壁纸"的混合画面。
        """
        signature = self._last_req.source_signature if self._last_req is not None else ""
        return (self._params, self._dark, signature)

    def _track_motion(self) -> None:
        """按 ``moveEvent`` 的时间与位置估计速度，并识别"正在缩放"。

        速度用于让 :class:`~ui.mica.drag.DragSampler` 预留足够余量，以及把
        拖动场**沿运动方向前移**（余量更多落在即将经过的一侧）。间隔超过
        0.25 s 视为新的一段运动并清零 —— 否则"停一会儿再拖"会算出一个跨越
        停顿的巨大瞬时速度。
        """
        rect = self._window_rect_tuple()
        now = time.perf_counter()
        prev = self._motion_last
        self._motion_last = (now, rect[0], rect[1])

        if self._motion_size is not None and rect[2:] != self._motion_size:
            # 尺寸在变 = 缩放中。此时网格尺寸随窗口尺寸变化，无法预测，
            # 偏移采样无意义，交给稳定后的常规烘焙。
            self._resizing = True
        self._motion_size = rect[2:]

        if prev is None:
            return
        dt = now - prev[0]
        if dt <= 1e-4 or dt > 0.25:
            self._velocity = (0.0, 0.0)
            return
        vx = (rect[0] - prev[1]) / dt
        vy = (rect[1] - prev[2]) / dt
        alpha = DRAG_VELOCITY_SMOOTHING
        self._velocity = (
            self._velocity[0] * alpha + vx * (1.0 - alpha),
            self._velocity[1] * alpha + vy * (1.0 - alpha),
        )

    def _drag_source_rect(self) -> Optional[Tuple[float, float, float, float]]:
        """取得当前窗口位置在拖动场中的子矩形。

        Returns:
            ``(sx, sy, sw, sh)`` 浮点源矩形；场未就绪、已作废或越界时 ``None``。
        """
        field = self._drag_field
        if field is None or self._drag_pixmap is None or self._drag_pixmap.isNull():
            return None
        if field.key != self._active_key():
            return None
        return field.source_rect(self._window_rect_tuple())

    def _ensure_drag_field(self) -> None:
        """按需申请一块拖动场（幂等：已有可用场或在途请求时直接返回）。"""
        if self._disposed or self._drag_pending or self._resizing:
            return
        if self._drag_sampler.frozen:
            return

        win = self._window_rect_tuple()
        key = self._active_key()
        field = self._drag_field

        if field is not None:
            if field.key != key or field.win_size != win[2:]:
                # 参数 / 主题 / 壁纸 / 尺寸已变：本场作废，按当前条件重新申请。
                self._drag_field = None
                self._drag_pixmap = None
            elif field.source_rect(win) is not None:
                return  # 仍在覆盖范围内，无需重烘焙
            else:
                # 跑到覆盖范围之外了：记一次越界，交给控制器放大余量。
                self._drag_sampler.note_miss()

        now = time.perf_counter()
        if now - self._drag_requested_at < DRAG_REQUEST_COOLDOWN_MS / 1000.0:
            return

        self._drag_requested_at = now
        self._drag_pending = True
        plan = self._drag_sampler.plan_for(
            win, self._velocity, self._params.to_engine(self._dark).sigma
        )
        QThreadPool.globalInstance().start(
            _DragTask(
                self._provider,
                plan,
                self._params,
                self._dark,
                self._bake_lock,
                self._drag_signals,
            )
        )

    def _on_drag_field_ready(self, field: Optional[DragField]) -> None:
        """主线程槽：接收拖动场并反馈耗时给自适应控制器。

        Args:
            field: 新的拖动场；``None`` 表示本次烘焙失败（保留旧场继续用）。
        """
        if self._disposed:
            return
        self._drag_pending = False
        if field is None:
            return
        self._drag_sampler.note_bake(field.duration_ms)
        self._drag_field = field
        self._drag_pixmap = self._make_pixmap(field.image)
        self._widget.update()

    # -- worker 回调 ------------------------------------------------------

    def _on_bake_done(self, field) -> None:
        """主线程槽：应用后台结果并安排线程回收。"""
        self._watchdog.stop()
        self._refresh_retries = 0
        self._refresh_outcome = "ok"
        was_shown = self._has_shown
        self._apply_field(field)
        if self._active:
            self._start_fade_in(reset=not was_shown)
        else:
            self._hide_immediately()
        if self._worker_thread is not None:
            self._worker_thread.quit()

    def _on_bake_failed(self) -> None:
        """主线程槽：后台烘焙失败 → 记录结果，由回收逻辑重试 / 放弃。"""
        self._watchdog.stop()
        self._refresh_retries += 1
        self._refresh_outcome = "fail"
        if self._worker_thread is not None:
            self._worker_thread.quit()

    def _on_bake_timeout(self) -> None:
        """看门狗：烘焙超时（疑似卡死）→ 强制终止线程，交由回收逻辑重试 / 放弃。"""
        if self._worker_thread is None:
            return
        self._watchdog.stop()
        self._worker_thread.terminate()
        self._refresh_retries += 1
        self._refresh_outcome = "timeout"

    def _cleanup_worker(self) -> None:
        """回收后台 worker 与线程，并按结果决定退避重试或放弃。"""
        self._watchdog.stop()
        thread = self._worker_thread
        worker = self._worker
        self._worker_thread = None
        self._worker = None
        if thread is None:
            return

        outcome = self._refresh_outcome
        if outcome == "ok":
            pass
        elif self._refresh_retries <= BAKE_MAX_RETRIES:
            QTimer.singleShot(
                BAKE_RETRY_DELAY_MS * self._refresh_retries, self.refresh_async
            )
        else:
            _LOG.warning("Mica 后台烘焙多次失败，已放弃，回退纯色背景")

        if worker is not None:
            worker.deleteLater()
        thread.deleteLater()

        if self._rebuild_pending and self._refresh_retries <= BAKE_MAX_RETRIES:
            self._rebuild_pending = False
            QTimer.singleShot(0, lambda: self._maybe_rebake(force=True))

    def _apply_field(self, field) -> None:
        """保存烘焙产物并更新绘制。

        Args:
            field: :class:`~ui.mica.engine.BakedField`。
        """
        if field is None:
            return
        self._last_req = field.request
        self._pixmap = self._make_pixmap(field.image)
        self._has_shown = True
        self._widget.update()

    # ------------------------------------------------------------------
    # 淡入淡出
    # ------------------------------------------------------------------

    def _start_fade_in(self, reset: bool = False) -> None:
        """Mica 叠加层线性淡入（由当前透明度 → 1.0）。

        Args:
            reset: 为 ``True`` 时强制从完全隐藏（0）揭示。
        """
        if reset:
            self._fade_alpha = 0.0
        self._start_fade_to(1.0)

    def _start_fade_out(self) -> None:
        """Mica 叠加层线性淡出（由当前透明度 → 0.0）。"""
        self._start_fade_to(0.0)

    def _start_fade_to(self, target: float) -> None:
        """启动透明度线性渐变（target ∈ [0,1]）。"""
        target = max(0.0, min(1.0, target))
        self._paused = False
        self._fade_from = self._fade_alpha
        self._fade_to = target
        self._fade_clock.start()
        if not self._fade_timer.isActive():
            self._fade_timer.start()
        self._widget.update()

    def _on_fade_tick(self) -> None:
        """渐变逐帧推进。"""
        if not self._fade_clock.isValid():
            self._fade_alpha = self._fade_to
            self._fade_timer.stop()
            self._widget.update()
            return
        t = self._fade_clock.elapsed() / FADE_DURATION_MS
        if t >= 1.0:
            self._fade_alpha = self._fade_to
            self._fade_timer.stop()
            if self._fade_to == 0.0 and not self._active:
                self._paused = True
                self._settle_timer.stop()
        else:
            self._fade_alpha = self._fade_from + (self._fade_to - self._fade_from) * t
        self._widget.update()

    def _stop_fade(self) -> None:
        """立即结束渐变并复位为完整显示。"""
        self._fade_alpha = 1.0
        self._fade_to = 1.0
        if self._fade_timer.isActive():
            self._fade_timer.stop()

    def _hide_immediately(self) -> None:
        """失焦且 Mica 才就绪时：直接隐藏并停止绘制。"""
        self._paused = True
        self._fade_alpha = 0.0
        self._fade_to = 0.0

    # ------------------------------------------------------------------
    # 图像转换
    # ------------------------------------------------------------------

    @staticmethod
    def _make_pixmap(image: np.ndarray) -> QPixmap:
        """把 ``(H, W, 3)`` uint8 RGB 数组转为 QPixmap（拷贝脱离 numpy 缓冲）。

        Args:
            image: 烘焙产物色调场。

        Returns:
            QPixmap。
        """
        h, w = int(image.shape[0]), int(image.shape[1])
        qimg = QImage(image.tobytes(), w, h, w * 3, QImage.Format_RGB888)
        return QPixmap.fromImage(qimg.copy())

    @staticmethod
    def _make_noise_tile(size: int = NOISE_TILE_SIZE, seed: int = NOISE_SEED) -> QPixmap:
        """生成薄膜颗粒平铺贴图：黑白随机点，极低不透明度即可消除色带。

        Args:
            size: 贴图边长（像素）。
            seed: 固定随机种子，保证跨重绘稳定不闪烁。

        Returns:
            QPixmap（黑 / 白随机点，alpha 255；由绘制期 opacity 控制强度）。
        """
        rng = np.random.default_rng(seed)
        mask = rng.integers(0, 2, size=(size, size), dtype=np.uint8)
        arr = np.zeros((size, size, 4), dtype=np.uint8)
        arr[..., 0] = arr[..., 1] = arr[..., 2] = np.where(mask, 255, 0)
        arr[..., 3] = 255
        qimg = QImage(arr.tobytes(), size, size, size * 4, QImage.Format_RGBA8888)
        return QPixmap.fromImage(qimg.copy())


# ---------------------------------------------------------------------------
# 便捷控件
# ---------------------------------------------------------------------------


class MicaWidget(QWidget):
    """内置 Mica 背景的 ``QWidget`` 便捷子类。"""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        blur_radius: int = 200,
        surface_color: Union[str, QColor, None] = None,
        luminosity: float = 0.65,
        contrast: float = 1.5,
        saturation: float = 4.5,
        overlay_opacity: float = 0.7,
    ) -> None:
        super().__init__(parent)
        self._mica = MicaMaterial(
            self, blur_radius, surface_color, luminosity, contrast, saturation, overlay_opacity
        )

    @property
    def mica(self) -> MicaMaterial:
        """底层 :class:`MicaMaterial` 实例。"""
        return self._mica

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        self._mica.paint(painter, event)
        painter.end()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._mica.begin_interaction()

    def moveEvent(self, event: QMoveEvent) -> None:
        super().moveEvent(event)
        self._mica.begin_interaction()


class MicaWindow(QWidget):
    """内置 Mica 背景的窗口便捷子类（兼容旧 ``components.mica_window.MicaWindow``）。"""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        window_title: str = "",
        blur_radius: Optional[int] = None,
        surface_color: Optional[str] = None,
        luminosity: Optional[float] = None,
        contrast: Optional[float] = None,
        saturation: Optional[float] = None,
    ) -> None:
        super().__init__(parent)
        cfg = DEFAULT_MICA_CONFIG
        self._blur_radius = blur_radius if blur_radius is not None else cfg["blur_radius"]
        self._surface_color = (
            surface_color if surface_color is not None else cfg["surface_color"]
        )
        self._luminosity = luminosity if luminosity is not None else cfg["luminosity"]
        self._contrast = contrast if contrast is not None else cfg["contrast"]
        self._saturation = saturation if saturation is not None else cfg["saturation"]
        if window_title:
            self.setWindowTitle(window_title)
        self._mica = MicaMaterial(
            self,
            self._blur_radius,
            self._surface_color,
            self._luminosity,
            self._contrast,
            self._saturation,
            overlay_opacity=0.7,
        )

    @property
    def mica(self) -> MicaMaterial:
        """底层 :class:`MicaMaterial` 实例。"""
        return self._mica

    @property
    def content_layout(self):
        """当前布局（``self.layout()``）。"""
        return self.layout()

    def refresh_background(self) -> None:
        """刷新背景（兼容旧签名）。"""
        self._mica.refresh()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        self._mica.paint(painter, event)
        painter.end()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._mica.begin_interaction()

    def moveEvent(self, event: QMoveEvent) -> None:
        super().moveEvent(event)
        self._mica.begin_interaction()


#: 默认 Mica 配置（与旧 ``components.mica_window.DEFAULT_MICA_CONFIG`` 一致），
#: 供调用方做默认值来源。
DEFAULT_MICA_CONFIG: dict = {
    "blur_radius": 200,
    "surface_color": "#000000",
    "luminosity": 0.65,
    "contrast": 1.5,
    "saturation": 4.5,
}


__all__ = [
    "DEFAULT_MICA_CONFIG",
    "MicaMaterial",
    "MicaWidget",
    "MicaWindow",
]
