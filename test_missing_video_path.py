import sys
import os
import tempfile
import datetime
import csv
from PyQt5.QtWidgets import QApplication

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))



def test_missing_video_path_csv():
    """测试处理缺少视频路径的CSV文件"""
    
    # 创建一个简单的QApplication实例
    app = QApplication(sys.argv)
    
    # 创建一个临时CSV文件，不包含视频路径列
    with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8', suffix='.csv') as f:
        writer = csv.writer(f)
        # 写入表头
        writer.writerow(['事件名称', '设备名称', '开始时间', '结束时间'])
        # 写入数据行
        writer.writerow(['A7S3', '24105', '2025-12-30 14:36:15', '2025-12-30 14:36:27'])
        writer.writerow(['FX6', '70200', '2025-12-30 14:37:53', '2025-12-30 14:38:03'])
        
        temp_csv_path = f.name
    
    try:
        # 导入需要测试的类
        from freeassetfilter.components.auto_timeline import AutoTimeline
        
        # 创建一个AutoTimeline实例
        auto_timeline = AutoTimeline()
        
        # 测试parse_csv方法
        print("\n1. 测试parse_csv方法处理缺少视频路径的CSV文件...")
        try:
            auto_timeline.parse_csv(temp_csv_path)
            print("✓ parse_csv成功处理了缺少视频路径的CSV文件")
            print(f"  解析的事件数量: {len(auto_timeline.events)}")
            
            # 检查事件是否正确创建
            for i, event in enumerate(auto_timeline.events, 1):
                print(f"\n  事件 {i}:")
                print(f"    名称: {event.name}")
                print(f"    设备: {event.device}")
                print(f"    视频数量: {len(event.videos)}")
                print(f"    视频列表: {event.videos}")
                
                # 验证视频列表为空
                assert len(event.videos) == 0, f"事件 {i} 不应该有视频路径"
                
        except Exception as e:
            print(f"✗ parse_csv失败: {e}")
            return False
        
        # 测试合并事件
        print("\n2. 测试合并事件...")
        try:
            auto_timeline.merge_events()
            print(f"✓ 合并成功，合并事件数量: {len(auto_timeline.timeline_widget.merged_events)}")
            
            for i, event in enumerate(auto_timeline.timeline_widget.merged_events, 1):
                print(f"\n  合并事件 {i}:")
                print(f"    名称: {event.name}")
                print(f"    设备: {event.device}")
                print(f"    时间范围数量: {len(event.time_ranges)}")
                for j, (start, end) in enumerate(event.time_ranges, 1):
                    print(f"      时间范围 {j}: {start} 到 {end}")
                    
        except Exception as e:
            print(f"✗ 合并事件失败: {e}")
            return False
        
        # 测试get_videos_in_selected_ranges方法
        print("\n3. 测试get_videos_in_selected_ranges方法...")
        try:
            # 添加一个选中范围
            start_time = datetime.datetime(2025, 12, 30, 14, 36, 0)
            end_time = datetime.datetime(2025, 12, 30, 14, 38, 0)
            auto_timeline.timeline_widget.selected_ranges.append((start_time, end_time))
            
            # 调用方法获取结果
            videos, selected_events = auto_timeline.timeline_widget.get_videos_in_selected_ranges()
            
            print(f"✓ 方法调用成功")
            print(f"  返回的视频数量: {len(videos)}")
            print(f"  返回的选中事件数量: {len(selected_events)}")
            
            # 检查视频列表为空
            assert len(videos) == 0, "不应该返回任何视频路径"
            
            # 检查选中事件是否正确
            for i, event in enumerate(selected_events, 1):
                print(f"\n  选中事件 {i}:")
                print(f"    名称: {event['name']}")
                print(f"    设备: {event['device']}")
                print(f"    开始时间: {event['start_time']}")
                print(f"    结束时间: {event['end_time']}")
                print(f"    视频数量: {len(event['videos'])}")
                
                # 验证事件信息正确
                assert event['videos'] == [], f"事件 {i} 不应该有视频路径"
                
        except Exception as e:
            print(f"✗ get_videos_in_selected_ranges失败: {e}")
            return False
        
        print("\n✓ 所有测试通过！")
        return True
        
    finally:
        # 清理临时文件
        if os.path.exists(temp_csv_path):
            os.unlink(temp_csv_path)
        
        # 退出QApplication
        app.quit()


if __name__ == "__main__":
    test_missing_video_path_csv()
