#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动时间轴组件测试脚本（带测试数据）
"""

import sys
import os
import datetime

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from PyQt5.QtWidgets import QApplication
from freeassetfilter.components.auto_timeline import AutoTimeline


def test_timeline_format():
    """测试时间轴时间格式显示"""
    app = QApplication(sys.argv)
    
    # 创建并显示自动时间轴窗口
    timeline_window = AutoTimeline()
    
    # 自动导入测试数据
    test_csv_path = os.path.join(os.path.dirname(__file__), 'test_timeline_data.csv')
    
    # 设置时间格式为小时:分钟:秒
    timeline_window.time_format_combo.setCurrentText("%Y-%m-%d %H:%M:%S")
    
    # 导入CSV文件
    timeline_window.parse_csv(test_csv_path)
    timeline_window.merge_events()
    timeline_window.update_view()
    timeline_window.update_status()
    
    # 验证时间范围显示
    print("时间范围显示:", timeline_window.time_range_label.text())
    
    # 验证时间轴控件的时间格式设置
    timeline_widget = timeline_window.timeline_widget
    
    # 测试format_time方法
    test_time = datetime.datetime(2023, 1, 1, 14, 0, 0)
    formatted_time = timeline_widget.format_time(test_time, 300)  # 5分钟间隔
    print("格式化时间测试:", formatted_time)
    
    # 验证是否显示为HH:MM:SS格式
    expected_format = "14:00:00"
    if formatted_time == expected_format:
        print("✓ 时间格式正确，显示为HH:MM:SS")
    else:
        print(f"✗ 时间格式错误，预期: {expected_format}, 实际: {formatted_time}")
    
    # 显示时间轴窗口
    timeline_window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    test_timeline_format()