#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

统一文件预览器组件
根据文件类型自动选择合适的预览组件
"""

import sys
import os

# 添加项目根目录到Python路径，解决直接运行时的导入问题
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# 导入日志模块
from freeassetfilter.utils.app_logger import info, debug, warning, error, exception_details

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QGroupBox, QGridLayout, QSizePolicy, QPushButton, QMessageBox, QApplication, QSplitter
)

# 导入自定义按钮
from freeassetfilter.widgets.D_widgets import CustomButton
from PySide6.QtCore import Qt, Signal, QTimer, QThread
from PySide6.QtGui import QFont

from freeassetfilter.components.file_info_previewer import FileInfoPreviewer
from freeassetfilter.components.folder_content_list import FolderContentList
from freeassetfilter.components.archive_browser import ArchiveBrowser
from freeassetfilter.widgets.D_widgets import CustomMessageBox
from freeassetfilter.widgets.progress_widgets import D_ProgressBar
from freeassetfilter.core.thumbnail_manager import get_thumbnail_manager


class UnifiedPreviewer(QWidget):
    """
    统一文件预览器组件
    根据文件类型自动选择合适的预览组件
    """

    # 信号定义
    open_in_selector_requested = Signal(str, object)  # 请求在文件选择器中打开路径，传递(目录路径, 文件信息)
    preview_started = Signal(dict)  # 预览开始信号，传递文件信息
    preview_cleared = Signal()  # 预览清除信号

    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 获取应用实例和DPI缩放因子
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QFont
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        self.global_font = getattr(app, 'global_font', QFont())
        
        # 设置组件字体
        self.setFont(self.global_font)
        
        # 设置焦点策略，确保组件能够接收键盘事件
        self.setFocusPolicy(Qt.StrongFocus)
        
        # 初始化当前预览的文件信息
        self.current_file_info = None
        
        # 初始化文件信息查看器
        self.file_info_viewer = FileInfoPreviewer()
        
        # 初始化当前预览组件
        self.current_preview_widget = None
        self.current_preview_type = None
        
        # 初始化进度条弹窗
        self.progress_dialog = None
        self.is_cancelled = False
        # 初始化临时PDF文件路径，用于文档预览
        self.temp_pdf_path = None
        # 预览加载状态标志，防止快速点击导致多个预览组件同时运行
        self.is_loading_preview = False
        
        # 保存主窗口引用，避免循环导入和运行时查找
        self.main_window = parent
        
        self._current_settings_window = None
        self._scheduled_preview_cleanup = False

        # 初始化UI
        self.init_ui()
    
    def _get_theme_colors(self):
        """
        获取当前主题颜色
        """
        app = QApplication.instance()
        colors = {
            "window_background": "#f1f3f5",
            "base_color": "#212121",
            "normal_color": "#717171",
            "secondary_color": "#FFFFFF",
        }

        if hasattr(app, "settings_manager"):
            colors["window_background"] = app.settings_manager.get_setting("appearance.colors.auxiliary_color", colors["window_background"])
            colors["base_color"] = app.settings_manager.get_setting("appearance.colors.base_color", colors["base_color"])
            colors["normal_color"] = app.settings_manager.get_setting("appearance.colors.normal_color", colors["normal_color"])
            colors["secondary_color"] = app.settings_manager.get_setting("appearance.colors.secondary_color", colors["secondary_color"])

        return colors

    def update_theme(self):
        """
        增量刷新统一预览器主题，不重建预览组件
        """
        colors = self._get_theme_colors()
        border_radius = int(8 * self.dpi_scale)

        self.setStyleSheet(f"background-color: {colors['window_background']}; border: none;")

        if hasattr(self, "content_splitter") and self.content_splitter:
            self.content_splitter.setStyleSheet(
                f"QSplitter {{ background-color: {colors['base_color']}; border-radius: {border_radius}px; }} "
                f"QSplitter::handle {{ background-color: {colors['base_color']}; }}"
            )

        if hasattr(self, "preview_area") and self.preview_area:
            self.preview_area.setStyleSheet(
                f"#PreviewArea {{ background-color: {colors['window_background']}; border: 1px solid {colors['normal_color']}; }}"
            )

        if hasattr(self, "info_group") and self.info_group:
            self.info_group.setStyleSheet(
                f"#InfoGroup {{ background-color: {colors['window_background']}; border: 1px solid {colors['normal_color']}; }}"
            )

        if hasattr(self, "default_label") and self.default_label:
            self.default_label.setStyleSheet(f"color: {colors['normal_color']};")

        for button_name in (
            "copy_to_clipboard_button",
            "open_with_system_button",
            "locate_in_selector_button",
            "clear_preview_button",
        ):
            button = getattr(self, button_name, None)
            if button and hasattr(button, "update_theme"):
                try:
                    button.update_theme()
                except Exception:
                    pass

        if hasattr(self, "file_info_viewer") and self.file_info_viewer and hasattr(self.file_info_viewer, "update_theme"):
            try:
                self.file_info_viewer.update_theme()
            except Exception:
                pass

        if hasattr(self, "current_preview_widget") and self.current_preview_widget and hasattr(self.current_preview_widget, "update_theme"):
            try:
                self.current_preview_widget.update_theme()
            except Exception:
                pass

        self.update()

    def stop_preview(self):
        """
        安全停止所有预览组件，释放资源
        在主题更新或设置保存前调用，避免阻塞
        """
        try:
            if hasattr(self, 'current_preview_widget') and self.current_preview_widget:
                from freeassetfilter.components.video_player import VideoPlayer
                from freeassetfilter.components.text_previewer import TextPreviewWidget
                
                if isinstance(self.current_preview_widget, VideoPlayer):
                    old_widget = self.current_preview_widget
                    self.preview_layout.removeWidget(old_widget)
                    self.current_preview_widget = None
                    
                    old_widget.close()
                    old_widget.setParent(None)
                
                elif isinstance(self.current_preview_widget, TextPreviewWidget):
                    old_widget = self.current_preview_widget
                    if hasattr(old_widget, 'cleanup'):
                        old_widget.cleanup()
                    self.preview_layout.removeWidget(old_widget)
                    self.current_preview_widget = None
                    old_widget.setParent(None)
                
                else:
                    old_widget = self.current_preview_widget
                    self.preview_layout.removeWidget(old_widget)
                    self.current_preview_widget.setParent(None)
                    self.current_preview_widget = None
            
            self.current_file_info = None
            self.is_loading_preview = False
            
        except Exception as e:
            exception_details("停止预览组件失败", e)
    
    def init_ui(self):
        """
        初始化用户界面
        """
        # 应用DPI缩放因子到布局参数（调整为原始的一半）
        scaled_spacing = int(5 * self.dpi_scale)
        scaled_margin = int(5 * self.dpi_scale)
        scaled_font_size = int(6 * self.dpi_scale)
        scaled_control_margin = int(2 * self.dpi_scale)
        
        # 创建主布局 - 使用QSplitter实现可拖拽调整
        main_layout = QVBoxLayout(self)
        app = QApplication.instance()
        background_color = "#f1f3f5"
        base_color = "#212121"
        normal_color = "#717171"
        if hasattr(app, 'settings_manager'):
            background_color = app.settings_manager.get_setting("appearance.colors.auxiliary_color", "#f1f3f5")
            base_color = app.settings_manager.get_setting("appearance.colors.base_color", "#212121")
            normal_color = app.settings_manager.get_setting("appearance.colors.normal_color", "#717171")
        self.setStyleSheet(f"background-color: {background_color}; border: none;")
        main_layout.setSpacing(scaled_spacing)
        main_layout.setContentsMargins(scaled_margin, scaled_margin, scaled_margin, scaled_margin)
        
        # 创建垂直分割器，实现预览区域和文件信息区域的拖拽调整
        self.content_splitter = QSplitter(Qt.Vertical)
        self.content_splitter.setContentsMargins(0, 0, 0, 0)
        self.content_splitter.setHandleWidth(10)
        border_radius = int(8 * self.dpi_scale)
        self.content_splitter.setStyleSheet(f"QSplitter {{ background-color: {base_color}; border-radius: {border_radius}px; }} QSplitter::handle {{ background-color: {base_color}; }}")
        
        # 创建预览内容区域
        self.preview_area = QWidget()
        self.preview_area.setObjectName("PreviewArea")
        self.preview_area.setStyleSheet(f"#PreviewArea {{ background-color: {background_color}; border: 1px solid {normal_color}; }}")
        self.preview_layout = QVBoxLayout(self.preview_area)
        
        # 创建预览控制栏（右上角按钮）- 放在预览组件上方
        self.control_layout = QHBoxLayout()
        self.control_layout.setContentsMargins(0, 0, 0, scaled_control_margin)
        self.control_layout.setAlignment(Qt.AlignRight)
        
        self.preview_layout.addLayout(self.control_layout)
        
        # 添加默认提示信息
        self.default_label = QLabel("请选择一个文件进行预览")
        self.default_label.setAlignment(Qt.AlignCenter)

        # 使用全局字体，让Qt6自动处理DPI缩放
        self.default_label.setFont(self.global_font)
        self.default_label.setStyleSheet("color: #999;")
        self.preview_layout.addWidget(self.default_label)
        
        # 将预览区域添加到分割器
        self.content_splitter.addWidget(self.preview_area)
        
        # 创建文件信息区域
        # 使用 QWidget 替代 QGroupBox，避免空白标题导致的边框缺口问题
        self.info_group = QWidget()
        self.info_group.setObjectName("InfoGroup")
        self.info_group.setStyleSheet(f"#InfoGroup {{ background-color: {background_color}; border: 1px solid {normal_color}; }}")
        self.info_layout = QVBoxLayout(self.info_group)
        self.info_layout.setContentsMargins(5, 5, 5, 5)
        
        # 创建文件信息查看器的UI
        self.file_info_widget = self.file_info_viewer.get_ui()
        self.info_layout.addWidget(self.file_info_widget)
        
        # 将文件信息区域添加到分割器
        self.content_splitter.addWidget(self.info_group)
        
        # 设置分割器初始比例 (预览区域:文件信息区域 = 2:1)
        total_height = 600  # 默认总高度
        preview_height = int(total_height * (2/3))
        info_height = int(total_height * (1/3))
        self.content_splitter.setSizes([preview_height, info_height])
        
        # 将分割器添加到主布局
        main_layout.addWidget(self.content_splitter, 1)
        
        # 创建按钮布局容器
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(int(10 * self.dpi_scale))
        buttons_layout.setContentsMargins(0, 0, 0, 0)

        # 创建"复制到剪切板"按钮（图标模式，使用share.svg，位于默认方式打开按钮左侧）
        share_icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "icons", "share.svg")
        self.copy_to_clipboard_button = CustomButton(share_icon_path, button_type="normal", display_mode="icon", tooltip_text="复制文件")
        self.copy_to_clipboard_button.clicked.connect(self._on_copy_to_clipboard_button_clicked)
        self.copy_to_clipboard_button.hide()
        buttons_layout.addWidget(self.copy_to_clipboard_button)

        # 创建"使用系统默认方式打开"按钮
        self.open_with_system_button = CustomButton("使用系统默认方式打开", button_type="secondary")
        self.open_with_system_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.open_with_system_button.clicked.connect(self._open_file_with_system)
        self.open_with_system_button.hide()
        buttons_layout.addWidget(self.open_with_system_button, 1)

        # 创建"定位到所在目录"按钮（强调样式）
        self.locate_in_selector_button = CustomButton("定位到所在目录", button_type="primary")
        self.locate_in_selector_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.locate_in_selector_button.clicked.connect(self._locate_file_in_selector)
        self.locate_in_selector_button.hide()
        buttons_layout.addWidget(self.locate_in_selector_button, 1)

        # 创建"清除预览"按钮（图标模式，使用close.svg）
        close_icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "icons", "close.svg")
        self.clear_preview_button = CustomButton(close_icon_path, button_type="normal", display_mode="icon", tooltip_text="清除预览")
        self.clear_preview_button.clicked.connect(self._on_clear_preview_button_clicked)
        self.clear_preview_button.hide()
        buttons_layout.addWidget(self.clear_preview_button)

        main_layout.addLayout(buttons_layout)
    
    def set_file(self, file_info):
        """
        设置要预览的文件
        
        Args:
            file_info (dict): 文件信息字典
        """
        debug(f"接收到文件选择信号: {file_info.get('name', 'unknown') if file_info else 'None'}")
        
        # 检查是否正在加载预览，如果是则忽略新的请求
        if self.is_loading_preview:
            debug("预览加载中，忽略新请求")
            return
        
        self.current_file_info = file_info
        
        # 发出预览开始信号，通知文件选择器和存储池更新预览态
        self.preview_started.emit(file_info)
        
        # 更新文件信息查看器
        self.file_info_viewer.set_file(file_info)
        
        # 根据文件类型显示不同的预览内容
        self._show_preview()
    
    def _show_preview(self):
        """
        根据文件类型显示预览内容，确保只有一个预览组件在工作
        """
        debug("开始处理文件预览")
        
        if not self.current_file_info:
            self._clear_preview()
            self.preview_layout.addWidget(self.default_label)
            self.default_label.show()
            self.open_with_system_button.hide()
            self.copy_to_clipboard_button.hide()
            self.locate_in_selector_button.hide()
            self.clear_preview_button.hide()
            return
        
        # 获取文件路径和类型
        file_path = self.current_file_info["path"]
        file_type = self.current_file_info["suffix"]
        
        # 确定预览类型
        preview_type = None
        if self.current_file_info["is_dir"]:
            preview_type = "dir"
        elif file_type in ["jpg", "jpeg", "png", "gif", "bmp", "tiff", "webp", "svg", "avif", "heic", "cr2", "cr3", "nef", "arw", "dng", "orf", "ico", "icon", "psd"]:
            preview_type = "image"
        elif file_type in ["mp4", "avi", "mov", "mkv", "m4v", "mxf", "3gp", "mpg", "wmv", "webm", "vob", "ogv", "rmvb", "m2ts", "ts", "mts"]:
            preview_type = "video"
        elif file_type in ["mp3", "wav", "flac", "ogg", "wma", "m4a", "aiff", "ape", "opus"]:
            preview_type = "audio"
        elif file_type in ["doc", "docx", "xls", "xlsx", "ppt", "pptx"]:
            preview_type = "document"
        elif file_type in ["pdf"]:
            preview_type = "pdf"
        elif file_type in ["txt", "md", "rst", "py", "java", "cpp", "js", "html", "css", "php", "c", "h", "cs", "go", "rb", "swift", "kt", "yml", "yaml", "json", "xml"]:
            preview_type = "text"
        elif file_type in ["zip", "rar", "tar", "gz", "tgz", "bz2", "xz", "7z", "iso"]:
            preview_type = "archive"
        elif file_type in ["ttf", "otf", "woff", "woff2", "eot"]:
            preview_type = "font"
        else:
            preview_type = "unknown"
        
        debug(f"预览类型: {preview_type}, 当前类型: {self.current_preview_type}")
        
        # 检查当前预览组件是否可以处理该类型
        # 如果预览类型相同，直接更新组件
        if preview_type == self.current_preview_type and self.current_preview_widget:
            # 更新现有组件
            debug("复用现有预览组件")
            self._update_preview_widget(file_path, preview_type)
        else:
            # 设置加载状态为True，防止快速点击触发多个预览
            self.is_loading_preview = True
            debug(f"创建新预览组件: {preview_type}")
            
            # 显示进度条弹窗
            title = "正在加载预览"
            message = "正在准备预览组件..."
            if preview_type == "video":
                title = "正在加载视频"
                message = "正在准备视频播放器..."
            elif preview_type == "audio":
                title = "正在加载音频"
                message = "正在准备音频播放器..."
            elif preview_type == "pdf":
                title = "正在加载PDF"
                message = "正在准备PDF阅读器..."
            elif preview_type == "archive":
                title = "正在加载压缩包"
                message = "正在准备压缩包浏览器..."
            
            self._show_progress_dialog(title, message)
            
            # 清除旧预览组件
            self._clear_preview()
            
            # 创建后台线程加载预览
            self._preview_thread = self.PreviewLoaderThread(file_path, preview_type, self)
            self._preview_thread.preview_created.connect(self._on_preview_created)
            self._preview_thread.preview_error.connect(self._on_preview_error)
            self._preview_thread.preview_progress.connect(self._on_progress_updated)
            self._preview_thread.start()
    
    def _update_preview_widget(self, file_path, preview_type):
        """
        更新现有预览组件的内容
        
        Args:
            file_path (str): 文件路径
            preview_type (str): 预览类型
        """
        try:
            if preview_type == "dir":
                # 文件夹预览 - 更新路径
                if hasattr(self.current_preview_widget, 'set_path'):
                    self.current_preview_widget.set_path(file_path)
            elif preview_type == "image":
                # 图片预览 - 更新图片
                if hasattr(self.current_preview_widget, 'set_image'):
                    self.current_preview_widget.set_image(file_path)
            elif preview_type == "video":
                # 视频预览 - 重新加载视频
                if hasattr(self.current_preview_widget, 'load_media'):
                    self.current_preview_widget.load_media(file_path, is_audio=False)
                    self.current_preview_widget.play()
            elif preview_type == "audio":
                # 音频预览 - 重新加载音频
                if hasattr(self.current_preview_widget, 'load_media'):
                    self.current_preview_widget.load_media(file_path, is_audio=True)
            elif preview_type == "pdf":
                # PDF预览 - 重新加载PDF
                if hasattr(self.current_preview_widget, 'load_file_from_path'):
                    self.current_preview_widget.load_file_from_path(file_path)
            elif preview_type == "text":
                # 文本预览 - 重新加载文本
                if hasattr(self.current_preview_widget, 'load_file'):
                    self.current_preview_widget.load_file(file_path)
            elif preview_type == "archive":
                # 压缩包预览 - 更新压缩包路径
                if hasattr(self.current_preview_widget, 'set_archive_path'):
                    self.current_preview_widget.set_archive_path(file_path)
            
            # 显示操作按钮
            self._show_action_buttons()
            
        except Exception as e:
            exception_details("更新预览组件失败", e)
            self._show_error_with_copy_button(f"预览更新失败: {str(e)}")
    
    def _clear_preview(self):
        """
        清除当前预览组件
        """
        # 清除预览区域中的所有组件（除了控制栏）
        while self.preview_layout.count() > 1:  # 保留控制栏（索引0）
            item = self.preview_layout.takeAt(1)
            if item and item.widget():
                widget = item.widget()
                widget.setParent(None)
                widget.deleteLater()
        
        self.current_preview_widget = None
        self.current_preview_type = None
        self.preview_cleared.emit()
    
    def _show_action_buttons(self):
        """
        显示操作按钮
        """
        self.open_with_system_button.show()
        self.copy_to_clipboard_button.show()
        self.locate_in_selector_button.show()
        self.clear_preview_button.show()
    
    def _on_clear_preview_button_clicked(self):
        """
        清除预览按钮点击事件
        """
        self._clear_preview()
        self.preview_layout.addWidget(self.default_label)
        self.default_label.show()
        self.open_with_system_button.hide()
        self.copy_to_clipboard_button.hide()
        self.locate_in_selector_button.hide()
        self.clear_preview_button.hide()
        self.current_file_info = None
    
    def _on_copy_to_clipboard_button_clicked(self):
        """
        复制到剪贴板按钮点击事件
        """
        if self.current_file_info:
            file_path = self.current_file_info.get("path", "")
            if file_path:
                self._copy_to_clipboard(file_path)
                info(f"文件路径已复制: {file_path}")
    
    def _open_file_with_system(self):
        """
        使用系统默认方式打开文件
        """
        if self.current_file_info:
            file_path = self.current_file_info.get("path", "")
            if file_path and os.path.exists(file_path):
                try:
                    import subprocess
                    subprocess.Popen(['start', '', file_path], shell=True)
                    debug(f"使用系统默认方式打开文件: {file_path}")
                except Exception as e:
                    exception_details("打开文件失败", e)
                    self._show_error_with_copy_button(f"打开文件失败: {str(e)}")
    
    def _locate_file_in_selector(self):
        """
        在文件选择器中定位文件
        """
        if self.current_file_info:
            file_path = self.current_file_info.get("path", "")
            if file_path:
                dir_path = os.path.dirname(file_path) if not self.current_file_info.get("is_dir", False) else file_path
                self.open_in_selector_requested.emit(dir_path, self.current_file_info)
                debug(f"请求在文件选择器中定位: {dir_path}")
    
    def _show_error_with_copy_button(self, error_message):
        """
        显示带复制按钮的错误信息
        
        Args:
            error_message (str): 错误信息
        """
        # 清除预览区域
        self._clear_preview()
        
        # 创建错误信息容器
        error_container = QWidget()
        error_container.setStyleSheet("background-color: transparent;")
        error_layout = QVBoxLayout(error_container)
        error_layout.setSpacing(10)
        error_layout.setContentsMargins(0, 0, 0, 0)
        
        # 显示错误信息
        error_label = QLabel(error_message)
        error_label.setAlignment(Qt.AlignCenter)
        error_label.setStyleSheet("color: red; font-weight: bold;")
        error_layout.addWidget(error_label)
        
        # 添加复制按钮
        copy_button = CustomButton("复制错误信息", button_type="secondary")
        copy_button.setFixedWidth(int(120 * self.dpi_scale))
        copy_button.clicked.connect(lambda: self._copy_to_clipboard(error_message))
        copy_button_layout = QHBoxLayout()
        copy_button_layout.addStretch()
        copy_button_layout.addWidget(copy_button)
        copy_button_layout.addStretch()
        error_layout.addLayout(copy_button_layout)
        
        self.preview_layout.addWidget(error_container)
        self.current_preview_widget = error_container
        self.current_preview_type = "error"
        
        # 隐藏操作按钮
        self.open_with_system_button.hide()
        self.copy_to_clipboard_button.hide()
        self.locate_in_selector_button.hide()
        self.clear_preview_button.show()
    
    def _show_text_preview(self, file_path):
        """
        显示文本预览
        
        Args:
            file_path (str): 文本文件路径
        """
        try:
            from freeassetfilter.components.text_previewer import TextPreviewWidget
            
            # 创建文本预览组件
            text_previewer = TextPreviewWidget()
            text_previewer.load_file(file_path)
            
            self.preview_layout.addWidget(text_previewer, 1)
            self.current_preview_widget = text_previewer
            self.current_preview_type = "text"
            
            self._show_action_buttons()
            
        except Exception as e:
            exception_details("文本预览失败", e)
            self._show_error_with_copy_button(f"文本预览失败: {str(e)}")
        finally:
            self.is_loading_preview = False
    
    def _show_image_preview(self, file_path):
        """
        显示图片预览
        
        Args:
            file_path (str): 图片文件路径
        """
        try:
            from freeassetfilter.components.image_previewer import ImagePreviewer
            
            # 创建图片预览组件
            image_previewer = ImagePreviewer()
            image_previewer.set_image(file_path)
            
            self.preview_layout.addWidget(image_previewer, 1)
            self.current_preview_widget = image_previewer
            self.current_preview_type = "image"
            
            self._show_action_buttons()
            
        except Exception as e:
            exception_details("图片预览失败", e)
            self._show_error_with_copy_button(f"图片预览失败: {str(e)}")
        finally:
            self.is_loading_preview = False

    def _is_animated_image(self, file_path):
        """
        检测图片是否为动画格式
        
        Args:
            file_path (str): 图片文件路径
            
        Returns:
            bool: 是否为动画图片
        """
        try:
            from PIL import Image
            with Image.open(file_path) as img:
                try:
                    return getattr(img, 'is_animated', False) or img.n_frames > 1
                except AttributeError:
                    return False
        except ImportError:
            return False
        except (AttributeError, OSError, ValueError) as e:
            debug(f'检查GIF动画时出错: {e}')
            return False
    
    def _show_video_preview(self, file_path):
        """
        显示视频预览
        进度条已在_show_preview中显示，将在PDF渲染完成后关闭
        
        Args:
            file_path (str): 视频文件路径
        """
        try:
            from freeassetfilter.components.video_player import VideoPlayer
            from freeassetfilter.core.settings_manager import SettingsManager
            
            # 从设置中读取播放器配置
            settings_manager = SettingsManager()
            enable_detach = settings_manager.get_setting("player.enable_fullscreen", False)
            initial_volume = settings_manager.get_player_volume()
            initial_speed = settings_manager.get_player_speed()
            
            # 创建视频播放器，传递初始设置
            video_player = VideoPlayer(
                playback_mode="video",
                show_detach_button=enable_detach,
                initial_volume=initial_volume,
                initial_speed=initial_speed
            )
            
            self.preview_layout.addWidget(video_player, 1)
            self.current_preview_widget = video_player
            self.current_preview_type = "video"

            video_player.load_media(file_path, is_audio=False)
            video_player.play()
            
            debug(f"视频预览组件已创建: {file_path}")
        except Exception as e:
            exception_details("视频预览失败", e)
            error_message = f"视频预览失败: {str(e)}"
            self._show_error_with_copy_button(error_message)
        finally:
            self.is_loading_preview = False
    
    def focusInEvent(self, event):
        """
        处理焦点进入事件
        - 确保组件获得焦点时能够接收键盘事件
        """
        super().focusInEvent(event)
    
    def _show_audio_preview(self, file_path):
        """
        显示音频预览
        进度条已在_show_preview中显示并在_on_preview_created中关闭
        
        Args:
            file_path (str): 音频文件路径
        """
        debug(f"开始加载音频: {file_path}")
        try:
            # 使用视频播放器组件处理音频文件，因为它已经支持音频播放
            from freeassetfilter.components.video_player import VideoPlayer
            from freeassetfilter.core.settings_manager import SettingsManager
            
            # 从设置中读取播放器配置
            settings_manager = SettingsManager()
            enable_detach = settings_manager.get_setting("player.enable_fullscreen", False)
            initial_volume = settings_manager.get_player_volume()
            initial_speed = settings_manager.get_player_speed()
            
            # 创建视频播放器（支持音频播放），传递初始设置
            # 音频模式下隐藏LUT按钮和分离窗口按钮
            debug("创建音频播放器实例")
            audio_player = VideoPlayer(
                playback_mode="audio",
                show_lut_controls=False,
                show_detach_button=False,
                initial_volume=initial_volume,
                initial_speed=initial_speed
            )
            
            # 先添加到布局，确保widget被正确初始化
            self.preview_layout.addWidget(audio_player, 1)
            self.current_preview_widget = audio_player
            self.current_preview_type = "audio"

            # 然后加载媒体文件
            debug("加载音频文件")
            audio_player.load_media(file_path, is_audio=True)
            debug("音频预览完成")
        except Exception as e:
            error_message = f"音频预览失败: {str(e)}"
            debug(f"音频预览异常: {error_message}")
            self._show_error_with_copy_button(error_message)
        finally:
            self.is_loading_preview = False
    
    def _show_pdf_preview(self, file_path):
        """
        显示PDF预览
        进度条已在_show_preview中显示并在_on_preview_created中关闭
        
        Args:
            file_path (str): PDF文件路径
        """
        try:
            # 尝试导入PDF预览器组件
            from freeassetfilter.components.pdf_previewer import PDFPreviewer
            
            # 创建PDF预览器
            pdf_previewer = PDFPreviewer()
            # 连接PDF渲染完成信号
            pdf_previewer.pdf_render_finished.connect(self._on_pdf_render_finished)
            
            # 加载PDF文件，开始渲染
            pdf_previewer.load_file_from_path(file_path)
            
            self.preview_layout.addWidget(pdf_previewer, 1)  # 设置伸展因子1，使预览组件占据剩余空间
            self.current_preview_widget = pdf_previewer
            self.current_preview_type = "pdf"
        except Exception as e:
            error_message = f"PDF预览失败: {str(e)}"
            self._show_error_with_copy_button(error_message)
            # 发生错误时也关闭进度条弹窗
            self._on_file_read_finished()
    
    def _show_progress_dialog(self, title, message):
        """
        显示进度条弹窗
        
        Args:
            title (str): 弹窗标题
            message (str): 弹窗消息
        """
        # 如果已经存在进度条弹窗，先关闭
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
        
        # 创建进度条
        progress_bar = D_ProgressBar(is_interactive=False)
        progress_bar.setRange(0, 1000)
        progress_bar.setValue(0)
        
        # 创建进度条弹窗
        self.progress_dialog = CustomMessageBox(self)
        self.progress_dialog.set_title(title)
        self.progress_dialog.set_text(message)
        self.progress_dialog.set_progress(progress_bar)
        self.progress_dialog.set_buttons(["取消"], orientations=Qt.Horizontal)
        
        # 连接取消按钮信号
        self.progress_dialog.buttonClicked.connect(self._on_cancel_progress)
        
        # 显示弹窗（非模态，允许主程序继续响应）
        self.progress_dialog.show()
    
    def _on_progress_updated(self, progress, status):
        """
        更新进度条进度
        
        Args:
            progress (int): 进度值(0-100)
            status (str): 状态描述
        """
        if self.progress_dialog:
            # 更新进度条值
            progress_widget = self.progress_dialog._progress
            if progress_widget:
                progress_widget.setValue(progress)
            # 更新状态文本
            self.progress_dialog.set_text(status)
    
    def _on_cancel_progress(self, button_index):
        """
        取消文件读取操作
        
        Args:
            button_index (int): 按钮索引
        """
        self.is_cancelled = True
        # 关闭进度条弹窗
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
        # 取消当前预览组件的文件读取操作
        if self.current_preview_widget and hasattr(self.current_preview_widget, 'cancel_file_read'):
            self.current_preview_widget.cancel_file_read()
        # 取消后台加载线程
        if hasattr(self, '_preview_thread') and self._preview_thread and self._preview_thread.isRunning():
            self._preview_thread.cancel()
            self._preview_thread.wait(1000)  # 等待1秒让线程结束
        # 如果有模拟进度定时器，停止它
        if hasattr(self, '_progress_timer') and self._progress_timer:
            self._progress_timer.stop()
            self._progress_timer.deleteLater()
            delattr(self, '_progress_timer')
    
    def _on_file_read_finished(self):
        """
        文件读取完成，关闭进度条弹窗
        """
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
        # 如果有模拟进度定时器，停止它
        if hasattr(self, '_progress_timer') and self._progress_timer:
            self._progress_timer.stop()
            self._progress_timer.deleteLater()
            delattr(self, '_progress_timer')

    def _on_pdf_render_finished(self):
        """
        PDF渲染完成，关闭进度条弹窗
        """
        debug("PDF渲染完成")
        self._on_file_read_finished()
    
    def _copy_to_clipboard(self, text):
        """
        将文本复制到剪贴板
        
        Args:
            text (str): 要复制的文本
        """
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
    
    def _on_preview_created(self, preview_widget, preview_type):
        """
        预览准备完成，在主线程中创建预览组件并添加到布局中
        
        Args:
            preview_widget: 预览组件实例（不再使用，改为在主线程创建）
            preview_type (str): 预览类型
        """
        try:
            # 注意：对于文档类型，我们不在这里关闭进度条弹窗，而是在转换完成后关闭
            if preview_type != "document":
                # 关闭进度条弹窗
                self._on_file_read_finished()
            
            # 获取文件路径
            file_path = self.current_file_info["path"]
            
            # 在主线程中创建预览组件
            created_widget = None
            
            if preview_type == "dir":
                # 文件夹预览
                from freeassetfilter.components.folder_content_list import FolderContentList
                created_widget = FolderContentList()
                created_widget.set_path(file_path)
                # 连接信号：请求在文件选择器中打开路径
                created_widget.open_in_selector_requested.connect(self.open_in_selector_requested.emit)
            elif preview_type == "image":
                # 图片预览
                self._show_image_preview(file_path)
                return  # _show_image_preview已经处理了组件添加
            elif preview_type == "video":
                # 视频预览
                self._show_video_preview(file_path)
                return  # _show_video_preview已经处理了组件添加
            elif preview_type == "audio":
                # 音频预览
                self._show_audio_preview(file_path)
                return  # _show_audio_preview已经处理了组件添加
            elif preview_type == "pdf":
                # PDF预览
                self._show_pdf_preview(file_path)
                return  # _show_pdf_preview已经处理了组件添加
            elif preview_type == "text":
                # 文本预览
                self._show_text_preview(file_path)
                return  # _show_text_preview已经处理了组件添加
            elif preview_type == "archive":
                # 压缩包预览
                from freeassetfilter.components.archive_browser import ArchiveBrowser
                created_widget = ArchiveBrowser()
                created_widget.set_archive_path(file_path)
            elif preview_type == "document":
                # 文档预览：转换为PDF后预览
                self._show_document_preview(file_path)
                return  # _show_document_preview已经处理了组件添加
            elif preview_type == "font":
                # 字体预览
                self._show_font_preview(file_path)
                return  # _show_font_preview已经处理了组件添加
            elif preview_type == "unknown":
                # 不支持的文件类型，显示普通提示文字
                # 创建普通信息容器
                info_container = QWidget()
                info_container.setStyleSheet("background-color: transparent;")
                info_layout = QVBoxLayout(info_container)
                info_layout.setSpacing(10)
                info_layout.setContentsMargins(0, 0, 0, 0)
                
                # 显示普通信息
                info_message = f"暂不支持预览该文件类型\n\n文件路径：{file_path}"
                info_label = QLabel(info_message)
                info_label.setAlignment(Qt.AlignCenter)
                
                # 启用自动换行，确保文本根据宽度调整
                info_label.setWordWrap(True)

                # 使用全局字体，让Qt6自动处理DPI缩放
                info_label.setFont(self.global_font)
                info_label.setStyleSheet("color: #999;")
                
                info_layout.addWidget(info_label)
                
                self.preview_layout.addWidget(info_container)
                self.current_preview_widget = info_container
                self.current_preview_type = "info"
                return

            # 添加创建的组件到布局
            if created_widget:
                self.preview_layout.addWidget(created_widget, 1)  # 设置伸展因子1，使预览组件占据剩余空间
                self.current_preview_widget = created_widget
            
        except Exception as e:
            exception_details("创建预览组件失败", e)
            # 创建错误信息容器
            error_container = QWidget()
            error_container.setStyleSheet("background-color: transparent;")
            error_layout = QVBoxLayout(error_container)
            error_layout.setSpacing(10)
            error_layout.setContentsMargins(0, 0, 0, 0)
            
            # 显示错误信息
            full_error_message = f"创建预览组件失败: {str(e)}"
            error_label = QLabel(full_error_message)
            error_label.setAlignment(Qt.AlignCenter)
            error_label.setStyleSheet("color: red; font-weight: bold;")
            error_layout.addWidget(error_label)
            
            # 添加复制按钮
            copy_button = CustomButton("复制错误信息", button_type="secondary")
            copy_button.setFixedWidth(int(120 * self.dpi_scale))
            copy_button.clicked.connect(lambda: self._copy_to_clipboard(full_error_message))
            copy_button_layout = QHBoxLayout()
            copy_button_layout.addStretch()
            copy_button_layout.addWidget(copy_button)
            copy_button_layout.addStretch()
            error_layout.addLayout(copy_button_layout)
            
            self.preview_layout.addWidget(error_container)
            self.current_preview_widget = error_container
            self.current_preview_type = "error"
        finally:
            # 无论成功还是失败，都将加载状态设置为False，恢复接收新的预览请求
            self.is_loading_preview = False
            
            # 清理线程资源
            if hasattr(self, '_preview_thread') and self._preview_thread:
                try:
                    self._preview_thread.deleteLater()
                except (RuntimeError, AttributeError) as e:
                    debug(f'删除预览线程时出错: {e}')
                self._preview_thread = None
    
    def _on_preview_error(self, error_message):
        """
        预览创建失败，显示错误信息
        
        Args:
            error_message (str): 错误信息
        """
        try:
            # 关闭进度条弹窗
            self._on_file_read_finished()
            
            # 创建错误信息容器
            error_container = QWidget()
            error_container.setStyleSheet("background-color: transparent;")
            error_layout = QVBoxLayout(error_container)
            error_layout.setSpacing(10)
            error_layout.setContentsMargins(0, 0, 0, 0)
            
            # 显示错误信息
            full_error_message = f"预览失败: {error_message}"
            error_label = QLabel(full_error_message)
            error_label.setAlignment(Qt.AlignCenter)
            error_label.setStyleSheet("color: red; font-weight: bold;")
            error_layout.addWidget(error_label)
            
            # 添加复制按钮
            copy_button = CustomButton("复制错误信息", button_type="secondary")
            copy_button.setFixedWidth(int(120 * self.dpi_scale))
            copy_button.clicked.connect(lambda: self._copy_to_clipboard(full_error_message))
            copy_button_layout = QHBoxLayout()
            copy_button_layout.addStretch()
            copy_button_layout.addWidget(copy_button)
            copy_button_layout.addStretch()
            error_layout.addLayout(copy_button_layout)
            
            self.preview_layout.addWidget(error_container)
            self.current_preview_widget = error_container
            self.current_preview_type = "error"
        finally:
            # 无论成功还是失败，都将加载状态设置为False，恢复接收新的预览请求
            self.is_loading_preview = False
            
            # 清理线程资源
            if hasattr(self, '_preview_thread') and self._preview_thread:
                try:
                    self._preview_thread.deleteLater()
                except (RuntimeError, AttributeError) as e:
                    debug(f'删除预览线程时出错: {e}')
                self._preview_thread = None

    class PreviewLoaderThread(QThread):
        """
        预览加载后台线程
        用于在后台线程中创建预览组件和加载媒体文件，避免阻塞主线程
        优化：避免在后台线程中创建UI组件，只处理媒体加载逻辑
        """
        # 信号定义
        preview_created = Signal(object, str)  # 预览组件创建完成，参数：组件实例，预览类型
        preview_error = Signal(str)  # 预览创建失败，参数：错误信息
        preview_progress = Signal(int, str)  # 预览进度更新，参数：进度(0-100)，状态描述

        def __init__(self, file_path, preview_type, parent=None):
            """
            初始化预览加载线程

            Args:
                file_path (str): 要预览的文件路径
                preview_type (str): 预览类型
                parent (QObject, optional): 父对象，默认为 None
            """
            # 使用 super() 正确调用父类初始化方法
            super().__init__(parent)
            self.file_path = file_path
            self.preview_type = preview_type
            self.is_cancelled = False

        def run(self):
            """
            后台线程执行逻辑
            注意：PyQt的UI组件必须在主线程中创建，所以我们只在后台线程中处理媒体加载
            """
            try:
                self.preview_progress.emit(10, "正在准备预览...")

                # 注意：UI组件必须在主线程中创建，所以我们只在后台线程中处理非UI逻辑
                # 实际的UI组件创建将在主线程中完成
                self.preview_progress.emit(100, "预览准备完成")
                self.preview_created.emit(None, self.preview_type)
            except Exception as e:
                self.preview_error.emit(str(e))

        def cancel(self):
            """
            取消预览加载
            """
            self.is_cancelled = True

    def _show_document_preview(self, file_path):
        """
        显示文档预览（Office文档转换为PDF后预览）
        
        Args:
            file_path (str): 文档文件路径
        """
        try:
            from freeassetfilter.components.document_converter import DocumentConverter
            from freeassetfilter.components.pdf_previewer import PDFPreviewer
            
            # 创建文档转换器
            converter = DocumentConverter()
            
            # 转换文档为PDF
            def on_conversion_finished(success, pdf_path, error_msg):
                if success and pdf_path and os.path.exists(pdf_path):
                    # 保存临时PDF路径，用于后续清理
                    self.temp_pdf_path = pdf_path
                    
                    # 创建PDF预览器
                    pdf_previewer = PDFPreviewer()
                    pdf_previewer.load_file_from_path(pdf_path)
                    
                    self.preview_layout.addWidget(pdf_previewer, 1)
                    self.current_preview_widget = pdf_previewer
                    self.current_preview_type = "document"
                    
                    self._show_action_buttons()
                else:
                    error_msg = error_msg or "文档转换失败"
                    self._show_error_with_copy_button(f"文档预览失败: {error_msg}")
                
                # 关闭进度条弹窗
                self._on_file_read_finished()
                self.is_loading_preview = False
            
            # 连接转换完成信号
            converter.conversion_finished.connect(on_conversion_finished)
            
            # 开始转换
            converter.convert_to_pdf(file_path)
            
        except Exception as e:
            exception_details("文档预览失败", e)
            self._show_error_with_copy_button(f"文档预览失败: {str(e)}")
            self._on_file_read_finished()
            self.is_loading_preview = False

    def _show_font_preview(self, file_path):
        """
        显示字体预览
        
        Args:
            file_path (str): 字体文件路径
        """
        try:
            from freeassetfilter.components.font_previewer import FontPreviewer
            
            # 创建字体预览组件
            font_previewer = FontPreviewer()
            font_previewer.load_font(file_path)
            
            self.preview_layout.addWidget(font_previewer, 1)
            self.current_preview_widget = font_previewer
            self.current_preview_type = "font"
            
            self._show_action_buttons()
            
        except Exception as e:
            exception_details("字体预览失败", e)
            self._show_error_with_copy_button(f"字体预览失败: {str(e)}")
        finally:
            self.is_loading_preview = False

    def cleanup(self):
        """
        清理资源
        """
        debug("开始清理预览器资源")
        
        # 停止预览
        self.stop_preview()
        
        # 清理临时PDF文件
        if self.temp_pdf_path and os.path.exists(self.temp_pdf_path):
            try:
                os.remove(self.temp_pdf_path)
                debug(f"临时PDF文件已删除: {self.temp_pdf_path}")
            except Exception as e:
                warning(f"删除临时PDF文件失败: {e}")
            self.temp_pdf_path = None
        
        # 清理进度条弹窗
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
        
        debug("预览器资源清理完成")

    def _rebuild_media_player(self, file_path, playback_mode, session):
        """
        重建媒体播放器（用于设置变更后）
        
        Args:
            file_path (str): 媒体文件路径
            playback_mode (str): 播放模式
            session (dict): 播放会话状态
        """
        def _rebuild_player():
            try:
                from freeassetfilter.components.video_player import VideoPlayer
                from freeassetfilter.core.settings_manager import SettingsManager
                
                settings_manager = SettingsManager()
                enable_detach = settings_manager.get_setting("player.enable_fullscreen", False)
                initial_volume = settings_manager.get_player_volume()
                initial_speed = settings_manager.get_player_speed()
                
                if playback_mode == VideoPlayer.AUDIO_MODE:
                    player = VideoPlayer(
                        playback_mode="audio",
                        show_lut_controls=False,
                        show_detach_button=False,
                        initial_volume=initial_volume,
                        initial_speed=initial_speed
                    )
                    self.current_preview_type = "audio"
                else:
                    player = VideoPlayer(
                        playback_mode="video",
                        show_detach_button=enable_detach,
                        initial_volume=initial_volume,
                        initial_speed=initial_speed
                    )
                    self.current_preview_type = "video"

                self.preview_layout.addWidget(player, 1)
                self.current_preview_widget = player

                if hasattr(player, "load_media"):
                    player.load_media(file_path, is_audio=(playback_mode == VideoPlayer.AUDIO_MODE))

                def _restore():
                    try:
                        if hasattr(player, "_restore_playback_state"):
                            player._restore_playback_state(session)
                    except Exception as restore_error:
                        error(f"恢复媒体会话失败: {restore_error}")

                QTimer.singleShot(350, _restore)
            except Exception as e:
                error(f"重建媒体播放器失败: {e}")

        QTimer.singleShot(200, _rebuild_player)

    def _refresh_file_selector_and_staging_pool(self):
        """
        刷新文件选择器和文件存储池的图标显示
        在设置保存后调用，确保图标样式等设置变更生效
        """
        try:
            main_window = None
            if hasattr(self, 'main_window') and self.main_window is not None:
                main_window = self.main_window
            elif hasattr(self.parent(), 'main_window') and self.parent().main_window is not None:
                main_window = self.parent().main_window

            # 刷新文件选择器
            if main_window is not None and hasattr(main_window, 'file_selector_a'):
                file_selector = main_window.file_selector_a
                # 刷新文件列表以更新图标显示
                if hasattr(file_selector, 'refresh_files'):
                    file_selector.refresh_files()

            # 刷新文件存储池
            if main_window is not None and hasattr(main_window, 'file_staging_pool'):
                staging_pool = main_window.file_staging_pool
                # 完全重载所有卡片，类似于应用启动时的初始化
                if hasattr(staging_pool, 'reload_all_cards'):
                    staging_pool.reload_all_cards()
        except Exception as e:
            error(f"刷新文件选择器和存储池失败: {e}")
    
    def _update_timeline_button_visibility(self):
        """
        更新时间线按钮的可见性
        根据设置中的 file_selector.timeline_view_enabled 控制文件选择器中时间线按钮的显示/隐藏
        """
        try:
            app = QApplication.instance()
            if not hasattr(app, 'settings_manager'):
                return

            timeline_enabled = app.settings_manager.get_setting("file_selector.timeline_view_enabled", False)

            # 通过主窗口访问文件选择器并更新时间线按钮可见性
            main_window = None
            if hasattr(self, 'main_window') and self.main_window is not None:
                main_window = self.main_window
            elif hasattr(self.parent(), 'main_window') and self.parent().main_window is not None:
                main_window = self.parent().main_window

            if main_window is not None and hasattr(main_window, 'file_selector_a'):
                file_selector = main_window.file_selector_a
                if hasattr(file_selector, '_update_timeline_button_visibility'):
                    file_selector._update_timeline_button_visibility()
        except Exception as e:
            error(f"更新时间线按钮可见性失败: {e}")

    def _refresh_settings_window(self):
        """刷新设置窗口样式"""
        try:
            if self._current_settings_window is None or not self._current_settings_window.isVisible():
                return

            settings_window = self._current_settings_window

            app = QApplication.instance()
            if app is None:
                return

            auxiliary_color = app.settings_manager.get_setting("appearance.colors.auxiliary_color", "#f1f3f5")

            try:
                settings_window.setStyleSheet(f"""
                    QDialog {{
                        background-color: {auxiliary_color};
                    }}
                """)
            except (RuntimeError, AttributeError):
                pass
        except (RuntimeError, AttributeError):
            pass

# 测试代码
if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication, QMainWindow
    
    app = QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle("统一文件预览器测试")
    window.setGeometry(100, 100, 800, 600)
    
    previewer = UnifiedPreviewer()
    window.setCentralWidget(previewer)
    
    # 测试预览一个文件
    test_file = {
        "name": "test.txt",
        "path": __file__,  # 使用当前文件作为测试
        "is_dir": False,
        "size": os.path.getsize(__file__),
        "modified": "2023-01-01T12:00:00",
        "created": "2023-01-01T12:00:00",
        "suffix": "py"
    }
    previewer.set_file(test_file)
    
    window.show()
    sys.exit(app.exec())
