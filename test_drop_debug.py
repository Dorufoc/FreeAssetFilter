#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
直接调试dropEvent方法
"""

import sys
import os
import tempfile
import datetime

# 设置Qt属性以避免QtWebEngine错误
from PyQt5.QtCore import Qt, QCoreApplication
QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)

# 创建应用实例
from PyQt5.QtWidgets import QApplication
app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)

# 初始化设置管理器
from freeassetfilter.core.settings_manager import SettingsManager
app.settings_manager = SettingsManager()

# 现在导入组件
from freeassetfilter.components.file_selector import CustomFileSelector

def debug(msg):
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    print(f"[{timestamp}] [DEBUG] {msg}")

def test_drop_event_direct():
    """直接测试dropEvent方法"""
    debug("=== 直接测试dropEvent方法 ===")
    
    # 创建临时文件
    temp_file = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
    temp_file.write(b"test file content")
    temp_file.close()
    file_path = temp_file.name
    file_dir = os.path.dirname(file_path)
    debug(f"创建临时文件: {file_path}")
    debug(f"文件目录: {file_dir}")
    
    # 创建文件选择器
    file_selector = CustomFileSelector()
    
    # 记录初始状态
    debug(f"初始selected_files: {file_selector.selected_files}")
    debug(f"初始current_path: {file_selector.current_path}")
    
    # 模拟拖拽文件到文件选择器
    debug(f"模拟拖拽文件: {file_path}")
    
    # 创建拖拽事件
    from PyQt5.QtCore import QMimeData, QUrl
    from PyQt5.QtGui import QDropEvent
    
    mime_data = QMimeData()
    url = QUrl.fromLocalFile(file_path)
    mime_data.setUrls([url])
    
    # 创建拖放事件
    drop_event = QDropEvent(
        file_selector.rect().center(),
        Qt.CopyAction | Qt.MoveAction,
        mime_data,
        Qt.LeftButton,
        Qt.NoModifier
    )
    
    # 调用dropEvent
    debug("调用file_selector.dropEvent()")
    try:
        file_selector.dropEvent(drop_event)
        debug("dropEvent调用完成，无异常")
    except Exception as e:
        debug(f"dropEvent调用抛出异常: {e}")
        import traceback
        traceback.print_exc()
    
    # 立即检查状态
    debug(f"调用后立即检查selected_files: {file_selector.selected_files}")
    
    # 检查文件是否在selected_files中
    file_in_selected = False
    if file_dir in file_selector.selected_files:
        debug(f"文件目录 {file_dir} 在selected_files中")
        debug(f"selected_files[{file_dir}]: {file_selector.selected_files[file_dir]}")
        file_in_selected = file_path in file_selector.selected_files[file_dir]
        debug(f"文件 {file_path} 是否在selected_files[{file_dir}]中: {file_in_selected}")
    else:
        debug(f"文件目录 {file_dir} 不在selected_files中")
    
    # 检查current_path是否已设置
    debug(f"最终current_path: {file_selector.current_path}")
    
    # 检查是否有回调函数被设置
    debug(f"_refresh_callback: {file_selector._refresh_callback}")
    
    # 等待异步操作完成
    import time
    for i in range(5):
        app.processEvents()
        time.sleep(0.1)
        debug(f"等待异步操作 {i+1}/5...")
    
    # 再次检查状态
    debug(f"等待后selected_files: {file_selector.selected_files}")
    
    # 清理
    os.unlink(file_path)
    debug(f"删除临时文件: {file_path}")
    
    return file_in_selected

if __name__ == "__main__":
    debug("开始直接测试")
    success = test_drop_event_direct()
    debug(f"测试完成: 文件是否在selected_files中: {success}")
    sys.exit(0 if success else 1)