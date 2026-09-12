"""Shared paint utilities for custom-drawn Qt6 components.

Provides reusable drawing primitives — capsule, circle, checkmark,
rounded rect, chevron, and dashed line — so every component's
paintEvent uses consistent geometry, pen/brush setup, and antialiasing.

Also hosts :func:`render_soft_shadow`, the pre-baked replacement for
drop-shadow graphics effects: the shadow bitmap is blurred once with a
separable box kernel (numpy, triple pass ≈ gaussian), cached per size,
and composited per frame with a single ``drawPixmap`` — no offscreen
effect pipeline on the paint path.
"""

from functools import lru_cache
from typing import Optional

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QImage, QPixmap


def draw_capsule(
    painter: QPainter,
    rect: QRectF,
    color: QColor,
    *,
    border_color: Optional[QColor] = None,
    border_width: float = 1.0,
) -> None:
    """Draw a fully rounded capsule inside *rect*.

    The corner radius is ``min(width, height) / 2`` — the ends are
    perfectly rounded.  Optional outline on top of the fill.
    """
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    radius = min(rect.width(), rect.height()) / 2.0

    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(color))
    painter.drawRoundedRect(rect, radius, radius)

    if border_color is not None:
        painter.setPen(QPen(border_color, border_width))
        painter.setBrush(Qt.NoBrush)
        inset = rect.adjusted(border_width / 2, border_width / 2,
                              -border_width / 2, -border_width / 2)
        inner_r = max(0.0, radius - border_width / 2)
        painter.drawRoundedRect(inset, inner_r, inner_r)

    painter.restore()


def draw_circle(
    painter: QPainter,
    cx: float,
    cy: float,
    r: float,
    border_color: Optional[QColor] = None,
    fill_color: Optional[QColor] = None,
    *,
    border_width: float = 1.0,
) -> None:
    """Draw a circle centred at *(cx, cy)* with radius *r*.

    Both fill and border are optional.  Pass ``None`` for either
    to skip that layer.
    """
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)

    rect = QRectF(cx - r, cy - r, r * 2, r * 2)

    if fill_color is not None:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(fill_color))
        painter.drawEllipse(rect)
    else:
        painter.setBrush(Qt.NoBrush)

    if border_color is not None:
        painter.setPen(QPen(border_color, border_width))
        painter.drawEllipse(rect)

    painter.restore()


def draw_checkmark(
    painter: QPainter,
    rect: QRectF,
    color: QColor,
    *,
    scale: float = 1.0,
    pen_width: float = 2.0,
) -> None:
    """Draw a ✓ checkmark centred inside *rect*.

    A three-point polyline (checkmark shape) anchored to the
    bounding box.  *scale* is a uniform factor from the centre
    (e.g. for animation).
    """
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(color, pen_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

    cx = rect.center().x()
    cy = rect.center().y()
    margin = rect.width() * 0.125
    box_w = rect.width() - margin * 2

    x1 = rect.x() + margin + box_w * 0.80
    y1 = rect.y() + margin + box_w * 0.25
    x2 = rect.x() + margin + box_w * 0.33
    y2 = rect.y() + margin + box_w * 0.75
    x3 = rect.x() + margin + box_w * 0.15
    y3 = rect.y() + margin + box_w * 0.48

    def _sp(px: float, py: float) -> tuple[float, float]:
        return (cx + (px - cx) * scale, cy + (py - cy) * scale)

    x1, y1 = _sp(x1, y1)
    x2, y2 = _sp(x2, y2)
    x3, y3 = _sp(x3, y3)

    painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    painter.drawLine(QPointF(x2, y2), QPointF(x3, y3))

    painter.restore()


def draw_rounded_rect(
    painter: QPainter,
    rect: QRectF,
    radius: float,
    border: Optional[QColor] = None,
    fill: Optional[QColor] = None,
    *,
    border_width: float = 1.0,
) -> None:
    """Draw a rounded rectangle with optional border and fill.

    Border is drawn *inside* the bounding rect so the outer
    edge never exceeds *rect*.
    """
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)

    if fill is not None:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(fill))
        painter.drawRoundedRect(rect, radius, radius)
    else:
        painter.setBrush(Qt.NoBrush)

    if border is not None:
        painter.setPen(QPen(border, border_width))
        painter.setBrush(Qt.NoBrush)
        inset = rect.adjusted(border_width / 2, border_width / 2,
                              -border_width / 2, -border_width / 2)
        inner_r = max(0.0, radius - border_width / 2)
        painter.drawRoundedRect(inset, inner_r, inner_r)

    painter.restore()


