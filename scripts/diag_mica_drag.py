# -*- coding: utf-8 -*-
"""Mica 拖动渲染瓶颈定位 + 渐变色带（banding）诊断。

一次性诊断脚本（非产品代码），回答两个问题：

1. **拖动期的帧成本到底花在哪** —— 在真实光栅绘制设备上（QPixmap 而非
   offscreen backstore）实测「事件记账 / 子矩形映射 / blit」的耗时，并量化
   「重绘区域面积」与「是否开启 SmoothPixmapTransform（双线性重采样）」的影响，
   从而给出「缩小重绘范围」的收益上界。
2. **渐变色带（banding）从哪来** —— 跑通真实烘焙管线产出视口层，用「平坦
   游程长度分布」「零差分占比」「唯一色数」量化 banding，并对比候选修复。

运行：
    QT_QPA_PLATFORM=offscreen <py> scripts/diag_mica_drag.py
"""

from __future__ import annotations

import os
import sys
import time
from typing import Callable, Tuple

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_ROOT, os.path.join(_ROOT, "freeassetfilter")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PySide6.QtCore import QRect, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from freeassetfilter.ui.mica.drag import (  # noqa: E402
    ViewportLayer,
    layer_grid,
    layer_to_source_clamped,
)

# 模拟的虚拟桌面（物理像素）与窗口尺寸。
VIRTUAL = (0, 0, 2560, 1440)
WIN_W, WIN_H = 1600, 1000


def _fmt_ms(v: float) -> str:
    return f"{v:8.3f} ms"


def _timeit(fn: Callable[[], object], n: int) -> float:
    """返回单次均值 ms（预热 1 次）。"""
    fn()
    fn()
    started = time.perf_counter()
    for _ in range(n):
        fn()
    return (time.perf_counter() - started) * 1000.0 / n


def _pixmap_from_rgb(image: np.ndarray) -> QPixmap:
    h, w = int(image.shape[0]), int(image.shape[1])
    data = np.ascontiguousarray(image, dtype=np.uint8).tobytes()
    qimg = QImage(data, w, h, w * 3, QImage.Format_RGB888)
    pm = QPixmap.fromImage(qimg)
    del qimg, data
    return pm


