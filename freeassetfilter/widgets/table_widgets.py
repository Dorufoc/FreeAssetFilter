#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 自定义表格控件
用于时间线左侧的自定义表格实现
"""

from PyQt5.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView, QScrollArea
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtWidgets import QApplication


class CustomTimelineTable(QTableWidget):
    """
    时间线专用的自定义表格控件
    实现了与时间线条高度一致的行高，自适应字体大小等功能
    """
    
    # 定义信号
    row_clicked = pyqtSignal(int)  # 行点击信号
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 获取应用实例和全局字体
        app = QApplication.instance()
        self.global_font = getattr(app, 'global_font', QFont())
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 应用全局字体和DPI缩放
        self.setup_font()
        
        # 初始化表格配置
        self.setup_table()
        
    def setup_font(self):
        """设置字体并应用DPI缩放"""
        # 创建全局字体的副本，避免修改全局字体对象
        scaled_font = QFont(self.global_font)
        
        # 根据DPI缩放因子调整字体大小
        font_size = scaled_font.pointSize()
        if font_size > 0:
            scaled_size = int(font_size * self.dpi_scale)
            scaled_font.setPointSize(scaled_size)
        
        # 保存缩放后的字体用于单元格
        self.scaled_font = scaled_font
        
        # 设置表格字体
        self.setFont(scaled_font)
    
    def setup_table(self):
        """设置表格基本配置"""
        # 设置表格属性
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.SingleSelection)
        
        # 隐藏行号
        self.verticalHeader().setVisible(False)
        
        # 设置列宽
        self.setColumnCount(3)
        self.setHorizontalHeaderLabels(["名称", "设备", "视频数量"])
        self.setColumnWidth(0, 150)
        self.setColumnWidth(1, 100)
        self.setColumnWidth(2, 80)
        
        # 设置表头样式
        self.horizontalHeader().setStyleSheet("QHeaderView::section { background-color: #333; color: white; padding: 4px; border: 1px solid #555; }")
        
        # 设置单元格样式
        self.setStyleSheet("QTableWidget { background-color: #222; color: white; border: 1px solid #555; }" +
                           "QTableWidget::item { padding: 4px; border: 1px solid #444; }" +
                           "QTableWidget::item:selected { background-color: #4682B4; color: white; }" +
                           "QScrollBar:vertical { background: #333; width: 12px; }" +
                           "QScrollBar::handle:vertical { background: #555; border-radius: 6px; }" +
                           "QScrollBar:horizontal { background: #333; height: 12px; }" +
                           "QScrollBar::handle:horizontal { background: #555; border-radius: 6px; }")
        
    def set_row_height(self, height):
        """设置行高，确保与时间线条高度一致
        
        Args:
            height: int - 行高像素值
        """
        self.verticalHeader().setDefaultSectionSize(int(height * self.dpi_scale))
    
    def update_data(self, merged_events):
        """更新表格数据
        
        Args:
            merged_events: list - 合并后的事件列表
        """
        self.setRowCount(len(merged_events))
        
        for row_idx, merged_event in enumerate(merged_events):
            # 名称
            name_item = QTableWidgetItem(merged_event.name)
            name_item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            name_item.setFont(self.scaled_font)
            self.setItem(row_idx, 0, name_item)
            
            # 设备
            device_item = QTableWidgetItem(merged_event.device)
            device_item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            device_item.setFont(self.scaled_font)
            self.setItem(row_idx, 1, device_item)
            
            # 视频数量
            total_videos = sum(len(vids) for _, _, vids in merged_event.segments)
            video_item = QTableWidgetItem(str(total_videos))
            video_item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            video_item.setFont(self.scaled_font)
            self.setItem(row_idx, 2, video_item)
    
    def mousePressEvent(self, event):
        """处理鼠标点击事件，发送行点击信号"""
        super().mousePressEvent(event)
        index = self.currentRow()
        if index >= 0:
            self.row_clicked.emit(index)


from PyQt5.QtWidgets import QWidget, QGridLayout, QLabel, QVBoxLayout
from PyQt5.QtGui import QPalette


class MatrixCell(QWidget):
    """
    矩阵表格的单元格组件
    可以自定义颜色、边框、大小等属性
    """
    def __init__(self, text="", bg_color="#333", text_color="#fff", 
                 border_color="#555", border_width=1,
                 width=None, height=None, parent=None):
        super().__init__(parent)
        
        # 设置单元格属性
        self.text = text
        self.bg_color = bg_color
        self.text_color = text_color
        self.border_color = border_color
        self.border_width = border_width
        self.cell_width = width
        self.cell_height = height
        
        # 设置布局
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建文本标签
        self.label = QLabel(text)
        self.label.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.label)
        
        # 应用样式
        self.apply_style()
    
    def apply_style(self):
        """应用单元格样式"""
        # 设置背景颜色和文本颜色
        palette = self.label.palette()
        palette.setColor(QPalette.Background, QColor(self.bg_color))
        palette.setColor(QPalette.WindowText, QColor(self.text_color))
        self.label.setPalette(palette)
        self.label.setAutoFillBackground(True)
        
        # 设置边框
        self.setStyleSheet(f"""
            MatrixCell {{ 
                border: {self.border_width}px solid {self.border_color}; 
                background-color: {self.bg_color}; 
            }}
        """)
        
        # 设置大小
        if self.cell_width:
            self.setFixedWidth(self.cell_width)
        if self.cell_height:
            self.setFixedHeight(self.cell_height)
    
    def set_text(self, text):
        """设置单元格文本"""
        self.text = text
        self.label.setText(text)
    
    def set_bg_color(self, color):
        """设置背景颜色"""
        self.bg_color = color
        self.apply_style()
    
    def set_text_color(self, color):
        """设置文本颜色"""
        self.text_color = color
        self.apply_style()
    
    def set_border(self, color, width):
        """设置边框颜色和宽度"""
        self.border_color = color
        self.border_width = width
        self.apply_style()
    
    def set_size(self, width, height):
        """设置单元格大小"""
        self.cell_width = width
        self.cell_height = height
        self.apply_style()
    
    def setAlignment(self, alignment):
        """设置文本对齐方式"""
        self.label.setAlignment(alignment)
    
    def setFont(self, font):
        """设置字体"""
        self.label.setFont(font)


class CustomMatrixTable(QWidget):
    """
    自定义矩阵表格控件
    使用QGridLayout实现，支持自定义每个单元格的样式
    """
    
    # 定义信号
    cell_clicked = pyqtSignal(int, int)  # 单元格点击信号 (行, 列)
    row_clicked = pyqtSignal(int)  # 行点击信号
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 获取应用实例和全局字体
        app = QApplication.instance()
        self.global_font = getattr(app, 'global_font', QFont())
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 应用全局字体和DPI缩放
        self.setup_font()
        
        # 初始化表格配置
        self.rows = 0
        self.columns = 0
        self.cells = []  # 存储所有单元格
        self.column_widths = [150, 100, 80]  # 默认列宽
        self.row_height = 40  # 默认行高
        
        # 创建内部滚动区域
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # 创建内容窗口
        self.content_widget = QWidget()
        self.grid_layout = QGridLayout(self.content_widget)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(0)
        
        # 将内容窗口设置到滚动区域
        self.scroll_area.setWidget(self.content_widget)
        
        # 设置主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.scroll_area)
        
        # 初始化表格
        self.setup_table()
        
    def setup_font(self):
        """设置字体并应用DPI缩放"""
        # 创建全局字体的副本，避免修改全局字体对象
        scaled_font = QFont(self.global_font)
        
        # 根据DPI缩放因子调整字体大小
        font_size = scaled_font.pointSize()
        if font_size > 0:
            scaled_size = int(font_size * self.dpi_scale)
            scaled_font.setPointSize(scaled_size)
        
        # 保存缩放后的字体用于单元格
        self.scaled_font = scaled_font
        
        # 设置表格字体
        self.setFont(scaled_font)
    
    def setup_table(self):
        """设置表格基本配置"""
        # 清空现有布局
        for i in reversed(range(self.grid_layout.count())):
            widget = self.grid_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()
        
        # 设置网格布局对齐方式为左上角
        self.grid_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        
        # 初始化表头
        headers = ["名称", "设备", "视频数量"]
        self.columns = len(headers)
        
        # 创建表头单元格
        for col in range(self.columns):
            header_cell = MatrixCell(
                text=headers[col],
                bg_color="#222",
                text_color="#fff",
                border_color="#555",
                border_width=1,
                width=int(self.column_widths[col] * self.dpi_scale),
                height=int(30 * self.dpi_scale)  # 表头高度
            )
            header_cell.setFont(self.scaled_font)
            # 表头文本居中
            header_cell.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            self.grid_layout.addWidget(header_cell, 0, col)
        
        # 初始化数据区域
        self.rows = 0
        self.cells = []
    
    def set_column_widths(self, widths):
        """设置列宽
        
        Args:
            widths: list - 各列宽度列表
        """
        self.column_widths = widths
        self.setup_table()
    
    def set_row_height(self, height):
        """设置行高
        
        Args:
            height: int - 行高像素值
        """
        self.row_height = height
        # 更新现有行的高度
        for row in range(1, self.rows + 1):  # 从1开始，0是表头
            for col in range(self.columns):
                cell = self.cells[row - 1][col]
                cell.set_size(int(self.column_widths[col] * self.dpi_scale), int(height * self.dpi_scale))
    
    def update_data(self, merged_events):
        """更新表格数据
        
        Args:
            merged_events: list - 合并后的事件列表
        """
        # 清空现有数据行
        for row in range(1, self.rows + 1):  # 从1开始，0是表头
            for col in range(self.columns):
                widget = self.grid_layout.itemAtPosition(row, col).widget()
                if widget:
                    widget.deleteLater()
        
        # 更新行数
        self.rows = len(merged_events)
        self.cells = []
        
        # 创建新的数据行
        for row_idx, merged_event in enumerate(merged_events):
            row_cells = []
            
            # 名称列
            name_cell = MatrixCell(
                text=merged_event.name,
                bg_color="#333",
                text_color="#fff",
                border_color="#555",
                border_width=1,
                width=int(self.column_widths[0] * self.dpi_scale),
                height=int(self.row_height * self.dpi_scale)
            )
            name_cell.setFont(self.scaled_font)
            name_cell.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            self.grid_layout.addWidget(name_cell, row_idx + 1, 0)
            row_cells.append(name_cell)
            
            # 设备列
            device_cell = MatrixCell(
                text=merged_event.device,
                bg_color="#333",
                text_color="#fff",
                border_color="#555",
                border_width=1,
                width=int(self.column_widths[1] * self.dpi_scale),
                height=int(self.row_height * self.dpi_scale)
            )
            device_cell.setFont(self.scaled_font)
            device_cell.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            self.grid_layout.addWidget(device_cell, row_idx + 1, 1)
            row_cells.append(device_cell)
            
            # 视频数量列
            total_videos = sum(len(vids) for _, _, vids in merged_event.segments)
            video_cell = MatrixCell(
                text=str(total_videos),
                bg_color="#333",
                text_color="#fff",
                border_color="#555",
                border_width=1,
                width=int(self.column_widths[2] * self.dpi_scale),
                height=int(self.row_height * self.dpi_scale)
            )
            video_cell.setFont(self.scaled_font)
            video_cell.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            self.grid_layout.addWidget(video_cell, row_idx + 1, 2)
            row_cells.append(video_cell)
            
            # 添加行单元格列表
            self.cells.append(row_cells)
    
    def mousePressEvent(self, event):
        """处理鼠标点击事件，发送行点击信号"""
        # 查找点击的单元格
        for row_idx, row_cells in enumerate(self.cells):
            for col_idx, cell in enumerate(row_cells):
                if cell.geometry().contains(event.pos() - self.content_widget.geometry().topLeft()):
                    self.cell_clicked.emit(row_idx, col_idx)
                    self.row_clicked.emit(row_idx)
                    break
    
    def verticalScrollBar(self):
        """返回垂直滚动条，与QTableWidget兼容"""
        return self.scroll_area.verticalScrollBar()

