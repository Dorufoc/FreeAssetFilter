#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试SVG渲染器，特别是半透明区域的渲染效果
"""

import sys
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QHBoxLayout
from PyQt5.QtGui import QPixmap
from src.utils.svg_renderer import SvgRenderer


class TestSvgRenderer(QWidget):
    """
    测试SVG渲染器的窗口类
    """
    
    def __init__(self):
        super().__init__()
        self.init_ui()
    
    def init_ui(self):
        """
        初始化用户界面
        """
        self.setWindowTitle('SVG渲染器测试')
        self.setGeometry(100, 100, 800, 400)
        
        # 创建布局
        main_layout = QVBoxLayout()
        
        # 测试标题
        title_label = QLabel('SVG渲染器半透明测试')
        main_layout.addWidget(title_label)
        
        # 创建水平布局，用于显示不同大小的渲染结果
        sizes_layout = QHBoxLayout()
        
        # 测试不同大小的渲染
        sizes = [24, 48, 128, 256]
        for size in sizes:
            # 创建垂直布局用于每个测试项
            test_layout = QVBoxLayout()
            
            # 显示大小
            size_label = QLabel(f'{size}x{size}')
            test_layout.addWidget(size_label)
            
            # 渲染SVG
            pixmap = SvgRenderer.render_svg_to_pixmap('test_svg_transparency.svg', size)
            
            # 显示渲染结果
            pixmap_label = QLabel()
            pixmap_label.setPixmap(pixmap)
            pixmap_label.setFixedSize(size, size)
            pixmap_label.setStyleSheet('background-color: #f0f0f0; border: 1px solid #ccc;')
            test_layout.addWidget(pixmap_label)
            
            sizes_layout.addLayout(test_layout)
        
        main_layout.addLayout(sizes_layout)
        
        # 测试SVG字符串渲染
        svg_string = '''
        <svg width="100" height="100" xmlns="http://www.w3.org/2000/svg">
          <circle cx="50" cy="50" r="40" fill="rgba(255, 0, 0, 0.5)" />
          <rect x="20" y="20" width="60" height="60" fill="rgba(0, 255, 0, 0.3)" />
        </svg>
        '''
        
        string_layout = QHBoxLayout()
        string_label = QLabel('SVG字符串渲染:')
        string_layout.addWidget(string_label)
        
        string_pixmap = SvgRenderer.render_svg_string_to_pixmap(svg_string, 128)
        string_pixmap_label = QLabel()
        string_pixmap_label.setPixmap(string_pixmap)
        string_pixmap_label.setFixedSize(128, 128)
        string_pixmap_label.setStyleSheet('background-color: #f0f0f0; border: 1px solid #ccc;')
        string_layout.addWidget(string_pixmap_label)
        
        main_layout.addLayout(string_layout)
        
        self.setLayout(main_layout)


if __name__ == '__main__':
    # 创建应用程序
    app = QApplication(sys.argv)
    
    # 创建测试窗口
    window = TestSvgRenderer()
    window.show()
    
    # 运行应用程序
    sys.exit(app.exec_())
