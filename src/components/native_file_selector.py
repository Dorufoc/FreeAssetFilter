#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

2. 商业使用：需联系 qpdrfc123@gmail.com 获取书面授权�?
项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE
原生Qt文件选择器组�?使用纯Qt组件实现，不依赖CEF
现在继承自CustomFileSelector，保证与main主页面中的文件选择器功能和UI一�?
"""

import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QWidget
)

from .custom_file_selector import CustomFileSelector


class NativeFileSelector(QMainWindow):
    """
    原生Qt文件选择器主窗口
    继承自QMainWindow，内部使用CustomFileSelector作为核心组件
    功能和UI与main主页面中的文件选择器完全一�?
    """
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("原生文件选择器")
        self.setGeometry(100, 100, 1200, 800)
        
        # 初始化UI
        self.init_ui()
    
    def init_ui(self):
        """
        初始化用户界�?
        """
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建CustomFileSelector实例，这是main主页面中使用的文件选择�?
        self.file_selector = CustomFileSelector()
        main_layout.addWidget(self.file_selector)


# 命令行参数支�?
if __name__ == "__main__":
    app = QApplication(sys.argv)
    selector = NativeFileSelector()
    selector.show()
    sys.exit(app.exec_())
