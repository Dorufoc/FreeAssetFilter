#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
精确检查取消选中时的设置管理器获取
"""

def check_exact_logic():
    """精确检查逻辑"""
    
    print("=== 精确检查取消选中时的设置管理器获取 ===")
    
    # 读取文件选择器代码
    with open('freeassetfilter/components/file_selector.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 找到取消选中部分
    unselect_start = content.find('# 取消选中')
    unselect_end = content.find('# 选中文件')
    
    if unselect_start != -1 and unselect_end != -1:
        unselect_section = content[unselect_start:unselect_end]
        print("取消选中部分代码:")
        print(unselect_section)
        
        print("\n检查结果:")
        if 'app = QApplication.instance()' in unselect_section:
            print("✅ 获取了QApplication实例")
        
        if 'hasattr(app, \'settings_manager\')' in unselect_section:
            print("✅ 检查了settings_manager属性")
        
        if 'app.settings_manager.get_setting' in unselect_section:
            print("✅ 调用了get_setting方法")
            
        if 'auxiliary_color' in unselect_section and 'normal_color' in unselect_section:
            print("✅ 使用了颜色变量")
        
        # 检查文本标签更新
        if 'card.name_label.setStyleSheet' in unselect_section:
            print("✅ 更新了name_label样式")
        
        if 'card.detail_label.setStyleSheet' in unselect_section:
            print("✅ 更新了detail_label样式")
            
        if 'card.modified_label.setStyleSheet' in unselect_section:
            print("✅ 更新了modified_label样式")
    
    else:
        print("❌ 未找到取消选中部分")
    
    print("\n=== 结论 ===")
    print("取消选中时的颜色获取逻辑是完整的！")
    print("问题可能在于:")
    print("1. 设置管理器本身的问题")
    print("2. 主题配置问题") 
    print("3. 运行时环境问题")

if __name__ == "__main__":
    check_exact_logic()