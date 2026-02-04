#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
滚动文本控件测试脚本
测试 ScrollingText 控件的各种功能和特性
"""

import sys
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QPushButton, QSlider, QSpinBox, QLineEdit
)
from PyQt5.QtCore import Qt

# 导入滚动文本控件
from freeassetfilter.widgets.scrolling_text import ScrollingText


class TestWindow(QWidget):
    """测试窗口"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("滚动文本控件测试")
        self.setGeometry(100, 100, 800, 600)
        
        # 初始化UI
        self._init_ui()
    
    def _init_ui(self):
        """初始化测试界面"""
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 标题
        title = QLabel("滚动文本控件功能测试")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title)
        
        # ========== 测试1: 短文本（不需要滚动） ==========
        test1_label = QLabel("测试1: 短文本（文本宽度 <= 容器宽度，居中显示，无滚动）")
        test1_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(test1_label)
        
        self.scrolling_text1 = ScrollingText(
            parent=self,
            text="短文本",
            width=200,
            height=30,
            font_size=14
        )
        self.scrolling_text1.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc;")
        layout.addWidget(self.scrolling_text1)
        
        # ========== 测试2: 长文本（需要滚动） ==========
        test2_label = QLabel("测试2: 长文本（文本宽度 > 容器宽度，自动启用滚动）")
        test2_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(test2_label)
        
        long_text = "这是一个非常长的文本内容，用于测试滚动文本控件的自动滚动功能，当文本长度超过容器宽度时会自动启用滚动动画"
        self.scrolling_text2 = ScrollingText(
            parent=self,
            text=long_text,
            width=300,
            height=30,
            font_size=14
        )
        self.scrolling_text2.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc;")
        self.scrolling_text2.clicked.connect(lambda: print("滚动文本2被点击"))
        layout.addWidget(self.scrolling_text2)
        
        # ========== 测试3: 不同颜色的文本 ==========
        test3_label = QLabel("测试3: 自定义文本颜色")
        test3_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(test3_label)
        
        color_layout = QHBoxLayout()
        
        self.scrolling_text3 = ScrollingText(
            parent=self,
            text="这是紫色文本，用于测试自定义颜色功能，当文本长度超过容器宽度时会自动启用滚动动画",
            width=250,
            height=30,
            font_size=14,
            text_color="#B036EE"
        )
        self.scrolling_text3.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc;")
        color_layout.addWidget(self.scrolling_text3)
        
        self.scrolling_text4 = ScrollingText(
            parent=self,
            text="这是红色文本，用于测试自定义颜色功能，当文本长度超过容器宽度时会自动启用滚动动画",
            width=250,
            height=30,
            font_size=14,
            text_color="#E74C3C"
        )
        self.scrolling_text4.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc;")
        color_layout.addWidget(self.scrolling_text4)
        
        layout.addLayout(color_layout)
        
        # ========== 测试4: 交互控制 ==========
        test4_label = QLabel("测试4: 交互控制（动态修改文本、暂停/恢复/停止）")
        test4_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(test4_label)
        
        self.scrolling_text5 = ScrollingText(
            parent=self,
            text="动态文本测试，可以通过下方输入框修改此文本内容",
            width=400,
            height=30,
            font_size=14
        )
        self.scrolling_text5.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc;")
        layout.addWidget(self.scrolling_text5)
        
        # 控制按钮区域
        control_layout = QHBoxLayout()
        
        # 文本输入
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("输入新文本...")
        self.text_input.setText("动态文本测试，可以通过下方输入框修改此文本内容")
        control_layout.addWidget(self.text_input, stretch=2)
        
        # 设置文本按钮
        set_text_btn = QPushButton("设置文本")
        set_text_btn.clicked.connect(self._on_set_text)
        control_layout.addWidget(set_text_btn)
        
        # 暂停按钮
        pause_btn = QPushButton("暂停")
        pause_btn.clicked.connect(self.scrolling_text5.pause)
        control_layout.addWidget(pause_btn)
        
        # 恢复按钮
        resume_btn = QPushButton("恢复")
        resume_btn.clicked.connect(self.scrolling_text5.resume)
        control_layout.addWidget(resume_btn)
        
        # 停止按钮
        stop_btn = QPushButton("停止")
        stop_btn.clicked.connect(self.scrolling_text5.stop)
        control_layout.addWidget(stop_btn)
        
        # 开始按钮
        start_btn = QPushButton("开始")
        start_btn.clicked.connect(self.scrolling_text5.start)
        control_layout.addWidget(start_btn)
        
        layout.addLayout(control_layout)
        
        # ========== 测试5: DPI缩放测试 ==========
        test5_label = QLabel("测试5: DPI缩放测试")
        test5_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(test5_label)
        
        dpi_layout = QHBoxLayout()
        
        dpi_label = QLabel("DPI缩放比例:")
        dpi_layout.addWidget(dpi_label)
        
        self.dpi_slider = QSlider(Qt.Horizontal)
        self.dpi_slider.setMinimum(100)
        self.dpi_slider.setMaximum(200)
        self.dpi_slider.setValue(100)
        self.dpi_slider.valueChanged.connect(self._on_dpi_changed)
        dpi_layout.addWidget(self.dpi_slider)
        
        self.dpi_value_label = QLabel("1.0")
        dpi_layout.addWidget(self.dpi_value_label)
        
        layout.addLayout(dpi_layout)
        
        self.scrolling_text6 = ScrollingText(
            parent=self,
            text="DPI缩放测试文本，用于测试控件在不同DPI缩放比例下的显示效果",
            width=300,
            height=30,
            font_size=14,
            dpi_scale=1.0
        )
        self.scrolling_text6.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc;")
        layout.addWidget(self.scrolling_text6)
        
        # ========== 测试6: 字体大小测试 ==========
        test6_label = QLabel("测试6: 字体大小测试")
        test6_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(test6_label)
        
        font_layout = QHBoxLayout()
        
        font_label = QLabel("字体大小:")
        font_layout.addWidget(font_label)
        
        self.font_spinbox = QSpinBox()
        self.font_spinbox.setMinimum(8)
        self.font_spinbox.setMaximum(24)
        self.font_spinbox.setValue(14)
        self.font_spinbox.valueChanged.connect(self._on_font_size_changed)
        font_layout.addWidget(self.font_spinbox)
        
        font_layout.addStretch()
        
        layout.addLayout(font_layout)
        
        self.scrolling_text7 = ScrollingText(
            parent=self,
            text="字体大小测试文本，用于测试控件在不同字体大小下的显示和滚动效果",
            width=300,
            height=30,
            font_size=14
        )
        self.scrolling_text7.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc;")
        layout.addWidget(self.scrolling_text7)
        
        # 添加弹性空间
        layout.addStretch()
        
        # 说明标签
        info_label = QLabel(
            "说明：\n"
            "1. 将鼠标悬停在滚动文本上可暂停动画，移开后恢复\n"
            "2. 点击滚动文本会触发 clicked 信号（查看控制台输出）\n"
            "3. 短文本自动居中显示，长文本自动启用滚动"
        )
        info_label.setStyleSheet("color: #666; font-size: 12px; margin-top: 10px;")
        layout.addWidget(info_label)
    
    def _on_set_text(self):
        """设置文本按钮回调"""
        new_text = self.text_input.text()
        self.scrolling_text5.set_text(new_text)
        print(f"文本已更新为: {new_text}")
    
    def _on_dpi_changed(self, value):
        """DPI滑块变化回调"""
        dpi_scale = value / 100.0
        self.dpi_value_label.setText(f"{dpi_scale:.1f}")
        self.scrolling_text6.set_dpi_scale(dpi_scale)
    
    def _on_font_size_changed(self, value):
        """字体大小变化回调"""
        self.scrolling_text7.set_font_size(value)


def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    # 设置全局字体
    from PyQt5.QtGui import QFont
    font = QFont("Microsoft YaHei", 10)
    app.setFont(font)
    app.default_font_size = 14
    
    # 创建测试窗口
    window = TestWindow()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
