# -*- coding: utf-8 -*-
"""
VideoPlayerLayout 全屏浮动控制栏焦点门控单元测试

验证新组件（ui/layout/preview/video_player_layout.py + StyledPlayerBar +
PreviewFullscreenHost）在分离全屏窗口失焦时：
1. 鼠标移动/底部区域检测不再唤出浮动控制栏；
2. 已显示的浮动控制栏立即隐藏（用户正在控制栏/弹窗上操作时除外）。
"""

from __future__ import annotations

from typing import Any, Dict, List

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

import pytest

from freeassetfilter.ui.layout.preview import video_player_layout as vpl
from freeassetfilter.ui.layout.preview.fullscreen_host import PreviewFullscreenHost


# =============================================================================
# Fakes（复用 test_video_player_layout_audio_mode.py 的隔离模式）
# =============================================================================


class FakeMPVManager(QObject):
    """Minimal stand-in for ``MPVManager`` in unit tests."""

    positionChanged = Signal(float, float)
    stateChanged = Signal(object)
    volumeChanged = Signal(int)
    mutedChanged = Signal(bool)
    speedChanged = Signal(float)
    fileLoaded = Signal(str)
    fileEnded = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self._initialized = False
        self.register_calls: List[tuple[Any, ...]] = []
        self.unregister_calls: List[str] = []

    def register_component(self, component_id: str, name: str) -> None:
        self.register_calls.append((component_id, name))

    def unregister_component(self, component_id: str) -> None:
        self.unregister_calls.append(component_id)

    def initialize(self, initial_window_id: int = 0) -> bool:  # noqa: ARG002
        self._initialized = True
        return True

    def is_initialized(self) -> bool:
        return self._initialized

    def set_window_id(self, win_id: int, component_id: str = "unknown") -> bool:  # noqa: ARG002
        return True

    def play(self, component_id: str = "unknown") -> bool:  # noqa: ARG002
        return True

    def pause(self, component_id: str = "unknown") -> bool:  # noqa: ARG002
        return True

    def stop(self, component_id: str = "unknown") -> bool:  # noqa: ARG002
        return True

    def seek(self, position: float, component_id: str = "unknown") -> bool:  # noqa: ARG002
        return True

    def set_volume(self, value: int, component_id: str = "unknown") -> bool:  # noqa: ARG002
        return True

    def set_speed(self, speed: float, component_id: str = "unknown") -> bool:  # noqa: ARG002
        return True

    def set_muted(self, muted: bool, component_id: str = "unknown") -> bool:  # noqa: ARG002
        return True

    def set_loop(self, loop: str, component_id: str = "unknown") -> bool:  # noqa: ARG002
        return True

    def get_duration(self) -> float:
        return 0.0

    def get_position(self) -> float:
        return 0.0


class FakeMediaMetadataService:
    """Configurable stand-in for ``MediaMetadataService``."""

    def __init__(self, tags: Dict[str, Any] | None = None) -> None:
        self._tags = tags or {"title": "", "artist": "", "album": "", "cover_data": None}
        self.initialized = False
        self.disposed = False

    def initialize(self) -> None:
        self.initialized = True

    def dispose(self) -> None:
        self.disposed = True

    def extract_audio_tags(self, file_path: str) -> Dict[str, Any] | None:  # noqa: ARG002
        return dict(self._tags)


class _FakeFloatContainer:
    """模拟 _FloatContainer 的最小替身。"""

    def __init__(self) -> None:
        self.hide_calls = 0

    def isVisible(self) -> bool:
        return True

    def hide_with_animation(self) -> None:
        self.hide_calls += 1


class _FakePopup:
    """模拟 _PlayerPopup 的最小替身。"""

    def __init__(self) -> None:
        self.close_calls = 0

    def isVisible(self) -> bool:
        return True

    def close_animated(self) -> None:
        self.close_calls += 1


class _FakeSignal:
    """模拟 Qt 信号（测试中用于验证 connect 被调用）。"""

    def __init__(self) -> None:
        self.connected: List[Any] = []

    def connect(self, slot: Any) -> None:
        self.connected.append(slot)


