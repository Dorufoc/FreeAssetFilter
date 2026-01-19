#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

文件块卡片组件
可伸缩的文件卡片控件，支持多种交互状态和文件信息展示
"""

import sys
import os

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy, QApplication
from PyQt5.QtCore import Qt, pyqtSignal, QEvent, QSize
from PyQt5.QtGui import QFont, QFontMetrics, QPixmap, QColor, QPainter
from PyQt5.QtSvg import QSvgWidget

from freeassetfilter.core.svg_renderer import SvgRenderer
from freeassetfilter.core.settings_manager import SettingsManager


class FileBlockCard(QWidget):
    """
    可伸缩文件卡片组件
    
    特性：
    - 最小横向宽度35，最大50（支持DPI缩放）
    - 圆角和边框设计
    - 三种状态：未选中态、hover态、选中态
    - 选中态不响应hover效果
    - 支持左键点击、右键点击、左键双击
    
    信号：
    - clicked: 点击信号，传递file_info
    - right_clicked: 右键点击信号，传递file_info
    - double_clicked: 双击信号，传递file_info
    """
    
    clicked = pyqtSignal(dict)
    right_clicked = pyqtSignal(dict)
    double_clicked = pyqtSignal(dict)
    
    def __init__(self, file_info, dpi_scale=1.0, parent=None):
        """
        初始化文件块卡片
        
        Args:
            file_info (dict): 文件信息字典，包含以下键：
                - name: 文件名
                - path: 文件路径
                - is_dir: 是否为文件夹
                - size: 文件大小（字节）
                - created: 创建时间（ISO格式字符串）
            dpi_scale (float): DPI缩放因子，默认1.0
            parent (QWidget): 父控件
        """
        super().__init__(parent)
        
        self.file_info = file_info
        self.dpi_scale = dpi_scale
        
        self._is_selected = False
        self._is_hovered = False
        
        self._setup_ui()
        self._setup_signals()
        self._update_styles()
    
    def _setup_ui(self):
        """设置UI布局和控件"""
        self.setObjectName("FileBlockCard")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        
        scaled_min_width = int(35 * self.dpi_scale)
        scaled_max_width = int(50 * self.dpi_scale)
        self.setMinimumWidth(scaled_min_width)
        self.setMaximumWidth(scaled_max_width)
        
        app = QApplication.instance()
        self.default_font_size = getattr(app, 'default_font_size', 9) if app else 9
        
        self._init_colors()
        self._create_layout()
        self._create_icon()
        self._create_labels()
    
    def _init_colors(self):
        """初始化颜色配置"""
        try:
            settings_manager = SettingsManager()
            self.auxiliary_color = settings_manager.get_setting("appearance.colors.auxiliary_color", "#ffffff")
            self.base_color = settings_manager.get_setting("appearance.colors.base_color", "#e0e0e0")
            self.normal_color = settings_manager.get_setting("appearance.colors.normal_color", "#4a7abc")
            self.accent_color = settings_manager.get_setting("appearance.colors.accent_color", "#1890ff")
            self.secondary_color = settings_manager.get_setting("appearance.colors.secondary_color", "#333333")
        except Exception:
            self.auxiliary_color = "#ffffff"
            self.base_color = "#e0e0e0"
            self.normal_color = "#4a7abc"
            self.accent_color = "#1890ff"
            self.secondary_color = "#333333"
    
    def _create_layout(self):
        """创建卡片布局"""
        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(int(2 * self.dpi_scale))
        self.layout.setContentsMargins(
            int(4 * self.dpi_scale), int(4 * self.dpi_scale),
            int(4 * self.dpi_scale), int(4 * self.dpi_scale)
        )
        self.layout.setAlignment(Qt.AlignCenter)
    
    def _create_icon(self):
        """创建文件图标"""
        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setStyleSheet("background: transparent; border: none;")
        
        scaled_icon_size = int(24 * self.dpi_scale)
        self.icon_label.setFixedSize(scaled_icon_size, scaled_icon_size)
        
        self._update_icon()
        
        self.layout.addWidget(self.icon_label, alignment=Qt.AlignCenter)
    
    def _update_icon(self):
        """更新文件图标"""
        icon_path = self._get_icon_path()
        
        if icon_path and os.path.exists(icon_path):
            scaled_icon_size = int(24 * self.dpi_scale)
            svg_widget = SvgRenderer.render_svg_to_widget(icon_path, scaled_icon_size, self.dpi_scale)
            
            for child in self.icon_label.findChildren(QLabel):
                child.deleteLater()
            for child in self.icon_label.findChildren(QSvgWidget):
                child.deleteLater()
            
            if isinstance(svg_widget, QSvgWidget):
                svg_widget.setParent(self.icon_label)
                svg_widget.setFixedSize(scaled_icon_size, scaled_icon_size)
                svg_widget.show()
            else:
                self.icon_label.setPixmap(svg_widget.pixmap())
        else:
            pixmap = QPixmap(self.icon_label.size())
            pixmap.fill(Qt.transparent)
            self.icon_label.setPixmap(pixmap)
    
    def _get_icon_path(self):
        """获取文件图标路径"""
        icon_dir = os.path.join(os.path.dirname(__file__), "..", "icons")
        
        if self.file_info.get("is_dir", False):
            return os.path.join(icon_dir, "文件夹.svg")
        
        suffix = self.file_info.get("suffix", "").lower()
        
        video_formats = ["mp4", "avi", "mov", "mkv", "m4v", "mxf", "wmv", "flv", "webm", "3gp", "mpg", "mpeg", "vob", "m2ts", "ts", "mts"]
        image_formats = ["jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "svg", "cr2", "cr3", "nef", "arw", "dng", "orf"]
        audio_formats = ["mp3", "wav", "flac", "ogg", "wma", "aac", "m4a", "opus"]
        document_formats = ["pdf", "txt", "md", "rst", "doc", "docx", "xls", "xlsx", "ppt", "pptx"]
        font_formats = ["ttf", "otf", "woff", "woff2", "eot", "svg"]
        archive_formats = ["zip", "rar", "7z", "tar", "gz", "bz2", "xz", "lzma", "tar.gz", "tar.bz2", "tar.xz", "tar.lzma", "iso", "cab", "arj", "lzh", "ace", "z"]
        
        if suffix in video_formats:
            return os.path.join(icon_dir, "视频.svg")
        elif suffix in image_formats:
            return os.path.join(icon_dir, "图像.svg")
        elif suffix == "pdf":
            return os.path.join(icon_dir, "PDF.svg")
        elif suffix in ["ppt", "pptx", "ppsx"]:
            return os.path.join(icon_dir, "PPT.svg")
        elif suffix in ["xls", "xlsx", "csv"]:
            return os.path.join(icon_dir, "表格.svg")
        elif suffix in ["doc", "docx", "wps"]:
            return os.path.join(icon_dir, "Word文档.svg")
        elif suffix in font_formats:
            return os.path.join(icon_dir, "字体.svg")
        elif suffix in audio_formats:
            return os.path.join(icon_dir, "音乐.svg")
        elif suffix in archive_formats:
            return os.path.join(icon_dir, "压缩文件.svg")
        else:
            return os.path.join(icon_dir, "文档.svg")
    
    def _create_labels(self):
        """创建文本标签"""
        scaled_font_size = int(self.default_font_size * self.dpi_scale)
        small_font_size = int(scaled_font_size * 0.85)
        
        font = QFont()
        font.setPointSize(scaled_font_size)
        
        small_font = QFont()
        small_font.setPointSize(small_font_size)
        
        self.name_label = QLabel()
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setFont(font)
        self.name_label.setStyleSheet("background: transparent; border: none;")
        self.name_label.setWordWrap(False)
        
        self._update_name_label()
        self.layout.addWidget(self.name_label)
        
        self.size_label = QLabel()
        self.size_label.setAlignment(Qt.AlignCenter)
        self.size_label.setFont(small_font)
        self.size_label.setStyleSheet("background: transparent; border: none;")
        self._update_size_label()
        self.layout.addWidget(self.size_label)
        
        self.time_label = QLabel()
        self.time_label.setAlignment(Qt.AlignCenter)
        self.time_label.setFont(small_font)
        self.time_label.setStyleSheet("background: transparent; border: none;")
        self._update_time_label()
        self.layout.addWidget(self.time_label)
    
    def _update_name_label(self):
        """更新文件名显示"""
        text = self.file_info.get("name", "")
        font = self.name_label.font()
        font_metrics = QFontMetrics(font)
        
        max_width = int(45 * self.dpi_scale)
        elided_text = font_metrics.elidedText(text, Qt.ElideRight, max_width)
        self.name_label.setText(elided_text)
    
    def _update_size_label(self):
        """更新文件大小显示"""
        if self.file_info.get("is_dir", False):
            self.size_label.setText("文件夹")
        else:
            size = self.file_info.get("size", 0)
            self.size_label.setText(self._format_size(size))
    
    def _update_time_label(self):
        """更新时间显示"""
        created = self.file_info.get("created", "")
        if created:
            from PyQt5.QtCore import QDateTime
            try:
                dt = QDateTime.fromString(created, Qt.ISODate)
                self.time_label.setText(dt.toString("yyyy-MM-dd"))
            except Exception:
                self.time_label.setText(created[:10] if len(created) >= 10 else created)
        else:
            self.time_label.setText("")
    
    def _format_size(self, size):
        """格式化文件大小"""
        if size < 0:
            size = 0
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.1f} GB"
    
    def _setup_signals(self):
        """设置事件过滤器"""
        self.installEventFilter(self)
    
    def eventFilter(self, obj, event):
        """事件过滤器，处理鼠标事件"""
        if obj == self:
            if event.type() == QEvent.MouseButtonPress:
                if event.button() == Qt.LeftButton:
                    self._on_click(event)
                elif event.button() == Qt.RightButton:
                    self._on_right_click(event)
                return True
            elif event.type() == QEvent.MouseButtonDblClick:
                if event.button() == Qt.LeftButton:
                    self._on_double_click(event)
                return True
            elif event.type() == QEvent.Enter:
                if not self._is_selected:
                    self._is_hovered = True
                    self._update_styles()
                return True
            elif event.type() == QEvent.Leave:
                self._is_hovered = False
                self._update_styles()
                return True
        return super().eventFilter(obj, event)
    
    def _on_click(self, event):
        """处理左键点击"""
        self.clicked.emit(self.file_info)
    
    def _on_right_click(self, event):
        """处理右键点击"""
        self.right_clicked.emit(self.file_info)
    
    def _on_double_click(self, event):
        """处理双击"""
        self.double_clicked.emit(self.file_info)
    
    def _update_styles(self):
        """更新卡片样式"""
        scaled_border_radius = int(6 * self.dpi_scale)
        scaled_border_width = int(1 * self.dpi_scale)
        
        if self._is_selected:
            self.setStyleSheet(f"""
                background-color: {self._hex_to_rgba(self.accent_color, 30)};
                border: {scaled_border_width}px solid {self.accent_color};
                border-radius: {scaled_border_radius}px;
            """)
            self.name_label.setStyleSheet(f"color: {self.secondary_color}; background: transparent; border: none;")
            self.size_label.setStyleSheet(f"color: {self.secondary_color}; background: transparent; border: none;")
            self.time_label.setStyleSheet(f"color: {self.secondary_color}; background: transparent; border: none;")
        elif self._is_hovered:
            self.setStyleSheet(f"""
                background-color: {self._hex_to_rgba(self.accent_color, 10)};
                border: {scaled_border_width}px solid {self.normal_color};
                border-radius: {scaled_border_radius}px;
            """)
            self.name_label.setStyleSheet(f"color: {self.normal_color}; background: transparent; border: none;")
            self.size_label.setStyleSheet(f"color: {self.normal_color}; background: transparent; border: none;")
            self.time_label.setStyleSheet(f"color: {self.normal_color}; background: transparent; border: none;")
        else:
            self.setStyleSheet(f"""
                background-color: {self.auxiliary_color};
                border: {scaled_border_width}px solid {self.base_color};
                border-radius: {scaled_border_radius}px;
            """)
            self.name_label.setStyleSheet(f"color: {self.secondary_color}; background: transparent; border: none;")
            self.size_label.setStyleSheet(f"color: {self.secondary_color}; background: transparent; border: none;")
            self.time_label.setStyleSheet(f"color: {self.secondary_color}; background: transparent; border: none;")
    
    def _hex_to_rgba(self, hex_color, alpha):
        """将十六进制颜色转换为RGBA格式"""
        hex_color = hex_color.lstrip('#')
        if len(hex_color) == 6:
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            return f"rgba({r}, {g}, {b}, {alpha / 100.0:.2f})"
        return hex_color
    
    def set_selected(self, selected):
        """
        设置卡片选中状态
        
        Args:
            selected (bool): 是否选中
        """
        self._is_selected = selected
        if selected:
            self._is_hovered = False
        self._update_styles()
    
    def is_selected(self):
        """获取卡片选中状态"""
        return self._is_selected
    
    def set_file_info(self, file_info):
        """
        设置文件信息
        
        Args:
            file_info (dict): 文件信息字典
        """
        self.file_info = file_info
        self._update_name_label()
        self._update_size_label()
        self._update_time_label()
        self._update_icon()
    
    def sizeHint(self):
        """返回建议的大小"""
        base_width = int(42 * self.dpi_scale)
        return QSize(base_width, int(80 * self.dpi_scale))
