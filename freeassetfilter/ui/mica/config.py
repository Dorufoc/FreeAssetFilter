"""Mica 参数模型 —— 设置项 ↔ 引擎参数的唯一映射层。

本模块是纯数据层（不依赖 Qt / numpy），可在无 GUI 环境下做单元测试。
它承担两件事：

1. **用户参数模型** :class:`MicaParams` —— 与设置页四个滑动条、持久化键
   ``appearance.mica.*`` 一一对应的四项可调参数。
2. **引擎参数模型** :class:`EngineParams` —— 烘焙管线真正消费的参数。
   二者通过 :meth:`MicaParams.to_engine` 转换，映射公式集中在此，避免
   "魔术数字"散落到渲染代码里。

设计约定
--------
* 设置区间保持与旧版一致（``saturation`` 0–8、``contrast`` 0–3、
  ``blur_radius`` 0–300、``tint_opacity`` 0–100），这样既有用户配置
  无需迁移即可被正确钳制。
* 引擎侧参数以**烘焙网格像素**为单位（而非屏幕像素），使烘焙耗时与窗口
  尺寸解耦 —— 这是性能可控的关键（见 :mod:`.engine`）。

Examples:
    >>> p = MicaParams()
    >>> e = p.to_engine(dark=True)
    >>> round(e.gain, 3), round(e.alpha, 2)
    (1.0, 0.7)
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, Tuple

# ---------------------------------------------------------------------------
# 设置项区间与默认值（与 settings_layout.MICA_PARAM_SPECS 同步）
# ---------------------------------------------------------------------------

#: 四项用户可调参数的取值区间。
PARAM_BOUNDS: Dict[str, Tuple[float, float]] = {
    "saturation": (0.0, 8.0),
    "contrast": (0.0, 3.0),
    "blur_radius": (0.0, 300.0),
    "tint_opacity": (0.0, 100.0),
}

#: 四项用户可调参数的默认值。
PARAM_DEFAULTS: Dict[str, float] = {
    "saturation": 4.5,
    "contrast": 1.5,
    "blur_radius": 200.0,
    "tint_opacity": 70.0,
}

# ---------------------------------------------------------------------------
# 主题基色（G1）—— 与 ThemeManager.surface（gray.g1 / gray_light.g1）一致
# ---------------------------------------------------------------------------

#: 深色模式基色（``#1a1a1a``）。
G1_DARK: Tuple[int, int, int] = (0x1A, 0x1A, 0x1A)
#: 浅色模式基色（``#f5f5f5``）。
G1_LIGHT: Tuple[int, int, int] = (0xF5, 0xF5, 0xF5)

#: 色度软上限基准（Oklab chroma）。深色可承受更浓；浅色必须更收敛，
#: 否则高亮度下极易出现刺眼的荧光色。
CHROMA_CAP_DARK: float = 0.055
CHROMA_CAP_LIGHT: float = 0.030

# ---------------------------------------------------------------------------
# 映射常数
# ---------------------------------------------------------------------------

#: 饱和度 → 色度增益的换算基准（4.5 ⇒ gain 1.0）。
SATURATION_REF: float = 4.5
#: 对比度 → 色度上限倍率的换算基准（1.5 ⇒ cap ×1.0）。
CONTRAST_REF: float = 1.5
#: 色度上限倍率的硬上限，防止极端设置把 UI 染成荧光色。
CAP_SCALE_MAX: float = 2.5
#: 色度低通标准差区间（**烘焙网格像素**）。
SIGMA_MIN: float = 2.0
SIGMA_MAX: float = 40.0

# ---------------------------------------------------------------------------
# 烘焙网格
# ---------------------------------------------------------------------------

#: 烘焙图长边下限 / 上限（像素）。
BAKE_LONG_MIN: int = 48
BAKE_LONG_MAX: int = 192

# ---------------------------------------------------------------------------
# 渲染与交互时序
# ---------------------------------------------------------------------------

#: Mica 叠加层淡入淡出时长（毫秒）。
FADE_DURATION_MS: int = 175
#: 交互（拖拽/缩放）停止后重建缓存的延时（毫秒）。
SETTLE_INTERVAL_MS: int = 80
#: 窗口移动超过该像素阈值才在稳定后重烘焙（色调场是低频量，微小位移不可见）。
MOVE_REBAKE_THRESHOLD_PX: int = 24
#: 失焦后判定"焦点是否真正离开应用"的防抖延时（毫秒）。
DEACTIVATE_DEBOUNCE_MS: int = 60

#: 噪声叠加层不透明度 —— Win11 Mica 带一层极细的胶片颗粒，用于掩盖
#: 8-bit 大面积渐变的色带。数值取经验值，肉眼几乎不可见但能消除 banding。
NOISE_OPACITY: float = 0.035
#: 噪声平铺贴图边长（像素）。
NOISE_TILE_SIZE: int = 64
#: 噪声固定随机种子（保证跨重绘稳定，不闪烁）。
NOISE_SEED: int = 1337

# ---------------------------------------------------------------------------
# 后台线程
# ---------------------------------------------------------------------------

#: 单次烘焙的最长容忍时间（毫秒）；超时即强制终止，防止野线程。
BAKE_WATCHDOG_MS: int = 10_000
#: 后台烘焙失败后的最大重试次数（共尝试 N+1 次）。
BAKE_MAX_RETRIES: int = 2
#: 重试退避基数（毫秒），第 N 次重试延迟 = 基数 × N。
BAKE_RETRY_DELAY_MS: int = 400


def clamp(value: float, low: float, high: float) -> float:
    """把 ``value`` 钳制到 ``[low, high]``。

    Args:
        value: 待钳制的数值。
        low: 下界。
        high: 上界（小于 ``low`` 时返回 ``low``）。

    Returns:
        钳制后的数值。
    """
    if high < low:
        return low
    return max(low, min(high, value))


@dataclass(frozen=True)
class MicaParams:
    """用户可调的四项 Mica 参数（设置页滑动条 / 持久化 ``appearance.mica.*``）。

    Attributes:
        saturation: 背景色饱和度倍率，0–8，默认 4.5。
        contrast: 对比度倍率，0–3，默认 1.5。
        blur_radius: 背景模糊度，0–300 px，默认 200。
        tint_opacity: 叠加层透明度，0–100 %，默认 70。
    """

    saturation: float = PARAM_DEFAULTS["saturation"]
    contrast: float = PARAM_DEFAULTS["contrast"]
    blur_radius: float = PARAM_DEFAULTS["blur_radius"]
    tint_opacity: float = PARAM_DEFAULTS["tint_opacity"]

    @classmethod
    def from_mapping(cls, data: object) -> "MicaParams":
        """由任意映射（如 V2 设置字典）构造，缺失键取默认值、越界值钳制。

        Args:
            data: 键名同属性名的映射；``None`` 或非映射时返回全部默认值。

        Returns:
            规范化后的 :class:`MicaParams`。
        """
        if not isinstance(data, dict):
            return cls()
        values = {}
        for key, default in PARAM_DEFAULTS.items():
            raw = data.get(key, default)
            try:
                num = float(raw)
            except (TypeError, ValueError):
                num = default
            low, high = PARAM_BOUNDS[key]
            values[key] = clamp(num, low, high)
        return cls(**values)

    def replace(self, **changes: float) -> "MicaParams":
        """返回按 ``changes`` 覆盖并重新钳制后的新实例（不可变更新）。

        Args:
            **changes: 待覆盖的字段（键名同属性名）；``None`` 值被忽略。

        Returns:
            新的 :class:`MicaParams` 实例。
        """
        payload = {k: v for k, v in changes.items() if v is not None}
        if not payload:
            return self
        merged = {}
        for key in PARAM_DEFAULTS:
            value = float(payload.get(key, getattr(self, key)))
            low, high = PARAM_BOUNDS[key]
            merged[key] = clamp(value, low, high)
        return replace(self, **merged)

    def to_engine(self, dark: bool) -> "EngineParams":
        """把用户参数换算为引擎参数。

        映射公式（集中于此，避免散落到渲染代码）：

        * 色度增益 ``gain = saturation / 4.5``（默认 ⇒ 1.0）；
        * 色度上限倍率 ``cap_scale = contrast / 1.5``（默认 ⇒ 1.0）；
        * 色度低通标准差 ``sigma = 2 + (blur_radius / 300) × 38``
          （单位：**烘焙网格像素**，默认 ⇒ ≈27.3）；
        * 色调强度 ``alpha = tint_opacity / 100``（默认 ⇒ 0.70）。

        Args:
            dark: True 使用深色基色与深色色度上限，False 使用浅色。

        Returns:
            :class:`EngineParams`，可直接交给烘焙管线。
        """
        gain = max(0.0, self.saturation / SATURATION_REF)
        cap_scale = clamp(self.contrast / CONTRAST_REF, 0.0, CAP_SCALE_MAX)
        sigma = clamp(
            SIGMA_MIN + (self.blur_radius / 300.0) * (SIGMA_MAX - SIGMA_MIN),
            SIGMA_MIN,
            SIGMA_MAX,
        )
        alpha = clamp(self.tint_opacity / 100.0, 0.0, 1.0)
        return EngineParams(
            sigma=sigma,
            gain=gain,
            cap_scale=cap_scale,
            alpha=alpha,
            dark=dark,
        )


@dataclass(frozen=True)
class EngineParams:
    """烘焙管线消费的参数（由 :meth:`MicaParams.to_engine` 生成）。

    Attributes:
        sigma: 色度低通标准差，单位**烘焙网格像素**。
        gain: 色度增益（0 表示完全去色，仅保留基色）。
        cap_scale: 色度软上限倍率（相对深浅模式的基准值）。
        alpha: 色调强度，0 = 纯基色（无色调），1 = 完整「颜色」混合结果。
        dark: True = 深色模式。
    """

    sigma: float = 27.33
    gain: float = 1.0
    cap_scale: float = 1.0
    alpha: float = 0.70
    dark: bool = True

    def g1(self) -> Tuple[int, int, int]:
        """当前模式的 G1 基色 ``(r, g, b)``。"""
        return G1_DARK if self.dark else G1_LIGHT

    def chroma_cap(self) -> float:
        """当前模式的 Oklab 色度软上限。"""
        base = CHROMA_CAP_DARK if self.dark else CHROMA_CAP_LIGHT
        return max(0.0, base * self.cap_scale)


def bake_grid_size(win_w: int, win_h: int) -> Tuple[int, int]:
    """按窗口尺寸计算烘焙网格尺寸（长边不超过 :data:`BAKE_LONG_MAX`）。

    烘焙分辨率与窗口尺寸解耦是性能可控的关键：色调场是纯低频量，长边
    192 px 的网格在放大到 4K 窗口后仍与全分辨率结果肉眼无差，而烘焙耗时
    因此恒定在毫秒级。

    Args:
        win_w: 窗口宽度（像素）。
        win_h: 窗口高度（像素）。

    Returns:
        ``(grid_w, grid_h)``，均为 ≥1 的整数，且保持窗口宽高比。
    """
    w = max(1, int(win_w))
    h = max(1, int(win_h))
    long_side = max(w, h)
    target = min(BAKE_LONG_MAX, max(BAKE_LONG_MIN, long_side))
    if long_side <= target:
        return (w, h)
    scale = target / float(long_side)
    return (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
