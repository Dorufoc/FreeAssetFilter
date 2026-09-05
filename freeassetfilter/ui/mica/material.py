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
* 坐标空间统一为 Win32 物理像素：顶层客户区取自 ``winapi.client_rect``，再按控件
  相对顶层客户区的逻辑几何换算；结果与壁纸源画布（``winapi.virtual_screen_rect``）同坐标系，
  HiDPI 下也严格对齐。

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

拖动期快速路径（为什么拖动中“冻结”合成）
-----------------------------------------
系统 move 期间 DWM 只平移窗口位图，客户区**零重绘** —— 这是任何原生窗口
拖动都流畅的根本原因。窗口是单面不透明光栅表面，无法让“内容”与“背景”
相对位移：只要逐帧重绘背景（哪怕只 blit 一块子矩形），成本就随窗口面积
增长（窗口越大帧率越低），数学上追不上 DWM。

因此默认策略是：**拖动中完全不打扰窗口**（:meth:`MicaMaterial.begin_interaction`
对“层就绪 + 尺寸不变”的纯移动事件只做 O(1) 记账，不重绘 / 不探测 / 不重烘），
代价是拖动期间背景短暂“贴窗”（画面随窗口整体平移）；松手后由
:meth:`MicaMaterial._on_settle` 单次重绘把背景重同步到按**最终位置**取样的
正确壁纸裁剪 —— 同监视器用 ~120ms 交叉淡化（旧裁剪 → 新裁剪）掩盖位移，
跨监视器则先画纯色底、等新层后台烘焙完成后淡入，绝不显示旧监视器的钳制伪色。
与 :class:`~freeassetfilter.ui.components.custom_background.CustomImageBackgroundWidget`
（图片层对 move 事件 no-op）共用同一套“拖动不重绘”先例。

