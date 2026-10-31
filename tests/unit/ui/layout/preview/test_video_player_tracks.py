# -*- coding: utf-8 -*-
"""VideoPlayerLayout 音轨/字幕轨真实接线测试。

覆盖：
* 文件加载后后台采集 mpv 音轨/字幕轨并映射填充 StyledPlayerBar 缓存
  （label 优先 title，否则 lang + 编码/声道，最后回退序号；字幕末尾追加
  「+ 添加…」项）；
* ``setting_changed("audio"|"subtitle", id)`` → 解析 int 调用
  MPVManager.set_audio_track / set_subtitle_track（component_id 透传）；
* ``add_subtitle_requested`` → QFileDialog 选择后调用 load_subtitle，
  取消不动；
* 无效轨道 ID 仅警告不崩溃。

MPV 管理器用 MagicMock 假对象替换（不真实播放）；布局显示在宿主窗口上
以满足「预览器可见」前置条件，后台任务经有界事件泵等待完成。
"""

from __future__ import annotations

import time
from typing import Any, Callable

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
from unittest.mock import MagicMock

from sopeek.ui.layout.preview.video_player_layout import VideoPlayerLayout

pytestmark = pytest.mark.unit

_AUDIO_TRACKS = [
    {
        "id": 1,
        "title": "中文 5.1",
        "lang": "chi",
        "codec": "aac",
        "audio_channels": "5.1",
        "selected": True,
    },
    {
        "id": 2,
        "title": "",
        "lang": "eng",
        "codec": "ac3",
        "audio_channels": "",
        "selected": False,
    },
    {"id": 3, "title": "", "lang": "", "codec": "", "selected": False},
]

_SUBTITLE_TRACKS = [
    {"id": 5, "title": "English", "lang": "eng", "selected": True},
    {"id": 6, "title": "", "lang": "chi", "selected": False},
]


def _pump(qapp: QApplication, ms: int = 30) -> None:
    """处理事件循环并等待指定毫秒（冲刷跨线程 queued 信号）。"""
    loop_quit = [False]

    def _timeout() -> None:
        loop_quit[0] = True

    QTimer.singleShot(ms, _timeout)
    while not loop_quit[0]:
        qapp.processEvents()


