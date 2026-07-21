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
from typing import Optional, Union

from PySide6.QtCore import Qt, QRect, QPoint, QTimer
from PySide6.QtGui import (
    QPixmap,
    QImage,
    QPainter,
    QColor,
    QPaintEvent,
    QResizeEvent,
    QMoveEvent,
)
from PySide6.QtWidgets import QWidget

from theme import tm

# ---------------------------------------------------------------------------
# Win32 API helpers
# ---------------------------------------------------------------------------
SPI_GETDESKWALLPAPER = 0x0073
MAX_PATH = 260

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32


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


def _apply_gaussian_blur(pixmap: QPixmap, radius: int = 30) -> QPixmap:
    """
    Apply Gaussian blur to a QPixmap (fallback path when the PIL-direct
    pipeline in MicaMaterial.refresh() is unavailable).

    Args:
        pixmap: Source pixmap
        radius: Gaussian blur radius (higher = more blur)

    Returns:
        Blurred QPixmap
    """
    if radius <= 0:
        return QPixmap(pixmap)

    # Pillow path: direct memory transfer, no PNG encode/decode
    try:
        from PIL import ImageFilter
        pil_img = _qimage_to_pil(pixmap.toImage())
        blurred = pil_img.filter(ImageFilter.GaussianBlur(radius=radius))
        qimg = _pil_to_qimage(blurred)
        return QPixmap.fromImage(qimg)
    except (ImportError, Exception):
        pass

    # Fallback: multi-pass pyramid blur (avoids banding from aggressive single-pass)
    w, h = pixmap.width(), pixmap.height()
    # Each pass uses a moderate factor; multiple passes accumulate blur smoothly
    per_pass_factor = max(2, min(8, radius // 10))
    passes = max(1, min(10, radius // (per_pass_factor * 3)))
    result = QPixmap(pixmap)
    for _ in range(passes):
        sw = max(1, w // per_pass_factor)
        sh = max(1, h // per_pass_factor)
        small = result.scaled(sw, sh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        result = small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return result


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


class MicaMaterial:
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
    ):
        """
        Args:
            widget: The widget to apply the Mica effect to.
            blur_radius: Gaussian blur radius (higher = more blur).
            tint_color: Overlay color. Hex string (e.g. "#202020A0") or QColor.
            luminosity: Brightness multiplier for the blurred image (0.0–1.0).
            contrast: Contrast multiplier. 1.0 = normal, 1.5 = +50%, 0.5 = -50%.
            saturation: Saturation multiplier. 1.0 = normal, 0.0 = grayscale.
        """
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

        # Init
        self.refresh()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """
        Reload wallpaper and rebuild the enhanced + blurred base, then bake.

        The heavy work (enhance + Gaussian blur) runs here and is cached in
        ``_blurred_base`` until the wallpaper path changes. Luminosity / tint /
        dither are applied cheaply on top in ``_bake()`` (see ``set_theme_tint``).
        """
        path = _get_wallpaper_path()
        if not path:
            self._blurred_base = None
            self._blurred_full = None
            return

        if path == self._wallpaper_path and self._blurred_base is not None:
            return  # Wallpaper unchanged; blurred base still valid

        self._wallpaper_path = path
        self._wallpaper_placement = _get_wallpaper_placement()
        self._virtual_rect = _get_virtual_desktop_rect()

        # Load wallpaper
        src = QPixmap(path)
        if src.isNull():
            self._blurred_base = None
            self._blurred_full = None
            return

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

            pil_img = _qimage_to_pil(src.toImage())
            if self._contrast != 1.0 or self._saturation != 1.0:
                pil_img = _enhance_pil_image(pil_img, self._contrast, self._saturation)
            pil_img = _apply_gaussian_blur_pil(pil_img, self._blur_radius)
            self._blurred_base = _pil_to_qimage(pil_img)

        except (ImportError, Exception):
            # Fallback: QPixmap-based enhance + blur
            if self._contrast != 1.0 or self._saturation != 1.0:
                src = self._enhance_pixmap(src)
            self._blurred_base = _apply_gaussian_blur(src, self._blur_radius).toImage()

        # Bake luminosity / tint / dither into the paint-ready pixmap
        self._bake()

    def invalidate_cache(self) -> None:
        """Mark cached pixmap as dirty – repaint will regenerate."""
        self._cached_pixmap = None

    def schedule_update(self) -> None:
        """Schedule a background repaint (debounced)."""
        self._schedule_update()

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

        window_geo = self._get_window_global_rect()

        if self._interacting:
            # Cheap path: one sub-rect blit with fast scaling. The source is
            # heavily blurred, so fast vs. smooth scaling is visually identical.
            painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
            self._blit(painter, rect, self._compute_source_rect(window_geo))
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

        painter.drawPixmap(rect, self._cached_pixmap)

    def _blit(self, painter: QPainter, target: QRect, src_rect: Optional[QRect]) -> None:
        """Draw the baked wallpaper (sub-rect to target) plus a light dither tile."""
        if src_rect is None:
            painter.drawPixmap(target, self._blurred_full)
        else:
            painter.drawPixmap(target, self._blurred_full, src_rect)
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
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self._blit(painter, rect, self._compute_source_rect(self._get_window_global_rect()))

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
        self._bake()
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

    def _bake(self) -> None:
        """
        Bake luminosity + tint + dithering into ``_blurred_full`` (once).

        The composite runs in the float domain so the final 8-bit quantization
        can be TPDF-dithered, which removes the color banding that a heavy blur
        plus saturation boost otherwise produces in 8-bit.
        """
        base = self._blurred_base
        if base is None:
            self._blurred_full = None
            return

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
            self._blurred_full = QPixmap.fromImage(_ndarray_to_qimage(arr.astype(np.uint8)))
        except (ImportError, Exception):
            self._blurred_full = self._bake_fallback(base)

        self._cached_pixmap = None
        self._schedule_update()

    def _bake_fallback(self, base: QImage) -> QPixmap:
        """QPainter-based bake used when numpy is unavailable. Runs once."""
        pm = QPixmap.fromImage(base)
        result = QPixmap(pm.size())
        result.fill(Qt.transparent)
        painter = QPainter(result)
        painter.drawPixmap(0, 0, pm)
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

    def _enhance_pixmap(self, pixmap: QPixmap) -> QPixmap:
        """Apply contrast and saturation to a QPixmap via PIL ImageEnhance."""
        try:
            from PIL import ImageEnhance
            pil_img = _qimage_to_pil(pixmap.toImage())
            if self._contrast != 1.0:
                pil_img = ImageEnhance.Contrast(pil_img).enhance(self._contrast)
            if self._saturation != 1.0:
                pil_img = ImageEnhance.Color(pil_img).enhance(self._saturation)
            return QPixmap.fromImage(_pil_to_qimage(pil_img))
        except (ImportError, Exception):
            return pixmap

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
