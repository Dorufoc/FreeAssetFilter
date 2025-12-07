#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

文件临时存储池组件
用于展示和管理从左侧素材区添加的文件/文件夹项目
"""

import os
import tempfile
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
    QScrollArea, QGroupBox, QListWidget, QListWidgetItem, 
    QSizePolicy, QCheckBox, QMessageBox, QMenu, QAction, QProgressBar, QFileDialog
)
from PyQt5.QtCore import (
    Qt, pyqtSignal, QFileInfo
)
from PyQt5.QtGui import QIcon, QColor, QPixmap, QFont

# 尝试导入PIL库，用于生成缩略图
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

class FileStagingPool(QWidget):
    """
    文件临时存储池组件
    用于展示和管理从左侧素材区添加的文件/文件夹项目
    """
    
    # 定义信号
    item_right_clicked = pyqtSignal(dict)  # 当项目被右键点击时发出
    remove_from_selector = pyqtSignal(dict)  # 当需要从选择器中移除文件时发出
    update_progress = pyqtSignal(int)  # 更新进度条信号
    export_finished = pyqtSignal(int, int, list)  # 导出完成信号
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 获取全局字体
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QFont
        app = QApplication.instance()
        self.global_font = getattr(app, 'global_font', QFont())
        print(f"[DEBUG] FileStagingPool获取到的全局字体: {self.global_font.family()}")
        
        # 设置组件字体
        self.setFont(self.global_font)
        
        # 初始化数据
        self.items = []  # 存储所有添加的文件/文件夹项目
        
        # 初始化UI
        self.init_ui()
        
        # 连接信号
        self.update_progress.connect(self.on_update_progress)
        self.export_finished.connect(self.on_export_finished)
    
    def init_ui(self):
        """
        初始化用户界面
        """
        # 创建主布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # 创建标题和控制区
        title_layout = QHBoxLayout()
        
        # 标题
        title_label = QLabel("文件临时存储池")
        # 只设置字体大小和粗细，不指定字体名称，使用全局字体
        font = QFont("", 12, QFont.Bold)
        title_label.setFont(font)
        title_layout.addWidget(title_label)
        
        # 控制按钮
        clear_btn = QPushButton("清空所有")
        clear_btn.clicked.connect(self.clear_all)
        title_layout.addWidget(clear_btn, 0, Qt.AlignRight)
        
        main_layout.addLayout(title_layout)
        
        # 创建项目列表
        self.items_list = QListWidget()
        self.items_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.items_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.items_list.customContextMenuRequested.connect(self.show_context_menu)
        self.items_list.itemDoubleClicked.connect(self.on_item_double_clicked)
        
        main_layout.addWidget(self.items_list)
        
        # 创建导出功能区
        export_layout = QHBoxLayout()
        
        # 导出按钮
        self.export_btn = QPushButton("导出文件")
        self.export_btn.clicked.connect(self.export_selected_files)
        export_layout.addWidget(self.export_btn)
        
        # 进度条
        from PyQt5.QtWidgets import QProgressBar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        export_layout.addWidget(self.progress_bar, 1)
        
        main_layout.addLayout(export_layout)
        
        # 创建统计信息
        self.stats_label = QLabel("当前项目数: 0")
        self.stats_label.setAlignment(Qt.AlignRight)
        main_layout.addWidget(self.stats_label)
    
    def add_file(self, file_info):
        """
        添加文件到临时存储池
        
        Args:
            file_info (dict): 文件信息字典
        """
        # 检查文件是否已存在
        for item in self.items:
            if item["path"] == file_info["path"]:
                return  # 文件已存在，不重复添加
        
        # 添加到项目列表
        self.items.append(file_info)
        
        # 创建列表项
        list_item = QListWidgetItem()
        list_item.setData(Qt.UserRole, file_info)
        
        # 创建自定义widget
        item_widget = self.create_item_widget(file_info)
        list_item.setSizeHint(item_widget.sizeHint())
        
        # 添加到列表
        self.items_list.addItem(list_item)
        self.items_list.setItemWidget(list_item, item_widget)
        
        # 更新统计信息
        self.update_stats()
    
    def remove_file(self, file_path):
        """
        从临时存储池移除文件
        
        Args:
            file_path (str): 文件路径
        """
        # 查找并移除项目
        for i, item in enumerate(self.items):
            if item["path"] == file_path:
                self.items.pop(i)
                # 从列表中移除对应的项
                list_item = self.items_list.item(i)
                if list_item:
                    self.items_list.takeItem(i)
                break
        
        # 更新统计信息
        self.update_stats()
    
    def clear_all(self):
        """
        清空所有项目
        """
        reply = QMessageBox.question(
            self, "确认清空", 
            "确定要清空所有项目吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # 清空列表
            self.items.clear()
            self.items_list.clear()
            # 更新统计信息
            self.update_stats()
    
    def create_item_widget(self, file_info):
        """
        创建项目widget
        
        Args:
            file_info (dict): 文件信息字典
        
        Returns:
            QWidget: 项目widget
        """
        # 创建widget和布局
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setSpacing(8)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # 添加图标
        icon_label = QLabel()
        icon_label.setFixedSize(32, 32)
        
        # 设置图标
        if file_info["is_dir"]:
            icon = QIcon.fromTheme("folder")
            icon_label.setPixmap(icon.pixmap(24, 24))
        else:
            # 为不同类型的文件设置不同的图标
            suffix = file_info["suffix"]
            if suffix in ["jpg", "jpeg", "png", "gif", "bmp"]:
                icon = QIcon.fromTheme("image")
            elif suffix in ["mp4", "avi", "mov", "mkv"]:
                icon = QIcon.fromTheme("video")
            elif suffix in ["mp3", "wav", "flac", "ogg"]:
                icon = QIcon.fromTheme("audio")
            elif suffix in ["pdf"]:
                icon = QIcon.fromTheme("application-pdf")
            elif suffix in ["txt", "md", "rst"]:
                icon = QIcon.fromTheme("text")
            elif suffix in ["py", "java", "cpp", "js"]:
                icon = QIcon.fromTheme("code")
            else:
                icon = QIcon.fromTheme("application")
            
            icon_label.setPixmap(icon.pixmap(24, 24))
        
        layout.addWidget(icon_label)
        
        # 添加文件信息
        info_layout = QVBoxLayout()
        
        # 文件名
        name_label = QLabel(file_info["name"])
        name_label.setStyleSheet("font-weight: bold;")
        name_label.setWordWrap(True)
        info_layout.addWidget(name_label)
        
        # 文件路径（仅显示部分）
        path_label = QLabel(file_info["path"])
        path_label.setStyleSheet("font-size: 8pt; color: #666;")
        path_label.setWordWrap(True)
        info_layout.addWidget(path_label)
        
        layout.addLayout(info_layout, 1)
        
        # 添加删除按钮
        delete_btn = QPushButton("删除")
        delete_btn.setFixedWidth(60)
        delete_btn.setStyleSheet("background-color: #ff4444; color: white; border: none; border-radius: 4px;")
        delete_btn.clicked.connect(lambda _, fi=file_info: self.remove_file(fi["path"]))
        layout.addWidget(delete_btn)
        
        return widget
    
    def update_stats(self):
        """
        更新统计信息
        """
        total_items = len(self.items)
        self.stats_label.setText(f"当前项目数: {total_items}")
    
    def show_context_menu(self, position):
        """
        显示上下文菜单
        
        Args:
            position (QPoint): 菜单位置
        """
        # 获取当前选中的项
        selected_items = self.items_list.selectedItems()
        if not selected_items:
            return
        
        # 创建菜单
        menu = QMenu()
        
        # 添加操作
        open_action = menu.addAction("打开")
        open_action.triggered.connect(self.open_selected_items)
        
        menu.addSeparator()
        
        remove_action = menu.addAction("删除选中项")
        remove_action.triggered.connect(self.remove_selected_items)
        
        # 显示菜单
        menu.exec_(self.items_list.mapToGlobal(position))
    
    def open_selected_items(self):
        """
        打开选中的项目
        """
        for item in self.items_list.selectedItems():
            file_info = item.data(Qt.UserRole)
            if file_info:
                self.open_file(file_info)
    
    def remove_selected_items(self):
        """
        删除选中的项目
        """
        for item in reversed(self.items_list.selectedItems()):
            file_info = item.data(Qt.UserRole)
            if file_info:
                self.remove_file(file_info["path"])
    
    def on_item_double_clicked(self, item):
        """
        双击项目事件处理
        
        Args:
            item (QListWidgetItem): 双击的项目
        """
        file_info = item.data(Qt.UserRole)
        if file_info:
            self.open_file(file_info)
    
    def open_file(self, file_info):
        """
        打开文件
        
        Args:
            file_info (dict): 文件信息
        """
        file_path = file_info["path"]
        if os.path.exists(file_path):
            if file_info["is_dir"]:
                # 如果是目录，发出信号
                pass
            else:
                # 如果是文件，使用默认应用打开
                os.startfile(file_path)
    
    def export_selected_files(self):
        """
        导出所有文件到指定目录
        """
        # 检查是否有文件可以导出
        if not self.items:
            QMessageBox.information(self, "提示", "文件临时存储池中没有文件可以导出")
            return
        
        # 选择目标目录
        target_dir = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not target_dir:
            return
        
        # 获取所有文件信息
        all_files = self.items
        
        # 显示进度条
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(all_files))
        self.progress_bar.setValue(0)
        
        # 开始复制文件
        self.copy_files(all_files, target_dir)
    
    def on_update_progress(self, value):
        """
        更新进度条
        
        Args:
            value (int): 进度值
        """
        self.progress_bar.setValue(value)
    
    def on_export_finished(self, success_count, error_count, errors):
        """
        处理导出完成
        
        Args:
            success_count (int): 成功导出的文件数
            error_count (int): 失败的文件数
            errors (list): 错误信息列表
        """
        # 隐藏进度条
        self.progress_bar.setVisible(False)
        
        # 显示导出结果
        if error_count == 0:
            QMessageBox.information(self, "导出完成", f"成功导出 {success_count} 个文件")
        else:
            error_msg = f"成功导出 {success_count} 个文件，失败 {error_count} 个文件\n\n失败详情：\n" + "\n".join(errors[:5])
            if len(errors) > 5:
                error_msg += f"\n\n还有 {len(errors) - 5} 个错误未显示"
            QMessageBox.warning(self, "导出结果", error_msg)
    
    def copy_files(self, files, target_dir):
        """
        复制文件到目标目录
        
        Args:
            files (list): 文件信息列表
            target_dir (str): 目标目录路径
        """
        import shutil
        import threading
        
        def copy_thread():
            """复制文件的线程函数"""
            success_count = 0
            error_count = 0
            errors = []
            
            for i, file_info in enumerate(files):
                source_path = file_info["path"]
                target_path = os.path.join(target_dir, file_info["name"])
                
                try:
                    if file_info["is_dir"]:
                        # 复制目录
                        shutil.copytree(source_path, target_path)
                    else:
                        # 复制文件
                        shutil.copy2(source_path, target_path)
                    success_count += 1
                except Exception as e:
                    error_count += 1
                    errors.append(f"{file_info['name']}: {str(e)}")
                
                # 发送进度更新信号
                progress = i + 1
                self.update_progress.emit(progress)
            
            # 发送导出完成信号
            self.export_finished.emit(success_count, error_count, errors)
        
        # 启动复制线程
        thread = threading.Thread(target=copy_thread)
        thread.daemon = True  # 设置为守护线程，防止程序退出时线程还在运行
        thread.start()

# 测试代码
if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication, QMainWindow
    
    app = QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle("文件临时存储池测试")
    window.setGeometry(100, 100, 600, 400)
    
    pool = FileStagingPool()
    window.setCentralWidget(pool)
    
    # 测试添加文件
    test_file = {
        "name": "test.txt",
        "path": "C:/test.txt",
        "is_dir": False,
        "size": 1024,
        "modified": "2023-01-01T12:00:00",
        "created": "2023-01-01T12:00:00",
        "suffix": "txt"
    }
    pool.add_file(test_file)
    
    window.show()
    sys.exit(app.exec_())
