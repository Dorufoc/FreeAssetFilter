"""拖动期偏移采样 —— 用「一次烘焙覆盖整段位移，逐帧只做子矩形取样」消除拖拽迟滞。

问题
----
常规路径下每次烘焙只产出**恰好覆盖窗口**的一小块色调场。窗口一移动，采样矩形
随之平移，就必须重跑整条管线（numpy 版 40–70 ms）。旧实现因此把重烘焙推迟到
"运动停止 80 ms 之后"（``SETTLE_INTERVAL_MS``），于是整段拖拽期间背景纹丝不动，
松手才突然跳到新位置 —— 这就是用户看到的迟滞。

思路
----
色度低通之后，色调场是**纯低频量**；而平移窗口等价于在壁纸上平移采样矩形。
由于管线（含边缘钳制扩边）是平移等变的，有：

    Field(窗口在 P 处) == BigField[偏移 (P − 区域原点)]

也就是说：只要烘一块**比窗口大一圈**的区域，之后任意位移都只是从这块场里
取一个子矩形，**不再有任何计算**。逐帧成本从"整条管线"降为"一次子矩形
blit"，这是能在 60 FPS 下实时透视的前提。

关键的密度约束
--------------
σ 以**网格像素**为单位，而网格尺寸由区域大小 × 密度决定。若把放大后的矩形
直接交给 :func:`ui.mica.engine.bake`，:func:`ui.mica.config.bake_grid_size`
会把它的长边压回 192，密度随之下降，色度低通相对窗口的物理半径就会变大 ——
结果明显更糊，松手回到常规烘焙时会出现一次可见的"变清晰"跳变。

因此本模块始终坚持：

    拖动场的网格密度 == 常规烘焙的网格密度（长边 192 对应窗口长边）

只有进入降级阶梯的最底层才允许降低密度，且必须在文档中明示这是可感知的
画质让步（见 :data:`DRAG_QUALITY_LEVELS`）。

自适应
------
能否跟上的判据只有一个 —— **有没有越界**（窗口跑出当前拖动场的覆盖范围）。
因为可持续速度 ``cover / latency(cover)`` 对 cover 是先增后减的：在小余量区
延迟被固定开销主导，增大余量是净收益；在大余量区延迟 ∝ 面积 ∝ cover²，再增大
反而是净亏损。这个峰值在哪台设备上都不同，与其解析求解，不如直接看结果：

* **越界** → 按 1.5 倍放大余量（连续 :data:`DRAG_MISS_LIMIT` 次才动作，
  避免偶发单次越界就放大）；
* **长期不越界** → 余量缓慢回落到基线，省掉过剩烘焙开销；
* **余量已到上限、或已被预算钳死仍越界** → 用画质阶梯（降低密度）换取更大
  覆盖 —— 这是唯一能突破预算的手段，因此只在走投无路时使用；
* **画质已到最低仍越界，或单次烘焙超过 :data:`DRAG_BAKE_MS_ABORT`** →
  冻结，退回旧行为（保持上一块色调场直到运动停止）。

画质阶梯是**响应式**的，绝不在规划时主动降档：静止拖动没有压力，却为了"多留
点余量"而降密度，会直接破坏密度守恒，松手时就出现糊→清晰的跳变。

冻结只影响"拖动时是否实时跟随"，不影响静止时的画质 —— 运动一停，稳定定时器
照常触发一次全质量烘焙，背景必然是正确的。

本模块不依赖 Qt，可在无 GUI 环境下完整单元测试。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from .config import BAKE_LONG_MIN, bake_grid_size
from .engine import margin_px

__all__ = [
    "DRAG_BAKE_MS_ABORT",
    "DRAG_COVER_DEFAULT_PX",
    "DRAG_COVER_MAX_PX",
    "DRAG_COVER_MIN_PX",
    "DRAG_MAX_PAD_PX",
    "DRAG_MISS_LIMIT",
    "DRAG_QUALITY_LEVELS",
    "DRAG_REQUEST_COOLDOWN_MS",
    "DRAG_VELOCITY_SMOOTHING",
    "DragField",
    "DragPlan",
    "DragSampler",
    "fit_cover",
    "grid_for_region",
]


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: 单侧余量下限（虚拟像素）。低于此值偏移采样已无意义（一次微小移动就出界）。
DRAG_COVER_MIN_PX: int = 96

#: 单侧余量上限（虚拟像素）。防止把整个虚拟桌面都烘进来。
DRAG_COVER_MAX_PX: int = 1024

#: 单侧余量初值（虚拟像素）。约能吸收 320 px 位移而无需重烘焙。
DRAG_COVER_DEFAULT_PX: int = 320

#: 由速度推算余量时的安全系数：``cover = 速度 × 实测延迟 × 本系数``。
DRAG_COVER_SAFETY: float = 1.6

#: 连续越界达到该次数即判定"跟不上"，扩大余量或进入冻结。
DRAG_MISS_LIMIT: int = 3

#: 单次烘焙超过该耗时（毫秒）即判定为病态，直接冻结 —— 说明这台设备在当前
#: 参数下根本无法负担拖动场，继续请求只会空耗 CPU / GPU。
DRAG_BAKE_MS_ABORT: float = 400.0

#: 单次拖动烘焙的工作像素硬上限（pad 面积）。与设备无关，纯粹防止内存与时间失控。
#:
#: 标定依据：σ 是**常量**（默认 27.33 网格像素，由 ``blur_radius`` 推出，与网格
#: 尺寸无关），因此扩边恒为 ``min(ceil(2σ)=55, 0.5×长边)``，pad 面积 ≈ (gw+110)
#: × (gh+110)。常规烘焙（192×120）pad ≈ 69 k，实测 CPU ≈ 40 ms / GPU ≈ 2.5 ms。
#: 本上限约为常规烘焙的 3.7 倍，对应 CPU ≈ 150 ms、GPU ≈ 9 ms、峰值内存 ≈ 8 MB，
#: 都在"后台线程、且仅在越界时才发生"的前提下可接受。
DRAG_MAX_PAD_PX: int = 260_000

#: 拖动场网格长边硬上限。防止小窗口（密度接近 1）叠加余量后把网格撑爆。
DRAG_GRID_MAX: int = 512

#: 允许的画质阶梯（窗口等效网格长边），从高到低。**仅在降级时**使用低档：
#: 降低它等价于降低密度，会让色度低通相对窗口变宽（更糊）。
DRAG_QUALITY_LEVELS: Tuple[int, ...] = (192, 160, 128)

#: 重烘焙请求的最小间隔（毫秒）。防止缩放过程中每个 moveEvent 都触发一次烘焙。
DRAG_REQUEST_COOLDOWN_MS: float = 40.0

#: 速度估计的指数平滑系数（0 = 不平滑，越接近 1 越迟钝）。
DRAG_VELOCITY_SMOOTHING: float = 0.6

#: 越界判定的浮点容差（网格像素），吸收舍入误差。
_EPS: float = 1e-3


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DragPlan:
    """一次拖动场烘焙的规划结果。

    Attributes:
        cover: 实际采用的单侧余量（虚拟像素），可能已被预算压缩。
        region: ``(x, y, w, h)`` 待烘焙的虚拟桌面矩形（窗口矩形外扩 ``cover``，
            并沿运动方向前移，见 :class:`DragSampler`）。
        grid: ``(grid_w, grid_h)`` 该区域对应的网格尺寸（与常规烘焙同密度）。
        win_size: ``(w, h)`` 规划时的窗口尺寸；窗口尺寸一变，本规划即失效。
        quality: 实际采用的画质档（窗口等效网格长边）。
    """

    cover: int
    region: Tuple[int, int, int, int]
    grid: Tuple[int, int]
    win_size: Tuple[int, int]
    quality: int

    def pad_size(self, sigma: float) -> Tuple[int, int]:
        """按给定 σ 计算含扩边的工作分辨率。

        Args:
            sigma: 色度低通标准差（网格像素）。

        Returns:
            ``(pad_w, pad_h)``。
        """
        m = margin_px(self.grid[0], self.grid[1], sigma)
        return (self.grid[0] + 2 * m, self.grid[1] + 2 * m)


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
        x, y, w, h = (float(v) for v in window_rect)
        if (int(w), int(h)) != self.win_size:
            # 缩放中：密度与尺寸都不再匹配，偏移采样不适用（回到旧行为）。
            return None

        gw, gh = float(self.grid[0]), float(self.grid[1])
        dx, dy = self.density
        sx = (x - float(self.region[0])) * dx
        sy = (y - float(self.region[1])) * dy
        sw = w * dx
        sh = h * dy

        if sx < -_EPS or sy < -_EPS:
            return None
        if sx + sw > gw + _EPS or sy + sh > gh + _EPS:
            return None
        return (sx, sy, sw, sh)


# ---------------------------------------------------------------------------
# 几何规划
# ---------------------------------------------------------------------------


def _window_scale(win_w: int, win_h: int, quality: int) -> float:
    """求网格密度（网格像素 / 虚拟像素）。

    取「常规烘焙的密度」与「目标画质档对应密度」的较小者，保证：
    正常档（192）下与常规烘焙**完全一致**；小窗口（长边 < 192，常规密度 = 1）
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


