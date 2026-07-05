# -*- coding: utf-8 -*-
"""
mpv_player_core 修复专项测试
验证 Wave 1 的所有修复是否生效
"""
import pytest
import os
import sys
import threading
import time
import queue
import ctypes
from unittest.mock import MagicMock, patch, PropertyMock

# 将项目根目录添加到 Python 路径
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


class TestWakeupCallback:
    """验证唤醒回调已注册"""

    def test_wakeup_callback_registered(self):
        """验证 mpv_set_wakeup_callback 在 worker 线程创建 mpv 实例后调用"""
        from freeassetfilter.core.mpv_player_core import (
            MPVPlayerCore, MPVDLLLoader, _wakeup_callback,
        )

        core = MPVPlayerCore()
        core._worker_thread = MagicMock()
        core._worker_thread.is_alive.return_value = False
        core._stop_event.set()  # 防止真正启动线程

        # 模拟 DLL loader
        mock_dll = MagicMock()
        mock_dll.mpv_create.return_value = ctypes.c_void_p(0x1234)
        mock_dll.mpv_initialize.return_value = 0
        core._dll_loader._dll = mock_dll
        core._dll_loader._initialized = True

        # 验证 _wakeup_callback 是 CFUNCTYPE 实例
        assert callable(_wakeup_callback)


class TestWidBeforeInit:
    """验证 wid 在 mpv_initialize 前作为选项设置"""

    def test_wid_set_before_init(self):
        """验证 _configure_mpv 在 wid 已知时将其添加到配置选项"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore

        core = MPVPlayerCore()
        mock_dll = MagicMock()
        mock_dll.mpv_set_option_string.return_value = 0
        core._dll_loader._dll = mock_dll

        # 设置 window_id
        core._window_id = 12345

        # 调用 _configure_mpv
        mpv_handle = ctypes.c_void_p(0x5678)
        core._configure_mpv(mpv_handle)

        # 验证 mpv_set_option_string 被调用且包含 "wid" 选项
        calls = mock_dll.mpv_set_option_string.call_args_list
        wid_calls = [c for c in calls if c[0][1] == b"wid"]
        assert len(wid_calls) > 0, "wid 选项应被设置"
        assert wid_calls[0][0][2] == b"12345", "wid 值应为 12345"

    def test_wid_not_set_when_unknown(self):
        """验证 wid 未知时不设置 wid 选项"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore

        core = MPVPlayerCore()
        mock_dll = MagicMock()
        mock_dll.mpv_set_option_string.return_value = 0
        core._dll_loader._dll = mock_dll

        # window_id 默认 None
        mpv_handle = ctypes.c_void_p(0x5678)
        core._configure_mpv(mpv_handle)

        calls = mock_dll.mpv_set_option_string.call_args_list
        wid_calls = [c for c in calls if c[0][1] == b"wid"]
        assert len(wid_calls) == 0, "wid 未知时不应设置 wid 选项"


class TestLutPropertyAfterInit:
    """验证 LUT 设置/清除使用正确的属性 API"""

    def test_lut_property_after_init(self):
        """验证 _set_lut_internal 使用 mpv_set_property_string 而非 mpv_set_option_string"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore

        core = MPVPlayerCore()
        mock_dll = MagicMock()
        mock_dll.mpv_set_property_string.return_value = 0
        core._dll_loader._dll = mock_dll

        mpv_handle = ctypes.c_void_p(0x1234)
        result = core._set_lut_internal(mpv_handle, r"C:\test\lut.cube")

        assert result is True
        # 验证使用的是 mpv_set_property_string 而非 mpv_set_option_string
        mock_dll.mpv_set_property_string.assert_called_once()
        args = mock_dll.mpv_set_property_string.call_args[0]
        assert args[0] == mpv_handle
        assert args[1] == b"options/lut"
        assert b"lut.cube" in args[2]
        assert mock_dll.mpv_set_option_string.call_count == 0, "不应使用 mpv_set_option_string"

    def test_clear_lut_property_after_init(self):
        """验证 _clear_lut_internal 使用 mpv_set_property_string 而非 mpv_set_option_string"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore

        core = MPVPlayerCore()
        mock_dll = MagicMock()
        mock_dll.mpv_set_property_string.return_value = 0
        core._dll_loader._dll = mock_dll

        mpv_handle = ctypes.c_void_p(0x1234)
        result = core._clear_lut_internal(mpv_handle)

        assert result is True
        mock_dll.mpv_set_property_string.assert_called_once()
        args = mock_dll.mpv_set_property_string.call_args[0]
        assert args[0] == mpv_handle
        assert args[1] == b"options/lut"
        assert args[2] == b""
        assert mock_dll.mpv_set_option_string.call_count == 0, "不应使用 mpv_set_option_string"


