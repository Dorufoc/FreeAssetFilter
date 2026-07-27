"""Pure-Python math/noise/color helpers for styled-fluid-background v2.

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
import random

from PySide6.QtGui import QColor

__all__ = [
    "ease_in_out_cubic",
    "hsv_shift",
    "mix_rgb",
    "sdf_soft_blob",
    "simplex_noise_2d",
    "wrap_phase",
]

_F2 = 0.5 * (math.sqrt(3.0) - 1.0)
_G2 = (3.0 - math.sqrt(3.0)) / 6.0
_PERM_CACHE: dict[int, tuple[int, ...]] = {}


def _safe_float(value: object) -> float:
    """Convert *value* to float, returning 0.0 for non-numeric inputs."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _get_perm(seed: int) -> tuple[int, ...]:
    """Return a 512-entry permutation table for the given integer seed.

    The table is cached per seed so repeated noise queries avoid rebuilding
    the permutation array.
    """
    try:
        key = int(seed)
    except (TypeError, ValueError):
        key = 0

    table = _PERM_CACHE.get(key)
    if table is not None:
        return table

    try:
        base = random.Random(key).sample(range(256), 256)
    except (TypeError, ValueError):
        base = random.Random(0).sample(range(256), 256)

    table = tuple(base + base)
    _PERM_CACHE[key] = table
    return table


def _grad(hash_value: int, x: float, y: float) -> float:
    """梯度函数 (gradient) for 2D simplex noise."""
    h = hash_value & 7
    u = x if h < 4 else y
    v = y if h < 4 else x
    if h & 1:
        u = -u
    if h & 2:
        v = -v
    return u + v


def sdf_soft_blob(
    x: float,
    y: float,
    cx: float,
    cy: float,
    radius: float,
    falloff: float = 0.5,
) -> float:
    """Soft signed-distance blob field.

    Returns 1.0 at the blob center and decays to 0.0 at
    ``radius * (1 + falloff)``.  The transition uses a smooth Hermite step.

    Args:
        x: Sample x coordinate.
        y: Sample y coordinate.
        cx: Blob center x.
        cy: Blob center y.
        radius: Inner radius where the field is still 1.0.
        falloff: Relative softness. 0.0 gives a hard step; larger values
            extend the fade-out region.  Negative values are clamped to 0.0.

    Returns:
        float: Field value in the range ``[0.0, 1.0]``.
    """
    radius = _safe_float(radius)
    if radius <= 0.0:
        return 0.0

    falloff = max(0.0, _safe_float(falloff))
    dist = math.hypot(_safe_float(x) - _safe_float(cx), _safe_float(y) - _safe_float(cy))

    if falloff == 0.0:
        return 1.0 if dist <= radius else 0.0

    outer = radius * (1.0 + falloff)
    if dist >= outer:
        return 0.0
    if dist <= radius:
        return 1.0

    t = (dist - radius) / (outer - radius)
    return 1.0 - (t * t * (3.0 - 2.0 * t))


def simplex_noise_2d(x: float, y: float, seed: int = 0) -> float:
    """Deterministic 2D Simplex-style noise.

    The permutation table is derived from *seed* using the standard library
    ``random`` module, making the result stable across process restarts and
    platforms for the same ``(x, y, seed)`` inputs.

    Args:
        x: X coordinate.
        y: Y coordinate.
        seed: Integer seed for the permutation table.

    Returns:
        float: Noise value in the range ``[-1.0, 1.0]``.  Non-finite
        coordinates return ``0.0``.
    """
    x = _safe_float(x)
    y = _safe_float(y)
    if not math.isfinite(x) or not math.isfinite(y):
        return 0.0

    perm = _get_perm(seed)

    s = (x + y) * _F2
    i = math.floor(x + s)
    j = math.floor(y + s)
    t = (i + j) * _G2
    x0 = x - (i - t)
    y0 = y - (j - t)

    if x0 > y0:
        i1, j1 = 1, 0
    else:
        i1, j1 = 0, 1

    x1 = x0 - i1 + _G2
    y1 = y0 - j1 + _G2
    x2 = x0 - 1.0 + 2.0 * _G2
    y2 = y0 - 1.0 + 2.0 * _G2

    ii = int(i) & 255
    jj = int(j) & 255

    n0 = n1 = n2 = 0.0

    t0 = 0.5 - x0 * x0 - y0 * y0
    if t0 >= 0.0:
        t0 *= t0
        n0 = t0 * t0 * _grad(perm[ii + perm[jj]], x0, y0)

    t1 = 0.5 - x1 * x1 - y1 * y1
    if t1 >= 0.0:
        t1 *= t1
        n1 = t1 * t1 * _grad(perm[ii + i1 + perm[jj + j1]], x1, y1)

    t2 = 0.5 - x2 * x2 - y2 * y2
    if t2 >= 0.0:
        t2 *= t2
        n2 = t2 * t2 * _grad(perm[ii + 1 + perm[jj + 1]], x2, y2)

    return max(-1.0, min(1.0, 70.0 * (n0 + n1 + n2)))


