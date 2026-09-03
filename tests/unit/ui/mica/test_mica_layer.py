# -*- coding: utf-8 -*-
"""``ui.mica.drag`` 视口层 + ``ui.mica.material`` 层拖动行为的**层级**验收测试。

锁定的五组不变量：

* **层等变性（核心正确性）** —— 在位置 ``P`` 烘一块覆盖整块监视器的层，再从层里
  按位移 ``d`` 取子矩形（``layer_to_source``）并重采样，必须**逐像素重现**直接在
  ``P+d`` 跑一次常规烘焙 + ``render_display`` 的结果（平均绝对差 < 1.5/255，
  p99 ≤ 4）。这是「一次烘焙 + 逐帧偏移」这整套方案的基石。
* **拖动期零重烘焙** —— 窗口在监视器内平移时 ``_layer_gen`` 保持稳定（0 次烘焙）。
* **密度 / σ 守恒** —— 层网格被钳制时 ``sigma_eff / applied_density`` 保持
  ``sigma / density`` 恒定（物理模糊半径不变）。
* **深浅两模式 band-free + 基色正确** —— ``render_display`` 在 float 场上对深/浅
  参数都是 band-free，中性输入下平均色对齐深色 ``#1a1a1a`` / 浅色 ``#f5f5f5``。
* **1:1 vs 亚像素绘制路径** —— ``layer_to_source`` 在层与虚拟区域 1:1 且坐标
  整型时返回整数坐标；否则返回浮点坐标。
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtWidgets import QWidget

from freeassetfilter.ui.mica import engine
from freeassetfilter.ui.mica import material as material_mod
from freeassetfilter.ui.mica.config import (
    BAKE_LONG_MAX,
    G1_DARK,
    G1_LIGHT,
    MicaParams,
    bake_grid_size,
)
from freeassetfilter.ui.mica.drag import (
    LAYER_GRID_CAP,
    ViewportLayer,
    _window_scale,
    layer_grid,
    layer_to_source,
)
from freeassetfilter.ui.mica.resample import crop_f32, crop_resize
from freeassetfilter.ui.mica.source import DesktopInfo, MonitorInfo, WallpaperSource

#: 等变性测试的窗口尺寸 / 监视器 / 参考位置。
_WIN = (800, 600)
_MON = (0, 0, 2560, 2000)
_ORIGIN = (512, 400)
#: 一组位移（含 0 与若干整数位移，使层内子矩形原点落在亚像素坐标上）。
_OFFSETS = [(0, 0), (37, 23), (-60, 40), (120, -85), (-150, -95)]


# ---------------------------------------------------------------------------
# 壁纸源工厂（确定性，无 GPU）
# ---------------------------------------------------------------------------


def _make_source(monitor: tuple = _MON) -> WallpaperSource:
    """构造一块确定性的、空间缓变的彩色画布（用于等变性测试）。

    色度带空间结构但平滑（远高于 σ 的物理半径），保证层子矩形取样与直接烘焙
    之间存在**真实但微小**的插值差 —— 既非零（证明测试不是干跑），也不超过
    1.5/255 容差。
    """
    w, h = int(monitor[2]), int(monitor[3])
    xx = np.linspace(0.0, 6.28, w, dtype=np.float32).reshape(1, w)
    yy = np.linspace(0.0, 6.28, h, dtype=np.float32).reshape(h, 1)
    r = 0.5 + 0.4 * np.sin(xx) * np.cos(yy * 0.7)
    g = 0.5 + 0.3 * np.sin(xx * 1.3 + 1.0) * np.cos(yy * 1.1)
    b = 0.5 + 0.35 * np.sin(xx * 0.8 + 2.0) * np.cos(yy * 1.6)
    rgb = np.concatenate([r[..., None], g[..., None], b[..., None]], axis=2)
    pix = (np.clip(rgb, 0.0, 1.0) * 255.0).astype(np.uint8)
    info = DesktopInfo(
        virtual_rect=monitor,
        monitors=(MonitorInfo(rect=monitor),),
        position="Fill",
        background_rgb=(0, 0, 0),
        source="test",
    )
    return WallpaperSource(
        pixels=pix,
        origin=(int(monitor[0]), int(monitor[1])),
        scale=1.0,
        backend="test",
        info=info,
        signature="test-src",
    )


def _make_neutral_source(gray: int, monitor: tuple = (0, 0, 1920, 1080)) -> WallpaperSource:
    """构造一块纯灰（无色度）画布，用于基色 / band-free 测试。"""
    w, h = int(monitor[2]), int(monitor[3])
    pix = np.full((h, w, 3), gray, dtype=np.uint8)
    info = DesktopInfo(
        virtual_rect=monitor,
        monitors=(MonitorInfo(rect=monitor),),
        position="Fill",
        background_rgb=(0, 0, 0),
        source="neutral",
    )
    return WallpaperSource(
        pixels=pix,
        origin=(int(monitor[0]), int(monitor[1])),
        scale=1.0,
        backend="test",
        info=info,
        signature="neutral",
    )


# ---------------------------------------------------------------------------
# 1) 层等变性
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("offset", _OFFSETS)
def test_layer_equivariance_matches_direct_bake(offset: tuple) -> None:
    """``layer_to_source`` 子矩形取样必须重现一次直接烘焙 + ``render_display``。

    两层对照：
    * **网格级** —— ``crop_resize``（u8，重现 ``verify_drag_equivariance.py``）
      对比直接烘焙的 ``field.image``；
    * **显示级** —— 把取样结果重建为字段后 ``render_display`` 对比直接烘焙的
      ``render_display`` 输出。
    """
    source = _make_source(monitor=_MON)
    params = MicaParams()
    dark = True
    sigma = params.to_engine(dark).sigma
    grid, sigma_eff = layer_grid(_MON, _WIN[0], _WIN[1], sigma)
    # 该监视器下密度恰为上限，未被钳制：sigma_eff 应等于原值。
    assert sigma_eff == pytest.approx(sigma, rel=1e-6)

    layer = ViewportLayer(region=_MON, width=grid[0], height=grid[1], win_size=_WIN)
    layer_field = engine.bake_with_grid(
        engine.BakeRequest(_MON, params, dark, "eq"), source, grid
    )

    moved = (_ORIGIN[0] + offset[0], _ORIGIN[1] + offset[1], _WIN[0], _WIN[1])
    src = layer_to_source(layer, moved)
    assert src is not None, "位移后的窗口必须落在层区域内"
    ref_grid = bake_grid_size(*_WIN)

    # --- 网格级：真实取样 vs 直接烘焙的 u8 网格场 ---
    sampled_u8 = crop_resize(layer_field.image, src, ref_grid[0], ref_grid[1])
    ref_field = engine.bake(engine.BakeRequest(moved, params, dark, "eq"), source)
    diff = np.abs(sampled_u8.astype(np.int16) - ref_field.image.astype(np.int16))
    mean = float(diff.mean())
    p99 = float(np.percentile(diff, 99))
    assert mean > 0.0, "必须在真实差异（非干跑）：平均差应 > 0"
    assert mean < 1.5, f"网格级平均差 {mean:.4f} 应 < 1.5/255"
    assert p99 <= 4.0, f"网格级 p99 {p99:.2f} 应 <= 4"

    # --- 显示级：把取样结果重建为字段后 render_display 对齐 ---
    sampled_f32 = crop_f32(layer_field.image_float, src, ref_grid[0], ref_grid[1])
    synth = engine.BakedField(
        image=None,
        request=engine.BakeRequest(moved, params, dark, "eq"),
        grid_size=ref_grid,
        sample_rect=src,
        margin=0,
        backend="test",
        duration_ms=0.0,
        image_float=sampled_f32.astype(np.float32),
    )
    disp_sampled = engine.render_display(synth, 800, 0.7, (0, 0, 0))
    disp_ref = engine.render_display(ref_field, 800, 0.7, (0, 0, 0))
    d2 = np.abs(disp_sampled.astype(np.int16) - disp_ref.astype(np.int16))
    assert float(d2.mean()) < 1.5, f"render_display 平均差 {float(d2.mean()):.4f} 应 < 1.5/255"
    assert float(np.percentile(d2, 99)) <= 4.0, "render_display p99 应 <= 4"


# ---------------------------------------------------------------------------
# 2) 拖动期零重烘焙
# ---------------------------------------------------------------------------


def test_no_rebake_during_in_monitor_drag(qapp, monkeypatch) -> None:
    """窗口在监视器内多次平移，``_layer_gen`` 保持稳定（0 次重烘焙）。"""
    widget = QWidget()
    mica = material_mod.MicaMaterial(widget, lazy=True)
    mon = (0, 0, 2560, 1440)
    key = ("params", True, "sig", mon, 2560)
    mica._layer = ViewportLayer(region=mon, width=512, height=288, win_size=(1600, 1000))
    mica._layer_key = key
    mica._layer_display_long = 2560
    monkeypatch.setattr(mica, "_monitor_rect_for", lambda window_rect: mon)
    monkeypatch.setattr(mica, "_layer_key_for", lambda region, dl: key)

    try:
        for pos in [(100, 100), (300, 400), (700, 200), (1500, 800)]:
            monkeypatch.setattr(
                mica, "_window_rect_tuple", lambda p=pos: (p[0], p[1], 1600, 1000)
            )
            before = mica._layer_gen
            mica.begin_interaction()
            assert mica._layer_gen == before, "监视器内平移不得触发层重烘焙"
    finally:
        mica.dispose()
        widget.deleteLater()


# ---------------------------------------------------------------------------
# 3) 密度 / σ 守恒
# ---------------------------------------------------------------------------


def test_sigma_conservation_unclamped() -> None:
    """未钳制时 ``sigma_eff/applied_density == sigma/density``（平凡成立）。"""
    win = (1600, 1000)
    mon = (0, 0, 2560, 1440)
    density = _window_scale(win[0], win[1], BAKE_LONG_MAX)
    sigma = MicaParams().to_engine(dark=True).sigma
    grid, sigma_eff = layer_grid(mon, win[0], win[1], sigma)
    assert sigma_eff == pytest.approx(sigma, rel=1e-9)
    applied = grid[0] / mon[2]
    assert sigma_eff / applied == pytest.approx(sigma / density, rel=1e-6)


def test_sigma_conservation_clamped() -> None:
    """宽轴被钳制到上限时，σ 按实际密度回缩，物理模糊半径仍不变。"""
    win = (1600, 1000)
    mon = (0, 0, 6000, 3360)
    density = _window_scale(win[0], win[1], BAKE_LONG_MAX)
    sigma = MicaParams().to_engine(dark=True).sigma
    grid, sigma_eff = layer_grid(mon, win[0], win[1], sigma)
    assert grid[0] == LAYER_GRID_CAP, "宽轴应被钳制到层网格上限"
    applied = min(grid[0] / mon[2], grid[1] / mon[3])
    assert sigma_eff == pytest.approx(sigma * (applied / density), rel=1e-6)
    assert sigma_eff / applied == pytest.approx(sigma / density, rel=1e-6)


# ---------------------------------------------------------------------------
# 4) 深 / 浅两模式 band-free + 基色正确
# ---------------------------------------------------------------------------


def _banding_stats(img: np.ndarray) -> tuple:
    """统计亮度平坦游程，返回 ``(ge100, max_run)``。"""
    lum = (0.30 * img[..., 0] + 0.59 * img[..., 1] + 0.11 * img[..., 2]).astype(np.int64)
    ge100 = 0
    max_run = 0
    for y in range(int(lum.shape[0])):
        row = lum[y]
        n = int(row.shape[0])
        i = 0
        while i < n:
            j = i
            while j + 1 < n and row[j + 1] == row[i]:
                j += 1
            run = j - i + 1
            max_run = max(max_run, run)
            if y % 40 == 0 and run >= 100:
                ge100 += 1
            i = j + 1
    return ge100, int(max_run)


@pytest.mark.parametrize("dark, base", [(True, G1_DARK), (False, G1_LIGHT)])
def test_render_display_band_free_and_correct_base(dark: bool, base: tuple) -> None:
    """中性输入下，render_display 的 float 场 band-free 且平均色对齐 G1 基色。"""
    source = _make_neutral_source(gray=128, monitor=(0, 0, 1920, 1080))
    params = MicaParams()
    field = engine.bake(engine.BakeRequest((0, 0, 1920, 1080), params, dark, "neutral"), source)
    disp = engine.render_display(field, 1920, 1.0, (0, 0, 0))

    mean = disp.reshape(-1, 3).mean(axis=0)
    assert np.allclose(mean, np.asarray(base, dtype=float), atol=3.0), (
        f"中性输入应得到 {base}（深=#1a1a1a 浅=#f5f5f5），实际 {np.round(mean, 1)}"
    )

    ge100, max_run = _banding_stats(disp)
    assert ge100 == 0, "不应出现 ≥100px 平坦游程（band-free）"
    assert max_run < 100


# ---------------------------------------------------------------------------
# 5) 1:1 vs 亚像素绘制路径
# ---------------------------------------------------------------------------


def test_layer_to_source_integer_when_1to1_integer_coords() -> None:
    """层与虚拟区域 1:1 且窗口坐标为整数 → 返回整数坐标（真 1:1 blit）。"""
    layer = ViewportLayer(region=(0, 0, 2560, 1440), width=2560, height=1440, win_size=(1600, 1000))
    src = layer_to_source(layer, (0, 0, 1600, 1000))
    assert src == (0, 0, 1600, 1000)
    assert all(isinstance(v, int) for v in src)


def test_layer_to_source_float_otherwise() -> None:
    """层与虚拟区域不同分辨率（或尺寸不匹配）→ 返回浮点坐标（亚像素平滑）。"""
    ratio_changed = ViewportLayer(region=(0, 0, 2560, 1440), width=512, height=288, win_size=(1600, 1000))
    src = layer_to_source(ratio_changed, (0, 0, 1600, 1000))
    assert src is not None
    assert all(isinstance(v, float) for v in src)

    # 窗口尺寸与烘焙时不匹配（缩放中）→ None。
    assert layer_to_source(ratio_changed, (0, 0, 1800, 1000)) is None
