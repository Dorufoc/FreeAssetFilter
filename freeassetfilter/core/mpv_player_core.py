#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

MPV媒体播放器核心类
基于 python-mpv 实现，提供高性能的媒体播放功能和Cube LUT支持
"""

import os
import platform
import sys
import time
import ctypes
import threading
from ctypes import *
from PyQt5.QtCore import QObject

# Windows 错误模式常量
SEM_FAILCRITICALERRORS = 0x0001
SEM_NOGPFAULTERRORBOX = 0x0002
SEM_NOALIGNMENTFAULTEXCEPT = 0x0004
SEM_NOOPENFILEERRORBOX = 0x8000

# 在 Windows 上抑制崩溃对话框和错误输出
if platform.system() == 'Windows':
    try:
        # 设置 Windows 错误模式，抑制崩溃对话框
        ctypes.windll.kernel32.SetErrorMode(
            SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX
        )
        # 禁用 Windows 错误报告
        ctypes.windll.kernel32.SetThreadErrorMode(
            SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX,
            None
        )
    except:
        pass

# 调试输出控制标志 - 设置为 False 可抑制所有调试输出
MPV_DEBUG_OUTPUT = False

def mpv_print(*args, **kwargs):
    """
    条件打印函数，仅在 MPV_DEBUG_OUTPUT 为 True 时输出
    用于控制 MPV 相关的调试信息输出
    """
    if MPV_DEBUG_OUTPUT:
        print(*args, **kwargs)

# 获取当前文件所在目录（core目录）
core_path = os.path.dirname(os.path.abspath(__file__))

# 将core目录添加到系统PATH中，确保能找到libmpv-2.dll
os.environ['PATH'] = core_path + os.pathsep + os.environ['PATH']

# 加载libmpv-2.dll
_libmpv_path = os.path.join(core_path, "libmpv-2.dll")
mpv_loaded = False
try:
    # 尝试加载libmpv-2.dll
    # print(f"[MPVPlayerCore] 尝试加载libmpv-2.dll，路径: {_libmpv_path}")
    libmpv = CDLL(_libmpv_path)
    # print(f"[MPVPlayerCore] 成功加载libmpv-2.dll")
    mpv_loaded = True
    
    # 定义libmpv数据类型
    mpv_handle = c_void_p
    mpv_event = c_void_p
    mpv_format = c_int
    mpv_error = c_int
    mpv_node = c_void_p
    
    # 定义libmpv事件类型
    MPV_EVENT_NONE = 0
    MPV_EVENT_SHUTDOWN = 1
    MPV_EVENT_LOG_MESSAGE = 2
    MPV_EVENT_GET_PROPERTY_REPLY = 3
    MPV_EVENT_SET_PROPERTY_REPLY = 4
    MPV_EVENT_COMMAND_REPLY = 5
    MPV_EVENT_START_FILE = 6
    MPV_EVENT_END_FILE = 7
    MPV_EVENT_FILE_LOADED = 8
    MPV_EVENT_TRACKS_CHANGED = 9
    MPV_EVENT_VIDEO_RECONFIG = 10
    MPV_EVENT_AUDIO_RECONFIG = 11
    MPV_EVENT_SEEK = 12
    MPV_EVENT_PLAYBACK_RESTART = 13
    MPV_EVENT_PROPERTIES_CHANGED = 14
    MPV_EVENT_PAUSE = 15
    MPV_EVENT_UNPAUSE = 16
    MPV_EVENT_IDLE = 17
    
    # 定义libmpv格式类型
    MPV_FORMAT_NONE = 0
    MPV_FORMAT_STRING = 1
    MPV_FORMAT_OSD_STRING = 2
    MPV_FORMAT_FLAG = 3
    MPV_FORMAT_INT64 = 4
    MPV_FORMAT_DOUBLE = 5
    MPV_FORMAT_NODE = 6
    MPV_FORMAT_NODE_ARRAY = 7
    MPV_FORMAT_NODE_MAP = 8
    
    # 定义libmpv错误类型
    MPV_ERROR_SUCCESS = 0
    MPV_ERROR_NOTHING_TO_DO = 1
    MPV_ERROR_UNKNOWN_FORMAT = 2
    MPV_ERROR_UNSUPPORTED = 3
    MPV_ERROR_INVALID_PARAMETER = 4
    MPV_ERROR_OPTION_NOT_FOUND = 5
    MPV_ERROR_OPTION_FORMAT = 6
    MPV_ERROR_OPTION_ERROR = 7
    MPV_ERROR_PROPERTY_NOT_FOUND = 8
    MPV_ERROR_PROPERTY_FORMAT = 9
    MPV_ERROR_PROPERTY_UNAVAILABLE = 10
    MPV_ERROR_PROPERTY_ERROR = 11
    MPV_ERROR_COMMAND = 12
    MPV_ERROR_LOADING_FAILED = 13
    MPV_ERROR_AO_INIT_FAILED = 14
    MPV_ERROR_VO_INIT_FAILED = 15
    MPV_ERROR_NOTHING_TO_PLAY = 16
    MPV_ERROR_UNKNOWN_ERROR = 17
    MPV_ERROR_EVENT_QUEUE_FULL = 18
    MPV_ERROR_NOMEM = 19
    MPV_ERROR_UNINITIALIZED = 20
    
    # 定义函数原型
    # 创建MPV实例
    libmpv.mpv_create.restype = mpv_handle
    libmpv.mpv_create.argtypes = []
    
    # 初始化MPV实例
    libmpv.mpv_initialize.restype = mpv_error
    libmpv.mpv_initialize.argtypes = [mpv_handle]
    
    # 终止并销毁MPV实例
    libmpv.mpv_terminate_destroy.restype = None
    libmpv.mpv_terminate_destroy.argtypes = [mpv_handle]
    
    # 执行命令
    libmpv.mpv_command.restype = mpv_error
    libmpv.mpv_command.argtypes = [mpv_handle, POINTER(c_char_p)]
    
    # 设置选项字符串
    libmpv.mpv_set_option_string.restype = mpv_error
    libmpv.mpv_set_option_string.argtypes = [mpv_handle, c_char_p, c_char_p]
    
    # 获取属性字符串
    libmpv.mpv_get_property_string.restype = mpv_error
    libmpv.mpv_get_property_string.argtypes = [mpv_handle, c_char_p, POINTER(c_char_p)]
    
    # 设置属性字符串
    libmpv.mpv_set_property_string.restype = mpv_error
    libmpv.mpv_set_property_string.argtypes = [mpv_handle, c_char_p, c_char_p]
    
    # 获取属性（通用类型）
    libmpv.mpv_get_property.restype = mpv_error
    libmpv.mpv_get_property.argtypes = [mpv_handle, c_char_p, mpv_format, c_void_p]
    
    # 设置属性（通用类型）
    libmpv.mpv_set_property.restype = mpv_error
    libmpv.mpv_set_property.argtypes = [mpv_handle, c_char_p, mpv_format, c_void_p]
    
    # 观察属性变化
    libmpv.mpv_observe_property.restype = mpv_error
    libmpv.mpv_observe_property.argtypes = [mpv_handle, c_uint64, c_char_p, mpv_format]
    
    # 取消观察属性
    libmpv.mpv_unobserve_property.restype = mpv_error
    libmpv.mpv_unobserve_property.argtypes = [mpv_handle, c_uint64]
    
    # 等待事件
    libmpv.mpv_wait_event.restype = mpv_event
    libmpv.mpv_wait_event.argtypes = [mpv_handle, c_double]
    
    # 设置唤醒回调
    libmpv.mpv_set_wakeup_callback.restype = None
    libmpv.mpv_set_wakeup_callback.argtypes = [mpv_handle, CFUNCTYPE(None, c_void_p), c_void_p]
    
    # 清除属性字符串内存
    libmpv.mpv_free.restype = None
    libmpv.mpv_free.argtypes = [c_void_p]
    
    # 执行命令节点（用于复杂命令）
    libmpv.mpv_command_node.restype = mpv_error
    libmpv.mpv_command_node.argtypes = [mpv_handle, c_void_p, POINTER(c_void_p)]
    
    # 执行异步命令
    libmpv.mpv_command_async.restype = mpv_error
    libmpv.mpv_command_async.argtypes = [mpv_handle, c_uint64, POINTER(c_char_p)]
    
    # 获取事件属性
    libmpv.mpv_event_name.restype = c_char_p
    libmpv.mpv_event_name.argtypes = [c_int]
    
    # 日志级别
    libmpv.mpv_request_log_messages.restype = mpv_error
    libmpv.mpv_request_log_messages.argtypes = [mpv_handle, c_char_p]
    
except Exception as e:
    print(f"[MPVPlayerCore] 错误: 无法加载libmpv-2.dll - {e}")
    import traceback
    traceback.print_exc()
    mpv_loaded = False


class MPVPlayerCore(QObject):
    """
    MPV媒体播放器核心类
    基于 python-mpv 实现，仅负责视频画面渲染和Cube LUT支持
    """
    
    # 支持的视频和音频格式（与VLC保持一致）
    SUPPORTED_VIDEO_FORMATS = ['.mp4', '.mov', '.m4v', '.flv', '.mxf', '.3gp', 
                              '.mpg', '.avi', '.wmv', '.mkv', '.webm', '.vob', 
                              '.ogv', '.rmvb', '.m2ts', '.ts', '.mts']
    SUPPORTED_AUDIO_FORMATS = ['.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma', 
                              '.m4a', '.aiff', '.ape', '.opus']
    
    def __init__(self):
        """
        初始化MPV播放器核心
        基于 libmpv-2.dll 实现，仅负责视频画面渲染
        """
        super().__init__()
        
        # 媒体对象
        self._media = None
        
        # 播放状态标志
        self._is_playing = False
        
        # 保护标志：防止在设置新媒体时循环播放逻辑干扰
        self._media_changing = False
        
        # 窗口句柄
        self._window_handle = None
        
        # 媒体时长缓存（毫秒）
        self._duration = 0
        
        # 当前播放时间缓存（毫秒）
        self._current_time = 0
        
        # 当前播放位置缓存（0.0 - 1.0）
        self._current_position = 0.0
        
        # Cube滤镜状态
        self._cube_filter_enabled = False
        self._current_cube_path = ""
        self._pending_cube_apply = None  # 用于保存需要在FILE_LOADED事件中应用的LUT设置
        
        # MPV实例
        self._mpv = None
        
        # 线程同步锁，防止MPV实例访问冲突
        self._mpv_lock = threading.RLock()
        
        # 事件处理相关
        self._event_thread = None
        self._event_thread_running = False
        self._property_observers = {}
        self._next_observer_id = 1
        
        # 唤醒回调相关
        self._wakeup_callback = None
        self._wakeup_context = None
        
        # idle事件回调
        self._on_idle_callback = None
        
        # idle事件频率控制相关变量
        self._idle_event_timestamps = []  # 记录idle事件发生的时间戳
        self._idle_event_threshold = 5  # 5秒内允许的最大idle事件数
        self._idle_event_window = 5.0  # 检查窗口（秒）
        self._idle_events_ignored = False  # 是否暂时忽略idle事件
        self._idle_ignore_until = 0.0  # 忽略idle事件直到这个时间戳
        self._idle_event_last_processed = 0.0  # 上次处理idle事件的时间
        
        # 检查MPV库是否加载成功
        if not mpv_loaded:
            print("[MPVPlayerCore] 警告: MPV库未加载成功，播放器功能不可用")
            return
            
        try:
            # print("[MPVPlayerCore] 开始初始化MPV实例...")
            
            # 创建MPV实例
            self._mpv = libmpv.mpv_create()
            if not self._mpv:
                print("[MPVPlayerCore] 错误: 创建MPV实例失败")
                return
            
            # 设置MPV选项
            def set_option(name, value):
                """辅助函数：设置MPV选项"""
                try:
                    result = libmpv.mpv_set_option_string(self._mpv, name.encode('utf-8'), value.encode('utf-8'))
                    if result != MPV_ERROR_SUCCESS:
                        print(f"[MPVPlayerCore] 警告: 设置选项 {name}={value} 失败，错误码: {result}")
                    return result == MPV_ERROR_SUCCESS
                except Exception as e:
                    print(f"[MPVPlayerCore] 错误: 设置选项 {name}={value} 异常 - {e}")
                    return False
            
            # 禁用硬件加速，避免兼容性问题
            set_option('hwdec', 'no')
            
            # 禁用标题栏
            set_option('title', '')
            
            # 禁用MPV的OSD
            set_option('osd-level', '0')
            
            # 禁用MPV的控制面板
            set_option('input-default-bindings', 'no')
            set_option('input-vo-keyboard', 'no')
            
            # 启用音频输出
            set_option('audio', 'auto')
            
            # 设置视频输出模块为gpu-next，确保LUT滤镜正常工作
            set_option('vo', 'gpu-next')
            
            # 视频缩放相关选项，确保视频渲染内容根据容器大小动态调整
            set_option('video-unscaled', 'no')  # 允许视频缩放
            set_option('keepaspect', 'yes')  # 保持视频原始宽高比
            set_option('autofit-larger', '100%')  # 确保视频在窗口放大时在容器内自动调整大小
            set_option('autofit-smaller', '100%')  # 确保视频在窗口缩小时也能正确适应容器大小，避免被裁切
            set_option('correct-downscaling', 'yes')  # 确保视频在缩小时有更好的质量
            set_option('linear-downscaling', 'yes')  # 确保视频在缩小时有更好的质量
            set_option('fit-osd', 'yes')  # 确保OSD（如果启用）也能适应容器大小
            set_option('osd-scale-by-window', 'yes')  # 确保OSD随窗口大小一起缩放
            
            # 启用日志
            set_option('loglevel', 'info')
            
            # 初始化MPV实例
            result = libmpv.mpv_initialize(self._mpv)
            if result != MPV_ERROR_SUCCESS:
                print(f"[MPVPlayerCore] 错误: 初始化MPV实例失败，错误码: {result}")
                libmpv.mpv_terminate_destroy(self._mpv)
                self._mpv = None
                return
            
            # 设置事件回调和状态同步
            self._setup_event_callback()
            
            # print("[MPVPlayerCore] MPV实例初始化成功")
            
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 初始化MPV播放器失败 - {e}")
            import traceback
            traceback.print_exc()
            if self._mpv:
                libmpv.mpv_terminate_destroy(self._mpv)
                self._mpv = None
    
    def _setup_event_callback(self):
        """
        设置MPV事件回调和唤醒机制
        """
        try:
            if not self._mpv:
                return
            
            # 定义唤醒回调函数类型
            wakeup_func_type = CFUNCTYPE(None, c_void_p)
            
            # 定义唤醒回调函数
            def wakeup_callback(ctx):
                """唤醒回调函数，用于处理MPV事件"""
                # print("[MPVPlayerCore] 收到唤醒回调")
                # 这里可以添加事件处理逻辑，或者通过信号通知UI线程
                # 由于线程安全问题，我们使用独立的事件线程来处理事件
            
            # 保存回调函数和上下文，防止被GC回收
            self._wakeup_callback = wakeup_func_type(wakeup_callback)
            self._wakeup_context = None
            
            # 设置唤醒回调
            libmpv.mpv_set_wakeup_callback(self._mpv, self._wakeup_callback, self._wakeup_context)
            # print("[MPVPlayerCore] 已设置唤醒回调")
            
            # 启动事件处理线程
            self._start_event_thread()
            
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 设置事件回调失败 - {e}")
            import traceback
            traceback.print_exc()
    
    def _start_event_thread(self):
        """
        启动事件处理线程，用于处理MPV事件
        """
        try:
            if self._event_thread_running or not self._mpv:
                return
            
            import threading
            self._event_thread_running = True
            self._event_thread = threading.Thread(target=self._event_loop, daemon=True)
            self._event_thread.start()
            # print("[MPVPlayerCore] 事件处理线程已启动")
            
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 启动事件处理线程失败 - {e}")
            import traceback
            traceback.print_exc()
            self._event_thread_running = False
    
    def _event_loop(self):
        """
        事件处理循环，用于处理MPV事件
        """
        try:
            while self._event_thread_running:
                # 使用锁保护MPV实例访问，防止与cleanup方法产生竞争条件
                with self._mpv_lock:
                    if not self._mpv:
                        break
                    # 等待事件，超时100ms，避免阻塞线程
                    event = libmpv.mpv_wait_event(self._mpv, 0.1)
                    
                    # 检查事件指针是否有效
                    if not event:
                        continue
                    
                    # 获取事件类型（事件指针的第一个成员）
                    # 注意：必须在锁内读取事件类型，因为事件指针可能指向MPV内部内存
                    try:
                        event_type = c_int.from_address(event).value
                    except (ValueError, OSError, MemoryError):
                        # 如果读取事件类型失败（例如内存无效），跳过此次循环
                        # 静默处理，避免输出干扰
                        continue
                
                # 1. 事件处理前检查：媒体切换状态过滤
                if self._media_changing:
                    # 只处理关键事件，其他事件暂时忽略
                    # 扩展关键事件列表，确保更多重要事件能够被处理
                    critical_events = [
                        MPV_EVENT_SHUTDOWN,      # 播放器关闭
                        MPV_EVENT_FILE_LOADED,   # 文件加载完成
                        MPV_EVENT_END_FILE,      # 文件播放结束
                        MPV_EVENT_VIDEO_RECONFIG, # 视频重新配置
                        MPV_EVENT_AUDIO_RECONFIG, # 音频重新配置
                        MPV_EVENT_TRACKS_CHANGED, # 音视频轨道变化
                        MPV_EVENT_PLAYBACK_RESTART # 播放重新开始
                    ]
                    
                    if event_type not in critical_events:
                        with self._mpv_lock:
                            event_name = libmpv.mpv_event_name(event_type)
                            event_name_str = event_name.decode('utf-8') if event_name else f"未知事件({event_type})"
                        # print(f"[MPVPlayerCore] 媒体正在切换，忽略非关键事件: {event_name_str}")
                        continue
                
                if event_type == MPV_EVENT_NONE:
                    # 没有事件，继续循环
                    continue
                elif event_type == MPV_EVENT_SHUTDOWN:
                    # 播放器关闭，退出事件循环
                    # print("[MPVPlayerCore] 收到关闭事件，退出事件循环")
                    break
                elif event_type == MPV_EVENT_END_FILE:
                    # 处理播放结束事件
                    # print(f"[MPVPlayerCore] 收到播放结束事件")
                    
                    # 媒体正在切换时，不执行循环播放
                    if self._media_changing:
                        # print(f"[MPVPlayerCore] 媒体正在切换，跳过循环播放逻辑")
                        self._is_playing = False
                        try:
                            self._set_property_bool('pause', True)
                        except Exception as e:
                            print(f"[MPVPlayerCore] 设置暂停状态失败: {e}")
                        continue
                    
                    # 实现循环播放：重新加载当前媒体文件
                    if self._media:
                        # print(f"[MPVPlayerCore] 循环播放：重新加载媒体文件 {self._media}")
                        
                        # 保存当前的播放速度，用于在FILE_LOADED事件中重新应用
                        try:
                            current_speed = self._get_property_double('speed')
                            # print(f"[MPVPlayerCore] 循环播放：保存当前播放速度: {current_speed}x")
                        except Exception as e:
                            current_speed = 1.0
                            # print(f"[MPVPlayerCore] 循环播放：获取当前播放速度失败，使用默认值: {current_speed}x")
                        
                        # 保存当前的LUT设置和播放速度，用于在FILE_LOADED事件中重新应用
                        self._pending_cube_apply = {
                            'enabled': self._cube_filter_enabled,
                            'path': self._current_cube_path,
                            'speed': current_speed
                        }
                        # print(f"[MPVPlayerCore] 循环播放：保存当前LUT设置 - enabled: {self._pending_cube_apply['enabled']}, path: {self._pending_cube_apply['path']}, speed: {self._pending_cube_apply['speed']}x")
                        
                        # 使用replace参数重新加载当前媒体文件
                        # 增加错误处理，确保命令执行成功
                        # 这里增加一个额外的检查，确保在重新加载之前，_media_changing仍然为False
                        if not self._media_changing:
                            load_result = self._execute_command(['loadfile', self._media, 'replace'], timeout=5.0)
                            if not load_result:
                                print(f"[MPVPlayerCore] 循环播放：加载媒体失败")
                                # 设置播放状态为停止，避免死循环
                                self._is_playing = False
                                try:
                                    self._set_property_bool('pause', True)
                                except Exception as e:
                                    print(f"[MPVPlayerCore] 设置暂停状态失败: {e}")
                            else:
                                # 设置播放状态
                                self._is_playing = True
                                
                                # 开始播放 - 在FILE_LOADED事件中处理，这里不立即设置
                                # 这样可以确保媒体完全加载后再开始播放
                                # print(f"[MPVPlayerCore] 循环播放：媒体重新加载成功，将在FILE_LOADED事件中恢复播放")
                                
                                # 清除可能存在的idle事件忽略状态
                                if self._idle_events_ignored:
                                    # print(f"[MPVPlayerCore] 循环播放：清除idle事件忽略状态")
                                    self._idle_events_ignored = False
                                    self._idle_ignore_until = 0.0
                                    self._idle_event_timestamps.clear()
                    else:
                        # 如果没有媒体文件，就正常结束播放
                        self._is_playing = False
                        # 确保pause属性被设置为True
                        try:
                            self._set_property_bool('pause', True)
                        except:
                            # 静默处理错误
                            pass
                        
                elif event_type == MPV_EVENT_FILE_LOADED:
                    # 处理媒体文件加载完成事件
                    # print(f"[MPVPlayerCore] 收到FILE_LOADED事件")
                    
                    # 即使媒体正在改变，也不忽略此事件
                    # 但需要特殊处理，避免与set_media方法冲突
                    is_media_changing = self._media_changing
                    # print(f"[MPVPlayerCore] FILE_LOADED事件：媒体是否正在改变: {is_media_changing}")
                    
                    # 保存LUT设置，但不立即清除，因为可能需要在媒体切换完成后应用
                    pending_lut = self._pending_cube_apply
                    # print(f"[MPVPlayerCore] FILE_LOADED事件：当前待处理LUT设置: {pending_lut}")
                    
                    # 检查是否有需要应用的LUT设置和播放速度
                    if pending_lut and not is_media_changing:
                        # 应用LUT设置
                        if pending_lut['enabled'] and pending_lut['path']:
                            try:
                                self.enable_cube_filter(pending_lut['path'])
                            except:
                                pass
                        
                        # 恢复播放速度 - 使用execute_command代替直接设置，避免底层崩溃
                        if 'speed' in pending_lut:
                            try:
                                # 使用命令方式设置速度，比直接调用API更稳定
                                speed_val = pending_lut['speed']
                                self._execute_command(['set', 'speed', str(speed_val)], timeout=1.0)
                            except:
                                pass
                        
                        # 清除待处理的LUT设置
                        self._pending_cube_apply = None
                    
                    # 媒体加载完成后，检查并恢复播放状态（独立于LUT设置处理）
                    try:
                        # 如果媒体正在改变，不恢复播放状态
                        if not is_media_changing:
                            # 如果是循环播放触发的FILE_LOADED事件，确保继续播放
                            if self._is_playing:
                                #print(f"[MPVPlayerCore] FILE_LOADED事件：媒体加载完成，恢复播放状态")
                                # 使用命令方式设置播放状态，比直接调用API更稳定
                                self._execute_command(['set', 'pause', 'no'], timeout=1.0)
                    except Exception as e:
                        print(f"[MPVPlayerCore] FILE_LOADED事件：恢复播放状态时发生异常 - {e}")
                    
                    # 媒体加载完成后，确保idle事件处理恢复正常
                    if self._idle_events_ignored:
                        # print(f"[MPVPlayerCore] FILE_LOADED事件：媒体加载完成，恢复idle事件处理")
                        self._idle_events_ignored = False
                        self._idle_ignore_until = 0.0
                        self._idle_event_timestamps.clear()
                
                elif event_type == MPV_EVENT_IDLE:
                    # 处理idle事件（播放结束后可能进入此状态）
                    current_time = time.time()
                    
                    # 1. 媒体切换时直接忽略所有IDLE事件
                    if self._media_changing:
                        # print(f"[MPVPlayerCore] 媒体切换中，忽略IDLE事件")
                        continue
                    
                    # 2. 检查是否处于事件忽略期
                    if self._idle_events_ignored and current_time < self._idle_ignore_until:
                        # print(f"[MPVPlayerCore] IDLE事件忽略期内，忽略事件")
                        continue
                    
                    # 3. 恢复处理事件
                    if self._idle_events_ignored:
                        # print(f"[MPVPlayerCore] 恢复处理IDLE事件")
                        self._idle_events_ignored = False
                        self._idle_ignore_until = 0.0
                        self._idle_event_timestamps.clear()
                    
                    # 3. 更新事件时间戳并检查频率
                    self._idle_event_timestamps.append(current_time)
                    # 移除时间窗口外的旧时间戳
                    window_start = current_time - self._idle_event_window
                    self._idle_event_timestamps = [ts for ts in self._idle_event_timestamps if ts >= window_start]
                    
                    # 4. 检测异常事件频率
                    if len(self._idle_event_timestamps) > self._idle_event_threshold:
                        print(f"[ERROR] IDLE事件异常！{self._idle_event_window}秒内检测到{len(self._idle_event_timestamps)}个事件")
                        # 进入事件忽略期
                        self._idle_events_ignored = True
                        self._idle_ignore_until = current_time + 3.0
                        # 清空时间戳列表，避免重复触发
                        self._idle_event_timestamps.clear()
                        continue
                    
                    # 5. 限制处理频率
                    if current_time - self._idle_event_last_processed < 0.5:
                        continue
                    self._idle_event_last_processed = current_time
                    
                    # print(f"[MPVPlayerCore] 处理IDLE事件，时间: {current_time:.3f}")
                    
                    # 6. 执行回调（如果有）
                    if self._on_idle_callback:
                        try:
                            self._on_idle_callback()
                        except Exception as e:
                            print(f"[MPVPlayerCore] IDLE回调执行失败 - {e}")
                            # 对象删除时清除回调
                            if "wrapped C/C++ object of type" in str(e) and "has been deleted" in str(e):
                                self._on_idle_callback = None
                    
                    # 7. 核心状态处理
                    try:
                        current_pause = self._get_property_bool('pause')
                        
                        # 获取播放时间，判断是否刚加载
                        time_pos = 0.0
                        is_recently_started = True
                        try:
                            time_pos = self._get_property_double('playback-time')
                            is_recently_started = time_pos < 0.5
                        except:
                            pass  # 默认视为刚加载
                        
                        # 8. 状态决策
                        if not current_pause:
                            if is_recently_started:
                                # 刚加载时忽略IDLE，保持播放
                                # print(f"[MPVPlayerCore] IDLE: 视频刚加载({time_pos:.2f}s)，保持播放")
                                self._is_playing = True
                                self._set_property_bool('pause', False)
                            else:
                                # 正常播放结束，进入暂停
                                # print(f"[MPVPlayerCore] IDLE: 播放结束，进入暂停")
                                self._is_playing = False
                                self._set_property_bool('pause', True)
                    except Exception as e:
                        print(f"[MPVPlayerCore] IDLE事件处理异常 - {e}")
                        # 异常时确保处于暂停状态
                        try:
                            self._set_property_bool('pause', True)
                            self._is_playing = False
                        except:
                            pass
                else:
                    # 处理其他事件
                    with self._mpv_lock:
                        event_name = libmpv.mpv_event_name(event_type)
                        if event_name:
                            event_name_str = event_name.decode('utf-8')
                            # print(f"[MPVPlayerCore] 收到事件: {event_name_str} (类型: {event_type})")
                    
        except Exception as e:
                print(f"[MPVPlayerCore] 错误: 事件循环异常 - {e}")
                import traceback
                traceback.print_exc()
        finally:
            self._event_thread_running = False
            # print("[MPVPlayerCore] 事件处理线程已退出")
    
    def _stop_event_thread(self):
        """
        停止事件处理线程
        """
        try:
            if not self._event_thread_running:
                # print("[MPVPlayerCore] 事件处理线程已停止")
                return
                
            # print("[MPVPlayerCore] 正在停止事件处理线程...")
            
            # 首先设置停止标志
            self._event_thread_running = False
            
            # 等待线程退出，最多等待2秒
            start_wait_time = time.time()
            thread_terminated = False
            
            while self._event_thread and self._event_thread.is_alive():
                if time.time() - start_wait_time > 2.0:
                    # print("[MPVPlayerCore] 等待超时，强制终止线程")
                    break
                
                # 尝试唤醒 mpv 以便它能检测到停止标志
                try:
                    with self._mpv_lock:
                        if self._mpv:
                            libmpv.mpv_wakeup(self._mpv)
                except:
                    pass
                
                # 短暂休眠
                time.sleep(0.05)
            
            # 如果线程仍在运行，强制终止
            if self._event_thread and self._event_thread.is_alive():
                # print("[MPVPlayerCore] 事件处理线程未能及时退出，强制终止")
                try:
                    # Python 线程不能被强制终止，但我们可以尝试其他方法
                    pass
                except:
                    pass
            
            # 确保线程引用被清除
            self._event_thread = None
            # print("[MPVPlayerCore] 事件处理线程已停止")
            
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 停止事件处理线程失败 - {e}")
            import traceback
            traceback.print_exc()
            self._event_thread_running = False
            self._event_thread = None
    
    def observe_property(self, property_name, property_format):
        """
        观察属性变化
        
        Args:
            property_name (str): 属性名称
            property_format (int): 属性格式，如 MPV_FORMAT_DOUBLE
            
        Returns:
            int: 观察者ID，用于取消观察
        """
        try:
            if not self._mpv:
                return -1
            
            observer_id = self._next_observer_id
            self._next_observer_id += 1
            
            result = libmpv.mpv_observe_property(self._mpv, observer_id, property_name.encode('utf-8'), property_format)
            if result != MPV_ERROR_SUCCESS:
                print(f"[MPVPlayerCore] 错误: 观察属性 {property_name} 失败，错误码: {result}")
                return -1
            
            # print(f"[MPVPlayerCore] 已开始观察属性: {property_name}")
            return observer_id
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 观察属性 {property_name} 异常 - {e}")
            import traceback
            traceback.print_exc()
            return -1
    
    def unobserve_property(self, observer_id):
        """
        取消观察属性
        
        Args:
            observer_id (int): 观察者ID
        """
        try:
            if not self._mpv:
                return
            
            result = libmpv.mpv_unobserve_property(self._mpv, observer_id)
            if result != MPV_ERROR_SUCCESS:
                print(f"[MPVPlayerCore] 错误: 取消观察属性失败，错误码: {result}")
                return
            
            # print(f"[MPVPlayerCore] 已取消观察属性，观察者ID: {observer_id}")
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 取消观察属性异常 - {e}")
            import traceback
            traceback.print_exc()
    
    @property
    def is_playing(self):
        """
        获取当前播放状态
        
        Returns:
            bool: 是否正在播放
        """
        try:
            # 优先从MPV实例获取真实状态
            if self._mpv:
                # 真实状态是暂停状态的反义
                current_pause = self._get_property_bool('pause')
                # 检查MPV是否处于idle状态
                core_idle = self._get_property_bool('core-idle')
                
                # 考虑实际情况：如果pause=False但core处于idle，可能是因为媒体不存在、播放刚结束或加载过程中
                # 只有当pause=False且core不处于idle状态时，才认为是真正在播放
                self._is_playing = (not current_pause) and (not core_idle)
                    
                # print(f"[MPVPlayerCore] 获取播放状态: pause={current_pause}, core-idle={core_idle}, is_playing={self._is_playing}")
        except Exception as e:
            print(f"[MPVPlayerCore] 警告: 获取播放状态失败 - {e}")
            # 失败时使用本地缓存的状态
        return self._is_playing
    
    @property
    def time(self):
        """
        获取当前播放时间（毫秒）
        
        Returns:
            int: 当前播放时间，单位毫秒
        """
        try:
            if self._mpv:
                # MPV返回的是秒，转换为毫秒
                time_pos = self._get_property_double('playback-time')
                return int(time_pos * 1000)
            return 0
        except Exception as e:
            print(f"[MPVPlayerCore] 警告: 获取当前播放时间失败 - {e}")
            return 0
    
    @property
    def duration(self):
        """
        获取媒体总时长（毫秒）
        
        Returns:
            int: 媒体总时长，单位毫秒
        """
        try:
            if not self._mpv:
                return 0
            
            # 优先使用缓存的时长
            if self._duration > 0:
                return self._duration
            
            # 从MPV获取时长（秒转换为毫秒）
            duration = self._get_property_double('duration')
            if duration > 0:
                self._duration = int(duration * 1000)
            return self._duration
        except Exception as e:
            print(f"[MPVPlayerCore] 警告: 获取媒体总时长失败 - {e}")
            return 0
    
    @property
    def position(self):
        """
        获取当前播放位置（0.0 - 1.0）
        
        Returns:
            float: 当前播放位置，范围 0.0 到 1.0
        """
        try:
            if not self._mpv:
                return 0.0
                
            duration = self._get_property_double('duration')
            if duration <= 0:
                return 0.0
                
            time_pos = self._get_property_double('playback-time')
            return time_pos / duration
        except Exception as e:
            print(f"[MPVPlayerCore] 警告: 获取当前播放位置失败 - {e}")
            return 0.0
    
    def set_media(self, file_path):
        """
        设置要播放的媒体文件
        
        Args:
            file_path (str): 媒体文件路径
            
        Returns:
            bool: 设置成功返回 True，否则返回 False
        """
        try:
            # 检查MPV实例是否初始化成功
            if not self._mpv:
                return False
                
            # 设置保护标志，防止在设置新媒体时循环播放逻辑干扰
            self._media_changing = True
            # print(f"[MPVPlayerCore] 开始设置媒体文件: {file_path}")
            
            # 1. 停止所有可能的事件处理
            # 暂停事件处理线程，确保媒体切换期间不会处理任何事件
            old_event_thread_running = self._event_thread_running
            if old_event_thread_running:
                self._stop_event_thread()
                # print(f"[MPVPlayerCore] 已停止事件处理线程")
            
            # 暂时忽略idle事件，防止媒体切换过程中受到干扰
            self._idle_events_ignored = True
            self._idle_ignore_until = time.time() + 5.0  # 进一步延长忽略时间到5秒
            self._idle_event_timestamps.clear()
            self._idle_event_last_processed = 0.0
            
            # 2. 清除待处理的LUT设置，避免新视频继承之前的LUT设置
            self._pending_cube_apply = None
            
            # 3. 保存旧媒体路径
            old_media_path = self._media
            
            # 4. 停止当前播放的媒体，避免新老媒体操作冲突
            # 在调用stop之前，先将_media设置为None，防止stop方法中使用错误的媒体路径
            self._media = None
            
            # 彻底清理当前播放资源
            for cleanup_cmd in [['stop'], ['playlist-clear'], ['osd-clear']]:
                try:
                    self._execute_command(cleanup_cmd, timeout=1.0)
                except Exception as e:
                    # print(f"[MPVPlayerCore] 清理命令 {cleanup_cmd} 执行失败: {e}")
                    # 继续执行其他清理命令，不中断
                    pass
            
            # 5. 重置播放状态
            self._is_playing = False

            # 6. 清除LUT滤镜
            if self._cube_filter_enabled:
                try:
                    self.disable_cube_filter()
                    self._cube_filter_enabled = False
                    self._current_cube_path = ""
                except Exception as e:
                    print(f"[MPVPlayerCore] 清除LUT滤镜失败: {e}")
            
            # 7. 保存媒体路径
            self._media = file_path
            
            # 8. 重置时长缓存
            self._duration = 0
            self._current_time = 0
            self._current_position = 0.0
            
            # 9. 确保MPV核心不处于idle状态
            try:
                # 先检查核心idle状态
                core_idle = self._get_property_bool('core-idle')
                # print(f"[MPVPlayerCore] 设置媒体前，核心idle状态: {core_idle}")
                
                # 处理路径中的中文问题
                processed_path = self.process_chinese_path(file_path)
                
                # 使用loadfile命令加载新媒体，replace参数确保替换当前播放
                # 增加超时时间到5秒，确保媒体有足够时间加载
                load_result = self._execute_command(['loadfile', processed_path, 'replace'], timeout=5.0)
                if not load_result:
                    print(f"[MPVPlayerCore] 加载媒体文件失败: {processed_path}")
                    # 尝试另一种方式加载，不使用replace参数
                    load_result = self._execute_command(['loadfile', processed_path], timeout=5.0)
                
                if load_result:
                    # 立即暂停，确保不会自动开始播放
                    time.sleep(0.2)  # 增加等待时间，确保状态稳定
                    self._set_property_bool('pause', True)
                    # print(f"[MPVPlayerCore] 媒体文件加载成功，已暂停")
                else:
                    print(f"[MPVPlayerCore] 尝试多种方式加载媒体文件均失败")
                    
            except Exception as e:
                print(f"[MPVPlayerCore] 预加载媒体失败 - {e}")
                import traceback
                traceback.print_exc()
                
                # 即使预加载失败，也要尝试恢复状态
                try:
                    self._set_property_bool('pause', True)
                    self._is_playing = False
                except:
                    pass
            
            # 10. 恢复事件处理线程
            if old_event_thread_running:
                # 直接启动新的事件处理线程
                self._start_event_thread()
                # print(f"[MPVPlayerCore] 已重新启动事件处理线程")
                
                # 等待事件处理线程真正开始运行（最多等待1秒）
                wait_time = 0
                while wait_time < 1.0 and self._event_thread and self._event_thread.is_alive():
                    time.sleep(0.1)
                    wait_time += 0.1
                    if wait_time >= 0.5:
                        # 0.5秒后仍未恢复，强制重新启动事件线程
                        # print(f"[MPVPlayerCore] 事件处理线程启动超时，强制重新启动")
                        self._start_event_thread()
                        break
            
            # 11. 恢复idle事件处理，但保持一定的缓冲时间
            self._idle_ignore_until = time.time() + 2.0  # 增加缓冲时间到2秒，确保更稳定的状态
            
            # 12. 清除保护标志
            self._media_changing = False
            # print(f"[MPVPlayerCore] 媒体文件设置完成: {file_path}")
            
            return True
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 设置媒体失败 - {e}")
            import traceback
            traceback.print_exc()
            
            # 确保在异常情况下也能正确重置状态
            try:
                self._media_changing = False
                self._media = None
                self._idle_events_ignored = False
                self._idle_ignore_until = 0.0
                self._idle_event_timestamps.clear()
                self._pending_cube_apply = None
                self._is_playing = False
                
                # 恢复事件处理线程
                self._event_thread_running = True
                if not self._event_thread or not self._event_thread.is_alive():
                    self._start_event_thread()
                
                # 尝试停止播放并清理资源
                if self._mpv:
                    for cleanup_cmd in [['stop'], ['playlist-clear'], ['osd-clear']]:
                        try:
                            self._execute_command(cleanup_cmd, timeout=1.0)
                        except:
                            pass
                    self._set_property_bool('pause', True)
                    
                    # 清除LUT滤镜
                    if self._cube_filter_enabled:
                        try:
                            self.disable_cube_filter()
                            self._cube_filter_enabled = False
                            self._current_cube_path = ""
                        except:
                            pass
            except:
                pass
                
            return False
    
    def load_media(self, file_path):
        """
        加载媒体文件（兼容FFPlayerCore接口）
        
        Args:
            file_path (str): 媒体文件路径
            
        Returns:
            bool: 加载成功返回 True，否则返回 False
        """
        return self.set_media(file_path)
    
    def _execute_command(self, command_list, timeout=2.0):
        """
        执行MPV命令，带有超时处理机制和状态保护

        Args:
            command_list (list): 命令列表，如 ['loadfile', 'path/to/file.mp4', 'replace']
            timeout (float): 超时时间（秒）

        Returns:
            bool: 执行成功返回 True，否则返回 False
        """
        import threading
        import time
        
        # 命令执行结果
        result_value = None
        exception_occurred = None
        command_start_time = time.time()
        
        # 检查MPV实例是否存在
        if not self._mpv:
            print(f"[MPVPlayerCore] 错误: MPV实例不存在，无法执行命令: {command_list}")
            return False
        
        # 检查命令是否需要在媒体切换期间执行
        is_media_change_related = any(cmd in ['stop', 'playlist-clear', 'osd-clear', 'loadfile'] 
                                    for cmd in command_list if isinstance(cmd, str))
        
        # 如果不是媒体切换相关命令，且正在切换媒体，则根据命令类型决定是否执行
        if not is_media_change_related and self._media_changing:
            command_name = command_list[0] if command_list else ""
            
            # 允许执行的命令类型列表
            allowed_commands = [
                # 查询类命令
                'get_property', 'get_time_pos', 'get_duration',
                # 状态查询命令
                'get_pause', 'get_playback_time', 'get_position',
                # 显示控制命令
                'set_property', 'set_pause',
                # 音量控制命令
                'set_volume', 'get_volume',
                # 视频控制命令
                'seek', 'set_position'
            ]
            
            if command_name in allowed_commands:
                # 允许执行的命令
                # print(f"[MPVPlayerCore] 媒体正在切换，但允许执行命令: {command_list}")
                pass
            else:
                # 非关键命令延迟执行
                print(f"[MPVPlayerCore] 警告: 正在切换媒体，跳过非关键命令: {command_list}")
                return False
        
        def _execute_command_thread():
            """在子线程中执行命令"""
            nonlocal result_value, exception_occurred
            thread_start_time = time.time()
            
            try:
                # 再次检查MPV实例和状态，确保线程执行时状态仍然有效
                if not self._mpv:
                    result_value = False
                    return
                
                if self._media_changing and not is_media_change_related:
                    result_value = False
                    return
                
                # 转换命令列表为ctypes所需的格式
                command_array = (c_char_p * (len(command_list) + 1))()
                for i, cmd in enumerate(command_list):
                    if isinstance(cmd, str):
                        command_array[i] = cmd.encode('utf-8')
                    else:
                        command_array[i] = str(cmd).encode('utf-8')
                command_array[len(command_list)] = None
                
                # 执行命令 - 添加额外的异常保护
                try:
                    result = libmpv.mpv_command(self._mpv, command_array)
                    if result != MPV_ERROR_SUCCESS:
                        # 仅在主线程中打印错误，避免事件循环中的输出干扰
                        if threading.current_thread() == threading.main_thread():
                            print(f"[MPVPlayerCore] 错误: 执行命令 {command_list} 失败，错误码: {result}")
                        result_value = False
                    else:
                        result_value = True
                        # print(f"[MPVPlayerCore] 命令执行成功: {command_list}")
                except ctypes.ArgumentError as e:
                    if threading.current_thread() == threading.main_thread():
                        print(f"[MPVPlayerCore] 参数错误: 执行命令 {command_list} 失败 - {e}")
                    result_value = False
                except ctypes.AccessViolationError as e:
                    # 访问违规错误静默处理，避免输出干扰
                    result_value = False
                except Exception as e:
                    # 其他未预期的异常，静默处理
                    result_value = False
                    
            except Exception as e:
                exception_occurred = e
                result_value = False
                # 仅在主线程中打印异常
                if threading.current_thread() == threading.main_thread():
                    print(f"[MPVPlayerCore] 命令执行线程异常: {e}")
            finally:
                elapsed = time.time() - thread_start_time
                if elapsed > timeout * 0.5:
                    # print(f"[MPVPlayerCore] 警告: 命令 {command_list} 执行时间较长 ({elapsed:.2f}秒)")
                    pass
        
        # 创建并启动线程
        thread = threading.Thread(target=_execute_command_thread, daemon=True)
        thread.start()
        
        # 等待线程完成或超时
        thread.join(timeout)
        
        # 计算总执行时间
        total_elapsed = time.time() - command_start_time
        
        if thread.is_alive():
            # 线程超时 - 这里我们无法强制终止线程，但可以记录警告
            # 仅在主线程中打印超时警告
            if threading.current_thread() == threading.main_thread():
                print(f"[MPVPlayerCore] 错误: 执行命令 {command_list} 超时（{total_elapsed:.2f}秒 > {timeout}秒）")
            # 尝试唤醒MPV事件循环，可能有助于命令线程结束
            try:
                libmpv.mpv_wakeup(self._mpv)
            except:
                pass
            return False
        
        if exception_occurred:
            # 线程执行时发生异常，静默处理
            return False
        
        if result_value is None:
            # 这是一个不应该发生的情况
            return False
        
        return result_value
    
    def play(self):
        """
        开始播放媒体

        Returns:
            bool: 播放成功返回 True，否则返回 False
        """
        # print(f"[MPVPlayerCore] 调用play()方法，_media={self._media}")
        
        try:
            # 检查MPV实例是否初始化成功
            if not self._mpv or not self._media:
                print(f"[MPVPlayerCore] 播放失败: MPV实例未初始化或媒体未设置")
                return False
            
            # 检查媒体是否正在改变
            if self._media_changing:
                print(f"[MPVPlayerCore] 播放失败: 媒体正在切换中")
                return False
                
            # 检查当前播放状态
            current_pause = self._get_property_bool('pause')
            # print(f"[MPVPlayerCore] 播放前状态: pause={current_pause}, is_playing={self._is_playing}")
            
            # 如果已经在播放，不要重新开始
            if not current_pause and self._is_playing:
                # print(f"[MPVPlayerCore] 已经在播放，不需要重新开始")
                return True
            
            # 初始化播放结束标志
            is_ended = False
            
            # 如果是暂停状态，检查是否已经播放结束
            if current_pause:
                # 检查多种播放结束的情况
                
                try:
                    # 情况1: 当前时间接近总时长
                    time_pos = self._get_property_double('playback-time')
                    time_duration = self._get_property_double('duration')
                    
                    if time_duration > 0 and time_pos >= time_duration - 0.5:
                        is_ended = True
                        # print(f"[MPVPlayerCore] 视频已播放结束（播放时间接近总时长）")
                except Exception as e:
                    print(f"[MPVPlayerCore] 获取播放状态失败: {e}")
                    
                try:
                    # 情况2: MPV处于idle状态且媒体已经播放完毕
                    core_idle = self._get_property_bool('core-idle')
                    # 只有当core-idle为True且当前时间确实接近结束时，才认为是播放结束
                    if core_idle:
                        try:
                            time_pos = self._get_property_double('playback-time')
                            time_duration = self._get_property_double('duration')
                            if time_duration > 0 and time_pos >= time_duration - 1.0:
                                is_ended = True
                                # print(f"[MPVPlayerCore] 视频已播放结束（core-idle=True且播放时间接近总时长）")
                        except:
                            # 如果无法获取时间信息，就不认为是播放结束
                            # print(f"[MPVPlayerCore] 无法获取时间信息，不认为是播放结束")
                            pass
                except Exception as e:
                    print(f"[MPVPlayerCore] 获取core-idle状态失败: {e}")
            
            if is_ended:
                # print(f"[MPVPlayerCore] 重置播放位置并重新开始播放")
                
                # 当播放结束时，MPV可能已进入idle状态，媒体可能已被卸载
                # 因此直接重新加载媒体而不是尝试seek
                retry_count = 0
                max_retries = 2
                success = False
                
                while retry_count < max_retries and not success:
                    try:
                        retry_count += 1
                        print(f"[MPVPlayerCore] 第{retry_count}次尝试重新加载媒体: {self._media}")
                        
                        # 先尝试简单的seek到开头，如果成功就不需要重新加载
                        # print(f"[MPVPlayerCore] 尝试seek到开头...")
                        seek_result = self._execute_command(['seek', '0', 'absolute'])
                        
                        if seek_result:
                            # seek成功，尝试开始播放
                            self._set_property_bool('pause', False)
                            
                            # 检查是否真的开始播放
                            time.sleep(0.1)  # 减少等待时间，给MPV更少但足够的响应时间
                            current_pause = self._get_property_bool('pause')
                            if not current_pause:
                                self._is_playing = True
                                # print(f"[MPVPlayerCore] seek并播放成功，状态: pause={current_pause}, is_playing={self._is_playing}")
                                success = True
                                return True
                            else:
                                # print(f"[MPVPlayerCore] seek成功但播放未开始，pause仍为True，尝试重新加载媒体")
                                pass
                        else:
                            print(f"[MPVPlayerCore] seek失败，尝试重新加载媒体")
                        
                        # seek失败或播放未开始，尝试重新加载媒体
                        processed_path = self.process_chinese_path(self._media)
                        # 使用loadfile命令重新加载媒体，replace参数确保替换当前播放
                        load_result = self._execute_command(['loadfile', processed_path, 'replace'])
                        
                        if load_result:
                            # 显式设置pause=False以确保播放开始
                            time.sleep(0.3)  # 增加等待时间，确保媒体加载完成
                            
                            # 多次尝试设置pause=False，提高成功率
                            play_attempts = 0
                            while play_attempts < 3:
                                play_attempts += 1
                                self._set_property_bool('pause', False)
                                current_pause = self._get_property_bool('pause')
                                
                                if not current_pause:
                                    break
                                time.sleep(0.1)  # 每次尝试间隔100ms
                            
                            # 强制更新状态
                            self._is_playing = not current_pause
                            
                            if not current_pause:
                                # print(f"[MPVPlayerCore] 媒体重新加载并播放成功，状态: pause={current_pause}, is_playing={self._is_playing}")
                                success = True
                            else:
                                # print(f"[MPVPlayerCore] 媒体重新加载成功但播放未开始，pause仍为True")
                                pass
                        else:
                            print(f"[MPVPlayerCore] 媒体重新加载失败")
                            
                    except Exception as e:
                        print(f"[MPVPlayerCore] 重新播放尝试失败: {e}")
                        import traceback
                        traceback.print_exc()
                    
                    if not success and retry_count < max_retries:
                        # print(f"[MPVPlayerCore] 重试重新播放...")
                        time.sleep(0.3)  # 减少重试间隔到300ms
                
                # 所有尝试都失败
                if not success:
                    print(f"[MPVPlayerCore] 所有重新播放尝试都失败")
                    return False
                
                return success
            elif current_pause:
                # print(f"[MPVPlayerCore] 从暂停状态恢复播放")
                self._set_property_bool('pause', False)
                self._is_playing = True
                return True
            else:
                # 开始播放新媒体
                # print(f"[MPVPlayerCore] 开始播放媒体: {self._media}")
                # 处理媒体路径
                processed_path = self.process_chinese_path(self._media)
                # 使用loadfile命令播放媒体
                result = self._execute_command(['loadfile', processed_path, 'replace'])
                if result:
                    # 显式设置pause=False以确保播放开始
                    time.sleep(0.3)  # 增加等待时间，确保媒体加载完成
                    
                    # 多次尝试设置pause=False，提高成功率
                    play_attempts = 0
                    while play_attempts < 3:
                        play_attempts += 1
                        self._set_property_bool('pause', False)
                        current_pause = self._get_property_bool('pause')
                        
                        if not current_pause:
                            break
                        time.sleep(0.1)  # 每次尝试间隔100ms
                    
                    # 更新播放状态
                    self._is_playing = not current_pause
                    
                    if not current_pause:
                        # print(f"[MPVPlayerCore] 媒体播放成功，状态: pause={current_pause}, is_playing={self._is_playing}")
                        pass
                    else:
                        # print(f"[MPVPlayerCore] 媒体加载成功但播放未开始，pause仍为True")
                        pass
                else:
                    self._is_playing = False
                    print(f"[MPVPlayerCore] 媒体播放失败")
                return result
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 播放媒体失败 - {e}")
            import traceback
            traceback.print_exc()
            self._is_playing = False
            return False
    
    def pause(self):
        """
        暂停播放媒体
        """
        try:
            # 检查MPV实例是否初始化成功
            if not self._mpv:
                return
                
            # 直接设置为暂停状态，而不是切换
            self._set_property_bool('pause', True)
            # 更新播放状态
            self._is_playing = False
            # print(f"[MPVPlayerCore] 暂停播放")
        except Exception as e:
            print(f"[MPVPlayerCore] 警告: 暂停播放失败 - {e}")
            # 确保播放状态至少在本地是一致的
            self._is_playing = False
    
    def stop(self):
        """
        停止播放媒体
        """
        try:
            # 检查MPV实例是否初始化成功
            if not self._mpv:
                self._is_playing = False
                return
                
            # 如果当前处于暂停状态，先恢复播放再停止
            # 这可以避免在暂停状态下直接停止导致的阻塞问题
            try:
                current_pause = self._get_property_bool('pause')
                if current_pause:
                    # 先恢复播放，等待一小段时间确保状态稳定
                    self._set_property_bool('pause', False)
                    time.sleep(0.1)  # 短暂等待，确保状态稳定
            except Exception as e:
                print(f"[MPVPlayerCore] 检查暂停状态失败 - {e}")
                # 即使检查失败，仍继续尝试停止播放
            
            # 使用stop命令停止播放
            self._execute_command(['stop'])
            # 停止播放后，媒体会被卸载，只需要设置本地状态即可
            self._is_playing = False
            # print("[MPVPlayerCore] 播放已停止")
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 停止播放失败 - {e}")
            self._is_playing = False
    
    def set_position(self, position):
        """
        设置播放位置
        
        Args:
            position (float): 播放位置，范围 0.0 到 1.0
        """
        try:
            # 检查MPV实例是否初始化成功
            if not self._mpv:
                return
                
            # 确保位置在有效范围内
            position = max(0.0, min(1.0, position))
            
            # 计算精确的百分比位置
            percent = position * 100
            
            # 使用最精确的seek命令，确保位置准确
            # 'exact'参数确保精确跳转，避免帧对齐问题
            self._execute_command(['seek', str(percent), 'absolute-percent', 'exact'])
            
            # 减少等待时间，避免两个播放器之间的操作延迟
            time.sleep(0.01)
            
        except Exception as e:
            print(f"[MPVPlayerCore] 警告: 设置播放位置失败 - {e}")
            # 保留原位置，不做任何改变
    
    def _get_property_bool(self, property_name):
        """
        获取布尔类型属性
        
        Args:
            property_name (str): 属性名称
            
        Returns:
            bool: 属性值
        """
        try:
            if not self._mpv:
                return False
            
            value = c_int()
            result = libmpv.mpv_get_property(self._mpv, property_name.encode('utf-8'), MPV_FORMAT_FLAG, byref(value))
            if result != MPV_ERROR_SUCCESS:
                # print(f"[MPVPlayerCore] 警告: 获取属性 {property_name} 失败，错误码: {result}")
                return False
            
            return bool(value.value)
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 获取属性 {property_name} 异常 - {e}")
            return False
    
    def _set_property_bool(self, property_name, value):
        """
        设置布尔类型属性
        
        Args:
            property_name (str): 属性名称
            value (bool): 属性值
            
        Returns:
            bool: 设置成功返回 True，否则返回 False
        """
        try:
            if not self._mpv:
                return False
            
            value_int = c_int(1 if value else 0)
            result = libmpv.mpv_set_property(self._mpv, property_name.encode('utf-8'), MPV_FORMAT_FLAG, byref(value_int))
            if result != MPV_ERROR_SUCCESS:
                print(f"[MPVPlayerCore] 警告: 设置属性 {property_name} 失败，错误码: {result}")
                return False
            
            return True
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 设置属性 {property_name} 异常 - {e}")
            return False
    
    def _get_property_double(self, property_name):
        """
        获取double类型属性
        
        Args:
            property_name (str): 属性名称
            
        Returns:
            float: 属性值
        """
        try:
            if not self._mpv:
                return 0.0
            
            value = c_double()
            result = libmpv.mpv_get_property(self._mpv, property_name.encode('utf-8'), MPV_FORMAT_DOUBLE, byref(value))
            if result != MPV_ERROR_SUCCESS:
                # print(f"[MPVPlayerCore] 警告: 获取属性 {property_name} 失败，错误码: {result}")
                return 0.0
            
            return float(value.value)
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 获取属性 {property_name} 异常 - {e}")
            return 0.0
    
    def _set_property_double(self, property_name, value):
        """
        设置双精度浮点属性
        注意：此方法在事件循环中调用可能导致崩溃，建议在事件循环外使用
        """
        try:
            if not self._mpv:
                return False

            with self._mpv_lock:
                # 检查MPV实例是否仍然有效
                if not self._mpv:
                    return False
                value_double = c_double(value)
                result = libmpv.mpv_set_property(self._mpv, property_name.encode('utf-8'), MPV_FORMAT_DOUBLE, byref(value_double))
                if result != MPV_ERROR_SUCCESS:
                    # 仅在非事件循环线程中打印警告，避免输出干扰
                    if threading.current_thread() == threading.main_thread():
                        print(f"[MPVPlayerCore] 警告: 设置属性 {property_name} 失败，错误码: {result}")
                    return False

            return True
        except Exception as e:
            # 仅在主线程中打印错误，避免事件循环中的异常输出
            if threading.current_thread() == threading.main_thread():
                print(f"[MPVPlayerCore] 错误: 设置属性 {property_name} 异常 - {e}")
            return False
    
    def _set_property_string(self, property_name, value):
        try:
            if not self._mpv:
                return False

            with self._mpv_lock:
                result = libmpv.mpv_set_property_string(self._mpv, property_name.encode('utf-8'), value.encode('utf-8'))
                if result != MPV_ERROR_SUCCESS:
                    print(f"[MPVPlayerCore] 警告: 设置属性 {property_name} 失败，错误码: {result}")
                    return False

            return True
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 设置属性 {property_name} 异常 - {e}")
            return False

    def _get_property_string(self, property_name):
        try:
            if not self._mpv:
                return ""

            with self._mpv_lock:
                value_ptr = c_char_p()
                result = libmpv.mpv_get_property_string(self._mpv, property_name.encode('utf-8'), byref(value_ptr))
                if result != MPV_ERROR_SUCCESS:
                    return ""

                if not value_ptr or not value_ptr.value:
                    return ""

                value = value_ptr.value.decode('utf-8')
                libmpv.mpv_free(value_ptr)
                return value
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 获取属性 {property_name} 异常 - {e}")
            return ""
    
    def set_speed(self, speed):
        """
        设置播放速度
        
        Args:
            speed (float): 播放速度，范围 0.1 到 10.0
        """
        try:
            # 检查MPV实例是否初始化成功
            if not self._mpv:
                return
                
            # 确保速度在有效范围内
            speed = max(0.1, min(10.0, speed))
            self._set_property_double('speed', speed)
            # print(f"[MPVPlayerCore] 播放速度已设置为: {speed}x")
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 设置播放速度失败 - {e}")
    
    def set_volume(self, volume):
        """
        设置音量
        
        Args:
            volume (int): 音量值，范围 0 到 100
        """
        try:
            # 检查MPV实例是否初始化成功
            if not self._mpv:
                return
                
            # 确保音量在有效范围内
            volume = max(0, min(100, volume))
            self._set_property_double('volume', float(volume))
            # print(f"[MPVPlayerCore] 音量已设置为: {volume}%")
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 设置音量失败 - {e}")
    
    def set_window(self, window_id):
        """
        将媒体播放器绑定到指定窗口
        
        Args:
            window_id: 窗口句柄，根据平台不同类型可能不同
        """
        try:
            # 检查MPV实例是否初始化成功
            if not self._mpv:
                print("[MPVPlayerCore] 警告: MPV实例未初始化，无法绑定窗口")
                return
                
            # print(f"[MPVPlayerCore] 尝试绑定窗口，窗口ID: {window_id}")
            
            # 保存窗口句柄
            self._window_handle = window_id
            
            # 将窗口句柄转换为整数，处理sip.voidptr对象
            if hasattr(window_id, 'value'):
                # 处理sip.voidptr对象
                window_id = window_id.value
                # print(f"[MPVPlayerCore] 转换窗口ID为: {window_id}")
            elif not isinstance(window_id, int):
                # 尝试转换为整数
                window_id = int(window_id)
                # print(f"[MPVPlayerCore] 转换窗口ID为: {window_id}")
            
            # 设置MPV的渲染窗口
            # 使用mpv_set_option_string设置wid选项
            result = libmpv.mpv_set_option_string(self._mpv, b"wid", str(window_id).encode('utf-8'))
            if result != MPV_ERROR_SUCCESS:
                print(f"[MPVPlayerCore] 错误: 设置窗口失败，错误码: {result}")
                return
            
            # print("[MPVPlayerCore] 窗口绑定成功")
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 设置窗口失败 - {e}")
            import traceback
            traceback.print_exc()
    
    def set_on_idle_callback(self, callback):
        """
        设置idle事件的回调函数
        
        Args:
            callback: idle事件的回调函数
        """
        self._on_idle_callback = callback

    def clear_window(self):
        """
        清除媒体播放器与窗口的绑定
        """
        try:
            # 检查MPV实例是否初始化成功
            if not self._mpv:
                self._window_handle = None
                return
            
            # 尝试清除MPV的渲染窗口
            # 注意：如果 mpv 处于不稳定状态，这个调用可能会失败或崩溃
            # 使用 try-except 保护，但即使失败也不影响程序运行
            try:
                result = libmpv.mpv_set_option_string(self._mpv, b"wid", b"0")
                if result != MPV_ERROR_SUCCESS:
                    print(f"[MPVPlayerCore] 错误: 清除窗口绑定失败，错误码: {result}")
            except Exception as e:
                # 忽略 mpv API 调用失败，继续清理
                # print(f"[MPVPlayerCore] 警告: 清除窗口绑定时出错（可忽略）: {e}")
                pass
            
            # 清除窗口句柄
            self._window_handle = None
            # print("[MPVPlayerCore] 窗口绑定已清除")
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 清除窗口绑定失败 - {e}")
            import traceback
            traceback.print_exc()
            self._window_handle = None
    
    def cleanup(self):
        """
        清理资源，释放 MPV 实例
        
        注意：由于 libmpv 库在多线程环境下可能不稳定，
        我们采用特殊的清理顺序来避免崩溃：
        1. 先设置停止标志并等待线程退出
        2. 清除所有回调函数
        3. 最后才清理 mpv 实例
        """
        # print("[MPVPlayerCore] 开始清理资源...")
        
        # 检查是否已经在清理过程中，防止重复清理
        if hasattr(self, '_cleanup_in_progress') and self._cleanup_in_progress:
            # print("[MPVPlayerCore] 清理已在进行中，跳过")
            return
        
        self._cleanup_in_progress = True
        
        try:
            # 第一步：先停止事件线程（在停止播放之前）
            # 这样可以防止事件循环在清理过程中执行新命令
            # print("[MPVPlayerCore] 步骤1: 停止事件处理线程...")
            self._event_thread_running = False
            
            # 等待事件循环检测到停止标志并退出
            max_wait = 1.0  # 最多等待1秒
            start_time = time.time()
            while self._event_thread and self._event_thread.is_alive():
                if time.time() - start_time > max_wait:
                    # print("[MPVPlayerCore] 等待事件线程超时，强制继续")
                    break
                time.sleep(0.05)
            
            # 确保线程引用被清除
            self._event_thread = None
            # print("[MPVPlayerCore] 事件线程已停止")
            
            # 第二步：清除所有回调函数
            # print("[MPVPlayerCore] 步骤2: 清除回调函数...")
            self._on_idle_callback = None
            self._wakeup_callback = None
            
            # 第三步：停止播放（现在事件线程已停止，不会产生竞态）
            # print("[MPVPlayerCore] 步骤3: 停止播放...")
            try:
                if self._mpv:
                    # 使用try-except捕获所有异常，包括Windows致命异常
                    libmpv.mpv_command_string(self._mpv, b"stop")
                    time.sleep(0.05)
            except:
                pass
            
            # 第四步：清除窗口绑定
            # print("[MPVPlayerCore] 步骤4: 清除窗口绑定...")
            try:
                if self._mpv:
                    libmpv.mpv_set_option_string(self._mpv, b"wid", b"0")
            except:
                pass
            self._window_handle = None
            
            # 第五步：终止并销毁 mpv 实例
            # print("[MPVPlayerCore] 步骤5: 终止并销毁 mpv 实例...")
            mpv_instance = None
            try:
                if self._mpv:
                    # 保存实例指针到局部变量，避免在销毁过程中被其他线程访问
                    mpv_instance = self._mpv
                    # 先清空self._mpv，防止其他操作访问到即将销毁的实例
                    with self._mpv_lock:
                        self._mpv = None
            except:
                pass
            
            # 在锁外调用mpv_terminate_destroy，避免死锁
            # 使用延迟确保之前的操作已完成
            if mpv_instance:
                try:
                    # 短暂延迟，确保之前的操作（如stop命令）已完成
                    time.sleep(0.1)
                    # 调用mpv_terminate_destroy正确销毁MPV实例，释放dll资源
                    libmpv.mpv_terminate_destroy(mpv_instance)
                    # print("[MPVPlayerCore] MPV实例已正确销毁")
                except:
                    # 忽略所有销毁错误，包括Windows致命异常
                    pass
            
            # print("[MPVPlayerCore] 资源清理完成")
        except:
            # 忽略清理过程中的所有异常，包括Windows致命异常
            pass
        finally:
            self._cleanup_in_progress = False
    

    
    def process_chinese_path(self, raw_path: str) -> str:
        """
        处理带中文/空格的路径：
        1. 确保路径使用正斜杠，避免MPV解析问题
        2. 确保路径编码正确，避免中文乱码问题
        3. 处理包含空格的路径，为vf系统的滤镜参数添加引号
        
        Args:
            raw_path (str): 原始路径
            
        Returns:
            str: 处理后的路径，适合传递给libmpv
        """
        # 步骤1：确保路径使用正斜杠，避免MPV解析问题
        normalized_path = raw_path.replace('\\', '/')
        
        return normalized_path
    
    def _encode_path(self, path: str) -> bytes:
        """
        编码路径为UTF-8字节流，确保中文和空格能被正确处理
        
        Args:
            path (str): 原始路径
            
        Returns:
            bytes: UTF-8编码的路径字节流
        """
        # 确保路径使用正斜杠
        normalized_path = path.replace('\\', '/')
        # 编码为UTF-8字节流
        return normalized_path.encode('utf-8')

    def enable_cube_filter(self, cube_path):
        """
        启用Cube色彩映射滤镜
        
        Args:
            cube_path (str): Cube文件的绝对路径
        """
        try:
            if not self._mpv or not cube_path:
                print(f"[MPVPlayerCore] 警告: MPV实例未初始化或Cube路径为空")
                return False
            
            # 检查文件是否存在
            if not os.path.exists(cube_path):
                print(f"[MPVPlayerCore] 错误: Cube文件不存在: {cube_path}")
                return False
            
            # 如果已经启用了相同的Cube滤镜，直接返回
            if self._cube_filter_enabled and self._current_cube_path == cube_path:
                # print(f"[MPVPlayerCore] 已启用相同的Cube滤镜，无需重复添加")
                return True
            
            # 先清除所有现有的Cube滤镜，避免重复添加
            self.disable_cube_filter()
            
            # 更新标志位和当前Cube路径
            self._cube_filter_enabled = True
            self._current_cube_path = cube_path
            
            # print(f"[MPVPlayerCore] 尝试启用Cube滤镜，文件路径: {cube_path}")
            
            # 处理Cube路径（中文/空格）
            processed_cube_path = self.process_chinese_path(cube_path)
            
            # 尝试使用vf add命令添加lut3d滤镜（通用方法）
            try:
                # print(f"[MPVPlayerCore] 尝试使用vf add命令添加lut3d滤镜")
                # 确保路径格式正确，处理中文和空格
                normalized_path = processed_cube_path
                # 使用绝对路径，确保能找到文件
                # 为包含空格的路径添加单引号，避免MPV解析错误
                if ' ' in normalized_path:
                    filter_arg = f"lut3d=file='{normalized_path}'"
                else:
                    filter_arg = f'lut3d=file={normalized_path}'
                # print(f"[MPVPlayerCore] 尝试添加滤镜: {filter_arg}")
                
                if self._execute_command(['vf', 'add', filter_arg]):
                    # print(f"[MPVPlayerCore] 成功使用vf add命令添加lut3d滤镜")
                    return True
                else:
                    print(f"[MPVPlayerCore] vf add命令失败")
            except Exception as e:
                print(f"[MPVPlayerCore] vf add命令异常: {e}")
                import traceback
                traceback.print_exc()
            
            # 尝试使用load glsl-shaders命令（适用于vo=gpu-next）
            try:
                # print(f"[MPVPlayerCore] 尝试使用load glsl-shaders命令")
                # 执行load glsl-shaders命令
                if self._execute_command(['load', 'glsl-shaders', processed_cube_path]):
                    # print(f"[MPVPlayerCore] 成功使用load glsl-shaders命令加载滤镜")
                    return True
                else:
                    print(f"[MPVPlayerCore] load glsl-shaders命令失败")
            except Exception as e:
                print(f"[MPVPlayerCore] load glsl-shaders命令异常: {e}")
                import traceback
                traceback.print_exc()
            
            # 尝试使用glsl-shaders选项（替换模式，避免重复添加）
            try:
                # print(f"[MPVPlayerCore] 尝试使用glsl-shaders选项（替换模式）")
                
                # glsl-shaders属性需要的是一个shader列表，格式为["shader1", "shader2", ...]
                # 对于单个shader，需要格式化为["path/to/shader"]
                shader_list = f'["{processed_cube_path}"]'
                
                # 使用_execute_command执行glsl-shaders选项命令
                # 使用set_property命令替代直接调用libmpv函数，以获得超时保护
                if self._execute_command(['set', 'glsl-shaders', shader_list]):
                    # print(f"[MPVPlayerCore] 成功使用glsl-shaders选项加载滤镜")
                    return True
                else:
                    print(f"[MPVPlayerCore] glsl-shaders选项失败")
            except Exception as e:
                print(f"[MPVPlayerCore] glsl-shaders选项异常: {e}")
                import traceback
                traceback.print_exc()
            
            # 尝试使用set_property_double方法设置glsl-shaders（最后手段）
            try:
                # print(f"[MPVPlayerCore] 尝试使用set_property方法设置glsl-shaders")
                # 对于单个shader，使用列表格式
                shader_list = f'["{processed_cube_path}"]'
                if self._set_property_string('glsl-shaders', shader_list):
                    # print(f"[MPVPlayerCore] 成功使用set_property方法设置glsl-shaders")
                    return True
                else:
                    print(f"[MPVPlayerCore] set_property方法设置glsl-shaders失败")
            except Exception as e:
                print(f"[MPVPlayerCore] set_property方法设置glsl-shaders异常: {e}")
                import traceback
                traceback.print_exc()
            
            # 恢复标志位
            print(f"[MPVPlayerCore] 所有方式都失败，无法启用Cube滤镜")
            self._cube_filter_enabled = False
            self._current_cube_path = ""
            return False
            
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 启用Cube滤镜失败 - {e}")
            import traceback
            traceback.print_exc()
            # 恢复标志位
            self._cube_filter_enabled = False
            self._current_cube_path = ""
            return False
    
    def disable_cube_filter(self):
        """
        禁用Cube色彩映射滤镜
        """
        try:
            if not self._mpv:
                return
            
            # 如果没有启用Cube滤镜，直接返回，避免不必要的操作
            if not self._cube_filter_enabled:
                # print(f"[MPVPlayerCore] Cube滤镜未启用，无需禁用")
                self._current_cube_path = ""
                return
            
            # print(f"[MPVPlayerCore] 开始禁用Cube滤镜")
            
            # 1. 移除所有lut3d滤镜（通过vf系统）
            # print(f"[MPVPlayerCore] 尝试移除所有lut3d滤镜")
            try:
                # 先尝试移除所有已知的lut3d相关滤镜
                filter_names = ['@lavfi/lut3d', 'lut3d']
                for filter_name in filter_names:
                    try:
                        self._execute_command(['vf', 'remove', filter_name])
                        # print(f"[MPVPlayerCore] 成功移除滤镜: {filter_name}")
                    except Exception as e:
                        print(f"[MPVPlayerCore] 移除滤镜 {filter_name} 失败: {e}")
                
                # 只在确实有滤镜时才移除所有滤镜
                if self._execute_command(['vf', 'get']):
                    self._execute_command(['vf', 'remove', 'all'])
                    # print(f"[MPVPlayerCore] 已移除所有视频滤镜")
            except Exception as e:
                print(f"[MPVPlayerCore] 滤镜移除操作失败: {e}")
            
            # 2. 清除glsl-shaders（通过shader系统）
            # print(f"[MPVPlayerCore] 尝试清除glsl-shaders")
            try:
                # 使用最基本的清除方式
                self._execute_command(['glsl-shaders', 'clr'])
                # print(f"[MPVPlayerCore] 成功清除glsl-shaders")
            except Exception as e:
                print(f"[MPVPlayerCore] 清除glsl-shaders失败: {e}")
            
            # 3. 强制刷新视频播放，确保滤镜效果立即移除
            # print(f"[MPVPlayerCore] 尝试刷新视频播放")
            
            try:
                # 保存当前状态
                was_playing = self._is_playing
                current_pos = 0.0
                if was_playing:
                    current_pos = self._get_property_double('playback-time')
                    # print(f"[MPVPlayerCore] 保存当前播放位置: {current_pos}s")
                
                # 使用最安全的刷新方式：视频重新配置
                self._execute_command(['video-reconfig'])
                # print(f"[MPVPlayerCore] 强制视频重新配置")
                
                # 如果正在播放，使用seek到当前位置来确保画面刷新
                if was_playing:
                    try:
                        self._set_property_double('time-pos', current_pos)
                        # print(f"[MPVPlayerCore] 视频seek到当前位置 {current_pos}s，强制刷新画面")
                    except Exception as e:
                        print(f"[MPVPlayerCore] 视频seek失败: {e}")
            except Exception as e:
                print(f"[MPVPlayerCore] 视频刷新操作失败: {e}")
            
            # 4. 更新标志位
            self._cube_filter_enabled = False
            self._current_cube_path = ""
            # print(f"[MPVPlayerCore] Cube滤镜已成功禁用")
            
        except Exception as e:
            print(f"[MPVPlayerCore] 禁用Cube滤镜失败: {e}")
            import traceback
            traceback.print_exc()
            # 即使发生异常，也要更新标志位
            self._cube_filter_enabled = False
            self._current_cube_path = ""
    
    def video_set_filter(self, filter_name, filter_param=None):
        """
        设置或移除MPV视频滤镜
        
        Args:
            filter_name (str): 滤镜名称，如"cube"或"lut_filter"
            filter_param (str, optional): 滤镜参数，如"file=path/to/cube.cube"。如果为None或空字符串，则移除滤镜
        """
        try:
            if not self._mpv:
                return
            
            # 处理滤镜设置
            if filter_param and filter_name in ["cube", "lut_filter"]:
                # 处理cube或lut_filter滤镜
                cube_path = filter_param.split('=')[1] if '=' in filter_param else filter_param
                self.enable_cube_filter(cube_path)
            elif not filter_param:
                # 移除滤镜
                self.disable_cube_filter()
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 设置滤镜失败 - {e}")
            import traceback
            traceback.print_exc()
    
    @property
    def is_cube_filter_enabled(self):
        """
        检查Cube滤镜是否已启用
        
        Returns:
            bool: Cube滤镜是否已启用
        """
        try:
            if not self._mpv:
                return False
            
            # 检查标志位
            return self._cube_filter_enabled
        except Exception:
            return False
    
    def __del__(self):
        """
        析构函数，确保资源被正确释放
        """
        self.cleanup()
