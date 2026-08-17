# -*- coding: utf-8 -*-
"""MPVManager（core/managers/mpv_manager.py）单元测试。

todo-8（unit/core 批 2）验收口径：
* **所有视频播放必须经过此管理器**（AGENTS.md 全局约束）——覆盖队列锁语义、
  单例语义、状态快照、信号转发；
* 线程安全：提交操作、关闭路径都会结束操作线程 / MPVWorkerThread，
  teardown 使用 ``_do_close()`` + ``_stop_operation_thread()`` 强制收尾
  （``close(async_mode=True)`` 已知不完整：异步线程不一定跑完，见 learnings）；
* mock 分支全部拦截 ``MPVPlayerCore`` 与 LuaJIT VEH 注册，**零真实 DLL 副作用**；
* 真实分支由 ``mpv_available``（session 级）门控，播放 WAV 走完整
  initialize → load_file → play → stop → close 链路。

实现约束（来自过程探针）：
* ``MPVManager`` 单例用类属性 ``_instance``/``_instance_lock`` +
  实例级 ``_initialized``；conftest 的 ``reset_singletons`` 仅清 ``_instance``。
* ``_do_initialize`` 会先 connect core 信号再调 ``MPVPlayerCore.initialize()``；
  之后才 ``_register_luajit_veh()``（真实 VirtualAlloc）。mock 分支必须
  patch 掉该注册，避免分配可执行内存。
* ``close(async_mode=False)`` 走 ``_do_sync_close``：提交 CLOSE 操作 + 停线程。
"""

from __future__ import annotations

import os
import wave
from unittest.mock import MagicMock, patch

import pytest
from pytest import MonkeyPatch

from freeassetfilter.core.managers.mpv_manager import (
    MPVManager,
    MPVState,
)
from tests.support.qt_helpers import (
    process_qt_events,
    wait_for_signal,
)


# =============================================================================
# 工具
# =============================================================================
def _make_wav(tmp_path: object) -> str:
    """生成 0.5s 单声道 8kHz 16bit 的 WAV（MPV 可加载的最小真实媒体）。"""
    path: str = str(tmp_path / "tone.wav")
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x00\x00" * 4000)
    return path


def _force_close(manager: MPVManager) -> None:
    """强制收尾：直接核心关闭 + 停止操作线程（真实分支专用）。"""
    try:
        if manager._mpv_core is not None:  # noqa: SLF001
            manager._do_close()  # noqa: SLF001
    except Exception:
        pass
    if manager._operation_thread and manager._operation_thread.is_alive():  # noqa: SLF001
        manager._stop_operation_thread(2.0)  # noqa: SLF001


# =============================================================================
# Mock 分支（恒运行，无真实 DLL）
# =============================================================================
class TestSingletonAndDefaults:
    """单例语义与初始状态。"""

    def test_singleton_returns_same_instance(self, qapp: object) -> None:
        """同一进程内 ``MPVManager()`` 恒返回同一实例。"""
        from freeassetfilter.core.managers.mpv_manager import MPVManager as M

        first: M = M()
        second: M = M()
        assert first is second
        assert M._instance is first  # noqa: SLF001

    def test_not_initialized_and_default_state(self, qapp: object) -> None:
        """构造后 ``is_initialized()`` False，``get_state()`` 返回默认快照。"""
        manager: MPVManager = MPVManager()
        assert manager.is_initialized() is False
        state: MPVState = manager.get_state()
        assert state.is_initialized is False
        assert state.is_playing is False
        assert state.current_file == ""
        assert state.volume == 100
        assert state.speed == 1.0

    def test_submit_operations_rejected_while_shutting_down(self, qapp: object) -> None:
        """关闭中提交操作返回 False（RuntimeError 被吞），不启动线程。"""
        manager: MPVManager = MPVManager()
        manager._is_shutting_down = True  # noqa: SLF001
        assert manager.play() is False
        assert manager.pause() is False
        assert manager.stop() is False
        assert manager.load_file(r"C:\fake\media.mp4") is False
        assert manager.set_volume(50) is False
        assert manager.set_speed(1.5) is False
        assert manager.seek(10.0) is False
        assert manager._operation_thread is None  # noqa: SLF001

    def test_state_changed_signal_emits_mpvstate(self, qapp: object) -> None:
        """``_emit_state_changed_now`` 同步发射 ``stateChanged(MPVState)``。"""
        manager: MPVManager = MPVManager()
        got: list = []

        def _spy(state: MPVState) -> None:
            got.append(state)

        manager.stateChanged.connect(_spy)
        manager._emit_state_changed_now()  # noqa: SLF001
        process_qt_events(qapp, ms=0)
        assert len(got) == 1
        assert isinstance(got[0], MPVState)
        manager.stateChanged.disconnect(_spy)

    def test_initialize_mocked_core(self, qapp: object, monkeypatch: MonkeyPatch) -> None:
        """mock 核心：``initialize()`` 返回 True 且 ``is_initialized()`` True。"""
        manager: MPVManager = MPVManager()
        # 拦截 LuaJIT VEH（真实 VirtualAlloc 副作用）
        monkeypatch.setattr(manager, "_register_luajit_veh", lambda: None)
        monkeypatch.setattr(manager, "_unregister_luajit_veh", lambda: None)

        fake_core: MagicMock = MagicMock()
        fake_core.initialize.return_value = True
        with patch(
            "freeassetfilter.core.managers.mpv_manager.MPVPlayerCore",
            return_value=fake_core,
        ):
            assert manager.initialize(timeout=5.0) is True
            assert manager.is_initialized() is True

        # 强制收尾：停操作线程 + 核心置空
        manager._operation_thread is not None and manager._operation_thread.is_alive() and manager._stop_operation_thread(2.0)  # noqa: SLF001
        manager._mpv_core = None  # noqa: SLF001
        assert manager.is_initialized() is False


