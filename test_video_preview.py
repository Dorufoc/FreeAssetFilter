#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试视频预览修复
验证视频不会弹出独立窗口，而是在预览面板中正常显示
"""

import os
import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton, QFileDialog, QLabel
from PyQt5.QtCore import Qt

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入测试组件
from freeassetfilter.components.unified_previewer import UnifiedPreviewer


class TestWindow(QMainWindow):
    """
    测试窗口，用于验证视频预览修复
    """
    
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("视频预览测试")
        self.setGeometry(100, 100, 1200, 800)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建布局
        layout = QVBoxLayout(central_widget)
        
        # 添加标题
        title = QLabel("视频预览测试 - 验证视频不会弹出独立窗口")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: bold; margin: 10px;")
        layout.addWidget(title)
        
        # 创建选择文件按钮
        self.select_btn = QPushButton("选择视频文件")
        self.select_btn.clicked.connect(self.select_video_file)
        self.select_btn.setStyleSheet("margin: 10px; padding: 10px;")
        layout.addWidget(self.select_btn)
        
        # 创建统一预览器
        self.previewer = UnifiedPreviewer()
        self.previewer.setMinimumSize(800, 600)
        layout.addWidget(self.previewer)
        
        # 添加状态标签
        self.status_label = QLabel("选择视频文件开始测试")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("margin: 10px; color: blue;")
        layout.addWidget(self.status_label)
    
    def select_video_file(self):
        """
        选择视频文件进行预览
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "选择视频文件", 
            "", 
            "视频文件 (*.mp4 *.mov *.m4v *.flv *.mxf *.3gp *.mpg *.avi *.wmv *.mkv *.webm *.vob *.ogv *.rmvb)"
        )
        
        if file_path:
            self.status_label.setText(f"正在预览: {os.path.basename(file_path)}")
            print(f"开始预览视频: {file_path}")
            
            # 使用统一预览器预览视频
            self.previewer.show_preview(file_path)
            
            print("视频预览启动成功 - 检查是否弹出独立窗口")


if __name__ == "__main__":
    """
    主测试函数
    """
    print("启动视频预览测试...")
    print("注意：测试期间不应出现独立的视频窗口弹出")
    print("视频应在主窗口的预览面板中显示")
    print("=" * 60)
    
    app = QApplication(sys.argv)
    
    window = TestWindow()
    window.show()
    
    print("测试窗口已显示")
    print("点击 '选择视频文件' 按钮开始测试")
    
    sys.exit(app.exec_())
