"""GPU 与 CPU 烘焙管线的一致性 / 性能对比脚本（开发期诊断工具）。

在真实桌面上分别用原生 GPU 管线与 numpy CPU 管线烘焙同一组窗口矩形，报告
逐像素差异与耗时。用于验证 HLSL 移植的正确性。

用法::

    python compare_cpu_gpu.py [--dump 输出目录]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import List, Tuple

def _project_root() -> Path:
    """向上查找包含 ``freeassetfilter`` 包的目录，作为 ``sys.path`` 根。

    比硬编码 ``parents[n]`` 更稳健：脚本在源码树内移动后仍能定位。

    Returns:
        工作区根目录。

    Raises:
        RuntimeError: 未能在任何祖先目录中找到 ``freeassetfilter`` 包。
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "freeassetfilter" / "__init__.py").is_file():
            return parent
    raise RuntimeError(f"未能从 {here} 向上定位 freeassetfilter 包")


ROOT = _project_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from freeassetfilter.core.native.bridges import mica_render as mr  # noqa: E402
from freeassetfilter.ui.mica import engine, source, tint  # noqa: E402
from freeassetfilter.ui.mica.config import MicaParams, bake_grid_size  # noqa: E402

#: 参与对比的窗口矩形（覆盖居中、贴边、超小、超大四类几何）。
CASES: Tuple[Tuple[int, int, int, int], ...] = (
    (200, 150, 1400, 900),
    (0, 0, 800, 600),
    (1800, 1100, 700, 480),
    (-100, -80, 2700, 1700),
    (640, 400, 320, 240),
)

#: 参与对比的参数组（默认 / 高饱和 / 弱模糊 / 浅色模式）。
PARAM_SETS: Tuple[Tuple[str, MicaParams, bool], ...] = (
    ("默认(暗)", MicaParams(), True),
    ("高饱和(暗)", MicaParams(saturation=8.0, contrast=3.0), True),
    ("弱模糊(暗)", MicaParams(blur_radius=20.0), True),
    ("默认(亮)", MicaParams(), False),
)


def build_gpu_params(
    window_rect: Tuple[int, int, int, int], params: MicaParams, dark: bool
) -> mr.BakeParams:
    """把 CPU 侧参数模型换算为原生 :class:`~...mica_render.BakeParams`。

    几何量（网格尺寸、扩边）复用 CPU 侧的同一批函数，确保两条管线看到的
    是**完全相同**的输入，差异只可能来自内核实现本身。

    Args:
        window_rect: 窗口矩形。
        params: 用户参数。
        dark: 是否深色模式。

    Returns:
        原生烘焙参数。
    """
    ep = params.to_engine(dark)
    grid_w, grid_h = bake_grid_size(window_rect[2], window_rect[3])
    margin = engine.margin_px(grid_w, grid_h, ep.sigma)
    return mr.BakeParams(
        window_rect=window_rect,
        grid_size=(grid_w, grid_h),
        margin=margin,
        sigma=ep.sigma,
        gain=ep.gain,
        chroma_cap=ep.chroma_cap(),
        alpha=ep.alpha,
        l_ref=tint.g1_oklab_l(ep.g1()),
        g1_rgb=ep.g1(),
        gate_lo=tint.CHROMA_LUMA_GATE_LO,
        gate_hi=tint.CHROMA_LUMA_GATE_HI,
        gate_feather=tint.CHROMA_LUMA_GATE_FEATHER,
        dither=True,
    )


