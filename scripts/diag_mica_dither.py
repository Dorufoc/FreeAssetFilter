# -*- coding: utf-8 -*-
"""抖动图案选型：幅值扫描 + 频谱对比（确定最终方案）。

上一轮结论：
* 插值方式**不是** banding 成因（smoothstep 与 bilinear 结果逐位相同，
  因为色调场频率极低，不存在刻面）；
* 成因是 8-bit 量化 + 抖动图案的低频能量过高（白噪声会聚簇，留下长游程）；
* IGN（交错梯度噪声）在 ±0.7 时把最长游程从 37px 压到 6px。

本脚本确定两件事：
1. **幅值** —— 在无可见色带（最长游程 ≤ 16px）前提下取最小幅值（噪点最不可见）；
2. **频谱** —— 量化各图案的「低频能量占比」，验证 IGN 确实把能量推到高频
   （低频能量越低，人眼越不易察觉抖动纹理）。
"""

from __future__ import annotations

import numpy as np

TH, TW = 720, 1280


def dither_uniform(th, tw, amp):
    rng = np.random.default_rng(1337)
    return (rng.random((th, tw, 1), dtype=np.float32) - 0.5) * (2.0 * amp)


def dither_tpdf(th, tw, amp):
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
    return np.tile(_BAYER8, (th // 8 + 1, tw // 8 + 1))[:th, :tw, None] * (2.0 * amp)


def dither_ign(th, tw, amp, ox: int = 0, oy: int = 0):
    xs = (np.arange(tw, dtype=np.float32) + float(ox)).reshape(1, tw)
    ys = (np.arange(th, dtype=np.float32) + float(oy)).reshape(th, 1)
    n = np.mod(52.9829189 * np.mod(0.06711056 * xs + 0.00583715 * ys, 1.0), 1.0)
    return (n - 0.5)[..., None] * (2.0 * amp)


PATTERNS = {
    "uniform(白噪声)": dither_uniform,
    "tpdf(三角)": dither_tpdf,
    "bayer8(有序)": dither_bayer,
    "ign(交错梯度)": dither_ign,
}


def low_freq_ratio(noise: np.ndarray) -> float:
    """噪声的低频能量占比（8×8 块均值的方差 / 总方差）。越低越接近蓝噪声。"""
    n = noise[..., 0].astype(np.float64)
    n = n - n.mean()
    total = float((n ** 2).mean())
    h = (n.shape[0] // 8) * 8
    w = (n.shape[1] // 8) * 8
    blocks = n[:h, :w].reshape(h // 8, 8, w // 8, 8).mean(axis=(1, 3))
    return float((blocks ** 2).mean()) / max(total, 1e-12)


def make_signal(levels: float = 3.0):
    gw, gh = TW // 5, TH // 5
    yy = np.linspace(0.0, 1.0, gh, dtype=np.float32).reshape(gh, 1)
    xx = np.linspace(0.0, 1.0, gw, dtype=np.float32).reshape(1, gw)
    base = (np.sin(xx * 2.1 + 0.3) * 0.5 + np.cos(yy * 1.7) * 0.35
            + np.sin((xx + yy) * 1.1) * 0.15)
    base = (base - base.min()) / (base.max() - base.min())
    return np.repeat((base * levels + 30.0)[..., None], 3, axis=2).astype(np.float32)


def bilinear_up(src, tw, th):
    def _a1(b, n):
        g = b.shape[1]
        xs = np.linspace(0, g - 1, n, dtype=np.float32)
        x0 = np.floor(xs).astype(np.intp)
        w = (xs - x0).astype(np.float32)
        return b[:, x0, :] * (1 - w)[None, :, None] + \
            b[:, np.minimum(x0 + 1, g - 1), :] * w[None, :, None]

    def _a0(b, n):
        g = b.shape[0]
        ys = np.linspace(0, g - 1, n, dtype=np.float32)
        y0 = np.floor(ys).astype(np.intp)
        w = (ys - y0).astype(np.float32)
        return b[y0, :, :] * (1 - w)[:, None, None] + \
            b[np.minimum(y0 + 1, g - 1), :, :] * w[:, None, None]

    return _a0(_a1(src, tw), th)


def score(img: np.ndarray) -> dict:
    f = img.astype(np.float64)
    luma = np.rint(0.30 * f[..., 0] + 0.59 * f[..., 1] + 0.11 * f[..., 2]).astype(np.int64)
    longest, long_runs, zero, total = 0, 0, 0, 0
    for row in luma:
        d = np.diff(row)
        zero += int((d == 0).sum())
        total += int(d.size)
        runs = np.diff(np.concatenate(([0], np.flatnonzero(d != 0) + 1, [row.size])))
        longest = max(longest, int(runs.max()))
        long_runs += int((runs >= 64).sum())
    return {"longest": longest, "long_runs": long_runs, "zero": zero / max(1, total)}


def main() -> int:
    src = make_signal()
    up = bilinear_up(src, TW, TH)

    print("=" * 88)
    print("一、抖动图案的频谱特性（低频能量占比越低 = 越接近蓝噪声 = 越不易察觉）")
    print("=" * 88)
    for name, fn in PATTERNS.items():
        n = fn(TH, TW, 1.0)
        print(f"  {name:<18} 低频能量占比 {low_freq_ratio(n)*100:6.2f}%   "
              f"幅值包络 ±{np.abs(n).max():.3f}")

    print("\n" + "=" * 88)
    print("二、幅值扫描（目标：最长游程 ≤ 16px 且 ≥64px 游程为 0 的最小幅值）")
    print("=" * 88)
    print(f"  {'图案':<18}" + "".join(f"{a:>13}" for a in
                                    (0.5, 0.6, 0.7, 0.8, 1.0, 1.2)))
    print("  " + "-" * 84)
    for name, fn in PATTERNS.items():
        row = f"  {name:<18}"
        for amp in (0.5, 0.6, 0.7, 0.8, 1.0, 1.2):
            img = np.clip(np.rint(up + fn(TH, TW, amp)), 0, 255).astype(np.uint8)
            m = score(img)
            mark = "√" if (m["longest"] <= 16 and m["long_runs"] == 0) else "×"
            row += f"{m['longest']:>10}px{mark:<2}"
        print(row)
    print("  （单元内容为最长平坦游程；√ = 无可见色带）")

    print("\n" + "=" * 88)
    print("三、IGN 屏幕锚定验证（同绝对坐标必得同一噪声）")
    print("=" * 88)
    a = dither_ign(64, 64, 0.7, ox=-1920, oy=-1080)
    b = dither_ign(64, 64, 0.7, ox=-1920, oy=-1080)
    c = dither_ign(64, 64, 0.7, ox=0, oy=0)
    print(f"  同原点可复现：{np.array_equal(a, b)}")
    print(f"  异原点不同  ：{not np.array_equal(a, c)}")
    # 平移等变性：层坐标 (i+dy, j+dx) 在原点 O 下的值 == 层坐标 (i,j) 在原点 O+(dx,dy) 下的值
    base = dither_ign(200, 200, 0.7, ox=0, oy=0)
    shifted = dither_ign(200, 200, 0.7, ox=37, oy=11)
    same = np.allclose(base[11:, 37:], shifted[:-11, :-37], atol=1e-5)
    print(f"  平移等变（窗口位移时纹理锚定壁纸）：{same}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
