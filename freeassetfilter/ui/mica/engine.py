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
完成整条管线，最后再把中心区域裁出来。扩边只发生在极小的网格上（长边
≤:data:`BAKE_LONG_MAX`），代价是可以忽略的，而它换来的是"色调只与屏幕位置有关"
这一关键正确性。

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
from typing import Dict, Optional, Tuple

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
    #: **未量化**的浮点合成结果 ``(grid_h, grid_w, 3)``，sRGB 编码值 0..1。
    #: 8-bit 量化必须推迟到显示分辨率再做（见 :func:`upscale_to_display`），
    #: 否则亚 LSB 的渐变信息在网格分辨率上就被抹掉，放大后即成色带（断层）。
    #: 仅 CPU 管线提供；GPU 管线为 ``None``，届时退回 uint8 网格放大。
    image_float: Optional[np.ndarray] = None

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
    网格          ≤BAKE_LONG_MAX×BAKE_LONG_MAX（含扩边 ≤~300²）   去明度 → 门控 → 低通 → 整形 →
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
    :func:`bake`，:func:`config.bake_grid_size` 会把它的长边压回 :data:`BAKE_LONG_MAX`，
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
    # 不在网格分辨率上量化：色调场会被放大铺满窗口，此时网格级的量化台阶
    # 与抖动噪声会被同步放大 —— 前者成色带（断层），后者成块状噪点（磨砂
    # 玻璃感）。这里只保留 uint8 快照供纯色降级 / GPU 管线 / 单测使用；
    # 真正用于绘制的是 :attr:`BakedField.image_float` 在**显示分辨率**上的
    # 一次量化（见 :func:`upscale_to_display`）。
    image = tint.quantize_u8(composite, dither=False)

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
        image_float=composite,
    )


# ---------------------------------------------------------------------------
# 显示分辨率上采样 + 屏幕锚定抖动（消除渐变区色彩断层 / banding）
# ---------------------------------------------------------------------------

#: 最终空间抖动幅值（LSB，±0.7 LSB）。
#:
#: 幅值经全组合实测标定：真实 Mica 色调场
#: 明度被 ``SetLum`` 锁在 G1、色度被 cap 到 ~0.055 Oklab，整屏动态范围往往只有
#: **几个 LSB** —— 8-bit 量化必然产生台阶。以「最长平坦游程 ≤ 16px 且不存在
#: ≥64px 游程」为无可见色带判据，各图案的最小可用幅值为：
#:
#: ================  ======  ======  ======  ======  ======
#: 图案              ±0.5    ±0.6    ±0.7    ±0.8    ±1.0
#: ================  ======  ======  ======  ======  ======
#: 白噪声（旧实现）  287px   58px    33px    24px    18px
#: TPDF 三角        511px   249px   116px   75px    39px
#: Bayer 8×8 有序   687px   543px   335px    7px     3px
#: **IGN（采用）**   245px    **8px**  **6px**  **4px**  **2px**
#: ================  ======  ======  ======  ======  ======
#:
#: 白噪声即使加到 ±1.2 仍有 18px 游程（肉眼可见色带）；IGN 在 ±0.6 即达标。
#: 取 **±0.7** 留一档余量，且幅值与旧实现相同 —— 噪点可见度不升反降（见下）。
_DITHER_AMP_DEFAULT: float = 0.7

#: 交错梯度噪声（Interleaved Gradient Noise, IGN）的两个方向频率与放大系数。
#: 该式逐像素把 ``(x, y)`` 映射为 ``[0, 1)`` 上的低差异序列（Jorge Jimenez）。
_IGN_C1: float = 0.06711056
_IGN_C2: float = 0.00583715
_IGN_K: float = 52.9829189

