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

import os
import platform
import sys

# 直接使用项目内置的libvlc.dll，不使用系统VLC
vlc_core_path = os.path.dirname(__file__)
libvlc_path = os.path.join(vlc_core_path, 'libvlc.dll')

# 检查VLC核心文件是否存在
vlc_files = ['libvlc.dll', 'libvlccore.dll']
missing_files = []
for file in vlc_files:
    if not os.path.exists(os.path.join(vlc_core_path, file)):
        missing_files.append(file)

if missing_files:
    print(f"[PlayerCore] 错误: 找不到必要的VLC核心文件: {missing_files}")
    vlc_loaded = False
else:
    # 修改系统PATH，确保VLC依赖的DLL能被找到
    os.environ['PATH'] = vlc_core_path + ';' + os.environ['PATH']
    
    # 尝试导入和初始化VLC
    try:
        import ctypes
        import vlc
        
        # 检查插件目录是否存在
        plugins_path = os.path.join(vlc_core_path, 'plugins')
        if not os.path.exists(plugins_path):
            print(f"[PlayerCore] 警告: 找不到VLC插件目录，路径: {plugins_path}")
            print(f"[PlayerCore] 提示: VLC需要plugins目录才能正常工作")
        
        vlc_loaded = True
    except Exception as e:
        print(f"[PlayerCore] 错误: 无法初始化VLC库 - {e}")
        vlc_loaded = False


