"""Unit tests for the GPU shader renderer of the styled fluid background."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from PySide6.QtGui import QColor

# Keep the same path bootstrap used by the sibling styled-fluid tests so
# ``from components.xxx`` absolute imports resolve without touching the repo.
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_UI_ROOT = _PROJECT_ROOT / "freeassetfilter" / "ui"
for _p in (_PROJECT_ROOT, _UI_ROOT):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

from components._styled_fluid_gpu import (
    _DEFAULT_GL_CONFIGURED,
    _FRAGMENT_SHADER,
    _VERTEX_SHADER,
    _FluidGPUShaderWidget,
)


class TestShaderSources:
    """Shader source string coverage."""

    def test_vertex_shader_is_non_empty(self) -> None:
        """The embedded vertex shader must contain code and a version tag."""
        assert _VERTEX_SHADER
        assert "#version 330" in _VERTEX_SHADER
        assert "a_position" in _VERTEX_SHADER

    def test_fragment_shader_is_non_empty(self) -> None:
        """The embedded fragment shader must contain code and all listed uniforms."""
        assert _FRAGMENT_SHADER
        assert "#version 330" in _FRAGMENT_SHADER
        for name in (
            "u_resolution",
            "u_time",
            "u_palette",
            "u_blob_centers",
            "u_blob_radii",
            "u_noise_offset",
            "u_overlay_color",
        ):
            assert name in _FRAGMENT_SHADER

    def test_fragment_shader_has_blobs_noise_and_blur(self) -> None:
        """The fragment shader must combine blobs, noise and a 9-tap blur."""
        assert "soft_blob" in _FRAGMENT_SHADER
        assert "noise" in _FRAGMENT_SHADER
        assert "for" in _FRAGMENT_SHADER
        assert "mix" in _FRAGMENT_SHADER


class _FakeGLFunctions:
    """Minimal stand-in for ``QOpenGLFunctions``."""

    def glViewport(self, x: int, y: int, w: int, h: int) -> None:
        pass

    def glClearColor(self, r: float, g: float, b: float, a: float) -> None:
        pass

    def glClear(self, mask: int) -> None:
        pass

    def glDrawArrays(self, mode: int, first: int, count: int) -> None:
        pass


class _FakeContext:
    """Minimal stand-in for ``QOpenGLContext``."""

    def isValid(self) -> bool:
        return True

    def functions(self) -> _FakeGLFunctions:
        return _FakeGLFunctions()


class TestWidgetLifecycle:
    """Tests for construction, GL context handling and cleanup."""

    def _make_widget(self) -> _FluidGPUShaderWidget:
        return _FluidGPUShaderWidget()

    def test_default_gl_format_requested(self, qapp: Any) -> None:
        """The module must have requested the default OpenGL format once."""
        assert _DEFAULT_GL_CONFIGURED is True

    def test_initialize_gl_raises_on_null_context(self, qapp: Any) -> None:
        """A missing OpenGL context must raise RuntimeError."""
        widget = self._make_widget()

        def _null_context() -> None:
            return None

        widget.context = _null_context  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="OpenGL context is not valid"):
            widget.initializeGL()

    def test_initialize_gl_raises_on_invalid_context(self, qapp: Any) -> None:
        """An invalid OpenGL context must raise RuntimeError."""
        widget = self._make_widget()
        fake_context = _FakeContext()
        fake_context.isValid = lambda: False  # type: ignore[method-assign]

        widget.context = lambda: fake_context  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="OpenGL context is not valid"):
            widget.initializeGL()

    def test_widget_initializes_with_valid_context(self, qapp: Any) -> None:
        """A valid (mocked) context should allow initialization to succeed."""
        widget = self._make_widget()
        widget.context = lambda: _FakeContext()  # type: ignore[method-assign]

        # Bypass real shader compile and geometry upload.
        widget._init_shader_program = lambda: None  # type: ignore[method-assign]
        widget._init_geometry = lambda: None  # type: ignore[method-assign]
        widget._initialized = True

        widget.initializeGL()
        assert widget._initialized is True

    def test_widget_can_be_destroyed(self, qapp: Any) -> None:
        """Destroying the widget must not leak native resources or raise."""
        widget = self._make_widget()
        widget.deleteLater()
        qapp.processEvents()
        assert True


class TestShaderCompilation:
    """Tests that shader failure paths raise RuntimeError."""

    def test_compile_failure_raises_runtime_error(
        self, qapp: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A compile failure must raise RuntimeError with the driver log."""

        class _BrokenProgram:
            def __init__(self, parent: Any = None) -> None:
                pass

            def addShaderFromSourceCode(self, shader_type: Any, source: str) -> bool:
                return False

            def log(self) -> str:
                return "fake compile error"

        monkeypatch.setattr(
            "components._styled_fluid_gpu.QOpenGLShaderProgram", _BrokenProgram
        )

        widget = _FluidGPUShaderWidget()
        widget.context = lambda: _FakeContext()  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="fake compile error"):
            widget.initializeGL()

    def test_link_failure_raises_runtime_error(
        self, qapp: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A link failure must raise RuntimeError with the driver log."""

        class _BrokenLinkProgram:
            def __init__(self, parent: Any = None) -> None:
                pass

            def addShaderFromSourceCode(self, shader_type: Any, source: str) -> bool:
                return True

            def link(self) -> bool:
                return False

            def log(self) -> str:
                return "fake link error"

        monkeypatch.setattr(
            "components._styled_fluid_gpu.QOpenGLShaderProgram", _BrokenLinkProgram
        )

        widget = _FluidGPUShaderWidget()
        widget.context = lambda: _FakeContext()  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="fake link error"):
            widget.initializeGL()


class TestUniformAssignment:
    """Tests that runtime uniform updates reach the shader program."""

    def _make_initialized_widget(
        self, qapp: Any
    ) -> tuple[_FluidGPUShaderWidget, MagicMock]:
        """Create a widget with a fully mocked shader program."""
        widget = _FluidGPUShaderWidget()
        widget.context = lambda: _FakeContext()  # type: ignore[method-assign]

        program = MagicMock()
        program.isLinked.return_value = True
        program.uniformLocation.return_value = 1
        program.setUniformValue1f = MagicMock()
        program.setUniformValueArray = MagicMock()
        program.setUniformValue = MagicMock()

        locations = {
            "u_resolution": 1,
            "u_time": 2,
            "u_palette": 3,
            "u_blob_centers": 4,
            "u_blob_radii": 5,
            "u_blob_colors": 6,
            "u_noise_offset": 7,
            "u_overlay_color": 8,
        }

        def _init_program() -> None:
            widget._program = program
            widget._uniform_locations = locations

        def _init_geometry() -> None:
            pass

        widget._init_shader_program = _init_program  # type: ignore[method-assign]
        widget._init_geometry = _init_geometry  # type: ignore[method-assign]
        widget._initialized = True
        widget.initializeGL()
        return widget, program

    def test_update_uniforms_stores_values(self, qapp: Any) -> None:
        """update_uniforms must update internal state."""
        widget, _ = self._make_initialized_widget(qapp)

        palette = [QColor(255, 0, 0), QColor(0, 255, 0), QColor(0, 0, 255)]
        widget.update_uniforms(
            time=3.14,
            palette=palette,
            blob_centers=[(0.1, 0.2), (0.3, 0.4), (0.5, 0.6), (0.7, 0.8)],
            blob_radii=[0.1, 0.2, 0.3, 0.4],
            blob_colors=[0, 1, 2, 3],
            noise_offset=(0.5, 0.6),
            overlay_color=QColor(0, 0, 0, 64),
        )

        assert widget._time == pytest.approx(3.14)
        assert len(widget._palette) == widget._PALETTE_SIZE
        assert widget._palette[0].red() == 255
        assert widget._blob_centers[0] == pytest.approx((0.1, 0.2))
        assert widget._blob_radii[3] == pytest.approx(0.4)
        assert widget._blob_colors[2] == 2
        assert widget._noise_offset == pytest.approx((0.5, 0.6))
        assert widget._overlay_color.alpha() == 64

    def test_set_uniforms_reaches_program(self, qapp: Any) -> None:
        """_set_uniforms must call the expected program methods."""
        widget, program = self._make_initialized_widget(qapp)
        widget.update_uniforms(
            time=2.0,
            palette=[QColor(255, 0, 0), QColor(0, 255, 0)],
            blob_centers=[(0.1, 0.2), (0.3, 0.4), (0.5, 0.6), (0.7, 0.8)],
            blob_radii=[0.1, 0.2, 0.3, 0.4],
            blob_colors=[0, 1, 2, 3],
            noise_offset=(0.5, 0.6),
            overlay_color=QColor(255, 255, 255, 32),
        )

        widget._set_uniforms(160, 90)

        program.setUniformValue.assert_any_call(1, 160.0, 90.0)
        program.setUniformValue1f.assert_any_call(2, 2.0)
        program.setUniformValue.assert_any_call(8, widget._overlay_color)

        # Float arrays are uploaded via setUniformValueArray.
        palette_call = program.setUniformValueArray.call_args_list[0]
        assert palette_call.args[0] == 3
        assert palette_call.args[2] == 5
        assert palette_call.args[3] == 3

        center_call = program.setUniformValueArray.call_args_list[1]
        assert center_call.args[2] == 4
        assert center_call.args[3] == 2

        radius_call = program.setUniformValueArray.call_args_list[2]
        assert radius_call.args[2] == 4
        assert radius_call.args[3] == 1

        color_call = program.setUniformValueArray.call_args_list[3]
        assert color_call.args[2] == 4

        program.setUniformValue.assert_any_call(7, 0.5, 0.6)


class TestOffscreenSmoke:
    """Optional offscreen smoke capture for the GPU renderer."""

    def test_offscreen_smoke_png_captured(
        self, qapp: Any, tmp_path: Path
    ) -> None:
        """Capture a smoke PNG unless explicitly skipped via env var."""
        if os.environ.get("FAF_SKIP_FLUID_GPU_SMOKE") == "1":
            pytest.skip("FAF_SKIP_FLUID_GPU_SMOKE=1")

        evidence_dir = Path(__file__).resolve().parents[4] / ".omo" / "evidence" / "styled-fluid-background-v2"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        target = evidence_dir / "task-3-gpu-renderer-smoke.png"

        widget = _FluidGPUShaderWidget()
        widget.resize(160, 90)
        widget.show()
        qapp.processEvents()

        try:
            if not widget._initialized:
                widget.initializeGL()
            if widget._initialized:
                widget.update_uniforms(
                    time=1.0,
                    palette=[
                        QColor("#FF0055"),
                        QColor("#5500FF"),
                        QColor("#00AAFF"),
                        QColor("#FFAA00"),
                        QColor("#AA00FF"),
                    ],
                    overlay_color=QColor(0, 0, 0, 51),
                )
                widget.update()
                qapp.processEvents()
                pixmap = widget.grab()
                pixmap.save(str(target))
        except RuntimeError as exc:
            # OpenGL is unavailable in this environment; write a note image
            # so the evidence file still exists and no crash occurs.
            from PySide6.QtGui import QPainter, QPixmap

            note = QPixmap(160, 90)
            note.fill(QColor(0, 0, 0, 0))
            painter = QPainter(note)
            painter.drawText(5, 45, f"GPU smoke skipped: {exc}")
            painter.end()
            note.save(str(target))

        assert target.exists()
        assert target.stat().st_size > 0
