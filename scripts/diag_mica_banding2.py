# -*- coding: utf-8 -*-
"""色带（banding）根因二分：是「插值造台阶」还是「抖动不足」？

从上一轮诊断已知：真实 Mica 色调场的动态范围极小（全屏仅几个 LSB），
因此 8-bit 量化必然产生台阶。本脚本把两个嫌疑因子拆开做全组合实验：

* **插值方式** —— 网格（如 512×288）放大 5× 到显示分辨率时，
  bilinear 只有 C0 连续（网格线处导数跳变 → 菱形刻面），
  smoothstep / Catmull-Rom（双三次）为 C1，可消除刻面。
* **抖动图案与幅值** —— 均匀噪声 / TPDF 三角 / Bayer 有序 / IGN 交错梯度噪声。

评价指标：
* 最长平坦游程（≥64px 即肉眼可见色带）
* 零差分占比
* **抖动可见度**：平坦区局部标准差（越小越不易察觉噪点）
"""

from __future__ import annotations

import numpy as np

np.random.seed(0)


# ---------------------------------------------------------------- 被测信号
def make_lowfreq_signal(gw: int = 512, gh: int = 288, levels: float = 3.0):
    """构造与真实 Mica 同构的超低频场：全屏动态范围仅 ``levels`` 个 LSB。

    真实 Mica 的明度被 SetLum 锁在 G1，只有被 cap 到 ~0.055 Oklab 的色度在变，
    因此最终 RGB 全屏只有几个 LSB 的动态范围 —— 正是 banding 的病理场景。
    """
    yy = np.linspace(0.0, 1.0, gh, dtype=np.float32).reshape(gh, 1)
    xx = np.linspace(0.0, 1.0, gw, dtype=np.float32).reshape(1, gw)
    # 低频起伏（模拟色度低通后的残余）
    base = (np.sin(xx * 2.1 + 0.3) * 0.5 + np.cos(yy * 1.7) * 0.35
            + np.sin((xx + yy) * 1.1) * 0.15)
    base = (base - base.min()) / (base.max() - base.min())
    rgb = np.repeat((base * levels + 30.0)[..., None], 3, axis=2)
    return rgb.astype(np.float32)


# ---------------------------------------------------------------- 插值
def _weights(n_out: int, n_in: int, kind: str):
    """返回 (idx0, idx1, w) —— w 为给 idx1 的权重。"""
    xs = np.linspace(0.0, float(n_in - 1), n_out, dtype=np.float32)
    x0 = np.floor(xs).astype(np.intp)
    w = (xs - x0).astype(np.float32)
    if kind == "bilinear":
        pass
    elif kind == "smoothstep":
        w = w * w * (3.0 - 2.0 * w)
    elif kind == "catmullrom":
        # 先保留线性 w，在取样时用 4 tap
        pass
    return x0, w


def upsample(src: np.ndarray, tw: int, th: int, kind: str) -> np.ndarray:
    """把 (gh,gw,3) float32 放大到 (th,tw,3)。kind ∈ bilinear/smoothstep/catmullrom。"""
    gh, gw = src.shape[0], src.shape[1]

    if kind == "catmullrom":
        def _cr(b, n_out, axis):
            g = b.shape[axis]
            xs = np.linspace(0.0, float(g - 1), n_out, dtype=np.float32)
            x0 = np.floor(xs).astype(np.intp)
            t = (xs - x0).astype(np.float32)[..., None] if axis == 0 else \
                (xs - x0).astype(np.float32)[:, None]
            t = t.reshape(-1, 1) if axis == 0 else t.reshape(-1, 1)
            im1 = np.take(b, np.clip(x0 - 1, 0, g - 1), axis=axis)
            i0 = np.take(b, x0, axis=axis)
            i1 = np.take(b, np.clip(x0 + 1, 0, g - 1), axis=axis)
            i2 = np.take(b, np.clip(x0 + 2, 0, g - 1), axis=axis)
            tt = t.reshape((n_out,) + (1,) * (b.ndim - 1))
            a = -0.5 * i0 + 1.5 * i1 - 1.5 * i2 + 0.5 * i2 * 0
            # 标准 Catmull-Rom
            return (i0 * (-0.5 * tt ** 3 + tt ** 2 - 0.5 * tt)
                    + i1 * (1.5 * tt ** 3 - 2.5 * tt ** 2 + 1.0)
                    + i1 * 0 + i2 * (-1.5 * tt ** 3 + 2.0 * tt ** 2 + 0.5 * tt)
                    + im1 * (0.5 * tt ** 3 - 1.0 * tt ** 2 + 0.5 * tt)) * 0 + (
                im1 * (-0.5 * tt ** 3 + tt ** 2 - 0.5 * tt)
                + i0 * (1.5 * tt ** 3 - 2.5 * tt ** 2 + 1.0)
                + i1 * (-1.5 * tt ** 3 + 2.0 * tt ** 2 + 0.5 * tt)
                + i2 * (0.5 * tt ** 3 - 0.5 * tt ** 2))
        b = _cr(src, tw, 1)
        return _cr(b, th, 0)

    def _axis1(b, n_out):
        x0, w = _weights(n_out, b.shape[1], kind)
        out = b[:, x0, :] * (1.0 - w)[None, :, None]
        out += b[:, np.minimum(x0 + 1, b.shape[1] - 1), :] * w[None, :, None]
        return out

    def _axis0(b, n_out):
        y0, w = _weights(n_out, b.shape[0], kind)
        out = b[y0, :, :] * (1.0 - w)[:, None, None]
        out += b[np.minimum(y0 + 1, b.shape[0] - 1), :, :] * w[:, None, None]
        return out

    if gh * tw <= th * gw:
        return _axis0(_axis1(src, tw), th)
    return _axis1(_axis0(src, th), tw)


