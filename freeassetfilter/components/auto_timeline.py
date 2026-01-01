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
import csv
import datetime
from collections import defaultdict

# 导入文件夹时间轴生成器
from freeassetfilter.core.folder_timeline_generator import FolderTimelineGenerator

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QPushButton, QLabel, QFileDialog, QMessageBox,
    QComboBox, QSpinBox, QStatusBar, QProgressDialog
)
from PyQt5.QtCore import QTimer
from PyQt5.QtCore import Qt, QRect, QRectF, QPoint, QSize, QEvent
from PyQt5.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QFontMetrics,
    QTextOption, QCursor
)


class TimelineEvent:
    """时间轴事件类"""
    def __init__(self, name, device, start_time, end_time):
        self.name = name
        self.device = device
        self.start_time = start_time
        self.end_time = end_time

    def duration(self):
        """返回事件持续时间（秒）"""
        return (self.end_time - self.start_time).total_seconds()


class MergedEvent:
    """合并后的事件类"""
    def __init__(self, name, device):
        self.name = name
        self.device = device
        self.time_ranges = []

    def add_range(self, start_time, end_time):
        """添加时间范围"""
        self.time_ranges.append((start_time, end_time))
        # 按起始时间排序
        self.time_ranges.sort(key=lambda x: x[0])

    def duration(self):
        """返回总持续时间（秒）"""
        total = 0
        for start, end in self.time_ranges:
            total += (end - start).total_seconds()
        return total


