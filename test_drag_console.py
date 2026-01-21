#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
控制台测试拖拽功能
"""

import sys
import os
import tempfile
import datetime

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

# 初始化Qt应用
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
    debug(f"创建临时文件: {file_path}")
    
    # 创建文件选择器和储存池
    file_selector = CustomFileSelector()
    staging_pool = FileStagingPool()
    
    # 连接信号
    file_selector.file_selection_changed.connect(lambda f, s: on_selection_changed(f, s, staging_pool))
    
    # 记录初始状态
    file_dir = os.path.dirname(file_path)
    debug(f"文件目录: {file_dir}")
    debug(f"初始selected_files: {file_selector.selected_files}")
    
    # 模拟拖拽文件到文件选择器
    debug(f"模拟拖拽文件: {file_path}")
    
    # 创建拖拽事件
    from PyQt5.QtCore import Qt, QMimeData, QUrl
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
    
    # 处理事件队列
    app.processEvents()
    
    # 短暂延迟，等待异步操作
    import time
    time.sleep(0.5)
    app.processEvents()
    
    # 检查结果
    debug(f"最终selected_files: {file_selector.selected_files}")
    is_selected = file_dir in file_selector.selected_files and file_path in file_selector.selected_files[file_dir]
    debug(f"文件是否选中: {is_selected}")
    
    # 检查储存池
    debug(f"储存池项目数量: {len(staging_pool.items)}")
    
    # 清理
    os.unlink(file_path)
    debug(f"删除临时文件: {file_path}")
    
    return is_selected and len(staging_pool.items) > 0

def on_selection_changed(file_info, is_selected, staging_pool):
    """选择状态变化处理"""
    debug(f"信号触发: file_selection_changed(文件={file_info['path']}, 选中={is_selected})")
    if is_selected:
        staging_pool.add_file(file_info)
        debug(f"添加到储存池: {file_info['path']}")
    else:
        staging_pool.remove_file(file_info['path'])
        debug(f"从储存池移除: {file_info['path']}")

if __name__ == "__main__":
    debug("开始控制台测试")
    success = test_drag_drop()
    debug(f"测试结果: {'成功' if success else '失败'}")
    sys.exit(0 if success else 1)