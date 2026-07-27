"""Static CPU renderer for the styled fluid background.

FreeAssetFilter - 多功能文件预览与管理工具
Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPixmap

from components._styled_fluid_math import (
    ease_in_out_cubic,
    mix_rgb,
    sdf_soft_blob,
    simplex_noise_2d,
    wrap_phase,
)

__all__ = ["render_static_frame"]

# Downsample the target to at most this fraction in each dimension.
_RENDER_SCALE = 0.25

# Minimum off-screen render resolution (width x height).
_MIN_RENDER_WIDTH = 64
_MIN_RENDER_HEIGHT = 48

# Noise texture frequency in normalized render-UV space.
_NOISE_FREQ = 2.8

# Noise distortion amplitude in render pixels.
_NOISE_AMP = 8.0

# Softness of the SDF blob edge. Larger value = longer fade tail so the
# static frame matches the softer GPU blob profile.
_BLOB_FALLOFF = 0.9

# Normalised blob parameters shared with the GPU path.
_FLUID_BLOBS = [
    {"base_u": 0.16, "base_v": 0.20, "orbit_u": 0.14, "orbit_v": 0.10,
     "radius": 0.58, "scale_u": 1.34, "scale_v": 1.06,
     "phase": 0.0, "speed": 0.34, "opacity": 0.72, "color_index": 0},
    {"base_u": 0.84, "base_v": 0.24, "orbit_u": 0.13, "orbit_v": 0.11,
     "radius": 0.50, "scale_u": 1.20, "scale_v": 1.34,
     "phase": 1.1, "speed": 0.30, "opacity": 0.62, "color_index": 1},
    {"base_u": 0.30, "base_v": 0.80, "orbit_u": 0.11, "orbit_v": 0.12,
     "radius": 0.53, "scale_u": 1.28, "scale_v": 1.20,
     "phase": 2.2, "speed": 0.28, "opacity": 0.56, "color_index": 2},
    {"base_u": 0.78, "base_v": 0.72, "orbit_u": 0.14, "orbit_v": 0.10,
     "radius": 0.45, "scale_u": 1.42, "scale_v": 1.10,
     "phase": 3.0, "speed": 0.33, "opacity": 0.54, "color_index": 3},
    {"base_u": 0.50, "base_v": 0.46, "orbit_u": 0.10, "orbit_v": 0.10,
     "radius": 0.38, "scale_u": 1.10, "scale_v": 1.52,
     "phase": 4.1, "speed": 0.24, "opacity": 0.44, "color_index": 4},
    {"base_u": 0.60, "base_v": 0.16, "orbit_u": 0.09, "orbit_v": 0.08,
     "radius": 0.28, "scale_u": 1.30, "scale_v": 0.88,
     "phase": 0.8, "speed": 0.42, "opacity": 0.42, "color_index": 2},
    {"base_u": 0.20, "base_v": 0.58, "orbit_u": 0.10, "orbit_v": 0.06,
     "radius": 0.26, "scale_u": 0.96, "scale_v": 1.24,
     "phase": 2.8, "speed": 0.40, "opacity": 0.38, "color_index": 1},
    {"base_u": 0.84, "base_v": 0.52, "orbit_u": 0.07, "orbit_v": 0.09,
     "radius": 0.22, "scale_u": 1.12, "scale_v": 1.12,
     "phase": 5.0, "speed": 0.48, "opacity": 0.34, "color_index": 0},
]

_NOISE_CACHE: dict[tuple[int, int, int], list[list[float]]] = {}


def _is_finite(value: float) -> bool:
    """Return True when *value* is a finite real number."""
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _clamp01(value: float) -> float:
    """Clamp *value* to the unit interval."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    if value <= 0.0:
        return 0.0
    if value >= 1.0:
        return 1.0
    return value


def _normalized_palette(palette: Sequence[QColor]) -> list[QColor]:
    """Return a list of valid QColor values, falling back to opaque black."""
    colors = [QColor(c) for c in palette if isinstance(c, QColor) and c.isValid()]
    if not colors:
        return [QColor(0, 0, 0, 255)]
    return colors


def _render_size(width: int, height: int) -> tuple[int, int]:
    """Pick a reduced off-screen render size for the given target dimensions.

    The result is at most one quarter of the target in each dimension and
    never smaller than ``_MIN_RENDER_WIDTH`` by ``_MIN_RENDER_HEIGHT``.
    """
    try:
        w = max(_MIN_RENDER_WIDTH, int(width * _RENDER_SCALE))
        h = max(_MIN_RENDER_HEIGHT, int(height * _RENDER_SCALE))
    except (TypeError, ValueError):
        return (_MIN_RENDER_WIDTH, _MIN_RENDER_HEIGHT)
    return (w, h)


