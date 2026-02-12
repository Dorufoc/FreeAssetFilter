#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主题配置诊断工具
输出当前应用的主题配置以及获取到的setting的dark状态
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

print("=" * 70)
print("主题配置诊断")
print("=" * 70)

# 模拟settings_manager
class MockSettingsManager:
    def __init__(self, theme="light"):  # 改为light模式测试
        self._theme = theme
    
    def get_setting(self, key, default=None):
        if key == "general.theme":
            return self._theme
        return default

# 先创建QApplication
from PySide6.QtWidgets import QApplication
app = QApplication.instance()
if not app:
    app = QApplication(sys.argv)
    print("(已创建QApplication实例)")

# 附加模拟的settings_manager (light模式)
app.settings_manager = MockSettingsManager("light")
print("(已附加模拟settings_manager: light模式)")

# 1. 检查QApplication和settings_manager
print("\n【1. 应用设置检查】")
try:
    print("  QApplication: 已创建")
    
    if hasattr(app, 'settings_manager'):
        sm = app.settings_manager
        print("  settings_manager: 已存在")
        
        # 获取主题设置
        theme = sm.get_setting("general.theme", "未设置")
        print(f"  general.theme: {theme}")
        
        is_dark = theme == "dark"
        print(f"  is_dark: {is_dark}")
    else:
        print("  settings_manager: 不存在")
        print("  (使用默认设置: dark模式)")
except Exception as e:
    print(f"  错误: {e}")

# 2. 检查语法高亮器配置
print("\n【2. 语法高亮器配置】")
try:
    from freeassetfilter.utils.syntax_highlighter import (
        is_dark_mode, get_auto_theme_scheme, SYNTECT_AVAILABLE, PYGMENTS_AVAILABLE
    )
    
    print(f"  SYNTECT_AVAILABLE: {SYNTECT_AVAILABLE}")
    print(f"  PYGMENTS_AVAILABLE: {PYGMENTS_AVAILABLE}")
    
    # 检测暗色模式
    dark_mode = is_dark_mode()
    print(f"  is_dark_mode(): {dark_mode}")
    
    # 获取自动配色方案
    color_scheme = get_auto_theme_scheme()
    print(f"  get_auto_theme_scheme():")
    print(f"    名称: {color_scheme.name}")
    print(f"    背景色: {color_scheme.background}")
    print(f"    前景色: {color_scheme.foreground}")
    
except Exception as e:
    print(f"  错误: {e}")
    import traceback
    traceback.print_exc()

# 3. 检查TextPreviewWidget配置
print("\n【3. 文本预览器配置】")
try:
    from freeassetfilter.components.text_previewer import TextPreviewWidget
    
    # 创建预览器实例
    previewer = TextPreviewWidget()
    
    # 检查高亮器
    if hasattr(previewer, 'faf_highlighter') and previewer.faf_highlighter:
        highlighter = previewer.faf_highlighter
        print(f"  高亮器已创建")
        print(f"    配色方案: {highlighter.color_scheme.name}")
        print(f"    背景色: {highlighter.color_scheme.background}")
        print(f"    前景色: {highlighter.color_scheme.foreground}")
        
        # 检查引擎
        if hasattr(highlighter, '_engine') and highlighter._engine:
            engine_name = type(highlighter._engine).__name__
            print(f"    使用引擎: {engine_name}")
        else:
            print(f"    使用引擎: 无")
    else:
        print("  高亮器: 未创建")
        
except Exception as e:
    print(f"  错误: {e}")
    import traceback
    traceback.print_exc()

# 4. 检查所有可用配色方案
print("\n【4. 可用配色方案】")
try:
    from freeassetfilter.utils.syntax_highlighter import ColorSchemes
    
    schemes = [
        ("github_dark", ColorSchemes.github_dark()),
        ("github_light", ColorSchemes.github_light()),
        ("vscode_dark", ColorSchemes.vscode_dark()),
        ("vscode_light", ColorSchemes.vscode_light()),
        ("base16_ocean_dark", ColorSchemes.base16_ocean_dark()),
        ("base16_ocean_light", ColorSchemes.base16_ocean_light()),
    ]
    
    for name, scheme in schemes:
        print(f"  {name}:")
        print(f"    背景: {scheme.background}, 前景: {scheme.foreground}")
        
except Exception as e:
    print(f"  错误: {e}")

# 5. 检查语法文件加载情况
print("\n【5. 语法文件加载情况】")
try:
    from pathlib import Path
    from freeassetfilter.utils.syntax_highlighter import SyntaxHighlighter
    
    syntax_dir = SyntaxHighlighter.DEFAULT_SYNTAX_DIR
    print(f"  语法目录: {syntax_dir}")
    print(f"  目录存在: {syntax_dir.exists()}")
    
    if syntax_dir.exists():
        tm_files = list(syntax_dir.glob("*.tmLanguage.json"))
        print(f"  .tmLanguage.json 文件数: {len(tm_files)}")
        
except Exception as e:
    print(f"  错误: {e}")

print("\n" + "=" * 70)
print("诊断完成")
print("=" * 70)
