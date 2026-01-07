#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

自动时间线组件
用于多媒体资产管理与行为分析的核心可视化工具
"""

import os
import sys
import csv
from itertools import groupby

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, 
    QScrollArea, QPushButton, QLabel, QGroupBox,
    QSpinBox, QFileDialog, QApplication, QSlider, QToolTip, QHeaderView, QComboBox,
    QTextEdit, QTabWidget, QTableWidget, QTableWidgetItem, QProgressBar
)

# 导入自定义按钮组件
from freeassetfilter.widgets.button_widgets import CustomButton
from freeassetfilter.widgets.table_widgets import CustomMatrixTable
from PyQt5.QtCore import (
    Qt, pyqtSignal, QDateTime, QThread, QRectF, QPoint, QTimer
)
from PyQt5.QtGui import (
    QPainter, QColor, QLinearGradient, QBrush, QPen, QFont, QPixmap, QCursor
)

# 从core模块导入后端处理逻辑
from freeassetfilter.core.timeline_generator import (
    TimelineEvent, MergedEvent, TimelineParams,
    FolderScanner, CSVParser, merge_logic
)


# 自定义绘图引擎：TimelineWidget
class TimelineWidget(QWidget):
    """
    自定义时间线绘制组件
    继承自QWidget，重写paintEvent实现高性能2D渲染
    """
    # 定义点击事件信号，传递点击位置和对应的事件信息
    timeline_clicked = pyqtSignal(int, int, dict)
    # 定义缩放值改变信号
    scale_changed = pyqtSignal(float)
    
    def __init__(self, params):
        super().__init__()
        self.params = params
        self.data = []
        self.setMinimumHeight(600)
        self.setMinimumWidth(1200)
        self.pixmap_cache = None  # 双缓冲Pixmap缓存
        self.last_params = {}
        self.last_data_hash = None
        self.mouse_pos = QPoint()  # 鼠标位置，用于提示
        self.current_mouse_pos = QPoint()  # 当前鼠标位置，用于绘制时间竖线
        self.setMouseTracking(True)  # 启用鼠标跟踪，确保即使没有按下鼠标按钮，也能捕获到鼠标移动事件
        # 选中状态跟踪
        self.selected_event = None  # 存储当前选中的事件信息：(row_idx, start, end)
        
        # 拖动选择状态跟踪
        self.is_dragging = False  # 是否正在拖动
        self.drag_start_x = 0  # 拖动开始的X坐标
        self.drag_end_x = 0  # 拖动结束的X坐标
        self.selected_events = []  # 存储所有选中的事件信息：[(row_idx, start, end, merged_event, vids), ...]
        
        # 获取应用实例和全局字体
        app = QApplication.instance()
        # 创建全局字体的副本，避免修改全局字体对象
        global_font = getattr(app, 'global_font', QFont())
        self.global_font = QFont(global_font)
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 调整字体大小以适应DPI
        font_size = self.global_font.pointSize()
        if font_size > 0:
            scaled_size = int(font_size * self.dpi_scale)
            self.global_font.setPointSize(scaled_size)
    
    def set_data(self, data):
        """设置时间线数据"""
        self.data = data
        if data:
            # 计算全局时间范围
            all_starts = []
            all_ends = []
            for event in data:
                for start, end, _ in event.segments:
                    all_starts.append(start)
                    all_ends.append(end)
            
            if all_starts and all_ends:
                self.params.global_start_time = min(all_starts)
                self.params.global_end_time = max(all_ends)
        self.update()
    
    def paintEvent(self, event):
        """绘制时间线"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 检查是否需要重新生成缓存
        if self.needs_redraw():
            self.generate_cache()
        
        # 使用双缓冲绘制缓存的Pixmap
        if self.pixmap_cache:
            painter.drawPixmap(0, 0, self.pixmap_cache)
        else:
            # 如果缓存为空，直接绘制
            self.draw_content(painter)
        
        # 单独绘制当前鼠标位置的时间竖线（不影响缓存）
        if not self.current_mouse_pos.isNull() and self.params.global_start_time and self.params.global_end_time:
            # 获取鼠标X坐标
            mouse_x = self.current_mouse_pos.x()
            
            # 检查X坐标是否在有效范围内
            if 0 <= mouse_x <= self.width():
                # 绘制红色竖线
                painter.setPen(QPen(QColor(255, 0, 0), 1, Qt.DashLine))
                painter.drawLine(mouse_x, 0, mouse_x, self.height())
                
                # 计算当前时间
                time_offset = mouse_x / self.params.px_per_second
                current_time = self.params.global_start_time.addSecs(int(time_offset))
                
                # 显示当前时间
                painter.setPen(QPen(QColor(255, 255, 255), 1))
                time_font = QFont(self.global_font)
                time_font.setPointSize(int(10 * self.dpi_scale))
                painter.setFont(time_font)
                time_str = current_time.toString("yyyy-MM-dd HH:mm:ss")
                painter.drawText(mouse_x + 5, 20, time_str)
        
        # 绘制框选区域（如果正在拖动）
        if self.is_dragging:
            # 计算框选区域的坐标
            x1 = min(self.drag_start_x, self.drag_end_x)
            y1 = 30  # 从时间刻度下方开始
            x2 = max(self.drag_start_x, self.drag_end_x)
            y2 = self.height()
            
            # 创建半透明的蓝色填充
            painter.setBrush(QBrush(QColor(0, 100, 255, 50)))
            # 创建蓝色边框
            painter.setPen(QPen(QColor(0, 150, 255), 1))
            # 绘制矩形框选区域
            painter.drawRect(x1, y1, x2 - x1, y2 - y1)
    
    def needs_redraw(self):
        """检查是否需要重新绘制"""
        # 检查参数是否变化
        current_params = {
            'px_per_second': self.params.px_per_second,
            'row_height': self.params.row_height,
            'width': self.width(),
            'height': self.height(),
            'global_start': self.params.global_start_time,
            'global_end': self.params.global_end_time
        }
        
        # 检查数据是否变化
        if self.data:
            # 将segments中的videos列表转换为元组以支持哈希
            hashable_data = []
            for event in self.data:
                hashable_segments = []
                for start, end, videos in event.segments:
                    # 将videos列表转换为元组
                    hashable_segments.append((start, end, tuple(videos)))
                hashable_data.append((event.name, event.device, tuple(hashable_segments)))
            current_data_hash = hash(tuple(hashable_data))
        else:
            current_data_hash = None
        
        # 如果参数或数据变化，需要重新绘制
        if current_params != self.last_params or current_data_hash != self.last_data_hash:
            self.last_params = current_params
            self.last_data_hash = current_data_hash
            return True
        
        return False
    
    def generate_cache(self):
        """生成Pixmap缓存"""
        # 创建与实际内容大小相同的Pixmap
        # 内容高度：行数 * 行高 + 时间刻度高度
        content_height = max(self.height(), len(self.data) * self.params.row_height + 30)
        # 内容宽度：使用实际内容宽度，而不是控件宽度
        content_width = self.width()
        
        self.pixmap_cache = QPixmap(content_width, content_height)
        self.pixmap_cache.fill(Qt.transparent)
        
        # 在Pixmap上绘制内容
        painter = QPainter(self.pixmap_cache)
        painter.setRenderHint(QPainter.Antialiasing)
        self.draw_content(painter)
        painter.end()
    
    def draw_content(self, painter):
        """绘制时间线内容"""
        # 获取当前配置参数
        px_per_sec = self.params.px_per_second  # 缩放比例
        row_height = self.params.row_height
        
        # 绘制背景
        self.draw_background(painter)
        
        # 绘制时间刻度
        self.draw_time_scale(painter)
        
        # 绘制事件块
        for row_idx, merged_event in enumerate(self.data):
            # 计算当前行的 Y 坐标
            y_pos = row_idx * row_height + 30  # 留出时间刻度的空间
            
            # 绘制行分隔线
            painter.setPen(QPen(QColor(60, 60, 60), 1))
            painter.drawLine(0, y_pos, self.width(), y_pos)
            
            # 绘制事件块
            for start, end, vids in merged_event.segments:
                # 计算X坐标
                x_start = self.time_to_x(start)
                duration = start.secsTo(end)
                width = duration * px_per_sec
                
                # 确保宽度至少为2像素
                if width < 2:
                    width = 2
                
                # 检查是否为选中事件
                is_selected = False
                # 检查单个选中事件
                if self.selected_event is not None:
                    is_selected = (self.selected_event[0] == row_idx and 
                                  self.selected_event[1] == start and 
                                  self.selected_event[2] == end)
                # 检查多个选中事件（拖动选择）
                if not is_selected and self.selected_events:
                    for selected_event in self.selected_events:
                        if (selected_event[0] == row_idx and 
                            selected_event[1] == start and 
                            selected_event[2] == end):
                            is_selected = True
                            break
                
                # 绘制事件块
                rect = QRectF(x_start, y_pos + 5, width, row_height - 10)
                
                # 渐变填充
                gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
                color_hash = hash(merged_event.name) % 256
                
                if is_selected:
                    # 选中状态：颜色加深，边框加粗
                    gradient.setColorAt(0, QColor(60 + color_hash % 100, 125, 183))
                    gradient.setColorAt(1, QColor(16 + color_hash % 80, 87, 152))
                    painter.setBrush(QBrush(gradient))
                    painter.setPen(QPen(QColor(255, 255, 255), 2))  # 白色边框
                else:
                    # 普通状态：原始颜色
                    gradient.setColorAt(0, QColor(90 + color_hash % 100, 155, 213))
                    gradient.setColorAt(1, QColor(46 + color_hash % 80, 117, 182))
                    painter.setBrush(QBrush(gradient))
                    painter.setPen(QPen(QColor(30, 30, 30), 1))  # 普通边框
                
                painter.drawRoundedRect(rect, 4, 4)
                
                # 绘制视频数量标记
                if vids:
                    painter.setPen(QPen(Qt.white, 1))
                    # 使用全局字体，调整大小以适应视频数量标记
                    count_font = QFont(self.global_font)
                    count_font.setPointSize(int(8 * self.dpi_scale))
                    painter.setFont(count_font)
                    painter.drawText(rect.adjusted(5, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, f"{len(vids)}")

    def draw_background(self, painter):
        """绘制背景网格"""
        # 绘制主背景
        painter.fillRect(self.rect(), QColor(30, 30, 30))
        
        # 绘制垂直网格线
        if self.params.global_start_time and self.params.global_end_time:
            painter.setPen(QPen(QColor(50, 50, 50), 1))
            total_duration = self.params.global_start_time.secsTo(self.params.global_end_time)
            
            # 每30秒绘制一条网格线
            for i in range(0, int(total_duration) + 30, 30):
                x = int(self.time_to_x(self.params.global_start_time.addSecs(i)))
                painter.drawLine(x, 0, x, self.height())
    
    def draw_time_scale(self, painter):
        """绘制顶部时间刻度"""
        if not self.params.global_start_time or not self.params.global_end_time:
            return
        
        painter.setPen(QPen(Qt.white, 1))
        # 使用全局字体，调整大小以适应时间刻度
        time_font = QFont(self.global_font)
        time_font.setPointSize(int(10 * self.dpi_scale))
        painter.setFont(time_font)
        
        total_duration = self.params.global_start_time.secsTo(self.params.global_end_time)
        viewport_width = self.width()
        
        # 智能计算刻度间隔
        # 目标：使刻度数量在5-20个之间
        target_ticks = 10  # 理想刻度数量
        raw_interval = total_duration / target_ticks
        
        # 选择合适的时间间隔（秒）
        # 支持的间隔：1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400
        intervals = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400]
        
        # 找到最接近raw_interval的间隔
        interval = min(intervals, key=lambda x: abs(x - raw_interval))
        
        # 根据间隔选择合适的时间格式
        if interval < 60:  # 秒级
            format_str = "HH:mm:ss"
        elif interval < 3600:  # 分钟级
            format_str = "HH:mm"
        else:  # 小时级
            format_str = "yyyy-MM-dd HH:mm"
        
        # 计算第一个刻度的时间（向上取整到最近的间隔）
        first_tick = self.params.global_start_time
        secs_since_epoch = first_tick.toSecsSinceEpoch()
        secs_to_next_interval = interval - (secs_since_epoch % interval)
        if secs_to_next_interval < interval:  # 避免当恰好是间隔倍数时加一个间隔
            first_tick = first_tick.addSecs(secs_to_next_interval)
        
        # 绘制刻度
        current_time = first_tick
        while current_time <= self.params.global_end_time:
            x = int(self.time_to_x(current_time))
            
            # 绘制刻度线
            painter.drawLine(x, 0, x, 20)
            
            # 绘制时间文本
            time_str = current_time.toString(format_str)
            painter.drawText(x - 30, 28, 60, 20, Qt.AlignCenter, time_str)
            
            # 移动到下一个刻度
            current_time = current_time.addSecs(interval)
    
    def time_to_x(self, time):
        """将时间转换为X坐标
        
        Args:
            time: QDateTime - 要转换的时间
            
        Returns:
            float - X坐标
        """
        if not self.params.global_start_time:
            return 0
        
        # 计算与全局起始时间的秒数差
        sec_diff = self.params.global_start_time.secsTo(time)
        
        # 转换为X坐标
        return sec_diff * self.params.px_per_second
    
    def x_to_time(self, x):
        """将X坐标转换为时间
        
        Args:
            x: float - X坐标
            
        Returns:
            QDateTime - 转换后的时间
        """
        if not self.params.global_start_time:
            return QDateTime.currentDateTime()
        
        # 计算秒数差
        sec_diff = x / self.params.px_per_second
        
        # 转换为时间
        return self.params.global_start_time.addSecs(int(sec_diff))
    
    def wheelEvent(self, event):
        """处理鼠标滚轮事件，实现缩放"""
        # Ctrl + 滚轮实现缩放
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            current_scale = self.params.px_per_second
            
            if delta > 0:
                # 放大：每次增加10%或0.1x，取较大值
                new_scale = min(current_scale * 1.1, current_scale + 0.1)
            else:
                # 缩小：每次减少10%或0.1x，取较小值
                new_scale = max(current_scale * 0.9, current_scale - 0.1)
            
            # 限制缩放范围在0.1x到200x之间
            new_scale = max(0.1, min(new_scale, 200))
            
            # 更新参数
            self.params.px_per_second = new_scale
            
            # 发送缩放值改变信号
            self.scale_changed.emit(new_scale)
            
            # 更新绘制
            self.update()
            
            # 阻止事件传播，避免滚动区域响应
            event.accept()
        else:
            # 不按Ctrl键时，正常传递事件给父类
            super().wheelEvent(event)
    
    def enterEvent(self, event):
        """鼠标进入组件时显示时间竖线"""
        # 设置初始位置为鼠标当前位置
        self.current_mouse_pos = self.mapFromGlobal(QCursor.pos())
        self.update()
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        """鼠标离开组件时隐藏时间竖线"""
        self.current_mouse_pos = QPoint()  # 清空鼠标位置
        self.update()
        super().leaveEvent(event)
    
    def mouseMoveEvent(self, event):
        """处理鼠标移动事件，显示提示信息并更新当前鼠标位置，同时处理拖动选择"""
        self.mouse_pos = event.pos()
        self.current_mouse_pos = event.pos()
        
        # 如果正在拖动，更新拖动结束位置并计算选中的时间条
        if self.is_dragging:
            self.drag_end_x = event.x()
            
            # 计算拖动区域
            drag_left = min(self.drag_start_x, self.drag_end_x)
            drag_right = max(self.drag_start_x, self.drag_end_x)
            
            # 如果没有按住ctrl键，清除之前的选中事件，否则保留
            if not event.modifiers() & Qt.ControlModifier:
                new_selected_events = []
            else:
                # 复制现有选中事件
                new_selected_events = self.selected_events.copy()
            
            # 检查所有事件块是否与拖动区域重叠
            for row_idx, merged_event in enumerate(self.data):
                # 遍历当前行的所有事件块
                for start, end, vids in merged_event.segments:
                    x_start = self.time_to_x(start)
                    duration = start.secsTo(end)
                    width = duration * self.params.px_per_second
                    x_end = x_start + width
                    
                    # 检查事件块是否与拖动区域重叠
                    if not (x_end < drag_left or x_start > drag_right):
                        # 检查事件是否已经在选中列表中
                        event_key = (row_idx, start.toString(), end.toString())
                        is_already_selected = any(
                            (item[0] == row_idx and 
                             item[1].toString() == start.toString() and 
                             item[2].toString() == end.toString()) 
                            for item in new_selected_events
                        )
                        
                        if not is_already_selected:
                            # 添加到选中事件列表
                            new_selected_events.append((row_idx, start, end, merged_event, vids))
            
            # 更新选中事件列表
            self.selected_events = new_selected_events
            
            # 清除缓存以触发重绘
            self.pixmap_cache = None
            self.update()
        else:
            # 普通鼠标移动，显示提示信息
            # 检查是否在事件块上
            for row_idx, merged_event in enumerate(self.data):
                y_pos = row_idx * self.params.row_height + 30
                
                # 检查Y坐标是否在当前行
                if y_pos < event.y() < y_pos + self.params.row_height:
                    # 检查X坐标是否在某个事件块上
                    for start, end, vids in merged_event.segments:
                        x_start = self.time_to_x(start)
                        duration = start.secsTo(end)
                        width = duration * self.params.px_per_second
                        
                        if x_start < event.x() < x_start + width:
                            # 显示提示信息
                            tooltip_text = f"{merged_event.name}\n"
                            tooltip_text += f"设备: {merged_event.device}\n"
                            tooltip_text += f"开始时间: {start.toString('yyyy-MM-dd HH:mm:ss')}\n"
                            tooltip_text += f"结束时间: {end.toString('yyyy-MM-dd HH:mm:ss')}\n"
                            tooltip_text += f"视频数量: {len(vids)}"
                            QToolTip.showText(event.globalPos(), tooltip_text, self)
                            self.update()  # 触发重绘以更新时间竖线
                            return
            
            # 如果不在任何事件块上，显示当前时间
            current_time = self.x_to_time(event.x())
            tooltip_text = current_time.toString('yyyy-MM-dd HH:mm:ss')
            QToolTip.showText(event.globalPos(), tooltip_text, self)
        
        self.update()  # 触发重绘以更新时间竖线
    
    def mousePressEvent(self, event):
        """处理鼠标点击事件，记录拖动起始位置"""
        # 记录拖动起始位置
        self.drag_start_x = event.x()
        self.drag_end_x = event.x()
        self.is_dragging = True
        
        # 只有在没有按住ctrl键时才清除之前的选中状态
        if not event.modifiers() & Qt.ControlModifier:
            self.selected_events = []
            self.selected_event = None
        
        # 清除缓存以触发重绘
        self.pixmap_cache = None
        self.update()
    
    def mouseReleaseEvent(self, event):
        """处理鼠标释放事件，完成拖动选择并发送选中事件信息"""
        if self.is_dragging:
            self.is_dragging = False
            
            # 计算拖动距离
            drag_distance = abs(self.drag_end_x - self.drag_start_x)
            
            # 如果拖动距离很小，视为单击
            if drag_distance < 5:  # 阈值设为5像素
                # 处理为单击事件
                click_x = event.x()
                click_y = event.y()
                
                # 检查是否在事件块上
                found_event = False
                clicked_event = None
                
                for row_idx, merged_event in enumerate(self.data):
                    y_pos = row_idx * self.params.row_height + 30
                    
                    # 检查Y坐标是否在当前行
                    if y_pos < click_y < y_pos + self.params.row_height:
                        # 检查X坐标是否在某个事件块上
                        for start, end, vids in merged_event.segments:
                            x_start = self.time_to_x(start)
                            duration = start.secsTo(end)
                            width = duration * self.params.px_per_second
                            
                            if x_start < click_x < x_start + width:
                                clicked_event = (row_idx, start, end, merged_event, vids)
                                found_event = True
                                break
                        if found_event:
                            break
                
                # 处理点击事件
                if found_event:
                    row_idx, start, end, merged_event, vids = clicked_event
                    event_key = (row_idx, start.toString(), end.toString())
                    
                    # 检查事件是否已经被选中
                    is_selected = any(
                        (item[0] == row_idx and 
                         item[1].toString() == start.toString() and 
                         item[2].toString() == end.toString()) 
                        for item in self.selected_events
                    )
                    
                    # 如果按住ctrl键
                    if event.modifiers() & Qt.ControlModifier:
                        if is_selected:
                            # 取消选中
                            self.selected_events = [
                                item for item in self.selected_events 
                                if not (item[0] == row_idx and 
                                       item[1].toString() == start.toString() and 
                                       item[2].toString() == end.toString())
                            ]
                        else:
                            # 添加到选中列表
                            self.selected_events.append(clicked_event)
                    else:
                        # 普通点击，替换选中列表
                        self.selected_events = [clicked_event]
                    
                    # 更新selected_event（主要用于高亮显示）
                    self.selected_event = (row_idx, start, end)
                    
                    # 准备点击事件信息
                    event_info = {
                        'selected_events': []
                    }
                    
                    for selected_row, selected_start, selected_end, selected_merged, selected_vids in self.selected_events:
                        selected_duration = selected_start.secsTo(selected_end)
                        event_info['selected_events'].append({
                            'name': selected_merged.name,
                            'device': selected_merged.device,
                            'start_time': selected_start.toString('yyyy-MM-dd HH:mm:ss'),
                            'end_time': selected_end.toString('yyyy-MM-dd HH:mm:ss'),
                            'duration': selected_duration,
                            'video_count': len(selected_vids),
                            'video_paths': selected_vids
                        })
                    
                    # 发送信号
                    self.timeline_clicked.emit(click_x, click_y, event_info)
                else:
                    # 如果不在任何事件块上
                    if not (event.modifiers() & Qt.ControlModifier):
                        # 清除选中状态
                        self.selected_events = []
                        self.selected_event = None
                    # 发送点击位置和事件信息
                    event_info = {
                        'selected_events': []
                    }
                    
                    for selected_row, selected_start, selected_end, selected_merged, selected_vids in self.selected_events:
                        selected_duration = selected_start.secsTo(selected_end)
                        event_info['selected_events'].append({
                            'name': selected_merged.name,
                            'device': selected_merged.device,
                            'start_time': selected_start.toString('yyyy-MM-dd HH:mm:ss'),
                            'end_time': selected_end.toString('yyyy-MM-dd HH:mm:ss'),
                            'duration': selected_duration,
                            'video_count': len(selected_vids),
                            'video_paths': selected_vids
                        })
                    
                    self.timeline_clicked.emit(event.x(), event.y(), event_info)
            else:
                # 处理为拖动选择事件
                if self.selected_events:
                    # 准备选中事件信息
                    event_info = {
                        'selected_events': []
                    }
                    
                    for row_idx, start, end, merged_event, vids in self.selected_events:
                        duration = start.secsTo(end)
                        event_info['selected_events'].append({
                            'name': merged_event.name,
                            'device': merged_event.device,
                            'start_time': start.toString('yyyy-MM-dd HH:mm:ss'),
                            'end_time': end.toString('yyyy-MM-dd HH:mm:ss'),
                            'duration': duration,
                            'video_count': len(vids),
                            'video_paths': vids
                        })
                    
                    # 发送信号
                    self.timeline_clicked.emit(event.x(), event.y(), event_info)
                else:
                    # 如果没有选中任何事件，发送空信息
                    self.timeline_clicked.emit(event.x(), event.y(), {})
            
            # 清除缓存以触发重绘
            self.pixmap_cache = None
            self.update()