def _build_noise_texture(seed: int, width: int, height: int) -> list[list[float]]:
    """Build a deterministic grayscale noise texture for the render size.

    The texture is keyed by ``(seed, width, height)`` and reused across
    invocations of :func:`render_static_frame`.
    """
    texture: list[list[float]] = []
    denom_w = max(1, width - 1)
    denom_h = max(1, height - 1)
    for y in range(height):
        row: list[float] = []
        for x in range(width):
            nx = (x / denom_w) * _NOISE_FREQ
            ny = (y / denom_h) * _NOISE_FREQ
            row.append(float(simplex_noise_2d(nx, ny, seed)))
        texture.append(row)
    return texture


def _sample_base(u: float, v: float, palette: list[QColor]) -> QColor:
    """Sample the diagonal base gradient from the palette.

    The gradient follows the same three-stop diagonal used by the GPU path:
    top-left uses ``palette[3]``, mid around 45 % uses ``palette[0]``, and
    bottom-right uses ``palette[1]``.
    """
    u = _clamp01(u)
    v = _clamp01(v)
    t = _clamp01((u + v) / 2.0)

    if len(palette) >= 5:
        c3, c0, c1 = palette[3], palette[0], palette[1]
    elif len(palette) >= 3:
        c3, c0, c1 = palette[2], palette[0], palette[1]
    else:
        c0 = palette[0]
        c1 = palette[-1]
        c3 = c0

    if t < 0.45:
        return mix_rgb(c3, c0, t / 0.45)
    return mix_rgb(c0, c1, (t - 0.45) / 0.55)


def _screen_blend(base: QColor, add: QColor, strength: float) -> QColor:
    """Screen-blend *add* over *base* with the given per-channel strength.

    ``strength`` is clamped to ``[0, 1]``. The result is a brighter color that
    approximates the ``QPainter.CompositionMode_Screen`` path used by the GPU
    renderer.
    """
    try:
        strength = float(strength)
    except (TypeError, ValueError):
        strength = 0.0
    strength = _clamp01(strength)

    br, bg, bb, ba = base.getRgb()
    ar, ag, ab, _ = add.getRgb()

    # Normalise to [0, 1].
    br_f = br / 255.0
    bg_f = bg / 255.0
    bb_f = bb / 255.0
    ar_f = ar / 255.0
    ag_f = ag / 255.0
    ab_f = ab / 255.0

    # Screen blend: 1 - (1 - dst) * (1 - src * strength).
    out_r = 1.0 - (1.0 - br_f) * (1.0 - ar_f * strength)
    out_g = 1.0 - (1.0 - bg_f) * (1.0 - ag_f * strength)
    out_b = 1.0 - (1.0 - bb_f) * (1.0 - ab_f * strength)

    return QColor(
        round(max(0.0, min(255.0, out_r * 255.0))),
        round(max(0.0, min(255.0, out_g * 255.0))),
        round(max(0.0, min(255.0, out_b * 255.0))),
        ba,
    )


def _alpha_blend(dst: QColor, src: QColor) -> QColor:
    """Alpha-composite *src* over *dst*.

    The result uses non-premultiplied RGBA math matching Qt's source-over
    composition. Fully transparent *src* leaves *dst* unchanged.
    """
    sr, sg, sb, sa = src.getRgb()
    dr, dg, db, da = dst.getRgb()

    if sa <= 0:
        return QColor(dr, dg, db, da)
    if sa >= 255:
        return QColor(sr, sg, sb, sa)

    src_a = sa / 255.0
    src_one_minus = 1.0 - src_a
    out_a = src_a + (da / 255.0) * src_one_minus
    if out_a <= 0.0:
        return QColor(0, 0, 0, 0)

    out_r = (sr * src_a + dr * src_one_minus) / out_a
    out_g = (sg * src_a + dg * src_one_minus) / out_a
    out_b = (sb * src_a + db * src_one_minus) / out_a

    return QColor(
        round(max(0.0, min(255.0, out_r))),
        round(max(0.0, min(255.0, out_g))),
        round(max(0.0, min(255.0, out_b))),
        round(max(0.0, min(255.0, out_a * 255.0))),
    )


