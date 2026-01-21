#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
最小化拖拽测试
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
from freeassetfilter.components.file_staging_pool import FileStagingPool

def debug(msg):
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    print(f"[{timestamp}] [测试] {msg}")

def test_drag_drop():
    """测试拖拽文件"""
    debug("=== 开始拖拽测试 ===")
    
    # 创建临时文件
    temp_file = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
    temp_file.write(b"test file content")
    temp_file.close()
    file_path = temp_file.name
    file_dir = os.path.dirname(file_path)
    debug(f"创建临时文件: {file_path}")
    debug(f"文件目录: {file_dir}")
    
    # 创建文件选择器和储存池
    file_selector = CustomFileSelector()
    staging_pool = FileStagingPool()
    
    # 跟踪信号
    signals_received = []
    
    def on_selection_changed(file_info, is_selected):
        debug(f"信号: file_selection_changed(文件={file_info['path']}, 选中={is_selected})")
        signals_received.append(('file_selection_changed', file_info['path'], is_selected))
        if is_selected:
            staging_pool.add_file(file_info)
    
    def on_added_to_pool(file_info):
        debug(f"信号: file_added_to_pool(文件={file_info['path']})")
        signals_received.append(('file_added_to_pool', file_info['path']))
    
    # 连接信号
    file_selector.file_selection_changed.connect(on_selection_changed)
    staging_pool.file_added_to_pool.connect(on_added_to_pool)
    
    # 记录初始状态
    debug(f"初始selected_files: {file_selector.selected_files}")
    
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
    file_selector.dropEvent(drop_event)
    
    # 处理事件队列，等待异步操作
    import time
    for i in range(10):  # 最多等待1秒
        app.processEvents()
        time.sleep(0.1)
        if len(signals_received) >= 2:  # 收到两个信号
            break
    
    # 检查结果
    debug(f"最终selected_files: {file_selector.selected_files}")
    is_selected = file_dir in file_selector.selected_files and file_path in file_selector.selected_files[file_dir]
    debug(f"文件是否选中: {is_selected}")
    
    # 检查储存池
    debug(f"储存池项目数量: {len(staging_pool.items)}")
    
    # 检查信号
    debug(f"收到的信号: {signals_received}")
    
    # 检查UI状态：模拟调用_update_file_selection_state
    debug("调用_update_file_selection_state检查UI状态")
    file_selector._update_file_selection_state()
    
    # 清理
    os.unlink(file_path)
    debug(f"删除临时文件: {file_path}")
    
    # 验证结果
    success = is_selected and len(staging_pool.items) > 0
    debug(f"测试结果: {'成功' if success else '失败'}")
    
    if not success:
        debug("详细诊断:")
        debug(f"  - 文件在selected_files中: {is_selected}")
        debug(f"  - 储存池有项目: {len(staging_pool.items) > 0}")
        debug(f"  - 收到的信号数量: {len(signals_received)}")
        for sig in signals_received:
            debug(f"    - {sig}")
    
    return success

if __name__ == "__main__":
    debug("开始最小化测试")
    success = test_drag_drop()
    debug(f"测试完成: {'成功' if success else '失败'}")
    sys.exit(0 if success else 1)