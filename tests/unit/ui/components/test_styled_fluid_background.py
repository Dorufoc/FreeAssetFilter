"""StyledFluidBackground unit tests."""
# allow: SIZE_OK — test file extends the existing color API tests with
# renderer/lifecycle coverage for the GPU-first/CPU-fallback integration.

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QStackedLayout, QWidget

from freeassetfilter.ui.theme import tm

# 与 video_player_layout.py 保持一致：将 freeassetfilter/ui 加入 sys.path，
# 使 `from components.xxx` 的组件导入可用。
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_UI_ROOT = _PROJECT_ROOT / "freeassetfilter" / "ui"
for _p in (_PROJECT_ROOT, _UI_ROOT):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

from components.styled_fluid_background import StyledFluidBackground


@pytest.fixture(autouse=True)
def _reset_ui_theme(qt_app):
    """每个测试结束后恢复 UI 主题管理器的全局颜色字典。"""
    original_colors = copy.deepcopy(tm._colors)
    yield
    tm._colors = original_colors


class TestColors:
    """测试 StyledFluidBackground 的颜色状态转换。"""

    def _create_widget(self) -> StyledFluidBackground:
        """返回一个新的组件实例。"""
        return StyledFluidBackground()

    def test_initial_palette_is_accent_derived(self, qt_app):
        """构造后应提供一个基于当前主题强调色的 5 色盘。"""
        widget = self._create_widget()
        palette = widget.colors()

        assert len(palette) == 5
        assert all(isinstance(c, QColor) and c.isValid() for c in palette)

    def test_set_custom_colors_five_is_identity(self, qt_app):
        """传入 5 个 QColor 时原样保留。"""
        colors = [
            QColor(255, 0, 0),
            QColor(0, 255, 0),
            QColor(0, 0, 255),
            QColor(255, 255, 0),
            QColor(0, 255, 255),
        ]
        widget = self._create_widget()
        widget.set_custom_colors(colors)
        palette = widget.colors()

        assert len(palette) == 5
        for original, current in zip(colors, palette):
            assert original == current

    def test_set_custom_colors_two_interpolates_to_five(self, qt_app):
        """传入 2 个 QColor 时扩展为 5 色，首尾保持原色。"""
        c0 = QColor(0, 0, 0)
        c1 = QColor(255, 255, 255)
        widget = self._create_widget()
        widget.set_custom_colors([c0, c1])
        palette = widget.colors()

        assert len(palette) == 5
        assert palette[0] == c0
        assert palette[4] == c1
        midpoint = palette[2]
        assert midpoint.red() == 128
        assert midpoint.green() == 128
        assert midpoint.blue() == 128

    def test_set_custom_colors_three_interpolates_to_five(self, qt_app):
        """传入 3 个 QColor 时扩展为 5 色，原色位于 0/2/4。"""
        c0 = QColor(255, 0, 0)
        c1 = QColor(0, 255, 0)
        c2 = QColor(0, 0, 255)
        widget = self._create_widget()
        widget.set_custom_colors([c0, c1, c2])
        palette = widget.colors()

        assert len(palette) == 5
        assert palette[0] == c0
        assert palette[2] == c1
        assert palette[4] == c2

    def test_set_custom_colors_one_derives_five(self, qt_app):
        """传入 1 个 QColor 时基于该色派生 5 色盘。"""
        base = QColor(128, 64, 32)
        widget = self._create_widget()
        widget.set_custom_colors([base])
        palette = widget.colors()

        assert len(palette) == 5
        assert all(isinstance(c, QColor) and c.isValid() for c in palette)

    def test_empty_color_list_falls_back_to_accent(self, qt_app):
        """空列表应回退到基于 tm.accent 的配色盘。"""
        widget = self._create_widget()
        widget.set_custom_colors([])

        expected = self._create_widget()
        expected.use_accent_theme()

        assert len(widget.colors()) == 5
        assert widget.colors() == expected.colors()

    def test_invalid_color_entry_falls_back_to_accent(self, qt_app):
        """非 QColor 条目应触发回退。"""
        widget = self._create_widget()
        widget.set_custom_colors([QColor("#FF0000"), "not a color"])

        expected = self._create_widget()
        expected.use_accent_theme()

        assert widget.colors() == expected.colors()

    def test_use_accent_theme_derives_from_tm_accent(self, qt_app):
        """use_accent_theme 应读取 tm.accent 并生成配色盘。"""
        tm._colors["accent"]["primary"] = "#07C160"
        widget = self._create_widget()
        widget.use_accent_theme()
        palette = widget.colors()

        assert len(palette) == 5
        assert palette[0].isValid()

    def test_colors_updated_signal_rebuilds_accent_palette(self, qt_app):
        """连接 tm.colors_updated 后，主题切换应自动重建配色盘。"""
        tm._colors["accent"]["primary"] = "#AABBCC"
        widget = self._create_widget()
        widget.use_accent_theme()
        original = widget.colors()

        tm._colors["accent"]["primary"] = "#123456"
        expected_widget = self._create_widget()
        expected_widget.use_accent_theme()
        expected = expected_widget.colors()

        tm.colors_updated.emit(tm._colors)
        actual = widget.colors()

        assert actual == expected
        assert actual[0] != original[0]


