#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

自动时间轴组件
类似非线编剪辑软件的时间管理程序，通过导入CSV文件可视化展示事件的时间分布
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

import csv
import datetime
import json
from collections import defaultdict

# 导入文件夹时间轴生成器
from freeassetfilter.core.folder_timeline_generator import FolderTimelineGenerator

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QSplitter,
    QPushButton, QLabel, QFileDialog, QMessageBox,
    QComboBox, QSpinBox, QStatusBar, QProgressDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QSizePolicy, QTextEdit
)
from freeassetfilter.widgets.custom_widgets import CustomButton
from PyQt5.QtCore import QTimer
from PyQt5.QtCore import Qt, QRect, QRectF, QPoint, QSize, QEvent
from PyQt5.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QFontMetrics,
    QTextOption, QCursor
)


class TimelineEvent:
    """时间轴事件类"""
    def __init__(self, name, device, start_time, end_time, videos=None, folder_name=None):
        self.name = name
        self.device = device
        self.start_time = start_time
        self.end_time = end_time
        self.videos = videos if videos else []  # 存储视频文件路径列表
        self.folder_name = folder_name  # 存储文件夹名称

    def duration(self):
        """返回事件持续时间（秒）"""
        return (self.end_time - self.start_time).total_seconds()
    
    def add_video(self, video_path):
        """添加视频文件路径"""
        if video_path not in self.videos:
            self.videos.append(video_path)


class MergedEvent:
    """合并后的事件类"""
    def __init__(self, name, device, folder_name=None):
        self.name = name
        self.device = device
        self.folder_name = folder_name  # 存储文件夹名称
        self.time_range_videos = []  # 存储时间范围和对应的视频文件：[(start_time, end_time, videos_list), ...]
        self.all_videos = []  # 存储该事件的所有视频文件（用于兼容旧代码）

    def add_range(self, start_time, end_time, videos=None):
        """添加时间范围和对应的视频文件"""
        videos = videos if videos else []
        self.time_range_videos.append((start_time, end_time, videos))
        # 按起始时间排序
        self.time_range_videos.sort(key=lambda x: x[0])
        
        # 更新所有视频文件列表
        for video in videos:
            if video not in self.all_videos:
                self.all_videos.append(video)
    
    def add_video(self, video_path):
        """添加视频文件路径（用于兼容旧代码）"""
        if video_path not in self.all_videos:
            self.all_videos.append(video_path)
    
    def add_videos(self, video_paths):
        """批量添加视频文件路径（用于兼容旧代码）"""
        for video_path in video_paths:
            self.add_video(video_path)
    
    @property
    def time_ranges(self):
        """返回所有时间范围（用于兼容旧代码）"""
        return [(start, end) for start, end, _ in self.time_range_videos]
    
    @property
    def videos(self):
        """返回所有视频文件（用于兼容旧代码）"""
        return self.all_videos

    def duration(self):
        """返回总持续时间（秒）"""
        total = 0
        for start, end, _ in self.time_range_videos:
            total += (end - start).total_seconds()
        return total


