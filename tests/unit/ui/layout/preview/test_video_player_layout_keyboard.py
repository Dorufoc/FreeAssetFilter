# -*- coding: utf-8 -*-
"""
VideoPlayerLayout 键盘快捷操作与 OSD 单元测试

验证新组件（ui/layout/preview/video_player_layout.py + StyledPlayerBar）的
键盘快捷操作（移植自旧版 VideoPlayer / DetachedVideoWindow）：
1. 空格 → 播放/暂停
2. 左/右方向键 → seek ±5s + seek 进度 OSD
3. 上/下方向键 → 音量 ±5 + OSD
4. 1/2/3/` → 倍速 1x/2x/3x/0.5x + OSD
5. Esc 不由 VideoPlayerLayout 处理（由全屏宿主既有链路处理）
6. StyledPlayerBar.set_fullscreen 同步全屏按钮状态（Esc 退出全屏回归）
"""

from __future__ import annotations

from typing import Any, Dict, List

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

import pytest

from freeassetfilter.ui.layout.preview import video_player_layout as vpl


# =============================================================================
# Fakes（复用 test_video_player_layout_focus_guard.py 的隔离模式）
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
        self._playing = False
        self._paused = True
        self._position = 0.0
        self._duration = 100.0
        self._volume = 50
        self.calls: List[tuple[Any, ...]] = []

    def register_component(self, component_id: str, name: str) -> None:
        self.calls.append(("register_component", component_id, name))

    def unregister_component(self, component_id: str) -> None:
        self.calls.append(("unregister_component", component_id))

    def initialize(self, initial_window_id: int = 0) -> bool:  # noqa: ARG002
        self._initialized = True
        return True

    def is_initialized(self) -> bool:
        return self._initialized

    def set_window_id(self, win_id: int, component_id: str = "unknown") -> bool:  # noqa: ARG002
        return True

    def play(self, component_id: str = "unknown") -> bool:  # noqa: ARG002
        self.calls.append(("play",))
        self._playing = True
        self._paused = False
        return True

    def pause(self, component_id: str = "unknown") -> bool:  # noqa: ARG002
        self.calls.append(("pause",))
        self._playing = False
        self._paused = True
        return True

    def stop(self, component_id: str = "unknown") -> bool:  # noqa: ARG002
        return True

    def seek(self, position: float, component_id: str = "unknown") -> bool:  # noqa: ARG002
        self.calls.append(("seek", position))
        self._position = position
        return True

    def set_volume(self, value: int, component_id: str = "unknown") -> bool:  # noqa: ARG002
        self.calls.append(("set_volume", value))
        self._volume = value
        return True

    def set_speed(self, speed: float, component_id: str = "unknown") -> bool:  # noqa: ARG002
        self.calls.append(("set_speed", speed))
        return True

    def set_muted(self, muted: bool, component_id: str = "unknown") -> bool:  # noqa: ARG002
        return True

    def set_loop(self, loop: str, component_id: str = "unknown") -> bool:  # noqa: ARG002
        return True

    def get_duration(self) -> float:
        return self._duration

    def get_position(self) -> float:
        return self._position

    def get_volume(self) -> int:
        return self._volume

    def is_playing(self) -> bool:
        return self._playing

    def is_paused(self) -> bool:
        return self._paused


class FakeMediaMetadataService:
    """Configurable stand-in for ``MediaMetadataService``."""

    def __init__(self, tags: Dict[str, Any] | None = None) -> None:
        self._tags = tags or {"title": "", "artist": "", "album": "", "cover_data": None}

    def initialize(self) -> None:
        pass

    def dispose(self) -> None:
        pass

    def extract_audio_tags(self, file_path: str) -> Dict[str, Any] | None:  # noqa: ARG002
        return dict(self._tags)


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
):
    """Create a VideoPlayerLayout with mocked MPVManager (no libmpv needed)."""
    monkeypatch.setattr(vpl, "MPVManager", lambda: fake_mpv)
    monkeypatch.setenv("FAF_FORCE_FLUID_CPU", "1")
    monkeypatch.setattr(vpl, "MediaMetadataService", lambda: FakeMediaMetadataService())

    layout = vpl.VideoPlayerLayout()
    # 模拟已加载文件并初始化 MPV 核心
    fake_mpv._initialized = True
    try:
        yield layout, fake_mpv
    finally:
        layout.cleanup()
        layout.close()
        layout.deleteLater()
        QApplication.processEvents()