# =============================================================================
# 真实分支（需 libmpv-2.dll）
# =============================================================================
class TestRealMpvLifecycle:
    """真实 MPV：初始化 → 加载 → 播放 → 停止 → 关闭。"""

    @staticmethod
    def _can_run(mpv_available: bool) -> bool:
        return mpv_available

    def test_real_init_load_play_stop(
        self, qapp: object, mpv_available: bool, tmp_path: object
    ) -> None:
        """完整生命周期：全部操作返回 True，状态随文件加载更新。"""
        if not mpv_available:
            pytest.skip("libmpv-2.dll 不可用")
        wav: str = _make_wav(tmp_path)
        manager: MPVManager = MPVManager()

        try:
            assert manager.initialize(timeout=15.0) is True
            process_qt_events(qapp, ms=50)
            assert manager.is_initialized() is True

            assert manager.load_file(wav, is_audio=True, timeout=30.0) is True
            process_qt_events(qapp, ms=100)
            state: MPVState = manager.get_state()
            assert state.current_file.lower() == os.path.abspath(wav).lower()

            assert manager.play() is True
            process_qt_events(qapp, ms=100)
            assert manager.stop() is True
            process_qt_events(qapp, ms=100)
        finally:
            _force_close(manager)

    def test_real_file_loaded_signal(
        self, qapp: object, mpv_available: bool, tmp_path: object
    ) -> None:
        """真实加载后 ``fileLoaded`` 信号在超时内被发射。"""
        if not mpv_available:
            pytest.skip("libmpv-2.dll 不可用")
        wav: str = _make_wav(tmp_path)
        manager: MPVManager = MPVManager()

        try:
            assert manager.initialize(timeout=15.0) is True
            process_qt_events(qapp, ms=50)
            assert manager.load_file(wav, is_audio=True, timeout=30.0) is True
            assert wait_for_signal(manager.fileLoaded, timeout_ms=5000) is True
        finally:
            _force_close(manager)
            process_qt_events(qapp, ms=50)

    def test_real_sync_close_cleans_up(
        self, qapp: object, mpv_available: bool, tmp_path: object
    ) -> None:
        """同步关�闭后：``is_initialized()`` False、线程全部退出、可靠再次初始化。"""
        if not mpv_available:
            pytest.skip("libmpv-2.dll 不可用")
        wav: str = _make_wav(tmp_path)
        manager: MPVManager = MPVManager()

        assert manager.initialize(timeout=15.0) is True
        process_qt_events(qapp, ms=50)
        assert manager.load_file(wav, is_audio=True, timeout=30.0) is True
        process_qt_events(qapp, ms=100)

        assert manager.close(async_mode=False, timeout=5.0) is True
        process_qt_events(qapp, ms=50)

        assert manager._mpv_core is None  # noqa: SLF001
        assert manager.is_initialized() is False
        op_thread = manager._operation_thread  # noqa: SLF001
        assert op_thread is None or not op_thread.is_alive()

        # 关闭后仍可再次初始化（幂等可恢复）
        assert manager.initialize(timeout=15.0) is True
        _force_close(manager)
        process_qt_events(qapp, ms=50)


# =============================================================================
# MPVOperation / MPVOperationType / get_mpv_manager
# =============================================================================
class TestMpvOperationTypes:
    """MPVOperationType 枚举与 MPVOperation 数据类契约。"""

    def test_operation_type_values(self) -> None:
        """枚举值覆盖全部操作类型（含初始化/关闭/字幕/音频）。"""
        from freeassetfilter.core.managers.mpv_manager import MPVOperationType

        assert MPVOperationType.INITIALIZE.value == "initialize"
        assert MPVOperationType.LOAD_FILE.value == "load_file"
        assert MPVOperationType.SET_SUBTITLE_TRACK.value == "set_subtitle_track"
        assert MPVOperationType.GET_AUDIO_STATE.value == "get_audio_state"
        values: set = {member.name for member in MPVOperationType}
        assert {"PLAY", "STOP", "SEEK", "SET_VOLUME", "LOAD_LUT", "UNLOAD_LUT"} <= values

    def test_operation_dataclass_defaults(self) -> None:
        """默认字段：priority=5、component_id=unknown、args/kwargs 空。"""
        from freeassetfilter.core.managers.mpv_manager import MPVOperation, MPVOperationType

        op: MPVOperation = MPVOperation(operation_type=MPVOperationType.PLAY)
        assert op.operation_type == MPVOperationType.PLAY
        assert op.args == ()
        assert op.kwargs == {}
        assert op.priority == 5
        assert op.component_id == "unknown"


class TestGetMpvManager:
    """get_mpv_manager 工厂函数。"""

    def test_returns_singleton(self) -> None:
        """返回与 MPVManager() 同一实例。"""
        from freeassetfilter.core.managers.mpv_manager import MPVManager, get_mpv_manager

        assert get_mpv_manager() is MPVManager()