class _FakeHost:
    """模拟 PreviewFullscreenHost 的最小替身。"""

    def __init__(self, visible: bool = True, active: bool = True) -> None:
        self._visible = visible
        self._active = active
        self.attach_calls = 0
        self.show_calls = 0
        self.escapePressed = _FakeSignal()
        self.activated_changed = _FakeSignal()

    def isVisible(self) -> bool:
        return self._visible

    def isActiveWindow(self) -> bool:
        return self._active

    def attach(self, widget: Any) -> bool:  # noqa: ARG002
        self.attach_calls += 1
        return True

    def show_fullscreen(self) -> None:
        self.show_calls += 1

    def exit_fullscreen(self) -> None:
        pass

    def deleteLater(self) -> None:
        pass

    def screen(self) -> None:
        return None


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def fake_mpv() -> FakeMPVManager:
    """Provide a fresh fake MPVManager with call-recording helpers."""
    return FakeMPVManager()


@pytest.fixture
def video_player_layout(
    qapp,
    monkeypatch: pytest.MonkeyPatch,
    fake_mpv: FakeMPVManager,
) -> vpl.VideoPlayerLayout:
    """Create a VideoPlayerLayout with mocked MPVManager (no libmpv needed)."""
    monkeypatch.setattr(vpl, "MPVManager", lambda: fake_mpv)
    monkeypatch.setenv("FAF_FORCE_FLUID_CPU", "1")
    monkeypatch.setattr(vpl, "MediaMetadataService", lambda: FakeMediaMetadataService())

    layout = vpl.VideoPlayerLayout()
    layout._fullscreen = False
    layout._fullscreen_host = None
    try:
        yield layout
    finally:
        layout.cleanup()
        layout.close()
        layout.deleteLater()
        QApplication.processEvents()


# =============================================================================
# StyledPlayerBar 浮动模式焦点守卫
# =============================================================================


