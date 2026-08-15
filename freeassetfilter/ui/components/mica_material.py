"""
Mica Material Effect for Windows

Simulates Windows 11 Mica by:
1. Reading the current desktop wallpaper via Win32 API
2. Applying Gaussian blur to the wallpaper
3. Cropping the blurred wallpaper based on window screen position
4. Painting the result as the window background

Supports multi-monitor setups and wallpaper change detection.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path
from typing import Optional, Union, Tuple

from PySide6.QtCore import Qt, QRect, QPoint, QTimer, QThread, QObject, Signal, QElapsedTimer, QEvent
from PySide6.QtGui import (
    QPixmap,
    QImage,
    QPainter,
    QColor,
    QPaintEvent,
    QResizeEvent,
    QMoveEvent,
)
from PySide6.QtWidgets import QWidget, QApplication

from theme import tm
from freeassetfilter.utils.app_logger import warning

# ---------------------------------------------------------------------------
# Win32 API helpers
# ---------------------------------------------------------------------------
SPI_GETDESKWALLPAPER = 0x0073
MAX_PATH = 260

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32

# ── 后台刷新（refresh_async）生命周期常量 ──────────────────────────────────
# 单次壁纸计算（读取+增强+高斯模糊+烘焙）的最长容忍时间；超时即强制 terminate，
# 防止线程卡死成野线程。
REFRESH_WATCHDOG_MS = 15000
# 后台刷新失败后的最大重试次数（共尝试 MAX_RETRIES+1 次）。超过即放弃，
# 走纯色兜底，绝不死循环重启拖垮 CPU。
REFRESH_MAX_RETRIES = 2
# 重试退避延迟基数（毫秒），第 N 次重试延迟 = REFRESH_RETRY_DELAY_MS * N。
REFRESH_RETRY_DELAY_MS = 500


def _get_wallpaper_path() -> str:
    """Retrieve the current desktop wallpaper file path via Win32 API."""
    buffer = ctypes.create_unicode_buffer(MAX_PATH)
    if user32.SystemParametersInfoW(SPI_GETDESKWALLPAPER, MAX_PATH, buffer, 0):
        path = buffer.value
        if path and Path(path).exists():
            return path
    # Fallback: try registry
    return _get_wallpaper_from_registry()


def _get_wallpaper_from_registry() -> str:
    """Fallback: read wallpaper path from registry."""
    import winreg
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Control Panel\Desktop",
        )
        value, _ = winreg.QueryValueEx(key, "WallPaper")
        winreg.CloseKey(key)
        if value and Path(value).exists():
            return value
    except OSError:
        pass
    return ""


# ---------------------------------------------------------------------------
# Gaussian blur implementations
# ---------------------------------------------------------------------------

def _qimage_to_pil(img: QImage):
    """
    Fast QImage → PIL Image conversion via direct memory access (no PNG encode).

    Args:
        img: Source QImage

    Returns:
        PIL Image in RGBA mode
    """
    from PIL import Image

    # Standard 8-bit RGBA processing
    img = img.convertToFormat(QImage.Format_RGBA8888)
    w, h = img.width(), img.height()
    ptr = img.constBits()

    # PySide6 returns memoryview; older sip returns sip.voidptr
    if isinstance(ptr, memoryview):
        return Image.frombytes("RGBA", (w, h), bytes(ptr))
    # sip.voidptr path
    try:
        addr = ptr.__int__()
    except (ValueError, TypeError, AttributeError):
        addr = ctypes.cast(ptr, ctypes.c_void_p).value or 0
    data = ctypes.string_at(addr, w * h * 4)
    return Image.frombytes("RGBA", (w, h), data)


def _pil_to_qimage(pil_img) -> QImage:
    """
    Fast PIL Image → QImage conversion (no PNG encode).

    Note: QPixmap on Windows is 8-bit per channel, so a 16-bit QImage would be
    downsampled immediately on QPixmap.fromImage(). We therefore always output
    8-bit here and reduce banding via a float composite + dithering pass in
    MicaMaterial._bake().

    Args:
        pil_img: Source PIL Image

    Returns:
        QImage in RGBA8888 format (8-bit)
    """
    w, h = pil_img.size

    # Ensure RGBA mode
    if pil_img.mode != "RGBA":
        pil_img = pil_img.convert("RGBA")

    data = pil_img.tobytes()
    qimg = QImage(data, w, h, w * 4, QImage.Format_RGBA8888)
    return qimg.copy()


def _qimage_to_ndarray(img: QImage):
    """
    QImage → numpy (h, w, 4) uint8 RGBA array via direct memory access.

    Accounts for the row stride (bytesPerLine) so it stays correct even when
    Qt pads scanlines.
    """
    import numpy as np

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
            addr = ctypes.cast(ptr, ctypes.c_void_p).value or 0
        buf = ctypes.string_at(addr, bpl * h)
    arr = np.frombuffer(buf, dtype=np.uint8)[: bpl * h].reshape(h, bpl)
    return arr[:, : w * 4].reshape(h, w, 4).copy()


def _ndarray_to_qimage(arr) -> QImage:
    """numpy (h, w, 4) uint8 RGBA array → QImage (RGBA8888, deep-copied)."""
    import numpy as np

    arr = np.ascontiguousarray(arr, dtype=np.uint8)
    h, w = arr.shape[0], arr.shape[1]
    qimg = QImage(arr.data, w, h, w * 4, QImage.Format_RGBA8888)
    return qimg.copy()


def _enhance_pil_image(pil_img, contrast: float = 1.0, saturation: float = 1.0):
    """
    Apply contrast and saturation enhancement to a PIL Image.

    PIL's ImageEnhance internally works with better precision during calculations,
    reducing color banding compared to direct pixel manipulation.

    Args:
        pil_img: PIL Image (any mode)
        contrast: Contrast multiplier (1.0 = normal, 1.5 = +50%)
        saturation: Saturation multiplier (1.0 = normal, 0.0 = grayscale)

    Returns:
        Enhanced PIL Image in RGBA mode
    """
    from PIL import ImageEnhance

    # Ensure RGBA for consistent processing
    if pil_img.mode != "RGBA":
        pil_img = pil_img.convert("RGBA")

    if contrast != 1.0:
        pil_img = ImageEnhance.Contrast(pil_img).enhance(contrast)
    if saturation != 1.0:
        pil_img = ImageEnhance.Color(pil_img).enhance(saturation)
    return pil_img


def _apply_gaussian_blur_pil(pil_img, radius: int = 30):
    """
    Apply Gaussian blur directly to a PIL Image (avoids conversion overhead).

    Args:
        pil_img: PIL Image (already converted)
        radius: Gaussian blur radius

    Returns:
        Blurred PIL Image
    """
    if radius <= 0:
        return pil_img

    from PIL import ImageFilter
    return pil_img.filter(ImageFilter.GaussianBlur(radius=radius))


# ---------------------------------------------------------------------------
# Monitor helpers
# ---------------------------------------------------------------------------

def _get_virtual_desktop_rect() -> QRect:
    """Get the bounding rectangle of the virtual desktop (all monitors)."""
    try:
        from PySide6.QtGui import QGuiApplication
        app = QGuiApplication.instance()
        if app:
            screen = app.primaryScreen()
            if screen:
                geo = screen.virtualGeometry()
                return QRect(geo.x(), geo.y(), geo.width(), geo.height())
    except Exception:
        pass

    # Fallback: Win32 API
    SM_XVIRTUALSCREEN = 76
    SM_YVIRTUALSCREEN = 77
    SM_CXVIRTUALSCREEN = 78
    SM_CYVIRTUALSCREEN = 79
    x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    w = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    h = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    return QRect(x, y, w, h)


def _get_wallpaper_placement() -> str:
    """Get wallpaper placement style (Tile, Center, Stretch, Fit, Fill, Span)."""
    import winreg
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Control Panel\Desktop",
        )
        value, _ = winreg.QueryValueEx(key, "WallpaperStyle")
        is_tiled, _ = winreg.QueryValueEx(key, "TileWallpaper")
        winreg.CloseKey(key)

        style = str(value)
        tiled = str(is_tiled) == "1"

        if tiled:
            return "Tile"
        return {
            "0": "Center",
            "2": "Stretch",
            "6": "Fit",
            "10": "Fill",
            "22": "Span",
        }.get(style, "Stretch")
    except OSError:
        return "Fill"


# ---------------------------------------------------------------------------
# MicaMaterial – the core class
# ---------------------------------------------------------------------------

def _parse_color(value: Union[str, QColor, None], fallback: QColor) -> QColor:
    """Parse a hex string or QColor, return QColor. Supports #RGB, #RGBA, #RRGGBB, #RRGGBBAA."""
    if value is None:
        return fallback
    if isinstance(value, QColor):
        return value
    if isinstance(value, str):
        s = value.lstrip("#")
        if len(s) == 3:
            r, g, b = int(s[0]*2, 16), int(s[1]*2, 16), int(s[2]*2, 16)
            return QColor(r, g, b)
        elif len(s) == 4:
            r, g, b = int(s[0]*2, 16), int(s[1]*2, 16), int(s[2]*2, 16)
            a = int(s[3]*2, 16)
            return QColor(r, g, b, a)
        elif len(s) == 6:
            return QColor("#" + s)
        elif len(s) == 8:
            r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
            a = int(s[6:8], 16)
            return QColor(r, g, b, a)
    return fallback


