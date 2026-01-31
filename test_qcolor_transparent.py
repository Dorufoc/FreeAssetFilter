#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 QColor 透明色的不同表示方法
"""

from PyQt5.QtGui import QColor

# 创建透明色
transparent = QColor(0, 0, 0, 0)

print("QColor 透明色测试")
print("=" * 60)
print(f"QColor(0, 0, 0, 0)")
print(f"  name(): {transparent.name()}")
print(f"  name(QColor.HexArgb): {transparent.name(QColor.HexArgb)}")
print(f"  rgba(): {transparent.rgba()}")
print(f"  alpha(): {transparent.alpha()}")
print(f"  isValid(): {transparent.isValid()}")

# 测试其他方式
transparent2 = QColor("transparent")
print(f"\nQColor('transparent')")
print(f"  name(): {transparent2.name()}")
print(f"  isValid(): {transparent2.isValid()}")

# 测试 CSS 透明色格式
print(f"\nCSS 透明色格式:")
print(f"  rgba(0, 0, 0, 0)")
print(f"  #00000000")
