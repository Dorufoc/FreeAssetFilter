"""OpenGL GLSL renderer for the styled fluid background.

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

import logging
import struct
from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLVertexArrayObject,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QWidget

__all__ = ["_FluidGPUShaderWidget"]

logger = logging.getLogger(__name__)

# OpenGL ES 2.0 / desktop constants used through QOpenGLFunctions.
_GL_TRIANGLES = 0x0004
_GL_FLOAT = 0x1406
_GL_COLOR_BUFFER_BIT = 0x00004000

_VERTEX_SHADER = """#version 330

layout(location = 0) in vec3 a_position;
out vec2 v_uv;

void main()
{
    v_uv = a_position.xy * 0.5 + 0.5;
    gl_Position = vec4(a_position, 1.0);
}
"""

_FRAGMENT_SHADER = """#version 330

in vec2 v_uv;
out vec4 fragColor;

uniform vec2 u_resolution;
uniform float u_time;
uniform vec3 u_palette[5];
uniform vec2 u_blob_centers[4];
uniform float u_blob_radii[4];
uniform int u_blob_colors[4];
uniform vec2 u_noise_offset;
uniform vec4 u_overlay_color;

#define PALETTE_SIZE 5
#define BLOB_COUNT 4

float hash(vec2 p)
{
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

float noise(vec2 p)
{
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);

    float a = hash(i);
    float b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0));
    float d = hash(i + vec2(1.0, 1.0));

    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

// Fully soft gaussian-like blob: no hard inner plateau, long smooth tail.
float soft_blob(vec2 uv, vec2 center, float radius)
{
    float d = length(uv - center);
    float outer = radius * 1.9;
    float t = clamp(d / outer, 0.0, 1.0);
    float s = 1.0 - t * t * (3.0 - 2.0 * t);
    return s * s;
}

// Diagonal base gradient matching the CPU renderer so the canvas is always
// fully covered by palette colors (no dark gaps between blobs).
vec3 base_gradient(vec2 uv)
{
    float t = clamp((uv.x + uv.y) * 0.5, 0.0, 1.0);
    if (t < 0.45) {
        return mix(u_palette[3], u_palette[0], t / 0.45);
    }
    return mix(u_palette[0], u_palette[1], (t - 0.45) / 0.55);
}

vec3 sample_scene(vec2 uv)
{
    const float opacity[BLOB_COUNT] = float[](0.95, 0.90, 0.85, 0.80);
    vec3 col = base_gradient(uv);

    // Source-over blending keeps colors inside the palette gamut instead of
    // additively blowing out to white where blobs overlap.
    for (int i = 0; i < BLOB_COUNT; ++i) {
        int idx = u_blob_colors[i];
        vec3 blob_col = u_palette[idx % PALETTE_SIZE];
        float field = soft_blob(uv, u_blob_centers[i], u_blob_radii[i]);
        col = mix(col, blob_col, field * opacity[i]);
    }
    return col;
}

