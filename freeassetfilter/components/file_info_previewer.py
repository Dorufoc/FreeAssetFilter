#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

文件信息预览器组件
用于获取和显示各种文件类型的详细信息
特点：
- 文本内容根据窗口大小自适应换行显示
- 使用项目自定义控件（D_MoreMenu、D_ScrollBar、CustomButton等）
- 平滑滚动体验
- 异步加载详细信息，避免阻塞主线程
"""

import os
import sys
import subprocess
import platform
import json
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional, List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QScrollArea, QGroupBox,
    QSizePolicy, QFormLayout, QApplication, QTextEdit
)
from PySide6.QtCore import Qt, QThread, Signal, QRunnable, QThreadPool, QObject
from PySide6.QtGui import QFont, QCursor, QTextOption

# 导入项目自定义控件
from freeassetfilter.widgets.smooth_scroller import D_ScrollBar, SmoothScroller
from freeassetfilter.widgets.D_more_menu import D_MoreMenu
from freeassetfilter.widgets.D_widgets import CustomButton, CustomMessageBox
from freeassetfilter.widgets.progress_widgets import D_ProgressBar

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


class AudioInfoTask(QRunnable):
    """
    音频信息获取任务
    在后台线程中执行音频信息获取，避免阻塞主线程
    """
    def __init__(self, file_path: str, task_id: int, callback):
        super().__init__()
        self.file_path = file_path
        self.task_id = task_id
        self.callback = callback
        self._is_cancelled = False

    def cancel(self):
        """取消任务"""
        self._is_cancelled = True

    def run(self):
        """执行音频信息获取"""
        info = {}

        if mutagen_file:
            try:
                audio = mutagen_file(self.file_path)
                if audio:
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

        if not info:
            try:
                result = subprocess.run(
                    ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", self.file_path],
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

        # 调用回调函数，传递任务ID和结果
        if not self._is_cancelled and self.callback:
            self.callback(self.task_id, info)

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """格式化时长"""
        if seconds < 0:
            return "无法获取"

        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes:02d}:{secs:02d}"

    @staticmethod
    def _format_bitrate(bitrate: int) -> str:
        """格式化比特率"""
        if bitrate < 0:
            return "无法获取"

        if bitrate < 1000:
            return f"{bitrate} bps"
        elif bitrate < 1000000:
            return f"{bitrate / 1000:.1f} Kbps"
        else:
            return f"{bitrate / 1000000:.1f} Mbps"


class FileInfoPreviewer(QObject):
    """
    文件信息预览器组件
    负责提取和管理各种类型文件的详细信息
    文本内容根据窗口大小自适应换行显示
    """

    audioInfoLoaded = Signal(dict)  # 音频信息加载完成信号

    def __init__(self):
        super().__init__()
        self.current_file = None
        self.file_info = {}

        # 音频信息获取任务管理
        self._audio_task_id = 0
        self._current_audio_task = None

        # 获取全局字体和DPI缩放因子
        app = QApplication.instance()
        self.global_font = getattr(app, 'global_font', QFont())
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)

        # 主题颜色
        self._load_theme_colors()

        self.init_ui()

    def _load_theme_colors(self):
        """加载主题颜色"""
        app = QApplication.instance()
        self.background_color = "#2D2D2D"
        self.base_color = "#212121"
        self.auxiliary_color = "#313131"
        self.normal_color = "#717171"
        self.secondary_color = "#FFFFFF"
        self.accent_color = "#F0C54D"

        if hasattr(app, 'settings_manager'):
            self.background_color = app.settings_manager.get_setting("appearance.colors.window_background", "#2D2D2D")
            self.base_color = app.settings_manager.get_setting("appearance.colors.base_color", "#212121")
            self.auxiliary_color = app.settings_manager.get_setting("appearance.colors.auxiliary_color", "#313131")
            self.normal_color = app.settings_manager.get_setting("appearance.colors.normal_color", "#717171")
            self.secondary_color = app.settings_manager.get_setting("appearance.colors.secondary_color", "#FFFFFF")
            self.accent_color = app.settings_manager.get_setting("appearance.colors.accent_color", "#F0C54D")

    def init_ui(self):
        """初始化UI组件"""
        # UI创建在get_ui方法中
        pass

    def _create_value_widget(self, text="-", is_clickable=False):
        """
        创建值显示控件
        使用QTextEdit替代QLabel，实现更好的文本换行控制（包括英文路径）

        Args:
            text: 初始文本
            is_clickable: 是否可点击（用于MD5/SHA1/SHA256）

        Returns:
            QTextEdit: 配置好的文本控件
        """
        text_edit = QTextEdit()
        text_edit.setPlainText(text)
        text_edit.setFont(self.global_font)
        text_edit.setReadOnly(True)
        text_edit.setFrameStyle(0)  # 无边框
        text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        text_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        text_edit.setMinimumWidth(0)
        text_edit.setContextMenuPolicy(Qt.CustomContextMenu)

        # 设置文本对齐方式 - 左对齐
        text_edit.setAlignment(Qt.AlignLeft)

        # 设置文档边距为0，我们将使用viewport margin来实现垂直居中
        doc = text_edit.document()
        doc.setDocumentMargin(0)

        # 设置样式
        if is_clickable:
            text_edit.setStyleSheet(f"""
                QTextEdit {{
                    color: {self.secondary_color};
                    text-decoration: underline;
                    background-color: transparent;
                    border: none;
                }}
            """)
            text_edit.setCursor(QCursor(Qt.PointingHandCursor))
        else:
            text_edit.setStyleSheet(f"""
                QTextEdit {{
                    color: {self.secondary_color};
                    background-color: transparent;
                    border: none;
                }}
            """)

        # 根据内容调整高度和垂直居中
        self._adjust_text_edit_height(text_edit)

        return text_edit

    def _adjust_text_edit_height(self, text_edit):
        """
        根据内容调整QTextEdit的高度，并实现所有行数的垂直居中

        Args:
            text_edit: QTextEdit控件
        """
        # 获取字体行高
        font_metrics = text_edit.fontMetrics()
        line_height = font_metrics.lineSpacing()

        # 获取文档
        doc = text_edit.document()
        doc.setTextWidth(text_edit.viewport().width())

        # 设置文档边距为0
        doc.setDocumentMargin(0)

        # 获取文档高度
        doc_height = doc.size().height()

        # 计算行数
        line_count = max(1, round(doc_height / line_height))

        # 计算内容总高度（行高 * 行数）
        content_height = int(line_height * line_count)

        # 设置最小高度（单行高度加一点边距空间）
        min_height = int(line_height + 6 * self.dpi_scale)

        # 移除最大高度限制，允许文本无限换行
        # final_height = min_height or content_height + padding
        final_height = max(min_height, content_height + int(6 * self.dpi_scale))
        text_edit.setFixedHeight(final_height)

        # 计算垂直居中需要的边距
        # 内容高度
        actual_content_height = int(line_height * line_count)
        # 可用空间
        available_space = final_height - actual_content_height
        if available_space > 0:
            # 均匀分配上下边距实现垂直居中
            top_margin = available_space // 2
            bottom_margin = available_space - top_margin
        else:
            top_margin = 0
            bottom_margin = 0
        text_edit.setViewportMargins(0, top_margin, 0, bottom_margin)

        # 连接文本变化信号，动态调整高度
        def update_height():
            doc = text_edit.document()
            doc.setTextWidth(text_edit.viewport().width())
            doc.setDocumentMargin(0)
            new_doc_height = doc.size().height()
            new_line_count = max(1, round(new_doc_height / line_height))
            new_content_height = int(line_height * new_line_count)
            new_final_height = max(min_height, new_content_height + int(6 * self.dpi_scale))
            text_edit.setFixedHeight(new_final_height)

            # 重新计算垂直居中
            new_actual_content_height = int(line_height * new_line_count)
            new_available_space = new_final_height - new_actual_content_height
            if new_available_space > 0:
                new_top_margin = new_available_space // 2
                new_bottom_margin = new_available_space - new_top_margin
            else:
                new_top_margin = 0
                new_bottom_margin = 0
            text_edit.setViewportMargins(0, new_top_margin, 0, new_bottom_margin)

        text_edit.textChanged.connect(update_height)

    def get_ui(self):
        """
        获取UI组件

        Returns:
            QScrollArea: 文件信息预览组件的UI组件
        """
        # 创建滚动区域，作为主容器
        scroll_area = QScrollArea()
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: 0px solid transparent;
                background-color: {self.background_color};
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: {self.base_color};
            }}
        """)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # 使用动画滚动条
        scroll_area.setVerticalScrollBar(D_ScrollBar(scroll_area, Qt.Vertical))
        scroll_area.setHorizontalScrollBar(D_ScrollBar(scroll_area, Qt.Horizontal))
        scroll_area.verticalScrollBar().set_colors(
            self.normal_color, self.secondary_color, self.accent_color, self.auxiliary_color
        )
        scroll_area.horizontalScrollBar().set_colors(
            self.normal_color, self.secondary_color, self.accent_color, self.auxiliary_color
        )
        
        # 保存滚动区域引用，用于后续滚动控制
        self.scroll_area = scroll_area

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
        main_widget.setStyleSheet(f"background-color: {self.background_color};")
        main_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(scaled_margin, scaled_margin, scaled_margin, scaled_margin)
        main_layout.setSpacing(scaled_spacing)

        # 创建统一的信息组，包含所有信息
        self.info_group = QGroupBox(" ")
        self.info_group.setFont(self.global_font)
        self.info_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.info_group.setStyleSheet(f"""
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: {scaled_title_left}px;
                color: {self.secondary_color};
            }}
            QGroupBox {{
                border: none;
            }}
        """)

        # 使用QFormLayout，更适合表单布局
        self.info_layout = QFormLayout(self.info_group)
        self.info_layout.setContentsMargins(
            scaled_group_margin, scaled_group_top_margin,
            scaled_group_right_margin, scaled_group_bottom_margin
        )
        self.info_layout.setSpacing(scaled_info_spacing)
        self.info_layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.info_layout.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        # 关键：设置字段增长策略，让值字段可以扩展
        self.info_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        # 基本信息标签 - 使用自适应换行的QLabel
        self.basic_info_labels = {}
        basic_info_order = [
            "文件名", "文件路径", "文件大小", "文件类型",
            "创建时间", "修改时间", "权限", "所有者", "组"
        ]

        # 存储基本信息控件的引用
        self.basic_info_widgets = {}

        for key in basic_info_order:
            # 创建值标签 - 使用QTextEdit实现更好的文本换行控制（包括英文路径）
            is_clickable = key in ["MD5", "SHA1", "SHA256"]
            value_widget = self._create_value_widget("-", is_clickable=is_clickable)

            # 为MD5、SHA1、SHA256添加点击事件
            if is_clickable:
                value_widget.mousePressEvent = lambda event, k=key: self._load_detailed_info()

            # 创建标签文本
            label_widget = QLabel(key + ":")
            label_widget.setFont(self.global_font)
            label_widget.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            label_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
            label_widget.setContextMenuPolicy(Qt.CustomContextMenu)
            label_widget.setStyleSheet(f"color: {self.secondary_color}; border: none;")

            # 连接右键菜单信号
            self._connect_context_menu(label_widget, key)
            self._connect_context_menu(value_widget, key)

            # 添加到表单布局
            self.info_layout.addRow(label_widget, value_widget)

            # 存储控件引用
            self.basic_info_labels[key] = value_widget
            self.basic_info_widgets[key] = {
                "label": label_widget,
                "value": value_widget
            }

        # 存储基本信息的行数
        self.basic_info_row_count = len(basic_info_order)

        # 存储详细信息标签，用于动态添加和删除
        self.details_info_widgets = []

        main_layout.addWidget(self.info_group)

        # 添加"更多信息"按钮（次选样式）
        self.more_info_btn = CustomButton(
            text="更多信息",
            parent=main_widget,
            button_type="secondary",
            display_mode="text"
        )
        self.more_info_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.more_info_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.more_info_btn.clicked.connect(self._load_detailed_info)
        main_layout.addWidget(self.more_info_btn)

        # 将主widget设置为滚动区域的内容
        scroll_area.setWidget(main_widget)

        return scroll_area

    def set_file(self, file_info: Dict[str, Any]):
        """
        设置要查看的文件

        Args:
            file_info (Dict[str, Any]): 文件信息字典
        """
        # 清除之前动态创建的校验码字段
        hash_keys = ["MD5", "SHA1", "SHA256"]
        for key in hash_keys:
            if key in self.basic_info_widgets:
                # 从布局中移除并删除控件
                widget_pair = self.basic_info_widgets[key]
                label_widget = widget_pair["label"]
                value_widget = widget_pair["value"]
                
                label_widget.hide()
                value_widget.hide()
                label_widget.deleteLater()
                value_widget.deleteLater()
                
                # 从字典中移除
                del self.basic_info_widgets[key]
                if key in self.basic_info_labels:
                    del self.basic_info_labels[key]
        
        self.current_file = file_info
        self.extract_file_info()
        
        # 显示"更多信息"按钮
        if hasattr(self, 'more_info_btn'):
            self.more_info_btn.show()
        
        self.update_ui()
        
        # 滚动到顶部，确保每次加载新文件时显示最顶端的内容
        if hasattr(self, 'scroll_area'):
            self.scroll_area.verticalScrollBar().setValue(0)

    def extract_file_info(self):
        """
        提取文件信息
        优化：移除了所有可能阻塞主线程的操作，只提取基本信息
        """
        if not self.current_file:
            return

        file_path = self.current_file["path"]

        # 提取基本信息
        self.file_info["basic"] = self._get_basic_info(file_path)

        # 初始化详细信息字典
        self.file_info["details"] = {}

        # 根据文件类型提取最小化的详细信息
        if self.current_file["is_dir"]:
            self.file_info["details"] = self._get_directory_info(file_path)
        else:
            file_ext = self.current_file["suffix"].lower()
            self.file_info["details"]["文件类型"] = file_ext

    def _get_basic_info(self, file_path: str) -> Dict[str, str]:
        """
        获取文件基本信息

        Args:
            file_path (str): 文件路径

        Returns:
            Dict[str, str]: 基本信息字典
        """
        try:
            stat = os.stat(file_path)
        except Exception:
            return {
                "文件名": os.path.basename(file_path),
                "文件路径": file_path,
                "文件大小": "无法获取",
                "创建时间": "无法获取",
                "修改时间": "无法获取",
                "权限": "无法获取",
                "所有者": "无法获取",
                "组": "无法获取",
                "文件类型": "目录" if os.path.isdir(file_path) else "文件"
            }

        return {
            "文件名": os.path.basename(file_path),
            "文件路径": file_path,
            "文件大小": self._format_size(stat.st_size),
            "创建时间": datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
            "修改时间": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "权限": oct(stat.st_mode)[-3:],
            "所有者": f"{stat.st_uid}",
            "组": f"{stat.st_gid}",
            "文件类型": "目录" if os.path.isdir(file_path) else "文件"
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
        获取音频文件信息
        先返回基本信息，然后在后台异步获取详细信息
        """
        # 取消之前的音频信息获取任务
        self._cancel_audio_task()

        # 返回基本信息（异步加载中状态）
        info = {
            "时长": "加载中...",
            "比特率": "加载中...",
            "声道数": "加载中...",
            "采样率": "加载中..."
        }

        # 启动后台任务获取详细信息
        self._start_audio_info_task(file_path)

        return info

    def _cancel_audio_task(self):
        """取消当前的音频信息获取任务"""
        if self._current_audio_task:
            self._current_audio_task.cancel()
            self._current_audio_task = None

    def _start_audio_info_task(self, file_path: str):
        """
        启动音频信息获取后台任务

        Args:
            file_path: 音频文件路径
        """
        # 生成新的任务ID
        self._audio_task_id += 1
        current_task_id = self._audio_task_id

        # 创建并启动后台任务
        task = AudioInfoTask(file_path, current_task_id, self._on_audio_info_loaded)
        self._current_audio_task = task
        QThreadPool.globalInstance().start(task)

    def _on_audio_info_loaded(self, task_id: int, info: Dict[str, Any]):
        """
        音频信息加载完成回调

        Args:
            task_id: 任务ID，用于验证是否是最新的任务
            info: 音频信息字典
        """
        # 检查任务ID是否匹配（避免旧任务结果覆盖新任务）
        if task_id != self._audio_task_id:
            return

        # 清除当前任务引用
        self._current_audio_task = None

        # 更新文件信息
        if "details" not in self.file_info:
            self.file_info["details"] = {}

        # 更新音频相关信息
        for key, value in info.items():
            self.file_info["details"][key] = value

        # 发射信号通知UI更新
        self.audioInfoLoaded.emit(info)

        # 更新UI显示
        self.update_ui()

    def _get_audio_advanced_info(self, file_path: str) -> Dict[str, Any]:
        """获取音频文件高级信息"""
        # 不解析音频元数据，避免大型二进制数据导致的问题
        return {}

    def _get_audio_info_sync(self, file_path: str) -> Dict[str, Any]:
        """
        同步获取音频文件信息（用于后台线程）
        直接返回实际值，不启动异步任务
        """
        info = {}

        if mutagen_file:
            try:
                audio = mutagen_file(file_path)
                if audio:
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

        if not info or "时长" not in info:
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
                if "时长" not in info:
                    info["时长"] = "无法获取"
                if "比特率" not in info:
                    info["比特率"] = "无法获取"

        return info

    def _get_video_info(self, file_path: str) -> Dict[str, Any]:
        """获取视频文件基本信息"""
        info = {}
        info["文件大小"] = self._format_size(os.path.getsize(file_path))

        # 尝试使用moviepy
        try:
            from moviepy.editor import VideoFileClip
            with VideoFileClip(file_path) as clip:
                info["时长"] = self._format_duration(clip.duration)
                info["分辨率"] = f"{clip.size[0]} x {clip.size[1]}"
                info["帧率"] = f"{clip.fps:.2f} fps"
                return info
        except Exception:
            pass

        # 尝试使用opencv-python
        try:
            import cv2
            cap = cv2.VideoCapture(file_path)
            if cap.isOpened():
                frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                fps = cap.get(cv2.CAP_PROP_FPS)
                if frame_count > 0 and fps > 0:
                    info["时长"] = self._format_duration(frame_count / fps)

                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                if width > 0 and height > 0:
                    info["分辨率"] = f"{width} x {height}"

                if fps > 0:
                    info["帧率"] = f"{fps:.2f} fps"

                cap.release()
                return info
            cap.release()
        except Exception:
            pass

        return info

    def _get_video_advanced_info(self, file_path: str) -> Dict[str, Any]:
        """获取视频文件高级信息"""
        info = {}
        info["码率"] = "无法获取"

        # 尝试使用opencv获取编解码器信息
        try:
            import cv2
            cap = cv2.VideoCapture(file_path)
            if cap.isOpened():
                fourcc = cap.get(cv2.CAP_PROP_FOURCC)
                try:
                    fourcc_int = int(fourcc)
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
            pass

        # 尝试计算码率
        try:
            duration = 0
            try:
                from moviepy.editor import VideoFileClip
                with VideoFileClip(file_path) as clip:
                    duration = clip.duration
            except Exception:
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
                file_size = os.path.getsize(file_path)
                bitrate = int((file_size * 8) / duration)
                info["码率"] = self._format_bitrate(bitrate)
        except Exception:
            pass

        # 尝试使用ffprobe获取更准确的码率
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", file_path],
                capture_output=True, text=True, check=True
            )
            ffprobe_data = json.loads(result.stdout)
            if "streams" in ffprobe_data:
                for stream in ffprobe_data["streams"]:
                    if stream.get("codec_type") == "video":
                        bit_rate = stream.get("bit_rate")
                        if bit_rate:
                            info["码率"] = self._format_bitrate(int(bit_rate))
                            break
        except Exception:
            pass

        return info

    def _get_image_info(self, file_path: str) -> Dict[str, Any]:
        """获取图像文件基本信息"""
        info = {}

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
        """获取图像文件高级信息"""
        info = {}

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
        """获取文本文件基本信息"""
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
        """获取文本文件高级信息"""
        info = {}

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
        """获取压缩文件基本信息"""
        info = {}

        file_ext = os.path.splitext(file_path)[1].lower()
        info["压缩格式"] = file_ext[1:]

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
                    info["总大小"] = "无法获取"
                    info["压缩率"] = "无法计算"
        except Exception:
            info["文件数"] = "无法获取"
            info["总大小"] = "无法获取"
            info["压缩率"] = "无法计算"

        return info

    def _get_archive_advanced_info(self, file_path: str) -> Dict[str, Any]:
        """获取压缩文件高级信息"""
        info = {}

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
                info["内容列表"] = content_list[:10]
                if len(content_list) > 10:
                    info["内容列表"].append({"名称": f"... 还有 {len(content_list) - 10} 个文件", "大小": "", "修改时间": ""})

        except Exception:
            pass

        return info

    def _get_pdf_info(self, file_path: str) -> Dict[str, Any]:
        """获取PDF文件基本信息"""
        info = {}

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
        """获取PDF文件高级信息"""
        info = {}

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
        """获取字体文件基本信息"""
        info = {}

        try:
            from fontTools.ttLib import TTFont

            with TTFont(file_path) as font:
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
        """获取字体文件高级信息"""
        info = {}

        try:
            from fontTools.ttLib import TTFont

            with TTFont(file_path) as font:
                info["字体格式"] = "TrueType"
                if 'CFF ' in font:
                    info["字体格式"] = "OpenType/CFF"

                info["字符数"] = len(font.getGlyphOrder())

                if 'hhea' in font:
                    hhea = font['hhea']
                    info["上升"] = hhea.ascent
                    info["下降"] = hhea.descent
                    info["行间距"] = hhea.lineGap
        except Exception:
            pass

        return info

    def _load_detailed_info(self):
        """加载详细信息，包括校验码和详细文件信息"""
        if not self.current_file:
            return

        file_path = self.current_file["path"]

        # 先检查缓存
        cached_info = self._get_cached_info(file_path)
        cache_valid = False
        if cached_info:
            # 检查缓存是否有效（不包含"加载中..."状态）
            cached_details = cached_info["details"].copy()
            audio_keys = ["时长", "比特率", "声道数", "采样率"]
            has_loading = any(cached_details.get(key) == "加载中..." for key in audio_keys)
            
            if not has_loading:
                cache_valid = True
                # 过滤掉音频元数据，避免显示大型二进制数据
                if "元数据" in cached_details:
                    del cached_details["元数据"]
                self.file_info["details"].update(cached_details)
                
                # 隐藏"更多信息"按钮
                if hasattr(self, 'more_info_btn'):
                    self.more_info_btn.hide()
                
                # 更新UI显示详细信息
                self.update_ui()
                
                # 添加校验码显示（从缓存中获取）
                hash_keys = ["MD5", "SHA1", "SHA256"]
                for key in hash_keys:
                    if key in cached_info["basic"] and cached_info["basic"][key] not in ["-", "点击查看", None]:
                        if key not in self.basic_info_widgets:
                            value = cached_info["basic"][key]
                            value_widget = self._create_value_widget(str(value), is_clickable=False)
                            
                            label_widget = QLabel(key + ":")
                            label_widget.setFont(self.global_font)
                            label_widget.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                            label_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
                            label_widget.setContextMenuPolicy(Qt.CustomContextMenu)
                            label_widget.setStyleSheet(f"color: {self.secondary_color}; border: none;")
                            
                            self._connect_context_menu(label_widget, key)
                            self._connect_context_menu(value_widget, key)
                            
                            self.info_layout.addRow(label_widget, value_widget)
                            
                            self.basic_info_labels[key] = value_widget
                            self.basic_info_widgets[key] = {
                                "label": label_widget,
                                "value": value_widget
                            }
                
                return

        # 显示加载状态
        self._show_loading_dialog()

        # 使用线程加载详细信息
        class LoadThread(QThread):
            finished = Signal(dict)
            error = Signal(str)

            def __init__(self, file_path, file_info, parent):
                super().__init__()
                self.file_path = file_path
                self.file_info = file_info
                self.parent = parent

            def run(self):
                try:
                    basic_info = {}
                    basic_info["MD5"] = self.parent._get_file_hash(self.file_path, hashlib.md5)
                    basic_info["SHA1"] = self.parent._get_file_hash(self.file_path, hashlib.sha1)
                    basic_info["SHA256"] = self.parent._get_file_hash(self.file_path, hashlib.sha256)

                    details = {}
                    if not self.file_info["basic"]["文件类型"] == "目录":
                        file_ext = os.path.splitext(self.file_path)[1].lower()[1:]

                        if file_ext in ["jpg", "jpeg", "png", "gif", "bmp", "tiff", "webp", "svg", "cr2", "cr3", "nef", "arw", "dng", "orf"]:
                            details.update(self.parent._get_image_info(self.file_path))
                            details.update(self.parent._get_image_advanced_info(self.file_path))
                        elif file_ext in ["mp4", "avi", "mov", "mkv", "m4v", "mxf", "3gp", "mpg", "wmv", "webm", "vob", "ogv", "rmvb", "m2ts", "ts", "mts"]:
                            details.update(self.parent._get_video_info(self.file_path))
                            details.update(self.parent._get_video_advanced_info(self.file_path))
                        elif file_ext in ["mp3", "wav", "flac", "ogg", "wma", "m4a", "aiff", "ape", "opus"]:
                            details.update(self.parent._get_audio_info_sync(self.file_path))
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
        """显示加载状态对话框"""
        self.loading_dialog = CustomMessageBox()
        self.loading_dialog.setModal(True)
        self.loading_dialog.set_title("加载中")
        self.loading_dialog.set_text("正在计算校验码和获取详细信息...")

        self.progress_bar = D_ProgressBar(is_interactive=False)
        self.progress_bar.setValue(500)
        self.loading_dialog.set_progress(self.progress_bar)

        self.loading_dialog.show()

    def _on_loading_finished(self, result):
        """加载完成后的处理"""
        if hasattr(self, 'loading_dialog'):
            self.loading_dialog.close()

        # 只更新详细信息到 file_info，校验码单独处理
        # 过滤掉音频元数据
        result_details = result["details"].copy()
        if "元数据" in result_details:
            del result_details["元数据"]
        self.file_info["details"].update(result_details)

        self._save_to_cache(self.current_file["path"], result)
        
        # 隐藏"更多信息"按钮
        if hasattr(self, 'more_info_btn'):
            self.more_info_btn.hide()
        
        # 更新UI显示详细信息
        self.update_ui()
        
        # 动态添加校验码显示
        hash_keys = ["MD5", "SHA1", "SHA256"]
        for key in hash_keys:
            if key in result["basic"] and result["basic"][key] not in ["-", "点击查看", None]:
                if key not in self.basic_info_widgets:
                    value = result["basic"][key]
                    value_widget = self._create_value_widget(str(value), is_clickable=False)
                    
                    label_widget = QLabel(key + ":")
                    label_widget.setFont(self.global_font)
                    label_widget.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                    label_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
                    label_widget.setContextMenuPolicy(Qt.CustomContextMenu)
                    label_widget.setStyleSheet(f"color: {self.secondary_color}; border: none;")
                    
                    self._connect_context_menu(label_widget, key)
                    self._connect_context_menu(value_widget, key)
                    
                    self.info_layout.addRow(label_widget, value_widget)
                    
                    self.basic_info_labels[key] = value_widget
                    self.basic_info_widgets[key] = {
                        "label": label_widget,
                        "value": value_widget
                    }

    def _on_loading_error(self, error_msg):
        """加载出错时的处理"""
        if hasattr(self, 'loading_dialog'):
            self.loading_dialog.close()

        msg_box = CustomMessageBox(None)
        msg_box.set_title("错误")
        msg_box.set_text(f"加载详细信息失败: {error_msg}")
        msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
        msg_box.exec()

    def _get_cache_dir(self):
        """获取缓存目录路径"""
        cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
        return cache_dir

    def _get_cached_info(self, file_path):
        """从缓存中获取信息"""
        try:
            cache_file = os.path.join(self._get_cache_dir(), "file_info_cache.json")
            if not os.path.exists(cache_file):
                return None

            with open(cache_file, "r", encoding="utf-8") as f:
                cache_data = json.load(f)

            if file_path in cache_data:
                return cache_data[file_path]
        except Exception:
            pass

        return None

    def _save_to_cache(self, file_path, info):
        """保存信息到缓存"""
        try:
            cache_file = os.path.join(self._get_cache_dir(), "file_info_cache.json")

            cache_data = {}
            if os.path.exists(cache_file):
                with open(cache_file, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)

            # 过滤掉音频的"加载中..."状态和元数据，避免缓存无效数据
            info_to_cache = {
                "basic": info.get("basic", {}),
                "details": {}
            }
            for key, value in info.get("details", {}).items():
                if key == "元数据":
                    continue  # 不缓存元数据
                if value == "加载中...":
                    continue  # 不缓存"加载中..."状态
                info_to_cache["details"][key] = value

            cache_data[file_path] = info_to_cache

            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存缓存失败: {e}")

    def _format_size(self, size: int) -> str:
        """格式化文件大小"""
        if size < 0:
            return "无法获取"

        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"

    def _format_duration(self, seconds: float) -> str:
        """格式化时长"""
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
        """格式化比特率"""
        if bitrate < 0:
            return "无法获取"

        if bitrate < 1000:
            return f"{bitrate} bps"
        elif bitrate < 1000000:
            return f"{bitrate / 1000:.1f} Kbps"
        else:
            return f"{bitrate / 1000000:.1f} Mbps"

    def update_ui(self):
        """更新UI显示"""
        if not self.file_info:
            return

        # 注意：校验码（MD5、SHA1、SHA256）不会在这里自动显示
        # 它们只在用户点击"更多信息"按钮后才动态创建

        # 更新基本信息
        if "basic" in self.file_info:
            for key, value in self.file_info["basic"].items():
                if key in self.basic_info_labels:
                    widget = self.basic_info_labels[key]
                    widget.setPlainText(str(value))

                    # 更新高度以适应新内容
                    self._adjust_text_edit_height(widget)

                    # 如果是哈希值字段，根据值的状态设置不同样式
                    if key in ["MD5", "SHA1", "SHA256"]:
                        widget.setCursor(QCursor(Qt.ArrowCursor))
                        widget.setStyleSheet(f"""
                            QTextEdit {{
                                color: {self.secondary_color};
                                background-color: transparent;
                                border: none;
                            }}
                        """)
                        widget.mousePressEvent = lambda event: None

        # 清空之前的详细信息标签
        if hasattr(self, 'details_info_widgets'):
            for widget_pair in self.details_info_widgets:
                label_widget, value_widget = widget_pair
                label_widget.hide()
                value_widget.hide()
                label_widget.deleteLater()
                value_widget.deleteLater()
            self.details_info_widgets.clear()

        # 在表单布局中添加详细信息
        if hasattr(self, 'info_layout') and "details" in self.file_info and self.file_info["details"]:
            for key, value in self.file_info["details"].items():
                # 创建标签文本
                label_widget = QLabel(key + ":")
                label_widget.setFont(self.global_font)
                label_widget.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                label_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
                label_widget.setContextMenuPolicy(Qt.CustomContextMenu)
                label_widget.setStyleSheet(f"color: {self.secondary_color}; border: none;")

                # 创建值控件 - 使用QTextEdit实现更好的文本换行控制（包括英文路径）
                value_widget = self._create_value_widget(str(value))

                # 连接右键菜单信号
                self._connect_context_menu(label_widget, key)
                self._connect_context_menu(value_widget, key)

                # 添加到表单布局
                self.info_layout.addRow(label_widget, value_widget)

                # 存储详细信息标签
                self.details_info_widgets.append((label_widget, value_widget))

    def _connect_context_menu(self, widget, key):
        """
        连接控件的右键菜单信号

        Args:
            widget: 要连接右键菜单的控件
            key: 信息键
        """
        def show_menu(point):
            """显示右键菜单"""
            if not hasattr(self, '_context_menu'):
                self._context_menu = D_MoreMenu(parent=None)
                self._context_menu.set_items([
                    {"text": "复制当前信息", "data": "copy_current"},
                    {"text": "复制全部信息", "data": "copy_all"},
                ])
                self._context_menu.itemClicked.connect(self._on_context_menu_clicked)

            self._context_menu._current_key = key
            # 获取值文本，QTextEdit使用toPlainText()，QLabel使用text()
            if key in self.basic_info_labels:
                value_widget = self.basic_info_labels[key]
                if isinstance(value_widget, QTextEdit):
                    self._context_menu._current_value = value_widget.toPlainText()
                else:
                    self._context_menu._current_value = value_widget.text()
            else:
                self._context_menu._current_value = ""
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

    def _copy_current_info(self, key: str, value: str):
        """
        复制当前信息到剪贴板

        Args:
            key (str): 信息键
            value (str): 信息值
        """
        clipboard = QApplication.clipboard()
        clipboard.setText(f"{key}: {value}")

    def _copy_all_info(self):
        """复制所有信息到剪贴板"""
        all_info = []

        all_info.append("文件信息")
        all_info.append("=" * 20)

        if "basic" in self.file_info:
            for key, value in self.file_info["basic"].items():
                all_info.append(f"{key}: {value}")

        if "details" in self.file_info:
            for key, value in self.file_info["details"].items():
                all_info.append(f"{key}: {value}")

        clipboard = QApplication.clipboard()
        clipboard.setText("\n".join(all_info))
