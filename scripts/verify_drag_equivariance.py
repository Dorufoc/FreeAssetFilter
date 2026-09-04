# -*- coding: utf-8 -*-
"""实证验证**逐监视器视口层**取样的平移等变性。

这是整套拖动跟随方案的正确性基石，必须实测而非只靠几何推导：

    Layer[窗口移动位移 d 处的子矩形]  ==  Bake(窗口矩形 = P + d)

其中 ``Layer`` 是一块持久化、覆盖整块监视器的「视口层」——烘焙一次，之后任意
位移都只是从这块场里取一个子矩形，不再有任何重计算。若二者不等价，"一次烘焙 +
逐帧取样"就只是几何上自洽、像素上却是错的 —— 用户会看到拖动时颜色与松手后
不一致。

验证方法
--------
在真实壁纸上，对同一窗口矩形做两次：

1. **基准**：把窗口放到 ``P + d`` 跑一次常规完整烘焙（``gpu_bake``）；
2. **取样**：先按 :func:`layer_region_for` / :func:`layer_grid` 烘一块覆盖整块
   监视器的视口层，再从层内按位移 ``d`` 取窗口子矩形（``layer_to_source``），
   把该子矩形的浮点合成结果重采样回窗口网格分辨率后，经 :func:`render_display`
   渲染到显示分辨率。

二者都以 :func:`render_display` 渲染到**相同的窗口显示长边** —— 确定性抖动图案
因此完全一致、在差值里抵消。比较二者的 uint8 像素差，差异来源只有三处，都应当
很小：

* 层密度与常规烘焙一致 ⇒ 子矩形内的采样点几乎重合（``round()`` 带来的亚像素差）；
* 层网格被硬上限 :data:`LAYER_GRID_CAP` 钳制时，:func:`layer_grid` 按 σ 守恒
  回算 ``sigma_eff``，物理模糊半径保持不变；
* 子矩形重采样引入的插值误差。

因此判据定为：**平均绝对差 < 1.5 / 255，p99 ≤ 4**（与 GPU/CPU 一致性验证同量级）。
位移使窗口越出层区域（离开监视器）时无法取样 —— 视口层本身不覆盖该区域，真实
实现会回退到常规烘焙 —— 这种情形直接跳过（属 N/A，而非失败）。

运行::

    python scripts/verify_drag_equivariance.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parent
while not (_PROJECT_ROOT / "freeassetfilter").is_dir():
    if _PROJECT_ROOT.parent == _PROJECT_ROOT:
        raise SystemExit("找不到项目根目录")
    _PROJECT_ROOT = _PROJECT_ROOT.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from freeassetfilter.ui.mica.config import (  # noqa: E402
    BAKE_LONG_MAX,
    MicaParams,
    SIGMA_MAX,
    SIGMA_MIN,
    bake_grid_size,
)
from freeassetfilter.ui.mica.drag import (  # noqa: E402
    ViewportLayer,
    layer_grid,
    layer_region_for,
    layer_to_source,
)
from freeassetfilter.ui.mica.engine import BakeRequest, BakedField, render_display  # noqa: E402
from freeassetfilter.ui.mica.gpu import gpu_available, gpu_bake  # noqa: E402
from freeassetfilter.ui.mica.resample import crop_f32  # noqa: E402
from freeassetfilter.ui.mica.source import WallpaperProvider  # noqa: E402

#: 参与验证的窗口尺寸（长边均 > BAKE_LONG_MAX，层密度 = 320 / 长边）。
_WIN_SIZES: Tuple[Tuple[int, int], ...] = ((1600, 1000), (1000, 700), (600, 400))
#: 取样位移（虚拟桌面像素）。窗口越出层区域时跳过（N/A）。
_OFFSETS: Tuple[Tuple[int, int], ...] = ((0, 0), (37, 23), (-60, 40), (120, -85), (-150, -95))

_MEAN_TOLERANCE = 1.5  # / 255
_P99_TOLERANCE = 4  # / 255


class _Skip(Exception):
    """脚本因环境原因应干净退出的信号（不视为失败）。"""


def _params_with_sigma(params: MicaParams, sigma: float) -> MicaParams:
    """把引擎 σ 反解为等价 ``blur_radius``，层网格被钳制时保持物理模糊半径不变。

    与 :mod:`~freeassetfilter.ui.mica.material` 的同名辅助一致：层网格按监视器
    换算后可能被 :data:`~freeassetfilter.ui.mica.drag.LAYER_GRID_CAP` 钳制、实际
    密度低于常规烘焙，此时必须同步回缩 σ（网格像素），色度低通的**物理半径**
    ``σ_physical = sigma_eff / density`` 才能保持不变。

    Args:
        params: 用户参数。
        sigma: 目标引擎 σ（网格像素）。

    Returns:
        以等价 ``blur_radius`` 重建的 :class:`~freeassetfilter.ui.mica.config.MicaParams`。
    """
    k = BAKE_LONG_MAX / 192.0
    base = float(sigma) / k
    blur = min(300.0, max(0.0, (base - SIGMA_MIN) / (SIGMA_MAX - SIGMA_MIN) * 300.0))
    if abs(blur - params.blur_radius) < 1e-6:
        return params
    return params.replace(blur_radius=blur)


def _monitor_for(source, origin: Tuple[int, int]) -> Tuple[int, int, int, int]:
    """返回包含窗口中心的监视器矩形；找不到时回退第一块监视器。

    Args:
        source: 壁纸源。
        origin: 窗口中心点 ``(cx, cy)``（虚拟桌面像素）。

    Returns:
        监视器矩形 ``(x, y, w, h)``。
    """
    try:
        monitors = source.info.monitors
    except AttributeError:
        monitors = ()
    for mon in monitors:
        mx, my, mw, mh = (int(v) for v in mon.rect)
        if mx <= origin[0] < mx + mw and my <= origin[1] < my + mh:
            return (mx, my, mw, mh)
    if monitors:
        first = monitors[0]
        return (int(first.rect[0]), int(first.rect[1]), int(first.rect[2]), int(first.rect[3]))
    return source.info.virtual_rect


def _bake_layer(
    params: MicaParams,
    dark: bool,
    sig: str,
    monitor: Tuple[int, int, int, int],
    win: Tuple[int, int],
) -> Tuple[Optional[BakedField], Optional[ViewportLayer]]:
    """按持久化视口层几何烘一块覆盖整块监视器的层。

    步骤与真实实现 :meth:`material._BakeWorker.run` 完全一致：
    层区域 = 监视器矩形；层网格经 :func:`layer_grid` 得出（含 σ 守恒校正）；
    烘焙参数用 ``_params_with_sigma`` 回缩 σ；以层区域为 ``window_rect``、
    显式 ``grid_size`` 烘焙。

    Args:
        params: 用户参数。
        dark: 是否深色模式。
        sig: 壁纸源指纹。
        monitor: ``(x, y, w, h)`` 监视器矩形。
        win: ``(w, h)`` 窗口尺寸。

    Returns:
        ``(layer_field, layer)``；烘焙失败时 ``(None, None)``。
    """
    region = layer_region_for((0, 0, win[0], win[1]), monitor)  # = monitor
    sigma = params.to_engine(dark).sigma
    grid, sigma_eff = layer_grid(monitor, win[0], win[1], sigma)
    bake_params = _params_with_sigma(params, sigma_eff)
    request = BakeRequest(region, bake_params, dark, sig)
    field = gpu_bake(request, _SOURCE, grid_size=grid)
    if field is None:
        return None, None
    layer = ViewportLayer(
        region=region,
        width=int(field.grid_size[0]),
        height=int(field.grid_size[1]),
        win_size=(int(win[0]), int(win[1])),
    )
    return field, layer


def _render(field: BakedField, target_long: int) -> np.ndarray:
    """把烘焙产物渲染到 ``target_long`` 长边的显示分辨率 uint8 图像。"""
    return render_display(field, target_long, 1.0, (0, 0, 0))


def _sub_field_from_layer(
    layer_field: BakedField,
    src: Tuple[float, float, float, float],
    moved: Tuple[int, int, int, int],
    params: MicaParams,
    dark: bool,
    sig: str,
    ref_grid: Tuple[int, int],
) -> BakedField:
    """从层字段的浮点合成里取窗口子矩形，重采样回窗口网格分辨率。

    Args:
        layer_field: 覆盖整块监视器的层字段（含 ``image_float``）。
        src: ``layer_to_source`` 返回的层内子矩形（浮点）。
        moved: 移动后的窗口矩形。
        params: 用户参数。
        dark: 是否深色模式。
        sig: 壁纸源指纹。
        ref_grid: 窗口常规烘焙的网格分辨率 ``(gw, gh)``。

    Returns:
        以 ``ref_grid`` 为网格、含浮点合成结果的 :class:`BakedField`，供
        :func:`render_display` 渲染。
    """
    sub_float = crop_f32(layer_field.image_float, src, ref_grid[0], ref_grid[1])
    return BakedField(
        image=np.clip(np.rint(sub_float * 255.0), 0, 255).astype(np.uint8),
        request=BakeRequest(moved, params, dark, sig),
        grid_size=(int(ref_grid[0]), int(ref_grid[1])),
        sample_rect=(float(src[0]), float(src[1]), float(src[2]), float(src[3])),
        margin=0,
        backend="layer-sample",
        duration_ms=0.0,
        work_size=(int(ref_grid[0]), int(ref_grid[1])),
        image_float=sub_float,
    )


def main() -> int:
    """执行验证，返回进程退出码。"""
    global _SOURCE
    print("=" * 78)
    print("逐监视器视口层 · 平移等变性验证")
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
    print(f"GPU 可用 = {gpu_available()}")
    if not gpu_available():
        print("GPU 不可用，跳过验证（视口层采样基于 GPU 管线）")
        return 0

    params = MicaParams()
    sig = provider.probe().signature()
    dark = True

    # 预热：首次烘焙要建 GPU 上下文、解码画布、编译着色器，耗时不可比。
    pre_monitor = _monitor_for(source, (400 + 800, 260 + 500))
    _bake_layer(params, dark, sig, pre_monitor, (1600, 1000))
    _bake_layer(params, dark, sig, pre_monitor, (600, 400))
    print("（已预热）\n")

    failures = 0
    for win in _WIN_SIZES:
        win_w, win_h = win
        monitor = _monitor_for(
            source, (int(win_w) // 2, int(win_h) // 2)
        )
        mx, my, mw, mh = (int(v) for v in monitor)
        if win_w > mw or win_h > mh:
            print(f"窗口 {win_w}x{win_h}  大于监视器 {mw}x{mh}，跳过该尺寸")
            continue

        # 窗口居中放置，给位移留足余量（最佳采样点：远离层边缘钳制）。
        base_x = mx + max(0, (mw - win_w) // 2)
        base_y = my + max(0, (mh - win_h) // 2)

        t0 = time.perf_counter()
        layer_field, layer = _bake_layer(params, dark, sig, monitor, win)
        layer_ms = (time.perf_counter() - t0) * 1000.0
        if layer_field is None or layer is None:
            print(f"窗口 {win_w}x{win_h}  视口层烘焙失败，跳过")
            failures += 1
            continue

        ref_grid = bake_grid_size(win_w, win_h)
        print(
            f"窗口 {win_w}x{win_h}  监视器 {mx},{my} {mw}x{mh}  "
            f"层 region={layer.region} grid={layer.width}x{layer.height}  "
            f"常规 grid={ref_grid}  层烘焙 {layer_ms:.1f} ms"
        )

        for dx, dy in _OFFSETS:
            moved = (base_x + dx, base_y + dy, win_w, win_h)
            src = layer_to_source(layer, moved)
            if src is None:
                print(f"  位移 {dx:+5d},{dy:+5d}  越出层区域（无法取样，N/A）")
                continue

            t1 = time.perf_counter()
            sub_field = _sub_field_from_layer(
                layer_field, src, moved, params, dark, sig, ref_grid
            )
            sample_ms = (time.perf_counter() - t1) * 1000.0
            sampled = _render(sub_field, max(win_w, win_h))

            t2 = time.perf_counter()
            direct_field = gpu_bake(BakeRequest(moved, params, dark, sig), _SOURCE)
            ref_ms = (time.perf_counter() - t2) * 1000.0
            if direct_field is None:
                print(f"  位移 {dx:+5d},{dy:+5d}  直接烘焙失败，跳过")
                failures += 1
                continue
            reference = _render(direct_field, max(win_w, win_h))

            if sampled.shape != reference.shape:
                print(
                    f"  位移 {dx:+5d},{dy:+5d}  形状不一致 "
                    f"取样{sampled.shape} 基准{reference.shape}"
                )
                failures += 1
                continue

            diff = np.abs(sampled.astype(np.int16) - reference.astype(np.int16))
            mean = float(diff.mean())
            p99 = float(np.percentile(diff, 99))
            ok = mean < _MEAN_TOLERANCE and p99 <= _P99_TOLERANCE
            failures += 0 if ok else 1
            print(
                f"  位移 {dx:+5d},{dy:+5d}  平均差={mean:5.2f}  p99={p99:4.1f}  "
                f"最大={int(diff.max()):3d}  取样={sample_ms:4.2f} ms  "
                f"重烘焙={ref_ms:5.1f} ms  {'OK' if ok else 'FAIL'}"
            )

    print("\n" + "=" * 78)
    print(f"结论：{'全部通过' if failures == 0 else f'{failures} 项不通过'}")
    print("=" * 78)
    return 0 if failures == 0 else 1


_SOURCE = None

if __name__ == "__main__":
    raise SystemExit(main())