def draw_chevron(
    painter: QPainter,
    rect: QRectF,
    color: QColor,
    direction: str = "right",
    *,
    pen_width: float = 1.8,
    t: float = 0.3,
) -> None:
    """Draw a chevron arrow (``>`` / ``v`` / ``<`` / ``^``) inside *rect*.

    ``t`` is the fraction of the half-size used for the arrow tip width;
    smaller values produce sharper arrows.
    """
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(color, pen_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)

    cx = rect.center().x()
    cy = rect.center().y()
    hs = min(rect.width(), rect.height()) / 2.0
    d = hs * t

    # Draw arrow based on direction
    if direction == "right":
        painter.drawLine(QPointF(cx - d, cy - hs), QPointF(cx + d, cy))
        painter.drawLine(QPointF(cx + d, cy), QPointF(cx - d, cy + hs))
    elif direction == "left":
        painter.drawLine(QPointF(cx + d, cy - hs), QPointF(cx - d, cy))
        painter.drawLine(QPointF(cx - d, cy), QPointF(cx + d, cy + hs))
    elif direction == "down":
        painter.drawLine(QPointF(cx - hs, cy - d), QPointF(cx, cy + d))
        painter.drawLine(QPointF(cx, cy + d), QPointF(cx + hs, cy - d))
    elif direction == "up":
        painter.drawLine(QPointF(cx - hs, cy + d), QPointF(cx, cy - d))
        painter.drawLine(QPointF(cx, cy - d), QPointF(cx + hs, cy + d))
    else:  # default to right
        painter.drawLine(QPointF(cx - d, cy - hs), QPointF(cx + d, cy))
        painter.drawLine(QPointF(cx + d, cy), QPointF(cx - d, cy + hs))

    painter.restore()


def draw_dashed_line(
    painter: QPainter,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    color: QColor,
    *,
    pen_width: float = 1.0,
    dash_pattern: Optional[list[float]] = None,
) -> None:
    """Draw a dashed line from *(x1, y1)* to *(x2, y2)*.

    Default dash pattern is ``[4.0, 4.0]`` (4 px dash, 4 px gap).
    Pass a custom *dash_pattern* to override.
    """
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)

    pen = QPen(color, pen_width, Qt.CustomDashLine)
    pen.setDashPattern(dash_pattern if dash_pattern is not None else [4.0, 4.0])
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    painter.restore()


def _box_blur_alpha(alpha: "object", radius: int) -> "object":
    """Separable box blur of a 2D float32 alpha plane, zero-padded edges.

    Args:
        alpha: 2D float array in [0, 1].
        radius: Box half-width in pixels (>= 1).

    Returns:
        Blurred 2D float array of the same shape.
    """
    import numpy as np

    data = np.asarray(alpha, dtype=np.float32)
    radius = max(1, int(radius))
    width = 2 * radius + 1
    out = data
    for _ in range(3):  # triple box ≈ gaussian
        # Horizontal pass: pad columns only (rows keep their size).
        padded = np.pad(out, ((0, 0), (radius, radius)), mode="constant")
        cumsum = np.cumsum(padded, axis=1, dtype=np.float64)
        # Leading zero so window sums align: out[i] = mean(padded[i:i+width]).
        cumsum = np.concatenate(
            [np.zeros((cumsum.shape[0], 1), dtype=np.float64), cumsum], axis=1
        )
        out = (cumsum[:, width:] - cumsum[:, :-width]) / width
        # Vertical pass: pad rows only.
        padded = np.pad(out, ((radius, radius), (0, 0)), mode="constant")
        cumsum = np.cumsum(padded, axis=0, dtype=np.float64)
        cumsum = np.concatenate(
            [np.zeros((1, cumsum.shape[1]), dtype=np.float64), cumsum], axis=0
        )
        out = (cumsum[width:, :] - cumsum[:-width, :]) / width
    assert out.shape == data.shape, (out.shape, data.shape)
    return out.astype(np.float32)


