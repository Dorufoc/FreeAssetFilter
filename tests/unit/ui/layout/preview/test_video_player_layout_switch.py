# -*- coding: utf-8 -*-
"""VideoPlayerLayout 布局切换挂起/恢复单元测试。

覆盖 ``suspend_for_layout_switch`` / ``resume_after_layout_switch`` /
``_apply_layout_switch_resume`` 三个接缝：

* 挂起快照：优先 mpv 播放位置、回退本地进度；播放态查询异常按暂停处理；
  无当前文件时快照为 None 但仍停止播放并切回遮罩层；
* 恢复加载：重载原文件并武装 pending 快照（seek/暂停延后到 fileLoaded）；
  原文件已不存在时静默跳过；
* 快照应用：fileLoaded 集成路径还原进度与暂停态；播放态仅 seek 不 pause；
  位置为 0 跳过 seek；加载文件与快照不一致时作废快照。

MPV 管理器用 MagicMock 假对象替换（不真实播放）；布局不显示（不可见时
轨道采集自动跳过），仅验证状态机与 mpv 调用契约。
"""

from __future__ import annotations

import os
import time
from typing import Any
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from freeassetfilter.ui.layout.preview.video_player_layout import VideoPlayerLayout

pytestmark = pytest.mark.unit


def _pump(qapp: QApplication, ms: int = 30) -> None:
    """处理事件循环并等待指定毫秒（冲刷单发定时器等 queued 回调）。"""
    loop_quit = [False]

    def _timeout() -> None:
        loop_quit[0] = True

    QTimer.singleShot(ms, _timeout)
    while not loop_quit[0]:
        qapp.processEvents()


def _wait_for(qapp: QApplication, predicate: Any, timeout_ms: int = 1500) -> None:
    """等待线程池任务落地（``stop`` / ``load_file`` / ``play`` 均为异步投递）。"""
    elapsed = 0
    while not predicate() and elapsed < timeout_ms:
        _pump(qapp, 10)
        elapsed += 10


def _make_fake_mpv() -> MagicMock:
    """构造假 MPVManager（核心可用、可加载、位置从 0 开始）。"""
    fake = MagicMock()
    fake.is_initialized.return_value = True
    fake.is_core_operational.return_value = True
    fake.get_position.return_value = 0.0
    fake.get_duration.return_value = 10.0
    fake.is_playing.return_value = False
    fake.is_paused.return_value = False
    fake.load_file.return_value = True
    fake.play.return_value = True
    fake.seek.return_value = True
    fake.pause.return_value = True
    fake.stop.return_value = True
    fake.set_loop.return_value = True
    return fake


def _make_layout(fake_mpv: MagicMock) -> VideoPlayerLayout:
    """构造布局并替换 MPV 管理器（不显示，轨道采集因不可见自动跳过）。"""
    layout = VideoPlayerLayout()
    layout._mpv_manager = fake_mpv  # noqa: SLF001
    # 假 MPV 无原生窗口：标记已嵌入，跳过 winId 原生嵌入路径
    layout._is_mpv_embedded = True  # noqa: SLF001
    return layout


def _teardown(qapp: QApplication, layout: VideoPlayerLayout) -> None:
    """销毁布局并冲刷 Qt 事件（DeferredDelete 落地）。"""
    layout.cleanup()
    layout.deleteLater()
    _pump(qapp)


def _norm(path: str) -> str:
    """路径规范化（与实现内 normcase+abspath 快照口径一致）。"""
    return os.path.normcase(os.path.abspath(path))


def test_suspend_snapshots_state_and_stops(
    qapp: QApplication, heartbeat_manager: Any
) -> None:
    """挂起：优先 mpv 播放位置、记录播放态，随后停止并显示遮罩层。"""
    fake = _make_fake_mpv()
    fake.get_position.return_value = 30.0
    fake.is_playing.return_value = True
    fake.is_paused.return_value = False
    layout = _make_layout(fake)
    try:
        layout._current_file = "C:/media/clip.mp4"  # noqa: SLF001
        layout._current_position = 12.5  # noqa: SLF001
        layout._stack.setCurrentIndex(0)  # 预置视频表面，验证挂起后切到遮罩层  # noqa: SLF001
        layout.suspend_for_layout_switch()

        # stop 由 _ManagerStopTask 异步投递到全局线程池
        _wait_for(qapp, lambda: fake.stop.called)

        assert layout._layout_switch_suspend_state == {  # noqa: SLF001
            "file": "C:/media/clip.mp4",
            "is_audio": False,
            "position": 30.0,
            "was_playing": True,
        }
        fake.stop.assert_called_once_with(component_id=layout._component_id)
        assert layout._stack.currentIndex() == 1  # noqa: SLF001
    finally:
        _teardown(qapp, layout)