def render_static_frame(
    width: int,
    height: int,
    palette: Sequence[QColor],
    noise_seed: int,
    time: float,
    overlay_color: QColor,
) -> QPixmap:
    """Render a single static fluid background frame on the CPU.

    The image is computed at a reduced resolution (at most one quarter of the
    target dimensions, clamped to a minimum of 64x48), the translucent overlay
    is applied, and the result is upscaled to the requested size using smooth
    interpolation.

    The function intentionally keeps no animation state.  *time* only offsets
    the noise sampling phase and blob positions; no timers or heartbeat
    callbacks are registered.

    Args:
        width: Target width in pixels.
        height: Target height in pixels.
        palette: Sequence of QColor values used for the base gradient and
            blobs. Invalid entries are ignored.
        noise_seed: Seed used to build the deterministic Simplex noise texture.
        time: Phase offset for noise and blob positions.
        overlay_color: Semi-transparent color drawn over the fluid layer.

    Returns:
        QPixmap: A pixmap of exactly ``(width, height)`` pixels. A non-positive
        target size returns a null pixmap.
    """
    if width <= 0 or height <= 0:
        return QPixmap()

    palette = _normalized_palette(palette)
    if not overlay_color or not isinstance(overlay_color, QColor):
        overlay_color = QColor(0, 0, 0, 0)

    if not _is_finite(time):
        time = 0.0

    render_w, render_h = _render_size(width, height)

    # Reuse a cached noise texture for this (seed, width, height).
    cache_key = (int(noise_seed), render_w, render_h)
    noise = _NOISE_CACHE.get(cache_key)
    if noise is None:
        noise = _build_noise_texture(int(noise_seed), render_w, render_h)
        _NOISE_CACHE[cache_key] = noise

    # Pre-compute blob centers/radii in render-pixel space.
    max_dim = max(render_w, render_h)
    blobs: list[tuple[float, float, float, float, float, float, QColor]] = []
    for blob in _FLUID_BLOBS:
        phase = time * blob["speed"] + blob["phase"]
        cx = (blob["base_u"] + math.sin(phase) * blob["orbit_u"]) * render_w
        cy = (blob["base_v"] + math.cos(phase) * blob["orbit_v"]) * render_h
        radius = max_dim * blob["radius"]
        color = palette[blob["color_index"] % len(palette)]
        blobs.append((
            cx, cy,
            radius,
            float(blob["scale_u"]), float(blob["scale_v"]),
            float(blob["opacity"]),
            color,
        ))

    # Noise texture coordinate offsets derived from time so the same cached
    # texture produces different distortions for different time values.
    e = _clamp01(ease_in_out_cubic(wrap_phase(time * 0.05)))
    noise_offset_x = int(e * (render_w - 1))
    noise_offset_y = int((1.0 - e) * (render_h - 1))

    image = QImage(render_w, render_h, QImage.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 255).rgba())

    denom_w = max(1, render_w - 1)
    denom_h = max(1, render_h - 1)

    for y in range(render_h):
        noise_row = noise[y]
        for x in range(render_w):
            # Sample two independent offsets from the cached texture.
            nx = noise_row[x]
            ny = noise[(y + noise_offset_y) % render_h][
                (x + noise_offset_x) % render_w
            ]

            # Distort pixel coordinates in render-pixel space.
            px = x + nx * _NOISE_AMP
            py = y + ny * _NOISE_AMP

            # Normalised coordinates for the base gradient.
            u = _clamp01(px / denom_w)
            v = _clamp01(py / denom_h)

            color = _sample_base(u, v, palette)

            for cx, cy, radius, scale_u, scale_v, opacity, blob_color in blobs:
                dx = (px - cx) / scale_u
                dy = (py - cy) / scale_v
                dist = math.hypot(dx, dy)
                field = sdf_soft_blob(dist, 0.0, 0.0, 0.0, radius, _BLOB_FALLOFF)
                if field > 0.0:
                    color = _screen_blend(color, blob_color, field * opacity)

            if overlay_color.alpha() > 0:
                color = _alpha_blend(color, overlay_color)

            image.setPixel(x, y, color.rgba())

    pixmap = QPixmap.fromImage(image)
    if pixmap.isNull():
        # QPixmap creation failed (e.g. no Qt platform); return an empty pixmap
        # matching the requested geometry so callers can still query size.
        return QPixmap(width, height)

    if width == render_w and height == render_h:
        return pixmap

    return pixmap.scaled(
        width,
        height,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.SmoothTransformation,
    )
