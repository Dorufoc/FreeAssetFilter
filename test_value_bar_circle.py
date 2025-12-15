#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试自定义数值控制条控件（圆形滑块版本）
用于验证不同缩放级别和数值控制条长度下，圆形滑块的显示效果、缩放同步性及中线对齐准确性
"""

import sys
import warnings

# 忽略所有PyQt5相关的弃用警告
warnings.filterwarnings("ignore", category=DeprecationWarning, module="PyQt5")
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*sipPyTypeDict.*")

from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                             QWidget, QLabel, QSlider, QPushButton, QFrame, QGroupBox)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from freeassetfilter.widgets.custom_widgets import CustomValueBar

class TestValueBarApp(QMainWindow):
    """
    测试CustomValueBar控件的应用程序
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("自定义数值控制条测试 - 圆形滑块版本")
        self.setGeometry(100, 100, 1000, 600)
        
        # 获取应用实例，设置全局字体和DPI缩放因子
        self.app = QApplication.instance()
        self.app.global_font = QFont("Microsoft YaHei", 9)
        self.app.dpi_scale_factor = 1.0
        
        # 初始化UI
        self.init_ui()
    
    def init_ui(self):
        """
        初始化UI组件
        """
        # 主布局
        main_layout = QVBoxLayout()
        
        # 创建控制区域，用于调整参数
        control_group = QGroupBox("控制参数")
        control_layout = QHBoxLayout()
        
        # DPI缩放因子控制
        dpi_label = QLabel("DPI缩放因子:")
        self.dpi_slider = QSlider(Qt.Horizontal)
        self.dpi_slider.setMinimum(5)
        self.dpi_slider.setMaximum(30)
        self.dpi_slider.setValue(10)
        self.dpi_slider.setTickInterval(5)
        self.dpi_slider.setSingleStep(1)
        self.dpi_slider.setTickPosition(QSlider.TicksBelow)
        self.dpi_value_label = QLabel("1.0")
        self.dpi_slider.valueChanged.connect(self.on_dpi_change)
        
        control_layout.addWidget(dpi_label)
        control_layout.addWidget(self.dpi_slider)
        control_layout.addWidget(self.dpi_value_label)
        control_layout.addSpacing(20)
        
        # 数值条长度控制
        length_label = QLabel("数值条长度:")
        self.length_slider = QSlider(Qt.Horizontal)
        self.length_slider.setMinimum(100)
        self.length_slider.setMaximum(800)
        self.length_slider.setValue(400)
        self.length_slider.setTickInterval(100)
        self.length_slider.setSingleStep(10)
        self.length_slider.setTickPosition(QSlider.TicksBelow)
        self.length_value_label = QLabel("400px")
        self.length_slider.valueChanged.connect(self.on_length_change)
        
        control_layout.addWidget(length_label)
        control_layout.addWidget(self.length_slider)
        control_layout.addWidget(self.length_value_label)
        control_layout.addSpacing(20)
        
        # 数值控制
        value_label = QLabel("数值:")
        self.value_slider = QSlider(Qt.Horizontal)
        self.value_slider.setMinimum(0)
        self.value_slider.setMaximum(1000)
        self.value_slider.setValue(500)
        self.value_slider.setTickInterval(100)
        self.value_slider.setSingleStep(10)
        self.value_slider.setTickPosition(QSlider.TicksBelow)
        self.value_label = QLabel("50%")
        self.value_slider.valueChanged.connect(self.on_value_change)
        
        control_layout.addWidget(value_label)
        control_layout.addWidget(self.value_slider)
        control_layout.addWidget(self.value_label)
        
        control_group.setLayout(control_layout)
        main_layout.addWidget(control_group)
        
        # 创建测试区域
        test_group = QGroupBox("测试区域")
        test_layout = QVBoxLayout()
        
        # 创建水平数值控制条测试
        horizontal_group = QGroupBox("水平方向")
        horizontal_layout = QVBoxLayout()
        
        self.horizontal_value_bar = CustomValueBar(orientation=CustomValueBar.Horizontal)
        self.horizontal_value_bar.setValue(500)
        self.horizontal_value_bar.setRange(0, 1000)
        self.horizontal_value_bar.setMinimumHeight(40)
        self.horizontal_value_bar.valueChanged.connect(self.on_value_bar_change)
        
        horizontal_layout.addWidget(self.horizontal_value_bar)
        
        # 添加调试信息
        self.horizontal_debug_label = QLabel("调试信息：")
        horizontal_layout.addWidget(self.horizontal_debug_label)
        
        horizontal_group.setLayout(horizontal_layout)
        test_layout.addWidget(horizontal_group)
        
        # 创建垂直数值控制条测试
        vertical_group = QGroupBox("垂直方向")
        vertical_layout = QHBoxLayout()
        
        self.vertical_value_bar = CustomValueBar(orientation=CustomValueBar.Vertical)
        self.vertical_value_bar.setValue(500)
        self.vertical_value_bar.setRange(0, 1000)
        self.vertical_value_bar.setMinimumWidth(40)
        self.vertical_value_bar.valueChanged.connect(self.on_value_bar_change)
        
        vertical_layout.addWidget(self.vertical_value_bar)
        
        # 添加调试信息
        self.vertical_debug_label = QLabel("调试信息：")
        vertical_layout.addWidget(self.vertical_debug_label)
        
        vertical_group.setLayout(vertical_layout)
        test_layout.addWidget(vertical_group)
        
        test_group.setLayout(test_layout)
        main_layout.addWidget(test_group, 1)
        
        # 设置主窗口中心部件
        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)
        
        # 更新调试信息
        self.update_debug_info()
    
    def on_dpi_change(self, value):
        """
        DPI缩放因子变化事件
        """
        dpi_scale = value / 10.0
        self.app.dpi_scale_factor = dpi_scale
        self.dpi_value_label.setText(f"{dpi_scale:.1f}")
        
        # 重新创建数值控制条，以应用新的DPI缩放因子
        self.recreate_value_bars()
        
        # 更新调试信息
        self.update_debug_info()
    
    def on_length_change(self, value):
        """
        数值条长度变化事件
        """
        self.length_value_label.setText(f"{value}px")
        
        # 更新数值控制条长度
        self.horizontal_value_bar.setMinimumWidth(value)
        self.vertical_value_bar.setMinimumHeight(value)
        
        # 更新调试信息
        self.update_debug_info()
    
    def on_value_change(self, value):
        """
        数值变化事件
        """
        percent = (value / 1000.0) * 100
        self.value_label.setText(f"{percent:.0f}%")
        
        # 更新数值控制条的值
        self.horizontal_value_bar.setValue(value)
        self.vertical_value_bar.setValue(value)
    
    def on_value_bar_change(self, value):
        """
        数值控制条值变化事件
        """
        percent = (value / 1000.0) * 100
        self.value_label.setText(f"{percent:.0f}%")
        self.value_slider.setValue(value)
        
        # 更新调试信息
        self.update_debug_info()
    
    def recreate_value_bars(self):
        """
        重新创建数值控制条，以应用新的DPI缩放因子
        """
        # 保存当前值
        current_value = self.horizontal_value_bar.value()
        
        # 创建新的水平数值控制条
        new_horizontal_bar = CustomValueBar(orientation=CustomValueBar.Horizontal)
        new_horizontal_bar.setValue(current_value)
        new_horizontal_bar.setRange(0, 1000)
        new_horizontal_bar.setMinimumHeight(40)
        new_horizontal_bar.setMinimumWidth(self.length_slider.value())
        new_horizontal_bar.valueChanged.connect(self.on_value_bar_change)
        
        # 替换水平数值控制条
        # 直接使用已保存的布局引用，避免findChild查找失败
        horizontal_layout = self.horizontal_value_bar.parent().layout()
        if horizontal_layout:
            # 移除旧的水平数值控制条
            horizontal_layout.removeWidget(self.horizontal_value_bar)
            self.horizontal_value_bar.deleteLater()
            # 添加新的水平数值控制条
            horizontal_layout.insertWidget(0, new_horizontal_bar)
            # 更新引用
            self.horizontal_value_bar = new_horizontal_bar
        
        # 创建新的垂直数值控制条
        new_vertical_bar = CustomValueBar(orientation=CustomValueBar.Vertical)
        new_vertical_bar.setValue(current_value)
        new_vertical_bar.setRange(0, 1000)
        new_vertical_bar.setMinimumWidth(40)
        new_vertical_bar.setMinimumHeight(self.length_slider.value())
        new_vertical_bar.valueChanged.connect(self.on_value_bar_change)
        
        # 替换垂直数值控制条
        # 直接使用已保存的布局引用，避免findChild查找失败
        vertical_layout = self.vertical_value_bar.parent().layout()
        if vertical_layout:
            # 移除旧的垂直数值控制条
            vertical_layout.removeWidget(self.vertical_value_bar)
            self.vertical_value_bar.deleteLater()
            # 添加新的垂直数值控制条
            vertical_layout.insertWidget(0, new_vertical_bar)
            # 更新引用
            self.vertical_value_bar = new_vertical_bar
    
    def update_debug_info(self):
        """
        更新调试信息
        """
        # 水平数值控制条调试信息
        horizontal_info = [
            f"水平数值控制条:",
            f"  值: {self.horizontal_value_bar.value()} (范围: {self.horizontal_value_bar._minimum} - {self.horizontal_value_bar._maximum})",
            f"  宽度: {self.horizontal_value_bar.width()}px",
            f"  高度: {self.horizontal_value_bar.height()}px",
            f"  滑块半径: {self.horizontal_value_bar._handle_radius}px",
            f"  边框宽度: {self.horizontal_value_bar._handle_border_width}px",
            f"  进度条高度: {self.horizontal_value_bar._bar_size}px",
            f"  DPI缩放因子: {self.app.dpi_scale_factor}"
        ]
        self.horizontal_debug_label.setText("\n".join(horizontal_info))
        
        # 垂直数值控制条调试信息
        vertical_info = [
            f"垂直数值控制条:",
            f"  值: {self.vertical_value_bar.value()} (范围: {self.vertical_value_bar._minimum} - {self.vertical_value_bar._maximum})",
            f"  宽度: {self.vertical_value_bar.width()}px",
            f"  高度: {self.vertical_value_bar.height()}px",
            f"  滑块半径: {self.vertical_value_bar._handle_radius}px",
            f"  边框宽度: {self.vertical_value_bar._handle_border_width}px",
            f"  进度条宽度: {self.vertical_value_bar._bar_size}px",
            f"  DPI缩放因子: {self.app.dpi_scale_factor}"
        ]
        self.vertical_debug_label.setText("\n".join(vertical_info))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # 设置全局字体
    font = QFont("Microsoft YaHei", 9)
    app.setFont(font)
    
    # 设置默认DPI缩放因子
    app.dpi_scale_factor = 1.0
    
    window = TestValueBarApp()
    window.show()
    
    sys.exit(app.exec_())
