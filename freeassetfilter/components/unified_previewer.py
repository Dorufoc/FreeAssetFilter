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
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QGroupBox, QGridLayout, QSizePolicy, QPushButton, QMessageBox, QApplication
)

# 导入自定义按钮
from freeassetfilter.widgets.custom_widgets import CustomButton
from PyQt5.QtCore import Qt
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QThread
from PyQt5.QtGui import QFont

from freeassetfilter.core.file_info_browser import FileInfoBrowser
from freeassetfilter.components.folder_content_list import FolderContentList
from freeassetfilter.components.archive_browser import ArchiveBrowser
from freeassetfilter.widgets.custom_widgets import CustomMessageBox, CustomProgressBar

class UnifiedPreviewer(QWidget):
    """
    统一文件预览器组件
    根据文件类型自动选择合适的预览组件
    """
    
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
        
        # 初始化当前预览的文件信息
        self.current_file_info = None
        
        # 初始化文件信息查看器
        self.file_info_viewer = FileInfoBrowser()
        
        # 初始化当前预览组件
        self.current_preview_widget = None
        self.current_preview_type = None
        
        # 初始化进度条弹窗
        self.progress_dialog = None
        self.is_cancelled = False
        # 初始化临时PDF文件路径，用于文档预览
        self.temp_pdf_path = None
        
        # 初始化UI
        self.init_ui()
    
    def init_ui(self):
        """
        初始化用户界面
        """
        # 应用DPI缩放因子到布局参数
        scaled_spacing = int(10 * self.dpi_scale)
        scaled_margin = int(10 * self.dpi_scale)
        scaled_font_size = int(12 * self.dpi_scale)
        scaled_control_margin = int(5 * self.dpi_scale)
        
        # 创建主布局
        main_layout = QVBoxLayout(self)
        self.setStyleSheet("background-color: #f1f3f5;")
        main_layout.setSpacing(scaled_spacing)
        main_layout.setContentsMargins(scaled_margin, scaled_margin, scaled_margin, scaled_margin)
        
        # 创建标题
        #title_label = QLabel("统一文件预览器")
        # 只设置字体大小和粗细，不指定字体名称，使用全局字体
        font = QFont("", scaled_font_size, QFont.Bold)
        #title_label.setFont(font)
        #main_layout.addWidget(title_label)
        
        # 创建预览内容区域
        self.preview_area = QWidget()
        self.preview_layout = QVBoxLayout(self.preview_area)
        
        # 创建预览控制栏（右上角按钮）- 放在预览组件上方
        self.control_layout = QHBoxLayout()
        self.control_layout.setContentsMargins(0, 0, 0, scaled_control_margin)  # 底部添加间距，应用DPI缩放
        self.control_layout.setAlignment(Qt.AlignRight)
        
        # 创建"全局设置"按钮
        self.global_settings_button = CustomButton("全局设置", button_type="emphasis")
        self.global_settings_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.global_settings_button.clicked.connect(self._open_global_settings)
        
        # 创建"使用系统默认方式打开"按钮
        self.open_with_system_button = CustomButton("使用系统默认方式打开", button_type="normal")
        self.open_with_system_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.open_with_system_button.clicked.connect(self._open_file_with_system)
        self.open_with_system_button.hide()  # 默认隐藏
        
        self.control_layout.addWidget(self.global_settings_button)
        self.control_layout.addWidget(self.open_with_system_button)
        self.preview_layout.addLayout(self.control_layout)  # 控制栏放在最上方
        
        # 添加默认提示信息
        self.default_label = QLabel("请选择一个文件进行预览")
        self.default_label.setAlignment(Qt.AlignCenter)
        
        # 从app对象获取全局默认字体大小和DPI缩放因子
        app = QApplication.instance()
        default_font_size = getattr(app, 'default_font_size', 14)
        dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        scaled_font_size = int(default_font_size * dpi_scale)
        
        self.default_label.setStyleSheet(f"font-size: {scaled_font_size}pt; color: #999;")
        self.preview_layout.addWidget(self.default_label)
        
        main_layout.addWidget(self.preview_area, 2)
        
        # 创建文件信息区域
        self.info_group = QGroupBox(" ")
        self.info_layout = QVBoxLayout(self.info_group)
        self.info_layout.setContentsMargins(5, 5, 5, 5)
        
        # 创建文件信息查看器的UI
        self.file_info_widget = self.file_info_viewer.get_ui()
        self.info_layout.addWidget(self.file_info_widget)
        
        main_layout.addWidget(self.info_group, 1)
    
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
        
        debug(f"接收到file_selected信号，文件信息: {file_info}")
        
        self.current_file_info = file_info
        
        # 更新文件信息查看器
        debug("更新文件信息查看器")
        self.file_info_viewer.set_file(file_info)
        
        # 根据文件类型显示不同的预览内容
        debug("调用_show_preview()显示预览")
        self._show_preview()
    
    def _show_preview(self):
        """
        根据文件类型显示预览内容，确保只有一个预览组件在工作
        """
        # 生成带时间戳的debug信息
        import datetime
        def debug(msg):
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            print(f"[{timestamp}] [UnifiedPreviewer] {msg}")
        
        debug("开始处理文件预览")
        
        if not self.current_file_info:
            # 没有文件信息时，显示默认提示
            debug("没有文件信息，显示默认提示")
            self._clear_preview()
            self.preview_layout.addWidget(self.default_label)
            self.default_label.show()
            self.open_with_system_button.hide()
            return
        
        debug(f"获取文件信息: {self.current_file_info}")
        
        # 获取文件路径和类型
        file_path = self.current_file_info["path"]
        file_type = self.current_file_info["suffix"]
        
        debug(f"提取的文件路径: {file_path}, 文件类型: {file_type}")
        
        # 确定预览类型
        preview_type = None
        if self.current_file_info["is_dir"]:
            preview_type = "dir"
        elif file_type in ["jpg", "jpeg", "png", "gif", "bmp", "tiff", "webp", "svg", "cr2", "cr3", "nef", "arw", "dng", "orf"]:
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
        else:
            preview_type = "unknown"
        
        debug(f"确定预览类型: {preview_type}")
        
        # 检查当前预览组件是否可以处理该类型
        # 如果预览类型相同，直接更新组件
        if preview_type == self.current_preview_type and self.current_preview_widget:
            # 更新现有组件
            debug(f"预览类型相同，直接更新组件: {preview_type}")
            self._update_preview_widget(file_path, preview_type)
        else:
            # 对于所有预览类型，都使用后台线程加载，确保UI响应
            debug(f"预览类型不同，创建新组件: {preview_type}")
            
            # 显示进度条弹窗
            title = "正在加载预览"
            message = "正在准备预览组件..."
            if preview_type == "video":
                title = "正在加载视频"
                message = "正在准备视频播放器..."
                debug("显示视频加载进度条")
            elif preview_type == "audio":
                title = "正在加载音频"
                message = "正在准备音频播放器..."
                debug("显示音频加载进度条")
            elif preview_type == "pdf":
                title = "正在加载PDF"
                message = "正在准备PDF阅读器..."
                debug("显示PDF加载进度条")
            elif preview_type == "archive":
                title = "正在加载压缩包"
                message = "正在准备压缩包浏览器..."
                debug("显示压缩包加载进度条")
            elif preview_type == "image":
                title = "正在加载图片"
                message = "正在准备图片查看器..."
                debug("显示图片加载进度条")
            elif preview_type == "text":
                title = "正在加载文本"
                message = "正在准备文本查看器..."
                debug("显示文本加载进度条")
            elif preview_type == "dir":
                title = "正在加载文件夹"
                message = "正在准备文件夹浏览器..."
                debug("显示文件夹加载进度条")
            
            self._show_progress_dialog(title, message)
            
            # 预览类型不同，清除当前组件，创建新组件
            debug("清除当前预览组件")
            self._clear_preview()
            
            # 创建后台加载线程
            debug(f"创建后台加载线程，预览类型: {preview_type}, 文件路径: {file_path}")
            self._preview_thread = self.PreviewLoaderThread(file_path, preview_type)
            
            # 连接线程信号
            debug("连接线程信号")
            self._preview_thread.preview_created.connect(self._on_preview_created)
            self._preview_thread.preview_error.connect(self._on_preview_error)
            self._preview_thread.preview_progress.connect(self._on_progress_updated)
            
            # 启动线程
            debug("启动后台加载线程")
            self._preview_thread.start()
            
            # 更新当前预览类型
            debug(f"更新当前预览类型: {preview_type}")
            self.current_preview_type = preview_type
        
        # 显示"使用系统默认方式打开"按钮
        self.open_with_system_button.show()
        
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
            from freeassetfilter.widgets.custom_widgets import CustomMessageBox
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
            from freeassetfilter.widgets.custom_widgets import CustomMessageBox
            msg_box = CustomMessageBox(self)
            msg_box.set_title("错误")
            msg_box.set_text(f"无法打开文件: {str(e)}")
            msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            msg_box.exec_()
    
    def _clear_preview(self):
        """
        清除当前预览内容，确保所有组件都被正确释放，但保留控制栏
        """
        # 先移除默认标签（如果存在），避免重复添加
        if hasattr(self, 'default_label') and self.default_label and self.default_label.parent() is self.preview_area:
            self.preview_layout.removeWidget(self.default_label)
            self.default_label.hide()
        
        # 停止当前预览组件的播放（如果是视频或音频）
        if self.current_preview_widget:
            # 停止播放
            if hasattr(self.current_preview_widget, 'stop'):
                try:
                    self.current_preview_widget.stop()
                except Exception as e:
                    print(f"停止预览组件时出错: {e}")
            
            # 断开所有信号连接
            self.current_preview_widget.disconnect()
            
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
        # 删除临时PDF文件（如果存在）
        print("=== 进入_clear_preview方法 ===")
        print(f"hasattr(temp_pdf_path): {hasattr(self, 'temp_pdf_path')}")
        if hasattr(self, 'temp_pdf_path'):
            print(f"temp_pdf_path值: {self.temp_pdf_path}")
            print(f"temp_pdf_path存在: {os.path.exists(self.temp_pdf_path) if self.temp_pdf_path else False}")
            if self.temp_pdf_path and os.path.exists(self.temp_pdf_path):
                try:
                    os.remove(self.temp_pdf_path)
                    print(f"已删除临时PDF文件: {self.temp_pdf_path}")
                except Exception as e:
                    print(f"删除临时PDF文件失败: {e}")
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
            # 如果是文档类型预览，先清理旧的临时PDF文件
            if preview_type == "document":
                # 清理旧的临时PDF文件
                if hasattr(self, 'temp_pdf_path') and self.temp_pdf_path and os.path.exists(self.temp_pdf_path):
                    try:
                        os.remove(self.temp_pdf_path)
                        print(f"已删除旧临时PDF文件: {self.temp_pdf_path}")
                    except Exception as e:
                        print(f"删除旧临时PDF文件失败: {e}")
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
        error_label.setStyleSheet("color: red; font-weight: bold; word-wrap: true;")
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
            # 使用专业的PhotoViewer组件进行图片预览
            from freeassetfilter.components.photo_viewer import PhotoViewer
            
            # 创建PhotoViewer实例
            photo_viewer = PhotoViewer()
            # 加载图片
            photo_viewer.load_image_from_path(file_path)
            
            self.preview_layout.addWidget(photo_viewer)
            self.current_preview_widget = photo_viewer
        except Exception as e:
            # 如果PhotoViewer加载失败，使用简单的QLabel显示
            try:
                from PyQt5.QtGui import QPixmap
                from PyQt5.QtWidgets import QLabel, QScrollArea
                
                # 创建滚动区域
                scroll_area = QScrollArea()
                scroll_area.setWidgetResizable(True)
                
                # 创建图片标签
                image_label = QLabel()
                pixmap = QPixmap(file_path)
                image_label.setPixmap(pixmap)
                image_label.setAlignment(Qt.AlignCenter)
                
                scroll_area.setWidget(image_label)
                self.preview_layout.addWidget(scroll_area)
                self.current_preview_widget = scroll_area
            except Exception as simple_e:
                error_message = f"图片预览失败: {str(simple_e)}"
                self._show_error_with_copy_button(error_message)
    
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
            
            # 添加到布局
            self.preview_layout.addWidget(video_player)
            self.current_preview_widget = video_player
            
            # 加载并播放视频文件
            video_player.load_media(file_path)
            video_player.play()
            
            print(f"[DEBUG] 视频预览组件已创建并开始播放: {file_path}")
        except Exception as e:
            import traceback
            # 打印详细错误信息到控制台
            print(f"[ERROR] 视频预览失败: {str(e)}")
            traceback.print_exc()
            # 显示友好的错误信息到界面
            error_message = f"视频预览失败: {str(e)}"
            self._show_error_with_copy_button(error_message)
    
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
            
            self.preview_layout.addWidget(audio_player)
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
            
            self.preview_layout.addWidget(pdf_previewer)
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
        progress_bar = CustomProgressBar(is_interactive=False)
        progress_bar.setRange(0, 100)
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
    
    def _open_global_settings(self):
        """
        打开全局设置窗口
        """
        # 创建全局设置窗口
        from freeassetfilter.widgets.custom_widgets import CustomWindow
        from freeassetfilter.widgets.setting_widgets import CustomSettingItem
        from PyQt5.QtWidgets import QScrollArea, QVBoxLayout, QGroupBox, QWidget
        from freeassetfilter.widgets.custom_widgets import CustomMessageBox
        
        # 获取应用实例和DPI缩放因子
        app = QApplication.instance()
        dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 初始化设置管理器
        from freeassetfilter.core.settings_manager import SettingsManager
        settings_manager = getattr(app, 'settings_manager', SettingsManager())
        
        # 创建自定义窗口，确保它是独立的顶级窗口
        self.settings_window = CustomWindow("全局设置", None)
        # 设置窗口标志，确保它是一个独立的顶级窗口
        self.settings_window.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.settings_window.setAttribute(Qt.WA_TranslucentBackground)
        self.settings_window.setGeometry(100, 100, int(800 * dpi_scale), int(600 * dpi_scale))
        
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("background-color: #f1f3f5;")
        
        # 创建滚动内容容器
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background-color: #f1f3f5;")
        scroll_layout = QVBoxLayout(scroll_content)
        
        # 获取主程序的全局常量和用户设置
        default_font_size = getattr(app, 'default_font_size', 20)
        # 从设置管理器获取全局DPI系数，而不是直接使用当前的dpi_scale_factor
        global_dpi_scale = settings_manager.get_setting("dpi.global_scale_factor", 1.0)
        
        # 主程序设置项组
        main_program_group = QGroupBox("主程序设置")
        # 设置分组标题字体大小，使用合适的大小，避免过大
        group_font = QFont()
        group_font.setPointSize(int(14 * dpi_scale))
        group_font.setBold(True)
        main_program_group.setFont(group_font)
        main_program_group.setStyleSheet("background-color: #f1f3f5;")
        main_program_layout = QVBoxLayout(main_program_group)
        # 添加适当的间距，避免分组标题与子项重叠
        main_program_layout.setContentsMargins(int(10 * dpi_scale), int(20 * dpi_scale), int(10 * dpi_scale), int(10 * dpi_scale))
        main_program_layout.setSpacing(int(10 * dpi_scale))
        
        # DPI设置
        dpi_setting = CustomSettingItem(
            text="DPI设置",
            secondary_text="调整界面元素的DPI缩放比例",
            interaction_type=CustomSettingItem.INPUT_BUTTON_TYPE,
            placeholder="输入DPI缩放值",
            initial_text=str(global_dpi_scale),
            button_text="应用"
        )
        # 连接DPI设置的应用按钮信号
        def on_dpi_applied(text):
            try:
                # 尝试将输入转换为浮点数
                new_dpi_scale = float(text)
                if new_dpi_scale > 0:
                    # 获取当前应用实例
                    app = QApplication.instance()
                    
                    # 保存原始DPI系数，用于回退
                    original_dpi_scale = settings_manager.get_setting("dpi.global_scale_factor", 1.0)
                    
                    # 临时应用新的DPI系数
                    settings_manager.set_setting("dpi.global_scale_factor", new_dpi_scale)
                    
                    # 创建带有倒计时功能的自定义提示窗
                    from freeassetfilter.widgets.custom_widgets import CustomMessageBox
                    from freeassetfilter.widgets.progress_widgets import CustomProgressBar
                    from PyQt5.QtCore import QTimer, Qt
                    
                    # 创建进度条
                    progress_bar = CustomProgressBar(is_interactive=False)
                    progress_bar.setRange(0, 100)
                    progress_bar.setValue(0)
                    
                    # 创建自定义提示窗
                    confirm_box = CustomMessageBox(self)
                    confirm_box.set_title("DPI设置预览")
                    confirm_box.set_text("DPI设置已临时应用，10秒后将自动回退，点击保存更改以保留设置")
                    confirm_box.set_progress(progress_bar)
                    confirm_box.set_buttons(["保存更改", "放弃"], orientations=Qt.Horizontal)
                    
                    # 倒计时变量
                    countdown = 10
                    
                    # 更新进度条的函数
                    def update_progress():
                        nonlocal countdown
                        countdown -= 0.1
                        progress = int((10 - countdown) * 10)
                        progress_bar.setValue(progress)
                        if countdown <= 0:
                            # 倒计时结束，回退到原始DPI系数
                            settings_manager.set_setting("dpi.global_scale_factor", original_dpi_scale)
                            confirm_box.close()
                            msg_box = CustomMessageBox(self)
                            msg_box.set_title("提示")
                            msg_box.set_text("DPI设置已自动回退")
                            msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                            msg_box.exec_()
                            # 更新设置项的显示值
                            dpi_setting.set_input_text(str(original_dpi_scale))
                            timer.stop()
                    
                    # 创建定时器，每100毫秒更新一次进度条
                    timer = QTimer()
                    timer.timeout.connect(update_progress)
                    timer.start(100)
                    
                    # 按钮点击处理函数
                    def on_button_clicked(button_index):
                        timer.stop()
                        if button_index == 0:  # 保存更改
                            # 保存设置
                            settings_manager.save_settings()
                            confirm_box.close()
                            msg_box = CustomMessageBox(self)
                            msg_box.set_title("成功")
                            msg_box.set_text("DPI设置已保存")
                            msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                            msg_box.exec_()
                        else:  # 放弃
                            # 回退到原始DPI系数
                            settings_manager.set_setting("dpi.global_scale_factor", original_dpi_scale)
                            confirm_box.close()
                            msg_box = CustomMessageBox(self)
                            msg_box.set_title("提示")
                            msg_box.set_text("DPI设置已回退")
                            msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                            msg_box.exec_()
                            # 更新设置项的显示值
                            dpi_setting.set_input_text(str(original_dpi_scale))
                    
                    # 连接按钮点击信号
                    confirm_box.buttonClicked.connect(on_button_clicked)
                    
                    # 显示提示窗
                    confirm_box.show()
                else:
                    msg_box = CustomMessageBox(self)
                    msg_box.set_title("错误")
                    msg_box.set_text("DPI缩放值必须大于0")
                    msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                    msg_box.exec_()
            except ValueError:
                msg_box = CustomMessageBox(self)
                msg_box.set_title("错误")
                msg_box.set_text("请输入有效的数字")
                msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                msg_box.exec_()
        dpi_setting.input_submitted.connect(on_dpi_applied)
        main_program_layout.addWidget(dpi_setting)
        
        # 字体大小设置
        font_size_setting = CustomSettingItem(
            text="字体大小设置",
            secondary_text="调整界面全局字体大小",
            interaction_type=CustomSettingItem.INPUT_BUTTON_TYPE,
            placeholder="输入字体大小",
            initial_text=str(settings_manager.get_setting("font.size", default_font_size)),
            button_text="应用"
        )
        # 连接字体大小设置的应用按钮信号
        def on_font_size_applied(text):
            try:
                # 尝试将输入转换为整数
                new_font_size = int(text)
                if new_font_size > 0:
                    # 获取当前应用实例
                    app = QApplication.instance()
                    
                    # 保存原始字体大小，用于回退
                    original_font_size = settings_manager.get_setting("font.size", default_font_size)
                    
                    # 临时应用新的字体大小
                    settings_manager.set_setting("font.size", new_font_size)
                    
                    # 创建带有倒计时功能的自定义提示窗
                    from freeassetfilter.widgets.custom_widgets import CustomMessageBox
                    from freeassetfilter.widgets.progress_widgets import CustomProgressBar
                    from PyQt5.QtCore import QTimer, Qt
                    
                    # 创建进度条
                    progress_bar = CustomProgressBar(is_interactive=False)
                    progress_bar.setRange(0, 100)
                    progress_bar.setValue(0)
                    
                    # 创建自定义提示窗
                    confirm_box = CustomMessageBox(self)
                    confirm_box.set_title("字体大小设置预览")
                    confirm_box.set_text("字体大小已临时应用，10秒后将自动回退，点击保存更改以保留设置")
                    confirm_box.set_progress(progress_bar)
                    confirm_box.set_buttons(["保存更改", "放弃"], orientations=Qt.Horizontal)
                    
                    # 倒计时变量
                    countdown = 10
                    
                    # 更新进度条的函数
                    def update_progress():
                        nonlocal countdown
                        countdown -= 0.1
                        progress = int((10 - countdown) * 10)
                        progress_bar.setValue(progress)
                        if countdown <= 0:
                            # 倒计时结束，回退到原始字体大小
                            settings_manager.set_setting("font.size", original_font_size)
                            confirm_box.close()
                            msg_box = CustomMessageBox(self)
                            msg_box.set_title("提示")
                            msg_box.set_text("字体大小设置已自动回退")
                            msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                            msg_box.exec_()
                            # 更新设置项的显示值
                            font_size_setting.set_input_text(str(original_font_size))
                            timer.stop()
                    
                    # 创建定时器，每100毫秒更新一次进度条
                    timer = QTimer()
                    timer.timeout.connect(update_progress)
                    timer.start(100)
                    
                    # 按钮点击处理函数
                    def on_button_clicked(button_index):
                        timer.stop()
                        if button_index == 0:  # 保存更改
                            # 保存设置
                            settings_manager.save_settings()
                            confirm_box.close()
                            msg_box = CustomMessageBox(self)
                            msg_box.set_title("成功")
                            msg_box.set_text("字体大小设置已保存")
                            msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                            msg_box.exec_()
                        else:  # 放弃
                            # 回退到原始字体大小
                            settings_manager.set_setting("font.size", original_font_size)
                            confirm_box.close()
                            msg_box = CustomMessageBox(self)
                            msg_box.set_title("提示")
                            msg_box.set_text("字体大小设置已回退")
                            msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                            msg_box.exec_()
                            # 更新设置项的显示值
                            font_size_setting.set_input_text(str(original_font_size))
                    
                    # 连接按钮点击信号
                    confirm_box.buttonClicked.connect(on_button_clicked)
                    
                    # 显示提示窗
                    confirm_box.show()
                else:
                    msg_box = CustomMessageBox(self)
                    msg_box.set_title("错误")
                    msg_box.set_text("字体大小必须大于0")
                    msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                    msg_box.exec_()
            except ValueError:
                msg_box = CustomMessageBox(self)
                msg_box.set_title("错误")
                msg_box.set_text("请输入有效的整数")
                msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                msg_box.exec_()
        font_size_setting.input_submitted.connect(on_font_size_applied)
        main_program_layout.addWidget(font_size_setting)
        
        # 字体样式设置
        font_style_setting = CustomSettingItem(
            text="字体样式设置",
            secondary_text="调整界面全局字体样式",
            interaction_type=CustomSettingItem.INPUT_BUTTON_TYPE,
            placeholder="输入字体样式",
            initial_text=settings_manager.get_setting("font.style", "Microsoft YaHei"),
            button_text="应用"
        )
        # 连接字体样式设置的应用按钮信号
        def on_font_style_applied(text):
            if text:
                # 获取当前应用实例
                app = QApplication.instance()
                
                # 保存原始字体样式，用于回退
                original_font_style = settings_manager.get_setting("font.style", "Microsoft YaHei")
                
                # 临时应用新的字体样式
                settings_manager.set_setting("font.style", text)
                
                # 创建带有倒计时功能的自定义提示窗
                from freeassetfilter.widgets.custom_widgets import CustomMessageBox
                from freeassetfilter.widgets.progress_widgets import CustomProgressBar
                from PyQt5.QtCore import QTimer, Qt
                
                # 创建进度条
                progress_bar = CustomProgressBar(is_interactive=False)
                progress_bar.setRange(0, 100)
                progress_bar.setValue(0)
                
                # 创建自定义提示窗
                confirm_box = CustomMessageBox(self)
                confirm_box.set_title("字体样式设置预览")
                confirm_box.set_text("字体样式已临时应用，10秒后将自动回退，点击保存更改以保留设置")
                confirm_box.set_progress(progress_bar)
                confirm_box.set_buttons(["保存更改", "放弃"], orientations=Qt.Horizontal)
                
                # 倒计时变量
                countdown = 10
                
                # 更新进度条的函数
                def update_progress():
                    nonlocal countdown
                    countdown -= 0.1
                    progress = int((10 - countdown) * 10)
                    progress_bar.setValue(progress)
                    if countdown <= 0:
                        # 倒计时结束，回退到原始字体样式
                        settings_manager.set_setting("font.style", original_font_style)
                        confirm_box.close()
                        msg_box = CustomMessageBox(self)
                        msg_box.set_title("提示")
                        msg_box.set_text("字体样式设置已自动回退")
                        msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                        msg_box.exec_()
                        # 更新设置项的显示值
                        font_style_setting.set_input_text(original_font_style)
                        timer.stop()
                
                # 创建定时器，每100毫秒更新一次进度条
                timer = QTimer()
                timer.timeout.connect(update_progress)
                timer.start(100)
                
                # 按钮点击处理函数
                def on_button_clicked(button_index):
                    timer.stop()
                    if button_index == 0:  # 保存更改
                        # 保存设置
                        settings_manager.save_settings()
                        confirm_box.close()
                        msg_box = CustomMessageBox(self)
                        msg_box.set_title("成功")
                        msg_box.set_text("字体样式设置已保存")
                        msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                        msg_box.exec_()
                    else:  # 放弃
                        # 回退到原始字体样式
                        settings_manager.set_setting("font.style", original_font_style)
                        confirm_box.close()
                        msg_box = CustomMessageBox(self)
                        msg_box.set_title("提示")
                        msg_box.set_text("字体样式设置已回退")
                        msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                        msg_box.exec_()
                        # 更新设置项的显示值
                        font_style_setting.set_input_text(original_font_style)
                
                # 连接按钮点击信号
                confirm_box.buttonClicked.connect(on_button_clicked)
                
                # 显示提示窗
                confirm_box.show()
            else:
                msg_box = CustomMessageBox(self)
                msg_box.set_title("错误")
                msg_box.set_text("字体样式不能为空")
                msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                msg_box.exec_()
        font_style_setting.input_submitted.connect(on_font_style_applied)
        main_program_layout.addWidget(font_style_setting)
        
        # 主题设置
        theme_setting = CustomSettingItem(
            text="主题设置",
            secondary_text="调整应用主题样式",
            interaction_type=CustomSettingItem.BUTTON_GROUP_TYPE,
            buttons=[{"text": "设计器", "type": "primary"}]
        )
        main_program_layout.addWidget(theme_setting)
        
        # 文件选择器设置项组
        file_selector_group = QGroupBox("文件选择器")
        # 设置分组标题字体大小，使用合适的大小，避免过大
        file_selector_group.setFont(group_font)
        file_selector_group.setStyleSheet("background-color: #f1f3f5;")
        file_selector_layout = QVBoxLayout(file_selector_group)
        # 添加适当的间距，避免分组标题与子项重叠
        file_selector_layout.setContentsMargins(int(10 * dpi_scale), int(20 * dpi_scale), int(10 * dpi_scale), int(10 * dpi_scale))
        file_selector_layout.setSpacing(int(10 * dpi_scale))
        
        # 缩略图缓存自动清理
        thumbnail_cache_setting = CustomSettingItem(
            text="缩略图缓存自动清理",
            secondary_text="是否自动清理缩略图缓存",
            interaction_type=CustomSettingItem.SWITCH_TYPE,
            initial_value=settings_manager.get_setting("file_selector.auto_clear_thumbnail_cache", True)
        )
        # 连接开关信号
        def on_thumbnail_cache_toggled(checked):
            settings_manager.set_setting("file_selector.auto_clear_thumbnail_cache", checked)
            settings_manager.save_settings()
        thumbnail_cache_setting.switch_toggled.connect(on_thumbnail_cache_toggled)
        file_selector_layout.addWidget(thumbnail_cache_setting)
        
        # 启动时恢复上次退出路径
        restore_path_setting = CustomSettingItem(
            text="启动时恢复上次退出路径",
            secondary_text="是否在启动时恢复上次退出时的路径",
            interaction_type=CustomSettingItem.SWITCH_TYPE,
            initial_value=settings_manager.get_setting("file_selector.restore_last_path", True)
        )
        # 连接开关信号
        def on_restore_path_toggled(checked):
            settings_manager.set_setting("file_selector.restore_last_path", checked)
            settings_manager.save_settings()
        restore_path_setting.switch_toggled.connect(on_restore_path_toggled)
        file_selector_layout.addWidget(restore_path_setting)
        
        # 返回上级鼠标快捷键
        return_shortcut_setting = CustomSettingItem(
            text="返回上级鼠标快捷键",
            secondary_text="设置返回上级目录的鼠标快捷键",
            interaction_type=CustomSettingItem.BUTTON_GROUP_TYPE,
            buttons=[{"text": "设置", "type": "primary"}]
        )
        file_selector_layout.addWidget(return_shortcut_setting)
        
        # 默认布局
        default_layout_setting = CustomSettingItem(
            text="默认布局",
            secondary_text="设置文件选择器的默认布局",
            interaction_type=CustomSettingItem.BUTTON_GROUP_TYPE,
            buttons=[{"text": "卡片布局", "type": "normal"}, {"text": "列表布局", "type": "normal"}]
        )
        file_selector_layout.addWidget(default_layout_setting)
        
        # 文件存储池设置项组
        file_staging_group = QGroupBox("文件存储池")
        # 设置分组标题字体大小，使用合适的大小，避免过大
        file_staging_group.setFont(group_font)
        file_staging_group.setStyleSheet("background-color: #f1f3f5;")
        file_staging_layout = QVBoxLayout(file_staging_group)
        # 添加适当的间距，避免分组标题与子项重叠
        file_staging_layout.setContentsMargins(int(10 * dpi_scale), int(20 * dpi_scale), int(10 * dpi_scale), int(10 * dpi_scale))
        file_staging_layout.setSpacing(int(10 * dpi_scale))
        
        # 上次记录自动恢复
        restore_records_setting = CustomSettingItem(
            text="上次记录自动恢复",
            secondary_text="是否自动恢复上次的文件存储池记录",
            interaction_type=CustomSettingItem.SWITCH_TYPE,
            initial_value=settings_manager.get_setting("file_staging.auto_restore_records", True)
        )
        # 连接开关信号
        def on_restore_records_toggled(checked):
            settings_manager.set_setting("file_staging.auto_restore_records", checked)
            settings_manager.save_settings()
        restore_records_setting.switch_toggled.connect(on_restore_records_toggled)
        file_staging_layout.addWidget(restore_records_setting)
        
        # 默认导出数据路径
        export_data_path_setting = CustomSettingItem(
            text="默认导出数据路径",
            secondary_text="设置默认的数据导出路径",
            interaction_type=CustomSettingItem.INPUT_BUTTON_TYPE,
            placeholder="输入导出数据路径",
            initial_text=settings_manager.get_setting("file_staging.default_export_data_path", ""),
            button_text="应用"
        )
        # 连接数据导出路径设置的应用按钮信号
        def on_export_data_path_applied(text):
            settings_manager.set_setting("file_staging.default_export_data_path", text)
            settings_manager.save_settings()
            from freeassetfilter.widgets.custom_widgets import CustomMessageBox
            msg_box = CustomMessageBox(self)
            msg_box.set_title("成功")
            msg_box.set_text("默认导出数据路径已保存")
            msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            msg_box.exec_()
        export_data_path_setting.input_submitted.connect(on_export_data_path_applied)
        file_staging_layout.addWidget(export_data_path_setting)
        
        # 默认导出文件路径
        export_file_path_setting = CustomSettingItem(
            text="默认导出文件路径",
            secondary_text="设置默认的文件导出路径",
            interaction_type=CustomSettingItem.INPUT_BUTTON_TYPE,
            placeholder="输入导出文件路径",
            initial_text=settings_manager.get_setting("file_staging.default_export_file_path", ""),
            button_text="应用"
        )
        # 连接文件导出路径设置的应用按钮信号
        def on_export_file_path_applied(text):
            settings_manager.set_setting("file_staging.default_export_file_path", text)
            settings_manager.save_settings()
            from freeassetfilter.widgets.custom_widgets import CustomMessageBox
            msg_box = CustomMessageBox(self)
            msg_box.set_title("成功")
            msg_box.set_text("默认导出文件路径已保存")
            msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            msg_box.exec_()
        export_file_path_setting.input_submitted.connect(on_export_file_path_applied)
        file_staging_layout.addWidget(export_file_path_setting)
        
        # 导出后删除原始文件
        delete_original_setting = CustomSettingItem(
            text="导出后删除原始文件",
            secondary_text="导出文件后是否删除原始文件",
            interaction_type=CustomSettingItem.SWITCH_TYPE,
            initial_value=settings_manager.get_setting("file_staging.delete_original_after_export", False)
        )
        # 连接开关信号
        def on_delete_original_toggled(checked):
            settings_manager.set_setting("file_staging.delete_original_after_export", checked)
            settings_manager.save_settings()
        delete_original_setting.switch_toggled.connect(on_delete_original_toggled)
        file_staging_layout.addWidget(delete_original_setting)
        
        # 将所有设置组添加到滚动布局
        scroll_layout.addWidget(main_program_group)
        scroll_layout.addWidget(file_selector_group)
        scroll_layout.addWidget(file_staging_group)
        
        # 设置滚动区域内容
        scroll_area.setWidget(scroll_content)
        
        # 添加滚动区域到窗口
        self.settings_window.add_widget(scroll_area)
        
        # 显示窗口
        self.settings_window.show()
    
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

            # 添加创建的组件到布局
            if created_widget:
                self.preview_layout.addWidget(created_widget)
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
            error_label.setStyleSheet("color: red; font-weight: bold; word-wrap: true;")
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
        error_label.setStyleSheet("color: red; font-weight: bold; word-wrap: true;")
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
                if self.preview_type in ["video", "audio", "pdf", "archive", "image", "text", "dir", "document"]:
                    # 模拟进度更新，确保UI能响应
                    import time
                    for i in range(20, 100, 10):
                        if self.is_cancelled:
                            self.preview_error.emit("预览已取消")
                            return
                        self.preview_progress.emit(i, f"正在加载{self.preview_type}文件...")
                        # 短暂休眠，让主线程有机会处理事件
                        time.sleep(0.1)
                    
                    # 标记预览准备完成
                    self.preview_progress.emit(100, f"{self.preview_type}文件准备完成")
                    
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
            from freeassetfilter.components.text_previewer import TextPreviewer
            
            # 创建文本预览器
            text_previewer = TextPreviewer()
            
            # 设置文件，开始异步读取
            text_previewer.set_file(file_path)
            
            self.preview_layout.addWidget(text_previewer)
            self.current_preview_widget = text_previewer
        except Exception as e:
            error_message = f"文本预览失败: {str(e)}"
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
            temp_pdf_name = f"{base_name}_temp.pdf"
            self.temp_pdf_path = os.path.join(temp_dir, temp_pdf_name)
            print(f"临时PDF路径: {self.temp_pdf_path}")
            
            print(f"正在将文档转换为PDF: {file_path} -> {self.temp_pdf_path}")
            
            # 找到便携版LibreOffice的路径
            # __file__ = freeassetfilter/components/unified_previewer.py
            # 三个dirname：freeassetfilter/components → freeassetfilter → 项目根目录
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            libreoffice_exe = os.path.join(project_root, "data", "LibreOfficePortable", "App", "LibreOffice", "program", "soffice.exe")
            
            if not os.path.exists(libreoffice_exe):
                # 关闭进度条弹窗
                self._on_file_read_finished()
                # 弹窗提示用户需要安装LibreOffice组件
                QMessageBox.information(
                    self,
                    "LibreOffice组件缺失",
                    "预览Office类文件需要LibreOffice组件支持。\n\n请将LibreOfficePortable解压后放置于:\nFreeassetfilter/data文件夹内\n\n文件夹结构应为：\nFreeAssetFliter/data/LibreOfficePortable/...",
                    QMessageBox.Ok
                )
                # 显示默认提示
                self.default_label.setText("Office文件预览需要LibreOffice组件支持")
                self.preview_layout.addWidget(self.default_label)
                self.default_label.show()
                self.current_preview_widget = self.default_label
                return
            
            # 使用LibreOffice将文档转换为PDF
            cmd = [
                libreoffice_exe,
                "--headless",
                "--convert-to", "pdf:writer_pdf_Export",
                "--outdir", temp_dir,
                file_path
            ]
            
            print(f"执行命令: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                error_msg = f"文档转换失败: {result.stderr}" if result.stderr else f"文档转换失败，返回码: {result.returncode}"
                self._show_error_with_copy_button(error_msg)
                return
            
            # 检查PDF文件是否生成
            # 先获取所有可能的生成文件
            import glob
            generated_pdfs = glob.glob(os.path.join(temp_dir, f"{base_name}*.pdf"))
            
            if generated_pdfs:
                # 找到所有生成的PDF文件
                for pdf_path in generated_pdfs:
                    print(f"找到生成的PDF: {pdf_path}")
                    # 如果不是我们想要的临时文件名，重命名为临时文件名
                    if pdf_path != self.temp_pdf_path:
                        try:
                            # 删除已存在的临时文件（如果有）
                            if os.path.exists(self.temp_pdf_path):
                                os.remove(self.temp_pdf_path)
                            # 重命名为临时文件名
                            os.rename(pdf_path, self.temp_pdf_path)
                            print(f"将PDF重命名为: {self.temp_pdf_path}")
                        except Exception as e:
                            print(f"重命名PDF失败: {e}")
                            # 如果重命名失败，直接使用生成的PDF路径
                            self.temp_pdf_path = pdf_path
                            break
            elif not os.path.exists(self.temp_pdf_path):
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
            error_label.setStyleSheet("color: red; font-weight: bold; word-wrap: true;")
            self.preview_layout.addWidget(error_label)
            self.current_preview_widget = error_label
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