def test_suspend_falls_back_to_local_position_and_paused_state(
    qapp: QApplication, heartbeat_manager: Any
) -> None:
    """挂起：mpv 位置为 0 时回退本地进度；播放态查询异常按暂停处理。"""
    fake = _make_fake_mpv()
    fake.get_position.return_value = 0.0
    fake.is_playing.side_effect = RuntimeError("mpv state unavailable")
    layout = _make_layout(fake)
    try:
        layout._current_file = "C:/media/song.mp3"  # noqa: SLF001
        layout._current_media_is_audio = True  # noqa: SLF001
        layout._current_position = 42.0  # noqa: SLF001
        layout.suspend_for_layout_switch()

        assert layout._layout_switch_suspend_state == {  # noqa: SLF001
            "file": "C:/media/song.mp3",
            "is_audio": True,
            "position": 42.0,
            "was_playing": False,
        }
    finally:
        _teardown(qapp, layout)


def test_suspend_without_file_keeps_none_state_but_stops(
    qapp: QApplication, heartbeat_manager: Any
) -> None:
    """挂起：无当前文件时快照为 None，但仍执行停止与遮罩切换。"""
    fake = _make_fake_mpv()
    layout = _make_layout(fake)
    try:
        layout._stack.setCurrentIndex(0)  # 预置视频表面，验证挂起后切到遮罩层  # noqa: SLF001
        layout.suspend_for_layout_switch()

        # stop 由 _ManagerStopTask 异步投递到全局线程池
        _wait_for(qapp, lambda: fake.stop.called)

        assert layout._layout_switch_suspend_state is None  # noqa: SLF001
        fake.stop.assert_called_once_with(component_id=layout._component_id)
        assert layout._stack.currentIndex() == 1  # noqa: SLF001
    finally:
        _teardown(qapp, layout)


def test_resume_reloads_file_and_arms_pending(
    qapp: QApplication, heartbeat_manager: Any, tmp_path: Any
) -> None:
    """恢复：重新加载原文件并武装 pending 快照（seek/暂停延后到 fileLoaded）。"""
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 16)
    fake = _make_fake_mpv()
    layout = _make_layout(fake)
    try:
        layout._layout_switch_suspend_state = {  # noqa: SLF001
            "file": str(video),
            "is_audio": False,
            "position": 7.5,
            "was_playing": False,
        }
        layout.resume_after_layout_switch()

        # load/play 由 _MediaLoadTask 投递到全局线程池异步执行，等任务落地再断言
        _wait_for(qapp, lambda: fake.play.called)

        assert layout._layout_switch_suspend_state is None  # noqa: SLF001
        assert layout._layout_switch_resume_pending == {  # noqa: SLF001
            "file": _norm(str(video)),
            "position": 7.5,
            "was_playing": False,
        }
        fake.load_file.assert_called_once_with(
            str(video), is_audio=False, component_id=layout._component_id
        )
        fake.play.assert_called_once_with(component_id=layout._component_id)
        # seek/暂停延后到 fileLoaded（_apply_layout_switch_resume）执行
        fake.seek.assert_not_called()
        fake.pause.assert_not_called()
        assert layout._current_file == str(video)  # noqa: SLF001
    finally:
        _teardown(qapp, layout)


def test_resume_missing_file_discards_snapshot(
    qapp: QApplication, heartbeat_manager: Any, tmp_path: Any
) -> None:
    """恢复：原文件已不存在时静默跳过（不加载、不武装 pending）。"""
    missing = tmp_path / "gone.mp4"
    fake = _make_fake_mpv()
    layout = _make_layout(fake)
    try:
        layout._layout_switch_suspend_state = {  # noqa: SLF001
            "file": str(missing),
            "is_audio": False,
            "position": 7.5,
            "was_playing": True,
        }
        layout.resume_after_layout_switch()

        assert layout._layout_switch_suspend_state is None  # noqa: SLF001
        assert layout._layout_switch_resume_pending is None  # noqa: SLF001
        fake.load_file.assert_not_called()
    finally:
        _teardown(qapp, layout)


def test_file_loaded_applies_pending_seek_and_pause(
    qapp: QApplication, heartbeat_manager: Any, tmp_path: Any
) -> None:
    """fileLoaded 集成路径：快照匹配后还原进度并暂停、切回视频表面。"""
    video = tmp_path / "clip.mp4"
    fake = _make_fake_mpv()
    layout = _make_layout(fake)
    try:
        layout._layout_switch_resume_pending = {  # noqa: SLF001
            "file": _norm(str(video)),
            "position": 7.5,
            "was_playing": False,
        }
        layout._on_file_loaded(str(video))  # noqa: SLF001

        fake.seek.assert_called_once_with(7.5, component_id=layout._component_id)
        fake.pause.assert_called_once_with(component_id=layout._component_id)
        fake.set_loop.assert_called_once_with("yes", component_id=layout._component_id)
        assert layout._layout_switch_resume_pending is None  # noqa: SLF001
        assert layout._stack.currentIndex() == 0  # noqa: SLF001
    finally:
        # 冲刷 _on_file_loaded 内 200ms 进度初始化 singleShot，确保定时器在布局存活期触发
        _pump(qapp, 260)
        _teardown(qapp, layout)


