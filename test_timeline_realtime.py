#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动时间轴实时选中文件显示测试脚本
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from PyQt5.QtWidgets import QApplication
from freeassetfilter.components.auto_timeline import AutoTimeline

def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    # 创建并显示自动时间轴窗口
    timeline_window = AutoTimeline()
    timeline_window.show()
    
    # 添加一些提示信息
    print("\n=== 实时选中文件显示测试 ===")
    print("1. 左键框选时间轴区域，选中的文件会实时显示在测试窗口")
    print("2. 右键点击时间轴区域，会清除所有选中区域并更新显示")
    print("3. 可以创建多个不重叠的选中区域")
    print("4. 重叠的选中区域会自动合并\n")
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
