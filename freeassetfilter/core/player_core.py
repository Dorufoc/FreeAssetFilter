#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

媒体播放器核心类
基于 Python-VLC 实现，提供高性能的媒体播放功能
"""

import vlc
import platform
import os


class PlayerCore:
    """
    媒体播放器核心类
    基于 Python-VLC 实现，提供完整的媒体播放功能
    """
    
    # 支持的视频和音频格式
    SUPPORTED_VIDEO_FORMATS = ['.mp4', '.mov', '.m4v', '.flv', '.mxf', '.3gp', 
                              '.mpg', '.avi', '.wmv', '.mkv', '.webm', '.vob', 
                              '.ogv', '.rmvb']
    SUPPORTED_AUDIO_FORMATS = ['.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma', 
                              '.m4a', '.aiff', '.ape', '.opus']
    
    def __init__(self):
        """
        初始化播放器核心
        使用单例模式管理 VLC 实例，优化资源使用
        """
        # 初始化 VLC 实例，使用最佳实践配置
        self._instance = vlc.Instance('--no-xlib --quiet')
        
        # 初始化媒体播放器
        self._player = self._instance.media_player_new()
        
        # 媒体对象
        self._media = None
        
        # 播放状态标志
        self._is_playing = False
        
        # 循环播放设置
        self._loop = False
        
        # 窗口句柄
        self._window_handle = None
        
        # 媒体时长缓存
        self._duration = 0
        
        # 绑定事件处理
        self._bind_events()
    
    def _bind_events(self):
        """
        绑定 VLC 事件处理
        优化事件处理，只监听必要的事件
        """
        # 获取事件管理器
        event_manager = self._player.event_manager()
        
        # 监听媒体结束事件
        event_manager.event_attach(vlc.EventType.MediaPlayerEndReached, self._on_media_end)
        
        # 监听播放状态变化事件
        event_manager.event_attach(vlc.EventType.MediaPlayerPlaying, self._on_playing)
        event_manager.event_attach(vlc.EventType.MediaPlayerPaused, self._on_paused)
        event_manager.event_attach(vlc.EventType.MediaPlayerStopped, self._on_stopped)
        
        # 监听媒体解析完成事件
        event_manager.event_attach(vlc.EventType.MediaParsedChanged, self._on_media_parsed)
    
    def _on_media_end(self, event):
        """
        媒体播放结束事件处理
        """
        self._is_playing = False
        
        # 如果启用了循环播放，重新播放
        if self._loop:
            self._player.set_position(0.0)
            self._player.play()
    
    def _on_playing(self, event):
        """
        开始播放事件处理
        """
        self._is_playing = True
    
    def _on_paused(self, event):
        """
        暂停播放事件处理
        """
        self._is_playing = False
    
    def _on_stopped(self, event):
        """
        停止播放事件处理
        """
        self._is_playing = False
    
    def _on_media_parsed(self, event):
        """
        媒体解析完成事件处理
        """
        # 更新媒体时长缓存
        if self._media:
            self._duration = self._media.get_duration()
    
    @property
    def is_playing(self):
        """
        获取当前播放状态
        
        Returns:
            bool: 是否正在播放
        """
        return self._is_playing
    
    @property
    def time(self):
        """
        获取当前播放时间（毫秒）
        
        Returns:
            int: 当前播放时间，单位毫秒
        """
        try:
            return self._player.get_time()
        except Exception:
            return 0
    
    @property
    def duration(self):
        """
        获取媒体总时长（毫秒）
        
        Returns:
            int: 媒体总时长，单位毫秒
        """
        try:
            # 优先使用缓存的时长
            if self._duration > 0:
                return self._duration
            # 否则从媒体对象获取
            if self._media:
                duration = self._media.get_duration()
                if duration > 0:
                    self._duration = duration
                    return duration
            # 最后尝试从播放器获取
            duration = self._player.get_length()
            if duration > 0:
                self._duration = duration
                return duration
            return 0
        except Exception:
            return 0
    
    @property
    def position(self):
        """
        获取当前播放位置（0.0 - 1.0）
        
        Returns:
            float: 当前播放位置，范围 0.0 到 1.0
        """
        try:
            return self._player.get_position()
        except Exception:
            return 0.0
    
    def set_media(self, file_path):
        """
        设置要播放的媒体文件
        移除了os.path.exists调用，避免网络文件阻塞主线程
        
        Args:
            file_path (str): 媒体文件路径
            
        Returns:
            bool: 设置成功返回 True，否则返回 False
        """
        # 生成带时间戳的debug信息
        import datetime
        def debug(msg):
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            print(f"[{timestamp}] [PlayerCore] {msg}")
        
        try:
            debug(f"开始设置媒体: {file_path}")
            # 停止当前播放
            debug("停止当前播放")
            self.stop()
            
            # 创建新的媒体对象
            debug("创建新的媒体对象")
            self._media = self._instance.media_new(file_path)
            debug(f"媒体对象创建成功: {self._media}")
            
            # 设置媒体到播放器
            debug("设置媒体到播放器")
            self._player.set_media(self._media)
            
            # 开始异步解析媒体信息
            # 对于网络文件，使用network标志，1秒超时
            debug("开始异步解析媒体信息，1秒超时")
            self._media.parse_with_options(vlc.MediaParseFlag.network, 1000)  # 1秒超时
            
            # 重置时长缓存
            debug("重置时长缓存")
            self._duration = 0
            
            debug("媒体设置成功")
            return True
        except Exception as e:
            debug(f"媒体设置失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def play(self):
        """
        开始播放媒体

        Returns:
            bool: 播放成功返回 True，否则返回 False
        """
        try:
            # 确保媒体已设置
            if not self._media:
                return False
            
            # 开始播放
            result = self._player.play()
            if result == 0:
                # 立即更新播放状态，不依赖事件回调
                self._is_playing = True
            return result == 0
        except Exception:
            return False
    
    def pause(self):
        """
        暂停播放媒体
        """
        try:
            # 保存当前状态，用于判断暂停后的状态
            was_playing = self._is_playing
            
            # 切换暂停状态
            self._player.pause()
            
            # 立即更新播放状态，不依赖事件回调
            # pause() 方法会切换状态：如果正在播放则暂停，否则继续播放
            self._is_playing = not was_playing
        except Exception:
            pass
    
    def stop(self):
        """
        停止播放媒体
        """
        try:
            self._player.stop()
            self._is_playing = False
        except Exception:
            pass
    
    def set_position(self, position):
        """
        设置播放位置
        
        Args:
            position (float): 播放位置，范围 0.0 到 1.0
        """
        try:
            # 确保位置在有效范围内
            position = max(0.0, min(1.0, position))
            self._player.set_position(position)
        except Exception:
            pass
    
    def set_volume(self, volume):
        """
        设置音量
        
        Args:
            volume (int): 音量值，范围 0 到 100
        """
        try:
            # 确保音量在有效范围内
            volume = max(0, min(100, volume))
            self._player.audio_set_volume(volume)
        except Exception:
            pass
    
    def get_volume(self):
        """
        获取当前音量
        
        Returns:
            int: 当前音量值，范围 0 到 100
        """
        try:
            return self._player.audio_get_volume()
        except Exception:
            return 50  # 默认返回50%
    
    def set_loop(self, loop):
        """
        设置循环播放
        
        Args:
            loop (bool): 是否启用循环播放
        """
        self._loop = loop
    
    def set_window(self, window_id):
        """
        将媒体播放器绑定到指定窗口
        
        Args:
            window_id: 窗口句柄，根据平台不同类型可能不同
        """
        try:
            # 保存窗口句柄
            self._window_handle = window_id
            
            # 根据平台设置不同的窗口绑定方法
            if platform.system() == "Windows":
                self._player.set_hwnd(int(window_id))
            elif platform.system() == "Linux":
                self._player.set_xwindow(int(window_id))
            elif platform.system() == "Darwin":  # macOS
                self._player.set_nsobject(int(window_id))
        except Exception:
            pass
    
    def clear_window(self):
        """
        清除媒体播放器与窗口的绑定
        """
        try:
            # 根据平台清除不同的窗口绑定
            if platform.system() == "Windows":
                self._player.set_hwnd(0)
            elif platform.system() == "Linux":
                self._player.set_xwindow(0)
            elif platform.system() == "Darwin":  # macOS
                self._player.set_nsobject(0)
            
            # 清除窗口句柄
            self._window_handle = None
        except Exception:
            pass
    
    def cleanup(self):
        """
        清理资源，释放 VLC 实例和媒体播放器
        """
        try:
            # 停止播放
            self.stop()
            
            # 清除窗口绑定
            self.clear_window()
            
            # 释放媒体对象
            if self._media:
                self._media.release()
                self._media = None
            
            # 释放媒体播放器
            if self._player:
                self._player.release()
                self._player = None
            
            # 释放 VLC 实例
            if self._instance:
                self._instance.release()
                self._instance = None
        except Exception:
            pass
    
    def set_rate(self, rate):
        """
        设置播放速度
        
        Args:
            rate (float): 播放速度，1.0为正常速度
        """
        try:
            self._player.set_rate(rate)
        except Exception:
            pass
    
    def get_rate(self):
        """
        获取当前播放速度
        
        Returns:
            float: 当前播放速度
        """
        try:
            return self._player.get_rate()
        except Exception:
            return 1.0
    
    def __del__(self):
        """
        析构函数，确保资源被正确释放
        """
        self.cleanup()