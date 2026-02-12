#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

时间线生成器核心模块
负责时间线数据的加载、处理和合并算法
"""

import os
import sys
import csv
import concurrent.futures
from itertools import groupby

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from PySide6.QtCore import (
    Qt, QDateTime, QThread, Signal
)


# 核心数据结构：原始事件
def get_video_duration(file_path):
    """
    获取视频文件的真实时长（秒）
    
    Args:
        file_path: str - 视频文件路径
        
    Returns:
        float - 视频时长（秒），如果无法获取则返回默认值60秒
    """
    default_duration = 60.0
    
    # 尝试使用moviepy（如果可用）
    try:
        from moviepy.editor import VideoFileClip
        with VideoFileClip(file_path) as clip:
            return clip.duration
    except Exception:
        pass
    
    # 尝试使用opencv-python（如果可用）
    try:
        import cv2
        cap = cv2.VideoCapture(file_path)
        if cap.isOpened():
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            fps = cap.get(cv2.CAP_PROP_FPS)
            if frame_count > 0 and fps > 0:
                return frame_count / fps
            cap.release()
    except Exception:
        pass
    
    return default_duration

class TimelineEvent:
    """
    封装单一事件的时间戳、关联视频路径及基础属性
    """
    def __init__(self, name, device, start_time, end_time, videos=None):
        self.name = name
        self.device = device
        self.start_time = start_time  # QDateTime 对象
        self.end_time = end_time      # QDateTime 对象
        self.videos = videos or []


# 核心数据结构：聚合后的事件（用于 UI 渲染的一行）
class MergedEvent:
    """
    存储经过合并算法处理后的多段式事件，维护视频列表索引
    """
    def __init__(self, name, device):
        self.name = name
        self.device = device
        # 存储多个片段：[(start, end, [videos]), ...]
        self.segments = [] 

    def add_segment(self, start, end, videos):
        """添加一个事件片段"""
        self.segments.append((start, end, videos))


# 核心数据结构：全局状态配置
class TimelineParams:
    """
    采用单例模式/解耦设计，管理 DPI 缩放、行高、像素比等核心参数
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            # 初始化默认参数
            cls._instance.px_per_second = 1.0  # 每秒像素数，控制缩放
            cls._instance.row_height = 45       # 每行高度
            cls._instance.gap_threshold = 30    # 默认容差值
            cls._instance.gap_threshold_unit = 'sec'  # 默认容差单位：秒
            cls._instance.global_start_time = None  # 全局起始时间
            cls._instance.global_end_time = None    # 全局结束时间
            cls._instance.dpi_scale = 1.0        # DPI缩放因子
        return cls._instance
        
    @property
    def gap_threshold_seconds(self):
        """获取容差值（秒）"""
        if self.gap_threshold_unit == 'min':
            return self.gap_threshold * 60
        elif self.gap_threshold_unit == 'hour':
            return self.gap_threshold * 3600
        else:  # 'sec'
            return self.gap_threshold


