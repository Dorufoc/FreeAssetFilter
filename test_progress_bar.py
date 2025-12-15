#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CustomProgressBar 组件测试应用
用于独立测试进度条的点击、拖动和位置映射功能
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QLineEdit
from PyQt5.QtCore import Qt, QTimer, QRect, QSize, QPoint
from PyQt5.QtGui import QIcon, QPainter, QColor, QPen, QBrush, QPixmap, QImage, QCursor, QDoubleValidator

# 导入CustomProgressBar组件
from freeassetfilter.components.video_player import CustomProgressBar

class ProgressBarTestApp(QWidget):
    """
    进度条测试应用
    """
    
    def __init__(self):
        super().__init__()
        
        # 设置窗口属性
        self.setWindowTitle("CustomProgressBar 测试应用")
        self.setGeometry(100, 100, 800, 200)
        
        # 初始DPI缩放因子
        self.dpi_scale = 1.0
        print(f"初始DPI缩放因子: {self.dpi_scale}")
        
        # 初始化UI
        self.init_ui()
        
        # 创建定时器用于模拟进度更新
        self.timer = QTimer(self)
        self.timer.setInterval(1000)  # 1秒更新一次
        self.timer.timeout.connect(self.update_test_progress)
        
        # 测试进度值
        self.test_progress = 0
    
    def init_ui(self):
        """
        初始化用户界面
        """
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # 添加标题
        title_label = QLabel("CustomProgressBar 组件测试")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        main_layout.addWidget(title_label)
        
        # 调试信息标签
        self.debug_label = QLabel("调试信息:")
        self.debug_label.setStyleSheet("font-family: Consolas; font-size: 12px; background-color: #f0f0f0; padding: 10px; border-radius: 5px;")
        self.debug_label.setWordWrap(True)
        main_layout.addWidget(self.debug_label)
        
        # 当前进度值标签
        self.progress_value_label = QLabel("当前进度值: 0")
        self.progress_value_label.setAlignment(Qt.AlignCenter)
        self.progress_value_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        main_layout.addWidget(self.progress_value_label)
        
        # 创建可交互进度条
        self.progress_bar = CustomProgressBar(self)
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)
        
        # 连接进度条信号
        self.progress_bar.valueChanged.connect(self.on_progress_value_changed)
        self.progress_bar.userInteracting.connect(self.on_user_interacting)
        self.progress_bar.userInteractionEnded.connect(self.on_user_interaction_ended)
        
        # 测试控制按钮和DPI设置
        control_layout = QWidget()
        control_layout.setStyleSheet("background-color: #e0e0e0; padding: 10px; border-radius: 5px;")
        control_layout_layout = QVBoxLayout(control_layout)
        control_layout_layout.setContentsMargins(0, 0, 0, 0)
        
        # DPI缩放系数设置
        from PyQt5.QtWidgets import QHBoxLayout, QLineEdit
        dpi_layout = QWidget()
        dpi_layout_layout = QHBoxLayout(dpi_layout)
        dpi_layout_layout.setContentsMargins(0, 0, 0, 10)
        
        dpi_label = QLabel("DPI缩放系数:")
        dpi_layout_layout.addWidget(dpi_label)
        
        self.dpi_input = QLineEdit(str(self.dpi_scale))
        self.dpi_input.setMaximumWidth(80)
        self.dpi_input.setValidator(QDoubleValidator(0.5, 3.0, 2))
        dpi_layout_layout.addWidget(self.dpi_input)
        
        apply_dpi_button = QPushButton("应用")
        apply_dpi_button.setMaximumWidth(60)
        apply_dpi_button.clicked.connect(self.apply_dpi_scale)
        dpi_layout_layout.addWidget(apply_dpi_button)
        
        control_layout_layout.addWidget(dpi_layout)
        
        # 测试按钮
        test_button_layout = QWidget()
        test_button_layout_layout = QVBoxLayout(test_button_layout)
        test_button_layout_layout.setContentsMargins(0, 0, 0, 0)
        
        # 开始/停止按钮
        self.start_stop_button = QPushButton("开始模拟进度")
        self.start_stop_button.clicked.connect(self.toggle_test)
        test_button_layout_layout.addWidget(self.start_stop_button)
        
        # 重置按钮
        reset_button = QPushButton("重置进度条")
        reset_button.clicked.connect(self.reset_progress)
        test_button_layout_layout.addWidget(reset_button)
        
        control_layout_layout.addWidget(test_button_layout)
        main_layout.addWidget(control_layout)
    
    def on_progress_value_changed(self, value):
        """
        处理进度值变化
        """
        self.progress_value_label.setText(f"当前进度值: {value}")
        
        # 更新调试信息
        debug_info = f"进度值变化: {value}\n"
        debug_info += f"进度比例: {value / 1000.0:.2f}\n"
        debug_info += f"进度条宽度: {self.progress_bar.width()}\n"
        debug_info += f"DPI缩放因子: {self.dpi_scale}\n"
        self.debug_label.setText(debug_info)
    
    def on_user_interacting(self):
        """
        处理用户开始交互
        """
        print("用户开始交互")
        self.debug_label.setText(self.debug_label.text() + "\n用户开始交互")
    
    def on_user_interaction_ended(self):
        """
        处理用户结束交互
        """
        print("用户结束交互")
        self.debug_label.setText(self.debug_label.text() + "\n用户结束交互")
    
    def update_test_progress(self):
        """
        更新测试进度
        """
        self.test_progress += 50  # 每次增加5%
        if self.test_progress > 1000:
            self.test_progress = 0
        
        self.progress_bar.setValue(self.test_progress)
    
    def toggle_test(self):
        """
        切换测试状态
        """
        if self.timer.isActive():
            self.timer.stop()
            self.start_stop_button.setText("开始模拟进度")
        else:
            self.timer.start()
            self.start_stop_button.setText("停止模拟进度")
    
    def reset_progress(self):
        """
        重置进度条
        """
        self.test_progress = 0
        self.progress_bar.setValue(0)
        self.timer.stop()
        self.start_stop_button.setText("开始模拟进度")
    
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
            
            # 重新创建进度条
            from PyQt5.QtWidgets import QWidgetItem
            
            # 保存当前进度值
            current_value = self.progress_bar.value()
            
            # 移除当前进度条
            item = self.layout().takeAt(3)  # 进度条在布局中的索引
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            
            # 创建新的进度条
            self.progress_bar = CustomProgressBar(self)
            self.progress_bar.setRange(0, 1000)
            self.progress_bar.setValue(current_value)
            
            # 连接进度条信号
            self.progress_bar.valueChanged.connect(self.on_progress_value_changed)
            self.progress_bar.userInteracting.connect(self.on_user_interacting)
            self.progress_bar.userInteractionEnded.connect(self.on_user_interaction_ended)
            
            # 添加新进度条到布局
            self.layout().insertWidget(3, self.progress_bar)
            
            # 更新调试信息
            debug_info = f"进度值变化: {current_value}\n"
            debug_info += f"进度比例: {current_value / 1000.0:.2f}\n"
            debug_info += f"进度条宽度: {self.progress_bar.width()}\n"
            debug_info += f"DPI缩放因子: {self.dpi_scale}\n"
            self.debug_label.setText(debug_info)
            
        except Exception as e:
            print(f"应用DPI缩放系数失败: {e}")
            import traceback
            traceback.print_exc()

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
    test_app = ProgressBarTestApp()
    test_app.show()
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()