def _press(layout, key) -> QKeyEvent:
    """向 layout 投递一个键盘按下事件。"""
    event = QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    layout.keyPressEvent(event)
    return event


# =============================================================================
# 键盘快捷操作映射
# =============================================================================


class TestKeyboardShortcuts:
    """键盘快捷操作映射（对应旧版 DetachedVideoWindow 信号）。"""

    def test_space_plays_when_paused(self, video_player_layout) -> None:
        layout, mpv = video_player_layout
        mpv._paused = True
        mpv._playing = False
        _press(layout, Qt.Key.Key_Space)
        assert ("play",) in mpv.calls

    def test_space_pauses_when_playing(self, video_player_layout) -> None:
        layout, mpv = video_player_layout
        mpv._paused = False
        mpv._playing = True
        _press(layout, Qt.Key.Key_Space)
        assert ("pause",) in mpv.calls

    def test_right_arrow_seeks_forward(self, video_player_layout) -> None:
        layout, mpv = video_player_layout
        mpv._position = 10.0
        mpv._duration = 100.0
        _press(layout, Qt.Key.Key_Right)
        assert ("seek", 15.0) in mpv.calls

    def test_left_arrow_seeks_backward(self, video_player_layout) -> None:
        layout, mpv = video_player_layout
        mpv._position = 10.0
        mpv._duration = 100.0
        _press(layout, Qt.Key.Key_Left)
        assert ("seek", 5.0) in mpv.calls

    def test_up_arrow_volume_up(self, video_player_layout) -> None:
        layout, mpv = video_player_layout
        mpv._volume = 50
        _press(layout, Qt.Key.Key_Up)
        assert ("set_volume", 55) in mpv.calls

    def test_down_arrow_volume_down(self, video_player_layout) -> None:
        layout, mpv = video_player_layout
        mpv._volume = 50
        _press(layout, Qt.Key.Key_Down)
        assert ("set_volume", 45) in mpv.calls

    def test_number_keys_set_speed(self, video_player_layout) -> None:
        layout, mpv = video_player_layout
        _press(layout, Qt.Key.Key_1)
        assert ("set_speed", 1.0) in mpv.calls
        _press(layout, Qt.Key.Key_2)
        assert ("set_speed", 2.0) in mpv.calls
        _press(layout, Qt.Key.Key_3)
        assert ("set_speed", 3.0) in mpv.calls

    def test_tilde_key_set_speed_0_5(self, video_player_layout) -> None:
        layout, mpv = video_player_layout
        _press(layout, Qt.Key.Key_QuoteLeft)
        assert ("set_speed", 0.5) in mpv.calls

    def test_escape_not_handled_by_layout(self, video_player_layout) -> None:
        """Esc 不触发任何播放操作（由全屏宿主 escapePressed 链路处理）。"""
        layout, mpv = video_player_layout
        before = list(mpv.calls)
        _press(layout, Qt.Key.Key_Escape)
        assert mpv.calls == before

    def test_unknown_key_falls_through(self, video_player_layout) -> None:
        """未识别按键走默认处理，不触发播放操作。"""
        layout, mpv = video_player_layout
        before = list(mpv.calls)
        _press(layout, Qt.Key.Key_F5)
        assert mpv.calls == before


# =============================================================================
# 键盘操作对应的 OSD 显示
# =============================================================================


