#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import time
from PyQt5.QtWidgets import QApplication

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# 导入统一预览器组件
from freeassetfilter.components.unified_previewer import UnifiedPreviewer


def test_archive_preview():
    """
    测试压缩包预览功能
    """
    app = QApplication(sys.argv)
    
    # 创建统一预览器实例
    previewer = UnifiedPreviewer()
    
    # 设置预览器大小
    previewer.resize(800, 600)
    
    # 显示预览器
    previewer.show()
    
    # 模拟选择一个压缩包文件
    # 请将下面的路径替换为您系统中实际存在的压缩包文件路径
    # archive_path = "C:/path/to/your/archive/file.zip"
    archive_path = "C:/Users/Dorufoc/Desktop/diskgenius_86330.rar"  # 示例路径，需要替换为实际路径
    
    # 检查文件是否存在
    if not os.path.exists(archive_path):
        print(f"错误: 文件不存在 - {archive_path}")
        print("请在test_archive_preview.py中修改archive_path为实际存在的压缩包文件路径")
        sys.exit(1)
    
    # 构建文件信息字典
    file_info = {
        "path": archive_path,
        "suffix": os.path.splitext(archive_path)[1][1:].lower(),  # 获取文件后缀（不含.）
        "is_dir": False
    }
    
    print(f"测试压缩包预览: {archive_path}")
    
    # 设置要预览的文件
    previewer.set_file(file_info)
    
    # 运行应用程序
    sys.exit(app.exec_())


if __name__ == "__main__":
    test_archive_preview()
