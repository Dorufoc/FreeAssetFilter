# -*- coding: utf-8 -*-
"""
VideoPlayerLayout 音频模式单元测试

在隔离环境中测试 ``freeassetfilter/ui/layout/preview/video_player_layout.py``
的音频分支，不依赖 ``libmpv-2.dll`` 或真实音频文件。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from PySide6.QtCore import QByteArray, QBuffer, QObject, Signal
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QApplication

import pytest

from freeassetfilter.core.managers.heartbeat_manager import HeartbeatManager
from freeassetfilter.ui.theme import tm


# The module under test bootstraps sys.path so imports like
# ``from components.styled_player_bar import StyledPlayerBar`` work.
from freeassetfilter.ui.layout.preview import video_player_layout as vpl


# =============================================================================
# Helpers
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
        self.load_file_calls: List[tuple[str, Dict[str, Any]]] = []
        self.embed_calls = 0
        self._window_ids: List[tuple[int, str]] = []
        self.play_calls: List[str] = []
        self.pause_calls: List[str] = []
        self.stop_calls: List[str] = []
        self.seek_calls: List[tuple[float, str]] = []
        self.set_volume_calls: List[tuple[int, str]] = []
        self.set_speed_calls: List[tuple[float, str]] = []
        self.set_muted_calls: List[tuple[bool, str]] = []

    def register_component(self, component_id: str, name: str) -> None:
        self.register_calls.append((component_id, name))

    def unregister_component(self, component_id: str) -> None:
        self.unregister_calls.append(component_id)

    def initialize(self, initial_window_id: int = 0) -> bool:  # noqa: ARG002
        """Accept the optional native window id used by ``_embed_mpv_window``."""
        self._initialized = True
        return True

    def is_initialized(self) -> bool:
        return self._initialized

    def load_file(
        self,
        file_path: str,
        is_audio: bool = False,
        component_id: str = "unknown",
        timeout: float = 30.0,
    ) -> bool:
        self.load_file_calls.append(
            (file_path, {"is_audio": is_audio, "component_id": component_id, "timeout": timeout})
        )
        return True

    def set_window_id(self, win_id: int, component_id: str = "unknown") -> bool:
        self._window_ids.append((win_id, component_id))
        return True

    def play(self, component_id: str = "unknown") -> bool:  # noqa: ARG002
        self.play_calls.append(component_id)
        return True

    def pause(self, component_id: str = "unknown") -> bool:  # noqa: ARG002
        self.pause_calls.append(component_id)
        return True

    def stop(self, component_id: str = "unknown") -> bool:  # noqa: ARG002
        self.stop_calls.append(component_id)
        return True

    def seek(self, position: float, component_id: str = "unknown") -> bool:  # noqa: ARG002
        self.seek_calls.append((position, component_id))
        return True

    def set_volume(self, value: int, component_id: str = "unknown") -> bool:  # noqa: ARG002
        self.set_volume_calls.append((value, component_id))
        return True

    def set_speed(self, speed: float, component_id: str = "unknown") -> bool:  # noqa: ARG002
        self.set_speed_calls.append((speed, component_id))
        return True

    def set_muted(self, muted: bool, component_id: str = "unknown") -> bool:  # noqa: ARG002
        self.set_muted_calls.append((muted, component_id))
        return True

    def set_loop(self, loop: str, component_id: str = "unknown") -> bool:  # noqa: ARG002
        return True

    def get_duration(self) -> float:
        return 0.0

    def get_position(self) -> float:
        return 0.0


class FakeMediaMetadataService:
    """Configurable stand-in for ``MediaMetadataService``."""

    _tags: Dict[str, Any]

    def __init__(self, tags: Dict[str, Any] | None = None) -> None:
        self._tags = tags or {
            "title": "",
            "artist": "",
            "album": "",
            "cover_data": None,
        }
        self.initialized = False
        self.disposed = False

    def initialize(self) -> None:
        self.initialized = True

    def dispose(self) -> None:
        self.disposed = True

    def extract_audio_tags(self, file_path: str) -> Dict[str, Any] | None:
        return dict(self._tags)


class FakeFluidBackground:
    """Lightweight stand-in for ``StyledFluidBackground``."""

    def __init__(self, parent: Any = None) -> None:  # noqa: ARG002
        self.custom_colors_calls: List[List[QColor]] = []
        self.accent_calls = 0
        self._loaded = False

    def load(self, parent_layout_slot: int | None = None) -> None:  # noqa: ARG002
        self._loaded = True

    def unload(self) -> None:
        self._loaded = False

    def set_custom_colors(self, colors: List[QColor]) -> None:
        self.custom_colors_calls.append(list(colors))

    def use_accent_theme(self) -> None:
        self.accent_calls += 1

    def renderer(self) -> str | None:
        return "cpu" if self._loaded else None


class FakeMusicInfoPanel:
    """Lightweight stand-in for ``StyledMusicInfoPanel``."""

    def __init__(self, parent: Any = None) -> None:  # noqa: ARG002
        self.title = ""
        self.artist = ""
        self.cover_pixmap: QPixmap | None = None
        self.placeholder_calls = 0
        self.clear_calls = 0

    def set_title(self, title: str) -> None:
        self.title = title

    def set_artist(self, artist: str) -> None:
        self.artist = artist

    def set_cover_pixmap(self, pixmap: QPixmap | None) -> None:
        self.cover_pixmap = pixmap

    def set_placeholder(self) -> None:
        self.placeholder_calls += 1
        self.cover_pixmap = None

    def clear(self) -> None:
        self.clear_calls += 1


def _make_png_bytes(width: int = 4, height: int = 4, color: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    """Create an in-memory PNG suitable for QImage.fromData."""
    image = QImage(width, height, QImage.Format_RGB888)
    image.fill(QColor(*color))
    byte_array = QByteArray()
    buffer = QBuffer(byte_array)
    buffer.open(QBuffer.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(byte_array)


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
    """Create a VideoPlayerLayout with mocked MPVManager.

    The real ``libmpv-2.dll`` is not required because ``MPVManager`` is
    replaced by ``FakeMPVManager`` before the layout instantiates it.
    """
    monkeypatch.setattr(vpl, "MPVManager", lambda: fake_mpv)
    monkeypatch.setenv("FAF_FORCE_FLUID_CPU", "1")

    layout = vpl.VideoPlayerLayout()
    try:
        yield layout
    finally:
        layout.cleanup()
        layout.close()
        layout.deleteLater()
        # Remove the layout-specific heartbeat callback so lingering singleton
        # state does not leak into sibling tests.
        HeartbeatManager().unregister_tick_callback(
            f"video_player_layout_sync_{id(layout)}"
        )


# =============================================================================
# 1. UI creation
# =============================================================================


class TestAudioSurfaceCreation:
    """Verify the audio rendering surface is created and hidden by default."""

    def test_audio_surface_created_and_in_stack(
        self,
        video_player_layout: vpl.VideoPlayerLayout,
    ) -> None:
        """``_audio_surface`` must exist, belong to ``_stack`` and stay hidden initially."""
        layout = video_player_layout
        assert hasattr(layout, "_audio_surface")
        assert layout._audio_surface is not None
        assert layout._stack.indexOf(layout._audio_surface) >= 0
        # Default visible widget is overlay (index 1).
        assert layout._stack.currentIndex() == 1

    def test_fluid_background_and_info_panel_created(
        self,
        video_player_layout: vpl.VideoPlayerLayout,
    ) -> None:
        """The audio surface must contain ``StyledFluidBackground`` and ``StyledMusicInfoPanel``."""
        layout = video_player_layout
        assert hasattr(layout, "_fluid_background")
        assert hasattr(layout, "_music_info_panel")
        assert layout._fluid_background is not None
        assert layout._music_info_panel is not None
        assert layout._audio_surface is layout._fluid_background.parentWidget()
        assert layout._audio_surface is layout._music_info_panel.parentWidget()


# =============================================================================
# 2. Audio-mode loading
# =============================================================================


class TestAudioModeLoading:
    """Verify ``set_file(path, is_audio=True)`` branch behaviour."""

    def test_audio_mode_does_not_embed_mpv_window(
        self,
        video_player_layout: vpl.VideoPlayerLayout,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Audio mode must not call ``_embed_mpv_window()``."""
        layout = video_player_layout
        embed_calls: List[Any] = []
        monkeypatch.setattr(layout, "_embed_mpv_window", lambda: embed_calls.append(True))

        audio_file = tmp_path / "fake.mp3"
        audio_file.write_bytes(b"mp3-noise")

        assert layout.set_file(str(audio_file), is_audio=True) is True
        assert len(embed_calls) == 0

    def test_audio_mode_passes_is_audio_to_load_file(
        self,
        video_player_layout: vpl.VideoPlayerLayout,
        fake_mpv: FakeMPVManager,
        tmp_path: Path,
    ) -> None:
        """``load_file`` must receive ``is_audio=True``."""
        audio_file = tmp_path / "fake.mp3"
        audio_file.write_bytes(b"mp3-noise")

        assert video_player_layout.set_file(str(audio_file), is_audio=True) is True

        assert len(fake_mpv.load_file_calls) == 1
        _, kwargs = fake_mpv.load_file_calls[0]
        assert kwargs["is_audio"] is True

    def test_audio_mode_initializes_mpv_when_not_embedded(
        self,
        video_player_layout: vpl.VideoPlayerLayout,
        fake_mpv: FakeMPVManager,
        tmp_path: Path,
    ) -> None:
        """Audio mode should call ``initialize()`` if MPV is not yet initialized."""
        assert fake_mpv.is_initialized() is False
        assert video_player_layout._is_mpv_embedded is False

        audio_file = tmp_path / "fake.mp3"
        audio_file.write_bytes(b"mp3-noise")

        assert video_player_layout.set_file(str(audio_file), is_audio=True) is True

        assert fake_mpv.is_initialized() is True

    def test_audio_mode_keeps_mpv_unembedded_flag(
        self,
        video_player_layout: vpl.VideoPlayerLayout,
        tmp_path: Path,
    ) -> None:
        """After audio playback ``_is_mpv_embedded`` must remain False for the next video embed."""
        audio_file = tmp_path / "fake.mp3"
        audio_file.write_bytes(b"mp3-noise")

        assert video_player_layout.set_file(str(audio_file), is_audio=True) is True
        assert video_player_layout._is_mpv_embedded is False

    def test_audio_mode_shows_audio_surface(
        self,
        video_player_layout: vpl.VideoPlayerLayout,
        tmp_path: Path,
    ) -> None:
        """After loading audio ``_stack.currentIndex()`` must point to ``_audio_surface``."""
        layout = video_player_layout
        audio_file = tmp_path / "fake.mp3"
        audio_file.write_bytes(b"mp3-noise")

        assert layout.set_file(str(audio_file), is_audio=True) is True

        audio_index = layout._stack.indexOf(layout._audio_surface)
        assert audio_index >= 0
        assert layout._stack.currentIndex() == audio_index
        assert layout.is_audio_mode is True

    def test_audio_mode_returns_false_for_missing_file(
        self,
        video_player_layout: vpl.VideoPlayerLayout,
    ) -> None:
        """A missing path returns False and keeps the overlay visible."""
        layout = video_player_layout

        result = layout.set_file("/non/existent/file.mp3", is_audio=True)

        assert result is False
        assert layout._stack.currentIndex() == 1


