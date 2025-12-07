#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

2. 商业使用：需联系 qpdrfc123@gmail.com 获取书面授权�?
项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE
文件信息查看器用户界面组�?为FileInfoViewer提供完整的图形用户界�?
"""

import os
import sys
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox, 
    QGridLayout, QTreeWidget, QTreeWidgetItem, QTabWidget, QFileDialog, 
    QLineEdit, QListWidget, QListWidgetItem, QInputDialog, QMessageBox,
    QScrollArea, QFrame, QSplitter, QFormLayout, QComboBox, QApplication
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QIcon, QPixmap, QFont, QColor

# 导入自定义文件信息查看器核心组件
from src.core.file_info_viewer import FileInfoViewer


class FileInfoPanel(QWidget):
    """
    文件信息面板组件，显示文件的详细信息
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.file_info_viewer = FileInfoViewer()
        self.init_ui()
    
    def init_ui(self):
        """
        初始化用户界�?
        """
        # 创建主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # 1. 文件操作工具�?
        toolbar_layout = QHBoxLayout()
        
        # 打开文件按钮
        self.open_file_button = QPushButton("打开文件")
        self.open_file_button.setIcon(self._get_icon('file-open'))
        self.open_file_button.clicked.connect(self.open_file)
        toolbar_layout.addWidget(self.open_file_button)
        
        # 打开方式按钮
        self.open_with_button = QPushButton("使用系统打开")
        self.open_with_button.setIcon(self._get_icon('system-open'))
        self.open_with_button.clicked.connect(self.open_with_system)
        self.open_with_button.setEnabled(False)
        toolbar_layout.addWidget(self.open_with_button)
        
        toolbar_layout.addStretch()
        main_layout.addLayout(toolbar_layout)
        
        # 2. 文件信息标签
        self.file_path_label = QLabel("未选择文件")
        self.file_path_label.setStyleSheet("font-size: 12px; color: #666; font-weight: bold;")
        self.file_path_label.setWordWrap(True)
        main_layout.addWidget(self.file_path_label)
        
        # 3. 标签页控�?
        self.tab_widget = QTabWidget()
        self.tab_widget.setMinimumHeight(400)
        
        # 基本信息标签�?
        self.basic_info_tab = QWidget()
        self._init_basic_info_tab()
        self.tab_widget.addTab(self.basic_info_tab, "基本信息")
        
        # 类型特定信息标签�?
        self.type_specific_tab = QWidget()
        self._init_type_specific_tab()
        self.tab_widget.addTab(self.type_specific_tab, "详细信息")
        
        # 自定义标签标签页
        self.custom_tags_tab = QWidget()
        self._init_custom_tags_tab()
        self.tab_widget.addTab(self.custom_tags_tab, "自定义标�?)
        
        main_layout.addWidget(self.tab_widget)
        
    def _init_basic_info_tab(self):
        """
        初始化基本信息标签页
        """
        layout = QVBoxLayout(self.basic_info_tab)
        
        # 创建信息显示区域
        self.basic_info_tree = QTreeWidget()
        self.basic_info_tree.setHeaderLabels(["属�?, "�?])
        self.basic_info_tree.setColumnWidth(0, 150)
        self.basic_info_tree.setAlternatingRowColors(True)
        
        # 添加占位�?
        self._add_placeholder(self.basic_info_tree, "请打开一个文件查看信�?)
        
        layout.addWidget(self.basic_info_tree)
    
    def _init_type_specific_tab(self):
        """
        初始化类型特定信息标签页
        """
        layout = QVBoxLayout(self.type_specific_tab)
        
        # 创建信息显示区域
        self.type_specific_tree = QTreeWidget()
        self.type_specific_tree.setHeaderLabels(["属�?, "�?])
        self.type_specific_tree.setColumnWidth(0, 150)
        self.type_specific_tree.setAlternatingRowColors(True)
        
        # 添加占位�?
        self._add_placeholder(self.type_specific_tree, "请打开一个文件查看详细信�?)
        
        layout.addWidget(self.type_specific_tree)
    
    def _init_custom_tags_tab(self):
        """
        初始化自定义标签标签�?
        """
        layout = QVBoxLayout(self.custom_tags_tab)
        
        # 标签列表
        self.custom_tags_list = QListWidget()
        self.custom_tags_list.setAlternatingRowColors(True)
        
        # 标签操作按钮布局
        button_layout = QHBoxLayout()
        
        self.add_tag_button = QPushButton("添加标签")
        self.add_tag_button.clicked.connect(self.add_custom_tag)
        button_layout.addWidget(self.add_tag_button)
        
        self.remove_tag_button = QPushButton("删除标签")
        self.remove_tag_button.clicked.connect(self.remove_custom_tag)
        self.remove_tag_button.setEnabled(False)
        button_layout.addWidget(self.remove_tag_button)
        
        layout.addWidget(QLabel("自定义标签列表："))
        layout.addWidget(self.custom_tags_list)
        layout.addLayout(button_layout)
        
        # 连接列表选择信号
        self.custom_tags_list.itemSelectionChanged.connect(self._on_tag_selected)
    
    def _add_placeholder(self, tree_widget, text):
        """
        添加占位文本
        """
        item = QTreeWidgetItem([text])
        item.setTextAlignment(0, Qt.AlignCenter)
        item.setTextAlignment(1, Qt.AlignCenter)
        item.setForeground(0, QColor(128, 128, 128))
        item.setForeground(1, QColor(128, 128, 128))
        tree_widget.addTopLevelItem(item)
        tree_widget.setCurrentItem(item)
    
    def open_file(self):
        """
        打开文件对话�?
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择文件",
            "",
            "所有文�?(*.*);;视频文件 (*.mp4 *.mov *.m4v *.flv *.mxf *.3gp *.mpg *.avi *.wmv *.mkv *.webm *.vob *.ogv *.rmvb);;图片文件 (*.jpg *.jpeg *.png *.gif *.bmp *.tiff *.tif *.webp *.svg *.raw *.cr2 *.nef *.orf *.arw);;文本文件 (*.txt *.md *.json *.csv *.xml *.html *.htm *.css *.js *.py *.java *.c *.cpp *.h *.hpp *.php *.rb *.sh *.bat)"
        )
        
        if file_path:
            self.load_file(file_path)
    
    def load_file(self, file_path):
        """
        加载指定文件的信�?
        
        Args:
            file_path: 文件路径
        """
        if self.file_info_viewer.set_file_path(file_path):
            # 更新文件路径标签
            self.file_path_label.setText(f"文件: {file_path}")
            
            # 启用相关按钮
            self.open_with_button.setEnabled(True)
            
            # 更新基本信息
            self._update_basic_info()
            
            # 更新类型特定信息
            self._update_type_specific_info()
            
            # 更新自定义标�?
            self._update_custom_tags()
        else:
            QMessageBox.warning(self, "错误", "无法加载文件信息")
    
    def _update_basic_info(self):
        """
        更新基本信息显示
        """
        self.basic_info_tree.clear()
        
        file_info = self.file_info_viewer.file_info
        if not file_info or 'basic' not in file_info:
            self._add_placeholder(self.basic_info_tree, "无法获取基本信息")
            return
        
        basic_info = file_info['basic']
        
        # 添加基本信息�?
        items = [
            ("文件�?, basic_info.get('name', 'Unknown')),
            ("文件类型", basic_info.get('type', 'Unknown')),
            ("文件格式", basic_info.get('extension', 'Unknown')),
            ("文件大小", basic_info.get('size_readable', 'Unknown')),
            ("创建时间", basic_info.get('created_time', 'Unknown')),
            ("修改时间", basic_info.get('modified_time', 'Unknown')),
            ("访问时间", basic_info.get('accessed_time', 'Unknown')),
            ("完整路径", self.file_info_viewer.current_file_path)
        ]
        
        for key, value in items:
            item = QTreeWidgetItem([key, str(value)])
            item.setForeground(0, QColor(0, 0, 0))
            item.setForeground(1, QColor(64, 64, 64))
            self.basic_info_tree.addTopLevelItem(item)
    
    def _update_type_specific_info(self):
        """
        更新类型特定信息显示
        """
        self.type_specific_tree.clear()
        
        file_info = self.file_info_viewer.file_info
        if not file_info or 'basic' not in file_info or 'type_specific' not in file_info:
            self._add_placeholder(self.type_specific_tree, "无法获取详细信息")
            return
        
        file_type = file_info['basic'].get('type', 'other')
        type_specific_info = file_info['type_specific']
        
        # 根据文件类型显示不同的信�?
        if file_type == 'video':
            self._display_video_info(type_specific_info)
        elif file_type == 'image':
            self._display_image_info(type_specific_info)
        elif file_type == 'text':
            self._display_text_info(type_specific_info)
        else:
            self._add_placeholder(self.type_specific_tree, "不支持的文件类型")
    
    def _display_video_info(self, video_info):
        """
        显示视频文件信息
        """
        items = [
            ("时长", video_info.get('duration_readable', 'Unknown')),
            ("视频分辨�?, video_info.get('resolution', 'Unknown')),
            ("视频宽度", str(video_info.get('width', 'Unknown'))),
            ("视频高度", str(video_info.get('height', 'Unknown'))),
            ("视频帧率", f"{video_info.get('frame_rate', 'Unknown')} fps"),
            ("视频码率", f"{video_info.get('bitrate', 'Unknown')} kbps")
        ]
        
        for key, value in items:
            item = QTreeWidgetItem([key, str(value)])
            item.setForeground(0, QColor(0, 0, 0))
            item.setForeground(1, QColor(64, 64, 64))
            self.type_specific_tree.addTopLevelItem(item)
    
    def _display_image_info(self, image_info):
        """
        显示图片文件信息
        """
        items = [
            ("分辨�?, image_info.get('resolution', 'Unknown')),
            ("宽度", str(image_info.get('width', 'Unknown'))),
            ("高度", str(image_info.get('height', 'Unknown')))
        ]
        
        for key, value in items:
            item = QTreeWidgetItem([key, str(value)])
            item.setForeground(0, QColor(0, 0, 0))
            item.setForeground(1, QColor(64, 64, 64))
            self.type_specific_tree.addTopLevelItem(item)
        
        # 添加EXIF信息（如果有�?
        if image_info.get('exif'):
            exif_parent = QTreeWidgetItem(["EXIF信息", ""])
            exif_parent.setForeground(0, QColor(0, 0, 0))
            exif_parent.setForeground(1, QColor(64, 64, 64))
            exif_parent.setExpanded(True)
            
            for tag, value in image_info['exif'].items():
                # 只显示常用的EXIF标签
                if self._is_important_exif_tag(tag):
                    exif_item = QTreeWidgetItem([tag, str(value)])
                    exif_item.setForeground(0, QColor(0, 0, 0))
                    exif_item.setForeground(1, QColor(64, 64, 64))
                    exif_parent.addChild(exif_item)
            
            if exif_parent.childCount() > 0:
                self.type_specific_tree.addTopLevelItem(exif_parent)
    
    def _display_text_info(self, text_info):
        """
        显示文本文件信息
        """
        items = [
            ("编码格式", text_info.get('encoding', 'Unknown')),
            ("行数", str(text_info.get('line_count', 'Unknown'))),
            ("字符�?, str(text_info.get('char_count', 'Unknown')))
        ]
        
        for key, value in items:
            item = QTreeWidgetItem([key, str(value)])
            item.setForeground(0, QColor(0, 0, 0))
            item.setForeground(1, QColor(64, 64, 64))
            self.type_specific_tree.addTopLevelItem(item)
    
    def _is_important_exif_tag(self, tag):
        """
        判断是否为重要的EXIF标签
        
        Args:
            tag: EXIF标签�?
            
        Returns:
            bool: 是否为重要标�?
        """
        important_tags = [
            'Image.DateTime', 'Image.Make', 'Image.Model', 'Image.Orientation',
            'Image.Software', 'EXIF.ExposureTime', 'EXIF.FNumber', 
            'EXIF.ISO', 'EXIF.FocalLength', 'EXIF.DateTimeOriginal',
            'EXIF.DateTimeDigitized', 'EXIF.WhiteBalance', 'EXIF.Flash'
        ]
        
        return any(important_tag in tag for important_tag in important_tags)
    
    def _update_custom_tags(self):
        """
        更新自定义标签显�?
        """
        self.custom_tags_list.clear()
        
        for key, value in self.file_info_viewer.custom_tags.items():
            item = QListWidgetItem(f"{key}: {value}")
            self.custom_tags_list.addItem(item)
    
    def add_custom_tag(self):
        """
        添加自定义标�?
        """
        if not self.file_info_viewer.current_file_path:
            QMessageBox.warning(self, "提示", "请先打开一个文�?)
            return
        
        # 获取标签�?
        tag_name, ok = QInputDialog.getText(self, "添加标签", "请输入标签名�?)
        if not ok or not tag_name.strip():
            return
        
        # 获取标签�?
        tag_value, ok = QInputDialog.getText(self, "添加标签", f"请输�?{tag_name}'的值：")
        if not ok:
            return
        
        # 添加标签
        if self.file_info_viewer.add_custom_tag(tag_name.strip(), tag_value):
            self._update_custom_tags()
        else:
            QMessageBox.warning(self, "错误", "无法添加标签")
    
    def remove_custom_tag(self):
        """
        删除自定义标�?
        """
        current_item = self.custom_tags_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "提示", "请选择要删除的标签")
            return
        
        # 解析标签�?
        text = current_item.text()
        if ':' in text:
            tag_name = text.split(':', 1)[0].strip()
            
            # 删除标签
            if self.file_info_viewer.remove_custom_tag(tag_name):
                self._update_custom_tags()
            else:
                QMessageBox.warning(self, "错误", "无法删除标签")
    
    def open_with_system(self):
        """
        使用系统默认应用打开文件
        """
        if not self.file_info_viewer.current_file_path:
            QMessageBox.warning(self, "提示", "请先打开一个文�?)
            return
        
        if not self.file_info_viewer.open_file_with_default_app():
            QMessageBox.warning(self, "错误", "无法使用系统应用打开文件")
    
    def _on_tag_selected(self):
        """
        标签选择变化时的处理
        """
        has_selection = self.custom_tags_list.currentItem() is not None
        self.remove_tag_button.setEnabled(has_selection)
    
    def _get_icon(self, icon_name):
        """
        获取图标（这里使用占位图标，实际应用中可以使用系统图标或自定义图标）
        
        Args:
            icon_name: 图标名称
            
        Returns:
            QIcon: 图标对象
        """
        # 这里简化处理，实际应用中应该使用合适的图标
        return QIcon()
    
    def _add_placeholder(self, tree_widget, text):
        """
        在树控件中添加占位文�?
        """
        item = QTreeWidgetItem([text, ""])
        item.setTextAlignment(0, Qt.AlignCenter)
        item.setTextAlignment(1, Qt.AlignCenter)
        item.setForeground(0, QColor(128, 128, 128))
        tree_widget.addTopLevelItem(item)
        tree_widget.setCurrentItem(item)


class FileInfoViewerApp(QWidget):
    """
    文件信息查看器应用程�?
    """
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("文件信息查看�?)
        self.setGeometry(100, 100, 800, 600)
        self.init_ui()
    
    def init_ui(self):
        """
        初始化应用程序界�?
        """
        layout = QVBoxLayout(self)
        
        # 创建文件信息面板
        self.file_info_panel = FileInfoPanel(self)
        
        layout.addWidget(self.file_info_panel)


# 测试代码
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = FileInfoViewerApp()
    window.show()
    sys.exit(app.exec_())