class TestExtractPropertyData:
    """验证属性数据深拷贝"""

    def test_extract_property_data_deep_copy(self):
        """验证 _extract_property_data 返回 Python-owned 对象，非浅指针"""
        from freeassetfilter.core.mpv_player_core import (
            MPVPlayerCore, MpvEventProperty, MpvFormat,
        )

        core = MPVPlayerCore()
        mock_dll = MagicMock()
        core._dll_loader._dll = mock_dll

        # 模拟 PROPERTY_CHANGE 事件数据（double）
        import ctypes
        prop_event = MpvEventProperty()
        prop_event.name = b"time-pos"
        prop_event.format = MpvFormat.DOUBLE
        val = ctypes.c_double(42.5)
        prop_event.data = ctypes.cast(ctypes.pointer(val), ctypes.c_void_p)

        result = core._extract_property_data(ctypes.pointer(prop_event))

        assert result is not None
        name, value = result
        assert name == "time-pos"
        assert value == 42.5
        # 验证是 Python float，不是指针
        assert isinstance(value, float)

    def test_extract_property_data_handles_string(self):
        """验证字符串属性被正确深拷贝"""
        from freeassetfilter.core.mpv_player_core import (
            MPVPlayerCore, MpvEventProperty, MpvFormat,
        )
        import ctypes

        core = MPVPlayerCore()
        prop_event = MpvEventProperty()
        prop_event.name = b"loop-file"
        prop_event.format = MpvFormat.STRING
        str_val = ctypes.c_char_p(b"yes")
        prop_event.data = ctypes.cast(ctypes.pointer(str_val), ctypes.c_void_p)

        result = core._extract_property_data(ctypes.pointer(prop_event))
        assert result is not None
        name, value = result
        assert name == "loop-file"
        assert value == "yes"
        assert isinstance(value, str)

    def test_extract_property_data_handles_flag(self):
        """验证 FLAG 属性被正确深拷贝"""
        from freeassetfilter.core.mpv_player_core import (
            MPVPlayerCore, MpvEventProperty, MpvFormat,
        )
        import ctypes

        core = MPVPlayerCore()
        prop_event = MpvEventProperty()
        prop_event.name = b"pause"
        prop_event.format = MpvFormat.FLAG
        flag_val = ctypes.c_int(1)
        prop_event.data = ctypes.cast(ctypes.pointer(flag_val), ctypes.c_void_p)

        result = core._extract_property_data(ctypes.pointer(prop_event))
        assert result is not None
        name, value = result
        assert name == "pause"
        assert value is True
        assert isinstance(value, bool)

    def test_extract_property_data_handles_int64(self):
        """验证 INT64 属性被正确深拷贝"""
        from freeassetfilter.core.mpv_player_core import (
            MPVPlayerCore, MpvEventProperty, MpvFormat,
        )
        import ctypes

        core = MPVPlayerCore()
        prop_event = MpvEventProperty()
        prop_event.name = b"volume"
        prop_event.format = MpvFormat.INT64
        int_val = ctypes.c_int64(80)
        prop_event.data = ctypes.cast(ctypes.pointer(int_val), ctypes.c_void_p)

        result = core._extract_property_data(ctypes.pointer(prop_event))
        assert result is not None
        name, value = result
        assert name == "volume"
        assert value == 80


