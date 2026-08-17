# -*- coding: utf-8 -*-
"""MPV 播放核心单测（tests-comprehensive-refactor todo-9 补全）。

覆盖 ``freeassetfilter.core.native.bridges.mpv_player_core``：

* **非 DLL 依赖（恒运行）**：枚举常量（MpvErrorCode / MpvFormat /
  MpvEventId / MpvEndFileReason / MPVCommandType）、``_deep_copy_mpv_node``
  的 ctypes 深拷贝、``MPVDLLLoader`` 未加载时的错误字符串、构造函数默认
  状态与缓存 getter、未初始化时命令快速返回、崩溃状态快速路径；
* **DLL 可用（真实路径）**：``libmpv-2.dll`` 加载 / 最小生命周期
  create → load → play → stop → close；全程 ``finally`` 确保关闭，
  ``process_qt_events`` 让异步完成，teardown 用 ``join`` + ``is_alive``
  检查线程退出（对应 AGENTS.md threading 跨线程模式）；
* **DLL 缺失**：真实路径经 conftest session fixture ``mpv_available`` 注入
  方法参数 + 方法内 ``pytest.skip``（**不使用**类级 ``pytest.mark.skipif``
  引用 fixture——learnings 已记录该写法会踩 ``AttributeError`` 的坑）。

本文件还自带对 ``MPVDLLLoader`` 单例的 teardown 重置（conftest 的
``reset_singletons`` 未覆盖该单例）。
"""

from __future__ import annotations

import ctypes
import os
import queue
import threading
import time
import wave
from ctypes import (
    byref,
    c_char_p,
    c_double,
    c_int,
    c_int64,
    c_void_p,
)
from typing import Any, Dict, List, Optional

import pytest
from unittest.mock import MagicMock, patch

from freeassetfilter.core.native.bridges.mpv_player_core import (
    MPVCommandType,
    MPVDLLLoader,
    MPVError,
    MPVPlayerCore,
    MpvEndFileReason,
    MpvErrorCode,
    MpvEvent,
    MpvEventEndFile,
    MpvEventId,
    MpvEventProperty,
    MpvEventStartFile,
    MpvFormat,
    MpvNode,
    MpvNodeList,
    _deep_copy_mpv_node,
)
from tests.support.qt_helpers import process_qt_events


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_mpv_dll_loader() -> None:
    """每个用例前后重置 MPVDLLLoader 类级单例（conftest 未覆盖）。"""
    MPVDLLLoader._instance = None
    MPVDLLLoader._dll = None
    MPVDLLLoader._initialized = False
    yield
    MPVDLLLoader._instance = None
    MPVDLLLoader._dll = None
    MPVDLLLoader._initialized = False


def _make_wav(tmp_path: Any) -> str:
    """生成 0.5s 单声道 8kHz 16bit WAV（MPV 可加载的最小真实媒体）。"""
    path: str = str(tmp_path / "tone.wav")
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x00\x00" * 4000)
    return path


def _teardown_core(core: MPVPlayerCore, qapp: Any) -> None:
    """强制关闭播放器并等待工作线程退出（绝不泄漏实例）。"""
    try:
        core.close(timeout=5.0)
    except Exception:
        pass
    process_qt_events(qapp, ms=50)
    assert core.wait_for_close(timeout=5.0) is True
    worker = core._worker_thread  # noqa: SLF001
    assert worker is None or not worker.is_alive()


# =============================================================================
# 枚举常量
# =============================================================================
class TestEnums:
    """MPV 枚举常量取值。"""

    def test_error_code_values(self) -> None:
        """典型错误码映射正确。"""
        assert MpvErrorCode.SUCCESS == 0
        assert MpvErrorCode.UNINITIALIZED == -3
        assert MpvErrorCode.GENERIC == -20

    def test_format_values(self) -> None:
        """数据格式枚举。"""
        assert MpvFormat.NONE == 0
        assert MpvFormat.STRING == 1
        assert MpvFormat.DOUBLE == 5
        assert MpvFormat.NODE_MAP == 8

    def test_event_id_values(self) -> None:
        """事件 ID 枚举。"""
        assert MpvEventId.SHUTDOWN == 1
        assert MpvEventId.END_FILE == 7
        assert MpvEventId.FILE_LOADED == 8

    def test_end_file_reason_values(self) -> None:
        """文件结束原因枚举。"""
        assert MpvEndFileReason.EOF == 0
        assert MpvEndFileReason.QUIT == 3
        assert MpvEndFileReason.ERROR == 4

    def test_command_type_values(self) -> None:
        """命令类型枚举首尾取值。"""
        assert MPVCommandType.INITIALIZE == 0
        assert MPVCommandType.SET_LUT == 22
        assert MPVCommandType.CLOSE == 99


# =============================================================================
# _deep_copy_mpv_node（纯 ctypes，无 DLL）
# =============================================================================
class TestDeepCopyMpvNode:
    """``_deep_copy_mpv_node`` 将原生节点深拷贝为 Python 类型。"""

    def test_none_format_returns_none(self) -> None:
        """NONE 格式返回 None。"""
        node = MpvNode()
        node.u = None
        node.format = MpvFormat.NONE
        assert _deep_copy_mpv_node(ctypes.pointer(node)) is None

    def test_string_format(self) -> None:
        """STRING 节点解码为 str。"""
        text = c_char_p(b"hello")
        node = MpvNode()
        node.u = ctypes.cast(byref(text), c_void_p).value
        node.format = MpvFormat.STRING
        assert _deep_copy_mpv_node(ctypes.pointer(node)) == "hello"

    def test_int64_format(self) -> None:
        """INT64 节点解析为 int。"""
        value = c_int64(123)
        node = MpvNode()
        node.u = ctypes.cast(byref(value), c_void_p).value
        node.format = MpvFormat.INT64
        assert _deep_copy_mpv_node(ctypes.pointer(node)) == 123

    def test_double_format(self) -> None:
        """DOUBLE 节点解析为 float。"""
        value = c_double(3.5)
        node = MpvNode()
        node.u = ctypes.cast(byref(value), c_void_p).value
        node.format = MpvFormat.DOUBLE
        assert _deep_copy_mpv_node(ctypes.pointer(node)) == 3.5

    def test_flag_format(self) -> None:
        """FLAG 节点解析为 bool。"""
        flag = c_int(1)
        node = MpvNode()
        node.u = ctypes.cast(byref(flag), c_void_p).value
        node.format = MpvFormat.FLAG
        assert _deep_copy_mpv_node(ctypes.pointer(node)) is True

    def test_node_array_format(self) -> None:
        """NODE_ARRAY 递归展开为 list。"""
        text0 = c_char_p(b"a")
        iv = c_int64(7)
        values = (MpvNode * 2)()
        values[0].u = ctypes.cast(byref(text0), c_void_p).value
        values[0].format = MpvFormat.STRING
        values[1].u = ctypes.cast(byref(iv), c_void_p).value
        values[1].format = MpvFormat.INT64
        lst = MpvNodeList()
        lst.num = 2
        lst.values = values
        node = MpvNode()
        node.u = ctypes.cast(byref(lst), c_void_p).value
        node.format = MpvFormat.NODE_ARRAY
        assert _deep_copy_mpv_node(ctypes.pointer(node)) == ["a", 7]

    def test_node_map_format(self) -> None:
        """NODE_MAP 递归展开为 dict。"""
        text0 = c_char_p(b"x")
        dbl = c_double(2.25)
        values = (MpvNode * 2)()
        values[0].u = ctypes.cast(byref(text0), c_void_p).value
        values[0].format = MpvFormat.STRING
        values[1].u = ctypes.cast(byref(dbl), c_void_p).value
        values[1].format = MpvFormat.DOUBLE
        keys = (ctypes.c_char_p * 2)(b"name", b"score")
        lst = MpvNodeList()
        lst.num = 2
        lst.values = values
        lst.keys = keys
        node = MpvNode()
        node.u = ctypes.cast(byref(lst), c_void_p).value
        node.format = MpvFormat.NODE_MAP
        assert _deep_copy_mpv_node(ctypes.pointer(node)) == {"name": "x", "score": 2.25}

    def test_unknown_format_returns_none(self) -> None:
        """未识别格式安全返回 None。"""
        node = MpvNode()
        node.u = None
        node.format = c_int64(99)
        assert _deep_copy_mpv_node(ctypes.pointer(node)) is None