class TestKeyboardOsd:
    """键盘操作对应的 OSD 显示（复用 StyledPlayerBar 已有 _OSDWidget）。"""

    def test_seek_forward_shows_seek_osd(self, video_player_layout, monkeypatch) -> None:
        layout, mpv = video_player_layout
        mpv._position = 10.0
        mpv._duration = 100.0
        shown = []
        monkeypatch.setattr(
            layout._player_bar,
            "show_seek_osd",
            lambda cur, dur, direction, duration=2000: shown.append((cur, dur, direction)),
        )
        layout.seek_forward()
        assert shown == [(15.0, 100.0, "forward")]

    def test_seek_backward_shows_seek_osd(self, video_player_layout, monkeypatch) -> None:
        layout, mpv = video_player_layout
        mpv._position = 10.0
        mpv._duration = 100.0
        shown = []
        monkeypatch.setattr(
            layout._player_bar,
            "show_seek_osd",
            lambda cur, dur, direction, duration=2000: shown.append((cur, dur, direction)),
        )
        layout.seek_backward()
        assert shown == [(5.0, 100.0, "backward")]

    def test_volume_up_shows_osd(self, video_player_layout, monkeypatch) -> None:
        layout, mpv = video_player_layout
        mpv._volume = 50
        shown = []
        monkeypatch.setattr(
            layout._player_bar,
            "show_osd",
            lambda msg, duration=2000: shown.append(msg),
        )
        layout.volume_up()
        assert shown == ["音量 55%"]

    def test_volume_down_shows_osd(self, video_player_layout, monkeypatch) -> None:
        layout, mpv = video_player_layout
        mpv._volume = 50
        shown = []
        monkeypatch.setattr(
            layout._player_bar,
            "show_osd",
            lambda msg, duration=2000: shown.append(msg),
        )
        layout.volume_down()
        assert shown == ["音量 45%"]

    def test_set_speed_shows_osd(self, video_player_layout, monkeypatch) -> None:
        layout, mpv = video_player_layout
        shown = []
        monkeypatch.setattr(
            layout._player_bar,
            "show_osd",
            lambda msg, duration=2000: shown.append(msg),
        )
        layout.set_speed(2.0)
        assert shown == ["2.0x"]


# =============================================================================
# StyledPlayerBar.set_fullscreen（Esc 退出全屏按钮状态回归）
# =============================================================================


class TestSetFullscreen:
    """``set_fullscreen`` 同步全屏状态与按钮图标（与 _on_fullscreen_clicked 一致）。"""

    def test_set_fullscreen_toggles_state_and_icon(self, qapp) -> None:
        bar = vpl.StyledPlayerBar()
        try:
            assert bar._fullscreen is False
            bar.set_fullscreen(True)
            assert bar._fullscreen is True
            assert "minisize.svg" in bar._fs_btn._svg_icon_path
            bar.set_fullscreen(False)
            assert bar._fullscreen is False
            assert "maxsize.svg" in bar._fs_btn._svg_icon_path
        finally:
            bar.close()
            bar.deleteLater()

    def test_set_fullscreen_idempotent(self, qapp) -> None:
        bar = vpl.StyledPlayerBar()
        try:
            bar.set_fullscreen(True)
            icon_after_first = bar._fs_btn._svg_icon_path
            bar.set_fullscreen(True)
            assert bar._fs_btn._svg_icon_path == icon_after_first
        finally:
            bar.close()
            bar.deleteLater()

    def test_set_fullscreen_does_not_emit_toggled(self, qapp) -> None:
        """set_fullscreen 不重发 fullscreen_toggled 信号（避免与调用方循环）。"""
        bar = vpl.StyledPlayerBar()
        emitted = []
        bar.fullscreen_toggled.connect(lambda value: emitted.append(value))
        try:
            bar.set_fullscreen(True)
            bar.set_fullscreen(False)
            assert emitted == []
        finally:
            bar.close()
            bar.deleteLater()
