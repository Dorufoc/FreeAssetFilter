#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动时间轴组件测试脚本
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
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()