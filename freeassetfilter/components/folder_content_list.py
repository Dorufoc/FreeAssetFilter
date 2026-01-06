#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

文件夹内信息列表预览组件
显示给定路径下的所有文件和文件夹，提供基本信息预览
"""

import sys
import os
from datetime import datetime

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QSplitter, QFrame, QSizePolicy,
    QFileIconProvider, QMenu
)
from PyQt5.QtCore import (
    Qt, pyqtSignal, QFileInfo, QDateTime
)
from PyQt5.QtGui import (
    QIcon, QFont, QColor, QBrush
)


class FolderContentList(QWidget):
    """
    文件夹内信息列表预览组件
    显示给定路径下的所有文件和文件夹
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 获取应用实例和DPI缩放因子
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QFont
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 获取全局字体
        self.global_font = getattr(app, 'global_font', QFont())
        # 设置组件字体
        self.setFont(self.global_font)
        
        # 初始化配置
        self.current_path = os.path.expanduser("~")  # 默认路径为用户主目录
        
        # 创建文件图标提供者
        self.icon_provider = QFileIconProvider()
        
        # 初始化UI
        self.init_ui()
        
        # 加载初始路径内容
        self.load_folder_content()
    
    def init_ui(self):
        """
        初始化用户界面
        """
        # 应用DPI缩放因子到布局参数
        scaled_spacing = int(5 * self.dpi_scale)
        scaled_margin = int(5 * self.dpi_scale)
        
        # 获取应用实例
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        
        # 获取默认字体大小并应用DPI缩放
        default_font_size = getattr(app, 'default_font_size', 14)
        scaled_font_size = int(default_font_size * self.dpi_scale)
        
        # 创建主布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(scaled_spacing)
        main_layout.setContentsMargins(scaled_margin, scaled_margin, scaled_margin, scaled_margin)
        
        # 创建顶部路径栏
        path_layout = QHBoxLayout()
        path_layout.setSpacing(scaled_spacing)
        
        # 路径标签
        self.path_label = QLabel(f"当前路径: {self.current_path}")
        self.path_label.setFont(self.global_font)
        self.path_label.setStyleSheet(f"font-size: {scaled_font_size}px;")
        path_layout.addWidget(self.path_label)
        
        main_layout.addLayout(path_layout)
        
        # 创建列表控件
        self.content_list = QListWidget()
        self.content_list.setAlternatingRowColors(True)
        self.content_list.setFont(self.global_font)
        self.content_list.setStyleSheet(f"font-size: {scaled_font_size}px;")
        # 移除所有交互事件
        # 只保留列表显示功能
        main_layout.addWidget(self.content_list)
        
        # 创建底部状态栏
        self.status_label = QLabel("就绪")
        self.status_label.setFont(self.global_font)
        self.status_label.setStyleSheet(f"font-size: {scaled_font_size}px;")
        main_layout.addWidget(self.status_label)
    
    def set_path(self, path):
        """
        设置当前路径
        
        Args:
            path (str): 要设置的路径
        """
        if os.path.exists(path) and os.path.isdir(path):
            self.current_path = path
            self.path_label.setText(f"当前路径: {self.current_path}")
            self.load_folder_content()
        
    def load_folder_content(self):
        """
        加载当前路径下的内容
        """
        # 清空列表
        self.content_list.clear()
        
        try:
            # 获取当前路径下的所有文件和文件夹
            entries = os.listdir(self.current_path)
            
            # 排序：文件夹在前，文件在后，按名称排序
            entries.sort(key=lambda x: (not os.path.isdir(os.path.join(self.current_path, x)), x.lower()))
            
            # 添加当前目录下的所有项
            for entry in entries:
                entry_path = os.path.join(self.current_path, entry)
                file_info = QFileInfo(entry_path)
                
                # 创建列表项
                item = QListWidgetItem()
                
                # 设置图标
                if file_info.isDir():
                    icon = self.icon_provider.icon(QFileIconProvider.Folder)
                    item.setText(entry)
                else:
                    icon = self.icon_provider.icon(file_info)
                    # 显示文件名、大小和修改时间
                    size = self._format_size(file_info.size())
                    modified_time = file_info.lastModified().toString("yyyy-MM-dd HH:mm")
                    item.setText(f"{entry} ({size}) - {modified_time}")
                
                item.setIcon(icon)
                self.content_list.addItem(item)
            
            # 更新状态
            self.status_label.setText(f"共 {len(entries)} 项")
        except Exception as e:
            self.status_label.setText(f"错误: {str(e)}")
    

    
    def _format_size(self, size_bytes):
        """
        格式化文件大小
        
        Args:
            size_bytes (int): 文件大小（字节）
            
        Returns:
            str: 格式化后的文件大小
        """
        if size_bytes == 0:
            return "0 B"
        
        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024
            i += 1
        
        return f"{size_bytes:.1f} {size_names[i]}"


# 测试代码
if __name__ == "__main__":
    from PyQt5.QtWidgets import QApplication, QMainWindow
    
    app = QApplication(sys.argv)
    
    window = QMainWindow()
    window.setWindowTitle("文件夹内信息列表预览组件")
    window.setGeometry(100, 100, 800, 600)
    
    folder_list = FolderContentList()
    window.setCentralWidget(folder_list)
    
    window.show()
    sys.exit(app.exec_())
