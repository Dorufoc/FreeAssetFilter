#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 自定义控件演示
演示自定义窗口和按钮控件的使用
"""

import sys
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QPushButton, QScrollArea,
    QHBoxLayout
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont

# 导入自定义控件
from src.widgets.custom_widgets import CustomWindow, CustomButton, CustomProgressBar, CustomMessageBox


def show_custom_window():
    """
    演示自定义窗口
    """
    # 创建应用实例
    app = QApplication(sys.argv)
    
    # 设置全局字体
    font = QFont()
    app.setFont(font)
    
    # 创建自定义窗口
    custom_window = CustomWindow("自定义控件演示")
    custom_window.setGeometry(200, 200, 500, 600)  # 调整窗口大小，增加高度
    
    # 创建滚动区域
    scroll_area = QScrollArea()
    scroll_area.setWidgetResizable(True)
    scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # 只显示垂直滚动条
    scroll_area.setStyleSheet("""
        QScrollArea {
            background-color: transparent;
            border: none;
        }
        QScrollArea QWidget {
            background-color: transparent;
        }
        QScrollBar:vertical {
            width: 8px;
            background: transparent;
        }
        QScrollBar::handle:vertical {
            background: #e0e0e0;
            border-radius: 4px;
        }
        QScrollBar::handle:vertical:hover {
            background: #bdbdbd;
        }
        QScrollBar::sub-page:vertical,
        QScrollBar::add-page:vertical {
            background: transparent;
        }
    """)
    
    # 创建滚动区域内容 widget
    scroll_content = QWidget()
    scroll_layout = QVBoxLayout(scroll_content)
    scroll_layout.setContentsMargins(16, 8, 16, 16)
    scroll_layout.setSpacing(12)
    
    # 添加控件到滚动区域
    
    # 标题标签
    title_label = QLabel("这是一个自定义控件演示")
    title_label.setStyleSheet("""
        QLabel {
            font-size: 20px;
            font-weight: bold;
            color: #333;
            text-align: center;
            margin: 20px 0;
        }
    """)
    scroll_layout.addWidget(title_label)
    
    # 说明文本
    info_label = QLabel("这个窗口展示了自定义控件库的核心功能：\n\n" \
                        "• 纯白圆角矩形外观\n" \
                        "• 右上角圆形关闭按钮\n" \
                        "• 可拖拽移动（通过标题栏）\n" \
                        "• 支持内嵌其他控件\n" \
                        "• 带阴影效果\n" \
                        "• 多种按钮样式\n" \
                        "• 自定义进度条\n" \
                        "• 自定义提示窗口")
    info_label.setStyleSheet("""
        QLabel {
            font-size: 14px;
            color: #666;
            line-height: 1.6;
            margin: 0 20px 20px;
        }
    """)
    info_label.setWordWrap(True)
    scroll_layout.addWidget(info_label)
    
    # 按钮类型展示（只保留3种样式按钮）
    
    # 按钮样式标题
    button_style_title = QLabel("按钮样式演示")
    button_style_title.setStyleSheet("""
        QLabel {
            font-size: 18px;
            font-weight: bold;
            color: #333;
            margin: 20px 0 10px;
        }
    """)
    scroll_layout.addWidget(button_style_title)
    
    # 1. 强调色按钮
    primary_button = CustomButton("强调色按钮", button_type="primary")
    primary_button.clicked.connect(lambda: print("强调色按钮被点击了！"))
    scroll_layout.addWidget(primary_button)
    
    # 2. 次选色按钮
    secondary_button = CustomButton("次选色按钮", button_type="secondary")
    secondary_button.clicked.connect(lambda: print("次选色按钮被点击了！"))
    scroll_layout.addWidget(secondary_button)
    
    # 3. 普通按钮（纯白色背景，纯黑色文字）
    normal_button = CustomButton("普通按钮", button_type="normal")
    normal_button.clicked.connect(lambda: print("普通按钮被点击了！"))
    scroll_layout.addWidget(normal_button)
    
    # 自定义提示窗口演示
    message_box_title = QLabel("自定义提示窗口演示")
    message_box_title.setStyleSheet("""
        QLabel {
            font-size: 18px;
            font-weight: bold;
            color: #333;
            margin: 20px 0 10px;
        }
    """)
    scroll_layout.addWidget(message_box_title)
    
    # 添加一个按钮来演示基本提示窗口
    show_basic_msg_btn = CustomButton("显示基本提示窗口", button_type="primary")
    show_basic_msg_btn.clicked.connect(lambda: show_basic_message_box(custom_window))
    scroll_layout.addWidget(show_basic_msg_btn)
    
    # 添加一个按钮来演示带图像的提示窗口
    show_image_msg_btn = CustomButton("显示带图像的提示窗口", button_type="secondary")
    show_image_msg_btn.clicked.connect(lambda: show_image_message_box(custom_window))
    scroll_layout.addWidget(show_image_msg_btn)
    
    # 添加一个按钮来演示带进度条的提示窗口
    show_progress_msg_btn = CustomButton("显示带进度条的提示窗口", button_type="normal")
    show_progress_msg_btn.clicked.connect(lambda: show_progress_message_box(custom_window))
    scroll_layout.addWidget(show_progress_msg_btn)
    
    # 添加一个按钮来演示带多个按钮的提示窗口
    show_multi_btn_msg_btn = CustomButton("显示带多个按钮的提示窗口", button_type="primary")
    show_multi_btn_msg_btn.clicked.connect(lambda: show_multi_button_message_box(custom_window))
    scroll_layout.addWidget(show_multi_btn_msg_btn)
    
    # 添加进度条演示部分
    
    # 进度条标题
    progress_title = QLabel("自定义进度条演示")
    progress_title.setStyleSheet("""
        QLabel {
            font-size: 18px;
            font-weight: bold;
            color: #333;
            margin: 20px 0 10px;
        }
    """)
    scroll_layout.addWidget(progress_title)
    
    # 1. 基本进度条演示
    basic_progress = CustomProgressBar()
    basic_progress.setValue(300)  # 设置初始值为30%
    scroll_layout.addWidget(basic_progress)
    
    # 2. 带有标签的进度条
    # 创建水平布局用于进度条和标签
    labeled_progress_container = QWidget()
    labeled_progress_layout = QHBoxLayout(labeled_progress_container)
    labeled_progress_layout.setContentsMargins(0, 0, 0, 0)
    labeled_progress_layout.setSpacing(10)
    
    labeled_progress = CustomProgressBar()
    labeled_progress.setValue(50)  # 设置初始值为50%
    labeled_progress.setRange(0, 100)  # 范围改为0-100
    
    progress_label = QLabel("50%")
    progress_label.setStyleSheet("""
        QLabel {
            font-size: 14px;
            color: #666;
            min-width: 50px;
            text-align: right;
        }
    """)
    
    # 连接进度条值变化信号到标签更新函数
    def update_progress_label(value):
        progress_label.setText(f"{value}%")
    
    labeled_progress.valueChanged.connect(update_progress_label)
    
    labeled_progress_layout.addWidget(labeled_progress, 1)
    labeled_progress_layout.addWidget(progress_label)
    scroll_layout.addWidget(labeled_progress_container)
    
    # 3. 动态更新的进度条
    dynamic_progress = CustomProgressBar()
    dynamic_progress.setRange(0, 100)
    
    # 创建计时器用于动态更新进度
    timer = QTimer()
    
    # 使用类或闭包替代全局变量
    class ProgressUpdater:
        def __init__(self, progress_bar):
            self.progress_bar = progress_bar
            self.current_progress = 0
            
        def update(self):
            self.current_progress += 5
            if self.current_progress > 100:
                self.current_progress = 0
            self.progress_bar.setValue(self.current_progress)
    
    updater = ProgressUpdater(dynamic_progress)
    timer.timeout.connect(updater.update)
    timer.start(500)  # 每500毫秒更新一次
    
    scroll_layout.addWidget(dynamic_progress)
    
    # 4. 展示交互功能的进度条
    interactive_progress = CustomProgressBar()
    interactive_progress.setRange(0, 100)
    interactive_progress.setValue(70)
    
    # 创建状态标签
    status_label = QLabel("进度条状态：未交互")
    status_label.setStyleSheet("""
        QLabel {
            font-size: 14px;
            color: #666;
            margin: 5px 0;
        }
    """)
    
    # 连接进度条交互信号
    def on_user_interacting():
        status_label.setText("进度条状态：用户正在交互")
    
    def on_user_interaction_ended():
        status_label.setText(f"进度条状态：交互结束，当前值为 {interactive_progress.value()}%")
    
    interactive_progress.userInteracting.connect(on_user_interacting)
    interactive_progress.userInteractionEnded.connect(on_user_interaction_ended)
    
    scroll_layout.addWidget(interactive_progress)
    scroll_layout.addWidget(status_label)
    
    # 5. 不同范围的进度条
    range_progress = CustomProgressBar()
    range_progress.setRange(0, 10000)  # 大范围
    range_progress.setValue(6500)  # 设置为65%
    
    range_label = QLabel("大范围进度条（0-10000）")
    range_label.setStyleSheet("""
        QLabel {
            font-size: 14px;
            color: #666;
            margin: 5px 0;
        }
    """)
    
    scroll_layout.addWidget(range_label)
    scroll_layout.addWidget(range_progress)
    
    # 不可交互进度条演示
    non_interactive_title = QLabel("不可交互进度条演示")
    non_interactive_title.setStyleSheet("""
        QLabel {
            font-size: 18px;
            font-weight: bold;
            color: #333;
            margin: 20px 0 10px;
        }
    """)
    scroll_layout.addWidget(non_interactive_title)
    
    # 1. 基本不可交互进度条
    basic_non_interactive = CustomProgressBar(is_interactive=False)
    basic_non_interactive.setValue(400)  # 设置初始值为40%
    scroll_layout.addWidget(basic_non_interactive)
    
    # 2. 不同进度值的不可交互进度条
    # 创建垂直布局用于多个进度条
    multiple_progress_container = QWidget()
    multiple_progress_layout = QVBoxLayout(multiple_progress_container)
    multiple_progress_layout.setContentsMargins(0, 0, 0, 0)
    multiple_progress_layout.setSpacing(8)
    
    # 添加多个不同进度值的不可交互进度条
    for progress_value in [20, 45, 70, 95]:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        label = QLabel(f"{progress_value}%")
        label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                color: #666;
                min-width: 40px;
                text-align: right;
            }
        """)
        
        progress_bar = CustomProgressBar(is_interactive=False)
        progress_bar.setRange(0, 100)
        progress_bar.setValue(progress_value)
        
        layout.addWidget(label)
        layout.addWidget(progress_bar, 1)
        multiple_progress_layout.addWidget(container)
    
    scroll_layout.addWidget(multiple_progress_container)
    
    # 3. 动态更新的不可交互进度条
    dynamic_non_interactive = CustomProgressBar(is_interactive=False)
    dynamic_non_interactive.setRange(0, 100)
    
    # 创建计时器用于动态更新进度
    timer_non_interactive = QTimer()
    
    class ProgressUpdaterNonInteractive:
        def __init__(self, progress_bar):
            self.progress_bar = progress_bar
            self.current_progress = 0
            
        def update(self):
            self.current_progress += 3
            if self.current_progress > 100:
                self.current_progress = 0
            self.progress_bar.setValue(self.current_progress)
    
    updater_non_interactive = ProgressUpdaterNonInteractive(dynamic_non_interactive)
    timer_non_interactive.timeout.connect(updater_non_interactive.update)
    timer_non_interactive.start(300)  # 每300毫秒更新一次
    
    scroll_layout.addWidget(dynamic_non_interactive)
    
    # 4. 可切换交互状态的进度条
    toggle_progress_container = QWidget()
    toggle_progress_layout = QVBoxLayout(toggle_progress_container)
    toggle_progress_layout.setContentsMargins(0, 0, 0, 0)
    toggle_progress_layout.setSpacing(10)
    
    toggle_progress = CustomProgressBar()
    toggle_progress.setRange(0, 100)
    toggle_progress.setValue(60)
    
    toggle_button = QPushButton("切换交互状态")
    toggle_button.setStyleSheet("""
        QPushButton {
            background-color: #4CAF50;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 4px;
            font-size: 14px;
        }
        QPushButton:hover {
            background-color: #45a049;
        }
    """)
    
    def toggle_interactive():
        current_state = toggle_progress.isInteractive()
        new_state = not current_state
        toggle_progress.setInteractive(new_state)
        toggle_button.setText(f"切换到{'可交互' if current_state else '不可交互'}状态")
    
    toggle_button.clicked.connect(toggle_interactive)
    toggle_progress_layout.addWidget(toggle_progress)
    toggle_progress_layout.addWidget(toggle_button)
    
    scroll_layout.addWidget(toggle_progress_container)
    
    # 添加说明文本
    progress_info = QLabel("进度条功能特点：\n\n" \
                        "• 可交互进度条：支持点击跳转、拖拽调整、悬停和点击效果\n" \
                        "• 不可交互进度条：仅用于进度展示，两端使用条-顶-头图标\n" \
                        "• 使用SVG图标作为装饰元素\n" \
                        "• 提供丰富的信号支持\n" \
                        "• 可自定义外观和范围\n" \
                        "• 支持动态更新\n" \
                        "• 可随时切换交互状态")
    progress_info.setStyleSheet("""
        QLabel {
            font-size: 14px;
            color: #666;
            line-height: 1.6;
            margin: 10px 0 20px;
        }
    """)
    progress_info.setWordWrap(True)
    scroll_layout.addWidget(progress_info)
    
    # 添加一个占位符，确保最后一个控件能完全显示
    spacer = QWidget()
    spacer.setFixedHeight(20)
    scroll_layout.addWidget(spacer)
    
    # 设置滚动区域的内容
    scroll_area.setWidget(scroll_content)
    
    # 将滚动区域添加到自定义窗口
    custom_window.add_widget(scroll_area)
    
    # 触发resizeEvent以更新所有按钮的圆角半径
    # 正确获取所有按钮
    all_buttons = []
    for i in range(scroll_layout.count()):
        widget = scroll_layout.itemAt(i).widget()
        if isinstance(widget, QPushButton):
            all_buttons.append(widget)
    
    for button in all_buttons:
        button.resizeEvent(None)
    
    # 显示窗口
    custom_window.show()
    
    # 运行应用
    sys.exit(app.exec_())