设环境变量 ``FAF_MICA_DRAG_LIVE=1`` 恢复旧的逐帧行为，``FAF_MICA_SETTLE_FADE_MS``
可调淡化时长（``0`` 关闭）。拖动路径有专项回归门禁（``tests/unit/ui/mica/
test_drag_perf.py``），禁止在该路径重新引入逐事件重绘 / COM 探测。
"""

from __future__ import annotations

import logging
import os
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
from .compositor import (
    PRESENT_DEFER,
    PRESENT_NOW,
    PRESENT_SKIP,
    ViewportCompositor,
)
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

#: 静态场（无层兜底路径）渲染到显示分辨率时的长边上限（像素）。与视口层
#: 同理，必须以 1:1 窗口分辨率渲染：抖动图案锚定屏幕坐标、被 1:1 blit 原样
#: 保留，双线性重采样才不会把抖动抹平、在渐变区重现色彩断层（banding）。8192
#: 覆盖至单 4K / 单 5K / 双 4K 窗口的严格 1:1；静态场仅在层未就绪的启动 / 降级
#: 期出现，渲染一次的成本可被接受。
DISPLAY_LONG_CAP: int = 8192

#: 混合预合成使用的默认纯色底（黑）。绘制端不再二次混合，见 render_display。
_DEFAULT_SURFACE_RGB: Tuple[int, int, int] = (0, 0, 0)

#: 原生 DWM 云母模式下铺在客户区的纯黑（扩展帧约定：被涂黑的区域由 DWM 以
#: 系统背景即原生云母代替呈现）。与主题无关恒为纯黑 —— 深浅色观感由
#: ``DWMWA_USE_IMMERSIVE_DARK_MODE`` 控制，见 :func:`ui.mica.winapi.dwm_use_dark_mode`。
_NATIVE_BACKDROP_COLOR = QColor(0, 0, 0)

# ---------------------------------------------------------------------------
# 拖动期快速路径
# ---------------------------------------------------------------------------
#: 拖动期默认策略：**逐帧不重绘**（窗口画面交给 DWM 平移，客户区零合成负载，
#: 帧成本与窗口尺寸无关）。与 ``custom_background.CustomImageBackgroundWidget``
#: 对 move 事件 no-op 的先例一致 —— 静止观感零变化，代价是拖动中背景“贴窗”，
#: 松手后由 settle 交叉淡化（见 :data:`_SETTLE_FADE_MS`）重同步到正确壁纸裁剪。
#: 设 ``FAF_MICA_DRAG_LIVE=1`` 可恢复旧的“拖动中逐帧重绘”行为（对照回归用）。
DRAG_LIVE_ENV: str = "FAF_MICA_DRAG_LIVE"

#: 松手时旧裁剪 → 新裁剪的交叉淡化时长（毫秒）。掩盖“贴窗 → 贴壁纸”的一次
#: 背景重同步。设 ``FAF_MICA_SETTLE_FADE_MS=0`` 可关闭（退化为瞬间重绘）。
SETTLE_FADE_ENV: str = "FAF_MICA_SETTLE_FADE_MS"
#: 默认淡化时长（毫秒）。
_SETTLE_FADE_DEFAULT_MS: int = 120
#: settle 淡化逐帧节拍（毫秒）。
_FADE_TICK_MS: int = 16


def _settle_fade_ms_from_env() -> int:
    """读取 ``FAF_MICA_SETTLE_FADE_MS``（非法值回退默认）。"""
    raw = os.environ.get(SETTLE_FADE_ENV, "").strip()
    if not raw:
        return _SETTLE_FADE_DEFAULT_MS
    try:
        return max(0, int(float(raw)))
    except ValueError:
        return _SETTLE_FADE_DEFAULT_MS


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
    """后台层烘焙任务：在独立线程里烘一块覆盖整块虚拟桌面的"视口层"。

    只消费 numpy / COM（无 Qt 控件访问），结果以信号把
    ``(display_image, layer_info, layer_key, gen)`` 回传主线程：
    ``display_image`` 是已在**本线程**渲染好的 ``(H, W, 3)`` uint8 数组，
    主线程只做 QImage→QPixmap 转换。``layer_info`` 为
    :class:`~ui.mica.drag.ViewportLayer`（region / width / height / win_size）。

    层覆盖整块虚拟桌面（所有监视器拼接），因此窗口在桌面内任意平移**不**触发
    重烘焙 —— 逐帧只需从层里按窗口位置取子矩形（见 :meth:`MicaMaterial.paint`）。
    本 worker 负责把层烘焙到位（1:1 屏幕分辨率，抖动锚定绝对屏幕坐标，杜绝渐变
    区色彩断层）。
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
        screen_rect: Tuple[int, int, int, int],
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
        self._screen_rect = screen_rect
        self._layer_display_long = layer_display_long
        self._overlay = overlay
        self._surface_rgb = surface_rgb
        self._layer_key = layer_key
        self._generation = generation

    def run(self) -> None:
        """执行一次层烘焙并渲染到显示分辨率；异常按失败上报，绝不抛出到线程之外。

        步骤：以整块虚拟桌面矩形为层区域 → 由虚拟矩形 + 窗口尺寸 + σ 算层网格
        （含 σ 守恒校正）→ 以层区域为 ``window_rect`` 烘焙（显式 ``grid_size``）
        → 渲染到显示分辨率（long = 层区域长边 ≤ ``LAYER_DISPLAY_LONG_MAX``，
        常见配置下 == 层区域长边 ⇒ 1:1 屏幕分辨率，抖动不被重采样抹平）。
        """
        try:
            source = self._provider.acquire()
            if source.pixels.size == 0:
                self.failed.emit()
                return
            region = layer_region_for(self._window_rect, self._screen_rect)
            sigma = self._params.to_engine(self._dark).sigma
            grid, sigma_eff = layer_grid(
                self._screen_rect, self._window_rect[2], self._window_rect[3], sigma
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
                field,
                self._layer_display_long,
                self._overlay,
                self._surface_rgb,
                origin=(int(region[0]), int(region[1])),
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

        # 拖动期快速路径（详见模块头与 begin_interaction）：
        # - 拖动会话期间窗口内容（含背景）由 DWM 平移，客户区零重绘；
        # - 最近一次“真正把层画上去”时的窗口矩形 —— 它就是拖动开始时屏幕上
        #   所见背景对应的采样位置（拖动中不重绘，位置不再前进）；
        # - 跨监视器松手后、新层烘焙完成前只画纯色底（不显示旧监视器伪色）。
        self._drag_live = os.environ.get(DRAG_LIVE_ENV, "").strip().lower() == "1"
        self._last_painted_win: Optional[Tuple[int, int, int, int]] = None
        self._hide_until_new_layer = False
        # settle 淡化状态：旧裁剪 → 新裁剪，见 _start_settle_fade。
        self._settle_fade_ms = _settle_fade_ms_from_env()
        self._settle_fade_old_src: Optional[Tuple[float, float, float, float]] = None
        self._settle_fade_ticks = 0
        self._settle_fade_timer = QTimer(self._widget)
        self._settle_fade_timer.setInterval(_FADE_TICK_MS)
        self._settle_fade_timer.timeout.connect(self._on_settle_fade_tick)

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
        #: 自研合成器：整块虚拟桌面层 + 窗口视口取样 + 自适应呈现调度。
        #: 层的像素与几何全部由它持有（见 :mod:`ui.mica.compositor`）；
        #: ``_layer`` / ``_layer_pixmap`` 是它的只读视图（property 委托），
        #: 保持旧字段名的读写契约。
        self._compositor = ViewportCompositor()
        #: 实验性「原生 DWM 云母」模式：自研层停用，绘制端只铺纯黑让 DWM 呈现
        #: 系统背景（见 :meth:`set_native_backdrop`）。
        self._native_backdrop = False
        #: 层有效性判据 ``(params, dark, source_signature, region, layer_display_long)``；
        #: 主题 / 参数 / 壁纸 / 监视器任一变化 ⇒ key 变化 ⇒ 重烘焙一层。
        self._layer_key = None
        #: 层代际单调递增计数器：每次请求新层烘焙时自增；主线程槽据此丢弃过期结果。
        self._layer_gen = 0
        #: 当前监视器的层显示参考长边（像素），随 refresh_async 更新。
        self._layer_display_long = 0
        #: 交互期被节流推迟的呈现（补一次，保证最终位置一定被刷新）。
        self._defer_timer = QTimer(self._widget)
        self._defer_timer.setSingleShot(True)
        self._defer_timer.timeout.connect(self._on_defer_present)
        #: 绘制耗时采样（供合成器自适应节流；只测 blit，不含事件派发）。
        self._paint_clock = QElapsedTimer()

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
    # 层状态视图（property 委托到合成器，保持旧字段读写契约）
    # ------------------------------------------------------------------

    @property
    def _layer(self) -> Optional[ViewportLayer]:
        """当前视口层几何（由合成器持有）。"""
        return self._compositor.layer

    @_layer.setter
    def _layer(self, value: Optional[ViewportLayer]) -> None:
        self._compositor.set_geometry(value)

    @property
    def _layer_pixmap(self) -> Optional[QPixmap]:
        """当前视口层像素（由合成器持有）。"""
        return self._compositor.pixmap

    @_layer_pixmap.setter
    def _layer_pixmap(self, value: Optional[QPixmap]) -> None:
        self._compositor.set_pixels(value)

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """同步（主线程）重载壁纸并烘焙。用作初始化与后台失败时的降级路径。

        若已有后台烘焙在途则直接返回（由 worker 交付结果），避免重复烘焙。
        """
        if self._native_backdrop or self._disposed:
            # 原生 DWM 云母模式下自研层停用：不烘焙、不改状态。
            return
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
        if self._native_backdrop or self._disposed:
            # 原生 DWM 云母模式下自研层停用：绝不起后台线程（零渲染开销）。
            return
        if self._worker_thread is not None:
            return
        if self._refresh_retries > BAKE_MAX_RETRIES:
            return
        win = self._window_rect_tuple()
        region = self._virtual_rect()
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
            region,
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
        if self._native_backdrop:
            # 原生 DWM 云母：客户区铺纯黑（扩展帧约定 —— 帧扩展区域内被涂成
            # 纯黑的部分由 DWM 以系统背景即原生云母代替呈现）。自研渲染全免。
            painter.fillRect(rect, _NATIVE_BACKDROP_COLOR)
            return
        if self._paused:
            painter.fillRect(rect, self._surface_color)
            return

        # 整块虚拟桌面层覆盖全局、与窗口尺寸无关：背景在交互期已由实时 blit
        # 严格跟随光标，这里始终直接绘制层子矩形（无跨屏等待 / 无松手淡化）。
        self._draw_layer(painter, rect)

    def paint_gpu(self, painter: QPainter) -> None:
        """在 GPU 画笔画笔（``QOpenGLWidget``）上绘制 Mica 背景。

        与 :meth:`paint` 策略一致（整块虚拟桌面层路径），只是画笔来自 ``paintGL``。
        """
        rect = self._widget.rect()
        if self._native_backdrop:
            painter.fillRect(rect, _NATIVE_BACKDROP_COLOR)
            return
        if self._paused:
            painter.fillRect(rect, self._surface_color)
            return
        self._draw_layer(painter, rect)

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

    def _draw_layer(self, painter: QPainter, rect) -> None:
        """常规路径：把层（或回退静态场）按窗口当前位置取样绘制到 ``rect``。

        绘制结果**全不透明**（混合已在 worker 端预合成进 pixmap，见
        :func:`ui.mica.engine.render_display`），避免第二次 8-bit 量化
        （banding 根因）。成功后记录 :attr:`_last_painted_win` —— 它代表
        "屏幕上可见背景的采样位置"，拖动快速路径松手时据此做 settle 淡化。

        性能要点：

        * **条件化实色底**：层取样可铺满且完全不透明（``fade_alpha>=0.999``）
          时跳过整窗 ``fillRect``（稳态省一次全窗内存写，绘制帧成本近乎减半）；
          仅淡入期 / 静态场兜底 / 无任何产物时才先铺（或只铺）实色底。
        * **呈现记账**：本次 blit 的实测耗时喂给合成器的成本 EMA（自适应呈现
          间隔的输入），呈现锚点同步更新（后续 ``advise`` 的跳过 / 节流依据）。

        CPU（:meth:`paint`）与 GPU（:meth:`paint_gpu`）共用本方法。

        Args:
            painter: 画笔。
            rect: 目标矩形（= 控件 rect）。
        """
        pixmap, src, smooth = self._layer_blit()
        if pixmap is None or pixmap.isNull():
            # 无任何产物（层与静态场均缺失）：只画实色兜底层。
            painter.fillRect(rect, self._surface_color)
            return

        # 不透明且层取样可用 ⇒ 绘制必然铺满 ⇒ 省掉整窗实色填充；
        # 淡入期 / 静态场兜底需要底色参与 surface→Mica 过渡（先铺后绘）。
        if src is None or self._fade_alpha < 0.999:
            painter.fillRect(rect, self._surface_color)

        self._paint_clock.start()
        painter.setRenderHint(QPainter.SmoothPixmapTransform, smooth)
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
        cost_ms = max(0.0, self._paint_clock.nsecsElapsed() / 1e6)

        if self._layer is not None:
            win = self._window_rect_tuple()
            self._last_painted_win = win
            if src is not None and self._compositor.ready:
                # 记录一次真实呈现：锚点（后续 advise 的 SKIP/DEFER 判据）+
                # 绘制成本 EMA（自适应目标间隔，见 ViewportCompositor.interval_ms）。
                self._compositor.note_presented(win, cost_ms)

    def _settle_fade_active(self) -> bool:
        """settle 淡化是否在途（旧裁剪 → 新裁剪）。"""
        return self._settle_fade_old_src is not None

    def _draw_settle_fade(self, painter: QPainter, rect) -> None:
        """绘制松手重同步的交叉淡化帧：旧裁剪打底，新裁剪按进度叠入。

        旧裁剪 = 拖动期间屏幕上实际所见（= 拖动开始前最后绘制帧的取样位置，
        DWM 平移整窗位图时它保持不变）；新裁剪 = 按**当前最终位置**取样。
        结果是 ``(1-t)·old + t·new`` 的标准交叉淡化，掩盖“贴窗 → 贴壁纸”的
        一次背景位移。淡化期无重烘焙（见 :meth:`_on_settle`），层恒定。

        Args:
            painter: 画笔（已叠好实色底）。
            rect: 目标矩形（= 控件 rect）。
        """
        layer = self._layer
        pixmap = self._layer_pixmap
        old_src = self._settle_fade_old_src
        if layer is None or pixmap is None or pixmap.isNull() or old_src is None:
            # 状态异常兜底：直接画当前裁剪（幂等）。
            self._draw_layer(painter, rect)
            return
        span = max(1, int(self._settle_fade_ms))
        t = min(1.0, float(self._settle_fade_ticks) * _FADE_TICK_MS / float(span))
        new_src = layer_to_source_clamped(layer, self._window_rect_tuple())

        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        # 旧裁剪打底（不透明 —— 与拖动期间所见帧一致）。
        painter.setOpacity(self._fade_alpha)
        painter.drawPixmap(QRectF(rect), pixmap, QRectF(*old_src))
        # 新裁剪按进度叠入；t→1 由 _on_settle_fade_tick 停机后的常规帧收尾。
        painter.setOpacity(self._fade_alpha * max(0.0, min(1.0, t)))
        painter.drawPixmap(QRectF(rect), pixmap, QRectF(*new_src))
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

        整块虚拟桌面层 + 实时 blit 快速路径
        ---------------------------------
        视口层覆盖整块虚拟桌面、与窗口尺寸无关，因此拖动（含跨监视器）与缩放
        期间**无需任何重烘焙 / COM 探测**。每个 move / resize 事件只需做 O(1)
        的 ``widget.update()`` —— 由 Qt 在随后的 ``paintEvent`` 里合成一次子矩形
        blit（GPU 纹理拷贝，成本与窗口面积、帧率都无关）：窗口作为"窗户"从已
        烘焙好的层里按当前屏幕位置取子矩形绘制，背景严格跟随光标，不再"贴窗"、
        不再有松手跳变。这正是抹掉色彩断层的前提——层以 1:1 屏幕分辨率渲染，
        抖动图案锚定绝对屏幕坐标，blit 时原样保留。

        层未就绪（启动首帧 / 降级）时才走旧路径：确保异步烘焙在途并重绘兜底
        静态场，不阻塞交互。
        """
        self._interacting = True
        if self._native_backdrop:
            # 原生 DWM 云母：窗口移动/缩放由 DWM 自行重绘系统背景，
            # 客户区零参与（O(1)/事件，零自研渲染开销）。
            return
        win = self._window_rect_tuple()
        if self._layer_is_drag_ready(win):
            # 快速路径：纯移动 / 缩放 → 呈现调度（O(1)/事件），
            # 零重烘焙、零探测、零运动态判断。
            self._stop_settle_fade()
            decision = self._compositor.advise(win)
            if decision == PRESENT_NOW:
                # 首帧 / 位置跳变（最大化、吸附、还原、跨屏瞬移）/ 节流窗口已过
                # → 立即呈现，零延迟刷新。
                self._defer_timer.stop()
                self._widget.update()
            elif decision == PRESENT_DEFER:
                # 节流窗口内：安排一次补绘，保证最终位置必然被刷新
                # （绘制便宜时 interval=16ms ≈ 逐帧，无感知延迟）。
                self._defer_timer.start(self._compositor.defer_delay_ms())
            # PRESENT_SKIP：取样结果与上次呈现一致（亚像素抖动 / 原地微动）
            # → 零重绘，连带成本为零。
            return
        # 层未就绪：确保异步烘焙在途，并立即重绘兜底静态场（不阻塞交互）。
        self._maybe_rebake(force=False)
        self._widget.update()

    def _on_defer_present(self) -> None:
        """补上被节流推迟的一次呈现（保证被 DEFER 掉的最终位置必然被刷新）。"""
        if self._disposed or self._paused or self._native_backdrop:
            return
        self._widget.update()

    def set_native_backdrop(self, enabled: bool) -> None:
        """切换「原生 DWM 云母」模式（实验性开关的材质层一侧）。

        开启：自研合成器停用（清空层、停掉全部烘焙 / 节流计时器），绘制端只在
        客户区铺纯黑 —— 配合 ``DwmExtendFrameIntoClientArea(margins=-1)`` 的
        扩展帧约定，被涂黑的客户区由 DWM 以系统背景（原生云母）代替呈现，
        主线程自研渲染开销降为零。深浅色观感由 ``DWMWA_USE_IMMERSIVE_DARK_MODE``
        对齐（见 :func:`ui.mica.winapi.dwm_use_dark_mode`）。

        关闭：恢复自研层 —— 立即强制重烘焙一块视口层并重绘。

        Args:
            enabled: 是否启用原生 DWM 云母。
        """
        enabled = bool(enabled)
        if enabled == self._native_backdrop:
            return
        self._native_backdrop = enabled
        if enabled:
            self._compositor.clear()
            self._pixmap = None
            self._paused = True
            self._stop_fade()
            self._settle_timer.stop()
            self._defer_timer.stop()
            self._opacity_timer.stop()
            self._stop_settle_fade()
        else:
            self._paused = False
            self._fade_alpha = 1.0
            self._fade_to = 1.0
            self._last_req = None
            self._maybe_rebake(force=True)
        self._widget.update()

    def _layer_is_drag_ready(self, win: Tuple[int, int, int, int]) -> bool:
        """拖动期快速路径是否可用：视口层已就绪（覆盖整块虚拟桌面）。

        整块虚拟桌面层与窗口尺寸无关，因此只需判断层与层 pixmap 是否已就绪，
        不再校验窗口尺寸（resize 也走同一路径，绝不退化为重烘焙 / 逐事件重绘）。

        Args:
            win: ``(x, y, w, h)`` 当前窗口矩形（仅接口兼容）。

        Returns:
            层就绪则可走快速路径 ``True``。
        """
        if self._layer is None:
            return False
        if self._layer_pixmap is None or self._layer_pixmap.isNull():
            return False
        return True

    def _window_left_layer_region(
        self, win: Tuple[int, int, int, int], layer: ViewportLayer
    ) -> bool:
        """窗口中心是否已离开层覆盖区域（= 跨监视器越界）。

        层区域 == 烘焙时的监视器矩形（见 :func:`ui.mica.drag.layer_region_for`），
        用窗口中心点判定与 :meth:`_monitor_rect_for` 一致 —— 无需每次事件都做
        COM 探测即可发现跨屏。

        Args:
            win: ``(x, y, w, h)`` 当前窗口矩形。
            layer: 当前视口层。

        Returns:
            中心已越出层区域则 ``True``。
        """
        cx = float(win[0]) + float(win[2]) / 2.0
        cy = float(win[1]) + float(win[3]) / 2.0
        rx, ry, rw, rh = (int(v) for v in layer.region)
        return not (rx <= cx < rx + rw and ry <= cy < ry + rh)

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
        self._compositor.clear()
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
        self._stop_settle_fade()
        self._settle_fade_timer.stop()
        self._hide_until_new_layer = False
        self._deactivate_timer.stop()
        self._watchdog.stop()
        self._opacity_timer.stop()
        self._defer_timer.stop()
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
        """取得 Mica 控件的屏幕矩形（Win32 物理像素）。

        直接调用普通子控件的 ``winId()`` 会把它及部分祖先强制原生化。若顶层
        窗口随后居中移动，这些原生子窗口首次显示时可能仍停在移动前的屏幕坐标，
        导致整个内容区偏移并被裁切，直到 resize 才同步。因此 Windows 路径只读取
        顶层窗口句柄，再把控件相对客户区的 Qt 逻辑几何按实际客户区比例换算为
        物理像素；既保持任意 Mica 子控件的取样语义，也让内容树保持 alien widgets。

        Returns:
            ``(x, y, w, h)``。失败时回退到 Qt 逻辑屏幕几何。
        """
        widget = self._widget
        window = widget.window()
        if winapi.IS_WINDOWS and window is not None:
            hwnd = 0
            try:
                # 必须取顶层窗口句柄：对子控件调 winId() 会强制它原生化，
                # 并连带原生化全部兄弟控件（未设 AA_DontCreateNativeWidgetSiblings
                # 时），原生子窗口位置同步出错会导致整窗内容偏移/黑边。
                hwnd = int(window.winId())
            except (TypeError, RuntimeError, ValueError):
                pass
            if hwnd:
                client = winapi.client_rect(hwnd)
                logical_w = window.width()
                logical_h = window.height()
                if client[2] > 0 and client[3] > 0 and logical_w > 0 and logical_h > 0:
                    pos = widget.mapTo(window, widget.rect().topLeft())
                    scale_x = client[2] / logical_w
                    scale_y = client[3] / logical_h
                    return (
                        client[0] + round(pos.x() * scale_x),
                        client[1] + round(pos.y() * scale_y),
                        max(1, round(widget.width() * scale_x)),
                        max(1, round(widget.height() * scale_y)),
                    )
        top_left = widget.mapToGlobal(widget.rect().topLeft())
        return (top_left.x(), top_left.y(), widget.width(), widget.height())

    def _virtual_rect(self) -> Tuple[int, int, int, int]:
        """当前进程的整块虚拟桌面矩形（所有监视器拼接，物理像素）。

        视口层覆盖此矩形，因此层与窗口尺寸无关 —— 拖动（含跨监视器）期间
        永不重烘焙，窗口只是"窗户"从已烘焙好的层里按当前屏幕位置取子矩形
        blit。非 Windows / 探测失败时回退到 1920×1080 的默认虚拟矩形，保证
        离线测试与无桌面环境下仍能正常烘焙与绘制。

        Returns:
            ``(x, y, w, h)`` 整块虚拟桌面矩形。
        """
        rect = winapi.virtual_screen_rect()
        if rect[2] <= 0 or rect[3] <= 0:
            return (0, 0, 1920, 1080)
        return rect

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
        """按需触发热重烘焙（整块虚拟桌面层）：仅当 ``layer_key`` 确有变化
        （参数 / 主题 / 壁纸 / 层区域 / 层显示长边）时才重烘焙一层。

        Args:
            force: 强制重烘焙（忽略 key 判据）。
        """
        win = self._window_rect_tuple()
        region = self._virtual_rect()
        layer_display_long = _layer_display_long(region)
        key = self._layer_key_for(region, layer_display_long)
        if not force and key == self._layer_key:
            # key 未变化：层仍覆盖整块虚拟桌面，无需重烘焙（窗口在桌面内平移 /
            # 缩放 / 跨监视器、主题参数未变，no-op）。
            return
        if self._worker_thread is not None:
            # 在途烘焙：本次变化（主题 / 参数 / 壁纸 / 区域）已使在途结果过期。
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
        """交互停止回调（拖动 / 缩放结束）。

        整块虚拟桌面层下，背景在交互期间已由实时 blit 严格跟随光标，松手时
        屏幕上所见即正确壁纸裁剪，无需任何重烘焙 / 交叉淡化 / 跨屏等待。此处
        仅复位交互态并补一次重绘（幂等），保持与旧接口一致。
        """
        self._interacting = False
        self._stop_settle_fade()
        self._widget.update()

    def _start_settle_fade(self, final_win: Tuple[int, int, int, int]) -> None:
        """启动松手背景重同步淡化（旧裁剪 → 新裁剪，约 120ms）。

        旧裁剪取自 :attr:`_last_painted_win`（拖动期间屏幕上所见帧的采样位置）；
        与当前裁剪几乎重合时跳过淡化直接重绘。时长经
        ``FAF_MICA_SETTLE_FADE_MS`` 配置，0 表示关闭（瞬间重绘）。

        Args:
            final_win: ``(x, y, w, h)`` 松手时的最终窗口矩形。
        """
        self._stop_settle_fade()
        # 能走到淡化 ⇒ 当前层已覆盖最终位置（settle 判据），跨监视器等待标志作废。
        self._hide_until_new_layer = False
        layer = self._layer
        pixmap = self._layer_pixmap
        if layer is None or pixmap is None or pixmap.isNull():
            self._widget.update()
            return
        if self._settle_fade_ms <= 0 or self._last_painted_win is None:
            self._widget.update()
            return
        old = layer_to_source_clamped(layer, self._last_painted_win)
        new = layer_to_source_clamped(layer, final_win)
        if all(abs(a - b) <= 0.5 for a, b in zip(old, new)):
            # 采样位置几乎未变（原地小抖动 / 拖动又回到起点）：无需淡化。
            self._widget.update()
            return
        self._settle_fade_old_src = tuple(float(v) for v in old)
        self._settle_fade_ticks = 0
        self._settle_fade_timer.start()
        self._widget.update()

    def _stop_settle_fade(self) -> None:
        """立即结束松手淡化（幂等）。"""
        if self._settle_fade_timer.isActive():
            self._settle_fade_timer.stop()
        self._settle_fade_old_src = None
        self._settle_fade_ticks = 0

    def _on_settle_fade_tick(self) -> None:
        """settle 淡化逐帧推进：时长耗尽即停机，由随后的常规帧收尾到 t=1。"""
        self._settle_fade_ticks += 1
        if self._settle_fade_ticks * _FADE_TICK_MS >= self._settle_fade_ms:
            self._stop_settle_fade()
        self._widget.update()

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
        was_hidden = self._hide_until_new_layer
        self._hide_until_new_layer = False
        # 新层到达：若正处于松手淡化（旧裁剪 → 新裁剪），该淡化基于的旧层已
        # 被替换，立即停机，由新层直接接管（跨监视器等待期则由淡入揭示）。
        self._stop_settle_fade()
        self._layer = layer_info
        self._layer_pixmap = _pixmap_from_rgb(display)
        self._layer_key = layer_key
        self._has_shown = True
        # 新层已就绪：被节流推迟的呈现不再需要（新层会强制立即呈现）。
        self._defer_timer.stop()
        self._widget.update()
        if self._active:
            self._start_fade_in(reset=(not was_shown) or was_hidden)
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
            if self._hide_until_new_layer:
                # 跨监视器等待的新层已彻底失败：解除隐藏，回退到旧层（钳制取样）
                # / 纯色底，避免窗口永久停留在纯色状态。
                self._hide_until_new_layer = False
                self._widget.update()

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
                field,
                self._display_long(field),
                self._overlay_opacity,
                self._surface_rgb(),
                origin=(
                    int(field.request.window_rect[0]),
                    int(field.request.window_rect[1]),
                ),
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