@lru_cache(maxsize=32)
def _cached_shadow_bitmap(
    content_w: int,
    content_h: int,
    radius_px: int,
    blur_px: int,
    color_rgba: tuple[int, int, int, int],
    pad: int,
) -> bytes:
    """Render and blur a rounded-rect alpha mask; cached by geometry.

    Args:
        content_w: Mask (content) width in pixels.
        content_h: Mask (content) height in pixels.
        radius_px: Corner radius of the mask in pixels.
        blur_px: Blur diameter in pixels (mirrors drop-shadow blur radius).
        color_rgba: Shadow tint as an (r, g, b, a) tuple.
        pad: Transparent padding around the mask in pixels.

    Returns:
        Raw BGRA bytes of the ``(content_w + 2*pad, content_h + 2*pad)``
        shadow bitmap.
    """
    import numpy as np

    full_w = content_w + pad * 2
    full_h = content_h + pad * 2
    mask = QImage(full_w, full_h, QImage.Format_ARGB32)
    mask.fill(Qt.transparent)
    painter = QPainter(mask)
    try:
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255))
        painter.drawRoundedRect(
            QRectF(pad, pad, content_w, content_h), radius_px, radius_px
        )
    finally:
        painter.end()

    ptr = mask.bits()
    plane = np.frombuffer(ptr, dtype=np.uint8).reshape(full_h, full_w, 4)
    alpha = plane[:, :, 3].astype(np.float32) / 255.0
    blurred = _box_blur_alpha(alpha, max(1, blur_px // 2))

    out = np.zeros((full_h, full_w, 4), dtype=np.uint8)
    out[:, :, 0] = color_rgba[2]
    out[:, :, 1] = color_rgba[1]
    out[:, :, 2] = color_rgba[0]
    out[:, :, 3] = np.clip(
        blurred * color_rgba[3], 0.0, 255.0
    ).astype(np.uint8)
    return out.tobytes()


def render_soft_shadow(
    content_w: int,
    content_h: int,
    radius_px: int,
    blur_px: int,
    color: QColor,
    pad: int,
) -> QPixmap:
    """Return a pre-baked soft-shadow pixmap for a rounded-rect content box.

    The caller draws it with a single ``drawPixmap`` at
    ``(content_x - pad + offset_x, content_y - pad + offset_y)`` inside its
    own paintEvent — no graphics effect involved. Results are cached per
    geometry so repeated frames cost one blit.

    Args:
        content_w: Content width the shadow belongs to.
        content_h: Content height the shadow belongs to.
        radius_px: Content corner radius.
        blur_px: Blur diameter (drop-shadow blur-radius equivalent).
        color: Shadow tint (alpha scales the falloff).
        pad: Transparent margin baked around the mask.

    Returns:
        QPixmap: ``(content_w + 2*pad, content_h + 2*pad)`` shadow bitmap;
        null pixmap when inputs are degenerate.
    """
    content_w = max(0, int(content_w))
    content_h = max(0, int(content_h))
    if content_w <= 0 or content_h <= 0 or pad <= 0:
        return QPixmap()
    full_w = content_w + pad * 2
    full_h = content_h + pad * 2
    raw = _cached_shadow_bitmap(
        content_w,
        content_h,
        max(0, int(radius_px)),
        max(1, int(blur_px)),
        (color.red(), color.green(), color.blue(), color.alpha()),
        int(pad),
    )
    image = QImage(
        raw, full_w, full_h, full_w * 4, QImage.Format_ARGB32
    )
    return QPixmap.fromImage(image.copy())
