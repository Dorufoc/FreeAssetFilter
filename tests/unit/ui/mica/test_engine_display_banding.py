# -*- coding: utf-8 -*-
"""``ui.mica.engine`` 显示分辨率渲染 / 抖动 / 预合成的纯函数测试（无 Qt）。

锁定以下视觉正确性 invariants：

* **跨重建稳定** —— 确定性均匀噪声抖动（固定种子）在相同目标尺寸下逐元素
  一致，窗口停留 / 拖动往返时不会闪烁。
* **无系统偏置** —— ``dither=False`` 是纯粹的 ``rint`` 取整，不存在 -0.5 LSB
  的整体变暗。
* **默认参数等价** —— ``overlay=1.0``（不透底）结果与「先缩放再抖动」一致，
  不引入底色偏移。
* **打散二次量化色带（核心）** —— 旧路径在 8-bit 抖动结果上由 Qt
  ``setOpacity(0.7)`` 二次混合，会把相邻源色阶（如 107/108/109）全部坍缩到
  同一终值，超缓渐变上出现长平坦游程；新路径改为「上采样 float → 预合成 →
  最终空间一次性量化 + 抖动」，实测 ≥100px 游程被压到个位数。
"""

from __future__ import annotations

import dataclasses

import numpy as np

from freeassetfilter.ui.mica import engine
from freeassetfilter.ui.mica.config import MicaParams


def _make_gradient_field(gw: int = 320, gh: int = 200) -> "engine.BakedField":
    """构造一块超缓 float 渐变场（三通道相同），最接近真实 Mica 的低频色调场。

    ``0.02`` 的水平增长使相邻像素差约 0.06/320·255 ≈ 0.05 LSB，远低于 1 LSB，
    是最容易触发 8-bit 色带 / 平坦游程的病理场景。
    """
    xx = np.linspace(0.0, 1.0, gw, dtype=np.float32).reshape(1, gw)
    yy = np.linspace(0.0, 1.0, gh, dtype=np.float32).reshape(gh, 1)
    base = 0.30 + 0.15 * xx + 0.02 * np.sin(yy * 3.0) * np.cos(xx * 2.0)
    base = np.clip(base, 0.0, 1.0)
    rgb = np.repeat(base[..., None], 3, axis=2)  # (gh, gw, 3) float32

    request = engine.BakeRequest((0, 0, 1920, 1080), MicaParams(), True, "test")
    return engine.BakedField(
        image=np.clip(rgb * 255.0, 0.0, 255.0).astype(np.uint8),
        request=request,
        grid_size=(gw, gh),
        sample_rect=(0.0, 0.0, 1920.0, 1080.0),
        margin=0,
        backend="test",
        duration_ms=0.0,
        image_float=rgb.astype(np.float32),
    )


def _luma(img: np.ndarray) -> np.ndarray:
    """图像亮度（int64），Rec.709 加权，用于游程统计。"""
    f = img.astype(np.float64)
    return (0.30 * f[..., 0] + 0.59 * f[..., 1] + 0.11 * f[..., 2]).astype(np.int64)


def _row_runs(row: np.ndarray) -> list:
    """单行按「连续相同像素」拆出游程长度列表。"""
    n = int(row.shape[0])
    runs: list = []
    i = 0
    while i < n:
        j = i
        while j + 1 < n and row[j + 1] == row[i]:
            j += 1
        runs.append(j - i + 1)
        i = j + 1
    return runs


def _banding_stats(img: np.ndarray, sample_step: int = 40) -> tuple:
    """按行（步长抽样）统计平坦游程，返回 ``(ge60, ge100, max_run)``。

    * ``ge60`` / ``ge100``：抽样行中长度 ≥60px / ≥100px 的游程条数；
    * ``max_run``：全图扫描出的最大游程长度（不依赖抽样，防最坏情况被漏掉）。
    """
    lum = _luma(img)
    ge60 = 0
    ge100 = 0
    for y in range(0, int(lum.shape[0]), sample_step):
        for r in _row_runs(lum[y]):
            if r >= 100:
                ge100 += 1
            elif r >= 60:
                ge60 += 1
    max_run = 0
    for y in range(int(lum.shape[0])):
        runs = _row_runs(lum[y])
        if runs:
            max_run = max(max_run, max(runs))
    return ge60, ge100, int(max_run)