def ease_in_out_cubic(t: float) -> float:
    """Cubic ease-in-out function.

    Maps the clamped input ``[0.0, 1.0]`` to ``[0.0, 1.0]`` using
    ``4t^3`` for ``t < 0.5`` and ``1 - ((-2t + 2)^3) / 2`` otherwise.

    Args:
        t: Interpolation parameter.

    Returns:
        float: Eased value in ``[0.0, 1.0]``.  Inputs outside ``[0, 1]``
        are clamped; non-numeric inputs return ``0.0``.
    """
    t = _safe_float(t)
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    if t < 0.5:
        return 4.0 * t * t * t
    p = -2.0 * t + 2.0
    return 1.0 - (p * p * p) / 2.0


def wrap_phase(value: float) -> float:
    """Wrap a phase-like value into ``[0.0, 1.0)``.

    Args:
        value: Any real number.

    Returns:
        float: Fractional part in ``[0.0, 1.0)``.  Non-finite values
        return ``0.0``.
    """
    value = _safe_float(value)
    if not math.isfinite(value):
        return 0.0
    return value - math.floor(value)


def hsv_shift(color: QColor, dh: float, ds: float, dv: float) -> QColor:
    """Shift a color in HSV space.

    Hue shift is expressed in degrees and wraps automatically.  Saturation
    and value shifts are additive on Qt's ``0-255`` HSV scale and clamped to
    that range.  Alpha is preserved.

    The result is built with ``QColor.fromHsvF`` so fractional shifts stay
    smooth (no 1-degree quantization steps) and the hue can never land on
    the invalid integer 360: a tiny negative *dh* on a zero-hue color makes
    ``(h + dh) % 360.0`` round to exactly ``360.0`` in float math, which
    ``QColor.fromHsv`` rejects as out of range, silently producing an
    invalid color.

    Args:
        color: Base color.
        dh: Hue offset in degrees.
        ds: Saturation offset on the ``0-255`` scale.
        dv: Value offset on the ``0-255`` scale.

    Returns:
        QColor: A new shifted color.  Invalid *color* returns opaque black.
    """
    if not isinstance(color, QColor) or not color.isValid():
        return QColor(0, 0, 0, 255)

    h, s, v, a = color.getHsv()
    h = max(h, 0)

    new_h = (h + _safe_float(dh)) % 360.0
    if new_h >= 360.0:  # float-rounding guard for the wrap boundary
        new_h = 0.0
    new_s = max(0.0, min(255.0, s + _safe_float(ds)))
    new_v = max(0.0, min(255.0, v + _safe_float(dv)))

    return QColor.fromHsvF(
        new_h / 360.0, new_s / 255.0, new_v / 255.0, a / 255.0
    )


def mix_rgb(a: QColor, b: QColor, t: float) -> QColor:
    """Linearly interpolate two colors in RGBA space.

    Args:
        a: Start color.
        b: End color.
        t: Interpolation factor, clamped to ``[0.0, 1.0]``.

    Returns:
        QColor: Interpolated color.  Invalid inputs return opaque black.
    """
    if not isinstance(a, QColor) or not isinstance(b, QColor):
        return QColor(0, 0, 0, 255)

    t = max(0.0, min(1.0, _safe_float(t)))
    inv = 1.0 - t

    ra, ga, ba, aa = a.getRgb()
    rb, gb, bb, ab = b.getRgb()

    return QColor(
        round(ra * inv + rb * t),
        round(ga * inv + gb * t),
        round(ba * inv + bb * t),
        round(aa * inv + ab * t),
    )
