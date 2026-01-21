#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调试拖拽功能问题
"""

import sys
import os
import tempfile
import datetime
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, QPushButton, QLabel, QTextEdit
from PyQt5.QtCore import Qt, QMimeData, QUrl, pyqtSignal, QObject
from PyQt5.QtGui import QDragEnterEvent, QDropEvent

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from freeassetfilter.components.file_selector import CustomFileSelector
from freeassetfilter.components.file_staging_pool import FileStagingPool

class DebugLogger(QObject):
    """调试日志记录器"""
    log_signal = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.logs = []
    
    def log(self, message):
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        log_message = f"[{timestamp}] {message}"
        self.logs.append(log_message)
        self.log_signal.emit(log_message)
        print(log_message)

class TestDebugWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("拖拽功能调试")
        self.setGeometry(100, 100, 1400, 700)
        
        self.logger = DebugLogger()
        
        # 创建主部件和布局
        central_widget = QWidget()
        main_layout = QHBoxLayout(central_widget)
        
        # 左侧：控制面板和日志
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
        # 控制按钮
        control_widget = QWidget()
        control_layout = QVBoxLayout(control_widget)
        
        test_drag_btn = QPushButton("测试拖拽文件")
        test_drag_btn.clicked.connect(self.test_drag_file)
        control_layout.addWidget(test_drag_btn)
        
        test_duplicate_btn = QPushButton("测试重复添加")
        test_duplicate_btn.clicked.connect(self.test_duplicate_add)
        control_layout.addWidget(test_duplicate_btn)
        
        clear_logs_btn = QPushButton("清空日志")
        clear_logs_btn.clicked.connect(self.clear_logs)
        control_layout.addWidget(clear_logs_btn)
        
        left_layout.addWidget(control_widget)
        
        # 状态标签
        self.status_label = QLabel("就绪")
        left_layout.addWidget(self.status_label)
        
        # 日志显示
        log_label = QLabel("调试日志:")
        left_layout.addWidget(log_label)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(300)
        left_layout.addWidget(self.log_text)
        
        # 连接日志信号
        self.logger.log_signal.connect(self.append_log)
        
        # 中间：文件选择器
        self.file_selector = CustomFileSelector()
        
        # 右侧：文件暂存池
        self.staging_pool = FileStagingPool()
        
        # 添加到主布局
        main_layout.addWidget(left_widget, 1)
        main_layout.addWidget(self.file_selector, 2)
        main_layout.addWidget(self.staging_pool, 2)
        
        # 设置中心部件
        self.setCentralWidget(central_widget)
        
        # 连接信号
        self.file_selector.file_selection_changed.connect(self.on_file_selection_changed)
        self.staging_pool.remove_from_selector.connect(self.on_remove_from_selector)
        
        # 创建临时测试文件
        self.temp_files = []
        self.create_temp_files()
        
        # 监控计数器
        self.drag_count = 0
        self.add_count = 0
    
    def create_temp_files(self):
        """创建临时测试文件"""
        temp_dir = tempfile.mkdtemp()
        for i in range(3):
            file_path = os.path.join(temp_dir, f"test_file_{i+1}.txt")
            with open(file_path, 'w') as f:
                f.write(f"测试文件内容 {i+1}")
            self.temp_files.append(file_path)
        
        self.logger.log(f"创建临时测试文件: {self.temp_files}")
        self.logger.log(f"临时目录: {temp_dir}")
    
    def test_drag_file(self):
        """测试拖拽文件到文件选择器"""
        if not self.temp_files:
            self.logger.log("没有临时文件可用")
            return
        
        file_path = self.temp_files[0]
        self.logger.log(f"=== 开始拖拽测试 {self.drag_count+1} ===")
        self.logger.log(f"拖拽文件: {file_path}")
        
        # 记录拖拽前的状态
        file_dir = os.path.dirname(file_path)
        was_selected = file_dir in self.file_selector.selected_files and file_path in self.file_selector.selected_files[file_dir]
        self.logger.log(f"拖拽前选中状态: {was_selected}")
        self.logger.log(f"selected_files: {self.file_selector.selected_files}")
        
        # 模拟拖拽
        self.simulate_drag_drop(file_path)
        
        self.drag_count += 1
        self.update_status()
    
    def test_duplicate_add(self):
        """测试重复添加文件到储存池"""
        if not self.temp_files:
            self.logger.log("没有临时文件可用")
            return
        
        file_path = self.temp_files[0]
        self.logger.log(f"=== 测试重复添加 ===")
        self.logger.log(f"第一次拖拽:")
        self.simulate_drag_drop(file_path)
        
        self.logger.log(f"等待1秒...")
        QApplication.processEvents()  # 处理事件队列
        
        self.logger.log(f"第二次拖拽:")
        self.simulate_drag_drop(file_path)
        
        self.update_status()
    
    def simulate_drag_drop(self, file_path):
        """模拟拖拽文件到文件选择器"""
        # 创建拖拽事件
        mime_data = QMimeData()
        url = QUrl.fromLocalFile(file_path)
        mime_data.setUrls([url])
        
        # 创建拖放事件
        drop_event = QDropEvent(
            self.file_selector.rect().center(),
            Qt.CopyAction | Qt.MoveAction,
            mime_data,
            Qt.LeftButton,
            Qt.NoModifier
        )
        
        # 记录拖拽前状态
        file_dir = os.path.dirname(file_path)
        was_selected = file_dir in self.file_selector.selected_files and file_path in self.file_selector.selected_files[file_dir]
        self.logger.log(f"拖拽前: selected={was_selected}")
        
        # 调用文件选择器的dropEvent方法
        self.file_selector.dropEvent(drop_event)
        
        # 短暂延迟后检查状态
        QApplication.processEvents()
        
        # 记录拖拽后状态
        is_selected = file_dir in self.file_selector.selected_files and file_path in self.file_selector.selected_files[file_dir]
        self.logger.log(f"拖拽后: selected={is_selected}, UI刷新应显示选中状态")
    
    def on_file_selection_changed(self, file_info, is_selected):
        """处理文件选择状态变化"""
        self.logger.log(f"--- file_selection_changed信号 ---")
        self.logger.log(f"文件: {file_info['path']}")
        self.logger.log(f"选中: {is_selected}")
        
        if is_selected:
            self.staging_pool.add_file(file_info)
            self.add_count += 1
        else:
            self.staging_pool.remove_file(file_info['path'])
        
        self.update_status()
    
    def on_remove_from_selector(self, file_info):
        """处理从选择器中移除文件"""
        self.logger.log(f"--- remove_from_selector信号 ---")
        self.logger.log(f"文件: {file_info['path']}")
        
        file_path = file_info['path']
        file_dir = os.path.dirname(file_path)
        
        if file_dir in self.file_selector.selected_files:
            self.file_selector.selected_files[file_dir].discard(file_path)
            
            if not self.file_selector.selected_files[file_dir]:
                del self.file_selector.selected_files[file_dir]
        
        self.file_selector._update_file_selection_state()
        self.update_status()
    
    def append_log(self, message):
        """添加日志到文本框"""
        self.log_text.append(message)
        # 滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def clear_logs(self):
        """清空日志"""
        self.log_text.clear()
        self.logger.logs = []
        self.logger.log("日志已清空")
    
    def update_status(self):
        """更新状态标签"""
        status = f"拖拽次数: {self.drag_count}, 添加次数: {self.add_count}"
        self.status_label.setText(status)
    
    def closeEvent(self, event):
        """窗口关闭时清理临时文件"""
        import shutil
        for temp_file in self.temp_files:
            if os.path.exists(temp_file):
                os.unlink(temp_file)
                self.logger.log(f"删除临时文件: {temp_file}")
        
        # 删除临时目录
        temp_dir = os.path.dirname(self.temp_files[0])
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            self.logger.log(f"删除临时目录: {temp_dir}")
        
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # 初始化设置管理器
    from freeassetfilter.core.settings_manager import SettingsManager
    app.settings_manager = SettingsManager()
    
    window = TestDebugWindow()
    window.show()
    sys.exit(app.exec_())