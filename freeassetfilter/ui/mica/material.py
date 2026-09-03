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
* 烘焙产物是**已经按窗口尺寸生成的色调场**（网格 ≤BAKE_LONG_MAX 长边），因此绘制时只需
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

逐监视器视口层（持久化）
------------------------
重烘焙天然是"按次计费"的（一次完整管线），无法逐帧承担。因此每个监视器
维护**一块**持久化的"视口层"：烘焙一次 —— 模糊 + 着色的壁纸，正好覆盖
窗口当前所在的整块监视器（见 :func:`ui.mica.drag.layer_region_for` /
:func:`ui.mica.drag.layer_grid`）。窗口在监视器内平移时，层不需要重烘焙，
逐帧只需从层里按窗口位置取一个子矩形 blit，零重计算（子矩形取样的绘制细化
见后续任务，本模块只负责把层烘焙到位并保存）。

主线程按 ``layer_key``（params、dark、source_signature、region、
layer_display_long）判断层是否过期：主题 / 参数 / 壁纸 / 监视器变化时重烘焙
一次；key 不变则跳过。worker 结果携带生成时的 ``layer_key``，主线程槽
若发现已不匹配当前 key，则丢弃该过期的烘焙结果（陈旧结果绝不提交）。
"""

from __future__ import annotations

import logging
import threading
import weakref
from typing import Optional, Tuple, Union

import numpy as np
from PySide6.QtCore import (
    QElapsedTimer,
    QEvent,
    QObject,
    QRect,
    QRectF,
    QThread,
    QTimer,
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
    BAKE_LONG_MAX,
    BAKE_MAX_RETRIES,
    BAKE_RETRY_DELAY_MS,
    BAKE_WATCHDOG_MS,
    DEACTIVATE_DEBOUNCE_MS,
    FADE_DURATION_MS,
    G1_DARK,
    G1_LIGHT,
    SETTLE_INTERVAL_MS,
    SIGMA_MAX,
    SIGMA_MIN,
)
from .drag import (
    LAYER_DISPLAY_LONG_MAX,
    ViewportLayer,
    layer_grid,
    layer_region_for,
    layer_to_source,
    layer_to_source_clamped,
)
from .engine import BakeRequest, render_display
from .gpu import gpu_bake
from .source import WallpaperProvider

_LOG = logging.getLogger(__name__)

#: 静态场渲染到显示分辨率时的长边上限（像素）。足够高以在 2K 屏上
#: 获得 1px 颗粒的抖动（色带被彻底打散），又给 4K 屏等极端尺寸封了内存顶。
DISPLAY_LONG_CAP: int = 2048

#: 混合预合成使用的默认纯色底（黑）。绘制端不再二次混合，见 render_display。
_DEFAULT_SURFACE_RGB: Tuple[int, int, int] = (0, 0, 0)


def _layer_display_long(region: Tuple[int, int, int, int]) -> int:
    """视口层的显示参考长边（像素）。

    层覆盖整块监视器，按层区域（= 监视器矩形）长边封顶
    :data:`~ui.mica.drag.LAYER_DISPLAY_LONG_MAX`，**不是**窗口长边。
    ``LAYER_DISPLAY_LONG_MAX`` 高于静态场的 :data:`DISPLAY_LONG_CAP`，因为
    层要在显示分辨率上保留 1px 颗粒的抖动，且逐帧只取其中窗口大小的子矩形。

    Args:
        region: ``(x, y, w, h)`` 层覆盖矩形（= 监视器矩形）。

    Returns:
        目标长边（像素），恒 ≥ 1。
    """
    region_long = max(int(region[2]), int(region[3]))
    return min(max(1, region_long), LAYER_DISPLAY_LONG_MAX)


def _params_with_sigma(params, dark: bool, sigma: float):
    """把引擎 σ 反解为等价 ``blur_radius``，保持层网格被钳制时物理模糊半径不变。

    层网格按监视器换算后可能被 :data:`~ui.mica.drag.LAYER_GRID_CAP` 钳制，
    实际密度低于常规烘焙。此时必须同步缩小 σ（网格像素），才能让色度低通的
    **物理半径** ``σ_physical = sigma_eff / density`` 不变 —— 否则视口层与常规
    烘焙观感不一致（松手出现糊→清晰跳变）。:func:`ui.mica.drag.layer_grid`
    返回的 ``sigma_eff`` 即为此准备。

    Args:
        params: 用户参数。
        dark: 是否深色模式（不影响换算，仅保留签名对称性）。
        sigma: 目标引擎 σ（网格像素）。

    Returns:
        以等价 ``blur_radius`` 重建的 :class:`~ui.mica.config.MicaParams`。
    """
    k = BAKE_LONG_MAX / 192.0
    base = float(sigma) / k
    blur = min(300.0, max(0.0, (base - SIGMA_MIN) / (SIGMA_MAX - SIGMA_MIN) * 300.0))
    if abs(blur - params.blur_radius) < 1e-6:
        return params
    return params.replace(blur_radius=blur)


def _pixmap_from_rgb(image: np.ndarray) -> QPixmap:
    """把 ``(H, W, 3)`` uint8 RGB 数组转为 QPixmap（拷贝脱离 numpy 缓冲）。

    这是**主线程唯一允许执行**的图像转换：只做一次格式转换 + 拷贝，实测
    1920×1080 约 2 ms。所有重活（双线性上采样、抖动量化）都已在 worker
    线程完成。

    Args:
        image: ``(H, W, 3)`` uint8 RGB 数组（连续内存）。

    Returns:
        QPixmap；输入非法时返回空 QPixmap。
    """
    if image is None or image.ndim != 3 or image.shape[2] != 3:
        return QPixmap()
    h, w = int(image.shape[0]), int(image.shape[1])
    if h <= 0 or w <= 0:
        return QPixmap()
    buf = np.ascontiguousarray(image, dtype=np.uint8)
    # QImage 的这个重载**不拷贝**缓冲，只持有裸指针，因此 bytes 对象必须在
    # QImage 整个使用周期内保持存活 —— 这里显式绑定到局部变量，直到转换完成。
    data = buf.tobytes()
    qimg = QImage(data, w, h, w * 3, QImage.Format_RGB888)
    pixmap = QPixmap.fromImage(qimg)
    del qimg, data
    return pixmap


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
    """后台层烘焙任务：在独立线程里烘一块覆盖当前监视器的"视口层"。

    只消费 numpy / COM（无 Qt 控件访问），结果以信号把
    ``(display_image, layer_info, layer_key, gen)`` 回传主线程：
    ``display_image`` 是已在**本线程**渲染好的 ``(H, W, 3)`` uint8 数组，
    主线程只做 QImage→QPixmap 转换。``layer_info`` 为
    :class:`~ui.mica.drag.ViewportLayer`（region / width / height / win_size）。

    层覆盖整块监视器，因此窗口在监视器内平移**不**触发重烘焙 —— 逐帧只需从层里
    按窗口位置取子矩形（见后续绘制细化任务）。本 worker 负责把层烘焙到位。
    """

    #: 参数为 ``(display_image, layer_info, layer_key, gen)``。
    done = Signal(object)
    failed = Signal()

    def __init__(
        self,
        provider: WallpaperProvider,
        window_rect: Tuple[int, int, int, int],
        params,  # MicaParams（不可变 dataclass，跨线程只读安全）
        dark: bool,
        monitor_rect: Tuple[int, int, int, int],
        layer_display_long: int,
        overlay: float,
        surface_rgb: Tuple[int, int, int],
        layer_key: Tuple[object, ...],
        generation: int,
    ) -> None:
        super().__init__()
        self._provider = provider
        self._window_rect = window_rect
        self._params = params
        self._dark = dark
        self._monitor_rect = monitor_rect
        self._layer_display_long = layer_display_long
        self._overlay = overlay
        self._surface_rgb = surface_rgb
        self._layer_key = layer_key
        self._generation = generation

    def run(self) -> None:
        """执行一次层烘焙并渲染到显示分辨率；异常按失败上报，绝不抛出到线程之外。

        步骤：由窗口矩形 + 监视器矩形算层区域 → 由监视器 + 窗口尺寸 + σ 算层网格
        （含 σ 守恒校正）→ 以层区域为 ``window_rect`` 烘焙（显式 ``grid_size``）
        → 渲染到显示分辨率（long = 层区域长边 ≤ ``LAYER_DISPLAY_LONG_MAX``）。
        """
        try:
            source = self._provider.acquire()
            if source.pixels.size == 0:
                self.failed.emit()
                return
            region = layer_region_for(self._window_rect, self._monitor_rect)
            sigma = self._params.to_engine(self._dark).sigma
            grid, sigma_eff = layer_grid(
                self._monitor_rect, self._window_rect[2], self._window_rect[3], sigma
            )
            # 网格被钳制时，σ 按密度比例回缩，保持物理模糊半径不变。
            bake_params = _params_with_sigma(self._params, self._dark, sigma_eff)
            request = BakeRequest(
                region, bake_params, self._dark, source.signature
            )
            field = gpu_bake(request, source, grid_size=grid)
            if field is None:
                self.failed.emit()
                return
            display = render_display(
                field, self._layer_display_long, self._overlay, self._surface_rgb
            )
            layer_info = ViewportLayer(
                region=region,
                width=int(display.shape[1]),
                height=int(display.shape[0]),
                win_size=(int(self._window_rect[2]), int(self._window_rect[3])),
            )
            self.done.emit((display, layer_info, self._layer_key, self._generation))
        except Exception as exc:  # pragma: no cover - 防御性兜底
            _LOG.debug("后台层烘焙异常：%s", exc)
            self.failed.emit()


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

        # 逐监视器持久化视口层（详见 ui.mica.drag）—— 代替旧的拖动场偏移采样。
        # 层烘焙一次覆盖整块监视器；窗口在监视器内平移无需重烘焙，只逐帧取样
        # （绘制期子矩形取样是后续任务，本模块只需把层烘焙到位并保存）。
        self._disposed = False
        #: 层几何：region（虚拟桌面覆盖范围）、width/height（层实际渲染像素）、win_size。
        self._layer: Optional[ViewportLayer] = None
        #: 层在显示分辨率上的 QPixmap（worker 已渲染好，主线程只做转换）。
        self._layer_pixmap: Optional[QPixmap] = None
        #: 当前层的有效性判据 ``(params, dark, source_signature, region, layer_display_long)``；
        #: 主题 / 参数 / 壁纸 / 监视器任一变化 ⇒ key 变化 ⇒ 重烘焙一层。
        self._layer_key: Optional[Tuple[object, ...]] = None
        #: 层代际单调递增计数器：每次请求新层烘焙时自增；主线程槽据此丢弃过期结果。
        self._layer_gen: int = 0
        #: 当前监视器的层显示参考长边（像素），随 refresh_async 更新。
        self._layer_display_long: int = 0

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

        # overlay_opacity 现在会影响烘焙产物（混合预合成在 worker 完成），
        # 因此滑块连拖用防抖合并，静置 250ms 后再重建。
        self._opacity_render_pending = False
        self._opacity_timer = QTimer(self._widget)
        self._opacity_timer.setSingleShot(True)
        self._opacity_timer.setInterval(250)
        self._opacity_timer.timeout.connect(self._on_opacity_settle)

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
        """在后台线程异步烘焙一块覆盖当前监视器的**视口层**（非阻塞）。

        有界重试：失败 / 超时累计超过 :data:`~ui.mica.config.BAKE_MAX_RETRIES` 后
        放弃并保留上一块有效层（或纯色兜底）。已有在途任务时忽略。

        请求前先在主线程算好监视器矩形、层区域、层显示长边与 ``layer_key``，
        并提交时自增 ``_layer_gen`` —— worker 结果携带同一 key/gen，主线程槽
        若发现 key/gen 已不匹配（一次更新的请求已提交）则丢弃过期结果。
        """
        if self._worker_thread is not None:
            return
        if self._refresh_retries > BAKE_MAX_RETRIES:
            return
        win = self._window_rect_tuple()
        monitor = self._monitor_rect_for(win)
        region = layer_region_for(win, monitor)
        layer_display_long = _layer_display_long(region)
        layer_key = self._layer_key_for(region, layer_display_long)
        self._layer_display_long = layer_display_long
        self._layer_key = layer_key
        self._layer_gen += 1
        generation = self._layer_gen
        self._worker = _BakeWorker(
            self._provider,
            win,
            self._params,
            self._dark,
            monitor,
            layer_display_long,
            self._overlay_opacity,
            self._surface_rgb(),
            layer_key,
            generation,
        )
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

        绘制优先取**视口层**（逐监视器持久化，覆盖当前监视器）的**窗口子矩形**：
        窗口在监视器内平移无需重烘焙，绘制期只从层里按窗口位置取一个子矩形做
        单次 blit（几何 100% 复用 :func:`ui.mica.drag.layer_to_source`）。

        * `layer_to_source` 返回整型子矩形（层与虚拟区域 1:1 且恰好落在整像素）
          ⇒ 真 1:1 blit —— ``SmoothPixmapTransform=False``（无重采样，最锐）。
        * 返回浮点型子矩形（层分辨率与虚拟区域不同 / 落在亚像素）⇒ 双线性平滑
          ``SmoothPixmapTransform=True``（亚像素取样，抗台阶）。
        * 返回 ``None``（窗口部分/全部落在层区域之外，或缩放中尺寸不匹配）
          ⇒ 回退到整窗静态场 ``_pixmap`` 整幅绘制；仍取不到则只画实色底（纯色 +
          淡入渐出）；**绝不**把整块层缩放铺满窗口。

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

        # 实色兜底层 + 线性淡入：透明度 = 淡入，实现 surface→Mica 过渡
        # （混合已在 worker 端预合成进 pixmap，绘制端只承担淡入淡出）。
        painter.fillRect(rect, self._surface_color)

        pixmap, src, smooth = self._layer_blit()
        if pixmap is None or pixmap.isNull():
            return

        painter.setRenderHint(QPainter.SmoothPixmapTransform, smooth)
        # 混合已在 worker 端预合成进 pixmap（render_display 消费 overlay/surface），
        # 绘制端**全不透明**，避免第二次 8-bit 量化（banding 根因）。
        painter.setOpacity(self._fade_alpha)
        if src is None:
            # 回退到整窗静态场（已是窗口尺寸，1:1 平铺）。
            painter.drawPixmap(rect, pixmap)
        elif smooth:
            # 浮点源子矩形：亚像素双线性取样。
            painter.drawPixmap(QRectF(rect), pixmap, QRectF(*src))
        else:
            # 整型源子矩形：真 1:1 blit（无重采样）。
            painter.drawPixmap(QRect(rect), pixmap, QRect(*src))
        painter.setOpacity(1.0)

    def paint_gpu(self, painter: QPainter) -> None:
        """在 GPU 画笔画笔（``QOpenGLWidget``）上绘制 Mica 背景。

        与 :meth:`paint` 策略一致：优先取层内窗口子矩形（blit），回退整窗静态场，
        再退实色底。

        Args:
            painter: 来自 ``paintGL`` 的画笔画笔。
        """
        rect = self._widget.rect()
        if self._paused:
            painter.fillRect(rect, self._surface_color)
            return
        painter.fillRect(rect, self._surface_color)
        pixmap, src, smooth = self._layer_blit()
        if pixmap is None or pixmap.isNull():
            return
        # 混合已在 worker 端预合成进 pixmap，绘制端全不透明（见 paint）。
        painter.setRenderHint(QPainter.SmoothPixmapTransform, smooth)
        painter.setOpacity(self._fade_alpha)
        if src is None:
            painter.drawPixmap(rect, pixmap)
        elif smooth:
            painter.drawPixmap(QRectF(rect), pixmap, QRectF(*src))
        else:
            painter.drawPixmap(QRect(rect), pixmap, QRect(*src))
        painter.setOpacity(1.0)

    def _layer_blit(
        self,
    ) -> Tuple[Optional[QPixmap], Optional[tuple], bool]:
        """绘制取材：返回应绘制的 pixmap 与可选的窗口子矩形。

        返回 ``(pixmap, src, smooth)``：

        * 视口层就绪（``_layer`` + ``_layer_pixmap`` 均存在且非空）时，**始终**返回
          层本身与一个非 ``None`` 的子矩形 —— 用 :func:`ui.mica.drag.layer_to_source_clamped`
          按窗口当前位置与**当前尺寸**映射并钳制（resize / 越界都取样，Mica 永不消失）：
          整型 ⇒ 真 1:1（``smooth=False``）；浮点 ⇒ 亚像素平滑（``smooth=True``）。
        * 仅当层**确实尚未就绪**（首帧之前从未烘焙过）时才回退到整窗静态场
          ``_pixmap``（``src=None``，``smooth=True``）；仍无则 ``(None, None, True)``。

        真正的区域 / 密度修正由 :meth:`_needs_layer_rebake` 在窗口稳定后重烘焙一层
        完成；本方法只负责在层就绪后永远取样，杜绝"Mica 消失（只剩纯色）"。

        CPU（``paint``）与 GPU（``paint_gpu``）两条路径共用此方法，确保子矩形
        取材行为一致。

        Returns:
            ``(pixmap, src, smooth)``：``src`` 为 ``None`` 表示整幅绘制静态场。
        """
        if self._layer is not None and self._layer_pixmap is not None and not self._layer_pixmap.isNull():
            win = self._window_rect_tuple()
            src = layer_to_source_clamped(self._layer, win)
            smooth = isinstance(src[0], float)
            return (self._layer_pixmap, (int(src[0]), int(src[1]), int(src[2]), int(src[3])) if not smooth else src, smooth)
        pixmap = self._pixmap
        if pixmap is None or pixmap.isNull():
            return (None, None, True)
        return (pixmap, None, True)

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
        # 仅当主题导致 layer_key 变化（主要是 dark 翻转）才重烘焙一层；key 未变
        # 则跳过 —— 浅色切换同深浅 / 仅改 luminosity 时零重烘焙。
        self._maybe_rebake(force=False)
        self._widget.update()

    def set_effect_parameters(
        self,
        blur_radius: Optional[int] = None,
        overlay_opacity: Optional[float] = None,
        saturation: Optional[float] = None,
        contrast: Optional[float] = None,
    ) -> None:
        """更新用户可调的 Mica 参数。

        * ``overlay_opacity``：现在影响烘焙产物（混合预合成在 worker 完成）
          → 防抖 250ms 后触发重建（连续拖动滑块合并为一次）。
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
            # 参数（模糊 / 饱和度 / 对比度）变化 → 层 key 变化 ⇒ 必须重烘焙一次。
            # 走 _request_rebuild（内部 _maybe_rebake(force=True)），保证真正的参数
            # 变更必然触发重建；测试与外部契约均依赖它。
            self._request_rebuild()
        elif opacity_changed:
            # overlay 不在 layer_key 内，但影响 render_display 产物 → 防抖后强制重建。
            self._opacity_render_pending = True
            self._opacity_timer.start()

    def begin_interaction(self) -> None:
        """标记窗口拖拽 / 缩放开始或持续。

        视口层是**逐监视器持久化**的 —— 窗口在监视器内平移无需重烘焙，逐帧从层里
        按位置取样即可。这里**只**在真正需要时才触发**一次**层重烘焙：

        * 窗口离开当前层区域（= 跨监视器 / 越界到另一块监视器）；
        * 监视器变化（区域变化）；
        * 密度目标变化（层显示长边或窗口尺寸变化 —— 层网格密度随之改变）；
        * 主题 / 参数 / 壁纸变化（由 ``layer_key`` 判据覆盖）。

        触发时调用 :meth:`_maybe_rebake`（force），它会经 :meth:`refresh_async`
        自增 ``_layer_gen`` 并提交新请求；若已有烘焙在途则置 ``_rebuild_pending``
        交由回收逻辑续接，**绝不**清除旧层 —— 旧层保持可见直到新层就绪
        （陈旧性守卫保证过期结果不被提交）。

        其余帧仅重绘（``self._widget.update()``），零重计算。
        """
        self._interacting = True
        win = self._window_rect_tuple()
        monitor = self._monitor_rect_for(win)
        region = layer_region_for(win, monitor)
        layer_display_long = _layer_display_long(region)
        if self._needs_layer_rebake(win, monitor, region, layer_display_long):
            self._maybe_rebake(force=True)
        self._settle_timer.start()
        self._widget.update()

    def _needs_layer_rebake(
        self,
        window_rect: Tuple[int, int, int, int],
        monitor_rect: Tuple[int, int, int, int],
        region: Tuple[int, int, int, int],
        layer_display_long: int,
    ) -> bool:
        """判断当前窗口条件下的层是否需要重烘焙。

        判据（任一成立即需）：

        * 层尚未烘焙（``_layer`` 为 ``None``）；
        * 层区域 != 当前监视器区域（窗口离开层区域 / 跨监视器）；
        * 层显示长边 != 当前值，或层烘焙时的窗口尺寸 != 当前尺寸
          （密度目标变化 —— 层网格密度随监视器 / 窗口尺寸变化）；
        * ``layer_key`` 变化（主题 / 参数 / 壁纸变化）。

        Args:
            window_rect: ``(x, y, w, h)`` 当前窗口矩形。
            monitor_rect: ``(x, y, w, h)`` 当前监视器矩形。
            region: ``(x, y, w, h)`` 层区域（= 监视器矩形）。
            layer_display_long: 当前层显示长边。

        Returns:
            ``True`` 表示需要重烘焙一层。
        """
        layer = self._layer
        if layer is None:
            return True
        if tuple(int(v) for v in layer.region) != tuple(int(v) for v in region):
            return True
        if int(layer_display_long) != int(self._layer_display_long):
            return True
        if layer.win_size != (int(window_rect[2]), int(window_rect[3])):
            return True
        key = self._layer_key_for(region, layer_display_long)
        return key != self._layer_key

    def invalidate_cache(self) -> None:
        """使缓存失效：下次绘制前强制重烘焙。"""
        self._last_req = None
        self._pixmap = None
        self._maybe_rebake(force=True)

    def dispose(self) -> None:
        """释放资源：阻止重试、移除焦点过滤器、回收在途线程。窗口关闭时调用。"""
        self._disposed = True
        self._layer = None
        self._layer_pixmap = None
        self._pixmap = None
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
        self._opacity_timer.stop()
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
            hwnd = int(self._widget.winId())
        except (TypeError, RuntimeError, ValueError):
            hwnd = 0
        if winapi.IS_WINDOWS and hwnd:
            r = winapi.window_rect(hwnd)
            if r[2] > 0 and r[3] > 0:
                return r
        w = self._widget.window()
        geo = w.geometry() if w is not None else self._widget.geometry()
        return (geo.x(), geo.y(), geo.width(), geo.height())

    def _surface_rgb(self) -> Tuple[int, int, int]:
        """当前实色底的 ``(r, g, b)``，供 worker 混合预合成使用。

        Returns:
            ``(r, g, b)`` 三元组。
        """
        c = self._surface_color
        return (c.red(), c.green(), c.blue())

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
        """按需触发热重烘焙（视口层）：仅当 ``layer_key`` 确有变化（参数 / 主题 /
        壁纸 / 监视器区域 / 层显示长边）时才重烘焙一层。

        Args:
            force: 强制重烘焙（忽略 key 判据）。
        """
        win = self._window_rect_tuple()
        monitor = self._monitor_rect_for(win)
        region = layer_region_for(win, monitor)
        layer_display_long = _layer_display_long(region)
        key = self._layer_key_for(region, layer_display_long)
        if not force and key == self._layer_key:
            # key 未变化：层仍覆盖当前监视器，无需重烘焙（窗口在监视器内平移 /
            # 主题参数未变，no-op）。
            return
        if self._worker_thread is not None:
            # 在途烘焙：本次变化（主题 / 参数 / 壁纸 / 监视器）已使在途结果过期。
            # 置 ``_layer_key`` 失效，令旧 key 的在途结果被陈旧性守卫丢弃（绝不
            # 提交一份旧主题/旧区域的混合层），并交由回收逻辑按最新 key 续接请求。
            self._layer_key = None
            self._rebuild_pending = True
            return
        self.refresh_async()

    def _request_rebuild(self) -> None:
        """使相对上一次请求的判据失效并触发热重烘焙（视口层）。"""
        self._layer_key = None
        self._last_req = None
        self._maybe_rebake(force=True)

    def _on_settle(self) -> None:
        """交互停止：按当前条件决定是否重烘焙视口层。

        视口层逐监视器持久化 —— 窗口在监视器内平移不触发重烘焙；跨监视器 /
        参数 / 主题 / 壁纸变化时，``_maybe_rebake`` 会按新 ``layer_key`` 重烘焙一层。
        """
        self._interacting = False
        self._maybe_rebake(force=False)

    def _on_opacity_settle(self) -> None:
        """overlay_opacity 防抖静置：结束连续改动，触发烘焙重建。"""
        self._opacity_render_pending = False
        self._request_rebuild()

    # ------------------------------------------------------------------
    # 视口层调度辅助
    # ------------------------------------------------------------------

    def _monitor_rect_for(
        self, window_rect: Tuple[int, int, int, int]
    ) -> Tuple[int, int, int, int]:
        """返回包含窗口的监视器矩形（虚拟桌面物理像素）。

        取窗口中心点所在的监视器；找不到（罕见）回退到第一块（主）监视器。
        监视器探测失败（无源 / 非 Windows）时回退到窗口矩形自身 —— 此时层
        退化为覆盖窗口的静态场，仍能正常烘焙与绘制。

        Args:
            window_rect: ``(x, y, w, h)`` 窗口矩形（虚拟桌面物理像素）。

        Returns:
            监视器矩形 ``(x, y, w, h)``。
        """
        try:
            info = self._provider.probe()
            monitors = info.monitors
            if monitors:
                cx = float(window_rect[0]) + float(window_rect[2]) / 2.0
                cy = float(window_rect[1]) + float(window_rect[3]) / 2.0
                for mon in monitors:
                    mx, my, mw, mh = (int(v) for v in mon.rect)
                    if mx <= cx < mx + mw and my <= cy < my + mh:
                        return (mx, my, mw, mh)
                first = monitors[0]
                return (
                    int(first.rect[0]),
                    int(first.rect[1]),
                    int(first.rect[2]),
                    int(first.rect[3]),
                )
        except Exception as exc:  # pragma: no cover - 防御性兜底
            _LOG.debug("监视器探测失败，回退到窗口矩形作为层区域：%s", exc)
        return window_rect

    def _layer_key_for(
        self, region: Tuple[int, int, int, int], layer_display_long: int
    ) -> Tuple[object, ...]:
        """当前视口层的有效性判据。

        Args:
            region: ``(x, y, w, h)`` 层区域（= 监视器矩形）。
            layer_display_long: 层显示参考长边。

        Returns:
            ``(params, dark, source_signature, region, layer_display_long)``；
            任一成分变化即视为需重烘焙。
        """
        try:
            signature = self._provider.probe().signature()
        except Exception:  # pragma: no cover - 防御性兜底
            signature = ""
        return (self._params, self._dark, signature, region, int(layer_display_long))

    # -- worker 回调 ------------------------------------------------------

    def _on_bake_done(self, payload: object) -> None:
        """主线程槽：应用后台层烘焙结果并安排线程回收。

        **key 陈旧性守卫** —— 一次性更新请求可能被主题 / 参数 / 壁纸 / 监视器
        变化取代；若 worker 携带的 ``layer_key`` / ``gen`` 已不匹配当前值，该结果
        视为过期并**丢弃**（陈旧结果绝不提交），避免显示一份与当前条件不符的层。

        Args:
            payload: ``(display, layer_info, layer_key, gen)``；
                ``display`` 已在 worker 线程渲染成显示分辨率 uint8 数组。
        """
        self._watchdog.stop()
        self._refresh_retries = 0
        self._refresh_outcome = "ok"
        display, layer_info, layer_key, gen = payload
        if layer_key != self._layer_key or gen != self._layer_gen:
            # 过期结果：来自一次已被更新的请求（主题/参数/壁纸/监视器变化后新请求已提交）。
            _LOG.debug("丢弃过期的视口层烘焙结果（key/gen 不匹配）")
            if self._worker_thread is not None:
                self._worker_thread.quit()
            return
        was_shown = self._has_shown
        self._layer = layer_info
        self._layer_pixmap = _pixmap_from_rgb(display)
        self._layer_key = layer_key
        self._has_shown = True
        self._widget.update()
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
            # 续接被推迟的重烘焙：**按 key 判据**（force=False）—— 若延迟期间
            # 条件已解析为与当前 key 一致，则不再多烘一层（保证"精确一次"）。
            QTimer.singleShot(0, lambda: self._maybe_rebake(force=False))

    def _apply_field(self, field, display: Optional[np.ndarray] = None) -> None:
        """保存烘焙产物并更新绘制。

        Args:
            field: :class:`~ui.mica.engine.BakedField`。
            display: worker 线程已渲染好的显示分辨率图像；``None`` 时本方法
                现场渲染（仅同步降级路径会走到，主线程一次性开销）。
        """
        if field is None:
            return
        self._last_req = field.request
        if display is None:
            display = render_display(
                field, self._display_long(field), self._overlay_opacity, self._surface_rgb()
            )
        self._pixmap = _pixmap_from_rgb(display)
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
    def _display_long(field) -> int:
        """静态场渲染长边：与窗口长边 1:1（封顶 :data:`DISPLAY_LONG_CAP`）。

        Args:
            field: 含 ``request`` 的烘焙产物（``BakedField``）。

        Returns:
            目标长边（像素）。
        """
        win_w, win_h = field.request.size
        return max(1, min(max(win_w, win_h), DISPLAY_LONG_CAP))

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
