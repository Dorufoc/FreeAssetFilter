# -*- coding: utf-8 -*-
"""``ui.mica.drag`` 的纯几何 / 视口层测试（无 Qt、无显示器依赖）。

这里锁定的都是**视觉正确性** invariants，而非实现细节：

* **密度守恒** —— 视口层网格的密度必须等于常规烘焙的密度。这是"松手时不会
  出现糊→清晰跳变"的唯一保障，因为它保证 σ 相对窗口的物理半径不变。
* **层区域** —— 视口层覆盖整块监视器；任何位于监视器内的窗口都能取到子矩形。
* **分辨率无关映射** —— ``layer_to_source`` 由窗口矩形映射到层内子矩形，
  层分辨率与虚拟区域不同（被钳制）时仍正确。
* **1:1 恒等路径** —— 层分辨率等于虚拟区域时返回整数坐标（避免不必要的重采样）。
* **亚像素平滑** —— 源矩形必须是浮点的，否则放大后会出现台阶式抖动。
"""

from __future__ import annotations

import numpy as np
import pytest

from freeassetfilter.ui.mica.config import (
    BAKE_LONG_MAX,
    BAKE_LONG_MIN,
    MicaParams,
    bake_grid_size,
)
from freeassetfilter.ui.mica.drag import (
    LAYER_DISPLAY_LONG_MAX,
    LAYER_GRID_CAP,
    DragField,
    ViewportLayer,
    _window_scale,
    grid_for_region,
    layer_grid,
    layer_region_for,
    layer_to_source,
    layer_to_source_clamped,
)

_SIGMA = MicaParams().to_engine(dark=True).sigma

#: 覆盖常见窗口尺寸（含超宽、超小、小于网格长边）。
_WINDOW_SIZES = [(1600, 1000), (1000, 700), (600, 400), (200, 150), (3200, 900)]

#: 默认的拖动余量（虚拟像素），用于构造几何合法的 :class:`DragField`。
_DEFAULT_COVER: int = 240


def _field(
    win: tuple = (1600, 1000),
    cover: int = _DEFAULT_COVER,
    region_origin: tuple = (0, 0),
) -> DragField:
    """构造一块几何合法的占位拖动场（像素内容全 0，几何为真）。"""
    w, h = win
    grid = grid_for_region(w, h, cover)
    region = (
        region_origin[0],
        region_origin[1],
        w + 2 * cover,
        h + 2 * cover,
    )
    return DragField(
        image=np.zeros((grid[1], grid[0], 3), dtype=np.uint8),
        region=region,
        grid=grid,
        win_size=win,
        key=(),
        backend="test",
        duration_ms=1.0,
        cover=cover,
        quality=BAKE_LONG_MAX,
    )


# ---------------------------------------------------------------------------
# 密度守恒（视觉一致性的核心保证）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("win", _WINDOW_SIZES)
def test_grid_density_matches_normal_bake(win: tuple) -> None:
    """层/拖动网格的密度必须等于常规烘焙，否则松手会出现可见跳变。

    σ 以网格像素为单位，密度一变，色度低通相对窗口的物理半径就变了。
    """
    w, h = win
    grid = grid_for_region(w, h, _DEFAULT_COVER)
    normal_w, _ = bake_grid_size(w, h)

    grid_density = grid[0] / (w + 2 * _DEFAULT_COVER)
    assert grid_density == pytest.approx(normal_w / w, rel=5e-3)
    assert w * grid_density == pytest.approx(float(normal_w), abs=1.0)


def test_window_scale_equals_normal_density_at_max_quality() -> None:
    """``_window_scale`` 在最高画质档下与常规烘焙密度一致。"""
    scale = _window_scale(1600, 1000, BAKE_LONG_MAX)
    normal_w, _ = bake_grid_size(1600, 1000)
    assert scale == pytest.approx(normal_w / 1600, rel=1e-6)

    # 小窗口长边 < BAKE_LONG_MAX 时密度保持 1（不强行放大）。
    small_scale = _window_scale(200, 150, BAKE_LONG_MAX)
    assert small_scale == pytest.approx(1.0, abs=1e-6)


@pytest.mark.parametrize("win", _WINDOW_SIZES)
def test_grid_grows_with_cover_at_fixed_density(win: tuple) -> None:
    """余量翻倍时网格应按比例增大（密度不变），而非被压回长边上限。

    网格是整数，密度只能在 ``round()`` 的 ±0.5 网格像素量化误差内守恒，
    因此这里直接对照理想值断言，而不是拿两次取整结果相除（那会把量化误差
    放大到 0.3% 量级，反而掩盖真正的密度漂移）。
    """
    w, h = win
    scale = _window_scale(w, h, BAKE_LONG_MAX)
    small = grid_for_region(w, h, 100)
    large = grid_for_region(w, h, 200)
    assert large[0] > small[0]

    for cover, grid in ((100, small), (200, large)):
        assert abs(grid[0] - (w + 2 * cover) * scale) <= 0.5 + 1e-9
        assert abs(grid[1] - (h + 2 * cover) * scale) <= 0.5 + 1e-9