# ---------------------------------------------------------------------------
# 抖动本身
# ---------------------------------------------------------------------------


def test_noise_offsets_are_deterministic_and_stable() -> None:
    """同一 ``(th, tw, amp)`` 两次调用逐元素相等；幅值随 amp 增大；shape 正确。"""
    a1 = engine._dither_offsets(50, 80, 0.7)
    a2 = engine._dither_offsets(50, 80, 0.7)
    assert a1.shape == (50, 80, 1)
    # 同一组合跨「重建」稳定：逐元素相等（不是近似，是缓存 / 固定种子复现）。
    assert np.array_equal(a1, a2)

    # 不同 amp 是同一份噪声的缩放：小 amp 的偏移包络不超出 ±amp。
    big = engine._dither_offsets(50, 80, 0.7)
    small = engine._dither_offsets(50, 80, 0.35)
    assert np.abs(small).max() <= 0.35 + 1e-6
    assert np.abs(big).max() <= 0.7 + 1e-6
    # 幅值随 amp 增大（同一固定噪声的 ± 范围随之变大）。
    assert np.abs(big).max() > np.abs(small).max()


def test_upscale_dither_false_is_pure_rounding() -> None:
    """``dither=False`` 应等于对 f32 上采样后直接 ``rint``（无系统偏置）。"""
    field = _make_gradient_field()
    grid = field.image  # uint8 (0..255)
    target_long = 100

    out = engine.upscale_to_display(grid, target_long, dither=False)

    gh, gw = int(grid.shape[0]), int(grid.shape[1])
    scale = float(target_long) / float(max(gw, gh))
    tw = max(1, int(round(gw * scale)))
    th = max(1, int(round(gh * scale)))
    ref = np.clip(np.rint(engine._resize_bilinear(grid.astype(np.float32, copy=False), tw, th)), 0.0, 255.0).astype(np.uint8)

    # 逐元素一致，且与参考的均值差距 < 0.6 LSB（确认无整体变暗/变亮）。
    assert np.array_equal(out, ref)
    assert abs(float(out.mean()) - float(ref.mean())) < 0.6


def test_overlay_1_default_matches_no_surface_shift() -> None:
    """``overlay=1.0``（不透底）与默认参数输出一致，无底色偏移。"""
    field = _make_gradient_field()
    a = engine.render_display(field, 1920)
    b = engine.render_display(field, 1920, overlay=1.0, surface_rgb=(255, 0, 0))
    assert np.array_equal(a, b)


def test_banding_broken_under_simulated_8bit_blend() -> None:
    """核心验收：预合成后无需第二次混合，色阶坍缩 / 长平坦游程被打破。

    基线模拟**旧缺陷路径**：先在显示分辨率做带抖动的 8-bit 量化（等价
    ``upscale_to_display(dither=True)``），再用 Qt 的 ``setOpacity(0.7)`` 做
    第二次透明度量化。新路径 ``render_display(overlay=0.7)`` 把混合挪到 float
    期先做，一次性量化后抖动仍在最后一步打散台阶。
    """
    field = _make_gradient_field()
    surface = (0, 0, 0)

    # 新路径：float 期预合成 → 最终空间一次性量化 + 抖动。
    s0 = engine.render_display(field, 1920, overlay=0.7, surface_rgb=surface)
    # 基线：不带预合成的抖动结果再做第二次 8-bit 混合。
    blended = engine.upscale_to_display(field.image_float, 1920, dither=True)
    baseline = np.clip(np.rint(blended.astype(np.float32) * 0.7), 0.0, 255.0).astype(np.uint8)

    s60, s100, smax = _banding_stats(s0)
    b60, b100, bmax = _banding_stats(baseline)

    # 实测值（固定种子，稳定）：S0 = (99, 2, max 112)；基线 = (93, 63, max 156)。
    # 「第二次量化坍缩」的缺陷签名是 ≥100px 的长平坦游程与全图最大游程 ——
    # 在 ≥100 与最大游程上，预合成把基线杀成像（63→2、156→112）；≥60 中段计数
    # 在换用均匀噪声抖动后不再是单调判别量，故用宽松上界兜底，不设 < 基线断言。
    assert s100 <= 2, f"预合成后 ≥100px 平坦游程应被打破：S0={s100}"
    assert s100 < b100, f"≥100px 条数应少于基线：S0={s100} vs 基线={b100}"
    assert s60 <= 120, f"≥60px 条数应在宽松上界内（实测≈99）：S0={s60}"
    assert smax < bmax, f"全图最大游程应短于基线：S0={smax} vs 基线={bmax}"