#: 按 ``(th, tw, amp, ox, oy)`` 缓存的 IGN 抖动偏移。
#: 图案只由目标尺寸、幅值与**层原点**决定，同一组合可无限复用；虚拟桌面尺寸
#: 稳定时命中率 100%，只在层尺寸/原点变化时才付一次生成开销（2560×1440 约
#: 30 ms，与烘焙同量级的一次性成本）。
_DITHER_TILE_CACHE: Dict[Tuple[int, int, float, int, int], np.ndarray] = {}
#: 缓存条目上限。IGN 图案**平移等变**（见 :func:`_dither_offsets`），同一尺寸的
#: 不同原点理论上可由一份基准图案切片得到，但为负原点预生成整幅更省事；
#: 实际只会同时存在「视口层」与「静态场」两种尺寸，2 条足够，且把常驻内存
#: 从旧实现的 6×14 MB（≈84 MB）压到 ≈29 MB。
_DITHER_TILE_CACHE_MAX: int = 2


def _ign_offsets(th: int, tw: int, ox: int, oy: int, amp: float) -> np.ndarray:
    """生成**屏幕锚定**的交错梯度噪声（IGN）抖动偏移 ``(th, tw, 1)``，取值 ``±amp``。

    为什么是 IGN 而不是白噪声
    --------------------------
    抖动的作用是给量化器注入扰动，把 8-bit 台阶打散成空间噪声。关键在于噪声的
    **频谱**：人眼对低频扰动敏感、对高频噪点不敏感，因此理想抖动应把能量尽量
    推到高频（蓝噪声）。实测低频能量占比（8×8 块均值方差 / 总方差）：

    ================  ==================
    图案              低频能量占比
    ================  ==================
    白噪声 / TPDF      1.58 %
    Bayer 8×8 有序     0.00 %（但周期性 ⇒ 可见规则花纹）
    **IGN**           **0.14 %**
    ================  ==================

    白噪声会**聚簇** —— 局部若干像素的扰动同向，量化后仍连成大片同一种值，
    实测最长平坦游程 33px（±0.7）；IGN 相邻像素的扰动高速交替，同样幅值下
    最长游程仅 6px，且因低频能量低 11×，**观感上比白噪声更干净**。

    为什么必须屏幕锚定
    ------------------
    噪声值由**绝对屏幕坐标** ``(ox + j, oy + i)`` 决定，而非层的本地坐标
    ``(i, j)``。于是抖动纹理固定附着于壁纸：整块虚拟桌面层烘一次之后，窗口
    按位移做子矩形 1:1 裁剪时，露出的是「该屏幕位置专属」的噪声，而不是
    「抖动图案在窗口内乱跑」。真实 Mica 的纹理就锚定在壁纸上。

    实现要点
    --------
    * 用 ``x -= floor(x)`` 取小数部分，比 ``np.mod(x, 1.0)`` 快约 3.2×
      （2560×1440：30 ms vs 97 ms），结果逐位相同。
    * 一维坐标换算保留 float64 精度（数组仅 ``tw`` / ``th`` 长度），只有最后的
      广播加与取整降为 float32 —— 避免大图上的临时 float64 缓冲（29 MB）。
    * IGN 是**平移等变**的：``IGN(ox+dx, oy+dy)[i, j] == IGN(ox, oy)[i+dy, j+dx]``，
      这正是纹理锚定壁纸的数学保证（有专项测试锁定）。

    Args:
        th: 目标高度。
        tw: 目标宽度。
        ox: 本区域左上角在虚拟桌面坐标系中的 x（屏幕原点，可负）。
        oy: 本区域左上角在虚拟桌面坐标系中的 y（屏幕原点，可负）。
        amp: 抖动幅值（LSB），正值表示噪声覆盖 ``±amp``。

    Returns:
        float32 ``(th, tw, 1)`` 偏移数组，可直接与 0..255 的像素值相加。
    """
    # 一维部分用 float64，保证大坐标（负原点屏）下的相位精度。
    xs = (np.arange(int(tw), dtype=np.float64) + float(ox)) * _IGN_C1
    ys = (np.arange(int(th), dtype=np.float64) + float(oy)) * _IGN_C2
    # 广播加法在此物化为 th×tw 的 float32 —— 后续 floor 都在这块缓冲上原地做。
    a = (xs.astype(np.float32).reshape(1, -1)
         + ys.astype(np.float32).reshape(-1, 1))
    a -= np.floor(a)          # frac(c1·x + c2·y)
    a *= np.float32(_IGN_K)
    a -= np.floor(a)          # frac(K · frac(...))
    a -= np.float32(0.5)
    a *= np.float32(2.0 * float(amp))
    return a.reshape(int(th), int(tw), 1)


