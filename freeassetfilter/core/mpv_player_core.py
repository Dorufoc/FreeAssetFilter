#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

MPV播放器核心模块
基于libmpv实现高性能视频播放功能，提供完全独立的线程架构，内部闭环，避免DLL冲突
"""

import os
import sys
import ctypes
import threading
import time
import queue
from ctypes import c_void_p, c_int, c_int64, c_double, c_char_p, POINTER, Structure, byref
from typing import Optional, Callable, Dict, Any, List, Tuple, Union
from enum import IntEnum

from PySide6.QtCore import QObject, Signal, QThread, Qt


class MpvErrorCode(IntEnum):
    """MPV错误码枚举"""
    SUCCESS = 0
    EVENT_QUEUE_FULL = -1
    NOMEM = -2
    UNINITIALIZED = -3
    INVALID_PARAMETER = -4
    OPTION_NOT_FOUND = -5
    OPTION_FORMAT = -6
    OPTION_ERROR = -7
    PROPERTY_NOT_FOUND = -8
    PROPERTY_FORMAT = -9
    PROPERTY_UNAVAILABLE = -10
    PROPERTY_ERROR = -11
    COMMAND = -12
    LOADING_FAILED = -13
    AO_INIT_FAILED = -14
    VO_INIT_FAILED = -15
    NOTHING_TO_PLAY = -16
    UNKNOWN_FORMAT = -17
    UNSUPPORTED = -18
    NOT_IMPLEMENTED = -19
    GENERIC = -20


class MpvEventId(IntEnum):
    """MPV事件ID枚举"""
    NONE = 0
    SHUTDOWN = 1
    LOG_MESSAGE = 2
    GET_PROPERTY_REPLY = 3
    SET_PROPERTY_REPLY = 4
    COMMAND_REPLY = 5
    START_FILE = 6
    END_FILE = 7
    FILE_LOADED = 8
    CLIENT_MESSAGE = 16
    VIDEO_RECONFIG = 17
    AUDIO_RECONFIG = 18
    SEEK = 20
    PLAYBACK_RESTART = 21
    PROPERTY_CHANGE = 22
    QUEUE_OVERFLOW = 24
    HOOK = 25


class MpvFormat(IntEnum):
    """MPV数据格式枚举"""
    NONE = 0
    STRING = 1
    OSD_STRING = 2
    FLAG = 3
    INT64 = 4
    DOUBLE = 5
    NODE = 6
    NODE_ARRAY = 7
    NODE_MAP = 8
    BYTE_ARRAY = 9


class MpvEndFileReason(IntEnum):
    """MPV文件结束原因枚举"""
    EOF = 0
    STOP = 2
    QUIT = 3
    ERROR = 4
    REDIRECT = 5


class MpvEventProperty(Structure):
    """MPV属性事件结构体"""
    _fields_ = [
        ("name", c_char_p),
        ("format", ctypes.c_int),
        ("data", c_void_p),
    ]


class MpvEventEndFile(Structure):
    """MPV文件结束事件结构体"""
    _fields_ = [
        ("reason", ctypes.c_int),
        ("error", ctypes.c_int),
        ("playlist_entry_id", c_int64),
        ("playlist_insert_id", c_int64),
        ("playlist_insert_num_entries", ctypes.c_int),
    ]


class MpvEventStartFile(Structure):
    """MPV文件开始事件结构体"""
    _fields_ = [
        ("playlist_entry_id", c_int64),
    ]


class MpvEvent(Structure):
    """MPV事件结构体"""
    _fields_ = [
        ("event_id", ctypes.c_int),
        ("error", ctypes.c_int),
        ("reply_userdata", c_int64),
        ("data", c_void_p),
    ]


class MPVError(Exception):
    """MPV错误异常类"""
    
    def __init__(self, error_code: int, message: str = ""):
        self.error_code = error_code
        self.message = message
        super().__init__(f"MPV Error [{error_code}]: {message}")


class MPVCommandType(IntEnum):
    """MPV命令类型枚举"""
    INITIALIZE = 0
    LOAD_FILE = 1
    PLAY = 2
    PAUSE = 3
    STOP = 4
    SEEK = 5
    SET_VOLUME = 6
    SET_SPEED = 7
    SET_MUTED = 8
    SET_LOOP = 9
    SET_WINDOW_ID = 10
    SET_WINDOW_SIZE = 11
    GET_POSITION = 12
    GET_DURATION = 13
    GET_VOLUME = 14
    GET_SPEED = 15
    GET_VIDEO_SIZE = 16
    IS_AUDIO_ONLY = 17
    SET_VF_FILTER = 18
    LOAD_GLSL_SHADER = 19
    SET_GLSL_SHADERS = 20
    CLEAR_GLSL_SHADERS = 21
    SET_LUT = 22
    CLEAR_LUT = 23
    CLOSE = 99


@ctypes.CFUNCTYPE(None, c_void_p, c_void_p)
def mpv_wakeup_callback(_: c_void_p, __: c_void_p):
    """MPV唤醒回调（由MPV在内部线程调用）"""
    pass


class MPVDLLLoader:
    """
    MPV DLL加载器
    负责动态加载libmpv-2.dll并提供函数绑定
    """
    
    _instance = None
    _lock = threading.Lock()
    _dll = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def load_dll(self) -> bool:
        """
        加载libmpv DLL
        
        Returns:
            bool: 加载是否成功
        """
        if self._initialized:
            return self._dll is not None
        
        try:
            dll_paths = self._get_dll_paths()
            
            for dll_path in dll_paths:
                if os.path.exists(dll_path):
                    try:
                        self._dll = ctypes.CDLL(dll_path)
                        self._bind_functions()
                        self._initialized = True
                        return True
                    except OSError as e:
                        continue
            
            return False
            
        except Exception as e:
            self._dll = None
            self._initialized = True
            return False
    
    def _get_dll_paths(self) -> List[str]:
        """
        获取DLL可能的路径列表
        
        Returns:
            List[str]: DLL路径列表
        """
        paths = []
        
        current_dir = os.path.dirname(os.path.abspath(__file__))
        paths.append(os.path.join(current_dir, "libmpv-2.dll"))
        paths.append(os.path.join(current_dir, "libmpv.dll"))
        
        if sys.platform == "win32":
            system_paths = os.environ.get("PATH", "").split(os.pathsep)
            for sys_path in system_paths:
                paths.append(os.path.join(sys_path, "libmpv-2.dll"))
                paths.append(os.path.join(sys_path, "libmpv.dll"))
        
        return paths
    
    def _bind_functions(self):
        """绑定MPV API函数"""
        if not self._dll:
            return
        
        self._dll.mpv_client_api_version.restype = ctypes.c_ulong
        self._dll.mpv_client_api_version.argtypes = []
        
        self._dll.mpv_error_string.restype = c_char_p
        self._dll.mpv_error_string.argtypes = [ctypes.c_int]
        
        self._dll.mpv_free.restype = None
        self._dll.mpv_free.argtypes = [c_void_p]
        
        self._dll.mpv_create.restype = c_void_p
        self._dll.mpv_create.argtypes = []
        
        self._dll.mpv_initialize.restype = ctypes.c_int
        self._dll.mpv_initialize.argtypes = [c_void_p]
        
        self._dll.mpv_destroy.restype = None
        self._dll.mpv_destroy.argtypes = [c_void_p]
        
        self._dll.mpv_terminate_destroy.restype = None
        self._dll.mpv_terminate_destroy.argtypes = [c_void_p]
        
        self._dll.mpv_client_name.restype = c_char_p
        self._dll.mpv_client_name.argtypes = [c_void_p]
        
        self._dll.mpv_set_option_string.restype = ctypes.c_int
        self._dll.mpv_set_option_string.argtypes = [c_void_p, c_char_p, c_char_p]
        
        self._dll.mpv_command.restype = ctypes.c_int
        self._dll.mpv_command.argtypes = [c_void_p, POINTER(c_char_p)]
        
        self._dll.mpv_command_string.restype = ctypes.c_int
        self._dll.mpv_command_string.argtypes = [c_void_p, c_char_p]
        
        self._dll.mpv_set_property_string.restype = ctypes.c_int
        self._dll.mpv_set_property_string.argtypes = [c_void_p, c_char_p, c_char_p]
        
        self._dll.mpv_get_property_string.restype = c_char_p
        self._dll.mpv_get_property_string.argtypes = [c_void_p, c_char_p]
        
        self._dll.mpv_set_property.restype = ctypes.c_int
        self._dll.mpv_set_property.argtypes = [c_void_p, c_char_p, ctypes.c_int, c_void_p]
        
        self._dll.mpv_get_property.restype = ctypes.c_int
        self._dll.mpv_get_property.argtypes = [c_void_p, c_char_p, ctypes.c_int, c_void_p]
        
        self._dll.mpv_observe_property.restype = ctypes.c_int
        self._dll.mpv_observe_property.argtypes = [c_void_p, c_int64, c_char_p, ctypes.c_int]
        
        self._dll.mpv_unobserve_property.restype = ctypes.c_int
        self._dll.mpv_unobserve_property.argtypes = [c_void_p, c_int64]
        
        self._dll.mpv_wait_event.restype = POINTER(MpvEvent)
        self._dll.mpv_wait_event.argtypes = [c_void_p, c_double]
        
        self._dll.mpv_wakeup.restype = None
        self._dll.mpv_wakeup.argtypes = [c_void_p]
        
        self._dll.mpv_set_wakeup_callback.restype = None
        self._dll.mpv_set_wakeup_callback.argtypes = [c_void_p, c_void_p, c_void_p]
        
        self._dll.mpv_request_event.restype = ctypes.c_int
        self._dll.mpv_request_event.argtypes = [c_void_p, ctypes.c_int, ctypes.c_int]
    
    @property
    def dll(self):
        """获取DLL实例"""
        return self._dll
    
    @property
    def is_loaded(self) -> bool:
        """检查DLL是否已加载"""
        return self._dll is not None
    
    def get_error_string(self, error_code: int) -> str:
        """
        获取错误码对应的错误描述
        
        Args:
            error_code: MPV错误码
            
        Returns:
            str: 错误描述字符串
        """
        if not self._dll:
            return "DLL not loaded"
        
        error_str = self._dll.mpv_error_string(error_code)
        return error_str.decode('utf-8') if error_str else "Unknown error"


class MPVPlayerCore(QObject):
    """
    MPV播放器核心类（完全独立线程架构）
    
    所有MPV操作都在同一个独立线程中执行，内部闭环，避免DLL冲突。
    通过命令队列与外部交互，使用Qt信号反馈状态。
    
    Signals:
        stateChanged: 播放状态变化信号 (is_playing: bool)
        positionChanged: 播放位置变化信号 (position: float, duration: float)
        durationChanged: 时长变化信号 (duration: float)
        volumeChanged: 音量变化信号 (volume: int)
        speedChanged: 播放速度变化信号 (speed: float)
        mutedChanged: 静音状态变化信号 (muted: bool)
        fileLoaded: 文件加载完成信号 (file_path: str, is_audio: bool)
        fileEnded: 文件播放结束信号 (reason: int)
        errorOccurred: 错误发生信号 (error_code: int, error_message: str)
        seekFinished: 跳转完成信号
        videoSizeChanged: 视频尺寸变化信号 (width: int, height: int)
    """
    
    stateChanged = Signal(bool)
    positionChanged = Signal(float, float)
    durationChanged = Signal(float)
    volumeChanged = Signal(int)
    speedChanged = Signal(float)
    mutedChanged = Signal(bool)
    fileLoaded = Signal(str, bool)
    fileEnded = Signal(int)
    errorOccurred = Signal(int, str)
    seekFinished = Signal()
    videoSizeChanged = Signal(int, int)
    
    def __init__(self, parent=None):
        """
        初始化MPV播放器核心
        
        Args:
            parent: 父对象
        """
        super().__init__(parent)
        
        self._dll_loader = MPVDLLLoader()
        
        self._command_queue = queue.Queue()
        self._result_queue = queue.Queue()
        
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._initialized_event = threading.Event()
        
        self._current_file: str = ""
        self._is_playing: bool = False
        self._is_paused: bool = False
        self._is_seeking: bool = False
        self._duration: float = 0.0
        self._position: float = 0.0
        self._volume: int = 100
        self._speed: float = 1.0
        self._muted: bool = False
        self._loop_mode: str = "no"
        self._window_id: Optional[int] = None
        self._video_width: int = 0
        self._video_height: int = 0
        
        self._state_lock = threading.Lock()
        
        self._initialized = False
    
    def _worker_thread_func(self):
        """MPV工作线程主函数 - 所有MPV操作都在此线程执行"""
        mpv_handle = None
        
        try:
            if not self._dll_loader.load_dll():
                self._emit_error(MpvErrorCode.GENERIC, "无法加载libmpv DLL")
                return
            
            mpv_handle = self._dll_loader.dll.mpv_create()
            if not mpv_handle:
                self._emit_error(MpvErrorCode.GENERIC, "无法创建MPV实例")
                return
            
            self._configure_mpv(mpv_handle)
            
            result = self._dll_loader.dll.mpv_initialize(mpv_handle)
            if result < 0:
                error_msg = self._dll_loader.get_error_string(result)
                self._emit_error(result, f"MPV初始化失败: {error_msg}")
                return
            
            self._observe_properties(mpv_handle)
            
            with self._state_lock:
                self._initialized = True
            self._initialized_event.set()
            
            last_position_update = 0.0
            position_update_interval = 0.1
            
            while not self._stop_event.is_set():
                try:
                    event_ptr = self._dll_loader.dll.mpv_wait_event(mpv_handle, 0.01)
                    if event_ptr:
                        event = event_ptr.contents
                        self._handle_mpv_event(mpv_handle, event)
                    
                    try:
                        command = self._command_queue.get_nowait()
                        self._process_command(mpv_handle, command)
                    except queue.Empty:
                        pass
                    
                    current_time = time.time()
                    if current_time - last_position_update >= position_update_interval:
                        self._update_position_state(mpv_handle)
                        last_position_update = current_time
                        
                except Exception as e:
                    if not self._stop_event.is_set():
                        print(f"[MPVWorker] 错误: {e}")
                        import traceback
                        traceback.print_exc()
            
        except Exception as e:
            print(f"[MPVWorker] 致命错误: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if mpv_handle:
                try:
                    self._dll_loader.dll.mpv_command(mpv_handle, (c_char_p * 2)(b"quit", None))
                    time.sleep(0.1)
                    self._dll_loader.dll.mpv_terminate_destroy(mpv_handle)
                except Exception:
                    pass
            
            with self._state_lock:
                self._initialized = False
            self._initialized_event.clear()
    
    def _configure_mpv(self, mpv_handle: c_void_p):
        """配置MPV基本参数"""
        config = {
            "vo": "gpu-next",
            "hwdec": "auto-safe",
            "keep-open": "yes",
            "idle": "once",
            "force-window": "no",
            "audio-display": "no",
            "input-cursor": "no",
            "cursor-autohide": "no",
            "osc": "no",
            "osd-level": "0",
            "terminal": "no",
            "msg-level": "all=no",
            "keepaspect": "yes",
            "keepaspect-window": "no",
            "video-unscaled": "no",
            "video-pan-x": "0",
            "video-pan-y": "0",
            "video-zoom": "0",
            "panscan": "0",
            "video-align-x": "0",
            "video-align-y": "0",
            "input-default-bindings": "no",  # 禁用默认键盘绑定，让Qt处理键盘事件
            "input-vo-keyboard": "no",  # 禁用视频输出键盘输入
            "input-ar-delay": "999999",  # 设置自动重复延迟为极大值，禁用按键重复
            "input-ar-rate": "1",  # 设置自动重复速率为最小
            "stop-playback-on-init-failure": "no",  # 初始化失败不停止播放
            "load-scripts": "no",  # 禁用脚本加载，防止脚本拦截输入
            "load-auto-profiles": "no",  # 禁用自动配置文件
        }
        
        for name, value in config.items():
            self._dll_loader.dll.mpv_set_option_string(
                mpv_handle,
                name.encode('utf-8'),
                value.encode('utf-8')
            )
    
    def _observe_properties(self, mpv_handle: c_void_p):
        """设置属性观察"""
        properties = [
            ("time-pos", MpvFormat.DOUBLE),
            ("duration", MpvFormat.DOUBLE),
            ("pause", MpvFormat.FLAG),
            ("volume", MpvFormat.INT64),
            ("speed", MpvFormat.DOUBLE),
            ("mute", MpvFormat.FLAG),
            ("loop-file", MpvFormat.STRING),
            ("video-params/w", MpvFormat.INT64),
            ("video-params/h", MpvFormat.INT64),
        ]
        
        for prop_name, prop_format in properties:
            self._dll_loader.dll.mpv_observe_property(
                mpv_handle, 0, prop_name.encode('utf-8'), prop_format
            )
    
    def _handle_mpv_event(self, mpv_handle: c_void_p, event: MpvEvent):
        """处理MPV事件（在工作线程中执行）"""
        event_id = event.event_id
        
        if event_id == MpvEventId.NONE:
            return
        
        if event_id == MpvEventId.PROPERTY_CHANGE:
            self._handle_property_change_event(mpv_handle, event)
        elif event_id == MpvEventId.FILE_LOADED:
            self._handle_file_loaded_event(mpv_handle)
        elif event_id == MpvEventId.END_FILE:
            self._handle_end_file_event(mpv_handle, event)
        elif event_id == MpvEventId.SEEK:
            self._is_seeking = True
        elif event_id == MpvEventId.PLAYBACK_RESTART:
            self._is_seeking = False
            self.seekFinished.emit()
        elif event_id == MpvEventId.SHUTDOWN:
            self._stop_event.set()
    
    def _handle_property_change_event(self, mpv_handle: c_void_p, event: MpvEvent):
        """处理属性变化事件"""
        if not event.data:
            return
        
        prop_event = ctypes.cast(event.data, POINTER(MpvEventProperty)).contents
        prop_name = prop_event.name.decode('utf-8') if prop_event.name else ""
        
        value = None
        if prop_event.format == MpvFormat.STRING and prop_event.data:
            value_ptr = ctypes.cast(prop_event.data, POINTER(c_char_p))
            if value_ptr.contents:
                value = value_ptr.contents.value.decode('utf-8')
        elif prop_event.format == MpvFormat.DOUBLE and prop_event.data:
            value_ptr = ctypes.cast(prop_event.data, POINTER(c_double))
            value = value_ptr.contents.value
        elif prop_event.format == MpvFormat.FLAG and prop_event.data:
            value_ptr = ctypes.cast(prop_event.data, POINTER(ctypes.c_int))
            value = bool(value_ptr.contents.value)
        elif prop_event.format == MpvFormat.INT64 and prop_event.data:
            value_ptr = ctypes.cast(prop_event.data, POINTER(c_int64))
            value = value_ptr.contents.value
        
        with self._state_lock:
            if prop_name == "time-pos" and value is not None:
                self._position = float(value)
            elif prop_name == "duration" and value is not None:
                self._duration = float(value)
                self.durationChanged.emit(self._duration)
            elif prop_name == "pause":
                is_paused = bool(value) if value is not None else False
                self._is_paused = is_paused
                self._is_playing = not is_paused
                self.stateChanged.emit(self._is_playing)
            elif prop_name == "volume" and value is not None:
                self._volume = int(value)
                self.volumeChanged.emit(self._volume)
            elif prop_name == "speed" and value is not None:
                self._speed = float(value)
                self.speedChanged.emit(self._speed)
            elif prop_name == "mute":
                self._muted = bool(value) if value is not None else False
                self.mutedChanged.emit(self._muted)
            elif prop_name == "loop-file" and value is not None:
                self._loop_mode = str(value)
            elif prop_name == "video-params/w" and value is not None:
                self._video_width = int(value)
                h_val = self._get_property_double(mpv_handle, "video-params/h")
                if h_val is not None:
                    self._video_height = int(h_val)
                if self._video_width > 0 and self._video_height > 0:
                    self.videoSizeChanged.emit(self._video_width, self._video_height)
    
    def _handle_file_loaded_event(self, mpv_handle: c_void_p):
        """处理文件加载完成事件"""
        is_audio = self._is_audio_only_internal(mpv_handle)
        if is_audio:
            self._set_window_size_internal(mpv_handle, 0, 0)
        
        duration = self._get_property_double(mpv_handle, "duration")
        if duration is not None and duration > 0:
            with self._state_lock:
                self._duration = duration
            self.durationChanged.emit(self._duration)
        
        # 获取当前的播放状态（MPV加载文件后会自动开始播放）
        # 使用 FLAG 类型获取 pause 属性
        is_paused = False
        c_value = ctypes.c_int(0)
        result = self._dll_loader.dll.mpv_get_property(
            mpv_handle, b"pause", MpvFormat.FLAG, byref(c_value)
        )
        if result >= 0:
            is_paused = bool(c_value.value)
        
        with self._state_lock:
            self._is_paused = is_paused
            self._is_playing = not is_paused
        
        # 发出状态变化信号，确保UI正确更新播放按钮状态
        self.stateChanged.emit(self._is_playing)
        
        self.fileLoaded.emit(self._current_file, is_audio)
    
    def _handle_end_file_event(self, mpv_handle: c_void_p, event: MpvEvent):
        """处理文件播放结束事件"""
        reason = MpvEndFileReason.EOF
        error = 0
        
        if event.data:
            end_file_event = ctypes.cast(event.data, POINTER(MpvEventEndFile)).contents
            reason = end_file_event.reason
            error = end_file_event.error
        
        with self._state_lock:
            self._is_playing = False
            self._is_paused = False
        self.stateChanged.emit(False)
        
        if reason == MpvEndFileReason.ERROR:
            error_msg = self._dll_loader.get_error_string(error)
            self.errorOccurred.emit(error, error_msg)
        
        self.fileEnded.emit(reason)
    
    def _update_position_state(self, mpv_handle: c_void_p):
        """更新播放位置状态"""
        position = self._get_property_double(mpv_handle, "time-pos")
        duration = self._get_property_double(mpv_handle, "duration")
        
        with self._state_lock:
            if position is not None:
                self._position = position
            if duration is not None and duration > 0:
                self._duration = duration
        
        self.positionChanged.emit(self._position, self._duration)
    
    def _process_command(self, mpv_handle: c_void_p, command: dict):
        """处理命令（在工作线程中执行）"""
        cmd_type = command.get('type')
        args = command.get('args', ())
        kwargs = command.get('kwargs', {})
        result = None
        
        try:
            if cmd_type == MPVCommandType.INITIALIZE:
                result = True
            elif cmd_type == MPVCommandType.LOAD_FILE:
                result = self._load_file_internal(mpv_handle, *args, **kwargs)
            elif cmd_type == MPVCommandType.PLAY:
                result = self._play_internal(mpv_handle)
            elif cmd_type == MPVCommandType.PAUSE:
                result = self._pause_internal(mpv_handle)
            elif cmd_type == MPVCommandType.STOP:
                result = self._stop_internal(mpv_handle)
            elif cmd_type == MPVCommandType.SEEK:
                result = self._seek_internal(mpv_handle, *args, **kwargs)
            elif cmd_type == MPVCommandType.SET_VOLUME:
                result = self._set_volume_internal(mpv_handle, *args, **kwargs)
            elif cmd_type == MPVCommandType.SET_SPEED:
                result = self._set_speed_internal(mpv_handle, *args, **kwargs)
            elif cmd_type == MPVCommandType.SET_MUTED:
                result = self._set_muted_internal(mpv_handle, *args, **kwargs)
            elif cmd_type == MPVCommandType.SET_LOOP:
                result = self._set_loop_internal(mpv_handle, *args, **kwargs)
            elif cmd_type == MPVCommandType.SET_WINDOW_ID:
                result = self._set_window_id_internal(mpv_handle, *args, **kwargs)
            elif cmd_type == MPVCommandType.SET_WINDOW_SIZE:
                result = self._set_window_size_internal(mpv_handle, *args, **kwargs)
            elif cmd_type == MPVCommandType.GET_POSITION:
                result = self._get_property_double(mpv_handle, "time-pos")
            elif cmd_type == MPVCommandType.GET_DURATION:
                result = self._get_property_double(mpv_handle, "duration")
            elif cmd_type == MPVCommandType.GET_VOLUME:
                with self._state_lock:
                    result = self._volume
            elif cmd_type == MPVCommandType.GET_SPEED:
                with self._state_lock:
                    result = self._speed
            elif cmd_type == MPVCommandType.GET_VIDEO_SIZE:
                w = self._get_property_double(mpv_handle, "video-params/w") or 0
                h = self._get_property_double(mpv_handle, "video-params/h") or 0
                result = (int(w), int(h))
            elif cmd_type == MPVCommandType.IS_AUDIO_ONLY:
                result = self._is_audio_only_internal(mpv_handle)
            elif cmd_type == MPVCommandType.SET_VF_FILTER:
                result = self._set_vf_filter_internal(mpv_handle, *args, **kwargs)
            elif cmd_type == MPVCommandType.LOAD_GLSL_SHADER:
                result = self._load_glsl_shader_internal(mpv_handle, *args, **kwargs)
            elif cmd_type == MPVCommandType.SET_GLSL_SHADERS:
                result = self._set_glsl_shaders_internal(mpv_handle, *args, **kwargs)
            elif cmd_type == MPVCommandType.CLEAR_GLSL_SHADERS:
                result = self._clear_glsl_shaders_internal(mpv_handle, *args, **kwargs)
            elif cmd_type == MPVCommandType.SET_LUT:
                result = self._set_lut_internal(mpv_handle, *args, **kwargs)
            elif cmd_type == MPVCommandType.CLEAR_LUT:
                result = self._clear_lut_internal(mpv_handle)
            elif cmd_type == MPVCommandType.CLOSE:
                self._stop_event.set()
                result = True
        except Exception as e:
            print(f"[MPVWorker] 执行命令 {cmd_type} 时出错: {e}")
            result = None
        
        if 'result_id' in command:
            self._result_queue.put((command['result_id'], result))
    
    def _load_file_internal(self, mpv_handle: c_void_p, file_path: str, **kwargs) -> bool:
        """内部加载文件实现"""
        if not os.path.exists(file_path):
            self._emit_error(MpvErrorCode.LOADING_FAILED, f"文件不存在: {file_path}")
            return False
        
        with self._state_lock:
            self._current_file = file_path
            self._is_playing = False
            self._is_paused = False
            self._position = 0.0
            self._duration = 0.0
        
        cmd_args = [b"loadfile", file_path.encode('utf-8'), None]
        cmd_array = (c_char_p * len(cmd_args))(*cmd_args)
        
        result = self._dll_loader.dll.mpv_command(mpv_handle, cmd_array)
        return result >= 0
    
    def _play_internal(self, mpv_handle: c_void_p) -> bool:
        """内部播放实现"""
        c_value = ctypes.c_int(0)
        result = self._dll_loader.dll.mpv_set_property(
            mpv_handle, b"pause", MpvFormat.FLAG, byref(c_value)
        )
        if result >= 0:
            with self._state_lock:
                self._is_playing = True
                self._is_paused = False
            self.stateChanged.emit(True)
        return result >= 0
    
    def _pause_internal(self, mpv_handle: c_void_p) -> bool:
        """内部暂停实现"""
        c_value = ctypes.c_int(1)
        result = self._dll_loader.dll.mpv_set_property(
            mpv_handle, b"pause", MpvFormat.FLAG, byref(c_value)
        )
        if result >= 0:
            with self._state_lock:
                self._is_playing = False
                self._is_paused = True
            self.stateChanged.emit(False)
        return result >= 0
    
    def _stop_internal(self, mpv_handle: c_void_p) -> bool:
        """内部停止实现"""
        cmd_args = [b"stop", None]
        cmd_array = (c_char_p * len(cmd_args))(*cmd_args)
        result = self._dll_loader.dll.mpv_command(mpv_handle, cmd_array)
        
        if result >= 0:
            with self._state_lock:
                self._is_playing = False
                self._is_paused = False
                self._position = 0.0
            self.stateChanged.emit(False)
        return result >= 0
    
    def _seek_internal(self, mpv_handle: c_void_p, position: float, **kwargs) -> bool:
        """内部跳转实现"""
        cmd_args = [b"seek", str(position).encode('utf-8'), b"absolute", None]
        cmd_array = (c_char_p * len(cmd_args))(*cmd_args)
        return self._dll_loader.dll.mpv_command(mpv_handle, cmd_array) >= 0
    
    def _set_volume_internal(self, mpv_handle: c_void_p, volume: int, **kwargs) -> bool:
        """内部设置音量实现"""
        volume = max(0, min(100, volume))
        c_value = c_double(float(volume))
        result = self._dll_loader.dll.mpv_set_property(
            mpv_handle, b"volume", MpvFormat.DOUBLE, byref(c_value)
        )
        if result >= 0:
            with self._state_lock:
                self._volume = volume
            self.volumeChanged.emit(volume)
        return result >= 0
    
    def _set_speed_internal(self, mpv_handle: c_void_p, speed: float, **kwargs) -> bool:
        """内部设置速度实现"""
        speed = max(0.1, min(10.0, speed))
        c_value = c_double(speed)
        result = self._dll_loader.dll.mpv_set_property(
            mpv_handle, b"speed", MpvFormat.DOUBLE, byref(c_value)
        )
        if result >= 0:
            with self._state_lock:
                self._speed = speed
            self.speedChanged.emit(speed)
        return result >= 0
    
    def _set_muted_internal(self, mpv_handle: c_void_p, muted: bool, **kwargs) -> bool:
        """内部设置静音实现"""
        c_value = ctypes.c_int(1 if muted else 0)
        result = self._dll_loader.dll.mpv_set_property(
            mpv_handle, b"mute", MpvFormat.FLAG, byref(c_value)
        )
        if result >= 0:
            with self._state_lock:
                self._muted = muted
            self.mutedChanged.emit(muted)
        return result >= 0
    
    def _set_loop_internal(self, mpv_handle: c_void_p, loop_mode: str, **kwargs) -> bool:
        """内部设置循环模式实现"""
        result = self._dll_loader.dll.mpv_set_property_string(
            mpv_handle, b"loop-file", loop_mode.encode('utf-8')
        )
        if result >= 0:
            with self._state_lock:
                self._loop_mode = loop_mode
        return result >= 0
    
    def _set_vf_filter_internal(self, mpv_handle: c_void_p, filter_string: str, **kwargs) -> bool:
        """内部设置视频滤镜实现"""
        try:
            if filter_string:
                # 使用vf add命令添加滤镜
                cmd_args = [b"vf", b"add", filter_string.encode('utf-8'), None]
                cmd_array = (c_char_p * len(cmd_args))(*cmd_args)
                result = self._dll_loader.dll.mpv_command(mpv_handle, cmd_array)
                print(f"[LUT] vf add命令结果: {result}")
                
                # 尝试强制视频重新配置以应用滤镜
                if result >= 0:
                    try:
                        reconfig_args = [b"video-reconfig", None]
                        reconfig_array = (c_char_p * len(reconfig_args))(*reconfig_args)
                        reconfig_result = self._dll_loader.dll.mpv_command(mpv_handle, reconfig_array)
                        print(f"[LUT] video-reconfig结果: {reconfig_result}")
                    except Exception as e2:
                        print(f"[LUT] video-reconfig失败: {e2}")
                
                return result >= 0
            else:
                # 清除滤镜
                clear_cmd = [b"vf", b"cl", None]
                clear_array = (c_char_p * len(clear_cmd))(*clear_cmd)
                result = self._dll_loader.dll.mpv_command(mpv_handle, clear_array)
                print(f"[LUT] 清除vf结果: {result}")
                return result >= 0
        except Exception as e:
            print(f"[LUT] 设置vf滤镜失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _load_glsl_shader_internal(self, mpv_handle: c_void_p, shader_path: str, **kwargs) -> bool:
        """内部加载GLSL着色器实现（方式2）"""
        try:
            # 使用load glsl-shaders命令
            cmd_args = [b"load", b"glsl-shaders", shader_path.encode('utf-8'), None]
            cmd_array = (c_char_p * len(cmd_args))(*cmd_args)
            result = self._dll_loader.dll.mpv_command(mpv_handle, cmd_array)
            print(f"[LUT] load glsl-shaders命令结果: {result}")
            
            # 尝试强制视频重新配置
            if result >= 0:
                try:
                    reconfig_args = [b"video-reconfig", None]
                    reconfig_array = (c_char_p * len(reconfig_args))(*reconfig_args)
                    reconfig_result = self._dll_loader.dll.mpv_command(mpv_handle, reconfig_array)
                    print(f"[LUT] video-reconfig结果: {reconfig_result}")
                except Exception as e2:
                    print(f"[LUT] video-reconfig失败: {e2}")
            
            return result >= 0
        except Exception as e:
            print(f"[LUT] 加载GLSL着色器失败: {e}")
            return False
    
    def _set_glsl_shaders_internal(self, mpv_handle: c_void_p, shader_list: str, **kwargs) -> bool:
        """内部设置GLSL着色器列表实现（方式3）"""
        try:
            # 使用set glsl-shaders命令
            cmd_args = [b"set", b"glsl-shaders", shader_list.encode('utf-8'), None]
            cmd_array = (c_char_p * len(cmd_args))(*cmd_args)
            result = self._dll_loader.dll.mpv_command(mpv_handle, cmd_array)
            print(f"[LUT] set glsl-shaders命令结果: {result}")
            
            if result < 0:
                # 尝试使用set_property_string
                result2 = self._dll_loader.dll.mpv_set_property_string(
                    mpv_handle, b"glsl-shaders", shader_list.encode('utf-8')
                )
                print(f"[LUT] set_property_string glsl-shaders结果: {result2}")
                result = result2
            
            # 尝试强制视频重新配置
            if result >= 0:
                try:
                    reconfig_args = [b"video-reconfig", None]
                    reconfig_array = (c_char_p * len(reconfig_args))(*reconfig_args)
                    reconfig_result = self._dll_loader.dll.mpv_command(mpv_handle, reconfig_array)
                    print(f"[LUT] video-reconfig结果: {reconfig_result}")
                except Exception as e2:
                    print(f"[LUT] video-reconfig失败: {e2}")
            
            return result >= 0
        except Exception as e:
            print(f"[LUT] 设置GLSL着色器失败: {e}")
            return False
    
    def _clear_glsl_shaders_internal(self, mpv_handle: c_void_p, **kwargs) -> bool:
        """内部清除GLSL着色器实现"""
        try:
            # 使用glsl-shaders clr命令清除着色器
            cmd_args = [b"glsl-shaders", b"clr", None]
            cmd_array = (c_char_p * len(cmd_args))(*cmd_args)
            result = self._dll_loader.dll.mpv_command(mpv_handle, cmd_array)
            print(f"[LUT] glsl-shaders clr命令结果: {result}")
            return result >= 0
        except Exception as e:
            print(f"[LUT] 清除GLSL着色器失败: {e}")
            return False
    
    def _set_lut_internal(self, mpv_handle: c_void_p, lut_path: str, **kwargs) -> bool:
        """内部设置LUT实现（使用--lut选项）"""
        try:
            abs_path = os.path.abspath(lut_path).replace("\\", "/")
            result = self._dll_loader.dll.mpv_set_option_string(
                mpv_handle,
                b"lut",
                abs_path.encode('utf-8')
            )
            print(f"[LUT] set lut={abs_path} 结果: {result}")
            return result >= 0
        except Exception as e:
            print(f"[LUT] 设置LUT失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _clear_lut_internal(self, mpv_handle: c_void_p, **kwargs) -> bool:
        """内部清除LUT实现"""
        try:
            result = self._dll_loader.dll.mpv_set_option_string(
                mpv_handle,
                b"lut",
                b""
            )
            print(f"[LUT] 清除lut结果: {result}")
            return result >= 0
        except Exception as e:
            print(f"[LUT] 清除LUT失败: {e}")
            return False
    
    def _set_window_id_internal(self, mpv_handle: c_void_p, window_id: int, **kwargs) -> bool:
        """内部设置窗口ID实现"""
        with self._state_lock:
            self._window_id = window_id
        return self._dll_loader.dll.mpv_set_property_string(
            mpv_handle, b"wid", str(window_id).encode('utf-8')
        ) >= 0
    
    def _set_window_size_internal(self, mpv_handle: c_void_p, width: int, height: int, **kwargs) -> bool:
        """内部设置窗口大小实现"""
        return self._dll_loader.dll.mpv_set_property_string(
            mpv_handle, b"geometry", f"{width}x{height}".encode('utf-8')
        ) >= 0
    
    def _is_audio_only_internal(self, mpv_handle: c_void_p) -> bool:
        """内部检测纯音频文件实现"""
        try:
            video_width = self._get_property_double(mpv_handle, "video-params/w") or 0
            video_height = self._get_property_double(mpv_handle, "video-params/h") or 0
            
            if video_width == 0 or video_height == 0:
                return True
            
            video_codec = self._get_property_string(mpv_handle, "video-codec")
            if not video_codec:
                return True
            
            return False
        except Exception:
            return False
    
    def _get_property_double(self, mpv_handle: c_void_p, name: str) -> Optional[float]:
        """获取双精度属性"""
        c_value = c_double(0.0)
        result = self._dll_loader.dll.mpv_get_property(
            mpv_handle, name.encode('utf-8'), MpvFormat.DOUBLE, byref(c_value)
        )
        return c_value.value if result >= 0 else None
    
    def _get_property_string(self, mpv_handle: c_void_p, name: str) -> Optional[str]:
        """获取字符串属性"""
        result = self._dll_loader.dll.mpv_get_property_string(
            mpv_handle, name.encode('utf-8')
        )
        if result:
            value = result.decode('utf-8')
            self._dll_loader.dll.mpv_free(result)
            return value
        return None
    
    def _emit_error(self, error_code: int, error_message: str):
        """发射错误信号"""
        self.errorOccurred.emit(error_code, error_message)
    
    def _send_command(self, cmd_type: MPVCommandType, *args, **kwargs) -> Any:
        """发送命令到工作线程并等待结果"""
        if not self._initialized or not self._worker_thread or not self._worker_thread.is_alive():
            return None
        
        result_id = id(time.time())
        command = {
            'type': cmd_type,
            'args': args,
            'kwargs': kwargs,
            'result_id': result_id
        }
        
        self._command_queue.put(command)
        
        start_time = time.time()
        timeout = kwargs.get('timeout', 5.0)
        
        while time.time() - start_time < timeout:
            try:
                rid, result = self._result_queue.get(timeout=0.01)
                if rid == result_id:
                    return result
            except queue.Empty:
                continue
        
        return None
    
    def initialize(self) -> bool:
        """
        初始化MPV播放器
        
        Returns:
            bool: 初始化是否成功
        """
        if self._initialized:
            return True
        
        if self._worker_thread and self._worker_thread.is_alive():
            return True
        
        self._stop_event.clear()
        self._initialized_event.clear()
        
        self._worker_thread = threading.Thread(
            target=self._worker_thread_func,
            name="MPVWorkerThread",
            daemon=True
        )
        self._worker_thread.start()
        
        if self._initialized_event.wait(timeout=10.0):
            return True
        
        return False
    
    def load_file(self, file_path: str) -> bool:
        """
        加载视频文件
        
        Args:
            file_path: 视频文件路径
            
        Returns:
            bool: 加载是否成功
        """
        result = self._send_command(MPVCommandType.LOAD_FILE, file_path, timeout=30.0)
        return result if result is not None else False
    
    def play(self) -> bool:
        """
        开始/继续播放
        
        Returns:
            bool: 操作是否成功
        """
        result = self._send_command(MPVCommandType.PLAY, timeout=5.0)
        return result if result is not None else False
    
    def pause(self) -> bool:
        """
        暂停播放
        
        Returns:
            bool: 操作是否成功
        """
        result = self._send_command(MPVCommandType.PAUSE, timeout=5.0)
        return result if result is not None else False
    
    def toggle_pause(self) -> bool:
        """
        切换播放/暂停状态
        
        Returns:
            bool: 操作是否成功
        """
        with self._state_lock:
            is_paused = self._is_paused
        
        if is_paused or not self._is_playing:
            return self.play()
        else:
            return self.pause()
    
    def stop(self) -> bool:
        """
        停止播放
        
        Returns:
            bool: 操作是否成功
        """
        result = self._send_command(MPVCommandType.STOP, timeout=5.0)
        return result if result is not None else False
    
    def seek(self, position: float) -> bool:
        """
        跳转到指定位置
        
        Args:
            position: 目标位置（秒）
            
        Returns:
            bool: 操作是否成功
        """
        result = self._send_command(MPVCommandType.SEEK, position, timeout=5.0)
        return result if result is not None else False
    
    def seek_relative(self, seconds: float) -> bool:
        """
        相对跳转
        
        Args:
            seconds: 相对偏移量（秒），正数向前，负数向后
            
        Returns:
            bool: 操作是否成功
        """
        with self._state_lock:
            current_pos = self._position
        return self.seek(current_pos + seconds)
    
    def set_volume(self, volume: int) -> bool:
        """
        设置音量
        
        Args:
            volume: 音量值（0-100）
            
        Returns:
            bool: 操作是否成功
        """
        result = self._send_command(MPVCommandType.SET_VOLUME, volume, timeout=5.0)
        return result if result is not None else False
    
    def set_mute(self, muted: bool) -> bool:
        """
        设置静音状态
        
        Args:
            muted: 是否静音
            
        Returns:
            bool: 操作是否成功
        """
        result = self._send_command(MPVCommandType.SET_MUTED, muted, timeout=5.0)
        return result if result is not None else False
    
    def set_muted(self, muted: bool) -> bool:
        """
        设置静音状态（兼容API）
        
        Args:
            muted: 是否静音
            
        Returns:
            bool: 操作是否成功
        """
        return self.set_mute(muted)
    
    def toggle_mute(self) -> bool:
        """
        切换静音状态
        
        Returns:
            bool: 操作是否成功
        """
        with self._state_lock:
            muted = self._muted
        return self.set_mute(not muted)
    
    def set_speed(self, speed: float) -> bool:
        """
        设置播放速度
        
        Args:
            speed: 播放速度（0.1-10.0）
            
        Returns:
            bool: 操作是否成功
        """
        result = self._send_command(MPVCommandType.SET_SPEED, speed, timeout=5.0)
        return result if result is not None else False
    
    def set_loop(self, loop_mode: str) -> bool:
        """
        设置循环播放模式
        
        Args:
            loop_mode: 循环模式 ("no": 不循环, "yes": 单文件循环, "playlist": 播放列表循环)
            
        Returns:
            bool: 操作是否成功
        """
        result = self._send_command(MPVCommandType.SET_LOOP, loop_mode, timeout=5.0)
        return result if result is not None else False
    
    def set_loop_mode(self, mode: str) -> bool:
        """
        设置循环播放模式（兼容旧API）
        
        Args:
            mode: 循环模式
            
        Returns:
            bool: 操作是否成功
        """
        return self.set_loop(mode)
    
    def set_vf_filter(self, filter_string: str) -> bool:
        """
        设置视频滤镜（如LUT）
        
        Args:
            filter_string: 滤镜字符串，如 "lut3d=file=path/to/lut.cube"
            
        Returns:
            bool: 操作是否成功
        """
        result = self._send_command(MPVCommandType.SET_VF_FILTER, filter_string, timeout=5.0)
        return result if result is not None else False
    
    def load_glsl_shader(self, shader_path: str) -> bool:
        """
        加载GLSL着色器（方式2）
        
        Args:
            shader_path: 着色器文件路径
            
        Returns:
            bool: 操作是否成功
        """
        result = self._send_command(MPVCommandType.LOAD_GLSL_SHADER, shader_path, timeout=5.0)
        return result if result is not None else False
    
    def set_glsl_shaders(self, shader_list: str) -> bool:
        """
        设置GLSL着色器列表（方式3）
        
        Args:
            shader_list: 着色器列表JSON字符串
            
        Returns:
            bool: 操作是否成功
        """
        result = self._send_command(MPVCommandType.SET_GLSL_SHADERS, shader_list, timeout=5.0)
        return result if result is not None else False
    
    def clear_glsl_shaders(self) -> bool:
        """
        清除所有GLSL着色器
        
        Returns:
            bool: 操作是否成功
        """
        result = self._send_command(MPVCommandType.CLEAR_GLSL_SHADERS, timeout=5.0)
        return result if result is not None else False
    
    def set_lut(self, lut_path: str) -> bool:
        """
        设置LUT（使用--lut选项）
        
        Args:
            lut_path: LUT文件路径（.cube格式）
            
        Returns:
            bool: 操作是否成功
        """
        result = self._send_command(MPVCommandType.SET_LUT, lut_path, timeout=5.0)
        return result if result is not None else False
    
    def clear_lut(self) -> bool:
        """
        清除LUT
        
        Returns:
            bool: 操作是否成功
        """
        result = self._send_command(MPVCommandType.CLEAR_LUT, timeout=5.0)
        return result if result is not None else False
    
    def set_window_id(self, window_id: int) -> bool:
        """
        设置渲染窗口ID
        
        Args:
            window_id: 窗口句柄ID
            
        Returns:
            bool: 设置是否成功
        """
        result = self._send_command(MPVCommandType.SET_WINDOW_ID, window_id, timeout=10.0)
        return result if result is not None else False
    
    def set_window_size(self, width: int, height: int) -> bool:
        """
        设置MPV渲染窗口大小
        
        Args:
            width: 窗口宽度
            height: 窗口高度
            
        Returns:
            bool: 设置是否成功
        """
        result = self._send_command(MPVCommandType.SET_WINDOW_SIZE, width, height, timeout=5.0)
        return result if result is not None else False
    
    def refresh_video(self) -> bool:
        """刷新视频渲染"""
        return True
    
    def set_geometry(self, x: int, y: int, width: int, height: int) -> bool:
        """设置MPV渲染窗口几何尺寸"""
        return self.set_window_size(width, height)
    
    def set_position(self, position: float) -> bool:
        """设置播放位置"""
        return self.seek(position)
    
    def get_position(self) -> Optional[float]:
        """
        获取当前播放位置
        
        Returns:
            Optional[float]: 当前位置（秒），失败返回None
        """
        result = self._send_command(MPVCommandType.GET_POSITION, timeout=1.0)
        return result
    
    def get_duration(self) -> Optional[float]:
        """
        获取视频总时长
        
        Returns:
            Optional[float]: 总时长（秒），失败返回None
        """
        result = self._send_command(MPVCommandType.GET_DURATION, timeout=1.0)
        return result
    
    def get_volume(self) -> int:
        """
        获取当前音量
        
        Returns:
            int: 音量值（0-100）
        """
        with self._state_lock:
            return self._volume
    
    def get_speed(self) -> float:
        """
        获取当前播放速度
        
        Returns:
            float: 播放速度
        """
        with self._state_lock:
            return self._speed
    
    def is_playing(self) -> bool:
        """
        获取播放状态
        
        Returns:
            bool: 是否正在播放
        """
        with self._state_lock:
            return self._is_playing
    
    def is_paused(self) -> bool:
        """
        获取暂停状态
        
        Returns:
            bool: 是否暂停
        """
        with self._state_lock:
            return self._is_paused
    
    def is_muted(self) -> bool:
        """
        获取静音状态
        
        Returns:
            bool: 是否静音
        """
        with self._state_lock:
            return self._muted
    
    def get_loop_mode(self) -> str:
        """
        获取循环播放模式
        
        Returns:
            str: 循环模式
        """
        with self._state_lock:
            return self._loop_mode
    
    def get_current_file(self) -> str:
        """
        获取当前播放的文件路径
        
        Returns:
            str: 文件路径
        """
        with self._state_lock:
            return self._current_file
    
    def get_video_size(self) -> tuple:
        """
        获取视频尺寸
        
        Returns:
            tuple: (宽度, 高度)，失败返回(0, 0)
        """
        result = self._send_command(MPVCommandType.GET_VIDEO_SIZE, timeout=1.0)
        return result if result is not None else (0, 0)
    
    def is_audio_only(self) -> bool:
        """
        检测当前文件是否为纯音频文件
        
        Returns:
            bool: 如果是纯音频文件返回True，否则返回False
        """
        result = self._send_command(MPVCommandType.IS_AUDIO_ONLY, timeout=1.0)
        return result if result is not None else False
    
    def take_screenshot(self, file_path: str, include_subtitles: bool = True) -> bool:
        """
        截取当前帧
        
        Args:
            file_path: 保存路径
            include_subtitles: 是否包含字幕
            
        Returns:
            bool: 操作是否成功
        """
        return False
    
    def pre_cleanup(self):
        """
        预清理 - 让 MPV 进入空闲状态，加速后续销毁
        在调用 close() 之前先调用此方法，可以显著缩短销毁时间
        """
        if not self._initialized or not self._mpv_handle:
            return
        
        try:
            # 1. 先暂停播放（停止解码器工作）
            self._pause_internal(self._mpv_handle)
            time.sleep(0.03)  # 给30ms让解码器停止
            
            # 2. 停止播放（释放文件句柄）
            self._stop_internal(self._mpv_handle)
            time.sleep(0.02)  # 给20ms释放文件
            
            # 3. 清除视频滤镜/LUT（如果有）
            try:
                self._clear_glsl_shaders_internal(self._mpv_handle)
                self._set_vf_filter_internal(self._mpv_handle, "")
                self._clear_lut_internal(self._mpv_handle)
            except:
                pass
                
        except Exception as e:
            print(f"[MPVPlayerCore] 预清理时出错: {e}")
    
    def close(self, async_mode=False, timeout=1.0):
        """
        关闭播放器并释放资源
        
        Args:
            async_mode: 是否异步关闭（True=立即返回，后台清理）
            timeout: 同步模式下的最大等待时间（秒）
        """
        if not self._initialized:
            return
        
        # 预清理 - 让 MPV 进入空闲状态
        self.pre_cleanup()
        
        # 发送关闭命令
        self._send_command(MPVCommandType.CLOSE, timeout=0.5)
        self._stop_event.set()
        
        if async_mode:
            # 异步模式：启动后台线程执行清理
            cleanup_thread = threading.Thread(
                target=self._async_cleanup,
                args=(timeout,),
                daemon=True
            )
            cleanup_thread.start()
        else:
            # 同步模式：短超时等待
            self._sync_cleanup(timeout)
    
    def _sync_cleanup(self, timeout=1.0):
        """同步清理 - 短超时等待"""
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout)
            
            # 如果还在运行，记录警告但继续（不阻塞）
            if self._worker_thread.is_alive():
                print(f"[MPVPlayerCore] 警告：工作线程未在 {timeout}s 内结束，强制继续")
        
        self._worker_thread = None
        
        with self._state_lock:
            self._initialized = False
            self._is_playing = False
            self._is_paused = False
    
    def _async_cleanup(self, timeout=2.0):
        """异步清理 - 在后台完成"""
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout)
        
        self._worker_thread = None
        
        with self._state_lock:
            self._initialized = False
            self._is_playing = False
            self._is_paused = False
        
        print("[MPVPlayerCore] 异步清理完成")
    
    def is_closing(self):
        """检查是否正在关闭"""
        return self._stop_event.is_set()
    
    def wait_for_close(self, timeout=5.0):
        """
        等待关闭完成
        
        Args:
            timeout: 最大等待时间（秒）
            
        Returns:
            bool: 是否在超时前完成关闭
        """
        if not self._worker_thread:
            return True
        
        self._worker_thread.join(timeout=timeout)
        return not self._worker_thread.is_alive()
    
    def __del__(self):
        """析构函数"""
        try:
            self.close()
        except Exception:
            pass
