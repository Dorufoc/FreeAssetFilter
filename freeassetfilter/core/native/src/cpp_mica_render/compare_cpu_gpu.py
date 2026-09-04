"""GPU 与 CPU 烘焙管线的一致性 / 性能对比脚本（开发期诊断工具）。

在真实桌面画布（经 ``build_canvas_from_memory`` 与 CPU 源字节完全一致）上分别
用原生 GPU 管线与 numpy CPU 管线烘焙同一组窗口矩形，报告：
* **GPU-float**（:meth:`MicaRenderContext.bake_float` 的 0..1 未量化浮点复合）
  与 **CPU-float**（:func:`engine.bake_with_grid` 的 ``image_float``）的逐像素
  差异 —— 判据：平均绝对差 < 1.5/255、p99 ≤ 4；
* 同时保留 uint8 快照对比与耗时统计，验证 HLSL 移植的正确性。

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
        # 不做网格级抖动：CPU 复合结果（image_float）从不抖动（量化 + 抖动推迟到
        # 显示分辨率），GPU 若加抖动会引入与 CPU 无关的噪声。关闭后两条管线的
        # **未量化浮点复合**才能逐像素对齐，差距只来自内核实现本身。
        dither=False,
    )


#: GPU-float 与 CPU-float 的逐像素容量判据（0–255 标度）。
FLOAT_MEAN_TOLERANCE = 1.5
FLOAT_P99_TOLERANCE = 4


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
    # 用 CPU 侧已解码的画布字节直接上传为 GPU 画布：两条管线看到**完全相同**的
    # 输入像素，GPU-float 与 CPU-float 的差距只可能来自内核实现本身，而非画布
    # 解码 / 摆放的差异。这也是 gpu.py 降级链里「memory」通道的语义。
    t0 = time.perf_counter()
    ctx.build_canvas_from_memory(cpu_src.pixels)
    gpu_canvas_ms = (time.perf_counter() - t0) * 1000.0

    print(f"\n画布构建：GPU(memory) {gpu_canvas_ms:7.1f} ms   CPU {cpu_canvas_ms:7.1f} ms   "
          f"加速 {cpu_canvas_ms / max(gpu_canvas_ms, 1e-6):.1f}×")
    print(f"画布尺寸：GPU {ctx.device_info().canvas_size}  CPU {cpu_src.size}")

    # 预热：首次 bake 含着色器/资源惰性初始化，不计入统计。
    warm = build_gpu_params(CASES[0], PARAM_SETS[0][1], PARAM_SETS[0][2])
    ctx.bake_float(warm)

    print(f"\n{'参数组':<10} {'窗口':<22} {'网格':<9} "
          f"{'GPU ms':>8} {'CPU ms':>8} {'加速':>6} "
          f"{'Δu8均值':>8} {'Δu8p99':>7} {'Δu8max':>7} "
          f"{'Δfloat均值':>11} {'Δfloatp99':>10} {'Δfloatmax':>10}")
    print("-" * 126)

    worst: Tuple[float, str, np.ndarray, np.ndarray] = (-1.0, "", np.zeros(1), np.zeros(1))
    gpu_total = cpu_total = 0.0
    f_diffs: List[float] = []
    f_p99s: List[float] = []

    for label, params, dark in PARAM_SETS:
        for rect in CASES:
            gp = build_gpu_params(rect, params, dark)

            t0 = time.perf_counter()
            gpu_f32, meta = ctx.bake_float(gp)
            gpu_ms = (time.perf_counter() - t0) * 1000.0
            gpu_img = np.clip(np.rint(gpu_f32 * 255.0), 0, 255).astype(np.uint8)

            request = engine.BakeRequest(rect, params, dark, cpu_src.signature)
            t0 = time.perf_counter()
            cpu_field = engine.bake(request, cpu_src)
            cpu_ms = (time.perf_counter() - t0) * 1000.0

            gpu_total += gpu_ms
            cpu_total += cpu_ms

            a8 = gpu_img.astype(np.int16)
            b8 = cpu_field.image.astype(np.int16)
            if a8.shape != b8.shape:
                print(f"{label:<10} 形状不一致 GPU{a8.shape} CPU{b8.shape}")
                continue
            d8 = np.abs(a8 - b8)
            u8_mean = float(d8.mean())
            u8_p99 = float(np.percentile(d8, 99))
            u8_max = int(d8.max())

            # GPU-float（ctx.bake_float）vs CPU-float（engine.bake_with_grid.image_float）。
            # 两者都是 0..1 sRGB 的**未量化**浮点复合，无抖动 —— 差距只来自内核。
            af = gpu_f32.astype(np.float64)
            bf = np.asarray(cpu_field.image_float, dtype=np.float64)
            if af.shape != bf.shape:
                print(f"{label:<10} 形状不一致 GPU-float{af.shape} CPU-float{bf.shape}")
                continue
            d_float = np.abs(af - bf) * 255.0
            f_mean = float(d_float.mean())
            f_p99 = float(np.percentile(d_float, 99))
            f_max = float(d_float.max())
            f_diffs.append(f_mean)
            f_p99s.append(f_p99)

            geo = f"{rect[0]},{rect[1]} {rect[2]}x{rect[3]}"
            print(
                f"{label:<10} {geo:<22} {meta.size[0]}x{meta.size[1]:<5} "
                f"{gpu_ms:8.2f} {cpu_ms:8.2f} {cpu_ms / max(gpu_ms, 1e-6):5.1f}× "
                f"{u8_mean:8.2f} {u8_p99:7.1f} {u8_max:7d} "
                f"{f_mean:11.3f} {f_p99:10.1f} {f_max:10.1f}"
            )

            if f_mean > worst[0]:
                worst = (f_mean, f"{label}_{geo}", gpu_img.copy(), cpu_field.image.copy())

    n = len(f_diffs)
    print("-" * 126)
    print(f"合计 {n} 组：GPU {gpu_total:.1f} ms  CPU {cpu_total:.1f} ms  "
          f"平均加速 {cpu_total / max(gpu_total, 1e-6):.1f}×")
    if f_diffs:
        overall_mean = float(np.mean(f_diffs))
        pass_count = sum(
            1 for mean, p99 in zip(f_diffs, f_p99s)
            if mean < FLOAT_MEAN_TOLERANCE and p99 <= FLOAT_P99_TOLERANCE
        )
        verdict = "PASS" if pass_count == n else f"FAIL ({n - pass_count}/{n} 组越界)"
        print(
            f"GPU-float vs CPU-float：逐像素平均绝对差 均值 {overall_mean:.3f} / "
            f"最大 {max(f_diffs):.3f}（0–255 标度，判据 mean<{FLOAT_MEAN_TOLERANCE}、"
            f"p99≤{FLOAT_P99_TOLERANCE}）→ {verdict}"
        )

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
