#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
直接测试SvgRenderer类，输出详细信息
"""

import sys
from PyQt5.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
from PyQt5.QtGui import QPixmap
from src.utils.svg_renderer import SvgRenderer


class DirectSvgTest(QWidget):
    """
    直接测试SvgRenderer类的窗口
    """
    
    def __init__(self):
        super().__init__()
        self.init_ui()
    
    def init_ui(self):
        """
        初始化用户界面
        """
        self.setWindowTitle('直接SVG渲染测试')
        self.setGeometry(100, 100, 600, 400)
        
        # 创建布局
        layout = QVBoxLayout()
        
        # 测试项目1: 直接渲染实际的图标文件
        label1 = QLabel('测试1: 直接渲染实际的图标文件')
        layout.addWidget(label1)
        
        # 测试不同的图标
        icons_to_test = [
            'src/Icon/图像.svg',
            'src/Icon/视频.svg', 
            'src/Icon/文档.svg',
            'src/Icon/PDF.svg',
            'src/Icon/文件夹.svg'
        ]
        
        for icon_path in icons_to_test:
            # 渲染图标
            pixmap = SvgRenderer.render_svg_to_pixmap(icon_path, 64)
            
            # 显示渲染结果
            pixmap_label = QLabel()
            pixmap_label.setPixmap(pixmap)
            pixmap_label.setStyleSheet('background-color: #f0f0f0; border: 1px solid #ccc;')
            layout.addWidget(pixmap_label)
            
            # 保存到文件以便查看
            pixmap.save(f'test_direct_{os.path.basename(icon_path)}.png')
        
        self.setLayout(layout)


if __name__ == '__main__':
    import os
    
    # 创建应用程序实例
    app = QApplication(sys.argv)
    
    # 运行直接测试
    window = DirectSvgTest()
    window.show()
    
    # 运行简单的命令行测试
    print("\n命令行测试开始...")
    
    # 测试1: 渲染实际的图标文件
    test_icon = 'src/Icon/图像.svg'
    if os.path.exists(test_icon):
        print(f"\n测试1: 渲染图标文件 {test_icon}")
        pixmap = SvgRenderer.render_svg_to_pixmap(test_icon, 24)
        print(f"  渲染结果: {pixmap.size()}, 透明度支持: {pixmap.hasAlpha()}")
        
        # 检查像素值
        image = pixmap.toImage()
        pixel = image.pixel(12, 12)
        alpha = (pixel >> 24) & 0xFF
        red = (pixel >> 16) & 0xFF
        green = (pixel >> 8) & 0xFF
        blue = pixel & 0xFF
        print(f"  中心像素: RGBA({red},{green},{blue},{alpha}) = {hex(pixel)}")
    else:
        print(f"\n测试1失败: 图标文件不存在 {test_icon}")
    
    # 测试2: 渲染简单的SVG字符串
    simple_svg = '''
    <svg width="100" height="100" xmlns="http://www.w3.org/2000/svg">
      <circle cx="50" cy="50" r="40" fill="#ff00007f" />
    </svg>
    '''
    print("\n测试2: 渲染简单SVG字符串")
    pixmap = SvgRenderer.render_svg_string_to_pixmap(simple_svg, 24)
    print(f"  渲染结果: {pixmap.size()}, 透明度支持: {pixmap.hasAlpha()}")
    
    # 检查像素值
    image = pixmap.toImage()
    pixel = image.pixel(12, 12)
    alpha = (pixel >> 24) & 0xFF
    red = (pixel >> 16) & 0xFF
    green = (pixel >> 8) & 0xFF
    blue = pixel & 0xFF
    print(f"  中心像素: RGBA({red},{green},{blue},{alpha}) = {hex(pixel)}")
    
    # 保存测试结果
    pixmap.save('test_simple_svg.png')
    
    print("\n命令行测试完成！")
    
    # 运行窗口测试
    sys.exit(app.exec_())
