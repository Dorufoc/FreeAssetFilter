"""Mica 色彩科学内核 —— 从壁纸色度到等亮度色调层的全部数学。

本模块是 Win11 Mica 视觉模型的核心，**只依赖 numpy**，可在无 GUI 环境下
完整单元测试。

Mica 的视觉定义
---------------
Win11 Mica 不是"模糊的壁纸"，而是**壁纸的低频色度**叠加到主题基色之上：

* 壁纸的**明度结构**（明暗、轮廓）被彻底丢弃 —— 输出逐像素亮度恒等于
  主题基色 G1 的亮度；
* 壁纸的**色度**（色相 + 彩度）经大尺度归一化加权低通后被保留 —— 于是
  窗口看起来是一块近乎纯色的表面，却微妙地偏向壁纸的色调；
* 最后叠一层极细的噪声（Win11 亦有），掩盖 8-bit 大面积渐变的色带。

五步流水线
----------
1. **去明度**（:func:`chroma_from_srgb`）：sRGB → 线性光 → Oklab，丢弃
   ``L`` 通道，保留 ``(a, b)`` 色度平面。
2. **可靠性门控**（:func:`chroma_reliability`）：压暗的暗部与过曝的高光几乎
   不含可靠色度，用双侧 smoothstep 软门控压到 0（软过渡，否则低通后留块）。
3. **去轮廓**（:func:`blur_chroma`）：对 ``(a, b)`` 做**归一化加权高斯低通**
   ``ā = G_σ⊗(w·a) / G_σ⊗w``。只在色度平面卷积，故绝不产生明暗光晕。
4. **整形**（:func:`shape_chroma`）：增益 + 双曲正切软限幅，逐像素独立，
   保留全部空间变化，但杜绝高饱和壁纸把 UI 染成荧光色。
5. **重建与混合**（:func:`rebuild_source_layer` / :func:`compose_tint`）：
   以常数明度 ``L(G1)`` 重建等亮度源图，再用 Photoshop「颜色」混合模式
   （``Color(B, S) = SetLum(S, Lum(B))``）合成到 G1 之上。

亮度锁死的数学保证
------------------
``SetLum`` 中的 ``ClipColor`` 严格保持 ``luma_ps`` 不变，故输出逐像素亮度
恒等于 ``Lum(G1)``。**亮度为常数 ⇒ 壁纸的明暗与轮廓在数学上不可能残留**。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: 明度门控：线性亮度低于 ``lo`` 或高于 ``hi`` 的像素色度不可靠，权重按
#: smoothstep 衰减到 0。
CHROMA_LUMA_GATE_LO: float = 0.010
CHROMA_LUMA_GATE_HI: float = 0.990
#: 门控过渡带宽度（线性亮度单位）。硬掩膜会在低通后留下块状伪影，必须软过渡。
CHROMA_LUMA_GATE_FEATHER: float = 0.010

#: 色域映射二分迭代次数（12 次 ≈ 1/4096 精度）。
GAMUT_MAP_ITERS: int = 12
#: 抖动随机种子（固定 ⇒ 烘焙结果跨重绘稳定，不闪烁）。
DITHER_SEED: int = 42

#: 归一化加权低通的加速降采样上限。取 4 是质量/速度折中：降采样后双线性
#: 放大回网格分辨率，4 倍插值引入的误差约为 0.3 %，肉眼不可见。
MAX_BLUR_DOWNSCALE: int = 4
#: 降采样后的小图至少保留的边长（像素），保证高斯核半径不淹没整张小图。
MIN_DOWNSAMPLED_SIDE: int = 16

#: 工作分辨率的目标 σ（像素）。整条管线在 σ ≈ 4 px 的网格上运行，既让高斯
#: 核半径保持在 12 px 量级（卷积开销可控），又不至于让色度细节欠采样。
WORK_TARGET_SIGMA: float = 4.0
#: 工作分辨率降采样倍数上限。
MAX_WORK_DOWNSCALE: int = 8
#: 工作分辨率的最小长边（像素）。低于此值时可靠性门控会因为过度平均而失真
#: （压黑区与高光区被混进同一个像素），故以此为下限反推降采样倍数。
MIN_WORK_LONG_SIDE: int = 64

_EPS: float = 1e-6

# ---------------------------------------------------------------------------
# 基础色彩变换
# ---------------------------------------------------------------------------


def srgb_to_linear_lut() -> np.ndarray:
    """返回 256 项 sRGB(0..255) → 线性光(0..1) 查表。

    Returns:
        shape ``(256,)`` 的 float32 数组，索引即 8-bit sRGB 编码值。
    """
    v = np.arange(256, dtype=np.float64) / 255.0
    lin = np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)
    return lin.astype(np.float32)


#: 模块级缓存：查表在进程生命周期内恒定。
_LUT_LINEAR: np.ndarray = srgb_to_linear_lut()


def linear_from_srgb_u8(arr: np.ndarray) -> np.ndarray:
    """8-bit sRGB uint8 → 线性光 float32（查表，无幂运算）。

    Args:
        arr: shape ``(..., 3)`` 的 uint8 数组。

    Returns:
        同 shape 的 float32 线性光数组，取值 ``[0, 1]``。
    """
    return _LUT_LINEAR[np.asarray(arr, dtype=np.uint8)]


def srgb_from_linear(lin: np.ndarray) -> np.ndarray:
    """线性光 float → sRGB 编码值 float（0..1，允许越界，由调用方裁剪）。

    Args:
        lin: shape ``(..., 3)`` 的线性光数组。

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
    """线性 sRGB → Oklab ``(L, a, b)``，逐像素独立。

    Args:
        lin: shape ``(..., 3)`` 线性光数组。

    Returns:
        同 shape 的 Oklab 数组，``L`` ∈ ``[0,1]``，``a``/``b`` 通常 ∈ ``[-0.4, 0.4]``。
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

    实现上先尝试 ``scale=1``（绝大多数色域内输入直接命中），仅对越界子集
    做二分（取出越界子集 → 迭代 → 散射回原位），保证 in-gamut 像素的
    浮点级精度不受二分残留误差影响。

    Args:
        lab: shape ``(..., 3)`` 的 Oklab 数组。
        iters: 二分迭代次数。

    Returns:
        同 shape 的线性 sRGB 数组，逐像素落在 ``[0, 1]``。
    """
    rgb = _linear_rgb_from_lab_raw(lab)
    bad = np.any((rgb < -_EPS) | (rgb > 1.0 + _EPS), axis=-1)
    if not bool(bad.any()):
        return np.clip(rgb, 0.0, 1.0)

    flat_l = lab[..., 0:1].reshape(-1, 1)
    flat_a = lab[..., 1:2].reshape(-1, 1)
    flat_b = lab[..., 2:3].reshape(-1, 1)
    idx = np.flatnonzero(bad.reshape(-1))

    sl, sa, sb = flat_l[idx], flat_a[idx], flat_b[idx]
    lo = np.zeros_like(sa)
    hi = np.ones_like(sa)
    for _ in range(max(1, int(iters))):
        mid = 0.5 * (lo + hi)
        trial = _linear_rgb_from_lab_raw(
            np.concatenate([sl, sa * mid, sb * mid], axis=-1)
        )
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
        lab: shape ``(..., 3)`` 的 Oklab 数组。
        iters: 色域映射二分迭代次数。

    Returns:
        同 shape 的 sRGB 编码数组，落在 ``[0, 1]``。
    """
    return srgb_from_linear(linear_rgb_from_oklab(lab, iters))


# ---------------------------------------------------------------------------
# Photoshop「颜色」混合模式（PDF 规范）
# ---------------------------------------------------------------------------


def luma_ps(c: np.ndarray) -> np.ndarray:
    """Photoshop / PDF 规范亮度：0.3 / 0.59 / 0.11 加权。

    重要：该亮度定义在**伽马编码后的 sRGB 分量**上取值（Rec.601 luma on
    gamma values），正是 Photoshop 内部 Hue / Saturation / Color / Luminosity
    四模式所用定义；与 Rec.709 线性亮度不是一回事，**不可替换**。

    Args:
        c: shape ``(..., 3)`` 的 sRGB 编码数组（0..1）。

    Returns:
        shape ``(...)`` 的亮度数组。
    """
    return 0.3 * c[..., 0] + 0.59 * c[..., 1] + 0.11 * c[..., 2]


def clip_color(c: np.ndarray) -> np.ndarray:
    """把越界颜色拉回 ``[0,1]`` 且**严格保持亮度与色相**（PDF 规范 ClipColor）。

    先抬升负值下界，再压低超界上界；两步都沿"保亮度、保色相"方向缩放，
    且 ``luma_ps`` 在变换前后严格相等（可用单测验证）。

    Args:
        c: shape ``(..., 3)`` 数组，允许越界。

    Returns:
        同 shape 数组，逐通道落在 ``[0, 1]``，且 ``luma_ps`` 与输入一致。
    """
    l = luma_ps(c)[..., None]
    n = c.min(axis=-1, keepdims=True)
    # 存在负通道 → 以亮度为锚点按比例抬升，使最小值恰好抬到 0。
    # 两处 `any()` 短路是热路径优化：Mica 的输入绝大多数已在色域内，
    # 而 np.where 会无条件求值两个分支（含一次除法），代价不可忽略。
    if bool((n < 0.0).any()):
        c = np.where(n < 0.0, l + (c - l) * (l / np.maximum(l - n, _EPS)), c)
    # 存在 >1 通道 → 以亮度为锚点按比例压缩，使最大值恰好压到 1。
    x = c.max(axis=-1, keepdims=True)
    if bool((x > 1.0).any()):
        c = np.where(x > 1.0, l + (c - l) * ((1.0 - l) / np.maximum(x - l, _EPS)), c)
    return c


def set_lum(c: np.ndarray, l: np.ndarray) -> np.ndarray:
    """把颜色 ``c`` 的亮度改为 ``l``，保持色相与彩度（PDF 规范 SetLum）。

    Args:
        c: shape ``(..., 3)`` 的源颜色。
        l: shape ``(...)`` 或与 ``c`` 可广播的目标亮度。

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
        backdrop: shape ``(..., 3)`` 下层（Mica 中为 G1 基色，整幅同值）。
        source: shape ``(..., 3)`` 上层（Mica 中为等亮度色度图，逐像素变化）。

    Returns:
        同 shape 的混合结果，落在 ``[0, 1]``。

    Examples:
        >>> import numpy as np
        >>> g1 = np.array([0xF5, 0xF5, 0xF5], dtype=np.float32) / 255.0
        >>> blue = np.array([0.0, 0.0, 1.0], dtype=np.float32)
        >>> np.rint(color_blend(g1, blue) * 255).astype(int)
        array([244, 244, 255])
    """
    return set_lum(source, luma_ps(backdrop))


# ---------------------------------------------------------------------------
# 去明度 / 可靠性门控
# ---------------------------------------------------------------------------


def chroma_from_srgb(image_u8: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """逐像素提取色度并丢弃明度 —— **去明度的通道级实现**。

    sRGB(uint8) → 线性光 → Oklab → 丢弃 ``L`` 通道，返回 ``(a, b)``；同时
    返回用于可靠性门控的线性亮度 ``Y``（Rec.709，仅作权重，不参与合成）。

    Args:
        image_u8: shape ``(h, w, 3)`` 的 uint8 sRGB 图像。

    Returns:
        ``(ab, y)``：``ab`` 为 shape ``(h, w, 2)`` 的 Oklab 色度平面；
        ``y`` 为 shape ``(h, w)`` 的线性亮度。
    """
    lin = linear_from_srgb_u8(image_u8)
    lab = oklab_from_linear_rgb(lin)
    y = (
        0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]
    ).astype(np.float32)
    return lab[..., 1:].astype(np.float32), y


def chroma_reliability(
    y: np.ndarray,
    lo: float = CHROMA_LUMA_GATE_LO,
    hi: float = CHROMA_LUMA_GATE_HI,
    feather: float = CHROMA_LUMA_GATE_FEATHER,
) -> np.ndarray:
    """由线性亮度生成色度可靠性权重（0..1，smoothstep 软过渡）。

    压暗的暗部与过曝的高光几乎不含可靠色度（只有传感器噪声），若不加权
    参与低通，会把整幅色调往灰里拉。

    Args:
        y: shape ``(h, w)`` 的线性亮度。
        lo: 下门限中心。
        hi: 上门限中心。
        feather: 过渡带宽度。

    Returns:
        shape ``(h, w)`` 的 float32 权重，取值 ``[0, 1]``。
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
        shape ``(2r+1,)`` 的 float32 核，和为 1。
    """
    radius = max(1, int(np.ceil(3.0 * max(sigma, _EPS))))
    x = np.arange(-radius, radius + 1, dtype=np.float32)
    k = np.exp(-(x * x) / (2.0 * max(sigma, _EPS) ** 2))
    return (k / k.sum()).astype(np.float32)


def _blur_axis(p: np.ndarray, kernel: np.ndarray, axis: int) -> np.ndarray:
    """沿单个空间轴做边缘钳制的高斯卷积，支持前置批维。

    用滑动窗口视图 + 一次矩阵乘替代"逐核元素累加"的 Python 循环：核半径
    12 时前者是 1 次 BLAS 调用，后者是 25 次全数组遍历。批维的作用是把
    ``(w·a, w·b, w)`` 三个平面一次卷完，Python 层开销再降 2/3。

    Args:
        p: shape ``(h, w)`` 或 ``(n, h, w)`` 的数组（末两维为空间维）。
        kernel: 一维核。
        axis: 0 = 纵向（h），1 = 横向（w）。

    Returns:
        同 shape 的模糊结果（float32）。
    """
    arr = np.ascontiguousarray(p, dtype=np.float32)
    size = int(kernel.shape[0])
    radius = size // 2
    ax = arr.ndim - 2 + int(axis)
    pad = [(0, 0)] * arr.ndim
    pad[ax] = (radius, radius)
    padded = np.pad(arr, pad, mode="edge")
    win = np.lib.stride_tricks.sliding_window_view(padded, size, axis=ax)
    return np.asarray(win @ kernel, dtype=np.float32)


def _bin_edges(n: int, bins: int) -> np.ndarray:
    """生成 ``bins`` 个整数分箱的边界（单调不减，末值 = ``n``）。"""
    bins = max(1, min(int(bins), int(n)))
    return (np.arange(bins + 1) * n / bins).astype(np.int64)


def _box_mean_nd(a: np.ndarray, bins_h: int, bins_w: int) -> np.ndarray:
    """在前两维上做盒式平均降采样（后续维度原样保留）。

    整数倍时走 ``reshape + mean`` 快路径（一次连续 strided reduce）；非整数倍
    退回 ``np.add.reduceat``。前者在烘焙尺寸下比后者快约一个数量级 ——
    ``reduceat`` 的分箱开销在小数组上占绝对主导。

    Args:
        a: shape ``(h, w, ...)`` 的数组。
        bins_h: 目标高度。
        bins_w: 目标宽度。

    Returns:
        shape ``(bins_h, bins_w, ...)`` 的 float32 数组。
    """
    arr = np.ascontiguousarray(a, dtype=np.float32)
    h, w = int(arr.shape[0]), int(arr.shape[1])
    bh = max(1, min(int(bins_h), h))
    bw = max(1, min(int(bins_w), w))
    tail = arr.shape[2:]

    if h % bh == 0 and w % bw == 0:
        fy, fx = h // bh, w // bw
        return arr.reshape((bh, fy, bw, fx) + tail).mean(axis=(1, 3), dtype=np.float32)

    ey = _bin_edges(h, bh)
    ex = _bin_edges(w, bw)
    shape_y = (-1, 1) + (1,) * len(tail)
    shape_x = (1, -1) + (1,) * len(tail)
    out = np.add.reduceat(arr, ey[:-1], axis=0)
    out = out / np.maximum(np.diff(ey).reshape(shape_y), 1)
    out = np.add.reduceat(out, ex[:-1], axis=1)
    return np.asarray(out / np.maximum(np.diff(ex).reshape(shape_x), 1), dtype=np.float32)


def _box_mean_2d(p: np.ndarray, bins_h: int, bins_w: int) -> np.ndarray:
    """2D 盒式平均降采样。"""
    return _box_mean_nd(p, bins_h, bins_w)


def _box_mean_3d(a: np.ndarray, bins_h: int, bins_w: int) -> np.ndarray:
    """3D（末维为通道）盒式平均降采样。"""
    return _box_mean_nd(a, bins_h, bins_w)


def _auto_downscale(sigma: float, h: int, w: int) -> int:
    """为给定 σ 与图幅选择加速降采样倍数。

    取 ``round(σ/4)``（使降采样后的 σ 约为 4 px，核半径 12 —— 速度与质量的
    平衡点），再受 :data:`MAX_BLUR_DOWNSCALE` 与"降采样后边长不小于
    :data:`MIN_DOWNSAMPLED_SIDE`"双重约束。

    Args:
        sigma: 全分辨率下的高斯标准差（像素）。
        h: 图高。
        w: 图宽。

    Returns:
        降采样倍数，≥ 1。
    """
    auto = max(1, int(round(sigma / WORK_TARGET_SIGMA)))
    auto = min(auto, MAX_BLUR_DOWNSCALE)
    side_cap = max(1, min(int(h), int(w)) // MIN_DOWNSAMPLED_SIDE)
    return max(1, min(auto, max(1, side_cap)))


def work_divisor(sigma: float, crop_w: int, crop_h: int) -> int:
    """选择**整条管线**的工作分辨率降采样倍数。

    色调场经色度低通后带宽被限制在 ``~1/σ`` 周期/像素，因此低通之后的全部
    步骤（整形、等亮度重建、颜色混合）都是**逐点函数**，在 ``σ/4`` 的粗网格
    上算完再双线性放大，与全分辨率结果的差异远低于 8-bit 量化步长。这一步
    把默认参数下的像素工作量降低约 16 倍，是烘焙能进入毫秒级的主因。

    下限 :data:`MIN_WORK_LONG_SIDE` 保证可靠性门控仍作用在足够细的像素上：
    降采样过猛会把压黑区与高光区平均进同一个像素，门控随之失效。

    Args:
        sigma: 色度低通标准差（**烘焙网格像素**）。
        crop_w: 含扩边的烘焙网格宽度。
        crop_h: 含扩边的烘焙网格高度。

    Returns:
        降采样倍数，≥ 1。

    Examples:
        >>> work_divisor(27.33, 302, 238)
        4
        >>> work_divisor(2.0, 302, 238)
        1
    """
    if sigma <= WORK_TARGET_SIGMA:
        return 1
    want = min(MAX_WORK_DOWNSCALE, max(1, int(round(sigma / WORK_TARGET_SIGMA))))
    long_side = max(1, int(crop_w), int(crop_h))
    side_cap = max(1, long_side // MIN_WORK_LONG_SIDE)
    return max(1, min(want, side_cap))


def blur_chroma(
    ab: np.ndarray,
    weight: np.ndarray,
    sigma: float,
    downscale: Optional[int] = None,
) -> np.ndarray:
    """**归一化加权高斯低通**：对色度平面去轮廓，同时抑制不可靠色度。

    数学形式（逐像素、逐通道）::

        ā = G_σ ⊗ (w · a)  /  G_σ ⊗ w

    分母归一化保证"只做加权平均、不改变色度总量"，等价于在每个像素的 σ
    邻域内求**以可靠性为权重的色度质心** —— 同时消灭轮廓细节（低通）与
    暗部/高光的噪色（加权）。只在 ``(a, b)`` 平面上卷积，明度不参与，
    因此**绝不会产生明暗光晕**。

    Args:
        ab: shape ``(h, w, 2)`` 的 Oklab 色度平面。
        weight: shape ``(h, w)`` 的可靠性权重。
        sigma: 高斯标准差（**本图分辨率像素**）。
        downscale: 预降采样倍数；``None`` 时自动选择（见 :func:`_auto_downscale`）。

    Returns:
        shape ``(h, w, 2)`` 的低通后色度平面（float32）。
    """
    h, w = ab.shape[0], ab.shape[1]
    if sigma <= 0.0:
        return ab.astype(np.float32)

    if downscale is None:
        downscale = _auto_downscale(sigma, h, w)
    downscale = max(1, min(int(downscale), max(1, min(h, w))))

    if downscale > 1:
        small_h = max(1, h // downscale)
        small_w = max(1, w // downscale)
        # 色度是线性量，盒式平均直接成立（与伽马空间的图像降采样不同）
        ab_s = _box_mean_3d(ab, small_h, small_w)
        w_s = _box_mean_2d(weight, small_h, small_w)
        small_sigma = max(sigma / downscale, 0.5)
    else:
        ab_s, w_s, small_sigma = ab, weight, max(sigma, 0.5)

    kernel = _gaussian_kernel(small_sigma)
    # 三个平面 (w·a, w·b, w) 一次卷完：分子分母共享同一个核，批量化后
    # Python 层与 pad/视图构造的开销降到 1/3。
    planes = np.stack([ab_s[..., 0] * w_s, ab_s[..., 1] * w_s, w_s], axis=0)
    planes = _blur_axis(_blur_axis(planes, kernel, 0), kernel, 1)
    den = np.maximum(planes[2], _EPS)
    out = np.stack([planes[0] / den, planes[1] / den], axis=-1)

    if downscale > 1:
        from .resample import upsample_2d  # 局部导入：保持本模块对 resample 的弱依赖

        out = np.stack(
            [upsample_2d(out[..., 0], h, w), upsample_2d(out[..., 1], h, w)],
            axis=-1,
        )
    return np.asarray(out, dtype=np.float32)


# ---------------------------------------------------------------------------
# 色度整形与等亮度重建
# ---------------------------------------------------------------------------


def shape_chroma(ab: np.ndarray, cap: float, gain: float = 1.0) -> np.ndarray:
    """色度整形：增益 + 双曲正切软限幅，**逐像素独立**（保留全部空间变化）。

    ``C_out = cap · tanh(C_in · gain / cap)``

    * 小彩度区近似线性（``tanh x ≈ x``），弱色壁纸也能透出微妙色调；
    * 大彩度区平滑饱和到 ``cap``，杜绝高饱和壁纸把 UI 染成荧光色；
    * ``C_in = 0`` ⇒ ``C_out = 0``，纯灰 / 黑白壁纸自然退化为纯 G1；
    * 单调且过原点，因此色相角严格不变，只改彩度。

    Args:
        ab: shape ``(..., 2)`` 的 Oklab 色度。
        cap: 色度软上限。
        gain: 色度增益。

    Returns:
        同 shape 的整形后色度。
    """
    c = np.sqrt(ab[..., 0] ** 2 + ab[..., 1] ** 2)
    c_out = cap * np.tanh((c * gain) / max(cap, _EPS))
    scale = c_out / np.maximum(c, _EPS)
    return (ab * scale[..., None]).astype(np.float32)


def rebuild_source_layer(ab: np.ndarray, l_ref: float) -> np.ndarray:
    """以**常数明度** ``l_ref`` 重建 sRGB 图像 —— 得到等亮度的上层源图像。

    所有像素共享同一个 Oklab ``L``，故该图像逐像素亮度恒定：壁纸的明暗
    结构在进入混合之前就已被彻底抹除；而 ``(a, b)`` 仍逐像素变化，所以它
    **仍然是一幅图像**，不是平涂色块。

    Args:
        ab: shape ``(h, w, 2)`` 的整形后色度平面（全分辨率）。
        l_ref: 参考明度，取 G1 的 Oklab ``L``。

    Returns:
        shape ``(h, w, 3)`` 的 sRGB 编码源图像，落在 ``[0, 1]``。
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