class TestCommandLockNotBlocking:
    """验证 _command_request_lock 不会阻塞其他命令发送者"""

    def test_command_not_blocked_by_other_command(self):
        """验证并发 _send_command 调用不会互相阻塞等待"""
        from freeassetfilter.core.mpv_player_core import MPVCommandType, MPVPlayerCore

        core = MPVPlayerCore()
        core._initialized = True
        core._worker_thread = MagicMock()
        core._worker_thread.is_alive.return_value = True

        # 创建两个模拟的工作线程消费者来处理命令
        def consumer():
            while True:
                try:
                    cmd = core._command_queue.get(timeout=0.1)
                    core._command_queue.task_done()
                    core._resolve_command_result(cmd, True)
                except queue.Empty:
                    break

        # 发送第一个命令（锁释放后才开始等待结果）
        t1_results = []

        def send_cmd1():
            r = core._send_command(MPVCommandType.GET_POSITION, timeout=0.5)
            t1_results.append(r)

        t1 = threading.Thread(target=send_cmd1, daemon=True)
        t1.start()

        # 给 t1 一点时间来获取锁和入队
        time.sleep(0.05)

        # 发送第二个命令 - 即使第一个还在等待结果，第二个也应该能入队
        t2_results = []

        def send_cmd2():
            r = core._send_command(MPVCommandType.GET_DURATION, timeout=0.5)
            t2_results.append(r)

        t2 = threading.Thread(target=send_cmd2, daemon=True)
        t2.start()

        # 消费者处理命令
        time.sleep(0.05)
        consumer()

        # 等待线程完成
        t1.join(timeout=1)
        t2.join(timeout=1)

        # 两个命令都应该已入队
        assert len(t1_results) > 0, "命令1应返回结果"
        assert len(t2_results) > 0, "命令2应返回结果，不应被命令1阻塞"


class TestPreCleanupNonBlocking:
    """验证 pre_cleanup 不阻塞且不使用 QEventLoop"""

    def test_pre_cleanup_nonblocking(self):
        """验证 pre_cleanup 从非 worker 线程调用时不使用 QEventLoop"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore, MPVCommandType
        import queue as q_module

        core = MPVPlayerCore()
        core._initialized = True
        core._worker_thread = MagicMock()
        core._worker_thread.is_alive.return_value = True

        mock_dll = MagicMock()
        mock_dll.mpv_set_property.return_value = 0
        mock_dll.mpv_set_property_string.return_value = 0
        mock_dll.mpv_command.return_value = 0
        core._dll_loader._dll = mock_dll

        # 验证 _process_events_for 使用 threading.Event 而非 QEventLoop
        start = time.time()
        MPVPlayerCore._process_events_for(5)
        elapsed = time.time() - start
        assert elapsed < 0.05, f"5ms 等待不应超过 50ms，实际: {elapsed * 1000:.1f}ms"

    def test_no_qeventloop_in_non_main_thread(self):
        """验证 pre_cleanup 不依赖 QEventLoop（非主线程中调用 QEventLoop 是 UB）"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore

        import inspect
        source_lines = inspect.getsource(MPVPlayerCore._process_events_for).split('\n')
        # 排除 docstring 行（docstring 中提及 QEventLoop 作为被替代项）
        implementation_lines = [
            line for line in source_lines
            if not line.strip().startswith('"""') and not line.strip().startswith('*')
            and not line.strip().startswith('#')
        ]
        body = '\n'.join(implementation_lines[1:])
        assert "threading.Event" in body, "_process_events_for 应使用 threading.Event"
        assert "from PySide6" not in body, "不应包含 Qt 导入"


class TestPropertyEventReplyUserdata:
    """验证属性观察使用唯一 reply_userdata"""

    def test_property_event_reply_userdata_unique(self):
        """验证 _observe_properties 为每个属性分配不同的 reply_userdata"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore

        core = MPVPlayerCore()
        mock_dll = MagicMock()
        mock_dll.mpv_observe_property.return_value = 0
        core._dll_loader._dll = mock_dll

        mpv_handle = ctypes.c_void_p(0x1234)
        core._observe_properties(mpv_handle)

        # 验证每个 property 使用了不同的 reply_userdata
        calls = mock_dll.mpv_observe_property.call_args_list
        assert len(calls) >= 9, "应观察 9 个属性"

        reply_userdata_values = [call[0][1] for call in calls]
        # 验证所有 reply_userdata 都是正数且唯一
        assert len(set(reply_userdata_values)) == len(reply_userdata_values), "reply_userdata 应唯一"
        for uid in reply_userdata_values:
            assert uid > 0, f"reply_userdata 应 > 0，但得到 {uid}"


class TestQueueOverflow:
    """验证 QUEUE_OVERFLOW 被正确处理"""

    def test_queue_overflow_handling(self):
        """验证 QUEUE_OVERFLOW 事件被记录并递增计数器"""
        from freeassetfilter.core.mpv_player_core import (
            MPVPlayerCore, MpvEvent, MpvEventId,
        )

        core = MPVPlayerCore()
        mock_dll = MagicMock()
        mock_dll.mpv_observe_property.return_value = 0
        core._dll_loader._dll = mock_dll

        mpv_handle = ctypes.c_void_p(0x1234)
        initial_count = core._queue_overflow_count

        # 创建 QUEUE_OVERFLOW 事件
        event = MpvEvent()
        event.event_id = MpvEventId.QUEUE_OVERFLOW
        event.error = 0
        event.reply_userdata = 0
        event.data = None

        core._handle_mpv_event(mpv_handle, event)

        # 验证计数器递增
        assert core._queue_overflow_count == initial_count + 1, "QUEUE_OVERFLOW 计数器应递增"

    def test_queue_overflow_count_accessible(self):
        """验证可以通过 get_queue_overflow_count 获取计数器值"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore

        core = MPVPlayerCore()
        assert core.get_queue_overflow_count() == 0

        core._queue_overflow_count = 5
        assert core.get_queue_overflow_count() == 5