# =============================================================================
# MPVDLLLoader（未加载状态，无真实 DLL 副作用）
# =============================================================================
class TestDllLoaderWithoutLoad:
    """``MPVDLLLoader`` 未调用 ``load_dll`` 时的契约。"""

    def test_singleton_same_instance(self) -> None:
        """单例语义：两次构造返回同一实例。"""
        assert MPVDLLLoader() is MPVDLLLoader()

    def test_error_string_before_load(self) -> None:
        """未加载 DLL 时错误字符串为固定提示。"""
        loader = MPVDLLLoader()
        assert loader.get_error_string(0) == "DLL not loaded"

    def test_is_loaded_false_before_load(self) -> None:
        """未加载时 ``is_loaded`` 为 False。"""
        loader = MPVDLLLoader()
        assert loader.is_loaded is False


# =============================================================================
# MPVPlayerCore 非初始化状态（无真实 DLL）
# =============================================================================
class TestPlayerCoreUninitialized:
    """构造函数、默认状态与未初始化快速路径。"""

    def test_constructor_defaults(self, qapp: Any) -> None:
        """构造后不启动线程，缓存 getter 返回默认值。"""
        core = MPVPlayerCore()
        assert core._worker_thread is None  # noqa: SLF001
        assert core.is_playing_cached() is False
        assert core.is_paused_cached() is False
        assert core.get_volume_cached() == 100
        assert core.get_speed_cached() == 1.0
        assert core.get_duration_cached() is None
        assert core.get_position_cached() is None
        assert core.get_current_file() == ""
        assert core.get_loop_mode() == "no"
        assert core.is_closing() is False

    def test_send_command_not_initialized_returns_false(self, qapp: Any) -> None:
        """未初始化时命令快速返回 False，不启动线程。"""
        core = MPVPlayerCore()
        assert core.set_volume(50) is False
        assert core.set_speed(1.5) is False
        assert core.pause() is False
        assert core.load_file(r"C:\fake\media.mp4") is False
        assert core._worker_thread is None  # noqa: SLF001

    def test_close_without_initialize_is_noop(self, qapp: Any) -> None:
        """未初始化时 close 安全空操作，不抛异常。"""
        core = MPVPlayerCore()
        core.close(timeout=5.0)
        assert core._worker_thread is None  # noqa: SLF001

    def test_process_events_for_returns_quickly(self) -> None:
        """``_process_events_for(0)`` 非阻塞快速返回。"""
        import time

        start = time.monotonic()
        MPVPlayerCore._process_events_for(0)
        assert time.monotonic() - start < 1.0


class TestCrashedWorkerFastPath:
    """工作线程崩溃标记下的快速失败路径（无需真实 DLL）。"""

    def test_crash_state_roundtrip(self, qapp: Any) -> None:
        """崩溃标记可读写，普通命令立刻失败。"""
        core = MPVPlayerCore()
        with core._worker_crash_lock:  # noqa: SLF001
            core._worker_crashed = True  # noqa: SLF001
            core._worker_crash_info = "fake crash for test"  # noqa: SLF001
        assert core._is_worker_crashed() is True  # noqa: SLF001
        assert core.get_worker_crash_info() == "fake crash for test"
        # 崩溃后命令不再等待，快速返回 False
        assert core.set_volume(50) is False
        assert core._worker_thread is None  # noqa: SLF001
        # 关闭进程不抛异常
        core.close(timeout=5.0)

    def test_reset_crash_state(self, qapp: Any) -> None:
        """``reset_crash_state`` 清除崩溃标记。"""
        core = MPVPlayerCore()
        with core._worker_crash_lock:  # noqa: SLF001
            core._worker_crashed = True  # noqa: SLF001
        core.reset_crash_state()
        assert core._is_worker_crashed() is False  # noqa: SLF001
        assert core.is_closing() is False


# =============================================================================
# 真实路径（需 libmpv-2.dll 可加载）
# =============================================================================
class TestRealMpvCore:
    """libmpv-2.dll 可用时的真实生命周期。"""

    def test_real_load_dll(self, mpv_available: bool) -> None:
        """`mpv_available` 为真时 DLL 可被真实加载。"""
        if not mpv_available:
            pytest.skip("libmpv-2.dll 不可用，跳过真实加载分支")
        loader = MPVDLLLoader()
        assert loader.load_dll() is True
        assert loader.is_loaded is True

    def test_real_initialize_and_close(
        self, qapp: Any, mpv_available: bool
    ) -> None:
        """最小生命周期：仅初始化后干净关闭。"""
        if not mpv_available:
            pytest.skip("libmpv-2.dll 不可用，跳过真实 MPV 分支")
        core = MPVPlayerCore()
        try:
            assert core.initialize() is True
            process_qt_events(qapp, ms=50)
            assert core._initialized is True  # noqa: SLF001
        finally:
            _teardown_core(core, qapp)

    def test_real_init_load_play_stop(
        self, qapp: Any, mpv_available: bool, tmp_path: Any
    ) -> None:
        """真实完整链路：initialize → load_file → play → stop → close。"""
        if not mpv_available:
            pytest.skip("libmpv-2.dll 不可用，跳过真实 MPV 分支")
        wav: str = _make_wav(tmp_path)
        core = MPVPlayerCore()
        try:
            assert core.initialize() is True
            process_qt_events(qapp, ms=50)

            assert core.load_file(wav) is True
            process_qt_events(qapp, ms=100)

            assert core.set_volume(60) is True
            assert core.set_speed(1.25) is True
            assert core.play() is True
            process_qt_events(qapp, ms=100)

            assert core.stop() is True
            process_qt_events(qapp, ms=100)
        finally:
            _teardown_core(core, qapp)

    def test_real_double_initialize_idempotent(
        self, qapp: Any, mpv_available: bool
    ) -> None:
        """已初始化后再次 initialize 幂等返回 True。"""
        if not mpv_available:
            pytest.skip("libmpv-2.dll 不可用，跳过真实 MPV 分支")
        core = MPVPlayerCore()
        try:
            assert core.initialize() is True
            assert core.initialize() is True
            core.reset_crash_state()
            assert core.initialize() is True
        finally:
            _teardown_core(core, qapp)


