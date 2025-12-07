#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

文件信息查看器核心功能
用于获取和显示文件的详细信息
"""

import os
import sys
import subprocess
import platform
import json
from datetime import datetime
from typing import Dict, Any, Optional, List

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

class FileInfoViewer:
    """
    文件信息查看器核心类
    负责提取和管理各种类型文件的详细信息
    """
    
    def __init__(self):
        self.current_file = None
        self.file_info = {}
        self.custom_tags = {}
        
        # 获取全局字体
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QFont
        app = QApplication.instance()
        self.global_font = getattr(app, 'global_font', QFont())
        print(f"[DEBUG] FileInfoViewer获取到的全局字体: {self.global_font.family()}")
        
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
            QWidget: 文件信息查看器的UI组件
        """
        from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QScrollArea, QGroupBox, QGridLayout
        from PyQt5.QtCore import Qt
        
        # 创建主widget
        main_widget = QWidget()
        main_widget.setFont(self.global_font)
        main_layout = QVBoxLayout(main_widget)
        
        # 创建文件基本信息组
        basic_group = QGroupBox("基本信息")
        basic_group.setFont(self.global_font)
        basic_layout = QGridLayout(basic_group)
        
        # 添加基本信息字段
        self.basic_info_labels = {
            "文件名": QLabel("-"),
            "文件路径": QLabel("-"),
            "文件大小": QLabel("-"),
            "文件类型": QLabel("-"),
            "创建时间": QLabel("-"),
            "修改时间": QLabel("-"),
            "访问时间": QLabel("-"),
            "权限": QLabel("-"),
        }
        
        row = 0
        for label, widget in self.basic_info_labels.items():
            widget.setWordWrap(True)
            widget.setFont(self.global_font)
            
            # 创建标签文本并设置字体
            label_widget = QLabel(label + ":")
            label_widget.setFont(self.global_font)
            
            basic_layout.addWidget(label_widget, row, 0, Qt.AlignRight)
            basic_layout.addWidget(widget, row, 1)
            row += 1
        
        main_layout.addWidget(basic_group)
        
        # 创建自定义标签组
        custom_group = QGroupBox("自定义标签")
        custom_group.setFont(self.global_font)
        custom_layout = QVBoxLayout(custom_group)
        
        self.custom_tags_label = QLabel("无自定义标签")
        self.custom_tags_label.setFont(self.global_font)
        self.custom_tags_label.setWordWrap(True)
        custom_layout.addWidget(self.custom_tags_label)
        
        main_layout.addWidget(custom_group)
        
        print(f"[DEBUG] FileInfoViewer UI组件设置字体: {self.global_font.family()}")
        
        return main_widget
    
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
        """
        if not self.current_file:
            return
        
        file_path = self.current_file["path"]
        
        # 提取基本信息
        self.file_info["basic"] = self._get_basic_info(file_path)
        
        # 根据文件类型提取额外信息
        if self.current_file["is_dir"]:
            self.file_info["extra"] = self._get_directory_info(file_path)
        else:
            file_ext = self.current_file["suffix"].lower()
            if file_ext in ["jpg", "jpeg", "png", "gif", "bmp"]:
                self.file_info["extra"] = self._get_image_info(file_path)
            elif file_ext in ["mp4", "avi", "mov", "mkv"]:
                self.file_info["extra"] = self._get_video_info(file_path)
            elif file_ext in ["mp3", "wav", "flac", "ogg"]:
                self.file_info["extra"] = self._get_audio_info(file_path)
            elif file_ext in ["pdf"]:
                self.file_info["extra"] = self._get_pdf_info(file_path)
            else:
                self.file_info["extra"] = {}
    

    
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
    
    def _get_image_info(self, file_path: str) -> Dict[str, Any]:
        """
        获取图片信息
        
        Args:
            file_path (str): 图片文件路径
        
        Returns:
            Dict[str, Any]: 图片信息字典
        """
        info = {}
        
        # 尝试使用PIL获取图片尺寸
        try:
            from PIL import Image
            with Image.open(file_path) as img:
                width, height = img.size
                info["尺寸"] = f"{width} x {height}"
                info["格式"] = img.format
                info["模式"] = img.mode
        except Exception:
            info["尺寸"] = "无法获取"
            info["格式"] = "无法获取"
        
        # 尝试提取EXIF信息
        if exifread:
            try:
                with open(file_path, 'rb') as f:
                    exif = exifread.process_file(f, details=False)
                    if exif:
                        info["EXIF信息"] = "存在"
                    else:
                        info["EXIF信息"] = "无"
            except Exception:
                info["EXIF信息"] = "无法读取"
        
        return info
    
    def _get_video_info(self, file_path: str) -> Dict[str, Any]:
        """
        获取视频信息
        
        Args:
            file_path (str): 视频文件路径
        
        Returns:
            Dict[str, Any]: 视频信息字典
        """
        info = {}
        
        # 尝试使用ffprobe获取视频信息（如果可用）
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", file_path],
                capture_output=True, text=True, check=True
            )
            ffprobe_data = json.loads(result.stdout)
            
            # 提取格式信息
            if "format" in ffprobe_data:
                format_info = ffprobe_data["format"]
                info["时长"] = self._format_duration(float(format_info.get("duration", 0)))
                info["比特率"] = self._format_bitrate(int(format_info.get("bit_rate", 0)))
            
            # 提取视频流信息
            for stream in ffprobe_data.get("streams", []):
                if stream["codec_type"] == "video":
                    info["视频编码"] = stream.get("codec_name", "未知")
                    width = stream.get("width", 0)
                    height = stream.get("height", 0)
                    if width and height:
                        info["分辨率"] = f"{width} x {height}"
                    break
        except Exception:
            info["时长"] = "无法获取"
            info["视频编码"] = "无法获取"
        
        return info
    
    def _get_audio_info(self, file_path: str) -> Dict[str, Any]:
        """
        获取音频信息
        
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
        
        return info
    
    def _get_pdf_info(self, file_path: str) -> Dict[str, Any]:
        """
        获取PDF信息
        
        Args:
            file_path (str): PDF文件路径
        
        Returns:
            Dict[str, Any]: PDF信息字典
        """
        info = {}
        
        # 尝试使用PyMuPDF获取PDF信息
        try:
            import fitz
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
    
    def _format_size(self, size: int) -> str:
        """
        格式化文件大小
        
        Args:
            size (int): 文件大小（字节）
        
        Returns:
            str: 格式化后的文件大小
        """
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
        if bitrate < 1000:
            return f"{bitrate} bps"
        elif bitrate < 1000000:
            return f"{bitrate / 1000:.1f} Kbps"
        else:
            return f"{bitrate / 1000000:.1f} Mbps"
    
    def _get_basic_info(self, file_path: str) -> Dict[str, str]:
        """
        获取文件基本信息
        
        Args:
            file_path (str): 文件路径
        
        Returns:
            Dict[str, str]: 基本信息字典
        """
        stat = os.stat(file_path)
        
        return {
            "文件名": os.path.basename(file_path),
            "文件路径": file_path,
            "文件大小": self._format_size(stat.st_size),
            "创建时间": datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
            "修改时间": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "访问时间": datetime.fromtimestamp(stat.st_atime).strftime("%Y-%m-%d %H:%M:%S"),
            "权限": oct(stat.st_mode)[-3:],
            "文件类型": "目录" if os.path.isdir(file_path) else "文件",
        }
    
    def update_ui(self):
        """
        更新UI显示
        """
        if not self.file_info:
            return
        
        # 更新基本信息
        if "basic" in self.file_info:
            for key, value in self.file_info["basic"].items():
                if key in self.basic_info_labels:
                    self.basic_info_labels[key].setText(str(value))
        
        # 更新自定义标签
        if self.custom_tags:
            tags_text = ", ".join([f"{k}: {v}" for k, v in self.custom_tags.items()])
            self.custom_tags_label.setText(tags_text)
        else:
            self.custom_tags_label.setText("无自定义标签")
    
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

# 测试代码
if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication, QMainWindow
    
    app = QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle("文件信息查看器测试")
    window.setGeometry(100, 100, 600, 400)
    
    file_info_viewer = FileInfoViewer()
    window.setCentralWidget(file_info_viewer.get_ui())
    
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
    
    file_info_viewer.set_file(test_file)
    
    window.show()
    sys.exit(app.exec_())