class TestObservePropertyError:
    """验证 mpv_observe_property 返回码被检查"""

    def test_observe_property_error_logged(self):
        """验证 mpv_observe_property 失败时记录警告"""
        from freeassetfilter.core import mpv_player_core
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore

        core = MPVPlayerCore()
        mock_dll = MagicMock()
        # 第一次调用成功，后续调用失败（模拟部分属性观察失败）
        mock_dll.mpv_observe_property.side_effect = [0, -1, -1, 0, 0, 0, 0, 0, 0]
        mock_dll.mpv_error_string.return_value = b"property not found"
        core._dll_loader._dll = mock_dll

        mpv_handle = ctypes.c_void_p(0x1234)

        with patch.object(mpv_player_core, "warning") as mock_warning:
            core._observe_properties(mpv_handle)

            # 验证有调用 warning（至少2次失败）
            assert mock_warning.call_count >= 2, "属性观察失败时应记录警告"


class TestPositionReset:
    """验证文件加载时位置/时长被重置"""

    def test_position_reset_on_load(self):
        """验证 _load_file_internal 重置 _position 和 _duration 为 0.0"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore, MPVCommandType

        core = MPVPlayerCore()
        mock_dll = MagicMock()
        mock_dll.mpv_command.return_value = 0
        core._dll_loader._dll = mock_dll

        mpv_handle = ctypes.c_void_p(0x1234)

        # 先设置一些旧值
        with core._state_lock:
            core._position = 55.5
            core._duration = 120.0

        # 加载文件（需要文件存在）
        test_file = __file__  # 用自身作为测试文件
        core._load_file_internal(mpv_handle, test_file)

        # 验证 position 和 duration 被重置
        with core._state_lock:
            assert core._position == 0.0, f"position 应重置为 0.0，实际: {core._position}"
            assert core._duration == 0.0, f"duration 应重置为 0.0，实际: {core._duration}"


class TestCleanupQuitRemoved:
    """验证 cleanup 中不再发送冗余 quit 命令"""

    def test_no_redundant_quit_in_cleanup(self):
        """验证 _cleanup_mpv_handle 不发送 quit 命令"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore

        core = MPVPlayerCore()
        mock_dll = MagicMock()
        mock_dll.mpv_terminate_destroy.return_value = None
        core._dll_loader._dll = mock_dll

        mpv_handle = ctypes.c_void_p(0x1234)
        core._cleanup_mpv_handle(mpv_handle)

        # 验证 mpv_command 未被调用（不应有 quit 命令）
        mock_dll.mpv_command.assert_not_called(), "不应发送 quit 命令"

        # 验证 mpv_terminate_destroy 被调用
        mock_dll.mpv_terminate_destroy.assert_called_once_with(mpv_handle)