class AutoTimeline(QWidget):
    """自动时间轴组件"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_data()
        # 获取全局应用程序对象
        self.app = QApplication.instance()
        # 获取全局字体大小和DPI缩放因子
        self.global_font_size = getattr(self.app, 'default_font_size', 10)
        self.dpi_scale_factor = getattr(self.app, 'dpi_scale_factor', 0.5)
        # 获取全局字体
        self.global_font = getattr(self.app, 'global_font', QFont())
        self.init_settings()
        self.init_ui()
        # 设置全局字体
        self.setFont(self.global_font)
        # 初始化视图，应用全局字体设置
        self.update_view()
        
    def eventFilter(self, obj, event):
        """事件过滤器，用于捕获整个组件的滚轮事件"""
        if event.type() == QEvent.Wheel:
            # 检测Ctrl键是否被按住
            if event.modifiers() & Qt.ControlModifier:
                # 根据滚轮方向调整缩放
                delta = event.angleDelta().y()
                if delta > 0:
                    # 向上滚动，增加缩放
                    new_zoom = self.zoom_spinbox.value() + 1
                else:
                    # 向下滚动，减小缩放
                    new_zoom = self.zoom_spinbox.value() - 1
                
                # 限制缩放范围在1-200之间
                new_zoom = max(1, min(200, new_zoom))
                
                # 更新缩放控件并刷新视图
                self.zoom_spinbox.setValue(new_zoom)
                self.update_view()
                return True
        # 其他事件继续传递
        return False

    def init_ui(self):
        """初始化界面"""
        self.setWindowTitle("自动时间轴")
        self.setMinimumSize(800, 600)

        # 主布局
        main_layout = QVBoxLayout(self)

        # 顶部控制栏
        control_layout = QHBoxLayout()

        # CSV导入按钮
        self.import_btn = CustomButton("导入CSV", button_type="primary")
        self.import_btn.clicked.connect(self.import_csv)
        self.import_btn.setFont(self.global_font)
        control_layout.addWidget(self.import_btn)
        
        # 从文件夹生成时间轴按钮
        self.generate_from_folder_btn = CustomButton("从文件夹生成", button_type="primary")
        self.generate_from_folder_btn.clicked.connect(self.generate_timeline_from_folder)
        self.generate_from_folder_btn.setFont(self.global_font)
        control_layout.addWidget(self.generate_from_folder_btn)
        
        # 刷新时间轴按钮
        self.refresh_btn = CustomButton("刷新", button_type="primary")
        self.refresh_btn.clicked.connect(self.refresh_timeline)
        self.refresh_btn.setFont(self.global_font)
        control_layout.addWidget(self.refresh_btn)

        # 时间格式选择
        self.time_format_label = QLabel("时间格式：")
        self.time_format_label.setFont(self.global_font)
        control_layout.addWidget(self.time_format_label)
        self.time_format_combo = QComboBox()
        self.time_format_combo.addItems([
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%H:%M:%S"
        ])
        self.time_format_combo.setFont(self.global_font)
        control_layout.addWidget(self.time_format_combo)

        # 缩放控制
        self.zoom_label = QLabel("缩放：")
        self.zoom_label.setFont(self.global_font)
        control_layout.addWidget(self.zoom_label)
        self.zoom_spinbox = QSpinBox()
        self.zoom_spinbox.setRange(1, 200)
        self.zoom_spinbox.setValue(10)
        self.zoom_spinbox.valueChanged.connect(self.update_view)
        self.zoom_spinbox.setFont(self.global_font)
        control_layout.addWidget(self.zoom_spinbox)

        # 时间单位选择
        self.unit_label = QLabel("单位：")
        self.unit_label.setFont(self.global_font)
        control_layout.addWidget(self.unit_label)
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["秒", "分钟", "小时"])
        self.unit_combo.currentIndexChanged.connect(self.update_view)
        self.unit_combo.setFont(self.global_font)
        control_layout.addWidget(self.unit_combo)

        # 宽容度设置
        self.tolerance_label = QLabel("宽容度：")
        self.tolerance_label.setFont(self.global_font)
        control_layout.addWidget(self.tolerance_label)
        self.tolerance_combo = QComboBox()
        self.tolerance_combo.addItems(["秒", "分钟", "小时"])
        self.tolerance_combo.currentIndexChanged.connect(self.update_view)
        self.tolerance_combo.setFont(self.global_font)
        control_layout.addWidget(self.tolerance_combo)
        
        # 测试输出按钮 - 用于显示选中范围的文件列表
        self.show_selected_btn = CustomButton("显示选中文件", button_type="primary")
        self.show_selected_btn.clicked.connect(self.show_selected_files)
        self.show_selected_btn.setFont(self.global_font)
        control_layout.addWidget(self.show_selected_btn)

        control_layout.addStretch()
        main_layout.addLayout(control_layout)
        
        # 测试输出区域 - 显示选中范围的视频文件
        self.selected_files_label = QLabel("选中的视频文件：")
        self.selected_files_label.setFont(self.global_font)
        main_layout.addWidget(self.selected_files_label)
        
        self.selected_files_text = QTextEdit()
        self.selected_files_text.setReadOnly(True)
        self.selected_files_text.setMaximumHeight(100)
        self.selected_files_text.setFont(self.global_font)
        main_layout.addWidget(self.selected_files_text)

        # 左侧固定列控件
        self.timeline_left_columns = TimelineLeftColumns(global_font=self.global_font)
        
        # 右侧时间轴控件
        self.timeline_widget = TimelineWidget(global_font=self.global_font)
        
        # 创建水平布局来并列显示左侧固定列和右侧时间轴
        horizontal_layout = QHBoxLayout()
        horizontal_layout.addWidget(self.timeline_left_columns)
        horizontal_layout.addWidget(self.timeline_widget)
        horizontal_layout.setSpacing(0)
        horizontal_layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建一个容器widget来包含水平布局
        main_timeline_widget = QWidget()
        main_timeline_widget.setLayout(horizontal_layout)
        
        # 右侧时间轴滚动区域
        self.timeline_scroll_area = QScrollArea()
        self.timeline_scroll_area.setWidgetResizable(True)  # 允许时间轴控件自动调整大小
        self.timeline_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.timeline_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.timeline_scroll_area.setWidget(main_timeline_widget)
        
        # 整个时间轴区域的垂直滚动区域
        self.main_scroll_area = self.timeline_scroll_area
        
        # 存储滚动同步的标志，避免循环触发
        self.is_syncing = False
        
        main_layout.addWidget(self.main_scroll_area, 1)

        # 底部状态栏
        self.status_bar = QStatusBar()
        self.time_range_label = QLabel("时间范围：")
        self.time_range_label.setFont(self.global_font)
        self.event_count_label = QLabel("事件数量：0")
        self.event_count_label.setFont(self.global_font)
        
        # 创建水平布局用于状态栏内容
        status_layout = QHBoxLayout()
        status_layout.addWidget(self.time_range_label)
        status_layout.addStretch()
        status_layout.addWidget(self.event_count_label)
        
        # 创建一个容器widget来包含布局
        status_widget = QWidget()
        status_widget.setLayout(status_layout)
        
        # 将容器widget添加到状态栏
        self.status_bar.addWidget(status_widget, 1)
        main_layout.addWidget(self.status_bar)
        
        # 初始化延时检测定时器
        self.resize_timer = QTimer(self)
        self.resize_timer.setSingleShot(True)
        self.resize_timer.timeout.connect(self.on_resize_timer_timeout)
        
        # 安装事件过滤器，捕获整个组件的滚轮事件
        self.installEventFilter(self)
        self.main_scroll_area.installEventFilter(self)
        self.timeline_widget.installEventFilter(self)
        
        # 设置定期检测滚动同步的定时器
        self.sync_timer = QTimer(self)
        self.sync_timer.setInterval(1000)  # 每1秒检测一次
        self.sync_timer.timeout.connect(self.check_scroll_sync)
        self.sync_timer.start()
        
    def resizeEvent(self, event):
        """处理窗口大小变化事件"""
        # 重启延时检测定时器
        self.resize_timer.start(200)  # 200毫秒延时，避免窗口初始化过程中的尺寸波动
        super().resizeEvent(event)
        
    def on_resize_timer_timeout(self):
        """延时检测定时器超时处理"""
        # 计算并应用最佳缩放比例
        self.calculate_optimal_zoom()

    def init_data(self):
        """初始化数据"""
        self.events = []
        self.merged_events = []
        self.event_names = set()
        self.devices = set()
        self.current_folder_path = None  # 当前处理的文件夹路径
        self.current_csv_path = None  # 当前使用的CSV文件路径

    def init_settings(self):
        """初始化设置"""
        self.time_format = "%Y-%m-%d %H:%M:%S"
        self.pixels_per_unit = 10  # 每时间单位的像素数
        self.unit_multiplier = 1  # 秒=1, 分钟=60, 小时=3600
        self.tolerance_unit = "秒"  # 默认宽容度单位
        self.tolerance_multiplier = 1  # 宽容度单位转换因子
        # 应用DPI缩放因子到所有尺寸设置
        self.time_margin = int(10 * self.dpi_scale_factor)  # 时间轴两侧的边距
        self.name_column_width = int(200 * self.dpi_scale_factor)  # 活动名称列宽度
        self.device_column_width = int(100 * self.dpi_scale_factor)  # 设备列宽度
        self.folder_column_width = int(150 * self.dpi_scale_factor)  # 文件夹名称列宽度
        self.event_block_height = int(30 * self.dpi_scale_factor)  # 事件块高度
        self.row_spacing = int(10 * self.dpi_scale_factor)  # 行间距

    def import_csv(self):
        """导入CSV文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择CSV文件", "", "CSV Files (*.csv);;All Files (*)"
        )
        if not file_path:
            return

        try:
            self.parse_csv(file_path)
            self.merge_events()
            self.update_view()
            self.update_status()
            # 导入后自动计算并应用最佳缩放比例
            self.calculate_optimal_zoom()
            QMessageBox.information(self, "成功", "CSV文件导入成功！")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导入失败：{str(e)}")
            
    def generate_timeline_from_folder(self):
        """从文件夹生成时间轴"""
        # 选择要处理的文件夹
        folder_path = QFileDialog.getExistingDirectory(
            self, "选择文件夹", ""
        )
        if not folder_path:
            return
            
        try:
            # 保存当前文件夹路径
            self.current_folder_path = folder_path
            
            # 创建生成器实例
            generator = FolderTimelineGenerator()
            
            # 检查是否已经存在对应的CSV文件
            use_existing_csv = False
            csv_path = None
            
            # 检查映射文件
            mapping_file = os.path.join(generator.data_dir, 'timeline_mapping.json')
            if os.path.exists(mapping_file):
                try:
                    with open(mapping_file, 'r', encoding='utf-8') as f:
                        mapping_data = json.load(f)
                    
                    # 标准化路径
                    normalized_folder = os.path.normpath(folder_path)
                    
                    # 检查是否存在映射
                    if normalized_folder in mapping_data:
                        csv_path = mapping_data[normalized_folder]['csv_path']
                        if os.path.exists(csv_path):
                            # 获取当前文件夹的视频文件数量
                            current_file_count = generator.get_video_file_count(folder_path)
                            
                            # 检查CSV文件中的行数
                            with open(csv_path, 'r', encoding='utf-8') as f:
                                import csv
                                reader = csv.reader(f)
                                csv_row_count = sum(1 for row in reader) - 1  # 减去表头行
                            
                            # 如果文件数量一致，直接使用现有CSV
                            if current_file_count == csv_row_count:
                                use_existing_csv = True
                except Exception as e:
                    print(f"检查现有CSV失败：{str(e)}")
            
            if use_existing_csv and csv_path:
                # 使用现有CSV文件
                self.parse_csv(csv_path)
                self.merge_events()
                self.update_view()
                self.update_status()
                self.calculate_optimal_zoom()
                self.current_csv_path = csv_path
                QMessageBox.information(self, "成功", f"使用现有时间轴CSV：{csv_path}")
            else:
                # 创建进度条对话框
                progress_dialog = QProgressDialog("正在生成时间轴...", "取消", 0, 100, self)
                progress_dialog.setWindowTitle("生成进度")
                progress_dialog.setMinimumDuration(1000)  # 显示延迟，避免快速完成的任务闪烁
                progress_dialog.setValue(0)
                progress_dialog.setModal(True)  # 模态对话框，阻止用户操作其他窗口
                
                # 进度回调函数
                def progress_callback(current, total):
                    if total > 0:
                        percentage = int((current / total) * 100)
                        progress_dialog.setValue(percentage)
                        # 更新进度文本
                        progress_dialog.setLabelText(f"正在处理 {current}/{total} 个项目...")
                        # 处理取消操作
                        if progress_dialog.wasCanceled():
                            raise Exception("用户取消了操作")
                        # 强制应用更新
                        QApplication.processEvents()
                
                # 生成时间轴CSV（默认输出到data/timeline目录）
                success, message = generator.generate_timeline_csv(folder_path, None, progress_callback)
                
                progress_dialog.close()  # 关闭进度对话框
                
                if success:
                    # 从成功消息中提取CSV路径
                    csv_path = message.split("：")[-1].strip()
                    # 自动导入生成的CSV文件
                    self.parse_csv(csv_path)
                    self.merge_events()
                    self.update_view()
                    self.update_status()
                    # 导入后自动计算并应用最佳缩放比例
                    self.calculate_optimal_zoom()
                    self.current_csv_path = csv_path
                    QMessageBox.information(self, "成功", f"时间轴生成成功！\n{message}")
                else:
                    QMessageBox.critical(self, "错误", f"时间轴生成失败：{message}")
                    
        except Exception as e:
            QMessageBox.critical(self, "错误", f"操作失败：{str(e)}")

    def parse_csv(self, file_path):
        """解析CSV文件"""
        self.init_data()
        self.time_format = self.time_format_combo.currentText()
        
        # 设置当前CSV路径
        self.current_csv_path = os.path.normpath(file_path)
        
        # 尝试从Timeline map JSON中查找对应的文件夹路径
        self.current_folder_path = None
        try:
            # 读取映射文件
            generator = FolderTimelineGenerator()
            mapping_file = generator.mapping_file
            if os.path.exists(mapping_file):
                with open(mapping_file, 'r', encoding='utf-8') as f:
                    mapping_data = json.load(f)
                    
                # 查找当前CSV对应的文件夹路径
                for folder_path, mapping_info in mapping_data.items():
                    if os.path.normpath(mapping_info['csv_path']) == self.current_csv_path:
                        self.current_folder_path = folder_path
                        print(f"从映射文件中找到CSV对应的文件夹路径：{folder_path}")
                        break
        except Exception as e:
            print(f"读取映射文件时出错：{str(e)}")

        with open(file_path, 'r', encoding='utf-8') as f:
            # 设置quotechar='"'确保能够正确处理被双引号包围的字段
            reader = csv.reader(f, quotechar='"', delimiter=',')
            header = next(reader)  # 读取表头
            
            # 尝试自动识别列
            name_idx = -1
            device_idx = -1
            start_idx = -1
            end_idx = -1
            video_idx = -1  # 视频路径列索引
            folder_idx = -1  # 文件夹名称列索引

            for i, col in enumerate(header):
                col_lower = col.lower().strip()
                print(f"检查列: {col} -> 小写: {col_lower} (索引: {i})")
                if 'name' in col_lower or '事件' in col_lower:
                    name_idx = i
                    print(f"识别到名称列: {col} (索引: {i})")
                elif 'device' in col_lower or '设备' in col_lower:
                    device_idx = i
                    print(f"识别到设备列: {col} (索引: {i})")
                elif 'start' in col_lower or '开始' in col_lower:
                    start_idx = i
                    print(f"识别到开始时间列: {col} (索引: {i})")
                elif 'end' in col_lower or '结束' in col_lower:
                    end_idx = i
                    print(f"识别到结束时间列: {col} (索引: {i})")
                elif 'video' in col_lower or '视频' in col_lower or 'path' in col_lower or '路径' in col_lower or 'file' in col_lower or '文件' in col_lower:
                    # 尝试识别视频路径列
                    video_idx = i
                    print(f"识别到视频路径列: {col} (索引: {i})")
                elif 'folder' in col_lower or '文件夹' in col_lower:
                    # 尝试识别文件夹名称列
                    folder_idx = i
                    print(f"识别到文件夹名称列: {col} (索引: {i})")
            
            print(f"最终识别的列索引: name_idx={name_idx}, device_idx={device_idx}, start_idx={start_idx}, end_idx={end_idx}, video_idx={video_idx}, folder_idx={folder_idx}")

            if name_idx == -1 or start_idx == -1 or end_idx == -1:
                raise ValueError("无法识别CSV列：需要包含事件名称、开始时间和结束时间列")

            # 读取数据行
            for row in reader:
                if len(row) < max(name_idx, device_idx, start_idx, end_idx, video_idx if video_idx != -1 else 0, folder_idx if folder_idx != -1 else 0) + 1:
                    continue

                name = row[name_idx].strip()
                if not name:
                    continue

                device = row[device_idx].strip() if device_idx != -1 else "默认设备"
                
                try:
                    start_time = datetime.datetime.strptime(row[start_idx].strip(), self.time_format)
                    end_time = datetime.datetime.strptime(row[end_idx].strip(), self.time_format)
                except ValueError as e:
                    raise ValueError(f"时间格式错误：{str(e)}")

                if end_time <= start_time:
                    continue
                
                # 获取视频路径
                video_path = None
                if video_idx != -1 and len(row) > video_idx:
                    video_path = row[video_idx].strip()
                    print(f"  行数据中的视频路径: {video_path}")
                else:
                    print(f"  行数据中无视频路径 (video_idx: {video_idx}, 行长度: {len(row)})")
                
                # 获取文件夹名称
                folder_name = None
                if folder_idx != -1 and len(row) > folder_idx:
                    folder_name = row[folder_idx].strip()
                    print(f"  行数据中的文件夹名称: {folder_name}")
                else:
                    print(f"  行数据中无文件夹名称 (folder_idx: {folder_idx}, 行长度: {len(row)})")
                
                # 创建事件
                event = TimelineEvent(name, device, start_time, end_time, folder_name=folder_name)
                
                # 添加视频路径（如果有）
                if video_path:
                    event.add_video(video_path)
                    print(f"  添加视频路径到事件: {video_path}")
                
                print(f"  事件创建完成，视频数量: {len(event.videos)}, 文件夹名称: {folder_name}")
                
                self.events.append(event)
                self.event_names.add(name)
                self.devices.add(device)

    def _truncate_time(self, time):
        """根据宽容度单位截断时间"""
        if self.tolerance_unit == "秒":
            # 秒级宽容度：不截断，精确到秒
            return time
        elif self.tolerance_unit == "分钟":
            # 分钟级宽容度：截断到分钟，忽略秒
            return time.replace(second=0, microsecond=0)
        elif self.tolerance_unit == "小时":
            # 小时级宽容度：截断到小时，忽略分钟和秒
            return time.replace(minute=0, second=0, microsecond=0)
        return time

    def merge_events(self):
        """合并相同事件名称的时间范围，基于宽容度设置"""
        # 按事件名称和设备分组
        event_groups = defaultdict(list)
        for event in self.events:
            key = (event.name, event.device)
            event_groups[key].append(event)

        # 合并每个组内的事件
        self.merged_events = []
        for (name, device), group_events in event_groups.items():
            # 获取文件夹名称（使用组内第一个事件的文件夹名称）
            folder_name = group_events[0].folder_name if group_events else None
            merged_event = MergedEvent(name, device, folder_name=folder_name)
            
            # 按起始时间排序
            group_events.sort(key=lambda x: x.start_time)
            
            # 合并同一宽容度时间范围内的事件
            current_start = group_events[0].start_time
            current_end = group_events[0].end_time
            current_videos = group_events[0].videos.copy()  # 初始化当前范围的视频列表
            
            for event in group_events[1:]:
                # 根据宽容度截断时间
                truncated_current_end = self._truncate_time(current_end)
                truncated_event_start = self._truncate_time(event.start_time)
                
                # 如果在同一宽容度时间范围内或者有重叠，合并
                if truncated_event_start <= truncated_current_end:
                    # 合并时间范围
                    current_end = max(current_end, event.end_time)
                    # 合并视频文件列表
                    for video in event.videos:
                        if video not in current_videos:
                            current_videos.append(video)
                else:
                    # 不连续，保存当前范围并开始新范围
                    merged_event.add_range(current_start, current_end, current_videos)
                    current_start = event.start_time
                    current_end = event.end_time
                    current_videos = event.videos.copy()  # 初始化新范围的视频列表
            
            # 添加最后一个范围
            merged_event.add_range(current_start, current_end, current_videos)
            self.merged_events.append(merged_event)

        # 按事件名称排序
        self.merged_events.sort(key=lambda x: (x.name, x.device))

    def update_view(self):
        """更新视图"""
        # 更新时间单位
        unit = self.unit_combo.currentText()
        if unit == "秒":
            self.unit_multiplier = 1
        elif unit == "分钟":
            self.unit_multiplier = 60
        elif unit == "小时":
            self.unit_multiplier = 3600
        
        # 添加调试信息
        print(f"更新视图：事件数量={len(self.events)}, 合并后事件数量={len(self.merged_events)}")
        print(f"左侧列尺寸：名称列={self.name_column_width}, 设备列={self.device_column_width}")
        print(f"时间轴缩放：每单位像素数={self.pixels_per_unit}, 时间单位={unit}")
        print(f"全局字体大小：{self.global_font_size}, DPI缩放因子：{self.dpi_scale_factor}")
        
        # 更新宽容度设置
        self.tolerance_unit = self.tolerance_combo.currentText()
        if self.tolerance_unit == "秒":
            self.tolerance_multiplier = 1
        elif self.tolerance_unit == "分钟":
            self.tolerance_multiplier = 60
        elif self.tolerance_unit == "小时":
            self.tolerance_multiplier = 3600
        
        # 重新合并事件
        self.merge_events()
        
        # 更新缩放比例
        self.pixels_per_unit = self.zoom_spinbox.value()
        
        # 更新左侧固定列
        self.timeline_left_columns.set_data(self.merged_events, self.event_names, self.devices)
        self.timeline_left_columns.set_settings(
            self.time_margin,
            self.name_column_width,
            self.device_column_width,
            self.folder_column_width,
            self.event_block_height,
            self.row_spacing,
            self.global_font,  # 传递全局字体对象
            self.global_font_size,  # 传递全局字体大小
            self.dpi_scale_factor    # 传递DPI缩放因子
        )
        self.timeline_left_columns.update_table()
        
        # 更新时间轴控件
        self.timeline_widget.set_data(
            self.merged_events,
            self.event_names,
            self.devices
        )
        self.timeline_widget.set_settings(
            self.pixels_per_unit,
            self.unit_multiplier,
            self.time_margin,
            self.name_column_width,
            self.device_column_width,
            self.folder_column_width,
            self.event_block_height,
            self.row_spacing,
            self.tolerance_unit,
            self.tolerance_multiplier,
            self.global_font,  # 传递全局字体对象
            self.global_font_size,  # 传递全局字体大小
            self.dpi_scale_factor    # 传递DPI缩放因子
        )
        self.timeline_widget.update()

    def update_status(self):
        """更新状态栏"""
        if not self.events:
            self.time_range_label.setText("时间范围：")
            self.event_count_label.setText("事件数量：0")
            return

        # 计算时间范围
        all_times = []
        for event in self.events:
            all_times.append(event.start_time)
            all_times.append(event.end_time)
        min_time = min(all_times)
        max_time = max(all_times)

        self.time_range_label.setText(f"时间范围：{min_time.strftime(self.time_format)} - {max_time.strftime(self.time_format)}")
        self.event_count_label.setText(f"事件数量：{len(self.events)}（合并后：{len(self.merged_events)}）")
        
    def calculate_optimal_zoom(self):
        """根据窗口宽度计算合适的缩放比例，确保时间轴内容完整显示"""
        if not self.events:
            return
            
        # 获取可用宽度（窗口宽度减去名称列、设备列和文件夹列的宽度）
        available_width = self.width() - self.name_column_width - self.device_column_width - self.folder_column_width - self.time_margin * 2
        
        if available_width <= 0:
            return
            
        # 计算总时间（秒）
        all_times = []
        for event in self.events:
            all_times.append(event.start_time)
            all_times.append(event.end_time)
        min_time = min(all_times)
        max_time = max(all_times)
        total_time_seconds = (max_time - min_time).total_seconds()
        
        if total_time_seconds <= 0:
            return
            
        # 根据时间单位计算总时间单位数
        total_time_units = total_time_seconds / self.unit_multiplier
        
        if total_time_units <= 0:
            return
            
        # 计算最佳缩放比例（每时间单位的像素数）
        optimal_zoom = available_width / total_time_units
        
        # 限制缩放比例在合理范围内
        optimal_zoom = max(1, min(200, optimal_zoom))
        
        # 更新缩放控件并刷新视图
        self.zoom_spinbox.setValue(int(optimal_zoom))
        self.update_view()
    
    def sync_scroll(self, value):
        """同步左侧表格和右侧timeline的滚动位置"""
        if self.is_syncing:
            return
            
        try:
            self.is_syncing = True
            
            # 由于左侧和右侧都在同一个main_scroll_area中，它们应该自动同步
            # 这里添加额外的检查和调整，确保完全一致
            scrollbar = self.main_scroll_area.verticalScrollBar()
            if scrollbar.value() != value:
                scrollbar.setValue(value)
                
        finally:
            self.is_syncing = False
    
    def check_scroll_sync(self):
        """定期检测滚动位置，确保左右两侧同步"""
        # 检查左侧表格和右侧timeline的滚动位置
        scrollbar = self.main_scroll_area.verticalScrollBar()
        current_value = scrollbar.value()
        
        # 由于左侧和右侧都在同一个滚动区域中，理论上它们应该始终同步
        # 这里添加一些额外的检查，确保同步正常工作
        if scrollbar.value() != current_value:
            scrollbar.setValue(current_value)
    
    def show_selected_files(self):
        """显示选中区域内的视频文件和事件信息"""
        # 获取选中区域内的视频文件和事件信息
        videos, selected_events = self.timeline_widget.get_videos_in_selected_ranges()
        
        # 清空之前的内容
        self.selected_files_text.clear()
        
        if not selected_events:
            self.selected_files_text.append("没有选中任何事件")
            return
        
        # 显示选中的事件信息
        self.selected_files_text.append(f"共选中 {len(selected_events)} 个事件：")
        
        # 使用集合来跟踪已显示的视频，避免重复
        displayed_videos = set()
        
        for i, event in enumerate(selected_events, 1):
            self.selected_files_text.append(f"\n{i}. 事件: {event['name']}")
            self.selected_files_text.append(f"   设备: {event['device']}")
            self.selected_files_text.append(f"   时间范围: {event['start_time']} 到 {event['end_time']}")
            
            # 计算事件持续时间
            duration = event['end_time'] - event['start_time']
            hours, remainder = divmod(duration.total_seconds(), 3600)
            minutes, seconds = divmod(remainder, 60)
            self.selected_files_text.append(f"   持续时间: {int(hours)}小时{int(minutes)}分钟{int(seconds)}秒")
            
            # 显示视频文件列表
            if event['videos']:
                self.selected_files_text.append(f"   视频文件 ({len(event['videos'])} 个):")
                for video in event['videos']:
                    self.selected_files_text.append(f"     - {video}")
                    displayed_videos.add(video)
            else:
                self.selected_files_text.append(f"   视频文件: 无")
        
        # 显示所有唯一的视频文件列表
        if displayed_videos:
            self.selected_files_text.append(f"\n\n共选中 {len(displayed_videos)} 个唯一视频文件：")
            for i, video in enumerate(sorted(displayed_videos), 1):
                self.selected_files_text.append(f"{i}. {video}")
    
    def refresh_timeline(self):
        """刷新时间轴，重新生成CSV并覆盖原有文件"""
        if not self.current_folder_path:
            QMessageBox.warning(self, "警告", "没有可刷新的时间轴数据，请先从文件夹生成时间轴")
            return
            
        try:
            # 创建进度条对话框
            progress_dialog = QProgressDialog("正在刷新时间轴...", "取消", 0, 100, self)
            progress_dialog.setWindowTitle("刷新进度")
            progress_dialog.setMinimumDuration(1000)
            progress_dialog.setValue(0)
            progress_dialog.setModal(True)
            
            # 进度回调函数
            def progress_callback(current, total):
                if total > 0:
                    percentage = int((current / total) * 100)
                    progress_dialog.setValue(percentage)
                    progress_dialog.setLabelText(f"正在处理 {current}/{total} 个项目...")
                    if progress_dialog.wasCanceled():
                        raise Exception("用户取消了操作")
                    QApplication.processEvents()
            
            # 创建生成器实例
            generator = FolderTimelineGenerator()
            
            # 强制重新生成CSV文件，使用当前的CSV路径（如果存在）
            success, message = generator.generate_timeline_csv(
                self.current_folder_path, 
                self.current_csv_path,  # 指定当前CSV路径，实现覆盖
                progress_callback
            )
            
            progress_dialog.close()
            
            if success:
                # 重新解析生成的CSV文件
                self.parse_csv(self.current_csv_path)
                self.merge_events()
                self.update_view()
                self.update_status()
                self.calculate_optimal_zoom()
                QMessageBox.information(self, "成功", "时间轴刷新成功！")
            else:
                QMessageBox.critical(self, "错误", f"时间轴刷新失败：{message}")
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"操作失败：{str(e)}")