# ---------------------------------------------------------------------------
# DragField 偏移采样
# ---------------------------------------------------------------------------


def test_source_rect_covers_exactly_cover_px() -> None:
    """偏移采样应精确覆盖 ±cover；多一分是浪费，少一分会提前越界。"""
    field = _field(win=(1600, 1000))
    x0, y0 = _DEFAULT_COVER, _DEFAULT_COVER

    ok = [d for d in range(-1500, 1501) if field.source_rect((x0 + d, y0, 1600, 1000))]
    assert ok, "中心位置必须可取样"
    assert min(ok) == pytest.approx(-_DEFAULT_COVER, abs=1)
    assert max(ok) == pytest.approx(_DEFAULT_COVER, abs=1)


def test_source_rect_is_subpixel_smooth() -> None:
    """源矩形必须随位移连续变化 —— 取整会导致放大后台阶式抖动。"""
    field = _field(win=(1600, 1000))
    x0, y0 = _DEFAULT_COVER, _DEFAULT_COVER

    base = field.source_rect((x0, y0, 1600, 1000))
    step = field.source_rect((x0 + 1, y0, 1600, 1000))
    assert base is not None and step is not None

    delta = step[0] - base[0]
    assert 0.0 < abs(delta) < 1.0, "1 虚拟像素的位移必须落在亚像素区间"


def test_source_rect_rejects_out_of_range() -> None:
    """跑出覆盖范围应返回 ``None``，由上层回退到旧色调场。"""
    field = _field(win=(1600, 1000))
    x0, y0 = _DEFAULT_COVER, _DEFAULT_COVER
    assert field.source_rect((x0 + _DEFAULT_COVER + 50, y0, 1600, 1000)) is None
    assert field.source_rect((x0 - _DEFAULT_COVER - 50, y0, 1600, 1000)) is None
    assert field.source_rect((x0, y0 + _DEFAULT_COVER + 50, 1600, 1000)) is None


def test_source_rect_disabled_while_resizing() -> None:
    """缩放中窗口尺寸不可预测，偏移采样必须自行禁用。"""
    field = _field(win=(1600, 1000))
    x0, y0 = _DEFAULT_COVER, _DEFAULT_COVER
    assert field.source_rect((x0, y0, 1601, 1000)) is None
    assert field.source_rect((x0, y0, 1600, 1001)) is None


def test_source_rect_clamped_never_none_when_out_of_range() -> None:
    """越界时 ``source_rect`` 判 ``None``，``source_rect_clamped`` 钳制到网格边缘。"""
    field = _field(win=(1600, 1000))
    x0, y0 = _DEFAULT_COVER, _DEFAULT_COVER
    out_rect = (x0 + 5000, y0, 1600, 1000)
    assert field.source_rect(out_rect) is None
    clamped = field.source_rect_clamped(out_rect)
    assert clamped is not None
    gw = float(field.grid[0])
    dx = field.density[0]
    sw = 1600 * dx
    assert clamped[0] == pytest.approx(gw - sw, abs=1e-6)

    # 缩放中连同钳制路径也一并禁用。
    assert field.source_rect_clamped((x0, y0, 1601, 1000)) is None


def test_raw_rect_returns_none_on_resize() -> None:
    """``_raw_rect`` 在窗口尺寸与规划时不匹配（缩放中）返回 ``None``。"""
    field = _field(win=(1600, 1000))
    assert field._raw_rect((0, 0, 1600, 1000)) is not None
    assert field._raw_rect((0, 0, 1600, 1200)) is None
    rect = field._raw_rect((0, 0, 1600, 1000))
    assert rect is not None and len(rect) == 4 and all(isinstance(v, float) for v in rect)


# ---------------------------------------------------------------------------
# 层区域 / 网格密度 / σ 守恒
# ---------------------------------------------------------------------------


def test_layer_region_returns_monitor_rect() -> None:
    """视口层覆盖整块监视器（``monitor_rect`` 原样返回）。"""
    win = (100, 100, 1600, 1000)
    mon = (0, 0, 2560, 1440)
    assert layer_region_for(win, mon) == mon


