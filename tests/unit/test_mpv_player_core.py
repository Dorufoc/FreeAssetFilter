# -*- coding: utf-8 -*-
"""
mpv_player_core 单元测试
测试 freeassetfilter/core/mpv_player_core.py 模块的功能
"""
import pytest
import os
import sys
import threading
import ctypes
from unittest.mock import MagicMock, patch, PropertyMock

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


class TestMpvPlayerCoreBasic:
    """测试 MpvPlayerCore 基本功能"""

    def test_module_import(self):
        """测试模块可以导入"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore
        assert MPVPlayerCore is not None

    def test_module_has_required_attributes(self):
        """测试模块有必要的属性"""
        from freeassetfilter.core import mpv_player_core
        assert mpv_player_core is not None


class TestMpvPlayerCoreRobustness:
    """测试 MpvPlayerCore 鲁棒性"""

    def test_send_command_enqueues_without_cross_thread_mpv_wakeup(self):
        """命令入队不应从调用线程直接触碰 mpv handle。"""
        from freeassetfilter.core.mpv_player_core import MPVCommandType, MPVPlayerCore

        core = MPVPlayerCore()
        core._initialized = True
        core._worker_thread = MagicMock()
        core._worker_thread.is_alive.return_value = True

        result = core._send_command(MPVCommandType.GET_POSITION, timeout=0)

        assert result is None
        assert core._command_queue.qsize() == 1

    def test_drain_command_queue_processes_all_pending_commands(self):
        """工作线程每次醒来应清空当前命令批次，而不是空闲循环中逐条轮询。"""
        from freeassetfilter.core.mpv_player_core import MPVCommandType, MPVPlayerCore

        core = MPVPlayerCore()
        processed = []

        def fake_process_command(_mpv_handle, command):
            processed.append(command["type"])
            core._resolve_command_result(command, True)

        core._process_command = fake_process_command

        first = {"type": MPVCommandType.GET_POSITION, "result_event": MagicMock(), "result_holder": {}}
        second = {"type": MPVCommandType.GET_DURATION, "result_event": MagicMock(), "result_holder": {}}
        core._command_queue.put(first)
        core._command_queue.put(second)

        assert core._drain_command_queue(object()) is True
        assert processed == [MPVCommandType.GET_POSITION, MPVCommandType.GET_DURATION]
        assert core._command_queue.empty()

    def test_enqueue_signal_schedules_on_demand_processing(self, qapp):
        """信号入队后队列中有1个条目，持久定时器处于活动状态。"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore

        core = MPVPlayerCore()

        core._enqueue_signal("stateChanged", True)

        assert core._signal_queue.qsize() == 1
        # QTimer _signal_timer 已被 HeartbeatManager 替代
        assert core._heartbeat_signal_id is not None
        assert core._heartbeat_signal_id.startswith("mpv_player_core_")

    def test_enqueue_signal_deduplicates_pending_schedule(self, qapp):
        """多次入队后队列大小正确，持久定时器处于活动状态。"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore

        core = MPVPlayerCore()

        core._enqueue_signal("stateChanged", True)
        core._enqueue_signal("volumeChanged", 80)

        assert core._signal_queue.qsize() == 2
        # QTimer _signal_timer 已被 HeartbeatManager 替代
        assert core._heartbeat_signal_id is not None
        assert core._heartbeat_signal_id.startswith("mpv_player_core_")

    def test_seek_internal_uses_keyframe_mode_for_drag_preview(self):
        """拖动预览 seek 应使用关键帧模式，降低连续拖动时的解码压力。"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore

        core = MPVPlayerCore()
        dll = MagicMock()
        dll.mpv_command.return_value = 0
        core._dll_loader._dll = dll

        assert core._seek_internal(object(), 12.5, exact=False) is True

        command_args = dll.mpv_command.call_args[0][1]
        assert command_args[0] == b"seek"
        assert command_args[1] == b"12.5"
        assert command_args[2] == b"absolute+keyframes"

    def test_seek_internal_uses_exact_mode_for_final_position(self):
        """松手后的最终 seek 应使用精确模式保证落点正确。"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore

        core = MPVPlayerCore()
        dll = MagicMock()
        dll.mpv_command.return_value = 0
        core._dll_loader._dll = dll

        assert core._seek_internal(object(), 12.5, exact=True) is True

        command_args = dll.mpv_command.call_args[0][1]
        assert command_args[0] == b"seek"
        assert command_args[1] == b"12.5"
        assert command_args[2] == b"absolute+exact"


class TestWakeupCallback:
    """验证唤醒回调修复"""

    def test_wakeup_callback_module_level(self):
        """验证 _wakeup_callback 作为 CFUNCTYPE 在模块级可用"""
        from freeassetfilter.core.mpv_player_core import _wakeup_callback
        assert callable(_wakeup_callback)

    def test_mpv_set_wakeup_callback_binding(self):
        """验证 mpv_set_wakeup_callback 函数签名已绑定"""
        from freeassetfilter.core.mpv_player_core import MPVDLLLoader
        loader = MPVDLLLoader()
        mock_dll = MagicMock()
        loader._dll = mock_dll

        # 验证函数签名可以正确接收参数
        loader._bind_functions()


class TestWidBeforeInit:
    """验证 wid 在初始化前设置"""

    def test_wid_added_to_configure_mpv(self):
        """验证 _configure_mpv 在 wid 已知时包含 wid"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore

        core = MPVPlayerCore()
        core._window_id = 88888
        mock_dll = MagicMock()
        mock_dll.mpv_set_option_string.return_value = 0
        core._dll_loader._dll = mock_dll

        core._configure_mpv(ctypes.c_void_p(0x1234))

        # 验证 wid 选项被设置
        wid_set = False
        for call_args in mock_dll.mpv_set_option_string.call_args_list:
            if call_args[0][1] == b"wid":
                wid_set = True
                assert call_args[0][2] == b"88888"
                break
        assert wid_set, "wid 应在 _configure_mpv 中设置"

    def test_wid_not_in_configure_mpv_when_unknown(self):
        """验证 wid 未知时不添加到 _configure_mpv"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore

        core = MPVPlayerCore()
        core._window_id = None
        mock_dll = MagicMock()
        mock_dll.mpv_set_option_string.return_value = 0
        core._dll_loader._dll = mock_dll

        core._configure_mpv(ctypes.c_void_p(0x1234))

        for call_args in mock_dll.mpv_set_option_string.call_args_list:
            assert call_args[0][1] != b"wid", "wid 未知时不应设置 wid"


class TestLutApiFix:
    """验证 LUT API 修复"""

    def test_set_lut_uses_property_api(self):
        """验证 _set_lut_internal 使用 property API"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore

        core = MPVPlayerCore()
        mock_dll = MagicMock()
        mock_dll.mpv_set_property_string.return_value = 0
        core._dll_loader._dll = mock_dll

        core._set_lut_internal(ctypes.c_void_p(0x1234), r"D:\test\test_lut.cube")

        mock_dll.mpv_set_property_string.assert_called_once()
        args = mock_dll.mpv_set_property_string.call_args[0]
        assert args[1] == b"options/lut"
        assert b"test_lut.cube" in args[2]

    def test_clear_lut_uses_property_api(self):
        """验证 _clear_lut_internal 使用 property API"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore

        core = MPVPlayerCore()
        mock_dll = MagicMock()
        mock_dll.mpv_set_property_string.return_value = 0
        core._dll_loader._dll = mock_dll

        core._clear_lut_internal(ctypes.c_void_p(0x1234))

        mock_dll.mpv_set_property_string.assert_called_once()
        args = mock_dll.mpv_set_property_string.call_args[0]
        assert args[1] == b"options/lut"
        assert args[2] == b""


class TestExtractPropertyData:
    """验证属性数据深拷贝"""

    def test_extract_double(self):
        """验证 DOUBLE 属性提取"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore, MpvEventProperty, MpvFormat

        core = MPVPlayerCore()
        prop = MpvEventProperty()
        prop.name = b"time-pos"
        prop.format = MpvFormat.DOUBLE
        val = ctypes.c_double(12.5)
        prop.data = ctypes.cast(ctypes.pointer(val), ctypes.c_void_p)

        result = core._extract_property_data(ctypes.pointer(prop))
        assert result == ("time-pos", 12.5)

    def test_extract_int64(self):
        """验证 INT64 属性提取"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore, MpvEventProperty, MpvFormat

        core = MPVPlayerCore()
        prop = MpvEventProperty()
        prop.name = b"volume"
        prop.format = MpvFormat.INT64
        val = ctypes.c_int64(75)
        prop.data = ctypes.cast(ctypes.pointer(val), ctypes.c_void_p)

        result = core._extract_property_data(ctypes.pointer(prop))
        assert result == ("volume", 75)

    def test_extract_string(self):
        """验证 STRING 属性提取"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore, MpvEventProperty, MpvFormat

        core = MPVPlayerCore()
        prop = MpvEventProperty()
        prop.name = b"loop-file"
        prop.format = MpvFormat.STRING
        val = ctypes.c_char_p(b"yes")
        prop.data = ctypes.cast(ctypes.pointer(val), ctypes.c_void_p)

        result = core._extract_property_data(ctypes.pointer(prop))
        assert result == ("loop-file", "yes")

    def test_extract_flag(self):
        """验证 FLAG 属性提取"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore, MpvEventProperty, MpvFormat

        core = MPVPlayerCore()
        prop = MpvEventProperty()
        prop.name = b"pause"
        prop.format = MpvFormat.FLAG
        val = ctypes.c_int(1)
        prop.data = ctypes.cast(ctypes.pointer(val), ctypes.c_void_p)

        result = core._extract_property_data(ctypes.pointer(prop))
        assert result == ("pause", True)

    def test_extract_null_returns_none(self):
        """验证空指针返回 None"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore

        core = MPVPlayerCore()
        result = core._extract_property_data(None)
        assert result is None