class AutoTimeline(QWidget):
    """自动时间轴组件"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        self.init_data()
        self.init_settings()

    def init_ui(self):
        """初始化界面"""
        self.setWindowTitle("自动时间轴")
        self.setMinimumSize(800, 600)

        # 主布局
        main_layout = QVBoxLayout(self)

        # 顶部控制栏
        control_layout = QHBoxLayout()

        # CSV导入按钮
        self.import_btn = QPushButton("导入CSV")
        self.import_btn.clicked.connect(self.import_csv)
        control_layout.addWidget(self.import_btn)
        
        # 从文件夹生成时间轴按钮
        self.generate_from_folder_btn = QPushButton("从文件夹生成")
        self.generate_from_folder_btn.clicked.connect(self.generate_timeline_from_folder)
        control_layout.addWidget(self.generate_from_folder_btn)

        # 时间格式选择
        self.time_format_label = QLabel("时间格式：")
        control_layout.addWidget(self.time_format_label)
        self.time_format_combo = QComboBox()
        self.time_format_combo.addItems([
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%H:%M:%S"
        ])
        control_layout.addWidget(self.time_format_combo)

        # 缩放控制
        self.zoom_label = QLabel("缩放：")
        control_layout.addWidget(self.zoom_label)
        self.zoom_spinbox = QSpinBox()
        self.zoom_spinbox.setRange(1, 100)
        self.zoom_spinbox.setValue(10)
        self.zoom_spinbox.valueChanged.connect(self.update_view)
        control_layout.addWidget(self.zoom_spinbox)

        # 时间单位选择
        self.unit_label = QLabel("单位：")
        control_layout.addWidget(self.unit_label)
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["秒", "分钟", "小时"])
        self.unit_combo.currentIndexChanged.connect(self.update_view)
        control_layout.addWidget(self.unit_combo)

        control_layout.addStretch()
        main_layout.addLayout(control_layout)

        # 滚动区域
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_widget = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_widget)
        
        # 时间轴主控件
        self.timeline_widget = TimelineWidget()
        self.scroll_layout.addWidget(self.timeline_widget)
        
        self.scroll_area.setWidget(self.scroll_widget)
        main_layout.addWidget(self.scroll_area, 1)

        # 底部状态栏
        self.status_bar = QStatusBar()
        self.time_range_label = QLabel("时间范围：")
        self.event_count_label = QLabel("事件数量：0")
        
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

    def init_settings(self):
        """初始化设置"""
        self.time_format = "%Y-%m-%d %H:%M:%S"
        self.pixels_per_unit = 10  # 每时间单位的像素数
        self.unit_multiplier = 1  # 秒=1, 分钟=60, 小时=3600
        self.time_margin = 10  # 时间轴两侧的边距
        self.name_column_width = 200  # 活动名称列宽度
        self.device_column_width = 100  # 设备列宽度
        self.event_block_height = 30  # 事件块高度
        self.row_spacing = 10  # 行间距

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
            
        # 设置默认输出路径为输入文件夹目录
        default_output = os.path.join(folder_path, "timeline_generated.csv")
        
        # 选择输出CSV文件的位置
        output_path, _ = QFileDialog.getSaveFileName(
            self, "保存CSV文件", default_output, "CSV Files (*.csv);;All Files (*)"
        )
        if not output_path:
            return
            
        try:
            # 创建生成器实例
            generator = FolderTimelineGenerator()
            
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
            
            # 生成时间轴CSV
            success, message = generator.generate_timeline_csv(folder_path, output_path, progress_callback)
            
            progress_dialog.close()  # 关闭进度对话框
            
            if success:
                # 自动导入生成的CSV文件
                self.parse_csv(output_path)
                self.merge_events()
                self.update_view()
                self.update_status()
                # 导入后自动计算并应用最佳缩放比例
                self.calculate_optimal_zoom()
                
                QMessageBox.information(self, "成功", f"时间轴生成并导入成功！\n{message}")
            else:
                QMessageBox.critical(self, "错误", f"时间轴生成失败：{message}")
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"操作失败：{str(e)}")

    def parse_csv(self, file_path):
        """解析CSV文件"""
        self.init_data()
        self.time_format = self.time_format_combo.currentText()

        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader)  # 读取表头
            
            # 尝试自动识别列
            name_idx = -1
            device_idx = -1
            start_idx = -1
            end_idx = -1

            for i, col in enumerate(header):
                col_lower = col.lower().strip()
                if 'name' in col_lower or '事件' in col_lower:
                    name_idx = i
                elif 'device' in col_lower or '设备' in col_lower:
                    device_idx = i
                elif 'start' in col_lower or '开始' in col_lower:
                    start_idx = i
                elif 'end' in col_lower or '结束' in col_lower:
                    end_idx = i

            if name_idx == -1 or start_idx == -1 or end_idx == -1:
                raise ValueError("无法识别CSV列：需要包含事件名称、开始时间和结束时间列")

            # 读取数据行
            for row in reader:
                if len(row) < max(name_idx, device_idx, start_idx, end_idx) + 1:
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

                event = TimelineEvent(name, device, start_time, end_time)
                self.events.append(event)
                self.event_names.add(name)
                self.devices.add(device)

    def merge_events(self):
        """合并相同事件名称的时间范围"""
        # 按事件名称和设备分组
        event_groups = defaultdict(list)
        for event in self.events:
            key = (event.name, event.device)
            event_groups[key].append(event)

        # 合并每个组内的事件
        self.merged_events = []
        for (name, device), group_events in event_groups.items():
            merged_event = MergedEvent(name, device)
            
            # 按起始时间排序
            group_events.sort(key=lambda x: x.start_time)
            
            # 合并连续或重叠的时间范围
            current_start = group_events[0].start_time
            current_end = group_events[0].end_time
            
            for event in group_events[1:]:
                if event.start_time <= current_end:
                    # 重叠或连续，合并
                    current_end = max(current_end, event.end_time)
                else:
                    # 不连续，保存当前范围并开始新范围
                    merged_event.add_range(current_start, current_end)
                    current_start = event.start_time
                    current_end = event.end_time
            
            # 添加最后一个范围
            merged_event.add_range(current_start, current_end)
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
        
        # 更新缩放比例
        self.pixels_per_unit = self.zoom_spinbox.value()
        
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
            self.event_block_height,
            self.row_spacing
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
            
        # 获取可用宽度（窗口宽度减去名称列和设备列的宽度）
        available_width = self.width() - self.name_column_width - self.device_column_width - self.time_margin * 2
        
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
        optimal_zoom = max(1, min(100, optimal_zoom))
        
        # 更新缩放控件并刷新视图
        self.zoom_spinbox.setValue(int(optimal_zoom))
        self.update_view()


class TimelineWidget(QWidget):
    """时间轴绘制控件"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(500)
        self.setMouseTracking(True)
        
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
        self.event_block_height = 30
        self.row_spacing = 10
        
        # 交互
        self.hovered_event = None
        self.selected_event = None
        
        # 颜色映射
        self.colors = self.generate_colors()

    def set_data(self, merged_events, event_names, devices):
        """设置数据"""
        self.merged_events = merged_events
        self.event_names = event_names
        self.devices = devices

    def set_settings(self, pixels_per_unit, unit_multiplier, time_margin, 
                    name_column_width, device_column_width, event_block_height, row_spacing):
        """设置参数"""
        self.pixels_per_unit = pixels_per_unit
        self.unit_multiplier = unit_multiplier
        self.time_margin = time_margin
        self.name_column_width = name_column_width
        self.device_column_width = device_column_width
        self.event_block_height = event_block_height
        self.row_spacing = row_spacing

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

    def calculate_layout(self):
        """计算布局参数"""
        if not self.merged_events:
            return

        # 计算总高度
        self.total_height = self.time_margin * 2
        self.total_height += len(self.merged_events) * (self.event_block_height + self.row_spacing)
        
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
        self.content_width = self.name_column_width + self.device_column_width
        self.content_width += self.time_margin * 2
        self.content_width += int(self.total_time / self.unit_multiplier * self.pixels_per_unit)
        
        # 调整控件大小
        self.setMinimumSize(self.content_width, self.total_height)

    def draw_background(self, painter):
        """绘制背景"""
        # 绘制名称列背景
        painter.fillRect(
            0, 0, 
            self.name_column_width, self.total_height, 
            QColor(240, 240, 240)
        )
        
        # 绘制设备列背景
        painter.fillRect(
            self.name_column_width, 0, 
            self.device_column_width, self.total_height, 
            QColor(230, 230, 230)
        )
        
        # 绘制时间轴背景
        painter.fillRect(
            self.name_column_width + self.device_column_width, 0, 
            self.content_width - self.name_column_width - self.device_column_width, self.total_height, 
            QColor(255, 255, 255)
        )
        
        # 绘制分隔线
        pen = QPen(QColor(200, 200, 200), 1)
        painter.setPen(pen)
        
        # 名称列与设备列分隔线
        painter.drawLine(
            self.name_column_width, 0, 
            self.name_column_width, self.total_height
        )
        
        # 设备列与时间轴分隔线
        painter.drawLine(
            self.name_column_width + self.device_column_width, 0, 
            self.name_column_width + self.device_column_width, self.total_height
        )
        
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
        x = self.name_column_width + self.device_column_width + self.time_margin
        current_time = start_scale_time
        
        while current_time <= self.max_time:
            # 绘制刻度线
            pen = QPen(QColor(200, 200, 200), 1)
            painter.setPen(pen)
            painter.drawLine(x, 0, x, self.total_height)
            
            # 绘制时间标签
            font = QFont("Arial", 8)
            painter.setFont(font)
            painter.setPen(QColor(100, 100, 100))
            
            # 根据时间间隔选择合适的时间格式
            time_str = self.format_time(current_time, selected_interval)
            
            # 旋转标签
            painter.save()
            painter.translate(x + 5, 20)
            painter.rotate(-45)
            painter.drawText(0, 0, time_str)
            painter.restore()
            
            # 移动到下一个刻度
            current_time += datetime.timedelta(seconds=selected_interval)
            x += pixel_interval
            
    def format_time(self, time, interval_seconds):
        """根据时间间隔选择合适的时间格式"""
        if interval_seconds >= 86400:
            return time.strftime("%Y-%m-%d")
        elif interval_seconds >= 3600:
            return time.strftime("%m-%d %H:%M")
        elif interval_seconds >= 60:
            return time.strftime("%H:%M")
        else:
            return time.strftime("%H:%M:%S")

    def draw_events(self, painter):
        """绘制事件块"""
        if not self.merged_events:
            return

        y = self.time_margin + self.row_spacing / 2
        
        for i, event in enumerate(self.merged_events):
            # 绘制事件名称
            self.draw_event_name(painter, event.name, y)
            
            # 绘制设备名称
            self.draw_device_name(painter, event.device, y)
            
            # 绘制事件时间块
            self.draw_event_blocks(painter, event, y)
            
            # 移动到下一行
            y += self.event_block_height + self.row_spacing

    def draw_event_name(self, painter, name, y):
        """绘制事件名称"""
        # 设置字体
        font = QFont("Arial", 10, QFont.Bold)
        painter.setFont(font)
        painter.setPen(QColor(50, 50, 50))
        
        # 计算文本矩形
        rect = QRect(
            5, y, 
            self.name_column_width - 10, self.event_block_height
        )
        
        # 绘制文本（最多2行）
        option = QTextOption()
        option.setAlignment(Qt.AlignCenter)
        option.setWrapMode(QTextOption.WordWrap)
        painter.drawText(QRectF(rect), name, option)

    def draw_device_name(self, painter, device, y):
        """绘制设备名称"""
        # 设置字体
        font = QFont("Arial", 9)
        painter.setFont(font)
        painter.setPen(QColor(80, 80, 80))
        
        # 计算文本矩形
        rect = QRect(
            self.name_column_width + 5, y, 
            self.device_column_width - 10, self.event_block_height
        )
        
        # 绘制文本
        option = QTextOption()
        option.setAlignment(Qt.AlignCenter)
        option.setWrapMode(QTextOption.WordWrap)
        painter.drawText(QRectF(rect), device, option)

    def draw_event_blocks(self, painter, event, y):
        """绘制事件时间块"""
        # 获取颜色
        color_idx = hash(event.name) % len(self.colors)
        color = self.colors[color_idx]
        
        for start_time, end_time in event.time_ranges:
            # 计算时间块的位置和宽度
            start_seconds = (start_time - self.min_time).total_seconds()
            end_seconds = (end_time - self.min_time).total_seconds()
            
            x = self.name_column_width + self.device_column_width + self.time_margin
            x += int(start_seconds / self.unit_multiplier * self.pixels_per_unit)
            
            width = int((end_seconds - start_seconds) / self.unit_multiplier * self.pixels_per_unit)
            
            # 绘制圆角矩形
            rect = QRect(x, y, width, self.event_block_height)
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(color.darker(120), 1))
            painter.drawRoundedRect(rect, 5, 5)
            
            # 绘制事件名称（可选）
            if width > 50:
                font = QFont("Arial", 8)
                painter.setFont(font)
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(rect.adjusted(5, 0, -5, 0), Qt.AlignCenter, event.name[:10])

    def mouseMoveEvent(self, event):
        """鼠标移动事件"""
        # 检测鼠标悬停在哪个事件上
        hovered = self.get_hovered_event(event.pos())
        if hovered != self.hovered_event:
            self.hovered_event = hovered
            if hovered:
                self.setCursor(QCursor(Qt.PointingHandCursor))
            else:
                self.setCursor(QCursor(Qt.ArrowCursor))
            self.update()

    def mousePressEvent(self, event):
        """鼠标点击事件"""
        clicked = self.get_hovered_event(event.pos())
        if clicked:
            self.selected_event = clicked
            self.update()

    def get_hovered_event(self, pos):
        """获取鼠标悬停的事件"""
        if not self.merged_events:
            return None

        # 检查是否在时间轴区域内
        if pos.x() < self.name_column_width + self.device_column_width:
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


if __name__ == "__main__":
    """测试代码"""
    app = QApplication(sys.argv)
    window = AutoTimeline()
    window.show()
    sys.exit(app.exec_())