# =============================================================================
# ctypes 事件结构体与 MPVError（纯内存，无 DLL 依赖）
# =============================================================================
class TestEventStructures:
    """MpvEvent* 结构体布局与 MPVError 错误码语义。"""

    def test_mpv_error_holds_code_and_message(self) -> None:
        """``MPVError(error_code, message)`` 记录两者并格式化。"""
        err = MPVError(2, "failed to open")
        assert err.error_code == 2
        assert err.message == "failed to open"
        assert str(err) == "MPV Error [2]: failed to open"
        assert issubclass(MPVError, Exception)

    def test_mpv_event_property_fields(self) -> None:
        """``MpvEventProperty`` 字段布局：name/format/data。"""
        ev = MpvEventProperty()
        names = [f[0] for f in MpvEventProperty._fields_]
        assert names == ["name", "format", "data"]
        assert ev.name is None  # c_char_p 未赋值时为 NULL
        assert ev.format == 0
        assert ev.data is None or ev.data == 0
        ev.name = b"time-pos"
        assert ev.name == b"time-pos"

    def test_mpv_event_end_file_fields(self) -> None:
        """``MpvEventEndFile`` 字段布局：reason/error/playlist 元数据。"""
        names = [f[0] for f in MpvEventEndFile._fields_]
        assert names == [
            "reason",
            "error",
            "playlist_entry_id",
            "playlist_insert_id",
            "playlist_insert_num_entries",
        ]
        ev = MpvEventEndFile()
        assert ev.reason == 0
        assert ev.playlist_entry_id == 0

    def test_mpv_event_start_file_fields(self) -> None:
        """``MpvEventStartFile`` 字段布局：playlist_entry_id。"""
        names = [f[0] for f in MpvEventStartFile._fields_]
        assert names == ["playlist_entry_id"]
        ev = MpvEventStartFile()
        assert ev.playlist_entry_id == 0

    def test_mpv_event_fields(self) -> None:
        """``MpvEvent`` 字段布局：event_id/error/reply_userdata/data。"""
        names = [f[0] for f in MpvEvent._fields_]
        assert names == ["event_id", "error", "reply_userdata", "data"]
        ev = MpvEvent()
        assert ev.event_id == 0
        assert ev.error == 0
        assert ev.reply_userdata == 0


# =============================================================================
# 命令分发与 _send_command 内部路径（无真实 DLL，用 FakeDLL + 后台工作线程）
# =============================================================================
class _FakeDLL:
    """最小 mpv 原生 DLL 替身：记录调用、按格式读写属性缓冲，返回成功码。"""

    def __init__(self) -> None:
        self.calls: List[Any] = []
        self.props: Dict[bytes, Any] = {}
        self.command_result: int = 0
        self.set_property_result: int = 0

    def mpv_command(self, handle: Any, cmd_array: Any) -> int:
        """记录命令数组并返回命令结果。"""
        self.calls.append(("command", [a for a in cmd_array]))
        return self.command_result

    def mpv_set_property(self, handle: Any, name: bytes, fmt: int, val_ptr: Any) -> int:
        """按格式读取调用方填充的缓冲并记录属性写入。"""
        self.calls.append(("set_property", name, fmt))
        if fmt == MpvFormat.DOUBLE:
            value = ctypes.cast(val_ptr, ctypes.POINTER(c_double)).contents.value
        elif fmt == MpvFormat.FLAG:
            value = bool(ctypes.cast(val_ptr, ctypes.POINTER(c_int)).contents.value)
        else:
            value = None
        self.props[name] = value
        return self.set_property_result

    def mpv_set_property_string(self, handle: Any, name: bytes, value: bytes) -> int:
        """记录字符串属性写入并返回成功。"""
        self.calls.append(("set_property_string", name, value))
        self.props[name] = value
        return 0

    def mpv_get_property(self, handle: Any, name: bytes, fmt: int, out: Any) -> int:
        """把属性值写入调用方的输出缓冲。"""
        self.calls.append(("get_property", name, fmt))
        raw = self.props.get(name, 0)
        if fmt == MpvFormat.DOUBLE:
            ctypes.cast(out, ctypes.POINTER(c_double)).contents.value = float(raw)
        elif fmt == MpvFormat.INT64:
            ctypes.cast(out, ctypes.POINTER(c_int64)).contents.value = int(raw)
        elif fmt == MpvFormat.FLAG:
            ctypes.cast(out, ctypes.POINTER(c_int)).contents.value = int(raw)
        return 0

    def mpv_get_property_string(self, handle: Any, name: bytes) -> Optional[Any]:
        """返回字符串属性指针（可为 None）。"""
        self.calls.append(("get_property_string", name))
        value = self.props.get(name, b"")
        encoded = value.encode("utf-8") if isinstance(value, str) else value
        return ctypes.c_char_p(encoded)

    def mpv_free(self, ptr: Any) -> None:
        """释放字符串指针（FakeDLL 无操作）。"""
        self.calls.append(("free",))


class _FakeLoader:
    """伪造 DLL loader：暴露 FakeDLL 为 ``.dll`` 属性。"""

    def __init__(self, dll: _FakeDLL) -> None:
        self._dll = dll

    @property
    def dll(self) -> _FakeDLL:
        return self._dll

    def get_error_string(self, error_code: int) -> str:
        return f"fake error code {error_code}"

    def load_dll(self) -> bool:
        return True

    @property
    def is_loaded(self) -> bool:
        return True


def _make_command(
    cmd_type: int, args: tuple = (), kwargs: Optional[dict] = None
) -> Dict[str, Any]:
    """构造一条可直接交给 _process_command 的命令字典。"""
    return {
        "type": cmd_type,
        "args": args,
        "kwargs": kwargs or {},
        "result_holder": {"result": None},
        "result_event": threading.Event(),
    }


