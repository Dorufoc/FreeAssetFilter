#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

文件夹内信息列表预览组件
显示给定路径下的所有文件和文件夹，提供基本信息预览
"""

import sys
import os
from datetime import datetime

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# 导入日志模块
from freeassetfilter.utils.app_logger import info, debug, warning, error

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QSplitter, QFrame, QSizePolicy,
    QFileIconProvider, QMenu, QApplication
)
from PySide6.QtCore import (
    Qt, Signal, QFileInfo, QDateTime, QThread
)
from PySide6.QtGui import (
    QIcon, QFont, QColor, QBrush
)

# 导入自定义滚动条
from freeassetfilter.widgets.smooth_scroller import D_ScrollBar, SmoothScroller
# 导入自定义输入框
from freeassetfilter.widgets.input_widgets import CustomInputBox
# 导入自定义按钮
from freeassetfilter.widgets.button_widgets import CustomButton


class FolderContentLoaderThread(QThread):
    loaded = Signal(str, list)
    load_failed = Signal(str, str)

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self._path = path

    def run(self):
        entries = []
        try:
            with os.scandir(self._path) as it:
                for entry in it:
                    try:
                        is_dir = entry.is_dir(follow_symlinks=False)
                    except (OSError, PermissionError):
                        is_dir = False

                    try:
                        stat = entry.stat(follow_symlinks=False)
                        size = stat.st_size
                        modified_ts = stat.st_mtime
                    except (OSError, PermissionError):
                        size = 0
                        modified_ts = None

                    entries.append({
                        "name": entry.name,
                        "path": entry.path,
                        "is_dir": is_dir,
                        "size": size,
                        "modified_ts": modified_ts,
                    })

            entries.sort(key=lambda item: (not item["is_dir"], item["name"].lower()))
            self.loaded.emit(self._path, entries)
        except PermissionError as e:
            self.load_failed.emit(self._path, f"权限不足: {e}")
        except OSError as e:
            self.load_failed.emit(self._path, f"系统错误: {e}")


class FolderContentList(QWidget):
    """
    文件夹内信息列表预览组件
    显示给定路径下的所有文件和文件夹
    """

    # 定义信号：请求在文件选择器中打开当前路径（路径，文件信息）
    open_in_selector_requested = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        debug("文件夹内容列表组件初始化")

        # 获取应用实例和DPI缩放因子
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QFont
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)

        # 获取全局字体
        self.global_font = getattr(app, 'global_font', QFont())
        # 设置组件字体
        self.setFont(self.global_font)

        # 初始化配置
        self.current_path = os.path.expanduser("~")  # 默认路径为用户主目录

        # 创建文件图标提供者
        self.icon_provider = QFileIconProvider()
        self._load_thread = None
        self._load_request_id = 0

        # 初始化UI
        self.init_ui()

        # 加载初始路径内容
        self.load_folder_content()
        debug("文件夹内容列表组件初始化完成")
    
    def init_ui(self):
        """
        初始化用户界面
        """
        # 应用DPI缩放因子到布局参数
        scaled_spacing = int(5 * self.dpi_scale)
        scaled_margin = int(5 * self.dpi_scale)

        # 获取应用实例
        app = QApplication.instance()

        # 获取默认字体大小（Qt已自动处理DPI缩放，无需再乘dpi_scale）
        default_font_size = getattr(app, 'default_font_size', 9)

        # 创建主布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(scaled_spacing)
        main_layout.setContentsMargins(scaled_margin, scaled_margin, scaled_margin, scaled_margin)

        # 设置背景色
        background_color = app.settings_manager.get_setting("appearance.colors.window_background", "#2D2D2D")
        self.setStyleSheet(f"background-color: {background_color};")

        # 使用统一的按钮高度（与压缩包预览器保持一致）
        button_height = 20

        # 创建顶部路径栏
        path_layout = QHBoxLayout()
        path_layout.setSpacing(scaled_spacing)

        # 当前路径显示（使用CustomInputBox，与压缩包预览器保持一致）
        self.path_edit = CustomInputBox(height=button_height)
        self.path_edit.line_edit.setReadOnly(True)
        self.path_edit.set_text(self.current_path)
        path_layout.addWidget(self.path_edit, 1)

        # 在文件选择器中打开按钮（次选样式）
        self.open_in_selector_btn = CustomButton(
            "在文件选择器中打开",
            button_type="secondary",
            height=button_height
        )
        self.open_in_selector_btn.clicked.connect(self._on_open_in_selector_clicked)
        path_layout.addWidget(self.open_in_selector_btn)

        main_layout.addLayout(path_layout)

        # 创建列表控件
        self.content_list = QListWidget()
        self.content_list.setFont(self.global_font)

        # 为 QListWidget 设置自定义丝滑滚动条
        self.content_list.setVerticalScrollBar(D_ScrollBar(self.content_list, Qt.Vertical))
        self.content_list.verticalScrollBar().apply_theme_from_settings()
        # 禁用水平滚动条
        self.content_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # 启用 QListWidget 的像素级滚动模式以实现平滑滚动
        self.content_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)

        # 应用平滑滚动到 QListWidget 的视口，启用触摸滚动（禁用鼠标拖动，仅使用滚轮/滚动条）
        SmoothScroller.apply(self.content_list, enable_mouse_drag=False)

        # 禁用 QListWidget 自身的触摸事件处理，完全由 SmoothScroller 控制滚动
        self.content_list.setAttribute(Qt.WA_AcceptTouchEvents, False)
        self.content_list.viewport().setAttribute(Qt.WA_AcceptTouchEvents, False)

        # 使用全局字体，让Qt6自动处理DPI缩放
        self.content_list.setFont(self.global_font)

        # 存储字体供条目使用
        self.scaled_font = self.global_font

        # 获取颜色设置
        current_colors = app.settings_manager.get_setting("appearance.colors", {
            "secondary_color": "#FFFFFF",
            "base_color": "#212121",
            "auxiliary_color": "#3D3D3D",
            "normal_color": "#717171",
            "accent_color": "#B036EE"
        })

        base_color = current_colors.get('base_color', '#212121')
        border_radius = int(6 * self.dpi_scale)

        # 设置列表项高度
        scaled_item_height = int(15 * self.dpi_scale)

        # 获取强调色并设置透明度为0.4
        accent_color = current_colors.get("accent_color", "#B036EE")
        qcolor = QColor(accent_color)
        qcolor.setAlpha(155)
        selected_bg_color = f"rgba({qcolor.red()}, {qcolor.green()}, {qcolor.blue()}, 0.4)"

        # 获取其他颜色值
        secondary_color = current_colors.get('secondary_color', '#FFFFFF')
        auxiliary_color = current_colors.get('auxiliary_color', '#3D3D3D')
        normal_color = current_colors.get('normal_color', '#717171')

        # 计算圆角半径和边距（基于DPI缩放）
        item_margin = int(2 * self.dpi_scale)

        # 禁用列表的焦点策略
        self.content_list.setFocusPolicy(Qt.NoFocus)

        # 设置 QListWidget 的样式（与压缩包预览器保持一致）
        # 注意：字体大小由setFont设置，不在样式表中指定
        self.content_list.setStyleSheet(f"""
            QListWidget {{
                show-decoration-selected: 0;
                outline: none;
                background-color: {base_color};
                border: none;
                border-radius: {border_radius}px;
                padding: 6px;
            }}
            QListWidget::item {{
                width: -1;
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

        main_layout.addWidget(self.content_list)
    
    def set_path(self, path):
        """
        设置当前路径

        Args:
            path (str): 要设置的路径
        """
        if os.path.exists(path) and os.path.isdir(path):
            debug(f"设置文件夹路径: {path}")
            self.current_path = path
            self.path_edit.set_text(self.current_path)
            self.load_folder_content()

    def _on_open_in_selector_clicked(self):
        """
        处理"在文件选择器中打开"按钮点击事件
        发出信号请求主应用程序在文件选择器中打开当前路径
        """
        if self.current_path and os.path.exists(self.current_path):
            debug("请求在文件选择器中打开文件夹")
            # 创建文件信息字典，与 unified_previewer 格式保持一致
            file_info = {"path": self.current_path, "is_directory": True}
            self.open_in_selector_requested.emit(self.current_path, file_info)
        
    def load_folder_content(self):
        """
        加载当前路径下的内容
        """
        self._load_request_id += 1
        request_id = self._load_request_id
        path = self.current_path

        self.content_list.clear()
        loading_item = QListWidgetItem("正在加载...")
        loading_item.setFont(self.scaled_font)
        self.content_list.addItem(loading_item)

        if self._load_thread and self._load_thread.isRunning():
            self._load_thread.loaded.disconnect()
            self._load_thread.load_failed.disconnect()
            self._load_thread.quit()
            self._load_thread.wait(100)

        self._load_thread = FolderContentLoaderThread(path, self)
        self._load_thread.loaded.connect(lambda loaded_path, entries: self._on_folder_content_loaded(request_id, loaded_path, entries))
        self._load_thread.load_failed.connect(lambda failed_path, message: self._on_folder_content_failed(request_id, failed_path, message))
        self._load_thread.start()

    def _on_folder_content_loaded(self, request_id, loaded_path, entries):
        if request_id != self._load_request_id or loaded_path != self.current_path:
            return

        self.content_list.clear()
        debug(f"加载文件夹内容，条目数: {len(entries)}")

        for entry in entries:
            file_info = QFileInfo(entry["path"])
            item = QListWidgetItem()
            item.setFont(self.scaled_font)

            if entry["is_dir"]:
                icon = self.icon_provider.icon(QFileIconProvider.Folder)
                item.setText(entry["name"])
            else:
                icon = self.icon_provider.icon(file_info)
                size = self._format_size(entry["size"])
                if entry["modified_ts"] is None:
                    modified_time = ""
                else:
                    modified_time = datetime.fromtimestamp(entry["modified_ts"]).strftime("%Y-%m-%d %H:%M")
                item.setText(f"{entry['name']} ({size}) - {modified_time}" if modified_time else f"{entry['name']} ({size})")

            item.setIcon(icon)
            self.content_list.addItem(item)

    def _on_folder_content_failed(self, request_id, failed_path, message):
        if request_id != self._load_request_id or failed_path != self.current_path:
            return

        self.content_list.clear()
        error_item = QListWidgetItem(message)
        error_item.setFont(self.scaled_font)
        self.content_list.addItem(error_item)
        warning(message)
    

    
    def _format_size(self, size_bytes):
        """
        格式化文件大小
        
        Args:
            size_bytes (int): 文件大小（字节）
            
        Returns:
            str: 格式化后的文件大小
        """
        if size_bytes == 0:
            return "0 B"
        
        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024
            i += 1
        
        return f"{size_bytes:.1f} {size_names[i]}"


# 测试代码
if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication, QMainWindow
    
    app = QApplication(sys.argv)
    
    window = QMainWindow()
    window.setWindowTitle("文件夹内信息列表预览组件")
    window.setGeometry(100, 100, 800, 600)
    
    folder_list = FolderContentList()
    window.setCentralWidget(folder_list)
    
    window.show()
    sys.exit(app.exec())
