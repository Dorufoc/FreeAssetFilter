#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试文件选择器和文件暂存池的交互功能
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
        self.setWindowTitle("文件选择器和暂存池交互测试")
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
        self.staging_pool.file_added_to_pool.connect(self.on_file_added_to_pool)
        self.staging_pool.navigate_to_path.connect(self.on_navigate_to_path)
        
        # 设置中心部件
        self.setCentralWidget(central_widget)
        
        # 创建测试按钮布局
        button_widget = QWidget()
        button_layout = QVBoxLayout(button_widget)
        
        # 创建测试按钮
        test_drag_btn = QPushButton("测试拖拽文件到暂存池")
        test_drag_btn.clicked.connect(self.test_drag_to_pool)
        button_layout.addWidget(test_drag_btn)
        
        test_right_click_btn = QPushButton("模拟右键菜单取消暂存")
        test_right_click_btn.clicked.connect(self.test_right_click_cancel)
        button_layout.addWidget(test_right_click_btn)
        
        main_layout.addWidget(button_widget, 0)
        
        # 创建临时测试文件
        self.temp_files = []
        self.create_temp_files()
        
        # 保存当前测试的文件路径
        self.current_test_file = None
    
    def create_temp_files(self):
        """创建临时测试文件"""
        for i in range(3):
            temp_file = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
            temp_file.write(f"测试文件 {i+1}".encode())
            temp_file.close()
            self.temp_files.append(temp_file.name)
        
        print(f"创建临时测试文件: {self.temp_files}")
    
    def test_drag_to_pool(self):
        """测试拖拽文件到文件暂存池"""
        if not self.temp_files:
            print("没有临时文件可用")
            return
        
        # 获取第一个临时文件路径
        self.current_test_file = self.temp_files[0]
        
        # 模拟拖拽文件到文件暂存池
        self.simulate_drag_to_pool(self.current_test_file)
        
        print(f"测试拖拽文件到暂存池: {self.current_test_file}")
    
    def test_right_click_cancel(self):
        """测试从文件选择器右键菜单取消文件暂存"""
        if not self.current_test_file:
            print("请先测试拖拽文件到暂存池")
            return
        
        # 查找文件卡片
        file_path = self.current_test_file
        file_dir = os.path.dirname(file_path)
        
        # 确保文件选择器显示的是文件所在的目录
        if self.file_selector.current_path != file_dir:
            self.file_selector.current_path = file_dir
            self.file_selector.refresh_files()
        
        # 等待界面刷新完成
        QApplication.processEvents()
        
        # 查找文件卡片并模拟右键菜单操作
        for i in range(self.file_selector.files_layout.count()):
            widget = self.file_selector.files_layout.itemAt(i).widget()
            if widget and hasattr(widget, 'file_info') and widget.file_info['path'] == file_path:
                print(f"找到文件卡片: {file_path}")
                # 调用移除方法
                self.file_selector._remove_from_staging_pool(widget)
                print("模拟右键菜单取消暂存完成")
                return
        
        print(f"未找到文件卡片: {file_path}")
    
    def simulate_drag_to_pool(self, file_path):
        """模拟拖拽文件到文件暂存池"""
        # 1. 创建拖拽事件
        mime_data = QMimeData()
        url = QUrl.fromLocalFile(file_path)
        mime_data.setUrls([url])
        
        # 2. 创建拖放事件
        drop_event = QDropEvent(
            self.staging_pool.rect().center(),  # 位置
            Qt.CopyAction | Qt.MoveAction,  # 操作
            mime_data,  # MIME数据
            Qt.LeftButton,  # 按钮
            Qt.NoModifier  # 修饰键
        )
        
        # 3. 调用文件暂存池的dropEvent方法
        self.staging_pool.dropEvent(drop_event)
    
    def on_file_selection_changed(self, file_info, is_selected):
        """处理文件选择状态变化"""
        if is_selected:
            self.staging_pool.add_file(file_info)
            print(f"文件添加到暂存池: {file_info['path']}")
        else:
            self.staging_pool.remove_file(file_info['path'])
            print(f"文件从暂存池移除: {file_info['path']}")
    
    def on_remove_from_selector(self, file_info):
        """处理从选择器中移除文件"""
        file_path = file_info['path']
        file_dir = os.path.dirname(file_path)
        
        if file_dir in self.file_selector.selected_files:
            self.file_selector.selected_files[file_dir].discard(file_path)
            
            if not self.file_selector.selected_files[file_dir]:
                del self.file_selector.selected_files[file_dir]
        
        self.file_selector._update_file_selection_state()
        print(f"从文件选择器中移除文件: {file_path}")
    
    def on_file_added_to_pool(self, file_info):
        """处理文件被添加到储存池的事件"""
        file_path = file_info['path']
        print(f"文件已添加到储存池: {file_path}")
    
    def on_navigate_to_path(self, path):
        """处理导航到指定路径的请求"""
        self.file_selector.current_path = path
        self.file_selector.refresh_files()
        print(f"导航到路径: {path}")
    
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
