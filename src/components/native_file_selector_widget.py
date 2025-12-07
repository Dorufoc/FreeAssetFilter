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
可内嵌的原生Qt文件选择器组�?直接使用CustomFileSelector组件，保证与main主页面中的文件选择器功能和UI一�?
"""

import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow
)

from .custom_file_selector import CustomFileSelector


class NativeFileSelectorWidget(CustomFileSelector):
    """
    可内嵌的原生Qt文件选择器组�?
    直接继承自CustomFileSelector，功能和UI与main主页面中的文件选择器完全一�?
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 500)


# 测试代码
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle("测试原生文件选择器组件")
    window.setGeometry(100, 100, 1200, 800)
    
    # 创建并添加原生文件选择器组�?
    file_selector = NativeFileSelectorWidget()
    window.setCentralWidget(file_selector)
    
    window.show()
    sys.exit(app.exec_())