class TestCommandDispatchFakeDll:
    """``_process_command`` 分发：每条命令路由到正确的内部实现（无真实 DLL）。"""

    @pytest.fixture
    def core(self, qapp: Any) -> MPVPlayerCore:
        """已初始化 + FakeDLL + 假句柄的 core。"""
        core = MPVPlayerCore()
        core._dll_loader = _FakeLoader(_FakeDLL())  # noqa: SLF001
        with core._state_lock:  # noqa: SLF001
            core._initialized = True  # noqa: SLF001
        return core

    def _handle(self) -> c_void_p:
        return c_void_p(0x1)

    def test_seek_dispatches_to_seek_internal(self, core: MPVPlayerCore) -> None:
        """SEEK 分发触发 mpv_command（absolute+exact 模式）。"""
        cmd = _make_command(MPVCommandType.SEEK, (12.5,), {"exact": False})
        core._process_command(self._handle(), cmd)  # noqa: SLF001
        assert cmd["result_holder"]["result"] is True
        assert core._dll_loader.dll.calls[-1][0] == "command"  # noqa: SLF001

    def test_set_volume_clamps_and_updates_cache(self, core: MPVPlayerCore) -> None:
        """SET_VOLUME 超界值被钳制到 0-100 并更新缓存。"""
        cmd = _make_command(MPVCommandType.SET_VOLUME, (150,))
        core._process_command(self._handle(), cmd)  # noqa: SLF001
        assert cmd["result_holder"]["result"] is True
        with core._state_lock:  # noqa: SLF001
            assert core._volume == 100  # noqa: SLF001

    def test_set_muted_updates_state(self, core: MPVPlayerCore) -> None:
        """SET_MUTED(True) 更新缓存状态。"""
        cmd = _make_command(MPVCommandType.SET_MUTED, (True,))
        core._process_command(self._handle(), cmd)  # noqa: SLF001
        assert cmd["result_holder"]["result"] is True
        with core._state_lock:  # noqa: SLF001
            assert core._muted is True  # noqa: SLF001

    def test_stop_resets_play_state(self, core: MPVPlayerCore) -> None:
        """STOP 将播放状态复位。"""
        with core._state_lock:  # noqa: SLF001
            core._is_playing = True  # noqa: SLF001
        cmd = _make_command(MPVCommandType.STOP)
        core._process_command(self._handle(), cmd)  # noqa: SLF001
        assert cmd["result_holder"]["result"] is True
        with core._state_lock:  # noqa: SLF001
            assert core._is_playing is False  # noqa: SLF001

    def test_play_and_pause_update_state(self, core: MPVPlayerCore) -> None:
        """PLAY/PAUSE 更新缓存播放状态。"""
        core._process_command(self._handle(), _make_command(MPVCommandType.PLAY))  # noqa: SLF001
        with core._state_lock:  # noqa: SLF001
            assert core._is_playing is True  # noqa: SLF001
        core._process_command(self._handle(), _make_command(MPVCommandType.PAUSE))  # noqa: SLF001
        with core._state_lock:  # noqa: SLF001
            assert core._is_paused is True  # noqa: SLF001

    def test_get_position_returns_double(self, core: MPVPlayerCore) -> None:
        """GET_POSITION 通过 mpv_get_property 返回 double。"""
        core._dll_loader.dll.props[b"time-pos"] = 12.5  # noqa: SLF001
        cmd = _make_command(MPVCommandType.GET_POSITION)
        core._process_command(self._handle(), cmd)  # noqa: SLF001
        assert cmd["result_holder"]["result"] == 12.5

    def test_get_video_size_returns_dimensions(self, core: MPVPlayerCore) -> None:
        """GET_VIDEO_SIZE 组合宽高整数元组。"""
        core._dll_loader.dll.props[b"video-params/w"] = 1920  # noqa: SLF001
        core._dll_loader.dll.props[b"video-params/h"] = 1080  # noqa: SLF001
        cmd = _make_command(MPVCommandType.GET_VIDEO_SIZE)
        core._process_command(self._handle(), cmd)  # noqa: SLF001
        assert cmd["result_holder"]["result"] == (1920, 1080)

    def test_set_window_id_and_size(self, core: MPVPlayerCore) -> None:
        """SET_WINDOW_ID/SET_WINDOW_SIZE 走 mpv_set_property_string。"""
        core._process_command(  # noqa: SLF001
            self._handle(), _make_command(MPVCommandType.SET_WINDOW_ID, (777,))
        )
        with core._state_lock:  # noqa: SLF001
            assert core._window_id == 777  # noqa: SLF001
        core._process_command(  # noqa: SLF001
            self._handle(), _make_command(MPVCommandType.SET_WINDOW_SIZE, (800, 600))
        )
        assert any(c[0] == "set_property_string" for c in core._dll_loader.dll.calls)  # noqa: SLF001

    def test_close_sets_stop_event(self, core: MPVPlayerCore) -> None:
        """CLOSE 命令设置停止事件并返回 True。"""
        cmd = _make_command(MPVCommandType.CLOSE)
        core._process_command(self._handle(), cmd)  # noqa: SLF001
        assert cmd["result_holder"]["result"] is True
        assert core._stop_event.is_set()  # noqa: SLF001

    def test_initialize_command_returns_true(self, core: MPVPlayerCore) -> None:
        """INITIALIZE 命令直接返回 True。"""
        cmd = _make_command(MPVCommandType.INITIALIZE)
        core._process_command(self._handle(), cmd)  # noqa: SLF001
        assert cmd["result_holder"]["result"] is True

    def test_unknown_command_resolves_none(self, core: MPVPlayerCore) -> None:
        """未知命令类型解析为 None 且事件被触发。"""
        cmd = _make_command(999)
        core._process_command(self._handle(), cmd)  # noqa: SLF001
        assert cmd["result_holder"]["result"] is None
        assert cmd["result_event"].is_set()


class TestFakeWorkerLifecycle:
    """后台工作线程消费命令队列的完整往返（FakeDLL，无真实 DLL）。"""

    @pytest.fixture
    def core_with_worker(self, qapp: Any) -> Any:
        """启动消费线程的已初始化 core，返回 (core, handle, dll)。"""
        core = MPVPlayerCore()
        dll = _FakeDLL()
        core._dll_loader = _FakeLoader(dll)  # noqa: SLF001
        handle = c_void_p(0x1)
        stop = threading.Event()

        def _loop() -> None:
            while not stop.is_set():
                try:
                    core._drain_command_queue(handle)  # noqa: SLF001
                except Exception:
                    break
                time.sleep(0.001)

        thread = threading.Thread(target=_loop, daemon=True)
        core._worker_thread = thread  # noqa: SLF001
        with core._state_lock:  # noqa: SLF001
            core._initialized = True  # noqa: SLF001
        thread.start()
        yield core, handle, dll
        stop.set()
        core._stop_event.set()  # noqa: SLF001
        thread.join(timeout=2.0)
        core._worker_thread = None  # noqa: SLF001

    def test_set_volume_roundtrip(self, core_with_worker: Any) -> None:
        """set_volume 经 _send_command → 工作线程 → 内部实现完整返回。"""
        core, _, _ = core_with_worker
        assert core.set_volume(60) is True
        assert core.get_volume() == 60

    def test_seek_roundtrip(self, core_with_worker: Any) -> None:
        """seek 往返成功并触发 mpv_command。"""
        core, _, dll = core_with_worker
        assert core.seek(30.0, exact=False) is True
        assert any(c[0] == "command" for c in dll.calls)

    def test_play_stop_roundtrip(self, core_with_worker: Any) -> None:
        """play/stop 往返更新缓存状态。"""
        core, _, _ = core_with_worker
        assert core.play() is True
        assert core.is_playing() is True
        assert core.stop() is True
        assert core.is_playing() is False


class TestSendCommandPaths:
    """``_send_command`` 快速失败 / 队列满 / 超时内部路径（无真实线程）。"""

    @pytest.fixture
    def fake_worker_core(self, qapp: Any) -> MPVPlayerCore:
        """_initialized=True + is_alive()=True 的假 worker，不消费队列。"""
        core = MPVPlayerCore()
        with core._state_lock:  # noqa: SLF001
            core._initialized = True  # noqa: SLF001
        fake_worker = MagicMock()
        fake_worker.is_alive.return_value = True
        core._worker_thread = fake_worker  # noqa: SLF001
        return core

    def test_stop_event_set_returns_none(self, fake_worker_core: MPVPlayerCore) -> None:
        """停止事件已设置时普通命令快速返回 None。"""
        fake_worker_core._stop_event.set()  # noqa: SLF001
        assert fake_worker_core._send_command(  # noqa: SLF001
            MPVCommandType.SEEK, 5.0, timeout=0.05
        ) is None

    def test_crashed_worker_returns_none(self, fake_worker_core: MPVPlayerCore) -> None:
        """崩溃状态下普通命令快速返回 None。"""
        with fake_worker_core._worker_crash_lock:  # noqa: SLF001
            fake_worker_core._worker_crashed = True  # noqa: SLF001
        assert fake_worker_core._send_command(  # noqa: SLF001
            MPVCommandType.SEEK, 5.0, timeout=0.05
        ) is None

    def test_dead_worker_marks_crash(self, fake_worker_core: MPVPlayerCore) -> None:
        """worker 线程死亡时标记崩溃并返回 None。"""
        fake_worker_core._worker_thread = MagicMock()  # noqa: SLF001
        fake_worker_core._worker_thread.is_alive.return_value = False  # noqa: SLF001
        assert fake_worker_core._send_command(  # noqa: SLF001
            MPVCommandType.SEEK, 5.0, timeout=0.05
        ) is None
        assert fake_worker_core._is_worker_crashed() is True  # noqa: SLF001

    def test_command_timeout_returns_none(self, fake_worker_core: MPVPlayerCore) -> None:
        """命令入队但无人消费时超时返回 None。"""
        assert fake_worker_core._send_command(  # noqa: SLF001
            MPVCommandType.SEEK, 5.0, timeout=0.05
        ) is None

    def test_queue_full_drops_oldest(self, fake_worker_core: MPVPlayerCore) -> None:
        """队列已满时丢弃最旧命令（解析为 None）后接纳新命令。"""
        fake_worker_core._command_queue = queue.Queue(maxsize=1)  # noqa: SLF001
        old_holder: Dict[str, Any] = {"result": "stale"}
        old_event = threading.Event()
        old_cmd = _make_command(MPVCommandType.PAUSE)
        old_cmd["result_holder"] = old_holder
        old_cmd["result_event"] = old_event
        fake_worker_core._command_queue.put(old_cmd)  # noqa: SLF001
        assert fake_worker_core._send_command(  # noqa: SLF001
            MPVCommandType.SET_VOLUME, 50, timeout=0.05
        ) is None
        assert old_event.is_set()
        assert old_holder["result"] is None