def _synthetic_layer(w: int, h: int) -> np.ndarray:
    """合成一层缓变色调场（uint8），尺寸 = 虚拟桌面。"""
    yy = np.linspace(0.0, 1.0, h, dtype=np.float32).reshape(h, 1)
    xx = np.linspace(0.0, 1.0, w, dtype=np.float32).reshape(1, w)
    img = np.stack(
        [
            30.0 + 40.0 * xx + 18.0 * yy,
            32.0 + 36.0 * xx + 20.0 * yy,
            38.0 + 30.0 * xx + 26.0 * yy,
        ],
        axis=2,
    )
    return np.clip(img, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# 1) 拖动帧成本剖析（真实光栅设备）
# ---------------------------------------------------------------------------

def profile_drag(app: QApplication) -> None:
    print("\n" + "=" * 80)
    print("1) 拖动帧成本剖析（真实光栅绘制设备 QPixmap）")
    print("=" * 80)

    layer_img = _synthetic_layer(VIRTUAL[2], VIRTUAL[3])
    layer_pm = _pixmap_from_rgb(layer_img)
    layer = ViewportLayer(
        region=VIRTUAL, width=VIRTUAL[2], height=VIRTUAL[3], win_size=(WIN_W, WIN_H)
    )
    # 目标画布（模拟窗口背存 / 合成表面）
    target = QPixmap(WIN_W, WIN_H)
    rect = QRect(0, 0, WIN_W, WIN_H)

    print(f"\n  层 {layer_pm.width()}x{layer_pm.height()} "
          f"({layer_pm.width()*layer_pm.height()*4/1048576:.1f} MB) | "
          f"窗口 {WIN_W}x{WIN_H}")

    # --- A) 子矩形映射（纯 Python 几何） ---
    win0 = (400, 200, WIN_W, WIN_H)
    t_map = _timeit(lambda: layer_to_source_clamped(layer, win0), 50000)
    src = layer_to_source_clamped(layer, win0)
    print(f"\n  A 子矩形映射 (layer_to_source_clamped) {_fmt_ms(t_map)}  src={src}")

    # --- B) 全窗口 blit：smooth=False（1:1 整型）vs smooth=True（双线性） ---
    def _blit(smooth: bool, clip: QRect | None = None) -> None:
        p = QPainter(target)
        if clip is not None and not smooth:
            p.setClipRect(clip)
        p.setRenderHint(QPainter.SmoothPixmapTransform, smooth)
        if smooth:
            p.drawPixmap(QRectF(rect), layer_pm, QRectF(*[float(v) for v in src]))
        else:
            p.drawPixmap(QRect(rect), layer_pm, QRect(*[int(v) for v in src]))
        p.end()

    print("\n  B 全窗口 blit（每帧 6.10 MB）")
    t_hard = _timeit(lambda: _blit(False), 300)
    t_smooth = _timeit(lambda: _blit(True), 100)
    print(f"     整型 1:1 blit  (SmoothPixmapTransform=False)  {_fmt_ms(t_hard)}")
    print(f"     浮点双线性 blit (SmoothPixmapTransform=True)   {_fmt_ms(t_smooth)}"
          f"   ← {t_smooth / max(t_hard, 1e-6):.1f}× 慢")
    print(f"     折算带宽：1:1 {6.10 / (t_hard / 1000) / 1024:.1f} GB/s | "
          f"双线性 {6.10 / (t_smooth / 1000) / 1024:.1f} GB/s")

    # --- C) 重绘区域面积 vs 成本（整型 1:1 + clip） ---
    print("\n  C 重绘区域面积 vs 绘制成本（整型 1:1 blit + setClipRect）")
    print(f"     {'重绘区域':<16} | {'面积(px)':>10} | {'耗时':>10} | {'占全窗':>8} | {'收益':>7}")
    print("     " + "-" * 66)
    base_t = None
    for label, cw, ch in [
        ("全窗口", WIN_W, WIN_H),
        ("半窗口", WIN_W // 2, WIN_H // 2),
        ("1/4 窗口", WIN_W // 4, WIN_H // 4),
        ("竖条 32px", 32, WIN_H),
        ("横条 32px", WIN_W, 32),
        ("L 形 32px (横+竖)", WIN_W, 32),
        ("小块 64x64", 64, 64),
    ]:
        clip = QRect(0, 0, cw, ch)
        area = cw * ch
        t = _timeit(lambda c=clip: _blit(False, c), 400)
        if base_t is None:
            base_t = t
        print(f"     {label:<16} | {area:10,d} | {_fmt_ms(t)} | "
              f"{area / (WIN_W*WIN_H) * 100:7.1f}% | {t/base_t*100:6.1f}%")

    # --- D) Qt 的 update(region) 语义与 QWidget.scroll 是否可用 ---
    print("\n  D QWidget.scroll() / update(region) 语义探测")
    w = QWidget()
    w.resize(WIN_W, WIN_H)
    w.show()
    app.processEvents()

    regions: list = []

    class _Probe(QWidget):
        def paintEvent(self, e):  # noqa: N802
            regions.append((e.rect(), e.region().rectCount()))
            QWidget.paintEvent(self, e)

    probe = _Probe()
    probe.resize(WIN_W, WIN_H)
    probe.show()
    app.processEvents()
    regions.clear()
    probe.update(QRect(0, 0, WIN_W, 32))
    app.processEvents()
    print(f"     update(QRect(0,0,{WIN_W},32))  →  paintEvent.rect = "
          f"{regions[-1][0] if regions else 'N/A'}   (rects={regions[-1][1] if regions else '?'})")

    regions.clear()
    probe.scroll(0, -32)
    app.processEvents()
    if regions:
        r, n = regions[-1]
        print(f"     scroll(0,-32)                 →  paintEvent.rect = {r}   "
              f"(rects={n}, 面积={r.width()*r.height():,} px)")
    else:
        print("     scroll(0,-32)                 →  未触发 paintEvent")

    regions.clear()
    probe.scroll(10, 10)
    app.processEvents()
    if regions:
        r, n = regions[-1]
        print(f"     scroll(10,10)                 →  paintEvent.rect = {r}   "
              f"(rects={n}, 面积={r.width()*r.height():,} px)")
    else:
        print("     scroll(10,10)                 →  未触发 paintEvent")
    probe.deleteLater()
    w.deleteLater()

    # --- E) 连续拖动累计成本 ---
    print("\n  E 连续拖动 240 帧（4s @60fps）累计成本（仅 blit，1:1 整型）")
    frames = 240
    started = time.perf_counter()
    for i in range(frames):
        wr = (400 + i * 3, 200 + (i % 40), WIN_W, WIN_H)
        s = layer_to_source_clamped(layer, wr)
        p = QPainter(target)
        p.setRenderHint(QPainter.SmoothPixmapTransform, False)
        p.drawPixmap(QRect(rect), layer_pm, QRect(*[int(v) for v in s]))
        p.end()
    el = (time.perf_counter() - started) * 1000.0
    print(f"     全窗口重绘：总 {el:.1f} ms | 单帧 {el/frames:.3f} ms | "
          f"传输 {6.10*frames/1024:.2f} GB")
    started = time.perf_counter()
    for i in range(frames):
        wr = (400 + i * 3, 200 + (i % 40), WIN_W, WIN_H)
        s = layer_to_source_clamped(layer, wr)
        p = QPainter(target)
        p.setClipRect(QRect(0, 0, 3, WIN_H))  # 仅本帧新暴露的竖条
        p.setRenderHint(QPainter.SmoothPixmapTransform, False)
        p.drawPixmap(QRect(rect), layer_pm, QRect(*[int(v) for v in s]))
        p.end()
    el2 = (time.perf_counter() - started) * 1000.0
    print(f"     仅新暴露条带：总 {el2:.1f} ms | 单帧 {el2/frames:.3f} ms | "
          f"加速 {el/max(el2,1e-6):.1f}×")


# ---------------------------------------------------------------------------
# 2) 渐变色带诊断
# ---------------------------------------------------------------------------

def _flat_run_stats(img: np.ndarray) -> Tuple[int, float, int]:
    f = img.astype(np.float64)
    luma = np.rint(0.30 * f[..., 0] + 0.59 * f[..., 1] + 0.11 * f[..., 2]).astype(np.int64)
    longest = 0
    long_runs = 0
    zero = 0
    total = 0
    for row in luma:
        d = np.diff(row)
        zero += int((d == 0).sum())
        total += int(d.size)
        bounds = np.concatenate(([0], np.flatnonzero(d != 0) + 1, [row.size]))
        runs = np.diff(bounds)
        if runs.size:
            longest = max(longest, int(runs.max()))
            long_runs += int((runs >= 64).sum())
    return longest, zero / max(1, total), long_runs


def _report(name: str, img: np.ndarray) -> dict:
    longest, zero_ratio, long_runs = _flat_run_stats(img)
    uniq = int(len(np.unique(img.reshape(-1, 3), axis=0)))
    print(f"    {name:<32} 最长游程 {longest:5d}px | 零差分 {zero_ratio*100:5.1f}% "
          f"| ≥64px游程 {long_runs:5d} | 唯一色 {uniq:6d}")
    return {"name": name, "longest": longest, "zero": zero_ratio,
            "long_runs": long_runs, "uniq": uniq}


def diagnose_banding() -> None:
    print("\n" + "=" * 80)
    print("2) 渐变色带（banding）诊断 —— 复现真实烘焙管线")
    print("=" * 80)

    from freeassetfilter.ui.mica import engine as eng_mod
    from freeassetfilter.ui.mica.config import MicaParams
    from freeassetfilter.ui.mica.engine import BakeRequest, bake_with_grid, render_display
    from freeassetfilter.ui.mica.source import WallpaperSource, DesktopInfo

    # 合成一张缓变壁纸
    cw, ch = 1600, 900
    yy = np.linspace(0.0, 1.0, ch, dtype=np.float32).reshape(ch, 1)
    xx = np.linspace(0.0, 1.0, cw, dtype=np.float32).reshape(1, cw)
    wall = np.stack(
        [0.18 + 0.30 * xx + 0.10 * yy,
         0.24 + 0.26 * xx + 0.12 * yy,
         0.38 + 0.20 * xx + 0.14 * yy],
        axis=2,
    )
    wall_u8 = np.clip(wall * 255.0, 0, 255).astype(np.uint8)
    info = DesktopInfo(
        virtual_rect=(0, 0, cw, ch),
        monitors=(),
        position="fill",
        background_rgb=(0, 0, 0),
        source="diag",
    )
    source = WallpaperSource(
        pixels=wall_u8, origin=(0, 0), scale=1.0, backend="test", info=info,
        signature="diag",
    )

    params = MicaParams()
    dark = True
    sigma = params.to_engine(dark).sigma
    grid, sigma_eff = layer_grid(VIRTUAL, WIN_W, WIN_H, sigma)
    p2 = params.replace(blur_radius=max(0.0, min(300.0, (sigma_eff - 2.0) / 38.0 * 300.0)))
    request = BakeRequest(VIRTUAL, p2, dark, "diag")

    t0 = time.perf_counter()
    field = bake_with_grid(request, source, grid)
    bake_ms = (time.perf_counter() - t0) * 1000.0
    t0 = time.perf_counter()
    layer_u8 = render_display(field, VIRTUAL[2], 1.0, (0, 0, 0), origin=(0, 0))
    render_ms = (time.perf_counter() - t0) * 1000.0

    print(f"\n  视口层网格 {grid} | σ {sigma:.2f} → σ_eff {sigma_eff:.2f}")
    print(f"  烘焙 {bake_ms:.1f} ms | 渲染显示分辨率 {render_ms:.1f} ms | "
          f"层 {layer_u8.shape[1]}x{layer_u8.shape[0]}")
    print(f"  网格→显示放大倍数 {layer_u8.shape[1] / grid[0]:.2f}×")
    print(f"  image_float 可用: {field.image_float is not None} "
          f"（GPU 路径下为 None ⇒ 走 uint8 网格放大）")

    # 网格分辨率上的量化损失
    if field.image_float is not None:
        ref = np.clip(np.rint(field.image_float * 255.0), 0, 255).astype(int)
        got = field.image.astype(int)
        err = np.abs(ref - got)
        print(f"  网格级 uint8 量化误差：均值 {err.mean():.3f} LSB | "
              f"p99 {np.percentile(err,99):.1f} | 最大 {err.max()}")
        # 网格级相邻像素差分：看是否已被量化成台阶
        fl = field.image_float[..., 0]
        d = np.abs(np.diff(fl, axis=1)) * 255.0
        print(f"  网格级相邻像素差分：均值 {d.mean():.4f} LSB | 最大 {d.max():.3f} LSB"
              f"  （<1 LSB ⇒ 网格上就已无梯度信息，放大后只能靠插值造梯度）")

    print("\n  候选方案对比：")
    fl = field.image_float if field.image_float is not None else field.image

    # ③ 无抖动基线
    base = eng_mod.upscale_to_display(fl, VIRTUAL[2], dither=False, origin=(0, 0))
    r = []
    r.append(_report("③ 无抖动（基线）", base))

    # ① 当前：±0.7 LSB 均匀噪声
    cur = eng_mod.upscale_to_display(fl, VIRTUAL[2], dither=True, dither_amp=0.7, origin=(0, 0))
    r.append(_report("① 当前 ±0.7 LSB 均匀", cur))

    # ② GPU 路径：uint8 网格放大 + 抖动
    u8 = eng_mod.upscale_to_display(field.image, VIRTUAL[2], dither=True, dither_amp=0.7, origin=(0, 0))
    r.append(_report("② GPU 路径 uint8 网格+抖动", u8))

    # ④ ±1.0
    r.append(_report("④ ±1.0 LSB 均匀",
                     eng_mod.upscale_to_display(fl, VIRTUAL[2], dither=True, dither_amp=1.0, origin=(0, 0))))

    # ⑤ TPDF（两个均匀分布相减，三角 PDF）—— 无 DC 偏置、二阶无偏
    th, tw = base.shape[0], base.shape[1]
    rng = np.random.default_rng(1337)
    tpdf = (rng.random((th, tw, 1), dtype=np.float32)
            - rng.random((th, tw, 1), dtype=np.float32)) * 2.0
    r.append(_report("⑤ TPDF 三角 ±2 LSB",
                     np.clip(np.rint(base.astype(np.float32) + tpdf), 0, 255).astype(np.uint8)))

    # ⑥ 有序抖动 Bayer 8x8（幅度 ±0.5 等效 1 LSB）
    bayer = np.array([
        [0, 32, 8, 40, 2, 34, 10, 42], [48, 16, 56, 24, 50, 18, 58, 26],
        [12, 44, 4, 36, 14, 46, 6, 38], [60, 28, 52, 20, 62, 30, 54, 22],
        [3, 35, 11, 43, 1, 33, 9, 41], [51, 19, 59, 27, 49, 17, 57, 25],
        [15, 47, 7, 39, 13, 45, 5, 37], [63, 31, 55, 23, 61, 29, 53, 21],
    ], dtype=np.float32) / 64.0 - 0.5
    tile = np.tile(bayer, (th // 8 + 1, tw // 8 + 1))[:th, :tw, None]
    r.append(_report("⑥ Bayer 8×8 有序 ±0.5",
                     np.clip(np.rint(base.astype(np.float32) + tile * 2.0), 0, 255).astype(np.uint8)))

    # ⑦ TPDF + 屏幕锚定（最终候选）
    r.append(_report("⑦ TPDF ±1.5 均匀组合",
                     np.clip(np.rint(base.astype(np.float32)
                                     + (rng.random((th, tw, 1), dtype=np.float32)
                                        - rng.random((th, tw, 1), dtype=np.float32)) * 1.5),
                             0, 255).astype(np.uint8)))

    print("\n  判读：最长游程越接近 1~4 px 越好；≥64px 的长游程即肉眼可见色带；")
    print("        零差分占比高 = 大片完全平坦 = banding。")


def main() -> int:
    app = QApplication.instance() or QApplication([])
    profile_drag(app)
    diagnose_banding()
    print("\n完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