#: 抖动贴图边长（像素）。烘焙网格长边 ≤192，一张 256² 的贴图足以覆盖任何
#: 尺寸，故可全局缓存、按需切片。
_DITHER_TILE_SIZE: int = 256
#: 抖动贴图缓存（按种子）。
_DITHER_TILES: dict = {}


def _dither_tile(seed: int) -> np.ndarray:
    """返回缓存的 TPDF 抖动贴图（``(256, 256)`` float32）。"""
    tile = _DITHER_TILES.get(int(seed))
    if tile is None:
        rng = np.random.default_rng(int(seed))
        shape = (_DITHER_TILE_SIZE, _DITHER_TILE_SIZE)
        tile = (
            rng.random(shape, dtype=np.float32) - rng.random(shape, dtype=np.float32)
        ) * 0.5
        _DITHER_TILES[int(seed)] = tile
    return tile


def dither_tpdf(shape: Tuple[int, ...], seed: int = DITHER_SEED) -> np.ndarray:
    """生成确定性 TPDF 抖动噪声（三角分布，幅度 ±0.5 LSB）。

    合成结果是近乎平坦的大面积渐变，8-bit 量化极易产生色带；抖动是必需的。
    固定种子保证跨重绘稳定，不会闪烁。

    实现从一张全局缓存的 ``256²`` 贴图左上角切片，因此除首次调用外零随机数
    开销；同时带来一个额外好处：**噪声图案锚定在网格原点**，改变窗口尺寸
    时图案不会整体重排（否则缩放窗口会看到噪声"跳变"）。

    Args:
        shape: 噪声形状，通常为 ``(h, w, 1)``。
        seed: 随机种子。

    Returns:
        float32 噪声数组，取值范围 ``(-0.5, 0.5)``。
    """
    dims = tuple(int(v) for v in shape)
    tiled = (
        len(dims) >= 2
        and dims[0] <= _DITHER_TILE_SIZE
        and dims[1] <= _DITHER_TILE_SIZE
        and all(d == 1 for d in dims[2:])
    )
    if tiled:
        patch = _dither_tile(seed)[: dims[0], : dims[1]]
        return patch.reshape(dims) if len(dims) > 2 else patch
    rng = np.random.default_rng(seed)
    return (rng.random(dims, dtype=np.float32) - rng.random(dims, dtype=np.float32)) * 0.5