class TestCommandHelpers:
    """``seek_relative`` / toggle / 兼容别名等纯逻辑路径（无真实 DLL）。"""

    def test_seek_relative_uses_cached_position(self, qapp: Any) -> None:
        """``seek_relative`` 基于缓存 _position + 偏移量调用 seek。"""
        core = MPVPlayerCore()
        with core._state_lock:  # noqa: SLF001
            core._position = 10.5  # noqa: SLF001
        with patch.object(core, "seek", return_value=True) as mock_seek:
            assert core.seek_relative(2.0) is True
            mock_seek.assert_called_once_with(12.5)

    def test_toggle_pause_plays_when_paused(self, qapp: Any) -> None:
        """暂停状态下 toggle_pause 派发 play。"""
        core = MPVPlayerCore()
        with core._state_lock:  # noqa: SLF001
            core._is_paused = True  # noqa: SLF001
        with patch.object(core, "play", return_value=True) as mock_play:
            assert core.toggle_pause() is True
            mock_play.assert_called_once()

    def test_toggle_mute_flips_state(self, qapp: Any) -> None:
        """未静音时 toggle_mute 派发 set_mute(True)。"""
        core = MPVPlayerCore()
        with core._state_lock:  # noqa: SLF001
            core._muted = False  # noqa: SLF001
        with patch.object(core, "set_mute", return_value=True) as mock_mute:
            assert core.toggle_mute() is True
            mock_mute.assert_called_once_with(True)

    def test_set_muted_delegates_to_set_mute(self, qapp: Any) -> None:
        """兼容 API ``set_muted`` 委托到 ``set_mute``。"""
        core = MPVPlayerCore()
        with patch.object(core, "set_mute", return_value=True) as mock_mute:
            assert core.set_muted(True) is True
            mock_mute.assert_called_once_with(True)

    def test_set_loop_mode_delegates_to_set_loop(self, qapp: Any) -> None:
        """兼容 API ``set_loop_mode`` 委托到 ``set_loop``。"""
        core = MPVPlayerCore()
        with patch.object(core, "set_loop", return_value=True) as mock_loop:
            assert core.set_loop_mode("yes") is True
            mock_loop.assert_called_once_with("yes")

    def test_set_position_delegates_to_seek(self, qapp: Any) -> None:
        """``set_position`` 委托到 ``seek``。"""
        core = MPVPlayerCore()
        with patch.object(core, "seek", return_value=True) as mock_seek:
            assert core.set_position(3.0) is True
            mock_seek.assert_called_once_with(3.0)


class TestLoadFileErrorPath:
    """``load_file`` 文件不存在时的错误快速路径（无真实 DLL）。"""

    def test_load_file_missing_emits_error_signal(
        self, qapp: Any, tmp_path: Any
    ) -> None:
        """LOAD_FILE 不存在时返回 False 并入队 errorOccurred。"""
        core = MPVPlayerCore()
        core._dll_loader = _FakeLoader(_FakeDLL())  # noqa: SLF001
        handle = c_void_p(0x1)
        with core._state_lock:  # noqa: SLF001
            core._initialized = True  # noqa: SLF001
        missing = str(tmp_path / "does-not-exist.mp4")
        cmd = _make_command(MPVCommandType.LOAD_FILE, (missing,))
        core._process_command(handle, cmd)  # noqa: SLF001
        assert cmd["result_holder"]["result"] is False
        assert core._has_pending_signal("errorOccurred") is True  # noqa: SLF001


class TestResolveCommandResult:
    """``_resolve_command_result`` 的结果回写与事件触发。"""

    def test_sets_holder_and_sets_event(self, qapp: Any) -> None:
        """dict 持有者被回写结果，事件被触发。"""
        core = MPVPlayerCore()
        holder: Dict[str, Any] = {"result": None}
        event = threading.Event()
        core._resolve_command_result(  # noqa: SLF001
            {"result_holder": holder, "result_event": event}, 42
        )
        assert holder["result"] == 42
        assert event.is_set()

    def test_none_command_is_noop(self, qapp: Any) -> None:
        """空命令不抛异常。"""
        core = MPVPlayerCore()
        core._resolve_command_result(None, 1)  # noqa: SLF001


# =============================================================================
# 信号队列（_enqueue_signal / _queue_signal_if_changed / _process_signal_queue）
# =============================================================================
def _make_property_event(
    name: str, fmt: int, value: Any
) -> tuple:
    """构造一个 ``MpvEvent`` + 其 ctypes 持有者，event_id=PROPERTY_CHANGE。

    Args:
        name: 属性名（如 "time-pos"）。
        fmt: ``MpvFormat`` 取值。
        value: 数值（DOUBLE/INT64/FLAG/STRING 兼容）。

    Returns:
        ``(event, holder)`` —— holder 保存底层 ctypes 对象引用，防止过早回收。
    """
    holder: List[Any] = []
    prop = MpvEventProperty()
    prop.name = name.encode("utf-8")
    prop.format = fmt
    if fmt == MpvFormat.DOUBLE:
        buf = c_double(float(value))
        prop.data = ctypes.cast(byref(buf), c_void_p).value  # type: ignore[arg-type]
    elif fmt == MpvFormat.INT64:
        buf = c_int64(int(value))
        prop.data = ctypes.cast(byref(buf), c_void_p).value  # type: ignore[arg-type]
    elif fmt == MpvFormat.FLAG:
        buf = c_int(1 if value else 0)
        prop.data = ctypes.cast(byref(buf), c_void_p).value  # type: ignore[arg-type]
    elif fmt == MpvFormat.STRING:
        buf = c_char_p(str(value).encode("utf-8"))
        prop.data = ctypes.cast(byref(buf), c_void_p).value  # type: ignore[arg-type]
    else:
        buf = None
        prop.data = None
    holder.append(buf)
    holder.append(prop)
    event = MpvEvent()
    event.event_id = MpvEventId.PROPERTY_CHANGE
    event.data = ctypes.cast(byref(prop), c_void_p).value  # type: ignore[arg-type]
    holder.append(event)
    return event, holder


