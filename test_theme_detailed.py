#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试脚本：详细分析主题设置窗口问题
"""

import sys
import os
import time

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QApplication, QDialog, QVBoxLayout

# 在创建QApplication之前设置Qt属性
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)

# 创建应用程序实例
app = QApplication(sys.argv)

# 设置全局属性
app.dpi_scale_factor = 1.0
app.default_font_size = 9

# 导入设置管理器
from freeassetfilter.core.settings_manager import SettingsManager
# 先初始化SettingsManager（模拟main.py中的初始化）
print("预先初始化 SettingsManager...")
settings_manager = SettingsManager()
print("SettingsManager 初始化完成")
app.settings_manager = settings_manager

# 导入主题编辑器
from freeassetfilter.components.theme_editor import ThemeEditor

def test_theme_editor():
    """测试ThemeEditor创建过程"""
    print("=" * 60)
    print("开始测试 ThemeEditor 创建过程")
    print("=" * 60)

    start_time = time.time()

    print("步骤1: 创建 ThemeEditor 实例...")
    editor = ThemeEditor()
    step1_time = time.time()
    print(f"  完成，耗时: {(step1_time - start_time)*1000:.2f}ms")

    print("步骤2: 创建 QDialog...")
    dialog = QDialog()
    dialog.setWindowTitle("主题设置")
    dialog.resize(450, 350)
    step2_time = time.time()
    print(f"  完成，耗时: {(step2_time - step1_time)*1000:.2f}ms")

    print("步骤3: 创建布局...")
    layout = QVBoxLayout(dialog)
    step3_time = time.time()
    print(f"  完成，耗时: {(step3_time - step2_time)*1000:.2f}ms")

    print("步骤4: 将 ThemeEditor 添加到布局...")
    layout.addWidget(editor)
    step4_time = time.time()
    print(f"  完成，耗时: {(step4_time - step3_time)*1000:.2f}ms")

    print("步骤5: 显示对话框...")
    dialog.show()
    step5_time = time.time()
    print(f"  完成，耗时: {(step5_time - step4_time)*1000:.2f}ms")

    print("步骤6: 处理待处理的事件...")
    app.processEvents()
    step6_time = time.time()
    print(f"  完成，耗时: {(step6_time - step5_time)*1000:.2f}ms")

    total_time = step6_time - start_time
    print("=" * 60)
    print(f"总耗时: {total_time*1000:.2f}ms")
    print("=" * 60)

    # 检查editor的状态
    print(f"\n检查 editor 状态:")
    print(f"  viewport().width(): {editor.viewport().width()}")
    print(f"  _layout_initialized: {editor._layout_initialized}")
    print(f"  _update_retry_count: {editor._update_retry_count}")

    # 设置一个超时定时器，5秒后关闭对话框
    def close_dialog():
        print("\n超时，关闭对话框...")
        dialog.close()
        app.quit()

    QTimer.singleShot(5000, close_dialog)

    # 进入事件循环
    print("\n进入事件循环...")
    app.exec_()

    print("\n测试完成")

if __name__ == "__main__":
    test_theme_editor()