def _dither_offsets(
    th: int, tw: int, amp: float, origin: Tuple[int, int] = (0, 0)
) -> np.ndarray:
    """返回 ``(th, tw, 1)`` 的屏幕锚定 IGN 抖动偏移，取值 ``±amp``。

    图案由**绝对屏幕坐标** ``(origin + (i, j))`` 唯一决定（见
    :func:`_ign_offsets`），因此：

    * 同一 ``(th, tw, amp, origin)`` 下不同次重建得到逐位相同的图案 ——
      跨重建稳定、不闪烁；
    * 整块虚拟桌面层烘一次后，窗口按位移做子矩形 1:1 裁剪时，抖动纹理固定
      附着于壁纸而非窗口 —— 拖动时不会看到噪声在窗口内游动。

    抖动必须在上采样之后叠加，绝不能加在网格分辨率上，否则会被 Qt 双线性
    放大成块状噪点（磨砂玻璃感）。

    注意：返回的是缓存数组，调用方**不得原地修改**；如需可变副本请自行
    ``.copy()``。

    Args:
        th: 目标高度。
        tw: 目标宽度。
        amp: 抖动幅值（LSB），正值表示噪声覆盖 ``±amp``。
        origin: 本区域左上角在虚拟桌面坐标系中的 ``(ox, oy)``；默认 ``(0, 0)``。

    Returns:
        float32 ``(th, tw, 1)`` 偏移数组，可直接与 0..255 的像素值相加。
    """
    key = (int(th), int(tw), float(amp), int(origin[0]), int(origin[1]))
    cached = _DITHER_TILE_CACHE.get(key)
    if cached is not None:
        return cached
    if len(_DITHER_TILE_CACHE) >= _DITHER_TILE_CACHE_MAX:
        _DITHER_TILE_CACHE.clear()
    offsets = _ign_offsets(int(th), int(tw), int(origin[0]), int(origin[1]), float(amp))
    _DITHER_TILE_CACHE[key] = offsets
    return offsets


def _resize_bilinear(src: np.ndarray, tw: int, th: int) -> np.ndarray:
    """可分离双线性放大：``(gh, gw, 3)`` float32 → ``(th, tw, 3)`` float32。

    为什么可分离：二维双线性是可分离核，先横后纵与一次二维插值数学等价，
    但内存流量从 O(4·th·tw) 降到 O(2·th·tw)。大图的内存带宽是这一步的
    绝对瓶颈，故先做**输出更小的那个方向**，让中间结果尽量小。

    每一步都用「取一行/列 → 原地乘 → 原地加」的方式把临时数组压到 1 个，
    避免在同一块 2M 像素的缓冲上反复分配。

    Args:
        src: ``(gh, gw, 3)`` float32 源数组。
        tw: 目标宽度。
        th: 目标高度。

    Returns:
        ``(th, tw, 3)`` float32 **新数组**（永不与 ``src`` 共享内存）。
    """
    buf = np.ascontiguousarray(src, dtype=np.float32)
    gh, gw = int(buf.shape[0]), int(buf.shape[1])
    if tw == gw and th == gh:
        return buf.copy()

    def _axis1(b: np.ndarray, n_out: int) -> np.ndarray:
        g = int(b.shape[1])
        xs = np.linspace(0.0, float(g - 1), n_out, dtype=np.float32)
        x0 = np.floor(xs).astype(np.intp)
        wx = (xs - x0).astype(np.float32)
        out = b[:, x0, :]  # 高级索引 ⇒ 副本，可安全原地修改
        out *= (1.0 - wx)[None, :, None]
        tmp = b[:, np.minimum(x0 + 1, g - 1), :]
        tmp *= wx[None, :, None]
        out += tmp
        return out

    def _axis0(b: np.ndarray, n_out: int) -> np.ndarray:
        g = int(b.shape[0])
        ys = np.linspace(0.0, float(g - 1), n_out, dtype=np.float32)
        y0 = np.floor(ys).astype(np.intp)
        wy = (ys - y0).astype(np.float32)
        out = b[y0, :, :]
        out *= (1.0 - wy)[:, None, None]
        tmp = b[np.minimum(y0 + 1, g - 1), :, :]
        tmp *= wy[:, None, None]
        out += tmp
        return out

    # 中间结果更小的一侧先做：min(gh·tw, th·gw)。
    if gh * tw <= th * gw:
        return _axis0(_axis1(buf, tw), th)
    return _axis1(_axis0(buf, th), tw)


