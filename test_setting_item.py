#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试高度可定制的设置项控件
演示各种交互类型的使用方法
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

# 导入自定义设置项控件
from freeassetfilter.widgets.setting_widgets import CustomSettingItem

class TestWindow(QMainWindow):
    """测试窗口类"""
    def __init__(self):
        super().__init__()
        self.init_ui()
    
    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("自定义设置项控件测试")
        self.setGeometry(100, 100, 800, 600)
        
        # 中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 垂直布局
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        # 添加标题
        title = QLabel("高度可定制设置项控件测试")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))
        layout.addWidget(title)
        
        # 1. 测试开关类型设置项
        switch_item = CustomSettingItem(
            text="开关类型设置项",
            secondary_text="这是一个开关控件，用于切换功能开启/关闭状态",
            interaction_type=CustomSettingItem.SWITCH_TYPE,
            initial_value=True
        )
        switch_item.switch_toggled.connect(self.on_switch_toggled)
        layout.addWidget(switch_item)
        
        # 2. 测试按钮组类型设置项（1个按钮）
        button_item_single = CustomSettingItem(
            text="按钮组类型设置项（单个按钮）",
            secondary_text="这是一个包含单个按钮的设置项",
            interaction_type=CustomSettingItem.BUTTON_GROUP_TYPE,
            buttons=[{"text": "点击执行", "type": "primary"}]
        )
        button_item_single.button_clicked.connect(self.on_button_clicked)
        layout.addWidget(button_item_single)
        
        # 3. 测试按钮组类型设置项（2个按钮）
        button_item_double = CustomSettingItem(
            text="按钮组类型设置项（两个按钮）",
            secondary_text="这是一个包含两个按钮的设置项，支持不同按钮类型",
            interaction_type=CustomSettingItem.BUTTON_GROUP_TYPE,
            buttons=[
                {"text": "确认", "type": "primary"},
                {"text": "取消", "type": "secondary"}
            ]
        )
        button_item_double.button_clicked.connect(self.on_button_clicked)
        layout.addWidget(button_item_double)
        
        # 4. 测试文本输入与按钮组合类型设置项
        input_button_item = CustomSettingItem(
            text="文本输入与按钮组合设置项",
            secondary_text="这是一个包含文本输入框和按钮的组合控件",
            interaction_type=CustomSettingItem.INPUT_BUTTON_TYPE,
            placeholder="请输入内容...",
            initial_text="初始文本",
            button_text="提交"
        )
        input_button_item.input_submitted.connect(self.on_input_submitted)
        layout.addWidget(input_button_item)
        
        # 5. 测试数值控制条类型设置项
        value_bar_item = CustomSettingItem(
            text="数值控制条类型设置项",
            secondary_text="这是一个数值控制条控件，用于调整数值大小",
            interaction_type=CustomSettingItem.VALUE_BAR_TYPE,
            min_value=0,
            max_value=100,
            initial_value=50
        )
        value_bar_item.value_changed.connect(self.on_value_changed)
        layout.addWidget(value_bar_item)
        
        # 6. 测试单行文本模式
        single_line_item = CustomSettingItem(
            text="单行文本模式设置项",
            interaction_type=CustomSettingItem.SWITCH_TYPE,
            initial_value=False
        )
        layout.addWidget(single_line_item)
        
        # 添加拉伸空间
        layout.addStretch()
    
    def on_switch_toggled(self, checked):
        """开关状态变化处理"""
        print(f"开关状态变化: {'开启' if checked else '关闭'}")
    
    def on_button_clicked(self, button_index):
        """按钮点击处理"""
        print(f"按钮点击: 索引 {button_index}")
    
    def on_input_submitted(self, text):
        """输入提交处理"""
        print(f"输入提交: {text}")
    
    def on_value_changed(self, value):
        """数值变化处理"""
        print(f"数值变化: {value}")

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