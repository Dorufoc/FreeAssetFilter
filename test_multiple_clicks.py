#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试多次点击卡片是否会重复添加到储存池
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
    print(f"[{timestamp}] [多次点击测试] {msg}")

def test_multiple_clicks():
    """测试多次点击卡片是否会重复添加"""
    debug("=== 开始多次点击测试 ===")
    
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
    
    # 设置文件选择器到包含临时文件的目录
    file_selector.current_path = file_dir
    file_selector.refresh_files()
    
    # 等待UI刷新
    import time
    for i in range(3):  # 等待0.3秒
        app.processEvents()
        time.sleep(0.1)
    
    # 查找临时文件对应的卡片
    temp_card = None
    for i in range(file_selector.files_layout.count()):
        widget = file_selector.files_layout.itemAt(i).widget()
        if widget and hasattr(widget, 'file_info') and widget.file_info['path'] == file_path:
            temp_card = widget
            break
    
    if temp_card is None:
        debug("错误: 未找到临时文件对应的卡片")
        os.unlink(file_path)
        return False
    
    debug(f"找到临时文件卡片: {temp_card.file_info['path']}")
    
    # 第一次点击卡片
    debug("第一次点击卡片")
    temp_card.toggle_selection()
    
    # 等待异步操作
    for i in range(3):  # 等待0.3秒
        app.processEvents()
        time.sleep(0.1)
    
    debug(f"第一次点击后 - 储存池项目数: {len(staging_pool.items)}")
    debug(f"第一次点击后 - 收到信号数: {len(signals_received)}")
    
    # 第二次点击卡片（取消选中）
    debug("第二次点击卡片（取消选中）")
    temp_card.toggle_selection()
    
    # 等待异步操作
    for i in range(3):  # 等待0.3秒
        app.processEvents()
        time.sleep(0.1)
    
    debug(f"第二次点击后 - 储存池项目数: {len(staging_pool.items)}")
    debug(f"第二次点击后 - 收到信号数: {len(signals_received)}")
    
    # 第三次点击卡片（重新选中）
    debug("第三次点击卡片（重新选中）")
    temp_card.toggle_selection()
    
    # 等待异步操作
    for i in range(3):  # 等待0.3秒
        app.processEvents()
        time.sleep(0.1)
    
    debug(f"第三次点击后 - 储存池项目数: {len(staging_pool.items)}")
    debug(f"第三次点击后 - 收到信号数: {len(signals_received)}")
    
    # 检查最终状态
    expected_items = 1  # 应该只有一个项目（即使多次点击，最终只保留一个选中状态）
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
    
    # 检查是否合理（点击三次可能产生多个信号，但最终项目数应该是1）
    success = actual_items <= 1  # 最终最多应该只有1个项目
    debug(f"测试结果: {'成功' if success else '失败'}")
    
    return success

if __name__ == "__main__":
    debug("开始多次点击测试")
    success = test_multiple_clicks()
    debug(f"测试完成: {'成功' if success else '失败'}")
    sys.exit(0 if success else 1)