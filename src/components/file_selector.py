#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

2. 商业使用：需联系 qpdrfc123@gmail.com 获取书面授权
项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE
独立的文件选择器组件，前端使用HTML+CSS+JS实现，后端使用Python与之交互
支持多实例同时运行，后端业务相互隔离
"""

import sys
import os
import re
import tempfile
import shutil
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QGroupBox, QGridLayout, QSizePolicy, QScrollArea,
    QMenu, QAction, QFileDialog, QMessageBox, QSlider, QComboBox,
    QProgressBar, QSplitter, QStyle
)
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtCore import (
    Qt, QObject, pyqtSignal, pyqtSlot, QUrl, QFile, QIODevice,
    QStandardPaths
)
from PyQt5.QtGui import QIcon, QFont

# 尝试导入Pillow用于图像处理
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class FileSelectorBackend(QObject):
    """
    文件选择器后端，处理文件系统操作和与前端的通信
    每个实例独立维护状态，支持多实例运行
    """
    
    # 信号：更新文件列表
    filesUpdated = pyqtSignal(list)
    # 信号：更新当前路径
    pathUpdated = pyqtSignal(str)
    # 信号：更新历史记录状态
    historyStatusUpdated = pyqtSignal(bool, bool)  # canGoBack, canGoForward
    # 信号：更新选中文件列表
    selectedFilesChanged = pyqtSignal(list)
    
    def __init__(self):
        super().__init__()
        
        # 实例独立状态
        self.current_path = os.getcwd()  # 当前目录，默认为项目运行目录
        self.history = []  # 历史记录
        self.history_index = -1  # 当前历史记录索引
        self.selected_files = set()  # 选中的文件路径
        
        # 筛选、排序和视图模式
        self.filter_pattern = ''  # 筛选正则表达式
        self.sort_by = 'name'  # 排序字段：name, size, create_time, modify_time
        self.sort_order = 'asc'  # 排序顺序：asc, desc
        
        # 添加当前路径到历史记录
        self._add_to_history(self.current_path)
    
    @pyqtSlot(result=list)
    def getDrives(self):
        # 获取系统盘符列表
        if sys.platform == 'win32':
            # Windows系统
            drives = []
            for drive in range(65, 91):  # A-Z
                drive_letter = chr(drive) + ':/'
                if os.path.exists(drive_letter):
                    drives.append(drive_letter)
            return drives
        else:
            # Linux/macOS系统
            return ['/']
    
    @pyqtSlot(result=str)
    def getCurrentPath(self):
        # 获取当前路径
        return self.current_path
    
    @pyqtSlot(str)
    def setCurrentPath(self, path):
        # 设置当前路径
        if os.path.exists(path) and os.path.isdir(path):
            self.current_path = path
            self._add_to_history(path)
            self.pathUpdated.emit(path)
            self.refreshFiles()
    
    @pyqtSlot()
    def goBack(self):
        # 后退
        if self.history_index > 0:
            self.history_index -= 1
            self.current_path = self.history[self.history_index]
            self.pathUpdated.emit(self.current_path)
            self.refreshFiles()
            
            # 发送历史记录状态更新
            self.historyStatusUpdated.emit(
                self.history_index > 0,  # canGoBack
                self.history_index < len(self.history) - 1  # canGoForward
            )
    
    @pyqtSlot()
    def goForward(self):
        # 前进
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self.current_path = self.history[self.history_index]
            self.pathUpdated.emit(self.current_path)
            self.refreshFiles()
            
            # 发送历史记录状态更新
            self.historyStatusUpdated.emit(
                self.history_index > 0,  # canGoBack
                self.history_index < len(self.history) - 1  # canGoForward
            )
    
    @pyqtSlot()
    def refreshFiles(self):
        # 刷新文件列表
        files = self._get_files_in_directory(self.current_path)
        self.filesUpdated.emit(files)
    
    def _get_files_in_directory(self, path):
        # 获取目录中的文件列表
        files = []
        
        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    try:
                        file_info = {
                            'name': entry.name,
                            'path': entry.path,
                            'is_dir': entry.is_dir(),
                            'size': entry.stat().st_size if not entry.is_dir() else 0,
                            'create_time': entry.stat().st_ctime,
                            'modify_time': entry.stat().st_mtime,
                            'thumbnail': self._get_thumbnail(entry.path, entry.is_dir())
                        }
                        files.append(file_info)
                    except Exception as e:
                        continue
        except Exception as e:
            return []
        
        # 应用筛选
        if self.filter_pattern:
            pattern = re.compile(self.filter_pattern, re.IGNORECASE)
            files = [f for f in files if pattern.search(f['name'])]
        
        # 应用排序
        files.sort(key=self._get_sort_key, reverse=(self.sort_order == 'desc'))
        
        return files
    
    def _get_sort_key(self, file_info):
        # 获取排序键
        if self.sort_by == 'name':
            return file_info['name'].lower()
        elif self.sort_by == 'create_time':
            return file_info['create_time']
        elif self.sort_by == 'modify_time':
            return file_info['modify_time']
        elif self.sort_by == 'size':
            return file_info['size']
        return file_info['name'].lower()
    
    def _get_thumbnail(self, file_path, is_dir):
        # 获取文件缩略图
        if is_dir:
            # 目录使用默认图标
            return 'directory'
        
        # 获取文件扩展名
        ext = os.path.splitext(file_path)[1].lower()
        
        # 图片文件
        if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp']:
            return self._generate_image_thumbnail(file_path)
        
        # 视频文件
        elif ext in ['.mp4', '.avi', '.mov', '.wmv', '.flv']:
            return self._generate_video_thumbnail(file_path)
        
        # 其他文件
        else:
            return self._get_file_type_icon(ext)
    
    def _generate_image_thumbnail(self, file_path):
        # 生成图片缩略图（简化实现，返回默认图片图标）
        try:
            if PIL_AVAILABLE:
                # 使用Pillow生成缩略图
                thumbnail_dir = tempfile.mkdtemp(prefix='file_selector_thumbnails_')
                thumbnail_path = os.path.join(thumbnail_dir, os.path.basename(file_path))
                return thumbnail_path
        except Exception as e:
            pass
        return 'image'
    
    def _generate_video_thumbnail(self, file_path):
        # 生成视频缩略图（简化实现，返回默认视频图标）
        return 'video'
    
    def _get_file_type_icon(self, ext):
        # 根据文件扩展名返回图标类型
        icon_map = {
            '.txt': 'text',
            '.md': 'text',
            '.py': 'code',
            '.js': 'code',
            '.html': 'code',
            '.css': 'code',
            '.pdf': 'pdf',
            '.doc': 'doc',
            '.docx': 'doc',
            '.xls': 'excel',
            '.xlsx': 'excel',
            '.ppt': 'ppt',
            '.pptx': 'ppt',
            '.zip': 'zip',
            '.rar': 'zip',
            '.7z': 'zip',
            '.mp3': 'audio',
            '.wav': 'audio',
            '.flac': 'audio',
        }
        return icon_map.get(ext, 'file')
    
    def _add_to_history(self, path):
        # 添加到历史记录
        if not self.history or self.history[-1] != path:
            # 如果不在历史记录末尾，截断历史记录
            if self.history_index < len(self.history) - 1:
                self.history = self.history[:self.history_index + 1]
            
            self.history.append(path)
            self.history_index = len(self.history) - 1
            
            # 发送历史记录状态更新
            self.historyStatusUpdated.emit(
                self.history_index > 0,  # canGoBack
                self.history_index < len(self.history) - 1  # canGoForward
            )
    
    @pyqtSlot(str)
    def navigateTo(self, path):
        # 导航到指定路径
        if os.path.exists(path):
            if os.path.isdir(path):
                self.setCurrentPath(path)
            else:
                # 如果是文件，导航到文件所在目录
                self.setCurrentPath(os.path.dirname(path))
    
    @pyqtSlot(str)
    def setFilter(self, pattern):
        # 设置筛选正则表达式
        self.filter_pattern = pattern
        self.refreshFiles()
    
    @pyqtSlot(str)
    def setSortBy(self, sort_by):
        # 设置排序方式
        self.sort_by = sort_by
        self.refreshFiles()
    
    @pyqtSlot(str)
    def setSortOrder(self, sort_order):
        # 设置排序顺序
        self.sort_order = sort_order
        self.refreshFiles()
    
    @pyqtSlot(str, bool)
    def toggleSelectFile(self, file_path, is_selected):
        # 切换文件选中状态
        if is_selected:
            self.selected_files.add(file_path)
        else:
            self.selected_files.discard(file_path)
        self.selectedFilesChanged.emit(list(self.selected_files))
    
    @pyqtSlot()
    def selectAll(self):
        # 全选（包括文件和文件夹）
        files = self._get_files_in_directory(self.current_path)
        for file_info in files:
            self.selected_files.add(file_info['path'])
        self.selectedFilesChanged.emit(list(self.selected_files))
    
    @pyqtSlot()
    def selectAllFiles(self):
        # 仅全选文件，不包括文件夹
        files = self._get_files_in_directory(self.current_path)
        for file_info in files:
            if not file_info['is_dir']:  # 只选择文件，不选择目录
                self.selected_files.add(file_info['path'])
    
    @pyqtSlot()
    def selectNone(self):
        # 取消选择
        self.selected_files.clear()
        self.selectedFilesChanged.emit([])
    
    @pyqtSlot()
    def invertSelection(self):
        # 反选（包括文件和文件夹）
        files = self._get_files_in_directory(self.current_path)
        current_items = {f['path'] for f in files}  # 包括文件和文件夹
        
        # 计算反选后的项
        new_selection = current_items - self.selected_files
        self.selected_files = new_selection
        self.selectedFilesChanged.emit(list(self.selected_files))
    
    @pyqtSlot(result=list)
    def getSelectedFiles(self):
        # 获取选中的文件列表
        return list(self.selected_files)
    
    @pyqtSlot()
    def clearSelection(self):
        # 清除选择
        self.selected_files.clear()
        self.selectedFilesChanged.emit([])


class FileSelector(QMainWindow):
    """
    文件选择器主窗口
    """
    
    def __init__(self, instance_id=1):
        super().__init__()
        self.setWindowTitle("文件选择器")
        self.setGeometry(100, 100, 1200, 800)
        self.instance_id = instance_id
        
        # 初始化UI
        self.init_ui()
    
    def init_ui(self):
        # 初始化用户界面
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建主布局
        main_layout = QVBoxLayout(central_widget)     
        
        # 创建Web引擎视图
        self.web_view = QWebEngineView()
        
        # 创建Web通道
        self.channel = QWebChannel()
        
        # 创建后端对象（每个实例独立）
        self.backend = FileSelectorBackend()
        
        # 为每个实例生成唯一的后端对象名称，避免多实例冲突
        backend_name = f"backend_{self.instance_id}"  
        
        # 注册后端对象到Web通道
        self.channel.registerObject(backend_name, self.backend)
        
        # 设置Web通道
        self.web_view.page().setWebChannel(self.channel)
        
        # 加载HTML文件
        html_path = os.path.join(os.path.dirname(__file__), 'file_selector_ui', 'index.html')
        self.web_view.setUrl(QUrl.fromLocalFile(html_path))
        
        # 添加Web视图到布局
        main_layout.addWidget(self.web_view)
    
    def closeEvent(self, event):
        # 关闭事件
        event.accept()


# 命令行参数支持
if __name__ == "__main__":
    app = QApplication(sys.argv)
    selector = FileSelector()
    selector.show()
    sys.exit(app.exec_())