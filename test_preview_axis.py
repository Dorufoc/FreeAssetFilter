#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试实时预览轴功能
"""

import sys
import os
import datetime
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt, QPoint

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from freeassetfilter.components.auto_timeline import AutoTimeline
from freeassetfilter.components.auto_timeline import TimelineWidget


def test_preview_axis():
    """测试实时预览轴功能"""
    app = QApplication(sys.argv)
    
    # 创建时间轴窗口
    auto_timeline = AutoTimeline()
    auto_timeline.show()
    
    # 等待应用程序初始化完成
    QApplication.processEvents()
    
    # 检查TimelineWidget是否有预览轴相关属性
    timeline_widget = auto_timeline.scroll_widget.timeline_widget
    
    # 检查是否存在预览轴相关属性
    assert hasattr(timeline_widget, 'mouse_position'), "TimelineWidget 缺少 mouse_position 属性"
    assert hasattr(timeline_widget, 'is_mouse_in_timeline'), "TimelineWidget 缺少 is_mouse_in_timeline 属性"
    
    # 检查是否存在预览轴相关方法
    assert hasattr(timeline_widget, 'draw_preview_axis'), "TimelineWidget 缺少 draw_preview_axis 方法"
    assert hasattr(timeline_widget, 'get_time_at_position'), "TimelineWidget 缺少 get_time_at_position 方法"
    assert hasattr(timeline_widget, 'get_event_at_position'), "TimelineWidget 缺少 get_event_at_position 方法"
    
    print("预览轴功能基本结构检查通过")
    
    # 运行应用程序
    sys.exit(app.exec_())


if __name__ == "__main__":
    test_preview_axis()