# 异步文件夹扫描线程
class FolderScanner(QThread):
    """
    使用QThread执行文件扫描与CSV读写，确保UI线程响应速度
    增强版支持生成特定格式的CSV和JSON记录
    """
    scan_finished = Signal(list, str, str)  # 扫描完成后发送结果：事件列表、CSV路径、JSON路径
    progress = Signal(int, int)  # 进度信号：已完成数量，总数
    
    def __init__(self, path):
        super().__init__()
        self.path = path
        self.data_timeline_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'timeline')
        
        # 确保data/timeline目录存在
        if not os.path.exists(self.data_timeline_dir):
            os.makedirs(self.data_timeline_dir)
    
    def run(self):
        """扫描文件夹，生成TimelineEvent列表，并创建CSV和JSON记录"""
        results = []
        video_files = []  # 存储所有需要处理的视频文件信息
        subfolder_set = set()  # 跟踪所有子文件夹名称
        main_folder_name = os.path.basename(self.path)
        
        # 增加详细日志
        print(f"=== 开始扫描文件夹: {self.path} ===")
        print(f"文件夹存在: {os.path.exists(self.path)}")
        print(f"文件夹可访问: {os.access(self.path, os.R_OK)}")
        
        # 1. 首先扫描所有视频文件，收集信息
        try:
            for root, dirs, files in os.walk(self.path):
                print(f"\n  正在扫描目录: {root}")
                print(f"  子目录数量: {len(dirs)}")
                print(f"  文件数量: {len(files)}")
                print(f"  文件列表: {files}")
                
                # 确定当前子文件夹名称
                if root == self.path:
                    subfolder_name = main_folder_name  # 直接在主文件夹下的视频
                else:
                    subfolder_name = os.path.basename(root)
                
                # 记录子文件夹名称
                subfolder_set.add(subfolder_name)
                
                for file in files:
                    print(f"\n    检查文件: {file}")
                    
                    # 检查文件扩展名（不区分大小写）
                    file_lower = file.lower()
                    if file_lower.endswith(('.mp4', '.avi', '.mov', '.wmv', '.mkv', '.flv', '.webm', '.mpg', '.mpeg', '.mxf')):
                        print(f"    匹配视频文件: {file}")
                        file_path = os.path.join(root, file)
                        print(f"    文件路径: {file_path}")
                        print(f"    文件存在: {os.path.exists(file_path)}")
                        print(f"    文件可访问: {os.access(file_path, os.R_OK)}")
                        
                        try:
                            # 获取文件元数据
                            stat = os.stat(file_path)
                            mod_time = int(stat.st_mtime)
                            
                            # 收集视频文件信息
                            video_files.append((file, file_path, subfolder_name, mod_time))
                        except Exception as e:
                            print(f"    获取文件信息出错 {file_path}: {e}")
                            import traceback
                            traceback.print_exc()
                    else:
                        print(f"    不是视频文件（扩展名不匹配）")
        except Exception as e:
            print(f"扫描过程中出错: {e}")
            import traceback
            traceback.print_exc()
            
        video_count = len(video_files)
        print(f"\n=== 扫描完成，开始并发处理视频文件 ===")
        print(f"找到的视频文件数量: {video_count}")
        
        # 2. 使用多线程并发处理视频时长计算
        if video_count > 0:
            # 定义线程池大小（根据CPU核心数或固定数量）
            max_workers = min(8, os.cpu_count() or 4)
            
            processed_count = 0
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                # 提交所有视频处理任务
                future_to_video = {
                    executor.submit(self._process_single_video, file_info): file_info 
                    for file_info in video_files
                }
                
                # 处理完成的任务
                for future in concurrent.futures.as_completed(future_to_video):
                    video_info = future_to_video[future]
                    try:
                        event = future.result()
                        if event:
                            results.append(event)
                    except Exception as e:
                        file_name, file_path, *_ = video_info
                        print(f"处理视频文件 {file_name} 时出错: {e}")
                        import traceback
                        traceback.print_exc()
                    
                    # 更新进度
                    processed_count += 1
                    self.progress.emit(processed_count, video_count)
        
        print(f"\n=== 所有视频文件处理完成 ===")
        print(f"成功处理的视频文件数量: {len(results)}")
        print(f"子文件夹数量: {len(subfolder_set)}")
        print(f"子文件夹列表: {list(subfolder_set)}")
        
        # 生成CSV文件
        csv_path = self._generate_csv(results, main_folder_name)
        
        # 生成JSON记录
        json_path = self._generate_json(main_folder_name, video_count, subfolder_set, results)
        
        self.scan_finished.emit(results, csv_path, json_path)
        
    def _generate_csv(self, events, main_folder_name):
        """
        生成特定格式的CSV文件
        每行包含：主文件夹名称、子文件夹名称、每个视频的修改时间、每个视频的修改时间+视频时长的时间、文件原始路径
        """
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_file_name = f"{main_folder_name}_{timestamp}.csv"
        csv_path = os.path.join(self.data_timeline_dir, csv_file_name)
        
        fieldnames = ['main_folder', 'subfolder', 'modification_time', 'end_time', 'file_path']
        
        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for event in events:
                for video_path in event.videos:
                    row = {
                        'main_folder': main_folder_name,
                        'subfolder': event.device,  # event.device 存储的是子文件夹名称
                        'modification_time': event.start_time.toString("yyyy-MM-dd HH:mm:ss"),
                        'end_time': event.end_time.toString("yyyy-MM-dd HH:mm:ss"),
                        'file_path': video_path
                    }
                    writer.writerow(row)
        
        print(f"CSV文件已生成: {csv_path}")
        return csv_path
    
    def _process_single_video(self, video_info):
        """
        处理单个视频文件，计算时长并创建TimelineEvent
        
        Args:
            video_info: tuple - (file_name, file_path, subfolder_name, mod_time)
            
        Returns:
            TimelineEvent or None - 处理成功返回事件对象，失败返回None
        """
        file_name, file_path, subfolder_name, mod_time = video_info
        
        try:
            # 获取视频真实时长
            duration = get_video_duration(file_path)
            
            # 创建时间对象
            start_time = QDateTime.fromSecsSinceEpoch(mod_time)
            end_time = QDateTime.fromSecsSinceEpoch(mod_time + int(duration))
            
            # 为每个视频创建一个TimelineEvent
            event = TimelineEvent(
                name=file_name,  # 使用文件名作为事件名称
                device=subfolder_name,  # 使用子文件夹名称作为设备
                start_time=start_time,
                end_time=end_time,
                videos=[file_path]
            )
            
            print(f"    成功创建视频事件: {file_name}")
            print(f"    事件设备: {subfolder_name}")
            print(f"    事件开始时间: {start_time.toString()}")
            print(f"    事件结束时间: {end_time.toString()}")
            print(f"    视频时长: {duration:.2f} 秒")
            
            return event
        except Exception as e:
            print(f"    处理文件 {file_name} 时出错: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _generate_json(self, main_folder_name, video_count, subfolder_set, events):
        """
        生成JSON记录文件
        记录：主文件夹的路径、文件总数、子文件夹名称和数量、创建csv时间等信息
        """
        import datetime
        import json
        
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        json_file_name = f"{main_folder_name}_{timestamp}.json"
        json_path = os.path.join(self.data_timeline_dir, json_file_name)
        
        # 收集处理过的文件名
        processed_files = []
        for event in events:
            for video_path in event.videos:
                processed_files.append(os.path.basename(video_path))
        
        json_data = {
            'main_folder_path': self.path,
            'main_folder_name': main_folder_name,
            'file_total_count': video_count,
            'subfolder_count': len(subfolder_set),
            'subfolder_names': list(subfolder_set),
            'creation_time': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'processed_files': processed_files
        }
        
        with open(json_path, 'w', encoding='utf-8') as jsonfile:
            json.dump(json_data, jsonfile, ensure_ascii=False, indent=2)
        
        print(f"JSON记录已生成: {json_path}")
        return json_path


# 异步CSV解析线程
class CSVParser(QThread):
    """
    异步解析CSV文件，生成TimelineEvent列表
    """
    finished = Signal(list)  # 解析完成后发送结果
    progress = Signal(int, int)  # 进度信号：已完成数量，总数
    
    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path
    
    def run(self):
        """解析CSV文件，生成TimelineEvent列表"""
        results = []
        
        try:
            # 先计算总行数（不包括标题行）
            with open(self.file_path, 'r', encoding='utf-8') as f:
                line_count = sum(1 for _ in f) - 1  # 减去标题行
            
            processed_count = 0
            
            with open(self.file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                # 智能列匹配
                fieldnames = reader.fieldnames
                name_col = None
                device_col = None
                start_col = None
                end_col = None
                video_col = None
                
                # 匹配列名
                for col in fieldnames:
                    col_lower = col.lower()
                    if any(keyword in col_lower for keyword in ['event', 'name', '事件']):
                        name_col = col
                    elif any(keyword in col_lower for keyword in ['device', '设备', 'subfolder']):
                        device_col = col
                    elif any(keyword in col_lower for keyword in ['start', '开始', 'modification_time']):
                        start_col = col
                    elif any(keyword in col_lower for keyword in ['end', '结束']):
                        end_col = col
                    elif any(keyword in col_lower for keyword in ['video', 'path', '路径', 'file_path']):
                        video_col = col
                
                # 解析每行数据
                for row in reader:
                    try:
                        # 如果没有name列，使用文件路径的文件名作为名称
                        if name_col and row.get(name_col):
                            name = row.get(name_col, 'Unknown')
                        elif video_col and row.get(video_col):
                            name = os.path.basename(row[video_col])
                        else:
                            name = 'Unknown'
                        
                        # 解析时间
                        start_time = self.parse_datetime(row[start_col])
                        
                        # 解析时长
                        duration_sec = 60  # 默认60秒
                        if end_col:
                            end_time = self.parse_datetime(row[end_col])
                            duration_sec = start_time.secsTo(end_time)
                        else:
                            # 从文件路径获取真实时长
                            if video_col and row.get(video_col):
                                video_path = row[video_col]
                                duration_sec = int(get_video_duration(video_path))
                                end_time = start_time.addSecs(duration_sec)
                            else:
                                end_time = start_time.addSecs(duration_sec)
                        
                        videos = []
                        device = 'Default'  # 默认设备/文件夹
                        
                        if video_col and row.get(video_col):
                            video_path = row[video_col]
                            videos = [video_path]
                            
                            # 从文件路径中提取文件夹信息作为device
                            if device_col is None or not row.get(device_col):
                                device = os.path.basename(os.path.dirname(video_path))
                        
                        # 如果CSV中有device列，使用该值
                        if device_col and row.get(device_col):
                            device = row.get(device_col)
                        
                        event = TimelineEvent(name, device, start_time, end_time, videos)
                        results.append(event)
                    except Exception as e:
                        print(f"Error parsing row {row}: {e}")
                        continue
                    finally:
                        # 更新进度
                        processed_count += 1
                        self.progress.emit(processed_count, line_count)
        except Exception as e:
            print(f"Error reading CSV file: {e}")
        
        self.finished.emit(results)
    
    def parse_datetime(self, datetime_str):
        """
        智能解析时间字符串
        支持ISO 8601、Unix时间戳及常见的自定义日期格式
        """
        # 尝试Unix时间戳
        try:
            timestamp = int(datetime_str)
            return QDateTime.fromSecsSinceEpoch(timestamp)
        except ValueError:
            pass
        
        # 尝试ISO 8601格式
        try:
            return QDateTime.fromString(datetime_str, Qt.ISODate)
        except ValueError:
            pass
        
        # 尝试常见的自定义格式
        formats = [
            'yyyy-MM-dd HH:mm:ss',
            'yyyy/MM/dd HH:mm:ss',
            'MM/dd/yyyy HH:mm:ss',
            'dd/MM/yyyy HH:mm:ss',
            'yyyy-MM-dd',
            'yyyy/MM/dd',
            'MM/dd/yyyy',
            'dd/MM/yyyy'
        ]
        
        for fmt in formats:
            try:
                return QDateTime.fromString(datetime_str, fmt)
            except ValueError:
                continue
        
        # 如果都失败，返回当前时间
        return QDateTime.currentDateTime()


# CSV生成器
def generate_csv_from_events(events, csv_path):
    """
    从TimelineEvent列表生成CSV文件
    
    Args:
        events: List[TimelineEvent] - 事件列表
        csv_path: str - 输出CSV文件路径
    """
    # 定义CSV字段
    fieldnames = ['event_name', 'device', 'start_time', 'end_time', 'video_path']
    
    with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        # 写入表头
        writer.writeheader()
        
        # 写入数据
        for event in events:
            for video_path in event.videos:
                row = {
                    'event_name': event.name,
                    'device': event.device,
                    'start_time': event.start_time.toString(Qt.ISODate),
                    'end_time': event.end_time.toString(Qt.ISODate),
                    'video_path': video_path
                }
                writer.writerow(row)

# 智能合并算法
def merge_logic(events, gap_threshold_seconds):
    """
    智能合并事件的核心算法
    
    Args:
        events: List[TimelineEvent] - 原始事件列表
        gap_threshold_seconds: int - 容差值（秒）
        
    Returns:
        List[MergedEvent] - 合并后的事件列表，按device分组
    """
    if not events: return []
    
    # 排序：按设备（子文件夹）-> 开始时间
    sorted_events = sorted(events, key=lambda x: (x.device, x.start_time.toMSecsSinceEpoch()))
    
    # 按设备分组，每个设备对应一个轨道
    device_grouped = groupby(sorted_events, key=lambda x: x.device)
    
    merged_results = []
    
    for device, device_events in device_grouped:
        # 转换为列表以便处理
        device_event_list = list(device_events)
        
        # 按开始时间排序
        device_event_list.sort(key=lambda x: x.start_time.toMSecsSinceEpoch())
        
        # 创建合并事件（使用子文件夹名称作为名称）
        merged = MergedEvent(device, device)
        
        if not device_event_list:
            continue
        
        # 初始化当前合并段
        curr_start = device_event_list[0].start_time
        curr_end = device_event_list[0].end_time
        curr_vids = list(device_event_list[0].videos)
        
        # 遍历所有事件，合并重叠或接近的事件
        for i in range(1, len(device_event_list)):
            next_ev = device_event_list[i]
            gap = curr_end.secsTo(next_ev.start_time)
            
            if gap <= gap_threshold_seconds:
                # 合并事件
                curr_end = max(curr_end, next_ev.end_time)
                curr_vids.extend(next_ev.videos)
            else:
                # 添加当前合并段
                merged.add_segment(curr_start, curr_end, list(set(curr_vids)))
                # 开始新的合并段
                curr_start = next_ev.start_time
                curr_end = next_ev.end_time
                curr_vids = list(next_ev.videos)
        
        # 添加最后一个合并段
        merged.add_segment(curr_start, curr_end, list(set(curr_vids)))
        merged_results.append(merged)
    
    return merged_results