def test_layer_region_not_clamped_by_window() -> None:
    """窗在监视器任意位置，层区域始终为整块监视器。"""
    mon = (0, 0, 2560, 1440)
    assert layer_region_for((100, 100, 600, 400), mon) == mon
    assert layer_region_for((2000, 1200, 600, 400), mon) == mon


def test_layer_grid_unclamped_matches_normal_density() -> None:
    """未钳制时层网格密度 == 常规烘焙密度，且 ``sigma_eff`` 保持原值。"""
    mon = (0, 0, 2560, 1440)
    win_w, win_h = 1600, 1000
    density = _window_scale(win_w, win_h, BAKE_LONG_MAX)
    grid, sigma_eff = layer_grid(mon, win_w, win_h, _SIGMA)
    assert grid[0] == pytest.approx(mon[2] * density, abs=1)
    assert grid[1] == pytest.approx(mon[3] * density, abs=1)
    assert sigma_eff == pytest.approx(_SIGMA, rel=1e-6)
    # 未钳制时密度守恒平凡成立。
    applied = grid[0] / mon[2]
    assert sigma_eff / applied == pytest.approx(_SIGMA / density, rel=1e-6)


def test_layer_grid_clamped_stays_within_cap_and_conserves_sigma() -> None:
    """双轴都被钳制时网格落在上限，且 σ 按密度比例回缩（物理半径不变）。"""
    mon = (0, 0, 9999999, 9999999)
    win_w, win_h = 1600, 1000
    density = _window_scale(win_w, win_h, BAKE_LONG_MAX)
    grid, sigma_eff = layer_grid(mon, win_w, win_h, _SIGMA)
    assert grid[0] == LAYER_GRID_CAP
    assert grid[1] == LAYER_GRID_CAP
    assert sigma_eff < _SIGMA
    applied = min(grid[0] / mon[2], grid[1] / mon[3])
    assert sigma_eff == pytest.approx(_SIGMA * (applied / density), rel=1e-6)
    assert sigma_eff / applied == pytest.approx(_SIGMA / density, rel=1e-6)


def test_layer_grid_one_axis_clamped_conserves_sigma() -> None:
    """宽轴被钳制、窄轴未钳制时，σ 守恒仍成立。"""
    mon = (0, 0, 6000, 3360)
    win_w, win_h = 1600, 1000
    density = _window_scale(win_w, win_h, BAKE_LONG_MAX)
    grid, sigma_eff = layer_grid(mon, win_w, win_h, _SIGMA)
    assert grid[0] == LAYER_GRID_CAP  # 宽轴被钳制
    assert grid[1] == pytest.approx(3360 * density, abs=1)  # 窄轴未钳制
    applied = min(grid[0] / mon[2], grid[1] / mon[3])
    assert sigma_eff / applied == pytest.approx(_SIGMA / density, rel=1e-6)


@pytest.mark.parametrize("mon_w, mon_h", [(2560, 1440), (6000, 3360), (50, 50), (9999999, 9999999)])
def test_layer_grid_bounds(mon_w: int, mon_h: int) -> None:
    """任意监视器尺寸下网格每轴都必须落在 ``[BAKE_LONG_MIN, LAYER_GRID_CAP]``。"""
    grid, _ = layer_grid((0, 0, mon_w, mon_h), 1600, 1000, _SIGMA)
    for dim in grid:
        assert BAKE_LONG_MIN <= dim <= LAYER_GRID_CAP


# ---------------------------------------------------------------------------
# 层 → 源子矩形映射（layer_to_source）
# ---------------------------------------------------------------------------


def test_layer_to_source_identity_integer_when_1to1() -> None:
    """层分辨率 == 虚拟区域（逐像素 1:1）且坐标为整数 → 返回整数坐标。"""
    layer = ViewportLayer(
        region=(0, 0, 2560, 1440), width=2560, height=1440, win_size=(1600, 1000)
    )
    src = layer_to_source(layer, (0, 0, 1600, 1000))
    assert src == (0, 0, 1600, 1000)
    assert all(isinstance(v, int) for v in src)


def test_layer_to_source_float_when_ratio_changed() -> None:
    """层分辨率与虚拟区域不同（被钳制/降密度）→ 恒返回浮点坐标。"""
    layer = ViewportLayer(
        region=(0, 0, 2560, 1440), width=512, height=288, win_size=(1600, 1000)
    )
    src = layer_to_source(layer, (192, 88, 1600, 1000))
    assert src is not None
    assert all(isinstance(v, float) for v in src)
    assert src[2] == pytest.approx(320.0, abs=1e-6)
    assert src[3] == pytest.approx(200.0, abs=1e-6)