# =============================================================================
# 操作队列内部路径（_submit_operation / 优先级 / 合并 / 处理循环）
# =============================================================================
class TestOperationQueueInternals:
    """``_submit_operation`` 入队、优先级与合并语义（不启动线程）。"""

    def test_submit_operation_queues_item(self, qapp: object) -> None:
        """提交后队列出现 (priority, seq, MPVOperation)，Future 即返回值。"""
        from concurrent.futures import Future

        from freeassetfilter.core.managers.mpv_manager import MPVOperationType

        manager: MPVManager = MPVManager()
        future: Future = manager._submit_operation(  # noqa: SLF001
            MPVOperationType.PLAY, component_id="comp", priority=2
        )
        assert isinstance(future, Future)
        assert manager._operation_queue.qsize() == 1  # noqa: SLF001
        priority: int
        seq: int
        operation: object
        priority, seq, operation = manager._operation_queue.get_nowait()  # noqa: SLF001
        assert priority == 2
        assert seq == 1
        assert operation.operation_type == MPVOperationType.PLAY  # type: ignore[attr-defined]
        assert operation.component_id == "comp"  # type: ignore[attr-defined]
        assert operation.future is future  # type: ignore[attr-defined]

    def test_submit_operation_raises_when_shutting_down(self, qapp: object) -> None:
        """关闭中直接提交操作抛 RuntimeError。"""
        from freeassetfilter.core.managers.mpv_manager import MPVOperationType

        manager: MPVManager = MPVManager()
        manager._is_shutting_down = True  # noqa: SLF001
        with pytest.raises(RuntimeError):
            manager._submit_operation(MPVOperationType.PLAY)  # noqa: SLF001

    def test_submit_operation_coalesces_same_component(self, qapp: object) -> None:
        """同组件同类型合并：前一个 future 立即置 False，仅保留最新。"""
        from freeassetfilter.core.managers.mpv_manager import MPVOperationType

        manager: MPVManager = MPVManager()
        first = manager._submit_operation(  # noqa: SLF001
            MPVOperationType.SET_VOLUME, 50, component_id="c"
        )
        second = manager._submit_operation(  # noqa: SLF001
            MPVOperationType.SET_VOLUME, 60, component_id="c"
        )
        assert first.done()
        assert first.result() is False
        pending_key = ("c", "set_volume")
        assert manager._pending_latest_operations[pending_key].future is second  # noqa: SLF001

    def test_priority_ordering(self, qapp: object) -> None:
        """优先级数字越小越先出队（PriorityQueue）。"""
        from freeassetfilter.core.managers.mpv_manager import MPVOperationType

        manager: MPVManager = MPVManager()
        manager._submit_operation(MPVOperationType.PLAY, component_id="a", priority=5)  # noqa: SLF001
        manager._submit_operation(MPVOperationType.STOP, component_id="a", priority=1)  # noqa: SLF001
        p1, _, op1 = manager._operation_queue.get_nowait()  # noqa: SLF001
        p2, _, op2 = manager._operation_queue.get_nowait()  # noqa: SLF001
        assert (p1, op1.operation_type) == (1, MPVOperationType.STOP)  # type: ignore[attr-defined]
        assert (p2, op2.operation_type) == (5, MPVOperationType.PLAY)  # type: ignore[attr-defined]


class TestOperationProcessingLoop:
    """``_start_operation_thread`` / ``_stop_operation_thread`` 与处理循环。"""

    def test_thread_start_stop_lifecycle(self, qapp: object) -> None:
        """启动后线程存活且命名正确，停止后退出。"""
        manager: MPVManager = MPVManager()
        manager._start_operation_thread()  # noqa: SLF001
        assert manager._operation_thread is not None  # noqa: SLF001
        assert manager._operation_thread.is_alive()  # noqa: SLF001
        assert manager._operation_thread.name == "MPVOperationThread"  # noqa: SLF001
        manager._stop_operation_thread(2.0)  # noqa: SLF001
        assert not manager._operation_thread.is_alive()  # noqa: SLF001

    def test_process_operation_sets_future_result(self, qapp: object) -> None:
        """循环执行 PLAY 并写回 True，mock 核心被调用。"""
        from freeassetfilter.core.managers.mpv_manager import MPVOperationType

        manager: MPVManager = MPVManager()
        manager._mpv_core = MagicMock()  # noqa: SLF001
        executed: list = []
        original = manager._execute_operation

        def _spy(operation: object) -> object:
            executed.append(getattr(operation, "operation_type", None))
            return original(operation)

        manager._execute_operation = _spy  # type: ignore[method-assign]
        manager._start_operation_thread()  # noqa: SLF001
        try:
            future = manager._submit_operation(  # noqa: SLF001
                MPVOperationType.PLAY, component_id="c"
            )
            assert future.result(timeout=5.0) is True
            assert MPVOperationType.PLAY in executed
        finally:
            manager._stop_operation_thread(2.0)  # noqa: SLF001
        manager._mpv_core.play.assert_called_once()  # type: ignore[union-attr]

    def test_stale_coalesced_operation_skipped(self, qapp: object) -> None:
        """旧合并操作被跳过，只有最新 SET_VOLUME 被执行。"""
        from freeassetfilter.core.managers.mpv_manager import MPVOperationType

        manager: MPVManager = MPVManager()
        manager._mpv_core = MagicMock()  # noqa: SLF001
        manager._start_operation_thread()  # noqa: SLF001
        try:
            old = manager._submit_operation(  # noqa: SLF001
                MPVOperationType.SET_VOLUME, 50, component_id="c"
            )
            latest = manager._submit_operation(  # noqa: SLF001
                MPVOperationType.SET_VOLUME, 60, component_id="c"
            )
            assert old.result(timeout=5.0) is False
            assert latest.result(timeout=5.0) is True
            manager._mpv_core.set_volume.assert_called_once_with(60)  # type: ignore[union-attr]
        finally:
            manager._stop_operation_thread(2.0)  # noqa: SLF001

    def test_execute_operation_unknown_type_raises(self, qapp: object) -> None:
        """未知操作类型直接抛 ValueError（无线程副作用）。"""
        manager: MPVManager = MPVManager()
        from freeassetfilter.core.managers.mpv_manager import MPVOperation

        bogus: MPVOperation = MPVOperation(operation_type="bogus_type")  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            manager._execute_operation(bogus)  # noqa: SLF001

    def test_execute_operation_rethrows_runtime_error(self, qapp: object) -> None:
        """``_do_*`` 抛 RuntimeError 时由 ``_execute_operation`` 统一重抛。"""
        from freeassetfilter.core.managers.mpv_manager import MPVOperation, MPVOperationType

        manager: MPVManager = MPVManager()
        manager._mpv_core = MagicMock()  # noqa: SLF001
        manager._mpv_core.play.side_effect = RuntimeError("boom")  # type: ignore[union-attr]
        op: MPVOperation = MPVOperation(operation_type=MPVOperationType.PLAY)
        with patch("freeassetfilter.core.managers.mpv_manager.QMetaObject.invokeMethod"):
            with pytest.raises(RuntimeError, match="boom"):
                manager._execute_operation(op)  # noqa: SLF001
        assert manager.is_busy() is False


