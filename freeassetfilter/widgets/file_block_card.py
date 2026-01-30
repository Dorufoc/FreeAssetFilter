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
from PyQt5.QtCore import Qt, pyqtSignal, QEvent, QSize, QPropertyAnimation, pyqtProperty, QEasingCurve, QParallelAnimationGroup
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
    - 支持非线性动画过渡效果
    
    信号：
    - clicked: 点击信号，传递file_info
    - right_clicked: 右键点击信号，传递file_info
    - double_clicked: 双击信号，传递file_info
    - selection_changed: 选中状态变化信号，传递(file_info, is_selected)
    """
    
    clicked = pyqtSignal(dict)
    right_clicked = pyqtSignal(dict)
    double_clicked = pyqtSignal(dict)
    selection_changed = pyqtSignal(dict, bool)
    
    @pyqtProperty(QColor)
    def anim_bg_color(self):
        return self._anim_bg_color
    
    @anim_bg_color.setter
    def anim_bg_color(self, color):
        self._anim_bg_color = color
        self._apply_animated_style()
    
    @pyqtProperty(QColor)
    def anim_border_color(self):
        return self._anim_border_color
    
    @anim_border_color.setter
    def anim_border_color(self, color):
        self._anim_border_color = color
        self._apply_animated_style()
    
    def _apply_animated_style(self):
        """应用动画颜色到卡片样式"""
        if not hasattr(self, '_style_colors'):
            return
        
        scaled_border_radius = int(8 * self.dpi_scale)
        scaled_border_width = int(1 * self.dpi_scale)
        
        r, g, b, a = self._anim_bg_color.red(), self._anim_bg_color.green(), self._anim_bg_color.blue(), self._anim_bg_color.alpha()
        bg_color = f"rgba({r}, {g}, {b}, {a})"
        border_color = self._anim_border_color.name()
        
        self.setStyleSheet(f"background-color: {bg_color}; border: {scaled_border_width}px solid {border_color}; border-radius: {scaled_border_radius}px;")
    
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
        self._flexible_width = None
        
        self._is_selected = False
        self._is_hovered = False
        
        self._touch_drag_threshold = int(10 * self.dpi_scale)
        self._touch_start_pos = None
        self._is_touch_dragging = False
        
        self._setup_ui()
        self._setup_signals()
        self._init_animations()
        self._update_styles()
    
    def _setup_ui(self):
        """设置UI布局和控件"""
        self.setObjectName("FileBlockCard")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        
        scaled_min_width = int(35 * self.dpi_scale)
        scaled_max_width = int(50 * self.dpi_scale)
        scaled_max_height = int(75 * self.dpi_scale)
        self.setMinimumWidth(scaled_min_width)
        self.setMaximumWidth(scaled_max_width)
        self.setMaximumHeight(scaled_max_height)
        self.setMinimumHeight(scaled_max_height)
        
        app = QApplication.instance()
        self.default_font_size = getattr(app, 'default_font_size', 8) if app else 8
        
        self._init_colors()
        self._create_layout()
        self._create_icon()
        self._create_labels()
    
    def _init_colors(self):
        """初始化颜色配置"""
        try:
            settings_manager = SettingsManager()
            self.base_color = settings_manager.get_setting("appearance.colors.base_color", "#212121")
            self.auxiliary_color = settings_manager.get_setting("appearance.colors.auxiliary_color", "#3D3D3D")
            self.normal_color = settings_manager.get_setting("appearance.colors.normal_color", "#717171")
            self.accent_color = settings_manager.get_setting("appearance.colors.accent_color", "#B036EE")
            self.secondary_color = settings_manager.get_setting("appearance.colors.secondary_color", "#FFFFFF")
        except Exception:
            self.base_color = "#212121"
            self.auxiliary_color = "#3D3D3D"
            self.normal_color = "#717171"
            self.accent_color = "#B036EE"
            self.secondary_color = "#FFFFFF"
    
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
        
        scaled_icon_size = int(38 * self.dpi_scale)
        self.icon_label.setFixedSize(scaled_icon_size, scaled_icon_size)
        
        self._update_icon()
        
        self.layout.addWidget(self.icon_label, alignment=Qt.AlignCenter)
    
    def _update_icon(self):
        """更新文件图标"""
        file_path = self.file_info.get("path", "")
        if not file_path:
            self._set_default_icon()
            return
        
        is_dir = self.file_info.get("is_dir", False)
        suffix = self.file_info.get("suffix", "").lower()
        
        try:
            if not is_dir and suffix in ["lnk", "exe", "url"]:
                scaled_icon_size = int(38 * self.dpi_scale)
                
                try:
                    from freeassetfilter.utils.icon_utils import get_highest_resolution_icon, hicon_to_pixmap, DestroyIcon
                    hicon = get_highest_resolution_icon(file_path, desired_size=256)
                    if hicon:
                        pixmap = hicon_to_pixmap(hicon, scaled_icon_size, None)
                        DestroyIcon(hicon)
                        if pixmap and not pixmap.isNull():
                            self._set_icon_pixmap(pixmap, scaled_icon_size)
                            return
                except Exception:
                    pass
            
            thumbnail_path = self._get_thumbnail_path(file_path)
            is_photo = suffix in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'tiff', 'avif', 'cr2', 'cr3', 'nef', 'arw', 'dng', 'orf']
            is_video = suffix in ['mp4', 'mov', 'avi', 'mkv', 'wmv', 'flv', 'webm', 'm4v', 'mpeg', 'mpg', 'mxf']
            
            if (is_photo or is_video) and os.path.exists(thumbnail_path):
                base_icon_size = int(38 * self.dpi_scale)
                scaled_icon_size = int(base_icon_size * 1.0)
                
                pixmap = QPixmap(thumbnail_path)
                self._set_icon_pixmap(pixmap, scaled_icon_size)
                return
            
            icon_path = self._get_icon_path()
            if icon_path and os.path.exists(icon_path):
                base_icon_size = int(38 * self.dpi_scale)
                
                svg_widget = None
                if icon_path.endswith("未知底板.svg"):
                    display_suffix = suffix.upper()
                    if len(display_suffix) > 5:
                        display_suffix = "FILE"
                    svg_widget = SvgRenderer.render_unknown_file_icon(icon_path, display_suffix, base_icon_size, self.dpi_scale)
                elif icon_path.endswith("压缩文件.svg"):
                    display_suffix = "." + suffix
                    svg_widget = SvgRenderer.render_unknown_file_icon(icon_path, display_suffix, base_icon_size, self.dpi_scale)
                else:
                    svg_widget = SvgRenderer.render_svg_to_widget(icon_path, base_icon_size, self.dpi_scale)
                
                if isinstance(svg_widget, QSvgWidget):
                    for child in self.icon_label.findChildren((QLabel, QSvgWidget)):
                        child.deleteLater()
                    svg_widget.setParent(self.icon_label)
                    svg_widget.setFixedSize(base_icon_size, base_icon_size)
                    svg_widget.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
                    svg_widget.setAttribute(Qt.WA_TranslucentBackground, True)
                    svg_widget.show()
                elif isinstance(svg_widget, QLabel):
                    for child in self.icon_label.findChildren((QLabel, QSvgWidget)):
                        child.deleteLater()
                    svg_widget.setParent(self.icon_label)
                    svg_widget.setFixedSize(base_icon_size, base_icon_size)
                    svg_widget.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
                    svg_widget.setAttribute(Qt.WA_TranslucentBackground, True)
                    svg_widget.show()
                elif isinstance(svg_widget, QWidget):
                    for child in self.icon_label.findChildren((QLabel, QSvgWidget, QWidget)):
                        child.deleteLater()
                    svg_widget.setParent(self.icon_label)
                    svg_widget.setFixedSize(base_icon_size, base_icon_size)
                    svg_widget.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
                    svg_widget.setAttribute(Qt.WA_TranslucentBackground, True)
                    svg_widget.show()
                else:
                    self._set_default_icon()
            else:
                self._set_default_icon()
        except Exception as e:
            print(f"更新文件图标失败: {e}")
            self._set_default_icon()
    
    def _set_icon_pixmap(self, pixmap, size):
        """设置图标Pixmap"""
        scaled_size = int(size * self.devicePixelRatio())
        if scaled_size > 0:
            scaled_pixmap = pixmap.scaled(scaled_size, scaled_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            scaled_pixmap.setDevicePixelRatio(self.devicePixelRatio())
            self.icon_label.setPixmap(scaled_pixmap)
    
    def _set_default_icon(self):
        """设置默认图标"""
        pixmap = QPixmap(self.icon_label.size())
        pixmap.fill(Qt.transparent)
        self.icon_label.setPixmap(pixmap)
    
    def _get_thumbnail_path(self, file_path):
        """获取缩略图路径"""
        import hashlib
        thumb_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "thumbnails")
        md5_hash = hashlib.md5(file_path.encode('utf-8'))
        file_hash = md5_hash.hexdigest()[:16]
        return os.path.join(thumb_dir, f"{file_hash}.png")
    
    def _get_icon_path(self):
        """获取文件图标路径"""
        icon_dir = os.path.join(os.path.dirname(__file__), "..", "icons")
        
        if self.file_info.get("is_dir", False):
            return os.path.join(icon_dir, "文件夹.svg")
        
        suffix = self.file_info.get("suffix", "").lower()
        
        video_formats = ["mp4", "mov", "avi", "mkv", "wmv", "flv", "webm", "m4v", "mpeg", "mpg", "mxf", "3gp", "vob", "m2ts", "ts", "mts"]
        image_formats = ["jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "svg", "avif", "cr2", "cr3", "nef", "arw", "dng", "orf"]
        audio_formats = ["mp3", "wav", "flac", "ogg", "wma", "aac", "m4a", "opus"]
        document_formats = ["pdf", "ppt", "pptx", "xls", "xlsx", "doc", "docx", "txt", "md", "rst", "rtf"]
        font_formats = ["ttf", "otf", "woff", "woff2", "eot"]
        archive_formats = ["zip", "rar", "7z", "tar", "gz", "bz2", "xz", "lzma", "iso", "cab", "arj"]
        
        if suffix in video_formats:
            return os.path.join(icon_dir, "视频.svg")
        elif suffix in image_formats:
            return os.path.join(icon_dir, "图像.svg")
        elif suffix == "pdf":
            return os.path.join(icon_dir, "PDF.svg")
        elif suffix in ["ppt", "pptx"]:
            return os.path.join(icon_dir, "PPT.svg")
        elif suffix in ["xls", "xlsx"]:
            return os.path.join(icon_dir, "表格.svg")
        elif suffix in ["doc", "docx"]:
            return os.path.join(icon_dir, "Word文档.svg")
        elif suffix in document_formats:
            return os.path.join(icon_dir, "文档.svg")
        elif suffix in font_formats:
            return os.path.join(icon_dir, "字体.svg")
        elif suffix in audio_formats:
            return os.path.join(icon_dir, "音乐.svg")
        elif suffix in archive_formats:
            return os.path.join(icon_dir, "压缩文件.svg")
        else:
            return os.path.join(icon_dir, "未知底板.svg")
    
    def _create_labels(self):
        """创建文本标签"""
        # 将文字大小保持默认为系统缩放的1.0倍
        scaled_font_size = int(self.default_font_size * 1.0)
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
        
        self._update_label_styles()
    
    def _update_name_label(self):
        """更新文件名显示"""
        text = self.file_info.get("name", "")
        font = self.name_label.font()
        font_metrics = QFontMetrics(font)
        
        # 扩大文件名显示宽度，以显示更多内容
        max_width = int(60 * self.dpi_scale)
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
                    self._touch_start_pos = event.pos()
                    self._is_touch_dragging = False
                elif event.button() == Qt.RightButton:
                    self._on_right_click(event)
                else:
                    return False
                return True
            elif event.type() == QEvent.MouseMove:
                if self._touch_start_pos is not None:
                    delta = event.pos() - self._touch_start_pos
                    if abs(delta.x()) > self._touch_drag_threshold or abs(delta.y()) > self._touch_drag_threshold:
                        self._is_touch_dragging = True
                return False
            elif event.type() == QEvent.MouseButtonRelease:
                if event.button() == Qt.LeftButton:
                    if self._touch_start_pos is not None and not self._is_touch_dragging:
                        self._on_click(event)
                    self._touch_start_pos = None
                    self._is_touch_dragging = False
                return True
            elif event.type() == QEvent.MouseButtonDblClick:
                if event.button() == Qt.LeftButton:
                    self._on_double_click(event)
                return True
            elif event.type() == QEvent.Enter:
                if not self._is_selected:
                    self._is_hovered = True
                    self._trigger_hover_animation()
                return False
            elif event.type() == QEvent.Leave:
                self._is_hovered = False
                self._trigger_leave_animation()
                self._touch_start_pos = None
                self._is_touch_dragging = False
                return False
        return super().eventFilter(obj, event)
    
    def _on_click(self, event):
        """处理左键点击"""
        self.clicked.emit(self.file_info)
    
    def _on_right_click(self, event):
        """处理右键点击 - 切换选中状态"""
        self.set_selected(not self._is_selected)
        self.right_clicked.emit(self.file_info)
    
    def _on_double_click(self, event):
        """处理双击"""
        self.double_clicked.emit(self.file_info)
    
    def _init_animations(self):
        """初始化卡片状态切换动画"""
        base_qcolor = QColor(self.base_color)
        auxiliary_qcolor = QColor(self.auxiliary_color)
        normal_qcolor = QColor(self.normal_color)
        accent_qcolor = QColor(self.accent_color)
        
        normal_bg = QColor(base_qcolor)
        hover_bg = QColor(auxiliary_qcolor)
        selected_bg = QColor(accent_qcolor)
        selected_bg.setAlpha(102)
        normal_border = QColor(auxiliary_qcolor)
        hover_border = QColor(normal_qcolor)
        selected_border = QColor(accent_qcolor)
        
        self._style_colors = {
            'normal_bg': normal_bg,
            'hover_bg': hover_bg,
            'selected_bg': selected_bg,
            'normal_border': normal_border,
            'hover_border': hover_border,
            'selected_border': selected_border
        }
        
        self._anim_bg_color = QColor(normal_bg)
        self._anim_border_color = QColor(normal_border)
        
        self._hover_anim_group = QParallelAnimationGroup(self)
        
        self._anim_hover_bg = QPropertyAnimation(self, b"anim_bg_color")
        self._anim_hover_bg.setStartValue(normal_bg)
        self._anim_hover_bg.setEndValue(hover_bg)
        self._anim_hover_bg.setDuration(150)
        self._anim_hover_bg.setEasingCurve(QEasingCurve.OutCubic)
        
        self._anim_hover_border = QPropertyAnimation(self, b"anim_border_color")
        self._anim_hover_border.setStartValue(normal_border)
        self._anim_hover_border.setEndValue(hover_border)
        self._anim_hover_border.setDuration(150)
        self._anim_hover_border.setEasingCurve(QEasingCurve.OutCubic)
        
        self._hover_anim_group.addAnimation(self._anim_hover_bg)
        self._hover_anim_group.addAnimation(self._anim_hover_border)
        
        self._leave_anim_group = QParallelAnimationGroup(self)
        
        self._anim_leave_bg = QPropertyAnimation(self, b"anim_bg_color")
        self._anim_leave_bg.setStartValue(hover_bg)
        self._anim_leave_bg.setEndValue(normal_bg)
        self._anim_leave_bg.setDuration(200)
        self._anim_leave_bg.setEasingCurve(QEasingCurve.InOutQuad)
        
        self._anim_leave_border = QPropertyAnimation(self, b"anim_border_color")
        self._anim_leave_border.setStartValue(hover_border)
        self._anim_leave_border.setEndValue(normal_border)
        self._anim_leave_border.setDuration(200)
        self._anim_leave_border.setEasingCurve(QEasingCurve.InOutQuad)
        
        self._leave_anim_group.addAnimation(self._anim_leave_bg)
        self._leave_anim_group.addAnimation(self._anim_leave_border)
        
        self._select_anim_group = QParallelAnimationGroup(self)
        
        self._anim_select_bg = QPropertyAnimation(self, b"anim_bg_color")
        self._anim_select_bg.setStartValue(normal_bg)
        self._anim_select_bg.setEndValue(selected_bg)
        self._anim_select_bg.setDuration(180)
        self._anim_select_bg.setEasingCurve(QEasingCurve.OutCubic)
        
        self._anim_select_border = QPropertyAnimation(self, b"anim_border_color")
        self._anim_select_border.setStartValue(normal_border)
        self._anim_select_border.setEndValue(selected_border)
        self._anim_select_border.setDuration(180)
        self._anim_select_border.setEasingCurve(QEasingCurve.OutCubic)
        
        self._select_anim_group.addAnimation(self._anim_select_bg)
        self._select_anim_group.addAnimation(self._anim_select_border)
        
        self._deselect_anim_group = QParallelAnimationGroup(self)
        
        self._anim_deselect_bg = QPropertyAnimation(self, b"anim_bg_color")
        self._anim_deselect_bg.setStartValue(selected_bg)
        self._anim_deselect_bg.setEndValue(normal_bg)
        self._anim_deselect_bg.setDuration(200)
        self._anim_deselect_bg.setEasingCurve(QEasingCurve.InOutQuad)
        
        self._anim_deselect_border = QPropertyAnimation(self, b"anim_border_color")
        self._anim_deselect_border.setStartValue(selected_border)
        self._anim_deselect_border.setEndValue(normal_border)
        self._anim_deselect_border.setDuration(200)
        self._anim_deselect_border.setEasingCurve(QEasingCurve.InOutQuad)
        
        self._deselect_anim_group.addAnimation(self._anim_deselect_bg)
        self._deselect_anim_group.addAnimation(self._anim_deselect_border)
        
        self._apply_animated_style()
    
    def _trigger_hover_animation(self):
        """触发悬停动画"""
        if not hasattr(self, '_style_colors'):
            self._update_styles()
            return
        
        self._leave_anim_group.stop()
        
        colors = self._style_colors
        if self._is_selected:
            self._anim_hover_bg.setStartValue(self._anim_bg_color)
            self._anim_hover_bg.setEndValue(colors['selected_bg'])
            self._anim_hover_border.setStartValue(self._anim_border_color)
            self._anim_hover_border.setEndValue(colors['selected_border'])
        else:
            self._anim_hover_bg.setStartValue(self._anim_bg_color)
            self._anim_hover_bg.setEndValue(colors['hover_bg'])
            self._anim_hover_border.setStartValue(self._anim_border_color)
            self._anim_hover_border.setEndValue(colors['hover_border'])
        
        self._hover_anim_group.start()
    
    def _trigger_leave_animation(self):
        """触发离开动画"""
        if not hasattr(self, '_style_colors'):
            self._update_styles()
            return
        
        if self._is_selected:
            return
        
        self._hover_anim_group.stop()
        
        colors = self._style_colors
        self._anim_leave_bg.setStartValue(self._anim_bg_color)
        self._anim_leave_bg.setEndValue(colors['normal_bg'])
        self._anim_leave_border.setStartValue(self._anim_border_color)
        self._anim_leave_border.setEndValue(colors['normal_border'])
        self._leave_anim_group.start()
    
    def _update_styles(self):
        """更新卡片和标签的完整样式"""
        self._update_card_style()
        self._update_label_styles()
    
    def _update_card_style(self):
        """更新卡片背景色和边框样式"""
        from PyQt5.QtGui import QColor
        
        scaled_border_radius = int(8 * self.dpi_scale)
        scaled_border_width = int(1 * self.dpi_scale)
        
        if self._is_selected:
            qcolor = QColor(self.accent_color)
            r, g, b = qcolor.red(), qcolor.green(), qcolor.blue()
            bg_color = f"rgba({r}, {g}, {b}, 102)"
            border_color = self.accent_color
        elif self._is_hovered:
            bg_color = self.auxiliary_color
            border_color = self.normal_color
        else:
            bg_color = self.base_color
            border_color = self.auxiliary_color
        
        self.setStyleSheet(f"background-color: {bg_color}; border: {scaled_border_width}px solid {border_color}; border-radius: {scaled_border_radius}px;")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.update()
    
    def _update_label_styles(self):
        """更新标签颜色样式"""
        label_style = f"color: {self.secondary_color}; background: transparent; border: none;"
        self.name_label.setStyleSheet(label_style)
        self.size_label.setStyleSheet(label_style)
        self.time_label.setStyleSheet(label_style)
    
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
        import datetime
        def debug(msg):
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            print(f"[{timestamp}] [FileBlockCard.set_selected] {msg}")
        
        debug(f"设置选中状态: {selected}, 当前状态: {self._is_selected}, 文件: {self.file_info['path']}")
        if self._is_selected != selected:
            self._is_selected = selected
            if selected:
                self._is_hovered = False
                self._trigger_select_animation()
            else:
                self._trigger_deselect_animation()
            self._update_label_styles()
            self.selection_changed.emit(self.file_info, selected)
    
    def _trigger_select_animation(self):
        """触发选中动画"""
        if not hasattr(self, '_style_colors'):
            self._update_styles()
            return
        
        self._hover_anim_group.stop()
        self._leave_anim_group.stop()
        
        colors = self._style_colors
        self._anim_select_bg.setStartValue(self._anim_bg_color)
        self._anim_select_bg.setEndValue(colors['selected_bg'])
        self._anim_select_border.setStartValue(self._anim_border_color)
        self._anim_select_border.setEndValue(colors['selected_border'])
        self._select_anim_group.start()
    
    def _trigger_deselect_animation(self):
        """触发取消选中动画"""
        if not hasattr(self, '_style_colors'):
            self._update_styles()
            return
        
        self._select_anim_group.stop()
        
        colors = self._style_colors
        self._anim_deselect_bg.setStartValue(self._anim_bg_color)
        self._anim_deselect_bg.setEndValue(colors['normal_bg'])
        self._anim_deselect_border.setStartValue(self._anim_border_color)
        self._anim_deselect_border.setEndValue(colors['normal_border'])
        self._deselect_anim_group.start()
    
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
        if self._flexible_width is not None:
            base_width = self._flexible_width
        else:
            base_width = int(42 * self.dpi_scale)
        return QSize(base_width, int(80 * self.dpi_scale))
    
    def set_flexible_width(self, width):
        """
        设置卡片动态宽度
        
        Args:
            width (int): 可用宽度（像素）
        """
        self._flexible_width = width
        min_width = int(35 * self.dpi_scale)
        max_width = int(500 * self.dpi_scale)
        constrained_width = max(min_width, min(width, max_width))
        self.setFixedWidth(constrained_width)
        self.updateGeometry()
