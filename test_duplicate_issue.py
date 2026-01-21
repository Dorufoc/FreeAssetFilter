#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试重复添加问题
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
    print(f"[{timestamp}] [重复添加测试] {msg}")

def test_duplicate_issue():
    """测试重复添加问题"""
    debug("=== 开始重复添加测试 ===")
    
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
    debug(f"初始储存池项目数: {len(staging_pool.items)}")
    
    # 第一次拖拽文件到文件选择器
    debug(f"第一次拖拽文件: {file_path}")
    
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
    
    # 第一次调用dropEvent
    debug("第一次调用file_selector.dropEvent()")
    file_selector.dropEvent(drop_event)
    
    # 等待异步操作
    import time
    for i in range(5):  # 最多等待0.5秒
        app.processEvents()
        time.sleep(0.1)
    
    debug(f"第一次操作后 - selected_files: {file_selector.selected_files}")
    debug(f"第一次操作后 - 储存池项目数: {len(staging_pool.items)}")
    debug(f"第一次操作后 - 收到信号数: {len(signals_received)}")
    
    # 第二次拖拽同一个文件（模拟重复添加）
    debug(f"第二次拖拽同一个文件: {file_path}")
    
    # 创建第二个拖拽事件
    mime_data2 = QMimeData()
    url2 = QUrl.fromLocalFile(file_path)
    mime_data2.setUrls([url2])
    
    # 创建第二个拖放事件
    drop_event2 = QDropEvent(
        file_selector.rect().center(),
        Qt.CopyAction | Qt.MoveAction,
        mime_data2,
        Qt.LeftButton,
        Qt.NoModifier
    )
    
    # 第二次调用dropEvent
    debug("第二次调用file_selector.dropEvent()（测试重复添加）")
    file_selector.dropEvent(drop_event2)
    
    # 等待异步操作
    for i in range(5):  # 最多等待0.5秒
        app.processEvents()
        time.sleep(0.1)
    
    debug(f"第二次操作后 - selected_files: {file_selector.selected_files}")
    debug(f"第二次操作后 - 储存池项目数: {len(staging_pool.items)}")
    debug(f"第二次操作后 - 收到信号数: {len(signals_received)}")
    
    # 检查是否重复添加
    expected_items = 1  # 应该只有一个项目
    actual_items = len(staging_pool.items)
    duplicate_detected = actual_items > expected_items
    
    debug(f"预期项目数: {expected_items}")
    debug(f"实际项目数: {actual_items}")
    debug(f"是否检测到重复添加: {duplicate_detected}")
    
    # 检查信号
    debug(f"收到的信号: {signals_received}")
    
    # 统计每个类型的信号数量
    sel_changes = sum(1 for sig in signals_received if sig[0] == 'file_selection_changed')
    pool_adds = sum(1 for sig in signals_received if sig[0] == 'file_added_to_pool')
    debug(f"file_selection_changed 信号数: {sel_changes}")
    debug(f"file_added_to_pool 信号数: {pool_adds}")
    
    # 清理
    os.unlink(file_path)
    debug(f"删除临时文件: {file_path}")
    
    # 如果检测到重复添加则返回失败
    success = not duplicate_detected and actual_items == 1
    debug(f"测试结果: {'成功' if success else '失败'}")
    
    return success

if __name__ == "__main__":
    debug("开始重复添加测试")
    success = test_duplicate_issue()
    debug(f"测试完成: {'成功' if success else '失败'}")
    sys.exit(0 if success else 1)