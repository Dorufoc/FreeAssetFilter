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

import os
import sys
import time
import threading
import traceback
from enum import Enum, IntEnum
from dataclasses import dataclass, field
from typing import Optional, Callable, Dict, Any, List, Union, Tuple
from queue import Queue, Empty
from threading import Lock, RLock, Event
from concurrent.futures import Future, TimeoutError as FutureTimeoutError

from PySide6.QtCore import (
    QObject, Signal, Slot, QThread, QMutex, QWaitCondition,
    QTimer, Qt, QMetaObject, Q_ARG
)
from PySide6.QtWidgets import QWidget

# 导入MPV核心
from freeassetfilter.core.mpv_player_core import (
    MPVPlayerCore, MpvEndFileReason, MpvErrorCode
)

# 导入日志模块
from freeassetfilter.utils.app_logger import info, debug, warning, error


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


class MPVManagerLogger:
    """MPV管理器日志记录器"""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.log_history: List[Dict[str, Any]] = []
        self.max_history = 1000

    def log(self, level: str, message: str, **kwargs):
        """记录日志"""
        if not self.enabled:
            return

        log_entry = {
            "timestamp": time.time(),
            "level": level,
            "message": message,
            **kwargs
        }

        self.log_history.append(log_entry)

        # 限制历史记录大小
        if len(self.log_history) > self.max_history:
            self.log_history = self.log_history[-self.max_history:]

        # 打印到控制台
        #print(f"[MPVManager][{level}] {message}")

    def debug(self, message: str, **kwargs):
        """记录调试日志"""
        self.log("DEBUG", message, **kwargs)

    def info(self, message: str, **kwargs):
        """记录信息日志"""
        self.log("INFO", message, **kwargs)

    def warning(self, message: str, **kwargs):
        """记录警告日志"""
        self.log("WARNING", message, **kwargs)

    def error(self, message: str, **kwargs):
        """记录错误日志"""
        self.log("ERROR", message, **kwargs)

    def get_recent_logs(self, count: int = 100) -> List[Dict[str, Any]]:
        """获取最近的日志记录"""
        return self.log_history[-count:]


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
        debug(f"当前位置: {state.position}")

        # 关闭MPV
        manager.close()
    """

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

    def __init__(self, parent=None, enable_logging: bool = True):
        """
        初始化MPV管理器

        Args:
            parent: 父对象
            enable_logging: 是否启用日志记录
        """
        # 避免重复初始化
        if self._initialized:
            return

        super().__init__(parent)

        # 初始化日志记录器
        self._logger = MPVManagerLogger(enabled=enable_logging)
        self._logger.info("MPV管理器初始化开始")

        # MPV核心实例
        self._mpv_core: Optional[MPVPlayerCore] = None

        # 状态管理
        self._current_state = MPVState()
        self._state_lock = RLock()

        # 资源锁定
        self._resource_lock = RLock()
        self._is_busy = False

        # 操作队列
        self._operation_queue: Queue = Queue()
        self._queue_lock = Lock()
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

        self._logger.info("MPV管理器初始化完成")

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
            self._logger.info("操作处理线程已启动")

    def _stop_operation_thread(self, timeout: float = 2.0):
        """停止操作处理线程"""
        if self._operation_thread and self._operation_thread.is_alive():
            self._stop_event.set()
            self._operation_thread.join(timeout=timeout)
            if self._operation_thread.is_alive():
                self._logger.warning(f"操作处理线程未在 {timeout}s 内停止")
            else:
                self._logger.info("操作处理线程已停止")

    def _cleanup_resources(self):
        """清理资源"""
        self._logger.info("清理MPV管理器资源")
        # 清空操作队列
        while not self._operation_queue.empty():
            try:
                self._operation_queue.get_nowait()
            except Empty:
                debug("清空操作队列: 队列为空")
                break
        with self._pending_operation_lock:
            self._pending_latest_operations.clear()
        # 清空组件注册表
        self._registered_components.clear()
        # 重置状态
        self._current_state = MPVState()
        self._current_file = ""
        self._position = 0.0
        self._duration = 0.0
        self._volume = 100
        self._muted = False
        self._speed = 1.0
        self._loop = "no"

    def _process_operations(self):
        """处理操作队列的主循环"""
        self._logger.info("操作处理循环开始")

        while not self._stop_event.is_set():
            operation = None
            try:
                # 从队列获取操作，超时1秒
                operation = self._operation_queue.get(timeout=1.0)

                if operation is None:
                    continue

                if operation.operation_type in self._coalescible_operations:
                    pending_key = (operation.component_id, operation.operation_type.value)
                    with self._pending_operation_lock:
                        latest_operation = self._pending_latest_operations.get(pending_key)
                        if latest_operation is not operation:
                            self._logger.debug(
                                f"跳过过期操作: {operation.operation_type.value}, "
                                f"组件: {operation.component_id}"
                            )
                            if operation.future and not operation.future.done():
                                operation.future.set_result(False)
                            continue
                        self._pending_latest_operations.pop(pending_key, None)

                self._logger.debug(
                    f"处理操作: {operation.operation_type.value}, "
                    f"组件: {operation.component_id}"
                )

                # 执行操作
                result = self._execute_operation(operation)

                # 设置Future结果
                if operation.future and not operation.future.done():
                    operation.future.set_result(result)

            except Empty:
                # 队列为空，继续循环
                continue
            except RuntimeError as e:
                error(f"处理操作时运行时错误: {e}")
                traceback.print_exc()
                # 设置Future异常，避免调用方永久阻塞
                if operation and operation.future and not operation.future.done():
                    operation.future.set_exception(e)

        self._logger.info("操作处理循环结束")

    def _execute_operation(self, operation: MPVOperation) -> Any:
        """
        执行单个操作

        Args:
            operation: 操作对象

        Returns:
            操作结果
        """
        operation_type = operation.operation_type
        args = operation.args
        kwargs = operation.kwargs

        try:
            with self._resource_lock:
                self._is_busy = True

                if operation_type == MPVOperationType.INITIALIZE:
                    return self._do_initialize()

                elif operation_type == MPVOperationType.CLOSE:
                    return self._do_close()

                elif operation_type == MPVOperationType.LOAD_FILE:
                    return self._do_load_file(*args, **kwargs)

                elif operation_type == MPVOperationType.PLAY:
                    return self._do_play()

                elif operation_type == MPVOperationType.PAUSE:
                    return self._do_pause()

                elif operation_type == MPVOperationType.STOP:
                    return self._do_stop()

                elif operation_type == MPVOperationType.SEEK:
                    return self._do_seek(*args, **kwargs)

                elif operation_type == MPVOperationType.SET_POSITION:
                    return self._do_set_position(*args, **kwargs)

                elif operation_type == MPVOperationType.SET_VOLUME:
                    return self._do_set_volume(*args, **kwargs)

                elif operation_type == MPVOperationType.SET_SPEED:
                    return self._do_set_speed(*args, **kwargs)

                elif operation_type == MPVOperationType.SET_MUTED:
                    return self._do_set_muted(*args, **kwargs)

                elif operation_type == MPVOperationType.SET_LOOP:
                    return self._do_set_loop(*args, **kwargs)

                elif operation_type == MPVOperationType.SET_WINDOW_ID:
                    return self._do_set_window_id(*args, **kwargs)

                elif operation_type == MPVOperationType.GET_POSITION:
                    return self._do_get_position()

                elif operation_type == MPVOperationType.GET_DURATION:
                    return self._do_get_duration()

                elif operation_type == MPVOperationType.GET_VOLUME:
                    return self._do_get_volume()

                elif operation_type == MPVOperationType.GET_SPEED:
                    return self._do_get_speed()

                elif operation_type == MPVOperationType.IS_PLAYING:
                    return self._do_is_playing()

                elif operation_type == MPVOperationType.IS_PAUSED:
                    return self._do_is_paused()

                elif operation_type == MPVOperationType.IS_MUTED:
                    return self._do_is_muted()

                elif operation_type == MPVOperationType.GET_VIDEO_SIZE:
                    return self._do_get_video_size()

                elif operation_type == MPVOperationType.LOAD_LUT:
                    return self._do_load_lut(*args, **kwargs)

                elif operation_type == MPVOperationType.UNLOAD_LUT:
                    return self._do_unload_lut()

                elif operation_type == MPVOperationType.LOAD_SUBTITLE:
                    return self._do_load_subtitle(*args, **kwargs)

                elif operation_type == MPVOperationType.GET_SUBTITLE_STATE:
                    return self._do_get_subtitle_state()

                elif operation_type == MPVOperationType.GET_SUBTITLE_TRACKS:
                    return self._do_get_subtitle_tracks()

                elif operation_type == MPVOperationType.SET_SUBTITLE_VISIBILITY:
                    return self._do_set_subtitle_visibility(*args, **kwargs)

                elif operation_type == MPVOperationType.SET_SUBTITLE_TRACK:
                    return self._do_set_subtitle_track(*args, **kwargs)

                elif operation_type == MPVOperationType.GET_AUDIO_STATE:
                    return self._do_get_audio_state()

                elif operation_type == MPVOperationType.GET_AUDIO_TRACKS:
                    return self._do_get_audio_tracks()

                elif operation_type == MPVOperationType.SET_AUDIO_TRACK:
                    return self._do_set_audio_track(*args, **kwargs)

                else:
                    raise ValueError(f"未知操作类型: {operation_type}")

        except RuntimeError as e:
            error(f"执行操作 {operation_type.value} 运行时错误: {e}")
            traceback.print_exc()

            # 设置错误状态
            with self._state_lock:
                self._current_state.error_code = MpvErrorCode.GENERIC
                self._current_state.error_message = str(e)
                self._current_state.last_update = time.time()

            # 发射错误信号（使用 QMetaObject.invokeMethod 确保在主线程执行）
            QMetaObject.invokeMethod(
                self,
                "_emit_error_occurred",
                Qt.QueuedConnection,
                Q_ARG(int, MpvErrorCode.GENERIC),
                Q_ARG(str, str(e))
            )

            # 抛出异常，由 _process_operations 统一处理并设置 Future 异常
            raise

        finally:
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
            self._operation_queue.put(operation)

        self._logger.debug(
            f"操作已提交: {operation_type.value}, "
            f"组件: {component_id}"
        )

        return future

    # ==================== 具体操作实现 ====================

    def _do_initialize(self) -> bool:
        """执行初始化操作"""
        self._logger.info("开始初始化MPV核心")

        if self._mpv_core is not None:
            self._logger.warning("MPV核心已存在，先关闭旧实例")
            self._do_close()

        self._mpv_core = MPVPlayerCore()

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

        # 初始化MPV
        success = self._mpv_core.initialize()

        if success:
            with self._state_lock:
                self._current_state.is_initialized = True
                self._current_state.last_update = time.time()
            self._logger.info("MPV核心初始化成功")
        else:
            self._logger.error("MPV核心初始化失败")
            self._mpv_core = None

        return success

    def _do_close(self) -> bool:
        """执行关闭操作"""
        self._logger.info("开始关闭MPV核心")

        if self._mpv_core is None:
            self._logger.warning("MPV核心不存在，无需关闭")
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
            self._logger.debug(f"断开信号连接时出错: {e}")

        # 关闭MPV核心
        try:
            self._mpv_core.close()
        except RuntimeError as e:
            error(f"关闭MPV核心时运行时错误: {e}")

        self._mpv_core = None

        # 重置状态
        with self._state_lock:
            self._current_state = MPVState()

        self._logger.info("MPV核心已关闭")
        return True

    def _do_load_file(self, file_path: str, is_audio: bool = False) -> bool:
        """执行加载文件操作"""
        if self._mpv_core is None:
            raise RuntimeError("MPV核心未初始化")

        self._logger.info(f"加载文件: {file_path}, 音频: {is_audio}")

        # MPVPlayerCore.load_file 只接受 file_path 参数
        success = self._mpv_core.load_file(file_path)

        if success:
            with self._state_lock:
                self._current_state.current_file = file_path
                self._current_state.last_update = time.time()

        return success

    def _do_play(self) -> bool:
        """执行播放操作"""
        if self._mpv_core is None:
            raise RuntimeError("MPV核心未初始化")

        self._mpv_core.play()

        with self._state_lock:
            self._current_state.is_playing = True
            self._current_state.is_paused = False
            self._current_state.last_update = time.time()

        return True

    def _do_pause(self) -> bool:
        """执行暂停操作"""
        if self._mpv_core is None:
            raise RuntimeError("MPV核心未初始化")

        self._mpv_core.pause()

        with self._state_lock:
            self._current_state.is_paused = True
            self._current_state.last_update = time.time()

        return True

    def _do_stop(self) -> bool:
        """执行停止操作"""
        if self._mpv_core is None:
            raise RuntimeError("MPV核心未初始化")

        self._mpv_core.stop()

        with self._state_lock:
            self._current_state.is_playing = False
            self._current_state.is_paused = False
            self._current_state.position = 0.0
            self._current_state.last_update = time.time()

        return True

    def _do_seek(self, position: float) -> bool:
        """执行跳转操作"""
        if self._mpv_core is None:
            raise RuntimeError("MPV核心未初始化")

        self._mpv_core.seek(position)
        return True

    def _do_set_position(self, position: float) -> bool:
        """执行设置位置操作"""
        if self._mpv_core is None:
            raise RuntimeError("MPV核心未初始化")

        self._mpv_core.set_position(position)

        with self._state_lock:
            self._current_state.position = position
            self._current_state.last_update = time.time()

        return True

    def _do_set_volume(self, volume: int) -> bool:
        """执行设置音量操作"""
        if self._mpv_core is None:
            raise RuntimeError("MPV核心未初始化")

        self._mpv_core.set_volume(volume)

        with self._state_lock:
            self._current_state.volume = volume
            self._current_state.last_update = time.time()

        return True

    def _do_set_speed(self, speed: float) -> bool:
        """执行设置速度操作"""
        if self._mpv_core is None:
            raise RuntimeError("MPV核心未初始化")

        self._mpv_core.set_speed(speed)

        with self._state_lock:
            self._current_state.speed = speed
            self._current_state.last_update = time.time()

        return True

    def _do_set_muted(self, muted: bool) -> bool:
        """执行设置静音操作"""
        if self._mpv_core is None:
            raise RuntimeError("MPV核心未初始化")

        self._mpv_core.set_muted(muted)

        with self._state_lock:
            self._current_state.is_muted = muted
            self._current_state.last_update = time.time()

        return True

    def _do_set_loop(self, loop_mode: str) -> bool:
        """执行设置循环模式操作"""
        if self._mpv_core is None:
            raise RuntimeError("MPV核心未初始化")

        self._mpv_core.set_loop(loop_mode)

        with self._state_lock:
            self._current_state.loop_mode = loop_mode
            self._current_state.last_update = time.time()

        return True

    def _do_set_window_id(self, window_id: int) -> bool:
        """执行设置窗口ID操作"""
        if self._mpv_core is None:
            raise RuntimeError("MPV核心未初始化")

        return self._mpv_core.set_window_id(window_id)

    def _do_get_position(self) -> float:
        """执行获取位置操作"""
        if self._mpv_core is None:
            return 0.0

        result = self._mpv_core.get_position()
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
            warning(f"[LUT] MPV未初始化")
            return False

        try:
            import os
            abs_path = os.path.abspath(lut_file_path)
            debug(f"[LUT] 加载LUT文件: {abs_path}")
            debug(f"[LUT] 文件存在: {os.path.exists(abs_path)}")

            abs_path2 = abs_path.replace("\\", "/")

            debug(f"[LUT] 尝试使用 --lut 选项")
            result = self._mpv_core.set_lut(abs_path2)
            debug(f"[LUT] --lut 方式结果: {result}")

            if not result:
                debug(f"[LUT] 尝试方式1 (vf add lavfi-lut3d)")
                filter_arg = f"lavfi-lut3d=file='{abs_path2}'" if ' ' in abs_path2 else f"lavfi-lut3d=file={abs_path2}"
                result = self._mpv_core.set_vf_filter(filter_arg)
                debug(f"[LUT] 方式1 结果: {result}")

            if not result:
                debug(f"[LUT] 尝试方式2 (load glsl-shaders)")
                result = self._mpv_core.load_glsl_shader(abs_path2)
                debug(f"[LUT] 方式2 结果: {result}")

            if not result:
                debug(f"[LUT] 尝试方式3 (set glsl-shaders)")
                shader_list = f'["{abs_path2}"]'
                result = self._mpv_core.set_glsl_shaders(shader_list)
                debug(f"[LUT] 方式3 结果: {result}")

            if result:
                with self._state_lock:
                    self._current_state.current_lut = lut_file_path
                    self._current_state.last_update = time.time()

                self.lutLoaded.emit(lut_file_path)
                return True
            else:
                warning(f"[LUT] 所有方式都失败")
                return False

        except (OSError, ValueError, TypeError) as e:
            error(f"加载LUT失败: {e}")
            import traceback
            traceback.print_exc()
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
            debug(f"[LUT] 清除lut结果: {result}")

            if not result:
                result = self._mpv_core.clear_glsl_shaders()
                debug(f"[LUT] 清除glsl着色器结果: {result}")

            if not result:
                result = self._mpv_core.set_vf_filter("")
                debug(f"[LUT] 清除vf滤镜结果: {result}")

            if result:
                with self._state_lock:
                    self._current_state.current_lut = ""
                    self._current_state.last_update = time.time()

                self.lutUnloaded.emit()
                return True
            else:
                return False

        except RuntimeError as e:
            error(f"卸载LUT运行时错误: {e}")
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
            warning("[Subtitle] MPV未初始化")
            return False

        try:
            return self._mpv_core.load_subtitle(subtitle_file_path)
        except RuntimeError as e:
            error(f"加载字幕运行时错误: {e}")
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
            error(f"获取字幕状态运行时错误: {e}")
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
            error(f"获取字幕轨列表运行时错误: {e}")
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
            warning("[Subtitle] MPV未初始化")
            return False

        try:
            return self._mpv_core.set_subtitle_visibility(visible)
        except RuntimeError as e:
            error(f"设置字幕可见性运行时错误: {e}")
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
            warning("[Subtitle] MPV未初始化")
            return False

        try:
            return self._mpv_core.set_subtitle_track(track_id)
        except RuntimeError as e:
            error(f"切换字幕轨运行时错误: {e}")
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
            error(f"获取音轨状态运行时错误: {e}")
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
            error(f"获取音轨列表运行时错误: {e}")
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
            warning("[Audio] MPV未初始化")
            return False

        try:
            return self._mpv_core.set_audio_track(track_id)
        except RuntimeError as e:
            error(f"切换音轨运行时错误: {e}")
            return False

    # ==================== 信号处理回调 ====================

    def _on_state_changed(self, is_playing: bool):
        """播放状态变化回调"""
        with self._state_lock:
            self._current_state.is_playing = is_playing
            if is_playing:
                self._current_state.is_paused = False
            self._current_state.last_update = time.time()

        self.stateChanged.emit(self._current_state)

    def _on_position_changed(self, position: float, duration: float):
        """位置变化回调"""
        with self._state_lock:
            self._current_state.position = position
            self._current_state.duration = duration
            self._current_state.last_update = time.time()

        self.positionChanged.emit(position, duration)

    def _on_duration_changed(self, duration: float):
        """时长变化回调"""
        with self._state_lock:
            self._current_state.duration = duration
            self._current_state.last_update = time.time()
        self.positionChanged.emit(self._current_state.position, duration)

    def _on_volume_changed(self, volume: int):
        """音量变化回调"""
        with self._state_lock:
            self._current_state.volume = volume
            self._current_state.last_update = time.time()
        self.volumeChanged.emit(volume)

    def _on_speed_changed(self, speed: float):
        """速度变化回调"""
        with self._state_lock:
            self._current_state.speed = speed
            self._current_state.last_update = time.time()
        self.speedChanged.emit(speed)

    def _on_muted_changed(self, muted: bool):
        """静音状态变化回调"""
        with self._state_lock:
            self._current_state.is_muted = muted
            self._current_state.last_update = time.time()
        self.mutedChanged.emit(muted)

    def _on_file_loaded(self, file_path: str):
        """文件加载完成回调"""
        with self._state_lock:
            self._current_state.current_file = file_path
            self._current_state.last_update = time.time()

        self.fileLoaded.emit(file_path)

    def _on_file_ended(self, reason: int):
        """文件播放结束回调"""
        with self._state_lock:
            self._current_state.is_playing = False
            self._current_state.is_paused = False
            self._current_state.last_update = time.time()

        self.fileEnded.emit(reason)

    @Slot(int, str)
    def _emit_error_occurred(self, error_code: int, error_message: str):
        """发射错误信号（供 QMetaObject.invokeMethod 调用）"""
        self.errorOccurred.emit(error_code, error_message)

    def _on_error_occurred(self, error_code: int, error_message: str):
        """错误发生回调（由 MPVPlayerCore 信号触发，已在主线程）"""
        with self._state_lock:
            self._current_state.error_code = error_code
            self._current_state.error_message = error_message
            self._current_state.last_update = time.time()

        self.errorOccurred.emit(error_code, error_message)

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
        # 检查并等待上次清理完成（避免冲突）
        if wait_for_cleanup and not self.ensure_cleanup_complete(timeout=5.0):
            self._logger.warning("上次清理未完成，可能存在资源冲突")
            # 继续尝试初始化，但记录警告
        
        # 如果正在关闭中，等待关闭完成
        if self._is_shutting_down:
            self._logger.info("等待关闭完成后再初始化...")
            if not self.wait_for_cleanup(timeout=5.0):
                self._logger.error("等待关闭完成超时")
                return False

        self._start_operation_thread()

        future = self._submit_operation(
            MPVOperationType.INITIALIZE,
            component_id="manager",
            priority=1
        )

        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            self._logger.error("初始化操作超时")
            return False
        except RuntimeError as e:
            error(f"initialize 运行时错误: {e}")
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

        self._is_shutting_down = True
        self._cleanup_event.clear()  # 标记清理开始

        # 如果操作线程未运行，直接清理并重置状态
        if not self._operation_thread or not self._operation_thread.is_alive():
            self._cleanup_resources()
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
                error(f"关闭MPV管理器运行时错误: {e}")
                self._do_force_cleanup()
                return False
    
    def _do_sync_close(self, timeout: float = 2.0) -> bool:
        """同步关闭"""
        try:
            # 预清理 - 让 MPV 进入空闲状态
            if self._mpv_core:
                self._mpv_core.pre_cleanup()
            
            # 执行关闭操作
            result = self._do_close()
            self._stop_operation_thread(timeout)
            self._cleanup_resources()
            self._is_shutting_down = False
            self._cleanup_event.set()  # 标记清理完成
            return result
        except RuntimeError as e:
            error(f"同步关闭运行时错误: {e}")
            self._do_force_cleanup()
            raise

    def _do_async_close(self, timeout: float = 3.0):
        """异步关闭 - 在后台执行"""
        try:
            self._logger.info("开始异步关闭MPV管理器")

            # 先停止操作线程，确保没有并发操作
            self._stop_operation_thread(timeout)

            # 预清理
            if self._mpv_core:
                self._mpv_core.pre_cleanup()

            # 执行关闭
            self._do_close()
            self._cleanup_resources()

            self._logger.info("异步关闭MPV管理器完成")
        except RuntimeError as e:
            error(f"异步关闭运行时错误: {e}")
        finally:
            self._is_shutting_down = False
            self._cleanup_event.set()  # 标记清理完成
            self._async_cleanup_thread = None
    
    def _do_force_cleanup(self):
        """强制清理 - 在出错时使用"""
        try:
            self._stop_operation_thread(1.0)
            self._cleanup_resources()
        except RuntimeError as e:
            error(f"强制清理运行时错误: {e}")
        finally:
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
            self._logger.info("等待上次清理完成...")
            completed = self._cleanup_event.wait(timeout=timeout)
            if not completed:
                self._logger.warning(f"等待清理完成超时（{timeout}s）")
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
            self._logger.error(f"加载文件操作超时: {file_path}")
            return False
        except RuntimeError as e:
            error(f"load_file 运行时错误: {e}")
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
            error(f"play 运行时错误: {e}")
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
            error(f"pause 运行时错误: {e}")
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
            error(f"stop 运行时错误: {e}")
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
            error(f"seek 运行时错误: {e}")
            return False

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
            error(f"set_position 运行时错误: {e}")
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
            error(f"set_volume 运行时错误: {e}")
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
            error(f"set_speed 运行时错误: {e}")
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
            error(f"set_muted 运行时错误: {e}")
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
            error(f"set_loop 运行时错误: {e}")
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
            error(f"set_window_id 运行时错误: {e}")
            return False

    def get_position(self) -> float:
        """
        获取当前播放位置

        Returns:
            当前位置（秒）
        """
        try:
            future = self._submit_operation(
                MPVOperationType.GET_POSITION,
                priority=5
            )
            return future.result(timeout=1.0)
        except FutureTimeoutError:
            return 0.0
        except RuntimeError as e:
            error(f"get_position 运行时错误: {e}")
            return 0.0

    def get_duration(self) -> float:
        """
        获取媒体总时长

        Returns:
            总时长（秒）
        """
        try:
            future = self._submit_operation(
                MPVOperationType.GET_DURATION,
                priority=5
            )
            return future.result(timeout=1.0)
        except FutureTimeoutError:
            return 0.0
        except RuntimeError as e:
            error(f"get_duration 运行时错误: {e}")
            return 0.0

    def get_volume(self) -> int:
        """
        获取当前音量

        Returns:
            音量值（0-100）
        """
        try:
            future = self._submit_operation(
                MPVOperationType.GET_VOLUME,
                priority=5
            )
            return future.result(timeout=1.0)
        except FutureTimeoutError:
            return 100
        except RuntimeError as e:
            error(f"get_volume 运行时错误: {e}")
            return 100

    def get_speed(self) -> float:
        """
        获取当前播放速度

        Returns:
            播放速度
        """
        try:
            future = self._submit_operation(
                MPVOperationType.GET_SPEED,
                priority=5
            )
            return future.result(timeout=1.0)
        except FutureTimeoutError:
            return 1.0
        except RuntimeError as e:
            error(f"get_speed 运行时错误: {e}")
            return 1.0

    def is_playing(self) -> bool:
        """
        获取是否正在播放

        Returns:
            是否正在播放
        """
        try:
            future = self._submit_operation(
                MPVOperationType.IS_PLAYING,
                priority=5
            )
            return future.result(timeout=1.0)
        except FutureTimeoutError:
            return False
        except RuntimeError as e:
            error(f"is_playing 运行时错误: {e}")
            return False

    def is_paused(self) -> bool:
        """
        获取是否暂停

        Returns:
            是否暂停
        """
        try:
            future = self._submit_operation(
                MPVOperationType.IS_PAUSED,
                priority=5
            )
            return future.result(timeout=1.0)
        except FutureTimeoutError:
            return False
        except RuntimeError as e:
            error(f"is_paused 运行时错误: {e}")
            return False

    def is_muted(self) -> bool:
        """
        获取是否静音

        Returns:
            是否静音
        """
        try:
            future = self._submit_operation(
                MPVOperationType.IS_MUTED,
                priority=5
            )
            return future.result(timeout=1.0)
        except FutureTimeoutError:
            return False
        except RuntimeError as e:
            error(f"is_muted 运行时错误: {e}")
            return False

    def get_video_size(self) -> Tuple[int, int]:
        """
        获取视频尺寸

        Returns:
            (宽度, 高度)元组
        """
        try:
            future = self._submit_operation(
                MPVOperationType.GET_VIDEO_SIZE,
                priority=5
            )
            return future.result(timeout=1.0)
        except FutureTimeoutError:
            return (0, 0)
        except RuntimeError as e:
            error(f"get_video_size 运行时错误: {e}")
            return (0, 0)

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
            self._logger.error(f"加载LUT操作超时: {lut_file_path}")
            return False
        except RuntimeError as e:
            error(f"load_lut 运行时错误: {e}")
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
            self._logger.error("卸载LUT操作超时")
            return False
        except RuntimeError as e:
            error(f"unload_lut 运行时错误: {e}")
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
            self._logger.error(f"加载字幕操作超时: {subtitle_file_path}")
            return False
        except RuntimeError as e:
            error(f"load_subtitle 运行时错误: {e}")
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
            error(f"get_subtitle_state 运行时错误: {e}")
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
            error(f"get_subtitle_tracks 运行时错误: {e}")
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
            self._logger.error("设置字幕可见性操作超时")
            return False
        except RuntimeError as e:
            error(f"set_subtitle_visibility 运行时错误: {e}")
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
            self._logger.error(f"切换字幕轨操作超时: {track_id}")
            return False
        except RuntimeError as e:
            error(f"set_subtitle_track 运行时错误: {e}")
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
            error(f"get_audio_state 运行时错误: {e}")
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
            error(f"get_audio_tracks 运行时错误: {e}")
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
            self._logger.error(f"切换音轨操作超时: {track_id}")
            return False
        except RuntimeError as e:
            error(f"set_audio_track 运行时错误: {e}")
            return False

    def get_current_lut(self) -> str:
        """
        获取当前加载的LUT文件路径

        Returns:
            LUT文件路径，未加载则返回空字符串
        """
        with self._state_lock:
            return self._current_state.current_lut

    def get_state(self) -> MPVState:
        """
        获取当前状态

        Returns:
            当前状态的数据类副本
        """
        with self._state_lock:
            # 返回副本，避免外部修改
            return MPVState(
                is_initialized=self._current_state.is_initialized,
                is_playing=self._current_state.is_playing,
                is_paused=self._current_state.is_paused,
                is_muted=self._current_state.is_muted,
                position=self._current_state.position,
                duration=self._current_state.duration,
                volume=self._current_state.volume,
                speed=self._current_state.speed,
                loop_mode=self._current_state.loop_mode,
                current_file=self._current_state.current_file,
                video_width=self._current_state.video_width,
                video_height=self._current_state.video_height,
                error_code=self._current_state.error_code,
                error_message=self._current_state.error_message,
                last_update=self._current_state.last_update,
                current_lut=self._current_state.current_lut
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
        with self._state_lock:
            return self._current_state.is_initialized

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
                self._logger.warning(f"组件已存在: {component_id}")
                return False

            self._registered_components[component_id] = {
                "type": component_type,
                "callback": callback,
                "registered_at": time.time()
            }

        self._logger.info(f"组件已注册: {component_id}, 类型: {component_type}")
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

        self._logger.info(f"组件已注销: {component_id}")
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
        return self._logger.get_recent_logs(count)

    def clear_logs(self):
        """清空日志"""
        self._logger.log_history.clear()

    # ==================== 析构 ====================

    def __del__(self):
        """析构函数"""
        try:
            if self._mpv_core is not None:
                self.close()
        except RuntimeError as e:
            debug(f"析构时关闭MPV管理器运行时错误: {e}")


# 便捷函数，用于快速获取管理器实例
def get_mpv_manager(enable_logging: bool = True) -> MPVManager:
    """
    获取MPV管理器实例

    Args:
        enable_logging: 是否启用日志

    Returns:
        MPVManager实例
    """
    return MPVManager(enable_logging=enable_logging)
