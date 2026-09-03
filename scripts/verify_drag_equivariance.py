# -*- coding: utf-8 -*-
"""实证验证拖动偏移采样的**平移等变性**。

这是整套拖动跟随方案的正确性基石，必须实测而非只靠几何推导：

    DragField[窗口在 P+d 处的子矩形]  ==  Bake(窗口矩形 = P+d)

若二者不等价，"一次烘焙 + 逐帧偏移"就只是几何上自洽、像素上却是错的 ——
用户会看到拖动时颜色与松手后不一致。

验证方法
--------
在真实壁纸上，对同一窗口矩形做两次：

1. **基准**：在位置 ``P + d`` 跑一次常规完整烘焙；
2. **取样**：在位置 ``P`` 烘一块放大拖动场，从中按位移 ``d`` 取子矩形。

比较二者的 uint8 像素差。差异来源只有三处，都应当很小：

* 网格密度相同 ⇒ 采样点几乎重合（``round()`` 取整带来的亚像素差）；
* 扩边方式相同 ⇒ 边缘钳制一致（只要取样点远离拖动场外边界）；
* 双线性重采样把子矩形放大回窗口尺寸，引入插值误差。

因此判据定为：**平均绝对差 < 1.5 / 255，p99 ≤ 4**（与 GPU/CPU 一致性验证
同量级）。为避开拖动场外边界的钳制差异，取样位移限制在余量的 60% 以内。

运行::

    python scripts/verify_drag_equivariance.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import List, Tuple

import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parent
while not (_PROJECT_ROOT / "freeassetfilter").is_dir():
    if _PROJECT_ROOT.parent == _PROJECT_ROOT:
        raise SystemExit("找不到项目根目录")
    _PROJECT_ROOT = _PROJECT_ROOT.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from freeassetfilter.ui.mica.config import MicaParams, bake_grid_size  # noqa: E402
from freeassetfilter.ui.mica.drag import (  # noqa: E402
    DRAG_COVER_DEFAULT_PX,
    DragSampler,
)
from freeassetfilter.ui.mica.engine import BakeRequest, bake, bake_with_grid  # noqa: E402
from freeassetfilter.ui.mica.gpu import gpu_available, gpu_bake  # noqa: E402
from freeassetfilter.ui.mica.resample import crop_resize  # noqa: E402
from freeassetfilter.ui.mica.source import WallpaperProvider  # noqa: E402

_WIN_SIZES: List[Tuple[int, int]] = [(1600, 1000), (1000, 700), (600, 400)]
_OFFSETS: List[Tuple[int, int]] = [(0, 0), (37, 23), (-60, 40), (120, -85), (-150, -95)]

_MEAN_TOLERANCE = 1.5
_P99_TOLERANCE = 4


def _bake_at(rect, params, dark, sig, grid=None):
    """在给定矩形上烘焙，返回网格分辨率的 uint8 色调场。"""
    request = BakeRequest(
        window_rect=rect, params=params, dark=dark, source_signature=sig
    )
    if grid is None:
        field = gpu_bake(request, _SOURCE)
    else:
        field = gpu_bake(request, _SOURCE, grid_size=grid)
    return field.image, field.duration_ms, getattr(field, "backend", "cpu")


def _sample(field_img, src_rect, out_size) -> np.ndarray:
    """按浮点子矩形双线性取样，重采样到 **网格分辨率**。

    与 Qt 的 ``drawPixmap(QRectF, pixmap, QRectF)`` 语义一致：浮点源矩形、
    像素中心对齐、边缘钳制。此处输出到常规烘焙的网格分辨率，因为
    :func:`bake` 返回的正是网格分辨率 —— 二者必须在同一分辨率下比较，
    否则比的是插值器而不是管线本身（后续放大到窗口尺寸对两者完全相同）。
    """
    return crop_resize(field_img, src_rect, out_size[0], out_size[1])


def main() -> int:
    global _SOURCE
    print("=" * 78)
    print("拖动偏移采样 · 平移等变性验证")
    print("=" * 78)

    provider = WallpaperProvider()
    source = provider.acquire()
    if source is None or source.pixels.size == 0:
        print("无法获取壁纸源，跳过验证")
        return 0
    _SOURCE = source
    print(
        f"壁纸后端 = {source.backend}, "
        f"画布 = {source.pixels.shape[1]}x{source.pixels.shape[0]}"
    )
    print(f"GPU 可用 = {gpu_available()}\n")

    params = MicaParams()
    sig = provider.probe().signature()
    dark = True
    origin = (400, 260)

    # 预热：首次烘焙要建 GPU 上下文、解码画布、编译着色器，耗时不可比。
    _bake_at((origin[0], origin[1], 800, 600), params, dark, sig)
    _bake_at((origin[0], origin[1], 1600, 1000), params, dark, sig, grid=(269, 197))
    print("（已预热）\n")

    failures = 0
    for win in _WIN_SIZES:
        sampler = DragSampler()
        sampler.note_bake(3.0)
        plan = sampler.plan_for((origin[0], origin[1], win[0], win[1]), (0.0, 0.0),
                                params.to_engine(dark).sigma)
        grid = plan.grid
        ref_grid = bake_grid_size(*win)

        t0 = time.perf_counter()
        drag_img, _, backend = _bake_at(
            (plan.region[0], plan.region[1], plan.region[2], plan.region[3]),
            params, dark, sig, grid=grid,
        )
        drag_ms = (time.perf_counter() - t0) * 1000.0

        print(f"窗口 {win[0]}x{win[1]}  拖动场 grid={grid}  cover={plan.cover}  "
              f"常规 grid={ref_grid}  后端={backend}  拖动场烘焙 {drag_ms:.1f} ms")

        limit = int(plan.cover * 0.6)
        for dx, dy in _OFFSETS:
            if abs(dx) > limit or abs(dy) > limit:
                continue
            moved = (origin[0] + dx, origin[1] + dy, win[0], win[1])
            src = _source_rect(plan, moved)
            if src is None:
                print(f"  位移 {dx:+5d},{dy:+5d}  越界（不应发生）")
                failures += 1
                continue

            t1 = time.perf_counter()
            sampled = _sample(drag_img, src, ref_grid)
            sample_ms = (time.perf_counter() - t1) * 1000.0
            reference, ref_ms, _ = _bake_at(moved, params, dark, sig)

            diff = np.abs(sampled.astype(np.int16) - reference.astype(np.int16))
            mean = float(diff.mean())
            p99 = float(np.percentile(diff, 99))
            ok = mean < _MEAN_TOLERANCE and p99 <= _P99_TOLERANCE
            failures += 0 if ok else 1
            print(f"  位移 {dx:+5d},{dy:+5d}  平均差={mean:5.2f}  p99={p99:4.1f}  "
                  f"最大={int(diff.max()):3d}  取样={sample_ms:4.2f} ms  "
                  f"重烘焙={ref_ms:5.1f} ms  {'OK' if ok else 'FAIL'}")

    print("\n" + "=" * 78)
    print(f"结论：{'全部通过' if failures == 0 else f'{failures} 项不通过'}")
    print("=" * 78)
    return 0 if failures == 0 else 1


def _source_rect(plan, window_rect):
    """复用 DragField.source_rect 的几何，避免重复实现。"""
    from freeassetfilter.ui.mica.drag import DragField

    field = DragField(
        image=np.zeros((plan.grid[1], plan.grid[0], 3), dtype=np.uint8),
        region=plan.region,
        grid=plan.grid,
        win_size=plan.win_size,
        key=(),
        backend="verify",
        duration_ms=0.0,
        cover=plan.cover,
        quality=plan.quality,
    )
    return field.source_rect(window_rect)


_SOURCE = None

if __name__ == "__main__":
    raise SystemExit(main())
