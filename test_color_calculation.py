#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试颜色计算逻辑，验证深色模式下的颜色变化
"""

from PyQt5.QtGui import QColor


def darken_color_qcolor(color_hex, percentage, is_dark_mode):
    """模拟 darken_color_qcolor 函数"""
    color = QColor(color_hex)
    
    if is_dark_mode:
        # 深色模式下变浅
        r = min(255, int(color.red() * (1 + percentage)))
        g = min(255, int(color.green() * (1 + percentage)))
        b = min(255, int(color.blue() * (1 + percentage)))
    else:
        # 浅色模式下加深
        r = max(0, int(color.red() * (1 - percentage)))
        g = max(0, int(color.green() * (1 - percentage)))
        b = max(0, int(color.blue() * (1 - percentage)))
    return QColor(r, g, b)


def test_colors():
    """测试各种颜色在不同模式下的变化"""
    print("=" * 80)
    print("颜色变化测试")
    print("=" * 80)
    
    # 测试颜色配置
    test_cases = [
        ("深色模式 - 底层色 (黑)", "#000000", 0.1),
        ("深色模式 - 底层色 (黑)", "#000000", 0.2),
        ("深色模式 - 普通色", "#3A3A3C", 0.1),
        ("深色模式 - 普通色", "#3A3A3C", 0.2),
        ("深色模式 - 强调色", "#0A84FF", 0.1),
        ("深色模式 - 强调色", "#0A84FF", 0.2),
        ("浅色模式 - 底层色 (白)", "#ffffff", 0.1),
        ("浅色模式 - 底层色 (白)", "#ffffff", 0.2),
        ("浅色模式 - 普通色", "#e0e0e0", 0.1),
        ("浅色模式 - 普通色", "#e0e0e0", 0.2),
        ("浅色模式 - 强调色", "#007AFF", 0.1),
        ("浅色模式 - 强调色", "#007AFF", 0.2),
    ]
    
    for name, color, percentage in test_cases:
        is_dark = "深色模式" in name
        result = darken_color_qcolor(color, percentage, is_dark)
        
        print(f"\n{name}")
        print(f"  原始颜色: {color}")
        print(f"  变化比例: {percentage*100}%")
        print(f"  结果颜色: {result.name()}")
        
        # 计算亮度变化
        orig = QColor(color)
        orig_luminance = 0.299 * orig.red() + 0.587 * orig.green() + 0.114 * orig.blue()
        result_luminance = 0.299 * result.red() + 0.587 * result.green() + 0.114 * result.blue()
        
        if orig_luminance > 0:
            change = (result_luminance - orig_luminance) / orig_luminance * 100
            print(f"  亮度变化: {change:+.1f}%")
        else:
            print(f"  亮度变化: 从纯黑到 {result_luminance:.1f}")
    
    print("\n" + "=" * 80)
    print("问题分析")
    print("=" * 80)
    print("""
在深色模式下：
- 底层色是黑色 (#000000)
- 使用公式: color * (1 + 0.1) = 0 * 1.1 = 0
- 结果仍然是黑色，没有变化

解决方案：
1. 对于深色模式下的黑色，应该使用一个固定的变亮值，而不是百分比
2. 或者使用加法而不是乘法：color + (255 - color) * percentage
3. 或者设置一个最小亮度值
    """)


def test_improved_logic():
    """测试改进后的颜色逻辑"""
    print("\n" + "=" * 80)
    print("改进后的颜色逻辑测试")
    print("=" * 80)
    
    def improved_darken_color(color_hex, percentage, is_dark_mode):
        """改进后的颜色处理函数"""
        color = QColor(color_hex)
        
        if is_dark_mode:
            # 深色模式下变浅 - 使用加法逻辑
            # 从当前颜色向白色方向移动
            r = min(255, int(color.red() + (255 - color.red()) * percentage))
            g = min(255, int(color.green() + (255 - color.green()) * percentage))
            b = min(255, int(color.blue() + (255 - color.blue()) * percentage))
        else:
            # 浅色模式下加深 - 使用乘法逻辑
            r = max(0, int(color.red() * (1 - percentage)))
            g = max(0, int(color.green() * (1 - percentage)))
            b = max(0, int(color.blue() * (1 - percentage)))
        return QColor(r, g, b)
    
    # 测试颜色配置
    test_cases = [
        ("深色模式 - 底层色 (黑)", "#000000", 0.1),
        ("深色模式 - 底层色 (黑)", "#000000", 0.2),
        ("深色模式 - 普通色", "#3A3A3C", 0.1),
        ("深色模式 - 普通色", "#3A3A3C", 0.2),
        ("深色模式 - 强调色", "#0A84FF", 0.1),
        ("深色模式 - 强调色", "#0A84FF", 0.2),
        ("浅色模式 - 底层色 (白)", "#ffffff", 0.1),
        ("浅色模式 - 底层色 (白)", "#ffffff", 0.2),
        ("浅色模式 - 普通色", "#e0e0e0", 0.1),
        ("浅色模式 - 普通色", "#e0e0e0", 0.2),
        ("浅色模式 - 强调色", "#007AFF", 0.1),
        ("浅色模式 - 强调色", "#007AFF", 0.2),
    ]
    
    for name, color, percentage in test_cases:
        is_dark = "深色模式" in name
        result = improved_darken_color(color, percentage, is_dark)
        
        print(f"\n{name}")
        print(f"  原始颜色: {color}")
        print(f"  变化比例: {percentage*100}%")
        print(f"  结果颜色: {result.name()}")


if __name__ == "__main__":
    test_colors()
    test_improved_logic()
