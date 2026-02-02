#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

文件信息浏览组件核心类
用于获取和显示各种文件类型的详细信息
"""

import os
import sys
import subprocess
import platform
import json
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional, List

from freeassetfilter.widgets.D_more_menu import D_MoreMenu

# 用于提取EXIF信息的库
try:
    import exifread
except ImportError:
    exifread = None

# 用于处理音频文件元数据
try:
    from mutagen import File as mutagen_file
except ImportError:
    mutagen_file = None

# 用于检测文件类型
try:
    import magic
except ImportError:
    magic = None

# 用于处理压缩文件
try:
    import zipfile
    import tarfile
    import rarfile
    import py7zr
except ImportError:
    zipfile = None
    tarfile = None
    rarfile = None
    py7zr = None

# 用于处理图像文件
try:
    from PIL import Image
    from PIL.ExifTags import TAGS
except ImportError:
    Image = None
    TAGS = None

# 用于处理PDF文件
try:
    import fitz
except ImportError:
    fitz = None

# 用于处理文本编码
try:
    import chardet
except ImportError:
    chardet = None

class FileInfoBrowser:
    """
    文件信息浏览组件核心类
    负责提取和管理各种类型文件的详细信息
    """
    
    def __init__(self):
        self.current_file = None
        self.file_info = {}
        self.custom_tags = {}
        
        # 获取全局字体和DPI缩放因子
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QFont
        app = QApplication.instance()
        self.global_font = getattr(app, 'global_font', QFont())
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        self.init_ui()
    
    def init_ui(self):
        """
        初始化UI组件
        """
        # 这里只初始化UI结构，实际UI创建在get_ui方法中
        pass
    
    def get_ui(self):
        """
        获取UI组件
        
        Returns:
            QWidget: 文件信息浏览组件的UI组件
        """
        from PyQt5.QtWidgets import (
            QApplication, QWidget, QVBoxLayout, QLabel, QScrollArea, QGroupBox, QGridLayout,
            QTabWidget, QFrame, QSplitter, QSizePolicy, QHBoxLayout, QPushButton,
            QTextBrowser, QTreeWidget, QTreeWidgetItem, QFormLayout
        )
        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QFont, QCursor
        
        from freeassetfilter.widgets.smooth_scroller import D_ScrollBar
        from freeassetfilter.widgets.smooth_scroller import SmoothScroller
        
        # 创建滚动区域，作为主容器
        scroll_area = QScrollArea()
        
        # 获取主题颜色
        app = QApplication.instance()
        background_color = "#2D2D2D"  # 默认窗口背景色
        base_color = "#212121"
        auxiliary_color = "#313131"
        normal_color = "#717171"
        secondary_color = "#FFFFFF"
        accent_color = "#F0C54D"
        if hasattr(app, 'settings_manager'):
            background_color = app.settings_manager.get_setting("appearance.colors.window_background", "#2D2D2D")
            base_color = app.settings_manager.get_setting("appearance.colors.base_color", "#212121")
            auxiliary_color = app.settings_manager.get_setting("appearance.colors.auxiliary_color", "#313131")
            normal_color = app.settings_manager.get_setting("appearance.colors.normal_color", "#717171")
            secondary_color = app.settings_manager.get_setting("appearance.colors.secondary_color", "#FFFFFF")
            accent_color = app.settings_manager.get_setting("appearance.colors.accent_color", "#F0C54D")
        
        # 保存颜色到实例变量，供其他方法使用
        self.secondary_color = secondary_color
        
        scrollbar_style = f"""
            QScrollArea {{
                border: 0px solid transparent;
                background-color: {background_color};
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: {base_color};
            }}
            QScrollBar:vertical {{
                width: 6px;
                background-color: {auxiliary_color};
                border: 0px solid transparent;
                border-radius: 0px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {normal_color};
                min-height: 15px;
                border-radius: 3px;
                border: none;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {secondary_color};
                border: none;
            }}
            QScrollBar::handle:vertical:pressed {{
                background-color: {accent_color};
                border: none;
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height: 0px;
                border: none;
            }}
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {{
                background: none;
                border: 0px solid transparent;
                border: none;
            }}
            QScrollBar:horizontal {{
                height: 6px;
                background-color: {auxiliary_color};
                border: 0px solid transparent;
                border-radius: 0px;
            }}
            QScrollBar::handle:horizontal {{
                background-color: {normal_color};
                min-width: 15px;
                border-radius: 3px;
                border: none;
            }}
            QScrollBar::handle:horizontal:hover {{
                background-color: {secondary_color};
                border: none;
            }}
            QScrollBar::handle:horizontal:pressed {{
                background-color: {accent_color};
                border: none;
            }}
            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal {{
                width: 0px;
                border: none;
            }}
            QScrollBar::add-page:horizontal,
            QScrollBar::sub-page:horizontal {{
                background: none;
                border: 0px solid transparent;
                border: none;
            }}
        """
        scroll_area.setStyleSheet(scrollbar_style)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # 使用动画滚动条
        scroll_area.setVerticalScrollBar(D_ScrollBar(scroll_area, Qt.Vertical))
        scroll_area.setHorizontalScrollBar(D_ScrollBar(scroll_area, Qt.Horizontal))
        scroll_area.verticalScrollBar().set_colors(normal_color, secondary_color, accent_color, auxiliary_color)
        scroll_area.horizontalScrollBar().set_colors(normal_color, secondary_color, accent_color, auxiliary_color)
        
        SmoothScroller.apply_to_scroll_area(scroll_area)
        
        # 应用DPI缩放因子到布局参数
        scaled_margin = int(6 * self.dpi_scale)
        scaled_spacing = int(6 * self.dpi_scale)
        scaled_group_margin = int(6 * self.dpi_scale)
        scaled_group_top_margin = int(5 * self.dpi_scale)
        scaled_group_right_margin = int(10 * self.dpi_scale)
        scaled_group_bottom_margin = int(4 * self.dpi_scale)
        scaled_info_spacing = int(4 * self.dpi_scale)
        scaled_title_left = int(10 * self.dpi_scale)
        
        # 创建主widget
        main_widget = QWidget()
        main_widget.setFont(self.global_font)
        main_widget.setStyleSheet(f"background-color: {background_color};")
        main_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(scaled_margin, scaled_margin, scaled_margin, scaled_margin)
        main_layout.setSpacing(scaled_spacing)
        
        # 创建统一的信息组，包含所有信息
        self.info_group = QGroupBox(" ")
        self.info_group.setFont(self.global_font)
        self.info_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.info_group.setStyleSheet(f"QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: {scaled_title_left}px; color: {secondary_color}; }} QGroupBox {{ border: none; }}")
        
        # 使用QFormLayout替代QGridLayout，更适合表单布局
        self.info_layout = QFormLayout(self.info_group)
        self.info_layout.setContentsMargins(scaled_group_margin, scaled_group_top_margin, scaled_group_right_margin, scaled_group_bottom_margin)  # 左边距减少5px，让标签左移
        self.info_layout.setSpacing(scaled_info_spacing)
        self.info_layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.info_layout.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        
        # 基本信息标签
        self.basic_info_labels = {
            "文件名": QLabel("-"),
            "文件路径": QLabel("-"),
            "文件大小": QLabel("-"),
            "文件类型": QLabel("-"),
            "创建时间": QLabel("-"),
            "修改时间": QLabel("-"),
            "权限": QLabel("-"),
            "所有者": QLabel("-"),
            "组": QLabel("-"),
            "MD5": QLabel("点击查看"),
            "SHA1": QLabel("点击查看"),
            "SHA256": QLabel("点击查看")
        }
        
        # 存储详细信息标签，用于动态添加和删除
        self.details_info_widgets = []
        
        # 添加基本信息到表单布局
        # 使用有序列表确保基本信息顺序一致
        basic_info_order = [
            "文件名", "文件路径", "文件大小", "文件类型",
            "创建时间", "修改时间", "权限", "所有者",
            "组", "MD5", "SHA1", "SHA256"
        ]
        
        # 存储基本信息控件的引用
        self.basic_info_widgets = {}
        
        for key in basic_info_order:
            # 获取或创建值标签
            if key not in self.basic_info_labels:
                self.basic_info_labels[key] = QLabel("-")
            
            widget = self.basic_info_labels[key]
            widget.setWordWrap(True)
            widget.setFont(self.global_font)
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            widget.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            widget.setMinimumWidth(0)
            widget.setContextMenuPolicy(Qt.CustomContextMenu)
            widget.setStyleSheet(f"color: {secondary_color}; border: none;")
            
            # 为MD5、SHA1、SHA256添加点击事件（仅当值为"点击查看"时）
            if key in ["MD5", "SHA1", "SHA256"]:
                if widget.text() == "点击查看":
                    widget.setCursor(QCursor(Qt.PointingHandCursor))
                    widget.setStyleSheet(f"color: {secondary_color}; text-decoration: underline; border: none;")
                    widget.mousePressEvent = lambda event, key=key: self._load_detailed_info()
                else:
                    # 如果已经有值，则使用普通样式
                    widget.setCursor(QCursor(Qt.ArrowCursor))
                    widget.setStyleSheet(f"color: {secondary_color}; border: none;")
            
            # 创建标签文本
            label_widget = QLabel(key + ":")
            label_widget.setFont(self.global_font)
            label_widget.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            label_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
            label_widget.setContextMenuPolicy(Qt.CustomContextMenu)
            label_widget.setStyleSheet(f"color: {secondary_color}; border: none;")
            
            # 连接右键菜单信号
            self._connect_context_menu(label_widget, key)
            self._connect_context_menu(widget, key)
            
            # 添加到表单布局
            self.info_layout.addRow(label_widget, widget)
            
            # 存储控件引用
            self.basic_info_widgets[key] = {
                "label": label_widget,
                "value": widget
            }
        
        # 移除了"点击加载"按钮，因为详细信息已在set_file方法中自动提取
        # 存储基本信息的行数，用于后续添加详细信息
        
        # 存储基本信息的行数，用于后续添加详细信息
        self.basic_info_row_count = len(basic_info_order)
        
        main_layout.addWidget(self.info_group)
        
        # 自定义标签组
        custom_group = QGroupBox("自定义标签")
        custom_group.setFont(self.global_font)
        custom_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        
        # 设置组框标题左对齐，应用DPI缩放和颜色
        scaled_title_left = int(12 * self.dpi_scale)
        custom_group.setStyleSheet(f"QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: {scaled_title_left}px; color: {secondary_color}; }} QGroupBox {{ border: none; }}")
        
        custom_layout = QVBoxLayout(custom_group)
        
        # 应用DPI缩放因子到布局参数
        scaled_margin = int(10 * self.dpi_scale)
        scaled_top_margin = int(35 * self.dpi_scale)
        scaled_right_margin = int(15 * self.dpi_scale)
        custom_layout.setContentsMargins(scaled_margin, scaled_top_margin, scaled_right_margin, scaled_margin)  # 调整左边距与文件信息框一致，避免内容盖住标题
        
        self.custom_tags_browser = QTextBrowser()
        self.custom_tags_browser.setFont(self.global_font)
        self.custom_tags_browser.setPlainText("当前功能暂未开发完成，敬请期待！")
        self.custom_tags_browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        
        # 应用DPI缩放因子到最小高度
        scaled_min_height = int(80 * self.dpi_scale)
        self.custom_tags_browser.setMinimumHeight(scaled_min_height)
        
        custom_layout.addWidget(self.custom_tags_browser)
        
        main_layout.addWidget(custom_group)
        
        # 将主widget设置为滚动区域的内容
        scroll_area.setWidget(main_widget)
        
        return scroll_area
    
    def set_file(self, file_info: Dict[str, Any]):
        """
        设置要查看的文件
        
        Args:
            file_info (Dict[str, Any]): 文件信息字典
        """
        self.current_file = file_info
        self.extract_file_info()
        self.update_ui()
    
    def extract_file_info(self):
        """
        提取文件信息
        优化：移除了所有可能阻塞主线程的操作，只提取基本信息
        """
        if not self.current_file:
            return
        
        file_path = self.current_file["path"]
        
        # 提取基本信息（已优化，移除了哈希计算）
        self.file_info["basic"] = self._get_basic_info(file_path)
        
        # 初始化详细信息字典
        self.file_info["details"] = {}
        
        # 根据文件类型提取最小化的详细信息，避免阻塞
        if self.current_file["is_dir"]:
            self.file_info["details"] = self._get_directory_info(file_path)
        else:
            file_ext = self.current_file["suffix"].lower()
            # 只添加文件类型信息，不执行任何可能阻塞的操作
            self.file_info["details"]["文件类型"] = file_ext
            
            # 对于大文件，不执行任何可能阻塞的详细信息提取
            # 避免使用PIL、moviepy、opencv等库打开大文件
            # 避免读取文件内容或元数据
            
            # 可以在后续添加异步提取机制，但当前优先确保UI响应
            self.file_info["details"]["详细信息"] = "为保证程序响应速度，未提取详细信息"
    
    def _get_basic_info(self, file_path: str) -> Dict[str, str]:
        """
        获取文件基本信息
        优化：移除了文件哈希计算，避免阻塞主线程
        
        Args:
            file_path (str): 文件路径
        
        Returns:
            Dict[str, str]: 基本信息字典
        """
        try:
            stat = os.stat(file_path)
        except Exception:
            # 处理网络文件无法访问的情况
            return {
                "文件名": os.path.basename(file_path),
                "文件路径": file_path,
                "文件大小": "无法获取",
                "创建时间": "无法获取",
                "修改时间": "无法获取",
                "权限": "无法获取",
                "所有者": "无法获取",
                "组": "无法获取",
                "文件类型": "目录" if os.path.isdir(file_path) else "文件",
                "MD5": "点击查看",
                "SHA1": "点击查看",
                "SHA256": "点击查看"
            }
        
        # 移除文件哈希计算，避免阻塞主线程
        return {
            "文件名": os.path.basename(file_path),
            "文件路径": file_path,
            "文件大小": self._format_size(stat.st_size),
            "创建时间": datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
            "修改时间": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "权限": oct(stat.st_mode)[-3:],
            "所有者": f"{stat.st_uid}",
            "组": f"{stat.st_gid}",
            "文件类型": "目录" if os.path.isdir(file_path) else "文件",
            "MD5": "点击查看",  # 移除文件哈希计算，避免阻塞
            "SHA1": "点击查看",  # 移除文件哈希计算，避免阻塞
            "SHA256": "点击查看"  # 移除文件哈希计算，避免阻塞
        }
    
    def _get_file_hash(self, file_path: str, hash_func) -> str:
        """
        计算文件哈希值
        
        Args:
            file_path (str): 文件路径
            hash_func: 哈希函数
        
        Returns:
            str: 哈希值
        """
        try:
            hasher = hash_func()
            with open(file_path, 'rb') as f:
                # 分块读取文件，避免占用过多内存
                for chunk in iter(lambda: f.read(4096), b''):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception:
            return "无法计算"
    
    def _get_directory_info(self, dir_path: str) -> Dict[str, Any]:
        """
        获取目录信息
        
        Args:
            dir_path (str): 目录路径
        
        Returns:
            Dict[str, Any]: 目录信息字典
        """
        try:
            items = os.listdir(dir_path)
            files = [item for item in items if os.path.isfile(os.path.join(dir_path, item))]
            dirs = [item for item in items if os.path.isdir(os.path.join(dir_path, item))]
            
            return {
                "子目录数": len(dirs),
                "文件数": len(files),
            }
        except Exception:
            return {
                "子目录数": "无法访问",
                "文件数": "无法访问",
            }
    
    def _get_audio_info(self, file_path: str) -> Dict[str, Any]:
        """
        获取音频文件基本信息
        
        Args:
            file_path (str): 音频文件路径
        
        Returns:
            Dict[str, Any]: 音频信息字典
        """
        info = {}
        
        # 尝试使用mutagen获取音频信息
        if mutagen_file:
            try:
                audio = mutagen_file(file_path)
                if audio:
                    # 提取基本音频信息
                    if hasattr(audio.info, 'length'):
                        info["时长"] = self._format_duration(audio.info.length)
                    if hasattr(audio.info, 'bitrate'):
                        info["比特率"] = self._format_bitrate(audio.info.bitrate)
                    if hasattr(audio.info, 'channels'):
                        info["声道数"] = audio.info.channels
                    if hasattr(audio.info, 'sample_rate'):
                        info["采样率"] = f"{audio.info.sample_rate} Hz"
            except Exception:
                pass
        
        # 如果mutagen失败，尝试使用ffprobe
        if not info:
            try:
                result = subprocess.run(
                    ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", file_path],
                    capture_output=True, text=True, check=True
                )
                ffprobe_data = json.loads(result.stdout)
                if "format" in ffprobe_data:
                    format_info = ffprobe_data["format"]
                    info["时长"] = self._format_duration(float(format_info.get("duration", 0)))
                    info["比特率"] = self._format_bitrate(int(format_info.get("bit_rate", 0)))
            except Exception:
                info["时长"] = "无法获取"
                info["比特率"] = "无法获取"
        
        return info
    
    def _get_audio_advanced_info(self, file_path: str) -> Dict[str, Any]:
        """
        获取音频文件高级信息
        
        Args:
            file_path (str): 音频文件路径
        
        Returns:
            Dict[str, Any]: 音频高级信息字典
        """
        info = {}
        
        # 尝试使用mutagen获取音频元数据
        if mutagen_file:
            try:
                audio = mutagen_file(file_path)
                if audio:
                    # 提取元数据
                    metadata = {}
                    for key, value in audio.items():
                        try:
                            metadata[key] = str(value)
                        except:
                            pass
                    if metadata:
                        info["元数据"] = metadata
                    
                    # 提取格式信息
                    if hasattr(audio.info, 'codec'):
                        info["编码格式"] = audio.info.codec
            except Exception:
                pass
        
        return info
    
    def _get_video_info(self, file_path: str) -> Dict[str, Any]:
        """
        获取视频文件基本信息，使用不依赖ffprobe的方法
        
        Args:
            file_path (str): 视频文件路径
        
        Returns:
            Dict[str, Any]: 视频信息字典，只包含对用户有用的信息
        """
        info = {}
        
        # 只添加对用户有用的基本文件信息
        info["文件大小"] = self._format_size(os.path.getsize(file_path))
        
        # 尝试使用moviepy（如果可用）
        try:
            from moviepy.editor import VideoFileClip
            with VideoFileClip(file_path) as clip:
                info["时长"] = self._format_duration(clip.duration)
                info["分辨率"] = f"{clip.size[0]} x {clip.size[1]}"
                info["帧率"] = f"{clip.fps:.2f} fps"  # 保留两位小数
                return info
        except Exception:
            # 不显示moviepy相关的错误信息给用户
            pass
        
        # 尝试使用opencv-python（如果可用）
        try:
            import cv2
            cap = cv2.VideoCapture(file_path)
            if cap.isOpened():
                # 计算时长（总帧数/帧率）
                frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                fps = cap.get(cv2.CAP_PROP_FPS)
                if frame_count > 0 and fps > 0:
                    info["时长"] = self._format_duration(frame_count / fps)
                
                # 获取分辨率
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                if width > 0 and height > 0:
                    info["分辨率"] = f"{width} x {height}"
                
                # 获取帧率
                if fps > 0:
                    info["帧率"] = f"{fps:.2f} fps"  # 保留两位小数
                
                cap.release()
                return info
            cap.release()
        except Exception:
            # 不显示opencv相关的错误信息给用户
            pass
        
        # 尝试简单的文件头解析（MP4格式）
        try:
            with open(file_path, 'rb') as f:
                # 检查文件是否是MP4格式
                f.seek(4)
                box_type = f.read(4)
                if box_type == b'ftyp':
                    info["文件格式"] = "MP4"
                    # 可以添加更多MP4特定的解析
        except Exception:
            pass
        
        return info
    
    def _get_video_advanced_info(self, file_path: str) -> Dict[str, Any]:
        """
        获取视频文件高级信息
        
        Args:
            file_path (str): 视频文件路径
        
        Returns:
            Dict[str, Any]: 视频高级信息字典，只包含对用户有用的信息
        """
        info = {}
        
        # 尝试使用opencv获取一些高级信息（如果可用）
        try:
            import cv2
            cap = cv2.VideoCapture(file_path)
            if cap.isOpened():
                # 获取一些基本的高级信息
                fourcc = cap.get(cv2.CAP_PROP_FOURCC)
                # 只显示易读的编解码器字符串，不显示原始数值
                try:
                    fourcc_int = int(fourcc)
                    # 转换为易读的字符串格式
                    codec_chars = []
                    for i in range(4):
                        char = chr((fourcc_int >> (8 * i)) & 0xFF)
                        if char.isprintable() and char != '\x00':
                            codec_chars.append(char)
                    
                    if codec_chars:
                        codec_str = ''.join(codec_chars)
                        info["视频编解码器"] = codec_str
                except Exception:
                    pass
                
                cap.release()
        except Exception:
            # 不显示opencv相关的错误信息给用户
            pass
        
        # 确保码率信息被添加，默认值为"无法获取"
        info["码率"] = "无法获取"
        
        # 尝试获取视频码率，使用多种方法确保成功
        # 方法1：通过文件大小和时长计算总码率（最可靠的后备方案）
        try:
            # 先获取视频时长
            duration = 0
            
            # 尝试使用moviepy获取时长
            try:
                from moviepy.editor import VideoFileClip
                with VideoFileClip(file_path) as clip:
                    duration = clip.duration
            except Exception:
                # 尝试使用opencv获取时长
                try:
                    import cv2
                    cap = cv2.VideoCapture(file_path)
                    if cap.isOpened():
                        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                        fps = cap.get(cv2.CAP_PROP_FPS)
                        if frame_count > 0 and fps > 0:
                            duration = frame_count / fps
                        cap.release()
                except Exception:
                    pass
            
            if duration > 0:
                # 获取文件大小（字节）
                file_size = os.path.getsize(file_path)
                # 计算码率（bps）: 码率 = 文件大小（字节） * 8 / 时长（秒）
                bitrate = int((file_size * 8) / duration)
                info["码率"] = self._format_bitrate(bitrate)
        except Exception as e:
            pass
        
        # 方法2：如果ffprobe可用，尝试获取更准确的视频流码率
        try:
            # 使用ffprobe获取视频流的码率
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", file_path],
                capture_output=True, text=True, check=True
            )
            ffprobe_data = json.loads(result.stdout)
            if "streams" in ffprobe_data:
                # 遍历所有流，找到视频流
                for stream in ffprobe_data["streams"]:
                    if stream.get("codec_type") == "video":
                        # 获取视频流的比特率
                        bit_rate = stream.get("bit_rate")
                        if bit_rate:
                            info["码率"] = self._format_bitrate(int(bit_rate))
                            break
                        # 如果没有直接的bit_rate字段，尝试从bit_rate字段或计算
                        if not bit_rate and stream.get("duration") and stream.get("nb_frames"):
                            try:
                                duration = float(stream["duration"])
                                frame_count = int(stream["nb_frames"])
                                if duration > 0:
                                    # 从帧率和分辨率估算码率
                                    width = int(stream.get("width", 0))
                                    height = int(stream.get("height", 0))
                                    fps = frame_count / duration
                                    # 简单估算：码率 = 分辨率 * 帧率 * 位深（假设24位）
                                    estimated_bitrate = int(width * height * fps * 24 / 1000) * 1000
                                    info["码率"] = self._format_bitrate(estimated_bitrate)
                                    break
                            except Exception:
                                pass
        except Exception:
            # 方法3：尝试获取总码率作为备选
            try:
                result = subprocess.run(
                    ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", file_path],
                    capture_output=True, text=True, check=True
                )
                ffprobe_data = json.loads(result.stdout)
                if "format" in ffprobe_data:
                    format_info = ffprobe_data["format"]
                    bit_rate = format_info.get("bit_rate")
                    if bit_rate:
                        info["码率"] = self._format_bitrate(int(bit_rate))
            except Exception:
                # 所有方法都失败了，保留默认值"无法获取"
                pass
        
        # 尝试使用moviepy获取一些高级信息（如果可用）
        try:
            from moviepy.editor import VideoFileClip
            with VideoFileClip(file_path) as clip:
                # 获取音频相关信息
                if clip.audio:
                    info["音频采样率"] = f"{clip.audio.fps} Hz"
                    info["音频通道数"] = clip.audio.nchannels
        except Exception:
            # 不显示moviepy相关的错误信息给用户
            pass
        
        return info
    
    def _get_image_info(self, file_path: str) -> Dict[str, Any]:
        """
        获取图像文件基本信息
        
        Args:
            file_path (str): 图像文件路径
        
        Returns:
            Dict[str, Any]: 图像信息字典
        """
        info = {}
        
        # 尝试使用PIL获取图片尺寸
        try:
            with Image.open(file_path) as img:
                width, height = img.size
                info["尺寸"] = f"{width} x {height}"
                info["格式"] = img.format
                info["模式"] = img.mode
        except Exception:
            info["尺寸"] = "无法获取"
            info["格式"] = "无法获取"
            info["模式"] = "无法获取"
        
        return info
    
    def _get_image_advanced_info(self, file_path: str) -> Dict[str, Any]:
        """
        获取图像文件高级信息
        
        Args:
            file_path (str): 图像文件路径
        
        Returns:
            Dict[str, Any]: 图像高级信息字典
        """
        info = {}
        
        # 尝试提取EXIF信息
        if exifread and TAGS:
            try:
                with open(file_path, 'rb') as f:
                    exif = exifread.process_file(f, details=False)
                    if exif:
                        exif_info = {}
                        for tag, value in exif.items():
                            tag_name = tag.split(':')[-1]
                            exif_info[tag_name] = str(value)
                        info["EXIF信息"] = exif_info
            except Exception:
                pass
        
        return info
    
    def _get_text_info(self, file_path: str) -> Dict[str, Any]:
        """
        获取文本文件基本信息
        
        Args:
            file_path (str): 文本文件路径
        
        Returns:
            Dict[str, Any]: 文本信息字典
        """
        info = {}
        
        # 检测编码
        try:
            with open(file_path, 'rb') as f:
                raw_data = f.read(1024)
                result = chardet.detect(raw_data)
                info["编码格式"] = result['encoding']
        except Exception:
            info["编码格式"] = "无法检测"
        
        # 统计字数
        try:
            with open(file_path, 'r', encoding=info["编码格式"] or 'utf-8') as f:
                content = f.read()
                info["字符数"] = len(content)
                info["字符数（不含空格）"] = len(content.replace(' ', ''))
                info["行数"] = content.count('\n') + 1
                info["单词数"] = len(content.split())
        except Exception:
            info["字符数"] = "无法统计"
            info["字符数（不含空格）"] = "无法统计"
            info["行数"] = "无法统计"
            info["单词数"] = "无法统计"
        
        return info
    
    def _get_text_advanced_info(self, file_path: str) -> Dict[str, Any]:
        """
        获取文本文件高级信息
        
        Args:
            file_path (str): 文本文件路径
        
        Returns:
            Dict[str, Any]: 文本高级信息字典
        """
        info = {}
        
        # 尝试使用magic检测文件类型
        if magic:
            try:
                mime = magic.Magic(mime=True)
                info["MIME类型"] = mime.from_file(file_path)
                
                magic_instance = magic.Magic()
                info["详细类型"] = magic_instance.from_file(file_path)
            except Exception:
                pass
        
        return info
    
    def _get_archive_info(self, file_path: str) -> Dict[str, Any]:
        """
        获取压缩文件基本信息
        
        Args:
            file_path (str): 压缩文件路径
        
        Returns:
            Dict[str, Any]: 压缩文件信息字典
        """
        info = {}
        
        # 获取压缩文件格式
        file_ext = os.path.splitext(file_path)[1].lower()
        info["压缩格式"] = file_ext[1:]
        
        # 尝试获取压缩文件内容信息
        try:
            if file_ext == '.zip' and zipfile:
                with zipfile.ZipFile(file_path, 'r') as zf:
                    info["文件数"] = len(zf.infolist())
                    total_size = sum(file.file_size for file in zf.infolist())
                    info["总大小"] = self._format_size(total_size)
                    info["压缩率"] = f"{round((1 - os.path.getsize(file_path) / total_size) * 100, 2)}%" if total_size > 0 else "0%"
            elif file_ext == '.rar' and rarfile:
                with rarfile.RarFile(file_path, 'r') as rf:
                    info["文件数"] = len(rf.infolist())
                    total_size = sum(file.file_size for file in rf.infolist())
                    info["总大小"] = self._format_size(total_size)
                    info["压缩率"] = f"{round((1 - os.path.getsize(file_path) / total_size) * 100, 2)}%" if total_size > 0 else "0%"
            elif file_ext in ['.tar', '.gz', '.tgz', '.bz2', '.xz'] and tarfile:
                with tarfile.open(file_path, 'r') as tf:
                    info["文件数"] = len(tf.getmembers())
                    total_size = sum(file.size for file in tf.getmembers())
                    info["总大小"] = self._format_size(total_size)
                    info["压缩率"] = f"{round((1 - os.path.getsize(file_path) / total_size) * 100, 2)}%" if total_size > 0 else "0%"
            elif file_ext == '.7z' and py7zr:
                with py7zr.SevenZipFile(file_path, 'r') as szf:
                    info["文件数"] = len(szf.getnames())
                    # py7zr不直接提供未压缩大小，所以无法计算压缩率
                    info["总大小"] = "无法获取"
                    info["压缩率"] = "无法计算"
        except Exception:
            info["文件数"] = "无法获取"
            info["总大小"] = "无法获取"
            info["压缩率"] = "无法计算"
        
        return info
    
    def _get_archive_advanced_info(self, file_path: str) -> Dict[str, Any]:
        """
        获取压缩文件高级信息
        
        Args:
            file_path (str): 压缩文件路径
        
        Returns:
            Dict[str, Any]: 压缩文件高级信息字典
        """
        info = {}
        
        # 尝试获取压缩文件内容列表
        try:
            file_ext = os.path.splitext(file_path)[1].lower()
            content_list = []
            
            if file_ext == '.zip' and zipfile:
                with zipfile.ZipFile(file_path, 'r') as zf:
                    for file in zf.infolist():
                        content_list.append({
                            "名称": file.filename,
                            "大小": self._format_size(file.file_size),
                            "修改时间": datetime(*file.date_time).strftime("%Y-%m-%d %H:%M:%S")
                        })
            elif file_ext == '.rar' and rarfile:
                with rarfile.RarFile(file_path, 'r') as rf:
                    for file in rf.infolist():
                        content_list.append({
                            "名称": file.filename,
                            "大小": self._format_size(file.file_size),
                            "修改时间": file.mtime.strftime("%Y-%m-%d %H:%M:%S") if file.mtime else "未知"
                        })
            elif file_ext in ['.tar', '.gz', '.tgz', '.bz2', '.xz'] and tarfile:
                with tarfile.open(file_path, 'r') as tf:
                    for file in tf.getmembers():
                        content_list.append({
                            "名称": file.name,
                            "大小": self._format_size(file.size),
                            "修改时间": datetime.fromtimestamp(file.mtime).strftime("%Y-%m-%d %H:%M:%S") if file.mtime else "未知"
                        })
            
            if content_list:
                info["内容列表"] = content_list[:10]  # 只显示前10个文件
                if len(content_list) > 10:
                    info["内容列表"].append({"名称": f"... 还有 {len(content_list) - 10} 个文件", "大小": "", "修改时间": ""})
                    
        except Exception:
            pass
        
        return info
    
    def _get_pdf_info(self, file_path: str) -> Dict[str, Any]:
        """
        获取PDF文件基本信息
        
        Args:
            file_path (str): PDF文件路径
        
        Returns:
            Dict[str, Any]: PDF信息字典
        """
        info = {}
        
        # 尝试使用PyMuPDF获取PDF信息
        try:
            with fitz.open(file_path) as doc:
                info["页数"] = doc.page_count
                metadata = doc.metadata
                if metadata:
                    if metadata.get("title"):
                        info["标题"] = metadata["title"]
                    if metadata.get("author"):
                        info["作者"] = metadata["author"]
                    if metadata.get("creator"):
                        info["创建者"] = metadata["creator"]
        except Exception:
            info["页数"] = "无法获取"
        
        return info
    
    def _get_pdf_advanced_info(self, file_path: str) -> Dict[str, Any]:
        """
        获取PDF文件高级信息
        
        Args:
            file_path (str): PDF文件路径
        
        Returns:
            Dict[str, Any]: PDF高级信息字典
        """
        info = {}
        
        # 尝试使用PyMuPDF获取详细PDF信息
        try:
            with fitz.open(file_path) as doc:
                metadata = doc.metadata
                if metadata:
                    advanced_metadata = {}
                    advanced_metadata["主题"] = metadata.get("subject", "未知")
                    advanced_metadata["关键字"] = metadata.get("keywords", "未知")
                    advanced_metadata["生产者"] = metadata.get("producer", "未知")
                    advanced_metadata["创建日期"] = metadata.get("creationDate", "未知")
                    advanced_metadata["修改日期"] = metadata.get("modDate", "未知")
                    advanced_metadata["PDF版本"] = metadata.get("format", "未知").split("-")[-1] if metadata.get("format") else "未知"
                    info["元数据"] = advanced_metadata
        except Exception:
            pass
        
        return info
    
    def _get_font_info(self, file_path: str) -> Dict[str, Any]:
        """
        获取字体文件基本信息
        
        Args:
            file_path (str): 字体文件路径
        
        Returns:
            Dict[str, Any]: 字体信息字典
        """
        info = {}
        
        # 尝试使用fontTools获取字体信息
        try:
            from fontTools.ttLib import TTFont
            
            with TTFont(file_path) as font:
                # 获取字体名称
                name_table = font['name']
                font_names = {
                    1: "字体名称",
                    2: "字体样式",
                    3: "唯一标识符",
                    4: "全名",
                    5: "版本",
                    6: "PostScript名称"
                }
                
                for name_id, name_desc in font_names.items():
                    for record in name_table.names:
                        if record.nameID == name_id:
                            try:
                                info[name_desc] = record.string.decode('utf-8')
                            except:
                                info[name_desc] = record.string.decode('latin-1')
                            break
        except Exception:
            pass
        
        return info
    
    def _get_font_advanced_info(self, file_path: str) -> Dict[str, Any]:
        """
        获取字体文件高级信息
        
        Args:
            file_path (str): 字体文件路径
        
        Returns:
            Dict[str, Any]: 字体高级信息字典
        """
        info = {}
        
        # 尝试使用fontTools获取详细字体信息
        try:
            from fontTools.ttLib import TTFont
            
            with TTFont(file_path) as font:
                # 获取字体格式
                info["字体格式"] = "TrueType"
                if 'CFF ' in font:
                    info["字体格式"] = "OpenType/CFF"
                
                # 获取字符集信息
                info["字符数"] = len(font.getGlyphOrder())
                
                # 获取字体指标
                if 'hhea' in font:
                    hhea = font['hhea']
                    info["上升"] = hhea.ascent
                    info["下降"] = hhea.descent
                    info["行间距"] = hhea.lineGap
        except Exception:
            pass
        
        return info
    
    def _load_detailed_info(self):
        """
        加载详细信息，包括校验码和详细文件信息
        """
        if not self.current_file:
            return
        
        file_path = self.current_file["path"]
        
        # 先检查缓存
        cached_info = self._get_cached_info(file_path)
        if cached_info:
            self.file_info["basic"].update(cached_info["basic"])
            self.file_info["details"].update(cached_info["details"])
            self.update_ui()
            return
        
        # 显示加载状态
        self._show_loading_dialog()
        
        # 使用线程加载详细信息
        from PyQt5.QtCore import QThread, pyqtSignal
        
        class LoadThread(QThread):
            finished = pyqtSignal(dict)
            error = pyqtSignal(str)
            
            def __init__(self, file_path, file_info, parent):
                super().__init__()
                self.file_path = file_path
                self.file_info = file_info
                self.parent = parent  # 保存外部类的实例
            
            def run(self):
                try:
                    # 计算校验码
                    basic_info = {}
                    basic_info["MD5"] = self.parent._get_file_hash(self.file_path, hashlib.md5)
                    basic_info["SHA1"] = self.parent._get_file_hash(self.file_path, hashlib.sha1)
                    basic_info["SHA256"] = self.parent._get_file_hash(self.file_path, hashlib.sha256)
                    
                    # 获取详细信息
                    details = {}
                    if not self.file_info["basic"]["文件类型"] == "目录":
                        file_ext = os.path.splitext(self.file_path)[1].lower()[1:]  # 移除点
                        
                        # 根据文件类型获取详细信息
                        if file_ext in ["jpg", "jpeg", "png", "gif", "bmp", "tiff", "webp", "svg", "cr2", "cr3", "nef", "arw", "dng", "orf"]:
                            details.update(self.parent._get_image_info(self.file_path))
                            details.update(self.parent._get_image_advanced_info(self.file_path))
                        elif file_ext in ["mp4", "avi", "mov", "mkv", "m4v", "mxf", "3gp", "mpg", "wmv", "webm", "vob", "ogv", "rmvb", "m2ts", "ts", "mts"]:
                            details.update(self.parent._get_video_info(self.file_path))
                            details.update(self.parent._get_video_advanced_info(self.file_path))
                        elif file_ext in ["mp3", "wav", "flac", "ogg", "wma", "m4a", "aiff", "ape", "opus"]:
                            details.update(self.parent._get_audio_info(self.file_path))
                            details.update(self.parent._get_audio_advanced_info(self.file_path))
                        elif file_ext in ["txt", "md", "rst", "py", "java", "cpp", "js", "html", "css", "php", "c", "h", "cs", "go", "rb", "swift", "kt", "yml", "yaml", "json", "xml"]:
                            details.update(self.parent._get_text_info(self.file_path))
                            details.update(self.parent._get_text_advanced_info(self.file_path))
                        elif file_ext in ["zip", "rar", "tar", "gz", "tgz", "bz2", "xz", "7z", "iso"]:
                            details.update(self.parent._get_archive_info(self.file_path))
                            details.update(self.parent._get_archive_advanced_info(self.file_path))
                        elif file_ext in ["pdf"]:
                            details.update(self.parent._get_pdf_info(self.file_path))
                            details.update(self.parent._get_pdf_advanced_info(self.file_path))
                        elif file_ext in ["ttf", "otf", "woff", "woff2"]:
                            details.update(self.parent._get_font_info(self.file_path))
                            details.update(self.parent._get_font_advanced_info(self.file_path))
                    
                    self.finished.emit({"basic": basic_info, "details": details})
                except Exception as e:
                    self.error.emit(str(e))
        
        # 创建并启动线程
        self.load_thread = LoadThread(file_path, self.file_info, self)
        self.load_thread.finished.connect(self._on_loading_finished)
        self.load_thread.error.connect(self._on_loading_error)
        self.load_thread.start()
    
    def _show_loading_dialog(self):
        """
        显示加载状态对话框（使用自定义提示弹窗）
        """
        from freeassetfilter.widgets.message_box import CustomMessageBox
        from freeassetfilter.widgets.progress_widgets import D_ProgressBar
        from PyQt5.QtCore import Qt
        
        # 创建自定义提示弹窗
        self.loading_dialog = CustomMessageBox()
        self.loading_dialog.setModal(True)
        
        # 设置标题和文本
        self.loading_dialog.set_title("加载中")
        self.loading_dialog.set_text("正在计算校验码和获取详细信息...")
        
        # 添加不可交互进度条
        self.progress_bar = D_ProgressBar(is_interactive=False)
        self.progress_bar.setValue(500)  # 显示中间状态 (0-1000)
        self.loading_dialog.set_progress(self.progress_bar)
        
        # 显示对话框
        self.loading_dialog.show()
    
    def _on_loading_finished(self, result):
        """
        加载完成后的处理
        """
        # 关闭加载对话框
        if hasattr(self, 'loading_dialog'):
            self.loading_dialog.close()
        
        # 更新文件信息
        self.file_info["basic"].update(result["basic"])
        self.file_info["details"].update(result["details"])
        
        # 保存到缓存
        self._save_to_cache(self.current_file["path"], result)
        
        # 更新UI
        self.update_ui()
    
    def _on_loading_error(self, error_msg):
        """
        加载出错时的处理
        """
        # 关闭加载对话框
        if hasattr(self, 'loading_dialog'):
            self.loading_dialog.close()
        
        # 显示错误提示
        from freeassetfilter.widgets.D_widgets import CustomMessageBox
        msg_box = CustomMessageBox(None)
        msg_box.set_title("错误")
        msg_box.set_text(f"加载详细信息失败: {error_msg}")
        msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
        msg_box.exec_()
    
    def _get_cache_dir(self):
        """
        获取缓存目录路径
        """
        import os
        cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
        return cache_dir
    
    def _get_cached_info(self, file_path):
        """
        从缓存中获取信息
        """
        import os
        import json
        
        try:
            # 创建缓存文件路径
            cache_file = os.path.join(self._get_cache_dir(), "file_info_cache.json")
            if not os.path.exists(cache_file):
                return None
            
            # 读取缓存文件
            with open(cache_file, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
            
            # 检查文件是否在缓存中
            if file_path in cache_data:
                return cache_data[file_path]
        except Exception:
            pass
        
        return None
    
    def _save_to_cache(self, file_path, info):
        """
        保存信息到缓存
        """
        import os
        import json
        
        try:
            # 创建缓存文件路径
            cache_file = os.path.join(self._get_cache_dir(), "file_info_cache.json")
            
            # 读取现有缓存
            cache_data = {}
            if os.path.exists(cache_file):
                with open(cache_file, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
            
            # 更新缓存
            cache_data[file_path] = info
            
            # 保存到文件
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存缓存失败: {e}")
    
    def _format_size(self, size: int) -> str:
        """
        格式化文件大小
        
        Args:
            size (int): 文件大小（字节）
        
        Returns:
            str: 格式化后的文件大小
        """
        if size < 0:
            return "无法获取"
        
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"
    
    def _format_duration(self, seconds: float) -> str:
        """
        格式化时长
        
        Args:
            seconds (float): 时长（秒）
        
        Returns:
            str: 格式化后的时长
        """
        if seconds < 0:
            return "无法获取"
        
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes:02d}:{secs:02d}"
    
    def _format_bitrate(self, bitrate: int) -> str:
        """
        格式化比特率
        
        Args:
            bitrate (int): 比特率（bps）
        
        Returns:
            str: 格式化后的比特率
        """
        if bitrate < 0:
            return "无法获取"
        
        if bitrate < 1000:
            return f"{bitrate} bps"
        elif bitrate < 1000000:
            return f"{bitrate / 1000:.1f} Kbps"
        else:
            return f"{bitrate / 1000000:.1f} Mbps"
    
    def update_ui(self):
        """
        更新UI显示
        """
        if not self.file_info:
            return
        
        # 更新基本信息
        if "basic" in self.file_info:
            for key, value in self.file_info["basic"].items():
                if hasattr(self, 'basic_info_labels') and key in self.basic_info_labels:
                    self.basic_info_labels[key].setText(str(value))
                    
                    # 如果是哈希值字段，根据值的状态设置不同样式
                    if key in ["MD5", "SHA1", "SHA256"]:
                        from PyQt5.QtCore import Qt
                        from PyQt5.QtGui import QCursor
                        from PyQt5.QtWidgets import QSizePolicy
                        widget = self.basic_info_labels[key]
                        if str(value) == "点击查看":
                            # 设置为可点击的链接样式
                            widget.setCursor(QCursor(Qt.PointingHandCursor))
                            widget.setStyleSheet(f"color: {self.secondary_color}; text-decoration: underline; border: none;")
                            # 重新绑定点击事件
                            widget.mousePressEvent = lambda event, key=key: self._load_detailed_info()
                        else:
                            # 如果已经有值，则使用普通样式
                            widget.setCursor(QCursor(Qt.ArrowCursor))
                            widget.setStyleSheet(f"color: {self.secondary_color}; border: none;")
                            # 确保换行和尺寸策略正确
                            widget.setWordWrap(True)
                            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                            # 移除点击事件
                            widget.mousePressEvent = lambda event: super(type(widget), widget).mousePressEvent(event)
        
        # 更新自定义标签
        if hasattr(self, 'custom_tags_browser'):
            if self.custom_tags:
                tags_text = "\n".join([f"{k}: {v}" for k, v in self.custom_tags.items()])
                self.custom_tags_browser.setText(tags_text)
            else:
                self.custom_tags_browser.setText("无自定义标签")
        
        # 清空之前的详细信息标签
        if hasattr(self, 'details_info_widgets'):
            for widget_pair in self.details_info_widgets:
                label_widget, value_widget = widget_pair
                # 从布局中移除并删除组件
                label_widget.hide()
                value_widget.hide()
                label_widget.deleteLater()
                value_widget.deleteLater()
            self.details_info_widgets.clear()
        
        # 在表单布局中添加详细信息
        if hasattr(self, 'info_layout') and "details" in self.file_info and self.file_info["details"]:
            # 导入需要的PyQt组件
            from PyQt5.QtWidgets import QLabel, QSizePolicy
            from PyQt5.QtCore import Qt
            
            # 为详细信息创建标签和值
            for key, value in self.file_info["details"].items():
                # 创建标签文本
                label_widget = QLabel(key + ":")
                label_widget.setFont(self.global_font)
                label_widget.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                label_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
                label_widget.setContextMenuPolicy(Qt.CustomContextMenu)
                label_widget.setStyleSheet(f"color: {self.secondary_color}; border: none;")
                
                # 创建值标签
                value_widget = QLabel(str(value))
                value_widget.setWordWrap(True)
                value_widget.setFont(self.global_font)
                value_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                value_widget.setAlignment(Qt.AlignLeft | Qt.AlignTop)
                value_widget.setMinimumWidth(0)
                value_widget.setContextMenuPolicy(Qt.CustomContextMenu)
                value_widget.setStyleSheet(f"color: {self.secondary_color}; border: none;")
                
                # 连接右键菜单信号
                self._connect_context_menu(label_widget, key)
                self._connect_context_menu(value_widget, key)
                
                # 添加到表单布局
                self.info_layout.addRow(label_widget, value_widget)
                
                # 存储详细信息标签，用于后续删除
                self.details_info_widgets.append((label_widget, value_widget))
    
    def _add_info_group(self, layout, title, info_dict):
        """
        添加信息组到布局
        
        Args:
            layout: 目标布局
            title: 信息组标题
            info_dict: 信息字典
        """
        from PyQt5.QtWidgets import QGroupBox, QGridLayout, QLabel, QTreeWidget, QTreeWidgetItem
        from PyQt5.QtCore import Qt
        
        group = QGroupBox(title)
        group.setFont(self.global_font)
        
        # 获取主题颜色
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        secondary_color = "#FFFFFF"
        if hasattr(app, 'settings_manager'):
            secondary_color = app.settings_manager.get_setting("appearance.colors.secondary_color", "#FFFFFF")
        
        group.setStyleSheet(f"QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 12px; color: {secondary_color}; }} QGroupBox {{ border: none; }}")
        
        # 检查信息是否包含嵌套字典
        has_nested = any(isinstance(v, dict) for v in info_dict.values())
        
        # 导入需要的PyQt组件
        from PyQt5.QtWidgets import QMenu, QAction, QSizePolicy
        from PyQt5.QtGui import QCursor
        
        # 创建右键菜单
        def create_context_menu(widget, key="", value=""):
            """创建右键菜单"""
            # 确保菜单的父部件正确设置，以便正确显示
            menu = QMenu(widget)
            
            # 复制当前信息
            copy_current_action = QAction("复制当前信息", widget)
            copy_current_action.triggered.connect(lambda: self._copy_current_info(key, value))
            menu.addAction(copy_current_action)
            
            # 复制全部信息
            copy_all_action = QAction("复制全部信息", widget)
            copy_all_action.triggered.connect(self._copy_all_info)
            menu.addAction(copy_all_action)
            
            return menu
        
        if has_nested:
            # 使用树形控件显示嵌套信息
            tree = QTreeWidget()
            tree.setFont(self.global_font)
            tree.setHeaderLabels(["属性", "值"])
            
            for key, value in info_dict.items():
                if isinstance(value, dict):
                    # 创建父节点
                    parent_item = QTreeWidgetItem(tree, [key, ""])
                    for sub_key, sub_value in value.items():
                        QTreeWidgetItem(parent_item, [sub_key, str(sub_value)])
                else:
                    QTreeWidgetItem(tree, [key, str(value)])
            
            tree.expandAll()
            group_layout = QGridLayout(group)
            group_layout.setContentsMargins(5, 5, 5, 5)  # 减小内边距
            group_layout.addWidget(tree)
            
            # 为树状控件添加右键菜单
            def tree_context_menu(point):
                item = tree.itemAt(point)
                if item:
                    # 无论点击属性列还是值列，都获取相同的键值对
                    key = item.text(0)
                    value = item.text(1)
                    menu = create_context_menu(tree, key, value)
                    
                    # 使用QCursor.pos()获取准确的鼠标位置，自动处理DPI缩放
                    menu.popup(QCursor.pos())
            
            tree.setContextMenuPolicy(Qt.CustomContextMenu)
            tree.customContextMenuRequested.connect(tree_context_menu)
        else:
            # 使用网格布局显示简单信息，参考基础信息的显示方式
            grid = QGridLayout(group)
            grid.setContentsMargins(1, 1, 1, 1)  # 减小内边距
            grid.setSpacing(2)  # 减小间距，调整上下宽度
            row = 0
            for key, value in info_dict.items():
                # 创建标签文本并设置字体
                label_widget = QLabel(key + ":")
                label_widget.setFont(self.global_font)
                label_widget.setMinimumWidth(60)  # 设置标签文本的最小宽度
                label_widget.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)  # 标签文本居中
                label_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)  # 固定宽度，高度自适应
                label_widget.setStyleSheet(f"color: {self.secondary_color}; border: none;")
                
                value_widget = QLabel(str(value))
                value_widget.setWordWrap(True)
                value_widget.setFont(self.global_font)
                value_widget.setMinimumWidth(80)  # 设置标签的最小宽度
                value_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)  # 宽度扩展，高度自适应
                value_widget.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # 设置统一的对齐方式
                value_widget.setStyleSheet(f"color: {self.secondary_color}; border: none;")
                
                # 为标签和值添加右键菜单
                label_widget.setContextMenuPolicy(Qt.CustomContextMenu)
                value_widget.setContextMenuPolicy(Qt.CustomContextMenu)
                
                def label_menu(point, k=key, v=value):
                    menu = create_context_menu(label_widget, k, v)
                    # 使用QCursor.pos()获取准确的鼠标位置，自动处理DPI缩放
                    menu.popup(QCursor.pos())
                
                def value_menu(point, k=key, v=value):
                    menu = create_context_menu(value_widget, k, v)
                    # 使用QCursor.pos()获取准确的鼠标位置，自动处理DPI缩放
                    menu.popup(QCursor.pos())
                
                label_widget.customContextMenuRequested.connect(label_menu)
                value_widget.customContextMenuRequested.connect(value_menu)
                
                grid.addWidget(label_widget, row, 0)
                grid.addWidget(value_widget, row, 1)
                row += 1
        
        layout.addWidget(group)
    
    def add_custom_tag(self, key: str, value: str):
        """
        添加自定义标签
        
        Args:
            key (str): 标签键
            value (str): 标签值
        """
        self.custom_tags[key] = value
        self.update_ui()
    
    def remove_custom_tag(self, key: str):
        """
        移除自定义标签
        
        Args:
            key (str): 标签键
        """
        if key in self.custom_tags:
            del self.custom_tags[key]
            self.update_ui()
    
    def clear_custom_tags(self):
        """
        清除所有自定义标签
        """
        self.custom_tags.clear()
        self.update_ui()
    
    def _copy_current_info(self, key: str, value: str):
        """
        复制当前信息到剪贴板
        
        Args:
            key (str): 信息键
            value (str): 信息值
        """
        from PyQt5.QtWidgets import QApplication
        
        clipboard = QApplication.clipboard()
        clipboard.setText(f"{key}: {value}")
    
    def _copy_all_info(self):
        """
        复制所有信息到剪贴板
        """
        from PyQt5.QtWidgets import QApplication
        
        all_info = []
        
        # 添加所有信息
        all_info.append("文件信息")
        all_info.append("=" * 20)
        
        # 添加基本信息
        if "basic" in self.file_info:
            for key, value in self.file_info["basic"].items():
                all_info.append(f"{key}: {value}")
        
        # 添加详细信息
        if "details" in self.file_info:
            for key, value in self.file_info["details"].items():
                all_info.append(f"{key}: {value}")
        
        # 复制到剪贴板
        clipboard = QApplication.clipboard()
        clipboard.setText("\n".join(all_info))
    
    def _connect_context_menu(self, widget, key):
        """
        连接控件的右键菜单信号

        Args:
            widget: 要连接右键菜单的控件
            key: 信息键
        """
        def show_menu(point):
            """显示右键菜单"""
            from PyQt5.QtGui import QCursor
            from PyQt5.QtWidgets import QApplication

            if not hasattr(self, '_context_menu'):
                app = QApplication.instance()
                self._context_menu = D_MoreMenu(parent=None)
                self._context_menu.set_items([
                    {"text": "复制当前信息", "data": "copy_current"},
                    {"text": "复制全部信息", "data": "copy_all"},
                ])
                self._context_menu.itemClicked.connect(self._on_context_menu_clicked)

            self._context_menu._current_key = key
            self._context_menu._current_value = self.basic_info_labels[key].text() if key in self.basic_info_labels else ""
            self._context_menu.popup(QCursor.pos())

        widget.customContextMenuRequested.connect(show_menu)

    def _on_context_menu_clicked(self, data):
        """
        右键菜单项点击事件处理

        Args:
            data: 菜单项数据
        """
        if data == "copy_current" and hasattr(self._context_menu, '_current_key'):
            key = self._context_menu._current_key
            value = self._context_menu._current_value
            self._copy_current_info(key, value)
        elif data == "copy_all":
            self._copy_all_info()
    
    def _show_context_menu(self, widget, key, value):
        """
        显示右键菜单

        Args:
            widget: 调用右键菜单的控件
            key: 信息键
            value: 信息值
        """
        from PyQt5.QtGui import QCursor

        if not hasattr(self, '_context_menu'):
            self._context_menu = D_MoreMenu(parent=None)
            self._context_menu.set_items([
                {"text": "复制当前信息", "data": "copy_current"},
                {"text": "复制全部信息", "data": "copy_all"},
            ])
            self._context_menu.itemClicked.connect(self._on_context_menu_clicked)

        self._context_menu._current_key = key
        self._context_menu._current_value = value
        self._context_menu.popup(QCursor.pos())

# 测试代码
if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication, QMainWindow
    
    app = QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle("文件信息浏览组件测试")
    window.setGeometry(100, 100, 800, 600)
    
    file_info_browser = FileInfoBrowser()
    window.setCentralWidget(file_info_browser.get_ui())
    
    # 测试文件信息
    test_file = {
        "name": "test.py",
        "path": __file__,
        "is_dir": False,
        "size": os.path.getsize(__file__),
        "modified": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "created": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "suffix": "py"
    }
    
    file_info_browser.set_file(test_file)
    
    window.show()
    sys.exit(app.exec_())