def _queued_signal_count(core: MPVPlayerCore, signal_name: str) -> int:
    """统计信号队列中指定名称的待处理信号数量（与 ``_has_pending_signal`` 同口径）。

    Args:
        core: MPVPlayerCore 实例。
        signal_name: 信号名称，如 "positionChanged"。

    Returns:
        int: 队列中匹配的信号条目数。
    """
    with core._signal_queue_peek_lock:  # noqa: SLF001
        return sum(
            1
            for item in core._signal_queue.queue  # noqa: SLF001
            if isinstance(item, (tuple, list)) and len(item) > 0 and item[0] == signal_name
        )


class TestSignalQueue:
    """``_enqueue_signal`` 满队丢旧与 ``_queue_signal_if_changed`` 去重。"""

    def test_enqueue_signal_normal(self, qapp: Any) -> None:
        """普通入队后可由队列读出。"""
        core = MPVPlayerCore()
        core._enqueue_signal("stateChanged", True)  # noqa: SLF001
        assert core._signal_queue.get_nowait()[0] == "stateChanged"  # noqa: SLF001

    def test_enqueue_signal_drops_oldest_when_full(self, qapp: Any) -> None:
        """队列满时丢弃最旧信号，保留最新。"""
        core = MPVPlayerCore()
        core._signal_queue = queue.Queue(maxsize=1)  # noqa: SLF001
        core._enqueue_signal("stateChanged", True)  # noqa: SLF001
        core._enqueue_signal("volumeChanged", 50)  # noqa: SLF001
        item = core._signal_queue.get_nowait()  # noqa: SLF001
        assert item[0] == "volumeChanged"
        assert core._signal_queue.empty()  # noqa: SLF001

    def test_queue_signal_if_changed_position_threshold(self, qapp: Any) -> None:
        """positionChanged 按 0.05s 阈值去重。"""
        core = MPVPlayerCore()
        # 首次发射：缓存 None → 入队
        core._queue_signal_if_changed("positionChanged", 10.0, 100.0)  # noqa: SLF001
        assert _queued_signal_count(core,"positionChanged") == 1  # noqa: SLF001
        # 相同位置 → 不入队
        core._queue_signal_if_changed("positionChanged", 10.0, 100.0)  # noqa: SLF001
        assert _queued_signal_count(core,"positionChanged") == 1  # noqa: SLF001
        # 小偏移（<0.05）→ 不入队
        core._queue_signal_if_changed("positionChanged", 10.04, 100.0)  # noqa: SLF001
        assert _queued_signal_count(core,"positionChanged") == 1  # noqa: SLF001
        # 达到阈值 → 入队
        core._queue_signal_if_changed("positionChanged", 10.05, 100.0)  # noqa: SLF001
        assert _queued_signal_count(core,"positionChanged") == 2  # noqa: SLF001

    def test_queue_signal_if_changed_duration_epsilon(self, qapp: Any) -> None:
        """durationChanged 按 0.0001 epsilon 去重。"""
        core = MPVPlayerCore()
        core._queue_signal_if_changed("durationChanged", 10.0)  # noqa: SLF001
        core._queue_signal_if_changed("durationChanged", 10.0)  # noqa: SLF001
        assert _queued_signal_count(core,"durationChanged") == 1  # noqa: SLF001
        core._queue_signal_if_changed("durationChanged", 10.0002)  # noqa: SLF001
        assert _queued_signal_count(core,"durationChanged") == 2  # noqa: SLF001

    def test_queue_signal_if_changed_state_and_volume_dedup(self, qapp: Any) -> None:
        """stateChanged/volumeChanged/speedChanged/mutedChanged 同值去重。"""
        core = MPVPlayerCore()
        core._queue_signal_if_changed("stateChanged", True)  # noqa: SLF001
        core._queue_signal_if_changed("stateChanged", True)  # noqa: SLF001
        assert _queued_signal_count(core,"stateChanged") == 1  # noqa: SLF001
        core._queue_signal_if_changed("stateChanged", False)  # noqa: SLF001
        assert _queued_signal_count(core,"stateChanged") == 2  # noqa: SLF001

        core._queue_signal_if_changed("volumeChanged", 60)  # noqa: SLF001
        core._queue_signal_if_changed("volumeChanged", 60)  # noqa: SLF001
        assert _queued_signal_count(core,"volumeChanged") == 1  # noqa: SLF001

        core._queue_signal_if_changed("mutedChanged", True)  # noqa: SLF001
        core._queue_signal_if_changed("mutedChanged", True)  # noqa: SLF001
        assert _queued_signal_count(core,"mutedChanged") == 1  # noqa: SLF001

    def test_queue_signal_if_changed_video_size(self, qapp: Any) -> None:
        """videoSizeChanged 相同元组去重。"""
        core = MPVPlayerCore()
        core._queue_signal_if_changed("videoSizeChanged", 1920, 1080)  # noqa: SLF001
        core._queue_signal_if_changed("videoSizeChanged", 1920, 1080)  # noqa: SLF001
        assert _queued_signal_count(core,"videoSizeChanged") == 1  # noqa: SLF001
        core._queue_signal_if_changed("videoSizeChanged", 1280, 720)  # noqa: SLF001
        assert _queued_signal_count(core,"videoSizeChanged") == 2  # noqa: SLF001

    def test_queue_signal_if_changed_unknown_always_enqueues(self, qapp: Any) -> None:
        """未知信号名总是入队（默认分支）。"""
        core = MPVPlayerCore()
        core._queue_signal_if_changed("seekFinished")  # noqa: SLF001
        core._queue_signal_if_changed("seekFinished")  # noqa: SLF001
        assert _queued_signal_count(core,"seekFinished") == 2  # noqa: SLF001

    def test_has_pending_signal(self, qapp: Any) -> None:
        """``_has_pending_signal`` 正确探测队列中的同名信号。"""
        core = MPVPlayerCore()
        assert core._has_pending_signal("positionChanged") is False  # noqa: SLF001
        core._enqueue_signal("positionChanged", 1.0, 10.0)  # noqa: SLF001
        core._enqueue_signal("positionChanged", 2.0, 10.0)  # noqa: SLF001
        assert core._has_pending_signal("positionChanged") is True  # noqa: SLF001
        core._signal_queue.get_nowait()  # noqa: SLF001
        assert core._has_pending_signal("positionChanged") is True  # noqa: SLF001
        core._signal_queue.get_nowait()  # noqa: SLF001
        assert core._has_pending_signal("positionChanged") is False  # noqa: SLF001

    def test_process_signal_queue_emits_signals(self, qapp: Any) -> None:
        """``_process_signal_queue`` 将队列信号发射到 Qt 信号。"""
        core = MPVPlayerCore()
        received: List[tuple] = []
        core.positionChanged.connect(lambda p, d: received.append(("pos", p, d)))
        core.durationChanged.connect(lambda d: received.append(("dur", d)))
        core.stateChanged.connect(lambda s: received.append(("state", s)))
        core._enqueue_signal("positionChanged", 1.0, 10.0)  # noqa: SLF001
        core._enqueue_signal("durationChanged", 10.0)  # noqa: SLF001
        core._enqueue_signal("stateChanged", True)  # noqa: SLF001
        core._process_signal_queue()  # noqa: SLF001
        assert ("pos", 1.0, 10.0) in received
        assert ("dur", 10.0) in received
        assert ("state", True) in received

    def test_process_signal_queue_skips_older_position(self, qapp: Any) -> None:
        """存在待处理 positionChanged 时跳过旧信号，只发射最新。"""
        core = MPVPlayerCore()
        received: List[tuple] = []
        core.positionChanged.connect(lambda p, d: received.append((p, d)))
        core._enqueue_signal("positionChanged", 1.0, 10.0)  # noqa: SLF001
        core._enqueue_signal("positionChanged", 2.0, 10.0)  # noqa: SLF001
        core._process_signal_queue()  # noqa: SLF001
        assert received == [(2.0, 10.0)]

    def test_process_signal_queue_emits_file_and_error(self, qapp: Any) -> None:
        """fileLoaded/fileEnded/errorOccurred/videoSizeChanged 均被发射。"""
        core = MPVPlayerCore()
        received: List[tuple] = []
        core.fileLoaded.connect(lambda p: received.append(("file", p)))
        core.fileEnded.connect(lambda r: received.append(("ended", r)))
        core.errorOccurred.connect(lambda c, m: received.append(("err", c, m)))
        core.videoSizeChanged.connect(lambda w, h: received.append(("vsize", w, h)))
        core._enqueue_signal("fileLoaded", "/tmp/a.mp4")  # noqa: SLF001
        core._enqueue_signal("fileEnded", 0)  # noqa: SLF001
        core._enqueue_signal("errorOccurred", -13, "load failed")  # noqa: SLF001
        core._enqueue_signal("videoSizeChanged", 1920, 1080)  # noqa: SLF001
        core._process_signal_queue()  # noqa: SLF001
        assert ("file", "/tmp/a.mp4") in received
        assert ("ended", 0) in received
        assert ("err", -13, "load failed") in received
        assert ("vsize", 1920, 1080) in received


