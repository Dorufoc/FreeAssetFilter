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
        
        # 获取全局字体
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QFont
        app = QApplication.instance()
        self.global_font = getattr(app, 'global_font', QFont())
        
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
            QWidget, QVBoxLayout, QLabel, QScrollArea, QGroupBox, QGridLayout,
            QTabWidget, QFrame, QSplitter, QSizePolicy, QHBoxLayout, QPushButton,
            QTextBrowser, QTreeWidget, QTreeWidgetItem
        )
        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QFont
        
        # 创建滚动区域，作为主容器
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setMinimumWidth(200)  # 设置最小宽度
        scroll_area.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        
        # 创建主widget
        main_widget = QWidget()
        main_widget.setFont(self.global_font)
        main_widget.setMinimumWidth(180)  # 设置主widget的最小宽度
        main_layout = QVBoxLayout(main_widget)
        
        # 创建标签页控件
        self.tab_widget = QTabWidget()
        self.tab_widget.setFont(self.global_font)
        self.tab_widget.setMinimumWidth(160)  # 设置标签页的最小宽度
        self.tab_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        
        # 1. 基本信息标签页
        basic_tab = QWidget()
        basic_tab.setMinimumWidth(150)  # 设置标签页内容的最小宽度
        basic_layout = QVBoxLayout(basic_tab)
        basic_layout.setContentsMargins(5, 5, 5, 5)  # 减小内边距
        
        # 基本信息组
        basic_group = QGroupBox("基本信息")
        basic_group.setFont(self.global_font)
        basic_group.setMinimumWidth(140)  # 设置组框的最小宽度
        basic_grid = QGridLayout(basic_group)
        basic_grid.setContentsMargins(5, 5, 5, 5)  # 减小内边距
        basic_grid.setSpacing(5)  # 减小间距
        
        self.basic_info_labels = {
            "文件名": QLabel("-"),
            "文件路径": QLabel("-"),
            "文件大小": QLabel("-"),
            "文件类型": QLabel("-"),
            "创建时间": QLabel("-"),
            "修改时间": QLabel("-"),
            "访问时间": QLabel("-"),
            "权限": QLabel("-"),
            "所有者": QLabel("-"),
            "组": QLabel("-"),
            "MD5": QLabel("-"),
            "SHA1": QLabel("-"),
            "SHA256": QLabel("-")
        }
        
        row = 0
        for label, widget in self.basic_info_labels.items():
            widget.setWordWrap(True)
            widget.setFont(self.global_font)
            widget.setMinimumWidth(80)  # 设置标签的最小宽度
            widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            
            # 创建标签文本并设置字体
            label_widget = QLabel(label + ":")
            label_widget.setFont(self.global_font)
            label_widget.setMinimumWidth(60)  # 设置标签文本的最小宽度
            label_widget.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            label_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            
            basic_grid.addWidget(label_widget, row, 0)
            basic_grid.addWidget(widget, row, 1)
            row += 1
        
        basic_layout.addWidget(basic_group)
        
        # 自定义标签组
        custom_group = QGroupBox("自定义标签")
        custom_group.setFont(self.global_font)
        custom_group.setMinimumWidth(140)  # 设置组框的最小宽度
        custom_layout = QVBoxLayout(custom_group)
        custom_layout.setContentsMargins(5, 5, 5, 5)  # 减小内边距
        
        self.custom_tags_browser = QTextBrowser()
        self.custom_tags_browser.setFont(self.global_font)
        self.custom_tags_browser.setPlainText("无自定义标签")
        self.custom_tags_browser.setMinimumHeight(80)  # 设置最小高度
        custom_layout.addWidget(self.custom_tags_browser)
        
        basic_layout.addWidget(custom_group)
        
        self.tab_widget.addTab(basic_tab, "基本信息")
        
        # 2. 扩展信息标签页
        self.extra_tab = QWidget()
        self.extra_tab.setMinimumWidth(150)  # 设置标签页内容的最小宽度
        self.extra_layout = QVBoxLayout(self.extra_tab)
        self.extra_layout.setContentsMargins(5, 5, 5, 5)  # 减小内边距
        self.tab_widget.addTab(self.extra_tab, "扩展信息")
        
        # 3. 高级信息标签页
        self.advanced_tab = QWidget()
        self.advanced_tab.setMinimumWidth(150)  # 设置标签页内容的最小宽度
        self.advanced_layout = QVBoxLayout(self.advanced_tab)
        self.advanced_layout.setContentsMargins(5, 5, 5, 5)  # 减小内边距
        self.tab_widget.addTab(self.advanced_tab, "高级信息")
        
        main_layout.addWidget(self.tab_widget)
        
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
            if file_ext in ["jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "svg"]:
                self.file_info["extra"] = self._get_image_info(file_path)
                self.file_info["advanced"] = self._get_image_advanced_info(file_path)
            elif file_ext in ["mp3", "wav", "flac", "ogg", "wma", "m4a", "aiff", "ape", "opus"]:
                self.file_info["extra"] = self._get_audio_info(file_path)
                self.file_info["advanced"] = self._get_audio_advanced_info(file_path)
            elif file_ext in ["mp4", "avi", "mov", "mkv", "m4v", "flv", "mxf", "3gp", "mpg", "wmv", "webm", "vob", "ogv", "rmvb"]:
                self.file_info["extra"] = self._get_video_info(file_path)
                self.file_info["advanced"] = self._get_video_advanced_info(file_path)
            elif file_ext in ["txt", "md", "rst", "py", "java", "cpp", "js", "html", "css", "php", "c", "h", "cs", "go", "rb", "swift", "kt", "yml", "yaml", "json", "xml"]:
                self.file_info["extra"] = self._get_text_info(file_path)
                self.file_info["advanced"] = self._get_text_advanced_info(file_path)
            elif file_ext in ["zip", "rar", "tar", "gz", "tgz", "bz2", "xz", "7z", "iso"]:
                self.file_info["extra"] = self._get_archive_info(file_path)
                self.file_info["advanced"] = self._get_archive_advanced_info(file_path)
            elif file_ext in ["pdf"]:
                self.file_info["extra"] = self._get_pdf_info(file_path)
                self.file_info["advanced"] = self._get_pdf_advanced_info(file_path)
            elif file_ext in ["ttf", "otf", "woff", "woff2", "eot"]:
                self.file_info["extra"] = self._get_font_info(file_path)
                self.file_info["advanced"] = self._get_font_advanced_info(file_path)
            else:
                self.file_info["extra"] = {}
                self.file_info["advanced"] = {}
    
    def _get_basic_info(self, file_path: str) -> Dict[str, str]:
        """
        获取文件基本信息
        
        Args:
            file_path (str): 文件路径
        
        Returns:
            Dict[str, str]: 基本信息字典
        """
        stat = os.stat(file_path)
        
        # 获取文件哈希值
        md5 = self._get_file_hash(file_path, hashlib.md5)
        sha1 = self._get_file_hash(file_path, hashlib.sha1)
        sha256 = self._get_file_hash(file_path, hashlib.sha256)
        
        return {
            "文件名": os.path.basename(file_path),
            "文件路径": file_path,
            "文件大小": self._format_size(stat.st_size),
            "创建时间": datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
            "修改时间": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "访问时间": datetime.fromtimestamp(stat.st_atime).strftime("%Y-%m-%d %H:%M:%S"),
            "权限": oct(stat.st_mode)[-3:],
            "所有者": f"{stat.st_uid}",
            "组": f"{stat.st_gid}",
            "文件类型": "目录" if os.path.isdir(file_path) else "文件",
            "MD5": md5,
            "SHA1": sha1,
            "SHA256": sha256
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
        获取视频文件基本信息
        
        Args:
            file_path (str): 视频文件路径
        
        Returns:
            Dict[str, Any]: 视频信息字典
        """
        info = {}
        
        # 尝试使用ffprobe获取视频信息
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
                info["总比特率"] = self._format_bitrate(int(format_info.get("bit_rate", 0)))
                info["容器格式"] = format_info.get("format_name", "未知")
            
            # 提取视频流信息
            for stream in ffprobe_data.get("streams", []):
                if stream["codec_type"] == "video":
                    info["视频编码"] = stream.get("codec_name", "未知")
                    width = stream.get("width", 0)
                    height = stream.get("height", 0)
                    if width and height:
                        info["分辨率"] = f"{width} x {height}"
                    if "r_frame_rate" in stream:
                        info["帧率"] = stream["r_frame_rate"]
                    if "bit_rate" in stream:
                        info["视频比特率"] = self._format_bitrate(int(stream["bit_rate"]))
                    break
            
            # 提取音频流信息
            for stream in ffprobe_data.get("streams", []):
                if stream["codec_type"] == "audio":
                    info["音频编码"] = stream.get("codec_name", "未知")
                    if "bit_rate" in stream:
                        info["音频比特率"] = self._format_bitrate(int(stream["bit_rate"]))
                    break
        except Exception:
            info["时长"] = "无法获取"
            info["视频编码"] = "无法获取"
            info["分辨率"] = "无法获取"
        
        return info
    
    def _get_video_advanced_info(self, file_path: str) -> Dict[str, Any]:
        """
        获取视频文件高级信息
        
        Args:
            file_path (str): 视频文件路径
        
        Returns:
            Dict[str, Any]: 视频高级信息字典
        """
        info = {}
        
        # 尝试使用ffprobe获取详细信息
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", file_path],
                capture_output=True, text=True, check=True
            )
            ffprobe_data = json.loads(result.stdout)
            
            # 提取详细流信息
            streams_info = {}
            for i, stream in enumerate(ffprobe_data.get("streams", [])):
                stream_info = {}
                stream_info["类型"] = stream.get("codec_type", "未知")
                stream_info["编码"] = stream.get("codec_name", "未知")
                stream_info["语言"] = stream.get("tags", {}).get("language", "未知")
                if stream.get("codec_type") == "video":
                    stream_info["宽度"] = stream.get("width", 0)
                    stream_info["高度"] = stream.get("height", 0)
                    stream_info["宽高比"] = stream.get("display_aspect_ratio", "未知")
                    stream_info["色彩空间"] = stream.get("color_space", "未知")
                    stream_info["色彩深度"] = stream.get("bits_per_raw_sample", "未知")
                streams_info[f"流 {i+1}"] = stream_info
            
            if streams_info:
                info["流信息"] = streams_info
                
        except Exception:
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
                if key in self.basic_info_labels:
                    self.basic_info_labels[key].setText(str(value))
        
        # 更新自定义标签
        if self.custom_tags:
            tags_text = "\n".join([f"{k}: {v}" for k, v in self.custom_tags.items()])
            self.custom_tags_browser.setText(tags_text)
        else:
            self.custom_tags_browser.setText("无自定义标签")
        
        # 清空扩展信息和高级信息布局
        for i in reversed(range(self.extra_layout.count())):
            item = self.extra_layout.itemAt(i)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    self.extra_layout.removeWidget(widget)
                    widget.deleteLater()
        
        for i in reversed(range(self.advanced_layout.count())):
            item = self.advanced_layout.itemAt(i)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    self.advanced_layout.removeWidget(widget)
                    widget.deleteLater()
        
        # 更新扩展信息
        if "extra" in self.file_info and self.file_info["extra"]:
            self._add_info_group(self.extra_layout, "扩展信息", self.file_info["extra"])
        
        # 更新高级信息
        if "advanced" in self.file_info and self.file_info["advanced"]:
            self._add_info_group(self.advanced_layout, "高级信息", self.file_info["advanced"])
    
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
        
        # 检查信息是否包含嵌套字典
        has_nested = any(isinstance(v, dict) for v in info_dict.values())
        
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
            group_layout.addWidget(tree)
        else:
            # 使用网格布局显示简单信息
            grid = QGridLayout(group)
            row = 0
            for key, value in info_dict.items():
                # 创建标签文本并设置字体
                label_widget = QLabel(key + ":")
                label_widget.setFont(self.global_font)
                
                value_widget = QLabel(str(value))
                value_widget.setWordWrap(True)
                value_widget.setFont(self.global_font)
                
                grid.addWidget(label_widget, row, 0, Qt.AlignRight)
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