class TimelineLeftColumns(QWidget):
    """时间轴左侧固定列控件"""
    def __init__(self, parent=None, global_font=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        
        # 数据
        self.merged_events = []
        self.event_names = set()
        self.devices = set()
        
        # 设置
        self.time_margin = 10
        self.name_column_width = 200
        self.device_column_width = 100
        self.folder_column_width = 150  # 文件夹名称列宽度
        self.event_block_height = 30
        self.row_spacing = 10
        # 初始化默认的全局字体大小、DPI缩放因子和全局字体对象
        self.global_font_size = 10
        self.dpi_scale_factor = 0.5
        self.global_font = global_font or QFont()
        # 初始化默认高度，避免sizeHint方法调用时属性未定义
        self.total_height = 200  # 默认高度
        
        # 创建表格控件
        self.table_widget = QTableWidget(self)
        self.table_widget.setColumnCount(3)  # 三列：事件名称、设备和文件夹名称
        self.table_widget.setHorizontalHeaderLabels(["事件名称", "设备", "文件夹名称"])
        
        # 配置表格
        self.table_widget.horizontalHeader().setVisible(False)  # 隐藏表头
        self.table_widget.verticalHeader().setVisible(False)  # 隐藏行号
        self.table_widget.setShowGrid(False)  # 隐藏网格线
        self.table_widget.setEditTriggers(QTableWidget.NoEditTriggers)  # 禁止编辑
        self.table_widget.setSelectionMode(QTableWidget.NoSelection)  # 禁止选择
        
        # 设置尺寸策略，确保表格能随父容器拉伸
        self.table_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # 设置左侧固定列的尺寸策略为Fixed宽度，Expanding高度
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        
        # 设置列宽和伸缩模式
        self.table_widget.setColumnWidth(0, self.name_column_width)
        self.table_widget.setColumnWidth(1, self.device_column_width)
        self.table_widget.setColumnWidth(2, self.folder_column_width)
        # 设置列伸缩模式，让列可以随表格宽度变化而调整
        self.table_widget.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)  # 第一列（事件名称）自动伸缩
        self.table_widget.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)  # 第二列（设备）自动伸缩
        self.table_widget.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)  # 第三列（文件夹名称）自动伸缩
        
        # 创建布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.table_widget)
        
        # 设置背景颜色和单元格样式
        self.table_widget.setStyleSheet(""".QTableWidget {
            background-color: #f5f5f5;
        }
        .QTableWidget::item {
            border-bottom: 1px solid #e0e0e0;
            padding: 8px;
            white-space: pre-wrap;
        }""")

    def set_data(self, merged_events, event_names, devices):
        """设置数据"""
        self.merged_events = merged_events
        self.event_names = event_names
        self.devices = devices
        
        # 更新表格内容
        self.update_table()

    def set_settings(self, time_margin, name_column_width, device_column_width, folder_column_width, event_block_height, row_spacing, global_font=None, global_font_size=10, dpi_scale_factor=0.5):
        """
        设置参数
        """
        self.time_margin = time_margin
        self.name_column_width = name_column_width
        self.device_column_width = device_column_width
        self.folder_column_width = folder_column_width
        self.event_block_height = event_block_height
        self.row_spacing = row_spacing
        # 使用传递的全局字体对象，如果没有则使用当前的
        self.global_font = global_font or self.global_font
        # 更新字体大小和DPI缩放因子
        self.global_font_size = global_font_size
        self.dpi_scale_factor = dpi_scale_factor
        
        # 更新表格设置
        self.table_widget.setColumnWidth(0, self.name_column_width)
        self.table_widget.setColumnWidth(1, self.device_column_width)
        self.table_widget.setColumnWidth(2, self.folder_column_width)
        # 设置列宽为固定模式，确保缩放因子生效
        self.table_widget.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table_widget.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.table_widget.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        
        # 设置表格默认字体
        if self.global_font:
            font = QFont(self.global_font)
            font.setPointSize(int(self.global_font_size * self.dpi_scale_factor))
            self.table_widget.setFont(font)
        
        # 设置表格支持文本换行
        self.table_widget.setWordWrap(True)
        
        self.update_table()

    def update_table(self):
        """更新表格内容"""
        # 设置行数
        self.table_widget.setRowCount(len(self.merged_events))
        
        # 设置行高
        row_height = self.event_block_height + self.row_spacing
        for i in range(len(self.merged_events)):
            self.table_widget.setRowHeight(i, row_height)
        
        # 填充数据
        for i, event in enumerate(self.merged_events):
            # 事件名称单元格
            name_item = QTableWidgetItem(event.name)
            name_item.setTextAlignment(Qt.AlignTop | Qt.AlignLeft)
            # 创建粗体字体
            bold_font = QFont(self.global_font)
            bold_font.setBold(True)
            bold_font.setPointSize(int(self.global_font_size * self.dpi_scale_factor))
            name_item.setFont(bold_font)
            name_item.setForeground(QColor(50, 50, 50))
            name_item.setBackground(QColor(240, 240, 240))
            name_item.setFlags(Qt.ItemIsEnabled)
            self.table_widget.setItem(i, 0, name_item)
            
            # 设备名称单元格
            device_item = QTableWidgetItem(event.device)
            device_item.setTextAlignment(Qt.AlignTop | Qt.AlignLeft)
            # 创建设备名称字体
            device_font = QFont(self.global_font)
            device_font.setPointSize(int((self.global_font_size - 1) * self.dpi_scale_factor))
            device_item.setFont(device_font)
            device_item.setForeground(QColor(80, 80, 80))
            device_item.setBackground(QColor(230, 230, 230))
            device_item.setFlags(Qt.ItemIsEnabled)
            self.table_widget.setItem(i, 1, device_item)
            
            # 文件夹名称单元格（使用QLabel文本控件）
            folder_name = event.folder_name if event.folder_name else ""
            folder_label = QLabel(folder_name)
            # 设置文本对齐方式
            folder_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            # 创建文件夹名称字体
            folder_font = QFont(self.global_font)
            folder_font.setPointSize(int((self.global_font_size - 1) * self.dpi_scale_factor))
            folder_label.setFont(folder_font)
            # 设置文本颜色
            folder_label.setStyleSheet(f"color: #505050; background-color: #E6E6E6; padding: 8px; border: none;")
            # 设置自动换行
            folder_label.setWordWrap(True)
            # 设置垂直方向的尺寸策略为最小高度
            folder_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            # 将QLabel添加到单元格
            self.table_widget.setCellWidget(i, 2, folder_label)
        
        # 如果没有数据，显示提示
        if not self.merged_events:
            self.table_widget.setRowCount(5)
            for i in range(5):
                self.table_widget.setRowHeight(i, row_height)
                for j in range(3):  # 现在是3列，包括文件夹名称列
                    if i == 2 and j == 0:
                        # 在中间行第一列显示提示信息
                        empty_item = QTableWidgetItem("无数据，请先导入CSV文件")
                        empty_item.setBackground(QColor(240, 240, 240))
                        empty_item.setTextAlignment(Qt.AlignCenter)
                        # 创建浅色字体
                        light_font = QFont(self.global_font)
                        light_font.setPointSize(int((self.global_font_size - 1) * self.dpi_scale_factor))
                        light_font.setWeight(QFont.Light)
                        empty_item.setFont(light_font)
                        empty_item.setForeground(QColor(150, 150, 150))
                        empty_item.setFlags(Qt.ItemIsEnabled)
                        self.table_widget.setItem(i, j, empty_item)
                    else:
                        # 其他单元格显示空白背景
                        empty_item = QTableWidgetItem()
                        bg_color = QColor(240, 240, 240) if j == 0 else QColor(230, 230, 230)
                        empty_item.setBackground(bg_color)
                        empty_item.setFlags(Qt.ItemIsEnabled)
                        self.table_widget.setItem(i, j, empty_item)
        
        # 调整控件大小
        self.calculate_layout()

    def calculate_layout(self):
        """计算布局参数"""
        if not self.merged_events:
            # 即使没有事件数据，也要设置基本尺寸
            self.total_height = self.time_margin * 2 + 5 * (self.event_block_height + self.row_spacing)  # 包含上下边距的5行基本高度
        else:
            # 计算总高度，与右侧保持一致
            self.total_height = self.time_margin * 2 + len(self.merged_events) * (self.event_block_height + self.row_spacing)
        
        # 调整控件大小：只设置最小高度和最小宽度，移除固定宽度限制，让控件可以自由伸缩
        min_width = self.name_column_width + self.device_column_width + self.folder_column_width  # 设置最小宽度为能显示内容的宽度
        self.setMinimumSize(min_width, self.total_height)
        self.setMaximumSize(16777215, 16777215)  # 设置为Qt的最大允许值，让控件可以自由伸缩
    
    def sizeHint(self):
        """返回控件的建议大小"""
        # 计算总宽度：事件名称列 + 设备列 + 文件夹名称列
        total_width = self.name_column_width + self.device_column_width + self.folder_column_width
        
        # 返回建议大小
        return QSize(total_width, self.total_height)