def compose_tint_float(
    source: np.ndarray,
    g1_rgb: Tuple[int, int, int],
    alpha: float = 0.85,
) -> np.ndarray:
    """把等亮度源图像以「颜色」模式合成到 G1 之上，返回**未量化**的浮点结果。

    逐像素流程：

    1. ``tinted = Color(B=G1, S=source)`` → 亮度恒为 ``Lum(G1)``，色相/彩度
       取自 source 的对应像素；
    2. ``out = G1 + (tinted − G1) · alpha`` → 色调强度线性可控。

    保持浮点输出是刻意的：量化必须发生在**最终显示分辨率**上，否则先量化
    再放大会把抖动平滑掉、色带重现（见 :func:`quantize_u8`）。

    Args:
        source: shape ``(h, w, 3)`` 的上层源图像（sRGB 编码值 0..1）。
        g1_rgb: G1 基色 ``(r, g, b)``，各分量 0..255。
        alpha: 色调强度，0 = 纯 G1（无色调），1 = 完整「颜色」混合结果。

    Returns:
        shape ``(h, w, 3)`` 的 float32 sRGB 编码值（0..1）。
    """
    backdrop = (np.asarray(g1_rgb, dtype=np.float32) / 255.0).reshape(1, 1, 3)
    tinted = color_blend(backdrop, np.asarray(source, dtype=np.float32))
    return np.asarray(backdrop + (tinted - backdrop) * float(alpha), dtype=np.float32)


