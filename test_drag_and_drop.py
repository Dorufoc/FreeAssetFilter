#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试文件拖拽功能
"""

import sys
import os
import tempfile
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, QPushButton
from PyQt5.QtCore import Qt, QMimeData, QUrl
from PyQt5.QtGui import QDragEnterEvent, QDropEvent

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from freeassetfilter.components.file_selector import CustomFileSelector
from freeassetfilter.components.file_staging_pool import FileStagingPool

class TestWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("拖拽功能测试")
        self.setGeometry(100, 100, 1200, 600)
        
        # 创建主部件和布局
        central_widget = QWidget()
        main_layout = QHBoxLayout(central_widget)
        
        # 创建左侧文件选择器
        self.file_selector = CustomFileSelector()
        main_layout.addWidget(self.file_selector, 1)
        
        # 创建右侧文件暂存池
        self.staging_pool = FileStagingPool()
        main_layout.addWidget(self.staging_pool, 1)
        
        # 连接信号
        self.file_selector.file_selection_changed.connect(self.on_file_selection_changed)
        self.staging_pool.remove_from_selector.connect(self.on_remove_from_selector)
        
        # 设置中心部件
        self.setCentralWidget(central_widget)
        
        # 创建测试按钮布局
        button_widget = QWidget()
        button_layout = QVBoxLayout(button_widget)
        
        # 创建测试按钮
        test_drag_btn = QPushButton("测试拖拽文件")
        test_drag_btn.clicked.connect(self.test_drag_file)
        button_layout.addWidget(test_drag_btn)
        
        test_duplicate_btn = QPushButton("测试重复添加")
        test_duplicate_btn.clicked.connect(self.test_duplicate_add)
        button_layout.addWidget(test_duplicate_btn)
        
        main_layout.addWidget(button_widget, 0)
        
        # 创建临时测试文件
        self.temp_files = []
        self.create_temp_files()
    
    def create_temp_files(self):
        """创建临时测试文件"""
        for i in range(3):
            temp_file = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
            temp_file.write(f"测试文件 {i+1}".encode())
            temp_file.close()
            self.temp_files.append(temp_file.name)
        
        print(f"创建临时测试文件: {self.temp_files}")
    
    def test_drag_file(self):
        """测试拖拽文件到文件选择器"""
        if not self.temp_files:
            print("没有临时文件可用")
            return
        
        # 获取第一个临时文件路径
        file_path = self.temp_files[0]
        
        # 模拟拖拽文件
        self.simulate_drag_drop(file_path)
        
        print(f"测试拖拽文件: {file_path}")
    
    def test_duplicate_add(self):
        """测试重复添加文件到储存池"""
        if not self.temp_files:
            print("没有临时文件可用")
            return
        
        # 获取第一个临时文件路径
        file_path = self.temp_files[0]
        
        # 模拟拖拽文件两次
        self.simulate_drag_drop(file_path)
        self.simulate_drag_drop(file_path)
        
        print(f"测试重复添加文件: {file_path}")
    
    def simulate_drag_drop(self, file_path):
        """模拟拖拽文件到文件选择器"""
        # 1. 创建拖拽事件
        mime_data = QMimeData()
        url = QUrl.fromLocalFile(file_path)
        mime_data.setUrls([url])
        
        # 2. 创建拖放事件
        drop_event = QDropEvent(
            self.file_selector.rect().center(),  # 位置
            Qt.CopyAction | Qt.MoveAction,  # 操作
            mime_data,  # MIME数据
            Qt.LeftButton,  # 按钮
            Qt.NoModifier  # 修饰键
        )
        
        # 3. 调用文件选择器的dropEvent方法
        self.file_selector.dropEvent(drop_event)
    
    def on_file_selection_changed(self, file_info, is_selected):
        """处理文件选择状态变化"""
        if is_selected:
            self.staging_pool.add_file(file_info)
        else:
            self.staging_pool.remove_file(file_info['path'])
    
    def on_remove_from_selector(self, file_info):
        """处理从选择器中移除文件"""
        file_path = file_info['path']
        file_dir = os.path.dirname(file_path)
        
        if file_dir in self.file_selector.selected_files:
            self.file_selector.selected_files[file_dir].discard(file_path)
            
            if not self.file_selector.selected_files[file_dir]:
                del self.file_selector.selected_files[file_dir]
        
        self.file_selector._update_file_selection_state()
    
    def closeEvent(self, event):
        """窗口关闭时清理临时文件"""
        for temp_file in self.temp_files:
            if os.path.exists(temp_file):
                os.unlink(temp_file)
                print(f"删除临时文件: {temp_file}")
        
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # 初始化设置管理器
    from freeassetfilter.core.settings_manager import SettingsManager
    app.settings_manager = SettingsManager()
    
    window = TestWindow()
    window.show()
    sys.exit(app.exec_())
