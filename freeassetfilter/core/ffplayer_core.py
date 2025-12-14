#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

基于ffmpeg的视频播放核心类
提供高性能的媒体播放功能和LUT色彩映射支持
"""

import os
import threading
import time
import queue
import subprocess
import ffmpeg
import numpy as np
import cv2
from PyQt5.QtCore import QObject, pyqtSignal


class FFPlayerCore(QObject):
    """
    基于ffmpeg的视频播放核心类
    仅负责视频画面渲染
    """
    
    # 支持的视频和音频格式
    SUPPORTED_VIDEO_FORMATS = ['.mp4', '.mov', '.m4v', '.flv', '.mxf', '.3gp', 
                              '.mpg', '.avi', '.wmv', '.mkv', '.webm', '.vob', 
                              '.ogv', '.rmvb']
    SUPPORTED_AUDIO_FORMATS = ['.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma', 
                              '.m4a', '.aiff', '.ape', '.opus']
    
    # 硬件加速类型优先级顺序
    HARDWARE_ACCEL_TYPES = ['cuda', 'dxva2', 'd3d11va', 'qsv', 'vaapi', 'vdpau', 'none']
    
    # 信号定义
    frame_available = pyqtSignal(np.ndarray)  # 新视频帧可用
    
    def __init__(self):
        """
        初始化FFPlayerCore
        仅负责视频画面渲染
        """
        super().__init__()
        
        # 播放状态
        self._is_playing = False
        self._is_paused = False
        self._current_time = 0
        self._duration = 0
        self._position = 0.0
        self._file_path = ""
        self._speed = 1.0  # 播放速度
        self._volume = 50  # 音量，范围0-100
        
        # 视频参数
        self._video_width = 0
        self._video_height = 0
        self._fps = 0
        self._video_codec = ""
        self._frame_queue = queue.Queue(maxsize=30)
        
        # 音频参数
        self._audio_stream = None
        self._audio_codec = None
        
        # 解码线程
        self._decode_thread = None
        self._is_decoding = False
        self._seek_position = None
        self._seek_event = threading.Event()
        
        # LUT色彩映射
        self._lut_enabled = False
        self._lut_data = None
        self._lut_path = ""
        
        # 硬件加速
        self._hardware_accel = self._detect_hardware_accel()
        print(f"[FFPlayerCore] 检测到硬件加速: {self._hardware_accel}")
        
    def __del__(self):
        """
        析构函数，确保资源被正确释放
        """
        self.stop()
    
    @property
    def is_playing(self) -> bool:
        """
        获取当前播放状态
        
        Returns:
            bool: 是否正在播放
        """
        return self._is_playing
    
    @property
    def time(self) -> int:
        """
        获取当前播放时间（毫秒）
        
        Returns:
            int: 当前播放时间，单位毫秒
        """
        return self._current_time
    
    @property
    def duration(self) -> int:
        """
        获取媒体总时长（毫秒）
        
        Returns:
            int: 媒体总时长，单位毫秒
        """
        return self._duration
    
    @property
    def position(self) -> float:
        """
        获取当前播放位置（0.0 - 1.0）
        
        Returns:
            float: 当前播放位置，范围 0.0 到 1.0
        """
        return self._position
    
    def load_media(self, file_path: str) -> bool:
        """
        加载媒体文件
        
        Args:
            file_path (str): 媒体文件路径
            
        Returns:
            bool: 加载成功返回 True，否则返回 False
        """
        try:
            # 停止当前播放
            self.stop()
            
            # 检查文件是否存在
            if not os.path.exists(file_path):
                print(f"[FFPlayerCore] 文件不存在: {file_path}")
                return False
            
            # 保存文件路径
            self._file_path = file_path
            
            # 获取媒体信息
            probe = ffmpeg.probe(file_path)
            
            # 获取视频流
            video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
            
            if not video_stream:
                print(f"[FFPlayerCore] 未找到视频流")
                return False
            
            # 获取视频参数
            self._video_width = int(video_stream['width'])
            self._video_height = int(video_stream['height'])
            
            # 安全解析帧率，避免使用eval()
            frame_rate_str = video_stream.get('r_frame_rate', '0/1')
            try:
                if '/' in frame_rate_str:
                    numerator, denominator = map(int, frame_rate_str.split('/'))
                    if denominator != 0:
                        self._fps = numerator / denominator
                    else:
                        self._fps = 0.0
                else:
                    self._fps = float(frame_rate_str)
            except (ValueError, ZeroDivisionError):
                print(f"[FFPlayerCore] 警告: 无法解析帧率 '{frame_rate_str}'，使用默认值 24.0")
                self._fps = 24.0
            
            # 获取视频编码格式
            self._video_codec = video_stream.get('codec_name', 'unknown')
            print(f"[FFPlayerCore] 检测到视频编码: {self._video_codec}")
            
            # 获取音频流（如果有）
            self._audio_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'audio'), None)
            if self._audio_stream:
                self._audio_codec = self._audio_stream.get('codec_name', 'unknown')
                print(f"[FFPlayerCore] 检测到音频编码: {self._audio_codec}")
            else:
                self._audio_codec = None
                print(f"[FFPlayerCore] 未检测到音频流")
            
            # 获取总时长
            if 'duration' in probe['format']:
                self._duration = int(float(probe['format']['duration']) * 1000)
            else:
                # 尝试从视频流获取时长
                if 'duration' in video_stream:
                    self._duration = int(float(video_stream['duration']) * 1000)
                else:
                    self._duration = 0
            
            return True
        except Exception as e:
            print(f"[FFPlayerCore] 加载媒体失败: {e}")
            return False
    
    def play(self) -> bool:
        """
        开始播放媒体
        
        Returns:
            bool: 播放成功返回 True，否则返回 False
        """
        try:
            if not self._file_path:
                return False
            
            if self._is_playing:
                return True
            
            self._is_paused = False
            self._is_playing = True
            
            # 启动解码线程
            if not self._decode_thread or not self._decode_thread.is_alive():
                self._is_decoding = True
                self._decode_thread = threading.Thread(target=self._decode_loop, daemon=True)
                self._decode_thread.start()
            
            return True
        except Exception as e:
            print(f"[FFPlayerCore] 播放失败: {e}")
            self._is_playing = False
            return False
    
    def pause(self) -> bool:
        """
        暂停播放媒体
        
        Returns:
            bool: 暂停成功返回 True，否则返回 False
        """
        try:
            self._is_paused = not self._is_paused
            
            if not self._is_paused and not self._is_playing:
                return self.play()
            
            if self._is_paused and self._is_playing:
                self._is_playing = False
            
            return True
        except Exception as e:
            print(f"[FFPlayerCore] 暂停失败: {e}")
            return False
    
    def stop(self) -> bool:
        """
        停止播放媒体
        
        Returns:
            bool: 停止成功返回 True，否则返回 False
        """
        try:
            self._is_playing = False
            self._is_paused = False
            self._is_decoding = False
            
            # 清空帧队列
            while not self._frame_queue.empty():
                try:
                    self._frame_queue.get_nowait()
                except queue.Empty:
                    break
            
            # 等待解码线程结束
            if self._decode_thread and self._decode_thread.is_alive():
                # 检查是否是当前线程，如果是则不等待，避免死锁
                current_thread = threading.current_thread()
                if self._decode_thread.ident != current_thread.ident:
                    self._decode_thread.join(1.0)
            
            # 重置解码线程，确保下次播放时重新创建
            self._decode_thread = None
            
            # 重置LUT数据，释放内存
            self._lut_data = None
            self._lut_path = ""
            self._lut_enabled = False
            
            # 重置状态
            self._current_time = 0
            self._position = 0.0
            self._video_width = 0
            self._video_height = 0
            self._fps = 0
            self._duration = 0
            
            return True
        except Exception as e:
            print(f"[FFPlayerCore] 停止失败: {e}")
            return False
    
    def set_position(self, position: float) -> bool:
        """
        设置播放位置
        
        Args:
            position (float): 播放位置，范围 0.0 到 1.0
            
        Returns:
            bool: 设置成功返回 True，否则返回 False
        """
        try:
            if not self._file_path or self._duration == 0:
                return False
            
            # 确保位置在有效范围内
            position = max(0.0, min(1.0, position))
            
            # 设置seek位置
            self._seek_position = position
            self._seek_event.set()
            
            return True
        except Exception as e:
            print(f"[FFPlayerCore] 设置播放位置失败: {e}")
            return False
    
    def set_speed(self, speed: float) -> bool:
        """
        设置播放速度
        
        Args:
            speed (float): 播放速度，范围 0.1 到 10.0
            
        Returns:
            bool: 设置成功返回 True，否则返回 False
        """
        try:
            # 确保速度在有效范围内
            self._speed = max(0.1, min(10.0, speed))
            return True
        except Exception as e:
            print(f"[FFPlayerCore] 设置播放速度失败: {e}")
            return False
    
    def set_volume(self, volume: int) -> bool:
        """
        设置音量
        
        Args:
            volume (int): 音量值，范围 0 到 100
            
        Returns:
            bool: 设置成功返回 True，否则返回 False
        """
        try:
            # 确保音量在有效范围内
            self._volume = max(0, min(100, volume))
            return True
        except Exception as e:
            print(f"[FFPlayerCore] 设置音量失败: {e}")
            return False
    
    def _detect_hardware_accel(self):
        """
        检测可用的硬件加速
        
        Returns:
            str: 可用的硬件加速类型，如'cuda', 'dxva2', 'none'等
        """
        # 首先获取所有可用的硬件加速类型
        available_accels = []
        try:
            cmd = "ffmpeg -hide_banner -hwaccels"
            process = subprocess.Popen(
                cmd, 
                shell=True, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            stdout, _ = process.communicate(timeout=5)
            
            # 解析输出，提取硬件加速类型
            for line in stdout.strip().split('\n'):
                line = line.strip()
                if line and not line.startswith('--'):
                    available_accels.append(line.lower())
        except (subprocess.TimeoutExpired, Exception):
            available_accels = []
        
        # 按照优先级顺序检查可用的硬件加速
        for accel_type in self.HARDWARE_ACCEL_TYPES:
            if accel_type == 'none':
                return accel_type
            
            if accel_type.lower() in available_accels:
                # 进一步验证该加速类型是否可用
                try:
                    test_cmd = f"ffmpeg -hide_banner -f lavfi -i color=c=red:size=16x16:rate=1 -c:v libx264 -hwaccel {accel_type} -t 1 -f null -"
                    process = subprocess.Popen(
                        test_cmd, 
                        shell=True, 
                        stdout=subprocess.PIPE, 
                        stderr=subprocess.PIPE
                    )
                    _, stderr = process.communicate(timeout=5)
                    if process.returncode == 0:
                        return accel_type
                except (subprocess.TimeoutExpired, Exception):
                    continue
        return 'none'
    
    def _decode_loop(self):
        """
        视频解码循环
        """
        while self._is_decoding:
            try:
                # 检查是否需要seek
                seek_time = None
                if self._seek_event.is_set():
                    if self._seek_position is not None:
                        seek_time = self._seek_position * self._duration / 1000.0
                        self._seek_position = None
                    self._seek_event.clear()
                
                # 创建ffmpeg输入流
                input_kwargs = {}
                
                # MXF文件特定处理
                if self._file_path.lower().endswith('.mxf'):
                    input_kwargs['format'] = 'mxf'
                    input_kwargs['probe_size'] = '2G'  # 增大探测大小以处理大型MXF文件
                    input_kwargs['analyzeduration'] = '100M'  # 增加分析时长
                
                if seek_time is not None:
                    # 带seek的输入流
                    stream = ffmpeg.input(self._file_path, ss=seek_time, **input_kwargs)
                else:
                    # 正常输入流
                    stream = ffmpeg.input(self._file_path, **input_kwargs)
                
                # 只解码视频流
                stream = stream.video
                
                # 输出原始视频帧
                output_kwargs = {
                    'format': 'rawvideo',
                    'pix_fmt': 'bgr24',
                    'threads': 'auto',
                    'strict': 'experimental',
                    'max_muxing_queue_size': 4096,
                    'vsync': '0',
                    'hwaccel_output_format': 'cuda' if self._hardware_accel == 'cuda' else None
                }
                
                # 移除None值的参数
                output_kwargs = {k: v for k, v in output_kwargs.items() if v is not None}
                
                # 设置硬件加速
                if self._hardware_accel != 'none':
                    stream = stream.global_args('-hwaccel', self._hardware_accel)
                    
                    # 根据不同的硬件加速类型添加特定参数
                    if self._hardware_accel in ['dxva2', 'd3d11va']:
                        stream = stream.global_args('-hwaccel_device', '0')
                    elif self._hardware_accel == 'qsv':
                        stream = stream.global_args('-qsv_device', 'auto')
                
                # 输出原始视频帧
                stream = ffmpeg.output(
                    stream,
                    'pipe:',
                    **output_kwargs
                )
                
                # 运行ffmpeg进程
                try:
                    process = ffmpeg.run_async(
                        stream,
                        pipe_stdout=True,
                        pipe_stderr=True,
                        quiet=True
                    )
                except Exception as e:
                    print(f"[FFPlayerCore] 启动ffmpeg进程失败: {e}")
                    continue
                
                # 解码循环
                start_time = time.time()
                if seek_time is not None:
                    # 如果是seek，调整start_time以反映seek的位置
                    start_time -= seek_time
                frame_index = 0
                
                while self._is_decoding and process.poll() is None:
                    # 检查是否需要seek
                    if self._seek_event.is_set():
                        break
                    
                    # 读取一帧数据
                    expected_frame_size = self._video_width * self._video_height * 3
                    raw_frame = process.stdout.read(expected_frame_size)
                    
                    if not raw_frame:
                        break
                    
                    if len(raw_frame) != expected_frame_size:
                        break
                    
                    # 转换为numpy数组
                    try:
                        frame = np.frombuffer(raw_frame, np.uint8)
                        frame = frame.reshape([self._video_height, self._video_width, 3])
                    except Exception as e:
                        print(f"[FFPlayerCore] 帧转换失败: {e}")
                        break
                    
                    # 应用LUT色彩映射
                    if self._lut_enabled and self._lut_data is not None:
                        frame = self._apply_lut(frame)
                    
                    # 计算当前播放时间
                    current_time = int((time.time() - start_time) * 1000)
                    self._current_time = current_time
                    if self._duration > 0:
                        self._position = min(1.0, current_time / self._duration)
                    
                    # 如果正在播放，将帧放入队列
                    if self._is_playing and not self._is_paused:
                        try:
                            # 非阻塞放入，避免队列满时阻塞
                            self._frame_queue.put(frame, block=False)
                            # 发送新帧可用信号
                            self.frame_available.emit(frame)
                        except queue.Full:
                            # 队列满，丢弃最旧的帧
                            try:
                                self._frame_queue.get_nowait()
                                self._frame_queue.put(frame, block=False)
                                self.frame_available.emit(frame)
                            except:
                                pass
                    
                    # 控制播放速度
                    frame_index += 1
                    expected_time = frame_index / (self._fps * self._speed)
                    actual_time = time.time() - start_time
                    if actual_time < expected_time:
                        time.sleep(expected_time - actual_time)
                
                # 关闭ffmpeg进程
                try:
                    process.stdout.close()
                except:
                    pass
                
                try:
                    process.stderr.close()
                except:
                    pass
                
                process.wait()
                
                # 如果是正常播放结束，停止播放
                if not self._seek_event.is_set() and self._is_decoding:
                    self.stop()
                    break
                    
            except Exception as e:
                print(f"[FFPlayerCore] 解码失败: {e}")
                time.sleep(0.1)
    
    def _read_cube_lut(self, lut_path: str) -> np.ndarray:
        """
        读取.cube格式的LUT文件
        
        Args:
            lut_path (str): LUT文件路径
            
        Returns:
            np.ndarray: LUT数据，形状为 (size, size, size, 3) 或 None
        """
        try:
            with open(lut_path, 'r') as f:
                lines = f.readlines()
            
            # 解析LUT文件
            lut_data = []
            size = None
            
            for line in lines:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                if line.startswith('LUT_3D_SIZE'):
                    size = int(line.split(' ')[1])
                elif line.startswith('DOMAIN_MIN') or line.startswith('DOMAIN_MAX'):
                    continue
                else:
                    # 读取LUT数据
                    values = list(map(float, line.split()))
                    if len(values) == 3:
                        lut_data.append(values)
            
            if size is None or len(lut_data) != size * size * size:
                return None
            
            # 转换为numpy数组
            lut_array = np.array(lut_data, dtype=np.float32)
            lut_array = lut_array.reshape(size, size, size, 3)
            
            return lut_array
        except Exception as e:
            print(f"[FFPlayerCore] 读取LUT文件失败: {e}")
            return None
    
    def _apply_lut(self, frame: np.ndarray) -> np.ndarray:
        """
        应用LUT色彩映射到视频帧
        
        Args:
            frame (np.ndarray): 输入视频帧，形状为 (height, width, 3)
            
        Returns:
            np.ndarray: 应用LUT后的视频帧
        """
        try:
            if self._lut_data is None:
                return frame
            
            # 将帧转换为浮点数，范围0.0-1.0
            frame_float = frame.astype(np.float32) / 255.0
            
            # 获取LUT大小
            lut_size = self._lut_data.shape[0]
            
            # 计算LUT索引
            lut_index = frame_float * (lut_size - 1)
            
            # 获取整数索引和插值权重
            i0 = np.floor(lut_index).astype(np.int32)
            i1 = np.minimum(i0 + 1, lut_size - 1)
            
            # 计算插值权重
            t = lut_index - i0.astype(np.float32)
            
            # 进行三线性插值
            # 沿R轴插值
            c00 = self._lut_data[i0[:,:,0], i0[:,:,1], i0[:,:,2]]
            c10 = self._lut_data[i1[:,:,0], i0[:,:,1], i0[:,:,2]]
            c01 = self._lut_data[i0[:,:,0], i1[:,:,1], i0[:,:,2]]
            c11 = self._lut_data[i1[:,:,0], i1[:,:,1], i0[:,:,2]]
            
            c0 = c00 * (1 - t[:,:,0:1]) + c10 * t[:,:,0:1]
            c1 = c01 * (1 - t[:,:,0:1]) + c11 * t[:,:,0:1]
            
            # 沿G轴插值
            c = c0 * (1 - t[:,:,1:2]) + c1 * t[:,:,1:2]
            
            # 沿B轴插值
            c00 = self._lut_data[i0[:,:,0], i0[:,:,1], i1[:,:,2]]
            c10 = self._lut_data[i1[:,:,0], i0[:,:,1], i1[:,:,2]]
            c01 = self._lut_data[i0[:,:,0], i1[:,:,1], i1[:,:,2]]
            c11 = self._lut_data[i1[:,:,0], i1[:,:,1], i1[:,:,2]]
            
            c0 = c00 * (1 - t[:,:,0:1]) + c10 * t[:,:,0:1]
            c1 = c01 * (1 - t[:,:,0:1]) + c11 * t[:,:,0:1]
            
            c_b = c0 * (1 - t[:,:,1:2]) + c1 * t[:,:,1:2]
            
            # 最终插值
            final_color = c * (1 - t[:,:,2:3]) + c_b * t[:,:,2:3]
            
            # 转换回8位整数
            final_color = np.clip(final_color * 255.0, 0, 255).astype(np.uint8)
            
            return final_color
        except Exception as e:
            print(f"[FFPlayerCore] 应用LUT失败: {e}")
            return frame
