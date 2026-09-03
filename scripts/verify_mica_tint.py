"""Mica 色调层方案的数值验证与可视化对照脚本。

用途
----
1. 校验 Photoshop「颜色」混合模式实现与规范/手算值一致；
2. 校验上层源图像确实**等亮度**（无明暗结构残留）；
3. 校验最终合成图**逐像素亮度恒等于 Lum(G1)**（影像不可能残留的数学保证）；
4. 校验深浅两种模式只改变基色亮度、不改变色相场；
5. 输出一张对照图（原图 / 上层源图像 / 深色合成 / 浅色合成）。

运行（需要 numpy + Pillow）：
    python scripts/verify_mica_tint.py [输出PNG路径]
"""

from __future__ import annotations

import ctypes
import importlib.util
import math
import sys
from pathlib import Path
from typing import List, Tuple

import numpy as np
from PIL import Image, ImageDraw

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_MODULE_PATH = _PROJECT_ROOT / "freeassetfilter" / "ui" / "components" / "mica_tint.py"

_spec = importlib.util.spec_from_file_location("mica_tint", _MODULE_PATH)
if _spec is None or _spec.loader is None:  # pragma: no cover
    raise ImportError(f"无法加载模块: {_MODULE_PATH}")
mt = importlib.util.module_from_spec(_spec)
# 必须先行注册，否则模块内的 @dataclass 无法解析自身的类型注解命名空间。
sys.modules["mica_tint"] = mt
_spec.loader.exec_module(mt)


# ---------------------------------------------------------------------------
# 测试素材
# ---------------------------------------------------------------------------

