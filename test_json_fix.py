#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试JSON模块导入修复
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

def test_json_import():
    """测试JSON模块是否能正常导入和使用"""
    print("测试JSON模块导入修复...")
    
    try:
        # 导入auto_timeline模块，这会触发json模块的导入
        from freeassetfilter.components.auto_timeline import AutoTimeline
        print("✓ auto_timeline模块导入成功")
        
        # 直接测试json模块
        import json
        print("✓ json模块直接导入成功")
        
        # 测试JSON功能
        test_data = {"test": "value", "number": 42}
        json_str = json.dumps(test_data)
        parsed_data = json.loads(json_str)
        
        assert parsed_data == test_data, "JSON序列化/反序列化失败"
        print("✓ JSON序列化/反序列化功能正常")
        
        print("\n🎉 JSON模块导入修复成功！")
        return True
        
    except Exception as e:
        print(f"\n❌ 测试失败：{str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_json_import()