def upscale_to_display(
    grid: np.ndarray,
    target_long: int,
    dither: bool = True,
    dither_amp: float = _DITHER_AMP_DEFAULT,
    origin: Tuple[int, int] = (0, 0),
) -> np.ndarray:
    """把低分辨率网格色调场双线性放大到目标显示分辨率，并可选叠加抖动。

    设计要点
    --------
    色调场是低频量，直接把网格图像交给 Qt 双线性放大铺满窗口即可；但 8-bit
    量化在大面积平滑渐变上会出现可见色带（断层）。在**网格分辨率**上加抖动
    会被同步放大成块状噪点（磨砂玻璃感），因此抖动必须发生在**显示分辨率**
    （1px 颗粒）。本函数在 worker 线程把网格上采样到目标分辨率后再叠加
    **确定性均匀噪声**抖动（±:data:`_DITHER_AMP_DEFAULT` LSB，最终空间），
    产出的图像在放大到窗口时色带被彻底打散、过渡连续。

    Args:
        grid: ``(gh, gw, 3)`` 网格色调场。``uint8``（0..255）或 ``float``
            （0..1 的未量化合成结果）；后者能消除色带，优先使用。
        target_long: 目标显示分辨率长边（像素）；短边按网格宽高比推算。
        dither: 是否在显示分辨率上叠加 1px 抖动。
        dither_amp: 抖动幅值（LSB，默认 :data:`_DITHER_AMP_DEFAULT`）；仅
            ``dither=True`` 时生效。
        origin: 层在虚拟桌面坐标系中的左上角 ``(ox, oy)``；非 ``(0, 0)`` 时
            抖动改为屏幕锚定（见 :func:`_dither_offsets`），使纹理附着壁纸。

    Returns:
        ``(th, tw, 3)`` uint8 图像，长边 ≈ ``target_long``。
    """
    if grid.ndim != 3 or grid.shape[2] != 3:
        raise ValueError("grid 必须是 (H, W, 3) 的 RGB 数组")
    gh = int(grid.shape[0])
    gw = int(grid.shape[1])
    if gh <= 0 or gw <= 0:
        raise ValueError("grid 尺寸非法")
    long_side = max(gw, gh)
    scale = float(max(1, int(target_long))) / float(long_side)
    tw = max(1, int(round(gw * scale)))
    th = max(1, int(round(gh * scale)))

    # 输入可以是 uint8（0..255）或 float（0..1，未量化的合成结果）。
    # 后者保留了亚 LSB 精度，是消除色带的关键：量化只在最后发生一次。
    if grid.dtype == np.uint8:
        src = grid.astype(np.float32, copy=False)
    else:
        src = np.asarray(grid, dtype=np.float32) * 255.0

    out = _resize_bilinear(src, tw, th)
    if dither:
        # ±0.7 LSB 的确定性均匀噪声，均匀打断 256 级量化台阶；非原点时屏幕锚定。
        out += _dither_offsets(th, tw, dither_amp, origin)

    # 必须先 rint 再转 uint8。astype(uint8) 是**截断**而非四舍五入，会带来
    # -0.5 LSB 的系统性偏置：加了抖动反而整体变暗，且抖动图案只有一半的
    # 阈值被跨过，色带边缘退化成规则花纹 —— 实测比不抖动更容易看出断层。
    return np.clip(np.rint(out), 0.0, 255.0).astype(np.uint8)