def test_apply_resume_keeps_playing_without_pause(
    qapp: QApplication, heartbeat_manager: Any, tmp_path: Any
) -> None:
    """恢复应用：原为播放态时仅 seek 还原进度、不调用 pause。"""
    video = tmp_path / "clip.mp4"
    fake = _make_fake_mpv()
    layout = _make_layout(fake)
    try:
        layout._layout_switch_resume_pending = {  # noqa: SLF001
            "file": _norm(str(video)),
            "position": 7.5,
            "was_playing": True,
        }
        layout._apply_layout_switch_resume(str(video))  # noqa: SLF001

        fake.seek.assert_called_once_with(7.5, component_id=layout._component_id)
        fake.pause.assert_not_called()
        assert layout._layout_switch_resume_pending is None  # noqa: SLF001
    finally:
        _teardown(qapp, layout)


def test_apply_resume_skips_seek_at_zero_position(
    qapp: QApplication, heartbeat_manager: Any, tmp_path: Any
) -> None:
    """恢复应用：位置为 0 时跳过 seek，仅按暂停态调用 pause。"""
    video = tmp_path / "clip.mp4"
    fake = _make_fake_mpv()
    layout = _make_layout(fake)
    try:
        layout._layout_switch_resume_pending = {  # noqa: SLF001
            "file": _norm(str(video)),
            "position": 0.0,
            "was_playing": False,
        }
        layout._apply_layout_switch_resume(str(video))  # noqa: SLF001

        fake.seek.assert_not_called()
        fake.pause.assert_called_once_with(component_id=layout._component_id)
    finally:
        _teardown(qapp, layout)


def test_apply_resume_discards_pending_on_file_mismatch(
    qapp: QApplication, heartbeat_manager: Any, tmp_path: Any
) -> None:
    """恢复应用：加载文件与快照不一致（被抢占）时作废快照且不还原。"""
    video = tmp_path / "clip.mp4"
    other = tmp_path / "other.mp4"
    fake = _make_fake_mpv()
    layout = _make_layout(fake)
    try:
        layout._layout_switch_resume_pending = {  # noqa: SLF001
            "file": _norm(str(other)),
            "position": 7.5,
            "was_playing": False,
        }
        layout._apply_layout_switch_resume(str(video))  # noqa: SLF001

        assert layout._layout_switch_resume_pending is None  # noqa: SLF001
        fake.seek.assert_not_called()
        fake.pause.assert_not_called()
    finally:
        _teardown(qapp, layout)


def test_suspend_twice_reuses_first_snapshot(
    qapp: QApplication, heartbeat_manager: Any
) -> None:
    """挂起：恢复尚未执行时重复挂起复用首份快照，不重复停止。"""
    fake = _make_fake_mpv()
    fake.get_position.return_value = 30.0
    fake.is_playing.return_value = True
    fake.is_paused.return_value = False
    layout = _make_layout(fake)
    try:
        layout._current_file = "C:/media/clip.mp4"  # noqa: SLF001
        layout._current_position = 12.5  # noqa: SLF001
        layout.suspend_for_layout_switch()

        first_state = layout._layout_switch_suspend_state  # noqa: SLF001
        assert first_state == {
            "file": "C:/media/clip.mp4",
            "is_audio": False,
            "position": 30.0,
            "was_playing": True,
        }

        # 模拟首次挂起的停止已生效：位置归零、不再播放
        fake.get_position.return_value = 0.0
        fake.is_playing.return_value = False
        layout.suspend_for_layout_switch()

        assert layout._layout_switch_suspend_state is first_state  # noqa: SLF001
        assert layout._layout_switch_suspend_state == {  # noqa: SLF001
            "file": "C:/media/clip.mp4",
            "is_audio": False,
            "position": 30.0,
            "was_playing": True,
        }
        # P6.3：``stop_playback`` 经命名池异步执行 stop（不阻塞 UI），
        # 因此这里需等待后台任务落地，而非同步断言。
        deadline = time.monotonic() + 2.0
        while not fake.stop.called and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.01)
        fake.stop.assert_called_once_with(component_id=layout._component_id)
    finally:
        _teardown(qapp, layout)
