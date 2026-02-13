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
基于libmpv实现高性能视频播放功能，提供线程安全的播放控制接口
"""

import os
import sys
import ctypes
import threading
import time
from ctypes import c_void_p, c_int, c_int64, c_double, c_char_p, POINTER, Structure, byref
from typing import Optional, Callable, Dict, Any, List
from enum import IntEnum

from PySide6.QtCore import QObject, Signal, QThread, QMutex, QWaitCondition, QTimer, Qt


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


class MPVEventThread(QThread):
    """
    MPV事件处理线程
    负责从MPV事件队列中获取事件并转发到主线程
    """
    
    event_received = Signal(int, object)
    
    def __init__(self, mpv_handle, parent=None):
        super().__init__(parent)
        self._mpv_handle = mpv_handle
        self._running = False
        self._mutex = QMutex()
        self._wait_condition = QWaitCondition()
    
    def run(self):
        """线程主循环"""
        self._running = True
        
        while self._running:
            try:
                if not self._mpv_handle or not self._mpv_handle.handle:
                    break
                    
                event_ptr = self._mpv_handle.wait_event(0.1)
                
                if event_ptr:
                    event = event_ptr.contents
                    event_id = event.event_id
                    
                    if event_id != MpvEventId.NONE:
                        event_data = self._parse_event(event)
                        self.event_received.emit(event_id, event_data)
                        
                        if event_id == MpvEventId.SHUTDOWN:
                            break
                            
            except Exception as e:
                if not self._running:
                    break
                pass
    
    def _parse_event(self, event: MpvEvent) -> Dict[str, Any]:
        """
        解析MPV事件
        
        Args:
            event: MPV事件结构体
            
        Returns:
            Dict[str, Any]: 解析后的事件数据
        """
        event_data = {
            "event_id": event.event_id,
            "error": event.error,
            "reply_userdata": event.reply_userdata,
        }
        
        if event.event_id == MpvEventId.PROPERTY_CHANGE and event.data:
            prop_event = ctypes.cast(event.data, POINTER(MpvEventProperty)).contents
            event_data["property_name"] = prop_event.name.decode('utf-8') if prop_event.name else ""
            event_data["format"] = prop_event.format
            
            if prop_event.format == MpvFormat.STRING and prop_event.data:
                value_ptr = ctypes.cast(prop_event.data, POINTER(c_char_p))
                if value_ptr.contents:
                    event_data["value"] = value_ptr.contents.value.decode('utf-8')
            elif prop_event.format == MpvFormat.DOUBLE and prop_event.data:
                value_ptr = ctypes.cast(prop_event.data, POINTER(c_double))
                event_data["value"] = value_ptr.contents.value
            elif prop_event.format == MpvFormat.FLAG and prop_event.data:
                value_ptr = ctypes.cast(prop_event.data, POINTER(ctypes.c_int))
                event_data["value"] = bool(value_ptr.contents.value)
            elif prop_event.format == MpvFormat.INT64 and prop_event.data:
                value_ptr = ctypes.cast(prop_event.data, POINTER(c_int64))
                event_data["value"] = value_ptr.contents.value
                
        elif event.event_id == MpvEventId.END_FILE and event.data:
            end_file_event = ctypes.cast(event.data, POINTER(MpvEventEndFile)).contents
            event_data["reason"] = end_file_event.reason
            event_data["error"] = end_file_event.error
            
        elif event.event_id == MpvEventId.START_FILE and event.data:
            start_file_event = ctypes.cast(event.data, POINTER(MpvEventStartFile)).contents
            event_data["playlist_entry_id"] = start_file_event.playlist_entry_id
            
        return event_data
    
    def stop(self):
        """停止事件线程"""
        self._mutex.lock()
        self._running = False
        self._wait_condition.wakeAll()
        self._mutex.unlock()
        
        if self.isRunning():
            self.wait(1000)


class MPVHandle:
    """
    MPV句柄封装类
    提供对MPV实例的安全操作接口
    """
    
    def __init__(self, dll_loader: MPVDLLLoader):
        self._dll_loader = dll_loader
        self._handle = None
    
    def create(self) -> bool:
        """
        创建MPV实例
        
        Returns:
            bool: 创建是否成功
        """
        if not self._dll_loader.is_loaded:
            return False
        
        try:
            self._handle = self._dll_loader.dll.mpv_create()
            return self._handle is not None
        except Exception:
            return False
    
    def initialize(self) -> int:
        """
        初始化MPV实例
        
        Returns:
            int: 错误码，0表示成功
        """
        if not self._handle:
            return MpvErrorCode.UNINITIALIZED
        
        try:
            return self._dll_loader.dll.mpv_initialize(self._handle)
        except Exception:
            return MpvErrorCode.GENERIC
    
    def destroy(self):
        """销毁MPV实例"""
        if self._handle:
            try:
                self._dll_loader.dll.mpv_destroy(self._handle)
            except Exception:
                pass
            self._handle = None
    
    def terminate_destroy(self):
        """终止并销毁MPV实例"""
        if self._handle:
            try:
                self._dll_loader.dll.mpv_terminate_destroy(self._handle)
            except Exception:
                pass
            self._handle = None
    
    def set_option_string(self, name: str, value: str) -> int:
        """
        设置MPV选项（字符串格式）
        
        Args:
            name: 选项名称
            value: 选项值
            
        Returns:
            int: 错误码
        """
        if not self._handle:
            return MpvErrorCode.UNINITIALIZED
        
        try:
            return self._dll_loader.dll.mpv_set_option_string(
                self._handle,
                name.encode('utf-8'),
                value.encode('utf-8')
            )
        except Exception:
            return MpvErrorCode.GENERIC
    
    def command(self, *args) -> int:
        """
        执行MPV命令
        
        Args:
            *args: 命令参数列表
            
        Returns:
            int: 错误码
        """
        if not self._handle:
            return MpvErrorCode.UNINITIALIZED
        
        try:
            cmd_args = [arg.encode('utf-8') if isinstance(arg, str) else arg for arg in args]
            cmd_args.append(None)
            
            cmd_array = (c_char_p * len(cmd_args))()
            for i, arg in enumerate(cmd_args):
                cmd_array[i] = arg
            
            return self._dll_loader.dll.mpv_command(self._handle, cmd_array)
        except Exception:
            return MpvErrorCode.GENERIC
    
    def command_string(self, cmd: str) -> int:
        """
        执行MPV命令字符串
        
        Args:
            cmd: 命令字符串
            
        Returns:
            int: 错误码
        """
        if not self._handle:
            return MpvErrorCode.UNINITIALIZED
        
        try:
            return self._dll_loader.dll.mpv_command_string(
                self._handle,
                cmd.encode('utf-8')
            )
        except Exception:
            return MpvErrorCode.GENERIC
    
    def set_property_string(self, name: str, value: str) -> int:
        """
        设置MPV属性（字符串格式）
        
        Args:
            name: 属性名称
            value: 属性值
            
        Returns:
            int: 错误码
        """
        if not self._handle:
            return MpvErrorCode.UNINITIALIZED
        
        try:
            return self._dll_loader.dll.mpv_set_property_string(
                self._handle,
                name.encode('utf-8'),
                value.encode('utf-8')
            )
        except Exception:
            return MpvErrorCode.GENERIC
    
    def get_property_string(self, name: str) -> Optional[str]:
        """
        获取MPV属性（字符串格式）
        
        Args:
            name: 属性名称
            
        Returns:
            Optional[str]: 属性值，失败返回None
        """
        if not self._handle:
            return None
        
        try:
            result = self._dll_loader.dll.mpv_get_property_string(
                self._handle,
                name.encode('utf-8')
            )
            
            if result:
                value = result.decode('utf-8')
                self._dll_loader.dll.mpv_free(result)
                return value
            return None
        except Exception:
            return None
    
    def set_property_double(self, name: str, value: float) -> int:
        """
        设置MPV属性（双精度浮点格式）
        
        Args:
            name: 属性名称
            value: 属性值
            
        Returns:
            int: 错误码
        """
        if not self._handle:
            return MpvErrorCode.UNINITIALIZED
        
        try:
            c_value = c_double(value)
            return self._dll_loader.dll.mpv_set_property(
                self._handle,
                name.encode('utf-8'),
                MpvFormat.DOUBLE,
                byref(c_value)
            )
        except Exception:
            return MpvErrorCode.GENERIC
    
    def get_property_double(self, name: str) -> Optional[float]:
        """
        获取MPV属性（双精度浮点格式）
        
        Args:
            name: 属性名称
            
        Returns:
            Optional[float]: 属性值，失败返回None
        """
        if not self._handle:
            return None
        
        try:
            c_value = c_double(0.0)
            result = self._dll_loader.dll.mpv_get_property(
                self._handle,
                name.encode('utf-8'),
                MpvFormat.DOUBLE,
                byref(c_value)
            )
            
            if result >= 0:
                return c_value.value
            return None
        except Exception:
            return None
    
    def set_property_flag(self, name: str, value: bool) -> int:
        """
        设置MPV属性（布尔格式）
        
        Args:
            name: 属性名称
            value: 属性值
            
        Returns:
            int: 错误码
        """
        if not self._handle:
            return MpvErrorCode.UNINITIALIZED
        
        try:
            c_value = ctypes.c_int(1 if value else 0)
            return self._dll_loader.dll.mpv_set_property(
                self._handle,
                name.encode('utf-8'),
                MpvFormat.FLAG,
                byref(c_value)
            )
        except Exception:
            return MpvErrorCode.GENERIC
    
    def get_property_flag(self, name: str) -> Optional[bool]:
        """
        获取MPV属性（布尔格式）
        
        Args:
            name: 属性名称
            
        Returns:
            Optional[bool]: 属性值，失败返回None
        """
        if not self._handle:
            return None
        
        try:
            c_value = ctypes.c_int(0)
            result = self._dll_loader.dll.mpv_get_property(
                self._handle,
                name.encode('utf-8'),
                MpvFormat.FLAG,
                byref(c_value)
            )
            
            if result >= 0:
                return bool(c_value.value)
            return None
        except Exception:
            return None
    
    def observe_property(self, name: str, reply_userdata: int = 0, fmt: int = MpvFormat.STRING) -> int:
        """
        观察MPV属性变化
        
        Args:
            name: 属性名称
            reply_userdata: 回调用户数据
            fmt: 数据格式
            
        Returns:
            int: 错误码
        """
        if not self._handle:
            return MpvErrorCode.UNINITIALIZED
        
        try:
            return self._dll_loader.dll.mpv_observe_property(
                self._handle,
                reply_userdata,
                name.encode('utf-8'),
                fmt
            )
        except Exception:
            return MpvErrorCode.GENERIC
    
    def unobserve_property(self, reply_userdata: int) -> int:
        """
        取消观察MPV属性
        
        Args:
            reply_userdata: 之前注册的回调用户数据
            
        Returns:
            int: 移除的属性数量，负值表示错误
        """
        if not self._handle:
            return MpvErrorCode.UNINITIALIZED
        
        try:
            return self._dll_loader.dll.mpv_unobserve_property(
                self._handle,
                reply_userdata
            )
        except Exception:
            return MpvErrorCode.GENERIC
    
    def wait_event(self, timeout: float) -> Optional[POINTER]:
        """
        等待MPV事件
        
        Args:
            timeout: 超时时间（秒）
            
        Returns:
            Optional[POINTER]: 事件指针，超时返回None
        """
        if not self._handle:
            return None
        
        try:
            return self._dll_loader.dll.mpv_wait_event(self._handle, timeout)
        except Exception:
            return None
    
    def wakeup(self):
        """唤醒MPV事件等待"""
        if self._handle:
            try:
                self._dll_loader.dll.mpv_wakeup(self._handle)
            except Exception:
                pass
    
    def request_event(self, event_id: int, enable: bool) -> int:
        """
        请求启用/禁用特定事件
        
        Args:
            event_id: 事件ID
            enable: 是否启用
            
        Returns:
            int: 错误码
        """
        if not self._handle:
            return MpvErrorCode.UNINITIALIZED
        
        try:
            return self._dll_loader.dll.mpv_request_event(
                self._handle,
                event_id,
                1 if enable else 0
            )
        except Exception:
            return MpvErrorCode.GENERIC
    
    @property
    def handle(self):
        """获取原始MPV句柄"""
        return self._handle
    
    @property
    def is_valid(self) -> bool:
        """检查句柄是否有效"""
        return self._handle is not None


class MPVPlayerCore(QObject):
    """
    MPV播放器核心类
    
    提供基于libmpv的高性能视频播放功能，包括：
    - 视频文件加载和播放控制
    - 音量、播放速度、进度控制
    - 循环播放模式
    - 线程安全的事件处理
    - 与PySide6信号槽机制集成
    
    Signals:
        stateChanged: 播放状态变化信号 (is_playing: bool)
        positionChanged: 播放位置变化信号 (position: float, duration: float)
        durationChanged: 时长变化信号 (duration: float)
        volumeChanged: 音量变化信号 (volume: int)
        speedChanged: 播放速度变化信号 (speed: float)
        mutedChanged: 静音状态变化信号 (muted: bool)
        fileLoaded: 文件加载完成信号 (file_path: str)
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
    fileLoaded = Signal(str, bool)  # 文件路径, 是否为音频文件
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
        self._mpv_handle: Optional[MPVHandle] = None
        self._event_thread: Optional[MPVEventThread] = None
        
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
        
        self._mutex = QMutex()
        self._initialized = False
        self._window_id: Optional[int] = None
        
        self._position_timer = QTimer(self)
        self._position_timer.timeout.connect(self._update_position)
        self._position_timer.setInterval(100)
    
    def initialize(self) -> bool:
        """
        初始化MPV播放器
        
        Returns:
            bool: 初始化是否成功
        """
        if self._initialized:
            return True
        
        if not self._dll_loader.load_dll():
            self.errorOccurred.emit(
                MpvErrorCode.GENERIC,
                "无法加载libmpv DLL"
            )
            return False
        
        self._mpv_handle = MPVHandle(self._dll_loader)
        
        if not self._mpv_handle.create():
            self.errorOccurred.emit(
                MpvErrorCode.GENERIC,
                "无法创建MPV实例"
            )
            return False
        
        self._configure_mpv()
        
        result = self._mpv_handle.initialize()
        if result < 0:
            error_msg = self._dll_loader.get_error_string(result)
            self.errorOccurred.emit(result, f"MPV初始化失败: {error_msg}")
            self._mpv_handle.destroy()
            self._mpv_handle = None
            return False
        
        self._observe_properties()
        
        self._event_thread = MPVEventThread(self._mpv_handle, self)
        self._event_thread.event_received.connect(
            self._handle_event, 
            Qt.QueuedConnection
        )
        self._event_thread.start()
        
        self._initialized = True
        return True
    
    def _configure_mpv(self):
        """配置MPV基本参数"""
        if not self._mpv_handle:
            return
        
        config = {
            "vo": "gpu",
            "hwdec": "auto-safe",
            "keep-open": "yes",
            "idle": "once",
            "force-window": "no",
            "audio-display": "no",  # 禁用音频封面显示
            "input-cursor": "no",
            "cursor-autohide": "no",
            "osc": "no",
            "osd-level": "0",
            "terminal": "no",
            "msg-level": "all=no",
            "keepaspect": "yes",
            "keepaspect-window": "no",  # 禁用窗口保持宽高比，避免边缘凸起
            "video-unscaled": "no",
            "video-pan-x": "0",
            "video-pan-y": "0",
            "video-zoom": "0",
            "panscan": "0",
            "video-align-x": "0",
            "video-align-y": "0",
        }
        
        for name, value in config.items():
            self._mpv_handle.set_option_string(name, value)
    
    def _observe_properties(self):
        """设置属性观察"""
        if not self._mpv_handle:
            return
        
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
            self._mpv_handle.observe_property(prop_name, 0, prop_format)
    
    def _handle_event(self, event_id: int, event_data: Dict[str, Any]):
        """
        处理MPV事件
        
        Args:
            event_id: 事件ID
            event_data: 事件数据
        """
        if event_id == MpvEventId.PROPERTY_CHANGE:
            self._handle_property_change(event_data)
        elif event_id == MpvEventId.FILE_LOADED:
            self._handle_file_loaded()
        elif event_id == MpvEventId.END_FILE:
            self._handle_end_file(event_data)
        elif event_id == MpvEventId.SEEK:
            self._is_seeking = True
        elif event_id == MpvEventId.PLAYBACK_RESTART:
            self._is_seeking = False
            self.seekFinished.emit()
        elif event_id == MpvEventId.SHUTDOWN:
            self._handle_shutdown()
    
    def _handle_property_change(self, event_data: Dict[str, Any]):
        """
        处理属性变化事件
        
        Args:
            event_data: 事件数据
        """
        prop_name = event_data.get("property_name", "")
        value = event_data.get("value")
        
        if prop_name == "time-pos" and value is not None:
            self._position = float(value)
            if self._duration > 0:
                self.positionChanged.emit(self._position, self._duration)
                
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
            width = int(value)
            height = self._mpv_handle.get_property_double("video-params/h") or 0
            if width > 0 and height > 0:
                self.videoSizeChanged.emit(width, int(height))
    
    def _handle_file_loaded(self):
        """处理文件加载完成事件"""
        self._position_timer.start()
        # 使用 QTimer.singleShot 将音频检测推迟到主线程执行
        # 避免在事件线程中直接调用 MPV API 导致访问冲突
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._check_audio_and_emit_loaded)

    def _check_audio_and_emit_loaded(self):
        """
        在主线程中检测是否为纯音频文件并发送加载完成信号
        避免在 MPV 事件线程中直接访问 MPV API 导致访问冲突
        """
        is_audio = False
        try:
            # 检测是否为纯音频文件，如果是则将窗口大小设置为0×0
            is_audio = self.is_audio_only()
            if is_audio:
                self.set_window_size(0, 0)
        except Exception as e:
            print(f"[MPVPlayerCore] 检测音频文件时出错: {e}")
        finally:
            # 发送文件加载完成信号，同时传递是否为音频文件的信息
            self.fileLoaded.emit(self._current_file, is_audio)
    
    def _handle_end_file(self, event_data: Dict[str, Any]):
        """
        处理文件播放结束事件
        
        Args:
            event_data: 事件数据
        """
        reason = event_data.get("reason", MpvEndFileReason.EOF)
        error = event_data.get("error", 0)
        
        self._is_playing = False
        self._is_paused = False
        self.stateChanged.emit(False)
        
        self._position_timer.stop()
        
        if reason == MpvEndFileReason.ERROR:
            error_msg = self._dll_loader.get_error_string(error)
            self.errorOccurred.emit(error, error_msg)
        
        self.fileEnded.emit(reason)
    
    def _handle_shutdown(self):
        """处理MPV关闭事件"""
        self._initialized = False
        self._position_timer.stop()
    
    def _update_position(self):
        """更新播放位置"""
        if self._mpv_handle and self._initialized and not self._is_seeking:
            position = self.get_position()
            if position is not None:
                self._position = position
                if self._duration > 0:
                    self.positionChanged.emit(self._position, self._duration)
    
    def set_window_id(self, window_id: int) -> bool:
        """
        设置渲染窗口ID
        
        Args:
            window_id: 窗口句柄ID
            
        Returns:
            bool: 设置是否成功
        """
        if not self._initialized or not self._mpv_handle:
            return False
        
        self._window_id = window_id
        result = self._mpv_handle.set_property_string("wid", str(window_id))
        return result >= 0

    def refresh_video(self) -> bool:
        """
        刷新视频渲染
        在窗口尺寸变化时调用，确保MPV渲染尺寸同步

        Returns:
            bool: 操作是否成功
        """
        if not self._initialized or not self._mpv_handle:
            return False

        try:
            # 触发MPV重新计算视频几何尺寸
            self._mpv_handle.command("video-reload")
            return True
        except Exception:
            return False

    def set_geometry(self, x: int, y: int, width: int, height: int) -> bool:
        """
        设置MPV渲染窗口几何尺寸
        确保原生窗口与Qt窗口尺寸完全一致

        Args:
            x: 窗口X坐标
            y: 窗口Y坐标
            width: 窗口宽度
            height: 窗口高度

        Returns:
            bool: 设置是否成功
        """
        if not self._initialized or not self._mpv_handle:
            return False

        try:
            # 设置几何尺寸属性
            self._mpv_handle.set_property_string("geometry", f"{width}x{height}+{x}+{y}")
            # 强制重新配置视频输出
            self._mpv_handle.command("video-reload")
            return True
        except Exception:
            return False

    def load_file(self, file_path: str) -> bool:
        """
        加载视频文件
        
        Args:
            file_path: 视频文件路径
            
        Returns:
            bool: 加载是否成功
        """
        if not self._initialized:
            if not self.initialize():
                return False
        
        if not os.path.exists(file_path):
            self.errorOccurred.emit(
                MpvErrorCode.LOADING_FAILED,
                f"文件不存在: {file_path}"
            )
            return False
        
        if self._is_playing or self._current_file:
            self._mpv_handle.command("stop")
            self._is_playing = False
            self._is_paused = False
            self._position = 0.0
            self._duration = 0.0
            self._position_timer.stop()
            self.stateChanged.emit(False)
        
        self._current_file = file_path
        
        result = self._mpv_handle.command("loadfile", file_path)
        
        if result < 0:
            error_msg = self._dll_loader.get_error_string(result)
            self.errorOccurred.emit(result, f"加载文件失败: {error_msg}")
            return False
        
        return True
    
    def play(self) -> bool:
        """
        开始/继续播放
        
        Returns:
            bool: 操作是否成功
        """
        if not self._initialized or not self._mpv_handle:
            return False
        
        result = self._mpv_handle.set_property_flag("pause", False)
        
        if result >= 0:
            self._is_playing = True
            self._is_paused = False
            self.stateChanged.emit(True)
            self._position_timer.start()
            return True
        
        return False
    
    def pause(self) -> bool:
        """
        暂停播放
        
        Returns:
            bool: 操作是否成功
        """
        if not self._initialized or not self._mpv_handle:
            return False
        
        result = self._mpv_handle.set_property_flag("pause", True)
        
        if result >= 0:
            self._is_playing = False
            self._is_paused = True
            self.stateChanged.emit(False)
            return True
        
        return False
    
    def toggle_pause(self) -> bool:
        """
        切换播放/暂停状态
        
        Returns:
            bool: 操作是否成功
        """
        if self._is_paused or not self._is_playing:
            return self.play()
        else:
            return self.pause()
    
    def stop(self) -> bool:
        """
        停止播放
        
        Returns:
            bool: 操作是否成功
        """
        if not self._initialized or not self._mpv_handle:
            return False
        
        result = self._mpv_handle.command("stop")
        
        if result >= 0:
            self._is_playing = False
            self._is_paused = False
            self._position = 0.0
            self.stateChanged.emit(False)
            self._position_timer.stop()
            return True
        
        return False
    
    def seek(self, position: float) -> bool:
        """
        跳转到指定位置
        
        Args:
            position: 目标位置（秒）
            
        Returns:
            bool: 操作是否成功
        """
        if not self._initialized or not self._mpv_handle:
            return False
        
        result = self._mpv_handle.command("seek", str(position), "absolute")
        
        if result >= 0:
            self._is_seeking = True
            return True
        
        return False
    
    def seek_relative(self, seconds: float) -> bool:
        """
        相对跳转
        
        Args:
            seconds: 相对偏移量（秒），正数向前，负数向后
            
        Returns:
            bool: 操作是否成功
        """
        if not self._initialized or not self._mpv_handle:
            return False
        
        result = self._mpv_handle.command("seek", str(seconds), "relative")
        return result >= 0
    
    def set_volume(self, volume: int) -> bool:
        """
        设置音量
        
        Args:
            volume: 音量值（0-100）
            
        Returns:
            bool: 操作是否成功
        """
        if not self._initialized or not self._mpv_handle:
            return False
        
        volume = max(0, min(100, volume))
        result = self._mpv_handle.set_property_double("volume", float(volume))
        
        if result >= 0:
            self._volume = volume
            self.volumeChanged.emit(volume)
            return True
        
        return False
    
    def set_mute(self, muted: bool) -> bool:
        """
        设置静音状态
        
        Args:
            muted: 是否静音
            
        Returns:
            bool: 操作是否成功
        """
        if not self._initialized or not self._mpv_handle:
            return False
        
        result = self._mpv_handle.set_property_flag("mute", muted)
        
        if result >= 0:
            self._muted = muted
            self.mutedChanged.emit(muted)
            return True
        
        return False
    
    def toggle_mute(self) -> bool:
        """
        切换静音状态
        
        Returns:
            bool: 操作是否成功
        """
        return self.set_mute(not self._muted)
    
    def set_speed(self, speed: float) -> bool:
        """
        设置播放速度
        
        Args:
            speed: 播放速度（0.1-10.0）
            
        Returns:
            bool: 操作是否成功
        """
        if not self._initialized or not self._mpv_handle:
            return False
        
        speed = max(0.1, min(10.0, speed))
        result = self._mpv_handle.set_property_double("speed", speed)
        
        if result >= 0:
            self._speed = speed
            self.speedChanged.emit(speed)
            return True
        
        return False
    
    def set_loop_mode(self, mode: str) -> bool:
        """
        设置循环播放模式
        
        Args:
            mode: 循环模式 ("no": 不循环, "yes": 单文件循环, "playlist": 播放列表循环)
            
        Returns:
            bool: 操作是否成功
        """
        if not self._initialized or not self._mpv_handle:
            return False
        
        result = self._mpv_handle.set_property_string("loop-file", mode)
        
        if result >= 0:
            self._loop_mode = mode
            return True
        
        return False
    
    def get_position(self) -> Optional[float]:
        """
        获取当前播放位置
        
        Returns:
            Optional[float]: 当前位置（秒），失败返回None
        """
        if not self._initialized or not self._mpv_handle:
            return None
        
        return self._mpv_handle.get_property_double("time-pos")
    
    def get_duration(self) -> Optional[float]:
        """
        获取视频总时长
        
        Returns:
            Optional[float]: 总时长（秒），失败返回None
        """
        if not self._initialized or not self._mpv_handle:
            return None
        
        return self._mpv_handle.get_property_double("duration")
    
    def get_volume(self) -> int:
        """
        获取当前音量
        
        Returns:
            int: 音量值（0-100）
        """
        return self._volume
    
    def get_speed(self) -> float:
        """
        获取当前播放速度
        
        Returns:
            float: 播放速度
        """
        return self._speed
    
    def is_playing(self) -> bool:
        """
        获取播放状态
        
        Returns:
            bool: 是否正在播放
        """
        return self._is_playing
    
    def is_paused(self) -> bool:
        """
        获取暂停状态
        
        Returns:
            bool: 是否暂停
        """
        return self._is_paused
    
    def is_muted(self) -> bool:
        """
        获取静音状态
        
        Returns:
            bool: 是否静音
        """
        return self._muted
    
    def get_loop_mode(self) -> str:
        """
        获取循环播放模式
        
        Returns:
            str: 循环模式
        """
        return self._loop_mode
    
    def get_current_file(self) -> str:
        """
        获取当前播放的文件路径
        
        Returns:
            str: 文件路径
        """
        return self._current_file
    
    def get_video_size(self) -> tuple:
        """
        获取视频尺寸
        
        Returns:
            tuple: (宽度, 高度)，失败返回(0, 0)
        """
        if not self._initialized or not self._mpv_handle:
            return (0, 0)
        
        width = self._mpv_handle.get_property_double("video-params/w") or 0
        height = self._mpv_handle.get_property_double("video-params/h") or 0
        
        return (int(width), int(height))
    
    def is_audio_only(self) -> bool:
        """
        检测当前文件是否为纯音频文件（无视频流）
        
        Returns:
            bool: 如果是纯音频文件返回True，否则返回False
        """
        if not self._initialized or not self._mpv_handle:
            return False
        
        try:
            # 通过检查video-codec属性判断是否有视频流
            # 如果没有视频流或视频尺寸为0，则认为是纯音频文件
            video_width = self._mpv_handle.get_property_double("video-params/w") or 0
            video_height = self._mpv_handle.get_property_double("video-params/h") or 0
            
            # 如果视频宽或高为0，认为是纯音频文件
            if video_width == 0 or video_height == 0:
                return True
            
            # 额外检查video-codec属性，如果没有视频编解码器也认为是纯音频
            video_codec = self._mpv_handle.get_property_string("video-codec")
            if not video_codec:
                return True
            
            return False
        except Exception:
            return False
    
    def set_window_size(self, width: int, height: int) -> bool:
        """
        设置MPV渲染窗口大小
        用于纯音频播放时将窗口大小设置为0×0
        
        Args:
            width: 窗口宽度
            height: 窗口高度
            
        Returns:
            bool: 设置是否成功
        """
        if not self._initialized or not self._mpv_handle:
            return False
        
        try:
            # 设置geometry属性为0x0，隐藏视频渲染窗口
            result = self._mpv_handle.set_property_string("geometry", f"{width}x{height}")
            return result >= 0
        except Exception:
            return False
    
    def take_screenshot(self, file_path: str, include_subtitles: bool = True) -> bool:
        """
        截取当前帧
        
        Args:
            file_path: 保存路径
            include_subtitles: 是否包含字幕
            
        Returns:
            bool: 操作是否成功
        """
        if not self._initialized or not self._mpv_handle:
            return False
        
        mode = "subtitles" if include_subtitles else "video"
        result = self._mpv_handle.command("screenshot-to-file", file_path, mode)
        return result >= 0
    
    def close(self):
        """关闭播放器并释放资源"""
        if not self._initialized:
            return
        
        self._initialized = False
        self._is_playing = False
        self._is_paused = False
        
        try:
            if hasattr(self, '_position_timer') and self._position_timer:
                self._position_timer.stop()
        except RuntimeError:
            pass
        
        if self._mpv_handle:
            try:
                self._mpv_handle.command("quit")
            except Exception:
                pass
        
        if self._event_thread:
            self._event_thread.stop()
            if self._event_thread.isRunning():
                self._event_thread.wait(2000)
            self._event_thread = None
        
        if self._mpv_handle:
            try:
                self._mpv_handle.terminate_destroy()
            except Exception:
                pass
            self._mpv_handle = None
    
    def __del__(self):
        """析构函数"""
        try:
            self.close()
        except Exception:
            pass