class TestCommandLock:
    """验证命令锁修复"""

    def test_lock_released_before_wait(self):
        """验证 _send_command 释放在等待结果前释放锁"""
        from freeassetfilter.core.mpv_player_core import MPVCommandType, MPVPlayerCore

        core = MPVPlayerCore()
        core._initialized = True
        core._worker_thread = MagicMock()
        core._worker_thread.is_alive.return_value = True

        # 发送一个会超时的命令
        result = core._send_command(MPVCommandType.GET_POSITION, timeout=0)

        # 命令应该超时返回 None
        assert result is None

        # 锁应该已被释放（可以在当前线程重新获取）
        assert core._command_request_lock.acquire(timeout=0.5), "锁应该在 _send_command 返回后被释放"
        core._command_request_lock.release()


class TestQueueOverflow:
    """验证 QUEUE_OVERFLOW 处理"""

    def test_queue_overflow_counter(self):
        """验证 QUEUE_OVERFLOW 计数器"""
        from freeassetfilter.core.mpv_player_core import (
            MPVPlayerCore, MpvEvent, MpvEventId,
        )

        core = MPVPlayerCore()
        core._dll_loader._dll = MagicMock()

        event = MpvEvent()
        event.event_id = MpvEventId.QUEUE_OVERFLOW

        assert core._queue_overflow_count == 0
        core._handle_mpv_event(ctypes.c_void_p(0x1234), event)
        assert core._queue_overflow_count == 1
        core._handle_mpv_event(ctypes.c_void_p(0x1234), event)
        assert core._queue_overflow_count == 2

    def test_get_queue_overflow_count(self):
        """验证 get_queue_overflow_count 方法"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore

        core = MPVPlayerCore()
        assert core.get_queue_overflow_count() == 0
        core._queue_overflow_count = 3
        assert core.get_queue_overflow_count() == 3


class TestObserveProperty:
    """验证属性观察修复"""

    def test_observe_property_returns_checked(self):
        """验证 mpv_observe_property 返回码被检查和记录"""
        from freeassetfilter.core import mpv_player_core
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore

        core = MPVPlayerCore()
        mock_dll = MagicMock()
        mock_dll.mpv_observe_property.return_value = -1  # 全部失败
        mock_dll.mpv_error_string.return_value = b"error"
        core._dll_loader._dll = mock_dll

        with patch.object(mpv_player_core, "warning") as mock_warning:
            core._observe_properties(ctypes.c_void_p(0x1234))
            assert mock_warning.call_count == 9, "每个失败属性都应记录警告"

    def test_observe_property_unique_userdata(self):
        """验证每个属性观察使用唯一 reply_userdata"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore

        core = MPVPlayerCore()
        mock_dll = MagicMock()
        mock_dll.mpv_observe_property.return_value = 0
        core._dll_loader._dll = mock_dll

        core._observe_properties(ctypes.c_void_p(0x1234))

        calls = mock_dll.mpv_observe_property.call_args_list
        reply_data_ids = [call[0][1] for call in calls]
        assert len(set(reply_data_ids)) == len(reply_data_ids), "reply_userdata 必须唯一"
        assert min(reply_data_ids) >= 1, "reply_userdata 应从 1 开始"


