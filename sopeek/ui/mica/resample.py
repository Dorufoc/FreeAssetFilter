"""纯 numpy 图像重采样工具（伽马空间，与 Qt / GPU 纹理采样一致）。

烘焙管线只在一个很小的网格上工作（见 :func:`mica.config.bake_grid_size`），
因此重采样的核心任务是把**可能很大的壁纸区域**正确、抗锯齿地缩到网格分辨率。

为什么必须自己做而不能直接用 Qt 缩放：

* 管线运行在后台线程，Qt 的 ``QPixmap`` 不能在非 GUI 线程使用；
* 需要对越界区域做明确的**边缘钳制**（窗口贴在壁纸边缘时依然要采满）；
* 缩小时必须先做盒式预降采样，否则欠采样会产生摩尔纹 —— Qt 的
  ``SmoothTransformation`` 行为随版本与后端而异，不可依赖。

性能约定（热路径）
------------------
:func:`crop_resize` 每次烘焙都会在一幅**整屏尺寸**的画布上取一小块。因此它
必须遵守两条规则，否则单次烘焙会白白多花数十毫秒：

1. **先切包围盒、再预降采样**。只有真正会被采样到的源区域才参与盒式平均；
   对整幅画布做 ``mean`` 是纯粹的浪费（实测占单次烘焙 60 % 以上耗时）。
2. **包围盒按预降采样倍数对齐**。盒式平均的分块相位必须相对画布原点固定，
   否则窗口位置一变、分块相位就变，采样点随之亚像素漂移，破坏
   :mod:`mica.engine` 依赖的"色调只与屏幕位置有关"这一不变量。

所有函数均为纯函数（输入 numpy 数组，输出新数组），无 Qt / 平台依赖。
"""

from __future__ import annotations

import math
from typing import Dict, Optional, Tuple

import numpy as np

_EPS: float = 1e-6

#: mip 缓存的最大层级数。层级只按整数倍数索引，实测稳态下同时活跃的倍数
#: 不超过 3–4 个，12 是留足余量的上限。
MAX_MIP_ENTRIES: int = 12


# ---------------------------------------------------------------------------
# 内部：采样坐标与双线性取值
# ---------------------------------------------------------------------------


def _sample_coords(out_n: int, span: float, origin: float, limit: int) -> np.ndarray:
    """生成像素中心对齐的采样坐标，并按源图边界做钳制。

    映射规则：目标第 ``i`` 个像素的中心映射回源图
    ``(i + 0.5) · span / out_n + origin - 0.5``，等价于 ``GL_LINEAR``，
    与 Qt / GPU 纹理采样的对齐方式一致。

    Args:
        out_n: 输出方向上的像素数。
        span: 源图上被覆盖的长度（像素，浮点）。
        origin: 源图上的起始坐标（像素，浮点，允许为负）。
        limit: 源图该方向的尺寸（像素）。

    Returns:
        shape ``(out_n,)`` 的 float64 坐标数组，落在 ``[0, limit - 1]``。
    """
    n = max(1, int(out_n))
    t = (np.arange(n, dtype=np.float64) + 0.5) * float(span) / n + float(origin) - 0.5
    return np.clip(t, 0.0, float(max(int(limit) - 1, 0)))


