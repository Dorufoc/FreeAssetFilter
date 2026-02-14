#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

文件块卡片组件
可伸缩的文件卡片控件，支持多种交互状态和文件信息展示
支持长按拖拽功能
"""

import sys
import os

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy, QApplication, QGraphicsDropShadowEffect
from PySide6.QtCore import Qt, Signal, QEvent, QSize, QPropertyAnimation, Property, QEasingCurve, QParallelAnimationGroup, QTimer, QPoint
from PySide6.QtGui import QFont, QFontMetrics, QPixmap, QColor, QPainter, QCursor
from PySide6.QtSvgWidgets import QSvgWidget

from freeassetfilter.core.svg_renderer import SvgRenderer
from freeassetfilter.core.settings_manager import SettingsManager


class FileBlockCard(QWidget):
    """
    可伸缩文件卡片组件
    
    特性：
    - 最小横向宽度35，最大50（支持DPI缩放）
    - 圆角和边框设计
    - 四种状态：未选中态、hover态、选中态、预览态
    - 选中态不响应hover效果
    - 预览态边框使用secondary_color，宽度为选中态的2倍
    - 支持左键点击、右键点击、左键双击
    - 支持非线性动画过渡效果
    - 支持长按拖拽功能，拖拽到存储池选中文件，拖拽到预览器预览文件
    
    信号：
    - clicked: 点击信号，传递file_info
    - right_clicked: 右键点击信号，传递file_info
    - double_clicked: 双击信号，传递file_info
    - selection_changed: 选中状态变化信号，传递(file_info, is_selected)
    - preview_state_changed: 预览状态变化信号，传递(file_info, is_previewing)
    - drag_started: 拖拽开始信号，传递file_info
    - drag_ended: 拖拽结束信号，传递(file_info, drop_target_type)
    """
    
    clicked = Signal(dict)
    right_clicked = Signal(dict)
    double_clicked = Signal(dict)
    selection_changed = Signal(dict, bool)
    preview_state_changed = Signal(dict, bool)
    drag_started = Signal(dict)
    drag_ended = Signal(dict, str)
    
    @Property(QColor)
    def anim_bg_color(self):
        return self._anim_bg_color
    
    @anim_bg_color.setter
    def anim_bg_color(self, color):
        self._anim_bg_color = color
        self._apply_animated_style()
    
    @Property(QColor)
    def anim_border_color(self):
        return self._anim_border_color
    
    @anim_border_color.setter
    def anim_border_color(self, color):
        self._anim_border_color = color
        self._apply_animated_style()
    
    def _apply_animated_style(self):
        """应用动画颜色到卡片样式"""
        if not hasattr(self, '_style_colors') or not hasattr(self, '_anim_bg_color') or not hasattr(self, '_anim_border_color'):
            return
        
        try:
            scaled_border_radius = int(8 * self.dpi_scale)
            normal_border_width = int(1 * self.dpi_scale)
            # 预览态使用2倍边框宽度
            scaled_border_width = normal_border_width * 2 if self._is_previewing else normal_border_width
            
            r, g, b, a = self._anim_bg_color.red(), self._anim_bg_color.green(), self._anim_bg_color.blue(), self._anim_bg_color.alpha()
            bg_color = f"rgba({r}, {g}, {b}, {a})"
            
            # 预览态使用secondary_color作为边框颜色，其他状态使用动画边框颜色
            if self._is_previewing:
                border_color = self.secondary_color
            else:
                border_color = self._anim_border_color.name()
            
            self.setStyleSheet(f"background-color: {bg_color}; border: {scaled_border_width}px solid {border_color}; border-radius: {scaled_border_radius}px;")
        except Exception:
            pass
    
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
        self._is_previewing = False  # 预览态标志
        
        self._touch_drag_threshold = int(10 * self.dpi_scale)
        self._touch_start_pos = None
        self._is_touch_dragging = False
        
        # 长按拖拽相关属性
        self._long_press_timer = QTimer(self)
        self._long_press_timer.setSingleShot(True)
        self._long_press_timer.timeout.connect(self._on_long_press)
        self._long_press_duration = 500  # 长按触发时间（毫秒）
        self._is_long_pressing = False
        self._drag_start_pos = None
        self._drag_card = None  # 拖拽时显示的浮动卡片
        self._is_dragging = False
        self._original_opacity = 1.0
        
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
        scaled_max_height = int(75 * self.dpi_scale)
        self.setMinimumWidth(scaled_min_width)
        # 移除最大宽度限制，让卡片可以自适应填充可用空间
        self.setMaximumHeight(scaled_max_height)
        self.setMinimumHeight(scaled_max_height)
        
        app = QApplication.instance()
        self.default_font_size = getattr(app, 'default_font_size', 8) if app else 8
        self.global_font = getattr(app, 'global_font', QFont()) if app else QFont()

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
                    for child in self.icon_label.findChildren(QLabel):
                        child.deleteLater()
                    for child in self.icon_label.findChildren(QSvgWidget):
                        child.deleteLater()
                    svg_widget.setParent(self.icon_label)
                    svg_widget.setFixedSize(base_icon_size, base_icon_size)
                    svg_widget.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
                    svg_widget.setAttribute(Qt.WA_TranslucentBackground, True)
                    svg_widget.show()
                elif isinstance(svg_widget, QLabel):
                    for child in self.icon_label.findChildren(QLabel):
                        child.deleteLater()
                    for child in self.icon_label.findChildren(QSvgWidget):
                        child.deleteLater()
                    svg_widget.setParent(self.icon_label)
                    svg_widget.setFixedSize(base_icon_size, base_icon_size)
                    svg_widget.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
                    svg_widget.setAttribute(Qt.WA_TranslucentBackground, True)
                    svg_widget.show()
                elif isinstance(svg_widget, QWidget):
                    for child in self.icon_label.findChildren(QLabel):
                        child.deleteLater()
                    for child in self.icon_label.findChildren(QSvgWidget):
                        child.deleteLater()
                    for child in self.icon_label.findChildren(QWidget):
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
        # 直接使用全局字体，让Qt6自动处理DPI缩放
        # 小字体使用全局字体的0.85倍
        small_font_size = int(self.global_font.pointSize() * 0.85)

        font = QFont(self.global_font)

        small_font = QFont(self.global_font)
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

        # 根据卡片实际宽度动态计算文本最大宽度
        # 减去边距和布局间距，确保文本不会溢出
        layout_margins = self.layout.contentsMargins()
        horizontal_margin = layout_margins.left() + layout_margins.right()
        max_width = self.width() - horizontal_margin - int(4 * self.dpi_scale)
        max_width = max(int(35 * self.dpi_scale), max_width)  # 确保最小宽度

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
            from PySide6.QtCore import QDateTime
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
    
    def _is_touch_optimization_enabled(self):
        """
        检查触控操作优化是否启用

        Returns:
            bool: 触控操作优化是否启用
        """
        try:
            settings_manager = SettingsManager()
            return settings_manager.get_setting("file_selector.touch_optimization", True)
        except Exception:
            return True

    def _is_mouse_buttons_swapped(self):
        """
        检查鼠标按钮是否交换

        Returns:
            bool: 鼠标按钮是否交换
        """
        try:
            settings_manager = SettingsManager()
            return settings_manager.get_setting("file_selector.mouse_buttons_swap", False)
        except Exception:
            return False

    def eventFilter(self, obj, event):
        """事件过滤器，处理鼠标事件"""
        if obj == self:
            # 检查鼠标按钮是否交换
            buttons_swapped = self._is_mouse_buttons_swapped()

            if event.type() == QEvent.MouseButtonPress:
                if event.button() == Qt.LeftButton:
                    # 物理左键按下
                    self._touch_start_pos = event.pos()
                    self._is_touch_dragging = False
                    # 只有在触控操作优化开启时才启动长按定时器
                    if self._is_touch_optimization_enabled():
                        self._long_press_timer.start(self._long_press_duration)
                    self._drag_start_pos = event.globalPos()
                elif event.button() == Qt.RightButton:
                    # 物理右键按下
                    if buttons_swapped:
                        # 交换时，物理右键执行原左键功能（预览）
                        self._touch_start_pos = event.pos()
                        self._is_touch_dragging = False
                        if self._is_touch_optimization_enabled():
                            self._long_press_timer.start(self._long_press_duration)
                        self._drag_start_pos = event.globalPos()
                    else:
                        # 不交换时，物理右键执行原右键功能（选择/取消选择）
                        self._on_right_click(event)
                else:
                    return False
                return True
            elif event.type() == QEvent.MouseMove:
                if self._is_dragging and self._drag_card:
                    # 拖拽过程中，更新浮动卡片位置
                    self._update_drag_card_position(event.globalPos())
                    return True
                elif self._touch_start_pos is not None:
                    delta = event.pos() - self._touch_start_pos
                    if abs(delta.x()) > self._touch_drag_threshold or abs(delta.y()) > self._touch_drag_threshold:
                        self._is_touch_dragging = True
                        # 如果移动距离超过阈值，取消长按
                        if not self._is_dragging:
                            self._long_press_timer.stop()
                            self._is_long_pressing = False
                return False
            elif event.type() == QEvent.MouseButtonRelease:
                if event.button() == Qt.LeftButton:
                    # 物理左键释放
                    if self._is_dragging:
                        # 拖拽结束，处理放置逻辑
                        self._end_drag(event.globalPos())
                    elif self._touch_start_pos is not None and not self._is_touch_dragging:
                        # 如果不是拖拽，处理点击
                        if buttons_swapped:
                            # 交换时，物理左键执行原右键功能（选择/取消选择）
                            self._on_right_click(event)
                        else:
                            # 不交换时，物理左键执行原左键功能（预览）
                            self._on_click(event)
                    # 停止长按定时器
                    self._long_press_timer.stop()
                    self._is_long_pressing = False
                    self._touch_start_pos = None
                    self._is_touch_dragging = False
                elif event.button() == Qt.RightButton:
                    # 物理右键释放
                    if buttons_swapped:
                        # 交换时，物理右键执行原左键释放逻辑（预览）
                        if self._is_dragging:
                            self._end_drag(event.globalPos())
                        elif self._touch_start_pos is not None and not self._is_touch_dragging:
                            self._on_click(event)
                        self._long_press_timer.stop()
                        self._is_long_pressing = False
                        self._touch_start_pos = None
                        self._is_touch_dragging = False
                    # 不交换时，物理右键已在press时处理，release时不做额外操作
                return True
            elif event.type() == QEvent.MouseButtonDblClick:
                if event.button() == Qt.LeftButton:
                    # 物理左键双击
                    # 双击时取消长按
                    self._long_press_timer.stop()
                    self._is_long_pressing = False
                    if buttons_swapped:
                        # 交换时，物理左键双击执行原右键双击逻辑（选择/取消选择）
                        self._on_right_click(event)
                    else:
                        # 不交换时，物理左键双击执行原左键双击逻辑（预览）
                        self._on_double_click(event)
                elif event.button() == Qt.RightButton:
                    # 物理右键双击
                    if buttons_swapped:
                        # 交换时，物理右键双击执行原左键双击逻辑（预览）
                        self._long_press_timer.stop()
                        self._is_long_pressing = False
                        self._on_double_click(event)
                return True
            elif event.type() == QEvent.Enter:
                if not self._is_selected and not self._is_dragging:
                    self._is_hovered = True
                    self._trigger_hover_animation()
                return False
            elif event.type() == QEvent.Leave:
                if not self._is_dragging:
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
        
        # 预览态动画组
        self._preview_anim_group = QParallelAnimationGroup(self)
        
        self._anim_preview_bg = QPropertyAnimation(self, b"anim_bg_color")
        self._anim_preview_bg.setDuration(180)
        self._anim_preview_bg.setEasingCurve(QEasingCurve.OutCubic)
        
        self._anim_preview_border = QPropertyAnimation(self, b"anim_border_color")
        self._anim_preview_border.setDuration(180)
        self._anim_preview_border.setEasingCurve(QEasingCurve.OutCubic)
        
        self._preview_anim_group.addAnimation(self._anim_preview_bg)
        self._preview_anim_group.addAnimation(self._anim_preview_border)
        
        # 取消预览态动画组
        self._unpreview_anim_group = QParallelAnimationGroup(self)
        
        self._anim_unpreview_bg = QPropertyAnimation(self, b"anim_bg_color")
        self._anim_unpreview_bg.setDuration(200)
        self._anim_unpreview_bg.setEasingCurve(QEasingCurve.InOutQuad)
        
        self._anim_unpreview_border = QPropertyAnimation(self, b"anim_border_color")
        self._anim_unpreview_border.setDuration(200)
        self._anim_unpreview_border.setEasingCurve(QEasingCurve.InOutQuad)
        
        self._unpreview_anim_group.addAnimation(self._anim_unpreview_bg)
        self._unpreview_anim_group.addAnimation(self._anim_unpreview_border)
    
    def _trigger_hover_animation(self):
        """触发悬停动画"""
        if not hasattr(self, '_style_colors'):
            self._update_styles()
            return
        
        # 预览态和选中态不响应hover效果
        if self._is_selected or self._is_previewing:
            return
        
        self._leave_anim_group.stop()
        
        colors = self._style_colors
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
        
        # 预览态和选中态不响应leave效果
        if self._is_selected or self._is_previewing:
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
        from PySide6.QtGui import QColor
        
        scaled_border_radius = int(8 * self.dpi_scale)
        normal_border_width = int(1 * self.dpi_scale)
        
        if self._is_previewing:
            # 预览态：背景保持选中态或普通态，边框使用secondary_color，宽度为2倍
            if self._is_selected:
                # 预览态+选中态：使用选中态背景
                qcolor = QColor(self.accent_color)
                r, g, b = qcolor.red(), qcolor.green(), qcolor.blue()
                bg_color = f"rgba({r}, {g}, {b}, 102)"
            else:
                # 预览态+未选中态：使用普通背景
                bg_color = self.base_color
            # 预览态边框使用secondary_color，宽度为2倍
            border_color = self.secondary_color
            scaled_border_width = normal_border_width * 2
        elif self._is_selected:
            # 选中态
            qcolor = QColor(self.accent_color)
            r, g, b = qcolor.red(), qcolor.green(), qcolor.blue()
            bg_color = f"rgba({r}, {g}, {b}, 102)"
            border_color = self.accent_color
            scaled_border_width = normal_border_width
        elif self._is_hovered:
            # 悬停态
            bg_color = self.auxiliary_color
            border_color = self.normal_color
            scaled_border_width = normal_border_width
        else:
            # 普通态
            bg_color = self.base_color
            border_color = self.auxiliary_color
            scaled_border_width = normal_border_width
        
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
        
        # debug(f"设置选中状态: {selected}, 当前状态: {self._is_selected}, 文件: {self.file_info['path']}")
        if self._is_selected != selected:
            self._is_selected = selected
            if selected:
                self._is_hovered = False
                self._trigger_select_animation()
            else:
                self._trigger_deselect_animation()
            self._update_label_styles()
            self.selection_changed.emit(self.file_info, selected)
    
    def set_previewing(self, previewing):
        """
        设置卡片预览状态
        
        Args:
            previewing (bool): 是否处于预览态
        """
        if self._is_previewing != previewing:
            self._is_previewing = previewing
            if previewing:
                self._is_hovered = False
                self._trigger_preview_animation()
            else:
                self._trigger_unpreview_animation()
            self._update_card_style()
            self._update_label_styles()
            self.preview_state_changed.emit(self.file_info, previewing)
    
    def _trigger_preview_animation(self):
        """触发预览态动画"""
        if not hasattr(self, '_style_colors'):
            self._update_styles()
            return
        
        # 停止其他动画
        self._hover_anim_group.stop()
        self._leave_anim_group.stop()
        self._select_anim_group.stop()
        self._deselect_anim_group.stop()
        
        colors = self._style_colors
        secondary_qcolor = QColor(self.secondary_color)
        
        # 根据当前选中状态决定背景色
        if self._is_selected:
            target_bg = colors['selected_bg']
        else:
            target_bg = colors['normal_bg']
        
        self._anim_preview_bg.setStartValue(self._anim_bg_color)
        self._anim_preview_bg.setEndValue(target_bg)
        self._anim_preview_border.setStartValue(self._anim_border_color)
        self._anim_preview_border.setEndValue(secondary_qcolor)
        
        self._preview_anim_group.start()
    
    def _trigger_unpreview_animation(self):
        """触发取消预览态动画"""
        if not hasattr(self, '_style_colors'):
            self._update_styles()
            return
        
        self._preview_anim_group.stop()
        
        colors = self._style_colors
        
        # 根据当前选中状态决定目标状态
        if self._is_selected:
            target_bg = colors['selected_bg']
            target_border = colors['selected_border']
        else:
            target_bg = colors['normal_bg']
            target_border = colors['normal_border']
        
        self._anim_unpreview_bg.setStartValue(self._anim_bg_color)
        self._anim_unpreview_bg.setEndValue(target_bg)
        self._anim_unpreview_border.setStartValue(self._anim_border_color)
        self._anim_unpreview_border.setEndValue(target_border)
        
        self._unpreview_anim_group.start()
    
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
    
    def is_previewing(self):
        """获取卡片预览状态"""
        return self._is_previewing
    
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
        # 移除最大宽度限制，让卡片可以自适应填充可用空间
        constrained_width = max(min_width, width)
        self.setFixedWidth(constrained_width)
        self.updateGeometry()
        # 宽度变化后重新更新文本显示
        self._update_name_label()
    
    def resizeEvent(self, event):
        """处理大小变化事件，重新计算文本省略"""
        super().resizeEvent(event)
        # 宽度变化时重新更新文件名显示
        if hasattr(self, 'name_label') and self.name_label:
            self._update_name_label()

    def _on_long_press(self):
        """
        处理长按事件
        当用户长按卡片时触发，开始拖拽操作
        """
        self._is_long_pressing = True
        self._start_drag()
    
    def _start_drag(self):
        """
        开始拖拽操作
        创建浮动卡片并设置原始卡片为半透明
        """
        self._is_dragging = True
        
        # 设置原始卡片为半透明 - 使用样式表实现
        self._set_dragging_appearance(True)
        
        # 创建浮动拖拽卡片
        self._create_drag_card()
        
        # 发出拖拽开始信号
        self.drag_started.emit(self.file_info)
        
        # 改变鼠标样式
        self.setCursor(QCursor(Qt.ClosedHandCursor))
    
    def _set_dragging_appearance(self, is_dragging):
        """
        设置拖拽时的外观样式
        
        Args:
            is_dragging (bool): 是否正在拖拽
        """
        if is_dragging:
            # 保存当前样式
            self._original_style = self.styleSheet()
            
            # 创建半透明背景色
            base_qcolor = QColor(self.base_color)
            r, g, b = base_qcolor.red(), base_qcolor.green(), base_qcolor.blue()
            bg_color = f"rgba({r}, {g}, {b}, 102)"  # 40% 透明度
            
            border_qcolor = QColor(self.auxiliary_color)
            br, bg, bb = border_qcolor.red(), border_qcolor.green(), border_qcolor.blue()
            border_color = f"rgba({br}, {bg}, {bb}, 102)"
            
            scaled_border_radius = int(8 * self.dpi_scale)
            scaled_border_width = int(1 * self.dpi_scale)
            
            # 应用半透明样式
            self.setStyleSheet(
                f"background-color: {bg_color}; "
                f"border: {scaled_border_width}px solid {border_color}; "
                f"border-radius: {scaled_border_radius}px;"
            )
            
            # 设置子控件透明度
            self.icon_label.setStyleSheet("background: transparent; border: none; opacity: 0.4;")
            self.name_label.setStyleSheet(f"color: {self.secondary_color}; background: transparent; border: none; opacity: 0.4;")
            self.size_label.setStyleSheet(f"color: {self.secondary_color}; background: transparent; border: none; opacity: 0.4;")
            self.time_label.setStyleSheet(f"color: {self.secondary_color}; background: transparent; border: none; opacity: 0.4;")
        else:
            # 恢复正常样式
            self._update_styles()
    
    def _create_drag_card(self):
        """
        创建浮动拖拽卡片
        使用与原卡片完全一致的样式
        """
        if self._drag_card:
            self._drag_card.deleteLater()
        
        # 创建浮动卡片，使用与原卡片相同的尺寸
        self._drag_card = QWidget(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        
        # 使用当前卡片的实际尺寸（考虑自适应宽度算法）
        # 如果设置了灵活宽度则使用，否则使用默认尺寸
        if self._flexible_width is not None:
            card_width = self._flexible_width
        else:
            card_width = int(42 * self.dpi_scale)  # 默认建议宽度
        card_height = int(75 * self.dpi_scale)
        self._drag_card.setFixedSize(card_width, card_height)
        
        # 设置对象名以便样式表选择器匹配
        self._drag_card.setObjectName("DragCard")
        
        # 设置卡片样式
        # 外层透明，内层圆角区域显示背景色
        scaled_border_radius = int(8 * self.dpi_scale)
        scaled_border_width = int(1 * self.dpi_scale)
        self._drag_card.setStyleSheet(
            f"#DragCard {{"
            f"  background-color: transparent; "
            f"  border: none;"
            f"}}"
        )
        
        # 启用透明背景
        self._drag_card.setAttribute(Qt.WA_TranslucentBackground, True)
        self._drag_card.setAutoFillBackground(False)
        
        # 创建主布局
        main_layout = QVBoxLayout(self._drag_card)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 创建内部卡片（带圆角和背景色）
        from PySide6.QtWidgets import QFrame
        inner_card = QFrame()
        inner_card.setObjectName("InnerCard")
        inner_card.setStyleSheet(
            f"#InnerCard {{"
            f"  background-color: {self.base_color}; "
            f"  border: {scaled_border_width}px solid {self.normal_color}; "
            f"  border-radius: {scaled_border_radius}px;"
            f"}}"
            f"#InnerCard QLabel {{ background-color: transparent; border: none; }}"
        )
        inner_card.setAutoFillBackground(True)
        
        # 创建内部布局
        layout = QVBoxLayout(inner_card)
        layout.setSpacing(int(2 * self.dpi_scale))
        layout.setContentsMargins(
            int(4 * self.dpi_scale), int(4 * self.dpi_scale),
            int(4 * self.dpi_scale), int(4 * self.dpi_scale)
        )
        layout.setAlignment(Qt.AlignCenter)
        
        # 创建图标 - 与原卡片一致
        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet("background: transparent; border: none;")
        scaled_icon_size = int(38 * self.dpi_scale)
        icon_label.setFixedSize(scaled_icon_size, scaled_icon_size)
        
        # 重新渲染图标（使用与原卡片相同的逻辑）
        try:
            file_path = self.file_info.get("path", "")
            is_dir = self.file_info.get("is_dir", False)
            suffix = self.file_info.get("suffix", "").lower()
            
            icon_loaded = False
            
            # 1. 对于 lnk/exe/url 文件，使用 Windows 图标提取
            if not is_dir and suffix in ["lnk", "exe", "url"]:
                try:
                    from freeassetfilter.utils.icon_utils import get_highest_resolution_icon, hicon_to_pixmap, DestroyIcon
                    hicon = get_highest_resolution_icon(file_path, desired_size=256)
                    if hicon:
                        pixmap = hicon_to_pixmap(hicon, scaled_icon_size, None)
                        DestroyIcon(hicon)
                        if pixmap and not pixmap.isNull():
                            icon_label.setPixmap(pixmap)
                            icon_loaded = True
                except Exception:
                    pass
            
            # 2. 对于图片/视频，使用缩略图
            if not icon_loaded:
                thumbnail_path = self._get_thumbnail_path(file_path)
                is_photo = suffix in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'tiff', 'avif', 'cr2', 'cr3', 'nef', 'arw', 'dng', 'orf']
                is_video = suffix in ['mp4', 'mov', 'avi', 'mkv', 'wmv', 'flv', 'webm', 'm4v', 'mpeg', 'mpg', 'mxf']
                
                if (is_photo or is_video) and os.path.exists(thumbnail_path):
                    pixmap = QPixmap(thumbnail_path)
                    if not pixmap.isNull():
                        icon_label.setPixmap(pixmap.scaled(scaled_icon_size, scaled_icon_size,
                                                           Qt.KeepAspectRatio, Qt.SmoothTransformation))
                        icon_loaded = True
            
            # 3. 其他文件使用 SVG 图标
            if not icon_loaded:
                icon_path = self._get_icon_path()
                if icon_path and os.path.exists(icon_path):
                    svg_widget = None
                    if icon_path.endswith("未知底板.svg"):
                        display_suffix = suffix.upper()
                        if len(display_suffix) > 5:
                            display_suffix = "FILE"
                        svg_widget = SvgRenderer.render_unknown_file_icon(icon_path, display_suffix, scaled_icon_size, self.dpi_scale)
                    elif icon_path.endswith("压缩文件.svg"):
                        display_suffix = "." + suffix
                        svg_widget = SvgRenderer.render_unknown_file_icon(icon_path, display_suffix, scaled_icon_size, self.dpi_scale)
                    else:
                        svg_widget = SvgRenderer.render_svg_to_widget(icon_path, scaled_icon_size, self.dpi_scale)
                    
                    if svg_widget:
                        svg_widget.setParent(icon_label)
                        svg_widget.setFixedSize(scaled_icon_size, scaled_icon_size)
                        svg_widget.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
                        svg_widget.setAttribute(Qt.WA_TranslucentBackground, True)
                        svg_widget.show()
        except Exception as e:
            print(f"拖拽卡片图标渲染失败: {e}")
        
        layout.addWidget(icon_label, alignment=Qt.AlignCenter)

        # 创建文件名标签 - 与原卡片一致，直接使用全局字体让Qt6自动处理DPI缩放
        font = QFont(self.global_font)

        name_label = QLabel()
        name_label.setAlignment(Qt.AlignCenter)
        name_label.setFont(font)
        name_label.setStyleSheet(f"color: {self.secondary_color}; background: transparent; border: none;")
        name_label.setWordWrap(False)

        # 显示文件名（使用与原卡片相同的截断逻辑）
        text = self.file_info.get("name", "")
        font_metrics = QFontMetrics(font)
        # 根据拖拽卡片实际宽度动态计算文本最大宽度
        drag_card_width = self._drag_card.width()
        max_width = drag_card_width - int(4 * self.dpi_scale)
        max_width = max(int(35 * self.dpi_scale), max_width)  # 确保最小宽度
        elided_text = font_metrics.elidedText(text, Qt.ElideRight, max_width)
        name_label.setText(elided_text)

        layout.addWidget(name_label)

        # 创建文件大小标签 - 与原卡片一致，使用全局字体的0.85倍
        small_font = QFont(self.global_font)
        small_font.setPointSize(int(self.global_font.pointSize() * 0.85))
        
        size_label = QLabel()
        size_label.setAlignment(Qt.AlignCenter)
        size_label.setFont(small_font)
        size_label.setStyleSheet(f"color: {self.secondary_color}; background: transparent; border: none;")
        
        # 显示文件大小
        if self.file_info.get("is_dir", False):
            size_label.setText("文件夹")
        else:
            size = self.file_info.get("size", 0)
            size_label.setText(self._format_size_for_drag(size))
        
        layout.addWidget(size_label)
        
        # 创建时间标签 - 与原卡片一致
        time_label = QLabel()
        time_label.setAlignment(Qt.AlignCenter)
        time_label.setFont(small_font)
        time_label.setStyleSheet(f"color: {self.secondary_color}; background: transparent; border: none;")
        
        # 显示时间
        created = self.file_info.get("created", "")
        if created:
            from PySide6.QtCore import QDateTime
            try:
                dt = QDateTime.fromString(created, Qt.ISODate)
                time_label.setText(dt.toString("yyyy-MM-dd"))
            except Exception:
                time_label.setText(created[:10] if len(created) >= 10 else created)
        else:
            time_label.setText("")
        
        layout.addWidget(time_label)
        
        # 将内部卡片添加到主布局
        main_layout.addWidget(inner_card)
        
        # 显示拖拽卡片在鼠标位置
        cursor_pos = QCursor.pos()
        card_width = self._drag_card.width()
        card_height = self._drag_card.height()
        self._drag_card.move(cursor_pos.x() - card_width // 2, cursor_pos.y() - card_height // 2)
        self._drag_card.show()
    
    def _format_size_for_drag(self, size):
        """格式化文件大小（用于拖拽卡片）"""
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
    
    def _update_drag_card_position(self, global_pos):
        """
        更新拖拽卡片位置
        
        Args:
            global_pos: 鼠标全局位置
        """
        if self._drag_card:
            card_width = self._drag_card.width()
            card_height = self._drag_card.height()
            self._drag_card.move(global_pos.x() - card_width // 2, global_pos.y() - card_height // 2)
    
    def _end_drag(self, global_pos):
        """
        结束拖拽操作
        
        Args:
            global_pos: 鼠标释放时的全局位置
        """
        # 恢复原始卡片样式
        self._set_dragging_appearance(False)
        
        # 恢复鼠标样式
        self.setCursor(QCursor(Qt.ArrowCursor))
        
        # 检测放置目标
        drop_target = self._detect_drop_target(global_pos)
        
        # 发出拖拽结束信号
        self.drag_ended.emit(self.file_info, drop_target)
        
        # 清理拖拽卡片
        if self._drag_card:
            self._drag_card.deleteLater()
            self._drag_card = None
        
        self._is_dragging = False
        self._is_long_pressing = False
    
    def _detect_drop_target(self, global_pos):
        """
        检测拖拽放置的目标区域
        
        Args:
            global_pos: 鼠标全局位置
            
        Returns:
            str: 放置目标类型 ('staging_pool', 'previewer', 'none')
        """
        # 获取主窗口
        main_window = self.window()
        if not main_window:
            return 'none'
        
        # 将全局坐标转换为窗口坐标
        window_pos = main_window.mapFromGlobal(global_pos)
        
        # 检查是否在文件存储池区域
        if hasattr(main_window, 'file_staging_pool'):
            staging_pool = main_window.file_staging_pool
            if staging_pool and staging_pool.isVisible():
                staging_rect = staging_pool.rect()
                staging_global_pos = staging_pool.mapToGlobal(staging_rect.topLeft())
                staging_global_rect = staging_rect.translated(staging_global_pos - staging_pool.pos())
                if staging_global_rect.contains(global_pos):
                    return 'staging_pool'
        
        # 检查是否在统一预览器区域
        if hasattr(main_window, 'unified_previewer'):
            previewer = main_window.unified_previewer
            if previewer and previewer.isVisible():
                previewer_rect = previewer.rect()
                previewer_global_pos = previewer.mapToGlobal(previewer_rect.topLeft())
                previewer_global_rect = previewer_rect.translated(previewer_global_pos - previewer.pos())
                if previewer_global_rect.contains(global_pos):
                    return 'previewer'
        
        return 'none'
    
    def is_dragging(self):
        """
        获取当前是否正在拖拽
        
        Returns:
            bool: 是否正在拖拽
        """
        return self._is_dragging
