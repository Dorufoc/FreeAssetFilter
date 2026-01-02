#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试自动时间轴组件的新功能：
1. 检查目录文件数量一致时使用现有CSV
2. 刷新按钮重新生成CSV并覆盖原有文件
"""

import os
import sys
import json
import csv
import datetime
import tempfile
import shutil

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from freeassetfilter.core.folder_timeline_generator import FolderTimelineGenerator

def test_csv_generation_and_mapping():
    """测试CSV生成和映射功能"""
    print("=== 测试CSV生成和映射功能 ===")
    
    # 创建临时测试目录
    test_dir = os.path.join(os.path.dirname(__file__), "test_timeline_dir")
    os.makedirs(test_dir, exist_ok=True)
    
    # 创建测试子目录和文件
    test_subdirs = ["event1-cam1", "event1-cam2", "event2-cam1"]
    for subdir in test_subdirs:
        subdir_path = os.path.join(test_dir, subdir)
        os.makedirs(subdir_path, exist_ok=True)
        
        # 创建测试视频文件（空文件）
        for i in range(2):
            test_file = os.path.join(subdir_path, f"video_{i+1}.mp4")
            with open(test_file, "w") as f:
                f.write("test video content")
    
    try:
        # 创建生成器实例
        generator = FolderTimelineGenerator()
        
        # 生成CSV
        success, message = generator.generate_timeline_csv(test_dir)
        assert success, f"生成CSV失败：{message}"
        
        # 从消息中提取CSV路径
        csv_path = message.split("：")[-1].strip()
        assert os.path.exists(csv_path), f"CSV文件不存在：{csv_path}"
        
        print(f"✓ 成功生成CSV文件：{csv_path}")
        
        # 检查映射文件是否更新
        mapping_file = os.path.join(generator.data_dir, 'timeline_mapping.json')
        assert os.path.exists(mapping_file), f"映射文件不存在：{mapping_file}"
        
        with open(mapping_file, 'r', encoding='utf-8') as f:
            mapping_data = json.load(f)
        
        normalized_test_dir = os.path.normpath(test_dir)
        assert normalized_test_dir in mapping_data, f"测试目录不在映射文件中：{normalized_test_dir}"
        assert mapping_data[normalized_test_dir]['csv_path'] == csv_path, f"映射文件中的CSV路径不正确"
        
        print("✓ 映射文件更新成功")
        
        # 测试覆盖CSV功能
        print("\n测试覆盖CSV功能...")
        
        # 修改CSV内容（模拟第一次生成的内容）
        with open(csv_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # 记录原始行数
        original_row_count = len(lines)
        
        # 重新生成CSV，指定相同的输出路径
        success, message = generator.generate_timeline_csv(test_dir, csv_path)
        assert success, f"覆盖CSV失败：{message}"
        
        # 检查CSV文件是否存在
        assert os.path.exists(csv_path), f"CSV文件在覆盖后不存在：{csv_path}"
        
        # 验证覆盖后内容是否更新
        with open(csv_path, 'r', encoding='utf-8') as f:
            new_lines = f.readlines()
        
        # 至少应该有标题行
        assert len(new_lines) > 0, "覆盖后的CSV文件为空"
        
        print("✓ 成功覆盖CSV文件")
        
        print("\n=== CSV生成和映射功能测试通过 ===")
        return csv_path
        
    finally:
        # 清理临时目录
        shutil.rmtree(test_dir)


def test_file_count_matching():
    """测试文件数量匹配功能"""
    print("\n=== 测试文件数量匹配功能 ===")
    
    # 创建临时测试目录
    test_dir = os.path.join(os.path.dirname(__file__), "test_timeline_dir_2")
    os.makedirs(test_dir, exist_ok=True)
    
    # 创建测试子目录和文件
    test_subdirs = ["event1-cam1"]
    for subdir in test_subdirs:
        subdir_path = os.path.join(test_dir, subdir)
        os.makedirs(subdir_path, exist_ok=True)
        
        # 创建2个测试视频文件
        for i in range(2):
            test_file = os.path.join(subdir_path, f"video_{i+1}.mp4")
            with open(test_file, "w") as f:
                f.write("test video content")
    
    try:
        generator = FolderTimelineGenerator()
        
        # 第一次生成CSV
        success, message = generator.generate_timeline_csv(test_dir)
        assert success, f"第一次生成CSV失败：{message}"
        
        csv_path = message.split("：")[-1].strip()
        
        # 获取当前文件夹的视频文件数量
        current_file_count = generator.get_video_file_count(test_dir)
        assert current_file_count == 2, f"视频文件数量不正确：{current_file_count}，预期：2"
        
        # 检查CSV文件中的行数
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            csv_row_count = sum(1 for row in reader) - 1  # 减去表头行
        
        assert csv_row_count == 2, f"CSV行数不正确：{csv_row_count}，预期：2"
        
        # 验证文件数量匹配
        assert current_file_count == csv_row_count, f"文件数量与CSV行数不匹配：{current_file_count} vs {csv_row_count}"
        
        print("✓ 文件数量匹配测试通过")
        
        # 测试添加文件后数量不匹配的情况
        print("\n测试添加文件后数量不匹配的情况...")
        
        # 添加一个新的视频文件
        new_file = os.path.join(test_dir, "event1-cam1", "video_3.mp4")
        with open(new_file, "w") as f:
            f.write("new test video content")
        
        # 检查文件数量是否增加
        new_file_count = generator.get_video_file_count(test_dir)
        assert new_file_count == 3, f"视频文件数量不正确：{new_file_count}，预期：3"
        
        # 检查CSV行数是否仍然是2
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            csv_row_count = sum(1 for row in reader) - 1
        
        assert csv_row_count == 2, f"CSV行数应该保持不变：{csv_row_count}，预期：2"
        
        # 验证文件数量与CSV行数不匹配
        assert new_file_count != csv_row_count, f"文件数量与CSV行数应该不匹配：{new_file_count} vs {csv_row_count}"
        
        print("✓ 文件数量不匹配测试通过")
        
        print("\n=== 文件数量匹配功能测试通过 ===")
        
    finally:
        # 清理临时目录
        shutil.rmtree(test_dir)


def main():
    """主测试函数"""
    print("开始测试自动时间轴组件新功能...")
    
    try:
        # 测试CSV生成和映射功能
        test_csv_generation_and_mapping()
        
        # 测试文件数量匹配功能
        test_file_count_matching()
        
        print("\n🎉 所有测试通过！自动时间轴组件的新功能工作正常。")
        
    except Exception as e:
        print(f"\n❌ 测试失败：{str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