# =============================================================================
# _do_* 实现路径（mock 核心 / 无核心默认值）
# =============================================================================
class TestDoOperationImplementations:
    """``_execute_operation`` 分发的各 ``_do_*`` 委托与无核心默认值。"""

    @pytest.fixture
    def manager(self, qapp: object) -> MPVManager:
        manager = MPVManager()
        manager._mpv_core = MagicMock()  # noqa: SLF001
        return manager

    @staticmethod
    def _op(operation_type: object, *args: object, **kwargs: object) -> object:
        from freeassetfilter.core.managers.mpv_manager import MPVOperation

        return MPVOperation(operation_type=operation_type, args=args, kwargs=kwargs)

    # ---- 设置类操作：委托 core ----
    def test_do_set_loop_delegates(self, manager: MPVManager) -> None:
        from freeassetfilter.core.managers.mpv_manager import MPVOperationType

        result = manager._execute_operation(  # noqa: SLF001
            self._op(MPVOperationType.SET_LOOP, "inf")
        )
        assert result is True
        manager._mpv_core.set_loop.assert_called_once_with("inf")  # type: ignore[union-attr]

    def test_do_set_window_id_delegates(self, manager: MPVManager) -> None:
        from freeassetfilter.core.managers.mpv_manager import MPVOperationType

        manager._mpv_core.set_window_id.return_value = True  # type: ignore[union-attr]
        result = manager._execute_operation(  # noqa: SLF001
            self._op(MPVOperationType.SET_WINDOW_ID, 1234)
        )
        assert result is True
        manager._mpv_core.set_window_id.assert_called_once_with(1234)  # type: ignore[union-attr]

    def test_do_set_subtitle_visibility_and_track(self, manager: MPVManager) -> None:
        from freeassetfilter.core.managers.mpv_manager import MPVOperationType

        manager._mpv_core.set_subtitle_visibility.return_value = True  # type: ignore[union-attr]
        manager._mpv_core.set_subtitle_track.return_value = True  # type: ignore[union-attr]
        assert manager._execute_operation(  # noqa: SLF001
            self._op(MPVOperationType.SET_SUBTITLE_VISIBILITY, False)
        ) is True
        assert manager._execute_operation(  # noqa: SLF001
            self._op(MPVOperationType.SET_SUBTITLE_TRACK, None)
        ) is True
        manager._mpv_core.set_subtitle_visibility.assert_called_once_with(False)  # type: ignore[union-attr]
        manager._mpv_core.set_subtitle_track.assert_called_once_with(None)  # type: ignore[union-attr]

    def test_do_set_audio_track_delegates(self, manager: MPVManager) -> None:
        from freeassetfilter.core.managers.mpv_manager import MPVOperationType

        manager._mpv_core.set_audio_track.return_value = True  # type: ignore[union-attr]
        assert manager._execute_operation(  # noqa: SLF001
            self._op(MPVOperationType.SET_AUDIO_TRACK, 2)
        ) is True
        manager._mpv_core.set_audio_track.assert_called_once_with(2)  # type: ignore[union-attr]

    # ---- 获取类操作：委托 core 返回值 ----
    def test_do_get_volume_speed_delegates(self, manager: MPVManager) -> None:
        from freeassetfilter.core.managers.mpv_manager import MPVOperationType

        manager._mpv_core.get_volume.return_value = 42  # type: ignore[union-attr]
        manager._mpv_core.get_speed.return_value = 1.75  # type: ignore[union-attr]
        assert manager._execute_operation(  # noqa: SLF001
            self._op(MPVOperationType.GET_VOLUME)
        ) == 42
        assert manager._execute_operation(  # noqa: SLF001
            self._op(MPVOperationType.GET_SPEED)
        ) == 1.75

    def test_do_get_position_duration_handle_none(self, manager: MPVManager) -> None:
        from freeassetfilter.core.managers.mpv_manager import MPVOperationType

        manager._mpv_core.get_position_cached.return_value = None  # type: ignore[union-attr]
        manager._mpv_core.get_duration.return_value = None  # type: ignore[union-attr]
        assert manager._execute_operation(  # noqa: SLF001
            self._op(MPVOperationType.GET_POSITION)
        ) == 0.0
        assert manager._execute_operation(  # noqa: SLF001
            self._op(MPVOperationType.GET_DURATION)
        ) == 0.0

    def test_do_subtitle_audio_state_delegates(self, manager: MPVManager) -> None:
        from freeassetfilter.core.managers.mpv_manager import MPVOperationType

        manager._mpv_core.get_subtitle_state.return_value = {"has_available_subtitles": True}  # type: ignore[union-attr]
        manager._mpv_core.get_audio_state.return_value = {"track_count": 1}  # type: ignore[union-attr]
        assert manager._execute_operation(  # noqa: SLF001
            self._op(MPVOperationType.GET_SUBTITLE_STATE)
        ) == {"has_available_subtitles": True}
        assert manager._execute_operation(  # noqa: SLF001
            self._op(MPVOperationType.GET_AUDIO_STATE)
        ) == {"track_count": 1}

    # ---- 无核心：默认值路径 ----
    def test_do_operations_defaults_without_core(self, qapp: object) -> None:
        from freeassetfilter.core.managers.mpv_manager import MPVOperation, MPVOperationType

        manager: MPVManager = MPVManager()  # _mpv_core 为 None
        assert manager._execute_operation(  # noqa: SLF001
            MPVOperation(operation_type=MPVOperationType.GET_POSITION)
        ) == 0.0
        assert manager._execute_operation(  # noqa: SLF001
            MPVOperation(operation_type=MPVOperationType.GET_DURATION)
        ) == 0.0
        assert manager._execute_operation(  # noqa: SLF001
            MPVOperation(operation_type=MPVOperationType.GET_VOLUME)
        ) == 100
        assert manager._execute_operation(  # noqa: SLF001
            MPVOperation(operation_type=MPVOperationType.GET_SPEED)
        ) == 1.0
        assert manager._execute_operation(  # noqa: SLF001
            MPVOperation(operation_type=MPVOperationType.IS_PLAYING)
        ) is False
        assert manager._execute_operation(  # noqa: SLF001
            MPVOperation(operation_type=MPVOperationType.IS_PAUSED)
        ) is False
        assert manager._execute_operation(  # noqa: SLF001
            MPVOperation(operation_type=MPVOperationType.IS_MUTED)
        ) is False
        assert manager._execute_operation(  # noqa: SLF001
            MPVOperation(operation_type=MPVOperationType.GET_VIDEO_SIZE)
        ) == (0, 0)
        assert manager._execute_operation(  # noqa: SLF001
            MPVOperation(operation_type=MPVOperationType.GET_SUBTITLE_TRACKS)
        ) == []
        assert manager._execute_operation(  # noqa: SLF001
            MPVOperation(operation_type=MPVOperationType.GET_AUDIO_TRACKS)
        ) == []
        assert manager._execute_operation(  # noqa: SLF001
            MPVOperation(operation_type=MPVOperationType.SET_SUBTITLE_VISIBILITY, args=(True,))
        ) is False
        assert manager._execute_operation(  # noqa: SLF001
            MPVOperation(operation_type=MPVOperationType.SET_SUBTITLE_TRACK, args=(1,))
        ) is False
        assert manager._execute_operation(  # noqa: SLF001
            MPVOperation(operation_type=MPVOperationType.SET_AUDIO_TRACK, args=(1,))
        ) is False
        assert manager._execute_operation(  # noqa: SLF001
            MPVOperation(operation_type=MPVOperationType.UNLOAD_LUT)
        ) is False

    def test_do_load_file_without_core_raises(self, qapp: object) -> None:
        from freeassetfilter.core.managers.mpv_manager import MPVOperation, MPVOperationType

        manager: MPVManager = MPVManager()
        op: MPVOperation = MPVOperation(
            operation_type=MPVOperationType.LOAD_FILE, args=("x.mp4",)
        )
        with patch("freeassetfilter.core.managers.mpv_manager.QMetaObject.invokeMethod"):
            with pytest.raises(RuntimeError):
                manager._execute_operation(op)  # noqa: SLF001

    def test_do_load_file_normal_and_stop_interrupt(self, manager: MPVManager) -> None:
        """正常加载委托 core；停止事件中断加载间隔等待则放弃。"""
        from freeassetfilter.core.managers.mpv_manager import MPVOperation, MPVOperationType

        # 正常路径：首次调用无延迟
        manager._mpv_core.load_file.return_value = True  # type: ignore[union-attr]
        ok: MPVOperation = MPVOperation(
            operation_type=MPVOperationType.LOAD_FILE, args=("a.mp4", False)
        )
        assert manager._execute_operation(ok) is True  # noqa: SLF001
        manager._mpv_core.load_file.assert_called_once_with("a.mp4")  # type: ignore[union-attr]

        # 中断路径：立即上次加载 → 触发间隔等待，但 stop_event 已置位 → 放弃
        manager._last_file_load_time = __import__("time").monotonic()  # noqa: SLF001
        manager._stop_event.set()  # noqa: SLF001
        manager._mpv_core.load_file.reset_mock()  # type: ignore[union-attr]
        stopped: MPVOperation = MPVOperation(
            operation_type=MPVOperationType.LOAD_FILE, args=("b.mp4", False)
        )
        assert manager._execute_operation(stopped) is False  # noqa: SLF001
        manager._mpv_core.load_file.assert_not_called()  # type: ignore[union-attr]
        manager._stop_event.clear()  # noqa: SLF001