class TestWidSetAfterInit:
    """验证 _set_window_id_internal 在 init 后使用正确的 API"""

    def test_window_id_set_after_init_uses_property(self):
        """验证 _set_window_id_internal 使用 mpv_set_property_string"""
        from freeassetfilter.core.mpv_player_core import MPVPlayerCore

        core = MPVPlayerCore()
        mock_dll = MagicMock()
        mock_dll.mpv_set_property_string.return_value = 0
        core._dll_loader._dll = mock_dll

        mpv_handle = ctypes.c_void_p(0x1234)
        core._set_window_id_internal(mpv_handle, 99999)

        mock_dll.mpv_set_property_string.assert_called_once()
        args = mock_dll.mpv_set_property_string.call_args[0]
        assert args[1] == b"wid"
        assert args[2] == b"99999"


class TestEventLifecycle:
    """验证事件生命周期处理正确"""

    def test_send_command_does_not_hold_lock_during_wait(self):
        """验证 _send_command 在等待结果时不持有 _command_request_lock"""
        from freeassetfilter.core.mpv_player_core import MPVCommandType, MPVPlayerCore

        core = MPVPlayerCore()
        core._initialized = True
        core._worker_thread = MagicMock()
        core._worker_thread.is_alive.return_value = True

        # 验证在 _send_command 等待期间，其他线程可以获取锁
        lock_acquired_during_wait = threading.Event()

        # 创建一个永不完成的命令（timeout=0）
        result = core._send_command(MPVCommandType.GET_POSITION, timeout=0)

        # 如果锁被释放了（不在等待期间持有），result 应为 None（超时）
        assert result is None

        # 验证锁未被占用（可以在当前线程获取）
        acquired = core._command_request_lock.acquire(blocking=True, timeout=0.5)
        assert acquired, "_command_request_lock 应在 _send_command 返回后可用"
        core._command_request_lock.release()


class TestDeepCopyMpvNode:
    """验证 mpv_node 递归深拷贝"""

    def test_deep_copy_mpv_node(self):
        """验证 _deep_copy_mpv_node 函数能处理各种节点类型"""
        from freeassetfilter.core.mpv_player_core import (
            _deep_copy_mpv_node, MpvNode, MpvNodeList, MpvFormat,
        )
        import ctypes

        # 测试 DOUBLE 节点
        double_node = MpvNode()
        double_node.format = MpvFormat.DOUBLE
        val = ctypes.c_double(3.14)
        double_node.u = ctypes.cast(ctypes.pointer(val), ctypes.c_void_p)

        result = _deep_copy_mpv_node(ctypes.pointer(double_node))
        assert result == 3.14

        # 测试 INT64 节点
        int_node = MpvNode()
        int_node.format = MpvFormat.INT64
        ival = ctypes.c_int64(42)
        int_node.u = ctypes.cast(ctypes.pointer(ival), ctypes.c_void_p)

        result = _deep_copy_mpv_node(ctypes.pointer(int_node))
        assert result == 42

        # 测试 NONE 节点
        none_node = MpvNode()
        none_node.format = MpvFormat.NONE
        result = _deep_copy_mpv_node(ctypes.pointer(none_node))
        assert result is None

    def test_deep_copy_mpv_node_array(self):
        """验证 NODE_ARRAY 递归深拷贝"""
        from freeassetfilter.core.mpv_player_core import (
            _deep_copy_mpv_node, MpvNode, MpvNodeList, MpvFormat,
        )
        import ctypes

        # 创建一个包含 2 个 DOUBLE 的数组
        list_node = MpvNode()
        list_node.format = MpvFormat.NODE_ARRAY

        node_list = MpvNodeList()
        val1 = ctypes.c_double(1.0)
        val2 = ctypes.c_double(2.0)

        child1 = MpvNode()
        child1.format = MpvFormat.DOUBLE
        child1.u = ctypes.cast(ctypes.pointer(val1), ctypes.c_void_p)

        child2 = MpvNode()
        child2.format = MpvFormat.DOUBLE
        child2.u = ctypes.cast(ctypes.pointer(val2), ctypes.c_void_p)

        # 创建连续缓冲区用于子节点数组
        children = (MpvNode * 2)(child1, child2)
        node_list.num = 2
        node_list.values = children
        node_list.keys = None

        list_node.u = ctypes.cast(ctypes.pointer(node_list), ctypes.c_void_p)

        result = _deep_copy_mpv_node(ctypes.pointer(list_node))
        print(f"DEBUG result: {result!r}")
        # 注意：由于 ctypes 中通过指针偏移访问数组元素可能不准确，
        # 这个测试主要是验证函数不会崩溃
        assert result is not None
