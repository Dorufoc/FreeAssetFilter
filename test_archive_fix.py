#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# 导入统一预览器组件
from freeassetfilter.components.unified_previewer import UnifiedPreviewer


def test_archive_preview_fix():
    """
    测试压缩包预览修复
    专门用于验证压缩包预览组件是否正确占据整个预览区域
    """
    app = QApplication(sys.argv)
    
    # 创建主窗口
    main_window = QMainWindow()
    main_window.setWindowTitle("压缩包预览修复测试")
    main_window.resize(900, 700)  # 设置一个较大的窗口大小，以便更好地观察预览效果
    
    # 创建中央部件
    central_widget = QWidget()
    main_window.setCentralWidget(central_widget)
    
    # 创建布局
    main_layout = QVBoxLayout(central_widget)
    
    # 创建统一预览器实例
    previewer = UnifiedPreviewer()
    
    # 添加预览器到布局
    main_layout.addWidget(previewer)
    
    # 显示主窗口
    main_window.show()
    
    # 设置一个测试压缩包文件（请确保文件存在）
    # 替换为您系统中实际存在的压缩包文件
    test_archive_path = "C:/Users/Dorufoc/Desktop/diskgenius_86330.rar"  # 示例路径，需要替换为实际路径
    
    # 检查文件是否存在
    if not os.path.exists(test_archive_path):
        print(f"错误: 测试文件不存在 - {test_archive_path}")
        print("请在test_archive_fix.py中修改test_archive_path为实际存在的压缩包文件路径")
        sys.exit(1)
    
    # 构建文件信息字典
    file_info = {
        "path": test_archive_path,
        "suffix": os.path.splitext(test_archive_path)[1][1:].lower(),  # 获取文件后缀（不含.）
        "is_dir": False
    }
    
    print(f"开始测试压缩包预览: {test_archive_path}")
    print("请检查压缩包预览器是否正确占据了整个预览区域，没有中间空白布局")
    
    # 设置要预览的文件
    previewer.set_file(file_info)
    
    # 运行应用程序
    sys.exit(app.exec_())


if __name__ == "__main__":
    test_archive_preview_fix()