def main() -> int:
    """执行对比，返回进程退出码。"""
    parser = argparse.ArgumentParser(description="Mica GPU/CPU 烘焙一致性对比")
    parser.add_argument("--dump", default="", help="把差异最大的一组图像写入该目录")
    args = parser.parse_args()

    provider = source.WallpaperProvider()
    info = provider.probe()
    print(f"桌面：virtual={info.virtual_rect} position={info.position} "
          f"meta={info.source} monitors={len(info.monitors)}")

    t0 = time.perf_counter()
    cpu_src = provider.acquire()
    cpu_canvas_ms = (time.perf_counter() - t0) * 1000.0

    ctx = mr.MicaRenderContext()
    dev = ctx.device_info()
    print(f"GPU：{dev.adapter} FL{dev.feature_level_text} warp={dev.use_warp}")

    ctx.set_virtual_desktop(info.virtual_rect, source.CANVAS_MAX_LONG)
    layouts = [
        mr.MonitorLayout(
            rect=m.rect,
            position=info.position,
            background_rgb=info.background_rgb,
            wallpaper=m.wallpaper_path,
        )
        for m in info.monitors
    ]
    t0 = time.perf_counter()
    ctx.build_canvas_from_wallpapers(layouts, (26, 26, 26))
    gpu_canvas_ms = (time.perf_counter() - t0) * 1000.0

    print(f"\n画布构建：GPU {gpu_canvas_ms:7.1f} ms   CPU {cpu_canvas_ms:7.1f} ms   "
          f"加速 {cpu_canvas_ms / max(gpu_canvas_ms, 1e-6):.1f}×")
    print(f"画布尺寸：GPU {ctx.device_info().canvas_size}  CPU {cpu_src.size}")

    # 预热：首次 bake 含着色器/资源惰性初始化，不计入统计。
    warm = build_gpu_params(CASES[0], PARAM_SETS[0][1], PARAM_SETS[0][2])
    ctx.bake(warm)

    print(f"\n{'参数组':<12} {'窗口':<24} {'网格':<10} "
          f"{'GPU ms':>8} {'CPU ms':>8} {'加速':>6} "
          f"{'Δmean':>7} {'Δp99':>6} {'Δmax':>6}")
    print("-" * 104)

    worst: Tuple[float, str, np.ndarray, np.ndarray] = (-1.0, "", np.zeros(1), np.zeros(1))
    gpu_total = cpu_total = 0.0
    diffs: List[float] = []

    for label, params, dark in PARAM_SETS:
        for rect in CASES:
            gp = build_gpu_params(rect, params, dark)

            t0 = time.perf_counter()
            gpu_img, meta = ctx.bake(gp)
            gpu_ms = (time.perf_counter() - t0) * 1000.0

            request = engine.BakeRequest(rect, params, dark, cpu_src.signature)
            t0 = time.perf_counter()
            cpu_field = engine.bake(request, cpu_src)
            cpu_ms = (time.perf_counter() - t0) * 1000.0

            gpu_total += gpu_ms
            cpu_total += cpu_ms

            a = gpu_img.astype(np.int16)
            b = cpu_field.image.astype(np.int16)
            if a.shape != b.shape:
                print(f"{label:<12} 形状不一致 GPU{a.shape} CPU{b.shape}")
                continue
            delta = np.abs(a - b)
            d_mean = float(delta.mean())
            d_p99 = float(np.percentile(delta, 99))
            d_max = int(delta.max())
            diffs.append(d_mean)

            geo = f"{rect[0]},{rect[1]} {rect[2]}x{rect[3]}"
            print(f"{label:<12} {geo:<24} {meta.size[0]}x{meta.size[1]:<7} "
                  f"{gpu_ms:8.2f} {cpu_ms:8.2f} {cpu_ms / max(gpu_ms, 1e-6):5.1f}× "
                  f"{d_mean:7.2f} {d_p99:6.1f} {d_max:6d}")

            if d_mean > worst[0]:
                worst = (d_mean, f"{label}_{geo}", gpu_img.copy(), cpu_field.image.copy())

    n = len(diffs)
    print("-" * 104)
    print(f"合计 {n} 组：GPU {gpu_total:.1f} ms  CPU {cpu_total:.1f} ms  "
          f"平均加速 {cpu_total / max(gpu_total, 1e-6):.1f}×")
    print(f"逐像素平均绝对差：均值 {np.mean(diffs):.2f} / 最大 {max(diffs):.2f}（0–255 标度）")

    if args.dump and worst[0] >= 0:
        out = Path(args.dump)
        out.mkdir(parents=True, exist_ok=True)
        try:
            from PIL import Image

            tag = worst[1].replace(" ", "_").replace(",", "-")
            Image.fromarray(worst[2]).resize((512, 384), Image.NEAREST).save(
                out / f"gpu_{tag}.png"
            )
            Image.fromarray(worst[3]).resize((512, 384), Image.NEAREST).save(
                out / f"cpu_{tag}.png"
            )
            print(f"最差组已写入 {out}")
        except ImportError:
            print("Pillow 不可用，跳过图像导出")

    ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
