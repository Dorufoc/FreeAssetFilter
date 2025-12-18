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
import ctypes
from ctypes import *
from PyQt5.QtCore import QObject

# 获取当前文件所在目录（core目录）
core_path = os.path.dirname(os.path.abspath(__file__))

# 将core目录添加到系统PATH中，确保能找到libmpv-2.dll
os.environ['PATH'] = core_path + os.pathsep + os.environ['PATH']

# 加载libmpv-2.dll
_libmpv_path = os.path.join(core_path, "libmpv-2.dll")
mpv_loaded = False
try:
    # 尝试加载libmpv-2.dll
    print(f"[MPVPlayerCore] 尝试加载libmpv-2.dll，路径: {_libmpv_path}")
    libmpv = CDLL(_libmpv_path)
    print(f"[MPVPlayerCore] 成功加载libmpv-2.dll")
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
        
        # MPV实例
        self._mpv = None
        
        # 事件处理相关
        self._event_thread = None
        self._event_thread_running = False
        self._property_observers = {}
        self._next_observer_id = 1
        
        # 唤醒回调相关
        self._wakeup_callback = None
        self._wakeup_context = None
        
        # 检查MPV库是否加载成功
        if not mpv_loaded:
            print("[MPVPlayerCore] 警告: MPV库未加载成功，播放器功能不可用")
            return
            
        try:
            print("[MPVPlayerCore] 开始初始化MPV实例...")
            
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
            
            print("[MPVPlayerCore] MPV实例初始化成功")
            
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
                print("[MPVPlayerCore] 收到唤醒回调")
                # 这里可以添加事件处理逻辑，或者通过信号通知UI线程
                # 由于线程安全问题，我们使用独立的事件线程来处理事件
            
            # 保存回调函数和上下文，防止被GC回收
            self._wakeup_callback = wakeup_func_type(wakeup_callback)
            self._wakeup_context = None
            
            # 设置唤醒回调
            libmpv.mpv_set_wakeup_callback(self._mpv, self._wakeup_callback, self._wakeup_context)
            print("[MPVPlayerCore] 已设置唤醒回调")
            
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
            print("[MPVPlayerCore] 事件处理线程已启动")
            
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
            while self._event_thread_running and self._mpv:
                # 等待事件，超时100ms，避免阻塞线程
                event = libmpv.mpv_wait_event(self._mpv, 0.1)
                
                # 获取事件类型（事件指针的第一个成员）
                event_type = c_int.from_address(event).value
                
                if event_type == MPV_EVENT_NONE:
                    # 没有事件，继续循环
                    continue
                elif event_type == MPV_EVENT_SHUTDOWN:
                    # 播放器关闭，退出事件循环
                    print("[MPVPlayerCore] 收到关闭事件，退出事件循环")
                    break
                else:
                    # 处理其他事件
                    event_name = libmpv.mpv_event_name(event_type)
                    if event_name:
                        event_name_str = event_name.decode('utf-8')
                        print(f"[MPVPlayerCore] 收到事件: {event_name_str} (类型: {event_type})")
                    
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 事件循环异常 - {e}")
            import traceback
            traceback.print_exc()
        finally:
            self._event_thread_running = False
            print("[MPVPlayerCore] 事件处理线程已退出")
    
    def _stop_event_thread(self):
        """
        停止事件处理线程
        """
        try:
            self._event_thread_running = False
            if self._event_thread:
                self._event_thread.join(timeout=1.0)
                self._event_thread = None
            print("[MPVPlayerCore] 事件处理线程已停止")
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 停止事件处理线程失败 - {e}")
    
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
            
            print(f"[MPVPlayerCore] 已开始观察属性: {property_name}")
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
            
            print(f"[MPVPlayerCore] 已取消观察属性，观察者ID: {observer_id}")
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
                self._is_playing = not self._get_property_bool('pause')
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
                
            # 保存媒体路径
            self._media = file_path
            
            # 重置时长缓存
            self._duration = 0
            
            return True
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 设置媒体失败 - {e}")
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
    
    def _execute_command(self, command_list):
        """
        执行MPV命令
        
        Args:
            command_list (list): 命令列表，如 ['loadfile', 'path/to/file.mp4', 'replace']
            
        Returns:
            bool: 执行成功返回 True，否则返回 False
        """
        try:
            if not self._mpv:
                return False
            
            # 转换命令列表为ctypes所需的格式
            # 每个命令元素转换为bytes，最后添加None作为终止符
            command_array = (c_char_p * (len(command_list) + 1))()
            for i, cmd in enumerate(command_list):
                if isinstance(cmd, str):
                    command_array[i] = cmd.encode('utf-8')
                else:
                    command_array[i] = str(cmd).encode('utf-8')
            command_array[len(command_list)] = None
            
            # 执行命令
            result = libmpv.mpv_command(self._mpv, command_array)
            if result != MPV_ERROR_SUCCESS:
                print(f"[MPVPlayerCore] 错误: 执行命令 {command_list} 失败，错误码: {result}")
                return False
            
            return True
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 执行命令 {command_list} 异常 - {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def play(self):
        """
        开始播放媒体

        Returns:
            bool: 播放成功返回 True，否则返回 False
        """
        print(f"[MPVPlayerCore] 调用play()方法，_media={self._media}")
        
        try:
            # 检查MPV实例是否初始化成功
            if not self._mpv or not self._media:
                print(f"[MPVPlayerCore] 播放失败: MPV实例未初始化或媒体未设置")
                return False
                
            # 检查当前播放状态
            current_pause = self._get_property_bool('pause')
            print(f"[MPVPlayerCore] 播放前状态: pause={current_pause}, is_playing={self._is_playing}")
            
            # 如果已经在播放，不要重新开始
            if not current_pause and self._is_playing:
                print(f"[MPVPlayerCore] 已经在播放，不需要重新开始")
                return True
            
            # 如果是暂停状态，只恢复播放，不重新开始
            if current_pause:
                print(f"[MPVPlayerCore] 从暂停状态恢复播放")
                self._set_property_bool('pause', False)
                self._is_playing = True
                return True
            
            # 开始播放新媒体
            print(f"[MPVPlayerCore] 开始播放媒体: {self._media}")
            # 处理媒体路径
            processed_path = self.process_chinese_path(self._media)
            # 使用loadfile命令播放媒体
            result = self._execute_command(['loadfile', self._media, 'replace'])
            if result:
                self._is_playing = True
                print(f"[MPVPlayerCore] 媒体播放成功")
            return result
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 播放媒体失败 - {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def pause(self):
        """
        暂停播放媒体
        """
        try:
            # 检查MPV实例是否初始化成功
            if not self._mpv:
                return
                
            # 获取当前暂停状态
            current_pause = self._get_property_bool('pause')
            # 切换暂停状态
            new_pause = not current_pause
            self._set_property_bool('pause', new_pause)
            # 更新播放状态
            self._is_playing = not new_pause
            print(f"[MPVPlayerCore] 切换暂停状态: 原状态={current_pause}, 新状态={new_pause}")
        except Exception as e:
            print(f"[MPVPlayerCore] 警告: 切换暂停状态失败 - {e}")
            # 确保播放状态至少在本地是一致的
            self._is_playing = not self._is_playing
    
    def stop(self):
        """
        停止播放媒体
        """
        try:
            # 检查MPV实例是否初始化成功
            if not self._mpv:
                self._is_playing = False
                return
                
            # 使用stop命令停止播放
            self._execute_command(['stop'])
            self._is_playing = False
            print("[MPVPlayerCore] 播放已停止")
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
            
            print(f"[MPVPlayerCore] 设置播放位置: position={position}, percent={position*100}%")
            
            # 获取当前时长（秒）
            duration = self._get_property_double('duration')
            
            print(f"[MPVPlayerCore] 当前状态: duration={duration}s")
            
            if duration > 0:
                # 使用秒为单位进行seek
                seek_pos = position * duration
                print(f"[MPVPlayerCore] 使用秒seek: seek_pos={seek_pos}s")
                # 使用seek命令进行跳转
                self._execute_command(['seek', str(seek_pos), 'absolute'])
            else:
                # 使用百分比seek作为备选
                percent = position * 100
                print(f"[MPVPlayerCore] 使用百分比seek: {percent}%")
                self._execute_command(['seek', str(percent), 'absolute-percent'])
                
        except Exception as e:
            print(f"[MPVPlayerCore] 警告: 设置播放位置失败 - {e}")
            import traceback
            traceback.print_exc()
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
        设置double类型属性
        
        Args:
            property_name (str): 属性名称
            value (float): 属性值
            
        Returns:
            bool: 设置成功返回 True，否则返回 False
        """
        try:
            if not self._mpv:
                return False
            
            value_double = c_double(value)
            result = libmpv.mpv_set_property(self._mpv, property_name.encode('utf-8'), MPV_FORMAT_DOUBLE, byref(value_double))
            if result != MPV_ERROR_SUCCESS:
                print(f"[MPVPlayerCore] 警告: 设置属性 {property_name} 失败，错误码: {result}")
                return False
            
            return True
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 设置属性 {property_name} 异常 - {e}")
            return False
    
    def _get_property_string(self, property_name):
        """
        获取字符串类型属性
        
        Args:
            property_name (str): 属性名称
            
        Returns:
            str: 属性值
        """
        try:
            if not self._mpv:
                return ""
            
            value_ptr = c_char_p()
            result = libmpv.mpv_get_property_string(self._mpv, property_name.encode('utf-8'), byref(value_ptr))
            if result != MPV_ERROR_SUCCESS:
                # print(f"[MPVPlayerCore] 警告: 获取属性 {property_name} 失败，错误码: {result}")
                return ""
            
            if not value_ptr or not value_ptr.value:
                return ""
            
            value = value_ptr.value.decode('utf-8')
            # 释放内存
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
            print(f"[MPVPlayerCore] 播放速度已设置为: {speed}x")
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
            print(f"[MPVPlayerCore] 音量已设置为: {volume}%")
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
                
            print(f"[MPVPlayerCore] 尝试绑定窗口，窗口ID: {window_id}")
            
            # 保存窗口句柄
            self._window_handle = window_id
            
            # 将窗口句柄转换为整数，处理sip.voidptr对象
            if hasattr(window_id, 'value'):
                # 处理sip.voidptr对象
                window_id = window_id.value
                print(f"[MPVPlayerCore] 转换窗口ID为: {window_id}")
            elif not isinstance(window_id, int):
                # 尝试转换为整数
                window_id = int(window_id)
                print(f"[MPVPlayerCore] 转换窗口ID为: {window_id}")
            
            # 设置MPV的渲染窗口
            # 使用mpv_set_option_string设置wid选项
            result = libmpv.mpv_set_option_string(self._mpv, b"wid", str(window_id).encode('utf-8'))
            if result != MPV_ERROR_SUCCESS:
                print(f"[MPVPlayerCore] 错误: 设置窗口失败，错误码: {result}")
                return
            
            print("[MPVPlayerCore] 窗口绑定成功")
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 设置窗口失败 - {e}")
            import traceback
            traceback.print_exc()
    
    def clear_window(self):
        """
        清除媒体播放器与窗口的绑定
        """
        try:
            # 检查MPV实例是否初始化成功
            if not self._mpv:
                self._window_handle = None
                return
                
            # 清除MPV的渲染窗口
            result = libmpv.mpv_set_option_string(self._mpv, b"wid", b"0")
            if result != MPV_ERROR_SUCCESS:
                print(f"[MPVPlayerCore] 错误: 清除窗口绑定失败，错误码: {result}")
            
            # 清除窗口句柄
            self._window_handle = None
            print("[MPVPlayerCore] 窗口绑定已清除")
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 清除窗口绑定失败 - {e}")
            import traceback
            traceback.print_exc()
            self._window_handle = None
    
    def cleanup(self):
        """
        清理资源，释放 MPV 实例
        """
        try:
            # 停止播放
            self.stop()
            
            # 停止事件处理线程
            self._stop_event_thread()
            
            # 清除窗口绑定
            self.clear_window()
            
            # 释放MPV实例
            if self._mpv:
                try:
                    libmpv.mpv_terminate_destroy(self._mpv)
                    print("[MPVPlayerCore] MPV实例已销毁")
                except Exception as e:
                    print(f"[MPVPlayerCore] 错误: 销毁MPV实例失败 - {e}")
                self._mpv = None
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 清理资源失败 - {e}")
    

    
    def process_chinese_path(self, raw_path: str) -> str:
        """
        处理带中文/空格的路径：
        1. 确保路径使用正斜杠，避免MPV解析问题
        2. 给路径加英文双引号（解决空格被解析为参数分隔符的问题）
        3. 确保路径编码正确，避免中文乱码问题
        
        Args:
            raw_path (str): 原始路径
            
        Returns:
            str: 处理后的路径，适合传递给libmpv
        """
        # 步骤1：确保路径使用正斜杠，避免MPV解析问题
        normalized_path = raw_path.replace('\\', '/')
        
        # 步骤2：确保路径格式正确，处理中文和空格
        # 对于libmpv，直接使用UTF-8编码的路径即可，不需要额外的引号处理
        # 因为我们在execute_command中会将命令参数正确编码
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
                print(f"[MPVPlayerCore] 已启用相同的Cube滤镜，无需重复添加")
                return True
            
            # 检查文件内容，确保是有效的Cube文件
            try:
                with open(cube_path, 'r') as f:
                    content = f.read()
                print(f"[MPVPlayerCore] Cube文件内容前500字符: {content[:500]}")
            except Exception as e:
                print(f"[MPVPlayerCore] 无法读取Cube文件: {e}")
                return False
            
            # 先清除所有现有的Cube滤镜，避免重复添加
            self.disable_cube_filter()
            
            # 更新标志位和当前Cube路径
            self._cube_filter_enabled = True
            self._current_cube_path = cube_path
            
            print(f"[MPVPlayerCore] 尝试启用Cube滤镜，文件路径: {cube_path}")
            
            # 处理Cube路径（中文/空格）
            processed_cube_path = self.process_chinese_path(cube_path)
            
            # 尝试使用vf add命令添加lut3d滤镜（通用方法）
            try:
                print(f"[MPVPlayerCore] 尝试使用vf add命令添加lut3d滤镜")
                # 确保路径格式正确，处理中文和空格
                normalized_path = cube_path.replace('\\', '/')
                # 使用绝对路径，确保能找到文件
                filter_arg = f'lut3d=file={normalized_path}'
                print(f"[MPVPlayerCore] 尝试添加滤镜: {filter_arg}")
                
                if self._execute_command(['vf', 'add', filter_arg]):
                    print(f"[MPVPlayerCore] 成功使用vf add命令添加lut3d滤镜")
                    return True
                else:
                    print(f"[MPVPlayerCore] vf add命令失败")
            except Exception as e:
                print(f"[MPVPlayerCore] vf add命令异常: {e}")
                import traceback
                traceback.print_exc()
            
            # 尝试使用load glsl-shaders命令（适用于vo=gpu-next）
            try:
                print(f"[MPVPlayerCore] 尝试使用load glsl-shaders命令")
                # 执行load glsl-shaders命令
                if self._execute_command(['load', 'glsl-shaders', processed_cube_path]):
                    print(f"[MPVPlayerCore] 成功使用load glsl-shaders命令加载滤镜")
                    return True
                else:
                    print(f"[MPVPlayerCore] load glsl-shaders命令失败")
            except Exception as e:
                print(f"[MPVPlayerCore] load glsl-shaders命令异常: {e}")
                import traceback
                traceback.print_exc()
            
            # 尝试使用glsl-shaders选项（替换模式，避免重复添加）
            try:
                print(f"[MPVPlayerCore] 尝试使用glsl-shaders选项（替换模式）")
                # 使用mpv_set_option_string设置glsl-shaders选项（替换现有滤镜）
                result = libmpv.mpv_set_option_string(self._mpv, b"glsl-shaders", processed_cube_path.encode('utf-8'))
                if result == MPV_ERROR_SUCCESS:
                    print(f"[MPVPlayerCore] 成功使用glsl-shaders选项加载滤镜")
                    return True
                else:
                    print(f"[MPVPlayerCore] glsl-shaders选项失败，错误码: {result}")
            except Exception as e:
                print(f"[MPVPlayerCore] glsl-shaders选项异常: {e}")
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
            
            print(f"[MPVPlayerCore] 开始禁用Cube滤镜")
            
            # 1. 首先尝试移除所有lut3d滤镜（通过vf系统）
            print(f"[MPVPlayerCore] 尝试移除所有lut3d滤镜")
            # 使用多种方式尝试移除lut3d滤镜
            filter_names = ['@lavfi/lut3d', 'lut3d', '3dlut', 'colorgrade']
            for filter_name in filter_names:
                try:
                    self._execute_command(['vf', 'remove', filter_name])
                    print(f"[MPVPlayerCore] 尝试移除滤镜: {filter_name}")
                except Exception as e:
                    print(f"[MPVPlayerCore] 移除滤镜 {filter_name} 失败: {e}")
            
            # 移除所有视频滤镜，确保彻底清除
            try:
                self._execute_command(['vf', 'remove', 'all'])
                print(f"[MPVPlayerCore] 已移除所有视频滤镜")
            except Exception as e:
                print(f"[MPVPlayerCore] 移除所有视频滤镜失败: {e}")
            
            # 2. 清除glsl-shaders（通过shader系统）
            print(f"[MPVPlayerCore] 尝试清除glsl-shaders")
            # 尝试多种方式清除glsl-shaders
            shader_commands = [
                ['glsl-shaders', 'clr'],
                ['load', 'glsl-shaders', ''],
                ['glsl-shaders', 'reload']
            ]
            for cmd in shader_commands:
                try:
                    self._execute_command(cmd)
                    print(f"[MPVPlayerCore] 执行shader命令: {cmd}")
                except Exception as e:
                    print(f"[MPVPlayerCore] 执行shader命令 {cmd} 失败: {e}")
            
            # 方式3: 直接设置glsl-shaders选项为空
            try:
                libmpv.mpv_set_option_string(self._mpv, b"glsl-shaders", b"")
                print(f"[MPVPlayerCore] 成功设置glsl-shaders选项为空")
            except Exception as e:
                print(f"[MPVPlayerCore] 设置glsl-shaders选项失败: {e}")
            
            # 3. 清除所有可能的LUT相关选项
            print(f"[MPVPlayerCore] 清除LUT相关选项")
            lut_options = [
                b"video-output-levels",
                b"colorspace",
                b"color-primaries",
                b"transfer",
                b"hdr-compute-peak",
                b"target-trc",
                b"target-prim"
            ]
            for option in lut_options:
                try:
                    libmpv.mpv_set_option_string(self._mpv, option, b"")
                except Exception as e:
                    print(f"[MPVPlayerCore] 清除选项 {option.decode()} 失败: {e}")
            
            # 4. 强制刷新视频播放，确保滤镜效果立即移除
            print(f"[MPVPlayerCore] 尝试刷新视频播放")
            
            # 保存当前状态
            was_playing = self._is_playing
            current_pos = 0.0
            if was_playing:
                current_pos = self._get_property_double('playback-time')
                print(f"[MPVPlayerCore] 保存当前播放位置: {current_pos}s")
            
            # 尝试多种方式刷新视频
            # 方式1: 暂停再播放（安全刷新方式）
            self._set_property_bool('pause', True)
            self._set_property_bool('pause', False)
            
            # 方式2: 强制视频重新配置（更安全的刷新方式）
            try:
                self._execute_command(['video-reconfig'])
                print(f"[MPVPlayerCore] 强制视频重新配置")
            except Exception as e:
                print(f"[MPVPlayerCore] 强制视频重新配置失败: {e}")
                
            # 方式3: 如果视频输出有问题，尝试重置视频输出模块
            try:
                self._execute_command(['vo-reset'])
                print(f"[MPVPlayerCore] 重置视频输出模块")
            except Exception as e:
                print(f"[MPVPlayerCore] 重置视频输出模块失败: {e}")
            
            # 方式4: 确保播放状态正确恢复
            if was_playing and not self._get_property_bool('pause'):
                print(f"[MPVPlayerCore] 播放状态已正确恢复")
            elif was_playing:
                # 如果需要，手动恢复播放
                self._set_property_bool('pause', False)
                print(f"[MPVPlayerCore] 手动恢复播放状态")
            
            # 5. 更新标志位
            self._cube_filter_enabled = False
            self._current_cube_path = ""
            print(f"[MPVPlayerCore] Cube滤镜已成功禁用")
            
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
