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
    QGroupBox, QGridLayout, QSizePolicy, QPushButton, QMessageBox
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
        
        # 获取全局字体
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QFont
        app = QApplication.instance()
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
        
        # 初始化UI
        self.init_ui()
    
    def init_ui(self):
        """
        初始化用户界面
        """
        # 创建主布局
        main_layout = QVBoxLayout(self)
        self.setStyleSheet("background-color: #f1f3f5;")
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # 创建标题
        #title_label = QLabel("统一文件预览器")
        # 只设置字体大小和粗细，不指定字体名称，使用全局字体
        font = QFont("", 12, QFont.Bold)
        #title_label.setFont(font)
        #main_layout.addWidget(title_label)
        
        # 创建预览内容区域
        self.preview_area = QWidget()
        self.preview_layout = QVBoxLayout(self.preview_area)
        
        # 创建预览控制栏（右上角按钮）- 放在预览组件上方
        self.control_layout = QHBoxLayout()
        self.control_layout.setContentsMargins(0, 0, 0, 5)  # 底部添加5px间距
        self.control_layout.setAlignment(Qt.AlignRight)
        
        # 创建"使用系统默认方式打开"按钮
        self.open_with_system_button = CustomButton("使用系统默认方式打开", button_type="normal")
        self.open_with_system_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.open_with_system_button.clicked.connect(self._open_file_with_system)
        self.open_with_system_button.hide()  # 默认隐藏
        
        self.control_layout.addWidget(self.open_with_system_button)
        self.preview_layout.addLayout(self.control_layout)  # 控制栏放在最上方
        
        # 添加默认提示信息
        self.default_label = QLabel("请选择一个文件进行预览")
        self.default_label.setAlignment(Qt.AlignCenter)
        self.default_label.setStyleSheet("font-size: 14pt; color: #999;")
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
        elif file_type in ["mp4", "avi", "mov", "mkv", "m4v", "flac", "mxf", "3gp", "mpg", "wmv", "webm", "vob", "ogv", "rmvb"]:
            preview_type = "video"
        elif file_type in ["mp3", "wav", "flac", "ogg", "wma", "m4a", "aiff", "ape", "opus"]:
            preview_type = "audio"
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
            QMessageBox.warning(self, "错误", f"文件不存在: {file_path}")
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
            QMessageBox.warning(self, "错误", f"无法打开文件: {str(e)}")
    
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
                error_label = QLabel(f"图片预览失败: {str(simple_e)}")
                error_label.setAlignment(Qt.AlignCenter)
                self.preview_layout.addWidget(error_label)
                self.current_preview_widget = error_label
    
    def _show_video_preview(self, file_path):
        """
        显示视频预览
        进度条已在_show_preview中显示并在_on_preview_created中关闭
        
        Args:
            file_path (str): 视频文件路径
        """
        try:
            # 尝试导入VideoPlayer组件（基于VLC的播放器）
            from freeassetfilter.components.video_player import VideoPlayer
            
            # 创建VideoPlayer视频播放器
            video_player = VideoPlayer()
            
            # 加载视频文件
            video_player.load_media(file_path)
            
            # 添加到布局
            self.preview_layout.addWidget(video_player)
            self.current_preview_widget = video_player
        except Exception as e:
            import traceback
            # 打印详细错误信息到控制台
            print(f"[ERROR] 视频预览失败: {str(e)}")
            traceback.print_exc()
            # 显示友好的错误信息到界面
            error_label = QLabel(f"视频预览失败: {str(e)}")
            error_label.setAlignment(Qt.AlignCenter)
            error_label.setStyleSheet("color: red; font-weight: bold;")
            error_label.setWordWrap(True)
            self.preview_layout.addWidget(error_label)
            self.current_preview_widget = error_label
    
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
            error_label = QLabel(f"音频预览失败: {str(e)}")
            error_label.setAlignment(Qt.AlignCenter)
            self.preview_layout.addWidget(error_label)
            self.current_preview_widget = error_label
    
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
            pdf_previewer.load_file_from_path(file_path)
            
            self.preview_layout.addWidget(pdf_previewer)
            self.current_preview_widget = pdf_previewer
        except Exception as e:
            error_label = QLabel(f"PDF预览失败: {str(e)}")
            error_label.setAlignment(Qt.AlignCenter)
            self.preview_layout.addWidget(error_label)
            self.current_preview_widget = error_label
    
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
    
    def _on_preview_created(self, preview_widget, preview_type):
        """
        预览准备完成，在主线程中创建预览组件并添加到布局中
        
        Args:
            preview_widget: 预览组件实例（不再使用，改为在主线程创建）
            preview_type (str): 预览类型
        """
        try:
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
            
            # 添加创建的组件到布局
            if created_widget:
                self.preview_layout.addWidget(created_widget)
                self.current_preview_widget = created_widget
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            error_label = QLabel(f"创建预览组件失败: {str(e)}")
            error_label.setAlignment(Qt.AlignCenter)
            error_label.setStyleSheet("color: red; font-weight: bold; word-wrap: true;")
            self.preview_layout.addWidget(error_label)
            self.current_preview_widget = error_label
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
        
        # 显示错误信息
        error_label = QLabel(f"预览失败: {error_message}")
        error_label.setAlignment(Qt.AlignCenter)
        error_label.setStyleSheet("color: red; font-weight: bold; word-wrap: true;")
        self.preview_layout.addWidget(error_label)
        self.current_preview_widget = error_label
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
                if self.preview_type in ["video", "audio", "pdf", "archive", "image", "text", "dir"]:
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
            error_label = QLabel(f"文本预览失败: {str(e)}")
            error_label.setAlignment(Qt.AlignCenter)
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
