# allow: SIZE_OK — pure-data-table: 365+ lines are icon path coordinate data,
# only ~80 lines are actual code/logic.

"""Shared icon rendering utility using QPainterPath primitives.

Provides a 24x24 normalized viewBox icon system for all D-Fronted components.
Every icon is defined as a list of SVG-like drawing commands stored in
ICON_PATHS. The icon_path() function builds and caches QPainterPath objects
from those commands; render_icon() paints them into an arbitrary QRectF.

Usage:
    path = icon_path("chevron_right")
    render_icon(painter, "checkmark", rect, QColor("#07c160"))
"""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QColor, QPen

# ---------------------------------------------------------------------------
# Icon command reference
# ---------------------------------------------------------------------------
# Each icon is a list of tuples.  The first element of each tuple is a
# single-character command; the remaining elements are its parameters.
#
#   'M'  x y               — moveTo
#   'L'  x y               — lineTo
#   'C'  x1 y1 x2 y2 x y   — cubicTo (bezier)
#   'Q'  cx cy x y          — quadTo
#   'Z'                     — closeSubpath
#   'circle'  cx cy r       — addEllipse
#   'rect'  x y w h radius  — addRoundedRect
#
# All coordinates are in a 24x24 viewBox with (0,0) at top-left.

ICON_PATHS: dict[str, list[tuple]] = {
    # ── Chevrons ────────────────────────────────────────────────────────
    "chevron_right": [
        ("M", 8, 6),
        ("L", 16, 12),
        ("L", 8, 18),
    ],
    "chevron_down": [
        ("M", 6, 8),
        ("L", 12, 16),
        ("L", 18, 8),
    ],
    "chevron_left": [
        ("M", 16, 6),
        ("L", 8, 12),
        ("L", 16, 18),
    ],
    # ── Basic UI ────────────────────────────────────────────────────────
    "checkmark": [
        ("M", 5, 13),
        ("L", 10, 18),
        ("L", 19, 7),
    ],
    "close": [
        ("M", 6, 6),
        ("L", 18, 18),
        ("M", 18, 6),
        ("L", 6, 18),
    ],
    "plus": [
        ("M", 12, 4),
        ("L", 12, 20),
        ("M", 4, 12),
        ("L", 20, 12),
    ],
    "minus": [
        ("M", 4, 12),
        ("L", 20, 12),
    ],
    # ── Common objects ──────────────────────────────────────────────────
    "folder": [
        ("M", 4, 7),
        ("L", 10, 7),
        ("L", 12, 10),
        ("L", 20, 10),
        ("L", 20, 19),
        ("L", 4, 19),
        ("Z",),
    ],
    "folder_open": [
        ("M", 4, 8),
        ("L", 10, 8),
        ("L", 12, 11),
        ("L", 20, 11),
        ("L", 18.5, 18),
        ("L", 5.5, 18),
        ("Z",),
        ("M", 4, 8),
        ("L", 4, 6),
        ("L", 10, 6),
        ("L", 12, 8),
    ],
    # ── Actions ─────────────────────────────────────────────────────────
    "search": [
        ("circle", 10, 10, 6),
        ("M", 14.5, 14.5),
        ("L", 21, 21),
    ],
    "bell": [
        ("M", 12, 3),
        ("L", 6, 9),
        ("L", 8, 18),
        ("L", 16, 18),
        ("L", 18, 9),
        ("L", 12, 3),
        ("M", 13.5, 21),
        ("L", 10.5, 21),
    ],
    "user": [
        ("circle", 12, 8, 4),
        ("M", 6, 22),
        ("L", 8, 16),
        ("L", 16, 16),
        ("L", 18, 22),
    ],
    "gear": [
        ("circle", 12, 12, 3.5),
        # 8 gear teeth radiating outward
        ("M", 12, 2.5),
        ("L", 12, 5),
        ("M", 19, 5.5),
        ("L", 17.5, 7.5),
        ("M", 21.5, 12),
        ("L", 19, 12),
        ("M", 19, 18.5),
        ("L", 17.5, 16.5),
        ("M", 12, 21.5),
        ("L", 12, 19),
        ("M", 5, 18.5),
        ("L", 6.5, 16.5),
        ("M", 2.5, 12),
        ("L", 5, 12),
        ("M", 5, 5.5),
        ("L", 6.5, 7.5),
    ],
    # ── Status ──────────────────────────────────────────────────────────
    "info": [
        ("circle", 12, 12, 10),
        ("M", 12, 16),
        ("L", 12, 10),
        ("M", 12, 7.5),
        ("L", 12, 7),
    ],
    "warning": [
        ("M", 12, 3),
        ("L", 22, 20),
        ("L", 2, 20),
        ("Z",),
        ("M", 12, 15),
        ("L", 12, 10),
        ("M", 12, 18),
        ("L", 12, 17.5),
    ],
    "error": [
        ("circle", 12, 12, 10),
        ("M", 8, 8),
        ("L", 16, 16),
        ("M", 16, 8),
        ("L", 8, 16),
    ],
    # ── Favorites ───────────────────────────────────────────────────────
    "heart": [
        ("M", 12, 20.5),
        ("C", 12, 20.5, 4, 14, 4, 8.5),
        ("C", 4, 5.5, 6.5, 3.5, 9, 5.5),
        ("C", 10.5, 7, 12, 9, 12, 9),
        ("C", 12, 9, 13.5, 7, 15, 5.5),
        ("C", 17.5, 3.5, 20, 5.5, 20, 8.5),
        ("C", 20, 14, 12, 20.5, 12, 20.5),
        ("Z",),
    ],
    "star": [
        ("M", 12, 2.5),
        ("L", 14.8, 9.2),
        ("L", 22, 9.5),
        ("L", 16.5, 14.5),
        ("L", 18.5, 22),
        ("L", 12, 17.5),
        ("L", 5.5, 22),
        ("L", 7.5, 14.5),
        ("L", 2, 9.5),
        ("L", 9.2, 9.2),
        ("Z",),
    ],
    # ── Transfer ────────────────────────────────────────────────────────
    "download": [
        ("M", 12, 3),
        ("L", 12, 16),
        ("M", 6, 10),
        ("L", 12, 16),
        ("L", 18, 10),
        ("M", 4, 20),
        ("L", 20, 20),
    ],
    "upload": [
        ("M", 12, 17),
        ("L", 12, 4),
        ("M", 6, 10),
        ("L", 12, 4),
        ("L", 18, 10),
        ("M", 4, 20),
        ("L", 20, 20),
    ],
    "link": [
        ("M", 7, 12),
        ("C", 7, 8, 10, 5, 14, 5),
        ("L", 17, 5),
        ("C", 19.5, 5, 20.5, 7, 20.5, 9),
        ("L", 20.5, 10.5),
        ("M", 17, 12),
        ("C", 17, 16, 14, 19, 10, 19),
        ("L", 7, 19),
        ("C", 4.5, 19, 3.5, 17, 3.5, 15),
        ("L", 3.5, 13.5),
    ],
    "external_link": [
        ("M", 10, 4),
        ("L", 4, 4),
        ("L", 4, 20),
        ("L", 20, 20),
        ("L", 20, 14),
        ("M", 12, 12),
        ("L", 20, 4),
        ("M", 14, 4),
        ("L", 20, 4),
        ("L", 20, 10),
    ],
    # ── Arrows ──────────────────────────────────────────────────────────
    "arrow_up": [
        ("M", 12, 20),
        ("L", 12, 5),
        ("M", 6, 11),
        ("L", 12, 5),
        ("L", 18, 11),
    ],
    "arrow_down": [
        ("M", 12, 4),
        ("L", 12, 19),
        ("M", 6, 13),
        ("L", 12, 19),
        ("L", 18, 13),
    ],
    "arrow_left": [
        ("M", 20, 12),
        ("L", 5, 12),
        ("M", 11, 6),
        ("L", 5, 12),
        ("L", 11, 18),
    ],
    "arrow_right": [
        ("M", 4, 12),
        ("L", 19, 12),
        ("M", 13, 6),
        ("L", 19, 12),
        ("L", 13, 18),
    ],
    # ── More / Overflow ─────────────────────────────────────────────────
    "more_horizontal": [
        ("circle", 5, 12, 1.5),
        ("circle", 12, 12, 1.5),
        ("circle", 19, 12, 1.5),
    ],
    "more_vertical": [
        ("circle", 12, 5, 1.5),
        ("circle", 12, 12, 1.5),
        ("circle", 12, 19, 1.5),
    ],
    # ── Time ────────────────────────────────────────────────────────────
    "clock": [
        ("circle", 12, 12, 9.5),
        ("M", 12, 5.5),
        ("L", 12, 12),
        ("L", 16, 14),
    ],
    "calendar": [
        ("rect", 3, 6, 18, 15, 2),
        ("M", 7, 3),
        ("L", 7, 8),
        ("M", 17, 3),
        ("L", 17, 8),
        ("M", 3, 13),
        ("L", 21, 13),
    ],
    # ── Visibility ──────────────────────────────────────────────────────
    "eye": [
        ("M", 2, 12),
        ("C", 2, 12, 6, 4, 12, 4),
        ("C", 18, 4, 22, 12, 22, 12),
        ("C", 22, 12, 18, 20, 12, 20),
        ("C", 6, 20, 2, 12, 2, 12),
        ("Z",),
        ("circle", 12, 12, 3),
    ],
    "eye_off": [
        ("M", 2, 12),
        ("C", 2, 12, 6, 4, 12, 4),
        ("C", 18, 4, 22, 12, 22, 12),
        ("C", 22, 12, 18, 20, 12, 20),
        ("C", 6, 20, 2, 12, 2, 12),
        ("Z",),
        ("circle", 12, 12, 3),
        ("M", 5, 5),
        ("L", 19, 19),
    ],
    # ── Edit / Actions ──────────────────────────────────────────────────
    "edit": [
        ("M", 18, 4),
        ("L", 20, 6),
        ("L", 7, 19),
        ("L", 3, 21),
        ("L", 5, 17),
        ("Z",),
    ],
    "trash": [
        ("M", 7, 5),
        ("L", 7, 3),
        ("L", 17, 3),
        ("L", 17, 5),
        ("M", 4, 5),
        ("L", 20, 5),
        ("L", 18, 21),
        ("L", 6, 21),
        ("Z",),
        ("M", 9, 9),
        ("L", 9, 17),
        ("M", 12, 9),
        ("L", 12, 17),
        ("M", 15, 9),
        ("L", 15, 17),
    ],
    "copy": [
        ("M", 9, 4),
        ("L", 20, 4),
        ("L", 20, 15),
        ("L", 9, 15),
        ("Z",),
        ("M", 4, 9),
        ("L", 15, 9),
        ("L", 15, 20),
        ("L", 4, 20),
        ("Z",),
    ],
    "refresh": [
        ("M", 18, 10),
        ("C", 18, 5.5, 14.5, 3, 12, 3),
        ("C", 8, 3, 4.5, 6.5, 4.5, 12),
        ("C", 4.5, 17, 8, 20.5, 13, 20.5),
        ("M", 18, 10),
        ("L", 18, 4),
        ("L", 22, 10),
        ("Z",),
    ],
    # ── Navigation ──────────────────────────────────────────────────────
    "menu": [
        ("M", 4, 6),
        ("L", 20, 6),
        ("M", 4, 12),
        ("L", 20, 12),
        ("M", 4, 18),
        ("L", 20, 18),
    ],
    "home": [
        ("M", 2, 11),
        ("L", 12, 2),
        ("L", 22, 11),
        ("M", 5, 9),
        ("L", 5, 21),
        ("L", 19, 21),
        ("L", 19, 9),
        ("M", 10, 21),
        ("L", 10, 14),
        ("L", 14, 14),
        ("L", 14, 21),
    ],
    "settings": [
        # Alias — same path as gear
        ("circle", 12, 12, 3.5),
        ("M", 12, 2.5),
        ("L", 12, 5),
        ("M", 19, 5.5),
        ("L", 17.5, 7.5),
        ("M", 21.5, 12),
        ("L", 19, 12),
        ("M", 19, 18.5),
        ("L", 17.5, 16.5),
        ("M", 12, 21.5),
        ("L", 12, 19),
        ("M", 5, 18.5),
        ("L", 6.5, 16.5),
        ("M", 2.5, 12),
        ("L", 5, 12),
        ("M", 5, 5.5),
        ("L", 6.5, 7.5),
    ],
    "logout": [
        ("M", 8, 4),
        ("L", 4, 4),
        ("L", 4, 20),
        ("L", 8, 20),
        ("M", 12, 7),
        ("L", 19, 12),
        ("L", 12, 17),
        ("M", 10, 12),
        ("L", 19, 12),
    ],
}

