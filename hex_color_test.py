#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
专门测试十六进制颜色值的SVG渲染
"""

import sys
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
from PyQt5.QtGui import QPixmap
from PyQt5.QtSvg import QSvgRenderer, QSvgWidget


class HexColorTest(QWidget):
    """
    测试十六进制颜色值的SVG渲染
    """
    
    def __init__(self):
        super().__init__()
        self.init_ui()
    
    def init_ui(self):
        """
        初始化用户界面
        """
        self.setWindowTitle('十六进制颜色值SVG渲染测试')
        self.setGeometry(100, 100, 400, 600)
        
        # 创建布局
        layout = QVBoxLayout()
        
        # 测试不同的十六进制颜色值
        test_cases = [
            {'name': '纯红色', 'svg': '<svg width="100" height="100" xmlns="http://www.w3.org/2000/svg"><circle cx="50" cy="50" r="40" fill="#ff0000" /></svg>'},
            {'name': '50%透明红色', 'svg': '<svg width="100" height="100" xmlns="http://www.w3.org/2000/svg"><circle cx="50" cy="50" r="40" fill="#ff000080" /></svg>'},
            {'name': '25%透明红色', 'svg': '<svg width="100" height="100" xmlns="http://www.w3.org/2000/svg"><circle cx="50" cy="50" r="40" fill="#ff000040" /></svg>'},
            {'name': '纯蓝色', 'svg': '<svg width="100" height="100" xmlns="http://www.w3.org/2000/svg"><circle cx="50" cy="50" r="40" fill="#0000ff" /></svg>'},
            {'name': '50%透明蓝色', 'svg': '<svg width="100" height="100" xmlns="http://www.w3.org/2000/svg"><circle cx="50" cy="50" r="40" fill="#0000ff80" /></svg>'}
        ]
        
        for test_case in test_cases:
            # 创建测试项布局
            test_layout = QVBoxLayout()
            
            # 测试名称
            name_label = QLabel(test_case['name'])
            test_layout.addWidget(name_label)
            
            # 直接使用QSvgWidget渲染
            svg_widget = QSvgWidget()
            svg_widget.load(test_case['svg'].encode('utf-8'))
            svg_widget.setFixedSize(100, 100)
            svg_widget.setStyleSheet('background-color: #f0f0f0; border: 1px solid #ccc;')
            test_layout.addWidget(svg_widget)
            
            # 使用QSvgRenderer渲染到QPixmap
            pixmap = QPixmap(100, 100)
            pixmap.fill(Qt.transparent)  # 透明背景
            
            svg_renderer = QSvgRenderer(test_case['svg'].encode('utf-8'))
            from PyQt5.QtGui import QPainter
            painter = QPainter(pixmap)
            svg_renderer.render(painter)
            painter.end()
            
            # 显示渲染结果
            pixmap_label = QLabel()
            pixmap_label.setPixmap(pixmap)
            pixmap_label.setStyleSheet('background-color: #f0f0f0; border: 1px solid #ccc;')
            test_layout.addWidget(pixmap_label)
            
            # 保存到文件以便查看
            pixmap.save(f'test_hex_{test_case["name"]}.png')
            
            layout.addLayout(test_layout)
        
        self.setLayout(layout)


if __name__ == '__main__':
    # 创建应用程序实例
    app = QApplication(sys.argv)
    
    # 运行测试
    window = HexColorTest()
    window.show()
    
    # 运行命令行测试
    print("\n命令行测试开始...")
    
    # 测试简单的红色圆形SVG
    simple_red_svg = '<svg width="24" height="24" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="10" fill="#ff000080" /></svg>'
    
    # 直接使用QSvgRenderer渲染
    svg_renderer = QSvgRenderer(simple_red_svg.encode('utf-8'))
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.transparent)  # 透明背景
    
    from PyQt5.QtGui import QPainter
    painter = QPainter(pixmap)
    svg_renderer.render(painter)
    painter.end()
    
    # 检查像素值
    image = pixmap.toImage()
    pixel = image.pixel(12, 12)
    alpha = (pixel >> 24) & 0xFF
    red = (pixel >> 16) & 0xFF
    green = (pixel >> 8) & 0xFF
    blue = pixel & 0xFF
    print(f"中心像素: RGBA({red},{green},{blue},{alpha}) = {hex(pixel)}")
    
    # 保存到文件
    pixmap.save('test_simple_red.png')
    
    print("命令行测试完成！")
    
    sys.exit(app.exec_())