def render_display(
    field: "BakedField",
    target_long: int,
    overlay: float = 1.0,
    surface_rgb: Tuple[int, int, int] = (0, 0, 0),
    origin: Tuple[int, int] = (0, 0),
) -> np.ndarray:
    """把烘焙产物渲染到显示分辨率的 uint8 图像（先预合成、后一次性量化）。

    渲染管线先双线性上采样到**显示分辨率**的 float，再在显示分辨率上做
    「混合预合成」：``(1-o)*S + o*V``（``o=overlay``，``S=surface_rgb`` 纯色底，
    ``V=上采样后的色调场``），最后才在最终颜色空间一次性量化 + 抖动。由此
    Qt 绘制期**不再做第二次透明度混合**（旧路径的 pixmap ``setOpacity(0.7)``
    会在 8-bit 上产生第二次量化，把相邻源色阶如 107/108/109 全部坍缩到同一
    终值），抖动在最后一步有效打散台阶。

    实现上不依赖 :func:`upscale_to_display` 完成全部工作，而是复用
    :func:`_resize_bilinear` 与 :func:`_dither_offsets` 组合实现预合成；
    :data:`_DITHER_AMP_DEFAULT` 为最终空间的一次性量化幅值。

    Args:
        field: :class:`BakedField`。
        target_long: 目标显示分辨率长边（像素）。
        overlay: 叠加层不透明度 ``o``，``0..1``。``1.0``（默认）表示不透底混合，
            结果与「先缩放再抖动」一致（无底色偏移）；``<1.0`` 时按
            ``(1-o)*S + o*V`` 预合成到底色 ``surface_rgb`` 上。
        surface_rgb: 底色 ``(r, g, b)``（0..255），仅 ``overlay < 1.0`` 时使用。
        origin: 层在虚拟桌面坐标系中的左上角 ``(ox, oy)``；非 ``(0, 0)`` 时抖动
            改为屏幕锚定（见 :func:`_dither_offsets`），使整块层烘焙一次后窗口
            子矩形裁剪时纹理固定附着于壁纸，避免拖动时抖动在窗口内游动。

    Returns:
        ``(th, tw, 3)`` uint8 图像，可直接转 QImage/QPixmap。
    """
    float_src = getattr(field, "image_float", None)
    grid = float_src if float_src is not None else field.image

    gh = int(grid.shape[0])
    gw = int(grid.shape[1])
    if gh <= 0 or gw <= 0:
        raise ValueError("grid 尺寸非法")
    long_side = max(gw, gh)
    scale = float(max(1, int(target_long))) / float(long_side)
    tw = max(1, int(round(gw * scale)))
    th = max(1, int(round(gh * scale)))

    # 输入可以是 uint8（0..255）或 float（0..1，未量化的合成结果）。
    if grid.dtype == np.uint8:
        src = grid.astype(np.float32, copy=False)
    else:
        src = np.asarray(grid, dtype=np.float32) * 255.0

    out = _resize_bilinear(src, tw, th)

    if overlay - 1.0 < 1e-9:
        # 预合成：先混合再量化，避免 Qt 绘制期的第二次透明度量化。
        o = float(overlay)
        s = np.asarray(surface_rgb, dtype=np.float32).reshape(1, 1, 3)
        out = out * o + s * (1.0 - o)

    out += _dither_offsets(th, tw, _DITHER_AMP_DEFAULT, origin)

    return np.clip(np.rint(out), 0.0, 255.0).astype(np.uint8)


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
    "render_display",
    "sample_rect_for",
    "solid_field",
    "upscale_to_display",
]