class PlayerCore:
    """
    媒体播放器核心类
    基于 Python-VLC 实现，仅负责视频画面渲染
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
        基于 Python-VLC 实现，仅负责视频画面渲染
        """
        # 媒体对象
        self._media = None
        
        # 播放状态标志
        self._is_playing = False
        
        # 窗口句柄
        self._window_handle = None
        
        # 媒体时长缓存
        self._duration = 0
        
        # VLC实例和播放器
        self._instance = None
        self._player = None
        
        # 检查VLC库是否加载成功
        global vlc_loaded
        if not vlc_loaded:
            print("[PlayerCore] 警告: VLC库未加载成功，播放器功能不可用")
            return
            
        try:
            # 初始化VLC实例，禁用硬件解码以解决H.264解码错误
            self._instance = vlc.Instance([
                '--lua-config=lut_filter{lut_file=""}',
                '--avcodec-hw=none'
            ])
            
            # 检查VLC实例是否创建成功
            if not self._instance:
                print("[PlayerCore] 错误: 无法创建VLC实例")
                return
            
            # 初始化媒体播放器
            self._player = self._instance.media_player_new()
            
            # 检查媒体播放器是否创建成功
            if not self._player:
                print("[PlayerCore] 错误: 无法创建媒体播放器")
                return
            
        except Exception as e:
            print(f"[PlayerCore] 错误: 初始化VLC播放器失败 - {e}")
            import traceback
            traceback.print_exc()
    
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
            return self._player.get_time() if self._player else 0
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
            if not self._player:
                return 0
            
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
            return self._player.get_position() if self._player else 0.0
        except Exception:
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
            # 检查VLC实例和播放器是否初始化成功
            if not self._instance or not self._player:
                return False
                
            # 创建新的媒体对象
            self._media = self._instance.media_new(file_path)
            
            # 设置媒体到播放器
            self._player.set_media(self._media)
            
            # 开始异步解析媒体信息
            self._media.parse_with_options(vlc.MediaParseFlag.network, 1000)  # 1秒超时
            
            # 重置时长缓存
            self._duration = 0
            
            return True
        except Exception as e:
            print(f"[PlayerCore] 错误: 设置媒体失败 - {e}")
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
    
    def play(self):
        """
        开始播放媒体

        Returns:
            bool: 播放成功返回 True，否则返回 False
        """
        try:
            # 检查VLC实例和播放器是否初始化成功
            if not self._instance or not self._player:
                return False
                
            # 确保媒体已设置
            if not self._media:
                return False
            
            # 开始播放
            result = self._player.play()
            if result == 0:
                self._is_playing = True
            return result == 0
        except Exception:
            return False
    
    def pause(self):
        """
        暂停播放媒体
        """
        try:
            # 检查VLC播放器是否初始化成功
            if not self._player:
                return
                
            # 切换暂停状态
            self._player.pause()
            # 更新播放状态
            self._is_playing = not self._is_playing
        except Exception:
            pass
    
    def stop(self):
        """
        停止播放媒体
        """
        try:
            # 检查VLC播放器是否初始化成功
            if not self._player:
                self._is_playing = False
                return
                
            self._player.stop()
            self._is_playing = False
        except Exception:
            self._is_playing = False
            pass
    
    def set_position(self, position):
        """
        设置播放位置
        
        Args:
            position (float): 播放位置，范围 0.0 到 1.0
        """
        try:
            # 检查VLC播放器是否初始化成功
            if not self._player:
                return
                
            # 确保位置在有效范围内
            position = max(0.0, min(1.0, position))
            self._player.set_position(position)
        except Exception:
            pass
    
    def set_speed(self, speed):
        """
        设置播放速度
        
        Args:
            speed (float): 播放速度，范围 0.1 到 10.0
        """
        try:
            # 检查VLC播放器是否初始化成功
            if not self._player:
                return
                
            # 确保速度在有效范围内
            speed = max(0.1, min(10.0, speed))
            self._player.set_rate(speed)
        except Exception:
            pass
    
    def set_volume(self, volume):
        """
        设置音量
        
        Args:
            volume (int): 音量值，范围 0 到 100
        """
        try:
            # 检查VLC播放器是否初始化成功
            if not self._player:
                return
                
            # 确保音量在有效范围内
            volume = max(0, min(100, volume))
            self._player.audio_set_volume(volume)
        except Exception:
            pass
    
    def set_window(self, window_id):
        """
        将媒体播放器绑定到指定窗口
        
        Args:
            window_id: 窗口句柄，根据平台不同类型可能不同
        """
        try:
            # 检查VLC播放器是否初始化成功
            if not self._player:
                return
                
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
            # 检查VLC播放器是否初始化成功
            if not self._player:
                self._window_handle = None
                return
                
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
            self._window_handle = None
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
                try:
                    self._media.release()
                except Exception:
                    pass
                self._media = None
            
            # 释放媒体播放器
            if self._player:
                try:
                    self._player.release()
                except Exception:
                    pass
                self._player = None
            
            # 释放 VLC 实例
            if self._instance:
                try:
                    self._instance.release()
                except Exception:
                    pass
                self._instance = None
        except Exception:
            pass
    
    def video_set_filter(self, filter_name, filter_param=None):
        """
        设置或移除VLC视频滤镜
        
        Args:
            filter_name (str): 滤镜名称，如"cube"或"lut_filter"
            filter_param (str, optional): 滤镜参数，如"file=path/to/cube.cube"。如果为None或空字符串，则移除滤镜
        """
        try:
            if not self._player:
                return
            
            # 获取媒体对象
            media = self._player.get_media()
            if not media:
                return
            
            # 停止当前播放
            self._player.stop()
            
            # 获取当前媒体路径
            current_mrl = media.get_mrl()
            if not current_mrl:
                return
            
            # 创建新的媒体对象
            new_media = self._instance.media_new(current_mrl)
            
            # 处理滤镜设置
            if filter_param and filter_name in ["cube", "lut_filter"]:
                # 处理cube或lut_filter滤镜
                cube_path = filter_param.split('=')[1] if '=' in filter_param else filter_param
                lua_config = f'lut_filter{{lut_file="{cube_path}"}}'
                new_media.add_option(':video-filter=lut_filter')
                new_media.add_option(f':lua-config={lua_config}')
                # 更新标志位
                self._cube_filter_enabled = True
            elif not filter_param:
                # 移除滤镜
                new_media.add_option(':video-filter=')
                # 更新标志位
                if hasattr(self, '_cube_filter_enabled'):
                    self._cube_filter_enabled = False
            
            # 设置新的媒体到播放器
            self._player.set_media(new_media)
        except Exception as e:
            print(f"[PlayerCore] 错误: 设置滤镜失败 - {e}")
            import traceback
            traceback.print_exc()
    
    def enable_cube_filter(self, cube_path):
        """
        启用Cube色彩映射滤镜
        
        Args:
            cube_path (str): Cube文件的绝对路径
        """
        try:
            if not self._player or not cube_path:
                return False
            
            # 停止当前播放
            self._player.stop()
            
            # 获取媒体对象
            current_media = self._player.get_media()
            if not current_media:
                return False
            
            # 使用Lua滤镜，更新滤镜配置
            lua_config = f'lut_filter{{lut_file="{cube_path}"}}'
            
            # 重新设置媒体并添加滤镜选项
            current_mrl = current_media.get_mrl()
            new_media = self._instance.media_new(current_mrl)
            new_media.add_option(':video-filter=lut_filter')
            new_media.add_option(f':lua-config={lua_config}')
            
            # 设置新的媒体到播放器
            self._player.set_media(new_media)
            
            # 设置标志位，表示Cube滤镜已启用
            self._cube_filter_enabled = True
            return True
        except Exception as e:
            print(f"[PlayerCore] 错误: 启用Cube滤镜失败 - {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def disable_cube_filter(self):
        """
        禁用Cube色彩映射滤镜
        """
        try:
            if not self._player:
                return
            
            # 停止当前播放
            self._player.stop()
            
            # 获取媒体对象
            current_media = self._player.get_media()
            if not current_media:
                return
            
            # 重新创建媒体对象，不添加滤镜选项
            current_mrl = current_media.get_mrl()
            new_media = self._instance.media_new(current_mrl)
            new_media.add_option(':video-filter=')
            
            # 设置新的媒体到播放器
            self._player.set_media(new_media)
            
            # 重置标志位，表示Cube滤镜已禁用
            self._cube_filter_enabled = False
        except Exception as e:
            print(f"[PlayerCore] 错误: 禁用Cube滤镜失败 - {e}")
            import traceback
            traceback.print_exc()
    
    @property
    def is_cube_filter_enabled(self):
        """
        检查Cube滤镜是否已启用
        
        Returns:
            bool: Cube滤镜是否已启用
        """
        # VLC Python绑定没有直接检查滤镜状态的方法
        # 我们通过尝试获取滤镜列表来判断
        try:
            if not self._player:
                return False
            
            # 注意：VLC Python绑定可能不支持直接获取滤镜列表
            # 这里我们通过检查当前使用的滤镜参数来判断
            # 由于无法直接获取，我们使用一个简单的标志位来跟踪
            # 注意：这是一个简化实现，实际项目中可能需要更复杂的状态管理
            return hasattr(self, '_cube_filter_enabled') and self._cube_filter_enabled
        except Exception:
            return False
    
    def __del__(self):
        """
        析构函数，确保资源被正确释放
        """
        self.cleanup()