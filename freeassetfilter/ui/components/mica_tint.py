"""Mica 色调层（Tint Layer）—— 背景图逐像素色度提取 + Photoshop「颜色」混合。

本模块是 ``MICA_TINT_DESIGN.md`` 的参考实现，为 ``ui`` 目录下的 Mica / 亚克力
背景提供一条「只取颜色、不取影像」的合成路径。

⚠ 关键定位：**这是整幅图像 × 整幅图像的逐像素混合，不是取几个采样点颜色再填色。**
上层（Source, S）始终是一张与窗口同分辨率的完整图像，每个像素都独立携带壁纸
对应位置的色相与彩度；只是它的"明度"被逐像素抹平，且空间细节被低通掉。

五条核心性质
------------
1. **逐像素去明度**：上层每个像素转入 Oklab 后丢弃 ``L`` 通道，再以常数
   ``L = L(G1)`` 重建 —— 得到一张**等亮度**的全分辨率色度图。
2. **逐像素去轮廓**：对 Oklab 的 ``(a, b)`` 平面做**归一化加权高斯模糊**
   （权重由线性亮度的可靠性门控给出），低通掉轮廓细节，同时抑制暗部/高光的
   不可靠色度。模糊只作用在色度平面，因此不会产生任何明暗光晕。
3. **逐像素色彩整形**：增益 + 双曲正切软限幅，逐像素独立作用，保留空间变化。
4. **Photoshop「颜色」混合**：``Color(B, S) = SetLum(S, Lum(B))``，整幅 S 与
   整幅 G1 逐像素混合，结果取下层亮度 + 上层色相饱和度。
5. **亮度锁死（数学保证）**：``SetLum`` 的 ``ClipColor`` 严格保持 ``Lum`` 不变，
   故输出逐像素亮度恒等于 ``Lum(G1)``（常数）。**亮度为常数 ⇒ 壁纸的明暗与
   轮廓在数学上不可能残留**，残留的只有低频色度倾向 —— 但那仍是逐像素变化的
   图像，不是平涂色块。

层级定义
--------
* **下层（Backdrop / B）**：G1 纯色图层，整幅不透明。深色模式 ``#1a1a1a``，
  浅色模式 ``#f5f5f5``（来自 ``ThemeManager.surface`` →
  ``appearance.colors.gray[_light].g1``）。
* **上层（Source / S）**：壁纸经"去明度 + 去轮廓 + 整形"后的等亮度彩色图像，
  分辨率与合成输出一致。

依赖：仅 ``numpy``。数学内核不依赖 Qt / PIL，可在无 GUI 环境下做单元测试。
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: G1 基色层（深色模式）= gray.g1。
G1_DARK: Tuple[int, int, int] = (0x1A, 0x1A, 0x1A)
#: G1 基色层（浅色模式）= gray_light.g1。
G1_LIGHT: Tuple[int, int, int] = (0xF5, 0xF5, 0xF5)
#: 旧实现使用的纯黑 / 纯白基色，仅供对照与 A/B 验证。
G1_ALT_DARK: Tuple[int, int, int] = (0x00, 0x00, 0x00)
G1_ALT_LIGHT: Tuple[int, int, int] = (0xFF, 0xFF, 0xFF)

#: 色度软上限（Oklab chroma）。深色可承受更浓，浅色必须更收敛，
#: 否则高亮度下极易出现刺眼的荧光色。
CHROMA_CAP_DARK: float = 0.055
CHROMA_CAP_LIGHT: float = 0.030

#: 去轮廓高斯模糊的默认标准差（**烘焙分辨率像素**，与窗口尺寸无关）。
BLUR_SIGMA_DEFAULT: float = 96.0
#: 模糊标准差允许区间（烘焙分辨率像素）。
BLUR_SIGMA_MIN: float = 16.0
BLUR_SIGMA_MAX: float = 256.0

#: 采样区域相对窗口长边的最小外扩比例。
SAMPLE_MARGIN_RATIO_MIN: float = 0.10
#: 采样区域必须至少外扩 N 个模糊标准差，避免边界处色度被钳制污染。
SAMPLE_MARGIN_SIGMA: float = 3.0

#: 明度门控：线性亮度低于 ``lo``（压暗暗部）或高于 ``hi``（过曝高光）的像素，
#: 其色度不可靠，权重按 smoothstep 衰减到 0。
CHROMA_LUMA_GATE_LO: float = 0.010
CHROMA_LUMA_GATE_HI: float = 0.990
#: 门控过渡带宽度（线性亮度单位），避免硬边掩膜产生块状伪影。
CHROMA_LUMA_GATE_FEATHER: float = 0.010

#: 色域映射二分迭代次数。
GAMUT_MAP_ITERS: int = 12
#: 抖动随机种子（固定 ⇒ 烘焙结果跨重绘稳定，不会闪烁）。
DITHER_SEED: int = 42

_EPS: float = 1e-6


# ---------------------------------------------------------------------------
# 基础色彩变换
# ---------------------------------------------------------------------------

def srgb_to_linear_lut() -> np.ndarray:
    """返回 256 项 sRGB(0..255) → 线性光(0..1) 查表。

    Returns:
        shape (256,) 的 float32 数组，索引即 8-bit sRGB 编码值。
    """
    v = np.arange(256, dtype=np.float64) / 255.0
    lin = np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)
    return lin.astype(np.float32)


# 模块级缓存：查表在进程生命周期内恒定。
_LUT_LINEAR: np.ndarray = srgb_to_linear_lut()


def linear_from_srgb_u8(arr: np.ndarray) -> np.ndarray:
    """8-bit sRGB uint8 → 线性光 float32（查表，无幂运算）。

    Args:
        arr: shape (..., 3) 的 uint8 数组。

    Returns:
        同 shape 的 float32 线性光数组，取值 [0, 1]。
    """
    return _LUT_LINEAR[np.asarray(arr, dtype=np.uint8)]


def srgb_from_linear(lin: np.ndarray) -> np.ndarray:
    """线性光 float → sRGB 编码值 float（0..1，允许越界，由调用方裁剪）。

    Args:
        lin: shape (..., 3) 的线性光数组。

    Returns:
        同 shape 的 sRGB 编码数组。
    """
    lin = np.maximum(lin, 0.0)
    lo = lin * 12.92
    hi = 1.055 * np.power(np.maximum(lin, _EPS), 1.0 / 2.4) - 0.055
    return np.where(lin <= 0.0031308, lo, hi)


# Oklab 变换矩阵（Björn Ottosson, 2020）。
_M_RGB_TO_LMS = np.array(
    [
        [0.4122214708, 0.5363325363, 0.0514459929],
        [0.2119034982, 0.6806995451, 0.1073969566],
        [0.0883024619, 0.2817188376, 0.6299787005],
    ],
    dtype=np.float32,
)
_M_LMS_TO_LAB = np.array(
    [
        [0.2104542553, 0.7936177850, -0.0040720468],
        [1.9779984951, -2.4285922050, 0.4505937099],
        [0.0259040371, 0.7827717662, -0.8086757660],
    ],
    dtype=np.float32,
)
_M_LAB_TO_LMS = np.array(
    [
        [1.0, 0.3963377774, 0.2158037573],
        [1.0, -0.1055613458, -0.0638541728],
        [1.0, -0.0894841775, -1.2914855480],
    ],
    dtype=np.float32,
)
_M_LMS_TO_RGB = np.array(
    [
        [4.0767416621, -3.3077115913, 0.2309699292],
        [-1.2684380046, 2.6097574011, -0.3413193965],
        [-0.0041960863, -0.7034186147, 1.7076147010],
    ],
    dtype=np.float32,
)


def oklab_from_linear_rgb(lin: np.ndarray) -> np.ndarray:
    """线性 sRGB → Oklab (L, a, b)，逐像素独立。

    Args:
        lin: shape (..., 3) 线性光数组。

    Returns:
        同 shape 的 Oklab 数组，``L`` ∈ [0,1]，``a``/``b`` 通常 ∈ [-0.4, 0.4]。
    """
    lms = np.tensordot(lin, _M_RGB_TO_LMS.T, axes=([-1], [0]))
    lms_cbrt = np.cbrt(np.maximum(lms, 0.0))
    return np.tensordot(lms_cbrt, _M_LMS_TO_LAB.T, axes=([-1], [0]))


def _linear_rgb_from_lab_raw(lab: np.ndarray) -> np.ndarray:
    """Oklab → 线性 sRGB（不映射色域，允许越界）。"""
    lms_cbrt = np.tensordot(lab, _M_LAB_TO_LMS.T, axes=([-1], [0]))
    lms = lms_cbrt * lms_cbrt * lms_cbrt
    return np.tensordot(lms, _M_LMS_TO_RGB.T, axes=([-1], [0]))


def linear_rgb_from_oklab(lab: np.ndarray, iters: int = GAMUT_MAP_ITERS) -> np.ndarray:
    """Oklab → 线性 sRGB，越界像素**按色度二分收缩**回到 sRGB 色域内。

    与直接 ``clip`` 相比，本做法保持 ``L`` 与色相角不变、只降低彩度，
    因此不会出现"削顶偏色"（如亮蓝被削成青）。

    实现上先尝试 ``scale=1``（绝大多数 sRGB 色域内的输入直接命中），仅对
    越界子集做二分（先取出越界子集，迭代后再散射回原位）。**保持 in-gamut
    像素的浮点级精度**（无 bisection 残留误差）。

    Args:
        lab: shape (..., 3) 的 Oklab 数组。
        iters: 二分迭代次数，默认 :data:`GAMUT_MAP_ITERS`（12 次 ≈ 1/4096）。

    Returns:
        同 shape 的线性 sRGB 数组，逐像素落在 [0, 1]。
    """
    rgb = _linear_rgb_from_lab_raw(lab)
    bad = np.any((rgb < -_EPS) | (rgb > 1.0 + _EPS), axis=-1)
    if not bool(bad.any()):
        return np.clip(rgb, 0.0, 1.0)

    l = lab[..., 0:1]
    a = lab[..., 1:2]
    b = lab[..., 2:3]

    flat_l = l.reshape(-1, 1)
    flat_a = a.reshape(-1, 1)
    flat_b = b.reshape(-1, 1)
    idx = np.flatnonzero(bad.reshape(-1))

    sl = flat_l[idx]
    sa = flat_a[idx]
    sb = flat_b[idx]
    lo = np.zeros_like(sa)
    hi = np.ones_like(sa)
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        trial = _linear_rgb_from_lab_raw(np.concatenate([sl, sa * mid, sb * mid], axis=-1))
        ok = np.all((trial >= -_EPS) & (trial <= 1.0 + _EPS), axis=-1, keepdims=True)
        lo = np.where(ok, mid, lo)
        hi = np.where(ok, hi, mid)

    scale = np.ones((flat_a.shape[0], 1), dtype=flat_a.dtype)
    scale[idx] = lo
    out = _linear_rgb_from_lab_raw(
        np.concatenate([flat_l, flat_a * scale, flat_b * scale], axis=-1)
    )
    return np.clip(out.reshape(lab.shape), 0.0, 1.0)


def srgb_from_oklab(lab: np.ndarray, iters: int = GAMUT_MAP_ITERS) -> np.ndarray:
    """Oklab → sRGB 编码值（含色域映射），返回 0..1。

    Args:
        lab: shape (..., 3) 的 Oklab 数组。
        iters: 色域映射二分迭代次数。

    Returns:
        同 shape 的 sRGB 编码数组，落在 [0, 1]。
    """
    return srgb_from_linear(linear_rgb_from_oklab(lab, iters))


# ---------------------------------------------------------------------------
# Photoshop「颜色」混合模式
# ---------------------------------------------------------------------------

def luma_ps(c: np.ndarray) -> np.ndarray:
    """Photoshop / PDF 规范定义的亮度：0.3 / 0.59 / 0.11 加权。

    重要：该亮度定义在**伽马编码后的 sRGB 分量**上取值（Rec.601 luma on gamma
    values），正是 Photoshop 内部 Hue / Saturation / Color / Luminosity 四模式
    所使用的定义；它与 Rec.709 线性亮度不是一回事，**不可替换**。

    Args:
        c: shape (..., 3) 的 sRGB 编码数组（0..1）。

    Returns:
        shape (...) 的亮度数组。
    """
    return 0.3 * c[..., 0] + 0.59 * c[..., 1] + 0.11 * c[..., 2]


def clip_color(c: np.ndarray) -> np.ndarray:
    """把越界颜色拉回 [0,1] 且**严格保持亮度与色相**（PDF 规范 ClipColor）。

    先抬升负值下界，再压低超界上界；两步都沿"保亮度、保色相"方向缩放，
    且 ``luma_ps`` 在变换前后严格相等（可用单测验证）。

    Args:
        c: shape (..., 3) 数组，允许越界。

    Returns:
        同 shape 数组，逐通道落在 [0, 1]，且 ``luma_ps`` 与输入一致。
    """
    l = luma_ps(c)[..., None]
    n = c.min(axis=-1, keepdims=True)
    # 分支 1：存在负通道 → 以亮度为锚点按比例抬升，使最小值恰好抬到 0。
    c = np.where(n < 0.0, l + (c - l) * (l / np.maximum(l - n, _EPS)), c)
    # 分支 2：存在 >1 通道 → 以亮度为锚点按比例压缩，使最大值恰好压到 1。
    x = c.max(axis=-1, keepdims=True)
    c = np.where(x > 1.0, l + (c - l) * ((1.0 - l) / np.maximum(x - l, _EPS)), c)
    return c


def set_lum(c: np.ndarray, l: np.ndarray) -> np.ndarray:
    """把颜色 ``c`` 的亮度改为 ``l``，保持色相与彩度（PDF 规范 SetLum）。

    Args:
        c: shape (..., 3) 的源颜色。
        l: shape (...) 或与 ``c`` 可广播的目标亮度。

    Returns:
        同 shape 数组，``luma_ps`` 等于 ``l``（除浮点误差）。
    """
    l = np.asarray(l, dtype=np.float32)
    if l.ndim < c.ndim:
        l = l[..., None]
    d = l - luma_ps(c)[..., None]
    return clip_color(c + d)


def color_blend(backdrop: np.ndarray, source: np.ndarray) -> np.ndarray:
    """Photoshop「颜色」（Color）混合模式，逐像素。

    语义：结果取**下层的亮度** + **上层的色相与饱和度**；
    实现即 ``SetLum(Source, Lum(Backdrop))``。

    Args:
        backdrop: shape (..., 3) 下层（本项目为 G1 纯色图层，整幅同值）。
        source: shape (..., 3) 上层（本项目为等亮度色度图像，逐像素变化）。

    Returns:
        同 shape 的混合结果，落在 [0, 1]。

    Examples:
        >>> import numpy as np
        >>> g1 = np.array([0xF5, 0xF5, 0xF5], dtype=np.float32) / 255.0
        >>> blue = np.array([0.0, 0.0, 1.0], dtype=np.float32)
        >>> np.rint(color_blend(g1, blue) * 255).astype(int)
        array([244, 244, 255])
    """
    return set_lum(source, luma_ps(backdrop))


# ---------------------------------------------------------------------------
# 采样区域与几何
# ---------------------------------------------------------------------------

def sample_rect_px(
    src_rect_px: Tuple[float, float, float, float],
    sigma_px: float,
    wall_w: int,
    wall_h: int,
) -> Tuple[float, float, float, float]:
    """在窗口采样矩形基础上外扩，得到实际用于采样的壁纸像素矩形。

    外扩量取两者的较大值，二者各有明确来由：

    * ``SAMPLE_MARGIN_RATIO_MIN × max(w, h)``：窗口贴在壁纸边缘时，保证外侧
      cell 仍能采满，避免拖拽过程中出现色调跳变；
    * ``SAMPLE_MARGIN_SIGMA × σ``：后续要对色度做标准差 σ 的高斯低通，若采样
      区域不外扩 ~3σ，边界处的钳制（CLAMP_TO_EDGE）会把边缘色度"抹回去"。

    Args:
        src_rect_px: ``(x, y, w, h)`` 窗口在壁纸像素坐标系中的矩形（可越界）。
        sigma_px: 去轮廓高斯的标准差（**壁纸像素**单位）。
        wall_w: 壁纸宽度（像素）。
        wall_h: 壁纸高度（像素）。

    Returns:
        ``(x, y, w, h)`` 外扩后的壁纸像素矩形（可越界，裁切时按边缘钳制）。
    """
    x, y, ww, wh = (float(v) for v in src_rect_px)
    margin = max(
        SAMPLE_MARGIN_RATIO_MIN * max(ww, wh),
        SAMPLE_MARGIN_SIGMA * max(0.0, float(sigma_px)),
    )
    return (x - margin, y - margin, ww + 2.0 * margin, wh + 2.0 * margin)


def crop_resize(image_u8: np.ndarray, rect_px: Tuple[float, float, float, float],
                out_w: int, out_h: int) -> np.ndarray:
    """按浮点矩形裁切（越界按边缘钳制）并重采样到 ``(out_h, out_w)``。

    缩小时先做盒式预降采样再双线性，避免欠采样产生摩尔纹；放大时直接双线性。
    重采样在**伽马空间**进行（与 Qt / GPU 的纹理采样一致），随后才转线性光。

    Args:
        image_u8: shape (h, w, 3) 的 uint8 sRGB 源图。
        rect_px: ``(x, y, w, h)`` 浮点裁切矩形（允许越界）。
        out_w: 输出宽度（像素）。
        out_h: 输出高度（像素）。

    Returns:
        shape (out_h, out_w, 3) 的 uint8 数组。
    """
    h, w = image_u8.shape[0], image_u8.shape[1]
    out_w = max(1, int(out_w))
    out_h = max(1, int(out_h))
    x0, y0, rw, rh = rect_px

    # 目标像素中心映射回源图坐标（角点对齐，等价 GL_LINEAR）
    xs = (np.arange(out_w, dtype=np.float32) + 0.5) * float(rw) / out_w + float(x0) - 0.5
    ys = (np.arange(out_h, dtype=np.float32) + 0.5) * float(rh) / out_h + float(y0) - 0.5

    # 欠采样保护：缩放比 > 2 时先盒式预降采样
    pre = 1
    if rw > 2.0 * out_w or rh > 2.0 * out_h:
        pre = max(1, int(min(rw / max(out_w, 1), rh / max(out_h, 1)) / 2.0))
    src = image_u8
    if pre > 1:
        src = _box_downsample_u8(image_u8, pre)
        xs = xs / pre
        ys = ys / pre
        sh, sw = src.shape[0], src.shape[1]
    else:
        sh, sw = h, w

    xs = np.clip(xs, 0.0, sw - 1.0)
    ys = np.clip(ys, 0.0, sh - 1.0)
    ix0 = np.floor(xs).astype(np.int64)
    iy0 = np.floor(ys).astype(np.int64)
    ix1 = np.minimum(ix0 + 1, sw - 1)
    iy1 = np.minimum(iy0 + 1, sh - 1)
    tx = (xs - ix0).astype(np.float32)
    ty = (ys - iy0).astype(np.float32)

    row0 = (src[:, ix0].astype(np.float32) * (1 - tx)[None, :, None]
            + src[:, ix1].astype(np.float32) * tx[None, :, None])
    row1 = (src[:, ix0].astype(np.float32) * (1 - tx)[None, :, None]
            + src[:, ix1].astype(np.float32) * tx[None, :, None])
    del row1
    top = (src[iy0][:, ix0].astype(np.float32) * (1 - tx)[None, :, None]
           + src[iy0][:, ix1].astype(np.float32) * tx[None, :, None])
    bot = (src[iy1][:, ix0].astype(np.float32) * (1 - tx)[None, :, None]
           + src[iy1][:, ix1].astype(np.float32) * tx[None, :, None])
    del row0
    out = top * (1 - ty)[:, None, None] + bot * ty[:, None, None]
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


def _box_downsample_u8(image_u8: np.ndarray, factor: int) -> np.ndarray:
    """对 uint8 图像做 ``factor`` 倍盒式降采样（在伽马空间，仅用于预降采样）。

    Args:
        image_u8: shape (h, w, 3) 的 uint8 源图。
        factor: 降采样倍数（≥2 时才有意义）。

    Returns:
        shape (ceil(h/f), ceil(w/f), 3) 的 uint8 数组。
    """
    factor = max(1, int(factor))
    if factor == 1:
        return image_u8
    h, w = image_u8.shape[0], image_u8.shape[1]
    bh = max(1, int(np.ceil(h / factor)))
    bw = max(1, int(np.ceil(w / factor)))
    pad_h = bh * factor - h
    pad_w = bw * factor - w
    arr = image_u8.astype(np.float32)
    if pad_h > 0 or pad_w > 0:
        arr = np.pad(arr, ((0, max(0, pad_h)), (0, max(0, pad_w)), (0, 0)), mode="edge")
    return arr.reshape(bh, factor, bw, factor, 3).mean(axis=(1, 3)).astype(np.uint8)


# ---------------------------------------------------------------------------
# 去明度：逐像素 Oklab 通道处理
# ---------------------------------------------------------------------------

def chroma_from_srgb(image_u8: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """逐像素提取色度并丢弃明度 —— **去明度的通道级实现**。

    流程：sRGB(uint8) → 线性光 → Oklab → 丢弃 ``L`` 通道，返回 ``(a, b)``；
    同时返回用于可靠性门控的线性亮度 ``Y``（Rec.709，仅作权重，不参与合成）。

    Args:
        image_u8: shape (h, w, 3) 的 uint8 sRGB 图像。

    Returns:
        ``(ab, y)``：``ab`` 为 shape (h, w, 2) 的 Oklab 色度平面；
        ``y`` 为 shape (h, w) 的线性亮度。
    """
    lin = linear_from_srgb_u8(image_u8)
    lab = oklab_from_linear_rgb(lin)
    y = (0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]).astype(np.float32)
    return lab[..., 1:].astype(np.float32), y


def chroma_reliability(
    y: np.ndarray,
    lo: float = CHROMA_LUMA_GATE_LO,
    hi: float = CHROMA_LUMA_GATE_HI,
    feather: float = CHROMA_LUMA_GATE_FEATHER,
) -> np.ndarray:
    """由线性亮度生成色度可靠性权重（0..1，smoothstep 软过渡）。

    压暗的暗部与过曝的高光几乎不含可靠色度（只有传感器噪声），若不加权参与
    低通，会把整幅色调往灰里拉。这里用双侧 smoothstep 做**软**门控 —— 必须是
    软的，硬掩膜会在低通后留下块状伪影。

    Args:
        y: shape (h, w) 的线性亮度。
        lo: 下门限中心。
        hi: 上门限中心。
        feather: 过渡带宽度。

    Returns:
        shape (h, w) 的 float32 权重，取值 [0, 1]。
    """
    w_lo = np.clip((y - lo) / max(feather, _EPS), 0.0, 1.0)
    w_hi = np.clip((hi - y) / max(feather, _EPS), 0.0, 1.0)
    w = np.minimum(w_lo, w_hi)
    return (w * w * (3.0 - 2.0 * w)).astype(np.float32)


# ---------------------------------------------------------------------------
# 去轮廓：色度平面的归一化加权高斯低通
# ---------------------------------------------------------------------------

def _gaussian_kernel(sigma: float) -> np.ndarray:
    """生成归一化的一维高斯核（半径取 3σ）。

    Args:
        sigma: 标准差（像素）。

    Returns:
        shape (2r+1,) 的 float32 核，和为 1。
    """
    radius = max(1, int(np.ceil(3.0 * max(sigma, _EPS))))
    x = np.arange(-radius, radius + 1, dtype=np.float32)
    k = np.exp(-(x * x) / (2.0 * max(sigma, _EPS) ** 2))
    return (k / k.sum()).astype(np.float32)


def _blur_axis(p: np.ndarray, kernel: np.ndarray, axis: int) -> np.ndarray:
    """沿单个轴做边缘钳制的高斯卷积。

    Args:
        p: 2D 数组。
        kernel: 一维核。
        axis: 0 = 纵向，1 = 横向。

    Returns:
        同 shape 的模糊结果。
    """
    radius = kernel.shape[0] // 2
    if axis == 0:
        padded = np.pad(p, ((radius, radius), (0, 0)), mode="edge")
        out = np.zeros_like(p, dtype=np.float32)
        for i, k in enumerate(kernel):
            if k == 0.0:
                continue
            out += k * padded[i:i + p.shape[0]]
        return out
    padded = np.pad(p, ((0, 0), (radius, radius)), mode="edge")
    out = np.zeros_like(p, dtype=np.float32)
    for i, k in enumerate(kernel):
        if k == 0.0:
            continue
        out += k * padded[:, i:i + p.shape[1]]
    return out


def _upsample_2d(grid: np.ndarray, out_h: int, out_w: int) -> np.ndarray:
    """双线性放大 2D 数组。

    Args:
        grid: shape (gh, gw) 的 2D 数组。
        out_h: 输出高度。
        out_w: 输出宽度。

    Returns:
        shape (out_h, out_w) 的数组。
    """
    gh, gw = grid.shape[0], grid.shape[1]
    xs = np.clip((np.arange(out_w, dtype=np.float32) + 0.5) * gw / out_w - 0.5, 0.0, gw - 1.0)
    ys = np.clip((np.arange(out_h, dtype=np.float32) + 0.5) * gh / out_h - 0.5, 0.0, gh - 1.0)
    x0 = np.floor(xs).astype(np.int64)
    y0 = np.floor(ys).astype(np.int64)
    x1 = np.minimum(x0 + 1, gw - 1)
    y1 = np.minimum(y0 + 1, gh - 1)
    tx = (xs - x0).astype(np.float32)
    ty = (ys - y0).astype(np.float32)
    top = grid[y0][:, x0] * (1 - tx)[None, :] + grid[y0][:, x1] * tx[None, :]
    bot = grid[y1][:, x0] * (1 - tx)[None, :] + grid[y1][:, x1] * tx[None, :]
    return (top * (1 - ty)[:, None] + bot * ty[:, None]).astype(np.float32)


def blur_chroma(
    ab: np.ndarray,
    weight: np.ndarray,
    sigma: float,
    downscale: Optional[int] = None,
) -> np.ndarray:
    """**归一化加权高斯低通**：对色度平面去轮廓，同时抑制不可靠色度。

    数学形式（逐像素、逐通道）：

    ``ā = G_σ ⊗ (w · a)  /  G_σ ⊗ w``

    其中 ``G_σ`` 为高斯核，``w`` 为 :func:`chroma_reliability` 的可靠性权重。
    分母归一化保证了"只做加权平均、不改变色度总量"，等价于在每个像素的 σ
    邻域内求**以可靠性为权重的色度质心** —— 这同时消灭了轮廓细节（低通）与
    暗部/高光的噪色（加权）。

    由于只在 ``(a, b)`` 平面上做卷积，明度不参与，**绝不会产生明暗光晕**。

    性能：σ 较大时先用盒式降采样把图像缩小 ``downscale`` 倍，在小图上用
    σ/downscale 的核卷积，再双线性放大 —— 这是全分辨率高斯的标准加速近似。
    传 ``downscale=1`` 可得到严格的全分辨率卷积（慢，仅用于校验）。

    Args:
        ab: shape (h, w, 2) 的 Oklab 色度平面。
        weight: shape (h, w) 的可靠性权重。
        sigma: 高斯标准差（**本图分辨率像素**）。
        downscale: 预降采样倍数；None 时自动取 ``clamp(round(σ/2), 1, 16)``。

    Returns:
        shape (h, w, 2) 的低通后色度平面。
    """
    h, w = ab.shape[0], ab.shape[1]
    if sigma <= 0.0:
        return ab

    if downscale is None:
        downscale = int(max(1, min(16, round(sigma / 2.0))))
    downscale = max(1, min(int(downscale), max(1, min(h, w))))

    if downscale > 1:
        small_h = max(1, h // downscale)
        small_w = max(1, w // downscale)
        # 盒式预降采样（伽马无关，色度是线性量，直接平均即可）
        ab_s = _box_mean_3d(ab, small_h, small_w)
        w_s = _box_mean_2d(weight, small_h, small_w)
        small_sigma = max(sigma / downscale, 0.5)
    else:
        ab_s, w_s, small_sigma = ab, weight, max(sigma, 0.5)

    kernel = _gaussian_kernel(small_sigma)
    num_a = _blur_axis(_blur_axis(ab_s[..., 0] * w_s, kernel, 0), kernel, 1)
    num_b = _blur_axis(_blur_axis(ab_s[..., 1] * w_s, kernel, 0), kernel, 1)
    den = _blur_axis(_blur_axis(w_s, kernel, 0), kernel, 1)

    out = np.stack([num_a, num_b], axis=-1) / np.maximum(den, _EPS)[..., None]

    if downscale > 1:
        out = np.stack(
            [_upsample_2d(out[..., 0], h, w), _upsample_2d(out[..., 1], h, w)], axis=-1
        )
    return out.astype(np.float32)


def _bin_edges(n: int, bins: int) -> np.ndarray:
    """生成 ``bins`` 个整数分箱的边界（单调不减，末值 = n）。"""
    bins = max(1, min(int(bins), int(n)))
    return (np.arange(bins + 1) * n / bins).astype(np.int64)


def _box_mean_2d(p: np.ndarray, bins_h: int, bins_w: int) -> np.ndarray:
    """2D 盒式平均降采样。"""
    ey = _bin_edges(p.shape[0], bins_h)
    ex = _bin_edges(p.shape[1], bins_w)
    out = np.add.reduceat(p, ey[:-1], axis=0)
    out = out / np.maximum(np.diff(ey).reshape(-1, 1), 1)
    out = np.add.reduceat(out, ex[:-1], axis=1)
    return (out / np.maximum(np.diff(ex).reshape(1, -1), 1)).astype(np.float32)


def _box_mean_3d(a: np.ndarray, bins_h: int, bins_w: int) -> np.ndarray:
    """3D（末维为通道）盒式平均降采样。"""
    ey = _bin_edges(a.shape[0], bins_h)
    ex = _bin_edges(a.shape[1], bins_w)
    out = np.add.reduceat(a, ey[:-1], axis=0)
    out = out / np.maximum(np.diff(ey).reshape(-1, 1, 1), 1)
    out = np.add.reduceat(out, ex[:-1], axis=1)
    return (out / np.maximum(np.diff(ex).reshape(1, -1, 1), 1)).astype(np.float32)


# ---------------------------------------------------------------------------
# 色度整形（逐像素）
# ---------------------------------------------------------------------------

def shape_chroma(ab: np.ndarray, cap: float, gain: float = 1.0) -> np.ndarray:
    """色度整形：增益 + 双曲正切软限幅，**逐像素独立**（保留全部空间变化）。

    ``C_out = cap · tanh(C_in · gain / cap)``

    * 小彩度区近似线性（``tanh x ≈ x``），弱色壁纸也能透出微妙色调；
    * 大彩度区平滑饱和到 ``cap``，杜绝高饱和壁纸把 UI 染成荧光色；
    * ``C_in = 0`` ⇒ ``C_out = 0``，纯灰 / 黑白壁纸自然退化为纯 G1；
    * 单调且过原点，因此色相角严格不变，只改彩度。

    Args:
        ab: shape (..., 2) 的 Oklab 色度。
        cap: 色度软上限。
        gain: 色度增益（设置项「饱和度」映射到此值）。

    Returns:
        同 shape 的整形后色度。
    """
    c = np.sqrt(ab[..., 0] ** 2 + ab[..., 1] ** 2)
    c_out = cap * np.tanh((c * gain) / max(cap, _EPS))
    scale = c_out / np.maximum(c, _EPS)
    return (ab * scale[..., None]).astype(np.float32)


def rebuild_source_layer(ab: np.ndarray, l_ref: float) -> np.ndarray:
    """以**常数明度** ``l_ref`` 重建 sRGB 图像 —— 得到等亮度的上层源图像。

    由于所有像素共享同一个 Oklab ``L``，该图像的逐像素亮度恒定，壁纸的明暗
    结构在进入混合之前就已被彻底抹除；而 ``(a, b)`` 仍逐像素变化，所以它
    **仍然是一幅图像**，不是平涂色块。

    Args:
        ab: shape (h, w, 2) 的整形后色度平面（全分辨率）。
        l_ref: 参考明度，取 G1 的 Oklab ``L``。

    Returns:
        shape (h, w, 3) 的 sRGB 编码源图像，落在 [0, 1]。
    """
    lab = np.concatenate(
        [np.full(ab.shape[:-1] + (1,), float(l_ref), dtype=np.float32), ab], axis=-1
    )
    return srgb_from_oklab(lab).astype(np.float32)


def g1_oklab_l(g1_rgb: Tuple[int, int, int]) -> float:
    """计算 G1 基色的 Oklab 明度 ``L``（作为上层的等亮度参考值）。

    Args:
        g1_rgb: ``(r, g, b)``，各分量 0..255。

    Returns:
        Oklab ``L`` 分量（标量 float）。
    """
    arr = np.array([[[g1_rgb[0], g1_rgb[1], g1_rgb[2]]]], dtype=np.uint8)
    return float(oklab_from_linear_rgb(linear_from_srgb_u8(arr))[..., 0].reshape(-1)[0])


# ---------------------------------------------------------------------------
# 最终合成
# ---------------------------------------------------------------------------

def dither_tpdf(shape: Tuple[int, ...], seed: int = DITHER_SEED) -> np.ndarray:
    """生成确定性 TPDF 抖动噪声（三角分布，幅度 ±0.5 LSB）。

    合成结果是近乎平坦的大面积渐变，8-bit 量化极易产生色带；抖动是必需的。
    固定种子保证跨重绘稳定，不会闪烁。

    Args:
        shape: 噪声形状，通常为 ``(h, w, 1)``。
        seed: 随机种子。

    Returns:
        float32 噪声数组，取值范围 (-0.5, 0.5)。
    """
    rng = np.random.default_rng(seed)
    return (rng.random(shape, dtype=np.float32) - rng.random(shape, dtype=np.float32)) * 0.5


def compose_tint(
    source: np.ndarray,
    g1_rgb: Tuple[int, int, int],
    alpha: float = 0.85,
    dither: bool = True,
    seed: int = DITHER_SEED,
) -> np.ndarray:
    """把等亮度源图像以 Photoshop「颜色」模式合成到 G1 基色图层之上。

    逐像素流程（全在浮点域完成）：

    1. ``tinted = Color(B=G1, S=source)`` → 亮度恒为 ``Lum(G1)``，色相/彩度取自
       source 的对应像素；
    2. ``out = G1 + (tinted − G1) · alpha`` → 色调强度线性可控；
    3. TPDF 抖动 + 四舍五入 → 8-bit。

    Args:
        source: shape (h, w, 3) 的上层源图像（sRGB 编码值 0..1）。
        g1_rgb: G1 基色 ``(r, g, b)``，各分量 0..255。
        alpha: 色调强度，0 = 纯 G1（无色调），1 = 完整「颜色」混合结果。
        dither: 是否施加 TPDF 抖动。
        seed: 抖动种子。

    Returns:
        shape (h, w, 3) 的 uint8 合成结果（完全不透明）。
    """
    backdrop = (np.array(g1_rgb, dtype=np.float32) / 255.0).reshape(1, 1, 3)
    backdrop = np.broadcast_to(backdrop, source.shape).astype(np.float32)

    tinted = color_blend(backdrop, source)
    out = backdrop + (tinted - backdrop) * float(alpha)

    if dither:
        out = out + dither_tpdf((source.shape[0], source.shape[1], 1), seed) / 255.0

    return np.clip(np.rint(out * 255.0), 0.0, 255.0).astype(np.uint8)


# ---------------------------------------------------------------------------
# 顶层编排
# ---------------------------------------------------------------------------

@dataclass
class TintConfig:
    """色调层合成参数。

    Attributes:
        dark: True = 深色模式（G1 = ``#1a1a1a``），False = 浅色模式（``#f5f5f5``）。
        gain: 色度增益，映射设置项「饱和度」，1.0 = 标准。
        alpha: 色调强度，映射设置项「叠加透明度」，0..1。
        sigma: 去轮廓高斯标准差（**烘焙分辨率像素**），映射设置项「模糊半径」。
        cap: 色度软上限；None 时按深浅模式取推荐值。
        bake_scale: 烘焙分辨率比例，拖拽期可降到 0.25。
        downscale: 模糊加速的预降采样倍数；None = 自动。
        dither: 是否施加 TPDF 抖动。
    """

    dark: bool = True
    gain: float = 1.0
    alpha: float = 0.85
    sigma: float = BLUR_SIGMA_DEFAULT
    cap: Optional[float] = None
    bake_scale: float = 1.0
    downscale: Optional[int] = None
    dither: bool = True

    def g1(self) -> Tuple[int, int, int]:
        """返回当前模式下的 G1 基色。"""
        return G1_DARK if self.dark else G1_LIGHT

    def chroma_cap(self) -> float:
        """返回当前模式下的色度软上限。"""
        if self.cap is not None:
            return float(self.cap)
        return CHROMA_CAP_DARK if self.dark else CHROMA_CAP_LIGHT


@dataclass
class TintResult:
    """色调层合成结果（含中间产物，便于调试与自动化校验）。

    Attributes:
        image: shape (h, w, 3) 的 uint8 最终合成图。
        source_layer: shape (h, w, 3) 的 uint8 等亮度上层源图像，
            用于校验"无任何明暗结构残留"。
        chroma: shape (h, w, 2) 的低通整形后色度平面。
    """

    image: np.ndarray
    source_layer: np.ndarray
    chroma: np.ndarray


def build_source_from_crop(
    crop_u8: np.ndarray,
    cfg: TintConfig,
    l_ref: float,
    sigma: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """由裁切后的壁纸块构建等亮度上层源图像。

    阶段顺序（对应设计文档 Stage 2–6）：
    去明度 → 可靠性权重 → 归一化加权低通（去轮廓）→ 逐像素整形 → 等亮度重建。

    Args:
        crop_u8: shape (h, w, 3) 的 uint8 裁切壁纸块（烘焙分辨率）。
        cfg: 合成参数。
        l_ref: 上层等亮度参考值（G1 的 Oklab L）。
        sigma: 去轮廓高斯标准差（本图分辨率像素）。

    Returns:
        ``(source, chroma)``：``source`` 为 (h, w, 3) 的 sRGB 0..1 源图像，
        ``chroma`` 为 (h, w, 2) 的整形后色度平面。
    """
    ab, y = chroma_from_srgb(crop_u8)
    weight = chroma_reliability(y)
    ab = blur_chroma(ab, weight, sigma, cfg.downscale)
    ab = shape_chroma(ab, cfg.chroma_cap(), cfg.gain)
    return rebuild_source_layer(ab, l_ref), ab


def bake_tint(
    image_u8: np.ndarray,
    src_rect_px: Tuple[float, float, float, float],
    out_w: int,
    out_h: int,
    cfg: Optional[TintConfig] = None,
) -> TintResult:
    """完整编排：采样区域 → 去明度 → 去轮廓 → 整形 → 等亮度重建 → 与 G1 混合。

    Args:
        image_u8: shape (h, w, 3) 的 uint8 sRGB 壁纸（可为 RGBA 的前 3 通道）。
        src_rect_px: 窗口在壁纸像素坐标系中的矩形 ``(x, y, w, h)``，
            来自 ``MicaMaterial._placement_source_rect`` 的放置数学。
        out_w: 输出宽度（像素，= 窗口宽）。
        out_h: 输出高度（像素，= 窗口高）。
        cfg: 合成参数；None 时使用默认（深色模式）。

    Returns:
        :class:`TintResult`，含最终图像与中间产物。
    """
    cfg = cfg or TintConfig()
    out_w = max(1, int(out_w))
    out_h = max(1, int(out_h))

    scale = max(0.1, min(1.0, float(cfg.bake_scale)))
    bw = max(8, int(round(out_w * scale)))
    bh = max(8, int(round(out_h * scale)))

    # Stage 1：采样区域外扩（σ 需换算到壁纸像素单位）
    wall_scale = max(image_u8.shape[0], image_u8.shape[1]) / max(1.0, float(max(out_w, out_h)))
    sigma_bake = max(BLUR_SIGMA_MIN, min(BLUR_SIGMA_MAX, float(cfg.sigma))) * scale
    sigma_wall = sigma_bake * wall_scale
    rect = sample_rect_px(src_rect_px, sigma_wall, image_u8.shape[1], image_u8.shape[0])

    # Stage 2：裁切 + 重采样到烘焙分辨率
    crop = crop_resize(image_u8, rect, bw, bh)

    # Stage 3–6：去明度 → 去轮廓 → 整形 → 等亮度重建
    l_ref = g1_oklab_l(cfg.g1())
    source, chroma = build_source_from_crop(crop, cfg, l_ref, sigma_bake)

    # Stage 7–8：Photoshop「颜色」混合 + 强度控制 + 抖动量化
    image = compose_tint(source, cfg.g1(), cfg.alpha, cfg.dither)

    if (bw, bh) != (out_w, out_h):
        image = _resample_u8(image, out_w, out_h)
        source_u8 = _resample_u8(
            np.clip(np.rint(source * 255.0), 0, 255).astype(np.uint8), out_w, out_h
        )
    else:
        source_u8 = np.clip(np.rint(source * 255.0), 0, 255).astype(np.uint8)

    return TintResult(image=image, source_layer=source_u8, chroma=chroma)


def _resample_u8(image_u8: np.ndarray, out_w: int, out_h: int) -> np.ndarray:
    """把 uint8 图像双线性重采样到 ``(out_h, out_w)``。

    Args:
        image_u8: shape (h, w, c) 的 uint8 源图。
        out_w: 输出宽度。
        out_h: 输出高度。

    Returns:
        shape (out_h, out_w, c) 的 uint8 数组。
    """
    return crop_resize(
        image_u8, (0.0, 0.0, float(image_u8.shape[1]), float(image_u8.shape[0])), out_w, out_h
    )


# ---------------------------------------------------------------------------
# Qt 边界适配（惰性导入 PySide6，保持数学内核在无 Qt 环境下可测）
# ---------------------------------------------------------------------------

def qimage_from_ndarray(arr: np.ndarray) -> "object":  # QImage
    """``(h, w, 3) uint8`` ndarray → QImage（RGBA8888，opaque）。

    QPixmap 接受 8-bit per channel，因此无论源数据精度多高，最终都会被
    立即降采样 —— 故此处固定输出 8-bit 通道，颜色精度由浮点域内插值 +
    TPDF 抖动保证（见 :func:`compose_tint`）。

    Args:
        arr: shape (h, w, 3) 的 uint8 数组。

    Returns:
        QImage（RGBA8888，不透明，深拷贝可独立于 ndarray 生命周期）。
    """
    from PySide6.QtGui import QImage

    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr], axis=-1)
    if arr.ndim != 3 or arr.shape[2] not in (3, 4):
        raise ValueError(f"不支持的数组形状: {arr.shape}")
    arr = np.ascontiguousarray(arr.astype(np.uint8))
    if arr.shape[2] == 3:
        rgba = np.concatenate([arr, np.full(arr.shape[:2] + (1,), 255, dtype=np.uint8)], axis=-1)
    else:
        rgba = arr
    h, w = rgba.shape[0], rgba.shape[1]
    qimg = QImage(rgba.data, w, h, w * 4, QImage.Format_RGBA8888)
    return qimg.copy()  # 拷贝使 ndarray 可立即释放


def qpixmap_from_ndarray(arr: np.ndarray) -> "object":  # QPixmap
    """``(h, w, 3) uint8`` ndarray → QPixmap（深拷贝，可独立持有）。

    Args:
        arr: shape (h, w, 3) 的 uint8 数组。

    Returns:
        QPixmap。
    """
    from PySide6.QtGui import QPixmap

    return QPixmap.fromImage(qimage_from_ndarray(arr))


def qimage_to_ndarray_rgb(img) -> np.ndarray:  # QImage -> ndarray
    """QImage（任意格式） → ``(h, w, 3) uint8`` ndarray（深拷贝）。

    内部统一转为 RGBA8888 后取前三通道；alpha 通道被丢弃（色调层不透明度
    恒为 255）。

    Args:
        img: QImage 实例。

    Returns:
        shape (h, w, 3) 的 uint8 数组。
    """
    from PySide6.QtGui import QImage

    img = img.convertToFormat(QImage.Format_RGBA8888)
    w, h = img.width(), img.height()
    bpl = img.bytesPerLine()
    ptr = img.constBits()
    if isinstance(ptr, memoryview):
        buf = bytes(ptr)
    else:
        try:
            addr = ptr.__int__()
        except (ValueError, TypeError, AttributeError):
            addr = int(ctypes.cast(ptr, ctypes.c_void_p).value or 0)
        buf = ctypes.string_at(addr, bpl * h)
    arr = np.frombuffer(buf, dtype=np.uint8)[: bpl * h].reshape(h, bpl)
    return arr[:, : w * 4].reshape(h, w, 4)[..., :3].copy()


def bake_tint_qimage(
    image_u8: np.ndarray,
    src_rect_px: Tuple[float, float, float, float],
    out_w: int,
    out_h: int,
    cfg: Optional[TintConfig] = None,
) -> "object":  # QImage
    """完整调度的 Qt 友好入口 —— 直接返回 QImage，可立刻 ``QPixmap.fromImage``。

    其余语义同 :func:`bake_tint`。仅在调用时导入 PySide6，使数学内核本身
    保持 Qt-free（便于无显示环境下的单元测试）。

    Args:
        image_u8: shape (h, w, 3) 的 uint8 sRGB 壁纸。
        src_rect_px: 窗口在壁纸像素坐标系中的矩形 ``(x, y, w, h)``。
        out_w: 输出宽度（像素）。
        out_h: 输出高度（像素）。
        cfg: 合成参数；None 时使用默认（深色模式）。

    Returns:
        QImage（RGBA8888，opaque，深拷贝）。
    """
    res = bake_tint(image_u8, src_rect_px, out_w, out_h, cfg)
    return qimage_from_ndarray(res.image)
