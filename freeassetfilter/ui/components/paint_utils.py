"""Shared paint utilities for custom-drawn Qt6 components.

Provides reusable drawing primitives — capsule, circle, checkmark,
rounded rect, chevron, and dashed line — so every component's
paintEvent uses consistent geometry, pen/brush setup, and antialiasing.
"""

from typing import Optional

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QBrush


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