def test_layer_to_source_rejects_outside_and_resize() -> None:
    """窗口部分/完全落在层区域之外，或尺寸不匹配（缩放中）→ 返回 ``None``。"""
    layer = ViewportLayer(
        region=(0, 0, 2560, 1440), width=512, height=288, win_size=(1600, 1000)
    )
    assert layer_to_source(layer, (-100, 0, 1600, 1000)) is None
    assert layer_to_source(layer, (0, -100, 1600, 1000)) is None
    assert layer_to_source(layer, (2560, 0, 1600, 1000)) is None
    assert layer_to_source(layer, (0, 1440, 1600, 1000)) is None
    assert layer_to_source(layer, (1000, 700, 1600, 1000)) is None
    assert layer_to_source(layer, (0, 0, 1800, 1000)) is None  # 缩放中


def test_layer_to_source_clamped_never_none_on_resize() -> None:
    """缩放中（窗口尺寸 != layer.win_size）``layer_to_source_clamped`` 仍返回子矩形。

    严格版 :func:`layer_to_source` 在尺寸不匹配时判 ``None``（回到旧行为），但
    钳制版必须对 resize 窗口返回合法子矩形 —— 否则 resize 后 Mica 会"消失"。
    """
    layer = ViewportLayer(
        region=(0, 0, 2560, 1440), width=512, height=288, win_size=(1600, 1000)
    )
    # 尺寸与烘焙时不一致（缩放中）且位置合法：严格版判 None，钳制版必须给出数值。
    resized = layer_to_source_clamped(layer, (0, 0, 1800, 1000))
    assert resized is not None
    assert len(resized) == 4
    assert resized[2] == pytest.approx(1800 * (512 / 2560), abs=1e-6)
    assert resized[3] == pytest.approx(1000 * (288 / 1440), abs=1e-6)


def test_layer_to_source_clamped_clamps_outside_region() -> None:
    """窗口部分/完全落在层区域之外 → 钳制到层边界，返回子矩形且 sx/sy >= 0。

    严格版判 ``None``；钳制版把越界的一轴钳到层边缘，保证可取样（Mica 不消失）。
    """
    layer = ViewportLayer(
        region=(0, 0, 2560, 1440), width=2560, height=1440, win_size=(1600, 1000)
    )
    # 窗口负 x（部分在层之外）：严格版 None，钳制版 sx 钳到 0。
    src = layer_to_source_clamped(layer, (-100, 0, 1600, 1000))
    assert src is not None
    assert src[0] >= 0.0 and src[1] >= 0.0
    # 窗口完全在右侧之外：钳到 [0, lw - sw]，sx 非负。
    right = layer_to_source_clamped(layer, (5000, 0, 1600, 1000))
    assert right is not None
    assert right[0] >= 0.0 and right[1] >= 0.0
    assert right[0] == pytest.approx(2560 - 1600, abs=1e-6)


def test_layer_to_source_clamped_clamps_to_full_extent_when_window_larger() -> None:
    """窗口尺寸超过层宽/高 → 该轴钳到层的全宽/全高（sx=0，无负坐标、不崩溃）。"""
    layer = ViewportLayer(
        region=(0, 0, 2560, 1440), width=512, height=288, win_size=(1600, 1000)
    )
    src = layer_to_source_clamped(layer, (100, 100, 9000, 7000))
    assert src is not None
    assert src[0] == 0.0 and src[1] == 0.0
    assert src[2] == pytest.approx(512.0, abs=1e-6)   # 钳到层的全宽
    assert src[3] == pytest.approx(288.0, abs=1e-6)   # 钳到层的全高


def test_layer_to_source_clamped_identity_integer_when_1to1() -> None:
    """层与虚拟区域 1:1 且坐标为整数、未越界 → 与严格版一致地返回整型坐标。"""
    layer = ViewportLayer(
        region=(0, 0, 2560, 1440), width=2560, height=1440, win_size=(1600, 1000)
    )
    src = layer_to_source_clamped(layer, (0, 0, 1600, 1000))
    assert src == (0, 0, 1600, 1000)
    assert all(isinstance(v, int) for v in src)


# ---------------------------------------------------------------------------
# 常量与数据模型
# ---------------------------------------------------------------------------


def test_layer_constants() -> None:
    """层网格上限与层显示长边必须保持固定值。"""
    assert LAYER_GRID_CAP == 1024
    assert LAYER_DISPLAY_LONG_MAX == 8192


def test_viewport_layer_fields() -> None:
    """``ViewportLayer`` 暴露几何所需的四个字段。"""
    layer = ViewportLayer(region=(0, 0, 2560, 1440), width=512, height=288, win_size=(1600, 1000))
    assert layer.region == (0, 0, 2560, 1440)
    assert layer.width == 512
    assert layer.height == 288
    assert layer.win_size == (1600, 1000)
