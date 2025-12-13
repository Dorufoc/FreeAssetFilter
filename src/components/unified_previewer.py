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
from src.widgets.custom_widgets import CustomButton
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from src.core.file_info_browser import FileInfoBrowser
from src.components.folder_content_list import FolderContentList
from src.components.archive_browser import ArchiveBrowser

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
        
        # 初始化UI
        self.init_ui()
    
    def init_ui(self):
        """
        初始化用户界面
        """
        # 创建主布局
        main_layout = QVBoxLayout(self)
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
        self.current_file_info = file_info
        
        # 更新文件信息查看器
        self.file_info_viewer.set_file(file_info)
        
        # 根据文件类型显示不同的预览内容
        self._show_preview()
    
    def _show_preview(self):
        """
        根据文件类型显示预览内容，确保只有一个预览组件在工作
        """
        if not self.current_file_info:
            # 没有文件信息时，显示默认提示
            self._clear_preview()
            self.preview_layout.addWidget(self.default_label)
            self.default_label.show()
            self.open_with_system_button.hide()
            return
        
        # 获取文件路径和类型
        # print(f"[DEBUG] UnifiedPreviewer - 当前文件信息字典: {self.current_file_info}")
        file_path = self.current_file_info["path"]
        # 确保文件路径是绝对路径，并且格式正确
        if file_path:
            file_path = os.path.abspath(file_path)
            # print(f"[DEBUG] UnifiedPreviewer - 转换为绝对路径: {file_path}")
        file_type = self.current_file_info["suffix"]
        # print(f"[DEBUG] UnifiedPreviewer - 提取的文件路径: {file_path}, 文件类型: {file_type}")
        
        # 检查文件是否存在
        if not os.path.exists(file_path):
            self._clear_preview()
            error_label = QLabel(f"文件不存在: {self.current_file_info['name']}")
            error_label.setAlignment(Qt.AlignCenter)
            error_label.setStyleSheet("color: red; font-weight: bold;")
            self.preview_layout.addWidget(error_label)
            self.current_preview_widget = error_label
            self.current_preview_type = "error"
            self.open_with_system_button.hide()
            return
        
        # 确定预览类型
        preview_type = None
        if self.current_file_info["is_dir"]:
            preview_type = "dir"
        elif file_type in ["jpg", "jpeg", "png", "gif", "bmp", "tiff", "webp", "svg", "cr2", "cr3", "nef", "arw", "dng", "orf"]:
            preview_type = "image"
        elif file_type in ["mp4", "avi", "mov", "mkv", "m4v", "flv", "mxf", "3gp", "mpg", "wmv", "webm", "vob", "ogv", "rmvb"]:
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
        
        # 检查当前预览组件是否可以处理该类型
        # 如果预览类型相同，直接更新组件
        if preview_type == self.current_preview_type and self.current_preview_widget:
            # 更新现有组件
            self._update_preview_widget(file_path, preview_type)
        else:
            # 预览类型不同，清除当前组件，创建新组件
            self._clear_preview()
            
            # 根据预览类型显示新的预览组件
            if preview_type == "dir":
                # 文件夹预览
                self.folder_previewer = FolderContentList()
                self.folder_previewer.set_path(file_path)
                self.preview_layout.addWidget(self.folder_previewer)
                self.current_preview_widget = self.folder_previewer
            elif preview_type == "image":
                # 图片预览
                self._show_image_preview(file_path)
            elif preview_type == "video":
                # 视频预览
                self._show_video_preview(file_path)
            elif preview_type == "audio":
                # 音频预览
                self._show_audio_preview(file_path)
            elif preview_type == "pdf":
                # PDF预览
                self._show_pdf_preview(file_path)
            elif preview_type == "text":
                # 文本预览
                self._show_text_preview(file_path)
            elif preview_type == "archive":
                # 压缩包预览
                self.archive_browser = ArchiveBrowser()
                self.archive_browser.set_archive_path(file_path)
                self.preview_layout.addWidget(self.archive_browser)
                self.current_preview_widget = self.archive_browser
            else:
                # 未知文件类型预览
                unknown_label = QLabel("不支持预览")
                unknown_label.setAlignment(Qt.AlignCenter)
                self.preview_layout.addWidget(unknown_label)
                self.current_preview_widget = unknown_label
            
            # 更新当前预览类型
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
        
        Args:
            file_path (str): 文件路径
            preview_type (str): 预览类型
        """
        if not self.current_preview_widget:
            return
        
        # 先检查文件是否存在，避免无效文件路径导致的错误
        if not os.path.exists(file_path):
            error_label = QLabel(f"文件不存在: {os.path.basename(file_path)}")
            error_label.setAlignment(Qt.AlignCenter)
            error_label.setStyleSheet("color: red; font-weight: bold;")
            self._clear_preview()
            self.preview_layout.addWidget(error_label)
            self.current_preview_widget = error_label
            self.current_preview_type = "error"
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
            from src.components.photo_viewer import PhotoViewer
            
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
        
        Args:
            file_path (str): 视频文件路径
        """
        try:
            # print(f"[DEBUG] 统一预览器 - 开始视频预览，文件路径: {file_path}")
            # 尝试导入VideoPlayer组件（基于VLC的播放器）
            from src.components.video_player import VideoPlayer
            
            # print(f"[DEBUG] 统一预览器 - 导入VideoPlayer组件成功")
            # 创建VideoPlayer视频播放器
            video_player = VideoPlayer()
            # print(f"[DEBUG] 统一预览器 - 创建VideoPlayer实例成功")
            # 加载视频文件
            video_player.load_media(file_path)
            # print(f"[DEBUG] 统一预览器 - 调用VideoPlayer.load_media()方法成功")
            
            self.preview_layout.addWidget(video_player)
            self.current_preview_widget = video_player
            # print(f"[DEBUG] 统一预览器 - 将VideoPlayer添加到预览布局成功")
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
        
        Args:
            file_path (str): 音频文件路径
        """
        try:
            # 使用视频播放器组件处理音频文件，因为它已经支持音频播放
            from src.components.video_player import VideoPlayer
            
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
        
        Args:
            file_path (str): PDF文件路径
        """
        try:
            # 尝试导入PDF预览器组件
            from src.components.pdf_previewer import PDFPreviewer
            
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
    
    def _show_text_preview(self, file_path):
        """
        显示文本预览
        
        Args:
            file_path (str): 文本文件路径
        """
        try:
            # 尝试导入文本预览器组件
            from src.components.text_previewer import TextPreviewer
            
            # 创建文本预览器
            text_previewer = TextPreviewer()
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