# =============================================================================
# 3. Metadata-driven UI updates
# =============================================================================


class TestAudioModeMetadataUpdates:
    """Verify metadata drives the fluid background and info panel updates."""

    def test_no_cover_calls_use_accent_theme(
        self,
        qapp,
        monkeypatch: pytest.MonkeyPatch,
        video_player_layout: vpl.VideoPlayerLayout,
        tmp_path: Path,
    ) -> None:
        """Without cover art the fluid background should fall back to ``use_accent_theme()``."""
        layout = video_player_layout
        accent_calls: List[Any] = []
        custom_calls: List[List[QColor]] = []
        monkeypatch.setattr(layout._fluid_background, "use_accent_theme", lambda: accent_calls.append(True))
        monkeypatch.setattr(
            layout._fluid_background, "set_custom_colors", lambda colors: custom_calls.append(list(colors))
        )

        fake_service = FakeMediaMetadataService(
            {"title": "Test Title", "artist": "Test Artist", "album": "", "cover_data": None}
        )
        monkeypatch.setattr(vpl, "MediaMetadataService", lambda: fake_service)

        audio_file = tmp_path / "no_cover.mp3"
        audio_file.write_bytes(b"mp3-noise")

        result = layout.set_file(str(audio_file), is_audio=True)

        assert result is True
        assert len(accent_calls) == 1
        assert len(custom_calls) == 0

    def test_metadata_updates_info_panel(
        self,
        qapp,
        monkeypatch: pytest.MonkeyPatch,
        video_player_layout: vpl.VideoPlayerLayout,
        tmp_path: Path,
    ) -> None:
        """Title/artist metadata should propagate to the info panel."""
        layout = video_player_layout
        fake_service = FakeMediaMetadataService(
            {"title": "脉冲", "artist": "火星电台", "album": "Demo", "cover_data": None}
        )
        monkeypatch.setattr(vpl, "MediaMetadataService", lambda: fake_service)

        captured_title: list[str] = []
        captured_artist: list[str] = []
        monkeypatch.setattr(layout._music_info_panel, "set_title", captured_title.append)
        monkeypatch.setattr(layout._music_info_panel, "set_artist", captured_artist.append)

        audio_file = tmp_path / "tagged.mp3"
        audio_file.write_bytes(b"mp3-noise")

        assert layout.set_file(str(audio_file), is_audio=True) is True

        assert captured_title == ["脉冲"]
        assert captured_artist == ["火星电台"]

    def test_metadata_service_lifecycle(
        self,
        qapp,
        monkeypatch: pytest.MonkeyPatch,
        video_player_layout: vpl.VideoPlayerLayout,
        tmp_path: Path,
    ) -> None:
        """Every audio load should initialize/dispose ``MediaMetadataService``."""
        layout = video_player_layout
        fake_service = FakeMediaMetadataService(
            {"title": "x", "artist": "y", "album": "z", "cover_data": None}
        )
        monkeypatch.setattr(vpl, "MediaMetadataService", lambda: fake_service)

        audio_file = tmp_path / "lifecycle.mp3"
        audio_file.write_bytes(b"mp3-noise")

        assert layout.set_file(str(audio_file), is_audio=True) is True

        assert fake_service.initialized is True
        assert fake_service.disposed is True


