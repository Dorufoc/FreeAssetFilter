#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试不同变亮幅度下的颜色可见性
"""

from PyQt5.QtGui import QColor


def lighten_color(color_hex, percentage):
    """变亮颜色 - 使用加法逻辑"""
    color = QColor(color_hex)
    r = min(255, int(color.red() + (255 - color.red()) * percentage))
    g = min(255, int(color.green() + (255 - color.green()) * percentage))
    b = min(255, int(color.blue() + (255 - color.blue()) * percentage))
    return QColor(r, g, b)


def test_visibility():
    """测试不同幅度下的颜色可见性"""
    print("=" * 80)
    print("深色模式下按钮颜色变亮效果测试")
    print("=" * 80)

    # 深色模式下的典型颜色
    test_colors = {
        "底层色 (黑)": "#000000",
        "辅助色": "#1C1C1E",
        "普通色": "#3A3A3C",
    }

    # 测试不同的变亮幅度
    percentages = [0.1, 0.15, 0.2, 0.25, 0.3]

    for color_name, color_hex in test_colors.items():
        print(f"\n{color_name}: {color_hex}")
        print("-" * 60)

        for pct in percentages:
            result = lighten_color(color_hex, pct)
            print(f"  变亮 {pct*100:>3.0f}%: {result.name()}")

    print("\n" + "=" * 80)
    print("建议")
    print("=" * 80)
    print("""
对于深色模式下的按钮 hover 效果：
- 底层色 (黑) 建议使用 20-30% 的变亮幅度
- 辅助色和普通色建议使用 15-20% 的变亮幅度

当前代码使用的是 10% 和 20%，对于黑色来说可能不够明显。
建议调整为：
- hover: 20% (原来是 10%)
- pressed: 35% (原来是 20%)
""")


if __name__ == "__main__":
    test_visibility()