class TimelineWidget(QWidget):
    """时间轴绘制控件"""
    def __init__(self, parent=None, global_font=None):
        super().__init__(parent)
        self.setMinimumHeight(500)
        self.setMouseTracking(True)
        
        # 设置尺寸策略，确保时间轴能在布局中正确调整大小
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # 数据
        self.merged_events = []
        self.event_names = set()
        self.devices = set()
        
        # 设置
        self.pixels_per_unit = 10
        self.unit_multiplier = 1
        self.time_margin = 10
        self.name_column_width = 200
        self.device_column_width = 100
        self.folder_column_width = 150  # 文件夹名称列宽度
        self.event_block_height = 30
        self.row_spacing = 10
        # 初始化默认的全局字体大小、DPI缩放因子和全局字体对象
        self.global_font_size = 10
        self.dpi_scale_factor = 0.5
        self.global_font = global_font or QFont()
        # 初始化默认高度和宽度，避免sizeHint方法调用时属性未定义
        self.total_height = 200  # 默认高度
        self.content_width = 400  # 默认宽度
        
        # 交互
        self.hovered_event = None
        self.selected_event = None
        
        # 预览轴相关变量
        self.mouse_position = QPoint()  # 鼠标当前位置
        self.is_mouse_in_timeline = False  # 鼠标是否在时间轴区域内
        
        # 选择范围相关变量
        self.is_selecting = False  # 是否正在进行选择
        self.selection_start = QPoint()  # 选择开始位置
        self.selection_end = QPoint()  # 选择结束位置
        self.selected_ranges = []  # 存储所有选中的区域 [(start_time, end_time), ...]
        
        # 颜色映射
        self.colors = self.generate_colors()

    def set_data(self, merged_events, event_names, devices):
        """设置数据"""
        self.merged_events = merged_events
        self.event_names = event_names
        self.devices = devices

    def set_settings(self, pixels_per_unit, unit_multiplier, time_margin, 
                    name_column_width, device_column_width, folder_column_width, event_block_height, row_spacing,
                    tolerance_unit="秒", tolerance_multiplier=1, global_font=None, global_font_size=10, dpi_scale_factor=0.5):
        """设置参数"""
        self.pixels_per_unit = pixels_per_unit
        self.unit_multiplier = unit_multiplier
        self.time_margin = time_margin
        self.name_column_width = name_column_width
        self.device_column_width = device_column_width
        self.folder_column_width = folder_column_width
        self.event_block_height = event_block_height
        self.row_spacing = row_spacing
        self.tolerance_unit = tolerance_unit
        self.tolerance_multiplier = tolerance_multiplier
        # 使用传递的全局字体对象，如果没有则使用当前的
        self.global_font = global_font or self.global_font
        # 更新字体大小和DPI缩放因子
        self.global_font_size = global_font_size
        self.dpi_scale_factor = dpi_scale_factor

    def generate_colors(self):
        """生成颜色映射"""
        colors = [
            QColor(52, 152, 219),  # 蓝色
            QColor(46, 204, 113),  # 绿色
            QColor(230, 126, 34),  # 橙色
            QColor(155, 89, 182),  # 紫色
            QColor(231, 76, 60),   # 红色
            QColor(241, 196, 15),  # 黄色
            QColor(127, 140, 141), # 灰色
            QColor(26, 188, 156),  # 青色
            QColor(192, 57, 43),   # 深红色
            QColor(142, 68, 173)   # 深紫色
        ]
        return colors

    def paintEvent(self, event):
        """绘制时间轴"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if not self.merged_events:
            # 确保控件有足够的高度来显示提示文本
            self.setMinimumHeight(200)
            # 使用全局字体
            font = QFont(self.global_font)
            font.setPointSize(int(self.global_font_size * self.dpi_scale_factor))
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignCenter, "无数据，请先导入CSV文件")
            return

        # 计算布局参数
        self.calculate_layout()

        # 绘制背景
        self.draw_background(painter)
        
        # 绘制时间刻度
        self.draw_time_scale(painter)
        
        # 绘制事件块
        self.draw_events(painter)
        
        # 绘制实时预览轴
        self.draw_preview_axis(painter)
        
        # 绘制选择范围
        self.draw_selection_range(painter)

    def calculate_layout(self):
        """计算布局参数"""
        if not self.merged_events:
            return

        # 计算事件区域高度
        self.events_height = self.time_margin * 2
        self.events_height += len(self.merged_events) * (self.event_block_height + self.row_spacing)
        
        # 为时间刻度预留底部空间
        self.scale_height = 50  # 时间刻度区域高度
        
        # 计算总高度
        self.total_height = self.events_height + self.scale_height
        
        # 计算时间范围
        all_times = []
        for event in self.merged_events:
            for start, end in event.time_ranges:
                all_times.append(start)
                all_times.append(end)
        self.min_time = min(all_times)
        self.max_time = max(all_times)
        
        # 计算总时间（单位：秒）
        self.total_time = (self.max_time - self.min_time).total_seconds()
        
        # 计算内容宽度
        self.content_width = self.name_column_width + self.device_column_width + self.folder_column_width
        self.content_width += self.time_margin * 2
        self.content_width += int(self.total_time / self.unit_multiplier * self.pixels_per_unit)
        
        # 调整控件大小
        self.setMinimumSize(self.content_width, self.total_height)
    
    def sizeHint(self):
        """返回控件的建议大小"""
        if not self.merged_events:
            # 如果没有事件数据，返回一个最小的建议大小
            return QSize(400, 200)
        
        # 计算内容宽度（包括左侧固定列和时间轴区域）
        width = self.content_width
        
        # 计算总高度（包括事件区域和时间刻度）
        height = self.total_height
        
        return QSize(width, height)

    def draw_background(self, painter):
        """绘制背景"""
        # 只绘制时间轴背景（隐藏名称列和设备列）
        painter.fillRect(
            0, 0, 
            self.content_width, self.total_height, 
            QColor(255, 255, 255)
        )
        
        # 绘制分隔线
        pen = QPen(QColor(200, 200, 200), 1)
        painter.setPen(pen)
        
        # 行分隔线
        y = self.time_margin
        for i in range(len(self.merged_events) + 1):
            painter.drawLine(
                0, y, 
                self.content_width, y
            )
            y += self.event_block_height + self.row_spacing

    def draw_time_scale(self, painter):
        """绘制时间刻度"""
        # 计算理想的刻度间隔像素数（确保标签不重叠）
        ideal_pixel_interval = 80  # 标签之间的理想像素间隔
        
        # 计算当前像素密度对应的实际时间间隔
        current_pixel_density = self.pixels_per_unit / self.unit_multiplier  # 每秒钟的像素数
        ideal_time_interval_seconds = ideal_pixel_interval / current_pixel_density
        
        # 选择合适的时间间隔（确保是合理的时间单位）
        time_intervals = [1, 5, 10, 30, 60, 300, 600, 1800, 3600, 7200, 14400, 28800, 43200, 86400]
        selected_interval = min(time_intervals, key=lambda x: abs(x - ideal_time_interval_seconds))
        
        # 计算起始刻度时间（对齐到选择的时间间隔）
        start_seconds = (self.min_time - datetime.datetime(1970, 1, 1)).total_seconds()
        aligned_start_seconds = selected_interval * ((start_seconds + selected_interval - 1) // selected_interval)  # 向上取整对齐
        start_scale_time = datetime.datetime(1970, 1, 1) + datetime.timedelta(seconds=aligned_start_seconds)
        
        # 计算每个刻度的像素间隔
        pixel_interval = int(selected_interval * current_pixel_density)
        
        # 绘制刻度线和标签
        x = self.time_margin
        current_time = start_scale_time
        
        # 用于标签跳过机制的变量
        font = QFont(self.global_font)
        font.setPointSize(int((self.global_font_size - 2) * self.dpi_scale_factor))
        fm = QFontMetrics(font)
        last_label_x = -float('inf')  # 上一个标签的位置
        label_padding = 10  # 标签之间的额外间距
        
        while current_time <= self.max_time:
            # 绘制刻度线 - 从事件区域顶部到底部
            pen = QPen(QColor(200, 200, 200), 1)
            painter.setPen(pen)
            # 刻度线从事件区域顶部开始，到底部结束
            painter.drawLine(x, self.time_margin, x, self.events_height)
            
            # 绘制时间标签
            painter.setFont(font)
            painter.setPen(QColor(100, 100, 100))
            
            # 根据时间间隔选择合适的时间格式
            time_str = self.format_time(current_time, selected_interval)
            
            # 计算标签宽度
            text_width = fm.width(time_str)
            
            # 检查是否与上一个标签重叠，如果不重叠则绘制
            if x - text_width/2 >= last_label_x + label_padding:
                # 调整标签位置和旋转角度，确保文字在底部刻度区域完整显示
                painter.save()
                # 将标签绘制在底部刻度区域，旋转角度调整为0度以便更易读
                painter.translate(x, self.events_height + 20)  # 在事件区域下方绘制标签
                # 居中对齐文字
                painter.drawText(-text_width / 2, 0, time_str)
                painter.restore()
                
                # 更新上一个标签的位置
                last_label_x = x + text_width/2
            
            # 移动到下一个刻度
            current_time += datetime.timedelta(seconds=selected_interval)
            x += pixel_interval
            
    def format_time(self, time, interval_seconds):
        """根据时间间隔选择合适的时间格式"""
        # 始终显示时：分：秒格式，如14:00:00
        return time.strftime("%H:%M:%S")

    def draw_events(self, painter):
        """绘制事件块"""
        if not self.merged_events:
            return

        y = self.time_margin + self.row_spacing / 2
        
        for i, event in enumerate(self.merged_events):
            # 只绘制事件时间块（隐藏事件名称、设备名称和文件夹名称，这些都在左侧固定列中显示）
            self.draw_event_blocks(painter, event, y)
            
            # 移动到下一行
            y += self.event_block_height + self.row_spacing

    def draw_event_name(self, painter, name, y):
        """绘制事件名称"""
        # 设置字体
        font = QFont(self.global_font)
        font.setPointSize(int(self.global_font_size * self.dpi_scale_factor))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(50, 50, 50))
        
        # 计算文本矩形
        rect = QRect(
            5, y, 
            self.name_column_width - 10, self.event_block_height
        )
        
        # 绘制文本（最多2行）
        option = QTextOption()
        option.setAlignment(Qt.AlignTop)
        option.setWrapMode(QTextOption.WordWrap)
        painter.drawText(QRectF(rect), name, option)

    def draw_device_name(self, painter, device, y):
        """绘制设备名称"""
        # 设置字体
        font = QFont(self.global_font)
        font.setPointSize(int((self.global_font_size - 1) * self.dpi_scale_factor))
        painter.setFont(font)
        painter.setPen(QColor(80, 80, 80))
        
        # 计算文本矩形
        rect = QRect(
            self.name_column_width + 5, y, 
            self.device_column_width - 10, self.event_block_height
        )
        
        # 绘制文本
        option = QTextOption()
        option.setAlignment(Qt.AlignTop)
        option.setWrapMode(QTextOption.WordWrap)
        painter.drawText(QRectF(rect), device, option)

    def draw_folder_name(self, painter, folder_name, y):
        """绘制文件夹名称"""
        # 设置字体
        font = QFont(self.global_font)
        font.setPointSize(int((self.global_font_size - 1) * self.dpi_scale_factor))
        painter.setFont(font)
        painter.setPen(QColor(50, 50, 50))
        
        # 计算文本矩形
        rect = QRect(
            self.name_column_width + self.device_column_width + 5, y, 
            self.folder_column_width - 10, self.event_block_height
        )
        
        # 绘制文本
        option = QTextOption()
        option.setAlignment(Qt.AlignTop)
        option.setWrapMode(QTextOption.WordWrap)
        painter.drawText(QRectF(rect), folder_name or "", option)

    def draw_event_blocks(self, painter, event, y):
        """绘制事件时间块"""
        # 获取颜色
        color_idx = hash(event.name) % len(self.colors)
        color = self.colors[color_idx]
        
        for start_time, end_time in event.time_ranges:
            # 计算时间块的位置和宽度
            start_seconds = (start_time - self.min_time).total_seconds()
            end_seconds = (end_time - self.min_time).total_seconds()
            
            x = self.name_column_width + self.device_column_width + self.folder_column_width
            x += self.time_margin
            x += int(start_seconds / self.unit_multiplier * self.pixels_per_unit)
            
            width = int((end_seconds - start_seconds) / self.unit_multiplier * self.pixels_per_unit)
            
            # 绘制圆角矩形
            rect = QRect(x, y, width, self.event_block_height)
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(color.darker(120), 1))
            painter.drawRoundedRect(rect, 5, 5)
            
            # 绘制事件名称（可选）
            if width > 50:
                font = QFont(self.global_font)
                font.setPointSize(int((self.global_font_size - 2) * self.dpi_scale_factor))
                painter.setFont(font)
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(rect.adjusted(5, 0, -5, 0), Qt.AlignCenter, event.name[:10])

    def mouseMoveEvent(self, event):
        """鼠标移动事件"""
        # 更新鼠标位置
        self.mouse_position = event.pos()
        
        # 检测鼠标是否在时间轴区域内
        if hasattr(self, 'events_height') and self.time_margin <= self.mouse_position.x() <= self.content_width and self.time_margin <= self.mouse_position.y() <= self.events_height:
            self.is_mouse_in_timeline = True
        else:
            self.is_mouse_in_timeline = False
        
        # 如果正在选择范围，更新选择结束位置
        if self.is_selecting:
            self.selection_end = event.pos()
            self.update()
            return
        
        # 检测鼠标悬停在哪个事件上
        hovered = self.get_hovered_event(event.pos())
        if hovered != self.hovered_event:
            self.hovered_event = hovered
            if hovered:
                self.setCursor(QCursor(Qt.PointingHandCursor))
            else:
                self.setCursor(QCursor(Qt.ArrowCursor))
            self.update()
        elif self.is_mouse_in_timeline:
            # 即使没有悬停事件变化，也更新预览轴
            self.update()
    
    def enterEvent(self, event):
        """鼠标进入事件"""
        self.is_mouse_in_timeline = True
        self.update()
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        """鼠标离开事件"""
        self.is_mouse_in_timeline = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        """鼠标点击事件"""
        # 左键点击：开始新的选择区域
        if event.button() == Qt.LeftButton:
            # 检查是否在时间轴区域内
            if hasattr(self, 'events_height') and self.time_margin <= event.pos().x() <= self.content_width and self.time_margin <= event.pos().y() <= self.events_height:
                # 开始选择范围
                self.is_selecting = True
                self.selection_start = event.pos()
                self.selection_end = event.pos()
        
        # 右键点击：清除所有选中区域
        elif event.button() == Qt.RightButton:
            self.selected_ranges.clear()
            # 实时更新选中文件显示
            auto_timeline_widget = self.parent().parent().parent()
            if hasattr(auto_timeline_widget, 'show_selected_files'):
                auto_timeline_widget.show_selected_files()
            
        self.update()

    def get_hovered_event(self, pos):
        """获取鼠标悬停的事件"""
        if not self.merged_events:
            return None

        # 检查是否在时间轴区域内
        if pos.x() < self.time_margin:
            return None

        # 计算所在行
        y = pos.y() - self.time_margin - self.row_spacing / 2
        if y < 0:
            return None
        row = int(y / (self.event_block_height + self.row_spacing))
        if row >= len(self.merged_events):
            return None

        event = self.merged_events[row]
        return event

    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        if self.is_selecting:
            # 结束选择范围
            self.is_selecting = False
            
            # 确保布局参数已计算（包括min_time和max_time）
            self.calculate_layout()
            
            # 计算选择范围的像素区间
            select_start_x = min(self.selection_start.x(), self.selection_end.x())
            select_end_x = max(self.selection_start.x(), self.selection_end.x())
            
            # 将选择范围限制在时间轴的可视范围内
            select_start_x = max(select_start_x, self.time_margin)
            select_end_x = min(select_end_x, self.content_width)
            
            # 只有当选择范围有一定宽度时才进行后续操作
            if select_end_x - select_start_x > 10:
                # 获取选择范围的开始和结束时间
                start_time = self.get_time_at_position(select_start_x)
                end_time = self.get_time_at_position(select_end_x)
                
                print(f"鼠标释放事件：")
                print(f"  选择的像素范围：{select_start_x} 到 {select_end_x}")
                print(f"  转换的时间范围：{start_time} 到 {end_time}")
                
                if start_time and end_time:
                    # 保存选中的区域到列表中
                    self.selected_ranges.append((start_time, end_time))
                    
                    # 合并重叠的时间范围
                    self.selected_ranges = self.merge_overlapping_ranges(self.selected_ranges)
                    
                    print(f"  合并后的选中区域数量：{len(self.selected_ranges)}")
                    for i, (range_start, range_end) in enumerate(self.selected_ranges):
                        print(f"    区域 {i+1}: {range_start} 到 {range_end}")
                    
                    # 立即显示选中的文件
                    auto_timeline_widget = self.parent().parent().parent()  # 从scroll_widget到scroll_area到主控件
                    if hasattr(auto_timeline_widget, 'show_selected_files'):
                        auto_timeline_widget.show_selected_files()
        
        self.update()
    
    def wheelEvent(self, event):
        """鼠标滚轮事件处理，实现Ctrl+滚轮缩放"""
        # 检测Ctrl键是否被按住
        if event.modifiers() & Qt.ControlModifier:
            # 获取父控件的zoom_spinbox
            auto_timeline_widget = self.parent().parent().parent()  # 从scroll_widget到scroll_area到主控件
            if hasattr(auto_timeline_widget, 'zoom_spinbox'):
                # 根据滚轮方向调整缩放
                delta = event.angleDelta().y()
                if delta > 0:
                    # 向上滚动，增加缩放
                    new_zoom = auto_timeline_widget.zoom_spinbox.value() + 1
                else:
                    # 向下滚动，减小缩放
                    new_zoom = auto_timeline_widget.zoom_spinbox.value() - 1
                
                # 限制缩放范围在1-200之间
                new_zoom = max(1, min(200, new_zoom))
                
                # 更新缩放控件并刷新视图
                auto_timeline_widget.zoom_spinbox.setValue(new_zoom)
                auto_timeline_widget.update_view()
            event.accept()
        else:
            # 如果没有按住Ctrl键，继续默认的滚轮行为（滚动）
            super().wheelEvent(event)
            # 滚动后更新预览轴
            self.update()
    
    def draw_preview_axis(self, painter):
        """绘制实时预览轴"""
        if not self.is_mouse_in_timeline:
            return
        
        # 绘制竖直线
        x = self.mouse_position.x()
        pen = QPen(QColor(255, 0, 0), 1, Qt.DashLine)
        painter.setPen(pen)
        painter.drawLine(x, self.time_margin, x, self.events_height)
        
        # 获取当前位置的时间
        current_time = self.get_time_at_position(x)
        if current_time:
            # 绘制时间标签
            time_str = current_time.strftime("%H:%M:%S")
            font = QFont(self.global_font)
            font.setPointSize(int((self.global_font_size - 2) * self.dpi_scale_factor))
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor(255, 0, 0))
            
            # 计算文本位置
            text_rect = painter.fontMetrics().boundingRect(time_str)
            text_x = x - text_rect.width() // 2
            text_y = self.events_height + 15  # 在时间刻度上方绘制
            
            # 绘制文本背景
            painter.fillRect(text_x - 2, text_y - text_rect.height(), 
                           text_rect.width() + 4, text_rect.height() + 2, 
                           QColor(255, 255, 255))
            
            # 绘制文本
            painter.drawText(text_x, text_y, time_str)
        
        # 获取当前位置的事件
        current_event = self.get_event_at_position(self.mouse_position)
        if current_event:
            # 绘制事件信息
            event_info = f"{current_event.name} - {current_event.device}"
            font = QFont(self.global_font)
            font.setPointSize(int((self.global_font_size - 2) * self.dpi_scale_factor))
            painter.setFont(font)
            painter.setPen(QColor(255, 0, 0))
            
            # 计算文本位置
            text_rect = painter.fontMetrics().boundingRect(event_info)
            text_x = x - text_rect.width() // 2
            text_y = self.time_margin - 10  # 在事件区域上方绘制
            
            # 绘制文本背景
            painter.fillRect(text_x - 2, text_y - text_rect.height(), 
                           text_rect.width() + 4, text_rect.height() + 2, 
                           QColor(255, 255, 255))
            
            # 绘制文本
            painter.drawText(text_x, text_y, event_info)
    
    def get_time_at_position(self, x):
        """获取指定x坐标位置对应的时间"""
        if not hasattr(self, 'min_time') or not hasattr(self, 'max_time'):
            return None
        
        # 计算时间轴的起始和结束x坐标
        start_x = self.time_margin
        end_x = self.content_width
        
        # 检查x是否在时间轴范围内
        if x < start_x or x > end_x:
            return None
        
        # 计算时间比例
        ratio = (x - start_x) / (end_x - start_x)
        
        # 计算对应的时间
        time_diff = datetime.timedelta(seconds=self.total_time * ratio)
        current_time = self.min_time + time_diff
        
        return current_time
    
    def merge_overlapping_ranges(self, ranges):
        """合并重叠或相邻的时间范围
        
        参数:
            ranges: 时间范围列表，每个元素为(start_time, end_time)
            
        返回:
            合并后的时间范围列表
        """
        if not ranges:
            return []
            
        # 按起始时间排序
        sorted_ranges = sorted(ranges, key=lambda x: x[0])
        
        merged = [sorted_ranges[0]]
        
        for current_range in sorted_ranges[1:]:
            current_start, current_end = current_range
            last_start, last_end = merged[-1]
            
            # 如果当前范围与上一个范围有重叠或相邻，则合并
            if current_start <= last_end:
                # 合并两个范围，取最小的开始时间和最大的结束时间
                merged[-1] = (last_start, max(last_end, current_end))
            else:
                # 没有重叠，添加当前范围
                merged.append(current_range)
                
        return merged
        
    def get_position_at_time(self, time):
        """获取指定时间对应的x坐标位置"""
        if not hasattr(self, 'min_time') or not hasattr(self, 'max_time'):
            return None
        
        # 检查时间是否在范围内
        if time < self.min_time or time > self.max_time:
            return None
        
        # 计算时间比例
        elapsed_seconds = (time - self.min_time).total_seconds()
        ratio = elapsed_seconds / self.total_time
        
        # 计算对应的x坐标
        start_x = self.time_margin
        end_x = self.content_width
        x = start_x + (end_x - start_x) * ratio
        
        return x
    
    def get_event_at_position(self, pos):
        """获取鼠标位置对应的事件"""
        if not self.merged_events:
            return None
        
        # 检查是否在时间轴区域内
        if pos.x() < self.time_margin or pos.x() > self.content_width:
            return None
        
        if pos.y() < self.time_margin or pos.y() > self.events_height:
            return None
        
        # 计算所在行
        y = pos.y() - self.time_margin - self.row_spacing / 2
        if y < 0:
            return None
        row = int(y / (self.event_block_height + self.row_spacing))
        if row >= len(self.merged_events):
            return None
        
        event = self.merged_events[row]
        
        # 获取当前位置的时间
        current_time = self.get_time_at_position(pos.x())
        if not current_time:
            return None
        
        # 检查当前时间是否在事件的时间范围内
        for start_time, end_time in event.time_ranges:
            if start_time <= current_time <= end_time:
                return event
        
        return None
    
    def draw_selection_range(self, painter):
        """绘制选择范围"""
        # 绘制所有已保存的选中区域
        for start_time, end_time in self.selected_ranges:
            # 将时间转换为像素位置
            select_start_x = self.get_position_at_time(start_time)
            select_end_x = self.get_position_at_time(end_time)
            
            if select_start_x is None or select_end_x is None:
                continue
            
            # 确保选择区域在时间轴范围内
            select_start_x = max(select_start_x, self.time_margin)
            select_end_x = min(select_end_x, self.content_width)
            
            # 计算选择区域的宽度
            select_width = select_end_x - select_start_x
            
            # 如果选择区域太小，不绘制
            if select_width < 5:
                continue
            
            # 绘制半透明的选择区域
            selection_rect = QRect(select_start_x, self.time_margin, select_width, self.events_height - self.time_margin)
            painter.setBrush(QBrush(QColor(0, 128, 255, 50)))
            painter.setPen(QPen(QColor(0, 128, 255), 1, Qt.SolidLine))
            painter.drawRect(selection_rect)
        
        # 绘制当前正在选择的区域
        if self.is_selecting:
            # 计算选择区域的矩形
            select_start_x = min(self.selection_start.x(), self.selection_end.x())
            select_end_x = max(self.selection_start.x(), self.selection_end.x())
            
            # 确保选择区域在时间轴范围内
            select_start_x = max(select_start_x, self.time_margin)
            select_end_x = min(select_end_x, self.content_width)
            
            # 计算选择区域的宽度
            select_width = select_end_x - select_start_x
            
            # 如果选择区域太小，不绘制
            if select_width < 5:
                return
            
            # 绘制半透明的选择区域（使用不同颜色区分正在选择和已保存的区域）
            selection_rect = QRect(select_start_x, self.time_margin, select_width, self.events_height - self.time_margin)
            painter.setBrush(QBrush(QColor(255, 165, 0, 50)))
            painter.setPen(QPen(QColor(255, 165, 0), 1, Qt.SolidLine))
            painter.drawRect(selection_rect)
    
    def get_videos_in_selected_ranges(self):
        """获取所有选中区域内的视频文件和事件信息"""
        videos = set()  # 使用集合避免重复的视频路径
        selected_events = []  # 保存所有选中的事件信息
        
        # 添加调试信息
        print(f"选中区域数量: {len(self.selected_ranges)}")
        print(f"合并事件数量: {len(self.merged_events)}")
        
        # 检查宽容度属性是否存在
        tolerance_unit = getattr(self, 'tolerance_unit', '秒')
        tolerance_multiplier = getattr(self, 'tolerance_multiplier', 0)
        print(f"宽容度设置: {tolerance_unit} ({tolerance_multiplier} 秒)")
        
        # 遍历所有已保存的选中区域
        for i, (range_start, range_end) in enumerate(self.selected_ranges):
            # 应用模糊选择，根据宽容度扩展选中范围
            if hasattr(self, 'tolerance_multiplier'):
                tolerance_seconds = self.tolerance_multiplier
                # 扩展选中范围
                extended_start = range_start - datetime.timedelta(seconds=tolerance_seconds)
                extended_end = range_end + datetime.timedelta(seconds=tolerance_seconds)
                print(f"选中区域 {i+1}: {range_start} 到 {range_end} (扩展后: {extended_start} 到 {extended_end})")
            else:
                extended_start = range_start
                extended_end = range_end
                print(f"选中区域 {i+1}: {range_start} 到 {range_end} (未扩展)")
            
            # 遍历所有合并事件
            for event in self.merged_events:
                # 遍历事件的所有时间范围和对应的视频文件
                for j, (event_start, event_end, event_videos) in enumerate(event.time_range_videos):
                    print(f"  事件 '{event.name}' 时间范围 {j+1}: {event_start} 到 {event_end} (视频数量: {len(event_videos)})")
                    
                    # 检查时间范围是否与扩展后的选中区域有交集
                    if (event_start <= extended_end) and (event_end >= extended_start):
                        print(f"    -> 有交集！")
                        
                        # 保存事件信息
                        event_info = {
                            'name': event.name,
                            'device': event.device,
                            'start_time': event_start,
                            'end_time': event_end,
                            'videos': event_videos.copy()
                        }
                        selected_events.append(event_info)
                        
                        # 添加该时间范围对应的视频文件
                        for video in event_videos:
                            videos.add(video)
                            print(f"      -> 添加视频: {video}")
        
        print(f"最终返回视频列表数量: {len(videos)}")
        print(f"最终选中事件数量: {len(selected_events)}")
        
        return videos, selected_events  # 返回视频集合和选中事件列表


if __name__ == "__main__":
    """测试代码"""
    app = QApplication(sys.argv)
    window = AutoTimeline()
    window.show()
    sys.exit(app.exec_())