class _MicaRefreshWorker(QObject):
    """
    在独立 QThread 中执行 Mica 重型计算（壁纸读取+模糊+烘焙）的 worker。

    只产出 QImage（不创建 QPixmap），因此可在任意线程安全运行；结果通过
    信号回传主线程，由 MicaMaterial 在主线程完成 QPixmap 转换与重绘。
    """

    # (path, blurred_base_qimage, baked_full_qimage)
    finished = Signal(str, QImage, QImage)
    failed = Signal()

    def __init__(self, mica: "MicaMaterial") -> None:
        super().__init__()
        self._mica = mica

    def run(self) -> None:
        """执行后台计算；异常/空结果统一走 failed，绝不向外抛异常。"""
        try:
            path, base, full = self._mica._compute()
            if base is None or full is None:
                self.failed.emit()
                return
            self.finished.emit(path, base, full)
        except Exception:
            self.failed.emit()


class MicaMaterial(QObject):
    """
    Manages the Mica background effect for a window.

    Usage:
        mica = MicaMaterial(parent_widget, blur_radius=30, tint_color=QColor(32,32,32,140))
        # In your widget's paintEvent:
        mica.paint(widget, event)
        # Call mica.refresh() when wallpaper changes.
    """

    def __init__(
        self,
        widget: QWidget,
        blur_radius: int = 200,
        tint_color: Union[str, QColor, None] = "#202020B4",
        luminosity: float = 0.65,
        contrast: float = 1.5,
        saturation: float = 4.5,
        lazy: bool = False,
    ):
        """
        Args:
            widget: The widget to apply the Mica effect to.
            blur_radius: Gaussian blur radius (higher = more blur).
            tint_color: Overlay color. Hex string (e.g. "#202020A0") or QColor.
            luminosity: Brightness multiplier for the blurred image (0.0–1.0).
            contrast: Contrast multiplier. 1.0 = normal, 1.5 = +50%, 0.5 = -50%.
            saturation: Saturation multiplier. 1.0 = normal, 0.0 = grayscale.
            lazy: When True, defer the expensive wallpaper load + blur + bake
                until ``refresh()`` is called explicitly (e.g. from a QTimer
                after the window is shown). Until then the widget paints the
                solid theme surface fallback.
        """
        super().__init__()
        self._widget = widget
        self._blur_radius = blur_radius
        self._tint_color = _parse_color(tint_color, QColor(32, 32, 32, 160))
        self._luminosity = max(0.0, min(1.0, luminosity))
        self._contrast = max(0.0, contrast)
        self._saturation = max(0.0, saturation)

        # Pre-computed noise tile for dithering (breaks 8-bit gradient banding)
        self._noise_tile = self._make_noise_tile()

        # Cached state
        self._wallpaper_path: str = ""
        # Enhanced + blurred, pre-tint base (QImage). Rebuilt only when the
        # wallpaper changes — the expensive blur runs here exactly once.
        self._blurred_base: Optional[QImage] = None
        # Paint-ready pixmap with luminosity + tint + dither baked in.
        self._blurred_full: Optional[QPixmap] = None
        self._virtual_rect: QRect = QRect()
        self._wallpaper_placement: str = "Fill"
        self._cached_pixmap: Optional[QPixmap] = None
        self._last_window_geo: QRect = QRect()

        # Interaction state: during a window drag/resize we paint with fast
        # scaling and skip the settled cache to stay responsive.
        self._interacting: bool = False
        self._settle_timer = QTimer(widget)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(80)
        self._settle_timer.timeout.connect(self._on_settle)

        # Debounce timer for resize/move
        self._update_timer = QTimer(widget)
        self._update_timer.setSingleShot(True)
        self._update_timer.setInterval(50)
        self._update_timer.timeout.connect(self._do_update)

        # ── 后台刷新（refresh_async）生命周期状态 ──────────────────────────
        self._worker_thread = None          # 正在运行的后台 QThread（若有）
        self._worker = None                 # _MicaRefreshWorker 实例
        self._refresh_retries = 0           # 已失败重试次数
        self._pending_path = ""             # 本次刷新使用的壁纸路径（主线程赋值）
        self._refresh_outcome: Optional[str] = None  # "ok" | "fail" | "timeout"
        self._watchdog = QTimer(self._widget)  # 卡死看门狗（父对象须为 QObject）
        self._watchdog.setSingleShot(True)
        self._watchdog.setInterval(REFRESH_WATCHDOG_MS)
        self._watchdog.timeout.connect(self._on_refresh_timeout)

        # ── Mica 淡入/淡出（避免后台算完后“闪现”，以及失焦时平滑隐藏） ──────
        # _fade_alpha: Mica 当前绘制透明度（0.0→1.0）。paint() 先在实色兜底层
        # (tm.surface) 上铺满，再以此透明度叠加 Mica，形成 surface→Mica 的线性
        # 过渡——视觉上即“实色覆盖层透明度 100→0 渐变显露出 Mica”。
        self._fade_alpha = 1.0
        self._fade_from = 1.0        # 本次渐变起点透明度
        self._fade_to = 1.0          # 本次渐变目标透明度（0=隐藏，1=显示）
        self._fade_duration_ms = 175
        self._fade_clock = QElapsedTimer()
        self._fade_timer = QTimer(self._widget)
        self._fade_timer.setInterval(16)  # ~60fps
        self._fade_timer.timeout.connect(self._on_fade_tick)
        # 焦点/暂停状态：失焦时淡出并停止 Mica 绘制以省性能，回焦时淡入恢复。
        self._active = True           # 主窗口是否处于焦点
        self._paused = False          # 已淡出完成、停止绘制 Mica（仅画实色兜底）

        # 自动感知主窗口焦点：失焦→淡出并暂停绘制；回焦→淡入恢复。
        # 采用顶层窗口的 WindowActivate/WindowDeactivate 事件过滤器（而非对比
        # QApplication.focusWindowChanged 的窗口对象）——frameless 窗口的焦点窗口
        # 可能是内部包装对象，is 比较会误判为失焦，导致 Mica 被永久隐藏。
        top = self._widget.window()
        if top is not None:
            top.installEventFilter(self)

        # 失焦白名单：当焦点转移到「应用自身拉起的窗口」（设置窗口、style 弹窗、
        # 分离式全屏预览等）时，不视为失去焦点，效果层保持显示。判定依据是
        # QApplication.activeWindow() 在失焦后是否仍指向本应用内某个顶层窗口——
        # 只要仍非 None，说明焦点只是转移到应用内的窗口，保持激活；仅当为 None
        # （焦点真正离开整个应用）才隐藏并暂停绘制以省性能。
        self._focus_whitelist = set()  # 显式白名单窗口（弱引用），保留扩展能力
        self._deactivate_timer = QTimer(self._widget)
        self._deactivate_timer.setSingleShot(True)
        self._deactivate_timer.setInterval(60)  # 防抖：等待焦点切换的瞬态 None 回落
        self._deactivate_timer.timeout.connect(self._on_deactivate_check)

        # Init — lazy mode defers the heavy wallpaper load/blur/bake until an
        # explicit refresh() (see the `lazy` flag docstring).
        if not lazy:
            self.refresh()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """
        Reload wallpaper and rebuild the enhanced + blurred base, then bake.

        Synchronous (main-thread) path — used for manual refresh and as the
        fallback when the background thread cannot run. The heavy work (enhance
        + Gaussian blur) runs here and is cached in ``_blurred_base`` until the
        wallpaper path changes. Luminosity / tint / dither are baked on top via
        ``_bake_image()``.
        """
        old_present = self._blurred_full is not None
        path, base, full = self._compute()
        if base is None or full is None:
            self._blurred_base = None
            self._blurred_full = None
            return

        # Wallpaper unchanged; blurred base still valid (cache hit)
        if path == self._wallpaper_path and self._blurred_base is not None:
            return

        self._wallpaper_path = path
        self._wallpaper_placement = _get_wallpaper_placement()
        self._virtual_rect = _get_virtual_desktop_rect()
        self._blurred_base = base
        self._blurred_full = QPixmap.fromImage(full)
        # 窗口已可见且此前无 Mica（首次/重新出现）→ 淡入，避免唐突闪现
        if self._widget.isVisible() and not old_present:
            if self._active:
                self._start_fade_in(reset=True)
            else:
                self._hide_immediately()
        else:
            self._schedule_update()

    def _compute(self) -> Tuple[str, Optional[QImage], Optional[QImage]]:
        """
        Heavy, thread-safe computation of the Mica background.

        Runs on the calling thread (main thread for ``refresh()``, background
        thread for ``refresh_async()``). Produces **QImage only** — never a
        ``QPixmap`` — so it is safe to execute off the GUI thread.

        Returns:
            (wallpaper_path, blurred_base_qimage, baked_full_qimage). Any ``None``
            component signals failure (e.g. no wallpaper / load error).
        """
        path = _get_wallpaper_path()
        if not path:
            return ("", None, None)

        # QImage load is thread-safe (no native GUI handle), unlike QPixmap.
        src = QImage(path)
        if src.isNull():
            return ("", None, None)

        # Scale down for performance (blur on smaller image)
        max_dim = 1920
        if src.width() > max_dim or src.height() > max_dim:
            src = src.scaled(
                max_dim, max_dim, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )

        # Build the enhanced + blurred base. Enhancement BEFORE blur lets the
        # blur smooth the enhanced colors, reducing artifacts.
        try:
            from PIL import Image  # noqa: F401

            pil_img = _qimage_to_pil(src)
            if self._contrast != 1.0 or self._saturation != 1.0:
                pil_img = _enhance_pil_image(pil_img, self._contrast, self._saturation)
            pil_img = _apply_gaussian_blur_pil(pil_img, self._blur_radius)
            base = _pil_to_qimage(pil_img)
        except (ImportError, Exception):
            # PIL unavailable: QImage-based pyramid blur fallback (no QPixmap).
            base = self._blur_qimage_fallback(src)

        if base is None or base.isNull():
            return ("", None, None)

        # 将 base 作为参数传入，避免后台线程直接写 self._blurred_base（共享状态）
        full = self._bake_image(base)
        return (path, base, full)

    def _blur_qimage_fallback(self, src: QImage) -> QImage:
        """Thread-safe QImage-only blur used when PIL is unavailable."""
        w, h = src.width(), src.height()
        factor = max(2, self._blur_radius // 4)
        small = src.scaled(
            max(1, w // factor), max(1, h // factor),
            Qt.IgnoreAspectRatio, Qt.SmoothTransformation,
        )
        return small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

    # ------------------------------------------------------------------
    # Background refresh (refresh_async)
    # ------------------------------------------------------------------

    def refresh_async(self) -> None:
        """
        Refresh the Mica background on a background thread (non-blocking).

        The heavy wallpaper load + Gaussian blur + bake run in a ``QThread``;
        results are delivered back to the main thread via signals and applied
        without ever blocking the UI. Failures are retried with bounded backoff
        (see ``REFRESH_MAX_RETRIES``); repeated failures gracefully give up and
        leave the solid-color fallback in place.

        Safe to call from the main thread. No-op while a refresh is already in
        flight or after the retry budget is exhausted.
        """
        # 防重入：已有后台刷新在跑
        if self._worker_thread is not None:
            return
        # 已放弃（重试超限 / dispose）：不再重启，避免 CPU 空转
        if self._refresh_retries > REFRESH_MAX_RETRIES:
            return

        path = _get_wallpaper_path()
        if not path:
            return
        if path == self._wallpaper_path and self._blurred_base is not None:
            return  # 壁纸未变，缓存仍有效

        self._pending_path = path
        self._refresh_outcome = None
        self._worker = _MicaRefreshWorker(self)
        self._worker_thread = QThread()
        self._worker.moveToThread(self._worker_thread)
        # MicaMaterial 是主线程 QObject，因此以下连接自动以 Queued 方式在主线程派发，
        # 保证 _on_refresh_done/_failed/_cleanup_worker 均在主线程执行（避免单帧定时器
        # 被挂到后台线程而永不触发）。
        self._worker.finished.connect(self._on_refresh_done)
        self._worker.failed.connect(self._on_refresh_failed)
        self._worker_thread.finished.connect(self._cleanup_worker)
        self._worker_thread.started.connect(self._worker.run)
        self._watchdog.start(REFRESH_WATCHDOG_MS)
        self._worker_thread.start()

    def _on_refresh_done(self, path: str, base: QImage, full: QImage) -> None:
        """主线程槽：应用后台计算结果并触发线程回收。"""
        self._watchdog.stop()
        # 记录刷新前是否已在显示：首次就绪需从 0 揭示（淡入），已显示态的壁纸
        # 热替换则不重闪（原地更新）。
        was_shown = self._blurred_full is not None
        self._wallpaper_path = path
        self._wallpaper_placement = _get_wallpaper_placement()
        self._virtual_rect = _get_virtual_desktop_rect()
        self._blurred_base = base
        self._blurred_full = QPixmap.fromImage(full)
        self._refresh_retries = 0
        self._refresh_outcome = "ok"
        # 后台算完且已完全渲染：窗口处于焦点 → 首次出现从 0 淡入；失焦 → 直接隐藏，回焦再淡入
        if self._active:
            self._start_fade_in(reset=not was_shown)
        else:
            self._hide_immediately()
        # 停止 worker 线程事件循环，触发 finished → _cleanup_worker（异步、无阻塞）。
        if self._worker_thread is not None:
            self._worker_thread.quit()

    def _on_refresh_failed(self) -> None:
        """主线程槽：后台计算失败 → 标记结果，由 _cleanup_worker 按规则重试/放弃。"""
        self._watchdog.stop()
        self._refresh_retries += 1
        self._refresh_outcome = "fail"
        if self._worker_thread is not None:
            self._worker_thread.quit()

    def _on_refresh_timeout(self) -> None:
        """看门狗：计算超时（疑似卡死）→ 强制终止，避免野线程，交由回收逻辑重试/放弃。"""
        if self._worker_thread is None:
            return
        self._watchdog.stop()
        # 强制杀死卡死线程；terminate 后线程会发出 finished → _cleanup_worker。
        self._worker_thread.terminate()
        self._refresh_retries += 1
        self._refresh_outcome = "timeout"

    def _cleanup_worker(self) -> None:
        """
        彻底回收后台 worker 与线程（由 ``QThread.finished`` 异步触发，运行于主线程）。

        回收后根据本次刷新结果决定是否退避重试：成功则不重试；失败/超时则在预算内
        退避重启，超预算则放弃并回退纯色背景，杜绝 CPU 空转与野线程。
        """
        self._watchdog.stop()
        thread = self._worker_thread
        worker = self._worker
        self._worker_thread = None
        self._worker = None
        if thread is None:
            return

        outcome = self._refresh_outcome
        if outcome == "ok":
            # 成功：仅清理，无需重试
            pass
        elif self._refresh_retries <= REFRESH_MAX_RETRIES:
            # 退避重启：第 N 次重试延迟 = 基数 * N
            QTimer.singleShot(
                REFRESH_RETRY_DELAY_MS * self._refresh_retries, self.refresh_async
            )
        else:
            # 超过上限：放弃，回退纯色背景，不再重启
            self._blurred_base = None
            self._blurred_full = None
            warning("Mica 后台刷新多次失败，已放弃，回退纯色背景")

        if worker is not None:
            worker.deleteLater()
        thread.deleteLater()

    def dispose(self) -> None:
        """
        释放资源：标记放弃并强制回收任何在途的后台刷新线程。

        应在窗口关闭 / 应用退出时调用，确保无残留线程（野进程）。
        """
        # 标记放弃，阻止任何挂起的重试重启
        self._refresh_retries = REFRESH_MAX_RETRIES + 1
        self._refresh_outcome = "fail"
        # 移除焦点感知事件过滤器，停止任何渐变与绘制
        top = self._widget.window()
        if top is not None:
            try:
                top.removeEventFilter(self)
            except (TypeError, RuntimeError):
                pass
        self._active = False
        self._paused = True
        self._stop_fade()
        self._update_timer.stop()
        self._settle_timer.stop()
        if self._deactivate_timer.isActive():
            self._deactivate_timer.stop()
        if self._watchdog.isActive():
            self._watchdog.stop()
        if self._worker_thread is not None:
            thread = self._worker_thread
            worker = self._worker
            self._worker_thread = None
            self._worker = None
            # 非阻塞回收：请求退出并安排删除；若线程卡死则强制终止。
            thread.quit()
            if not thread.wait(0) and not thread.isFinished():
                thread.terminate()
            if worker is not None:
                worker.deleteLater()
            thread.deleteLater()

    def invalidate_cache(self) -> None:
        """Mark cached pixmap as dirty – repaint will regenerate."""
        self._cached_pixmap = None

    def schedule_update(self) -> None:
        """Schedule a background repaint (debounced)."""
        self._schedule_update()

    def _start_fade_in(self, reset: bool = False) -> None:
        """Mica 叠加层线性淡入（由当前透明度 → 1.0）。

        reset=True 时强制从完全隐藏（透明度 0）揭示，用于「首次渲染完成」与
        「重新获得焦点」这类本就该从隐藏态显现的场景；已显示态下的刷新（如壁纸
        热替换）不重闪，保持当前透明度原地更新。
        """
        if reset:
            self._fade_alpha = 0.0
        self._start_fade_to(1.0)

    def _start_fade_out(self) -> None:
        """Mica 叠加层线性淡出（由当前透明度 → 0.0）。用于失去焦点隐藏。"""
        self._start_fade_to(0.0)

    def _start_fade_to(self, target: float) -> None:
        """
        启动 Mica 透明度的线性渐变（target ∈ [0,1]）：0=实色覆盖完全透出（隐藏
        Mica），1=完整显示 Mica。渐变期间持续重绘，淡出完成且仍处于失焦时停止绘制
        以省性能。
        """
        target = max(0.0, min(1.0, target))
        # 任何渐变都意味着需要绘制 Mica，取消暂停态
        self._paused = False
        self._fade_from = self._fade_alpha
        self._fade_to = target
        self._fade_clock.start()
        if not self._fade_timer.isActive():
            self._fade_timer.start()
        self._widget.update()

    def _on_fade_tick(self) -> None:
        """渐变逐帧推进：线性插值 _fade_alpha，到达目标时停表。"""
        if not self._fade_clock.isValid():
            self._fade_alpha = self._fade_to
            self._fade_timer.stop()
            self._widget.update()
            return
        t = self._fade_clock.elapsed() / self._fade_duration_ms
        if t >= 1.0:
            self._fade_alpha = self._fade_to
            self._fade_timer.stop()
            # 淡出完成且仍失焦 → 暂停绘制，彻底停止 Mica 渲染开销
            if self._fade_to == 0.0 and not self._active:
                self._paused = True
                self._update_timer.stop()
                self._settle_timer.stop()
        else:
            self._fade_alpha = self._fade_from + (self._fade_to - self._fade_from) * t
        # 直接请求重绘（绕过 debounce），保证渐变帧率平滑
        self._widget.update()

    def _stop_fade(self) -> None:
        """立即结束渐变并复位为完整显示（如资源回收/主题重置时）。"""
        self._fade_alpha = 1.0
        self._fade_to = 1.0
        if self._fade_timer.isActive():
            self._fade_timer.stop()

    def _hide_immediately(self) -> None:
        """失焦且 Mica 才就绪时：直接隐藏并停止绘制，不进行淡入动画。"""
        self._paused = True
        self._fade_alpha = 0.0
        self._fade_to = 0.0
        self._update_timer.stop()
        self._settle_timer.stop()

    def set_active(self, active: bool) -> None:
        """
        设置主窗口焦点状态：失焦时淡出隐藏并停止绘制，回焦时淡入恢复。

        由顶层窗口的 ``WindowActivate``/``WindowDeactivate`` 事件过滤器自动调用，
        亦可由外部显式调用（如窗口最小化/隐藏时）。
        """
        if active == self._active:
            return
        self._active = active
        if active:
            self._start_fade_in()      # 回焦：淡入恢复
        else:
            self._start_fade_out()     # 失焦：淡出隐藏

    def eventFilter(self, obj, event) -> bool:
        """顶层窗口激活/失焦事件：驱动 Mica 的淡入恢复 / 淡出隐藏。"""
        top = self._widget.window()
        if obj is top:
            etype = event.type()
            if etype == QEvent.Type.WindowActivate:
                # 回焦：取消任何待定的失焦判定，立即淡入恢复
                if self._deactivate_timer.isActive():
                    self._deactivate_timer.stop()
                self.set_active(True)
            elif etype == QEvent.Type.WindowDeactivate:
                # 失焦：不立即判定，交由防抖复查——若焦点只是转移到应用内的窗口
                # （设置/style 弹窗/分离全屏预览等白名单窗口），应保持效果层显示
                if not self._deactivate_timer.isActive():
                    self._deactivate_timer.start()
        return False

    def add_focus_whitelist(self, window: QWidget) -> None:
        """
        将「应用自身拉起的窗口」登记为失焦白名单（弱引用，不影响其生命周期）。

        失焦时若焦点转移到白名单窗口，效果层不隐藏。常见登记对象：设置窗口、
        style 弹窗、分离式全屏预览宿主。注：本应用内任意顶层窗口默认即纳入白名单
        语义（见 ``_on_deactivate_check``），此处 API 主要供将来排除特定窗口使用。
        """
        try:
            import weakref
            self._focus_whitelist.add(weakref.ref(window))
        except TypeError:
            pass

    def remove_focus_whitelist(self, window: QWidget) -> None:
        """从失焦白名单移除指定窗口。"""
        self._focus_whitelist = {
            w for w in self._focus_whitelist if w() is not None and w() is not window
        }

    def _is_in_focus_whitelist(self, window: QWidget) -> bool:
        """判断窗口是否落在失焦白名单（含其作为主窗口子对话框的父链归属）。"""
        if window is None:
            return False
        if window in self._focus_whitelist:
            return True
        # 父链归属于主窗口的子对话框（设置窗口、style 弹窗等）同样视为白名单
        top = self._widget.window()
        p = window.parent()
        while p is not None:
            if p is top:
                return True
            p = p.parent()
        return False

    def _on_deactivate_check(self) -> None:
        """
        失焦防抖复查：决定是否真正隐藏效果层。

        仅当 ``QApplication.activeWindow()`` 为 None（焦点真正离开整个应用）才
        失焦隐藏并暂停绘制；若活动窗口仍属本应用——无论是显式白名单窗口、主窗口
        的子对话框，还是分离式全屏预览宿主——均视为「仍处于应用内」，保持效果层
        显示。
        """
        active = QApplication.activeWindow()
        if active is None:
            self.set_active(False)
        elif not self._is_in_focus_whitelist(active):
            # 焦点仍在应用内但不在白名单（极少见）——仍属自身拉起窗口，保持激活
            self.set_active(True)

    def paint(self, painter: Optional[QPainter] = None, event: Optional[QPaintEvent] = None) -> None:
        """
        Paint the Mica background onto the widget.

        During an active drag/resize we blit the baked wallpaper directly with
        fast scaling; when settled we cache the window-sized composite so idle
        repaints are a single cheap ``drawPixmap``.
        """
        widget = self._widget
        if painter is None:
            painter = QPainter(widget)

        rect = widget.rect()

        if self._blurred_full is None or self._blurred_full.isNull():
            # No wallpaper – paint solid fallback
            painter.fillRect(rect, tm.surface)
            return

        # 失焦且已淡出完成（暂停）：仅画实色兜底，不做任何 Mica 绘制，省去渲染开销
        if self._paused:
            painter.fillRect(rect, tm.surface)
            return

        # 先铺实色兜底层，再以 _fade_alpha 叠加 Mica，形成 surface→Mica 的线性渐变
        # （淡入期间实色覆盖透明度 100→0，避免算完后“闪现”）。
        painter.fillRect(rect, tm.surface)

        window_geo = self._get_window_global_rect()

        if self._interacting:
            # Cheap path: one sub-rect blit with fast scaling. The source is
            # heavily blurred, so fast vs. smooth scaling is visually identical.
            # 交互期间跳过 dither 平铺（拖拽时人眼注意不到），省去大窗口下
            # 每帧 drawTiledPixmap 的全屏平铺开销。
            painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
            self._blit(painter, rect, self._compute_source_rect(window_geo), dither=False)
            self._last_window_geo = window_geo
            return

        # Settled path: (re)build the window-sized composite when geometry or
        # size changed, then draw the cached result.
        if (
            self._cached_pixmap is None
            or self._cached_pixmap.isNull()
            or window_geo != self._last_window_geo
            or self._cached_pixmap.size() != widget.size()
        ):
            src_rect = self._compute_source_rect(window_geo)
            self._cached_pixmap = self._make_settled_cache(widget.size(), src_rect)
            self._last_window_geo = window_geo

        painter.setOpacity(self._fade_alpha)
        painter.drawPixmap(rect, self._cached_pixmap)
        painter.setOpacity(1.0)

    def _blit(self, painter: QPainter, target: QRect, src_rect: Optional[QRect], dither: bool = True) -> None:
        """Draw the baked wallpaper (sub-rect to target) plus a light dither tile."""
        if src_rect is None:
            painter.drawPixmap(target, self._blurred_full)
        else:
            painter.drawPixmap(target, self._blurred_full, src_rect)
        if not dither:
            return
        # Light residual dither at final resolution (cheap tiled blit)
        painter.setOpacity(0.04)
        painter.drawTiledPixmap(target, self._noise_tile)
        painter.setOpacity(1.0)

    def paint_gpu(self, painter: QPainter) -> None:
        """
        Paint the Mica background via a GPU-backed painter (QOpenGLWidget).

        Unlike ``paint()``, this always renders the full-quality composite (no
        interaction downgrade, no per-window cache): on the OpenGL paint engine
        the baked wallpaper is uploaded once as a cached texture, so each frame
        is a single textured-quad blit whose cost is independent of window size.
        This keeps dragging smooth even when maximized or spanning monitors.
        """
        rect = self._widget.rect()
        if self._blurred_full is None or self._blurred_full.isNull():
            painter.fillRect(rect, tm.surface)
            return
        # 失焦暂停：仅画实色兜底
        if self._paused:
            painter.fillRect(rect, tm.surface)
            return
        # 实色兜底层 + 线性淡入（与 paint() 一致）
        painter.fillRect(rect, tm.surface)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setOpacity(self._fade_alpha)
        self._blit(painter, rect, self._compute_source_rect(self._get_window_global_rect()))
        painter.setOpacity(1.0)

    def paint_event(self, event: QPaintEvent) -> None:
        """Convenience: handle a QPaintEvent directly."""
        painter = QPainter(self._widget)
        self.paint(painter, event)
        painter.end()

    def set_theme_tint(self, tint_color: Union[str, QColor, None], luminosity: float) -> None:
        """
        Re-bake tint + luminosity without re-blurring (fast; for theme changes).

        Reuses the cached ``_blurred_base`` so the expensive Gaussian blur is
        not repeated.
        """
        self._tint_color = _parse_color(tint_color, self._tint_color)
        self._luminosity = max(0.0, min(1.0, luminosity))
        full = self._bake_image()
        if full is not None:
            self._blurred_full = QPixmap.fromImage(full)
        self._cached_pixmap = None
        self._widget.update()

    def begin_interaction(self) -> None:
        """
        Mark the start (or continuation) of a window drag/resize.

        Switches painting to the cheap fast-scaling path and (re)starts the
        settle timer; when motion stops, ``_on_settle`` restores the crisp
        cached path.
        """
        self._interacting = True
        self._cached_pixmap = None
        self._settle_timer.start()  # restart on every event
        self._widget.update()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _schedule_update(self) -> None:
        """Request widget repaint (debounced)."""
        if not self._update_timer.isActive():
            self._update_timer.start()

    def _do_update(self) -> None:
        """Perform the actual update."""
        self._cached_pixmap = None
        self._widget.update()

    def _on_settle(self) -> None:
        """Interaction ended: drop the cache so the next paint rebuilds a crisp one."""
        self._interacting = False
        self._cached_pixmap = None
        self._widget.update()

    def _bake_image(self, base: Optional[QImage] = None) -> Optional[QImage]:
        """
        Bake luminosity + tint + dithering into a QImage (thread-safe, no QPixmap).

        The composite runs in the float domain so the final 8-bit quantization
        can be TPDF-dithered, which removes the color banding that a heavy blur
        plus saturation boost otherwise produces in 8-bit.

        Args:
            base: Source blurred base (QImage). If omitted, uses ``self._blurred_base``
                (main-thread callers). Passing it explicitly keeps the background
                worker from writing shared state.

        Returns:
            The baked full background as a QImage, or ``None`` if no base exists.
            Callers convert to ``QPixmap`` on the main thread before painting.
        """
        if base is None:
            base = self._blurred_base
        if base is None:
            return None

        try:
            import numpy as np

            arr = _qimage_to_ndarray(base).astype(np.float32)  # (h, w, 4)
            rgb = arr[:, :, :3]

            # Luminosity: darken (compositing black at alpha=(1-lum) == * lum)
            lum = self._luminosity
            if lum < 1.0:
                rgb *= lum

            # Tint overlay: rgb = rgb*(1 - a_t) + tint_rgb * a_t
            a_t = self._tint_color.alpha() / 255.0
            if a_t > 0.0:
                tint_rgb = np.array(
                    [self._tint_color.red(), self._tint_color.green(),
                     self._tint_color.blue()],
                    dtype=np.float32,
                )
                rgb *= (1.0 - a_t)
                rgb += tint_rgb * a_t

            # TPDF dither: triangular noise in [-1, 1] per pixel (~ +/-1 LSB),
            # deterministic so the baked image is stable across repaints.
            rng = np.random.default_rng(42)
            h, w = rgb.shape[0], rgb.shape[1]
            noise = (
                rng.random((h, w, 1), dtype=np.float32)
                - rng.random((h, w, 1), dtype=np.float32)
            )
            rgb += noise

            arr[:, :, :3] = np.clip(np.rint(rgb), 0.0, 255.0)
            arr[:, :, 3] = 255.0  # fully opaque
            return _ndarray_to_qimage(arr.astype(np.uint8))
        except (ImportError, Exception):
            return self._bake_fallback(base)

    def _bake_fallback(self, base: QImage) -> QImage:
        """QPainter-based bake used when numpy is unavailable. Returns a QImage."""
        result = QImage(base.size(), QImage.Format_RGBA8888)
        result.fill(Qt.transparent)
        painter = QPainter(result)
        painter.drawImage(0, 0, base)
        if self._luminosity < 1.0:
            dark_alpha = int((1.0 - self._luminosity) * 255)
            if dark_alpha > 0:
                painter.fillRect(result.rect(), QColor(0, 0, 0, dark_alpha))
        if self._tint_color.alpha() > 0:
            painter.fillRect(result.rect(), self._tint_color)
        painter.setOpacity(0.04)
        painter.drawTiledPixmap(result.rect(), self._noise_tile)
        painter.setOpacity(1.0)
        painter.end()
        return result

    def _make_settled_cache(self, size, src_rect: Optional[QRect]) -> QPixmap:
        """Render the window-sized composite (smooth scaled) for idle repaints."""
        pm = QPixmap(size)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self._blit(painter, QRect(0, 0, size.width(), size.height()), src_rect)
        painter.end()
        return pm

    def _get_window_global_rect(self) -> QRect:
        """Get the window's geometry in global (screen) coordinates."""
        widget = self._widget
        # Walk up to the top-level window
        w = widget.window()
        geo = w.geometry()
        # mapToGlobal gives us the top-left in screen coords
        top_left = w.mapToGlobal(QPoint(0, 0))
        return QRect(top_left.x(), top_left.y(), geo.width(), geo.height())

    def _compute_source_rect(self, window_geo: QRect) -> Optional[QRect]:
        """
        Compute the source sub-rect of ``_blurred_full`` for the current window
        position (via wallpaper placement math). Returns None when the whole
        blurred image should simply be stretched instead.
        """
        if self._blurred_full is None:
            return None

        widget_size = self._widget.size()
        if widget_size.width() <= 0 or widget_size.height() <= 0:
            return None

        pw, ph = self._blurred_full.width(), self._blurred_full.height()
        virtual = self._virtual_rect
        vx, vy, vw, vh = virtual.x(), virtual.y(), virtual.width(), virtual.height()

        if vw <= 0 or vh <= 0:
            return None  # No virtual-desktop info; caller stretches whole image

        # Window position relative to virtual desktop origin
        wx = window_geo.x() - vx
        wy = window_geo.y() - vy
        ww = window_geo.width()
        wh = window_geo.height()

        src = self._placement_source_rect(pw, ph, vw, vh, wx, wy, ww, wh)
        if src is None:
            return None

        sx, sy, sw, sh = src
        # Clamp and validate
        sx = max(0, min(int(sx), pw - 1))
        sy = max(0, min(int(sy), ph - 1))
        sw = max(1, min(int(sw), pw - sx))
        sh = max(1, min(int(sh), ph - sy))
        return QRect(sx, sy, sw, sh)

    def _placement_source_rect(
        self, pw: int, ph: int, vw: int, vh: int,
        wx: int, wy: int, ww: int, wh: int,
    ) -> Optional[tuple]:
        """
        Compute (x, y, w, h) in wallpaper pixel coordinates for the window
        at (wx, wy, ww, wh) on the virtual desktop.
        Returns None if the placement style is unsupported for direct math.
        """
        placement = self._wallpaper_placement

        if placement == "Fill":
            # Scale to fill, center-crop
            scale = max(vw / pw, vh / ph)
            fill_w = pw * scale
            fill_h = ph * scale
            offset_x = (vw - fill_w) / 2.0
            offset_y = (vh - fill_h) / 2.0
            return (
                (wx - offset_x) / scale,
                (wy - offset_y) / scale,
                ww / scale,
                wh / scale,
            )

        elif placement == "Fit":
            scale = min(vw / pw, vh / ph)
            fit_w = pw * scale
            fit_h = ph * scale
            offset_x = (vw - fit_w) / 2.0
            offset_y = (vh - fit_h) / 2.0
            return (
                (wx - offset_x) / scale,
                (wy - offset_y) / scale,
                ww / scale,
                wh / scale,
            )

        elif placement in ("Stretch", "Span"):
            scale_x = vw / pw
            scale_y = vh / ph
            return (
                wx / scale_x,
                wy / scale_y,
                ww / scale_x,
                wh / scale_y,
            )

        elif placement == "Center":
            offset_x = (vw - pw) / 2.0
            offset_y = (vh - ph) / 2.0
            return (
                wx - offset_x,
                wy - offset_y,
                ww,
                wh,
            )

        elif placement == "Tile":
            # Modulo into the tiled grid — works for single-tile overlap
            # (if window spans tile boundaries, we still get a reasonable result)
            return (
                wx % pw,
                wy % ph,
                min(ww, pw),
                min(wh, ph),
            )

        return None

    @staticmethod
    def _make_noise_tile(size: int = 64) -> QPixmap:
        """Create a small noise tile with sparse random dots for dithering."""
        import random
        tile = QPixmap(size, size)
        tile.fill(Qt.transparent)
        p = QPainter(tile)
        p.setPen(Qt.NoPen)
        rng = random.Random(42)  # fixed seed for consistency
        for _ in range(size * 3):
            x = rng.randint(0, size - 1)
            y = rng.randint(0, size - 1)
            v = rng.randint(0, 255)
            p.setBrush(QColor(v, v, v, 20))
            p.drawRect(x, y, 2, 2)
        p.end()
        return tile


# ---------------------------------------------------------------------------
# MicaWindow – a convenience base widget with Mica built in
# ---------------------------------------------------------------------------

class MicaWidget(QWidget):
    """
    A QWidget subclass that automatically paints a Mica background.

    Simply use MicaWidget instead of QWidget where you want the Mica effect.
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        blur_radius: int = 200,
        tint_color: Union[str, QColor, None] = "#202020B4",
        luminosity: float = 0.65,
        contrast: float = 1.5,
        saturation: float = 4.5,
    ):
        super().__init__(parent)
        self._mica = MicaMaterial(self, blur_radius, tint_color, luminosity, contrast, saturation)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.setAttribute(Qt.WA_TranslucentBackground, False)

    @property
    def mica(self) -> MicaMaterial:
        return self._mica

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        self._mica.paint(painter, event)
        painter.end()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._mica.begin_interaction()

    def moveEvent(self, event: QMoveEvent) -> None:
        super().moveEvent(event)
        self._mica.begin_interaction()