# =============================================================================
# 公共 API 委托（mock _submit_operation，零线程）
# =============================================================================
class TestPublicApiDelegation:
    """set_loop / set_window_id / 字幕 / 音轨 / LUT 等公共方法的成功与异常路径。"""

    @staticmethod
    def _resolved_future(value: object) -> object:
        from concurrent.futures import Future

        future: Future = Future()
        future.set_result(value)
        return future

    @staticmethod
    def _timed_out_future() -> object:
        from unittest.mock import MagicMock as _MM

        future: object = _MM()
        from concurrent.futures import TimeoutError as FutureTimeoutError

        future.result.side_effect = FutureTimeoutError  # type: ignore[attr-defined]
        return future

    def test_set_loop_success_and_timeout(self, qapp: object) -> None:
        manager: MPVManager = MPVManager()
        manager._submit_operation = MagicMock(  # type: ignore[method-assign]
            return_value=self._resolved_future(True)
        )
        assert manager.set_loop("inf") is True
        manager._submit_operation = MagicMock(  # type: ignore[method-assign]
            return_value=self._timed_out_future()
        )
        assert manager.set_loop("inf") is False

    def test_set_window_id_success(self, qapp: object) -> None:
        manager: MPVManager = MPVManager()
        future = self._resolved_future(True)
        manager._submit_operation = MagicMock(return_value=future)  # type: ignore[method-assign]
        assert manager.set_window_id(999) is True
        manager._submit_operation.assert_called_once()  # type: ignore[attr-defined]
        call_kwargs = manager._submit_operation.call_args  # type: ignore[attr-defined]
        assert call_kwargs.args[0].name == "SET_WINDOW_ID"

    def test_hide_subtitle_delegates_to_visibility(self, qapp: object) -> None:
        manager: MPVManager = MPVManager()
        manager.set_subtitle_visibility = MagicMock(return_value=True)  # type: ignore[method-assign]
        assert manager.hide_subtitle() is True
        manager.set_subtitle_visibility.assert_called_once_with(  # type: ignore[attr-defined]
            False, component_id="unknown", timeout=5.0
        )

    def test_get_subtitle_tracks_returns_list(self, qapp: object) -> None:
        manager: MPVManager = MPVManager()
        manager._submit_operation = MagicMock(  # type: ignore[method-assign]
            return_value=self._resolved_future([{"id": 1}])
        )
        assert manager.get_subtitle_tracks() == [{"id": 1}]
        manager._submit_operation = MagicMock(  # type: ignore[method-assign]
            return_value=self._resolved_future({"not": "a list"})
        )
        assert manager.get_subtitle_tracks() == []

    def test_get_audio_tracks_returns_list(self, qapp: object) -> None:
        manager: MPVManager = MPVManager()
        manager._submit_operation = MagicMock(  # type: ignore[method-assign]
            return_value=self._resolved_future([{"id": 2}])
        )
        assert manager.get_audio_tracks() == [{"id": 2}]

    def test_get_subtitle_audio_state_dict_guard(self, qapp: object) -> None:
        manager: MPVManager = MPVManager()
        manager._submit_operation = MagicMock(  # type: ignore[method-assign]
            return_value=self._resolved_future("not a dict")
        )
        assert manager.get_subtitle_state() == {}
        assert manager.get_audio_state() == {}

    def test_load_subtitle_unload_lut_failure_paths(self, qapp: object) -> None:
        manager: MPVManager = MPVManager()
        # 超时 → False
        manager._submit_operation = MagicMock(  # type: ignore[method-assign]
            return_value=self._timed_out_future()
        )
        assert manager.load_subtitle(r"C:\fake\sub.srt") is False
        assert manager.unload_lut() is False
        # RuntimeError → False
        manager._submit_operation = MagicMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("shut down")
        )
        assert manager.load_subtitle(r"C:\fake\sub.srt") is False
        assert manager.unload_lut() is False

    def test_seek_async_shutting_down_returns_pre_resolved(self, qapp: object) -> None:
        manager: MPVManager = MPVManager()
        manager._is_shutting_down = True  # noqa: SLF001
        future = manager.seek_async(10.0)
        assert future.result() is False

    def test_seek_async_submits_exact(self, qapp: object) -> None:
        manager: MPVManager = MPVManager()
        future = self._resolved_future(True)
        manager._submit_operation = MagicMock(return_value=future)  # type: ignore[method-assign]
        assert manager.seek_async(10.0, exact=True).result() is True
        call_kwargs = manager._submit_operation.call_args  # type: ignore[attr-defined]
        assert call_kwargs.kwargs["exact"] is True

    def test_seek_direct_shutting_down_short_circuit(self, qapp: object) -> None:
        manager: MPVManager = MPVManager()
        manager._is_shutting_down = True  # noqa: SLF001
        manager._submit_operation = MagicMock()  # type: ignore[method-assign]
        assert manager.seek(5.0) is False
        manager._submit_operation.assert_not_called()  # type: ignore[attr-defined]