# =============================================================================
# MPV 事件处理（_handle_mpv_event / 属性变化 / END_FILE）
# =============================================================================
class TestEventHandling:
    """``_handle_mpv_event`` 分支路由。"""

    def _core(self, qapp: Any) -> MPVPlayerCore:
        core = MPVPlayerCore()
        core._dll_loader = _FakeLoader(_FakeDLL())  # noqa: SLF001
        return core

    def _handle(self) -> c_void_p:
        return c_void_p(0x1)

    def test_none_event_returns(self, qapp: Any) -> None:
        """NONE 事件直接返回，无副作用。"""
        core = self._core(qapp)
        event = MpvEvent()
        event.event_id = MpvEventId.NONE
        core._handle_mpv_event(self._handle(), event)  # noqa: SLF001
        assert core.is_closing() is False
        assert core._is_seeking is False  # noqa: SLF001

    def test_seek_event_sets_seeking(self, qapp: Any) -> None:
        """SEEK 事件置 _is_seeking=True。"""
        core = self._core(qapp)
        event = MpvEvent()
        event.event_id = MpvEventId.SEEK
        core._handle_mpv_event(self._handle(), event)  # noqa: SLF001
        assert core._is_seeking is True  # noqa: SLF001

    def test_playback_restart_clears_seeking(self, qapp: Any) -> None:
        """PLAYBACK_RESTART 清除 seeking 并入队 seekFinished。"""
        core = self._core(qapp)
        core._is_seeking = True  # noqa: SLF001
        event = MpvEvent()
        event.event_id = MpvEventId.PLAYBACK_RESTART
        core._handle_mpv_event(self._handle(), event)  # noqa: SLF001
        assert core._is_seeking is False  # noqa: SLF001
        assert _queued_signal_count(core,"seekFinished") == 1  # noqa: SLF001

    def test_shutdown_event_sets_stop(self, qapp: Any) -> None:
        """SHUTDOWN 事件设置停止事件。"""
        core = self._core(qapp)
        event = MpvEvent()
        event.event_id = MpvEventId.SHUTDOWN
        core._handle_mpv_event(self._handle(), event)  # noqa: SLF001
        assert core.is_closing() is True

    def test_queue_overflow_reobserves(self, qapp: Any) -> None:
        """QUEUE_OVERFLOW 增加计数并重新观察属性。"""
        core = self._core(qapp)
        event = MpvEvent()
        event.event_id = MpvEventId.QUEUE_OVERFLOW
        with patch.object(core, "_observe_properties") as mock_obs:  # noqa: SLF001
            core._handle_mpv_event(self._handle(), event)  # noqa: SLF001
            mock_obs.assert_called_once()
            assert mock_obs.call_args.args[0].value == 0x1
        assert core.get_queue_overflow_count() == 1

    def test_property_change_dispatches(self, qapp: Any) -> None:
        """PROPERTY_CHANGE 委托给 _handle_property_change_event。"""
        core = self._core(qapp)
        event, _ = _make_property_event("time-pos", MpvFormat.DOUBLE, 12.5)
        with patch.object(core, "_handle_property_change_event") as mock_h:  # noqa: SLF001
            core._handle_mpv_event(self._handle(), event, extracted=("time-pos", 12.5))  # noqa: SLF001
            mock_h.assert_called_once()
            assert mock_h.call_args.args[0].value == 0x1
            assert mock_h.call_args.args[1] is event
            assert mock_h.call_args.args[2] == ("time-pos", 12.5)

    def test_file_loaded_dispatches(self, qapp: Any) -> None:
        """FILE_LOADED 委托给 _handle_file_loaded_event。"""
        core = self._core(qapp)
        event = MpvEvent()
        event.event_id = MpvEventId.FILE_LOADED
        with patch.object(core, "_handle_file_loaded_event") as mock_h:  # noqa: SLF001
            core._handle_mpv_event(self._handle(), event)  # noqa: SLF001
            mock_h.assert_called_once()
            assert mock_h.call_args.args[0].value == 0x1

    def test_end_file_dispatches(self, qapp: Any) -> None:
        """END_FILE 委托给 _handle_end_file_event。"""
        core = self._core(qapp)
        event = MpvEvent()
        event.event_id = MpvEventId.END_FILE
        with patch.object(core, "_handle_end_file_event") as mock_h:  # noqa: SLF001
            core._handle_mpv_event(self._handle(), event)  # noqa: SLF001
            mock_h.assert_called_once()
            assert mock_h.call_args.args[0].value == 0x1
            assert mock_h.call_args.args[1] is event