def quantize_u8(
    values: np.ndarray,
    dither: bool = True,
    seed: int = DITHER_SEED,
) -> np.ndarray:
    """TPDF 抖动 + 四舍五入，把 0..1 浮点图量化为 uint8。

    Args:
        values: shape ``(h, w, c)`` 的浮点图（sRGB 编码值 0..1）。
        dither: 是否施加 TPDF 抖动。
        seed: 抖动种子。

    Returns:
        同 shape 的 uint8 数组。
    """
    out = np.asarray(values, dtype=np.float32)
    if dither:
        out = out + dither_tpdf((out.shape[0], out.shape[1], 1), seed) / 255.0
    return np.clip(np.rint(out * 255.0), 0.0, 255.0).astype(np.uint8)


def compose_tint(
    source: np.ndarray,
    g1_rgb: Tuple[int, int, int],
    alpha: float = 0.85,
    dither: bool = True,
    seed: int = DITHER_SEED,
) -> np.ndarray:
    """把等亮度源图像以 Photoshop「颜色」模式合成到 G1 基色图层之上并量化。

    等价于 ``quantize_u8(compose_tint_float(...))``。

    Args:
        source: shape ``(h, w, 3)`` 的上层源图像（sRGB 编码值 0..1）。
        g1_rgb: G1 基色 ``(r, g, b)``，各分量 0..255。
        alpha: 色调强度，0 = 纯 G1（无色调），1 = 完整「颜色」混合结果。
        dither: 是否施加 TPDF 抖动。
        seed: 抖动种子。

    Returns:
        shape ``(h, w, 3)`` 的 uint8 合成结果（完全不透明）。
    """
    return quantize_u8(compose_tint_float(source, g1_rgb, alpha), dither, seed)


