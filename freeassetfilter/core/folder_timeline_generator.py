#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

文件夹时间轴生成器
根据文件夹结构生成时间轴组件所需的CSV数据
"""

import os
import sys
import csv
import json
import datetime
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple, Optional

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))


class FolderTimelineGenerator:
    """文件夹时间轴生成器"""
    
    def __init__(self):
        """初始化生成器"""
        self.video_extensions = ['.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.mxf']
        self.time_format = "%Y-%m-%d %H:%M:%S"
    
    def generate_timeline_csv(self, folder_path: str, output_csv_path: str, progress_callback=None) -> Tuple[bool, str]:
        """
        根据文件夹结构生成时间轴CSV
        
        Args:
            folder_path: 要处理的文件夹路径
            output_csv_path: 输出CSV文件路径
            progress_callback: 进度回调函数，接收两个参数：当前进度和总进度
            
        Returns:
            Tuple[bool, str]: (是否成功, 结果消息)
        """
        try:
            # 验证输入文件夹是否存在
            if not os.path.exists(folder_path):
                return False, f"输入文件夹不存在：{folder_path}"
            
            if not os.path.isdir(folder_path):
                return False, f"输入路径不是文件夹：{folder_path}"
            
            # 收集时间轴数据
            timeline_data = self._collect_timeline_data(folder_path, progress_callback)
            
            if not timeline_data:
                return False, "未找到任何视频文件或子文件夹"
            
            # 写入CSV文件
            self._write_csv(output_csv_path, timeline_data)
            
            return True, f"成功生成时间轴CSV：{output_csv_path}"
            
        except Exception as e:
            return False, f"生成失败：{str(e)}"
    
    def _collect_timeline_data(self, folder_path: str, progress_callback=None) -> List[Dict[str, str]]:
        """
        收集时间轴数据
        
        Args:
            folder_path: 要处理的文件夹路径
            progress_callback: 进度回调函数
            
        Returns:
            List[Dict[str, str]]: 时间轴数据列表
        """
        timeline_data = []
        
        # 遍历子文件夹，计算总任务数
        subfolders = []
        total_videos = 0
        for subfolder_name in os.listdir(folder_path):
            subfolder_path = os.path.join(folder_path, subfolder_name)
            
            if os.path.isdir(subfolder_path):
                subfolders.append(subfolder_name)
                video_files = self._get_video_files(subfolder_path)
                total_videos += len(video_files)
        
        total_tasks = len(subfolders) + total_videos  # 子文件夹解析 + 视频文件处理
        current_progress = 0
        
        # 遍历子文件夹
        for subfolder_name in subfolders:
            subfolder_path = os.path.join(folder_path, subfolder_name)
            
            # 解析子文件夹名称
            event_name, device_name = self._parse_folder_name(subfolder_name)
            current_progress += 1
            
            # 收集该子文件夹下的视频文件信息
            video_files = self._get_video_files(subfolder_path)
            
            for video_path in video_files:
                # 获取视频文件信息
                creation_time, duration_seconds = self._get_video_info(video_path)
                current_progress += 1
                
                if creation_time and duration_seconds:
                    # 计算结束时间
                    end_time = creation_time + datetime.timedelta(seconds=duration_seconds)
                    
                    # 添加到时间轴数据
                    timeline_data.append({
                        'event_name': event_name,
                        'device_name': device_name,
                        'start_time': creation_time.strftime(self.time_format),
                        'end_time': end_time.strftime(self.time_format)
                    })
                
                # 更新进度
                if progress_callback:
                    progress_callback(current_progress, total_tasks)
        
        # 按开始时间排序
        timeline_data.sort(key=lambda x: x['start_time'])
        
        return timeline_data
    
    def _parse_folder_name(self, folder_name: str) -> Tuple[str, str]:
        """
        解析文件夹名称，用'-'分隔成事件名称和设备名称
        
        Args:
            folder_name: 文件夹名称
            
        Returns:
            Tuple[str, str]: (事件名称, 设备名称)
        """
        if '-' in folder_name:
            event_name, device_name = folder_name.split('-', 1)  # 只分割第一个'-'
            return event_name.strip(), device_name.strip()
        else:
            return folder_name.strip(), ""
    
    def _get_video_files(self, folder_path: str) -> List[str]:
        """
        获取文件夹下所有视频文件
        
        Args:
            folder_path: 文件夹路径
            
        Returns:
            List[str]: 视频文件路径列表
        """
        video_files = []
        
        # 递归遍历文件夹
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                file_path = os.path.join(root, file)
                file_ext = os.path.splitext(file)[1].lower()
                
                if file_ext in self.video_extensions:
                    video_files.append(file_path)
        
        return video_files
    
    def _get_video_info(self, video_path: str) -> Tuple[Optional[datetime.datetime], Optional[float]]:
        """
        获取视频文件信息（创建时间和时长）
        
        Args:
            video_path: 视频文件路径
            
        Returns:
            Tuple[Optional[datetime.datetime], Optional[float]]: (创建时间, 时长秒数)
        """
        try:
            # 获取文件创建时间
            creation_time = datetime.datetime.fromtimestamp(os.path.getctime(video_path))
            
            # 获取视频时长
            duration_seconds = self._get_video_duration(video_path)
            
            # 如果无法获取视频时长，使用默认值10秒
            if duration_seconds is None:
                duration_seconds = 10.0
            
            return creation_time, duration_seconds
            
        except Exception as e:
            print(f"获取视频信息失败 {video_path}: {str(e)}")
            return None, None
    
    def _get_video_duration(self, video_path: str) -> Optional[float]:
        """
        获取视频时长（秒）
        
        Args:
            video_path: 视频文件路径
            
        Returns:
            Optional[float]: 视频时长（秒），如果获取失败返回None
        """
        # 尝试使用ffprobe获取视频时长
        try:
            cmd = [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                video_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, encoding='utf-8')
            data = json.loads(result.stdout)
            
            if "format" in data and "duration" in data["format"]:
                return float(data["format"]["duration"])
            
        except (subprocess.SubprocessError, json.JSONDecodeError) as e:
            # 如果ffprobe失败，尝试使用其他方法
            try:
                # 尝试使用OpenCV获取时长
                import cv2
                cap = cv2.VideoCapture(video_path)
                if cap.isOpened():
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                    if fps > 0:
                        return frame_count / fps
                    cap.release()
            except ImportError:
                # OpenCV未安装，尝试使用moviepy
                try:
                    from moviepy.editor import VideoFileClip
                    clip = VideoFileClip(video_path)
                    duration = clip.duration
                    clip.close()
                    return duration
                except ImportError:
                    # 所有方法都失败，返回None
                    pass
        
        return None
    
    def _write_csv(self, output_path: str, timeline_data: List[Dict[str, str]]) -> None:
        """
        写入CSV文件
        
        Args:
            output_path: 输出CSV文件路径
            timeline_data: 时间轴数据列表
        """
        # 创建输出目录（如果不存在）
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        # 写入CSV
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['事件名称', '设备名称', '开始时间', '结束时间']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            
            # 写入表头
            writer.writeheader()
            
            # 写入数据
            for data in timeline_data:
                writer.writerow({
                    '事件名称': data['event_name'],
                    '设备名称': data['device_name'],
                    '开始时间': data['start_time'],
                    '结束时间': data['end_time']
                })


if __name__ == "__main__":
    # 测试代码
    import argparse
    
    parser = argparse.ArgumentParser(description='根据文件夹结构生成时间轴CSV')
    parser.add_argument('folder_path', help='要处理的文件夹路径')
    parser.add_argument('output_csv', help='输出CSV文件路径')
    
    args = parser.parse_args()
    
    # 简单的进度回调函数
    def progress_callback(current, total):
        print(f"进度: {current}/{total} ({(current/total)*100:.1f}%)")
    
    generator = FolderTimelineGenerator()
    success, message = generator.generate_timeline_csv(args.folder_path, args.output_csv, progress_callback)
    
    if success:
        print(f"成功: {message}")
        sys.exit(0)
    else:
        print(f"失败: {message}")
        sys.exit(1)