def _wait_until(
    qapp: QApplication, cond: Callable[[], bool], timeout: float = 5.0
) -> bool:
    """有界事件泵：轮询直到条件满足或超时。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    qapp.processEvents()
    return cond()


def _make_fake_mpv(
    audio: list, subtitles: list
) -> MagicMock:
    """构造假 MPVManager（含轨道查询/切换/字幕加载接口）。"""
    fake = MagicMock()
    fake.is_initialized.return_value = True
    fake.is_core_operational.return_value = True
    fake.get_audio_tracks.return_value = list(audio)
    fake.get_subtitle_tracks.return_value = list(subtitles)
    fake.get_duration.return_value = 10.0
    fake.get_position.return_value = 1.0
    fake.set_audio_track.return_value = True
    fake.set_subtitle_track.return_value = True
    fake.load_subtitle.return_value = True
    return fake


def _make_shown_layout(
    qapp: QApplication, fake_mpv: MagicMock
) -> tuple[VideoPlayerLayout, QWidget]:
    """构造布局并挂到已显示宿主窗口上（满足预览器可见条件）。"""
    layout = VideoPlayerLayout()
    layout._mpv_manager = fake_mpv  # noqa: SLF001
    # offscreen 下避免真实 OpenGL / 流体层初始化失败（音频模式才需要）
    layout._fluid_background.load = lambda: None  # type: ignore[method-assign]  # noqa: SLF001

    host = QWidget()
    host.resize(720, 480)
    box = QVBoxLayout(host)
    box.setContentsMargins(0, 0, 0, 0)
    box.addWidget(layout)
    host.show()
    _wait_until(qapp, layout.isVisible)
    return layout, host


def _teardown(
    qapp: QApplication, layout: VideoPlayerLayout, host: QWidget
) -> None:
    """等待在途轨道任务结束并销毁布局/宿主。"""
    _wait_until(qapp, lambda: len(layout._tracks_tasks) == 0)  # noqa: SLF001
    layout.cleanup()
    host.close()
    host.deleteLater()
    _pump(qapp)


def test_file_loaded_fills_mapped_tracks(
    qapp: QApplication, heartbeat_manager: Any
) -> None:
    """文件加载后 bar 收到映射后的音轨/字幕轨列表（label/selected/追加项）。"""
    fake = _make_fake_mpv(_AUDIO_TRACKS, _SUBTITLE_TRACKS)
    layout, host = _make_shown_layout(qapp, fake)
    try:
        layout._on_file_loaded("dummy.mkv")  # noqa: SLF001

        bar = layout._player_bar  # noqa: SLF001
        assert _wait_until(
            qapp,
            lambda: len(bar._last_audio_tracks) == 3  # noqa: SLF001
            and len(bar._last_subtitle_tracks) == 3,  # noqa: SLF001
        )

        assert bar._last_audio_tracks == [  # noqa: SLF001
            {"id": 1, "label": "中文 5.1", "selected": True},
            {"id": 2, "label": "eng ac3", "selected": False},
            {"id": 3, "label": "音轨 3", "selected": False},
        ]

        subtitles = bar._last_subtitle_tracks  # noqa: SLF001
        assert subtitles[:2] == [
            {"id": 5, "label": "English", "selected": True},
            {"id": 6, "label": "chi", "selected": False},
        ]
        assert subtitles[2] == {"id": "add", "label": "+ 添加…", "is_add": True}
        fake.get_audio_tracks.assert_called()
        fake.get_subtitle_tracks.assert_called()
    finally:
        _teardown(qapp, layout, host)


def test_setting_changed_switches_tracks(
    qapp: QApplication, heartbeat_manager: Any
) -> None:
    """setting_changed 发射后调用 set_audio_track/set_subtitle_track（int id + component_id）。"""
    fake = _make_fake_mpv(_AUDIO_TRACKS, _SUBTITLE_TRACKS)
    layout, host = _make_shown_layout(qapp, fake)
    try:
        layout._on_file_loaded("dummy.mkv")  # noqa: SLF001
        bar = layout._player_bar  # noqa: SLF001
        assert _wait_until(
            qapp,
            lambda: len(bar._last_audio_tracks) == 3,  # noqa: SLF001
        )

        bar.setting_changed.emit("audio", "2")
        fake.set_audio_track.assert_any_call(2, component_id=layout._component_id)

        bar.setting_changed.emit("subtitle", "5")
        fake.set_subtitle_track.assert_any_call(5, component_id=layout._component_id)

        # 切换成功后会异步刷新一次轨道列表（复用同一后台任务）
        assert _wait_until(qapp, lambda: fake.get_audio_tracks.call_count >= 2)
    finally:
        _teardown(qapp, layout, host)


def test_setting_changed_invalid_id_only_warns(
    qapp: QApplication, heartbeat_manager: Any
) -> None:
    """无效轨道 ID 仅警告日志，不调用 mpv 接口、不崩溃。"""
    fake = _make_fake_mpv([], [])
    layout, host = _make_shown_layout(qapp, fake)
    try:
        bar = layout._player_bar  # noqa: SLF001
        bar.setting_changed.emit("audio", "not-a-number")
        bar.setting_changed.emit("audio", "")
        fake.set_audio_track.assert_not_called()
        fake.set_subtitle_track.assert_not_called()
    finally:
        _teardown(qapp, layout, host)


def test_add_subtitle_requested_loads_file(
    qapp: QApplication, heartbeat_manager: Any, tmp_path: Any, monkeypatch: Any
) -> None:
    """「+ 添加…」选择字幕文件后调用 load_subtitle 并刷新字幕轨列表。"""
    fake = _make_fake_mpv([], _SUBTITLE_TRACKS)
    layout, host = _make_shown_layout(qapp, fake)
    try:
        layout._on_file_loaded("dummy.mkv")  # noqa: SLF001
        bar = layout._player_bar  # noqa: SLF001
        assert _wait_until(
            qapp,
            lambda: len(bar._last_subtitle_tracks) == 3,  # noqa: SLF001
        )
        initial_calls = fake.get_subtitle_tracks.call_count

        subtitle_file = tmp_path / "movie.srt"
        subtitle_file.write_text(
            "1\n00:00:01,000 --> 00:00:02,000\nhello\n", encoding="utf-8"
        )
        monkeypatch.setattr(
            "PySide6.QtWidgets.QFileDialog.getOpenFileName",
            lambda *args, **kwargs: (str(subtitle_file), "字幕文件 (*.srt)"),
        )

        bar.add_subtitle_requested.emit()
        _wait_until(qapp, lambda: fake.load_subtitle.call_count == 1)
        fake.load_subtitle.assert_any_call(
            str(subtitle_file), component_id=layout._component_id
        )
        # 加载成功后异步刷新字幕轨
        assert _wait_until(
            qapp, lambda: fake.get_subtitle_tracks.call_count > initial_calls
        )
    finally:
        _teardown(qapp, layout, host)


def test_add_subtitle_cancel_does_nothing(
    qapp: QApplication, heartbeat_manager: Any, monkeypatch: Any
) -> None:
    """文件对话框取消（空路径）时不调用 load_subtitle。"""
    fake = _make_fake_mpv([], [])
    layout, host = _make_shown_layout(qapp, fake)
    try:
        monkeypatch.setattr(
            "PySide6.QtWidgets.QFileDialog.getOpenFileName",
            lambda *args, **kwargs: ("", ""),
        )
        bar = layout._player_bar  # noqa: SLF001
        bar.add_subtitle_requested.emit()
        _pump(qapp, 50)
        fake.load_subtitle.assert_not_called()
    finally:
        _teardown(qapp, layout, host)
