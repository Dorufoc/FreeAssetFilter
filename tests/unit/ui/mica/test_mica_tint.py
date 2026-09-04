# -*- coding: utf-8 -*-
"""``ui.mica.tint`` 颜色混合与量化的回归测试（无 Qt、无显示器依赖）。

这里锁定的核心不变量是「柔和渐变、无噪点」：

* 关闭抖动后，量化必须是对 255 倍值的纯四舍五入，不引入任何随机偏移
  —— 否则网格级的抖动会被 Qt 双线性放大成块状噪点（磨砂玻璃感）。
* 关闭抖动后，同一次烘焙必须完全确定（两次跑出完全相同的字节），
  既无逐像素抖动，也无跨重绘闪烁。
"""

from __future__ import annotations

import numpy as np

from freeassetfilter.ui.mica import tint


def test_quantize_u8_no_dither_is_pure_rounding() -> None:
    """关闭抖动后量化必须是对 255 倍值的纯四舍五入，无任何随机偏移。"""
    vals = np.array(
        [[[0.0, 0.5 / 255, 1.0 / 255, 0.499 / 255, 254.4 / 255, 255.0 / 255]]],
        dtype=np.float32,
    )
    out = tint.quantize_u8(vals, dither=False)
    expected = np.clip(np.rint(vals * 255.0), 0.0, 255.0).astype(np.uint8)
    assert np.array_equal(out, expected)


def test_compose_tint_no_noise_dither() -> None:
    """颜色混合的最后一步必须确定性、不含随机噪点（磨砂玻璃根源已移除）。"""
    source = np.zeros((4, 4, 3), dtype=np.float32)
    out = tint.compose_tint(source, (0, 0, 0), alpha=0.8, dither=False)
    assert out.shape == (4, 4, 3)
    # 全零源在纯色混合下应得到完全相同的像素（无逐像素抖动）。
    # 注意：out 是 (4,4,3) 三维数组，out[0, 0] 是 (3,) 一维数组，
    # 必须用广播比较 np.all(... == ...) 而非形状敏感的 np.array_equal。
    assert np.all(out == out[0, 0])


def test_bake_tint_field_is_deterministic_without_dither() -> None:
    """关闭抖动后，同一输入两次烘焙必须产生完全相同的字节。"""
    rng = np.random.default_rng(0)
    crop = rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)
    a = tint.bake_tint_field(
        crop, (0, 0, 0), cap=0.05, gain=1.0, sigma=27.33, alpha=0.8, dither=False
    )
    b = tint.bake_tint_field(
        crop, (0, 0, 0), cap=0.05, gain=1.0, sigma=27.33, alpha=0.8, dither=False
    )
    assert a.image.shape == (64, 64, 3)
    assert np.array_equal(a.image, b.image)


def test_field_has_no_per_pixel_speckle() -> None:
    """低频色调场应是平滑渐变，相邻像素差不应出现噪点级跳变。

    这是「磨砂玻璃」消失的量化判据：同一行上相邻像素的逐通道差应远小于
    量化步长（1/255）量级的高频噪声。
    """
    rng = np.random.default_rng(1)
    crop = rng.integers(0, 255, (96, 96, 3), dtype=np.uint8)
    field = tint.bake_tint_field(
        crop, (0, 0, 0), cap=0.05, gain=1.0, sigma=27.33, alpha=0.8, dither=False
    )
    img = field.image.astype(np.int16)
    # 仅考察内部区域，避开边缘扩边的钳制边界。
    inner = img[4:-4, 4:-4]
    row_diff = np.abs(np.diff(inner, axis=1))
    col_diff = np.abs(np.diff(inner, axis=0))
    # 平滑低频场：绝大多数相邻差为 0 或 1，几乎不应出现 ≥3 的跳变。
    assert float((row_diff >= 3).mean()) < 0.02
    assert float((col_diff >= 3).mean()) < 0.02