def make_test_wallpaper(w: int = 1200, h: int = 675) -> np.ndarray:
    """合成一张结构极强的测试壁纸（天空渐变 + 太阳 + 山脊剪影 + 高频条纹）。

    刻意包含：平滑渐变、高亮圆盘、锐利轮廓（山脊）、高对比高频条纹（模拟文字），
    用于验证合成结果中这些结构被完全移除。

    Args:
        w: 宽度（像素）。
        h: 高度（像素）。

    Returns:
        shape (h, w, 3) 的 uint8 数组。
    """
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    u = xx / w
    v = yy / h

    img = np.zeros((h, w, 3), dtype=np.float32)

    # 天空：顶部深蓝 → 地平线橙红
    sky_top = np.array([0.05, 0.12, 0.42], dtype=np.float32)
    sky_bot = np.array([0.98, 0.52, 0.18], dtype=np.float32)
    t = np.clip(v / 0.72, 0.0, 1.0)[..., None]
    sky = sky_top * (1 - t) + sky_bot * t
    img += sky

    # 太阳：高亮圆盘（过曝高光，用于检验门控）
    cx, cy, r = 0.72 * w, 0.30 * h, 0.075 * h
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    sun = np.clip(1.0 - d / r, 0.0, 1.0) ** 0.5
    img += sun[..., None] * np.array([1.0, 0.93, 0.55], dtype=np.float32)

    # 山脊：两层锐利剪影（冷色 → 检验轮廓去除）
    ridge1 = 0.60 * h + 0.10 * h * np.sin(u * 8.0) + 0.05 * h * np.sin(u * 21.0)
    ridge2 = 0.72 * h + 0.07 * h * np.sin(u * 5.0 + 1.7) + 0.03 * h * np.sin(u * 17.0)
    m1 = (yy > ridge1).astype(np.float32)[..., None]
    m2 = (yy > ridge2).astype(np.float32)[..., None]
    img = img * (1 - m1) + m1 * np.array([0.16, 0.20, 0.34], dtype=np.float32)
    img = img * (1 - m2) + m2 * np.array([0.06, 0.09, 0.16], dtype=np.float32)

    # 高频条纹 + 棋盘（模拟文字与 UI 细节，必须被完全抹除）
    stripe = (((xx // 6).astype(np.int32) + (yy // 6).astype(np.int32)) % 2).astype(np.float32)
    stripe *= (v > 0.80).astype(np.float32)
    img += stripe[..., None] * 0.55

    checker = (((xx // 14).astype(np.int32) % 2) ^ ((yy // 14).astype(np.int32) % 2)).astype(np.float32)
    checker *= ((u > 0.04) & (u < 0.22) & (v > 0.10) & (v < 0.34)).astype(np.float32)
    img += checker[..., None] * np.array([0.7, -0.2, 0.4], dtype=np.float32)

    return (np.clip(img, 0.0, 1.0) * 255.0).astype(np.uint8)


def get_real_wallpaper() -> str:
    """通过 Win32 API 读取当前桌面壁纸路径（与线上代码同一入口）。

    Returns:
        壁纸绝对路径；失败返回空字符串。
    """
    try:
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.user32.SystemParametersInfoW(0x0073, 260, buf, 0):
            p = buf.value
            if p and Path(p).exists():
                return p
    except Exception:
        pass
    return ""


def load_image_u8(path: str, max_side: int = 1920) -> np.ndarray:
    """读取图片为 (h, w, 3) uint8，并按长边缩放。

    Args:
        path: 图片路径。
        max_side: 长边上限。

    Returns:
        uint8 数组。
    """
    im = Image.open(path).convert("RGB")
    if max(im.size) > max_side:
        r = max_side / max(im.size)
        im = im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))), Image.BOX)
    return np.asarray(im, dtype=np.uint8)


# ---------------------------------------------------------------------------
# 校验指标
# ---------------------------------------------------------------------------

def _to01(arr_u8: np.ndarray) -> np.ndarray:
    """uint8 → float 0..1。"""
    return arr_u8.astype(np.float32) / 255.0


def hue_angle_deg(ab: np.ndarray) -> np.ndarray:
    """Oklab (a,b) → 色相角（度，0..360）。"""
    return np.degrees(np.arctan2(ab[..., 1], ab[..., 0])) % 360.0


def structure_residual(image_u8: np.ndarray, sigma: float = 8.0) -> float:
    """高通残差 RMS（0..255 灰阶单位）：衡量"影像/轮廓"残留程度。

    用同一套低通把图像模糊一遍，再与原图相减；若图像只含低频色度变化，
    残差应接近 0（仅抖动噪声量级）。

    Args:
        image_u8: shape (h, w, 3) 的 uint8 图像。
        sigma: 低通标准差。

    Returns:
        RMS 残差（0..255 单位）。
    """
    arr = _to01(image_u8)
    ones = np.ones(arr.shape[:2], dtype=np.float32)
    for c in range(arr.shape[2]):
        pass
    low = np.stack(
        [mt.blur_chroma(
            np.stack([arr[..., c], np.zeros_like(arr[..., c])], axis=-1),
            ones, sigma, downscale=1,
        )[..., 0] for c in range(arr.shape[2])],
        axis=-1,
    )
    return float(np.sqrt(np.mean((arr - low) ** 2)) * 255.0)


def check_color_blend_reference() -> List[Tuple[str, str, bool]]:
    """校验 Photoshop「颜色」混合实现与规范 / 手算值一致。

    Returns:
        ``(检查项, 实测值, 是否通过)`` 列表。
    """
    results: List[Tuple[str, str, bool]] = []

    # 1) 手算基准：Color(#F5F5F5, 纯蓝) = (244, 244, 255)
    g1l = (np.array([0xF5, 0xF5, 0xF5], dtype=np.float32) / 255.0).reshape(1, 3)
    blue = np.array([[0.0, 0.0, 1.0]], dtype=np.float32)
    got = np.rint(mt.color_blend(g1l, blue) * 255).astype(int)[0]
    ok = tuple(got) == (244, 244, 255)
    results.append(("PS Color(#F5F5F5, 纯蓝) == (244,244,255)", str(tuple(got)), ok))

    # 2) 手算基准：Color(#1A1A1A, 纯蓝) = (0, 0, 236)
    g1d = (np.array([0x1A, 0x1A, 0x1A], dtype=np.float32) / 255.0).reshape(1, 3)
    got2 = np.rint(mt.color_blend(g1d, blue) * 255).astype(int)[0]
    ok2 = tuple(got2) == (0, 0, 236)
    results.append(("PS Color(#1A1A1A, 纯蓝) == (0,0,236)", str(tuple(got2)), ok2))

    # 3) ClipColor 严格保亮度 + 落在 [0,1]。
    # 输入必须取自本管线的真实域：c = S + (Lum(B) − Lum(S))，其中 S、B 均在
    # sRGB 色域内 ⇒ luma_ps(c) = Lum(B) ∈ [0,1]。（ClipColor 在该前提下成立，
    # 用 [-1,2] 的任意随机数做测试是无效输入，会误报。）
    rng = np.random.default_rng(7)
    s_rand = rng.random((20000, 3)).astype(np.float32)
    b_rand = rng.random((20000, 3)).astype(np.float32)
    c = s_rand + (mt.luma_ps(b_rand) - mt.luma_ps(s_rand))[..., None]
    cc = mt.clip_color(c)
    err = float(np.max(np.abs(mt.luma_ps(cc) - mt.luma_ps(c))))
    in_range = bool(((cc >= -1e-4) & (cc <= 1 + 1e-4)).all())
    results.append(
        ("ClipColor 保亮度且落在 [0,1]", f"Δ={err:.3e}, in_range={in_range}",
         err < 1e-4 and in_range)
    )

    # 4) SetLum 命中目标亮度（目标取自 [0,1]，同为本管线真实域）
    tgt = rng.random((20000,)).astype(np.float32)
    out = mt.set_lum(rng.random((20000, 3)).astype(np.float32), tgt)
    err2 = float(np.max(np.abs(mt.luma_ps(out) - tgt)))
    results.append(("SetLum 命中目标亮度 (max Δ)", f"{err2:.3e}", err2 < 1e-4))

    # 5) Color 混合结果亮度 == 下层亮度（核心不变量）
    b = rng.random((20000, 3)).astype(np.float32)
    s = rng.random((20000, 3)).astype(np.float32)
    o = mt.color_blend(b, s)
    err3 = float(np.max(np.abs(mt.luma_ps(o) - mt.luma_ps(b))))
    results.append(("Color 结果亮度 == 下层亮度 (max Δ)", f"{err3:.3e}", err3 < 1e-4))

    # 6) 中性灰下层 + 任意上层 → 结果色相 == 上层色相（色相不被改变）
    grey = np.full((20000, 3), 0.5, dtype=np.float32)
    o2 = mt.color_blend(grey, s)
    h_src = np.degrees(np.arctan2(np.sqrt(3) / 2 * (s[..., 1] - s[..., 2]),
                                  s[..., 0] - 0.5 * (s[..., 1] + s[..., 2]))) % 360
    h_out = np.degrees(np.arctan2(np.sqrt(3) / 2 * (o2[..., 1] - o2[..., 2]),
                                  o2[..., 0] - 0.5 * (o2[..., 1] + o2[..., 2]))) % 360
    dh = np.abs(((h_out - h_src + 180) % 360) - 180)
    results.append(("灰底下层：色相不偏移 (max Δ°)", f"{float(dh.max()):.4f}",
                    float(dh.max()) < 0.05))
    return results


def run_pipeline_checks(wall: np.ndarray, label: str, out_w: int, out_h: int) -> Tuple[
    List[Tuple[str, str, bool]], np.ndarray, np.ndarray, np.ndarray
]:
    """对一张壁纸跑通深浅两种模式，并计算全部校验指标。

    Args:
        wall: shape (h, w, 3) 的 uint8 壁纸。
        label: 素材名（用于输出）。
        out_w: 合成输出宽度。
        out_h: 合成输出高度。

    Returns:
        ``(checks, src_dark, out_dark, out_light)``。
    """
    wh, ww = wall.shape[0], wall.shape[1]
    # 窗口居中，取壁纸中央 80% 区域做采样矩形（等价一个 16:9 窗口）
    win_w = int(ww * 0.8)
    win_h = int(wh * 0.8)
    rect = ((ww - win_w) / 2.0, (wh - win_h) / 2.0, float(win_w), float(win_h))

    cfg_dark = mt.TintConfig(dark=True, gain=1.0, alpha=0.85, sigma=96.0)
    cfg_light = mt.TintConfig(dark=False, gain=1.0, alpha=0.85, sigma=96.0)

    res_d = mt.bake_tint(wall, rect, out_w, out_h, cfg_dark)
    res_l = mt.bake_tint(wall, rect, out_w, out_h, cfg_light)

    checks: List[Tuple[str, str, bool]] = []

    # A) 上层源图像等亮度（去明度是否彻底）
    lum_src = mt.luma_ps(_to01(res_d.source_layer)) * 255.0
    std_src = float(lum_src.std())
    checks.append((f"[{label}] 上层源图像亮度标准差 (应 ≈0)", f"{std_src:.3f} /255", std_src < 2.0))

    # B) 最终合成逐像素亮度 == Lum(G1)（影像残留的数学上限）
    for name, res, g1 in (("深色", res_d, mt.G1_DARK), ("浅色", res_l, mt.G1_LIGHT)):
        lum_b = mt.luma_ps(np.array(g1, dtype=np.float32) / 255.0) * 255.0
        lum_o = mt.luma_ps(_to01(res.image)) * 255.0
        dev = float(np.max(np.abs(lum_o - lum_b)))
        checks.append(
            (f"[{label}] {name}合成 逐像素亮度 == Lum(G1)={lum_b:.1f} (max Δ)",
             f"{dev:.2f} /255", dev <= 1.5)
        )

    # C) 结构残留（轮廓是否被抹除）
    for name, res in (("深色", res_d), ("浅色", res_l)):
        resid = structure_residual(res.image, sigma=8.0)
        checks.append((f"[{label}] {name}合成 高通结构残差 RMS", f"{resid:.3f} /255", resid < 1.5))
    resid_src = structure_residual(res_d.source_layer, sigma=8.0)
    checks.append((f"[{label}] 上层源图像 高通结构残差 RMS", f"{resid_src:.3f} /255", resid_src < 1.5))

    # D) 色相保真：合成结果 vs 上层源图像（圆周平均误差）
    for name, res, g1 in (("深色", res_d, mt.G1_DARK), ("浅色", res_l, mt.G1_LIGHT)):
        ab_o = mt.chroma_from_srgb(res.image)[0]
        ab_s = mt.chroma_from_srgb(res_d.source_layer)[0]
        keep = np.sqrt(ab_s[..., 0] ** 2 + ab_s[..., 1] ** 2) > 0.006
        if keep.any():
            dh = np.abs(((hue_angle_deg(ab_o)[keep] - hue_angle_deg(ab_s)[keep] + 180) % 360) - 180)
            mean_dh = float(dh.mean())
            checks.append((f"[{label}] {name}合成 相对上层的色相偏移 (均值)",
                           f"{mean_dh:.2f}°", mean_dh < 6.0))
        del g1

    # E) 深浅模式色相场一致（只应改变亮度基色）
    ab_d = mt.chroma_from_srgb(res_d.image)[0]
    ab_l = mt.chroma_from_srgb(res_l.image)[0]
    keep = np.sqrt(ab_d[..., 0] ** 2 + ab_d[..., 1] ** 2) > 0.006
    if keep.any():
        dh = np.abs(((hue_angle_deg(ab_d)[keep] - hue_angle_deg(ab_l)[keep] + 180) % 360) - 180)
        checks.append((f"[{label}] 深色↔浅色 色相场一致性 (均值Δ)",
                       f"{float(dh.mean()):.2f}°", float(dh.mean()) < 6.0))

    # F) 色度幅度诊断（非通过/失败项，仅打印，用于调参）
    for name, res in (("深色", res_d), ("浅色", res_l)):
        ab = mt.chroma_from_srgb(res.image)[0]
        c = np.sqrt(ab[..., 0] ** 2 + ab[..., 1] ** 2)
        print(f"    · [{label}] {name}合成 Oklab 彩度 C: mean={c.mean():.4f} "
              f"p95={np.percentile(c, 95):.4f} max={c.max():.4f}")

    # G) 原图 vs 合成图：亮度相关性（必须≈0，证明明暗结构未泄漏）
    lum_wall = mt.luma_ps(_to01(crop_center(wall, res.image.shape[1], res.image.shape[0]))) * 255.0
    lum_out = mt.luma_ps(_to01(res_d.image)) * 255.0
    a = lum_wall - lum_wall.mean()
    b = lum_out - lum_out.mean()
    corr = float((a * b).sum() / math.sqrt(max((a * a).sum() * (b * b).sum(), 1e-9)))
    checks.append((f"[{label}] 原图↔合成图 亮度相关性 (应≈0)", f"{corr:+.4f}", abs(corr) < 0.05))

    return checks, res_d.source_layer, res_d.image, res_l.image


def crop_center(img: np.ndarray, w: int, h: int) -> np.ndarray:
    """居中裁切到 ``(h, w)``（不足则缩放补齐）。"""
    ih, iw = img.shape[0], img.shape[1]
    if iw < w or ih < h:
        im = Image.fromarray(img).resize((max(w, iw), max(h, ih)), Image.BILINEAR)
        img = np.asarray(im)
        ih, iw = img.shape[0], img.shape[1]
    x0 = (iw - w) // 2
    y0 = (ih - h) // 2
    return img[y0:y0 + h, x0:x0 + w]


# ---------------------------------------------------------------------------
# 可视化
# ---------------------------------------------------------------------------

def build_figure(rows: List[Tuple[str, np.ndarray]], out_path: Path,
                 cell_w: int = 520, cell_h: int = 292) -> None:
    """把若干 (标题, 图像) 排成 2 列网格成对照图并保存。

    Args:
        rows: ``(标题, uint8 图像)`` 列表。
        out_path: 输出 PNG 路径。
        cell_w: 单个图像单元格宽度（缩放目标）。
        cell_h: 单个图像单元格高度（缩放目标）。
    """
    if not rows:
        return
    cols = 2
    rows_n = (len(rows) + cols - 1) // cols
    gap = 10
    label_h = 22
    bg = (24, 24, 24)
    fg = (235, 235, 235)

    canvas_w = cols * cell_w + (cols + 1) * gap
    canvas_h = rows_n * (cell_h + label_h) + (rows_n + 1) * gap
    canvas = Image.new("RGB", (canvas_w, canvas_h), bg)
    draw = ImageDraw.Draw(canvas)

    for i, (title, im) in enumerate(rows):
        r, c = divmod(i, cols)
        x = gap + c * (cell_w + gap)
        y = gap + r * (cell_h + label_h + gap)
        draw.text((x + 4, y + 4), title, fill=fg)
        tile = Image.fromarray(im).resize((cell_w, cell_h), Image.BILINEAR)
        canvas.paste(tile, (x, y + label_h))
        # 描边，便于辨识
        draw.rectangle(
            [x, y + label_h, x + cell_w - 1, y + label_h + cell_h - 1],
            outline=(60, 60, 60),
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)
    print(f"\n对照图已保存: {out_path}  ({canvas_w}x{canvas_h})")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> int:
    """执行全部校验并输出对照图。

    Returns:
        0 = 全部通过；1 = 存在未通过项。
    """
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        _PROJECT_ROOT / "data" / "mica_tint_verify.png"
    )

    print("=" * 78)
    print("Mica 色调层（背景图色度采样 + Photoshop「颜色」混合）— 数值验证")
    print("=" * 78)

    all_checks: List[Tuple[str, str, bool]] = []
    all_checks += check_color_blend_reference()

    out_w, out_h = 640, 360

    # 素材 1：合成测试图
    wall = make_test_wallpaper()
    checks, src_d, out_d, out_l = run_pipeline_checks(wall, "合成图", out_w, out_h)
    all_checks += checks
    g1_dark_swatch = np.zeros((out_h, out_w, 3), dtype=np.uint8)
    g1_dark_swatch[...] = np.array(mt.G1_DARK, dtype=np.uint8)
    g1_light_swatch = np.zeros((out_h, out_w, 3), dtype=np.uint8)
    g1_light_swatch[...] = np.array(mt.G1_LIGHT, dtype=np.uint8)
    rows = [
        (f"[1] SYNTH wallpaper (sky+sun+ridge+high-freq)",
         crop_center(wall, out_w, out_h)),
        (f"[2] SOURCE layer S (iso-luminant chroma image)",
         src_d),
        (f"[3] COLOR over G1 DARK  #{mt.G1_DARK[0]:02X}{mt.G1_DARK[1]:02X}{mt.G1_DARK[2]:02X}",
         out_d),
        (f"[4] COLOR over G1 LIGHT #{mt.G1_LIGHT[0]:02X}{mt.G1_LIGHT[1]:02X}{mt.G1_LIGHT[2]:02X}",
         out_l),
        (f"[5] G1 DARK base #{mt.G1_DARK[0]:02X}{mt.G1_DARK[1]:02X}{mt.G1_DARK[2]:02X} (reference swatch)",
         g1_dark_swatch),
        (f"[6] G1 LIGHT base #{mt.G1_LIGHT[0]:02X}{mt.G1_LIGHT[1]:02X}{mt.G1_LIGHT[2]:02X} (reference swatch)",
         g1_light_swatch),
    ]

    # 素材 2：真实桌面壁纸（若可读到）
    wp = get_real_wallpaper()
    if wp:
        try:
            real = load_image_u8(wp)
            r_checks, r_src, r_out_d, r_out_l = run_pipeline_checks(real, "真实壁纸", out_w, out_h)
            all_checks += r_checks
            rows += [
                ("[7] REAL wallpaper (original crop)",
                 crop_center(real, out_w, out_h)),
                ("[8] REAL -> SOURCE layer S (iso-luminant chroma image)",
                 r_src),
                ("[9] REAL -> COLOR over G1 DARK", r_out_d),
                ("[10] REAL -> COLOR over G1 LIGHT", r_out_l),
            ]
            print(f"\n已加载真实桌面壁纸: {wp}  {real.shape[1]}x{real.shape[0]}")
        except Exception as exc:  # pragma: no cover
            print(f"\n真实壁纸处理失败（已跳过）: {exc}")

    print("\n" + "-" * 78)
    passed = 0
    for name, value, ok in all_checks:
        flag = "PASS" if ok else "FAIL"
        passed += int(ok)
        print(f"[{flag}] {name:<56} = {value}")
    print("-" * 78)
    print(f"通过 {passed}/{len(all_checks)}")
    print(f"G1 基色: 深色 #{mt.G1_DARK[0]:02X}{mt.G1_DARK[1]:02X}{mt.G1_DARK[1]:02X}"
          f"  浅色 #{mt.G1_LIGHT[0]:02X}{mt.G1_LIGHT[1]:02X}{mt.G1_LIGHT[2]:02X}")
    print(f"G1 Oklab L: 深色 {mt.g1_oklab_l(mt.G1_DARK):.4f}  浅色 {mt.g1_oklab_l(mt.G1_LIGHT):.4f}")
    print(f"色彩倾向（深色合成平均色）: "
          f"#{int(out_d[..., 0].mean()):02X}{int(out_d[..., 1].mean()):02X}{int(out_d[..., 2].mean()):02X}")
    print(f"色彩倾向（浅色合成平均色）: "
          f"#{int(out_l[..., 0].mean()):02X}{int(out_l[..., 1].mean()):02X}{int(out_l[..., 2].mean()):02X}")

    build_figure(rows, Path(out_path))
    return 0 if passed == len(all_checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
