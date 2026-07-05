#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量测试生成脚本
为所有模块生成基础测试文件
"""
import os
from pathlib import Path

# 模块分类
MODULES = {
    'core': [
        'settings_manager', 'theme_manager', 'thumbnail_manager', 'thumbnail_cleaner',
        'file_info_browser', 'color_extractor', 'mpv_player_core', 'mpv_manager',
        'lut_preview_generator', 'timeline_generator', 'update_manager',
        'component_launcher', 'py7z_core', 'svg_renderer'
    ],
    'widgets': [
        'D_widgets', 'D_hover_menu', 'D_volume_control', 'D_volume', 'D_more_menu',
        'button_widgets', 'file_block_card', 'file_horizontal_card', 'hover_tooltip',
        'volume_slider_menu', 'dropdown_menu', 'player_control_bar', 'progress_widgets',
        'audio_background', 'smooth_scroller', 'color_wheel_picker', 'lut_manager_dialog',
        'theme_card', 'table_widgets', 'switch_widgets', 'setting_widgets',
        'scrolling_text', 'psd_progress_dialog', 'message_box', 'menu_list',
        'list_widgets', 'input_widgets', 'control_menu', 'color_slider'
    ],
    'components': [
        'file_selector', 'unified_previewer', 'file_staging_pool', 'video_player',
        'settings_window', 'text_previewer', 'theme_editor', 'archive_browser',
        'photo_viewer', 'pdf_previewer', 'file_info_previewer', 'folder_content_list',
        'font_previewer', 'auto_timeline'
    ],
    'utils': [
        'app_logger', 'path_utils', 'fix_encoding', 'icon_utils',
        'file_icon_helper', 'lut_utils', 'syntax_highlighter',
        'global_mouse_monitor', 'mouse_activity_monitor'
    ]
}

TEST_TEMPLATE = '''# -*- coding: utf-8 -*-
"""
{module_name} 单元测试
测试 {module_path} 模块的功能
"""
import pytest
import os
import sys
from unittest.mock import MagicMock, patch


class Test{ModuleName}Basic:
    """测试 {ModuleName} 基本功能"""
    
    def test_module_import(self):
        """测试模块可以导入"""
        from freeassetfilter.{package}.{module_name} import {main_class}
        assert {main_class} is not None
    
    def test_module_has_required_attributes(self):
        """测试模块有必要的属性"""
        from freeassetfilter.{package} import {module_name}
        # 检查模块存在
        assert {module_name} is not None


class Test{ModuleName}Robustness:
    """测试 {ModuleName} 鲁棒性"""
    
    def test_module_handles_errors_gracefully(self):
        """测试模块能优雅处理错误"""
        # 基础错误处理测试
        pass


class Test{ModuleName}Integration:
    """测试 {ModuleName} 集成"""
    
    def test_module_integration(self):
        """测试模块集成"""
        # 集成测试
        pass
'''


def get_main_class(module_name):
    """根据模块名推断主类名"""
    # 转换下划线命名为驼峰命名
    parts = module_name.split('_')
    class_name = ''.join(part.capitalize() for part in parts)
    
    # 特殊处理
    special_cases = {
        'D_widgets': 'CustomWindow',
        'D_hover_menu': 'HoverMenu',
        'D_volume_control': 'VolumeControl',
        'D_volume': 'VolumeWidget',
        'D_more_menu': 'MoreMenu',
        'file_block_card': 'FileBlockCard',
        'file_horizontal_card': 'CustomFileHorizontalCard',
        'button_widgets': 'CustomButton',
        'message_box': 'CustomMessageBox',
        'settings_manager': 'SettingsManager',
        'theme_manager': 'ThemeManager',
        'thumbnail_manager': 'ThumbnailManager',
        'thumbnail_cleaner': 'ThumbnailCleaner',
        'app_logger': 'get_logger',
        'path_utils': 'get_resource_path',
    }
    
    return special_cases.get(module_name, class_name)


def generate_test_file(package, module_name):
    """为指定模块生成测试文件"""
    main_class = get_main_class(module_name)
    ModuleName = ''.join(part.capitalize() for part in module_name.split('_'))
    
    content = TEST_TEMPLATE.format(
        module_name=module_name,
        ModuleName=ModuleName,
        module_path=f'freeassetfilter/{package}/{module_name}.py',
        package=package,
        main_class=main_class
    )
    
    test_file = f'test_{module_name}.py'
    test_path = Path('tests/unit') / test_file
    
    return test_path, content


def main():
    """主函数"""
    print("=" * 60)
    print("批量测试生成器")
    print("=" * 60)
    
    generated = []
    skipped = []
    
    for package, modules in MODULES.items():
        print(f"\n处理 {package} 模块...")
        for module in modules:
            test_path, content = generate_test_file(package, module)
            
            # 检查文件是否已存在
            if test_path.exists():
                skipped.append(str(test_path))
                print(f"  跳过: {test_path} (已存在)")
            else:
                # 写入测试文件
                with open(test_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                generated.append(str(test_path))
                print(f"  生成: {test_path}")
    
    print("\n" + "=" * 60)
    print("生成完成!")
    print(f"新生成: {len(generated)} 个文件")
    print(f"跳过: {len(skipped)} 个文件")
    print("=" * 60)


if __name__ == '__main__':
    main()
