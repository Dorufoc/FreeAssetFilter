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
import json
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
        self.data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'timeline'))
        self.mapping_file = os.path.join(self.data_dir, 'timeline_mapping.json')
    
    def generate_timeline_csv(self, folder_path: str, output_csv_path: Optional[str] = None, progress_callback=None) -> Tuple[bool, str]:
        """
        根据文件夹结构生成时间轴CSV
        
        Args:
            folder_path: 要处理的文件夹路径
            output_csv_path: 输出CSV文件路径（可选，默认输出到data/timeline目录）
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
            
            # 确保data/timeline目录存在
            os.makedirs(self.data_dir, exist_ok=True)
            
            # 如果未指定输出路径，自动生成
            if not output_csv_path:
                # 使用当前时间和源文件夹名称生成唯一的CSV文件名
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                folder_name = os.path.basename(os.path.normpath(folder_path))
                csv_filename = f"timeline_{folder_name}_{timestamp}.csv"
                output_csv_path = os.path.join(self.data_dir, csv_filename)
            else:
                # 如果指定了路径但不是绝对路径，转换为绝对路径
                if not os.path.isabs(output_csv_path):
                    output_csv_path = os.path.abspath(output_csv_path)
            
            # 写入CSV文件
            self._write_csv(output_csv_path, timeline_data)
            
            # 更新JSON映射文件
            self._update_timeline_mapping(folder_path, output_csv_path)
            
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
        
        # 预扫描所有子文件夹，收集所有视频文件信息
        all_video_info = []
        
        # 遍历所有直接子文件夹
        for item in os.listdir(folder_path):
            item_path = os.path.join(folder_path, item)
            if os.path.isdir(item_path):
                folder_name = os.path.basename(item_path)
                
                # 解析文件夹名称 xxx-yyy
                event_name, device_name = self._parse_folder_name(folder_name)
                
                # 收集当前文件夹内的所有视频文件
                for root, dirs, files in os.walk(item_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        file_ext = os.path.splitext(file)[1].lower()
                        
                        if file_ext in self.video_extensions:
                            all_video_info.append({
                                'event_name': event_name,
                                'device_name': device_name,
                                'folder_name': folder_name,
                                'video_path': file_path
                            })
        
        # 基于视频文件总数计算进度
        total_tasks = len(all_video_info)
        current_progress = 0
        
        # 处理每个视频文件
        for video_info in all_video_info:
            creation_time, duration_seconds = self._get_video_info(video_info['video_path'])
            
            if creation_time and duration_seconds:
                # 计算结束时间
                end_time = creation_time + datetime.timedelta(seconds=duration_seconds)
                
                # 为每个视频文件单独创建记录
                timeline_data.append({
                    'event_name': video_info['event_name'],
                    'device_name': video_info['device_name'],
                    'folder_name': video_info['folder_name'],
                    'start_time': creation_time.strftime(self.time_format),
                    'end_time': end_time.strftime(self.time_format),
                    'video_path': video_info['video_path']
                })
            
            current_progress += 1
            
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
    
    def get_video_file_count(self, folder_path: str) -> int:
        """
        获取文件夹下所有视频文件的数量
        
        Args:
            folder_path: 文件夹路径
            
        Returns:
            int: 视频文件数量
        """
        video_files = self._get_video_files(folder_path)
        return len(video_files)
    
    def _get_video_info(self, video_path: str) -> Tuple[Optional[datetime.datetime], Optional[float]]:
        """
        获取视频文件信息（创建时间和时长）
        
        Args:
            video_path: 视频文件路径
            
        Returns:
            Tuple[Optional[datetime.datetime], Optional[float]]: (创建时间, 时长秒数)
        """
        try:
            # 获取文件修改时间
            creation_time = datetime.datetime.fromtimestamp(os.path.getmtime(video_path))
            
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
        with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
            fieldnames = ['event_name', 'device_name', 'folder_name', 'start_time', 'end_time', 'video_path']
            # 设置quoting=csv.QUOTE_ALL，确保所有字段都用引号包围，避免逗号引起的格式问题
            writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            
            # 写入中文表头
            writer.writerow({
                'event_name': '事件名称',
                'device_name': '设备名称',
                'folder_name': '文件夹名称',
                'start_time': '开始时间',
                'end_time': '结束时间',
                'video_path': '视频路径'
            })
            
            # 写入数据
            for data in timeline_data:
                writer.writerow({
                    'event_name': data['event_name'],
                    'device_name': data['device_name'],
                    'folder_name': data['folder_name'],
                    'start_time': data['start_time'],
                    'end_time': data['end_time'],
                    'video_path': data['video_path']
                })
    
    def _update_timeline_mapping(self, source_folder: str, csv_path: str) -> None:
        """
        更新时间轴映射JSON文件，记录CSV与提取来源目录路径的对应关系
        
        Args:
            source_folder: 源文件夹路径
            csv_path: 生成的CSV文件路径
        """
        # 确保映射文件目录存在
        os.makedirs(os.path.dirname(self.mapping_file), exist_ok=True)
        
        # 读取现有映射
        mapping_data = {}
        if os.path.exists(self.mapping_file):
            try:
                with open(self.mapping_file, 'r', encoding='utf-8') as f:
                    mapping_data = json.load(f)
            except (json.JSONDecodeError, IOError):
                mapping_data = {}
        
        # 标准化路径
        normalized_source = os.path.normpath(source_folder)
        normalized_csv = os.path.normpath(csv_path)
        
        # 添加或更新映射
        mapping_data[normalized_source] = {
            'csv_path': normalized_csv,
            'last_updated': datetime.datetime.now().strftime(self.time_format)
        }
        
        # 保存映射文件
        with open(self.mapping_file, 'w', encoding='utf-8') as f:
            json.dump(mapping_data, f, ensure_ascii=False, indent=2, sort_keys=True)


if __name__ == "__main__":
    # 测试代码
    import argparse
    
    parser = argparse.ArgumentParser(description='根据文件夹结构生成时间轴CSV')
    parser.add_argument('folder_path', help='要处理的文件夹路径')
    parser.add_argument('--output-csv', help='输出CSV文件路径（可选，默认输出到data/timeline目录）', default=None)
    
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