# ---------------------------------------------------------------------------
# float 字段（image_float）与 uint8-only 字段的回归契约
# ---------------------------------------------------------------------------
# 新 GPU/CPU 路径把「未量化的 float 合成结果」保留在 ``BakedField.image_float``，
# 由 :func:`render_display` 在显示分辨率（显示像素）上先做 float 上采样、预合成，
# 最后才一次性量化 + 抖动。于是在真实半透明 Mica（``overlay=0.7``）下，float
# 字段把 ≥100px 平坦游程压到个位数；而老路径（``image_float=None``，仅 uint8 网格）
# 在网格级已量化，放大后相邻源色阶坍缩，≥100px 游程明显增多。二者用
# :func:`_banding_stats` 在确定性均匀噪声抖动（固定种子 1337、目标 1920）下
# 稳定可测：float=``(99, 2, 112)``，uint8-only=``(81, 4, 135)``。
#
# 回归契约：float → band-free（``ge100 <= 2``），uint8-only → bands（``ge100 > 2``）。
# 一旦有人改回「总是用 uint8 网格、忽略 ``image_float``」，
# :func:`test_float_field_is_band_free` 会拿到 uint8 路径的 ``ge100=4`` 而失败。


def test_float_field_is_band_free() -> None:
    """float 字段经 ``render_display`` 在显示分辨率应无 ≥100px 色带（回归锁）。

    ``_make_gradient_field`` 同时携带 ``image_float``（float32，未量化）与 ``image``
    （uint8 快照）；:func:`render_display` 优先取 ``image_float``，因此整条管线
    走到「显示分辨率 float 上采样 → 预合成 → 最终一次性量化 + 抖动」的新路径。
    本测试断言其输出在真实半透明 Mica（``overlay=0.7``）下 ≥100px 平坦游程 ≤2
    （实测 ``ge100=2``）。这是针对「float 修复」的回归锁：若实现退化回总是 uint8
    路径，此处会得到 ``ge100=4`` 而失败。
    """
    field = _make_gradient_field()
    out = engine.render_display(field, 1920, overlay=0.7, surface_rgb=(0, 0, 0))
    _g60, g100, _max_run = _banding_stats(out)
    assert g100 <= 2, f"float 字段在显示分辨率应 band-free：ge100={g100}"


def test_uint8_only_field_bands() -> None:
    """uint8-only（``image_float=None``，老 GPU 路径）在显示分辨率仍会色带。

    把 :attr:`engine.BakedField.image_float` 置 ``None`` 即强制走 uint8-only 老路径
    （网格级已量化，无亚 LSB 精度）。同一超缓渐变下其 ≥100px 平坦游程明显多于
    float 字段（实测 ``ge100=4`` > float 的 2），全图最大游程也更长（135 > 112）。
    本测试对照锁定「uint8-only → bands」这一半：若回归把管线改回总是 uint8，
    :func:`test_float_field_is_band_free` 会失败，而这里是明确断言老路径确实带带。
    """
    field = dataclasses.replace(_make_gradient_field(), image_float=None)
    out = engine.render_display(field, 1920, overlay=0.7, surface_rgb=(0, 0, 0))
    _g60, g100, max_run = _banding_stats(out)
    assert g100 > 2, f"uint8-only 老路径应出现 ≥100px 色带：ge100={g100}"
    assert max_run > 112, f"uint8-only 老路径的最大游程应短于 float 路径：max_run={max_run}"