# =============================================================================
# 状态快照 / 访问器 / 组件注册表 / 信号回调 / 健康检测
# =============================================================================
class TestStateAndAccessors:
    """``get_state``、只读访问器、组件注册与状态节流。"""

    def test_get_state_defaults_without_core(self, qapp: object) -> None:
        manager: MPVManager = MPVManager()
        state: MPVState = manager.get_state()
        assert state.is_initialized is False
        assert state.volume == 100
        assert state.speed == 1.0
        assert state.loop_mode == "no"
        assert state.current_file == ""

    def test_get_state_populated_from_core(self, qapp: object) -> None:
        manager: MPVManager = MPVManager()
        core: MagicMock = MagicMock()
        core.is_playing.return_value = True
        core.is_paused.return_value = False
        core.is_muted.return_value = False
        core.get_position_cached.return_value = 12.5
        core.get_duration_cached.return_value = 100.0
        core.get_volume.return_value = 66
        core.get_speed.return_value = 1.25
        core.get_loop_mode.return_value = "inf"
        core.get_current_file.return_value = "/tmp/v.mp4"
        manager._mpv_core = core  # noqa: SLF001
        state: MPVState = manager.get_state()
        assert state.is_initialized is True
        assert state.is_playing is True
        assert state.position == 12.5
        assert state.duration == 100.0
        assert state.volume == 66
        assert state.speed == 1.25
        assert state.loop_mode == "inf"
        assert state.current_file == "/tmp/v.mp4"

    def test_read_accessors_defaults_without_core(self, qapp: object) -> None:
        manager: MPVManager = MPVManager()
        assert manager.get_position() == 0.0
        assert manager.get_duration() == 0.0
        assert manager.get_volume() == 100
        assert manager.get_speed() == 1.0
        assert manager.is_playing() is False
        assert manager.is_paused() is False
        assert manager.is_muted() is False
        assert manager.get_video_size() == (0, 0)
        assert manager.get_current_lut() == ""
        assert manager.get_position_direct() is None
        assert manager.get_duration_direct() is None
        assert manager.is_initialized() is False

    def test_read_accessors_delegate_to_core(self, qapp: object) -> None:
        manager: MPVManager = MPVManager()
        core: MagicMock = MagicMock()
        core.get_position_cached.return_value = 8.0
        core.get_duration_cached.return_value = 90.0
        core.get_volume.return_value = 33
        core.get_speed.return_value = 2.0
        core.is_playing.return_value = True
        core.is_paused.return_value = False
        core.is_muted.return_value = True
        core.get_video_size.return_value = (1920, 1080)
        manager._mpv_core = core  # noqa: SLF001
        assert manager.get_position() == 8.0
        assert manager.get_duration() == 90.0
        assert manager.get_volume() == 33
        assert manager.get_speed() == 2.0
        assert manager.is_playing() is True
        assert manager.is_paused() is False
        assert manager.is_muted() is True
        assert manager.get_video_size() == (1920, 1080)
        assert manager.get_position_direct() == 8.0

    def test_duration_direct_shutting_down_returns_none(self, qapp: object) -> None:
        manager: MPVManager = MPVManager()
        manager._mpv_core = MagicMock()  # noqa: SLF001
        manager._is_shutting_down = True  # noqa: SLF001
        assert manager.get_position_direct() is None
        assert manager.get_duration_direct() is None

    def test_component_registry(self, qapp: object) -> None:
        manager: MPVManager = MPVManager()
        assert manager.register_component("cmp", "video") is True
        assert manager.register_component("cmp", "video") is False  # 重复注册拒绝
        assert manager.unregister_component("cmp") is True
        assert manager.unregister_component("cmp") is False  # 不存在
        assert manager.get_registered_components() == {}

    def test_schedule_state_changed_emit_throttle(self, qapp: object) -> None:
        manager: MPVManager = MPVManager()
        got: list = []
        manager.stateChanged.connect(lambda s: got.append(s))
        # 首次：last_emit=0 → elapsed 超大 → 立即发射
        manager._schedule_state_changed_emit()  # noqa: SLF001
        process_qt_events(qapp, ms=0)
        assert len(got) == 1
        # 立即再次：未过阈值 → 进入 pending + 定时器路径
        manager._last_state_emit_time = __import__("time").monotonic()  # noqa: SLF001
        manager._schedule_state_changed_emit()  # noqa: SLF001
        manager._flush_state_changed()  # noqa: SLF001
        process_qt_events(qapp, ms=0)
        assert len(got) == 2
        manager.stateChanged.disconnect()

    def test_signal_forwarding_callbacks(self, qapp: object) -> None:
        manager: MPVManager = MPVManager()
        got: dict = {}
        manager.positionChanged.connect(lambda p, d: got.update(pos=(p, d)))
        manager.volumeChanged.connect(lambda v: got.update(vol=v))
        manager.speedChanged.connect(lambda s: got.update(spd=s))
        manager.mutedChanged.connect(lambda m: got.update(mut=m))
        manager.fileLoaded.connect(lambda p: got.update(file=p))
        manager.fileEnded.connect(lambda r: got.update(ended=r))
        manager.errorOccurred.connect(lambda c, m: got.update(err=(c, m)))

        manager._on_position_changed(3.0, 30.0)  # noqa: SLF001
        manager._on_volume_changed(55)  # noqa: SLF001
        manager._on_speed_changed(1.5)  # noqa: SLF001
        manager._on_muted_changed(True)  # noqa: SLF001
        manager._on_file_loaded("/tmp/a.mp4")  # noqa: SLF001
        manager._on_file_ended(0)  # noqa: SLF001
        manager._on_error_occurred(-1, "err")  # noqa: SLF001
        process_qt_events(qapp, ms=0)

        assert got["pos"] == (3.0, 30.0)
        assert got["vol"] == 55
        assert got["spd"] == 1.5
        assert got["mut"] is True
        assert got["file"] == "/tmp/a.mp4"
        assert got["ended"] == 0
        assert got["err"] == (-1, "err")
        manager.positionChanged.disconnect()
        manager.volumeChanged.disconnect()
        manager.speedChanged.disconnect()
        manager.mutedChanged.disconnect()
        manager.fileLoaded.disconnect()
        manager.fileEnded.disconnect()
        manager.errorOccurred.disconnect()

    def test_on_duration_changed_emits_position_with_cache(self, qapp: object) -> None:
        manager: MPVManager = MPVManager()
        core: MagicMock = MagicMock()
        core.get_position_cached.return_value = 9.5
        manager._mpv_core = core  # noqa: SLF001
        got: list = []
        manager.positionChanged.connect(lambda p, d: got.append((p, d)))
        manager._on_duration_changed(120.0)  # noqa: SLF001
        process_qt_events(qapp, ms=0)
        assert got == [(9.5, 120.0)]
        manager.positionChanged.disconnect()

    def test_health_checks_and_crash_reset(self, qapp: object) -> None:
        manager: MPVManager = MPVManager()
        assert manager.is_core_healthy() is False  # 无核心
        manager._core_crashed = True  # noqa: SLF001
        assert manager.is_core_healthy() is False
        manager._core_crashed = False  # noqa: SLF001

        core: MagicMock = MagicMock()
        core._is_worker_crashed.return_value = False
        manager._mpv_core = core  # noqa: SLF001
        assert manager.is_core_healthy() is True

        core._is_worker_crashed.return_value = True
        core.get_worker_crash_info.return_value = "segfault"
        assert manager.is_core_healthy() is False
        assert manager._core_crashed is True  # noqa: SLF001
        manager.reset_core_crash()
        assert manager._core_crashed is False  # noqa: SLF001
        core.reset_crash_state.assert_called_once()  # type: ignore[attr-defined]

    def test_pump_core_signals_healthy_and_crashed(self, qapp: object) -> None:
        manager: MPVManager = MPVManager()
        core: MagicMock = MagicMock()
        core._is_worker_crashed.return_value = False
        manager._mpv_core = core  # noqa: SLF001
        manager._pump_core_signals()  # noqa: SLF001
        core._process_signal_queue.assert_called_once()  # type: ignore[attr-defined]

        core._is_worker_crashed.return_value = True
        core.get_worker_crash_info.return_value = "crash!"
        with patch("freeassetfilter.core.managers.mpv_manager.QMetaObject.invokeMethod") as mock_invoke:
            manager._pump_core_signals()  # noqa: SLF001
        assert manager._core_crashed is True  # noqa: SLF001
        mock_invoke.assert_called_once()  # type: ignore[attr-defined]

    def test_cleanup_resources_drains_queue(self, qapp: object) -> None:
        from concurrent.futures import Future

        from freeassetfilter.core.managers.mpv_manager import MPVOperation, MPVOperationType

        manager: MPVManager = MPVManager()
        future: Future = Future()
        op: MPVOperation = MPVOperation(operation_type=MPVOperationType.PLAY, future=future)
        manager._operation_queue.put((2, 1, op))  # noqa: SLF001
        manager._cleanup_resources()  # noqa: SLF001
        assert manager._operation_queue.empty()  # noqa: SLF001
        assert future.done()
        assert future.result() is False

    def test_do_close_with_and_without_core(self, qapp: object) -> None:
        manager: MPVManager = MPVManager()
        # 无核心：直接 True
        assert manager._do_close() is True  # noqa: SLF001
        # 有核心：调用 core.close()，置空 _mpv_core
        core: MagicMock = MagicMock()
        manager._mpv_core = core  # noqa: SLF001
        assert manager._do_close() is True  # noqa: SLF001
        core.close.assert_called_once()  # type: ignore[attr-defined]
        assert manager._mpv_core is None  # noqa: SLF001

    def test_close_without_thread_returns_true(self, qapp: object) -> None:
        manager: MPVManager = MPVManager()
        assert manager.close(async_mode=False) is True
        assert manager.is_cleanup_complete() is True

    def test_wait_ensure_cleanup_complete(self, qapp: object) -> None:
        manager: MPVManager = MPVManager()
        assert manager.is_cleanup_complete() is True
        assert manager.wait_for_cleanup(timeout=0.1) is True
        assert manager.ensure_cleanup_complete(timeout=0.1) is True

    def test_check_gpu_drain_sets_event(self, qapp: object) -> None:
        manager: MPVManager = MPVManager()
        manager._gpu_drain_target = __import__("time").monotonic() - 1.0  # noqa: SLF001
        manager._gpu_drain_event.clear()  # noqa: SLF001
        manager._check_gpu_drain()  # noqa: SLF001
        assert manager._gpu_drain_event.is_set()  # noqa: SLF001
        assert manager._gpu_drain_target == 0.0  # noqa: SLF001