# 自动时间线主组件
class AutoTimeline(QWidget):
    """
    自动时间线主组件
    整合数据加载、处理和可视化功能
    """
    # 定义JSON结果信号，传递格式化后的JSON数据
    json_result_ready = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        
        # 获取应用实例和DPI缩放因子
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 获取全局字体并应用DPI缩放（创建副本避免修改全局字体）
        global_font = getattr(app, 'global_font', QFont())
        self.global_font = QFont(global_font)
        # 根据DPI缩放因子调整字体大小
        font_size = self.global_font.pointSize()
        if font_size > 0:
            scaled_size = int(font_size * self.dpi_scale)
            self.global_font.setPointSize(scaled_size)
        
        # 设置组件字体
        self.setFont(self.global_font)
        
        # 初始化参数
        self.params = TimelineParams()
        self.params.dpi_scale = self.dpi_scale
        self.params.row_height = int(40 * self.dpi_scale)  # 恢复原来的行高，不影响时间线显示
        
        # 初始化数据
        self.raw_events = []
        self.merged_events = []
        
        # 初始化UI
        self.init_ui()
        
        # 初始化扫描线程
        self.scanner = None
        self.csv_parser = None
        
        # 初始化JSON显示组件
        self.json_display_widget = None
        
        # 添加延时检测定时器
        self.delay_detection_timer = QTimer(self)
        self.delay_detection_timer.setInterval(500)  # 500ms检测一次
        self.delay_detection_timer.timeout.connect(self.check_and_adjust_timeline)
        
        # 初始化完成标志
        self.initialized = False
    
    def init_ui(self):
        """初始化用户界面"""
        # 创建主布局
        main_layout = QVBoxLayout(self)
        
        # 创建控制面板
        control_panel = self.create_control_panel()
        main_layout.addWidget(control_panel)
        
        # 创建进度条区域
        self.progress_layout = QHBoxLayout()
        self.progress_label = QLabel("进度:")
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)  # 初始隐藏
        
        self.progress_layout.addWidget(self.progress_label)
        self.progress_layout.addWidget(self.progress_bar)
        main_layout.addLayout(self.progress_layout)
        
        # 创建QSplitter布局，左侧固定信息列，右侧动态时间轨迹
        self.splitter = QSplitter(Qt.Horizontal)
        
        # 左侧固定列 (基于QTableWidget)
        self.left_table = self.create_left_table()
        # 设置左侧表格行高与右侧时间线行高一致
        self.left_table.set_row_height(self.params.row_height)
        self.splitter.addWidget(self.left_table)
        
        # 右侧时间轴绘图区 (基于自定义QWidget)
        self.timeline_draw_area = TimelineWidget(self.params)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidget(self.timeline_draw_area)
        self.scroll_area.setWidgetResizable(True)
        self.splitter.addWidget(self.scroll_area)
        
        # 设置初始比例
        self.splitter.setSizes([330, 600])  # 调整左侧表格初始宽度为三列总和
        
        # 监听splitter尺寸变化，实时调整左侧表格宽度
        self.splitter.splitterMoved.connect(self.on_splitter_moved)
        
        # 添加到主布局
        main_layout.addWidget(self.splitter, 1)
        
        # 创建JSON显示组件
        self.create_json_display()
        main_layout.addWidget(self.json_display_widget)
        
        # 垂直同步滚动
        self.left_table.verticalScrollBar().valueChanged.connect(
            self.scroll_area.verticalScrollBar().setValue
        )
        self.scroll_area.verticalScrollBar().valueChanged.connect(
            self.left_table.verticalScrollBar().setValue
        )
        
        # 连接时间线点击信号
        self.timeline_draw_area.timeline_clicked.connect(self.on_timeline_clicked)
        
        # 连接时间线缩放变化信号
        self.timeline_draw_area.scale_changed.connect(self.on_timeline_scale_changed)
        
        # 保存原始的resizeEvent并连接窗口大小变化信号
        if not hasattr(self.window(), '_old_resizeEvent'):
            self.window()._old_resizeEvent = self.window().resizeEvent
        self.window().resizeEvent = self.on_window_resize
    
    def showEvent(self, event):
        """窗口显示事件，用于初始化时间线"""
        super().showEvent(event)
        
        # 启动延时检测定时器
        self.delay_detection_timer.start()
        
        # 如果已经有数据，延时调整时间线宽度和左侧表格宽度
        if self.merged_events:
            QTimer.singleShot(100, self.adjust_timeline_width)
            QTimer.singleShot(100, self.adjust_left_table_width)
    
    def hideEvent(self, event):
        """窗口隐藏事件，用于停止定时器"""
        super().hideEvent(event)
        
        # 停止延时检测定时器
        self.delay_detection_timer.stop()
    
    def adjust_left_table_width(self):
        """调整左侧表格宽度，使其与左侧伸缩区域宽度匹配"""
        # 获取当前分割器位置
        if hasattr(self, 'splitter') and self.splitter.count() > 0:
            # 获取左侧面板的实际宽度
            left_width = self.splitter.sizes()[0]
            
            # 根据默认列宽比例（15:10:8）计算各列的新宽度
            total_ratio = 15 + 10 + 8  # 总比例
            
            # 计算各列的新宽度
            name_width = int(left_width * 15 / total_ratio)
            device_width = int(left_width * 10 / total_ratio)
            video_width = int(left_width * 8 / total_ratio)
            
            # 设置新的列宽
            new_widths = [name_width, device_width, video_width]
            self.left_table.set_column_widths(new_widths)
            
            # 更新表格数据以应用新的列宽
            if self.merged_events:
                self.left_table.update_data(self.merged_events)

    def on_window_resize(self, event):
        """处理窗口大小变化事件"""
        # 调用原窗口的resizeEvent
        if hasattr(self.window(), '_old_resizeEvent'):
            self.window()._old_resizeEvent(event)
        
        # 延时调整时间线宽度和左侧表格宽度
        if self.merged_events:
            QTimer.singleShot(100, self.adjust_timeline_width)
            QTimer.singleShot(100, self.adjust_left_table_width)
    
    def check_and_adjust_timeline(self):
        """延时检测并调整时间线宽度和左侧表格宽度"""
        if not self.initialized and self.merged_events:
            # 初次加载完成后调整时间线宽度和左侧表格宽度
            self.adjust_timeline_width()
            self.adjust_left_table_width()
            self.initialized = True
            
        # 检查时间线宽度是否需要调整
        if self.merged_events and self.params.global_start_time and self.params.global_end_time:
            # 计算期望的宽度
            total_duration = self.params.global_start_time.secsTo(self.params.global_end_time)
            expected_width = total_duration * self.params.px_per_second + 100
            
            # 如果当前宽度与期望宽度差异较大，调整时间线宽度
            if abs(self.timeline_draw_area.width() - expected_width) > 100:
                self.adjust_timeline_width()
            
            # 始终调整左侧表格宽度，确保与左侧伸缩区域匹配
            self.adjust_left_table_width()
    
    def create_control_panel(self):
        """创建控制面板"""
        panel = QGroupBox("控制面板")
        layout = QHBoxLayout(panel)
        
        # 导入按钮
        import_folder_btn = CustomButton("导入文件夹")
        import_folder_btn.clicked.connect(self.import_folder)
        layout.addWidget(import_folder_btn)
        
        import_csv_btn = CustomButton("导入CSV")
        import_csv_btn.clicked.connect(self.import_csv)
        layout.addWidget(import_csv_btn)
        
        # 容差设置
        layout.addWidget(QLabel("容差:"))
        self.gap_threshold_spinbox = QSpinBox()
        self.gap_threshold_spinbox.setRange(1, 3600)
        self.gap_threshold_spinbox.setValue(30)
        self.gap_threshold_spinbox.valueChanged.connect(self.on_gap_threshold_changed)
        layout.addWidget(self.gap_threshold_spinbox)
        
        # 容差单位选择
        self.gap_threshold_unit_combo = QComboBox()
        self.gap_threshold_unit_combo.addItems(["秒", "分", "时"])
        self.gap_threshold_unit_combo.setCurrentIndex(0)
        self.gap_threshold_unit_combo.currentIndexChanged.connect(self.on_gap_threshold_unit_changed)
        layout.addWidget(self.gap_threshold_unit_combo)
        
        # 缩放设置
        layout.addWidget(QLabel("缩放:"))
        self.scale_slider = QSlider(Qt.Horizontal)
        self.scale_slider.setRange(1, 1000)  # 0.1到100秒/像素 (通过除以10实现)
        self.scale_slider.setValue(10)  # 默认1秒/像素
        self.scale_slider.setSingleStep(1)
        self.scale_slider.setPageStep(10)
        self.scale_slider.valueChanged.connect(self.on_scale_changed)
        layout.addWidget(self.scale_slider)
        
        # 显示当前缩放比例（每像素代表的秒数）
        self.scale_label = QLabel("1秒/像素")
        self.scale_label.setFixedWidth(40)
        layout.addWidget(self.scale_label)
        
        # 刷新按钮
        refresh_btn = CustomButton("刷新")
        refresh_btn.clicked.connect(self.refresh_timeline)
        layout.addWidget(refresh_btn)
        
        return panel
    
    def create_left_table(self):
        """创建左侧固定信息列"""
        table = CustomMatrixTable()
        
        # 连接信号
        table.row_clicked.connect(self.on_table_row_clicked)
        
        return table
    
    def import_folder(self):
        """导入文件夹，生成时间线"""
        folder_path = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if not folder_path:
            return
        
        print(f"用户选择了文件夹: {folder_path}")
        
        # 显示进度条
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        # 启动扫描线程
        self.scanner = FolderScanner(folder_path)
        self.scanner.scan_finished.connect(self.on_scan_finished)
        self.scanner.progress.connect(self.on_progress_update)
        self.scanner.start()
        print(f"扫描线程已启动")
    
    def import_csv(self):
        """导入CSV文件，生成时间线"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择CSV文件", "", "CSV Files (*.csv);;All Files (*)"
        )
        if not file_path:
            return
        
        # 显示进度条
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        # 启动CSV解析线程
        self.csv_parser = CSVParser(file_path)
        self.csv_parser.finished.connect(self.on_csv_parse_finished)
        self.csv_parser.progress.connect(self.on_progress_update)
        self.csv_parser.start()
    
    def on_progress_update(self, current, total):
        """更新进度条"""
        if total > 0:
            progress = int((current / total) * 100)
            self.progress_bar.setValue(progress)
        
    def on_scan_finished(self, events, csv_path, json_path):
        """文件夹扫描完成"""
        if not events:
            return
        
        # 隐藏进度条
        self.progress_bar.setVisible(False)
        
        print(f"扫描完成，已生成CSV文件: {csv_path}")
        print(f"扫描完成，已生成JSON记录: {json_path}")
        
        # 保存生成的文件路径
        self.generated_csv_path = csv_path
        self.generated_json_path = json_path
        
        # 使用CSVParser解析生成的CSV
        self.csv_parser = CSVParser(csv_path)
        self.csv_parser.finished.connect(self.on_csv_parse_finished)
        self.csv_parser.progress.connect(self.on_progress_update)
        self.csv_parser.start()
    
    def on_csv_parse_finished_with_cleanup(self, events):
        """CSV解析完成并清理临时文件"""
        self.on_csv_parse_finished(events)
        
        # 删除临时文件
        import os
        if hasattr(self, 'temp_csv_path') and os.path.exists(self.temp_csv_path):
            os.unlink(self.temp_csv_path)
            delattr(self, 'temp_csv_path')
    
    def on_csv_parse_finished(self, events):
        """CSV解析完成"""
        # 隐藏进度条
        self.progress_bar.setVisible(False)
        
        self.raw_events = events
        self.process_events()
        
        # 重置初始化标志，让延时检测重新调整时间线
        self.initialized = False
    
    def process_events(self):
        """处理事件，执行合并算法"""
        if not self.raw_events:
            return
        
        # 执行合并算法
        self.merged_events = merge_logic(self.raw_events, self.params.gap_threshold_seconds)
        
        # 更新左侧表格
        self.update_left_table()
        
        # 更新时间线
        self.timeline_draw_area.set_data(self.merged_events)
        
        # 调整时间线宽度和左侧表格宽度（延时执行，确保UI已更新）
        QTimer.singleShot(200, self.adjust_timeline_width)
        QTimer.singleShot(200, self.adjust_left_table_width)
    
    def update_left_table(self):
        """更新左侧表格"""
        # 使用自定义表格的update_data方法
        self.left_table.update_data(self.merged_events)
        
        # 设置表格行高与时间线条高度一致
        self.left_table.set_row_height(self.params.row_height)  # 与时间线的row_height保持一致
    
    def on_table_row_clicked(self, row_idx):
        """处理表格行点击事件"""
        print(f"表格行点击: {row_idx}")
        # 这里可以添加行点击后的处理逻辑，比如高亮对应的时间线
    
    def on_timeline_clicked(self, x, y, event_info):
        """处理时间线点击事件，将事件信息转换为JSON格式并显示"""
        import json
        import os
        
        if event_info:
            # 创建JSON格式的事件信息
            json_data = {
                "click_position": {
                    "x": x,
                    "y": y
                },
                "event_info": event_info
            }
            
            # 格式化JSON数据
            json_str = json.dumps(json_data, ensure_ascii=False, indent=2)
            
            # 显示JSON数据
            self.json_text_edit.setText(json_str)
            
            # 清空文件列表表格
            self.file_list_table.setRowCount(0)
            
            # 添加文件列表到表格
            video_paths = []
            
            # 检查是否有多个选中事件
            if "selected_events" in event_info:
                # 合并所有选中事件的video_paths
                for selected_event in event_info["selected_events"]:
                    video_paths.extend(selected_event.get("video_paths", []))
            else:
                # 单个选中事件
                video_paths = event_info.get("video_paths", [])
            
            self.file_list_table.setRowCount(len(video_paths))
            
            for row, path in enumerate(video_paths):
                # 获取文件名
                file_name = os.path.basename(path)
                
                # 创建表格项
                name_item = QTableWidgetItem(file_name)
                path_item = QTableWidgetItem(path)
                
                # 设置表格项
                self.file_list_table.setItem(row, 0, name_item)
                self.file_list_table.setItem(row, 1, path_item)
            
            # 发送JSON结果信号
            self.json_result_ready.emit(json_str)
            
            # 打印JSON结果（用于调试）
            print("点击事件的JSON结果:")
            print(json_str)
        else:
            # 点击了空白区域，清空显示
            self.json_text_edit.setText("")
            self.file_list_table.setRowCount(0)
            print("点击了时间线空白区域")
    
    def adjust_timeline_width(self):
        """调整时间线宽度"""
        if not self.merged_events or not self.params.global_start_time or not self.params.global_end_time:
            return
        
        # 计算总宽度
        total_duration = self.params.global_start_time.secsTo(self.params.global_end_time)
        total_width = total_duration * self.params.px_per_second + 100
        
        # 设置时间线宽度
        self.timeline_draw_area.setMinimumWidth(int(total_width))
    
    def on_gap_threshold_changed(self, value):
        """容差设置改变"""
        self.params.gap_threshold = value
        if self.raw_events:
            self.process_events()
    
    def on_gap_threshold_unit_changed(self, index):
        """容差单位设置改变"""
        units = ['sec', 'min', 'hour']
        self.params.gap_threshold_unit = units[index]
        if self.raw_events:
            self.process_events()
    
    def on_splitter_moved(self, pos, index):
        """处理分割器移动事件，实时调整左侧表格宽度"""
        # 获取左侧分割器的宽度
        left_width = pos
        
        # 根据默认列宽比例（15:10:8）计算新的列宽
        total_ratio = 15 + 10 + 8  # 总比例
        
        # 计算各列的新宽度
        name_width = int(left_width * 15 / total_ratio)
        device_width = int(left_width * 10 / total_ratio)
        video_width = int(left_width * 8 / total_ratio)
        
        # 设置新的列宽
        new_widths = [name_width, device_width, video_width]
        self.left_table.set_column_widths(new_widths)
        
        # 更新表格数据以应用新的列宽
        if self.merged_events:
            self.left_table.update_data(self.merged_events)
    
    def create_json_display(self):
        """创建JSON显示组件，包含JSON数据和文件列表两个标签页"""
        # 创建标签页组件
        self.json_display_widget = QTabWidget()
        self.json_display_widget.setFixedHeight(int(300 * self.dpi_scale))
        
        # 创建JSON文本显示标签页
        self.json_text_edit = QTextEdit()
        self.json_text_edit.setReadOnly(True)
        self.json_text_edit.setStyleSheet("background-color: #2b2b2b; color: #f0f0f0; font-family: Consolas, monospace;")
        self.json_display_widget.addTab(self.json_text_edit, "JSON数据")
        
        # 创建文件列表表格标签页
        self.file_list_table = QTableWidget()
        self.file_list_table.setColumnCount(2)
        self.file_list_table.setHorizontalHeaderLabels(["文件名", "文件路径"])
        self.file_list_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.json_display_widget.addTab(self.file_list_table, "文件列表")
    
    def on_scale_changed(self, value):
        """缩放设置改变"""
        # 将滑块值转换为0.1秒的粒度
        secs_per_pixel = value / 10.0
        self.params.px_per_second = 1.0 / secs_per_pixel  # 每像素代表的秒数的倒数
        self.scale_label.setText(f"{secs_per_pixel:.1f}秒/像素")
        self.timeline_draw_area.update()
        
        # 调整时间线宽度（延时执行，确保UI已更新）
        QTimer.singleShot(100, self.adjust_timeline_width)
        
    def on_timeline_scale_changed(self, scale):
        """时间线缩放值改变（从TimelineWidget接收信号）"""
        # 将缩放值转换为滑块值
        secs_per_pixel = 1.0 / scale
        slider_value = secs_per_pixel * 10.0
        
        # 更新滑块位置（不触发信号，避免循环更新）
        self.scale_slider.blockSignals(True)
        self.scale_slider.setValue(int(round(slider_value)))
        self.scale_slider.blockSignals(False)
        
        # 更新缩放标签
        self.scale_label.setText(f"{secs_per_pixel:.1f}秒/像素")
        
        # 调整时间线宽度
        QTimer.singleShot(100, self.adjust_timeline_width)
    
    def refresh_timeline(self):
        """刷新时间线"""
        if self.raw_events:
            self.process_events()


if __name__ == "__main__":
    """测试代码"""
    import sys
    from PyQt5.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    # 设置全局字体
    font = QFont("Microsoft YaHei", 9)
    app.setFont(font)
    
    # 创建自动时间线组件
    timeline = AutoTimeline()
    timeline.setWindowTitle("自动时间线测试")
    timeline.resize(800, 600)
    timeline.show()
    
    sys.exit(app.exec_())