def show_basic_message_box(parent):
    """显示基本提示窗口"""
    from PyQt5.QtGui import QPixmap
    from PyQt5.QtCore import Qt
    
    msg_box = CustomMessageBox(parent)
    msg_box.set_title("基本提示")
    msg_box.set_text("这是一个基本的自定义提示窗口示例。")
    msg_box.set_buttons(["确定"])
    msg_box.buttonClicked.connect(lambda idx: print(f"按钮 {idx} 被点击") or msg_box.close())
    msg_box.show()


def show_image_message_box(parent):
    """显示带图像的提示窗口"""
    from PyQt5.QtGui import QPixmap
    from PyQt5.QtCore import Qt
    
    msg_box = CustomMessageBox(parent)
    msg_box.set_title("带图像提示")
    msg_box.set_text("这是一个带图像的自定义提示窗口示例。")
    # 使用PyQt5内置的测试图像
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.blue)
    msg_box.set_image(pixmap)
    msg_box.set_buttons(["确定"])
    msg_box.buttonClicked.connect(lambda idx: msg_box.close())
    msg_box.show()


def show_progress_message_box(parent):
    """显示带进度条的提示窗口"""
    from PyQt5.QtGui import QPixmap
    from PyQt5.QtCore import Qt
    
    msg_box = CustomMessageBox(parent)
    msg_box.set_title("带进度条提示")
    msg_box.set_text("这是一个带进度条的自定义提示窗口示例。")
    
    # 创建并设置进度条
    from src.widgets.custom_widgets import CustomProgressBar
    progress = CustomProgressBar()
    progress.setRange(0, 100)
    progress.setValue(50)
    msg_box.set_progress(progress)
    
    msg_box.set_buttons(["取消"])
    msg_box.buttonClicked.connect(lambda idx: msg_box.close())
    msg_box.show()


def show_multi_button_message_box(parent):
    """显示带多个按钮的提示窗口"""
    from PyQt5.QtGui import QPixmap
    from PyQt5.QtCore import Qt
    
    msg_box = CustomMessageBox(parent)
    msg_box.set_title("多按钮提示")
    msg_box.set_text("这是一个带多个按钮的自定义提示窗口示例。")
    msg_box.set_buttons(["确定", "取消", "更多"])
    msg_box.buttonClicked.connect(lambda idx: print(f"按钮 {idx} 被点击") or msg_box.close())
    msg_box.show()


if __name__ == "__main__":
    show_custom_window()