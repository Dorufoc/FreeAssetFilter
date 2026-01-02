#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
测试时间轴选择区域合并功能
"""

import sys
import os
from datetime import datetime, timedelta

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from freeassetfilter.components.auto_timeline import TimelineWidget

class MockTimelineWidget(TimelineWidget):
    """用于测试的模拟TimelineWidget类"""
    
    def __init__(self):
        # 只初始化必要的属性，避免依赖Qt事件循环
        self.selected_ranges = []
    
    def merge_overlapping_ranges(self, ranges):
        """合并重叠或相邻的时间范围"""
        if not ranges:
            return []
            
        # 按起始时间排序
        sorted_ranges = sorted(ranges, key=lambda x: x[0])
        
        merged = [sorted_ranges[0]]
        
        for current_range in sorted_ranges[1:]:
            current_start, current_end = current_range
            last_start, last_end = merged[-1]
            
            # 如果当前范围与上一个范围有重叠或相邻，则合并
            if current_start <= last_end:
                # 合并两个范围，取最小的开始时间和最大的结束时间
                merged[-1] = (last_start, max(last_end, current_end))
            else:
                # 没有重叠，添加当前范围
                merged.append(current_range)
                
        return merged


def test_merge_overlapping_ranges():
    """测试重叠时间范围合并功能"""
    
    print("=== 测试时间范围合并功能 ===")
    
    # 创建测试实例
    timeline = MockTimelineWidget()
    
    # 测试用例1：无重叠范围
    print("\n测试用例1：无重叠范围")
    ranges1 = [
        (datetime(2024, 1, 1, 10, 0, 0), datetime(2024, 1, 1, 10, 30, 0)),
        (datetime(2024, 1, 1, 11, 0, 0), datetime(2024, 1, 1, 11, 30, 0)),
        (datetime(2024, 1, 1, 12, 0, 0), datetime(2024, 1, 1, 12, 30, 0))
    ]
    merged1 = timeline.merge_overlapping_ranges(ranges1)
    print(f"原始范围: {[(r[0].strftime('%H:%M'), r[1].strftime('%H:%M')) for r in ranges1]}")
    print(f"合并后: {[(r[0].strftime('%H:%M'), r[1].strftime('%H:%M')) for r in merged1]}")
    print(f"测试结果: {'通过' if len(merged1) == 3 else '失败'} (期望: 3个范围，实际: {len(merged1)}个范围)")
    
    # 测试用例2：完全重叠范围
    print("\n测试用例2：完全重叠范围")
    ranges2 = [
        (datetime(2024, 1, 1, 10, 0, 0), datetime(2024, 1, 1, 12, 0, 0)),
        (datetime(2024, 1, 1, 10, 30, 0), datetime(2024, 1, 1, 11, 30, 0)),
        (datetime(2024, 1, 1, 10, 45, 0), datetime(2024, 1, 1, 11, 15, 0))
    ]
    merged2 = timeline.merge_overlapping_ranges(ranges2)
    print(f"原始范围: {[(r[0].strftime('%H:%M'), r[1].strftime('%H:%M')) for r in ranges2]}")
    print(f"合并后: {[(r[0].strftime('%H:%M'), r[1].strftime('%H:%M')) for r in merged2]}")
    print(f"测试结果: {'通过' if len(merged2) == 1 else '失败'} (期望: 1个范围，实际: {len(merged2)}个范围)")
    
    # 测试用例3：部分重叠范围
    print("\n测试用例3：部分重叠范围")
    ranges3 = [
        (datetime(2024, 1, 1, 10, 0, 0), datetime(2024, 1, 1, 11, 0, 0)),
        (datetime(2024, 1, 1, 10, 30, 0), datetime(2024, 1, 1, 11, 30, 0)),
        (datetime(2024, 1, 1, 12, 0, 0), datetime(2024, 1, 1, 13, 0, 0)),
        (datetime(2024, 1, 1, 12, 30, 0), datetime(2024, 1, 1, 13, 30, 0))
    ]
    merged3 = timeline.merge_overlapping_ranges(ranges3)
    print(f"原始范围: {[(r[0].strftime('%H:%M'), r[1].strftime('%H:%M')) for r in ranges3]}")
    print(f"合并后: {[(r[0].strftime('%H:%M'), r[1].strftime('%H:%M')) for r in merged3]}")
    print(f"测试结果: {'通过' if len(merged3) == 2 else '失败'} (期望: 2个范围，实际: {len(merged3)}个范围)")
    
    # 测试用例4：相邻范围
    print("\n测试用例4：相邻范围")
    ranges4 = [
        (datetime(2024, 1, 1, 10, 0, 0), datetime(2024, 1, 1, 11, 0, 0)),
        (datetime(2024, 1, 1, 11, 0, 0), datetime(2024, 1, 1, 12, 0, 0)),
        (datetime(2024, 1, 1, 12, 0, 0), datetime(2024, 1, 1, 13, 0, 0))
    ]
    merged4 = timeline.merge_overlapping_ranges(ranges4)
    print(f"原始范围: {[(r[0].strftime('%H:%M'), r[1].strftime('%H:%M')) for r in ranges4]}")
    print(f"合并后: {[(r[0].strftime('%H:%M'), r[1].strftime('%H:%M')) for r in merged4]}")
    print(f"测试结果: {'通过' if len(merged4) == 1 else '失败'} (期望: 1个范围，实际: {len(merged4)}个范围)")
    
    # 测试用例5：复杂混合范围
    print("\n测试用例5：复杂混合范围")
    ranges5 = [
        (datetime(2024, 1, 1, 10, 0, 0), datetime(2024, 1, 1, 10, 30, 0)),  # 独立
        (datetime(2024, 1, 1, 10, 20, 0), datetime(2024, 1, 1, 10, 45, 0)),  # 与第一个重叠
        (datetime(2024, 1, 1, 11, 0, 0), datetime(2024, 1, 1, 11, 30, 0)),  # 独立
        (datetime(2024, 1, 1, 11, 20, 0), datetime(2024, 1, 1, 11, 50, 0)),  # 与第三个重叠
        (datetime(2024, 1, 1, 12, 0, 0), datetime(2024, 1, 1, 12, 30, 0)),  # 独立
    ]
    merged5 = timeline.merge_overlapping_ranges(ranges5)
    print(f"原始范围: {[(r[0].strftime('%H:%M'), r[1].strftime('%H:%M')) for r in ranges5]}")
    print(f"合并后: {[(r[0].strftime('%H:%M'), r[1].strftime('%H:%M')) for r in merged5]}")
    print(f"测试结果: {'通过' if len(merged5) == 3 else '失败'} (期望: 3个范围，实际: {len(merged5)}个范围)")
    
    print("\n=== 所有测试完成 ===")


if __name__ == "__main__":
    test_merge_overlapping_ranges()
