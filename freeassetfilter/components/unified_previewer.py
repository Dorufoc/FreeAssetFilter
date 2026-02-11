#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
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

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QGroupBox, QGridLayout, QSizePolicy, QPushButton, QMessageBox, QApplication, QSplitter
)

# 导入自定义按钮
from freeassetfilter.widgets.D_widgets import CustomButton
from PyQt5.QtCore import Qt
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QThread
from PyQt5.QtGui import QFont

from freeassetfilter.components.file_info_previewer import FileInfoPreviewer
from freeassetfilter.components.folder_content_list import FolderContentList
from freeassetfilter.components.archive_browser import ArchiveBrowser
from freeassetfilter.widgets.D_widgets import CustomMessageBox
from freeassetfilter.widgets.progress_widgets import D_ProgressBar

class UnifiedPreviewer(QWidget):
    """
    统一文件预览器组件
    根据文件类型自动选择合适的预览组件
    """

    # 信号定义
    open_in_selector_requested = pyqtSignal(str)  # 请求在文件选择器中打开路径

    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 获取应用实例和DPI缩放因子
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QFont
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        self.global_font = getattr(app, 'global_font', QFont())
        #print(f"[DEBUG] UnifiedPreviewer获取到的全局字体: {self.global_font.family()}")
        
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
        
        # Idle事件异常检测相关属性
        self.idle_events = []  # 用于存储idle事件的时间戳，实现滑动时间窗口
        self.idle_event_window = 5000  # 滑动时间窗口大小，单位ms
        self.idle_event_threshold = 5  # 时间窗口内允许的最大idle事件数
        self.idle_detection_timer = None  # 用于定期清理过期事件的定时器
        self.video_load_time = 0  # 视频加载时间，用于忽略刚加载时的idle事件
        self.idle_detection_enabled = False  # 是否启用idle检测
        
        # 初始化idle检测定时器
        from PyQt5.QtCore import QTimer
        self.idle_detection_timer = QTimer(self)
        self.idle_detection_timer.setInterval(1000)  # 每秒清理一次过期事件
        self.idle_detection_timer.timeout.connect(self._cleanup_idle_events)

        # 保存主窗口引用，避免循环导入和运行时查找
        self.main_window = parent
        
        self._current_settings_window = None

        # 初始化UI
        self.init_ui()
    
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
                    try:
                        self.current_preview_widget.idle_event.disconnect(self._on_video_idle_event)
                    except (TypeError, RuntimeError):
                        pass
                    
                    # 停止idle检测定时器
                    if self.idle_detection_timer and self.idle_detection_timer.isActive():
                        self.idle_detection_timer.stop()
                    
                    self.idle_events.clear()
                    self.idle_detection_enabled = False
                    
                    # 获取VideoPlayer实例
                    old_widget = self.current_preview_widget
                    self.preview_layout.removeWidget(old_widget)
                    self.current_preview_widget = None
                    
                    # 关键：调用VideoPlayer的closeEvent方法来正确释放MPV资源
                    # 这会触发player_core.cleanup()，从而正确销毁dll
                    old_widget.close()
                    old_widget.setParent(None)
                
                elif isinstance(self.current_preview_widget, TextPreviewWidget):
                    # 对于文本预览器，调用cleanup方法释放QWebEngineView资源
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
            import traceback
            print(f"[ERROR] 停止预览组件失败: {str(e)}")
            traceback.print_exc()
    
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
        background_color = "#2D2D2D"
        base_color = "#212121"
        normal_color = "#717171"
        if hasattr(app, 'settings_manager'):
            background_color = app.settings_manager.get_setting("appearance.colors.window_background", "#2D2D2D")
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
        
        app = QApplication.instance()
        default_font_size = getattr(app, 'default_font_size', 14)
        dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        scaled_font_size = int(default_font_size * dpi_scale)
        
        self.default_label.setStyleSheet(f"font-size: {scaled_font_size}pt; color: #999;")
        self.preview_layout.addWidget(self.default_label)
        
        # 将预览区域添加到分割器
        self.content_splitter.addWidget(self.preview_area)
        
        # 创建文件信息区域
        self.info_group = QGroupBox(" ")
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

        main_layout.addLayout(buttons_layout)
    
    def set_file(self, file_info):
        """
        设置要预览的文件
        
        Args:
            file_info (dict): 文件信息字典
        """
        # 生成带时间戳的debug信息
        import datetime
        def debug(msg):
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            print(f"[{timestamp}] [UnifiedPreviewer] {msg}")
        
        # debug(f"接收到file_selected信号，文件信息: {file_info}")
        
        # 检查是否正在加载预览，如果是则忽略新的请求
        if self.is_loading_preview:
            # debug("正在加载预览中，忽略新的预览请求")
            return
        
        self.current_file_info = file_info
        
        # 更新文件信息查看器
        # debug("更新文件信息查看器")
        self.file_info_viewer.set_file(file_info)
        
        # 根据文件类型显示不同的预览内容
        # debug("调用_show_preview()显示预览")
        self._show_preview()
    
    def _show_preview(self):
        """
        根据文件类型显示预览内容，确保只有一个预览组件在工作
        """
        # 生成带时间戳的debug信息
        # import datetime
        # def debug(msg):
        #     timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        #     print(f"[{timestamp}] [UnifiedPreviewer] {msg}")
        
        # debug("开始处理文件预览")
        
        if not self.current_file_info:
            # 没有文件信息时，显示默认提示
            # debug("没有文件信息，显示默认提示")
            self._clear_preview()
            self.preview_layout.addWidget(self.default_label)
            self.default_label.show()
            self.open_with_system_button.hide()
            self.locate_in_selector_button.hide()
            return
        
        # debug(f"获取文件信息: {self.current_file_info}")
        
        # 获取文件路径和类型
        file_path = self.current_file_info["path"]
        file_type = self.current_file_info["suffix"]
        
        # debug(f"提取的文件路径: {file_path}, 文件类型: {file_type}")
        
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
            preview_type = "document"  # 新增文档类型
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
        
        # debug(f"确定预览类型: {preview_type}")
        
        # 检查当前预览组件是否可以处理该类型
        # 如果预览类型相同，直接更新组件
        if preview_type == self.current_preview_type and self.current_preview_widget:
            # 更新现有组件
            # debug(f"预览类型相同，直接更新组件: {preview_type}")
            self._update_preview_widget(file_path, preview_type)
        else:
            # 设置加载状态为True，防止快速点击触发多个预览
            self.is_loading_preview = True
            
            # 对于所有预览类型，都使用后台线程加载，确保UI响应
            # debug(f"预览类型不同，创建新组件: {preview_type}")
            
            # 显示进度条弹窗
            title = "正在加载预览"
            message = "正在准备预览组件..."
            if preview_type == "video":
                title = "正在加载视频"
                message = "正在准备视频播放器..."
                # debug("显示视频加载进度条")
            elif preview_type == "audio":
                title = "正在加载音频"
                message = "正在准备音频播放器..."
                # debug("显示音频加载进度条")
            elif preview_type == "pdf":
                title = "正在加载PDF"
                message = "正在准备PDF阅读器..."
                # debug("显示PDF加载进度条")
            elif preview_type == "archive":
                title = "正在加载压缩包"
                message = "正在准备压缩包浏览器..."
                # debug("显示压缩包加载进度条")
            elif preview_type == "image":
                title = "正在加载图片"
                message = "正在准备图片查看器..."
                # debug("显示图片加载进度条")
            elif preview_type == "text":
                title = "正在加载文本"
                message = "正在准备文本查看器..."
                # debug("显示文本加载进度条")
            elif preview_type == "dir":
                title = "正在加载文件夹"
                message = "正在准备文件夹浏览器..."
                # debug("显示文件夹加载进度条")
            elif preview_type == "font":
                title = "正在加载字体"
                message = "正在准备字体预览器..."
                # debug("显示字体加载进度条")

            self._show_progress_dialog(title, message)
            
            # 预览类型不同，清除当前组件，创建新组件
            # debug("清除当前预览组件")
            self._clear_preview()
            
            # 检查并终止现有线程（如果存在）
            if hasattr(self, '_preview_thread') and self._preview_thread and self._preview_thread.isRunning():
                # debug("发现正在运行的后台线程，尝试取消并终止")
                self._preview_thread.cancel()
                # 等待线程终止，最多等待1秒
                self._preview_thread.wait(1000)
                if self._preview_thread.isRunning():
                    # debug("线程终止超时")
                    pass
            
            # 创建后台加载线程
            # debug(f"创建后台加载线程，预览类型: {preview_type}, 文件路径: {file_path}")
            self._preview_thread = self.PreviewLoaderThread(file_path, preview_type)
            
            # 连接线程信号
            # debug("连接线程信号")
            self._preview_thread.preview_created.connect(self._on_preview_created)
            self._preview_thread.preview_error.connect(self._on_preview_error)
            self._preview_thread.preview_progress.connect(self._on_progress_updated)
            
            # 启动线程
            # debug("启动后台加载线程")
            self._preview_thread.start()
            
            # 更新当前预览类型
            # debug(f"更新当前预览类型: {preview_type}")
            self.current_preview_type = preview_type
        
        # 显示"使用系统默认方式打开"按钮和"定位到所在目录"按钮
        self.open_with_system_button.show()
        self.locate_in_selector_button.show()
        
    def _open_file_with_system(self):
        """
        使用系统默认方式打开当前预览的文件
        """
        if not self.current_file_info:
            return
        
        file_path = self.current_file_info["path"]
        if not file_path:
            return
        
        # 确保文件路径是绝对路径
        file_path = os.path.abspath(file_path)
        
        # 检查文件是否存在
        if not os.path.exists(file_path):
            from freeassetfilter.widgets.D_widgets import CustomMessageBox
            msg_box = CustomMessageBox(self)
            msg_box.set_title("错误")
            msg_box.set_text(f"文件不存在: {file_path}")
            msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            msg_box.exec_()
            return
        
        try:
            if sys.platform == "win32":
                # Windows系统
                os.startfile(file_path)
            elif sys.platform == "darwin":
                # macOS系统
                os.system(f"open \"{file_path}\"")
            else:
                # Linux系统
                os.system(f"xdg-open \"{file_path}\"")
        except Exception as e:
            from freeassetfilter.widgets.D_widgets import CustomMessageBox
            msg_box = CustomMessageBox(self)
            msg_box.set_title("错误")
            msg_box.set_text(f"无法打开文件: {str(e)}")
            msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            msg_box.exec_()

    def _locate_file_in_selector(self):
        """
        定位到当前预览文件所在的目录，发送信号给文件选择器加载该路径
        """
        if not self.current_file_info:
            return

        file_path = self.current_file_info["path"]
        if not file_path:
            return

        # 获取文件所在目录
        file_dir = os.path.dirname(file_path)
        if not file_dir or not os.path.exists(file_dir):
            from freeassetfilter.widgets.D_widgets import CustomMessageBox
            msg_box = CustomMessageBox(self)
            msg_box.set_title("错误")
            msg_box.set_text(f"目录不存在: {file_dir}")
            msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            msg_box.exec_()
            return

        # 发送信号请求在文件选择器中打开该路径
        self.open_in_selector_requested.emit(file_dir)

    def _clear_preview(self):
        """
        清除当前预览内容，确保所有组件都被正确释放，但保留控制栏
        """
        # 先停止后台线程，避免在清理过程中发生访问冲突
        if hasattr(self, '_preview_thread') and self._preview_thread and self._preview_thread.isRunning():
            self._preview_thread.cancel()
            # 等待线程结束，最多等待500ms
            self._preview_thread.wait(500)
            # 如果线程仍在运行，强制终止
            if self._preview_thread.isRunning():
                self._preview_thread.terminate()
                self._preview_thread.wait(100)
            # 断开信号连接，防止线程完成时触发信号
            try:
                self._preview_thread.preview_created.disconnect(self._on_preview_created)
                self._preview_thread.preview_error.disconnect(self._on_preview_error)
                self._preview_thread.preview_progress.disconnect(self._on_progress_updated)
            except:
                pass
        
        # 先移除默认标签（如果存在），避免重复添加
        if hasattr(self, 'default_label') and self.default_label and self.default_label.parent() is self.preview_area:
            self.preview_layout.removeWidget(self.default_label)
            self.default_label.hide()
        
        # 停止当前预览组件的播放（如果是视频或音频）
        if self.current_preview_widget:
            # 对于文本预览器，需要特别处理QWebEngineView的资源释放
            try:
                from freeassetfilter.components.text_previewer import TextPreviewWidget
                if isinstance(self.current_preview_widget, TextPreviewWidget):
                    # 调用cleanup方法进行完整的资源清理
                    if hasattr(self.current_preview_widget, 'cleanup'):
                        self.current_preview_widget.cleanup()
            except Exception as e:
                print(f"清理TextPreviewWidget组件时出错: {e}")
            
            # 对于字体预览器，需要特别处理字体资源释放
            try:
                from freeassetfilter.components.font_previewer import FontPreviewWidget
                if isinstance(self.current_preview_widget, FontPreviewWidget):
                    # 调用cleanup方法进行完整的资源清理
                    if hasattr(self.current_preview_widget, 'cleanup'):
                        self.current_preview_widget.cleanup()
            except Exception as e:
                print(f"清理FontPreviewWidget组件时出错: {e}")
            
            # 停止播放
            if hasattr(self.current_preview_widget, 'stop'):
                try:
                    self.current_preview_widget.stop()
                except Exception as e:
                    print(f"停止预览组件时出错: {e}")
            
            # 对于VideoPlayer组件，确保完全停止所有播放器核心
            try:
                from freeassetfilter.components.video_player import VideoPlayer
                if isinstance(self.current_preview_widget, VideoPlayer):
                    # 先调用cleanup方法（这会先停止事件线程，再停止播放，确保清理彻底）
                    if hasattr(self.current_preview_widget.player_core, 'cleanup'):
                        self.current_preview_widget.player_core.cleanup()
                    
                    # 同时处理比较模式下的原始播放器核心
                    if hasattr(self.current_preview_widget, 'original_player_core'):
                        if hasattr(self.current_preview_widget.original_player_core, 'cleanup'):
                            self.current_preview_widget.original_player_core.cleanup()
                    
                    # 作为安全网，再次调用stop确保播放完全停止
                    self.current_preview_widget.player_core.stop()
                    if hasattr(self.current_preview_widget, 'original_player_core'):
                        self.current_preview_widget.original_player_core.stop()
                    
                    # 最后禁用滤镜资源
                    if hasattr(self.current_preview_widget.player_core, 'disable_cube_filter'):
                        self.current_preview_widget.player_core.disable_cube_filter()
                    if hasattr(self.current_preview_widget, 'original_player_core'):
                        self.current_preview_widget.original_player_core.disable_cube_filter()
            except Exception as e:
                print(f"清理VideoPlayer组件时出错: {e}")

            # 注意：不要调用 self.current_preview_widget.disconnect()
            # 因为这会断开所有信号连接，包括 QWebEngineView 等内部组件的信号
            # 可能导致程序卡死。使用 removeWidget 和 deleteLater 已经足够

            # 清除布局中的所有组件，除了控制栏
            # 控制栏是第一个组件，所以只清除从索引1开始的组件
            for i in reversed(range(self.preview_layout.count())):
                if i == 0:  # 保留控制栏
                    continue
                item = self.preview_layout.itemAt(i)
                if item is not None:
                    widget = item.widget()
                    if widget is not None:
                        self.preview_layout.removeWidget(widget)
                        widget.deleteLater()
        
        # 确保布局中只保留控制栏
        while self.preview_layout.count() > 1:  # 1表示只保留控制栏
            item = self.preview_layout.takeAt(1)  # 从索引1开始移除
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
        # 重置临时PDF文件路径，但不删除缓存文件
        print("=== 进入_clear_preview方法 ===")
        print(f"hasattr(temp_pdf_path): {hasattr(self, 'temp_pdf_path')}")
        if hasattr(self, 'temp_pdf_path') and self.temp_pdf_path:
            print(f"temp_pdf_path值: {self.temp_pdf_path}")
            print(f"temp_pdf_path存在: {os.path.exists(self.temp_pdf_path) if self.temp_pdf_path else False}")
            # 只重置路径，不删除缓存文件，以便下次预览时可以复用
            self.temp_pdf_path = None
            print("已重置temp_pdf_path为None")
        print("=== 退出_clear_preview方法 ===")
        
        # 重置当前预览组件和类型
        self.current_preview_widget = None
        self.current_preview_type = None
    
    def _update_preview_widget(self, file_path, preview_type):
        """
        更新现有预览组件，确保组件状态正确刷新
        移除了os.path.exists检查，避免网络文件阻塞主线程
        
        Args:
            file_path (str): 文件路径
            preview_type (str): 预览类型
        """
        if not self.current_preview_widget:
            return
        
        try:
            # 如果是文档类型预览，只重置路径，不删除缓存文件
            if preview_type == "document":
                # 清理旧的临时PDF文件
                if hasattr(self, 'temp_pdf_path') and self.temp_pdf_path:
                    try:
                        # 只重置路径，不删除缓存文件，以便下次预览时可以复用
                        print(f"重置临时PDF路径: {self.temp_pdf_path}")
                    except Exception as e:
                        print(f"处理临时PDF文件失败: {e}")
                    finally:
                        self.temp_pdf_path = None
                # 对于文档类型，需要重新转换
                self._clear_preview()
                self._show_preview()
                return
            # 确保组件处于正确状态
            if preview_type in ["video", "audio"]:
                # 视频和音频组件都有load_media方法
                if hasattr(self.current_preview_widget, 'stop'):
                    self.current_preview_widget.stop()
                if hasattr(self.current_preview_widget, 'load_media'):
                    self.current_preview_widget.load_media(file_path)
            elif preview_type == "image":
                # 图片预览组件
                if hasattr(self.current_preview_widget, 'load_image_from_path'):
                    self.current_preview_widget.load_image_from_path(file_path)
                elif hasattr(self.current_preview_widget, 'set_image'):
                    self.current_preview_widget.set_image(file_path)
            elif preview_type == "pdf":
                # PDF预览组件
                if hasattr(self.current_preview_widget, 'set_file'):
                    self.current_preview_widget.set_file(file_path)
                elif hasattr(self.current_preview_widget, 'load_file_from_path'):
                    self.current_preview_widget.load_file_from_path(file_path)
            elif preview_type == "text":
                # 文本预览组件
                if hasattr(self.current_preview_widget, 'set_file'):
                    self.current_preview_widget.set_file(file_path)
            elif preview_type == "archive":
                # 压缩包预览组件
                if hasattr(self.current_preview_widget, 'set_archive_path'):
                    self.current_preview_widget.set_archive_path(file_path)
            elif preview_type == "dir":
                # 文件夹预览组件
                if hasattr(self.current_preview_widget, 'set_path'):
                    self.current_preview_widget.set_path(file_path)
            elif preview_type == "font":
                # 字体预览组件：每次传入新字体时，清除旧组件并创建新组件
                # 这样可以确保字体资源被正确释放，新字体能够正确加载
                self._clear_preview()
                self._show_font_preview(file_path)
                return
        except Exception as e:
            print(f"更新预览组件时出错: {e}")
            # 如果更新失败，清除当前组件，重新创建
            self._clear_preview()
            self._show_preview()
    
    def _show_error_with_copy_button(self, error_message):
        """
        显示带有复制按钮的错误信息
        
        Args:
            error_message (str): 错误信息
        """
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
    
    def _show_image_preview(self, file_path):
        """
        显示图片预览
        
        Args:
            file_path (str): 图片文件路径
        """
        try:
            file_ext = os.path.splitext(file_path)[1].lower()

            if file_ext == '.gif':
                from freeassetfilter.components.photo_viewer import GifViewer
                gif_viewer = GifViewer()
                if gif_viewer.load_gif(file_path):
                    self.preview_layout.addWidget(gif_viewer, 1)
                    self.current_preview_widget = gif_viewer
                    return

            elif file_ext == '.webp':
                if self._is_animated_image(file_path):
                    from freeassetfilter.components.photo_viewer import GifViewer
                    gif_viewer = GifViewer()
                    if gif_viewer.load_gif(file_path):
                        self.preview_layout.addWidget(gif_viewer, 1)
                        self.current_preview_widget = gif_viewer
                        return

            from freeassetfilter.components.photo_viewer import PhotoViewer
            
            photo_viewer = PhotoViewer()
            photo_viewer.load_image_from_path(file_path)
            
            self.preview_layout.addWidget(photo_viewer, 1)
            self.current_preview_widget = photo_viewer
        except Exception as e:
            self._show_error_with_copy_button(f"图片预览失败: {str(e)}")

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
        except Exception:
            return False
    
    def _cleanup_idle_events(self):
        """
        清理过期的idle事件，保持滑动时间窗口的有效性
        """
        import time
        current_time = time.time() * 1000  # 转换为ms
        
        # 过滤掉时间窗口外的事件
        self.idle_events = [event for event in self.idle_events 
                          if current_time - event < self.idle_event_window]
    
    def _on_video_idle_event(self):
        """
        处理视频播放器的idle事件，检测异常并在必要时重新加载
        """
        import time
        current_time = time.time() * 1000  # 转换为ms
        
        # 如果刚加载视频（5秒内），忽略idle事件
        if current_time - self.video_load_time < 5000:
            print(f"[DEBUG] 视频刚加载，忽略idle事件")
            return
        
        # 将当前idle事件添加到时间窗口
        self.idle_events.append(current_time)
        
        # 检测idle事件异常
        self._detect_idle_anomaly()
    
    def _detect_idle_anomaly(self):
        """
        检测idle事件是否异常：时间窗口内事件数量超过阈值
        """
        # 先清理过期事件
        self._cleanup_idle_events()
        
        # 检查事件数量是否超过阈值
        if len(self.idle_events) > self.idle_event_threshold:
            print(f"[ERROR] Idle事件异常！{self.idle_event_window}ms内检测到{len(self.idle_events)}个事件，超过阈值{self.idle_event_threshold}")
            
            # 重新加载视频播放器
            self._reload_video_player()
    
    def _reload_video_player(self):
        """
        重新加载视频播放器模块和当前视频
        """
        try:
            print("[INFO] 开始重新加载视频播放器...")
            
            # 获取当前播放的文件路径
            current_file_path = None
            if hasattr(self, 'current_file_info') and self.current_file_info:
                current_file_path = self.current_file_info.get("path")
            
            if not current_file_path:
                print("[ERROR] 无法获取当前播放的文件路径")
                return
            
            # 移除当前的视频播放器组件
            if hasattr(self, 'current_preview_widget') and self.current_preview_widget:
                from freeassetfilter.components.video_player import VideoPlayer
                if isinstance(self.current_preview_widget, VideoPlayer):
                    # 断开信号连接
                    self.current_preview_widget.idle_event.disconnect(self._on_video_idle_event)
                    
                    # 停止播放并移除组件
                    self.current_preview_widget.stop()
                    self.preview_layout.removeWidget(self.current_preview_widget)
                    self.current_preview_widget.deleteLater()
                    self.current_preview_widget = None
            
            # 重置idle检测状态
            self.idle_events.clear()
            self.idle_detection_enabled = False
            
            # 重新加载视频播放器模块
            import importlib
            import freeassetfilter.components.video_player
            import freeassetfilter.core.mpv_player_core
            
            # 重新导入模块
            importlib.reload(freeassetfilter.core.mpv_player_core)
            importlib.reload(freeassetfilter.components.video_player)
            
            print("[INFO] 视频播放器模块重新加载完成")
            
            # 重新创建视频播放器并加载视频
            self._show_video_preview(current_file_path)
            
        except Exception as e:
            import traceback
            print(f"[ERROR] 重新加载视频播放器失败: {str(e)}")
            traceback.print_exc()
    
    def _show_video_preview(self, file_path):
        """
        显示视频预览
        进度条已在_show_preview中显示，将在PDF渲染完成后关闭
        
        Args:
            file_path (str): 视频文件路径
        """
        try:
            # 使用统一的VideoPlayer组件处理视频文件
            from freeassetfilter.components.video_player import VideoPlayer
            
            # 创建VideoPlayer视频播放器
            video_player = VideoPlayer()
            
            # 连接idle事件信号，用于异常检测
            video_player.idle_event.connect(self._on_video_idle_event)
            
            # 添加到布局
            self.preview_layout.addWidget(video_player, 1)  # 设置伸展因子1，使预览组件占据剩余空间
            self.current_preview_widget = video_player
            
            # 记录视频加载时间
            import time
            self.video_load_time = time.time() * 1000  # 转换为ms
            
            # 加载并播放视频文件
            video_player.load_media(file_path)
            video_player.play()
            
            # 启用idle检测
            self.idle_detection_enabled = True
            self.idle_detection_timer.start()
            
            print(f"[DEBUG] 视频预览组件已创建并开始播放: {file_path}")
        except Exception as e:
            import traceback
            # 打印详细错误信息到控制台
            print(f"[ERROR] 视频预览失败: {str(e)}")
            traceback.print_exc()
            # 显示友好的错误信息到界面
            error_message = f"视频预览失败: {str(e)}"
            self._show_error_with_copy_button(error_message)
    
    def keyPressEvent(self, event):
        """
        处理键盘按键事件
        - 空格键：如果当前预览组件是视频播放器，则切换播放/暂停状态
        """
        if event.key() == Qt.Key_Space:
            # 检查当前预览组件是否是视频播放器
            try:
                from freeassetfilter.components.video_player import VideoPlayer
                if isinstance(self.current_preview_widget, VideoPlayer):
                    # 调用视频播放器的播放/暂停方法
                    self.current_preview_widget.toggle_play_pause()
                else:
                    # 如果不是视频播放器，调用父类的默认处理
                    super().keyPressEvent(event)
            except ImportError:
                # 如果无法导入VideoPlayer，调用父类的默认处理
                super().keyPressEvent(event)
        else:
            # 其他按键事件，交给父类处理
            super().keyPressEvent(event)
    
    def focusInEvent(self, event):
        """
        处理焦点进入事件
        - 确保组件获得焦点时能够接收键盘事件
        """
        super().focusInEvent(event)
    
    def _get_video_thumbnail(self, file_path):
        """
        获取视频缩略图路径
        
        Args:
            file_path (str): 视频文件路径
        
        Returns:
            str: 缩略图路径，如果无法生成则返回None
        """
        try:
            # 尝试使用opencv生成缩略图
            import cv2
            
            # 生成缩略图文件路径
            thumb_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'thumbnails')
            os.makedirs(thumb_dir, exist_ok=True)
            file_hash = hash(file_path)
            thumbnail_path = os.path.join(thumb_dir, f"{file_hash}.png")
            
            # 如果缩略图已存在，直接返回
            if os.path.exists(thumbnail_path):
                return thumbnail_path
            
            # 尝试打开视频文件
            cap = cv2.VideoCapture(file_path)
            if cap.isOpened():
                # 获取视频总帧数
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                if total_frames > 0:
                    # 跳转到视频中间位置
                    middle_frame = total_frames // 2
                    cap.set(cv2.CAP_PROP_POS_FRAMES, middle_frame)
                    
                    # 读取中间帧
                    ret, frame = cap.read()
                    if ret:
                        # 调整大小为128x128
                        thumbnail = cv2.resize(frame, (128, 128), interpolation=cv2.INTER_AREA)
                        # 保存缩略图
                        cv2.imwrite(thumbnail_path, thumbnail)
                    else:
                        # 如果无法读取中间帧，尝试读取第一帧
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        ret, frame = cap.read()
                        if ret:
                            thumbnail = cv2.resize(frame, (128, 128), interpolation=cv2.INTER_AREA)
                            cv2.imwrite(thumbnail_path, thumbnail)
                
                # 释放资源
                cap.release()
            
            return thumbnail_path
        except ImportError:
            # 如果没有安装opencv，返回None
            print("OpenCV is not installed")
            return None
        except Exception as e:
            # 处理其他可能的错误
            print(f"生成视频缩略图失败: {file_path}, 错误: {e}")
            return None
    
    def _show_audio_preview(self, file_path):
        """
        显示音频预览
        进度条已在_show_preview中显示并在_on_preview_created中关闭
        
        Args:
            file_path (str): 音频文件路径
        """
        try:
            # 使用视频播放器组件处理音频文件，因为它已经支持音频播放
            from freeassetfilter.components.video_player import VideoPlayer
            
            # 创建视频播放器（支持音频播放）
            audio_player = VideoPlayer()
            audio_player.load_media(file_path)
            
            self.preview_layout.addWidget(audio_player, 1)  # 设置伸展因子1，使预览组件占据剩余空间
            self.current_preview_widget = audio_player
        except Exception as e:
            error_message = f"音频预览失败: {str(e)}"
            self._show_error_with_copy_button(error_message)
    
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
        print("[DEBUG] PDF渲染完成，关闭进度条弹窗")
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
                
                # 使用全局统一字体大小，与LibreOffice提示样式保持一致
                app = QApplication.instance()
                default_font_size = getattr(app, 'default_font_size', 14)
                dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
                scaled_font_size = int(default_font_size * dpi_scale)
                info_label.setStyleSheet(f"font-size: {scaled_font_size}pt; color: #999; font-weight: normal;")
                
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
            import traceback
            traceback.print_exc()
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
            if hasattr(self, '_preview_thread'):
                self._preview_thread.deleteLater()
                delattr(self, '_preview_thread')
    
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
            if hasattr(self, '_preview_thread'):
                self._preview_thread.deleteLater()
                delattr(self, '_preview_thread')
    
    class PreviewLoaderThread(QThread):
        """
        预览加载后台线程
        用于在后台线程中创建预览组件和加载媒体文件，避免阻塞主线程
        优化：避免在后台线程中创建UI组件，只处理媒体加载逻辑
        """
        # 信号定义
        preview_created = pyqtSignal(object, str)  # 预览组件创建完成，参数：组件实例，预览类型
        preview_error = pyqtSignal(str)  # 预览创建失败，参数：错误信息
        preview_progress = pyqtSignal(int, str)  # 预览进度更新，参数：进度(0-100)，状态描述
        
        def __init__(self, file_path, preview_type, parent=None):
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
                
                # 对于不同的预览类型，执行不同的预处理逻辑
                if self.preview_type in ["video", "audio", "pdf", "archive", "image", "text", "dir", "document", "font", "unknown"]:
                    # 模拟进度更新，确保UI能响应
                    import time
                    for i in range(20, 100, 10):
                        if self.is_cancelled:
                            self.preview_error.emit("预览已取消")
                            return
                        self.preview_progress.emit(i, f"正在准备预览...")
                        # 短暂休眠，让主线程有机会处理事件
                        time.sleep(0.1)
                    
                    # 标记预览准备完成
                    self.preview_progress.emit(100, "预览准备完成")
                    
                    # 发送信号，通知主线程创建预览组件
                    # 注意：我们不在后台线程中创建UI组件，而是让主线程创建
                    self.preview_created.emit(None, self.preview_type)
                else:
                    self.preview_error.emit("不支持的预览类型")
                    
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.preview_error.emit(str(e))
        
        def cancel(self):
            """
            取消预览加载
            """
            self.is_cancelled = True
    
    def _simulate_video_progress(self):
        """
        模拟视频加载进度，当视频播放器没有进度信号时使用
        """
        if not hasattr(self, '_progress'):
            self._progress = 0
        
        # 每次更新增加5%的进度，直到95%
        self._progress += 5
        if self._progress >= 95:
            self._progress = 95
            # 不再增加，等待实际加载完成
        
        # 更新进度条
        self._on_progress_updated(self._progress, f"正在加载视频... {self._progress}%")
    
    def _show_text_preview(self, file_path):
        """
        显示文本预览
        进度条已在_show_preview中显示并在_on_preview_created中关闭
        
        Args:
            file_path (str): 文本文件路径
        """
        try:
            # 尝试导入文本预览器组件
            from freeassetfilter.components.text_previewer import TextPreviewWidget
            
            # 创建文本预览部件（注意：使用TextPreviewWidget而不是TextPreviewer）
            # TextPreviewer是QMainWindow，不能嵌入到布局中；TextPreviewWidget才是QWidget
            text_previewer = TextPreviewWidget()
            
            # 设置文件，开始异步读取
            text_previewer.set_file(file_path)
            
            self.preview_layout.addWidget(text_previewer, 1)  # 设置伸展因子1，使预览组件占据剩余空间
            self.current_preview_widget = text_previewer
        except Exception as e:
            error_message = f"文本预览失败: {str(e)}"
            self._show_error_with_copy_button(error_message)

    def _show_font_preview(self, file_path):
        """
        显示字体预览
        进度条已在_show_preview中显示并在_on_preview_created中关闭

        Args:
            file_path (str): 字体文件路径
        """
        try:
            # 尝试导入字体预览器组件
            from freeassetfilter.components.font_previewer import FontPreviewWidget

            # 创建字体预览部件（注意：使用FontPreviewWidget而不是FontPreviewer）
            # FontPreviewer是QMainWindow，不能嵌入到布局中；FontPreviewWidget才是QWidget
            font_previewer = FontPreviewWidget()

            # 设置字体文件
            font_previewer.set_font(file_path)

            self.preview_layout.addWidget(font_previewer, 1)  # 设置伸展因子1，使预览组件占据剩余空间
            self.current_preview_widget = font_previewer
        except Exception as e:
            error_message = f"字体预览失败: {str(e)}"
            self._show_error_with_copy_button(error_message)

    def _show_document_preview(self, file_path):
        """
        显示文档预览，先将文档转换为PDF，然后使用PDF预览器显示
        
        Args:
            file_path (str): 文档文件路径
        """
        try:
            import subprocess
            import tempfile
            import os
            
            # 生成临时PDF文件路径 - 使用程序data/temp文件夹
            # 计算项目根目录：freeassetfilter/components/unified_previewer.py -> freeassetfilter/components -> freeassetfilter -> 项目根目录
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            temp_dir = os.path.join(project_root, "data", "temp")
            # 确保temp文件夹存在
            if not os.path.exists(temp_dir):
                os.makedirs(temp_dir)
                print(f"创建了临时文件夹: {temp_dir}")
            
            file_name = os.path.basename(file_path)
            base_name = os.path.splitext(file_name)[0]
            
            # 使用稳定的临时文件名，不包含时间戳，便于缓存管理
            temp_pdf_name = f"{base_name}_temp.pdf"
            self.temp_pdf_path = os.path.join(temp_dir, temp_pdf_name)
            print(f"临时PDF路径: {self.temp_pdf_path}")
            
            # 检查是否已存在PDF缓存文件
            if os.path.exists(self.temp_pdf_path):
                print(f"找到已存在的PDF缓存文件，直接使用: {self.temp_pdf_path}")
                # 直接使用已存在的PDF文件
            else:
                # 缓存不存在，需要转换文档为PDF
                print(f"缓存不存在，正在将文档转换为PDF: {file_path} -> {self.temp_pdf_path}")
                
                # 找到便携版LibreOffice的路径
                # __file__ = freeassetfilter/components/unified_previewer.py
                # 三个dirname：freeassetfilter/components → freeassetfilter → 项目根目录
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
                libreoffice_exe = os.path.join(project_root, "data", "LibreOfficePortable", "App", "LibreOffice", "program", "soffice.exe")
                
                if not os.path.exists(libreoffice_exe):
                    # 关闭进度条弹窗
                    self._on_file_read_finished()
                    # 在预览器窗口内显示LibreOffice缺失提示（普通信息样式）
                    self._clear_preview()
                    
                    # 创建普通信息容器
                    info_container = QWidget()
                    info_container.setStyleSheet("background-color: transparent;")
                    info_layout = QVBoxLayout(info_container)
                    info_layout.setSpacing(10)
                    info_layout.setContentsMargins(0, 0, 0, 0)
                    
                    # 显示普通信息
                    info_message = "LibreOffice组件缺失\n\n预览Office类文件需要LibreOffice组件支持。\n\n请将LibreOfficePortable解压后放置于:\nFreeassetfilter/data文件夹内\n\n文件夹结构应为：\nFreeAssetFliter/data/LibreOfficePortable/..."
                    info_label = QLabel(info_message)
                    info_label.setAlignment(Qt.AlignCenter)
                    
                    # 启用自动换行，确保文本根据宽度调整
                    info_label.setWordWrap(True)
                    
                    # 使用全局统一字体大小
                    app = QApplication.instance()
                    default_font_size = getattr(app, 'default_font_size', 14)
                    dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
                    scaled_font_size = int(default_font_size * dpi_scale)
                    info_label.setStyleSheet(f"font-size: {scaled_font_size}pt; color: #999; font-weight: normal;")
                    
                    info_layout.addWidget(info_label)
                    
                    self.preview_layout.addWidget(info_container)
                    self.current_preview_widget = info_container
                    self.current_preview_type = "info"
                    return
                
                # 使用LibreOffice将文档转换为PDF
                # 修正命令参数格式，添加超时处理和内存限制
                cmd = [
                    libreoffice_exe,
                    "--headless",
                    "--convert-to", "pdf:writer_pdf_Export",
                    "--outdir", temp_dir,
                    "--nofirststartwizard",  # 禁用首次启动向导
                    "--norestore",  # 禁用恢复功能
                    "--minimized",  # 最小化启动
                    file_path
                ]
                
                print(f"执行命令: {' '.join(cmd)}")
                
                # 设置超时时间为300秒（5分钟），处理大文件
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                    
                    # 输出LibreOffice的执行结果，便于调试
                    if result.stdout:
                        print(f"LibreOffice输出: {result.stdout}")
                    if result.stderr:
                        print(f"LibreOffice错误: {result.stderr}")
                    print(f"LibreOffice返回码: {result.returncode}")
                    
                    if result.returncode != 0:
                        error_msg = f"文档转换失败: {result.stderr}" if result.stderr else f"文档转换失败，返回码: {result.returncode}"
                        self._show_error_with_copy_button(error_msg)
                        return
                except subprocess.TimeoutExpired:
                    # 处理转换超时情况
                    error_msg = f"文档转换超时，可能文件过大或内容复杂"
                    self._show_error_with_copy_button(error_msg)
                    return
                except Exception as e:
                    # 处理其他异常
                    error_msg = f"文档转换异常: {str(e)}"
                    self._show_error_with_copy_button(error_msg)
                    return
                
                # 检查PDF文件是否生成
                # 首先查找默认生成的PDF文件（基础文件名 + .pdf）
                default_pdf_path = os.path.join(temp_dir, f"{base_name}.pdf")
                
                if os.path.exists(default_pdf_path):
                    print(f"找到默认生成的PDF文件: {default_pdf_path}")
                    # 如果生成的文件名不是我们想要的临时文件名，重命名它
                    if default_pdf_path != self.temp_pdf_path:
                        try:
                            # 删除已存在的临时文件（如果有）
                            if os.path.exists(self.temp_pdf_path):
                                os.remove(self.temp_pdf_path)
                            # 重命名为临时文件名
                            os.rename(default_pdf_path, self.temp_pdf_path)
                            print(f"将PDF重命名为: {self.temp_pdf_path}")
                        except Exception as e:
                            print(f"重命名PDF失败: {e}")
                            # 如果重命名失败，直接使用生成的PDF路径
                            self.temp_pdf_path = default_pdf_path
                elif os.path.exists(self.temp_pdf_path):
                    print(f"PDF文件已生成: {self.temp_pdf_path}")
                else:
                    # 如果直接查找指定路径的PDF文件失败，尝试搜索所有生成的PDF文件
                    print("直接查找指定路径的PDF文件失败，尝试搜索所有生成的PDF文件")
                    import glob
                    import time
                    
                    # 查找所有可能的生成文件，使用更宽松的匹配模式
                    generated_pdfs = glob.glob(os.path.join(temp_dir, "*.pdf"))
                    
                    if generated_pdfs:
                        # 输出所有找到的PDF文件，便于调试
                        for pdf_path in generated_pdfs:
                            print(f"找到PDF文件: {pdf_path}")
                        
                        # 尝试找到最可能是我们需要的PDF文件
                        # 1. 优先匹配基础文件名的PDF
                        base_matches = [f for f in generated_pdfs if base_name in os.path.basename(f)]
                        if base_matches:
                            # 按修改时间排序，选择最新的
                            base_matches.sort(key=os.path.getmtime, reverse=True)
                            found_pdf = base_matches[0]
                            print(f"找到与基础文件名匹配的最新PDF: {found_pdf}")
                        else:
                            # 2. 如果没有基础文件名匹配，使用最新生成的PDF
                            found_pdf = max(generated_pdfs, key=os.path.getmtime)
                            print(f"使用最新生成的PDF: {found_pdf}")
                        
                        try:
                            # 将找到的PDF文件重命名为我们想要的临时文件名
                            if found_pdf != self.temp_pdf_path:
                                # 删除已存在的临时文件（如果有）
                                if os.path.exists(self.temp_pdf_path):
                                    os.remove(self.temp_pdf_path)
                                # 重命名为临时文件名
                                os.rename(found_pdf, self.temp_pdf_path)
                                print(f"将PDF重命名为: {self.temp_pdf_path}")
                        except Exception as e:
                            print(f"重命名PDF失败: {e}")
                            # 如果重命名失败，直接使用找到的PDF路径
                            self.temp_pdf_path = found_pdf
                    else:
                        # 没有找到任何生成的PDF文件
                        error_msg = f"PDF生成失败，未找到预期的PDF文件"
                        self._show_error_with_copy_button(error_msg)
                        return
                
                print(f"文档转换成功: {self.temp_pdf_path}")
                
                print(f"文档转换成功: {self.temp_pdf_path}")
            
            # 使用现有的PDF预览方法显示转换后的PDF
            # 注意：这里不再立即关闭进度条弹窗，而是等待PDF渲染完成后关闭
            self._show_pdf_preview(self.temp_pdf_path)
        except Exception as e:
            import traceback
            error_label = QLabel(f"文档预览失败: {str(e)}\n\n详细错误:\n{traceback.format_exc()}")
            error_label.setAlignment(Qt.AlignCenter)
            error_label.setStyleSheet("color: red; font-weight: bold;")
            self.preview_layout.addWidget(error_label)
            self.current_preview_widget = error_label

    def _open_global_settings(self):
        """
        打开全局设置窗口
        使用ModernSettingsWindow替代原来的设置窗口
        """
        from freeassetfilter.components.settings_window import ModernSettingsWindow

        parent_widget = None
        try:
            if self.main_window is not None:
                try:
                    if hasattr(self.main_window, 'isVisible') and self.main_window.isVisible():
                        parent_widget = self.main_window
                except (RuntimeError, AttributeError):
                    pass
        except Exception:
            pass
        
        if parent_widget is None:
            try:
                if hasattr(self, 'isVisible') and self.isVisible():
                    parent_widget = self
            except (RuntimeError, AttributeError):
                pass
        
        if parent_widget is None:
            app = QApplication.instance()
            if app is not None:
                try:
                    for widget in app.topLevelWidgets():
                        if hasattr(widget, 'isVisible') and widget.isVisible():
                            parent_widget = widget
                            break
                except (RuntimeError, AttributeError):
                    pass
        
        if parent_widget is None:
            return

        try:
            if self._current_settings_window is not None:
                try:
                    if self._current_settings_window.isVisible():
                        self._current_settings_window.close()
                except (RuntimeError, AttributeError):
                    pass
                self._current_settings_window = None
            
            self._current_settings_window = ModernSettingsWindow(parent_widget)
            self._current_settings_window.settings_saved.connect(self._update_appearance_after_settings_change)
            self._current_settings_window.finished.connect(self._on_settings_window_closed)
            self._current_settings_window.exec_()
        except (RuntimeError, AttributeError):
            self._current_settings_window = None
        except Exception as e:
            import traceback
            print(f"[ERROR] 打开设置窗口失败: {str(e)}")
            traceback.print_exc()
            self._current_settings_window = None
    
    def _on_settings_window_closed(self, result):
        """设置窗口关闭时的处理"""
        try:
            self._current_settings_window = None
        except (RuntimeError, AttributeError):
            pass
    
    def _update_appearance_after_settings_change(self):
        """
        设置更新后更新应用外观
        """
        try:
            app = QApplication.instance()

            if hasattr(app, 'update_theme') and callable(app.update_theme):
                app.update_theme()

            if hasattr(self, 'parent') and self.parent() and hasattr(self.parent(), 'update_theme'):
                self.parent().update_theme()

            # 更新时间线按钮的可见性
            self._update_timeline_button_visibility()
            
            if self._current_settings_window is not None:
                try:
                    if self._current_settings_window.isVisible():
                        self._refresh_settings_window()
                except (RuntimeError, AttributeError):
                    pass
        except (RuntimeError, AttributeError):
            pass
    
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
            print(f"[ERROR] 更新时间线按钮可见性失败: {e}")

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
    from PyQt5.QtWidgets import QApplication, QMainWindow
    
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
    sys.exit(app.exec_())