class TestFloatBarFocusGuard:
    """``set_float_focus_guard`` / ``hide_float_bar`` / ``_check_float_mouse_position`` 门控"""

    def _make_bar(self, qapp: Any) -> vpl.StyledPlayerBar:
        """创建真实 StyledPlayerBar 实例（不依赖 MPV）。"""
        return vpl.StyledPlayerBar()

    def test_set_guard_none_restores_default(self, qapp: Any) -> None:
        """guard 为 None 时应恢复默认（无焦点限制）。"""
        bar = self._make_bar(qapp)
        try:
            bar.set_float_focus_guard(lambda: False)
            assert bar._float_focus_guard is not None
            bar.set_float_focus_guard(None)
            assert bar._float_focus_guard is None
        finally:
            bar.close()
            bar.deleteLater()

    def test_guard_false_hides_visible_bar(self, qapp: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """guard 返回 False 且光标不在控制栏上 → 立即隐藏已显示的控制栏。"""
        bar = self._make_bar(qapp)
        try:
            bar._float_container = _FakeFloatContainer()
            bar._float_target_widget = object()
            bar._float_bar_visible = True
            bar._float_popup_open = False
            bar.set_float_focus_guard(lambda: False)
            monkeypatch.setattr(bar, "_is_float_cursor_in_bar_area", lambda: False)

            hidden: List[bool] = []
            bar.floating_bar_hidden.connect(lambda: hidden.append(True))

            bar._check_float_mouse_position()

            assert bar._float_bar_visible is False
            assert bar._float_container.hide_calls == 1
            assert hidden == [True]
        finally:
            bar.close()
            bar.deleteLater()

    def test_guard_false_keeps_bar_when_cursor_inside(self, qapp: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """guard 返回 False 但光标在控制栏上（正在操作）→ 不打断。"""
        bar = self._make_bar(qapp)
        try:
            bar._float_container = _FakeFloatContainer()
            bar._float_target_widget = object()
            bar._float_bar_visible = True
            bar._float_popup_open = False
            bar.set_float_focus_guard(lambda: False)
            monkeypatch.setattr(bar, "_is_float_cursor_in_bar_area", lambda: True)

            bar._check_float_mouse_position()

            assert bar._float_bar_visible is True
            assert bar._float_container.hide_calls == 0
        finally:
            bar.close()
            bar.deleteLater()

    def test_guard_false_blocks_wakeup(self, qapp: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """guard 返回 False 时鼠标移到底部也不会唤出控制栏（提前 return）。"""
        bar = self._make_bar(qapp)
        try:
            bar._float_container = _FakeFloatContainer()
            bar._float_target_widget = object()
            bar._float_bar_visible = False
            bar._float_popup_open = False
            bar.set_float_focus_guard(lambda: False)

            def _must_not_run() -> None:
                raise AssertionError("守卫分支应提前 return，不应走到显示逻辑")

            monkeypatch.setattr(bar, "_is_float_cursor_in_bar_area", lambda: False)
            monkeypatch.setattr(bar, "_update_float_popup_state", _must_not_run)

            bar._check_float_mouse_position()

            assert bar._float_bar_visible is False
            assert bar._float_container.hide_calls == 0
        finally:
            bar.close()
            bar.deleteLater()

    def test_hide_float_bar_hides_visible(self, qapp: Any) -> None:
        """hide_float_bar() 应隐藏可见的控制栏并发信号。"""
        bar = self._make_bar(qapp)
        try:
            bar._float_container = _FakeFloatContainer()
            bar._float_bar_visible = True
            bar._float_popup_open = False

            hidden: List[bool] = []
            bar.floating_bar_hidden.connect(lambda: hidden.append(True))

            bar.hide_float_bar()

            assert bar._float_bar_visible is False
            assert bar._float_container.hide_calls == 1
            assert hidden == [True]
        finally:
            bar.close()
            bar.deleteLater()

    def test_hide_float_bar_closes_popups(self, qapp: Any) -> None:
        """hide_float_bar() 在弹窗打开时应一并关闭弹窗。"""
        bar = self._make_bar(qapp)
        try:
            bar._float_container = _FakeFloatContainer()
            bar._float_bar_visible = True
            bar._float_popup_open = True
            bar._volume_popup = _FakePopup()
            bar._speed_popup = _FakePopup()
            bar._settings_popup = _FakePopup()

            bar.hide_float_bar()

            assert bar._volume_popup.close_calls == 1
            assert bar._speed_popup.close_calls == 1
            assert bar._settings_popup.close_calls == 1
        finally:
            bar.close()
            bar.deleteLater()

    def test_hide_float_bar_noop_when_hidden(self, qapp: Any) -> None:
        """控制栏已隐藏时 hide_float_bar() 无副作用。"""
        bar = self._make_bar(qapp)
        try:
            bar._float_container = _FakeFloatContainer()
            bar._float_bar_visible = False
            bar._float_popup_open = False

            hidden: List[bool] = []
            bar.floating_bar_hidden.connect(lambda: hidden.append(True))

            bar.hide_float_bar()

            assert bar._float_container.hide_calls == 0
            assert hidden == []
        finally:
            bar.close()
            bar.deleteLater()

    def test_hide_float_bar_noop_without_container(self, qapp: Any) -> None:
        """无浮动容器（未进入浮动模式）时 hide_float_bar() 不崩溃。"""
        bar = self._make_bar(qapp)
        try:
            bar._float_container = None
            bar.hide_float_bar()  # 不应抛出
        finally:
            bar.close()
            bar.deleteLater()


# =============================================================================
# VideoPlayerLayout 焦点门控决策
# =============================================================================


class TestLayoutFocusGuard:
    """``_allow_floating_bar_show`` 与 ``_on_fullscreen_host_active_changed``"""

    def test_disallow_when_no_host(self, video_player_layout: vpl.VideoPlayerLayout) -> None:
        """无全屏宿主时禁止显示。"""
        assert video_player_layout._allow_floating_bar_show() is False

    def test_disallow_when_host_hidden(self, video_player_layout: vpl.VideoPlayerLayout) -> None:
        """宿主不可见时禁止显示。"""
        video_player_layout._fullscreen_host = _FakeHost(visible=False, active=True)
        assert video_player_layout._allow_floating_bar_show() is False

    def test_allow_when_host_active(self, video_player_layout: vpl.VideoPlayerLayout) -> None:
        """宿主激活时允许显示。"""
        video_player_layout._fullscreen_host = _FakeHost(active=True)
        assert video_player_layout._allow_floating_bar_show() is True

    def test_disallow_when_host_inactive_and_cursor_outside(
        self, video_player_layout: vpl.VideoPlayerLayout, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """宿主失焦且光标不在控制栏上 → 禁止显示。"""
        video_player_layout._fullscreen_host = _FakeHost(active=False)
        monkeypatch.setattr(video_player_layout._player_bar, "is_float_cursor_in_bar_area", lambda: False)
        assert video_player_layout._allow_floating_bar_show() is False

    def test_allow_when_host_inactive_but_cursor_inside(
        self, video_player_layout: vpl.VideoPlayerLayout, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """宿主失焦但光标在控制栏/弹窗上（正在操作）→ 放行。"""
        video_player_layout._fullscreen_host = _FakeHost(active=False)
        monkeypatch.setattr(video_player_layout._player_bar, "is_float_cursor_in_bar_area", lambda: True)
        assert video_player_layout._allow_floating_bar_show() is True

    def test_active_gained_does_nothing(
        self, video_player_layout: vpl.VideoPlayerLayout, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """宿主获得激活时不隐藏控制栏。"""
        video_player_layout._fullscreen = True
        hide_calls: List[bool] = []
        monkeypatch.setattr(video_player_layout._player_bar, "hide_float_bar", lambda: hide_calls.append(True))
        video_player_layout._on_fullscreen_host_active_changed(True)
        assert hide_calls == []

    def test_active_lost_hides_bar(
        self, video_player_layout: vpl.VideoPlayerLayout, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """宿主失焦且光标不在控制栏上 → 立即隐藏控制栏。"""
        video_player_layout._fullscreen = True
        monkeypatch.setattr(video_player_layout._player_bar, "is_float_cursor_in_bar_area", lambda: False)
        hide_calls: List[bool] = []
        monkeypatch.setattr(video_player_layout._player_bar, "hide_float_bar", lambda: hide_calls.append(True))
        video_player_layout._on_fullscreen_host_active_changed(False)
        assert hide_calls == [True]

    def test_active_lost_keeps_bar_when_cursor_inside(
        self, video_player_layout: vpl.VideoPlayerLayout, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """宿主失焦但光标在控制栏上（正在操作）→ 不打断。"""
        video_player_layout._fullscreen = True
        monkeypatch.setattr(video_player_layout._player_bar, "is_float_cursor_in_bar_area", lambda: True)
        hide_calls: List[bool] = []
        monkeypatch.setattr(video_player_layout._player_bar, "hide_float_bar", lambda: hide_calls.append(True))
        video_player_layout._on_fullscreen_host_active_changed(False)
        assert hide_calls == []

    def test_active_lost_noop_when_not_fullscreen(
        self, video_player_layout: vpl.VideoPlayerLayout, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """非全屏状态失焦不处理。"""
        video_player_layout._fullscreen = False
        hide_calls: List[bool] = []
        monkeypatch.setattr(video_player_layout._player_bar, "hide_float_bar", lambda: hide_calls.append(True))
        video_player_layout._on_fullscreen_host_active_changed(False)
        assert hide_calls == []

    def test_enter_fullscreen_wires_focus_guard(
        self, video_player_layout: vpl.VideoPlayerLayout, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """进入全屏后应设置浮动控制栏焦点守卫并接线失焦隐藏。"""
        host = _FakeHost(active=True)
        monkeypatch.setattr(vpl, "PreviewFullscreenHost", lambda: host)

        enter_calls: List[tuple[Any, Any]] = []
        monkeypatch.setattr(
            video_player_layout._player_bar,
            "enter_floating_mode",
            lambda target_widget, screen_geometry: enter_calls.append((target_widget, screen_geometry)),
        )
        guard_set: List[Any] = []
        monkeypatch.setattr(video_player_layout._player_bar, "set_float_focus_guard", guard_set.append)

        video_player_layout._enter_fullscreen()

        assert video_player_layout._fullscreen is True
        assert video_player_layout._fullscreen_host is host
        assert host.attach_calls == 1
        assert host.show_calls == 1
        assert len(enter_calls) == 1
        assert guard_set == [video_player_layout._allow_floating_bar_show]
        # 失焦信号已接线到隐藏处理
        assert len(host.activated_changed.connected) == 1
        # 复位宿主引用以便 teardown 的 cleanup() 安全
        video_player_layout._fullscreen_host = None


# =============================================================================
# PreviewFullscreenHost 激活状态信号
# =============================================================================


class TestFullscreenHostActivatedSignal:
    """``activated_changed`` 信号转发"""

    def test_on_active_changed_emits_signal(self, qapp: Any) -> None:
        """``_on_active_changed`` 应转发激活状态为信号。"""
        host = PreviewFullscreenHost()
        try:
            received: List[bool] = []
            host.activated_changed.connect(received.append)

            host._on_active_changed(False)
            host._on_active_changed(True)

            assert received == [False, True]
        finally:
            host.close()
            host.deleteLater()

    def test_watch_active_state_without_handle(self, qapp: Any) -> None:
        """窗口未显示（无 windowHandle）时 ``_watch_active_state`` 不崩溃。"""
        host = PreviewFullscreenHost()
        try:
            host._watch_active_state()
            host._watch_active_state()  # 再次调用应幂等
        finally:
            host.close()
            host.deleteLater()