def _widget_tick_id(widget: StyledFluidBackground) -> str:
    """Return the HeartbeatManager callback id derived from a widget."""
    return f"styled_fluid_bg_{id(widget)}"


class MockContext:
    """Valid OpenGL context stand-in for ``_FakeGPUWidget``."""

    def isValid(self) -> bool:
        return True


class _FakeGPUWidget:
    """Stand-in for ``_FluidGPUShaderWidget`` that never touches OpenGL."""

    def __init__(self, parent: Any = None) -> None:
        self.parent = parent
        self.update_calls: int = 0
        self.uniforms: dict[str, Any] | None = None
        self._visible = False

    def initializeGL(self) -> None:
        pass

    def update_uniforms(self, **kwargs: Any) -> None:
        self.uniforms = kwargs

    def update(self) -> None:
        self.update_calls += 1

    def setGeometry(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setParent(self, parent: Any) -> None:
        self.parent = parent

    def deleteLater(self) -> None:
        pass

    def show(self) -> None:
        self._visible = True

    def context(self) -> "MockContext":
        """Return a mock context that reports as valid."""
        return MockContext()


@pytest.fixture
def fake_gpu_widget(monkeypatch: pytest.MonkeyPatch):
    """Patch ``_FluidGPUShaderWidget`` so the GPU path always succeeds."""
    target = "components.styled_fluid_background._FluidGPUShaderWidget"

    def _factory(parent: Any = None) -> _FakeGPUWidget:
        return _FakeGPUWidget(parent)

    monkeypatch.setattr(target, _factory)


class TestLifecycle:
    """Tests for load()/unload() and HeartbeatManager integration."""

    def _create_widget(self) -> StyledFluidBackground:
        return StyledFluidBackground()

    def test_cpu_path_does_not_register_heartbeat(
        self, qt_app, heartbeat_manager, monkeypatch
    ):
        """强制 CPU 路径时 load() 不得注册 HeartbeatManager tick。"""
        monkeypatch.setenv("FAF_FORCE_FLUID_CPU", "1")
        widget = self._create_widget()
        widget.setFixedSize(200, 200)
        widget.load()

        cid = _widget_tick_id(widget)
        assert widget.renderer() == "cpu"
        assert cid not in heartbeat_manager._callbacks
        assert widget._static_pixmap is not None
        assert not widget._static_pixmap.isNull()

    def test_gpu_path_registers_heartbeat_callback(
        self, qt_app, heartbeat_manager, fake_gpu_widget
    ):
        """GPU 路径时 load() 必须注册 normal-tick callback。"""
        widget = self._create_widget()
        widget.load()

        cid = _widget_tick_id(widget)
        assert cid in heartbeat_manager._callbacks
        entry = heartbeat_manager._callbacks[cid]
        assert entry.priority == 3
        assert entry.every_n_ticks == 1
        assert entry.use_fast_tick is False

    def test_load_callback_is_unique_per_instance(
        self, qt_app, heartbeat_manager, fake_gpu_widget
    ):
        """两个 GPU 实例必须获得不同的 Heartbeat callback id。"""
        w1 = self._create_widget()
        w2 = self._create_widget()
        w1.load()
        w2.load()

        ids = {c.callback_id for c in heartbeat_manager._callbacks.values()}
        assert len(ids) == 2

    def test_unload_unregisters_heartbeat_callback(
        self, qt_app, heartbeat_manager, fake_gpu_widget
    ):
        """unload() 必须移除 GPU 路径注册的动画 tick callback。"""
        widget = self._create_widget()
        widget.load()
        cid = _widget_tick_id(widget)
        assert cid in heartbeat_manager._callbacks

        widget.unload()
        assert cid not in heartbeat_manager._callbacks

    def test_unload_disconnects_theme_signals(
        self, qt_app, heartbeat_manager, fake_gpu_widget
    ):
        """unload() 必须断开 theme_changed 与 colors_updated 两个槽。"""
        theme_calls: list[str] = []
        color_calls: list[dict] = []

        class _MarkerFluid(StyledFluidBackground):
            def _on_theme_changed(self, theme: str) -> None:
                theme_calls.append(theme)

            def _on_colors_updated(self, colors: dict) -> None:
                color_calls.append(colors)

        widget = _MarkerFluid()
        widget.load()
        widget.unload()

        tm.theme_changed.emit("dark")
        tm.colors_updated.emit(tm._colors)
        QApplication.instance().processEvents()

        assert not theme_calls
        assert not color_calls

    def test_heartbeat_tick_advances_gpu_animation(
        self, qt_app, heartbeat_manager, fake_gpu_widget
    ):
        """GPU 路径下 tick callback 必须推进动画状态并通知 GPU widget。"""
        widget = self._create_widget()
        widget.setFixedSize(200, 200)
        widget.load()
        assert widget.renderer() == "gpu"

        gpu = widget._gpu_widget
        cid = _widget_tick_id(widget)
        before = widget._tick_count
        callback = heartbeat_manager._callbacks[cid].resolve()
        callback()

        assert widget._tick_count == before + 1
        assert gpu.update_calls == 1
        assert gpu.uniforms is not None
        assert "time" in gpu.uniforms


class TestRendererSelection:
    """Tests for GPU/CPU renderer selection and fallback behaviour."""

    def _create_widget(self) -> StyledFluidBackground:
        return StyledFluidBackground()

    def test_default_load_attempts_gpu(self, qt_app, heartbeat_manager, monkeypatch):
        """By default load() must attempt the GPU path before settling."""
        monkeypatch.delenv("FAF_FORCE_FLUID_CPU", raising=False)
        widget = self._create_widget()
        widget.setFixedSize(200, 200)
        widget.load()

        assert widget._gpu_attempted is True
        assert widget.renderer() in ("gpu", "cpu")

    def test_forced_cpu_env_uses_cpu_path(self, qt_app, heartbeat_manager, monkeypatch):
        """FAF_FORCE_FLUID_CPU=1 must bypass GPU and select CPU."""
        monkeypatch.setenv("FAF_FORCE_FLUID_CPU", "1")
        widget = self._create_widget()
        widget.load()

        assert widget.renderer() == "cpu"

    def test_gpu_initialize_failure_falls_back_to_cpu(
        self, qt_app, heartbeat_manager, monkeypatch
    ):
        """A QOpenGLWidget that raises in initializeGL must trigger CPU fallback."""
        try:
            from PySide6.QtOpenGLWidgets import QOpenGLWidget
        except ImportError:
            pytest.skip("QOpenGLWidget not available")

        class _BrokenGL(QOpenGLWidget):
            def __init__(self, parent: Any = None) -> None:
                super().__init__(parent)

            def initializeGL(self):
                raise RuntimeError("simulated GL init failure")

        target = "components.styled_fluid_background._FluidGPUShaderWidget"
        monkeypatch.setattr(target, _BrokenGL)

        widget = self._create_widget()
        widget.setFixedSize(200, 200)
        widget.load()

        assert widget.renderer() == "cpu"

    def test_native_sibling_forces_cpu_fallback(self, qt_app, heartbeat_manager):
        """A visible native-window sibling in the same layout must force CPU."""
        parent = QWidget()
        layout = QStackedLayout(parent)

        native = QWidget()
        native.setAttribute(Qt.WA_NativeWindow)
        layout.addWidget(native)
        widget = self._create_widget()
        layout.addWidget(widget)
        parent.show()
        if native.winId() == 0:
            pytest.skip("native window could not be created in this environment")

        widget.load()

        assert widget.renderer() == "cpu"


class TestRendering:
    """Smoke tests that the chosen renderer produces visible pixels."""

    def test_cpu_path_stores_static_pixmap(
        self, qt_app, heartbeat_manager, monkeypatch
    ):
        """CPU 路径在 load() 时必须生成与组件尺寸一致的静态 pixmap。"""
        monkeypatch.setenv("FAF_FORCE_FLUID_CPU", "1")
        widget = StyledFluidBackground()
        widget.setFixedSize(200, 200)
        widget.load()

        assert widget.renderer() == "cpu"
        assert widget._static_pixmap is not None
        assert widget._static_pixmap.width() == 200
        assert widget._static_pixmap.height() == 200

    def test_cpu_path_paints_visible_blobs(self, qt_app, heartbeat_manager, monkeypatch):
        """The CPU fallback must draw a non-uniform blob background."""
        monkeypatch.setenv("FAF_FORCE_FLUID_CPU", "1")
        widget = StyledFluidBackground()
        widget.setFixedSize(200, 200)
        widget.load()
        QApplication.instance().processEvents()

        pixmap = widget.grab()
        assert not pixmap.isNull()

        image = pixmap.toImage()
        samples = {
            image.pixelColor(x, y).rgba()
            for x in range(0, 200, 10)
            for y in range(0, 200, 10)
        }
        assert len(samples) > 1, "CPU renderer should produce visible blob variation"

    def test_offscreen_gpu_failure_is_graceful(self, qt_app, heartbeat_manager):
        """If the GPU path cannot initialise, the widget must still render."""
        widget = StyledFluidBackground()
        widget.setFixedSize(200, 200)
        widget.load()
        QApplication.instance().processEvents()

        assert widget.renderer() in ("gpu", "cpu")

        pixmap = widget.grab()
        assert not pixmap.isNull()
        assert pixmap.width() > 0
        assert pixmap.height() > 0


class TestAnimationState:
    """Tests for the GPU-only animation state machine."""

    def _create_widget(self) -> StyledFluidBackground:
        return StyledFluidBackground()

    def test_time_state_advances_by_fixed_delta(
        self, qt_app, fake_gpu_widget
    ):
        """Each tick must advance ``_time_state.time`` by 0.033 seconds."""
        widget = self._create_widget()
        widget.setFixedSize(200, 200)
        widget.load()
        assert widget.renderer() == "gpu"

        widget._on_tick()
        assert widget._time_state is not None
        assert widget._time_state.time == pytest.approx(0.033)

        for _ in range(29):
            widget._on_tick()
        assert widget._time_state.time == pytest.approx(0.99)

    def test_palette_phase_wraps(self, qt_app, fake_gpu_widget):
        """``palette_phase`` must stay in ``[0.0, 1.0)`` after wrapping."""
        widget = self._create_widget()
        widget.load()
        assert widget._time_state is not None

        widget._time_state = widget._time_state._replace(palette_phase=0.999)
        widget._on_tick()

        assert 0.0 <= widget._time_state.palette_phase < 1.0
        assert widget._time_state.palette_phase == pytest.approx(0.001)

    def test_gpu_uniforms_evolve_after_ticks(
        self, qt_app, fake_gpu_widget
    ):
        """Shader uniforms passed to the GPU widget must change after ticks."""
        widget = self._create_widget()
        widget.setFixedSize(200, 200)
        widget.load()
        widget._sync_gpu_widget()
        initial = widget._gpu_widget.uniforms

        for _ in range(5):
            widget._on_tick()

        after = widget._gpu_widget.uniforms
        assert after is not None
        assert after["time"] > initial["time"]
        assert after["noise_offset"] != initial["noise_offset"]
        assert len(after["palette"]) == 5
        assert len(after["blob_centers"]) == 4

    def test_cpu_path_ignores_time_state(
        self, qt_app, heartbeat_manager, monkeypatch
    ):
        """The CPU path must never create or advance ``_time_state``."""
        monkeypatch.setenv("FAF_FORCE_FLUID_CPU", "1")
        widget = self._create_widget()
        widget.load()

        assert widget.renderer() == "cpu"
        assert widget._time_state is None
        widget._on_tick()
        assert widget._time_state is None
        assert widget._tick_count == 0

    def test_palette_is_not_mutated_in_place(self, qt_app, fake_gpu_widget):
        """Drifted palette passed to the GPU must be a new list of new colors."""
        colors = [
            QColor(200, 100, 50),
            QColor(50, 150, 250),
            QColor(120, 80, 200),
            QColor(240, 240, 240),
            QColor(10, 20, 30),
        ]
        widget = self._create_widget()
        widget.set_custom_colors(colors)
        widget.setFixedSize(200, 200)
        widget.load()

        original = [QColor(c) for c in widget._palette]
        for _ in range(20):
            widget._on_tick()

        assert widget._palette == original


class TestThemeOverlay:
    """Tests for the theme-aware overlay and CPU re-bake de-duplication."""

    @pytest.fixture(autouse=True)
    def _restore_theme_mode(self):
        """Restore the global dark/light flag so tests do not leak state."""
        original = tm.is_dark_theme()
        yield
        tm._dark_mode = original

    def _create_widget(self) -> StyledFluidBackground:
        return StyledFluidBackground()

    def test_overlay_color_switches_with_theme(self, qt_app):
        """_overlay_color() returns black@30% in dark and white@25% in light."""
        widget = self._create_widget()
        tm._dark_mode = True
        dark_overlay = widget._overlay_color()
        assert dark_overlay == tm.alpha_of(tm.black, 30.0)

        tm._dark_mode = False
        light_overlay = widget._overlay_color()
        assert light_overlay == tm.alpha_of(tm.white, 25.0)

    def test_cpu_rebakes_exactly_once_per_toggle(
        self, qt_app, heartbeat_manager, monkeypatch
    ):
        """A theme toggle must bake the CPU pixmap once despite two signals."""
        monkeypatch.setenv("FAF_FORCE_FLUID_CPU", "1")
        tm._dark_mode = True
        widget = self._create_widget()
        widget.setFixedSize(200, 200)
        widget.load()
        assert widget.renderer() == "cpu"

        bakes: list[int] = []
        original = widget._bake_static_frame

        def _tracked_bake() -> None:
            bakes.append(1)
            original()

        monkeypatch.setattr(widget, "_bake_static_frame", _tracked_bake)

        tm.set_theme("light")
        assert sum(bakes) == 1

    def test_cpu_no_third_bake_after_redundant_colors_updated(
        self, qt_app, heartbeat_manager, monkeypatch
    ):
        """Toggling twice then emitting colors_updated must not re-bake a third time."""
        monkeypatch.setenv("FAF_FORCE_FLUID_CPU", "1")
        tm._dark_mode = True
        widget = self._create_widget()
        widget.setFixedSize(200, 200)
        widget.load()
        assert widget.renderer() == "cpu"

        bakes: list[int] = []

        def _tracked_bake() -> None:
            bakes.append(1)

        monkeypatch.setattr(widget, "_bake_static_frame", _tracked_bake)

        tm.toggle_theme()
        tm.toggle_theme()
        tm.colors_updated.emit(tm._colors)
        assert sum(bakes) == 2

    def test_gpu_overlay_uniform_follows_theme(
        self, qt_app, heartbeat_manager, fake_gpu_widget
    ):
        """GPU path must push the updated overlay color to the widget uniforms."""
        tm._dark_mode = True
        widget = self._create_widget()
        widget.setFixedSize(200, 200)
        widget.load()
        assert widget.renderer() == "gpu"
        assert widget._gpu_widget is not None

        tm.set_theme("light")
        uniforms = widget._gpu_widget.uniforms
        assert uniforms is not None
        assert uniforms["overlay_color"] == tm.alpha_of(tm.white, 25.0)

        tm.set_theme("dark")
        uniforms = widget._gpu_widget.uniforms
        assert uniforms["overlay_color"] == tm.alpha_of(tm.black, 30.0)

    def test_unload_signals_do_not_crash_or_rebake(
        self, qt_app, heartbeat_manager, fake_gpu_widget, monkeypatch
    ):
        """After unload(), theme signals must be ignored and must not re-bake."""
        widget = self._create_widget()
        widget.setFixedSize(200, 200)
        widget.load()
        assert widget.renderer() == "gpu"

        bakes: list[int] = []
        monkeypatch.setattr(widget, "_bake_static_frame", lambda: bakes.append(1))

        widget.unload()
        tm.theme_changed.emit("dark")
        tm.colors_updated.emit(tm._colors)
        QApplication.instance().processEvents()

        assert sum(bakes) == 0
