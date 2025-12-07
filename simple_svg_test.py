#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单的SVG渲染测试，直接输出渲染结果的详细信息
"""

import sys
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtSvg import QSvgRenderer, QSvgWidget
from PyQt5.QtWidgets import QApplication


# 测试不同的透明度表示方法
test_svgs = {
    'rgba': '''
<svg width="100" height="100" xmlns="http://www.w3.org/2000/svg">
  <rect width="100" height="100" fill="rgba(255, 255, 255, 0.5)" />
  <circle cx="50" cy="50" r="40" fill="rgba(255, 0, 0, 0.7)" />
</svg>
''',
    'hex': '''
<svg width="100" height="100" xmlns="http://www.w3.org/2000/svg">
  <rect width="100" height="100" fill="#ffffff80" />
  <circle cx="50" cy="50" r="40" fill="#ff0000b3" />
</svg>
''',
    'opacity': '''
<svg width="100" height="100" xmlns="http://www.w3.org/2000/svg">
  <rect width="100" height="100" fill="white" opacity="0.5" />
  <circle cx="50" cy="50" r="40" fill="red" opacity="0.7" />
</svg>
''',
    'solid': '''
<svg width="100" height="100" xmlns="http://www.w3.org/2000/svg">
  <rect width="100" height="100" fill="white" />
  <circle cx="50" cy="50" r="40" fill="red" />
</svg>
'''
}


def test_svg_rendering():
    """
    测试SVG渲染，输出详细信息
    """
    print("开始SVG渲染测试...")
    
    # 创建应用程序实例
    app = QApplication(sys.argv)
    
    for svg_type, svg_content in test_svgs.items():
        print(f"\n测试: {svg_type} 格式")
        
        try:
            # 创建透明背景的QPixmap
            pixmap = QPixmap(100, 100)
            pixmap.fill(Qt.transparent)
            
            from PyQt5.QtGui import QPainter
            painter = QPainter(pixmap)
            
            # 渲染SVG
            svg_renderer = QSvgRenderer(svg_content.encode('utf-8'))
            svg_renderer.render(painter)
            
            painter.end()
            
            # 保存像素图
            filename = f"test_result_{svg_type}.png"
            pixmap.save(filename)
            print(f"  已保存到: {filename}")
            
            # 转换为QImage检查
            image = pixmap.toImage()
            
            # 检查多个像素点
            pixels_to_check = [(0, 0), (50, 50), (99, 99)]
            for x, y in pixels_to_check:
                pixel = image.pixel(x, y)
                alpha = (pixel >> 24) & 0xFF
                red = (pixel >> 16) & 0xFF
                green = (pixel >> 8) & 0xFF
                blue = pixel & 0xFF
                print(f"  像素({x},{y}): RGBA({red},{green},{blue},{alpha}) = {hex(pixel)}")
            
        except Exception as e:
            print(f"  测试失败: {e}")
    
    print("\n测试完成！")


if __name__ == '__main__':
    test_svg_rendering()
