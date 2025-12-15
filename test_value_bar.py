#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CustomValueBar 组件测试应用
用于独立测试数值控制条的显示、交互和DPI缩放效果
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QGroupBox
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QIcon, QDoubleValidator

# 导入CustomValueBar组件
from freeassetfilter.components.video_player import CustomValueBar

class ValueBarTestApp(QWidget):
    """
    数值控制条测试应用
    """
    
    def __init__(self):
        super().__init__()
        
        # 设置窗口属性
        self.setWindowTitle("CustomValueBar 测试应用")
        self.setGeometry(100, 100, 900, 400)
        
        # 初始DPI缩放因子
        self.dpi_scale = 1.0
        print(f"初始DPI缩放因子: {self.dpi_scale}")
        
        # 初始化UI
        self.init_ui()
    
    def init_ui(self):
        """
        初始化用户界面
        """
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)
        
        # 添加标题
        title_label = QLabel("CustomValueBar 组件测试")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 20px; font-weight: bold;")
        main_layout.addWidget(title_label)
        
        # DPI缩放系数设置
        dpi_group = QGroupBox("DPI缩放系数设置")
        dpi_layout = QHBoxLayout(dpi_group)
        
        dpi_label = QLabel("缩放系数:")
        dpi_layout.addWidget(dpi_label)
        
        self.dpi_input = QLineEdit(str(self.dpi_scale))
        self.dpi_input.setMaximumWidth(80)
        self.dpi_input.setValidator(QDoubleValidator(0.5, 3.0, 2))
        dpi_layout.addWidget(self.dpi_input)
        
        apply_dpi_button = QPushButton("应用")
        apply_dpi_button.setMaximumWidth(60)
        apply_dpi_button.clicked.connect(self.apply_dpi_scale)
        dpi_layout.addWidget(apply_dpi_button)
        
        main_layout.addWidget(dpi_group)
        
        # 调试信息
        self.debug_label = QLabel("调试信息:")
        self.debug_label.setStyleSheet("font-family: Consolas; font-size: 12px; background-color: #f0f0f0; padding: 10px; border-radius: 5px;")
        self.debug_label.setWordWrap(True)
        main_layout.addWidget(self.debug_label)
        
        # 测试区域：横向和竖向数值控制条
        test_layout = QHBoxLayout()
        test_layout.setSpacing(20)
        
        # 横向数值控制条测试
        horizontal_group = QGroupBox("横向数值控制条")
        horizontal_layout = QVBoxLayout(horizontal_group)
        
        self.horizontal_value_bar = CustomValueBar(self, orientation=CustomValueBar.Horizontal)
        self.horizontal_value_bar.setRange(0, 1000)
        self.horizontal_value_bar.setValue(500)
        horizontal_layout.addWidget(self.horizontal_value_bar)
        
        self.horizontal_value_label = QLabel("当前值: 500")
        self.horizontal_value_label.setAlignment(Qt.AlignCenter)
        self.horizontal_value_label.setStyleSheet("font-weight: bold;")
        horizontal_layout.addWidget(self.horizontal_value_label)
        
        # 连接信号
        self.horizontal_value_bar.valueChanged.connect(lambda value: self.on_value_changed("horizontal", value))
        self.horizontal_value_bar.userInteracting.connect(lambda: self.on_user_interacting("horizontal"))
        self.horizontal_value_bar.userInteractionEnded.connect(lambda: self.on_user_interaction_ended("horizontal"))
        
        test_layout.addWidget(horizontal_group)
        
        # 竖向数值控制条测试
        vertical_group = QGroupBox("竖向数值控制条")
        vertical_layout = QVBoxLayout(vertical_group)
        
        self.vertical_value_bar = CustomValueBar(self, orientation=CustomValueBar.Vertical)
        self.vertical_value_bar.setRange(0, 1000)
        self.vertical_value_bar.setValue(500)
        vertical_layout.addWidget(self.vertical_value_bar)
        
        self.vertical_value_label = QLabel("当前值: 500")
        self.vertical_value_label.setAlignment(Qt.AlignCenter)
        self.vertical_value_label.setStyleSheet("font-weight: bold;")
        vertical_layout.addWidget(self.vertical_value_label)
        
        # 连接信号
        self.vertical_value_bar.valueChanged.connect(lambda value: self.on_value_changed("vertical", value))
        self.vertical_value_bar.userInteracting.connect(lambda: self.on_user_interacting("vertical"))
        self.vertical_value_bar.userInteractionEnded.connect(lambda: self.on_user_interaction_ended("vertical"))
        
        test_layout.addWidget(vertical_group)
        
        main_layout.addLayout(test_layout)
        
        # 控制按钮
        control_layout = QHBoxLayout()
        control_layout.setSpacing(10)
        
        reset_button = QPushButton("重置数值")
        reset_button.clicked.connect(self.reset_values)
        control_layout.addWidget(reset_button)
        
        random_button = QPushButton("随机数值")
        random_button.clicked.connect(self.set_random_values)
        control_layout.addWidget(random_button)
        
        # 居中显示控制按钮
        control_container = QWidget()
        control_container.setLayout(control_layout)
        control_container.setMaximumWidth(400)
        control_centered = QHBoxLayout()
        control_centered.addStretch()
        control_centered.addWidget(control_container)
        control_centered.addStretch()
        
        main_layout.addLayout(control_centered)
        
        # 更新调试信息
        self.update_debug_info()
    
    def on_value_changed(self, bar_type, value):
        """
        处理数值变化
        """
        if bar_type == "horizontal":
            self.horizontal_value_label.setText(f"当前值: {value}")
        else:
            self.vertical_value_label.setText(f"当前值: {value}")
        
        self.update_debug_info()
    
    def on_user_interacting(self, bar_type):
        """
        处理用户开始交互
        """
        print(f"{bar_type} 数值控制条: 用户开始交互")
        self.update_debug_info()
    
    def on_user_interaction_ended(self, bar_type):
        """
        处理用户结束交互
        """
        print(f"{bar_type} 数值控制条: 用户结束交互")
        self.update_debug_info()
    
    def update_debug_info(self):
        """
        更新调试信息
        """
        debug_info = f"DPI缩放因子: {self.dpi_scale}\n"
        debug_info += f"横向数值控制条: 当前值={self.horizontal_value_bar.value()}, 范围={self.horizontal_value_bar._minimum}-{self.horizontal_value_bar._maximum}, 方向=横向\n"
        debug_info += f"竖向数值控制条: 当前值={self.vertical_value_bar.value()}, 范围={self.vertical_value_bar._minimum}-{self.vertical_value_bar._maximum}, 方向=竖向\n"
        self.debug_label.setText(debug_info)
    
    def apply_dpi_scale(self):
        """
        应用新的DPI缩放系数
        """
        try:
            # 获取新的DPI缩放系数
            new_scale = float(self.dpi_input.text())
            print(f"应用新的DPI缩放系数: {new_scale}")
            
            # 更新DPI缩放因子
            self.dpi_scale = new_scale
            
            # 更新应用的DPI缩放因子
            app = QApplication.instance()
            app.dpi_scale_factor = new_scale
            
            # 保存当前值
            horizontal_value = self.horizontal_value_bar.value()
            vertical_value = self.vertical_value_bar.value()
            
            # 简单的重新创建方式：直接替换widget
            
            # 删除旧的数值控制条
            self.horizontal_value_bar.deleteLater()
            self.vertical_value_bar.deleteLater()
            
            # 创建新的横向数值控制条
            self.horizontal_value_bar = CustomValueBar(self, orientation=CustomValueBar.Horizontal)
            self.horizontal_value_bar.setRange(0, 1000)
            self.horizontal_value_bar.setValue(horizontal_value)
            
            # 连接信号
            self.horizontal_value_bar.valueChanged.connect(lambda value: self.on_value_changed("horizontal", value))
            self.horizontal_value_bar.userInteracting.connect(lambda: self.on_user_interacting("horizontal"))
            self.horizontal_value_bar.userInteractionEnded.connect(lambda: self.on_user_interaction_ended("horizontal"))
            
            # 创建新的竖向数值控制条
            self.vertical_value_bar = CustomValueBar(self, orientation=CustomValueBar.Vertical)
            self.vertical_value_bar.setRange(0, 1000)
            self.vertical_value_bar.setValue(vertical_value)
            
            # 连接信号
            self.vertical_value_bar.valueChanged.connect(lambda value: self.on_value_changed("vertical", value))
            self.vertical_value_bar.userInteracting.connect(lambda: self.on_user_interacting("vertical"))
            self.vertical_value_bar.userInteractionEnded.connect(lambda: self.on_user_interaction_ended("vertical"))
            
            # 重新创建整个测试布局
            # 移除当前测试布局
            from PyQt5.QtWidgets import QWidgetItem
            
            # 移除旧的测试布局
            test_layout_item = self.layout().takeAt(3)  # 测试布局在主布局中的索引
            if test_layout_item is not None:
                test_widget = test_layout_item.widget()
                if test_widget is not None:
                    test_widget.deleteLater()
            
            # 重新创建测试区域：横向和竖向数值控制条
            test_layout = QHBoxLayout()
            test_layout.setSpacing(20)
            
            # 横向数值控制条测试
            horizontal_group = QGroupBox("横向数值控制条")
            horizontal_layout = QVBoxLayout(horizontal_group)
            horizontal_layout.addWidget(self.horizontal_value_bar)
            horizontal_layout.addWidget(self.horizontal_value_label)
            
            # 竖向数值控制条测试
            vertical_group = QGroupBox("竖向数值控制条")
            vertical_layout = QVBoxLayout(vertical_group)
            vertical_layout.addWidget(self.vertical_value_bar)
            vertical_layout.addWidget(self.vertical_value_label)
            
            # 添加到测试布局
            test_layout.addWidget(horizontal_group)
            test_layout.addWidget(vertical_group)
            
            # 创建容器并添加到主布局
            test_container = QWidget()
            test_container.setLayout(test_layout)
            self.layout().insertWidget(3, test_container)  # 添加回主布局的第4个位置
            
            # 更新调试信息
            self.update_debug_info()
            
        except Exception as e:
            print(f"应用DPI缩放系数失败: {e}")
            import traceback
            traceback.print_exc()
    
    def reset_values(self):
        """
        重置数值控制条的值
        """
        self.horizontal_value_bar.setValue(500)
        self.vertical_value_bar.setValue(500)
        self.update_debug_info()
    
    def set_random_values(self):
        """
        设置随机数值
        """
        import random
        horizontal_value = random.randint(0, 1000)
        vertical_value = random.randint(0, 1000)
        self.horizontal_value_bar.setValue(horizontal_value)
        self.vertical_value_bar.setValue(vertical_value)
        self.update_debug_info()

def main():
    """
    主函数
    """
    # 设置DPI相关属性
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    
    app = QApplication(sys.argv)
    
    # 设置应用程序图标
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'freeassetfilter', 'icons', 'FAF-main.ico')
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    
    # 创建并显示测试应用
    test_app = ValueBarTestApp()
    test_app.show()
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()