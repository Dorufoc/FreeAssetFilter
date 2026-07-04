#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

MPV管理器模块
集中式MPV控制管理模块，作为所有组件访问MPV功能的唯一接口

功能特性：
- 单例模式：确保全局只有一个MPV实例管理者
- 操作队列：处理多个组件的并发请求，避免操作序列冲突
- 标准化API：封装所有MPV控制命令
- 资源锁定：防止多个组件同时访问DLL导致程序崩溃
- 状态管理：实时跟踪MPV当前状态并提供查询接口
- 错误处理：确保单个操作失败不会影响整体系统稳定性
- 日志记录：便于调试和问题追踪

使用说明：
所有需要与MPV交互的组件必须通过此管理模块进行操作，
禁止直接访问MPV DLL或创建独立的MPV实例。
"""

import time
import threading
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Callable, Dict, Any, List, Union, Tuple
from queue import PriorityQueue, Empty
from threading import Lock, RLock, Event
from concurrent.futures import Future, TimeoutError as FutureTimeoutError

from PySide6.QtCore import (
    QObject, Signal, Slot, QTimer, Qt, QMetaObject, Q_ARG
)

# 导入MPV核心
from freeassetfilter.core.mpv_player_core import (
    MPVPlayerCore, MpvErrorCode
)

# 导入日志模块
from freeassetfilter.utils.app_logger import info, warning, error, exception_details


class MPVOperationType(Enum):
    """MPV操作类型枚举"""
    INITIALIZE = "initialize"
    CLOSE = "close"
    LOAD_FILE = "load_file"
    PLAY = "play"
    PAUSE = "pause"
    STOP = "stop"
    SEEK = "seek"
    SET_POSITION = "set_position"
    SET_VOLUME = "set_volume"
    SET_SPEED = "set_speed"
    SET_MUTED = "set_muted"
    SET_LOOP = "set_loop"
    SET_WINDOW_ID = "set_window_id"
    GET_POSITION = "get_position"
    GET_DURATION = "get_duration"
    GET_VOLUME = "get_volume"
    GET_SPEED = "get_speed"
    IS_PLAYING = "is_playing"
    IS_PAUSED = "is_paused"
    IS_MUTED = "is_muted"
    GET_VIDEO_SIZE = "get_video_size"
    LOAD_LUT = "load_lut"
    UNLOAD_LUT = "unload_lut"
    LOAD_SUBTITLE = "load_subtitle"
    GET_SUBTITLE_STATE = "get_subtitle_state"
    GET_SUBTITLE_TRACKS = "get_subtitle_tracks"
    SET_SUBTITLE_VISIBILITY = "set_subtitle_visibility"
    SET_SUBTITLE_TRACK = "set_subtitle_track"
    GET_AUDIO_STATE = "get_audio_state"
    GET_AUDIO_TRACKS = "get_audio_tracks"
    SET_AUDIO_TRACK = "set_audio_track"


@dataclass
class MPVOperation:
    """MPV操作数据类"""
    operation_type: MPVOperationType
    args: Tuple = field(default_factory=tuple)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    future: Optional[Future] = None
    priority: int = 5  # 优先级：1-10，数字越小优先级越高
    timestamp: float = field(default_factory=time.time)
    component_id: str = "unknown"  # 发起操作的组件标识


@dataclass
class MPVState:
    """MPV状态数据类"""
    is_initialized: bool = False
    is_playing: bool = False
    is_paused: bool = False
    is_muted: bool = False
    position: float = 0.0
    duration: float = 0.0
    volume: int = 100
    speed: float = 1.0
    loop_mode: str = "no"
    current_file: str = ""
    video_width: int = 0
    video_height: int = 0
    error_code: int = 0
    error_message: str = ""
    last_update: float = field(default_factory=time.time)
    current_lut: str = ""  # 当前加载的LUT文件路径


class MPVManager(QObject):
    """
    MPV管理器类（单例模式）

    集中式MPV控制管理模块，作为所有组件访问MPV功能的唯一接口。
    确保操作的原子性和顺序性，提供可靠的资源管理和冲突解决机制。

    使用示例：
        # 获取管理器实例
        manager = MPVManager()

        # 初始化MPV
        manager.initialize()

        # 加载文件
        manager.load_file("/path/to/video.mp4")

        # 播放控制
        manager.play()
        manager.pause()
        manager.seek(30.0)  # 跳转到30秒

        # 获取状态
        state = manager.get_state()
        # debug(f"当前位置: {state.position}")

        # 关闭MPV
        manager.close()
    """

    # 文件加载间隔防御（防止GPU驱动因快速切换文件而崩溃）
    FILE_LOAD_MIN_INTERVAL: float = 0.5  # 文件加载最小间隔（秒），RTX 5070 Ti + gpu-next + hwdec 已知问题

    # 信号定义
    stateChanged = Signal(MPVState)  # 状态变化信号
    positionChanged = Signal(float, float)  # 位置变化信号（位置，时长）
    volumeChanged = Signal(int)  # 音量变化信号
    mutedChanged = Signal(bool)  # 静音状态变化信号
    speedChanged = Signal(float)  # 播放速度变化信号
    fileLoaded = Signal(str)  # 文件加载完成信号（路径）
    fileEnded = Signal(int)  # 文件播放结束信号（结束原因）
    errorOccurred = Signal(int, str)  # 错误发生信号（错误码，错误信息）
    lutLoaded = Signal(str)  # LUT加载完成信号（LUT路径）
    lutUnloaded = Signal()  # LUT卸载完成信号
    coreCrashed = Signal(str)  # 核心崩溃信号（崩溃描述）

    # 单例实例
    _instance: Optional['MPVManager'] = None
    _instance_lock = Lock()

    def __new__(cls, *args, **kwargs):
        """实现单例模式"""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, parent=None):
        """
        初始化MPV管理器

        Args:
            parent: 父对象
        """
        # 避免重复初始化
        if self._initialized:
            return

        super().__init__(parent)

        info("MPV管理器初始化开始")

        # MPV核心实例
        self._mpv_core: Optional[MPVPlayerCore] = None

        # 资源锁定（细粒度，读写不互斥）
        self._busy_lock = Lock()
        self._is_busy = False
        self._shutdown_lock = Lock()

        # 操作队列同步条件（替代1s timeout轮询）
        self._queue_condition = threading.Condition()

        # 操作队列
        self._operation_queue: PriorityQueue = PriorityQueue()
        self._queue_lock = Lock()
        self._operation_sequence = 0
        self._pending_operation_lock = RLock()
        self._pending_latest_operations: Dict[Tuple[str, str], MPVOperation] = {}
        self._coalescible_operations = {
            MPVOperationType.SEEK,
            MPVOperationType.SET_POSITION,
            MPVOperationType.SET_VOLUME,
            MPVOperationType.SET_SPEED,
            MPVOperationType.SET_MUTED,
        }
        self._operation_thread: Optional[threading.Thread] = None
        self._stop_event = Event()

        # 组件注册表
        self._registered_components: Dict[str, Dict[str, Any]] = {}
        self._component_lock = RLock()

        # 初始化标志
        self._initialized = True
        self._is_shutting_down = False
        
        # 清理状态跟踪（用于检测上次异步清理是否完成）
        self._cleanup_event = Event()
        self._cleanup_event.set()  # 初始状态为已完成
        self._async_cleanup_thread: Optional[threading.Thread] = None

        # 状态信号节流（默认最多 60fps）
        self._state_emit_interval_ms = 16
        self._last_state_emit_time = 0.0
        self._state_emit_pending = False
        self._state_emit_timer = QTimer(self)
        self._state_emit_timer.setSingleShot(True)
        self._state_emit_timer.timeout.connect(self._flush_state_changed)

        # 主线程信号泵浦定时器 — 驱动核心的信号队列处理
        # 核心自身的 QTimer 因 QObject 位于 threading.Thread 上而无法工作
        self._signal_pump_timer = QTimer(self)
        self._signal_pump_timer.setInterval(100)
        self._signal_pump_timer.timeout.connect(self._pump_core_signals)
        self._signal_pump_timer.start()

        # MPV核心崩溃状态
        self._core_crashed = False
        self._core_crash_reason: str = ""
        
        # 文件加载间隔防御
        self._last_file_load_time: float = 0.0
        self._file_load_lock = Lock()
        
        # LuaJIT VEH 处理器状态
        self._luajit_veh_handle: Optional[Any] = None
        self._luajit_veh_fn: Optional[Any] = None

        info("MPV管理器初始化完成")
        info(f"状态节流间隔: {self._state_emit_interval_ms}ms")

    def _start_operation_thread(self):
        """启动操作处理线程"""
        if self._operation_thread is None or not self._operation_thread.is_alive():
            self._stop_event.clear()
            self._operation_thread = threading.Thread(
                target=self._process_operations,
                name="MPVOperationThread",
                daemon=True
            )
            self._operation_thread.start()
            info("操作处理线程已启动")
            # debug(f"线程名称: {self._operation_thread.name}")

    def _stop_operation_thread(self, timeout: float = 2.0):
        """停止操作处理线程"""
        if self._operation_thread and self._operation_thread.is_alive():
            self._stop_event.set()
            self._operation_thread.join(timeout=timeout)
            if self._operation_thread.is_alive():
                warning(f"操作处理线程未在 {timeout}s 内停止")
            else:
                info("操作处理线程已停止")
            # debug(f"停止超时: {timeout}s")

    def _cleanup_resources(self):
        """清理资源"""
        info("清理MPV管理器资源")
        # 清空操作队列
        while not self._operation_queue.empty():
            try:
                _, _, operation = self._operation_queue.get_nowait()
                if operation and operation.future and not operation.future.done():
                    operation.future.set_result(False)
            except Empty:
                # 队列为空
                break
        with self._pending_operation_lock:
            self._pending_latest_operations.clear()
        # 清空组件注册表
        self._registered_components.clear()

    def _process_operations(self):
        """处理操作队列的主循环"""
        info("操作处理循环开始")

        while not self._stop_event.is_set():
            operation = None
            try:
                # 使用 Condition 等待，超时 100ms，避免空转
                with self._queue_condition:
                    # 检查停止/关闭标志（在锁内检查，避免条件竞争）
                    if self._stop_event.is_set():
                        break
                    with self._shutdown_lock:
                        if self._is_shutting_down:
                            break
                    if self._operation_queue.empty():
                        self._queue_condition.wait(timeout=0.1)
                        continue
                    _, _, operation = self._operation_queue.get_nowait()

                if operation is None:
                    continue
                    
                # 再次检查是否正在关闭
                with self._shutdown_lock:
                    if self._is_shutting_down:
                        if operation.future and not operation.future.done():
                            operation.future.set_result(False)
                        continue

                if operation.operation_type in self._coalescible_operations:
                    pending_key = (operation.component_id, operation.operation_type.value)
                    with self._pending_operation_lock:
                        latest_operation = self._pending_latest_operations.get(pending_key)
                        if latest_operation is not operation:
                            # 跳过过期操作
                            if operation.future and not operation.future.done():
                                operation.future.set_result(False)
                            continue
                        self._pending_latest_operations.pop(pending_key, None)

                #debug(f"处理操作: {operation.operation_type.value}, 组件: {operation.component_id}")

                # 执行操作前再次检查关闭状态
                if self._is_shutting_down:
                    if operation.future and not operation.future.done():
                        operation.future.set_result(False)
                    continue
                    
                # 执行操作
                result = self._execute_operation(operation)

                # 设置Future结果
                if operation.future and not operation.future.done():
                    operation.future.set_result(result)

            except Empty:
                # 队列为空，继续循环
                continue
            except RuntimeError as e:
                if not self._is_shutting_down:
                    exception_details("处理操作时运行时错误", e)
                if operation and operation.future and not operation.future.done():
                    operation.future.set_exception(e)

        info("操作处理循环结束")

    def _execute_operation(self, operation: MPVOperation) -> Any:
        """
        执行单个操作

        Args:
            operation: 操作对象

        Returns:
            操作结果
        """
        # 第一重检查：关闭中直接返回
        if self._is_shutting_down and operation.operation_type != MPVOperationType.CLOSE:
            return False

        # 第二重检查：核心崩溃时跳过所有非初始化/关闭操作
        if self._core_crashed and operation.operation_type not in (
            MPVOperationType.INITIALIZE, MPVOperationType.CLOSE
        ):
            warning(f"MPV核心已崩溃，跳过操作: {operation.operation_type.value}")
            return False
            
        operation_type = operation.operation_type
        args = operation.args
        kwargs = operation.kwargs

        try:
            with self._busy_lock:
                # 第三重检查：关闭中直接返回（关闭操作除外）
                with self._shutdown_lock:
                    if self._is_shutting_down and operation_type != MPVOperationType.CLOSE:
                        return False
                self._is_busy = True

            if operation_type == MPVOperationType.INITIALIZE:
                result = self._do_initialize()
            elif operation_type == MPVOperationType.CLOSE:
                result = self._do_close()
            elif operation_type == MPVOperationType.LOAD_FILE:
                result = self._do_load_file(*args, **kwargs)
            elif operation_type == MPVOperationType.PLAY:
                result = self._do_play()
            elif operation_type == MPVOperationType.PAUSE:
                result = self._do_pause()
            elif operation_type == MPVOperationType.STOP:
                result = self._do_stop()
            elif operation_type == MPVOperationType.SEEK:
                result = self._do_seek(*args, **kwargs)
            elif operation_type == MPVOperationType.SET_POSITION:
                result = self._do_set_position(*args, **kwargs)
            elif operation_type == MPVOperationType.SET_VOLUME:
                result = self._do_set_volume(*args, **kwargs)
            elif operation_type == MPVOperationType.SET_SPEED:
                result = self._do_set_speed(*args, **kwargs)
            elif operation_type == MPVOperationType.SET_MUTED:
                result = self._do_set_muted(*args, **kwargs)
            elif operation_type == MPVOperationType.SET_LOOP:
                result = self._do_set_loop(*args, **kwargs)
            elif operation_type == MPVOperationType.SET_WINDOW_ID:
                result = self._do_set_window_id(*args, **kwargs)
            elif operation_type == MPVOperationType.GET_POSITION:
                result = self._do_get_position()
            elif operation_type == MPVOperationType.GET_DURATION:
                result = self._do_get_duration()
            elif operation_type == MPVOperationType.GET_VOLUME:
                result = self._do_get_volume()
            elif operation_type == MPVOperationType.GET_SPEED:
                result = self._do_get_speed()
            elif operation_type == MPVOperationType.IS_PLAYING:
                result = self._do_is_playing()
            elif operation_type == MPVOperationType.IS_PAUSED:
                result = self._do_is_paused()
            elif operation_type == MPVOperationType.IS_MUTED:
                result = self._do_is_muted()
            elif operation_type == MPVOperationType.GET_VIDEO_SIZE:
                result = self._do_get_video_size()
            elif operation_type == MPVOperationType.LOAD_LUT:
                result = self._do_load_lut(*args, **kwargs)
            elif operation_type == MPVOperationType.UNLOAD_LUT:
                result = self._do_unload_lut()
            elif operation_type == MPVOperationType.LOAD_SUBTITLE:
                result = self._do_load_subtitle(*args, **kwargs)
            elif operation_type == MPVOperationType.GET_SUBTITLE_STATE:
                result = self._do_get_subtitle_state()
            elif operation_type == MPVOperationType.GET_SUBTITLE_TRACKS:
                result = self._do_get_subtitle_tracks()
            elif operation_type == MPVOperationType.SET_SUBTITLE_VISIBILITY:
                result = self._do_set_subtitle_visibility(*args, **kwargs)
            elif operation_type == MPVOperationType.SET_SUBTITLE_TRACK:
                result = self._do_set_subtitle_track(*args, **kwargs)
            elif operation_type == MPVOperationType.GET_AUDIO_STATE:
                result = self._do_get_audio_state()
            elif operation_type == MPVOperationType.GET_AUDIO_TRACKS:
                result = self._do_get_audio_tracks()
            elif operation_type == MPVOperationType.SET_AUDIO_TRACK:
                result = self._do_set_audio_track(*args, **kwargs)
            else:
                raise ValueError(f"未知操作类型: {operation_type}")

            return result

        except RuntimeError as e:
            exception_details(f"执行操作 {operation_type.value} 运行时错误", e)

            QMetaObject.invokeMethod(
                self,
                "_emit_error_occurred",
                Qt.QueuedConnection,
                Q_ARG(int, MpvErrorCode.GENERIC),
                Q_ARG(str, str(e))
            )

            raise

        finally:
            with self._busy_lock:
                self._is_busy = False

    def _submit_operation(
        self,
        operation_type: MPVOperationType,
        *args,
        component_id: str = "unknown",
        priority: int = 5,
        **kwargs
    ) -> Future:
        """
        提交操作到队列

        Args:
            operation_type: 操作类型
            *args: 位置参数
            component_id: 组件标识
            priority: 优先级
            **kwargs: 关键字参数

        Returns:
            Future对象，用于获取操作结果
        """
        if self._is_shutting_down:
            raise RuntimeError("MPV管理器正在关闭，无法接受新操作")

        future = Future()

        operation = MPVOperation(
            operation_type=operation_type,
            args=args,
            kwargs=kwargs,
            future=future,
            priority=priority,
            component_id=component_id
        )

        with self._queue_lock:
            if operation_type in self._coalescible_operations:
                pending_key = (component_id, operation_type.value)
                with self._pending_operation_lock:
                    previous_operation = self._pending_latest_operations.get(pending_key)
                    self._pending_latest_operations[pending_key] = operation
                if previous_operation and previous_operation.future and not previous_operation.future.done():
                    previous_operation.future.set_result(False)

            self._operation_sequence += 1
            queue_item = (priority, self._operation_sequence, operation)
            self._operation_queue.put(queue_item)

        # 通知操作处理线程有新任务
        with self._queue_condition:
            self._queue_condition.notify()

        return future

    # ==================== 具体操作实现 ====================

    def _do_initialize(self) -> bool:
        """执行初始化操作"""
        info("开始初始化MPV核心")

        if self._mpv_core is None:
            error("MPV核心为空")
            return False

        # 连接信号
        self._mpv_core.stateChanged.connect(self._on_state_changed)
        self._mpv_core.positionChanged.connect(self._on_position_changed)
        self._mpv_core.durationChanged.connect(self._on_duration_changed)
        self._mpv_core.volumeChanged.connect(self._on_volume_changed)
        self._mpv_core.speedChanged.connect(self._on_speed_changed)
        self._mpv_core.mutedChanged.connect(self._on_muted_changed)
        self._mpv_core.fileLoaded.connect(self._on_file_loaded)
        self._mpv_core.fileEnded.connect(self._on_file_ended)
        self._mpv_core.errorOccurred.connect(self._on_error_occurred)

        # 注册 LuaJIT VEH 处理器（在 mpv 初始化之前，确保最后一个注册）
        self._register_luajit_veh()

        # 初始化MPV
        success = self._mpv_core.initialize()

        if success:
            info("MPV核心初始化成功")
        else:
            error("MPV核心初始化失败")
            self._mpv_core = None
            self._unregister_luajit_veh()

        return success

    def _do_close(self) -> bool:
        """执行关闭操作"""
        info("开始关闭MPV核心")

        if self._mpv_core is None:
            warning("MPV核心不存在，无需关闭")
            return True

        # 断开信号连接
        try:
            self._mpv_core.stateChanged.disconnect(self._on_state_changed)
            self._mpv_core.positionChanged.disconnect(self._on_position_changed)
            self._mpv_core.durationChanged.disconnect(self._on_duration_changed)
            self._mpv_core.volumeChanged.disconnect(self._on_volume_changed)
            self._mpv_core.speedChanged.disconnect(self._on_speed_changed)
            self._mpv_core.mutedChanged.disconnect(self._on_muted_changed)
            self._mpv_core.fileLoaded.disconnect(self._on_file_loaded)
            self._mpv_core.fileEnded.disconnect(self._on_file_ended)
            self._mpv_core.errorOccurred.disconnect(self._on_error_occurred)
        except RuntimeError as e:
            # 信号可能未连接，这是正常情况
            pass
            # debug(f"断开信号连接时出错: {e}")

        try:
            self._mpv_core.close()
        except RuntimeError as e:
            error(f"关闭MPV核心失败: {e}")

        self._mpv_core = None
        self._unregister_luajit_veh()

        info("MPV核心已关闭")
        return True

    def _do_load_file(self, file_path: str, is_audio: bool = False) -> bool:
        """执行加载文件操作"""
        if self._mpv_core is None:
            raise RuntimeError("MPV核心未初始化")

        # GPU驱动崩溃防御：强制文件加载间隔，排空GPU管线后再加载新文件
        # 解决 RTX 5070 Ti + gpu-next + hwdec 在快速切换文件时的 0xe24c4a02 崩溃
        with self._file_load_lock:
            elapsed = time.monotonic() - self._last_file_load_time
            if elapsed < self.FILE_LOAD_MIN_INTERVAL:
                delay = self.FILE_LOAD_MIN_INTERVAL - elapsed
                info(f"文件加载间隔过短({elapsed:.3f}s)，延迟 {delay:.3f}s 以排空GPU管线")
                time.sleep(delay)
            self._last_file_load_time = time.monotonic()

        info(f"加载文件: {file_path}")

        # MPVPlayerCore.load_file 只接受 file_path 参数
        success = self._mpv_core.load_file(file_path)

        return success

    def _do_play(self) -> bool:
        """执行播放操作"""
        if self._mpv_core is None:
            raise RuntimeError("MPV核心未初始化")

        self._mpv_core.play()

        return True

    def _do_pause(self) -> bool:
        """执行暂停操作"""
        if self._mpv_core is None:
            raise RuntimeError("MPV核心未初始化")

        self._mpv_core.pause()

        return True

    def _do_stop(self) -> bool:
        """执行停止操作"""
        if self._mpv_core is None:
            raise RuntimeError("MPV核心未初始化")

        self._mpv_core.stop()

        return True

    def _do_seek(self, position: float, exact: bool = True) -> bool:
        """执行跳转操作"""
        if self._mpv_core is None:
            raise RuntimeError("MPV核心未初始化")

        self._mpv_core.seek(position, exact=exact)
        return True

    def _do_set_position(self, position: float) -> bool:
        """执行设置位置操作"""
        if self._mpv_core is None:
            raise RuntimeError("MPV核心未初始化")

        self._mpv_core.set_position(position)

        return True

    def _do_set_volume(self, volume: int) -> bool:
        """执行设置音量操作"""
        if self._mpv_core is None:
            raise RuntimeError("MPV核心未初始化")

        self._mpv_core.set_volume(volume)

        return True

    def _do_set_speed(self, speed: float) -> bool:
        """执行设置速度操作"""
        if self._mpv_core is None:
            raise RuntimeError("MPV核心未初始化")

        self._mpv_core.set_speed(speed)

        return True

    def _do_set_muted(self, muted: bool) -> bool:
        """执行设置静音操作"""
        if self._mpv_core is None:
            raise RuntimeError("MPV核心未初始化")

        self._mpv_core.set_muted(muted)

        return True

    def _do_set_loop(self, loop_mode: str) -> bool:
        """执行设置循环模式操作"""
        if self._mpv_core is None:
            raise RuntimeError("MPV核心未初始化")

        self._mpv_core.set_loop(loop_mode)

        return True

    def _do_set_window_id(self, window_id: int) -> bool:
        """执行设置窗口ID操作"""
        if self._mpv_core is None:
            raise RuntimeError("MPV核心未初始化")

        return self._mpv_core.set_window_id(window_id)

    def _do_get_position(self) -> float:
        """执行获取位置操作（非阻塞，读取缓存）"""
        if self._mpv_core is None:
            return 0.0

        result = self._mpv_core.get_position_cached()
        return result if result is not None else 0.0

    def _do_get_duration(self) -> float:
        """执行获取时长操作"""
        if self._mpv_core is None:
            return 0.0

        result = self._mpv_core.get_duration()
        return result if result is not None else 0.0

    def _do_get_volume(self) -> int:
        """执行获取音量操作"""
        if self._mpv_core is None:
            return 100

        return self._mpv_core.get_volume()

    def _do_get_speed(self) -> float:
        """执行获取速度操作"""
        if self._mpv_core is None:
            return 1.0

        return self._mpv_core.get_speed()

    def _do_is_playing(self) -> bool:
        """执行获取是否正在播放操作"""
        if self._mpv_core is None:
            return False

        return self._mpv_core.is_playing()

    def _do_is_paused(self) -> bool:
        """执行获取是否暂停操作"""
        if self._mpv_core is None:
            return False

        return self._mpv_core.is_paused()

    def _do_is_muted(self) -> bool:
        """执行获取是否静音操作"""
        if self._mpv_core is None:
            return False

        return self._mpv_core.is_muted()

    def _do_get_video_size(self) -> Tuple[int, int]:
        """执行获取视频尺寸操作"""
        if self._mpv_core is None:
            return (0, 0)

        return self._mpv_core.get_video_size()

    def _do_load_lut(self, lut_file_path: str) -> bool:
        """
        执行加载LUT操作

        Args:
            lut_file_path: LUT文件路径

        Returns:
            bool: 是否成功
        """
        if self._mpv_core is None:
            warning("MPV未初始化，无法加载LUT")
            return False

        try:
            import os
            abs_path = os.path.abspath(lut_file_path)
            # debug(f"加载LUT: {abs_path}")

            abs_path2 = abs_path.replace("\\", "/")

            result = self._mpv_core.set_lut(abs_path2)

            if not result:
                filter_arg = f"lavfi-lut3d=file='{abs_path2}'" if ' ' in abs_path2 else f"lavfi-lut3d=file={abs_path2}"
                result = self._mpv_core.set_vf_filter(filter_arg)

            if not result:
                result = self._mpv_core.load_glsl_shader(abs_path2)

            if not result:
                shader_list = f'["{abs_path2}"]'
                result = self._mpv_core.set_glsl_shaders(shader_list)

            if result:
                self.lutLoaded.emit(lut_file_path)
                return True
            else:
                warning("加载LUT所有方式均失败")
                return False

        except (OSError, ValueError, TypeError) as e:
            exception_details("加载LUT失败", e)
            return False

    def _do_unload_lut(self) -> bool:
        """
        执行卸载LUT操作

        Returns:
            bool: 是否成功
        """
        if self._mpv_core is None:
            return False

        try:
            result = self._mpv_core.clear_lut()

            if not result:
                result = self._mpv_core.clear_glsl_shaders()

            if not result:
                result = self._mpv_core.set_vf_filter("")

            if result:
                self.lutUnloaded.emit()
                return True
            else:
                return False

        except RuntimeError as e:
            error(f"卸载LUT失败: {e}")
            return False

    def _do_load_subtitle(self, subtitle_file_path: str) -> bool:
        """
        执行加载外部字幕操作

        Args:
            subtitle_file_path: 字幕文件路径

        Returns:
            bool: 是否成功
        """
        if self._mpv_core is None:
            warning("MPV未初始化，无法加载字幕")
            return False

        try:
            return self._mpv_core.load_subtitle(subtitle_file_path)
        except RuntimeError as e:
            error(f"加载字幕失败: {e}")
            return False

    def _do_get_subtitle_state(self) -> Dict[str, Any]:
        """
        获取当前字幕状态

        Returns:
            Dict[str, Any]: 字幕状态字典
        """
        if self._mpv_core is None:
            return {
                "has_available_subtitles": False,
                "has_embedded_subtitles": False,
                "has_external_subtitles": False,
                "is_subtitle_visible": False,
                "has_active_subtitle": False,
                "selected_track_id": None,
                "selected_track": None,
                "selected_track_external": False,
                "tracks": [],
            }

        try:
            return self._mpv_core.get_subtitle_state()
        except RuntimeError as e:
            error(f"获取字幕状态失败: {e}")
            return {
                "has_available_subtitles": False,
                "has_embedded_subtitles": False,
                "has_external_subtitles": False,
                "is_subtitle_visible": False,
                "has_active_subtitle": False,
                "selected_track_id": None,
                "selected_track": None,
                "selected_track_external": False,
                "tracks": [],
            }

    def _do_get_subtitle_tracks(self) -> List[Dict[str, Any]]:
        """
        获取当前字幕轨列表

        Returns:
            List[Dict[str, Any]]: 字幕轨列表
        """
        if self._mpv_core is None:
            return []

        try:
            return self._mpv_core.get_subtitle_tracks()
        except RuntimeError as e:
            error(f"获取字幕轨列表失败: {e}")
            return []

    def _do_set_subtitle_visibility(self, visible: bool) -> bool:
        """
        设置字幕可见性

        Args:
            visible: 是否显示字幕

        Returns:
            bool: 是否成功
        """
        if self._mpv_core is None:
            warning("MPV未初始化，无法设置字幕可见性")
            return False

        try:
            return self._mpv_core.set_subtitle_visibility(visible)
        except RuntimeError as e:
            error(f"设置字幕可见性失败: {e}")
            return False

    def _do_set_subtitle_track(self, track_id: Union[int, str, None]) -> bool:
        """
        切换当前字幕轨

        Args:
            track_id: 字幕轨ID，None表示隐藏

        Returns:
            bool: 是否成功
        """
        if self._mpv_core is None:
            warning("MPV未初始化，无法切换字幕轨")
            return False

        try:
            return self._mpv_core.set_subtitle_track(track_id)
        except RuntimeError as e:
            error(f"切换字幕轨失败: {e}")
            return False

    def _do_get_audio_state(self) -> Dict[str, Any]:
        """
        获取当前音轨状态

        Returns:
            Dict[str, Any]: 音轨状态字典
        """
        if self._mpv_core is None:
            return {
                "has_available_audio_tracks": False,
                "has_multiple_audio_tracks": False,
                "track_count": 0,
                "selected_track_id": None,
                "selected_track": None,
                "tracks": [],
            }

        try:
            return self._mpv_core.get_audio_state()
        except RuntimeError as e:
            error(f"获取音轨状态失败: {e}")
            return {
                "has_available_audio_tracks": False,
                "has_multiple_audio_tracks": False,
                "track_count": 0,
                "selected_track_id": None,
                "selected_track": None,
                "tracks": [],
            }

    def _do_get_audio_tracks(self) -> List[Dict[str, Any]]:
        """
        获取当前音轨列表

        Returns:
            List[Dict[str, Any]]: 音轨列表
        """
        if self._mpv_core is None:
            return []

        try:
            return self._mpv_core.get_audio_tracks()
        except RuntimeError as e:
            error(f"获取音轨列表失败: {e}")
            return []

    def _do_set_audio_track(self, track_id: Union[int, str, None]) -> bool:
        """
        切换当前音轨

        Args:
            track_id: 音轨ID，None表示自动选择

        Returns:
            bool: 是否成功
        """
        if self._mpv_core is None:
            warning("MPV未初始化，无法切换音轨")
            return False

        try:
            return self._mpv_core.set_audio_track(track_id)
        except RuntimeError as e:
            error(f"切换音轨失败: {e}")
            return False

    # ==================== 信号处理回调 ====================

    def _request_state_changed_emit(self):
        """请求发射节流后的状态变化信号"""
        QMetaObject.invokeMethod(
            self,
            "_schedule_state_changed_emit",
            Qt.QueuedConnection
        )

    @Slot()
    def _schedule_state_changed_emit(self):
        """按节流策略调度状态变化信号"""
        now = time.monotonic()
        elapsed_ms = (now - self._last_state_emit_time) * 1000

        if elapsed_ms >= self._state_emit_interval_ms and not self._state_emit_timer.isActive():
            self._emit_state_changed_now()
            return

        self._state_emit_pending = True
        remaining_ms = max(1, int(self._state_emit_interval_ms - elapsed_ms))
        if not self._state_emit_timer.isActive():
            self._state_emit_timer.start(remaining_ms)

    @Slot()
    def _flush_state_changed(self):
        """定时器触发后发射最新状态"""
        if self._state_emit_pending:
            self._emit_state_changed_now()

    def _pump_core_signals(self):
        """泵浦核心的信号队列（在主线程上每 100ms 执行一次）"""
        # 健康探测：检测工作线程是否意外死亡
        if not self._core_crashed and self._mpv_core is not None:
            try:
                if self._mpv_core._is_worker_crashed():
                    self._core_crashed = True
                    self._core_crash_reason = self._mpv_core.get_worker_crash_info()
                    crash_msg = f"MPV核心工作线程已崩溃: {self._core_crash_reason}"
                    error(crash_msg)
                    QMetaObject.invokeMethod(
                        self, "coreCrashed", Qt.QueuedConnection,
                        Q_ARG(str, crash_msg)
                    )
            except (RuntimeError, AttributeError):
                pass

        # 核心已崩溃时不再处理信号队列（访问损坏的 mpv 句柄会触发 access violation）
        if not self._core_crashed and self._mpv_core is not None and hasattr(self._mpv_core, '_process_signal_queue'):
            try:
                self._mpv_core._process_signal_queue()
            except (RuntimeError, AttributeError):
                pass

    def _emit_state_changed_now(self):
        """立即发射最新状态快照"""
        self._state_emit_pending = False
        self._last_state_emit_time = time.monotonic()
        self.stateChanged.emit(self.get_state())

    def _on_state_changed(self, is_playing: bool):
        """播放状态变化回调"""
        # debug(f"[MGR_STATE] stateChanged(playing={is_playing}) → 请求发射")
        self._request_state_changed_emit()

    def _on_position_changed(self, position: float, duration: float):
        """位置变化回调"""
        # debug(f"[MGR_POS] positionChanged(pos={position}, dur={duration}) → 转发")
        self.positionChanged.emit(position, duration)

    def _on_duration_changed(self, duration: float):
        """时长变化回调"""
        # debug(f"管理器收到 durationChanged: duration={duration}")
        # 从core获取当前缓存位置，避免阻塞
        position = self._mpv_core.get_position_cached() if self._mpv_core else 0.0
        # debug(f"[MGR_DUR] durationChanged(dur={duration}) → 读取缓存位置 {position} → positionChanged")
        self.positionChanged.emit(position if position is not None else 0.0, duration)
    def _on_volume_changed(self, volume: int):
        """音量变化回调"""
        self.volumeChanged.emit(volume)

    def _on_speed_changed(self, speed: float):
        """速度变化回调"""
        self.speedChanged.emit(speed)

    def _on_muted_changed(self, muted: bool):
        """静音状态变化回调"""
        self.mutedChanged.emit(muted)

    def _on_file_loaded(self, file_path: str):
        """文件加载完成回调"""
        self.fileLoaded.emit(file_path)

    def _on_file_ended(self, reason: int):
        """文件播放结束回调"""
        self.fileEnded.emit(reason)

    @Slot(int, str)
    def _emit_error_occurred(self, error_code: int, error_message: str):
        """发射错误信号（供 QMetaObject.invokeMethod 调用）"""
        self.errorOccurred.emit(error_code, error_message)

    def _on_error_occurred(self, error_code: int, error_message: str):
        """错误发生回调（由 MPVPlayerCore 信号触发，已在主线程）"""
        self.errorOccurred.emit(error_code, error_message)

    # ==================== LuaJIT VEH 处理器 ====================

    # x64 机器码: VEH handler — 捕获 LuaJIT 0xE24C4A02 异常
    # RCX = PEXCEPTION_POINTERS
    # 匹配 ExceptionCode → 返回 CONTINUE_EXECUTION 让 LuaJIT fallback 执行
    _LUAJIT_VEH_SHELLCODE = bytes([
        0x48, 0x8B, 0x01,                         # mov rax, [rcx]
        0x8B, 0x00,                               # mov eax, [rax]
        0x3D, 0x02, 0x4A, 0x4C, 0xE2,             # cmp eax, 0xE24C4A02
        0x74, 0x03,                               # je  +3
        0x33, 0xC0,                               # xor eax, eax (CONTINUE_SEARCH)
        0xC3,                                     # ret
        0xB8, 0xFF, 0xFF, 0xFF, 0xFF,             # mov eax, -1 (CONTINUE_EXECUTION)
        0xC3,                                     # ret
    ])

    def _register_luajit_veh(self):
        """注册 LuaJIT VEH 处理器（mpv 初始化前调用）"""
        import ctypes
        from ctypes import wintypes

        if self._luajit_veh_handle is not None:
            return  # 已注册

        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

            # 分配可执行内存
            PAGE_EXECUTE_READWRITE = 0x40
            MEM_COMMIT_RESERVE = 0x3000
            VirtualAlloc = kernel32.VirtualAlloc
            VirtualAlloc.restype = ctypes.c_void_p
            VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]

            p_fn = VirtualAlloc(None, len(self._LUAJIT_VEH_SHELLCODE), MEM_COMMIT_RESERVE, PAGE_EXECUTE_READWRITE)
            if not p_fn:
                raise RuntimeError("VirtualAlloc 失败")

            ctypes.memmove(p_fn, self._LUAJIT_VEH_SHELLCODE, len(self._LUAJIT_VEH_SHELLCODE))

            # 注册为 First-chance VEH
            AddVectoredExceptionHandler = kernel32.AddVectoredExceptionHandler
            AddVectoredExceptionHandler.argtypes = [wintypes.ULONG, ctypes.c_void_p]
            AddVectoredExceptionHandler.restype = ctypes.c_void_p

            handle = AddVectoredExceptionHandler(0, p_fn)
            if not handle:
                raise RuntimeError("AddVectoredExceptionHandler 返回 NULL")

            self._luajit_veh_handle = handle
            self._luajit_veh_fn = p_fn
            info("LuaJIT SEH VEH 处理器已注册 (0xE24C4A02)")
        except Exception as e:
            warning(f"LuaJIT SEH VEH 处理器注册失败: {e}")

    def _unregister_luajit_veh(self):
        """注销 LuaJIT VEH 处理器（mpv 关闭后调用）"""
        if self._luajit_veh_handle is None:
            return
        try:
            import ctypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            # 注意：RemoveVectoredExceptionHandler 处理 64 位 handle 需要特殊处理
            # 这里直接传 int，Windows 64 位 API 会正确处理
            # 即使移除失败也不影响进程退出
            try:
                kernel32.RemoveVectoredExceptionHandler(self._luajit_veh_handle)
            except (OverflowError, ctypes.ArgumentError):
                pass  # 64 位 handle 可能超出 ctypes 默认范围，忽略
            self._luajit_veh_handle = None
            self._luajit_veh_fn = None
            info("LuaJIT SEH VEH 处理器已注销")
        except Exception:
            pass

    # ==================== 核心健康检测 ====================

    def _check_core_health(self) -> bool:
        """
        检查MPV核心是否健康（未崩溃）

        Returns:
            bool: True=健康, False=已崩溃
        """
        if self._core_crashed:
            return False

        if self._mpv_core is None:
            return False

        if self._mpv_core._is_worker_crashed():
            self._core_crashed = True
            self._core_crash_reason = self._mpv_core.get_worker_crash_info()
            crash_msg = f"MPV核心工作线程已崩溃: {self._core_crash_reason}"
            error(crash_msg)
            self.coreCrashed.emit(crash_msg)
            return False

        return True

    def is_core_healthy(self) -> bool:
        """
        公开接口：检查MPV核心是否健康

        Returns:
            bool: True=健康可用, False=已崩溃需重新初始化
        """
        return self._check_core_health()

    def reset_core_crash(self):
        """重置核心崩溃状态（重新初始化前调用）"""
        self._core_crashed = False
        self._core_crash_reason = ""
        if self._mpv_core is not None:
            self._mpv_core.reset_crash_state()

    # ==================== 公共API接口 ====================

    def initialize(self, timeout: float = 10.0, wait_for_cleanup: bool = True) -> bool:
        """
        初始化MPV管理器

        Args:
            timeout: 初始化超时时间（秒）
            wait_for_cleanup: 是否等待上次清理完成（默认为True）

        Returns:
            是否初始化成功
        """
        # 重置核心崩溃状态
        self.reset_core_crash()

        # 检查并等待上次清理完成（避免冲突）
        if wait_for_cleanup and not self.ensure_cleanup_complete(timeout=5.0):
            warning("上次清理未完成，可能存在资源冲突")
            # 继续尝试初始化，但记录警告
        
        # 如果正在关闭中，等待关闭完成
        if self._is_shutting_down:
            info("等待关闭完成后再初始化...")
            if not self.wait_for_cleanup(timeout=5.0):
                error("等待关闭完成超时")
                return False

        # 在主线程上创建MPV核心（确保QObject/QTimer拥有正确的事件循环）
        if self._mpv_core is None:
            self._mpv_core = MPVPlayerCore()

        self._start_operation_thread()

        future = self._submit_operation(
            MPVOperationType.INITIALIZE,
            component_id="manager",
            priority=1
        )

        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            error("初始化操作超时")
            return False
        except RuntimeError as e:
            error(f"初始化失败: {e}")
            return False

    def close(self, async_mode: bool = True, timeout: float = 2.0) -> bool:
        """
        关闭MPV管理器

        Args:
            async_mode: 是否异步关闭（True=立即返回，后台清理）
            timeout: 同步模式下的超时时间（秒）

        Returns:
            是否关闭成功（异步模式下总是返回True）
        """
        # 如果已经在关闭中，直接返回
        if self._is_shutting_down:
            # 如果不是异步模式，等待上次清理完成
            if not async_mode:
                self.wait_for_cleanup(timeout)
            return True

        with self._shutdown_lock:
            self._is_shutting_down = True
        self._cleanup_event.clear()  # 标记清理开始

        # 如果操作线程未运行，直接清理并重置状态
        if not self._operation_thread or not self._operation_thread.is_alive():
            self._cleanup_resources()
            with self._shutdown_lock:
                self._is_shutting_down = False
            self._cleanup_event.set()  # 标记清理完成
            return True

        if async_mode:
            # 异步模式：启动后台线程执行关闭
            self._async_cleanup_thread = threading.Thread(
                target=self._do_async_close,
                args=(timeout,),
                name="MPVAsyncCleanupThread",
                daemon=True
            )
            self._async_cleanup_thread.start()
            return True
        else:
            # 同步模式：直接执行关闭
            try:
                result = self._do_sync_close(timeout)
                return result
            except RuntimeError as e:
                error(f"关闭MPV管理器失败: {e}")
                self._do_force_cleanup()
                return False
    
    def _do_sync_close(self, timeout: float = 2.0) -> bool:
        """同步关闭 - 通过操作队列提交CLOSE命令，确保在操作线程中执行"""
        try:
            # 通过操作队列提交CLOSE命令，确保线程安全
            future = self._submit_operation(
                MPVOperationType.CLOSE,
                component_id="manager",
                priority=1
            )
            result = future.result(timeout=timeout)
            self._stop_operation_thread(timeout)
            self._cleanup_resources()
            with self._shutdown_lock:
                self._is_shutting_down = False
            self._cleanup_event.set()  # 标记清理完成
            return result
        except RuntimeError as e:
            error(f"同步关闭失败: {e}")
            self._do_force_cleanup()
            raise

    def _do_async_close(self, timeout: float = 3.0):
        """异步关闭 - 在后台执行"""
        try:
            info("开始异步关闭MPV管理器")

            # 先通过操作队列提交关闭命令，再停止线程
            if self._mpv_core and self._operation_thread and self._operation_thread.is_alive():
                future = self._submit_operation(
                    MPVOperationType.CLOSE,
                    component_id="manager",
                    priority=1
                )
                try:
                    future.result(timeout=timeout)
                except (FutureTimeoutError, RuntimeError):
                    pass

            # 停止操作线程
            self._stop_operation_thread(timeout)

            # 执行关闭（已通过操作队列执行，但确保资源清理）
            self._do_close()
            self._cleanup_resources()

            info("异步关闭MPV管理器完成")
        except RuntimeError as e:
            error(f"异步关闭失败: {e}")
        finally:
            with self._shutdown_lock:
                self._is_shutting_down = False
            self._cleanup_event.set()  # 标记清理完成
            self._async_cleanup_thread = None
    
    def _do_force_cleanup(self):
        """强制清理 - 在出错时使用"""
        try:
            self._stop_operation_thread(1.0)
            self._cleanup_resources()
        except RuntimeError as e:
            error(f"强制清理失败: {e}")
        finally:
            with self._shutdown_lock:
                self._is_shutting_down = False
            self._cleanup_event.set()
    
    def wait_for_cleanup(self, timeout: float = 5.0) -> bool:
        """
        等待清理完成
        
        Args:
            timeout: 最大等待时间（秒）
            
        Returns:
            bool: 是否在超时前完成清理
        """
        return self._cleanup_event.wait(timeout=timeout)
    
    def is_cleanup_complete(self) -> bool:
        """检查清理是否已完成"""
        return self._cleanup_event.is_set()
    
    def ensure_cleanup_complete(self, timeout: float = 5.0) -> bool:
        """
        确保上次清理已完成（在初始化前调用）
        
        Args:
            timeout: 最大等待时间（秒）
            
        Returns:
            bool: 清理是否完成
        """
        if not self._cleanup_event.is_set():
            info("等待上次清理完成...")
            completed = self._cleanup_event.wait(timeout=timeout)
            if not completed:
                warning(f"等待清理完成超时（{timeout}s）")
            return completed
        return True

    def load_file(
        self,
        file_path: str,
        is_audio: bool = False,
        component_id: str = "unknown",
        timeout: float = 30.0
    ) -> bool:
        """
        加载媒体文件

        Args:
            file_path: 文件路径
            is_audio: 是否为音频文件
            component_id: 组件标识
            timeout: 超时时间（秒）

        Returns:
            是否加载成功
        """
        try:
            future = self._submit_operation(
                MPVOperationType.LOAD_FILE,
                file_path,
                is_audio,
                component_id=component_id,
                priority=3
            )
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            error(f"加载文件超时: {file_path}")
            return False
        except RuntimeError as e:
            error(f"加载文件失败: {e}")
            return False

    def play(self, component_id: str = "unknown") -> bool:
        """
        开始播放

        Args:
            component_id: 组件标识

        Returns:
            是否操作成功
        """
        try:
            future = self._submit_operation(
                MPVOperationType.PLAY,
                component_id=component_id,
                priority=2
            )
            return future.result(timeout=5.0)
        except FutureTimeoutError:
            return False
        except RuntimeError as e:
            error(f"播放失败: {e}")
            return False

    def pause(self, component_id: str = "unknown") -> bool:
        """
        暂停播放

        Args:
            component_id: 组件标识

        Returns:
            是否操作成功
        """
        try:
            future = self._submit_operation(
                MPVOperationType.PAUSE,
                component_id=component_id,
                priority=2
            )
            return future.result(timeout=5.0)
        except FutureTimeoutError:
            return False
        except RuntimeError as e:
            error(f"暂停失败: {e}")
            return False

    def stop(self, component_id: str = "unknown") -> bool:
        """
        停止播放

        Args:
            component_id: 组件标识

        Returns:
            是否操作成功
        """
        try:
            future = self._submit_operation(
                MPVOperationType.STOP,
                component_id=component_id,
                priority=2
            )
            return future.result(timeout=5.0)
        except FutureTimeoutError:
            return False
        except RuntimeError as e:
            error(f"停止失败: {e}")
            return False

    def seek(
        self,
        position: float,
        component_id: str = "unknown"
    ) -> bool:
        """
        跳转到指定位置

        Args:
            position: 目标位置（秒）
            component_id: 组件标识

        Returns:
            是否操作成功
        """
        # 第一重快速检查：关闭中直接返回
        if self._is_shutting_down:
            return False
            
        try:
            future = self._submit_operation(
                MPVOperationType.SEEK,
                position,
                component_id=component_id,
                priority=3
            )
            return future.result(timeout=5.0)
        except FutureTimeoutError:
            return False
        except RuntimeError as e:
            if not self._is_shutting_down:
                error(f"跳转失败: {e}")
            return False

    def seek_async(
        self,
        position: float,
        component_id: str = "unknown",
        exact: bool = False
    ) -> Future:
        """
        异步跳转到指定位置。

        用于进度条拖动这类高频交互。提交后立即返回 Future，仍复用
        _submit_operation 的同组件同类型合并逻辑，避免旧 seek 堆积。
        默认使用关键帧 seek，松手落点可传 exact=True 再做精确 seek。
        """
        future = Future()

        if self._is_shutting_down:
            future.set_result(False)
            return future

        try:
            return self._submit_operation(
                MPVOperationType.SEEK,
                position,
                component_id=component_id,
                priority=3,
                exact=exact,
            )
        except RuntimeError as e:
            if not self._is_shutting_down:
                error(f"异步跳转失败: {e}")
            future.set_result(False)
            return future

    def set_position(
        self,
        position: float,
        component_id: str = "unknown"
    ) -> bool:
        """
        设置播放位置

        Args:
            position: 目标位置（秒）
            component_id: 组件标识

        Returns:
            是否操作成功
        """
        try:
            future = self._submit_operation(
                MPVOperationType.SET_POSITION,
                position,
                component_id=component_id,
                priority=3
            )
            return future.result(timeout=5.0)
        except FutureTimeoutError:
            return False
        except RuntimeError as e:
            error(f"设置位置失败: {e}")
            return False

    def set_volume(
        self,
        volume: int,
        component_id: str = "unknown"
    ) -> bool:
        """
        设置音量

        Args:
            volume: 音量值（0-100）
            component_id: 组件标识

        Returns:
            是否操作成功
        """
        try:
            future = self._submit_operation(
                MPVOperationType.SET_VOLUME,
                volume,
                component_id=component_id,
                priority=4
            )
            return future.result(timeout=5.0)
        except FutureTimeoutError:
            return False
        except RuntimeError as e:
            error(f"设置音量失败: {e}")
            return False

    def set_speed(
        self,
        speed: float,
        component_id: str = "unknown"
    ) -> bool:
        """
        设置播放速度

        Args:
            speed: 播放速度（0.5-2.0）
            component_id: 组件标识

        Returns:
            是否操作成功
        """
        try:
            future = self._submit_operation(
                MPVOperationType.SET_SPEED,
                speed,
                component_id=component_id,
                priority=4
            )
            return future.result(timeout=5.0)
        except FutureTimeoutError:
            return False
        except RuntimeError as e:
            error(f"设置速度失败: {e}")
            return False

    def set_muted(
        self,
        muted: bool,
        component_id: str = "unknown"
    ) -> bool:
        """
        设置静音状态

        Args:
            muted: 是否静音
            component_id: 组件标识

        Returns:
            是否操作成功
        """
        try:
            future = self._submit_operation(
                MPVOperationType.SET_MUTED,
                muted,
                component_id=component_id,
                priority=4
            )
            return future.result(timeout=5.0)
        except FutureTimeoutError:
            return False
        except RuntimeError as e:
            error(f"设置静音失败: {e}")
            return False

    def set_loop(
        self,
        loop_mode: str,
        component_id: str = "unknown"
    ) -> bool:
        """
        设置循环模式

        Args:
            loop_mode: 循环模式（"no", "inf", "number"）
            component_id: 组件标识

        Returns:
            是否操作成功
        """
        try:
            future = self._submit_operation(
                MPVOperationType.SET_LOOP,
                loop_mode,
                component_id=component_id,
                priority=4
            )
            return future.result(timeout=5.0)
        except FutureTimeoutError:
            return False
        except RuntimeError as e:
            error(f"设置循环模式失败: {e}")
            return False

    def set_window_id(
        self,
        window_id: int,
        component_id: str = "unknown"
    ) -> bool:
        """
        设置视频输出窗口ID

        Args:
            window_id: 窗口句柄ID
            component_id: 组件标识

        Returns:
            是否设置成功
        """
        try:
            future = self._submit_operation(
                MPVOperationType.SET_WINDOW_ID,
                window_id,
                component_id=component_id,
                priority=1
            )
            return future.result(timeout=10.0)
        except FutureTimeoutError:
            return False
        except RuntimeError as e:
            error(f"设置窗口ID失败: {e}")
            return False

    def get_position(self) -> float:
        """
        获取当前播放位置（非阻塞，直接读取核心缓存）

        Returns:
            当前位置（秒）
        """
        if self._mpv_core is None or self._is_shutting_down:
            return 0.0
        result = self._mpv_core.get_position_cached()
        return result if result is not None else 0.0

    def get_duration(self) -> float:
        """
        获取媒体总时长（非阻塞，直接读取核心缓存）

        Returns:
            总时长（秒）
        """
        if self._mpv_core is None or self._is_shutting_down:
            return 0.0
        result = self._mpv_core.get_duration_cached()
        return result if result is not None else 0.0

    def get_volume(self) -> int:
        """
        获取当前音量（非阻塞，直接读取核心缓存）

        Returns:
            音量值（0-100）
        """
        if self._mpv_core is None:
            return 100
        return self._mpv_core.get_volume()

    def get_speed(self) -> float:
        """
        获取当前播放速度（非阻塞，直接读取核心缓存）

        Returns:
            播放速度
        """
        if self._mpv_core is None:
            return 1.0
        return self._mpv_core.get_speed()

    def is_playing(self) -> bool:
        """
        获取是否正在播放（非阻塞，直接读取核心缓存）

        Returns:
            是否正在播放
        """
        if self._mpv_core is None:
            return False
        return self._mpv_core.is_playing()

    def is_paused(self) -> bool:
        """
        获取是否暂停（非阻塞，直接读取核心缓存）

        Returns:
            是否暂停
        """
        if self._mpv_core is None:
            return False
        return self._mpv_core.is_paused()

    def is_muted(self) -> bool:
        """
        获取是否静音（非阻塞，直接读取核心缓存）

        Returns:
            是否静音
        """
        if self._mpv_core is None:
            return False
        return self._mpv_core.is_muted()

    def get_video_size(self) -> Tuple[int, int]:
        """
        获取视频尺寸

        Returns:
            (宽度, 高度)元组
        """
        if self._mpv_core is None:
            return (0, 0)
        return self._mpv_core.get_video_size()

    def load_lut(self, lut_file_path: str, component_id: str = "unknown", timeout: float = 5.0) -> bool:
        """
        加载LUT文件

        Args:
            lut_file_path: LUT文件路径
            component_id: 组件标识
            timeout: 超时时间（秒）

        Returns:
            是否加载成功
        """
        try:
            future = self._submit_operation(
                MPVOperationType.LOAD_LUT,
                lut_file_path,
                component_id=component_id,
                priority=3
            )
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            error(f"加载LUT超时: {lut_file_path}")
            return False
        except RuntimeError as e:
            error(f"加载LUT失败: {e}")
            return False

    def unload_lut(self, component_id: str = "unknown", timeout: float = 5.0) -> bool:
        """
        卸载LUT文件

        Args:
            component_id: 组件标识
            timeout: 超时时间（秒）

        Returns:
            是否卸载成功
        """
        try:
            future = self._submit_operation(
                MPVOperationType.UNLOAD_LUT,
                component_id=component_id,
                priority=3
            )
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            error("卸载LUT超时")
            return False
        except RuntimeError as e:
            error(f"卸载LUT失败: {e}")
            return False

    def load_subtitle(self, subtitle_file_path: str, component_id: str = "unknown", timeout: float = 5.0) -> bool:
        """
        加载外部字幕文件

        Args:
            subtitle_file_path: 字幕文件路径
            component_id: 组件标识
            timeout: 超时时间（秒）

        Returns:
            是否加载成功
        """
        try:
            future = self._submit_operation(
                MPVOperationType.LOAD_SUBTITLE,
                subtitle_file_path,
                component_id=component_id,
                priority=3
            )
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            error(f"加载字幕超时: {subtitle_file_path}")
            return False
        except RuntimeError as e:
            error(f"加载字幕失败: {e}")
            return False

    def get_subtitle_state(self, timeout: float = 1.0) -> Dict[str, Any]:
        """
        获取当前字幕状态

        Args:
            timeout: 超时时间（秒）

        Returns:
            Dict[str, Any]: 字幕状态字典
        """
        try:
            future = self._submit_operation(
                MPVOperationType.GET_SUBTITLE_STATE,
                priority=5
            )
            result = future.result(timeout=timeout)
            return result if isinstance(result, dict) else {}
        except FutureTimeoutError:
            return {}
        except RuntimeError as e:
            error(f"获取字幕状态失败: {e}")
            return {}

    def get_subtitle_tracks(self, timeout: float = 1.0) -> List[Dict[str, Any]]:
        """
        获取当前字幕轨列表

        Args:
            timeout: 超时时间（秒）

        Returns:
            List[Dict[str, Any]]: 字幕轨列表
        """
        try:
            future = self._submit_operation(
                MPVOperationType.GET_SUBTITLE_TRACKS,
                priority=5
            )
            result = future.result(timeout=timeout)
            return result if isinstance(result, list) else []
        except FutureTimeoutError:
            return []
        except RuntimeError as e:
            error(f"获取字幕轨列表失败: {e}")
            return []

    def set_subtitle_visibility(
        self,
        visible: bool,
        component_id: str = "unknown",
        timeout: float = 5.0
    ) -> bool:
        """
        设置字幕可见性

        Args:
            visible: 是否显示字幕
            component_id: 组件标识
            timeout: 超时时间（秒）

        Returns:
            bool: 是否设置成功
        """
        try:
            future = self._submit_operation(
                MPVOperationType.SET_SUBTITLE_VISIBILITY,
                visible,
                component_id=component_id,
                priority=3
            )
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            error("设置字幕可见性超时")
            return False
        except RuntimeError as e:
            error(f"设置字幕可见性失败: {e}")
            return False

    def set_subtitle_track(
        self,
        track_id: Union[int, str, None],
        component_id: str = "unknown",
        timeout: float = 5.0
    ) -> bool:
        """
        切换当前字幕轨

        Args:
            track_id: 字幕轨ID，None表示隐藏字幕
            component_id: 组件标识
            timeout: 超时时间（秒）

        Returns:
            bool: 是否切换成功
        """
        try:
            future = self._submit_operation(
                MPVOperationType.SET_SUBTITLE_TRACK,
                track_id,
                component_id=component_id,
                priority=3
            )
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            error(f"切换字幕轨超时: {track_id}")
            return False
        except RuntimeError as e:
            error(f"切换字幕轨失败: {e}")
            return False

    def hide_subtitle(self, component_id: str = "unknown", timeout: float = 5.0) -> bool:
        """
        隐藏当前字幕

        Args:
            component_id: 组件标识
            timeout: 超时时间（秒）

        Returns:
            bool: 是否成功
        """
        return self.set_subtitle_visibility(False, component_id=component_id, timeout=timeout)

    def get_audio_state(self, timeout: float = 1.0) -> Dict[str, Any]:
        """
        获取当前音轨状态

        Args:
            timeout: 超时时间（秒）

        Returns:
            Dict[str, Any]: 音轨状态字典
        """
        try:
            future = self._submit_operation(
                MPVOperationType.GET_AUDIO_STATE,
                priority=5
            )
            result = future.result(timeout=timeout)
            return result if isinstance(result, dict) else {}
        except FutureTimeoutError:
            return {}
        except RuntimeError as e:
            error(f"获取音轨状态失败: {e}")
            return {}

    def get_audio_tracks(self, timeout: float = 1.0) -> List[Dict[str, Any]]:
        """
        获取当前音轨列表

        Args:
            timeout: 超时时间（秒）

        Returns:
            List[Dict[str, Any]]: 音轨列表
        """
        try:
            future = self._submit_operation(
                MPVOperationType.GET_AUDIO_TRACKS,
                priority=5
            )
            result = future.result(timeout=timeout)
            return result if isinstance(result, list) else []
        except FutureTimeoutError:
            return []
        except RuntimeError as e:
            error(f"获取音轨列表失败: {e}")
            return []

    def set_audio_track(
        self,
        track_id: Union[int, str, None],
        component_id: str = "unknown",
        timeout: float = 5.0
    ) -> bool:
        """
        切换当前音轨

        Args:
            track_id: 音轨ID，None表示自动选择
            component_id: 组件标识
            timeout: 超时时间（秒）

        Returns:
            bool: 是否切换成功
        """
        try:
            future = self._submit_operation(
                MPVOperationType.SET_AUDIO_TRACK,
                track_id,
                component_id=component_id,
                priority=3
            )
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            error(f"切换音轨超时: {track_id}")
            return False
        except RuntimeError as e:
            error(f"切换音轨失败: {e}")
            return False

    def get_current_lut(self) -> str:
        """
        获取当前加载的LUT文件路径

        Returns:
            LUT文件路径，未加载则返回空字符串
        """
        if self._mpv_core is None:
            return ""
        # 从core的loop_file属性间接判断LUT状态
        return ""

    def get_state(self) -> MPVState:
        """
        获取当前状态（从MPVPlayerCore实时读取，不缓存）

        Returns:
            当前状态的数据类副本
        """
        core = self._mpv_core
        if core is None:
            return MPVState()

        return MPVState(
            is_initialized=True,
            is_playing=core.is_playing(),
            is_paused=core.is_paused(),
            is_muted=core.is_muted(),
            position=core.get_position_cached() or 0.0,
            duration=core.get_duration_cached() or 0.0,
            volume=core.get_volume(),
            speed=core.get_speed(),
            loop_mode=core.get_loop_mode(),
            current_file=core.get_current_file(),
            video_width=0,
            video_height=0,
            error_code=0,
            error_message="",
            last_update=time.time(),
            current_lut=self.get_current_lut()
        )

    def is_busy(self) -> bool:
        """
        获取是否正在处理操作

        Returns:
            是否忙碌
        """
        return self._is_busy

    def is_initialized(self) -> bool:
        """
        获取是否已初始化

        Returns:
            是否已初始化
        """
        return self._mpv_core is not None

    def get_position_direct(self) -> Optional[float]:
        """
        直接获取当前播放位置（不经过队列，用于UI快速更新）
        
        Returns:
            当前位置（秒），失败返回None
        """
        if self._mpv_core is None or self._is_shutting_down:
            return None
        return self._mpv_core.get_position_cached()

    def get_duration_direct(self) -> Optional[float]:
        """
        直接获取媒体总时长（不经过队列，用于UI快速更新）
        
        Returns:
            总时长（秒），失败返回None
        """
        if self._mpv_core is None or self._is_shutting_down:
            return None
        return self._mpv_core.get_duration_cached()

    # ==================== 组件管理 ====================

    def register_component(
        self,
        component_id: str,
        component_type: str,
        callback: Optional[Callable] = None
    ) -> bool:
        """
        注册组件

        Args:
            component_id: 组件唯一标识
            component_type: 组件类型
            callback: 回调函数

        Returns:
            是否注册成功
        """
        with self._component_lock:
            if component_id in self._registered_components:
                warning(f"组件已存在: {component_id}")
                return False

            self._registered_components[component_id] = {
                "type": component_type,
                "callback": callback,
                "registered_at": time.time()
            }

        info(f"组件已注册: {component_id}, 类型: {component_type}")
        return True

    def unregister_component(self, component_id: str) -> bool:
        """
        注销组件

        Args:
            component_id: 组件唯一标识

        Returns:
            是否注销成功
        """
        with self._component_lock:
            if component_id not in self._registered_components:
                return False

            del self._registered_components[component_id]

        info(f"组件已注销: {component_id}")
        return True

    def get_registered_components(self) -> Dict[str, Dict[str, Any]]:
        """
        获取已注册的组件列表

        Returns:
            组件字典
        """
        with self._component_lock:
            return self._registered_components.copy()

    # ==================== 日志管理 ====================

    def get_logs(self, count: int = 100) -> List[Dict[str, Any]]:
        """
        获取最近的日志

        Args:
            count: 日志条数

        Returns:
            日志列表
        """
        return []

    # ==================== 析构 ====================

    def __del__(self):
        """析构函数"""
        try:
            if self._mpv_core is not None:
                self.close()
        except RuntimeError as e:
            pass
            # debug(f"析构时关闭MPV管理器失败: {e}")


# 便捷函数，用于快速获取管理器实例
def get_mpv_manager() -> MPVManager:
    """
    获取MPV管理器实例

    Returns:
        MPVManager实例
    """
    return MPVManager()
