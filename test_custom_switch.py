#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试自定义开关控件
演示独立的CustomSwitch控件功能
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

# 导入自定义控件
from freeassetfilter.widgets.custom_widgets import CustomSwitch, CustomButton

class TestWindow(QMainWindow):
    """测试窗口类"""
    def __init__(self):
        super().__init__()
        self.init_ui()
    
    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("自定义开关控件测试")
        self.setGeometry(100, 100, 800, 600)
        
        # 中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主垂直布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)
        
        # 添加标题
        title = QLabel("自定义开关控件测试")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))
        main_layout.addWidget(title)
        
        # 1. 基本开关测试
        group1 = QGroupBox("基本开关测试")
        group1_layout = QVBoxLayout(group1)
        
        # 创建水平布局，显示开关和状态
        switch1_layout = QHBoxLayout()
        switch1 = CustomSwitch(initial_value=False)
        switch1_label = QLabel("初始关闭状态")
        switch1_status = QLabel("当前状态: 关闭")
        switch1_status.setFixedWidth(120)
        switch1.toggled.connect(lambda checked: self.on_switch_toggled(checked, switch1_status))
        
        switch1_layout.addWidget(switch1)
        switch1_layout.addWidget(switch1_label)
        switch1_layout.addWidget(switch1_status)
        switch1_layout.addStretch()
        group1_layout.addLayout(switch1_layout)
        
        switch2_layout = QHBoxLayout()
        switch2 = CustomSwitch(initial_value=True)
        switch2_label = QLabel("初始开启状态")
        switch2_status = QLabel("当前状态: 开启")
        switch2_status.setFixedWidth(120)
        switch2.toggled.connect(lambda checked: self.on_switch_toggled(checked, switch2_status))
        
        switch2_layout.addWidget(switch2)
        switch2_layout.addWidget(switch2_label)
        switch2_layout.addWidget(switch2_status)
        switch2_layout.addStretch()
        group1_layout.addLayout(switch2_layout)
        
        main_layout.addWidget(group1)
        
        # 2. 与普通按钮高度对比测试
        group2 = QGroupBox("高度对比测试")
        group2_layout = QVBoxLayout(group2)
        
        compare_layout = QHBoxLayout()
        
        # 创建普通按钮
        button = CustomButton(text="普通按钮", height=40)
        compare_layout.addWidget(button)
        compare_layout.addWidget(QLabel("与"))
        
        # 创建开关
        switch3 = CustomSwitch(height=40)
        compare_layout.addWidget(switch3)
        compare_layout.addWidget(QLabel("高度对比"))
        compare_layout.addStretch()
        
        group2_layout.addLayout(compare_layout)
        main_layout.addWidget(group2)
        
        # 3. 不同高度设置测试
        group3 = QGroupBox("不同高度设置测试")
        group3_layout = QVBoxLayout(group3)
        
        height_layout = QHBoxLayout()
        
        # 不同高度的开关
        switch4 = CustomSwitch(height=32)
        switch5 = CustomSwitch(height=40)
        switch6 = CustomSwitch(height=48)
        
        height_layout.addWidget(QLabel("32px: "))
        height_layout.addWidget(switch4)
        height_layout.addStretch()
        
        height_layout.addWidget(QLabel("40px: "))
        height_layout.addWidget(switch5)
        height_layout.addStretch()
        
        height_layout.addWidget(QLabel("48px: "))
        height_layout.addWidget(switch6)
        height_layout.addStretch()
        
        group3_layout.addLayout(height_layout)
        main_layout.addWidget(group3)
        
        # 4. 信号测试
        group4 = QGroupBox("信号测试")
        group4_layout = QVBoxLayout(group4)
        
        signal_layout = QHBoxLayout()
        signal_switch = CustomSwitch()
        signal_label = QLabel("点击开关查看控制台输出")
        
        signal_switch.toggled.connect(self.on_switch_signal_test)
        
        signal_layout.addWidget(signal_switch)
        signal_layout.addWidget(signal_label)
        signal_layout.addStretch()
        
        group4_layout.addLayout(signal_layout)
        main_layout.addWidget(group4)
        
        # 添加拉伸空间
        main_layout.addStretch()
    
    def on_switch_toggled(self, checked, status_label):
        """开关状态变化处理"""
        status = "开启" if checked else "关闭"
        status_label.setText(f"当前状态: {status}")
    
    def on_switch_signal_test(self, checked):
        """开关信号测试处理"""
        print(f"开关信号触发: {'开启' if checked else '关闭'}")

if __name__ == "__main__":
    # 设置DPI缩放（必须在创建QApplication实例之前设置）
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    QApplication.setAttribute(Qt.AA_Use96Dpi)
    
    app = QApplication(sys.argv)
    
    # 设置全局字体
    from PyQt5.QtGui import QFontDatabase
    font_db = QFontDatabase()
    font_families = font_db.families()
    
    yahei_fonts = ["Microsoft YaHei", "Microsoft YaHei UI"]
    selected_font = None
    for font_name in yahei_fonts:
        if font_name in font_families:
            selected_font = font_name
            break
    
    if selected_font:
        app.setFont(QFont(selected_font, 16))
    
    # 设置默认字体大小和DPI缩放因子
    app.default_font_size = 16
    app.dpi_scale_factor = 1.0
    app.global_font = app.font()
    
    window = TestWindow()
    window.show()
    
    sys.exit(app.exec_())
