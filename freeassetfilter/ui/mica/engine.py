"""烘焙编排层：把「窗口矩形 + 参数 + 壁纸源」变成一小块色调场图像。

本模块是纯 numpy 的，**不含 Qt**，因此可以整体在后台线程里跑，也可以在无显示
环境下完整测试。它只负责三件事：

1. **采样几何** —— 由窗口矩形推出应当采样的壁纸区域（含扩边，见下）；
2. **分辨率决策** —— 由窗口尺寸推出烘焙网格尺寸（:func:`config.bake_grid_size`）；
3. **调度色彩内核** —— 调用 :func:`mica.tint.bake_tint_field` 并裁出窗口对应部分。

为什么必须"采样扩边"
--------------------
色度低通（:func:`mica.tint.blur_chroma`）用的是**边缘钳制**填充。如果只裁窗口
矩形来烘焙，会引入两个可见缺陷：

* 窗口四边附近的色度被"拉伸"，与窗口中心的取色规律不一致；
* 更糟的是，同一块壁纸在窗口边界位置不同时会算出不同的色调 —— 拖动窗口时
  背景色会**跟着窗口边界游动**，而真实 Mica 的色调只由屏幕位置决定。

因此这里把采样矩形向外扩 :data:`EDGE_MARGIN_SIGMAS` 个 σ，在扩大后的网格上
完成整条管线，最后再把中心区域裁出来。扩边只发生在极小的网格上（长边 ≤192），
代价是可以忽略的，而它换来的是"色调只与屏幕位置有关"这一关键正确性。

重烘焙策略
----------
:class:`BakeRequest` 是一个不可变的输入快照，:meth:`BakeRequest.needs_rebake`
集中了"什么情况下才值得重烘焙"的全部判据（尺寸变化、位移超阈值、参数变化、
主题切换、壁纸变更）。色调场是纯低频量，因此小于
:data:`config.MOVE_REBAKE_THRESHOLD_PX` 的位移直接忽略 —— 这是拖动窗口时能
保持流畅的根本原因。
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from . import tint
from .config import EngineParams, MicaParams, bake_grid_size, MOVE_REBAKE_THRESHOLD_PX
from .source import WallpaperSource

_LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: 采样扩边宽度，以 σ 为单位。2σ 覆盖高斯 ~95% 的能量，足以让边缘取色与
#: 中心一致；再往大只是徒增开销。
EDGE_MARGIN_SIGMAS: float = 2.0

#: 扩边上限（相对网格长边的比例），把最坏情况的像素数锁在 4× 以内。
MARGIN_MAX_FRACTION: float = 0.5

#: 扩边下限（网格像素）。即使 σ 很小也留 2 px，避免最外一圈像素完全依赖填充。
MARGIN_MIN_PX: int = 2


# ---------------------------------------------------------------------------
# 请求与结果
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BakeRequest:
    """一次烘焙的完整输入快照（不可变，可安全跨线程传递）。

    Attributes:
        window_rect: ``(x, y, w, h)``，窗口在虚拟桌面空间中的矩形（物理像素）。
        params: 用户参数。
        dark: 是否深色模式。
        source_signature: 壁纸源指纹，用于判断壁纸是否变化。
    """

    window_rect: Tuple[int, int, int, int]
    params: MicaParams
    dark: bool
    source_signature: str = ""

    @property
    def size(self) -> Tuple[int, int]:
        """窗口尺寸 ``(w, h)``。"""
        return (int(self.window_rect[2]), int(self.window_rect[3]))

    @property
    def origin(self) -> Tuple[int, int]:
        """窗口左上角 ``(x, y)``。"""
        return (int(self.window_rect[0]), int(self.window_rect[1]))

    def needs_rebake(
        self, other: Optional["BakeRequest"], move_threshold: int = MOVE_REBAKE_THRESHOLD_PX
    ) -> bool:
        """相对上一次成功的请求，本次是否值得重新烘焙。

        判据（任一成立即需重烘焙）：

        * 上一次不存在；
        * 窗口尺寸变化（网格尺寸随之改变，缓存无法复用）；
        * 参数、深浅模式或壁纸指纹变化；
        * 位移在任一轴上超过 ``move_threshold``。

        位移阈值的正当性：色调场是低频量，几十像素的位移带来的色度变化远低于
        8-bit 量化步长，肉眼不可分辨。

        Args:
            other: 上一次成功烘焙所用的请求；``None`` 视为需要烘焙。
            move_threshold: 位移阈值（像素）。

        Returns:
            需要重烘焙则 ``True``。
        """
        if other is None:
            return True
        if self.size != other.size:
            return True
        if self.dark != other.dark:
            return True
        if self.params != other.params:
            return True
        if self.source_signature != other.source_signature:
            return True
        dx = abs(self.window_rect[0] - other.window_rect[0])
        dy = abs(self.window_rect[1] - other.window_rect[1])
        return dx >= int(move_threshold) or dy >= int(move_threshold)


@dataclass(frozen=True)
class BakedField:
    """一次烘焙的结果。

    Attributes:
        image: shape ``(grid_h, grid_w, 3)`` 的 uint8 sRGB 色调场，直接放大铺满
            窗口即可（它是低频量，双线性放大无损）。
        request: 产生本结果的请求快照。
        grid_size: ``(grid_w, grid_h)`` 网格尺寸。
        sample_rect: 实际采样的虚拟桌面矩形（含扩边），便于调试与校验。
        margin: 使用的扩边宽度（网格像素）。
        backend: 壁纸源后端标识。
        duration_ms: 烘焙耗时（毫秒）。
        work_size: 实际跑管线的工作分辨率 ``(work_w, work_h)``，便于性能诊断。
    """

    image: np.ndarray
    request: BakeRequest
    grid_size: Tuple[int, int]
    sample_rect: Tuple[float, float, float, float]
    margin: int
    backend: str
    duration_ms: float
    work_size: Tuple[int, int] = (0, 0)

    def mean_rgb(self) -> Tuple[int, int, int]:
        """色调场平均色，用于纯色降级与自动化校验。"""
        mean = self.image.reshape(-1, 3).mean(axis=0)
        return tuple(int(round(float(v))) for v in mean)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# 几何
# ---------------------------------------------------------------------------


def margin_px(grid_w: int, grid_h: int, sigma: float) -> int:
    """计算采样扩边宽度（网格像素）。

    Args:
        grid_w: 网格宽度。
        grid_h: 网格高度。
        sigma: 色度低通标准差（网格像素）。

    Returns:
        扩边宽度，受 :data:`MARGIN_MIN_PX` 与 :data:`MARGIN_MAX_FRACTION` 双重约束。
    """
    want = int(math.ceil(EDGE_MARGIN_SIGMAS * max(0.0, float(sigma))))
    cap = int(round(MARGIN_MAX_FRACTION * max(int(grid_w), int(grid_h))))
    return max(MARGIN_MIN_PX, min(want, max(MARGIN_MIN_PX, cap)))


def sample_rect_for(
    window_rect: Tuple[int, int, int, int],
    grid_w: int,
    grid_h: int,
    margin: int,
) -> Tuple[float, float, float, float]:
    """由窗口矩形与扩边宽度算出应采样的虚拟桌面矩形。

    扩边在**网格空间**给定，需按"网格像素 / 虚拟像素"的密度换算回虚拟空间，
    这样扩边前后网格的采样密度完全一致，σ 的物理含义才不会漂移。

    Args:
        window_rect: ``(x, y, w, h)`` 窗口矩形（虚拟桌面物理像素）。
        grid_w: 未扩边的网格宽度。
        grid_h: 未扩边的网格高度。
        margin: 扩边宽度（网格像素）。

    Returns:
        ``(x, y, w, h)`` 浮点采样矩形（可能越出桌面，由重采样做边缘钳制）。
    """
    x, y, w, h = (float(v) for v in window_rect)
    w = max(1.0, w)
    h = max(1.0, h)
    # 网格像素 / 虚拟像素
    density_x = max(int(grid_w), 1) / w
    density_y = max(int(grid_h), 1) / h
    mx = float(margin) / density_x
    my = float(margin) / density_y
    return (x - mx, y - my, w + 2.0 * mx, h + 2.0 * my)


# ---------------------------------------------------------------------------
# 烘焙
# ---------------------------------------------------------------------------


def bake(request: BakeRequest, source: WallpaperSource) -> BakedField:
    """执行一次完整烘焙：采样到网格 → 色调场管线 → 裁出窗口 → 量化。

    网格尺寸由窗口尺寸经 :func:`config.bake_grid_size` 推出。需要显式指定网格
    （拖动期偏移采样要烘一块比窗口更大的区域）时用 :func:`bake_with_grid`。

    两级分辨率的分工：

    ============  ==========================  ================================
    分辨率        典型尺寸                    承担的工作
    ============  ==========================  ================================
    画布          ≤1600 长边                  壁纸解码 / 摆放，跨烘焙复用
    网格          ≤192×192（含扩边 ≤~300²）   去明度 → 门控 → 低通 → 整形 →
                                              等亮度重建 → 颜色混合 → 量化
    ============  ==========================  ================================

    整条管线直接在**网格分辨率**上完成，因此与"全分辨率参考实现"在每一步都
    逐像素对齐——工作分辨率降采样引入的双线性相位偏移（壁纸彩色高频边缘处被
    高增益参数放大成孤立亮点）被彻底消除。性能不依赖工作分辨率优化，而依赖
    :class:`mica.source.WallpaperSource` 的 mip 缓存：整屏画布只在壁纸变化时
    解码/降采样一次，之后任意窗口的采样都从缓存小图取，成本恒定（与窗口尺寸
    无关）。实测单次烘焙 4–6 ms，远低于视觉流畅阈值。

    Args:
        request: 输入快照。
        source: 壁纸源画布。

    Returns:
        :class:`BakedField`。

    Raises:
        ValueError: 壁纸源画布为空（正常降级链下不会发生）。
    """
    win_w, win_h = request.size
    return bake_with_grid(request, source, bake_grid_size(win_w, win_h))


def bake_with_grid(
    request: BakeRequest,
    source: WallpaperSource,
    grid_size: Tuple[int, int],
) -> BakedField:
    """按**显式指定**的网格尺寸烘焙（:func:`bake` 的底层实现）。

    为什么需要它
    ------------
    拖动期偏移采样要一次性烘出一块**比窗口更大**的区域，供后续逐帧按位移做
    子矩形取样（见 :mod:`ui.mica.drag`）。若直接把放大后的矩形交给
    :func:`bake`，:func:`config.bake_grid_size` 会把它的长边压回 192，
    网格密度随之下降 —— 而 σ 是以**网格像素**为单位的，密度一变，色度低通
    相对窗口的物理半径就变了，结果会明显更糊。

    因此调用方必须先按「与常规烘焙相同的密度」算出目标网格尺寸再传进来。
    本函数不做任何密度校正，只保证 ``grid_size`` 被原样使用。

    Args:
        request: 输入快照，``window_rect`` 为待烘焙区域（可以是放大后的矩形）。
        source: 壁纸源画布。
        grid_size: ``(grid_w, grid_h)`` 目标网格尺寸（不含扩边），必须 ≥1。

    Returns:
        :class:`BakedField`。

    Raises:
        ValueError: 壁纸源画布为空，或 ``grid_size`` 非法。
    """
    started = time.perf_counter()
    if source.pixels.size == 0:
        raise ValueError("壁纸源画布为空")

    grid_w, grid_h = (max(1, int(v)) for v in grid_size)
    ep: EngineParams = request.params.to_engine(request.dark)

    margin = margin_px(grid_w, grid_h, ep.sigma)
    pad_w = grid_w + 2 * margin
    pad_h = grid_h + 2 * margin
    rect = sample_rect_for(request.window_rect, grid_w, grid_h, margin)

    # 采样到含扩边的网格分辨率。mip 缓存保证整屏画布只解码/降采样一次，故此处
    # 成本与窗口尺寸/位置无关，且分辨率与参考实现严格一致。
    crop = source.crop(rect, pad_w, pad_h)
    l_ref = tint.g1_oklab_l(ep.g1())
    source_layer, _chroma = tint.build_source_from_crop(
        crop,
        ep.chroma_cap(),
        ep.gain,
        ep.sigma,
        l_ref,
    )
    # 裁出窗口 interior（去掉边缘扩边），再在网格分辨率上做颜色混合 + 抖动量化。
    interior = source_layer[margin : margin + grid_h, margin : margin + grid_w]
    composite = tint.compose_tint_float(interior, ep.g1(), ep.alpha)
    image = tint.quantize_u8(composite, dither=True)

    duration = (time.perf_counter() - started) * 1000.0
    _LOG.debug(
        "烘焙完成：win=%dx%d grid=%dx%d pad=%dx%d margin=%d σ=%.2f "
        "α=%.2f cap=%.4f gain=%.2f backend=%s %.1fms",
        request.size[0], request.size[1], grid_w, grid_h, pad_w, pad_h, margin,
        ep.sigma, ep.alpha, ep.chroma_cap(), ep.gain,
        source.backend, duration,
    )
    return BakedField(
        image=image,
        request=request,
        grid_size=(grid_w, grid_h),
        sample_rect=rect,
        margin=margin,
        backend=source.backend,
        duration_ms=duration,
        work_size=(pad_w, pad_h),
    )


def solid_field(request: BakeRequest, rgb: Tuple[int, int, int]) -> BakedField:
    """构造一块纯色色调场，用于烘焙彻底失败时的最终降级。

    Args:
        request: 输入快照。
        rgb: 填充色。

    Returns:
        :class:`BakedField`，``backend`` 为 ``"solid"``。
    """
    grid_w, grid_h = bake_grid_size(*request.size)
    image = np.full((grid_h, grid_w, 3), np.array(rgb, np.uint8), np.uint8)
    return BakedField(
        image=image,
        request=request,
        grid_size=(grid_w, grid_h),
        sample_rect=tuple(float(v) for v in request.window_rect),  # type: ignore[arg-type]
        margin=0,
        backend="solid",
        duration_ms=0.0,
        work_size=(grid_w, grid_h),
    )


__all__ = [
    "BakeRequest",
    "BakedField",
    "EDGE_MARGIN_SIGMAS",
    "MARGIN_MAX_FRACTION",
    "MARGIN_MIN_PX",
    "bake",
    "bake_with_grid",
    "margin_px",
    "sample_rect_for",
    "solid_field",
]
