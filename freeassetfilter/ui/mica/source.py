"""壁纸源获取层：把 Windows 桌面壁纸解析为统一的 numpy 画布。

本模块回答一个问题：**"窗口后面的那块壁纸长什么样？"** 并把答案表达为一个
与虚拟桌面坐标严格对齐的低分辨率画布（:class:`WallpaperSource`），供
:mod:`mica.engine` 裁切、:mod:`mica.tint` 上色。

为什么首选"解码壁纸文件"而不是"抓屏"
------------------------------------
Win11 Mica 采样的是**壁纸本身**，不是屏幕上呈现的内容。若直接抓屏：

* 叠在下方的其他窗口会被采进来 —— 两个 Mica 窗口互相取色会正反馈发散；
* 自己上一帧的背景也会被采到，形成自激；
* 任务栏 / 图标的高对比边缘会在色度低通后渗出脏色块。

因此采集链把"抓屏"降级为兜底手段：

======  ==================================  ==========================
优先级  后端                                适用场景
======  ==================================  ==========================
1       ``IDesktopWallpaper``（Shell COM）  Win8+，可拿到**每显示器异图**、
                                            纯色背景色与放置方式
2       ``SystemParametersInfoW``           COM 不可用时的单图路径
3       ``Control Panel\\Desktop`` 注册表    SPI 亦失败时的路径 + 放置方式
4       DXGI 桌面复制（``FAF_MICA_DXGI=1``）动态壁纸 / 幻灯片 / 无文件可解码
5       GDI ``BitBlt``                      DXGI 不可用（零 COM 风险）
6       纯色                                以上全部失败；取桌面背景色 → G1
======  ==================================  ==========================

任一环节失败都静默降级到下一级，绝不抛异常打断 UI。

坐标空间约定
------------
画布的坐标空间是**当前进程看到的虚拟桌面空间**（``virtual_screen_rect()``）。
这一点很关键：DPI 感知进程里它等于物理像素，非感知进程里它是被系统缩放过的
逻辑像素。``IDesktopWallpaper::GetMonitorRECT`` **总是**返回物理像素，因此
:func:`_normalize_monitors` 会在两者不一致时把显示器矩形归一化到进程空间，
保证 Qt 几何、GDI 抓屏、壁纸摆放三者始终对得上。

本模块只依赖 numpy 与 Pillow（解码），**不依赖 Qt**，可在无显示环境下测试。
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import winapi
from .resample import crop_resize, resample_u8

_LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: 画布长边上限（画布像素）。烘焙网格长边最大 192（见 ``config.BAKE_LONG_MAX``），
#: 且色度会以 σ≥2 低通，因此保留 1600 已远超必要精度，同时把常驻内存压在 5MB 内。
CANVAS_MAX_LONG: int = 1600

#: 解码过采样系数：按画布需求的多少倍去请求解码分辨率，给重采样留抗锯齿余量。
DECODE_OVERSAMPLE: float = 1.5

#: 解码分辨率硬上限（长边像素），防止 8K 壁纸吃满内存。
DECODE_MAX_LONG: int = 4096

#: 启用 DXGI 桌面复制后端的环境变量（``"1"``/``"true"``/``"yes"``/``"on"`` 视为开启）。
ENV_DXGI: str = "FAF_MICA_DXGI"

#: DXGI ``AcquireNextFrame`` 超时（毫秒）。
DXGI_TIMEOUT_MS: int = 120

#: 后端标识。
BACKEND_WALLPAPER: str = "wallpaper"
BACKEND_DXGI: str = "dxgi"
BACKEND_GDI: str = "gdi"
BACKEND_SOLID: str = "solid"

#: 非 Windows / 探测失败时的兜底虚拟桌面尺寸。
DEFAULT_VIRTUAL_RECT: Tuple[int, int, int, int] = (0, 0, 1920, 1080)

#: 注册表 ``WallpaperStyle`` → 放置方式。
_REGISTRY_STYLES = {
    "0": "Center",
    "1": "Tile",
    "2": "Stretch",
    "6": "Fit",
    "10": "Fill",
    "22": "Span",
}

#: 合法放置方式（与 ``winapi._WALLPAPER_POSITIONS`` 一致）。
VALID_POSITIONS: Tuple[str, ...] = ("Center", "Tile", "Stretch", "Fit", "Fill", "Span")

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def dxgi_enabled() -> bool:
    """DXGI 桌面复制后端是否启用（读取 :data:`ENV_DXGI`）。

    默认**关闭**：桌面复制会与部分动态壁纸软件（如 Wallpaper Engine）争抢
    独占的复制会话而返回 ``DXGI_ERROR_INVALID_CALL``，且它只是第 4 级兜底，
    GDI 已足够。需要时显式设置 ``FAF_MICA_DXGI=1`` 开启。

    Returns:
        启用则 ``True``。
    """
    return os.environ.get(ENV_DXGI, "").strip().lower() in _TRUTHY


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MonitorInfo:
    """单台显示器的壁纸相关信息。

    Attributes:
        rect: ``(x, y, w, h)``，进程虚拟桌面空间中的显示器矩形。
        wallpaper_path: 该显示器的壁纸文件路径；纯色或未知时为空串。
        monitor_id: ``IDesktopWallpaper`` 的 monitorID；不可用时为空串。
    """

    rect: Tuple[int, int, int, int]
    wallpaper_path: str = ""
    monitor_id: str = ""


@dataclass(frozen=True)
class DesktopInfo:
    """一次桌面探测的结果（不含像素，仅元数据）。

    Attributes:
        virtual_rect: ``(x, y, w, h)`` 虚拟桌面矩形（进程空间）。
        monitors: 显示器列表，至少一项。
        position: 壁纸放置方式，取值见 :data:`VALID_POSITIONS`。
        background_rgb: 桌面纯色背景色 ``(r, g, b)``。
        source: 元数据来源标识（``"com"`` / ``"spi"`` / ``"registry"`` / ``"none"``）。
    """

    virtual_rect: Tuple[int, int, int, int]
    monitors: Tuple[MonitorInfo, ...]
    position: str
    background_rgb: Tuple[int, int, int]
    source: str

    def signature(self) -> str:
        """生成用于变更检测的指纹（含壁纸文件的 mtime/size）。

        Returns:
            稳定的短字符串；壁纸、显示器布局或放置方式变化时必然改变。
        """
        parts: List[str] = [
            f"v={self.virtual_rect}",
            f"p={self.position}",
            f"bg={self.background_rgb}",
        ]
        for mon in self.monitors:
            stamp = _file_stamp(mon.wallpaper_path)
            parts.append(f"m={mon.rect}|{mon.wallpaper_path}|{stamp}")
        return ";".join(parts)


@dataclass(frozen=True)
class WallpaperSource:
    """统一壁纸源：一块与虚拟桌面对齐的 uint8 RGB 画布。

    Attributes:
        pixels: shape ``(H, W, 3)`` 的 uint8 sRGB 画布。
        origin: ``pixels[0, 0]`` 对应的虚拟桌面坐标 ``(x, y)``。
        scale: 画布像素 / 虚拟桌面像素（``<= 1``）。
        backend: 实际生效的后端，取值见 ``BACKEND_*``。
        info: 产生该画布的 :class:`DesktopInfo`。
        signature: 对应的指纹字符串（用于缓存命中判断）。
        mip_cache: 画布的盒式降采样层级缓存，由 :meth:`crop` 内部维护。
            它与 ``pixels`` 一一绑定 —— 壁纸变化时整个 :class:`WallpaperSource`
            会被重建，缓存随之丢弃，因此不存在陈旧层级被误用的可能。
    """

    pixels: np.ndarray
    origin: Tuple[int, int]
    scale: float
    backend: str
    info: DesktopInfo
    signature: str
    mip_cache: Dict[int, np.ndarray] = field(
        default_factory=dict, compare=False, repr=False
    )

    @property
    def size(self) -> Tuple[int, int]:
        """画布尺寸 ``(w, h)``（画布像素）。"""
        return (int(self.pixels.shape[1]), int(self.pixels.shape[0]))

    def crop(
        self,
        rect_virtual: Tuple[float, float, float, float],
        out_w: int,
        out_h: int,
    ) -> np.ndarray:
        """把虚拟桌面矩形重采样为 ``(out_h, out_w, 3)`` 的 uint8 块。

        这是烘焙管线取样的**唯一入口**：它带上本实例的 mip 缓存，使整幅画布的
        预降采样层级跨烘焙复用（否则每次烘焙都要重扫整幅画布，见
        :func:`mica.resample.mip_level`）。

        Args:
            rect_virtual: ``(x, y, w, h)``，虚拟桌面空间（进程像素，允许越界）。
            out_w: 输出宽度（像素）。
            out_h: 输出高度（像素）。

        Returns:
            shape ``(out_h, out_w, 3)`` 的 uint8 数组。
        """
        return crop_resize(
            self.pixels,
            self.to_source_rect(rect_virtual),
            out_w,
            out_h,
            mip_cache=self.mip_cache,
        )

    def to_source_rect(
        self, rect_virtual: Tuple[float, float, float, float]
    ) -> Tuple[float, float, float, float]:
        """把虚拟桌面矩形换算为画布像素矩形（浮点，允许越界）。

        越界不需要在此钳制 —— :func:`mica.resample.crop_resize` 会做边缘钳制，
        这正是窗口贴到屏幕边缘时仍能采满色度的原因。

        Args:
            rect_virtual: ``(x, y, w, h)``，虚拟桌面空间（进程像素）。

        Returns:
            ``(x, y, w, h)`` 画布像素浮点矩形。
        """
        ox, oy = self.origin
        x, y, w, h = (float(v) for v in rect_virtual)
        return (
            (x - float(ox)) * self.scale,
            (y - float(oy)) * self.scale,
            max(1.0, w * self.scale),
            max(1.0, h * self.scale),
        )

    def mean_rgb(self) -> Tuple[int, int, int]:
        """画布平均色，用于极端降级（画布不可用时的单色兜底）。"""
        mean = self.pixels.reshape(-1, 3).mean(axis=0)
        return tuple(int(round(float(v))) for v in mean)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _file_stamp(path: str) -> str:
    """壁纸文件的 ``mtime_ns:size`` 指纹；不存在或不可读时返回 ``"-"``。

    Args:
        path: 文件路径。

    Returns:
        指纹字符串。
    """
    if not path:
        return "-"
    try:
        st = os.stat(path)
    except OSError:
        return "-"
    return f"{st.st_mtime_ns}:{st.st_size}"


def _canvas_scale(vw: int, vh: int, max_long: int) -> float:
    """按长边上限计算画布缩放系数。

    Args:
        vw: 虚拟桌面宽度。
        vh: 虚拟桌面高度。
        max_long: 画布长边上限。

    Returns:
        ``(0, 1]`` 区间的缩放系数。
    """
    long_side = max(int(vw), int(vh), 1)
    max_long = max(16, int(max_long))
    if long_side <= max_long:
        return 1.0
    return float(max_long) / float(long_side)


def _position_from_registry(style: str, tile: str) -> str:
    """把注册表的 ``WallpaperStyle`` / ``TileWallpaper`` 翻译为放置方式。

    Args:
        style: ``WallpaperStyle`` 原始值。
        tile: ``TileWallpaper`` 原始值。

    Returns:
        :data:`VALID_POSITIONS` 中的一项；无法识别时为 ``"Fill"``。
    """
    if str(tile).strip() == "1":
        return "Tile"
    return _REGISTRY_STYLES.get(str(style).strip(), "Fill")


def _normalize_monitors(
    rects: Sequence[Tuple[int, int, int, int]],
    virtual_rect: Tuple[int, int, int, int],
) -> List[Tuple[int, int, int, int]]:
    """把物理像素的显示器矩形归一化到进程虚拟桌面空间。

    ``IDesktopWallpaper::GetMonitorRECT`` 返回物理像素；而 ``GetSystemMetrics``
    在 DPI 非感知进程里返回缩放后的逻辑像素。两者不一致时按并集比例线性映射，
    使显示器矩形与 Qt 几何、GDI 抓屏处于同一空间。

    Args:
        rects: ``(l, t, r, b)`` 形式的显示器矩形序列（注意是 LTRB）。
        virtual_rect: ``(x, y, w, h)`` 进程虚拟桌面矩形。

    Returns:
        ``(x, y, w, h)`` 形式、已归一化的矩形列表；输入为空时返回 ``[virtual_rect]``。
    """
    vx, vy, vw, vh = (int(v) for v in virtual_rect)
    boxes = [
        (int(l), int(t), int(r) - int(l), int(b) - int(t))
        for (l, t, r, b) in rects
        if int(r) > int(l) and int(b) > int(t)
    ]
    if not boxes:
        return [(vx, vy, max(1, vw), max(1, vh))]

    ux0 = min(b[0] for b in boxes)
    uy0 = min(b[1] for b in boxes)
    ux1 = max(b[0] + b[2] for b in boxes)
    uy1 = max(b[1] + b[3] for b in boxes)
    uw, uh = max(1, ux1 - ux0), max(1, uy1 - uy0)

    if abs(uw - vw) <= 2 and abs(uh - vh) <= 2:
        return boxes

    sx = float(vw) / float(uw)
    sy = float(vh) / float(uh)
    _LOG.debug(
        "显示器矩形空间归一化：并集 %dx%d → 虚拟桌面 %dx%d (sx=%.4f sy=%.4f)",
        uw, uh, vw, vh, sx, sy,
    )
    scaled: List[Tuple[int, int, int, int]] = []
    for bx, by, bw, bh in boxes:
        nx = vx + int(round((bx - ux0) * sx))
        ny = vy + int(round((by - uy0) * sy))
        nw = max(1, int(round(bw * sx)))
        nh = max(1, int(round(bh * sy)))
        scaled.append((nx, ny, nw, nh))
    return scaled


def _bgra_to_rgb(data: bytes, width: int, height: int) -> Optional[np.ndarray]:
    """把自顶向下的 BGRA 原始字节转成 ``(h, w, 3)`` uint8 RGB。

    Args:
        data: 长度应为 ``width * height * 4`` 的字节串。
        width: 宽度（像素）。
        height: 高度（像素）。

    Returns:
        RGB 数组；长度不匹配时返回 ``None``。
    """
    width, height = int(width), int(height)
    expect = width * height * 4
    if width <= 0 or height <= 0 or len(data) < expect:
        return None
    arr = np.frombuffer(data[:expect], dtype=np.uint8).reshape(height, width, 4)
    return np.ascontiguousarray(arr[:, :, 2::-1])


# ---------------------------------------------------------------------------
# 壁纸文件解码
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DecodedWallpaper:
    """一次壁纸解码的结果。

    ``Center`` / ``Tile`` 两种放置方式依赖壁纸的**原始**像素尺寸，而解码期
    可能已做整数倍降采样，因此必须把原始尺寸一并带出，否则平铺周期与居中
    尺寸都会算错。

    Attributes:
        pixels: shape ``(h, w, 3)`` 的 uint8 RGB 数组（可能已降采样）。
        native_size: 壁纸文件的原始像素尺寸 ``(w, h)``。
    """

    pixels: np.ndarray
    native_size: Tuple[int, int]

    @property
    def decode_scale(self) -> float:
        """解码尺寸 / 原始尺寸（``<= 1``）。"""
        nat_w = max(1, int(self.native_size[0]))
        return float(self.pixels.shape[1]) / float(nat_w)


def decode_wallpaper(
    path: str, target_w: int, target_h: int
) -> Optional[DecodedWallpaper]:
    """解码壁纸文件为 uint8 RGB，尽量以接近目标尺寸的分辨率解码。

    JPEG 走 Pillow 的 ``draft()``（DCT 域 1/2、1/4、1/8 缩放，几乎零成本），
    其余格式解码后用 ``reduce()`` 做快速盒式降采样。两者都只**降**不升，
    最终精确缩放交给 :func:`mica.resample.crop_resize`。

    Args:
        path: 壁纸文件路径。
        target_w: 期望宽度（像素），用于挑选解码档位。
        target_h: 期望高度（像素）。

    Returns:
        :class:`DecodedWallpaper`；文件缺失、格式不支持或 Pillow 不可用时
        返回 ``None``。
    """
    if not path or not os.path.isfile(path):
        return None
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow 是硬依赖
        _LOG.warning("Pillow 不可用，无法解码壁纸文件")
        return None

    want_w = max(1, int(target_w))
    want_h = max(1, int(target_h))
    try:
        with Image.open(path) as img:
            native = (int(img.size[0]), int(img.size[1]))
            if native[0] <= 0 or native[1] <= 0:
                return None

            # JPEG：DCT 域缩放，直接省掉大部分解码开销
            try:
                img.draft("RGB", (want_w, want_h))
            except (AttributeError, ValueError, OSError):
                pass

            iw, ih = int(img.size[0]), int(img.size[1])

            # 解码后仍远大于需求时再做整数倍盒式降采样
            factor = min(iw // want_w, ih // want_h)
            long_side = max(iw, ih)
            if long_side > DECODE_MAX_LONG:
                factor = max(factor, int(math.ceil(long_side / DECODE_MAX_LONG)))
            if factor > 1:
                try:
                    img = img.reduce(factor)
                except (AttributeError, ValueError, OSError):
                    pass

            if img.mode != "RGB":
                img = img.convert("RGB")
            return DecodedWallpaper(
                pixels=np.asarray(img, dtype=np.uint8), native_size=native
            )
    except (OSError, ValueError, MemoryError) as exc:
        _LOG.debug("壁纸解码失败 %s: %s", path, exc)
        return None


# ---------------------------------------------------------------------------
# 放置数学
# ---------------------------------------------------------------------------


def render_placement(
    image_u8: np.ndarray,
    dest_w: int,
    dest_h: int,
    canvas_scale: float,
    position: str,
    background_rgb: Tuple[int, int, int],
    native_size: Optional[Tuple[int, int]] = None,
) -> np.ndarray:
    """按 Windows 壁纸放置方式把一幅壁纸渲染到 ``(dest_h, dest_w)`` 目标区域。

    六种放置方式的语义与 ``DESKTOP_WALLPAPER_POSITION`` 一致：

    * ``Fill`` / ``Span``：等比放大到铺满，居中裁切多余部分；
    * ``Fit``：等比缩放到完整可见，留边填充桌面背景色；
    * ``Stretch``：非等比拉伸到精确铺满；
    * ``Center``：原始像素尺寸居中（超出则居中裁切，不足则留边）；
    * ``Tile``：原始像素尺寸从左上角平铺。

    ``Center`` / ``Tile`` 依赖"原始像素尺寸"，因此需要 ``canvas_scale``
    把屏幕像素换算到画布像素。

    Args:
        image_u8: shape ``(h, w, 3)`` 的 uint8 壁纸（已按需降采样）。
        dest_w: 目标宽度（画布像素）。
        dest_h: 目标高度（画布像素）。
        canvas_scale: 画布像素 / 屏幕像素。
        position: 放置方式，见 :data:`VALID_POSITIONS`。
        background_rgb: 留边区域的填充色。
        native_size: 壁纸的**原始**像素尺寸 ``(w, h)``；``None`` 表示
            ``image_u8`` 即为原始分辨率。仅 ``Center`` / ``Tile`` 会用到。

    Returns:
        shape ``(dest_h, dest_w, 3)`` 的 uint8 数组。
    """
    dest_w = max(1, int(dest_w))
    dest_h = max(1, int(dest_h))
    ih, iw = int(image_u8.shape[0]), int(image_u8.shape[1])
    if iw <= 0 or ih <= 0:
        return np.full((dest_h, dest_w, 3), np.array(background_rgb, np.uint8), np.uint8)

    pos = position if position in VALID_POSITIONS else "Fill"

    # Center / Tile 以"原始屏幕像素尺寸"为基准，需换算到画布空间
    if pos in ("Center", "Tile"):
        nat_w, nat_h = _native_canvas_size(
            native_size if native_size else (iw, ih), canvas_scale
        )
        if pos == "Tile":
            return _render_tile(image_u8, dest_w, dest_h, nat_w, nat_h)
        return _render_center(image_u8, dest_w, dest_h, nat_w, nat_h, background_rgb)

    if pos == "Stretch":
        return resample_u8(image_u8, dest_w, dest_h)

    if pos == "Fit":
        scale = min(dest_w / iw, dest_h / ih)
        dw = max(1, int(round(iw * scale)))
        dh = max(1, int(round(ih * scale)))
        out = np.full((dest_h, dest_w, 3), np.array(background_rgb, np.uint8), np.uint8)
        ox = (dest_w - dw) // 2
        oy = (dest_h - dh) // 2
        out[oy : oy + dh, ox : ox + dw] = resample_u8(image_u8, dw, dh)
        return out

    # Fill / Span：按目标宽高比居中裁切源图后铺满
    target_ar = dest_w / dest_h
    image_ar = iw / ih
    if image_ar > target_ar:
        src_h = float(ih)
        src_w = src_h * target_ar
    else:
        src_w = float(iw)
        src_h = src_w / target_ar
    src_x = (iw - src_w) * 0.5
    src_y = (ih - src_h) * 0.5
    return crop_resize(image_u8, (src_x, src_y, src_w, src_h), dest_w, dest_h)


def _native_canvas_size(
    native_size: Tuple[int, int], canvas_scale: float
) -> Tuple[int, int]:
    """壁纸"原始像素尺寸"在画布空间中的大小。

    Args:
        native_size: 壁纸原始像素尺寸 ``(w, h)``。
        canvas_scale: 画布像素 / 屏幕像素。

    Returns:
        ``(w, h)``，最小为 ``(1, 1)``。
    """
    factor = max(float(canvas_scale), 1e-6)
    return (
        max(1, int(round(int(native_size[0]) * factor))),
        max(1, int(round(int(native_size[1]) * factor))),
    )


def _render_tile(
    image_u8: np.ndarray, dest_w: int, dest_h: int, nat_w: int, nat_h: int
) -> np.ndarray:
    """以原始尺寸从左上角平铺填满目标区域。

    Args:
        image_u8: 壁纸数组。
        dest_w: 目标宽度。
        dest_h: 目标高度。
        nat_w: 单块瓦片宽度（画布像素）。
        nat_h: 单块瓦片高度（画布像素）。

    Returns:
        shape ``(dest_h, dest_w, 3)`` 的 uint8 数组。
    """
    tile = resample_u8(image_u8, nat_w, nat_h)
    reps_x = max(1, int(math.ceil(dest_w / nat_w)))
    reps_y = max(1, int(math.ceil(dest_h / nat_h)))
    return np.ascontiguousarray(
        np.tile(tile, (reps_y, reps_x, 1))[:dest_h, :dest_w]
    )


def _render_center(
    image_u8: np.ndarray,
    dest_w: int,
    dest_h: int,
    nat_w: int,
    nat_h: int,
    background_rgb: Tuple[int, int, int],
) -> np.ndarray:
    """以原始尺寸居中放置（超出居中裁切，不足留边填背景色）。

    Args:
        image_u8: 壁纸数组。
        dest_w: 目标宽度。
        dest_h: 目标高度。
        nat_w: 原始尺寸宽度（画布像素）。
        nat_h: 原始尺寸高度（画布像素）。
        background_rgb: 留边填充色。

    Returns:
        shape ``(dest_h, dest_w, 3)`` 的 uint8 数组。
    """
    ih, iw = int(image_u8.shape[0]), int(image_u8.shape[1])
    out = np.full((dest_h, dest_w, 3), np.array(background_rgb, np.uint8), np.uint8)

    if nat_w <= dest_w:
        dx, dw = (dest_w - nat_w) // 2, nat_w
        sx, sw = 0.0, float(iw)
    else:
        dx, dw = 0, dest_w
        sw = iw * (dest_w / float(nat_w))
        sx = (iw - sw) * 0.5
    if nat_h <= dest_h:
        dy, dh = (dest_h - nat_h) // 2, nat_h
        sy, sh = 0.0, float(ih)
    else:
        dy, dh = 0, dest_h
        sh = ih * (dest_h / float(nat_h))
        sy = (ih - sh) * 0.5

    out[dy : dy + dh, dx : dx + dw] = crop_resize(image_u8, (sx, sy, sw, sh), dw, dh)
    return out


# ---------------------------------------------------------------------------
# 提供者
# ---------------------------------------------------------------------------


class WallpaperProvider:
    """壁纸源提供者：探测桌面元数据、构建画布、缓存与变更检测。

    线程约定：单个实例应只在一个线程上使用（COM 对象在每次调用内创建并释放，
    不跨线程持有）。:meth:`probe` 很轻（一次 COM + 若干 ``os.stat``），可用于
    定时轮询；:meth:`acquire` 才会真正解码与渲染。

    典型用法::

        provider = WallpaperProvider()
        src = provider.acquire()                     # 首次：解码 + 渲染
        if provider.probe().signature() != src.signature:
            src = provider.acquire()                 # 壁纸变了才重建
    """

    __slots__ = ("_canvas_max_long", "_fallback_rgb", "_cached", "_allow_dxgi")

    def __init__(
        self,
        *,
        canvas_max_long: int = CANVAS_MAX_LONG,
        fallback_rgb: Tuple[int, int, int] = (26, 26, 26),
        allow_dxgi: Optional[bool] = None,
    ) -> None:
        """初始化提供者。

        Args:
            canvas_max_long: 画布长边上限（画布像素）。
            fallback_rgb: 全部后端失败时的单色兜底（通常传主题 G1 基色）。
            allow_dxgi: 是否允许 DXGI 后端；``None`` 表示读取
                :data:`ENV_DXGI` 环境变量。
        """
        self._canvas_max_long = max(64, int(canvas_max_long))
        self._fallback_rgb = tuple(int(v) & 0xFF for v in fallback_rgb)  # type: ignore[assignment]
        self._cached: Optional[WallpaperSource] = None
        self._allow_dxgi = allow_dxgi

    # -- 探测 ---------------------------------------------------------------

    def probe(self) -> DesktopInfo:
        """探测桌面壁纸元数据（不解码像素）。

        依次尝试 ``IDesktopWallpaper`` → ``SystemParametersInfoW`` → 注册表，
        任一级拿到路径即停止向下探测放置方式的兜底来源。

        Returns:
            :class:`DesktopInfo`；非 Windows 或全部失败时返回纯色描述。
        """
        virtual_rect = self._virtual_rect()
        if not winapi.IS_WINDOWS:
            return DesktopInfo(
                virtual_rect=virtual_rect,
                monitors=(MonitorInfo(rect=virtual_rect),),
                position="Fill",
                background_rgb=self._fallback_rgb,
                source="none",
            )

        reg_path, reg_style, reg_tile = winapi.registry_desktop_values()
        info = self._probe_com(virtual_rect, reg_style, reg_tile)
        if info is not None:
            return info

        spi_path = winapi.wallpaper_path_spi()
        path = spi_path or reg_path
        source = "spi" if spi_path else ("registry" if reg_path else "none")
        bg = winapi.registry_background_color() or self._fallback_rgb
        return DesktopInfo(
            virtual_rect=virtual_rect,
            monitors=(MonitorInfo(rect=virtual_rect, wallpaper_path=path),),
            position=_position_from_registry(reg_style, reg_tile),
            background_rgb=bg,
            source=source,
        )

    def _probe_com(
        self, virtual_rect: Tuple[int, int, int, int], reg_style: str, reg_tile: str
    ) -> Optional[DesktopInfo]:
        """经 ``IDesktopWallpaper`` 探测；不可用时返回 ``None``。

        Args:
            virtual_rect: 进程虚拟桌面矩形。
            reg_style: 注册表 ``WallpaperStyle``（放置方式的兜底来源）。
            reg_tile: 注册表 ``TileWallpaper``。

        Returns:
            :class:`DesktopInfo` 或 ``None``。
        """
        dw = winapi.DesktopWallpaperCom.create()
        if dw is None:
            return None
        try:
            count = dw.monitor_count()
            ids: List[str] = []
            ltrb: List[Tuple[int, int, int, int]] = []
            for index in range(count):
                mid = dw.monitor_id(index)
                if not mid:
                    continue
                rect = dw.monitor_rect(mid)
                if rect is None:
                    continue
                ids.append(mid)
                ltrb.append(rect)

            position = dw.position()
            if position not in VALID_POSITIONS:
                position = _position_from_registry(reg_style, reg_tile)
            background = dw.background_color() or winapi.registry_background_color()

            boxes = _normalize_monitors(ltrb, virtual_rect)
            monitors: List[MonitorInfo] = []
            for i, box in enumerate(boxes):
                mid = ids[i] if i < len(ids) else ""
                monitors.append(
                    MonitorInfo(rect=box, wallpaper_path=dw.wallpaper(mid), monitor_id=mid)
                )
            if not monitors:
                monitors.append(
                    MonitorInfo(rect=virtual_rect, wallpaper_path=dw.wallpaper(""))
                )
            return DesktopInfo(
                virtual_rect=virtual_rect,
                monitors=tuple(monitors),
                position=position,
                background_rgb=background or self._fallback_rgb,
                source="com",
            )
        finally:
            dw.close()

    def _virtual_rect(self) -> Tuple[int, int, int, int]:
        """当前进程的虚拟桌面矩形；无效时回退 :data:`DEFAULT_VIRTUAL_RECT`。"""
        if not winapi.IS_WINDOWS:
            return DEFAULT_VIRTUAL_RECT
        x, y, w, h = winapi.virtual_screen_rect()
        if w <= 0 or h <= 0:
            return DEFAULT_VIRTUAL_RECT
        return (int(x), int(y), int(w), int(h))

    # -- 获取 ---------------------------------------------------------------

    def acquire(self, *, force: bool = False) -> WallpaperSource:
        """获取壁纸源画布（命中缓存时零成本返回）。

        Args:
            force: 忽略缓存强制重建。

        Returns:
            :class:`WallpaperSource`；任何情况下都返回有效画布（最差为单色）。
        """
        info = self.probe()
        signature = info.signature()
        cached = self._cached
        if not force and cached is not None and cached.signature == signature:
            return cached

        source = self._build(info, signature)
        self._cached = source
        _LOG.debug(
            "壁纸源重建：backend=%s meta=%s canvas=%dx%d scale=%.4f pos=%s monitors=%d",
            source.backend, info.source, source.size[0], source.size[1],
            source.scale, info.position, len(info.monitors),
        )
        return source

    def invalidate(self) -> None:
        """丢弃缓存，下次 :meth:`acquire` 必定重建。"""
        self._cached = None

    @property
    def cached(self) -> Optional[WallpaperSource]:
        """当前缓存的壁纸源（可能为 ``None``）。"""
        return self._cached

    def allow_dxgi(self) -> bool:
        """本实例是否允许使用 DXGI 后端。"""
        return dxgi_enabled() if self._allow_dxgi is None else bool(self._allow_dxgi)

    # -- 画布构建 -----------------------------------------------------------

    def _build(self, info: DesktopInfo, signature: str) -> WallpaperSource:
        """按降级链构建画布。

        Args:
            info: 桌面元数据。
            signature: 对应指纹。

        Returns:
            :class:`WallpaperSource`。
        """
        vx, vy, vw, vh = info.virtual_rect
        scale = _canvas_scale(vw, vh, self._canvas_max_long)
        canvas_w = max(1, int(round(vw * scale)))
        canvas_h = max(1, int(round(vh * scale)))

        canvas = self._build_from_files(info, canvas_w, canvas_h, scale)
        backend = BACKEND_WALLPAPER
        if canvas is None:
            canvas = self._build_from_capture(info, canvas_w, canvas_h)
            backend = canvas[1] if canvas is not None else BACKEND_SOLID
            canvas = canvas[0] if canvas is not None else None
        if canvas is None:
            canvas = np.full(
                (canvas_h, canvas_w, 3),
                np.array(self._solid_rgb(info), np.uint8),
                np.uint8,
            )
            backend = BACKEND_SOLID

        return WallpaperSource(
            pixels=canvas,
            origin=(int(vx), int(vy)),
            scale=scale,
            backend=backend,
            info=info,
            signature=signature,
        )

    def _solid_rgb(self, info: DesktopInfo) -> Tuple[int, int, int]:
        """纯色兜底应使用的颜色。

        区分两种语义完全不同的情况：

        * **用户确实设置了纯色桌面**（没有任何壁纸文件路径）—— 用桌面背景色，
          它的色度理应渗入 Mica；
        * **存在壁纸但采集全部失败** —— 此时我们对壁纸颜色一无所知，应退回中性
          基色，让结果收敛为纯净的 G1，而不是凭桌面背景色凭空造出一层色偏。

        Args:
            info: 桌面元数据。

        Returns:
            ``(r, g, b)``。
        """
        has_wallpaper = any(m.wallpaper_path for m in info.monitors)
        if not has_wallpaper and info.background_rgb:
            return info.background_rgb
        return self._fallback_rgb

    def _build_from_files(
        self, info: DesktopInfo, canvas_w: int, canvas_h: int, scale: float
    ) -> Optional[np.ndarray]:
        """解码壁纸文件并按放置方式合成整幅画布。

        Args:
            info: 桌面元数据。
            canvas_w: 画布宽度。
            canvas_h: 画布高度。
            scale: 画布像素 / 屏幕像素。

        Returns:
            画布数组；无任何可解码壁纸时返回 ``None``。
        """
        paths = [m.wallpaper_path for m in info.monitors if m.wallpaper_path]
        if not paths:
            return None

        background = np.array(info.background_rgb or self._fallback_rgb, np.uint8)
        canvas = np.full((canvas_h, canvas_w, 3), background, np.uint8)

        # Span：整个虚拟桌面视为一块画布做 Fill
        if info.position == "Span":
            decoded = decode_wallpaper(
                paths[0],
                int(canvas_w * DECODE_OVERSAMPLE),
                int(canvas_h * DECODE_OVERSAMPLE),
            )
            if decoded is None:
                return None
            return render_placement(
                decoded.pixels,
                canvas_w,
                canvas_h,
                scale,
                "Fill",
                info.background_rgb,
                decoded.native_size,
            )

        vx, vy = info.virtual_rect[0], info.virtual_rect[1]
        painted = False
        cache: Dict[Tuple[str, int, int], np.ndarray] = {}
        for mon in info.monitors:
            if not mon.wallpaper_path:
                continue
            # 显示器矩形 → 画布矩形（钳制到画布内）
            dx = int(round((mon.rect[0] - vx) * scale))
            dy = int(round((mon.rect[1] - vy) * scale))
            dw = max(1, int(round(mon.rect[2] * scale)))
            dh = max(1, int(round(mon.rect[3] * scale)))
            cx0, cy0 = max(0, dx), max(0, dy)
            cx1, cy1 = min(canvas_w, dx + dw), min(canvas_h, dy + dh)
            if cx1 <= cx0 or cy1 <= cy0:
                continue

            key = (mon.wallpaper_path, dw, dh)
            tile = cache.get(key)
            if tile is None:
                decoded = decode_wallpaper(
                    mon.wallpaper_path,
                    int(dw * DECODE_OVERSAMPLE),
                    int(dh * DECODE_OVERSAMPLE),
                )
                if decoded is None:
                    continue
                tile = render_placement(
                    decoded.pixels,
                    dw,
                    dh,
                    scale,
                    info.position,
                    info.background_rgb,
                    decoded.native_size,
                )
                cache[key] = tile

            canvas[cy0:cy1, cx0:cx1] = tile[cy0 - dy : cy1 - dy, cx0 - dx : cx1 - dx]
            painted = True

        return canvas if painted else None

    def _build_from_capture(
        self, info: DesktopInfo, canvas_w: int, canvas_h: int
    ) -> Optional[Tuple[np.ndarray, str]]:
        """抓屏兜底：DXGI（可选）→ GDI。

        Args:
            info: 桌面元数据。
            canvas_w: 画布宽度。
            canvas_h: 画布高度。

        Returns:
            ``(画布, 后端标识)``；全部失败返回 ``None``。
        """
        if not winapi.IS_WINDOWS:
            return None
        vx, vy, vw, vh = info.virtual_rect
        rect = (vx, vy, vw, vh)

        if self.allow_dxgi():
            try:
                data = winapi.capture_desktop_dxgi(rect, DXGI_TIMEOUT_MS)
            except (winapi.CaptureError, OSError, ValueError) as exc:
                _LOG.debug("DXGI 抓取失败：%s", exc)
                data = None
            rgb = _bgra_to_rgb(data, vw, vh) if data else None
            if rgb is not None:
                return (resample_u8(rgb, canvas_w, canvas_h), BACKEND_DXGI)

        try:
            data = winapi.capture_desktop_gdi(rect)
        except (winapi.CaptureError, OSError, ValueError) as exc:
            _LOG.debug("GDI 抓取失败：%s", exc)
            return None
        rgb = _bgra_to_rgb(data, vw, vh) if data else None
        if rgb is None:
            return None
        return (resample_u8(rgb, canvas_w, canvas_h), BACKEND_GDI)


__all__ = [
    "BACKEND_DXGI",
    "BACKEND_GDI",
    "BACKEND_SOLID",
    "BACKEND_WALLPAPER",
    "CANVAS_MAX_LONG",
    "DEFAULT_VIRTUAL_RECT",
    "DecodedWallpaper",
    "DesktopInfo",
    "ENV_DXGI",
    "MonitorInfo",
    "VALID_POSITIONS",
    "WallpaperProvider",
    "WallpaperSource",
    "decode_wallpaper",
    "dxgi_enabled",
    "render_placement",
]
