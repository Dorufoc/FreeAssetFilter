#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

压缩包浏览器组件
支持浏览多种压缩格式的文件目录结构
"""

import sys
import os
import re
import json
from datetime import datetime
import chardet

# 添加项目根目录到Python路径，解决直接运行时的导入问题
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QApplication,
    QLabel, QScrollArea,
    QGroupBox, QListWidget, QListWidgetItem, QMessageBox,
    QFrame, QSizePolicy, QFileIconProvider, QComboBox
)

# 导入自定义控件
from freeassetfilter.widgets.button_widgets import CustomButton
from freeassetfilter.widgets.input_widgets import CustomInputBox
from PyQt5.QtCore import Qt, pyqtSignal, QFileInfo
from PyQt5.QtGui import QFont, QIcon

# 导入压缩包处理库
import zipfile
import tarfile

try:
    import rarfile
except ImportError:
    rarfile = None

try:
    import py7zr
except ImportError:
    py7zr = None

try:
    import pycdlib
except ImportError:
    pycdlib = None


class ArchiveBrowser(QWidget):
    """
    压缩包浏览器组件
    支持浏览多种压缩格式的文件目录结构
    """
    
    # 定义信号
    path_changed = pyqtSignal(str)  # 当浏览路径变化时发出
    file_selected = pyqtSignal(dict)  # 当选中文件时发出
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 获取全局字体和DPI缩放因子
        app = QApplication.instance()
        self.global_font = getattr(app, 'global_font', QFont())
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 设置组件字体
        self.setFont(self.global_font)
        
        # 初始化配置
        self.archive_path = None  # 压缩包路径
        self.current_path = ""  # 当前浏览路径
        self.is_encrypted = False  # 压缩包是否加密
        self.archive_type = None  # 压缩包类型
        self.archive_content = []  # 压缩包内容列表
        
        # 初始化文件图标提供者
        self.icon_provider = QFileIconProvider()
        
        # 初始化编码相关属性
        self.manual_encoding = "gbk"  # 默认使用GBK编码
        self.supported_encodings = [
            "utf-8", "gbk", "gb2312", "iso-8859-1", 
            "ascii", "utf-16", "utf-16le", "utf-16be"
        ]  # 支持的编码列表
        
        # 初始化UI
        self.init_ui()
    
    def init_ui(self):
        """
        初始化用户界面
        """
        # 创建主布局
        main_layout = QVBoxLayout(self)
        scaled_spacing = int(10 * self.dpi_scale)
        scaled_margin = int(10 * self.dpi_scale)
        main_layout.setSpacing(scaled_spacing)
        main_layout.setContentsMargins(scaled_margin, scaled_margin, scaled_margin, scaled_margin)
        
        # 创建顶部控制面板
        control_panel = self._create_control_panel()
        main_layout.addWidget(control_panel)
        
        # 创建文件列表区域
        files_area = self._create_files_area()
        main_layout.addWidget(files_area, 1)
        
        # 创建底部状态栏
        status_bar = self._create_status_bar()
        main_layout.addWidget(status_bar)
    
    def _create_control_panel(self):
        """
        创建控制面板
        """
        panel = QGroupBox()
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        # 使用垂直布局
        main_layout = QVBoxLayout(panel)
        scaled_spacing = int(5 * self.dpi_scale)
        scaled_margin = int(5 * self.dpi_scale)
        main_layout.setSpacing(scaled_spacing)
        main_layout.setContentsMargins(scaled_margin, scaled_margin, scaled_margin, scaled_margin)
        
        # 从app对象获取全局默认字体大小
        app = QApplication.instance()
        default_font_size = getattr(app, 'default_font_size', 14)
        
        # 应用DPI缩放因子到字体和按钮高度
        scaled_font_size = int(default_font_size * self.dpi_scale)
        # 使用统一的按钮高度（与文件选择器保持一致）
        button_height = 40
        scaled_button_height = int(button_height * self.dpi_scale)
        
        # 第一行：路径显示和返回按钮
        path_layout = QHBoxLayout()
        path_layout.setSpacing(scaled_spacing)
        
        # 返回上一级按钮
        self.back_btn = CustomButton("返回上一级", button_type="secondary", height=button_height)
        self.back_btn.clicked.connect(self.go_to_parent)
        self.back_btn.setEnabled(False)  # 初始禁用
        path_layout.addWidget(self.back_btn)
        
        # 当前路径显示
        self.path_edit = CustomInputBox(height=button_height)
        self.path_edit.line_edit.setReadOnly(True)
        self.path_edit.set_text("无压缩包路径")
        path_layout.addWidget(self.path_edit, 1)
        
        main_layout.addLayout(path_layout)
        
        # 第二行：压缩包信息
        info_layout = QHBoxLayout()
        info_layout.setSpacing(scaled_spacing)
        
        # 压缩包类型显示
        self.type_label = QLabel("压缩包类型: ")
        self.type_label.setFont(self.global_font)
        self.type_label.setStyleSheet(f"font-size: {scaled_font_size}px; min-height: {scaled_button_height}px;")
        info_layout.addWidget(self.type_label)
        
        # 加密状态显示
        self.encryption_label = QLabel("加密状态: 未加密")
        self.encryption_label.setFont(self.global_font)
        self.encryption_label.setStyleSheet(f"font-size: {scaled_font_size}px; min-height: {scaled_button_height}px;")
        info_layout.addWidget(self.encryption_label)
        
        info_layout.addStretch(1)
        
        main_layout.addLayout(info_layout)
        
        # 第三行：编码选择
        encoding_layout = QHBoxLayout()
        encoding_layout.setSpacing(scaled_spacing)
        
        # 编码选择下拉框
        encoding_label = QLabel("编码: ")
        encoding_label.setFont(self.global_font)
        encoding_label.setStyleSheet(f"font-size: {scaled_font_size}px; min-height: {scaled_button_height}px;")
        encoding_layout.addWidget(encoding_label)
        self.encoding_combo = QComboBox()
        
        # 应用与文件选择器一致的尺寸设置方法
        # 设置最小宽度，应用DPI缩放
        scaled_combo_width = int(150 * self.dpi_scale)
        self.encoding_combo.setMinimumWidth(scaled_combo_width)
        
        # 设置字体，与文件选择器的设置方法一致
        combo_font = QFont(self.global_font)
        combo_font.setPointSize(scaled_font_size)
        self.encoding_combo.setFont(combo_font)
        
        # 添加支持的编码
        for enc in self.supported_encodings:
            self.encoding_combo.addItem(enc.upper(), enc)
        # 设置默认选择为GBK
        self.encoding_combo.setCurrentText("GBK")
        # 连接选择变化信号
        self.encoding_combo.currentIndexChanged.connect(self._on_encoding_changed)
        encoding_layout.addWidget(self.encoding_combo)
        
        main_layout.addLayout(encoding_layout)
        
        return panel
    
    def _create_files_area(self):
        """
        创建文件列表区域
        """
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # 关闭水平滚动条
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)  # 垂直滚动条按需显示
        
        # 创建文件列表
        self.files_list = QListWidget()
        self.files_list.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.files_list.itemClicked.connect(self.on_item_clicked)
        
        # 从app对象获取全局默认字体大小
        app = QApplication.instance()
        default_font_size = getattr(app, 'default_font_size', 14)
        
        # 应用DPI缩放因子到列表项字体
        scaled_font_size = int(default_font_size * self.dpi_scale)
        list_font = QFont(self.global_font)
        list_font.setPointSize(scaled_font_size)
        self.files_list.setFont(list_font)
        
        # 设置列表项高度
        scaled_item_height = int(30 * self.dpi_scale)
        self.files_list.setStyleSheet(f"QListWidget::item {{ height: {scaled_item_height}px; }}")
        
        scroll_area.setWidget(self.files_list)
        
        return scroll_area
    
    def _create_status_bar(self):
        """
        创建状态栏
        """
        status_bar = QFrame()
        status_bar.setFrameShape(QFrame.HLine)
        status_bar.setFrameShadow(QFrame.Sunken)
        
        layout = QHBoxLayout(status_bar)
        
        # 从app对象获取全局默认字体大小
        app = QApplication.instance()
        default_font_size = getattr(app, 'default_font_size', 14)
        
        # 应用DPI缩放因子到状态栏
        scaled_font_size = int(default_font_size * self.dpi_scale)
        scaled_height = int(30 * self.dpi_scale)
        
        # 文件计数显示
        self.file_count_label = QLabel("文件数量: 0")
        self.file_count_label.setFont(self.global_font)
        self.file_count_label.setStyleSheet(f"font-size: {scaled_font_size}px; min-height: {scaled_height}px; padding: 5px;")
        layout.addWidget(self.file_count_label)
        
        layout.addStretch(1)
        
        # 设置状态栏高度
        status_bar.setFixedHeight(scaled_height)
        
        return status_bar
    
    def _detect_encoding(self, filename_bytes):
        """
        检测文件名的编码
        
        Args:
            filename_bytes (bytes): 文件名的字节流
            
        Returns:
            str: 检测到的编码
        """
        if not filename_bytes:
            return "utf-8"
        
        # 优先尝试UTF-8和GBK，这两种编码覆盖了大部分中文文件名场景
        # 默认使用GBK或UTF-8，根据检测结果选择
        preferred_encodings = ["utf-8", "gbk"]
        
        # 先尝试直接解码，优先使用中文常见编码
        for enc in preferred_encodings:
            try:
                filename_bytes.decode(enc)
                return enc
            except UnicodeDecodeError:
                continue
        
        # 如果直接解码失败，使用chardet检测
        result = chardet.detect(filename_bytes)
        encoding = result["encoding"]
        confidence = result["confidence"]
        
        # 如果检测到的编码不在支持列表中，或者置信度低于0.7，尝试其他常见编码
        if encoding not in self.supported_encodings or confidence < 0.7:
            # 尝试其他常见编码
            for enc in ["gb2312", "iso-8859-1"]:
                try:
                    filename_bytes.decode(enc)
                    return enc
                except UnicodeDecodeError:
                    continue
            # 如果所有尝试都失败，返回utf-8（使用replace模式处理错误）
            return "utf-8"
        
        return encoding
    
    def _decode_filename(self, filename):
        """
        解码文件名，使用手动选择的编码
        
        Args:
            filename (str or bytes): 文件名
            
        Returns:
            str: 解码后的文件名
        """
        # 如果已经是字符串，直接返回
        if isinstance(filename, str):
            return filename
        
        # 只使用手动选择的编码
        if self.manual_encoding:
            try:
                return filename.decode(self.manual_encoding)
            except UnicodeDecodeError:
                # 解码失败，使用replace模式
                return filename.decode(self.manual_encoding, errors="replace")
        
        # 默认为GBK编码
        try:
            return filename.decode("gbk")
        except UnicodeDecodeError:
            return filename.decode("gbk", errors="replace")
    
    def set_archive_path(self, path):
        """
        设置压缩包路径
        
        Args:
            path (str): 压缩包路径
        """
        if os.path.exists(path) and os.path.isfile(path):
            self.archive_path = path
            self._detect_archive_type()
            self._detect_encryption()
            self.current_path = ""
            # 重置编码为默认值GBK
            self.manual_encoding = "gbk"
            # 更新编码选择下拉框
            self.encoding_combo.setCurrentText("GBK")
            self.refresh()
        else:
            QMessageBox.warning(self, "警告", "无效的压缩包路径")
    
    def _on_encoding_changed(self, index):
        """
        编码选择变化
        """
        # 获取选择的编码
        self.manual_encoding = self.encoding_combo.currentData()
        # 立即刷新文件列表，应用新编码
        self.refresh()
    
    def _detect_archive_type(self):
        """
        检测压缩包类型
        """
        ext = os.path.splitext(self.archive_path)[1].lower()
        
        if ext in ['.zip']:
            self.archive_type = 'zip'
        elif ext in ['.rar']:
            self.archive_type = 'rar'
        elif ext in ['.tar', '.gz', '.tgz', '.bz2', '.xz']:
            self.archive_type = 'tar'
        elif ext in ['.7z']:
            self.archive_type = '7z'
        elif ext in ['.iso']:
            self.archive_type = 'iso'
        else:
            self.archive_type = 'unknown'
        
        self.type_label.setText(f"压缩包类型: {self.archive_type.upper()}")
    
    def _detect_encryption(self):
        """
        检测压缩包是否加密
        """
        self.is_encrypted = False
        
        try:
            if self.archive_type == 'zip':
                with zipfile.ZipFile(self.archive_path, 'r') as zf:
                    for info in zf.infolist():
                        if info.flag_bits & 0x1:  # 检查加密标志
                            self.is_encrypted = True
                            break
            elif self.archive_type == 'rar' and rarfile:
                with rarfile.RarFile(self.archive_path, 'r') as rf:
                    self.is_encrypted = rf.needs_password()
            elif self.archive_type == '7z' and py7zr:
                with py7zr.SevenZipFile(self.archive_path, mode='r') as zf:
                    self.is_encrypted = zf.needs_password()
        except Exception as e:
            print(f"检测加密状态失败: {e}")
        
        self.encryption_label.setText(f"加密状态: {'已加密' if self.is_encrypted else '未加密'}")
    
    def refresh(self):
        """
        刷新文件列表
        """
        if not self.archive_path:
            return
        
        # 更新路径显示
        self.path_edit.set_text(f"{os.path.basename(self.archive_path)}{'/' + self.current_path if self.current_path else ''}")
        
        # 清空文件列表
        self.files_list.clear()
        
        # 获取当前路径下的文件和文件夹
        try:
            self.archive_content = self._get_files()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"读取压缩包失败: {e}")
            return
        
        # 添加返回上一级项（如果不是根目录）
        if self.current_path:
            back_item = QListWidgetItem()
            back_item.setText("..")
            back_item.setData(Qt.UserRole, {"name": "..", "path": "..", "is_dir": True})
            self.files_list.addItem(back_item)
        
        # 添加文件和文件夹项
        for file in self.archive_content:
            # 跳过空白文件名
            if not file["name"]:
                continue
            
            item = QListWidgetItem()
            item.setText(file["name"])
            item.setData(Qt.UserRole, file)
            
            # 设置图标
            if file["is_dir"]:
                # 使用文件夹图标
                folder_icon = self.icon_provider.icon(QFileIconProvider.Folder)
                item.setIcon(folder_icon)
            else:
                # 根据文件后缀获取对应的图标
                file_suffix = file["suffix"]
                # 创建一个临时的QFileInfo对象来获取图标
                temp_file_info = QFileInfo(f"temp.{file_suffix}")
                file_icon = self.icon_provider.icon(temp_file_info)
                item.setIcon(file_icon)
            
            self.files_list.addItem(item)
        
        # 更新返回按钮状态
        self.back_btn.setEnabled(bool(self.current_path))
        
        # 更新文件计数
        self.file_count_label.setText(f"文件数量: {len(self.archive_content)}")
        
        # 发送路径变化信号
        self.path_changed.emit(self.current_path)
    
    def _get_files(self):
        """
        获取当前路径下的文件和文件夹
        
        Returns:
            list: 文件和文件夹列表
        """
        files = []
        
        try:
            if self.archive_type == 'zip':
                files = self._get_zip_files()
            elif self.archive_type == 'rar':
                if rarfile:
                    files = self._get_rar_files()
                else:
                    # 如果rarfile库不可用，显示错误信息
                    raise Exception("需要rarfile库来处理RAR文件。请使用pip install rarfile安装。")
            elif self.archive_type == 'tar':
                files = self._get_tar_files()
            elif self.archive_type == '7z':
                if py7zr:
                    files = self._get_7z_files()
                else:
                    # 如果py7zr库不可用，显示错误信息
                    raise Exception("需要py7zr库来处理7z文件。请使用pip install py7zr安装。")
            elif self.archive_type == 'iso':
                if pycdlib:
                    files = self._get_iso_files()
                else:
                    # 如果pycdlib库不可用，显示错误信息
                    raise Exception("需要pycdlib库来处理ISO文件。请使用pip install pycdlib安装。")
            else:
                # 未知压缩包类型
                raise Exception(f"不支持的压缩包类型: {self.archive_type}")
        except Exception as e:
            raise e
        
        return files
    
    def _get_zip_files(self):
        """
        获取ZIP文件中的文件列表
        """
        files = []
        dirs = set()
        
        with zipfile.ZipFile(self.archive_path, 'r') as zf:
            for info in zf.infolist():
                # 处理ZIP文件的特殊情况，获取原始bytes文件名
                # 注意：Python 3.6+中，zipfile会尝试自动解码文件名，但可能不准确
                # 使用filename属性获取系统默认编码解码的结果
                # 使用orig_filename获取原始编码的字符串
                # 对于ZIP文件，我们需要手动处理编码
                try:
                    # 尝试直接访问filename属性（Python 3.6+）
                    filename_str = info.filename
                    # 对于ZIP文件，我们需要获取原始bytes进行正确编码检测
                    # 使用namelist()获取的是已经解码的字符串，所以我们需要特殊处理
                    # 遍历namelist，找到匹配的项
                    for name in zf.namelist():
                        if name == filename_str:
                            # 找到匹配项，尝试获取原始bytes
                            # 注意：zipfile内部使用CP437编码解码文件名，所以我们需要重新编码
                            # 然后使用我们的编码检测逻辑
                            filename_bytes = name.encode('cp437')
                            file_path = self._decode_filename(filename_bytes)
                            break
                    else:
                        # 没有找到匹配项，直接使用filename_str
                        file_path = filename_str
                except Exception as e:
                    # 处理异常，直接使用orig_filename
                    if isinstance(info.orig_filename, str):
                        file_path = info.orig_filename
                    else:
                        file_path = self._decode_filename(info.orig_filename)
                
                # 跳过隐藏文件
                if os.path.basename(file_path).startswith('.'):
                    continue
                
                # 如果是目录，添加到目录集合
                if file_path.endswith('/'):
                    dirs.add(file_path)
                    continue
                
                # 检查文件是否在当前路径下
                if self.current_path:
                    if not file_path.startswith(self.current_path + '/'):
                        continue
                    # 获取相对路径
                    rel_path = file_path[len(self.current_path) + 1:]
                else:
                    rel_path = file_path
                
                # 检查是否是当前路径下的直接子项
                if '/' in rel_path:
                    # 是子目录下的文件，只添加目录
                    sub_dir = rel_path.split('/')[0]
                    if sub_dir:  # 确保子目录名不为空
                        dirs.add(sub_dir)
                else:
                    # 是当前目录下的文件
                    files.append({
                        "name": rel_path,
                        "path": file_path,
                        "is_dir": False,
                        "size": info.file_size,
                        "modified": datetime(*info.date_time).isoformat(),
                        "suffix": os.path.splitext(rel_path)[1].lower()[1:] if '.' in rel_path else ''
                    })
        
        # 添加目录到文件列表
        for dir_name in sorted(dirs):
            if self.current_path:
                if not dir_name.startswith(self.current_path + '/'):
                    continue
                rel_dir = dir_name[len(self.current_path) + 1:].rstrip('/')
                if '/' in rel_dir:
                    # 只添加直接子目录
                    rel_dir = rel_dir.split('/')[0]
                    if rel_dir not in [f["name"] for f in files if f["is_dir"]]:
                        files.append({
                            "name": rel_dir,
                            "path": f"{self.current_path}/{rel_dir}",
                            "is_dir": True,
                            "size": 0,
                            "modified": "",
                            "suffix": ""
                        })
                else:
                    files.append({
                        "name": rel_dir,
                        "path": dir_name.rstrip('/'),
                        "is_dir": True,
                        "size": 0,
                        "modified": "",
                        "suffix": ""
                    })
            else:
                if '/' in dir_name:
                    # 只添加根目录下的直接子目录
                    rel_dir = dir_name.split('/')[0]
                    if rel_dir not in [f["name"] for f in files if f["is_dir"]]:
                        files.append({
                            "name": rel_dir,
                            "path": rel_dir,
                            "is_dir": True,
                            "size": 0,
                            "modified": "",
                            "suffix": ""
                        })
                else:
                    files.append({
                        "name": dir_name.rstrip('/'),
                        "path": dir_name.rstrip('/'),
                        "is_dir": True,
                        "size": 0,
                        "modified": "",
                        "suffix": ""
                    })
        
        # 去重并排序
        unique_files = {}
        for file in files:
            unique_files[file["name"]] = file
        
        return sorted(unique_files.values(), key=lambda x: (not x["is_dir"], x["name"].lower()))
    
    def _get_rar_files(self):
        """
        获取RAR文件中的文件列表
        """
        files = []
        dirs = set()
        
        with rarfile.RarFile(self.archive_path, 'r') as rf:
            for info in rf.infolist():
                # 获取原始文件名
                file_path = info.filename
                
                # 如果是bytes类型，直接解码；否则直接使用字符串
                if isinstance(file_path, bytes):
                    decoded_path = self._decode_filename(file_path)
                else:
                    # 已经是字符串，直接使用
                    decoded_path = file_path
                
                # 跳过隐藏文件
                if os.path.basename(decoded_path).startswith('.'):
                    continue
                
                # 检查是否是目录（使用多种方式确保准确性）
                is_dir = info.isdir() or decoded_path.endswith('/') or decoded_path.endswith('\\')
                
                if is_dir:
                    # 确保目录路径格式统一
                    dir_path = decoded_path.rstrip('/\\')
                    dirs.add(dir_path)
                    continue
                
                # 更新file_path为解码后的路径
                file_path = decoded_path
                
                # 检查文件是否在当前路径下
                if self.current_path:
                    if not file_path.startswith(self.current_path + '/'):
                        continue
                    # 获取相对路径
                    rel_path = file_path[len(self.current_path) + 1:]
                else:
                    rel_path = file_path
                
                # 检查是否是当前路径下的直接子项
                if '/' in rel_path or '\\' in rel_path:
                    # 是子目录下的文件，只添加目录
                    # 处理不同的路径分隔符
                    sub_dir = rel_path.split('/')[0] if '/' in rel_path else rel_path.split('\\')[0]
                    if sub_dir:  # 确保子目录名不为空
                        # 构建完整的目录路径
                        full_sub_dir = sub_dir if not self.current_path else f"{self.current_path}/{sub_dir}"
                        dirs.add(full_sub_dir)
                else:
                    # 是当前目录下的文件
                    # 使用正确的属性名称获取文件大小和修改时间
                    file_size = getattr(info, 'size', 0)
                    file_mtime = getattr(info, 'mtime', 0)
                    
                    # 处理修改时间，确保是整数时间戳
                    try:
                        # 尝试将修改时间转换为整数时间戳
                        if isinstance(file_mtime, (int, float)):
                            # 已经是时间戳格式
                            timestamp = file_mtime
                        else:
                            # 尝试从datetime对象或其他格式转换
                            import time
                            # 检查是否有timestamp方法
                            if hasattr(file_mtime, 'timestamp'):
                                timestamp = file_mtime.timestamp()
                            # 检查是否有struct_time属性
                            elif hasattr(file_mtime, 'timetuple'):
                                timestamp = time.mktime(file_mtime.timetuple())
                            else:
                                # 无法转换，使用当前时间
                                timestamp = time.time()
                        
                        modified_time = datetime.fromtimestamp(timestamp).isoformat()
                    except Exception as e:
                        # 转换失败，使用空字符串
                        print(f"[DEBUG] 转换RAR文件修改时间失败: {e}, 文件: {rel_path}")
                        modified_time = ""
                    
                    files.append({
                        "name": rel_path,
                        "path": file_path,
                        "is_dir": False,
                        "size": file_size,
                        "modified": modified_time,
                        "suffix": os.path.splitext(rel_path)[1].lower()[1:] if '.' in rel_path else ''
                    })
        
        # 添加目录到文件列表
        for dir_name in sorted(dirs):
            if self.current_path:
                if not dir_name.startswith(self.current_path + '/'):
                    continue
                # 获取相对目录路径
                rel_dir = dir_name[len(self.current_path) + 1:]
                # 检查是否是直接子目录
                if '/' in rel_dir or '\\' in rel_dir:
                    # 只添加直接子目录
                    # 处理不同的路径分隔符
                    rel_dir = rel_dir.split('/')[0] if '/' in rel_dir else rel_dir.split('\\')[0]
                    # 确保该目录尚未添加
                    if rel_dir not in [f["name"] for f in files if f["is_dir"]]:
                        files.append({
                            "name": rel_dir,
                            "path": f"{self.current_path}/{rel_dir}",
                            "is_dir": True,
                            "size": 0,
                            "modified": "",
                            "suffix": ""
                        })
                else:
                    # 直接子目录，直接添加
                    files.append({
                        "name": rel_dir,
                        "path": dir_name,
                        "is_dir": True,
                        "size": 0,
                        "modified": "",
                        "suffix": ""
                    })
            else:
                # 根目录下的目录
                if '/' in dir_name or '\\' in dir_name:
                    # 只添加直接子目录
                    # 处理不同的路径分隔符
                    rel_dir = dir_name.split('/')[0] if '/' in dir_name else dir_name.split('\\')[0]
                    # 确保该目录尚未添加
                    if rel_dir not in [f["name"] for f in files if f["is_dir"]]:
                        files.append({
                            "name": rel_dir,
                            "path": rel_dir,
                            "is_dir": True,
                            "size": 0,
                            "modified": "",
                            "suffix": ""
                        })
                else:
                    # 直接子目录，直接添加
                    files.append({
                        "name": dir_name,
                        "path": dir_name,
                        "is_dir": True,
                        "size": 0,
                        "modified": "",
                        "suffix": ""
                    })
        
        # 去重并排序
        unique_files = {}
        for file in files:
            unique_files[file["name"]] = file
        
        return sorted(unique_files.values(), key=lambda x: (not x["is_dir"], x["name"].lower()))
    
    def _get_tar_files(self):
        """
        获取TAR文件中的文件列表
        """
        files = []
        dirs = set()
        
        with tarfile.open(self.archive_path, 'r') as tf:
            for info in tf.getmembers():
                # 获取原始文件名
                file_path = info.name
                
                # 如果是bytes类型，直接解码；否则直接使用字符串
                if isinstance(file_path, bytes):
                    decoded_path = self._decode_filename(file_path)
                else:
                    # 已经是字符串，直接使用
                    decoded_path = file_path
                
                # 跳过隐藏文件
                if os.path.basename(decoded_path).startswith('.'):
                    continue
                
                # 如果是目录，添加到目录集合
                if info.isdir():
                    dirs.add(decoded_path)
                    continue
                
                # 更新file_path为解码后的路径
                file_path = decoded_path
                
                # 检查文件是否在当前路径下
                if self.current_path:
                    if not file_path.startswith(self.current_path + '/'):
                        continue
                    # 获取相对路径
                    rel_path = file_path[len(self.current_path) + 1:]
                else:
                    rel_path = file_path
                
                # 检查是否是当前路径下的直接子项
                if '/' in rel_path:
                    # 是子目录下的文件，只添加目录
                    sub_dir = rel_path.split('/')[0]
                    if sub_dir:  # 确保子目录名不为空
                        dirs.add(sub_dir)
                else:
                    # 是当前目录下的文件
                    files.append({
                        "name": rel_path,
                        "path": file_path,
                        "is_dir": False,
                        "size": info.size,
                        "modified": datetime.fromtimestamp(info.mtime).isoformat(),
                        "suffix": os.path.splitext(rel_path)[1].lower()[1:] if '.' in rel_path else ''
                    })
        
        # 添加目录到文件列表
        for dir_name in sorted(dirs):
            if self.current_path:
                if not dir_name.startswith(self.current_path + '/'):
                    continue
                rel_dir = dir_name[len(self.current_path) + 1:]
                if '/' in rel_dir:
                    # 只添加直接子目录
                    rel_dir = rel_dir.split('/')[0]
                    if rel_dir not in [f["name"] for f in files if f["is_dir"]]:
                        files.append({
                            "name": rel_dir,
                            "path": f"{self.current_path}/{rel_dir}",
                            "is_dir": True,
                            "size": 0,
                            "modified": "",
                            "suffix": ""
                        })
                else:
                    files.append({
                        "name": rel_dir,
                        "path": dir_name,
                        "is_dir": True,
                        "size": 0,
                        "modified": "",
                        "suffix": ""
                    })
            else:
                if '/' in dir_name:
                    # 只添加根目录下的直接子目录
                    rel_dir = dir_name.split('/')[0]
                    if rel_dir not in [f["name"] for f in files if f["is_dir"]]:
                        files.append({
                            "name": rel_dir,
                            "path": rel_dir,
                            "is_dir": True,
                            "size": 0,
                            "modified": "",
                            "suffix": ""
                        })
                else:
                    files.append({
                        "name": dir_name,
                        "path": dir_name,
                        "is_dir": True,
                        "size": 0,
                        "modified": "",
                        "suffix": ""
                    })
        
        # 去重并排序
        unique_files = {}
        for file in files:
            unique_files[file["name"]] = file
        
        return sorted(unique_files.values(), key=lambda x: (not x["is_dir"], x["name"].lower()))
    
    def _get_7z_files(self):
        """
        获取7z文件中的文件列表
        """
        files = []
        dirs = set()
        
        with py7zr.SevenZipFile(self.archive_path, mode='r') as zf:
            for info in zf.list():
                # 获取原始文件名
                file_path = info.filename
                
                # 如果是bytes类型，直接解码；否则直接使用字符串
                if isinstance(file_path, bytes):
                    decoded_path = self._decode_filename(file_path)
                else:
                    # 已经是字符串，直接使用
                    decoded_path = file_path
                
                # 跳过隐藏文件
                if os.path.basename(decoded_path).startswith('.'):
                    continue
                
                # 如果是目录，添加到目录集合
                if decoded_path.endswith('/'):
                    dirs.add(decoded_path)
                    continue
                
                # 更新file_path为解码后的路径
                file_path = decoded_path
                
                # 检查文件是否在当前路径下
                if self.current_path:
                    if not file_path.startswith(self.current_path + '/'):
                        continue
                    # 获取相对路径
                    rel_path = file_path[len(self.current_path) + 1:]
                else:
                    rel_path = file_path
                
                # 检查是否是当前路径下的直接子项
                if '/' in rel_path:
                    # 是子目录下的文件，只添加目录
                    sub_dir = rel_path.split('/')[0]
                    if sub_dir:  # 确保子目录名不为空
                        dirs.add(sub_dir if not self.current_path else f"{self.current_path}/{sub_dir}")
                else:
                    # 是当前目录下的文件
                    # 修复py7zr库FileInfo对象的属性访问
                    file_size = getattr(info, 'uncompressed_size', 0)  # 使用正确的属性名
                    file_mtime = getattr(info, 'mtime', 0)  # 使用正确的属性名
                    files.append({
                        "name": rel_path,
                        "path": file_path,
                        "is_dir": False,
                        "size": file_size,
                        "modified": datetime.fromtimestamp(file_mtime).isoformat() if file_mtime else "",
                        "suffix": os.path.splitext(rel_path)[1].lower()[1:] if '.' in rel_path else ''
                    })
        
        # 添加目录到文件列表
        for dir_name in sorted(dirs):
            if self.current_path:
                if not dir_name.startswith(self.current_path + '/'):
                    continue
                rel_dir = dir_name[len(self.current_path) + 1:].rstrip('/')
                if '/' in rel_dir:
                    # 只添加直接子目录
                    rel_dir = rel_dir.split('/')[0]
                    if rel_dir not in [f["name"] for f in files if f["is_dir"]]:
                        files.append({
                            "name": rel_dir,
                            "path": f"{self.current_path}/{rel_dir}",
                            "is_dir": True,
                            "size": 0,
                            "modified": "",
                            "suffix": ""
                        })
                else:
                    files.append({
                        "name": rel_dir,
                        "path": dir_name.rstrip('/'),
                        "is_dir": True,
                        "size": 0,
                        "modified": "",
                        "suffix": ""
                    })
            else:
                if '/' in dir_name:
                    # 只添加根目录下的直接子目录
                    rel_dir = dir_name.split('/')[0]
                    if rel_dir not in [f["name"] for f in files if f["is_dir"]]:
                        files.append({
                            "name": rel_dir,
                            "path": rel_dir,
                            "is_dir": True,
                            "size": 0,
                            "modified": "",
                            "suffix": ""
                        })
                else:
                    files.append({
                        "name": dir_name.rstrip('/'),
                        "path": dir_name.rstrip('/'),
                        "is_dir": True,
                        "size": 0,
                        "modified": "",
                        "suffix": ""
                    })
        
        # 去重并排序
        unique_files = {}
        for file in files:
            unique_files[file["name"]] = file
        
        return sorted(unique_files.values(), key=lambda x: (not x["is_dir"], x["name"].lower()))
    
    def _get_iso_files(self):
        """
        获取ISO文件中的文件列表
        """
        files = []
        
        iso = pycdlib.PyCdlib()
        iso.open(self.archive_path)
        
        # ISO文件系统的根目录是'/'
        root_path = '/' if not self.current_path else f'/{self.current_path}'
        
        try:
            for child in iso.listdir(path=root_path):
                # 跳过隐藏文件
                if child.startswith('.'):
                    continue
                
                # 检查是否是目录
                is_dir = False
                try:
                    # 尝试列出子目录，如果成功则是目录
                    iso.listdir(path=f'{root_path}{child}')
                    is_dir = True
                except:
                    pass
                
                files.append({
                    "name": child,
                    "path": child if not self.current_path else f"{self.current_path}/{child}",
                    "is_dir": is_dir,
                    "size": 0,  # ISO文件系统获取大小较复杂，暂时设为0
                    "modified": "",  # ISO文件系统获取修改时间较复杂，暂时设为空
                    "suffix": os.path.splitext(child)[1].lower()[1:] if not is_dir and '.' in child else ''
                })
        finally:
            iso.close()
        
        return sorted(files, key=lambda x: (not x["is_dir"], x["name"].lower()))
    
    def go_to_parent(self):
        """
        返回上一级目录
        """
        if self.current_path:
            # 获取父路径
            parent_path = os.path.dirname(self.current_path)
            self.current_path = parent_path if parent_path != '.' else ''
            self.refresh()
    
    def on_item_double_clicked(self, item):
        """
        双击列表项事件处理
        """
        file_info = item.data(Qt.UserRole)
        if file_info["is_dir"]:
            if file_info["name"] == "..":
                self.go_to_parent()
            elif file_info["name"]:  # 确保文件名不为空
                # 进入子目录
                new_path = f"{self.current_path}/{file_info['name']}" if self.current_path else file_info['name']
                self.current_path = new_path
                self.refresh()
    
    def on_item_clicked(self, item):
        """
        点击列表项事件处理
        """
        file_info = item.data(Qt.UserRole)
        self.file_selected.emit(file_info)


if __name__ == "__main__":
    # 测试代码
    app = QApplication(sys.argv)
    
    # 创建主窗口
    window = QWidget()
    window.setWindowTitle("压缩包浏览器测试")
    window.setGeometry(100, 100, 800, 600)
    
    # 创建布局
    layout = QVBoxLayout(window)
    
    # 创建压缩包浏览器
    browser = ArchiveBrowser()
    layout.addWidget(browser)
    
    # 显示窗口
    window.show()
    
    # 运行应用
    sys.exit(app.exec_())