# ---------------------------------------------------------------- 抖动图案
def dither_uniform(th, tw, amp):
    rng = np.random.default_rng(1337)
    return (rng.random((th, tw, 1), dtype=np.float32) - 0.5) * (2.0 * amp)


def dither_tpdf(th, tw, amp):
    """三角分布（两个均匀分布之差）：理论上去掉量化误差与信号的相关性。"""
    rng = np.random.default_rng(1337)
    return (rng.random((th, tw, 1), dtype=np.float32)
            - rng.random((th, tw, 1), dtype=np.float32)) * amp


_BAYER8 = np.array([
    [0, 32, 8, 40, 2, 34, 10, 42], [48, 16, 56, 24, 50, 18, 58, 26],
    [12, 44, 4, 36, 14, 46, 6, 38], [60, 28, 52, 20, 62, 30, 54, 22],
    [3, 35, 11, 43, 1, 33, 9, 41], [51, 19, 59, 27, 49, 17, 57, 25],
    [15, 47, 7, 39, 13, 45, 5, 37], [63, 31, 55, 23, 61, 29, 53, 21],
], dtype=np.float32) / 64.0 - 0.5


def dither_bayer(th, tw, amp):
    tile = np.tile(_BAYER8, (th // 8 + 1, tw // 8 + 1))[:th, :tw, None]
    return tile * (2.0 * amp)


def dither_ign(th, tw, amp):
    """交错梯度噪声（IGN, Jorge Jimenez）—— 逐像素哈希，近似蓝噪声谱。

    天然**屏幕锚定**（只依赖绝对像素坐标），与现有「抖动锚定壁纸」的需求一致，
    且无需缓存整张噪声图。
    """
    xs = np.arange(tw, dtype=np.float32).reshape(1, tw)
    ys = np.arange(th, dtype=np.float32).reshape(th, 1)
    n = np.mod(52.9829189 * np.mod(0.06711056 * xs + 0.00583715 * ys, 1.0), 1.0)
    return (n - 0.5)[..., None] * (2.0 * amp)


DITHERS = {
    "none": lambda th, tw, a: np.zeros((th, tw, 1), np.float32),
    "uniform±0.7": dither_uniform,
    "uniform±1.0": dither_uniform,
    "tpdf±1.0": dither_tpdf,
    "bayer8±0.5": dither_bayer,
    "ign±0.5": dither_ign,
    "ign±0.7": dither_ign,
    "ign±1.0": dither_ign,
}
AMPS = {
    "none": 0.0, "uniform±0.7": 0.7, "uniform±1.0": 1.0, "tpdf±1.0": 1.0,
    "bayer8±0.5": 0.5, "ign±0.5": 0.5, "ign±0.7": 0.7, "ign±1.0": 1.0,
}


# ---------------------------------------------------------------- 评价
def evaluate(img: np.ndarray) -> dict:
    f = img.astype(np.float64)
    luma = np.rint(0.30 * f[..., 0] + 0.59 * f[..., 1] + 0.11 * f[..., 2])
    longest = 0
    long_runs = 0
    zero = 0
    total = 0
    for row in luma.astype(np.int64):
        d = np.diff(row)
        zero += int((d == 0).sum())
        total += int(d.size)
        bounds = np.concatenate(([0], np.flatnonzero(d != 0) + 1, [row.size]))
        runs = np.diff(bounds)
        longest = max(longest, int(runs.max()))
        long_runs += int((runs >= 64).sum())
    # 抖动可见度：3×3 局部标准差的均值（越小越不易察觉）
    p = luma
    lap = (4 * p[1:-1, 1:-1] - p[:-2, 1:-1] - p[2:, 1:-1]
           - p[1:-1, :-2] - p[1:-1, 2:])
    return {
        "longest": longest,
        "long_runs": long_runs,
        "zero": zero / max(1, total),
        "grain": float(np.abs(lap).mean()),
        "levels": int(p.max() - p.min() + 1),
    }


def main() -> int:
    src = make_lowfreq_signal(levels=3.0)
    th, tw = 1440, 2560  # 目标显示分辨率（1:1 虚拟桌面）
    print("=" * 96)
    print("插值方式 × 抖动图案 全组合（超低频场，全屏动态范围仅 3 LSB，放大 5×）")
    print("=" * 96)
    print(f"{'插值':<13}{'抖动':<14}{'最长游程':>9}{'≥64px':>8}{'零差分':>9}"
          f"{'颗粒度':>9}{'色阶数':>8}  判决")
    print("-" * 96)

    best = []
    for interp in ("bilinear", "smoothstep", "catmullrom"):
        up = upsample(src, tw, th, interp)
        for dname, fn in DITHERS.items():
            amp = AMPS[dname]
            out = np.clip(np.rint(up + fn(th, tw, amp)), 0, 255).astype(np.uint8)
            m = evaluate(out)
            ok = m["longest"] <= 16 and m["long_runs"] == 0
            verdict = "√ 无可见色带" if ok else ("色带" if m["long_runs"] else "轻微")
            print(f"{interp:<13}{dname:<14}{m['longest']:9d}{m['long_runs']:8d}"
                  f"{m['zero']*100:8.1f}%{m['grain']:9.2f}{m['levels']:8d}  {verdict}")
            if ok:
                best.append((m["grain"], interp, dname, m))
    print("-" * 96)
    if best:
        best.sort()
        print("无可见色带方案中，按「抖动颗粒度最小（最不易察觉）」排序：")
        for i, (g, interp, dname, m) in enumerate(best[:5], 1):
            print(f"  {i}. {interp:<12} + {dname:<12} 颗粒度 {g:.2f} "
                  f"最长游程 {m['longest']}px 零差分 {m['zero']*100:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