# =============================================================================
# 4. Cover-driven palette
# =============================================================================


class TestAudioModeCoverPalette:
    """Verify embedded cover art drives the fluid background palette."""

    def test_cover_data_calls_set_custom_colors(
        self,
        qapp,
        monkeypatch: pytest.MonkeyPatch,
        video_player_layout: vpl.VideoPlayerLayout,
        tmp_path: Path,
    ) -> None:
        """With cover data ``set_custom_colors`` must be called with 2-5 QColor values."""
        layout = video_player_layout
        accent_calls: List[Any] = []
        custom_calls: List[List[QColor]] = []
        monkeypatch.setattr(layout._fluid_background, "use_accent_theme", lambda: accent_calls.append(True))
        monkeypatch.setattr(
            layout._fluid_background, "set_custom_colors", lambda colors: custom_calls.append(list(colors))
        )

        cover = _make_png_bytes(8, 8, (0, 128, 255))
        fake_service = FakeMediaMetadataService(
            {"title": "Blue", "artist": "Test", "album": "", "cover_data": cover}
        )
        monkeypatch.setattr(vpl, "MediaMetadataService", lambda: fake_service)

        audio_file = tmp_path / "with_cover.mp3"
        audio_file.write_bytes(b"mp3-noise")

        assert layout.set_file(str(audio_file), is_audio=True) is True

        assert len(accent_calls) == 0
        assert len(custom_calls) == 1
        colors = custom_calls[0]
        assert 2 <= len(colors) <= 5
        assert all(isinstance(c, QColor) and c.isValid() for c in colors)


