"""逐监视器视口层 —— 一次烘焙出整块监视器色调场，逐帧仅做子矩形取样。

问题
----
常规路径下每次烘焙只产出**恰好覆盖窗口**的一小块色调场。窗口一移动，采样矩形
随之平移，就必须重跑整条管线（numpy 版 40–70 ms）—— 拖拽期间必然滞涩。旧实现
把重烘焙推迟到"运动停止 80 ms 之后"，用户看到的正是拖拽期间背景纹丝不动、松手
突然跳到新位置的迟滞。

思路
----
把旧的「自适应拖动场机器」换成**一块持久化的逐监视器视口层**：烘一次、之后只
取样。由于色度低通之后的色调场是纯低频量，且管线（含边缘钳制扩边）是平移等变的，
有：

    Field(窗口在 P 处) == Layer[偏移 (P − 区域原点)]

因此只要烘一块**覆盖整块监视器**的层，之后任意位移都只是从这块场里取一个子矩形，
**不再有任何计算**。逐帧成本从"整条管线"降为"一次子矩形 blit"。

本模块只承载**纯几何**（无 Qt、无 GPU、无烘焙）：层如何覆盖监视器
（:func:`layer_region_for`）、层网格尺寸与 σ 守恒（:func:`layer_grid`）、以及由
窗口矩形到层内子矩形的分辨率无关映射（:func:`layer_to_source`）。烘焙本身由
material/engine 承担，本模块可脱离图形栈在无 GUI 环境下完整单元测试。

关键的密度约束
--------------
σ 以**网格像素**为单位，而网格尺寸由区域大小 × 密度决定。若层网格被
:data:`LAYER_GRID_CAP` 钳制、密度下降，色度低通相对窗口的物理半径就会变大 ——
层与常规烘焙观感不一致（更糊）。因此 :func:`layer_grid` 在钳制发生时按
σ 守恒回算 :math:`\\sigma_\\text{eff}`，使

    σ_physical = sigma_eff / applied_density = sigma / density

保持恒定为常数，与常规烘焙（长边 BAKE_LONG_MAX 对应窗口长边）完全一致。

本模块不依赖 Qt，可在无 GUI 环境下完整单元测试。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from .config import BAKE_LONG_MIN, BAKE_LONG_MAX, bake_grid_size

__all__ = [
    "LAYER_DISPLAY_LONG_MAX",
    "LAYER_GRID_CAP",
    "DragField",
    "ViewportLayer",
    "grid_for_region",
    "layer_grid",
    "layer_region_for",
    "layer_to_source",
]


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: 视口层网格长边硬上限（每轴像素）。与原生 ``kMaxPadSide`` 一致。
LAYER_GRID_CAP: int = 1024

#: 层显示参考长边（用于把相对层尺寸换算成窗口等效显示尺寸）。
LAYER_DISPLAY_LONG_MAX: int = 4096

#: 越界判定的浮点容差（网格像素），吸收舍入误差。
_EPS: float = 1e-3


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ViewportLayer:
    """一块持久化、逐监视器烘焙的放大色调场（供逐帧子矩形取样）。

    Attributes:
        region: ``(x, y, w, h)`` 本层在虚拟桌面中的覆盖范围（整数）。
        width: 本层实际渲染像素宽度（即层分辨率的宽）。
        height: 本层实际渲染像素高度（即层分辨率的高）。
        win_size: ``(w, h)`` 烘焙时的窗口尺寸；窗口尺寸一变，本层失效（缩放中）。
    """

    region: Tuple[int, int, int, int]
    width: int
    height: int
    win_size: Tuple[int, int]


@dataclass(frozen=True, eq=False)
class DragField:
    """一块可供逐帧偏移取样的放大色调场。

    Attributes:
        image: shape ``(grid_h, grid_w, 3)`` 的 uint8 色调场，覆盖 :attr:`region`。
        region: ``(x, y, w, h)`` 本场在虚拟桌面中的覆盖范围（整数）。
        grid: ``(grid_w, grid_h)`` 本场分辨率，即 ``image`` 的宽高。
        win_size: ``(w, h)`` 规划时的窗口尺寸。
        key: 有效性判据 ``(params, dark, source_signature)``；三者任一变化本场作废。
        backend: 实际生效的烘焙后端。
        duration_ms: 本次烘焙耗时（毫秒）。
        cover: 实际采用的单侧余量（虚拟像素）。
        quality: 实际采用的画质档（窗口等效网格长边）。
    """

    image: np.ndarray
    region: Tuple[int, int, int, int]
    grid: Tuple[int, int]
    win_size: Tuple[int, int]
    key: Tuple[object, ...]
    backend: str
    duration_ms: float
    cover: int
    quality: int

    @property
    def density(self) -> Tuple[float, float]:
        """本场的网格密度 ``(grid/虚拟像素_x, grid/虚拟像素_y)``。"""
        rw, rh = float(max(1, self.region[2])), float(max(1, self.region[3]))
        return (self.grid[0] / rw, self.grid[1] / rh)

    def _raw_rect(
        self, window_rect: Tuple[int, int, int, int]
    ) -> Optional[Tuple[float, float, float, float]]:
        """按窗口当前位置算出本场中的原始（未做越界判定的）子矩形。

        Args:
            window_rect: ``(x, y, w, h)`` 窗口当前矩形（虚拟桌面像素）。

        Returns:
            ``(sx, sy, sw, sh)`` 浮点子矩形；窗口尺寸与规划时不一致
            （缩放中）时返回 ``None``。
        """
        x, y, w, h = (float(v) for v in window_rect)
        if (int(w), int(h)) != self.win_size:
            # 缩放中：密度与尺寸都不再匹配，偏移采样不适用（回到旧行为）。
            return None
        gw, gh = float(self.grid[0]), float(self.grid[1])
        dx, dy = self.density
        sx = (x - float(self.region[0])) * dx
        sy = (y - float(self.region[1])) * dy
        return (sx, sy, w * dx, h * dy)

    def source_rect(
        self, window_rect: Tuple[int, int, int, int]
    ) -> Optional[Tuple[float, float, float, float]]:
        """按窗口当前位置算出本场中的子矩形（**浮点**，供亚像素取样）。

        返回浮点而非整数是抗锯齿的关键：若把源矩形取整，源坐标每跳 1 个网格
        像素，放大到窗口后就是一次 ~8 px 的台阶式跳动。交给 Qt 以 ``QRectF``
        双线性取样，运动才是平滑的。

        Args:
            window_rect: ``(x, y, w, h)`` 窗口当前矩形（虚拟桌面像素）。

        Returns:
            ``(sx, sy, sw, sh)`` 本场坐标系中的浮点子矩形；越界或窗口尺寸
            与规划时不一致（缩放中）时返回 ``None``。
        """
        rect = self._raw_rect(window_rect)
        if rect is None:
            return None
        sx, sy, sw, sh = rect
        gw, gh = float(self.grid[0]), float(self.grid[1])
        if sx < -_EPS or sy < -_EPS:
            return None
        if sx + sw > gw + _EPS or sy + sh > gh + _EPS:
            return None
        return rect

    def source_rect_clamped(
        self, window_rect: Tuple[int, int, int, int]
    ) -> Optional[Tuple[float, float, float, float]]:
        """按窗口位置算出子矩形，但**把越界钳制到边缘**而非返回 ``None``。

        与 :meth:`source_rect` 的唯一区别：窗口跑出本场覆盖范围时，不判越界，
        而是把源矩形左上角钳制到 ``[0, 网格尺寸 − 子矩形尺寸]``，使平移继续
        跟随（只是停在边缘内容），而不是交还给上层去画一块静止时的整窗色调场。

        这是消除拖拽抽搐的关键：若越界时回退到静止色调场（``_pixmap``），而它
        的色调是按窗口"上一次停留位置"烘焙的，与当前位置差了整个拖拽距离，
        画面会"跳回旧位置"再跳回跟随 —— 即用户看到的区域位置抽搐。钳制后画面
        永远随窗口位移连续变化，最多在极端越界时短暂停在边缘。

        缩放中（窗口尺寸与规划时不一致）一律返回 ``None``：此时密度已变，
        钳制无意义，交给稳定后的常规烘焙。

        Args:
            window_rect: ``(x, y, w, h)`` 窗口当前矩形（虚拟桌面像素）。

        Returns:
            ``(sx, sy, sw, sh)`` 浮点子矩形；尺寸不匹配时 ``None``。
        """
        rect = self._raw_rect(window_rect)
        if rect is None:
            return None
        sx, sy, sw, sh = rect
        gw = float(self.grid[0])
        gh = float(self.grid[1])
        sx = max(0.0, min(sx, gw - sw)) if sw <= gw else 0.0
        sy = max(0.0, min(sy, gh - sh)) if sh <= gh else 0.0
        return (sx, sy, sw, sh)


# ---------------------------------------------------------------------------
# 几何辅助
# ---------------------------------------------------------------------------


def _is_integer(value: float) -> bool:
    """判定 ``value`` 是否为精确整数。"""
    return abs(value - round(value)) < 1e-9


def _clamp(value: float, low: float, high: float) -> float:
    """把 ``value`` 钳制到 ``[low, high]``。"""
    if high < low:
        return low
    return max(low, min(high, value))


def _window_scale(win_w: int, win_h: int, quality: int) -> float:
    """求网格密度（网格像素 / 虚拟像素）。

    取「常规烘焙的密度」与「目标画质档对应密度」的较小者，保证：
    最高档（BAKE_LONG_MAX）下与常规烘焙**完全一致**；小窗口（长边 < BAKE_LONG_MAX，常规密度 = 1）
    不会被强行放大。

    Args:
        win_w: 窗口宽度。
        win_h: 窗口高度。
        quality: 窗口等效网格长边。

    Returns:
        密度，恒 > 0。
    """
    long_side = max(1, max(int(win_w), int(win_h)))
    base = max(bake_grid_size(win_w, win_h)) / long_side
    return max(1e-6, min(base, float(quality) / long_side))


def grid_for_region(
    win_w: int, win_h: int, cover: int, quality: int = BAKE_LONG_MAX
) -> Tuple[int, int]:
    """按「与常规烘焙相同的密度」把外扩区域换算为网格尺寸。

    Args:
        win_w: 窗口宽度。
        win_h: 窗口高度。
        cover: 单侧余量（虚拟像素）。
        quality: 窗口等效网格长边。

    Returns:
        ``(grid_w, grid_h)``，均 ≥ 1。
    """
    scale = _window_scale(win_w, win_h, quality)
    rw = max(1, int(win_w) + 2 * max(0, int(cover)))
    rh = max(1, int(win_h) + 2 * max(0, int(cover)))
    return (
        max(BAKE_LONG_MIN, int(round(rw * scale))),
        max(BAKE_LONG_MIN, int(round(rh * scale))),
    )


def layer_region_for(
    window_rect: Tuple[int, int, int, int],
    monitor_rect: Tuple[int, int, int, int],
) -> Tuple[int, int, int, int]:
    """决定视口层覆盖的虚拟桌面矩形。

    单层逐监视器烘焙：层覆盖整块监视器。任何位于该监视器内的窗口，其子矩形
    都能从层内取到，无需重烘焙。

    Args:
        window_rect: ``(x, y, w, h)`` 窗口矩形（虚拟桌面像素）。
        monitor_rect: ``(x, y, w, h)`` 监视器矩形（虚拟桌面像素）。

    Returns:
        ``(x, y, w, h)`` 层覆盖矩形（即 ``monitor_rect`` 原样）。
    """
    return monitor_rect


def layer_grid(
    monitor_rect: Tuple[int, int, int, int],
    win_w: int,
    win_h: int,
    sigma: float,
) -> Tuple[Tuple[int, int], float]:
    """按「与常规烘焙相同的密度」把监视器矩形换算为层分辨率，并保持 σ 守恒。

    密度取自 ``_window_scale(win_w, win_h, BAKE_LONG_MAX)`` —— 与常规烘焙最高档
    一致，否则松手会出现糊→清晰跳变。每个轴先 ``round(mon_side × density)``，
    再钳制到 ``[BAKE_LONG_MIN, LAYER_GRID_CAP]``。

    若任一轴被钳制（超上限），实际密度必然下降，而 σ（网格像素）必须同步缩小，
    才能保持**物理模糊半径** ``σ_physical = sigma_eff / applied_density =
    sigma / density`` 不变 —— 否则视口层与常规烘焙观感不一致。未发生钳制时
    ``sigma_eff`` 等于原 ``sigma``。

    Args:
        monitor_rect: ``(x, y, w, h)`` 监视器矩形（虚拟桌面像素）。
        win_w: 窗口宽度。
        win_h: 窗口高度。
        sigma: 色度低通标准差（网格像素）。

    Returns:
        ``((grid_w, grid_h), sigma_eff)``。``grid`` 每轴均在
        ``[BAKE_LONG_MIN, LAYER_GRID_CAP]`` 内。
    """
    mon_w = max(1, int(monitor_rect[2]))
    mon_h = max(1, int(monitor_rect[3]))
    density = _window_scale(win_w, win_h, BAKE_LONG_MAX)
    raw_w = int(round(mon_w * density))
    raw_h = int(round(mon_h * density))
    grid_w = int(_clamp(raw_w, BAKE_LONG_MIN, LAYER_GRID_CAP))
    grid_h = int(_clamp(raw_h, BAKE_LONG_MIN, LAYER_GRID_CAP))
    if grid_w != raw_w or grid_h != raw_h:
        # 任一轴被钳制 ⇒ 实际密度下降；按 σ 守恒回算 effective σ。
        applied_density = min(grid_w / mon_w, grid_h / mon_h)
        sigma_eff = sigma * (applied_density / density)
    else:
        sigma_eff = float(sigma)
    return ((grid_w, grid_h), sigma_eff)


def layer_to_source(
    layer: ViewportLayer, window_rect: Tuple[int, int, int, int]
) -> Optional[Tuple[float, float, float, float]]:
    """把窗口矩形映射成层内的源子矩形（**分辨率无关**）。

    映射规则：``源 = (win − region_origin) × layer_px / region_px``，其中
    ``layer_px`` 为 :attr:`ViewportLayer.width` / :attr:`ViewportLayer.height`，
    ``region_px`` 为 :attr:`ViewportLayer.region` 的宽 / 高。因此层的实际渲染尺寸
    可以与虚拟区域不同（层分辨率被钳制），映射始终正确。

    当层渲染尺寸与虚拟区域相等（恒等比例，逐像素 1:1）**且**映射坐标恰为整数时，
    返回整数坐标（避免不必要的重采样）；否则返回浮点坐标供亚像素平滑取样。

    Args:
        layer: 视口层。
        window_rect: ``(x, y, w, h)`` 窗口当前矩形（虚拟桌面像素）。

    Returns:
        ``(sx, sy, sw, sh)`` 层坐标系内的子矩形；窗口**部分或完全**落在层区域
        之外，或窗口尺寸与烘焙时不一致（缩放中）时返回 ``None`` —— 绝不静默钳制。
    """
    x, y, w, h = (float(v) for v in window_rect)
    if (int(w), int(h)) != layer.win_size:
        # 缩放中：密度与尺寸都不再匹配，偏移取样不适用（回到旧行为）。
        return None
    rx, ry, rw, rh = (float(v) for v in layer.region)
    if x < rx - _EPS or y < ry - _EPS:
        return None
    if x + w > rx + rw + _EPS or y + h > ry + rh + _EPS:
        return None

    sx = (x - rx) * (layer.width / rw) if rw else 0.0
    sy = (y - ry) * (layer.height / rh) if rh else 0.0
    sw = w * (layer.width / rw) if rw else 0.0
    sh = h * (layer.height / rh) if rh else 0.0

    if layer.width == layer.region[2] and layer.height == layer.region[3]:
        if all(_is_integer(v) for v in (sx, sy, sw, sh)):
            return (int(round(sx)), int(round(sy)), int(round(sw)), int(round(sh)))
    return (sx, sy, sw, sh)


def layer_to_source_clamped(
    layer: ViewportLayer, window_rect: Tuple[int, int, int, int]
) -> Tuple[float, float, float, float]:
    """把窗口矩形映射成层内源子矩形，**对已有层永不返回 ``None``**。

    与 :func:`layer_to_source` 的区别：本函数**不**因窗口尺寸与烘焙时不一致
    （缩放中）而拒绝，也**不**因窗口部分/完全落在层区域之外而返回 ``None``。
    它始终按当前位置与**当前尺寸**映射，并把越界的一轴钳制到层边缘；若子矩形
    在某轴超过层宽/高（例如窗口比所在监视器还大），则把该轴钳制到层的全宽/全高。
    由此 Mica 在任何时刻（resize / 越界）都从层里取样，**绝不**因取样失败而
    退化到只画纯色（Mica 消失）。真正的区域修正仍由 :meth:`_needs_layer_rebake`
    在窗口稳定后重烘焙一层来完成。

    映射规则同 :func:`layer_to_source`：``源 = (win − region_origin) × layer_px / region_px``
    （分辨率无关，层分辨率与虚拟区域不同时仍正确）。

    Args:
        layer: 视口层。
        window_rect: ``(x, y, w, h)`` 窗口当前矩形（虚拟桌面像素）。

    Returns:
        ``(sx, sy, sw, sh)`` 层坐标系内的子矩形（每轴均钳制到层内），恒为 4 元组，
        **绝不**返回 ``None``。当层与虚拟区域 1:1 且坐标均为整数时返回整型坐标，
        否则返回浮点坐标（亚像素平滑）。
    """
    x, y, w, h = (float(v) for v in window_rect)
    rx, ry, rw, rh = (float(v) for v in layer.region)

    sx = (x - rx) * (layer.width / rw) if rw else 0.0
    sy = (y - ry) * (layer.height / rh) if rh else 0.0
    sw = w * (layer.width / rw) if rw else 0.0
    sh = h * (layer.height / rh) if rh else 0.0

    lw = float(layer.width)
    lh = float(layer.height)

    # 钳制：子矩形在某轴不超过层宽/高时，把源坐标钳到 [0, 层宽 - sw]；
    # 超过层宽/高时，把该轴钳制到层的全宽/全高（sx=0, sw=层宽）。
    if sw > lw:
        sw = lw
        sx = 0.0
    else:
        sx = _clamp(sx, 0.0, max(0.0, lw - sw))
    if sh > lh:
        sh = lh
        sy = 0.0
    else:
        sy = _clamp(sy, 0.0, max(0.0, lh - sh))

    if layer.width == layer.region[2] and layer.height == layer.region[3]:
        if all(_is_integer(v) for v in (sx, sy, sw, sh)):
            return (int(round(sx)), int(round(sy)), int(round(sw)), int(round(sh)))
    return (sx, sy, sw, sh)
