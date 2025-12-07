#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

播放器核心组件
基于VLC的视频播放器，提供完整的播放控制接口
"""

import sys
import os
import time
from threading import Thread, Event
import vlc


class PlayerCore:
    """
    VLC播放器核心类，提供完整的媒体播放控制功能
    
    支持的视频格式：mp4, mov, m4v, flv, mxf, 3gp, mpg
    """
    
    # 支持的视频格式列表
    SUPPORTED_VIDEO_FORMATS = {
        '.mp4', '.mov', '.m4v', '.flv', '.mxf', '.3gp', '.mpg',
        '.avi', '.wmv', '.mkv', '.webm', '.vob', '.ogv', '.rmvb'
    }
    
    # 支持的音频格式列表
    SUPPORTED_AUDIO_FORMATS = {
        '.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma', '.m4a',
        '.aiff', '.ape', '.opus', '.ra', '.ram', '.mid', '.midi'
    }
    
    def __init__(self):
        """
        初始化播放器核心
        """
        print("PlayerCore.__init__: 开始初始化")
        self.instance = None
        self.player = None
        try:
            print("PlayerCore.__init__: 正在创建VLC实例")
            # 尝试使用不同的参数创建VLC实例
            self.instance = vlc.Instance('--no-xlib')
            print(f"PlayerCore.__init__: VLC实例创建结果: {self.instance}")
            if not self.instance:
                print("错误：无法创建VLC实例")
                return
            print("PlayerCore.__init__: 正在创建媒体播放器")
            # 创建媒体播放器
            self.player = self.instance.media_player_new()
            print(f"PlayerCore.__init__: 媒体播放器创建结果: {self.player}")
            if not self.player:
                print("错误：无法创建媒体播放器")
        except Exception as e:
            print(f"初始化播放器核心时出错: {e}")
            import traceback
            traceback.print_exc()
            self.instance = None
            self.player = None
        
        # 播放状态
        self.is_playing = False
        self.is_paused = False
        self.current_media = None
        self.media_path = ""
        # 循环播放标志
        self.loop = False
        
        # 播放信息
        self.duration = 0  # 总时长（毫秒）
        self.position = 0  # 当前位置 (0.0-1.0)
        self.time = 0  # 当前时间（毫秒）
        
        # 播放控制参数
        self.volume = 50  # 音量 (0-100)
        self.rate = 1.0  # 播放速率 (0.25-4.0)
        
        # 事件处理
        self.event_manager = self.player.event_manager()
        self._setup_events()
        
        # 移除重复的进度更新线程，只使用事件驱动更新
    def _setup_events(self):
        """
        设置VLC事件监听器
        仅附加当前VLC版本支持的事件类型
        """
        # 定义要附加的事件及其处理函数
        event_handlers = [
            ('MediaPlayerMediaChanged', self._on_media_changed),
            # 注释掉可能不支持的事件
            # ('MediaPlayerParsedChanged', self._on_media_parsed),
            ('MediaPlayerPlaying', self._on_playing),
            ('MediaPlayerPaused', self._on_paused),
            ('MediaPlayerStopped', self._on_stopped),
            ('MediaPlayerEndReached', self._on_end_reached),
            ('MediaPlayerPositionChanged', self._on_position_changed)
        ]
        
        # 尝试附加每个事件
        for event_name, handler in event_handlers:
            try:
                event_type = getattr(vlc.EventType, event_name)
                self.event_manager.event_attach(event_type, handler)
            except AttributeError:
                print(f"警告: VLC版本不支持 {event_name} 事件")
            except Exception as e:
                print(f"警告: 无法附加 {event_name} 事件 - {e}")
        
        # 添加替代的媒体解析方法
        # 定期检查媒体是否已解析完成
        self.check_media_parsed_timer = Thread(target=self._check_media_parsed_loop)
        self.check_media_parsed_timer.daemon = True
        self.check_media_parsed_timer.start()
    
    def _on_media_changed(self, event):
        """媒体已更改事件处理"""
        self.current_media = self.player.get_media()
        if self.current_media:
            self.current_media.parse()
    
    def _on_media_parsed(self, event):
        """媒体解析完成事件处理"""
        if self.current_media and self.current_media.parse_status() == vlc.MediaParsedStatus.done:
            self.duration = self.current_media.get_duration()
    
    def _on_playing(self, event):
        """开始播放事件处理"""
        self.is_playing = True
        self.is_paused = False
    
    def _on_paused(self, event):
        """暂停播放事件处理"""
        self.is_playing = False
        self.is_paused = True
    
    def _on_stopped(self, event):
        """停止播放事件处理"""
        self.is_playing = False
        self.is_paused = False
        self.position = 0
        self.time = 0
    
    def _on_end_reached(self, event):
        """播放结束事件处理"""
        if self.loop:
            # 如果设置了循环播放，重新开始播放
            try:
                # 重置播放位置到开始
                self.player.set_position(0.0)
                # 重新开始播放
                self.play()
            except Exception as e:
                print(f"循环播放时出错: {e}")
                # 如果出错，更新状态
                self.is_playing = False
                self.is_paused = False
                self.position = 1.0
                self.time = self.duration
        else:
            # 非循环模式，更新状态
            self.is_playing = False
            self.is_paused = False
            self.position = 1.0
            self.time = self.duration
    
    def _on_position_changed(self, event):
        """位置变化事件处理"""
        self.position = event.u.new_position
        # 优先使用播放器的实际时间，避免duration为0时的计算错误
        actual_time = self.player.get_time()
        if actual_time > 0:
            self.time = actual_time
        elif self.duration > 0:
            self.time = int(self.position * self.duration)
    
    def _check_media_parsed_loop(self):
        """
        定期检查媒体是否已解析完成的循环
        作为MediaPlayerParsedChanged事件的替代方法
        """
        while True:
            if self.current_media:
                try:
                    # 直接获取时长，通过时长是否有效来判断媒体是否已解析
                    duration = self.current_media.get_duration()
                    if duration > 0:
                        self.duration = duration
                except Exception:
                    pass
            time.sleep(1)  # 每秒检查一次
    
    def set_media(self, media_path):
        """
        设置要播放的媒体文件
        
        Args:
            media_path (str): 媒体文件路径
            
        Returns:
            bool: 是否成功设置媒体
        """
        # 确保vlc模块已导入
        import vlc
        
        if not os.path.exists(media_path):
            print(f"错误：文件不存在 - {media_path}")
            return False
        
        # 检查文件格式是否支持
        ext = os.path.splitext(media_path)[1].lower()
        if ext not in self.SUPPORTED_VIDEO_FORMATS and ext not in self.SUPPORTED_AUDIO_FORMATS:
            print(f"警告：文件格式 {ext} 可能不被支持")
        
        # 检查instance和player是否已初始化
        if not self.instance or not self.player:
            print("错误：VLC实例或媒体播放器未初始化")
            return False
        
        # 停止当前播放
        self.stop()
        
        # 清除视频输出窗口
        self.clear_window()
        
        # 释放旧媒体资源
        if self.current_media:
            try:
                self.current_media.release()
            except Exception as e:
                print(f"释放媒体资源时出错: {e}")
            self.current_media = None
        
        # 重置播放信息
        self.duration = 0
        self.position = 0
        self.time = 0
        self.media_path = ""
        
        # 设置新媒体
        self.media_path = media_path
        try:
            print(f"set_media: 正在使用VLC实例 {self.instance} 创建媒体实例")
            print(f"set_media: 媒体路径: {media_path}")
            
            # 尝试创建媒体实例
            try:
                self.current_media = self.instance.media_new(media_path)
                print(f"set_media: 媒体实例创建成功: {self.current_media}")
            except Exception as e:
                print(f"set_media: 媒体实例创建失败: {e}")
                import traceback
                traceback.print_exc()
                return False
            
            if not self.current_media:
                print("错误：无法创建媒体实例")
                return False
            
            # 设置媒体选项，添加错误处理
            try:
                # 添加错误处理选项，避免崩溃
                self.current_media.add_option(':no-error-dialog')  # 禁止错误对话框
                
                # 对于MOV文件，使用更适合的配置，支持透明通道
                if ext == '.mov':
                    # 基础配置
                    self.current_media.add_option(':no-error-dialog')  # 禁止错误对话框
                    self.current_media.add_option(':avcodec_threads=auto')  # 自动调整解码线程数，提高性能
                    self.current_media.add_option(':codec=all')  # 支持所有编解码器
                    self.current_media.add_option(':no-deinterlace')  # 禁用去隔行，避免透明通道问题
                    
                    # 颜色空间和偏色问题修复
                    self.current_media.add_option(':video-filter=adjust')  # 添加颜色调整滤镜
                    self.current_media.add_option(':adjust-brightness=0')  # 亮度调整
                    self.current_media.add_option(':adjust-contrast=1')  # 对比度调整
                    self.current_media.add_option(':adjust-saturation=1')  # 饱和度调整
                    self.current_media.add_option(':adjust-gamma=1')  # 伽马调整
                    self.current_media.add_option(':video-chroma=RV32')  # 明确设置视频颜色格式，解决颜色偏色问题
                    self.current_media.add_option(':colorspace=RGB')  # 设置颜色空间为RGB，适合透明通道
                    self.current_media.add_option(':color-range=full')  # 使用全色彩范围
                    self.current_media.add_option(':color-primaries=bt709')  # 设置色彩原色
                    self.current_media.add_option(':color-trc=bt709')  # 设置色彩传输特性
                    
                    # 解决SetThumbNailClip错误
                    self.current_media.add_option(':direct3d11-disable-thumbnail-clip')  # 禁用缩略图剪辑
                    
                    # 输出模块配置，优先使用支持透明通道的模块
                    self.current_media.add_option(':vout=direct3d11')  # 使用direct3d11，支持透明通道
                    self.current_media.add_option(':direct3d11-hw-yuv-conversion')  # 启用硬件YUV转换
                    self.current_media.add_option(':direct3d11-output-format=RGB32')  # 设置输出格式为RGB32，支持透明通道
                    
                    # 禁用可能导致问题的硬件加速
                    self.current_media.add_option(':hwdec=no')  # 禁用硬件解码，避免透明通道和颜色偏色问题
                    
                    # 特殊处理MOV文件的解码
                    self.current_media.add_option(':fflags=+genpts+igndts+fastseek')  # 生成pts并忽略dts错误，添加快速seek
                    self.current_media.add_option(':err_detect=ignore_err')  # 忽略错误
                    self.current_media.add_option(':reconnect=1')  # 允许重新连接
                    
                    # 性能优化，解决卡顿问题
                    self.current_media.add_option(':network-caching=150')  # 设置网络缓存为150ms
                    self.current_media.add_option(':file-caching=150')  # 设置文件缓存为150ms
                    self.current_media.add_option(':live-caching=150')  # 设置直播缓存为150ms
                    self.current_media.add_option(':drop-late-frames')  # 丢弃延迟帧，减少卡顿
                    self.current_media.add_option(':skip-frames=0')  # 不跳过帧，确保视频完整性
                    self.current_media.add_option(':framedrop=1')  # 启用帧丢弃，减少卡顿
                    
                    # 音频同步优化
                    self.current_media.add_option(':audio-sync=video')  # 音频同步到视频
                    self.current_media.add_option(':audio-resampler=soxr')  # 使用高质量音频重采样器
                    
                    # 禁用可能导致问题的选项
                    self.current_media.add_option(':no-avformat-dr')  # 禁用AVFormat动态范围压缩
                    self.current_media.add_option(':no-autoscale')  # 禁用自动缩放
                    self.current_media.add_option(':scale-factor=1')  # 设置缩放因子为1
                    
                    # 明确启用alpha通道支持
                    self.current_media.add_option(':alpha-channel=on')  # 启用透明通道支持
                    self.current_media.add_option(':video-opacity=100')  # 设置视频不透明度
                else:
                    # 其他文件格式使用原有配置
                    self.current_media.add_option(':avcodec_threads=1')  # 限制解码线程数，减少崩溃风险
                    # 添加Direct3D相关选项，避免SetThumb bNailClip错误
                    self.current_media.add_option(':vout=direct3d11')  # 指定Direct3D 11输出
                    self.current_media.add_option(':direct3d11-disable-threads')  # 禁用Direct3D线程，避免并发问题
                    self.current_media.add_option(':direct3d11-disable-thumbnail-clip')  # 禁用缩略图剪辑，解决SetThumb bNailClip错误
                    # 对于MP4等文件，添加快速启动选项，处理moov atom问题
                    if ext in ['.mp4', '.m4v', '.3gp', '.mj2']:
                        self.current_media.add_option(':fflags=+genpts+igndts')  # 生成pts并忽略dts错误
                        self.current_media.add_option(':err_detect=ignore_err')  # 忽略错误
            except Exception as e:
                print(f"设置媒体选项时出错: {e}")
            
            try:
                # 使用异步解析，避免阻塞主线程
                self.current_media.parse_with_options(vlc.MediaParseFlag.network, 1000)  # 1秒超时
                print(f"set_media: 媒体解析选项设置成功")
            except Exception as e:
                print(f"设置媒体解析选项时出错: {e}")
            
            # 设置媒体到播放器
            try:
                self.player.set_media(self.current_media)
                print(f"set_media: 媒体设置到播放器成功")
            except Exception as e:
                print(f"设置媒体到播放器时出错: {e}")
                return False
            
            # 立即获取一次时长信息，后续会通过事件或定期检查更新
            initial_duration = self.current_media.get_duration()
            if initial_duration > 0:
                self.duration = initial_duration
                print(f"set_media: 获取媒体时长成功: {initial_duration}ms")
            else:
                self.duration = 0
                print(f"set_media: 无法获取媒体时长，设置为0")
            
            return True
        except Exception as e:
            print(f"设置媒体时出错: {e}")
            import traceback
            traceback.print_exc()
            self.current_media = None
            return False
    
    def set_window(self, window_id):
        """
        设置视频输出窗口
        
        Args:
            window_id: 窗口句柄（平台特定）
        """
        if sys.platform.startswith('linux'):  # Linux
            self.player.set_xwindow(window_id)
        elif sys.platform == "win32":  # Windows
            self.player.set_hwnd(window_id)
        elif sys.platform == "darwin":  # MacOS
            self.player.set_nsobject(int(window_id))
    
    def clear_window(self):
        """
        清除视频输出窗口，避免重复创建导致的错误
        """
        try:
            if sys.platform.startswith('linux'):  # Linux
                self.player.set_xwindow(0)
            elif sys.platform == "win32":  # Windows
                self.player.set_hwnd(0)
            elif sys.platform == "darwin":  # MacOS
                self.player.set_nsobject(0)
        except Exception as e:
            print(f"清除视频输出窗口失败: {e}")
    
    def play(self):
        """
        开始播放
        
        Returns:
            bool: 是否成功开始播放
        """
        if not self.current_media:
            print("错误：没有设置媒体文件")
            return False
        
        if self.is_paused:
            # 从暂停状态恢复
            result = self.player.play()
            if result == 0:
                self.is_playing = True
                self.is_paused = False
            return result == 0
        else:
            # 开始新的播放
            result = self.player.play()
            if result == 0:
                self.is_playing = True
                self.is_paused = False
                # 设置音量和播放速率
                self.set_volume(self.volume)
                self.set_rate(self.rate)
            return result == 0
    
    def pause(self):
        """
        暂停播放
        """
        if self.is_playing:
            self.player.pause()
            self.is_playing = False
            self.is_paused = True
    
    def stop(self):
        """
        停止播放
        """
        self.player.stop()
        self.is_playing = False
        self.is_paused = False
        self.position = 0
        self.time = 0
        # 清除视频输出窗口，释放资源
        self.clear_window()
    
    def set_position(self, position):
        """
        设置播放位置
        
        Args:
            position (float): 位置 (0.0-1.0)
        """
        if 0.0 <= position <= 1.0:
            self.player.set_position(position)
            self.position = position
            if self.duration > 0:
                self.time = int(position * self.duration)
    
    def set_time(self, time_ms):
        """
        设置播放时间
        
        Args:
            time_ms (int): 时间（毫秒）
        """
        if 0 <= time_ms <= self.duration:
            self.player.set_time(time_ms)
            self.time = time_ms
            if self.duration > 0:
                self.position = time_ms / self.duration
    
    def set_volume(self, volume):
        """
        设置音量
        
        Args:
            volume (int): 音量 (0-100)
        """
        if 0 <= volume <= 100:
            self.volume = volume
            self.player.audio_set_volume(volume)
    
    def set_loop(self, loop):
        """
        设置是否循环播放
        
        Args:
            loop (bool): 是否循环播放
        """
        # 存储循环播放标志
        self.loop = loop
        # 设置媒体循环选项
        if self.current_media:
            try:
                if loop:
                    self.current_media.add_option(':loop')
                else:
                    self.current_media.add_option(':no-loop')
            except Exception as e:
                print(f"设置媒体循环选项失败: {e}")
    
    def set_rate(self, rate):
        """
        设置播放速率
        
        Args:
            rate (float): 播放速率 (0.25-4.0)
        """
        # VLC支持的速率范围通常为0.25-4.0
        if 0.25 <= rate <= 4.0:
            self.rate = rate
            self.player.set_rate(rate)
    
    def get_media_info(self):
        """
        获取媒体信息
        
        Returns:
            dict: 媒体信息
        """
        info = {
            'path': self.media_path,
            'filename': os.path.basename(self.media_path),
            'duration': self.duration,
            'is_playing': self.is_playing,
            'is_paused': self.is_paused,
            'position': self.position,
            'time': self.time,
            'volume': self.volume,
            'rate': self.rate
        }
        
        if self.current_media:
            # 尝试获取更多媒体信息，使用try-except处理可能不存在的Meta属性
            try:
                # 不同VLC版本的Meta属性可能不同，使用数字常量更可靠
                info['title'] = self.current_media.get_meta(0) or ''  # 0 = title
                info['artist'] = self.current_media.get_meta(1) or ''  # 1 = artist
                info['album'] = self.current_media.get_meta(4) or ''  # 4 = album
            except AttributeError:
                # 如果Meta属性访问失败，忽略并使用默认值
                pass
        
        return info
    
    def cleanup(self):
        """
        清理资源
        """
        self.stop()
        
        # 释放媒体资源
        if self.current_media:
            self.current_media.release()
        
        # 释放播放器资源
        self.player.release()
        self.instance.release()