# ---------------------------------------------------------------------------
# 顶层编排（纯 numpy，不含 Qt）
# ---------------------------------------------------------------------------


@dataclass
class TintField:
    """色调场烘焙结果（含中间产物，便于调试与自动化校验）。

    Attributes:
        image: shape ``(h, w, 3)`` 的 uint8 最终合成图。
        source_layer: shape ``(h, w, 3)`` 的 uint8 等亮度上层源图像，
            用于校验"无任何明暗结构残留"。
        chroma: shape ``(h, w, 2)`` 的低通整形后色度平面。
    """

    image: np.ndarray
    source_layer: np.ndarray
    chroma: np.ndarray


def build_source_from_crop(
    crop_u8: np.ndarray,
    cap: float,
    gain: float,
    sigma: float,
    l_ref: float,
    downscale: Optional[int] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """由裁切后的壁纸块构建等亮度上层源图像。

    阶段顺序：去明度 → 可靠性权重 → 归一化加权低通 → 逐像素整形 →
    等亮度重建。

    Args:
        crop_u8: shape ``(h, w, 3)`` 的 uint8 裁切壁纸块（烘焙分辨率）。
        cap: 色度软上限。
        gain: 色度增益。
        sigma: 去轮廓高斯标准差（本图分辨率像素）。
        l_ref: 上层等亮度参考值（G1 的 Oklab ``L``）。
        downscale: 低通降采样倍数；``None`` 时自动选择。

    Returns:
        ``(source, chroma)``：``source`` 为 ``(h, w, 3)`` 的 sRGB 0..1 源图像，
        ``chroma`` 为 ``(h, w, 2)`` 的整形后色度平面。
    """
    ab, y = chroma_from_srgb(crop_u8)
    weight = chroma_reliability(y)
    ab = blur_chroma(ab, weight, sigma, downscale)
    ab = shape_chroma(ab, cap, gain)
    return rebuild_source_layer(ab, l_ref), ab


def bake_composite(
    crop_u8: np.ndarray,
    g1_rgb: Tuple[int, int, int],
    cap: float,
    gain: float,
    sigma: float,
    alpha: float,
    downscale: Optional[int] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """完整色调场管线，输出**未量化**的浮点合成结果。

    这是 :mod:`mica.engine` 使用的热路径入口：它在工作分辨率上跑完整条管线，
    把量化推迟到放大之后（见 :func:`quantize_u8`）。

    Args:
        crop_u8: shape ``(h, w, 3)`` 的 uint8 sRGB 裁切壁纸块（**工作分辨率**）。
        g1_rgb: G1 基色 ``(r, g, b)``。
        cap: 色度软上限。
        gain: 色度增益。
        sigma: 色度低通标准差（**本图分辨率像素**）。
        alpha: 色调强度 0..1。
        downscale: 低通降采样倍数；``None`` 时自动选择。

    Returns:
        ``(composite, chroma)``：``composite`` 为 ``(h, w, 3)`` float32
        sRGB 0..1 合成结果，``chroma`` 为 ``(h, w, 2)`` 整形后色度平面。
    """
    crop_u8 = np.ascontiguousarray(crop_u8, dtype=np.uint8)
    l_ref = g1_oklab_l(g1_rgb)
    source, chroma = build_source_from_crop(crop_u8, cap, gain, sigma, l_ref, downscale)
    return compose_tint_float(source, g1_rgb, alpha), chroma


def bake_tint_field(
    crop_u8: np.ndarray,
    g1_rgb: Tuple[int, int, int],
    cap: float,
    gain: float,
    sigma: float,
    alpha: float,
    dither: bool = True,
    downscale: Optional[int] = None,
) -> TintField:
    """完整色调场烘焙：去明度 → 门控 → 低通 → 整形 → 重建 → 与 G1 混合。

    纯 numpy 实现，不含任何 Qt 依赖，可在无显示环境下完整测试。

    Args:
        crop_u8: shape ``(h, w, 3)`` 的 uint8 sRGB 裁切壁纸块（烘焙分辨率）。
        g1_rgb: G1 基色 ``(r, g, b)``。
        cap: 色度软上限。
        gain: 色度增益。
        sigma: 色度低通标准差（烘焙网格像素）。
        alpha: 色调强度 0..1。
        dither: 是否施加 TPDF 抖动。
        downscale: 低通降采样倍数；``None`` 时自动选择。

    Returns:
        :class:`TintField`，含最终图像与中间产物。
    """
    crop_u8 = np.ascontiguousarray(crop_u8, dtype=np.uint8)
    l_ref = g1_oklab_l(g1_rgb)
    source, chroma = build_source_from_crop(
        crop_u8, cap, gain, sigma, l_ref, downscale
    )
    image = compose_tint(source, g1_rgb, alpha, dither)
    source_u8 = np.clip(np.rint(source * 255.0), 0, 255).astype(np.uint8)
    return TintField(image=image, source_layer=source_u8, chroma=chroma)


__all__ = [
    "CHROMA_LUMA_GATE_FEATHER",
    "CHROMA_LUMA_GATE_HI",
    "CHROMA_LUMA_GATE_LO",
    "DITHER_SEED",
    "GAMUT_MAP_ITERS",
    "MAX_BLUR_DOWNSCALE",
    "MAX_WORK_DOWNSCALE",
    "MIN_DOWNSAMPLED_SIDE",
    "MIN_WORK_LONG_SIDE",
    "WORK_TARGET_SIGMA",
    "TintField",
    "bake_composite",
    "bake_tint_field",
    "blur_chroma",
    "build_source_from_crop",
    "chroma_from_srgb",
    "chroma_reliability",
    "clip_color",
    "color_blend",
    "compose_tint",
    "compose_tint_float",
    "dither_tpdf",
    "g1_oklab_l",
    "linear_from_srgb_u8",
    "linear_rgb_from_oklab",
    "luma_ps",
    "oklab_from_linear_rgb",
    "quantize_u8",
    "rebuild_source_layer",
    "set_lum",
    "shape_chroma",
    "srgb_from_linear",
    "srgb_from_oklab",
    "srgb_to_linear_lut",
    "work_divisor",
]