def grid_for_region(win_w: int, win_h: int, cover: int, quality: int = 192) -> Tuple[int, int]:
    """按「与常规烘焙相同的密度」把外扩区域换算为网格尺寸。

    Args:
        win_w: 窗口宽度。
        win_h: 窗口高度。
        cover: 单侧余量（虚拟像素）。
        quality: 窗口等效网格长边，见 :data:`DRAG_QUALITY_LEVELS`。

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


def fit_cover(
    win_w: int, win_h: int, cover: int, sigma: float, quality: int = 192
) -> int:
    """把期望余量压缩到预算之内。

    两道约束依次生效：

    1. **网格硬上限** :data:`DRAG_GRID_MAX` —— 小窗口密度接近 1，叠加余量极易
       把网格撑到几千像素；
    2. **工作像素硬上限** :data:`DRAG_MAX_PAD_PX` —— 按 0.7 倍迭代收缩，直到
       pad 面积达标。收缩到 0 时区域退化为窗口本身，即等价于一次常规烘焙。

    Args:
        win_w: 窗口宽度。
        win_h: 窗口高度。
        cover: 期望的单侧余量（虚拟像素）。
        sigma: 色度低通标准差（网格像素），决定扩边宽度。
        quality: 窗口等效网格长边。

    Returns:
        压缩后的单侧余量（≥ 0）。
    """
    cover = max(0, int(cover))
    scale = _window_scale(win_w, win_h, quality)

    # 1) 网格硬上限：解 (win + 2c) * scale <= DRAG_GRID_MAX
    if scale > 0.0:
        limit_w = (DRAG_GRID_MAX / scale - int(win_w)) / 2.0
        limit_h = (DRAG_GRID_MAX / scale - int(win_h)) / 2.0
        cover = min(cover, int(max(0.0, min(limit_w, limit_h))))

    # 2) 工作像素硬上限
    for _ in range(16):
        gw, gh = grid_for_region(win_w, win_h, cover, quality)
        m = margin_px(gw, gh, sigma)
        if (gw + 2 * m) * (gh + 2 * m) <= DRAG_MAX_PAD_PX or cover <= 0:
            break
        cover = max(0, int(cover * 0.7))
    return cover


# ---------------------------------------------------------------------------
# 自适应控制器
# ---------------------------------------------------------------------------


def _clamp(value: float, low: float, high: float) -> float:
    """把 ``value`` 钳制到 ``[low, high]``。"""
    if high < low:
        return low
    return max(low, min(high, value))


class DragSampler:
    """拖动场余量与画质的自适应控制器（纯数据，无 Qt 依赖）。

    状态在一个实例内累积：烘焙耗时的指数均值跨拖动段保留，因此第二次拖动
    起就能直接给出合适的余量，不需要"先失败几次再学"。

    典型用法::

        sampler = DragSampler()
        # 运动事件：
        plan = sampler.plan_for(win_rect, velocity, sigma)
        # 烘焙完成：
        sampler.note_bake(field.duration_ms)
        # 发现越界：
        sampler.note_miss()
    """

    __slots__ = (
        "_cover",
        "_bake_ms",
        "_misses",
        "_frozen",
        "_bakes",
        "_quality",
        "_budget_limited",
    )

    def __init__(
        self,
        *,
        cover: int = DRAG_COVER_DEFAULT_PX,
        quality: int = DRAG_QUALITY_LEVELS[0],
    ) -> None:
        """初始化控制器。

        Args:
            cover: 初始单侧余量（虚拟像素）。
            quality: 初始画质档（窗口等效网格长边）。
        """
        self._cover = int(_clamp(cover, DRAG_COVER_MIN_PX, DRAG_COVER_MAX_PX))
        self._quality = int(quality)
        self._bake_ms: float = 0.0
        self._misses: int = 0
        self._frozen: bool = False
        self._bakes: int = 0
        self._budget_limited: bool = False

    # -- 只读状态 ---------------------------------------------------------

    @property
    def cover(self) -> int:
        """当前期望的单侧余量（虚拟像素）。"""
        return self._cover

    @property
    def quality(self) -> int:
        """当前画质档（窗口等效网格长边）。"""
        return self._quality

    @property
    def bake_ms(self) -> float:
        """烘焙耗时的指数均值（毫秒）；``0.0`` 表示尚无样本。"""
        return self._bake_ms

    @property
    def frozen(self) -> bool:
        """是否已冻结偏移采样（设备跟不上，退回旧行为）。"""
        return self._frozen

    @property
    def budget_limited(self) -> bool:
        """上一次规划的实际余量是否被预算（网格/像素上限）钳制。

        为 ``True`` 时继续增大期望余量毫无意义 —— 它已经拿不到了，唯一的出路
        是降画质档，:meth:`note_miss` 据此直接走画质阶梯。
        """
        return self._budget_limited

    def reset(self) -> None:
        """新一段交互开始时复位。

        清除冻结与越界计数，**并把画质档恢复到最高** —— 每段拖动都从头尝试
        全质量，避免上一段的降级被永久继承。跨段学到的耗时均值与余量保留，
        这样第二次拖动起就能直接给出合适的余量。
        """
        self._misses = 0
        self._frozen = False
        self._budget_limited = False
        self._quality = int(DRAG_QUALITY_LEVELS[0])

    # -- 规划 -------------------------------------------------------------

    def desired_cover(self, velocity: Tuple[float, float]) -> int:
        """由运动速度推算需要的单侧余量。

        三者取最大：

        * **已学到的余量** :attr:`cover` —— 由 :meth:`note_miss` 按 1.5 倍
          放大、由 :meth:`note_bake` 缓慢回落而来。它是自适应的记忆载体：
          少了这一项，:meth:`note_miss` 放大出来的余量根本传不进规划，
          自适应闭环是断的；
        * **基线** :data:`DRAG_COVER_DEFAULT_PX` —— 静止或慢速拖动也要留出
          足够余量，否则一次小幅移动就出界、白白触发重烘焙；
        * **速度需求** ``|v| × 实测烘焙延迟 × 安全系数`` —— 含义是"覆盖住一次
          烘焙周转期间窗口可能走过的距离"。延迟用实测均值而非猜测值，因此能
          随设备（GPU 数毫秒 / CPU 数十毫秒）自动伸缩。

        Args:
            velocity: ``(vx, vy)`` 速度（虚拟像素 / 秒）。

        Returns:
            期望余量（虚拟像素），已被 :data:`DRAG_COVER_MIN_PX` /
            :data:`DRAG_COVER_MAX_PX` 钳制。
        """
        speed = math.hypot(float(velocity[0]), float(velocity[1]))
        latency_s = max(self._bake_ms, 1.0) / 1000.0
        demand = speed * latency_s * DRAG_COVER_SAFETY
        target = max(float(self._cover), float(DRAG_COVER_DEFAULT_PX), demand)
        return int(_clamp(target, DRAG_COVER_MIN_PX, DRAG_COVER_MAX_PX))

    def plan_for(
        self,
        window_rect: Tuple[int, int, int, int],
        velocity: Tuple[float, float] = (0.0, 0.0),
        sigma: float = 0.0,
    ) -> DragPlan:
        """为当前窗口位置与速度规划一次拖动场烘焙。

        画质档**不在此处选择** —— 它只由 :meth:`note_miss`（走投无路时降档）
        与 :meth:`reset`（每段拖动恢复到最高档）改变。若在这里为了"多留点
        余量"而主动降档，静止拖动也会被拉到最低密度，直接破坏密度守恒，
        松手时必然出现糊→清晰的跳变。

        Args:
            window_rect: ``(x, y, w, h)`` 窗口矩形（虚拟桌面像素）。
            velocity: ``(vx, vy)`` 速度（虚拟像素 / 秒）。
            sigma: 色度低通标准差（网格像素）。

        Returns:
            :class:`DragPlan`。
        """
        x, y, w, h = (int(v) for v in window_rect)
        desired = max(self.desired_cover(velocity), DRAG_COVER_MIN_PX)

        quality = self._quality
        cover = fit_cover(w, h, desired, sigma, quality)
        # 预算钳制记录供 note_miss 使用：此时增大期望余量已无意义，
        # 唯一出路是降画质档（降低密度 ⇒ 同样预算下覆盖更大区域）。
        self._budget_limited = cover < desired

        # 沿运动方向前移：让余量更多地落在"即将经过"的一侧。上限为半个余量，
        # 因此即使方向立刻反转，反方向仍留有 50% 余量。
        lead_s = max(self._bake_ms, 0.0) / 1000.0
        half = cover * 0.5
        bx = _clamp(float(velocity[0]) * lead_s, -half, half)
        by = _clamp(float(velocity[1]) * lead_s, -half, half)

        region = (
            x - cover + int(round(bx)),
            y - cover + int(round(by)),
            w + 2 * cover,
            h + 2 * cover,
        )
        return DragPlan(
            cover=cover,
            region=region,
            grid=grid_for_region(w, h, cover, quality),
            win_size=(w, h),
            quality=quality,
        )

    # -- 反馈 -------------------------------------------------------------

    def note_bake(self, duration_ms: float) -> None:
        """反馈一次烘焙完成（更新耗时均值，必要时回落余量）。

        注意这里**没有**"烘焙慢就收缩余量"的规则。可持续速度
        ``cover / latency(cover)`` 对 cover 是先增后减的：在慢设备上收缩
        cover 反而会让它变小（latency 的下降追不上 cover 的下降）。真正的
        判据只有**是否越界**，因此收缩只发生在"长期没越界"时 —— 那是纯节省。

        Args:
            duration_ms: 本次烘焙耗时（毫秒）。
        """
        value = max(0.0, float(duration_ms))
        self._bake_ms = value if self._bake_ms <= 0.0 else self._bake_ms * 0.6 + value * 0.4
        self._bakes += 1

        had_miss = self._misses > 0
        self._misses = 0

        if value > DRAG_BAKE_MS_ABORT:
            self._frozen = True
            return
        if not had_miss and self._cover > DRAG_COVER_DEFAULT_PX:
            # 一直没越界说明余量过剩，缓慢回落到基线，省掉无谓的烘焙开销。
            self._cover = max(DRAG_COVER_DEFAULT_PX, int(self._cover * 0.9))

    def note_miss(self) -> None:
        """反馈一次越界（窗口跑出了当前拖动场的覆盖范围）。

        连续越界达到 :data:`DRAG_MISS_LIMIT` 才动作，避免偶发单次越界就放大。
        动作分两级：

        1. **期望余量还有空间、且未被预算钳制** → 按 1.5 倍放大重试。这是
           首选路径，因为它不改变密度，画质零损失；
        2. **余量已到上限，或已被预算（网格/像素上限）钳死** → 走画质阶梯：
           降低密度，同样预算下就能覆盖更大的区域。这是**可见的画质让步**，
           只在第 1 条无路可走时使用。
        3. **画质已到最低档仍越界** → 冻结，整段拖动退回旧行为。

        Args:
            无。
        """
        if self._frozen:
            return
        self._misses += 1
        if self._misses < DRAG_MISS_LIMIT:
            return
        self._misses = 0

        if not self._budget_limited and self._cover < DRAG_COVER_MAX_PX:
            self._cover = min(DRAG_COVER_MAX_PX, int(self._cover * 1.5 + 16))
            return

        # 余量这条路已经走死，改用画质换覆盖。
        self._cover = DRAG_COVER_MAX_PX
        self._budget_limited = False
        try:
            index = DRAG_QUALITY_LEVELS.index(self._quality)
        except ValueError:
            index = 0
        if index + 1 < len(DRAG_QUALITY_LEVELS):
            self._quality = DRAG_QUALITY_LEVELS[index + 1]
            return
        self._frozen = True