void main()
{
    vec2 uv = v_uv;

    // Two-octave domain warp: slow global swirl plus local turbulence for an
    // organic, lava-lamp-like flow.
    float n1 = noise(uv * 2.0 + u_noise_offset + u_time * 0.03);
    float n2 = noise(uv * 3.5 - u_noise_offset * 0.7 - u_time * 0.02);
    float angle = (n1 - 0.5) * 0.9 + u_time * 0.015;
    mat2 rot = mat2(cos(angle), -sin(angle), sin(angle), cos(angle));
    vec2 centered = (uv - vec2(0.5)) * rot;
    uv = vec2(0.5) + centered;
    uv += vec2(n1 - 0.5, n2 - 0.5) * 0.12;

    // 9-tap soft-blur approximation.
    vec2 texel = 1.0 / max(u_resolution, vec2(1.0));
    vec3 sum = vec3(0.0);
    float weight = 0.0;
    for (int x = -1; x <= 1; ++x) {
        for (int y = -1; y <= 1; ++y) {
            vec2 offset = vec2(float(x), float(y)) * texel * 2.5;
            sum += sample_scene(uv + offset);
            weight += 1.0;
        }
    }
    vec3 col = sum / weight;

    // Gentle saturation lift for richer, Apple Music-like tones.
    float luma = dot(col, vec3(0.299, 0.587, 0.114));
    col = clamp(mix(vec3(luma), col, 1.18), 0.0, 1.0);

    // Soft vignette adds depth without crushing the palette.
    float vig = smoothstep(1.15, 0.30, length(v_uv - vec2(0.5)));
    col *= mix(0.86, 1.0, vig);

    // Dark / light translucent overlay.
    col = mix(col, u_overlay_color.rgb, u_overlay_color.a);

    // Tiny screen-space dither hides gradient banding on large soft blobs.
    col += (hash(gl_FragCoord.xy) - 0.5) * (1.5 / 255.0);

    fragColor = vec4(col, 1.0);
}
"""

_DEFAULT_BLOB_CENTERS = (
    (0.16, 0.20),
    (0.84, 0.24),
    (0.30, 0.80),
    (0.78, 0.72),
)

_DEFAULT_BLOB_RADII = (0.58, 0.50, 0.53, 0.45)

_DEFAULT_BLOB_COLORS = (0, 1, 2, 3)

_DEFAULT_GL_CONFIGURED = False


def _ensure_default_gl_format() -> None:
    """Request a 3.3 Compatibility context once per process.

    This is needed for the embedded ``#version 330`` GLSL sources to compile
    reliably on Windows PySide6.  The guard makes repeated imports/idempotent
    so user code is not clobbered.
    """
    global _DEFAULT_GL_CONFIGURED
    if _DEFAULT_GL_CONFIGURED:
        return
    from PySide6.QtGui import QSurfaceFormat

    fmt = QSurfaceFormat()
    fmt.setMajorVersion(3)
    fmt.setMinorVersion(3)
    fmt.setProfile(QSurfaceFormat.CompatibilityProfile)
    QSurfaceFormat.setDefaultFormat(fmt)
    _DEFAULT_GL_CONFIGURED = True


_ensure_default_gl_format()


class _FluidGPUShaderWidget(QOpenGLWidget):
    """GLSL-based fluid background renderer.

    Renders a full-screen quad with a fragment shader that draws four soft
    SDF blobs, distorts UVs with pseudo-simplex noise, applies a 9-tap soft
    blur approximation, and blends a theme overlay.  Uniforms are updated at
    runtime via :meth:`update_uniforms` so the integration can animate the
    background without recompiling shaders.

    On construction the module-level OpenGL format request is already in
    place.  :meth:`initializeGL` validates the context and compiles the
    embedded shader sources, raising :class:`RuntimeError` on any failure so
    that the caller can fall back to the CPU path.
    """

    _PALETTE_SIZE = 5
    _BLOB_COUNT = 4

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)

        self._time = 0.0
        self._palette = [QColor(0, 0, 0, 255)] * self._PALETTE_SIZE
        self._blob_centers = list(_DEFAULT_BLOB_CENTERS)
        self._blob_radii = list(_DEFAULT_BLOB_RADII)
        self._blob_colors = list(_DEFAULT_BLOB_COLORS)
        self._noise_offset = (0.0, 0.0)
        self._overlay_color = QColor(0, 0, 0, 0)

        self._program: QOpenGLShaderProgram | None = None
        self._vao: QOpenGLVertexArrayObject | None = None
        self._vbo: QOpenGLBuffer | None = None
        self._uniform_locations: dict[str, int] = {}
        self._initialized = False

    def initializeGL(self) -> None:
        """Compile shaders and build the full-screen quad geometry.

        Raises:
            RuntimeError: If the OpenGL context is missing/invalid or the
                shader program cannot be compiled/linked.
        """
        ctx = self.context()
        if ctx is None or not ctx.isValid():
            raise RuntimeError("OpenGL context is not valid")

        self._init_shader_program()
        self._init_geometry()
        self._initialized = True

    def _init_shader_program(self) -> None:
        """Create, compile and link the embedded shader program.

        Raises:
            RuntimeError: On vertex/fragment compile or program link failure.
        """
        program = QOpenGLShaderProgram(self)

        if not program.addShaderFromSourceCode(QOpenGLShader.Vertex, _VERTEX_SHADER):
            log = program.log()
            raise RuntimeError(f"Vertex shader compile failed: {log}")

        if not program.addShaderFromSourceCode(
            QOpenGLShader.Fragment, _FRAGMENT_SHADER
        ):
            log = program.log()
            raise RuntimeError(f"Fragment shader compile failed: {log}")

        if not program.link():
            log = program.log()
            raise RuntimeError(f"Shader program link failed: {log}")

        self._program = program
        self._cache_uniform_locations()

    def _cache_uniform_locations(self) -> None:
        """Cache uniform locations to avoid per-frame name lookups."""
        if self._program is None:
            return
        locations: dict[str, int] = {}
        for name in (
            "u_resolution",
            "u_time",
            "u_palette",
            "u_blob_centers",
            "u_blob_radii",
            "u_blob_colors",
            "u_noise_offset",
            "u_overlay_color",
        ):
            locations[name] = self._program.uniformLocation(name)
        self._uniform_locations = locations

    def _init_geometry(self) -> None:
        """Upload a full-screen triangle pair to a VBO/VAO."""
        if self._program is None:
            return

        # Two triangles covering normalized device coordinates.
        vertices = (
            -1.0, 1.0, 0.0,
            -1.0, -1.0, 0.0,
            1.0, -1.0, 0.0,
            -1.0, 1.0, 0.0,
            1.0, -1.0, 0.0,
            1.0, 1.0, 0.0,
        )
        data = struct.pack(f"{len(vertices)}f", *vertices)

        vao = QOpenGLVertexArrayObject(self)
        vao_bound = False
        if vao.create():
            vao.bind()
            vao_bound = True

        vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        vbo.create()
        vbo.bind()
        vbo.allocate(data, len(data))

        self._program.enableAttributeArray("a_position")
        stride = 3 * 4
        self._program.setAttributeBuffer("a_position", _GL_FLOAT, 0, 3, stride)

        vbo.release()
        if vao_bound:
            vao.release()

        self._vao = vao
        self._vbo = vbo

    def resizeGL(self, width: int, height: int) -> None:
        """Update the viewport and resolution uniform.

        Args:
            width: New widget width in pixels.
            height: New widget height in pixels.
        """
        ctx = self.context()
        if ctx is None or not ctx.isValid():
            return
        functions = ctx.functions()
        functions.glViewport(0, 0, max(0, width), max(0, height))

        if self._program is not None and self._program.isLinked():
            self._program.bind()
            loc = self._uniform_locations.get("u_resolution")
            if loc >= 0:
                self._program.setUniformValue(loc, float(width), float(height))
            self._program.release()

    def paintGL(self) -> None:
        """Render the fluid background into the current framebuffer."""
        if not self._initialized or self._program is None:
            return

        ctx = self.context()
        if ctx is None or not ctx.isValid():
            return

        functions = ctx.functions()
        functions.glClearColor(0.0, 0.0, 0.0, 0.0)
        functions.glClear(_GL_COLOR_BUFFER_BIT)

        width = self.width()
        height = self.height()
        if width <= 0 or height <= 0:
            return

        self._program.bind()
        self._set_uniforms(width, height)

        if self._vao is not None and self._vao.isCreated():
            self._vao.bind()

        functions.glDrawArrays(_GL_TRIANGLES, 0, 6)

        if self._vao is not None and self._vao.isCreated():
            self._vao.release()
        self._program.release()

    def _set_uniforms(self, width: int, height: int) -> None:
        """Upload all uniforms to the bound shader program.

        Args:
            width: Current widget width in pixels.
            height: Current widget height in pixels.
        """
        if self._program is None or not self._program.isLinked():
            return

        loc = self._uniform_locations.get("u_resolution")
        if loc is not None and loc >= 0:
            self._program.setUniformValue(loc, float(width), float(height))

        loc = self._uniform_locations.get("u_time")
        if loc is not None and loc >= 0:
            self._program.setUniformValue1f(loc, float(self._time))

        palette_values = self._flatten_palette()
        if len(palette_values) >= self._PALETTE_SIZE * 3:
            loc = self._uniform_locations.get("u_palette")
            if loc is not None and loc >= 0:
                self._program.setUniformValueArray(
                    loc, palette_values, self._PALETTE_SIZE, 3
                )

        center_values = self._flatten_centers()
        if len(center_values) >= self._BLOB_COUNT * 2:
            loc = self._uniform_locations.get("u_blob_centers")
            if loc is not None and loc >= 0:
                self._program.setUniformValueArray(
                    loc, center_values, self._BLOB_COUNT, 2
                )

        radius_values = self._flatten_radii()
        if len(radius_values) >= self._BLOB_COUNT:
            loc = self._uniform_locations.get("u_blob_radii")
            if loc is not None and loc >= 0:
                self._program.setUniformValueArray(
                    loc, radius_values, self._BLOB_COUNT, 1
                )

        color_indices = self._flatten_color_indices()
        if len(color_indices) >= self._BLOB_COUNT:
            loc = self._uniform_locations.get("u_blob_colors")
            if loc is not None and loc >= 0:
                self._program.setUniformValueArray(
                    loc, color_indices, self._BLOB_COUNT
                )

        noise_x, noise_y = self._noise_offset
        loc = self._uniform_locations.get("u_noise_offset")
        if loc is not None and loc >= 0:
            self._program.setUniformValue(loc, float(noise_x), float(noise_y))

        if self._overlay_color.isValid():
            loc = self._uniform_locations.get("u_overlay_color")
            if loc is not None and loc >= 0:
                self._program.setUniformValue(loc, self._overlay_color)

    def update_uniforms(
        self,
        *,
        time: float | None = None,
        palette: Sequence[QColor] | None = None,
        blob_centers: Sequence[tuple[float, float]] | None = None,
        blob_radii: Sequence[float] | None = None,
        blob_colors: Sequence[int] | None = None,
        noise_offset: tuple[float, float] | None = None,
        overlay_color: QColor | None = None,
    ) -> None:
        """Update the shader uniforms without recompiling.

        All arguments are keyword-only.  ``None`` leaves the corresponding
        state unchanged.

        Args:
            time: Animation time in seconds.
            palette: Up to 5 :class:`QColor` objects mapped to ``u_palette``.
            blob_centers: Four ``(x, y)`` normalized positions.
            blob_radii: Four normalized radii.
            blob_colors: Four palette indices.
            noise_offset: ``(x, y)`` noise scroll offset.
            overlay_color: Overlay color including alpha.
        """
        if time is not None:
            self._time = float(time)
        if palette is not None:
            self._palette = self._normalize_palette(list(palette))
        if blob_centers is not None:
            self._blob_centers = self._normalize_centers(list(blob_centers))
        if blob_radii is not None:
            self._blob_radii = self._normalize_radii(list(blob_radii))
        if blob_colors is not None:
            self._blob_colors = self._normalize_color_indices(list(blob_colors))
        if noise_offset is not None:
            self._noise_offset = (float(noise_offset[0]), float(noise_offset[1]))
        if overlay_color is not None:
            self._overlay_color = QColor(overlay_color)

        if self._initialized:
            self.update()

    def _normalize_palette(self, palette: list[QColor]) -> list[QColor]:
        """Return exactly ``_PALETTE_SIZE`` colors, preserving positions.

        Invalid entries are replaced in place (by the previous valid color in
        the list, falling back to opaque black) instead of being filtered
        out: dropping an entry would shift every following palette index and
        recolor the whole scene for that frame.
        """
        normalized: list[QColor] = []
        last_valid = QColor(0, 0, 0, 255)
        for c in palette[: self._PALETTE_SIZE]:
            if isinstance(c, QColor) and c.isValid():
                last_valid = QColor(c)
                normalized.append(QColor(c))
            else:
                normalized.append(QColor(last_valid))
        while len(normalized) < self._PALETTE_SIZE:
            normalized.append(QColor(last_valid))
        return normalized

    def _normalize_centers(
        self, centers: list[tuple[float, float]]
    ) -> list[tuple[float, float]]:
        """Return exactly ``_BLOB_COUNT`` center tuples."""
        while len(centers) < self._BLOB_COUNT:
            centers.append((0.0, 0.0))
        return centers[: self._BLOB_COUNT]

    def _normalize_radii(self, radii: list[float]) -> list[float]:
        """Return exactly ``_BLOB_COUNT`` radii."""
        while len(radii) < self._BLOB_COUNT:
            radii.append(0.25)
        return radii[: self._BLOB_COUNT]

    def _normalize_color_indices(self, indices: list[int]) -> list[int]:
        """Return exactly ``_BLOB_COUNT`` palette indices."""
        while len(indices) < self._BLOB_COUNT:
            indices.append(0)
        return [max(0, int(i)) % self._PALETTE_SIZE for i in indices[: self._BLOB_COUNT]]

    def _flatten_palette(self) -> list[float]:
        """Flatten the palette to ``[r, g, b, ...]``."""
        values: list[float] = []
        for color in self._palette[: self._PALETTE_SIZE]:
            values.extend((color.redF(), color.greenF(), color.blueF()))
        return values

    def _flatten_centers(self) -> list[float]:
        """Flatten blob centers to ``[x, y, ...]``."""
        values: list[float] = []
        for x, y in self._blob_centers[: self._BLOB_COUNT]:
            values.extend((float(x), float(y)))
        return values

    def _flatten_radii(self) -> list[float]:
        """Flatten blob radii to ``[r, ...]``."""
        return [float(r) for r in self._blob_radii[: self._BLOB_COUNT]]

    def _flatten_color_indices(self) -> list[int]:
        """Flatten blob palette indices."""
        return [int(i) for i in self._blob_colors[: self._BLOB_COUNT]]