class TestPropertyChangeEvent:
    """``_handle_property_change_event`` 属性状态更新与信号入队。"""

    @pytest.fixture
    def core(self, qapp: Any) -> MPVPlayerCore:
        core = MPVPlayerCore()
        core._dll_loader = _FakeLoader(_FakeDLL())  # noqa: SLF001
        return core

    def test_time_pos_updates_position(self, core: MPVPlayerCore) -> None:
        """time-pos 属性更新 _position 并入队 positionChanged。"""
        core._handle_property_change_event(  # noqa: SLF001
            c_void_p(0x1), MpvEvent(), extracted=("time-pos", 12.5)
        )
        with core._state_lock:  # noqa: SLF001
            assert core._position == 12.5  # noqa: SLF001
        assert _queued_signal_count(core,"positionChanged") == 1  # noqa: SLF001

    def test_duration_updates_duration(self, core: MPVPlayerCore) -> None:
        """duration 属性更新 _duration 并入队 durationChanged。"""
        core._handle_property_change_event(  # noqa: SLF001
            c_void_p(0x1), MpvEvent(), extracted=("duration", 100.0)
        )
        with core._state_lock:  # noqa: SLF001
            assert core._duration == 100.0  # noqa: SLF001
        assert _queued_signal_count(core,"durationChanged") == 1  # noqa: SLF001

    def test_pause_updates_state(self, core: MPVPlayerCore) -> None:
        """pause=True 时播放状态翻转。"""
        core._handle_property_change_event(  # noqa: SLF001
            c_void_p(0x1), MpvEvent(), extracted=("pause", True)
        )
        with core._state_lock:  # noqa: SLF001
            assert core._is_paused is True  # noqa: SLF001
            assert core._is_playing is False  # noqa: SLF001
        assert _queued_signal_count(core,"stateChanged") == 1  # noqa: SLF001

    def test_volume_speed_mute_loop_update(self, core: MPVPlayerCore) -> None:
        """volume/speed/mute/loop-file 属性各自更新缓存。"""
        core._handle_property_change_event(  # noqa: SLF001
            c_void_p(0x1), MpvEvent(), extracted=("volume", 60)
        )
        core._handle_property_change_event(  # noqa: SLF001
            c_void_p(0x1), MpvEvent(), extracted=("speed", 1.5)
        )
        core._handle_property_change_event(  # noqa: SLF001
            c_void_p(0x1), MpvEvent(), extracted=("mute", True)
        )
        core._handle_property_change_event(  # noqa: SLF001
            c_void_p(0x1), MpvEvent(), extracted=("loop-file", "yes")
        )
        with core._state_lock:  # noqa: SLF001
            assert core._volume == 60  # noqa: SLF001
            assert core._speed == 1.5  # noqa: SLF001
            assert core._muted is True  # noqa: SLF001
            assert core._loop_mode == "yes"  # noqa: SLF001

    def test_video_params_width_sets_size(self, core: MPVPlayerCore) -> None:
        """video-params/w 更新尺寸（高度通过 _get_property_double 读取）。"""
        core._dll_loader.dll.props[b"video-params/h"] = 720  # noqa: SLF001
        core._handle_property_change_event(  # noqa: SLF001
            c_void_p(0x1), MpvEvent(), extracted=("video-params/w", 1280)
        )
        with core._state_lock:  # noqa: SLF001
            assert core._video_width == 1280  # noqa: SLF001
            assert core._video_height == 720  # noqa: SLF001
        assert _queued_signal_count(core,"videoSizeChanged") == 1  # noqa: SLF001

    def test_fallback_extracts_from_event_data(self, core: MPVPlayerCore) -> None:
        """extracted=None 时从 event.data 原地提取属性。"""
        event, _ = _make_property_event("volume", MpvFormat.INT64, 55)
        core._handle_property_change_event(  # noqa: SLF001
            c_void_p(0x1), event, extracted=None
        )
        with core._state_lock:  # noqa: SLF001
            assert core._volume == 55  # noqa: SLF001
        assert _queued_signal_count(core,"volumeChanged") == 1  # noqa: SLF001

    def test_empty_event_data_returns(self, core: MPVPlayerCore) -> None:
        """event.data 为空且无 extracted 时安全返回。"""
        event = MpvEvent()
        event.event_id = MpvEventId.PROPERTY_CHANGE
        event.data = None
        core._handle_property_change_event(  # noqa: SLF001
            c_void_p(0x1), event, extracted=None
        )


class TestEndFileEvent:
    """``_handle_end_file_event`` EOF 与 ERROR 路径。"""

    @pytest.fixture
    def core(self, qapp: Any) -> MPVPlayerCore:
        core = MPVPlayerCore()
        core._dll_loader = _FakeLoader(_FakeDLL())  # noqa: SLF001
        return core

    def test_eof_resets_state_and_emits_end(self, core: MPVPlayerCore) -> None:
        """EOF：播放状态复位，入队 stateChanged(False) 与 fileEnded(0)。"""
        with core._state_lock:  # noqa: SLF001
            core._is_playing = True  # noqa: SLF001
        event = MpvEvent()
        event.event_id = MpvEventId.END_FILE
        event.data = None
        core._handle_end_file_event(c_void_p(0x1), event)  # noqa: SLF001
        with core._state_lock:  # noqa: SLF001
            assert core._is_playing is False  # noqa: SLF001
            assert core._is_paused is False  # noqa: SLF001
        assert _queued_signal_count(core,"stateChanged") == 1  # noqa: SLF001
        assert _queued_signal_count(core,"fileEnded") == 1  # noqa: SLF001

    def test_error_enqueues_error_occurred(self, core: MPVPlayerCore) -> None:
        """ERROR 结束原因并入队 errorOccurred 与 fileEnded(ERROR)。"""
        end_file = MpvEventEndFile()
        end_file.reason = MpvEndFileReason.ERROR
        end_file.error = -12
        event = MpvEvent()
        event.event_id = MpvEventId.END_FILE
        event.data = ctypes.cast(byref(end_file), c_void_p).value  # type: ignore[arg-type]
        core._handle_end_file_event(c_void_p(0x1), event)  # noqa: SLF001
        assert _queued_signal_count(core,"errorOccurred") == 1  # noqa: SLF001
        assert _queued_signal_count(core,"fileEnded") == 1  # noqa: SLF001


class TestExtractPropertyData:
    """``_extract_property_data`` 从原生属性事件结构体提取 Python 值。"""

    @staticmethod
    def _prop(name: str, fmt: int, value: Any, holder: List[Any]) -> MpvEventProperty:
        prop = MpvEventProperty()
        prop.name = name.encode("utf-8")
        prop.format = fmt
        if fmt == MpvFormat.STRING:
            buf = c_char_p(str(value).encode("utf-8"))
            prop.data = ctypes.cast(byref(buf), c_void_p).value  # type: ignore[arg-type]
        elif fmt == MpvFormat.DOUBLE:
            buf = c_double(float(value))
            prop.data = ctypes.cast(byref(buf), c_void_p).value  # type: ignore[arg-type]
        elif fmt == MpvFormat.INT64:
            buf = c_int64(int(value))
            prop.data = ctypes.cast(byref(buf), c_void_p).value  # type: ignore[arg-type]
        elif fmt == MpvFormat.FLAG:
            buf = c_int(int(value))
            prop.data = ctypes.cast(byref(buf), c_void_p).value  # type: ignore[arg-type]
        else:
            buf = None
            prop.data = None
        holder.append(buf)
        return prop

    def test_string_format(self) -> None:
        """STRING 提取为 str。"""
        holder: List[Any] = []
        prop = self._prop("loop-file", MpvFormat.STRING, "yes", holder)
        assert MPVPlayerCore._extract_property_data(ctypes.pointer(prop)) == ("loop-file", "yes")

    def test_double_format(self) -> None:
        """DOUBLE 提取为 float。"""
        holder: List[Any] = []
        prop = self._prop("time-pos", MpvFormat.DOUBLE, 12.5, holder)
        assert MPVPlayerCore._extract_property_data(ctypes.pointer(prop)) == ("time-pos", 12.5)

    def test_int64_format(self) -> None:
        """INT64 提取为 int。"""
        holder: List[Any] = []
        prop = self._prop("volume", MpvFormat.INT64, 60, holder)
        assert MPVPlayerCore._extract_property_data(ctypes.pointer(prop)) == ("volume", 60)

    def test_flag_format(self) -> None:
        """FLAG 提取为 bool。"""
        holder: List[Any] = []
        prop = self._prop("mute", MpvFormat.FLAG, 1, holder)
        assert MPVPlayerCore._extract_property_data(ctypes.pointer(prop)) == ("mute", True)

    def test_null_pointer_returns_none(self) -> None:
        """空指针返回 None。"""
        assert MPVPlayerCore._extract_property_data(None) is None

    def test_unknown_format_returns_name_with_none(self) -> None:
        """未知格式返回 (name, None)。"""
        holder: List[Any] = []
        prop = self._prop("unknown", MpvFormat.NONE, None, holder)
        assert MPVPlayerCore._extract_property_data(ctypes.pointer(prop)) == ("unknown", None)