# ---------------------------------------------------------------------------
# Internal cache
# ---------------------------------------------------------------------------
_cache: dict[str, QPainterPath] = {}


def _build_path(commands: list[tuple]) -> QPainterPath:
    """Convert a list of command tuples into a QPainterPath."""
    path = QPainterPath()
    for cmd in commands:
        op = cmd[0]
        if op == "M":
            path.moveTo(cmd[1], cmd[2])
        elif op == "L":
            path.lineTo(cmd[1], cmd[2])
        elif op == "C":
            path.cubicTo(cmd[1], cmd[2], cmd[3], cmd[4], cmd[5], cmd[6])
        elif op == "Q":
            path.quadTo(cmd[1], cmd[2], cmd[3], cmd[4])
        elif op == "Z":
            path.closeSubpath()
        elif op == "circle":
            cx, cy, r = cmd[1], cmd[2], cmd[3]
            path.addEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        elif op == "rect":
            x, y, w, h, radius = cmd[1], cmd[2], cmd[3], cmd[4], cmd[5]
            path.addRoundedRect(QRectF(x, y, w, h), radius, radius)
    return path


def icon_path(name: str) -> QPainterPath:
    """Return a QPainterPath for the requested icon.

    The path lives in a normalized 24×24 viewBox.
    Returns an empty QPainterPath if the icon name is unknown.
    Results are cached after first construction.
    """
    if name in _cache:
        return _cache[name]
    commands = ICON_PATHS.get(name)
    if commands is None:
        return QPainterPath()
    path = _build_path(commands)
    _cache[name] = path
    return path


def render_icon(
    painter: QPainter,
    name: str,
    rect: QRectF,
    color: QColor,
    pen_width: float = 1.8,
) -> None:
    """Render a named icon into *rect* with the given *color*.

    The path is scaled uniformly to fit *rect* while preserving aspect ratio,
    then centered within it.  Default pen properties use round caps and
    round joins for a clean stroke appearance.  No brush is set, so closed
    subpaths (e.g. warning triangle) appear as outlines — callers that need
    filled icons can set painter.setBrush() before calling.
    """
    path = icon_path(name)
    if path.isEmpty():
        return

    painter.save()
    try:
        view_size = 24.0
        sx = rect.width() / view_size
        sy = rect.height() / view_size
        scale = min(sx, sy)

        cx = rect.x() + rect.width() / 2.0
        cy = rect.y() + rect.height() / 2.0

        painter.translate(cx, cy)
        painter.scale(scale, scale)
        painter.translate(-view_size / 2.0, -view_size / 2.0)

        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(
            QPen(color, pen_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        )
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
    finally:
        painter.restore()
