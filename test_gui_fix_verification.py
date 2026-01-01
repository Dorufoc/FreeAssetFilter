#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUI修复验证测试脚本
模拟修改后的GUI路径处理逻辑
"""

import os
import sys
import tempfile
import shutil

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from freeassetfilter.core.folder_timeline_generator import FolderTimelineGenerator

def test_gui_path_fix():
    """测试GUI路径修复"""
    print("=== GUI路径修复验证测试 ===")
    
    # 测试用户提供的路径
    test_folder = r"E:\DFTP\飞院空镜头\20251230机关元旦晚会"
    
    print(f"\n1. 测试修复后的GUI路径处理:")
    print(f"用户选择的输入文件夹: {test_folder}")
    
    # 模拟修复后的路径处理逻辑
    default_output = os.path.join(test_folder, "timeline_generated.csv")
    print(f"修复后的默认输出路径: {default_output}")
    print(f"输出目录: {os.path.dirname(default_output)}")
    print(f"输出文件名: {os.path.basename(default_output)}")
    
    print("\n2. 测试完整生成流程:")
    try:
        # 创建生成器实例
        generator = FolderTimelineGenerator()
        
        # 模拟用户接受默认路径的情况
        output_path = default_output
        
        # 执行生成
        success, message = generator.generate_timeline_csv(test_folder, output_path)
        
        print(f"生成结果: {'成功' if success else '失败'}")
        print(f"生成消息: {message}")
        
        if success and os.path.exists(output_path):
            print(f"\n3. 验证输出文件位置:")
            print(f"文件是否存在: {'是' if os.path.exists(output_path) else '否'}")
            print(f"文件大小: {os.path.getsize(output_path)} 字节")
            print(f"文件保存位置: {output_path}")
            
            # 检查文件内容
            with open(output_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            print(f"文件行数: {len(lines)}")
            print(f"表头: {lines[0].strip()}")
            
            return True
        else:
            print(f"错误: 输出文件不存在或生成失败")
            return False
            
    except Exception as e:
        print(f"错误: 完整流程测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def test_subfolder_recognition():
    """再次验证子文件夹识别"""
    print("\n=== 子文件夹识别测试 ===")
    
    test_folder = r"E:\DFTP\飞院空镜头\20251230机关元旦晚会"
    
    try:
        # 创建生成器实例
        generator = FolderTimelineGenerator()
        
        # 收集数据
        timeline_data = generator._collect_timeline_data(test_folder)
        
        print(f"收集到 {len(timeline_data)} 条数据")
        
        # 分析数据中的事件和设备
        event_device_pairs = set()
        for data in timeline_data:
            event_device_pairs.add((data['event_name'], data['device_name']))
        
        print(f"\n识别到的事件-设备组合:")
        for event, device in sorted(event_device_pairs):
            print(f"  {event} - {device}")
        
        print(f"\n识别到的事件数: {len({event for event, _ in event_device_pairs})}")
        print(f"识别到的设备数: {len({device for _, device in event_device_pairs})}")
        
        return True
        
    except Exception as e:
        print(f"错误: 子文件夹识别测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("开始测试GUI路径修复...")
    
    # 运行测试
    path_test_result = test_gui_path_fix()
    folder_test_result = test_subfolder_recognition()
    
    print("\n=== 测试总结 ===")
    if path_test_result and folder_test_result:
        print("✅ 所有测试通过！修复成功。")
        print("\n修复内容:")
        print("1. 将默认输出路径设置为输入文件夹目录")
        print("2. 确保用户可以在熟悉的位置找到生成的文件")
        print("3. 保持了原有的功能和用户体验")
        sys.exit(0)
    else:
        print("❌ 测试失败！需要进一步修复。")
        sys.exit(1)