# =============================================================================
# 5. Video-mode continuity
# =============================================================================


class TestVideoModeContinuity:
    """Verify audio mode does not break subsequent video mode."""

    def test_video_after_audio_embeds_mpv_once(
        self,
        video_player_layout: vpl.VideoPlayerLayout,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """After audio, playing video should embed MPV exactly once."""
        layout = video_player_layout
        embed_calls: List[Any] = []
        original_embed = layout._embed_mpv_window

        def _wrapped_embed() -> None:
            embed_calls.append(True)
            original_embed()

        monkeypatch.setattr(layout, "_embed_mpv_window", _wrapped_embed)

        audio_file = tmp_path / "first.mp3"
        audio_file.write_bytes(b"mp3-noise")
        video_file = tmp_path / "second.mp4"
        video_file.write_bytes(b"mp4-noise")

        assert layout.set_file(str(audio_file), is_audio=True) is True
        assert layout._is_mpv_embedded is False
        assert len(embed_calls) == 0

        # First video load must embed.
        assert layout.set_file(str(video_file), is_audio=False) is True
        assert len(embed_calls) == 1
        assert layout._is_mpv_embedded is True

        # A second video load must not re-embed.
        video_file_2 = tmp_path / "third.mp4"
        video_file_2.write_bytes(b"mp4-noise-2")
        assert layout.set_file(str(video_file_2), is_audio=False) is True
        assert len(embed_calls) == 1

    def test_is_audio_mode_accessor(
        self,
        video_player_layout: vpl.VideoPlayerLayout,
        tmp_path: Path,
    ) -> None:
        """``is_audio_mode`` must be true only when the audio surface is current."""
        layout = video_player_layout
        assert layout.is_audio_mode is False

        audio_file = tmp_path / "check.mp3"
        audio_file.write_bytes(b"mp3-noise")
        assert layout.set_file(str(audio_file), is_audio=True) is True
        assert layout.is_audio_mode is True

        # Returning to overlay means not in audio mode.
        layout._stack.setCurrentIndex(1)
        assert layout.is_audio_mode is False


# =============================================================================
# 6. Helper for tests that need explicit lifecycle control
# =============================================================================


def _make_layout_with(
    qapp: Any,
    monkeypatch: pytest.MonkeyPatch,
    fake_mpv: FakeMPVManager,
    tags: Dict[str, Any] | None = None,
) -> vpl.VideoPlayerLayout:
    """Create a fresh ``VideoPlayerLayout`` with a fake MPV/metadata stack.

    Unlike the module-level ``video_player_layout`` fixture, this helper does
    not perform any teardown automatically. The caller must call
    ``layout.cleanup()`` when assertions are complete.
    """
    monkeypatch.setattr(vpl, "MPVManager", lambda: fake_mpv)
    monkeypatch.setenv("FAF_FORCE_FLUID_CPU", "1")
    monkeypatch.setattr(vpl, "MediaMetadataService", lambda: FakeMediaMetadataService(tags))
    return vpl.VideoPlayerLayout()


def _teardown_layout(
    layout: vpl.VideoPlayerLayout, cleanup: bool = True
) -> None:
    """Clean up a layout created with ``_make_layout_with``.

    Set ``cleanup=False`` when the test has already called ``cleanup()`` and
    only needs the widget closed.
    """
    if cleanup:
        layout.cleanup()
    layout.close()
    layout.deleteLater()
    QApplication.processEvents()


# =============================================================================
# 7. Control-bar routing in audio mode
# =============================================================================


class TestControlBarInAudioMode:
    """Verify audio mode reuses the same handlers as video mode."""

    def test_play_pause_routes_through_mpv(
        self,
        qapp: Any,
        monkeypatch: pytest.MonkeyPatch,
        fake_mpv: FakeMPVManager,
        tmp_path: Path,
    ) -> None:
        """``_on_play_pause`` must call play/pause with the layout's component id."""
        layout = _make_layout_with(qapp, monkeypatch, fake_mpv)
        audio_file = tmp_path / "ctrl_play.mp3"
        audio_file.write_bytes(b"mp3-noise")
        assert layout.set_file(str(audio_file), is_audio=True) is True

        # The initial load also emits a play(); record the count before toggling.
        plays_before = len(fake_mpv.play_calls)
        layout._player_bar.play_paused.emit(True)
        assert fake_mpv.play_calls[plays_before:] == [layout._component_id]

        layout._player_bar.play_paused.emit(False)
        assert fake_mpv.pause_calls == [layout._component_id]
        _teardown_layout(layout)

    def test_volume_routes_through_mpv(
        self,
        qapp: Any,
        monkeypatch: pytest.MonkeyPatch,
        fake_mpv: FakeMPVManager,
        tmp_path: Path,
    ) -> None:
        """``_on_volume_change`` must call set_volume in percent units."""
        layout = _make_layout_with(qapp, monkeypatch, fake_mpv)
        audio_file = tmp_path / "ctrl_vol.mp3"
        audio_file.write_bytes(b"mp3-noise")
        assert layout.set_file(str(audio_file), is_audio=True) is True

        layout._player_bar.volume_changed.emit(0.8)
        assert fake_mpv.set_volume_calls == [(80, layout._component_id)]
        _teardown_layout(layout)

    def test_speed_routes_through_mpv(
        self,
        qapp: Any,
        monkeypatch: pytest.MonkeyPatch,
        fake_mpv: FakeMPVManager,
        tmp_path: Path,
    ) -> None:
        """``_on_speed_change`` must parse the speed string and call set_speed."""
        layout = _make_layout_with(qapp, monkeypatch, fake_mpv)
        audio_file = tmp_path / "ctrl_speed.mp3"
        audio_file.write_bytes(b"mp3-noise")
        assert layout.set_file(str(audio_file), is_audio=True) is True

        layout._player_bar.speed_changed.emit("1.5x")
        assert fake_mpv.set_speed_calls == [(1.5, layout._component_id)]
        _teardown_layout(layout)

    def test_seek_routes_through_mpv(
        self,
        qapp: Any,
        monkeypatch: pytest.MonkeyPatch,
        fake_mpv: FakeMPVManager,
        tmp_path: Path,
    ) -> None:
        """``_on_progress_seek`` flushed on release must call seek with seconds."""
        layout = _make_layout_with(qapp, monkeypatch, fake_mpv)
        audio_file = tmp_path / "ctrl_seek.mp3"
        audio_file.write_bytes(b"mp3-noise")
        assert layout.set_file(str(audio_file), is_audio=True) is True

        layout._duration = 100.0
        layout._player_bar.progress_pressed.emit()
        layout._player_bar.progress_changed.emit(0.5)
        layout._player_bar.progress_released.emit()

        assert fake_mpv.seek_calls == [(50.0, layout._component_id)]
        _teardown_layout(layout)


# =============================================================================
# 8. Fullscreen target selection
# =============================================================================


class TestFullscreenTarget:
    """Verify fullscreen uses the currently visible stacked widget as target."""

    def test_audio_fullscreen_targets_audio_surface(
        self,
        qapp: Any,
        monkeypatch: pytest.MonkeyPatch,
        fake_mpv: FakeMPVManager,
        tmp_path: Path,
    ) -> None:
        """In audio mode ``enter_floating_mode`` must receive ``_audio_surface``
        and the layout must detach into a frameless fullscreen host instead of
        fullscreening the embedding window."""
        layout = _make_layout_with(qapp, monkeypatch, fake_mpv)
        audio_file = tmp_path / "fs_audio.mp3"
        audio_file.write_bytes(b"mp3-noise")
        assert layout.set_file(str(audio_file), is_audio=True) is True

        captured: list[Any] = []

        def _capture_enter(target_widget: Any, screen_geometry: Any) -> None:
            captured.append(target_widget)

        monkeypatch.setattr(layout._player_bar, "enter_floating_mode", _capture_enter)
        monkeypatch.setattr(
            layout._player_bar, "exit_floating_mode", lambda: None
        )

        layout._player_bar.fullscreen_toggled.emit(True)
        assert len(captured) == 1
        assert captured[0] is layout._audio_surface
        # 分离到独立 frameless 宿主窗口，而不是全屏主窗口
        assert layout._fullscreen_host is not None
        assert layout.window() is layout._fullscreen_host
        assert layout._fullscreen_host.isFullScreen()

        layout._player_bar.fullscreen_toggled.emit(False)
        assert layout._fullscreen_host is None
        _teardown_layout(layout)

    def test_video_fullscreen_targets_video_surface(
        self,
        qapp: Any,
        monkeypatch: pytest.MonkeyPatch,
        fake_mpv: FakeMPVManager,
        tmp_path: Path,
    ) -> None:
        """In video mode ``enter_floating_mode`` must receive ``_video_surface``
        and the layout must detach into a frameless fullscreen host."""
        layout = _make_layout_with(qapp, monkeypatch, fake_mpv)
        video_file = tmp_path / "fs_video.mp4"
        video_file.write_bytes(b"mp4-noise")
        assert layout.set_file(str(video_file), is_audio=False) is True

        captured: list[Any] = []

        def _capture_enter(target_widget: Any, screen_geometry: Any) -> None:
            captured.append(target_widget)

        monkeypatch.setattr(layout._player_bar, "enter_floating_mode", _capture_enter)
        monkeypatch.setattr(layout._player_bar, "exit_floating_mode", lambda: None)

        layout._player_bar.fullscreen_toggled.emit(True)
        assert len(captured) == 1
        assert captured[0] is layout._video_surface
        # 分离到独立 frameless 宿主窗口，而不是全屏主窗口
        assert layout._fullscreen_host is not None
        assert layout.window() is layout._fullscreen_host
        assert layout._fullscreen_host.isFullScreen()

        layout._player_bar.fullscreen_toggled.emit(False)
        assert layout._fullscreen_host is None
        _teardown_layout(layout)


# =============================================================================
# 9. Lifecycle and cleanup
# =============================================================================


class TestLifecycleAndCleanup:
    """Verify cleanup removes MPV, heartbeat, and fluid background state."""

    def test_cleanup_unregisters_layout_heartbeat_callback(
        self,
        qapp: Any,
        monkeypatch: pytest.MonkeyPatch,
        fake_mpv: FakeMPVManager,
    ) -> None:
        """After cleanup the layout's sync callback must be gone from HeartbeatManager."""
        layout = _make_layout_with(qapp, monkeypatch, fake_mpv)
        sync_id = f"video_player_layout_sync_{id(layout)}"
        hm = HeartbeatManager()
        assert sync_id in hm._callbacks

        layout.cleanup()

        assert sync_id not in hm._callbacks
        # No ``styled_fluid_bg_*`` callback may remain either, since nothing has
        # been loaded yet.
        assert not any(cid.startswith("styled_fluid_bg_") for cid in hm._callbacks)
        _teardown_layout(layout, cleanup=False)

    def test_cleanup_calls_fluid_background_unload(
        self,
        qapp: Any,
        monkeypatch: pytest.MonkeyPatch,
        fake_mpv: FakeMPVManager,
        tmp_path: Path,
    ) -> None:
        """``cleanup()`` must call ``_fluid_background.unload()`` exactly once."""
        layout = _make_layout_with(qapp, monkeypatch, fake_mpv)
        audio_file = tmp_path / "cleanup_fluid.mp3"
        audio_file.write_bytes(b"mp3-noise")
        assert layout.set_file(str(audio_file), is_audio=True) is True

        unload_calls: list[Any] = []
        original_unload = layout._fluid_background.unload

        def _wrapped_unload() -> None:
            unload_calls.append(True)
            original_unload()

        monkeypatch.setattr(layout._fluid_background, "unload", _wrapped_unload)

        layout.cleanup()
        assert len(unload_calls) == 1
        _teardown_layout(layout, cleanup=False)

    def test_cleanup_after_audio_load_leaves_no_heartbeat_callbacks(
        self,
        qapp: Any,
        monkeypatch: pytest.MonkeyPatch,
        fake_mpv: FakeMPVManager,
        tmp_path: Path,
    ) -> None:
        """``cleanup()`` must remove both the layout sync and fluid animation callbacks."""
        layout = _make_layout_with(qapp, monkeypatch, fake_mpv)
        audio_file = tmp_path / "cleanup_callbacks.mp3"
        audio_file.write_bytes(b"mp3-noise")
        assert layout.set_file(str(audio_file), is_audio=True) is True

        sync_id = f"video_player_layout_sync_{id(layout)}"
        hm = HeartbeatManager()
        assert sync_id in hm._callbacks

        # The fluid background only animates (and therefore only registers a
        # heartbeat callback) in GPU mode.  CPU mode is static and leaves no
        # callback behind.
        renderer = layout._fluid_background.renderer()
        if renderer == "gpu":
            assert any(cid.startswith("styled_fluid_bg_") for cid in hm._callbacks)
        else:
            assert not any(cid.startswith("styled_fluid_bg_") for cid in hm._callbacks)

        layout.cleanup()

        assert sync_id not in hm._callbacks
        assert not any(cid.startswith("styled_fluid_bg_") for cid in hm._callbacks)
        _teardown_layout(layout, cleanup=False)

    def test_cleanup_hides_music_info_panel(
        self,
        qapp: Any,
        monkeypatch: pytest.MonkeyPatch,
        fake_mpv: FakeMPVManager,
        tmp_path: Path,
    ) -> None:
        """After cleanup the music info panel should be hidden."""
        layout = _make_layout_with(qapp, monkeypatch, fake_mpv)
        audio_file = tmp_path / "cleanup_hide.mp3"
        audio_file.write_bytes(b"mp3-noise")
        assert layout.set_file(str(audio_file), is_audio=True) is True

        layout.cleanup()
        assert layout._music_info_panel.isHidden()
        _teardown_layout(layout, cleanup=False)

    def test_rapid_audio_switches_do_not_leak(
        self,
        qapp: Any,
        monkeypatch: pytest.MonkeyPatch,
        fake_mpv: FakeMPVManager,
        tmp_path: Path,
    ) -> None:
        """Switching audio files repeatedly must not grow MPV components or callbacks."""
        layout = _make_layout_with(qapp, monkeypatch, fake_mpv)
        hm = HeartbeatManager()

        audio_file_1 = tmp_path / "switch_1.mp3"
        audio_file_2 = tmp_path / "switch_2.mp3"
        audio_file_3 = tmp_path / "switch_3.mp3"
        audio_file_1.write_bytes(b"mp3-1")
        audio_file_2.write_bytes(b"mp3-2")
        audio_file_3.write_bytes(b"mp3-3")

        assert layout.set_file(str(audio_file_1), is_audio=True) is True
        expected_component_count = len(fake_mpv.register_calls)
        expected_callback_count = len(hm._callbacks)

        assert layout.set_file(str(audio_file_2), is_audio=True) is True
        assert len(fake_mpv.register_calls) == expected_component_count
        assert len(hm._callbacks) == expected_callback_count

        assert layout.set_file(str(audio_file_3), is_audio=True) is True
        assert len(fake_mpv.register_calls) == expected_component_count
        assert len(hm._callbacks) == expected_callback_count

        _teardown_layout(layout)


# =============================================================================
# 10. Theme update during audio playback
# =============================================================================


class TestThemeUpdateInAudioMode:
    """Verify theme changes reach the fluid background while audio is playing."""

    def test_colors_updated_rebuilds_accent_palette(
        self,
        qapp: Any,
        monkeypatch: pytest.MonkeyPatch,
        fake_mpv: FakeMPVManager,
        tmp_path: Path,
    ) -> None:
        """``tm.colors_updated`` must trigger the fluid background palette update."""
        from PySide6.QtWidgets import QApplication

        layout = _make_layout_with(qapp, monkeypatch, fake_mpv)
        audio_file = tmp_path / "theme_audio.mp3"
        audio_file.write_bytes(b"mp3-noise")
        assert layout.set_file(str(audio_file), is_audio=True) is True

        # In StyledFluidBackground v2 the ``colors_updated`` signal is handled
        # by ``_on_colors_updated`` -> ``_refresh_for_theme``, which rebuilds
        # the accent palette internally rather than calling ``use_accent_theme``.
        # We verify this by changing ``tm.accent`` and checking the palette.
        pre_palette = layout._fluid_background.colors()

        old_primary = tm._colors["accent"]["primary"]
        try:
            tm._colors["accent"]["primary"] = "#00FF00"  # clearly different accent
            tm.colors_updated.emit({})
            QApplication.processEvents()
            post_palette = layout._fluid_background.colors()

            assert len(post_palette) == len(pre_palette)
            assert any(a != b for a, b in zip(pre_palette, post_palette))
        finally:
            tm._colors["accent"]["primary"] = old_primary

        _teardown_layout(layout)
