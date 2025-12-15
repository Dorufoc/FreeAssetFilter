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
from PyQt5.QtCore import QObject

# 获取当前文件所在目录（core目录）
core_path = os.path.dirname(os.path.abspath(__file__))

# 将core目录添加到系统PATH中，确保能找到libmpv-2.dll
os.environ['PATH'] = core_path + os.pathsep + os.environ['PATH']

# 尝试导入和初始化MPV
mpv_loaded = False
try:
    import mpv
    print(f"[MPVPlayerCore] 成功导入 python-mpv 库，版本: {mpv.__version__ if hasattr(mpv, '__version__') else '未知'}")
    mpv_loaded = True
except Exception as e:
    print(f"[MPVPlayerCore] 错误: 无法导入 python-mpv 库 - {e}")
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
                              '.ogv', '.rmvb']
    SUPPORTED_AUDIO_FORMATS = ['.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma', 
                              '.m4a', '.aiff', '.ape', '.opus']
    
    def __init__(self):
        """
        初始化MPV播放器核心
        基于 python-mpv 实现，仅负责视频画面渲染
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
        
        # 检查MPV库是否加载成功
        if not mpv_loaded:
            print("[MPVPlayerCore] 警告: MPV库未加载成功，播放器功能不可用")
            return
            
        try:
            print("[MPVPlayerCore] 开始初始化MPV实例...")
            # 初始化MPV实例 - 配置为内嵌播放模式
            # 使用更简单的配置，减少初始化失败风险
            self._mpv = mpv.MPV(
                # 禁用硬件加速，避免兼容性问题
                hwdec='no',
                # 禁用标题栏
                title='',
                # 禁用MPV的OSD
                osd_level='0',
                # 禁用MPV的控制面板
                input_default_bindings='no',
                input_vo_keyboard='no',
                # 启用音频输出
                audio='auto',
                # 设置视频输出模块为gpu-next，确保LUT滤镜正常工作
                vo='gpu-next'
            )
            print("[MPVPlayerCore] MPV实例初始化成功")
            
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 初始化MPV播放器失败 - {e}")
            import traceback
            traceback.print_exc()
            self._mpv = None
    
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
                self._is_playing = not bool(self._mpv.pause)
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
                return int(self._mpv.time_pos * 1000)
            return 0
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
            if not self._mpv:
                return 0
            
            # 优先使用缓存的时长
            if self._duration > 0:
                return self._duration
            
            # 从MPV获取时长（秒转换为毫秒）
            duration = int(self._mpv.duration * 1000) if self._mpv.duration else 0
            if duration > 0:
                self._duration = duration
            return duration
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
            if self._mpv and self.duration > 0:
                return self._mpv.time_pos / (self.duration / 1000) if self._mpv.time_pos else 0.0
            return 0.0
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
            current_pause = bool(self._mpv.pause)
            print(f"[MPVPlayerCore] 播放前状态: pause={current_pause}, is_playing={self._is_playing}")
            
            # 如果已经在播放，不要重新开始
            if not current_pause and self._is_playing:
                print(f"[MPVPlayerCore] 已经在播放，不需要重新开始")
                return True
            
            # 如果是暂停状态，只恢复播放，不重新开始
            if current_pause:
                print(f"[MPVPlayerCore] 从暂停状态恢复播放")
                self._mpv.pause = False
                self._is_playing = True
                return True
            
            # 开始播放新媒体
            print(f"[MPVPlayerCore] 开始播放媒体: {self._media}")
            self._mpv.play(self._media)
            self._is_playing = True
            return True
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
                
            # 安全获取当前暂停状态
            current_pause = bool(self._mpv.pause)
            # 切换暂停状态
            self._mpv.pause = not current_pause
            # 更新播放状态
            self._is_playing = not self._mpv.pause
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
                
            self._mpv.stop()
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
            # 检查MPV实例是否初始化成功
            if not self._mpv:
                return
                
            # 确保位置在有效范围内
            position = max(0.0, min(1.0, position))
            
            print(f"[MPVPlayerCore] 设置播放位置: position={position}, percent={position*100}%")
            
            # 使用秒为单位进行seek，更可靠
            # 获取当前时长（秒）
            current_time = self._mpv.time_pos if hasattr(self._mpv, 'time_pos') and self._mpv.time_pos is not None else 0.0
            duration = self._mpv.duration if hasattr(self._mpv, 'duration') and self._mpv.duration is not None else 0.0
            
            print(f"[MPVPlayerCore] 当前状态: time_pos={current_time}, duration={duration}")
            
            if duration > 0:
                # 使用秒为单位进行seek
                seek_pos = position * duration
                print(f"[MPVPlayerCore] 使用秒seek: seek_pos={seek_pos}s")
                self._mpv.seek(seek_pos, reference='absolute')
            else:
                # 使用百分比seek作为备选
                print(f"[MPVPlayerCore] 使用百分比seek: {position*100}%")
                self._mpv.seek(position * 100, reference='absolute-percent')
                
            # 验证seek结果
            new_time = self._mpv.time_pos if hasattr(self._mpv, 'time_pos') and self._mpv.time_pos is not None else 0.0
            print(f"[MPVPlayerCore] Seek结果: new_time={new_time}s")
        except Exception as e:
            print(f"[MPVPlayerCore] 警告: 设置播放位置失败 - {e}")
            import traceback
            traceback.print_exc()
            # 保留原位置，不做任何改变
    
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
            self._mpv.speed = speed
        except Exception:
            pass
    
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
            self._mpv.volume = volume
        except Exception:
            pass
    
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
            self._mpv.wid = window_id
            print("[MPVPlayerCore] 窗口绑定成功")
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 设置窗口失败 - {e}")
            import traceback
            traceback.print_exc()
            pass
    
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
            self._mpv.wid = None
            
            # 清除窗口句柄
            self._window_handle = None
        except Exception:
            self._window_handle = None
            pass
    
    def cleanup(self):
        """
        清理资源，释放 MPV 实例
        """
        try:
            # 停止播放
            self.stop()
            
            # 清除窗口绑定
            self.clear_window()
            
            # 释放MPV实例
            if self._mpv:
                try:
                    self._mpv.terminate()
                except Exception:
                    pass
                self._mpv = None
        except Exception:
            pass
    

    
    def process_chinese_path(self, raw_path: str) -> str:
        """
        处理带中文/空格的路径：
        1. 给路径加英文双引号（解决空格被解析为参数分隔符的问题）
        2. 确保路径格式正确，避免编码问题
        
        Args:
            raw_path (str): 原始路径
            
        Returns:
            str: 处理后的路径
        """
        # 步骤1：确保路径使用正斜杠，避免MPV解析问题
        normalized_path = raw_path.replace('\\', '/')
        # 步骤2：加英文双引号（格式："原始路径"）
        wrapped_path = f'"{normalized_path}"'
        return wrapped_path

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
            
            # 更新标志位和当前Cube路径
            self._cube_filter_enabled = True
            self._current_cube_path = cube_path
            
            print(f"[MPVPlayerCore] 尝试启用Cube滤镜，文件路径: {cube_path}")
            
            # 检查文件是否存在
            if not os.path.exists(cube_path):
                print(f"[MPVPlayerCore] 错误: Cube文件不存在: {cube_path}")
                return False
            
            # 检查文件内容，确保是有效的Cube文件
            try:
                with open(cube_path, 'r') as f:
                    content = f.read()
                print(f"[MPVPlayerCore] Cube文件内容前500字符: {content[:500]}")
            except Exception as e:
                print(f"[MPVPlayerCore] 无法读取Cube文件: {e}")
                return False
            
            # 首先移除所有视频滤镜，避免冲突
            try:
                self._mpv.command('vf', 'remove', 'all')
                print(f"[MPVPlayerCore] 已移除所有视频滤镜")
            except Exception as e:
                print(f"[MPVPlayerCore] 移除所有视频滤镜失败: {e}")
            
            # 处理Cube路径（中文/空格）
            processed_cube_path = self.process_chinese_path(cube_path)
            
            # 尝试使用load glsl-shaders命令（推荐方法，适用于vo=gpu-next）
            try:
                print(f"[MPVPlayerCore] 尝试使用load glsl-shaders命令")
                # 执行load glsl-shaders命令
                self._mpv.command('load', 'glsl-shaders', processed_cube_path)
                print(f"[MPVPlayerCore] 成功使用load glsl-shaders命令加载滤镜")
                return True
            except Exception as e:
                print(f"[MPVPlayerCore] load glsl-shaders命令失败: {e}")
            
            # 尝试使用vfilter属性设置滤镜
            try:
                print(f"[MPVPlayerCore] 尝试使用vfilter属性设置滤镜")
                # 确保路径格式正确，去掉引号后再添加，避免重复引号
                normalized_path = cube_path.replace('\\', '/')
                filter_str = f'lut3d=file="{normalized_path}"'
                print(f"[MPVPlayerCore] 尝试设置vfilter: {filter_str}")
                self._mpv.vfilter = filter_str
                print(f"[MPVPlayerCore] 成功使用vfilter属性设置滤镜")
                return True
            except Exception as e:
                print(f"[MPVPlayerCore] vfilter属性设置失败: {e}")
                print(f"[MPVPlayerCore] 错误类型: {type(e).__name__}")
            
            # 尝试使用vf add命令
            try:
                print(f"[MPVPlayerCore] 尝试使用vf add命令")
                # 确保路径格式正确，去掉引号后再添加，避免重复引号
                normalized_path = cube_path.replace('\\', '/')
                # 先移除可能存在的lut3d滤镜
                try:
                    self._mpv.command('vf', 'remove', 'lut3d')
                except:
                    pass
                # 添加新的lut3d滤镜
                self._mpv.command('vf', 'add', f'lut3d=file="{normalized_path}"')
                print(f"[MPVPlayerCore] 成功使用vf add命令添加滤镜")
                return True
            except Exception as e:
                print(f"[MPVPlayerCore] vf add命令失败: {e}")
            
            # 尝试使用glsl-shaders-append选项（适用于旧版本MPV）
            try:
                print(f"[MPVPlayerCore] 尝试使用glsl-shaders-append选项")
                # 设置vo=gpu，确保glsl-shaders选项生效
                self._mpv.set_option('vo', 'gpu')
                # 使用glsl-shaders-append选项
                self._mpv.set_option('glsl-shaders-append', processed_cube_path)
                print(f"[MPVPlayerCore] 成功使用glsl-shaders-append选项加载滤镜")
                return True
            except Exception as e:
                print(f"[MPVPlayerCore] glsl-shaders-append选项失败: {e}")
            
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
            
            # 移除所有lut3d滤镜
            self._mpv.command('vf', 'remove', 'lut3d')
            
            # 更新标志位
            self._cube_filter_enabled = False
            self._current_cube_path = ""
        except Exception as e:
            print(f"[MPVPlayerCore] 错误: 禁用Cube滤镜失败 - {e}")
            import traceback
            traceback.print_exc()
    
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