def _bbox(coords: np.ndarray, limit: int, align: int = 1) -> Tuple[int, int]:
    """由采样坐标算出需要切出的源区间 ``[lo, hi)``。

    区间在两端各留 ``align`` 像素余量（保证双线性右邻点与盒式分块完整），
    并按 ``align`` 对齐到**源图原点**，使分块相位与采样位置无关。

    Args:
        coords: 单调的采样坐标数组（已钳制在源图内）。
        limit: 源图该方向的尺寸。
        align: 对齐粒度（= 预降采样倍数）。

    Returns:
        ``(lo, hi)``，满足 ``0 <= lo < hi <= limit``。
    """
    limit = max(1, int(limit))
    align = max(1, int(align))
    lo = int(math.floor(float(coords.min()))) - align
    hi = int(math.floor(float(coords.max()))) + 2 + align
    if align > 1:
        lo = (lo // align) * align
        hi = int(math.ceil(hi / align)) * align
    lo = max(0, min(lo, limit - 1))
    hi = max(lo + 1, min(hi, limit))
    return lo, hi


def _bilinear_gather(src: np.ndarray, ys: np.ndarray, xs: np.ndarray) -> np.ndarray:
    """在 ``src`` 上按分离的行/列坐标做双线性采样。

    使用二维花式索引 ``src[iy[:, None], ix[None, :]]`` 一步取到目标形状，
    **不**产生 ``(out_h, src_w, c)`` 这类整行中间量 —— 后者在整屏画布上
    会造成数 MB 的无谓拷贝。

    Args:
        src: shape ``(h, w, c)`` 的源图（uint8 或 float）。
        ys: shape ``(out_h,)`` 的行坐标。
        xs: shape ``(out_w,)`` 的列坐标。

    Returns:
        shape ``(out_h, out_w, c)`` 的 float32 采样结果。
    """
    sh, sw = int(src.shape[0]), int(src.shape[1])
    ix0 = np.clip(np.floor(xs), 0.0, sw - 1.0).astype(np.int64)
    iy0 = np.clip(np.floor(ys), 0.0, sh - 1.0).astype(np.int64)
    ix1 = np.minimum(ix0 + 1, sw - 1)
    iy1 = np.minimum(iy0 + 1, sh - 1)
    tx = (xs - ix0).astype(np.float32)[None, :, None]
    ty = (ys - iy0).astype(np.float32)[:, None, None]

    r0 = iy0[:, None]
    r1 = iy1[:, None]
    c0 = ix0[None, :]
    c1 = ix1[None, :]
    p00 = src[r0, c0].astype(np.float32, copy=False)
    p01 = src[r0, c1].astype(np.float32, copy=False)
    p10 = src[r1, c0].astype(np.float32, copy=False)
    p11 = src[r1, c1].astype(np.float32, copy=False)

    top = p00 + (p01 - p00) * tx
    bot = p10 + (p11 - p10) * tx
    return top + (bot - top) * ty


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


def box_downsample_u8(image_u8: np.ndarray, factor: int) -> np.ndarray:
    """对 uint8 图像做 ``factor`` 倍盒式降采样（伽马空间，仅用于预降采样）。

    Args:
        image_u8: shape ``(h, w, c)`` 的 uint8 源图。
        factor: 降采样倍数；``<= 1`` 时原样返回。

    Returns:
        shape ``(ceil(h/f), ceil(w/f), c)`` 的 uint8 数组。
    """
    factor = max(1, int(factor))
    if factor == 1:
        return image_u8
    h, w = int(image_u8.shape[0]), int(image_u8.shape[1])
    bh = max(1, int(math.ceil(h / factor)))
    bw = max(1, int(math.ceil(w / factor)))
    pad_h = bh * factor - h
    pad_w = bw * factor - w
    arr = np.asarray(image_u8, dtype=np.float32)
    if pad_h > 0 or pad_w > 0:
        arr = np.pad(arr, ((0, pad_h), (0, pad_w), (0, 0)), mode="edge")
    arr = np.ascontiguousarray(arr)
    return (
        arr.reshape(bh, factor, bw, factor, -1)
        .mean(axis=(1, 3))
        .astype(np.uint8)
    )


def pre_downsample_factor(span_w: float, span_h: float, out_w: int, out_h: int) -> int:
    """欠采样保护：缩放比超过 2 时需要的盒式预降采样倍数。

    Args:
        span_w: 源图上被覆盖的宽度（像素）。
        span_h: 源图上被覆盖的高度（像素）。
        out_w: 输出宽度。
        out_h: 输出高度。

    Returns:
        预降采样倍数，``1`` 表示不需要。
    """
    ow = max(1, int(out_w))
    oh = max(1, int(out_h))
    if span_w <= 2.0 * ow and span_h <= 2.0 * oh:
        return 1
    return max(1, int(min(span_w / ow, span_h / oh) / 2.0))


def mip_level(
    base: np.ndarray,
    factor: int,
    cache: Optional[Dict[int, np.ndarray]] = None,
) -> np.ndarray:
    """返回 ``base`` 的 ``factor`` 倍盒式降采样层级，按需构建并缓存。

    烘焙热路径的关键缓存：窗口较大时采样矩形会覆盖整个桌面，预降采样等于
    对整幅画布做一次盒式平均（1600×1000 约 20 ms）。而该结果**只取决于画布
    与倍数**，与窗口位置、参数、主题都无关，因此必须跨烘焙复用。

    构建新层级时优先从"能整除 ``factor``"的已有层级折算：整除保证分块边界与
    直接从 ``base`` 降采样完全一致，于是分块相位仍锚定画布原点，
    :mod:`mica.engine` 依赖的位置不变性不受影响。

    Args:
        base: shape ``(h, w, c)`` 的 uint8 原始画布。
        factor: 降采样倍数；``<= 1`` 时原样返回 ``base``。
        cache: 调用方持有的层级缓存（键为倍数）；``None`` 时不缓存。

    Returns:
        降采样后的 uint8 数组（``factor <= 1`` 时即 ``base`` 本身）。
    """
    f = max(1, int(factor))
    if f == 1:
        return base
    if cache is None:
        return box_downsample_u8(base, f)
    hit = cache.get(f)
    if hit is not None:
        return hit
    best = 1
    for have in cache:
        if have > best and f % have == 0:
            best = have
    src = cache[best] if best > 1 else base
    level = box_downsample_u8(src, f // best)
    if len(cache) >= MAX_MIP_ENTRIES:
        cache.pop(next(iter(cache)), None)
    cache[f] = level
    return level


def crop_resize(
    image_u8: np.ndarray,
    rect_px: Tuple[float, float, float, float],
    out_w: int,
    out_h: int,
    mip_cache: Optional[Dict[int, np.ndarray]] = None,
) -> np.ndarray:
    """按浮点矩形裁切（越界按边缘钳制）并重采样到 ``(out_h, out_w)``。

    执行顺序为「算坐标 → 预降采样 → 双线性」。预降采样有两条路径：

    * 传入 ``mip_cache`` 时走 :func:`mip_level`，整幅画布的层级跨烘焙复用 ——
      这是热路径应当使用的方式；
    * 未传缓存时退化为"先切包围盒再降采样"，只处理真正会被采样到的源区域。
      包围盒按倍数对齐到画布原点，保证分块相位与窗口位置无关。

    两条路径的输出在数值上一致（分块边界相同），差别只在是否复用。

    Args:
        image_u8: shape ``(h, w, c)`` 的 uint8 sRGB 源图。
        rect_px: ``(x, y, w, h)`` 浮点裁切矩形（允许越界）。
        out_w: 输出宽度（像素）。
        out_h: 输出高度（像素）。
        mip_cache: 可选的 mip 层级缓存，须与 ``image_u8`` 一一绑定。

    Returns:
        shape ``(out_h, out_w, c)`` 的 uint8 数组。
    """
    h, w = int(image_u8.shape[0]), int(image_u8.shape[1])
    out_w = max(1, int(out_w))
    out_h = max(1, int(out_h))
    x0, y0, rw, rh = (float(v) for v in rect_px)

    xs = _sample_coords(out_w, rw, x0, w)
    ys = _sample_coords(out_h, rh, y0, h)
    pre = pre_downsample_factor(rw, rh, out_w, out_h)

    if pre > 1 and mip_cache is not None:
        src = mip_level(image_u8, pre, mip_cache)
        # 盒式降采样后，层级像素 k 的中心对应原坐标 k·pre + (pre-1)/2
        half = (pre - 1) * 0.5
        xs = (xs - half) / pre
        ys = (ys - half) / pre
    else:
        bx0, bx1 = _bbox(xs, w, pre)
        by0, by1 = _bbox(ys, h, pre)
        src = image_u8[by0:by1, bx0:bx1]
        xs = xs - bx0
        ys = ys - by0
        if pre > 1:
            src = box_downsample_u8(src, pre)
            half = (pre - 1) * 0.5
            xs = (xs - half) / pre
            ys = (ys - half) / pre

    out = _bilinear_gather(src, ys, xs)
    return np.clip(np.rint(out), 0.0, 255.0).astype(np.uint8)


def crop_f32(
    image_f32: np.ndarray,
    rect_px: Tuple[float, float, float, float],
    out_w: int,
    out_h: int,
) -> np.ndarray:
    """浮点图像的双线性裁切重采样（**放大**专用，不做预降采样）。

    用于把工作分辨率上的浮点合成结果放大回烘焙网格分辨率。保持浮点直到
    最后一步量化，是抖动能真正消除色带的前提 —— 先量化再放大会把抖动
    平滑掉，色带重现。

    Args:
        image_f32: shape ``(h, w, c)`` 的浮点源图。
        rect_px: ``(x, y, w, h)`` 浮点裁切矩形（允许越界，按边缘钳制）。
        out_w: 输出宽度（像素）。
        out_h: 输出高度（像素）。

    Returns:
        shape ``(out_h, out_w, c)`` 的 float32 数组。
    """
    arr = np.asarray(image_f32, dtype=np.float32)
    h, w = int(arr.shape[0]), int(arr.shape[1])
    x0, y0, rw, rh = (float(v) for v in rect_px)
    xs = _sample_coords(out_w, rw, x0, w)
    ys = _sample_coords(out_h, rh, y0, h)
    return _bilinear_gather(arr, ys, xs)


def upsample_2d(grid: np.ndarray, out_h: int, out_w: int) -> np.ndarray:
    """双线性放大 2D 标量场（像素中心对齐，与 :func:`crop_resize` 一致）。

    Args:
        grid: shape ``(gh, gw)`` 的 2D 数组。
        out_h: 输出高度。
        out_w: 输出宽度。

    Returns:
        shape ``(out_h, out_w)`` 的 float32 数组。
    """
    arr = np.asarray(grid, dtype=np.float32)
    gh, gw = int(arr.shape[0]), int(arr.shape[1])
    xs = _sample_coords(out_w, float(gw), 0.0, gw)
    ys = _sample_coords(out_h, float(gh), 0.0, gh)
    return _bilinear_gather(arr[..., None], ys, xs)[..., 0]


def resample_u8(image_u8: np.ndarray, out_w: int, out_h: int) -> np.ndarray:
    """把 uint8 图像双线性重采样到 ``(out_h, out_w)``（整幅映射）。

    Args:
        image_u8: shape ``(h, w, c)`` 的 uint8 源图。
        out_w: 输出宽度（像素）。
        out_h: 输出高度（像素）。

    Returns:
        shape ``(out_h, out_w, c)`` 的 uint8 数组。
    """
    return crop_resize(
        image_u8,
        (0.0, 0.0, float(image_u8.shape[1]), float(image_u8.shape[0])),
        out_w,
        out_h,
    )


__all__ = [
    "MAX_MIP_ENTRIES",
    "box_downsample_u8",
    "crop_f32",
    "crop_resize",
    "mip_level",
    "pre_downsample_factor",
    "resample_u8",
    "upsample_2d",
]