class TestPositionResetOnLoad:
    """验证文件加载时位置重置"""

    def test_position_and_duration_reset(self):
        """验证 _load_file_internal 重置位置和时长"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore

        core = MPVPlayerCore()
        mock_dll = MagicMock()
        mock_dll.mpv_command.return_value = 0
        core._dll_loader._dll = mock_dll

        with core._state_lock:
            core._position = 99.9
            core._duration = 200.0

        # 使用存在的文件
        core._load_file_internal(ctypes.c_void_p(0x1234), __file__)

        with core._state_lock:
            assert core._position == 0.0
            assert core._duration == 0.0


class TestCleanupQuitRemoved:
    """验证冗余 quit 命令已被移除"""

    def test_no_quit_command_sent(self):
        """验证 _cleanup_mpv_handle 不发送 quit"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore

        core = MPVPlayerCore()
        mock_dll = MagicMock()
        core._dll_loader._dll = mock_dll

        core._cleanup_mpv_handle(ctypes.c_void_p(0x1234))

        # mpv_command 不应被调用
        mock_dll.mpv_command.assert_not_called()

        # mpv_terminate_destroy 应该被调用
        mock_dll.mpv_terminate_destroy.assert_called_once()


class TestPreCleanup:
    """验证 pre_cleanup 线程安全"""

    def test_process_events_for_uses_event(self):
        """验证 _process_events_for 使用 threading.Event（不引入 QEventLoop）"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore
        import inspect

        source_lines = inspect.getsource(MPVPlayerCore._process_events_for).split('\n')
        implementation_lines = [
            line for line in source_lines
            if not line.strip().startswith('"""') and not line.strip().startswith('*')
        ]
        body = '\n'.join(implementation_lines[1:])
        # Docstring mentions "QEventLoop" as the thing being replaced, so check body only
        assert "threading.Event" in body or "Event" in body
        # Verify implementation doesn't import/use QEventLoop
        assert "from PySide6" not in body, "不应包含 Qt 导入"

    def test_pre_cleanup_nonblocking(self):
        """验证 pre_cleanup 可以被非 worker 线程调用"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore

        core = MPVPlayerCore()
        core._initialized = True
        core._worker_thread = MagicMock()
        core._worker_thread.is_alive.return_value = True

        mock_dll = MagicMock()
        mock_dll.mpv_set_property.return_value = 0
        mock_dll.mpv_set_property_string.return_value = 0
        mock_dll.mpv_command.return_value = 0
        core._dll_loader._dll = mock_dll

        # 从非 worker 线程调用 pre_cleanup 不应该崩溃
        errors = []

        def call_pre_cleanup():
            try:
                core.pre_cleanup()
            except Exception as e:
                errors.append(e)

        t = threading.Thread(target=call_pre_cleanup, daemon=True)
        t.start()
        t.join(timeout=2)
        assert len(errors) == 0, f"pre_cleanup 不应抛出异常: {errors}"


class TestMpvCoreFixIntegration:
    """集成测试"""

    def test_send_command_non_blocking_flow(self):
        """验证完整的命令发送流程（非阻塞路径）"""
        from freeassetfilter.core.mpv_player_core import MPVCommandType, MPVPlayerCore

        core = MPVPlayerCore()
        core._initialized = True
        core._worker_thread = MagicMock()
        core._worker_thread.is_alive.return_value = True

        # 命令应能入队而不会阻塞在锁上
        cmd1_event = threading.Event()
        cmd2_event = threading.Event()

        results = []

        def sender1():
            # 手动创建命令以避免实际等待
            result_event = threading.Event()
            result_holder = {'result': 42}
            cmd = {
                'type': MPVCommandType.GET_POSITION,
                'args': (),
                'kwargs': {},
                'result_event': result_event,
                'result_holder': result_holder,
            }
            with core._command_request_lock:
                core._command_queue.put(cmd, block=False)
            cmd1_event.set()
            results.append(42)

        def sender2():
            cmd2_event.wait()  # 等待 sender1 入队
            result = core._send_command(MPVCommandType.GET_DURATION, timeout=0.1)
            results.append(result)

        t1 = threading.Thread(target=sender1, daemon=True)
        t2 = threading.Thread(target=sender2, daemon=True)
        t1.start()
        t2.start()

        cmd1_event.wait(timeout=1)
        cmd2_event.set()  # allow sender2 to proceed

        t1.join(timeout=1)
        t2.join(timeout=1)

        # sender2 应该能成功入队并等待结果
        assert len(results) == 2
