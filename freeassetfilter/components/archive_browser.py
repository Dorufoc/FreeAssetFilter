#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
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

# 导入日志模块
from freeassetfilter.utils.app_logger import info, debug, warning, error

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QApplication,
    QLabel,
    QGroupBox, QListWidget, QListWidgetItem, QMessageBox,
    QFrame, QSizePolicy, QFileIconProvider
)

# 导入自定义控件
from freeassetfilter.widgets.button_widgets import CustomButton
from freeassetfilter.widgets.input_widgets import CustomInputBox
from freeassetfilter.widgets.dropdown_menu import CustomDropdownMenu
from freeassetfilter.widgets.hover_tooltip import HoverTooltip
from freeassetfilter.widgets.smooth_scroller import D_ScrollBar
from freeassetfilter.widgets.smooth_scroller import SmoothScroller
from PySide6.QtCore import Qt, Signal, QFileInfo
from PySide6.QtGui import QFont, QIcon

# 导入os模块用于路径处理
import os

# 导入 7z 核心模块
from freeassetfilter.core.py7z_core import get_7z_core


class ArchiveBrowser(QWidget):
    """
    压缩包浏览器组件
    支持浏览多种压缩格式的文件目录结构
    """
    
    # 定义信号
    path_changed = Signal(str)  # 当浏览路径变化时发出
    file_selected = Signal(dict)  # 当选中文件时发出
    
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

        # 初始化 7z 核心模块
        self._7z_core = get_7z_core()

        # 初始化文件图标提供者
        self.icon_provider = QFileIconProvider()

        # 初始化编码相关属性
        self.manual_encoding = "utf-8"  # 默认使用UTF-8编码（7z默认输出UTF-8）
        self.supported_encodings = [
            "utf-8", "gbk", "gb2312", "iso-8859-1",
            "ascii", "utf-16", "utf-16le", "utf-16be"
        ]  # 支持的编码列表

        # 初始化悬浮提示工具
        self.hover_tooltip = HoverTooltip(self)

        # 初始化UI
        self.init_ui()
    
    def init_ui(self):
        """
        初始化用户界面
        """
        # 设置组件的大小策略，确保它能正确伸展
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # 设置背景色
        app = QApplication.instance()
        background_color = app.settings_manager.get_setting("appearance.colors.window_background", "#2D2D2D")
        self.setStyleSheet(f"background-color: {background_color};")
        
        # 创建主布局
        main_layout = QVBoxLayout(self)
        scaled_spacing = int(5 * self.dpi_scale)
        scaled_margin = int(5 * self.dpi_scale)
        main_layout.setSpacing(scaled_spacing)
        main_layout.setContentsMargins(scaled_margin, scaled_margin, scaled_margin, scaled_margin)
        
        # 创建顶部控制面板
        control_panel = self._create_control_panel()
        main_layout.addWidget(control_panel)
        
        # 创建文件列表区域
        files_area = self._create_files_area()
        main_layout.addWidget(files_area, 1)
        
        # 创建底部状态栏
        #status_bar = self._create_status_bar()
        #main_layout.addWidget(status_bar)
    
    def _create_control_panel(self):
        """
        创建控制面板
        """
        panel = QGroupBox()
        app = QApplication.instance()
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # 隐藏边框，与文件选择器保持一致的样式
        panel.setStyleSheet("QGroupBox { border: 20dx; }")
        if hasattr(app, 'settings_manager'):
            settings_manager = app.settings_manager
        else:
            from freeassetfilter.core.settings_manager import SettingsManager
            settings_manager = SettingsManager()
        base_color = settings_manager.get_setting("appearance.colors.base_color", "#212121")
        # 使用垂直布局
        main_layout = QVBoxLayout(panel)
        scaled_spacing = int(5 * self.dpi_scale)
        scaled_margin = int(5 * self.dpi_scale)
        main_layout.setSpacing(scaled_spacing)
        main_layout.setContentsMargins(scaled_margin, scaled_margin, scaled_margin, scaled_margin)
        
        # 应用DPI缩放因子到按钮高度（字体大小已由Qt自动处理）
        # 使用统一的按钮高度（与文件选择器保持一致）
        button_height = 20
        scaled_button_height = int(button_height * self.dpi_scale)

        # 使用全局字体，让Qt6自动处理DPI缩放
        control_font = self.global_font
        
        # 第一行：路径显示和返回按钮
        path_layout = QHBoxLayout()
        path_layout.setSpacing(scaled_spacing)
        
        # 返回上一级按钮
        # 使用与文件选择器相同的unto.svg图标
        unto_icon_path = os.path.join(os.path.dirname(__file__), "..", "icons", "unto.svg")
        self.back_btn = CustomButton(unto_icon_path, button_type="normal", display_mode="icon", tooltip_text="返回上一级目录")
        self.back_btn.clicked.connect(self.go_to_parent)
        # 始终保持启用状态，由go_to_parent方法内部处理是否有上一级
        path_layout.addWidget(self.back_btn)
        # 添加到悬浮提示目标控件
        self.hover_tooltip.set_target_widget(self.back_btn)
        
        # 当前路径显示
        self.path_edit = CustomInputBox(height=button_height)
        self.path_edit.line_edit.setReadOnly(True)
        self.path_edit.set_text("无压缩包路径")
        path_layout.addWidget(self.path_edit, 1)
        
        # 编码选择下拉框（放到地址栏后面，使用外部按钮 + 下拉菜单模式）
        self.encoding_combo = CustomDropdownMenu(self, position="bottom", use_internal_button=False)

        # 添加支持的编码（只显示编码格式本身）
        encoding_items = []
        for enc in self.supported_encodings:
            encoding_items.append({"text": enc.upper(), "data": enc})

        # 设置默认选择为UTF-8（7z默认输出UTF-8）
        self.encoding_combo.set_items(encoding_items, default_item={"text": "UTF-8", "data": "utf-8"})
        self.encoding_combo.itemClicked.connect(self._on_encoding_changed)

        self.encoding_button = CustomButton(
            "UTF-8",
            button_type="normal",
            display_mode="text",
            height=button_height,
            tooltip_text="编码"
        )
        self.encoding_button.setFont(control_font)
        self.encoding_combo.set_target_button(self.encoding_button)

        def show_encoding_menu():
            self.encoding_combo.set_target_button(self.encoding_button)
            self.encoding_combo.show_menu()

        self.encoding_button.clicked.connect(show_encoding_menu)
        path_layout.addWidget(self.encoding_button)
        
        main_layout.addLayout(path_layout)
        
        # 第二行：压缩包信息（已隐藏）
        # info_layout = QHBoxLayout()
        # info_layout.setSpacing(scaled_spacing)
        
        # 压缩包类型显示
        self.type_label = QLabel("压缩包类型: ")
        self.type_label.setFont(control_font)
        self.type_label.hide()  # 隐藏标签
        # info_layout.addWidget(self.type_label)

        # 加密状态显示
        self.encryption_label = QLabel("加密状态: 未加密")
        self.encryption_label.setFont(control_font)
        self.encryption_label.hide()  # 隐藏标签
        # info_layout.addWidget(self.encryption_label)
        
        # info_layout.addStretch(1)
        # main_layout.addLayout(info_layout)
        
        return panel
    
    def _adjust_color(self, color_hex, percent):
        """
        将颜色加深或变淡指定百分比，深色模式下则相反
        
        参数：
            color_hex (str): 十六进制颜色值
            percent (int): 加深/变淡百分比（1-100）
            
        返回：
            str: 处理后的十六进制颜色值
        """
        # 获取当前主题模式
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if hasattr(app, 'settings_manager'):
            settings_manager = app.settings_manager
        else:
            from freeassetfilter.core.settings_manager import SettingsManager
            settings_manager = SettingsManager()
        current_theme = settings_manager.get_setting("appearance.theme", "default")
        is_dark_mode = (current_theme == "dark")
        
        # 将十六进制颜色转换为RGB
        from PySide6.QtGui import QColor
        color = QColor(color_hex)
        r = color.red()
        g = color.green()
        b = color.blue()
        
        # 计算处理后的RGB值
        if is_dark_mode:
            # 深色模式下变浅
            factor = 1 + percent / 100
            r = min(255, int(r * factor))
            g = min(255, int(g * factor))
            b = min(255, int(b * factor))
        else:
            # 浅色模式下加深
            factor = 1 - percent / 100
            r = max(0, int(r * factor))
            g = max(0, int(g * factor))
            b = max(0, int(b * factor))
        
        # 转换回十六进制颜色
        return "#" + "{:02x}{:02x}{:02x}".format(r, g, b)
    
    def _create_files_area(self):
        """
        创建文件列表区域
        集成自定义丝滑滚动条和平滑滚动效果
        """
        # 获取颜色设置
        app = QApplication.instance()
        if hasattr(app, 'settings_manager'):
            settings_manager = app.settings_manager
        else:
            from freeassetfilter.core.settings_manager import SettingsManager
            settings_manager = SettingsManager()

        current_colors = settings_manager.get_setting("appearance.colors", {
            "secondary_color": "#FFFFFF",
            "base_color": "#212121",
            "auxiliary_color": "#3D3D3D",
            "normal_color": "#717171",
            "accent_color": "#B036EE"
        })

        base_color = current_colors.get('base_color', '#212121')
        border_radius = int(6 * self.dpi_scale)

        # 创建文件列表
        self.files_list = QListWidget()
        self.files_list.itemClicked.connect(self.on_item_clicked)
        # 双击事件通过重载 mouseDoubleClickEvent 处理，以区分鼠标按键

        # 为 QListWidget 设置自定义丝滑滚动条
        self.files_list.setVerticalScrollBar(D_ScrollBar(self.files_list, Qt.Vertical))
        self.files_list.verticalScrollBar().apply_theme_from_settings()

        # 启用 QListWidget 的像素级滚动模式以实现平滑滚动
        self.files_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.files_list.setHorizontalScrollMode(QListWidget.ScrollPerPixel)

        # 应用平滑滚动到 QListWidget 的视口，启用触摸滚动（禁用鼠标拖动，仅使用滚轮/滚动条）
        SmoothScroller.apply(self.files_list, enable_mouse_drag=False)

        # 禁用 QListWidget 自身的触摸事件处理，完全由 SmoothScroller 控制滚动
        self.files_list.setAttribute(Qt.WA_AcceptTouchEvents, False)
        self.files_list.viewport().setAttribute(Qt.WA_AcceptTouchEvents, False)
        
        # 从app对象获取全局默认字体大小（Qt已自动处理DPI缩放，无需再乘dpi_scale）
        # 使用全局字体，让Qt6自动处理DPI缩放
        self.files_list.setFont(self.global_font)

        # 存储字体供条目使用
        self.scaled_font = self.global_font
        
        # 获取颜色设置
        if hasattr(app, 'settings_manager'):
            settings_manager = app.settings_manager
        else:
            from freeassetfilter.core.settings_manager import SettingsManager
            settings_manager = SettingsManager()
        
        current_colors = settings_manager.get_setting("appearance.colors", {
            "secondary_color": "#FFFFFF",
            "base_color": "#212121",
            "auxiliary_color": "#3D3D3D",
            "normal_color": "#717171",
            "accent_color": "#B036EE"
        })
        
        # 设置列表项高度
        scaled_item_height = int(15 * self.dpi_scale)

        # 获取强调色并设置透明度为0.4
        from PySide6.QtGui import QColor
        accent_color = current_colors.get("accent_color", "#B036EE")
        qcolor = QColor(accent_color)
        # 设置alpha通道为155
        qcolor.setAlpha(155)
        # 转换为CSS rgba格式
        selected_bg_color = f"rgba({qcolor.red()}, {qcolor.green()}, {qcolor.blue()}, 0.4)"

        # 获取其他颜色值
        secondary_color = current_colors.get('secondary_color', '#FFFFFF')
        auxiliary_color = current_colors.get('auxiliary_color', '#3D3D3D')
        normal_color = current_colors.get('normal_color', '#717171')

        # 计算圆角半径和边距（基于DPI缩放）
        item_margin = int(2 * self.dpi_scale)

        # 禁用列表的焦点策略
        self.files_list.setFocusPolicy(Qt.NoFocus)

        # 连接鼠标点击事件，用于检测点击空白区域
        self.files_list.mousePressEvent = self._on_list_mouse_press

        # 连接鼠标双击事件，只响应左键双击
        self.files_list.mouseDoubleClickEvent = self._on_list_mouse_double_click

        # 设置 QListWidget 的样式（添加圆角背景，并在样式表中设置字体大小）
        self.files_list.setStyleSheet(f"""
            QListWidget {{
                show-decoration-selected: 0;
                outline: none;
                background-color: {base_color};
                border: none;
                border-radius: {border_radius}px;
                padding: 6px;
            }}
            QListWidget::item {{
                height: {scaled_item_height}px;
                color: {secondary_color};
                background-color: {base_color};
                border: 1px solid {auxiliary_color};
                border-radius: {border_radius}px;
                outline: none;
                margin: {item_margin}px {item_margin}px 0 {item_margin}px;
                padding-left: 8px;
            }}
            QListWidget::item:hover {{
                color: {secondary_color};
                background-color: {auxiliary_color};
                border: 1px solid {normal_color};
                border-radius: {border_radius}px;
            }}
            QListWidget::item:selected {{
                color: {secondary_color};
                background-color: {selected_bg_color};
                border: 1px solid {accent_color};
                border-radius: {border_radius}px;
            }}
            QListWidget::item:selected:focus, QListWidget::item:focus {{
                outline: none;
                border: 1px solid {accent_color};
                border-radius: {border_radius}px;
            }}
            QListWidget:focus, QListWidget::item:focus, QListWidget::item:selected:focus {{
                outline: none;
                selection-background-color: transparent;
                selection-color: transparent;
            }}
        """)

        return self.files_list
    
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
            # 重置编码为默认值UTF-8（7z默认输出UTF-8）
            self.manual_encoding = "utf-8"
            # 更新编码选择下拉框和外部按钮显示
            self.encoding_combo.set_current_item({"text": "UTF-8", "data": "utf-8"})
            self.encoding_button.setText("UTF-8")
            self.refresh()
        else:
            QMessageBox.warning(self, "警告", "无效的压缩包路径")
    
    def _on_encoding_changed(self, item_data):
        """
        编码选择变化
        """
        # 获取选择的编码
        self.manual_encoding = item_data
        if hasattr(self, "encoding_button") and self.encoding_button:
            self.encoding_button.setText(str(item_data).upper())
        # 立即刷新文件列表，应用新编码
        self.refresh()
    
    def _detect_archive_type(self):
        """
        检测压缩包类型
        使用 7z 核心模块获取类型
        """
        if self.archive_path and self._7z_core:
            self.archive_type = self._7z_core.get_archive_type(self.archive_path)
        else:
            self.archive_type = 'unknown'

        self.type_label.setText(f"压缩包类型: {self.archive_type.upper()}")
    
    def _detect_encryption(self):
        """
        检测压缩包是否加密
        使用 7z 核心模块检测
        """
        self.is_encrypted = False

        try:
            if self.archive_path and self._7z_core:
                self.is_encrypted = self._7z_core.is_encrypted(
                    self.archive_path,
                    encoding=self.manual_encoding
                )
        except Exception as e:
            warning(f"检测加密状态失败: {e}")

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
        except (OSError, IOError, RuntimeError) as e:
            QMessageBox.critical(self, "错误", f"读取压缩包失败: {e}")
            return

        # 检测是否有编码解码错误（文件名中包含替换字符）
        has_encoding_error = False
        for file in self.archive_content:
            if '\ufffd' in file.get("name", ""):
                has_encoding_error = True
                break

        # 添加文件和文件夹项
        for file in self.archive_content:
            # 跳过空白文件名
            if not file["name"]:
                continue

            item = QListWidgetItem()
            item.setText(file["name"])
            item.setData(Qt.UserRole, file)
            # 应用全局字体
            item.setFont(self.scaled_font)

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

        # 如果有编码错误，在列表顶部添加提示项
        if has_encoding_error:
            self._add_encoding_error_item()

        # 更新返回按钮状态（注释掉，使按钮始终保持启用状态）
        # self.back_btn.setEnabled(bool(self.current_path))

        # 更新文件计数
        #self.file_count_label.setText(f"文件数量: {len(self.archive_content)}")

        # 发送路径变化信号
        self.path_changed.emit(self.current_path)

    def _add_encoding_error_item(self):
        """
        添加编码错误提示项到文件列表顶部
        """
        # 创建提示项
        warning_item = QListWidgetItem()
        warning_item.setText("⚠️ 编码错误：当前编码无法解析部分文件名，请尝试切换编码")
        warning_item.setFlags(warning_item.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)  # 禁用选择和交互

        # 获取当前主题颜色
        app = QApplication.instance()
        if hasattr(app, 'settings_manager'):
            settings_manager = app.settings_manager
        else:
            from freeassetfilter.core.settings_manager import SettingsManager
            settings_manager = SettingsManager()

        current_colors = settings_manager.get_setting("appearance.colors", {
            "secondary_color": "#FFFFFF",
            "base_color": "#212121",
            "auxiliary_color": "#3D3D3D",
            "normal_color": "#717171",
            "accent_color": "#B036EE"
        })

        # 使用橙色/红色作为警告色
        warning_color = "#FF9800"  # 橙色

        # 设置提示项样式
        warning_item.setBackground(Qt.transparent)
        warning_item.setForeground(Qt.red)

        # 插入到列表顶部
        self.files_list.insertItem(0, warning_item)
    
    def _get_files(self):
        """
        获取当前路径下的文件和文件夹
        使用 7z 核心模块统一处理所有压缩格式

        Returns:
            list: 文件和文件夹列表
        """
        if not self.archive_path or not self._7z_core:
            return []

        try:
            files = self._7z_core.list_archive(
                self.archive_path,
                current_path=self.current_path,
                encoding=self.manual_encoding
            )
            return files
        except Exception as e:
            error(f"获取压缩包文件列表失败: {e}")
            raise RuntimeError(f"读取压缩包失败: {e}")
    
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
        if file_info["is_dir"] and file_info["name"]:  # 确保文件名不为空
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

    def _on_list_mouse_press(self, event):
        """
        处理列表区域的鼠标点击事件
        当点击空白区域时取消所有选中状态
        支持鼠标侧键返回上级目录

        参数：
            event: 鼠标事件对象
        """
        # 处理鼠标侧键返回上级（XButton1 通常是鼠标上的"后退"按钮）
        if event.button() == Qt.XButton1:
            self.go_to_parent()
            return

        # 获取点击位置对应的列表项
        item = self.files_list.itemAt(event.pos())

        if item is None:
            # 点击了空白区域，取消所有选中状态
            self.files_list.clearSelection()
            # 发送空信号表示取消选中
            self.file_selected.emit({})
        else:
            # 点击了列表项，调用原来的点击处理
            self.on_item_clicked(item)

        # 调用父类的鼠标按下事件处理（保持原有的交互行为）
        QListWidget.mousePressEvent(self.files_list, event)

    def _on_list_mouse_double_click(self, event):
        """
        处理列表区域的鼠标双击事件
        只响应左键双击，其他按键不响应

        参数：
            event: 鼠标事件对象
        """
        # 只响应左键双击
        if event.button() == Qt.LeftButton:
            # 获取双击位置对应的列表项
            item = self.files_list.itemAt(event.pos())
            if item is not None:
                # 调用双击处理
                self.on_item_double_clicked(item)

        # 调用父类的鼠标双击事件处理（保持原有的交互行为）
        QListWidget.mouseDoubleClickEvent(self.files_list, event)


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
    sys.exit(app.exec())
