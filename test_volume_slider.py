#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试音量条浮动菜单组件
"""

import sys
import os
import warnings

# 忽略sipPyTypeDict相关的弃用警告
warnings.filterwarnings("ignore", category=DeprecationWarning, module="PyQt5")
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*sipPyTypeDict.*")

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel
from PyQt5.QtCore import Qt

# 导入音量条浮动菜单组件
from freeassetfilter.widgets.volume_slider_menu import VolumeSliderMenu


class TestWindow(QMainWindow):
    """
    测试窗口，用于展示音量条浮动菜单
    """
    def __init__(self):
        """
        初始化测试窗口
        """
        super().__init__()
        
        # 设置窗口属性
        self.setWindowTitle("Volume Slider Menu Test")
        self.setGeometry(100, 100, 400, 300)
        
        # 初始化UI
        self.init_ui()
        
    def init_ui(self):
        """
        初始化UI组件
        """
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建布局
        layout = QVBoxLayout(central_widget)
        layout.setAlignment(Qt.AlignCenter)
        
        # 添加标题
        title_label = QLabel("独立音量条浮动菜单测试")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # 创建音量条浮动菜单
        self.volume_slider = VolumeSliderMenu(self)
        
        # 创建状态标签
        self.status_label = QLabel("当前音量: 50% | 静音: False")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)
        
        # 连接信号
        self.volume_slider.valueChanged.connect(self.on_volume_changed)
        self.volume_slider.mutedChanged.connect(self.on_muted_changed)
        
        # 添加音量条到布局
        layout.addWidget(self.volume_slider)
        
    def on_volume_changed(self, value):
        """
        音量值变化回调
        
        Args:
            value: 新的音量值
        """
        self.update_status()
        
    def on_muted_changed(self, muted):
        """
        静音状态变化回调
        
        Args:
            muted: 新的静音状态
        """
        self.update_status()
        
    def update_status(self):
        """
        更新状态标签
        """
        volume = self.volume_slider.volume()
        muted = self.volume_slider.muted()
        self.status_label.setText(f"当前音量: {volume}% | 静音: {muted}")
        

if __name__ == "__main__":
    """
    主函数，启动测试程序
    """
    app = QApplication(sys.argv)
    
    # 设置全局DPI缩放因子
    app.dpi_scale_factor = 1.0
    
    # 创建并显示测试窗口
    window = TestWindow()
    window.show()
    
    # 运行应用
    sys.exit(app.exec_())
