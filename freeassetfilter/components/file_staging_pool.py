#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

文件临时存储池组件
用于展示和管理从左侧素材区添加的文件/文件夹项目
"""

import os
import sys
import tempfile

# 添加项目根目录到Python路径，解决直接运行时的导入问题
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# 导入日志模块
from freeassetfilter.utils.app_logger import info, debug, warning, error
from freeassetfilter.utils.path_utils import get_app_data_path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QScrollArea, QGroupBox, QListWidget, QListWidgetItem,
    QSizePolicy, QCheckBox, QMenu, QProgressBar, QFileDialog, QApplication
)

# 导入自定义控件
from freeassetfilter.widgets.D_widgets import CustomButton, CustomMessageBox
from freeassetfilter.widgets.progress_widgets import D_ProgressBar
from freeassetfilter.widgets.file_horizontal_card import CustomFileHorizontalCard
from freeassetfilter.widgets.hover_tooltip import HoverTooltip
from freeassetfilter.widgets.smooth_scroller import D_ScrollBar
from freeassetfilter.widgets.smooth_scroller import SmoothScroller
from PySide6.QtCore import (
    Qt, Signal, QFileInfo, QThread, QMetaObject, Q_ARG, QObject, QRunnable, QTimer
)
from PySide6.QtGui import QIcon, QColor, QPixmap, QFont, QAction

# 导入缩略图管理器
from freeassetfilter.core.thumbnail_manager import get_thumbnail_manager, get_existing_thumbnail_path


class FileStagingPool(QWidget):
    """
    文件临时存储池组件
    用于展示和管理从左侧素材区添加的文件/文件夹项目
    """

    # 定义信号
    item_right_clicked = Signal(dict)  # 当项目被右键点击时发出
    item_left_clicked = Signal(dict)  # 当项目被左键点击时发出
    remove_from_selector = Signal(dict)  # 当需要从选择器中移除文件时发出
    file_added_to_pool = Signal(dict)  # 当文件被添加到储存池时发出
    update_progress = Signal(int)  # 更新进度条信号
    export_finished = Signal(int, int, list)  # 导出完成信号
    folder_size_calculated = Signal(dict)  # 文件夹体积计算完成信号
    navigate_to_path = Signal(str, dict)  # 当需要导航到某个路径时发出，第二个参数是可选的文件信息

    def __init__(self, parent=None):
        super().__init__(parent)

        # 获取应用实例和DPI缩放因子
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QFont
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)

        # 获取全局字体
        self.global_font = getattr(app, 'global_font', QFont())

        # 设置组件字体
        self.setFont(self.global_font)

        # 初始化数据
        self.items = []  # 存储所有添加的文件/文件夹项目
        self.previewing_file_path = None  # 当前处于预览态的文件路径
        self._active_size_calculators = []  # 跟踪活动的文件夹大小计算线程
        self._suspend_backup_save = False  # 启动恢复期间暂停频繁保存备份
        self._pending_backup_last_path = 'All'
        self._backup_save_delay_ms = 1500
        self._backup_save_timer = QTimer(self)
        self._backup_save_timer.setSingleShot(True)
        self._backup_save_timer.timeout.connect(self._flush_pending_backup_save)

        # 获取设置管理器引用
        app = QApplication.instance()
        self.settings_manager = getattr(app, 'settings_manager', None)

        # 备份文件路径 - 使用get_app_data_path确保打包后路径正确
        self.backup_file = os.path.join(get_app_data_path(), 'staging_pool_backup.json')

        # 初始化UI
        self.init_ui()

        # 启用拖拽功能
        self.setAcceptDrops(True)
        self.cards_container.setAcceptDrops(True)

        # 连接信号
        self.update_progress.connect(self.on_update_progress)
        self.export_finished.connect(self.on_export_finished)
        self.folder_size_calculated.connect(self.on_folder_size_calculated)

    def _save_backup_if_needed(self, last_path='All'):
        """
        在允许的情况下请求保存备份。
        启动恢复阶段会临时关闭频繁保存，结束后由主窗口统一请求一次保存。
        这里使用防抖定时器合并短时间内的多次保存请求，减少磁盘 I/O。

        Args:
            last_path (str): 文件选择器当前路径
        """
        self._pending_backup_last_path = last_path
        if self._suspend_backup_save:
            return

        if self._backup_save_timer.isActive():
            self._backup_save_timer.stop()
        self._backup_save_timer.start(self._backup_save_delay_ms)

    def _flush_pending_backup_save(self):
        """
        执行一次实际备份写入。
        """
        if self._suspend_backup_save:
            return
        self.save_backup(self._pending_backup_last_path)

    def flush_backup_save_now(self, last_path=None):
        """
        立即执行一次保存，通常用于退出前等必须落盘的场景。

        Args:
            last_path (str, optional): 指定路径；若为空则使用最近一次缓存的路径
        """
        if last_path is not None:
            self._pending_backup_last_path = last_path
        if self._backup_save_timer.isActive():
            self._backup_save_timer.stop()
        self.save_backup(self._pending_backup_last_path)

    def init_ui(self):
        """
        初始化用户界面
        """
        scaled_margin = int(5 * self.dpi_scale)
        scaled_h_margin = int(3 * self.dpi_scale)

        main_layout = QVBoxLayout(self)
        app = QApplication.instance()
        background_color = "#2D2D2D"
        if hasattr(app, 'settings_manager'):
            background_color = app.settings_manager.get_setting("appearance.colors.window_background", "#2D2D2D")
        self.setStyleSheet(f"background-color: {background_color};")
        main_layout.setSpacing(scaled_margin)
        main_layout.setContentsMargins(scaled_h_margin, scaled_margin, scaled_h_margin, scaled_margin)

        # 创建标题和控制区
        title_layout = QHBoxLayout()

        # 标题
        font = QFont("", 12, QFont.Bold)

        main_layout.addLayout(title_layout)

        # 创建滚动区域
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        app = QApplication.instance()
        base_color = app.settings_manager.get_setting("appearance.colors.base_color", "#212121")
        auxiliary_color = app.settings_manager.get_setting("appearance.colors.auxiliary_color", "#313131")
        normal_color = app.settings_manager.get_setting("appearance.colors.normal_color", "#717171")
        secondary_color = app.settings_manager.get_setting("appearance.colors.secondary_color", "#FFFFFF")
        accent_color = app.settings_manager.get_setting("appearance.colors.accent_color", "#F0C54D")

        scaled_border_radius = int(8 * self.dpi_scale)
        scaled_border_width = int(1 * self.dpi_scale)

        scaled_padding = int(3 * self.dpi_scale)

        scrollbar_style = f"""
            QScrollArea {{
                border: {scaled_border_width}px solid {normal_color};
                border-radius: {scaled_border_radius}px;
                background-color: {base_color};
                padding: {scaled_padding}px;
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: transparent;
                border: none;
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
        self.scroll_area.setStyleSheet(scrollbar_style)

        # 使用动画滚动条
        self.scroll_area.setVerticalScrollBar(D_ScrollBar(self.scroll_area, Qt.Vertical))
        self.scroll_area.verticalScrollBar().set_colors(normal_color, secondary_color, accent_color, auxiliary_color)

        SmoothScroller.apply_to_scroll_area(self.scroll_area)

        # 创建卡片容器和布局
        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setSpacing(int(3 * self.dpi_scale))
        self.cards_layout.setContentsMargins(int(3 * self.dpi_scale), 0, int(3 * self.dpi_scale), 0)
        self.cards_layout.setAlignment(Qt.AlignTop)
        self.cards_layout.addStretch(1)

        # 将卡片容器放入滚动区域
        self.scroll_area.setWidget(self.cards_container)

        # 添加到主布局
        main_layout.addWidget(self.scroll_area, 1)

        # 存储卡片对象
        self.cards = []

        # 创建统计信息容器
        stats_container = QWidget()
        stats_container.setStyleSheet("background-color: transparent; border: none;")
        stats_container_layout = QHBoxLayout(stats_container)
        stats_container_layout.setContentsMargins(0, 0, 0, 0)
        stats_container_layout.setSpacing(0)

        self.stats_label = QLabel("0个条目")
        self.stats_label.setAlignment(Qt.AlignCenter)
        self.stats_label.setFont(self.global_font)
        self.stats_label.setStyleSheet(f"color: {secondary_color};")
        stats_container_layout.addWidget(self.stats_label)

        main_layout.addWidget(stats_container)

        # 创建导出功能区
        export_layout = QHBoxLayout()

        # 导入/导出数据按钮
        self.import_export_btn = CustomButton("导入/导出数据", button_type="secondary")
        self.import_export_btn.clicked.connect(self.show_import_export_dialog)
        export_layout.addWidget(self.import_export_btn)

        # 导出按钮
        self.export_btn = CustomButton("导出文件", button_type="primary")
        self.export_btn.clicked.connect(self.export_selected_files)
        export_layout.addWidget(self.export_btn)

        # 控制按钮
        import os
        trash_icon_path = os.path.join(os.path.dirname(__file__), "..", "icons", "trash.svg")
        clear_btn = CustomButton(trash_icon_path, button_type="normal", display_mode="icon", tooltip_text="清空所有项目")
        clear_btn.clicked.connect(self.clear_all)
        export_layout.addWidget(clear_btn)

        # 进度条
        self.progress_bar = D_ProgressBar()
        self.progress_bar.setInteractive(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        export_layout.addWidget(self.progress_bar, 1)

        main_layout.addLayout(export_layout)

        # 初始化悬浮详细信息组件
        self.hover_tooltip = HoverTooltip(self)

        # 保存按钮引用，供主题刷新时复用
        self.clear_btn = clear_btn

        # 将按钮添加到悬浮信息目标控件
        self.hover_tooltip.set_target_widget(self.import_export_btn)
        self.hover_tooltip.set_target_widget(self.export_btn)
        self.hover_tooltip.set_target_widget(clear_btn)

    def _get_theme_colors(self):
        """
        获取当前主题颜色
        """
        app = QApplication.instance()
        colors = {
            "window_background": "#2D2D2D",
            "base_color": "#212121",
            "auxiliary_color": "#313131",
            "normal_color": "#717171",
            "secondary_color": "#FFFFFF",
            "accent_color": "#F0C54D",
        }

        if hasattr(app, "settings_manager"):
            colors["window_background"] = app.settings_manager.get_setting(
                "appearance.colors.window_background", colors["window_background"]
            )
            colors["base_color"] = app.settings_manager.get_setting(
                "appearance.colors.base_color", colors["base_color"]
            )
            colors["auxiliary_color"] = app.settings_manager.get_setting(
                "appearance.colors.auxiliary_color", colors["auxiliary_color"]
            )
            colors["normal_color"] = app.settings_manager.get_setting(
                "appearance.colors.normal_color", colors["normal_color"]
            )
            colors["secondary_color"] = app.settings_manager.get_setting(
                "appearance.colors.secondary_color", colors["secondary_color"]
            )
            colors["accent_color"] = app.settings_manager.get_setting(
                "appearance.colors.accent_color", colors["accent_color"]
            )

        return colors

    def _apply_scroll_area_theme(self, colors):
        """
        应用滚动区域主题
        """
        scaled_border_radius = int(8 * self.dpi_scale)
        scaled_border_width = int(1 * self.dpi_scale)
        scaled_padding = int(3 * self.dpi_scale)

        scrollbar_style = f"""
            QScrollArea {{
                border: {scaled_border_width}px solid {colors['normal_color']};
                border-radius: {scaled_border_radius}px;
                background-color: {colors['base_color']};
                padding: {scaled_padding}px;
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                width: 6px;
                background-color: {colors['auxiliary_color']};
                border: 0px solid transparent;
                border-radius: 0px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {colors['normal_color']};
                min-height: 15px;
                border-radius: 3px;
                border: none;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {colors['secondary_color']};
                border: none;
            }}
            QScrollBar::handle:vertical:pressed {{
                background-color: {colors['accent_color']};
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
                background-color: {colors['auxiliary_color']};
                border: 0px solid transparent;
                border-radius: 0px;
            }}
            QScrollBar::handle:horizontal {{
                background-color: {colors['normal_color']};
                min-width: 15px;
                border-radius: 3px;
                border: none;
            }}
            QScrollBar::handle:horizontal:hover {{
                background-color: {colors['secondary_color']};
                border: none;
            }}
            QScrollBar::handle:horizontal:pressed {{
                background-color: {colors['accent_color']};
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
        self.scroll_area.setStyleSheet(scrollbar_style)

        scrollbar = self.scroll_area.verticalScrollBar()
        if hasattr(scrollbar, "set_colors"):
            scrollbar.set_colors(
                colors["normal_color"],
                colors["secondary_color"],
                colors["accent_color"],
                colors["auxiliary_color"],
            )

    def update_theme(self):
        """
        增量刷新存储池主题，并重载卡片以确保横向卡片使用新配色
        """
        colors = self._get_theme_colors()

        self.setStyleSheet(f"background-color: {colors['window_background']};")
        self._apply_scroll_area_theme(colors)

        if hasattr(self, "stats_label") and self.stats_label:
            self.stats_label.setStyleSheet(f"color: {colors['secondary_color']};")
            self.stats_label.update()

        for button_name in ("import_export_btn", "export_btn", "clear_btn"):
            button = getattr(self, button_name, None)
            if button and hasattr(button, "update_theme"):
                try:
                    button.update_theme()
                except Exception:
                    pass

        if hasattr(self, "hover_tooltip") and self.hover_tooltip:
            try:
                self.hover_tooltip.update()
            except Exception:
                pass

        if self.items:
            self.reload_all_cards()

        self.update()

    def add_file(self, file_info):
        """
        添加文件或文件夹到临时存储池

        Args:
            file_info (dict): 文件或文件夹信息字典
        """
        file_path = os.path.normpath(file_info["path"])
        for item in self.items:
            if os.path.normpath(item["path"]) == file_path:
                return

        if "display_name" not in file_info:
            file_info["display_name"] = file_info["name"]
        if "original_name" not in file_info:
            file_info["original_name"] = file_info["name"]

        # 确保文件夹有 size_calculating 标记
        if file_info.get("is_dir") and "size_calculating" not in file_info:
            file_info["size_calculating"] = True

        self.items.append(file_info)

        card = CustomFileHorizontalCard(file_info["path"], display_name=file_info["display_name"])

        # 检查文件是否处于预览状态（使用normcase处理Windows路径大小写）
        if self.previewing_file_path and os.path.normcase(file_path) == os.path.normcase(self.previewing_file_path):
            card.set_previewing(True)

        # 设置文件信息用于拖拽
        card.set_file_info(file_info)

        card.clicked.connect(lambda path: self.on_card_clicked(path, card, file_info))
        card.doubleClicked.connect(lambda path: self.on_item_double_clicked(path))
        card.selectionChanged.connect(lambda selected, path: self.on_card_selection_changed(selected, path, file_info))
        card.renameRequested.connect(lambda path: self.on_card_rename_requested(path, file_info))
        card.deleteRequested.connect(lambda path: self.on_card_delete_requested(path, file_info))
        # 连接拖拽信号
        card.drag_started.connect(lambda fi: self.on_card_drag_started(fi))
        card.drag_ended.connect(lambda fi, target: self.on_card_drag_ended(fi, target))

        self.hover_tooltip.set_target_widget(card.card_container)

        if self.cards_layout.count() > 0 and self.cards_layout.itemAt(self.cards_layout.count() - 1).spacerItem():
            self.cards_layout.takeAt(self.cards_layout.count() - 1)

        self.cards_layout.addWidget(card)

        self.cards_layout.addStretch(1)

        self.cards.append((card, file_info))

        # 如果是文件夹，启动线程计算体积
        if file_info["is_dir"]:
            self._calculate_folder_size(file_info["path"])
        else:
            # 如果是图片或视频文件，异步生成缩略图
            thumbnail_manager = get_thumbnail_manager(self.dpi_scale)
            if thumbnail_manager.is_media_file(file_info["path"]):
                self._generate_thumbnail_async(file_info["path"], card)

        # 更新统计信息
        self.update_stats()

        # 实时保存备份（恢复阶段会被挂起，正常阶段会被防抖合并）
        self._save_backup_if_needed()

        # 发出信号通知文件选择器该文件已被添加到储存池
        self.file_added_to_pool.emit(file_info)

    def remove_file(self, file_path):
        """
        从临时存储池移除文件

        Args:
            file_path (str): 文件路径
        """
        file_path = os.path.normpath(file_path)
        for i, (card, file_info) in enumerate(self.cards):
            if os.path.normpath(file_info["path"]) == file_path:
                removed_file = file_info

                self.items.pop(i)

                self.cards_layout.removeWidget(card)
                card.deleteLater()

                self.cards.pop(i)

                self.remove_from_selector.emit(removed_file)
                break

        has_stretch = any(self.cards_layout.itemAt(i).spacerItem() for i in range(self.cards_layout.count()))
        if not has_stretch:
            self.cards_layout.addStretch(1)

        self.update_stats()

        self._save_backup_if_needed()

    def clear_all(self):
        """
        清空所有项目
        """
        # 确认对话框
        confirm_msg = CustomMessageBox(self)
        confirm_msg.set_title("确认清空")
        confirm_msg.set_text("确定要清空所有项目吗？")
        confirm_msg.set_buttons(["确定", "取消"], Qt.Horizontal, ["primary", "normal"])

        # 记录确认结果
        is_confirmed = False

        def on_confirm_clicked(button_index):
            nonlocal is_confirmed
            is_confirmed = (button_index == 0)  # 0表示确定按钮
            confirm_msg.close()

        confirm_msg.buttonClicked.connect(on_confirm_clicked)
        confirm_msg.exec()

        if is_confirmed:
            # 保存当前项目列表的副本，因为清空操作会修改原列表
            items_to_remove = self.items.copy()

            # 移除所有卡片，但保留拉伸因子
            while self.cards_layout.count() > 0:
                item = self.cards_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
                elif item.spacerItem():
                    # 保留拉伸因子，将其重新添加回布局
                    self.cards_layout.addItem(item)
                    break

            # 发出信号通知文件选择器取消所有选中
            for item in items_to_remove:
                self.remove_from_selector.emit(item)

            # 清空列表
            self.items.clear()
            self.cards.clear()
            # 更新统计信息
            self.update_stats()

            # 确保拉伸因子存在
            if not any(self.cards_layout.itemAt(i).spacerItem() for i in range(self.cards_layout.count())):
                self.cards_layout.addStretch(1)

            # 实时保存备份
            self._save_backup_if_needed()

    def reload_all_cards(self):
        """
        重载所有卡片
        清空当前所有卡片并重新创建，类似于应用启动时的初始化
        用于主题变更或需要完全刷新卡片显示的场景
        """
        if not self.items:
            return

        # 保存当前项目列表的副本
        items_to_reload = self.items.copy()

        # 清除预览状态
        self.previewing_file_path = None

        # 移除所有卡片（包括拉伸因子）
        while self.cards_layout.count() > 0:
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 清空卡片列表
        self.cards.clear()
        self.items.clear()

        # 重新添加所有文件（这会重新创建卡片）
        for file_info in items_to_reload:
            # 检查文件是否仍然存在
            if os.path.exists(file_info["path"]):
                self.add_file(file_info)

        # 更新统计信息
        self.update_stats()

        # 实时保存备份
        self._save_backup_if_needed()

    def _format_file_size(self, size_bytes):
        """
        将文件大小转换为自适应单位(B、KB、MB、GB、TB)

        Args:
            size_bytes (int): 文件大小，单位字节

        Returns:
            str: 格式化后的文件大小字符串
        """
        if size_bytes == 0:
            return "0 B"

        # 定义单位顺序和转换因子
        units = ["B", "KB", "MB", "GB", "TB"]
        index = 0
        size = float(size_bytes)

        # 转换到合适的单位
        while size >= 1024 and index < len(units) - 1:
            size /= 1024
            index += 1

        # 格式化输出，保留两位小数
        if index == 0:
            return f"{int(size)} {units[index]}"
        else:
            return f"{size:.2f} {units[index]}"

    def update_stats(self):
        """
        更新统计信息
        """
        total_items = len(self.items)

        # 计算所有文件大小总和
        total_size = 0
        calculating_count = 0
        for item in self.items:
            size_calc = item.get("size_calculating")
            if size_calc is True:
                calculating_count += 1
            elif "size" in item and item["size"] is not None:
                total_size += item["size"]

        formatted_size = self._format_file_size(total_size)

        if calculating_count > 0:
            self.stats_label.setText(f" {total_items}个条目 | {formatted_size} (正在计算{calculating_count}个文件夹...)")
        else:
            self.stats_label.setText(f" {total_items}个条目 | {formatted_size}")

    def on_card_clicked(self, path, card, file_info):
        """
        处理卡片点击事件

        Args:
            path: 文件路径
            card: 卡片对象
            file_info: 文件信息字典
        """
        # 发出左键点击信号，用于调用统一预览器
        self.item_left_clicked.emit(file_info)

    def on_card_selection_changed(self, selected, path, file_info):
        """
        处理卡片选中状态变化事件

        Args:
            selected: 是否选中
            path: 文件路径
            file_info: 文件信息字典
        """
        # 可以在这里添加选中状态变化后的处理逻辑
        pass

    def on_card_rename_requested(self, path, file_info):
        """
        处理卡片重命名请求

        Args:
            path: 文件路径
            file_info: 文件信息字典
        """
        self.rename_file(file_info, None)

    def on_card_delete_requested(self, path, file_info):
        """
        处理卡片删除请求

        Args:
            path: 文件路径
            file_info: 文件信息字典
        """
        self.remove_file(path)

    def on_item_double_clicked(self, path):
        """
        双击项目事件处理

        Args:
            path: 文件路径
        """
        for file_info in self.items:
            if file_info["path"] == path:
                self.item_left_clicked.emit(file_info)
                break

    def on_card_drag_started(self, file_info):
        """
        处理卡片拖拽开始事件

        Args:
            file_info (dict): 文件信息字典
        """
        pass

    def on_card_drag_ended(self, file_info, drop_target):
        """
        处理卡片拖拽结束事件

        Args:
            file_info (dict): 文件信息字典
            drop_target (str): 放置目标类型 ('file_selector', 'previewer', 'none')
        """
        import datetime
        from freeassetfilter.utils.app_logger import debug as logger_debug

        def debug(msg):
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            logger_debug(f"[{timestamp}] [FileStagingPool.on_card_drag_ended] {msg}")

        debug(f"拖拽结束，文件: {file_info.get('name', 'unknown')}, 目标: {drop_target}")

        if drop_target == 'file_selector':
            debug(f"拖拽到文件选择器，移除文件: {file_info.get('path', '')}")
            self.remove_file(file_info['path'])
        elif drop_target == 'previewer':
            debug(f"拖拽到预览器，触发预览: {file_info.get('path', '')}")
            self.item_left_clicked.emit(file_info)
        else:
            debug(f"未放置到有效区域")

    def rename_file(self, file_info, widget=None):
        """
        重命名文件（仅修改前端显示名称，保持原始后缀名）

        Args:
            file_info (dict): 文件信息字典
            widget (QWidget): 不再使用，保留参数以保持向后兼容
        """
        from freeassetfilter.widgets.D_widgets import CustomInputBox

        # 获取当前显示名称
        current_name = file_info["display_name"]

        # 分离文件名主体和后缀名
        if "." in current_name:
            # 有后缀名的情况
            name_parts = current_name.rsplit(".", 1)
            name_base = name_parts[0]
            name_ext = name_parts[1]
        else:
            # 没有后缀名的情况
            name_base = current_name
            name_ext = ""

        # 定义文件名非法字符
        illegal_chars = '<>:"/\\|?*' + ''.join([chr(c) for c in range(32)])

        while True:
            # 弹出自定义输入对话框，只显示和允许修改文件名主体
            input_box = CustomMessageBox(self)
            input_box.set_title("重命名")
            input_box.set_text("请输入新的文件名：")
            input_box.set_input(name_base)
            input_box.set_buttons(["确定", "取消"], Qt.Horizontal, ["primary", "normal"])

            # 连接按钮点击信号
            button_clicked = None

            def on_button_clicked(index):
                nonlocal button_clicked
                button_clicked = index
                input_box.close()

            input_box.buttonClicked.connect(on_button_clicked)
            input_box.exec()

            ok = button_clicked == 0
            new_name_input = input_box.get_input() if ok else ""

            if not ok:
                # 用户取消操作
                return

            if not new_name_input:
                # 文件名不能为空
                warning_msg = CustomMessageBox(self)
                warning_msg.set_title("错误")
                warning_msg.set_text("文件名不能为空！")
                warning_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                warning_msg.buttonClicked.connect(warning_msg.close)
                warning_msg.exec()
                continue

            if new_name_input == current_name:
                # 文件名未改变
                return

            # 检查是否包含非法字符
            if any(char in new_name_input for char in illegal_chars):
                warning_msg = CustomMessageBox(self)
                warning_msg.set_title("错误")
                warning_msg.set_text("文件名包含非法字符！请避免使用：< > : \" / \\ | ? * 以及控制字符")
                warning_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                warning_msg.buttonClicked.connect(warning_msg.close)
                warning_msg.exec()
                continue

            # 生成新的文件名
            if name_ext:
                new_name = f"{new_name_input}.{name_ext}"
            else:
                new_name = new_name_input

            # 检查路径长度
            MAX_PATH = 260
            estimated_total_length = len(new_name) + 150
            if estimated_total_length > MAX_PATH:
                warning_msg = CustomMessageBox(self)
                warning_msg.set_title("错误")
                warning_msg.set_text(f"文件名过长！加上路径后可能超过Windows系统的{MAX_PATH}字符限制。\n"
                                     f"当前估计总长度：{estimated_total_length}字符，建议缩短文件名。")
                warning_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                warning_msg.buttonClicked.connect(warning_msg.close)
                warning_msg.exec()
                continue

            # 更新文件信息中的显示名称
            file_info["display_name"] = new_name

            # 更新卡片的显示
            for card, card_file_info in self.cards:
                if card_file_info["path"] == file_info["path"]:
                    card_file_info["display_name"] = new_name
                    card.set_file_path(file_info["path"], display_name=new_name)
                    break

            # 实时保存备份
            self._save_backup_if_needed()
            break

    def open_file(self, file_info):
        """
        打开文件

        Args:
            file_info (dict): 文件信息
        """
        file_path = file_info["path"]
        if os.path.exists(file_path):
            if file_info["is_dir"]:
                pass
            else:
                os.startfile(file_path)

    def export_selected_files(self):
        """
        导出所有文件到指定目录
        显示导出模式选择弹窗，支持直接导出和分类导出
        """
        # 检查是否有文件可以导出
        if not self.items:
            info_msg = CustomMessageBox(self)
            info_msg.set_title("提示")
            info_msg.set_text("文件临时存储池中没有文件可以导出")
            info_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            info_msg.buttonClicked.connect(info_msg.close)
            info_msg.exec()
            return

        # 检查是否有文件正在计算体积
        calculating_count = 0
        for item in self.items:
            if item.get("size_calculating") is True:
                calculating_count += 1

        if calculating_count > 0:
            warning_msg = CustomMessageBox(self)
            warning_msg.set_title("数据未准备就绪")
            warning_msg.set_text(f"有 {calculating_count} 个文件夹正在计算体积，请等待计算完成后再导出。")
            warning_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            warning_msg.buttonClicked.connect(warning_msg.close)
            warning_msg.exec()
            return

        # 显示导出模式选择弹窗
        export_mode_msg = CustomMessageBox(self)
        export_mode_msg.set_title("选择导出方式")
        export_mode_msg.set_text("请选择导出模式：\n\n直接导出：所有文件平铺导出到目标目录\n分类导出：按照原始目录结构分类存储")
        export_mode_msg.set_buttons(
            ["直接导出", "分类导出", "取消"],
            Qt.Vertical,
            ["primary", "primary", "normal"]
        )

        export_mode = -1  # 0: 直接导出, 1: 分类导出, 2: 取消

        def on_export_mode_clicked(button_index):
            nonlocal export_mode
            export_mode = button_index
            export_mode_msg.close()

        export_mode_msg.buttonClicked.connect(on_export_mode_clicked)
        export_mode_msg.exec()

        if export_mode == 2 or export_mode == -1:
            return

        # 获取所有文件信息
        all_files = self.items

        # 获取默认导出文件路径作为初始目录
        initial_dir = ""
        if self.settings_manager:
            export_file_path = self.settings_manager.get_setting("file_staging.default_export_file_path", "")
            if export_file_path and os.path.isdir(export_file_path):
                initial_dir = export_file_path
            elif export_file_path and os.path.isfile(export_file_path):
                initial_dir = os.path.dirname(export_file_path)

        # 选择目标目录
        while True:
            target_dir = QFileDialog.getExistingDirectory(self, "选择导出目录", initial_dir if initial_dir else "")
            if not target_dir:
                return

            # 计算待导出文件的总大小
            total_file_size = self.calculate_total_file_size(all_files)

            # 获取目标目录的总容量和可用空间
            total_space, free_space = self.get_directory_space(target_dir)

            if total_space is None or free_space is None:
                warning_msg = CustomMessageBox(self)
                warning_msg.set_title("警告")
                warning_msg.set_text("无法获取目标目录的可用空间信息，可能是网络存储或远程目录。\n"
                                     "是否继续导出操作？")
                warning_msg.set_buttons(["继续", "重新选择", "取消"], Qt.Horizontal, ["primary", "normal", "normal"])

                user_choice = -1

                def on_button_clicked(button_index):
                    nonlocal user_choice
                    user_choice = button_index
                    warning_msg.close()

                warning_msg.buttonClicked.connect(on_button_clicked)
                warning_msg.exec()

                if user_choice == 0:
                    break
                elif user_choice == 1:
                    continue
                else:
                    return
            else:
                if free_space < total_file_size:
                    error_msg = CustomMessageBox(self)
                    error_msg.set_title("空间不足")
                    error_msg.set_text(f"目标目录可用空间不足！\n"
                                       f"待导出文件总大小：{self._format_file_size(total_file_size)}\n"
                                       f"目标目录可用空间：{self._format_file_size(free_space)}\n"
                                       f"所需额外空间：{self._format_file_size(total_file_size - free_space)}")
                    error_msg.set_buttons(["重新选择", "取消"], Qt.Horizontal, ["primary", "normal"])

                    user_choice = -1

                    def on_error_button_clicked(button_index):
                        nonlocal user_choice
                        user_choice = button_index
                        error_msg.close()

                    error_msg.buttonClicked.connect(on_error_button_clicked)
                    error_msg.exec()

                    if user_choice == 0:
                        continue
                    else:
                        return
                else:
                    break

        # 创建带进度条的自定义提示窗口
        progress_msg_box = CustomMessageBox(self)
        progress_msg_box.set_title("导出进度")
        progress_msg_box.set_text("正在导出文件，请稍候...")

        # 创建并配置进度条
        export_progress_bar = D_ProgressBar()
        export_progress_bar.setInteractive(False)
        export_progress_bar.setRange(0, len(all_files))
        export_progress_bar.setValue(0)

        progress_msg_box.set_progress(export_progress_bar)
        progress_msg_box.set_buttons(["取消"], Qt.Horizontal, ["normal"])

        # 保存引用以便在进度更新和完成时访问
        self.current_progress_msg_box = progress_msg_box
        self.current_export_progress_bar = export_progress_bar

        # 连接进度更新信号到新的进度条
        self.update_progress.connect(self.on_update_export_progress)

        # 根据导出模式执行相应的复制操作
        if export_mode == 0:
            self.copy_files(all_files, target_dir)
            progress_msg_box.exec()
        else:
            def on_categorized_confirm(folder_name_mapping):
                self.copy_files_categorized(all_files, target_dir, folder_name_mapping)
                progress_msg_box.exec()

            def on_categorized_cancel():
                self.export_selected_files()

            self._show_categorized_export_dialog(
                all_files,
                target_dir,
                on_categorized_confirm,
                on_categorized_cancel
            )

    def on_update_progress(self, value):
        """
        更新进度条

        Args:
            value (int): 进度值
        """
        self.progress_bar.setValue(value)

    def on_update_export_progress(self, value):
        """
        更新导出提示框中的进度条

        Args:
            value (int): 进度值
        """
        if hasattr(self, 'current_export_progress_bar'):
            self.current_export_progress_bar.setValue(value)

    def on_export_finished(self, success_count, error_count, errors):
        """
        处理导出完成

        Args:
            success_count (int): 成功导出的文件数
            error_count (int): 失败的文件数
            errors (list): 错误信息列表
        """
        # 断开进度更新信号的连接
        self.update_progress.disconnect(self.on_update_export_progress)

        # 关闭进度提示窗口
        if hasattr(self, 'current_progress_msg_box'):
            self.current_progress_msg_box.close()
            delattr(self, 'current_progress_msg_box')
            delattr(self, 'current_export_progress_bar')

        # 显示导出结果
        result_msg = CustomMessageBox(self)
        if error_count == 0:
            result_msg.set_title("导出完成")
            result_msg.set_text(f"成功导出 {success_count} 个文件")
        else:
            result_msg.set_title("导出结果")
            error_msg = f"成功导出 {success_count} 个文件，失败 {error_count} 个文件\n\n失败详情：\n" + "\n".join(errors[:5])
            if len(errors) > 5:
                error_msg += f"\n\n还有 {len(errors) - 5} 个错误未显示"
            result_msg.set_text(error_msg)
        result_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
        result_msg.buttonClicked.connect(result_msg.close)
        result_msg.exec()

    def on_folder_size_calculated(self, file_info):
        """
        处理文件夹体积计算完成信号

        Args:
            file_info (dict): 计算完成的文件夹信息
        """
        # 更新UI显示
        self.update_stats()

        # 更新卡片显示
        for card, card_file_info in self.cards:
            if card_file_info["path"] == file_info["path"]:
                card.set_file_path(file_info["path"], display_name=file_info["display_name"])
                break

        # 防抖保存
        self._save_backup_if_needed()

    def eventFilter(self, obj, event):
        """
        事件过滤器，用于处理鼠标进入和离开事件

        Args:
            obj (QObject): 事件对象
            event (QEvent): 事件类型

        Returns:
            bool: 是否处理了事件
        """
        if event.type() == event.Enter:
            if hasattr(obj, 'delete_btn'):
                obj.delete_btn.setVisible(True)
            if hasattr(obj, 'rename_btn'):
                obj.rename_btn.setVisible(True)
        elif event.type() == event.Leave:
            if hasattr(obj, 'delete_btn'):
                obj.delete_btn.setVisible(False)
            if hasattr(obj, 'rename_btn'):
                obj.rename_btn.setVisible(False)
        return super().eventFilter(obj, event)

    def save_backup(self, last_path='All'):
        """
        保存当前文件列表到备份文件

        Args:
            last_path (str): 文件选择器的当前路径
        """
        import json
        try:
            # 构建备份数据，包含文件列表和选择器状态
            backup_data = {
                'items': self.items,
                'selector_state': {
                    'last_path': last_path
                }
            }
            with open(self.backup_file, 'w', encoding='utf-8') as f:
                json.dump(backup_data, f, ensure_ascii=False, indent=2)
            debug(f"[DEBUG] 保存备份成功，路径: {self.backup_file}, 项目数: {len(self.items)}, 最后路径: {last_path}")
        except (IOError, OSError) as e:
            warning(f"保存文件列表备份失败: {e}")

    def show_import_export_dialog(self):
        """
        显示导入/导出数据对话框
        """
        # 使用自定义提示窗口实现导入/导出选择
        msg_box = CustomMessageBox(self)
        msg_box.set_title("导入/导出数据")
        msg_box.set_text("请选择操作:")

        # 设置按钮，使用垂直排列，导入和导出使用强调样式
        msg_box.set_buttons(["导入数据", "导出数据", "取消"], Qt.Vertical, ["primary", "primary", "normal"])

        # 记录用户选择
        user_choice = -1

        def on_button_clicked(button_index):
            nonlocal user_choice
            user_choice = button_index
            msg_box.close()

        msg_box.buttonClicked.connect(on_button_clicked)
        msg_box.exec()

        # 根据用户选择执行相应操作
        if user_choice == 0:
            from PySide6.QtWidgets import QDialog
            temp_dialog = QDialog(self)
            self.import_data(temp_dialog)
        elif user_choice == 1:
            from PySide6.QtWidgets import QDialog
            temp_dialog = QDialog(self)
            self.export_data(temp_dialog)

    def import_data(self, dialog):
        """
        导入数据功能

        Args:
            dialog (QDialog): 父对话框
        """
        from PySide6.QtWidgets import QFileDialog
        import json

        # 获取默认导出数据路径作为初始目录
        initial_dir = ""
        if self.settings_manager:
            export_data_path = self.settings_manager.get_setting("file_staging.default_export_data_path", "")
            if export_data_path and os.path.isdir(export_data_path):
                initial_dir = export_data_path
            elif export_data_path and os.path.isfile(export_data_path):
                initial_dir = os.path.dirname(export_data_path)

        # 打开文件选择对话框，选择JSON文件
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择导入文件", initial_dir, "JSON文件 (*.json)"
        )

        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    import_data = json.load(f)

                if not isinstance(import_data, list):
                    warning_msg = CustomMessageBox(self)
                    warning_msg.set_title("导入失败")
                    warning_msg.set_text("文件格式不正确，应为JSON数组格式")
                    warning_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                    warning_msg.buttonClicked.connect(warning_msg.close)
                    warning_msg.exec()
                    return

                # 询问用户是否要清空现有数据
                confirm_msg = CustomMessageBox(self)
                confirm_msg.set_title("确认导入")
                confirm_msg.set_text(f"即将导入 {len(import_data)} 个文件，是否要清空现有数据？")
                confirm_msg.set_buttons(["确定", "取消"], Qt.Horizontal, ["primary", "normal"])

                # 记录确认结果
                is_confirmed = False

                def on_confirm_clicked(button_index):
                    nonlocal is_confirmed
                    is_confirmed = (button_index == 0)
                    confirm_msg.close()

                confirm_msg.buttonClicked.connect(on_confirm_clicked)
                confirm_msg.exec()

                if is_confirmed:
                    # 清空现有数据
                    self.clear_all_without_confirmation()

                # 导入数据并检查文件是否存在
                success_count = 0
                unlinked_files = []

                for file_info in import_data:
                    if isinstance(file_info, dict) and "path" in file_info and "name" in file_info:
                        if os.path.exists(file_info["path"]):
                            self.add_file(file_info)
                            success_count += 1
                        else:
                            unlinked_files.append({
                                "original_file_info": file_info,
                                "status": "unlinked",
                                "new_path": None,
                                "md5": self.calculate_md5(file_info["path"]) if os.path.exists(file_info["path"]) else None
                            })

                # 如果有未链接文件，显示处理对话框
                if unlinked_files:
                    self.show_unlinked_files_dialog(unlinked_files)

                # 显示导入结果
                info_msg = CustomMessageBox(self)
                info_msg.set_title("导入完成")
                info_msg.set_text(f"成功导入 {success_count} 个文件，{len(unlinked_files)} 个文件需要手动链接")
                info_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                info_msg.buttonClicked.connect(info_msg.close)
                info_msg.exec()

                dialog.accept()
            except json.JSONDecodeError as e:
                warning(f"JSON解码错误: {e}")
                warning_msg = CustomMessageBox(self)
                warning_msg.set_title("导入失败")
                warning_msg.set_text("JSON文件格式不正确")
                warning_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                warning_msg.buttonClicked.connect(warning_msg.close)
                warning_msg.exec()
            except (IOError, OSError) as e:
                warning(f"导入数据时文件操作失败: {e}")
                warning_msg = CustomMessageBox(self)
                warning_msg.set_title("导入失败")
                warning_msg.set_text(f"文件读取失败: {str(e)}")
                warning_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                warning_msg.buttonClicked.connect(warning_msg.close)
                warning_msg.exec()

    def calculate_md5(self, file_path):
        """
        计算文件的MD5值

        Args:
            file_path (str): 文件路径

        Returns:
            str: 文件的MD5值，如果文件不存在则返回None
        """
        import hashlib
        try:
            if not os.path.exists(file_path):
                return None

            hash_md5 = hashlib.md5()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except (IOError, OSError, PermissionError) as e:
            warning(f"计算MD5失败: {e}")
            return None

    def show_unlinked_files_dialog(self, unlinked_files):
        """
        显示未链接文件处理对话框

        Args:
            unlinked_files (list): 未链接文件列表
        """
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
            QListWidget, QListWidgetItem, QMenu, QAction,
            QFileDialog, QLabel, QGridLayout
        )

        # 创建对话框
        dialog = QDialog(self)
        dialog.setWindowTitle("处理未链接文件")
        dialog.setMinimumSize(600, 400)

        # 创建布局
        main_layout = QVBoxLayout(dialog)

        # 添加标题
        title_label = QLabel(f"有 {len(unlinked_files)} 个文件需要手动链接:")
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)

        # 创建未链接文件列表
        self.unlinked_list_widget = QListWidget()
        self.unlinked_list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.unlinked_list_widget.customContextMenuRequested.connect(lambda pos: self.show_unlinked_context_menu(pos, unlinked_files))

        # 添加未链接文件到列表
        for i, file_item in enumerate(unlinked_files):
            list_item = QListWidgetItem()
            file_info = file_item["original_file_info"]
            display_text = f"{file_info['name']} - {file_info['path']} ({file_item['status']})"
            list_item.setText(display_text)
            list_item.setData(Qt.UserRole, i)
            self.unlinked_list_widget.addItem(list_item)

        main_layout.addWidget(self.unlinked_list_widget)

        # 创建按钮布局
        button_layout = QHBoxLayout()

        # 手动链接按钮
        manual_link_btn = CustomButton("手动链接", button_type="normal")
        manual_link_btn.clicked.connect(lambda: self.manual_link_files(unlinked_files, self.unlinked_list_widget))
        button_layout.addWidget(manual_link_btn)

        # 忽略所有按钮
        ignore_all_btn = CustomButton("忽略所有", button_type="normal")
        ignore_all_btn.clicked.connect(lambda: self.ignore_all_files(unlinked_files))
        button_layout.addWidget(ignore_all_btn)

        # 完成按钮
        finish_btn = CustomButton("完成", button_type="primary")
        finish_btn.clicked.connect(lambda: self.finish_unlinked_files_dialog(dialog, unlinked_files))
        button_layout.addWidget(finish_btn)

        main_layout.addLayout(button_layout)

        # 显示对话框
        dialog.exec()

        # 处理已链接的文件
        for file_item in unlinked_files:
            if file_item["status"] == "linked" and file_item["new_path"]:
                new_file_info = file_item["original_file_info"].copy()
                new_file_info["path"] = file_item["new_path"]
                new_file_info["name"] = os.path.basename(file_item["new_path"])
                self.add_file(new_file_info)

    def show_unlinked_context_menu(self, pos, unlinked_files):
        """
        显示未链接文件的右键菜单

        Args:
            pos (QPoint): 鼠标位置
            unlinked_files (list): 未链接文件列表
        """
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QAction

        # 获取当前选中的项
        selected_items = self.unlinked_list_widget.selectedItems()
        if not selected_items:
            return

        # 创建菜单
        menu = QMenu()

        # 忽略此项
        ignore_action = menu.addAction("忽略此项")
        ignore_action.triggered.connect(lambda: self.ignore_selected_files(unlinked_files, selected_items))

        # 手动链接此项
        link_action = menu.addAction("手动链接此文件")
        link_action.triggered.connect(lambda: self.manual_link_selected_files(unlinked_files, selected_items))

        # 显示菜单
        menu.exec_(self.unlinked_list_widget.mapToGlobal(pos))

    def manual_link_files(self, unlinked_files, list_widget):
        """
        手动链接文件

        Args:
            unlinked_files (list): 未链接文件列表
            list_widget (QListWidget): 列表控件
        """
        from PySide6.QtWidgets import QFileDialog

        # 选择一个目录
        dir_path = QFileDialog.getExistingDirectory(self, "选择文件目录")
        if not dir_path:
            return

        # 遍历目录下所有文件
        matched_count = 0
        for root, dirs, files in os.walk(dir_path):
            for file in files:
                file_path = os.path.join(root, file)
                file_md5 = self.calculate_md5(file_path)

                # 查找匹配的未链接文件
                for file_item in unlinked_files:
                    if file_item["status"] == "unlinked":
                        original_file_info = file_item["original_file_info"]
                        original_name = original_file_info["name"]
                        original_md5 = self.calculate_md5(original_file_info["path"])

                        # 优先匹配MD5
                        if file_md5 and original_md5 and file_md5 == original_md5:
                            file_item["status"] = "linked"
                            file_item["new_path"] = file_path
                            matched_count += 1
                            break
                        # 其次匹配文件名
                        elif file == original_name:
                            confirm_msg = CustomMessageBox(self)
                            confirm_msg.set_title("文件名匹配")
                            confirm_msg.set_text(f"找到文件名匹配的文件，但MD5不匹配。\n"
                                                 f"原始文件: {original_name}\n"
                                                 f"找到文件: {file_path}\n"
                                                 f"是否接受仅文件名匹配？")
                            confirm_msg.set_buttons(["确定", "取消"], Qt.Horizontal, ["primary", "normal"])

                            # 记录确认结果
                            is_confirmed = False

                            def on_confirm_clicked(button_index):
                                nonlocal is_confirmed
                                is_confirmed = (button_index == 0)
                                confirm_msg.close()

                            confirm_msg.buttonClicked.connect(on_confirm_clicked)
                            confirm_msg.exec()

                            if is_confirmed:
                                file_item["status"] = "linked"
                                file_item["new_path"] = file_path
                                matched_count += 1
                                break

        # 更新列表显示
        self.update_unlinked_list(unlinked_files)

        info_msg = CustomMessageBox(self)
        info_msg.set_title("匹配完成")
        info_msg.set_text(f"成功匹配 {matched_count} 个文件")
        info_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
        info_msg.buttonClicked.connect(info_msg.close)
        info_msg.exec()

    def manual_link_selected_files(self, unlinked_files, selected_items):
        """
        手动链接选中的文件

        Args:
            unlinked_files (list): 未链接文件列表
            selected_items (list): 选中的列表项
        """
        from PySide6.QtWidgets import QFileDialog

        for item in selected_items:
            index = item.data(Qt.UserRole)
            file_item = unlinked_files[index]

            if file_item["status"] == "unlinked":
                # 让用户选择文件
                file_path, _ = QFileDialog.getOpenFileName(
                    self, "选择文件", "", "所有文件 (*.*)"
                )

                if file_path:
                    # 检查文件名是否匹配
                    original_name = file_item["original_file_info"]["name"]
                    new_name = os.path.basename(file_path)

                    if original_name != new_name:
                        confirm_msg = CustomMessageBox(self)
                        confirm_msg.set_title("文件名不匹配")
                        confirm_msg.set_text(f"选中文件的文件名与原始文件不同。\n"
                                             f"原始文件名: {original_name}\n"
                                             f"选中文件名: {new_name}\n"
                                             f"是否继续？")
                        confirm_msg.set_buttons(["确定", "取消"], Qt.Horizontal, ["primary", "normal"])

                        # 记录确认结果
                        is_confirmed = False

                        def on_confirm_clicked(button_index):
                            nonlocal is_confirmed
                            is_confirmed = (button_index == 0)
                            confirm_msg.close()

                        confirm_msg.buttonClicked.connect(on_confirm_clicked)
                        confirm_msg.exec()

                        if not is_confirmed:
                            continue

                    # 更新文件状态
                    file_item["status"] = "linked"
                    file_item["new_path"] = file_path

        # 更新列表显示
        self.update_unlinked_list(unlinked_files)

    def ignore_selected_files(self, unlinked_files, selected_items):
        """
        忽略选中的文件

        Args:
            unlinked_files (list): 未链接文件列表
            selected_items (list): 选中的列表项
        """
        for item in selected_items:
            index = item.data(Qt.UserRole)
            file_item = unlinked_files[index]
            file_item["status"] = "ignored"

        # 更新列表显示
        self.update_unlinked_list(unlinked_files)

    def ignore_all_files(self, unlinked_files):
        """
        忽略所有未链接文件

        Args:
            unlinked_files (list): 未链接文件列表
        """
        confirm_msg = CustomMessageBox(self)
        confirm_msg.set_title("确认忽略所有")
        confirm_msg.set_text("确定要忽略所有未链接的文件吗？")
        confirm_msg.set_buttons(["确定", "取消"], Qt.Horizontal, ["primary", "normal"])

        # 记录确认结果
        is_confirmed = False

        def on_confirm_clicked(button_index):
            nonlocal is_confirmed
            is_confirmed = (button_index == 0)
            confirm_msg.close()

        confirm_msg.buttonClicked.connect(on_confirm_clicked)
        confirm_msg.exec()

        if is_confirmed:
            for file_item in unlinked_files:
                file_item["status"] = "ignored"

            # 更新列表显示
            self.update_unlinked_list(unlinked_files)

    def update_unlinked_list(self, unlinked_files):
        """
        更新未链接文件列表显示

        Args:
            unlinked_files (list): 未链接文件列表
        """
        self.unlinked_list_widget.clear()

        for i, file_item in enumerate(unlinked_files):
            list_item = QListWidgetItem()
            file_info = file_item["original_file_info"]
            display_text = f"{file_info['name']} - {file_info['path']} ({file_item['status']})"
            list_item.setText(display_text)
            list_item.setData(Qt.UserRole, i)
            self.unlinked_list_widget.addItem(list_item)

    def finish_unlinked_files_dialog(self, dialog, unlinked_files):
        """
        完成未链接文件处理

        Args:
            dialog (QDialog): 对话框实例
            unlinked_files (list): 未链接文件列表
        """
        # 检查是否还有未处理的文件
        has_unlinked = any(item["status"] == "unlinked" for item in unlinked_files)

        if has_unlinked:
            confirm_msg = CustomMessageBox(self)
            confirm_msg.set_title("还有未处理文件")
            confirm_msg.set_text("还有未链接的文件，确定要完成吗？未处理的文件将被忽略。")
            confirm_msg.set_buttons(["确定", "取消"], Qt.Horizontal, ["primary", "normal"])

            # 记录确认结果
            is_confirmed = False

            def on_confirm_clicked(button_index):
                nonlocal is_confirmed
                is_confirmed = (button_index == 0)
                confirm_msg.close()

            confirm_msg.buttonClicked.connect(on_confirm_clicked)
            confirm_msg.exec()

            if is_confirmed:
                # 忽略所有未处理的文件
                for file_item in unlinked_files:
                    if file_item["status"] == "unlinked":
                        file_item["status"] = "ignored"
                dialog.accept()
        else:
            dialog.accept()

    def export_data(self, dialog):
        """
        导出数据功能

        Args:
            dialog (QDialog): 父对话框
        """
        from PySide6.QtWidgets import QFileDialog
        import json

        # 检查是否有数据可导出
        if not self.items:
            info_msg = CustomMessageBox(self)
            info_msg.set_title("导出提示")
            info_msg.set_text("文件存储池中没有数据可以导出")
            info_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            info_msg.buttonClicked.connect(info_msg.close)
            info_msg.exec()
            return

        # 生成带时间戳的默认文件名
        from datetime import datetime
        current_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        default_filename = f"FAF_{current_time}.json"

        # 获取默认导出数据路径作为初始目录
        initial_dir = ""
        if self.settings_manager:
            export_data_path = self.settings_manager.get_setting("file_staging.default_export_data_path", "")
            if export_data_path and os.path.isdir(export_data_path):
                initial_dir = export_data_path
            elif export_data_path and os.path.isfile(export_data_path):
                initial_dir = os.path.dirname(export_data_path)

        # 打开文件保存对话框，选择保存路径
        if initial_dir:
            default_path = os.path.join(initial_dir, default_filename)
        else:
            default_path = default_filename
        file_path, _ = QFileDialog.getSaveFileName(
            self, "选择导出文件", default_path, "JSON文件 (*.json)"
        )

        if file_path:
            try:
                # 导出数据到JSON文件
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(self.items, f, ensure_ascii=False, indent=2)

                info_msg = CustomMessageBox(self)
                info_msg.set_title("导出成功")
                info_msg.set_text(f"成功导出 {len(self.items)} 个文件的数据到 {file_path}")
                info_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                info_msg.buttonClicked.connect(lambda: [info_msg.close(), dialog.accept()])
                info_msg.exec()

                dialog.accept()
            except (IOError, OSError, PermissionError) as e:
                warning(f"导出数据失败: {e}")
                warning_msg = CustomMessageBox(self)
                warning_msg.set_title("导出失败")
                warning_msg.set_text(f"文件写入失败: {str(e)}")
                warning_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                warning_msg.buttonClicked.connect(warning_msg.close)
                warning_msg.exec()

    def clear_all_without_confirmation(self):
        """
        不显示确认对话框，直接清空所有项目
        """
        # 保存当前项目列表的副本，因为清空操作会修改原列表
        items_to_remove = self.items.copy()

        # 移除所有卡片，但保留拉伸因子
        while self.cards_layout.count() > 0:
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.spacerItem():
                # 保留拉伸因子，将其重新添加回布局
                self.cards_layout.addItem(item)
                break

        # 发出信号通知文件选择器取消所有选中
        for item in items_to_remove:
            self.remove_from_selector.emit(item)

        self.items.clear()
        self.cards.clear()
        self.update_stats()

        if not any(self.cards_layout.itemAt(i).spacerItem() for i in range(self.cards_layout.count())):
            self.cards_layout.addStretch(1)

        self._save_backup_if_needed()

    def dragEnterEvent(self, event):
        """
        处理拖拽进入事件

        Args:
            event (QDragEnterEvent): 拖拽进入事件
        """
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet(f"background-color: #e8f4fc; border: 2px dashed #4a7abc; border-radius: {int(8 * self.dpi_scale)}px;")

    def dragMoveEvent(self, event):
        """
        处理拖拽移动事件

        Args:
            event (QDragMoveEvent): 拖拽移动事件
        """
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        """
        处理拖拽离开事件

        Args:
            event (QDragLeaveEvent): 拖拽离开事件
        """
        self.setStyleSheet("background-color: #ffffff;")

    def dropEvent(self, event):
        """
        处理拖拽释放事件

        Args:
            event (QDropEvent): 拖拽释放事件
        """
        self.setStyleSheet("background-color: #ffffff;")

        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()

            # 处理每个拖拽的文件/文件夹
            for url in urls:
                file_path = url.toLocalFile()

                if os.path.exists(file_path):
                    self._add_dropped_item(file_path)

            event.acceptProposedAction()

    def _add_dropped_item(self, file_path):
        """
        添加拖拽的文件或文件夹到储存池

        Args:
            file_path (str): 文件或文件夹路径
        """
        if os.path.isfile(file_path):
            file_info = self._get_file_info(file_path)
            if file_info:
                file_dir = os.path.dirname(file_path)
                self.navigate_to_path.emit(file_dir, file_info)
        elif os.path.isdir(file_path):
            file_info = self._get_file_info(file_path)
            if file_info:
                self.navigate_to_path.emit(file_path, file_info)

    def _get_file_info(self, file_path):
        """
        获取文件或文件夹信息

        Args:
            file_path (str): 文件或文件夹路径

        Returns:
            dict: 文件或文件夹信息字典
        """
        from datetime import datetime
        try:
            file_stat = os.stat(file_path)
            file_name = os.path.basename(file_path)
            is_dir = os.path.isdir(file_path)

            # 获取文件后缀（不带点号）
            suffix = ""
            if not is_dir:
                ext = os.path.splitext(file_name)[1].lower()
                suffix = ext[1:] if ext.startswith('.') else ext

            file_info = {
                "name": file_name,
                "path": file_path,
                "is_dir": is_dir,
                "size": None if is_dir else file_stat.st_size,
                "size_calculating": True if is_dir else False,
                "modified": datetime.fromtimestamp(file_stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "created": datetime.fromtimestamp(file_stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
                "suffix": suffix,
                "display_name": file_name,
                "original_name": file_name
            }

            return file_info
        except (OSError, PermissionError, FileNotFoundError) as e:
            warning(f"获取文件/文件夹信息失败: {e}")
            return None

    def _add_folder_contents(self, folder_path):
        """
        递归添加文件夹中的所有文件到储存池

        Args:
            folder_path (str): 文件夹路径
        """
        try:
            for root, dirs, files in os.walk(folder_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    file_info = self._get_file_info(file_path)
                    if file_info:
                        self.add_file(file_info)
        except (OSError, PermissionError) as e:
            warning(f"添加文件夹内容失败: {e}")
        self.items.clear()
        self.cards.clear()
        self.update_stats()

        if not any(self.cards_layout.itemAt(i).spacerItem() for i in range(self.cards_layout.count())):
            self.cards_layout.addStretch(1)

        self._save_backup_if_needed()

    def load_backup(self):
        """
        从备份文件加载文件列表

        Returns:
            list: 加载的文件列表，如果没有备份则返回空列表
        """
        import json
        try:
            if os.path.exists(self.backup_file):
                with open(self.backup_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except json.JSONDecodeError as e:
            warning(f"备份文件JSON格式错误: {e}")
        except (IOError, OSError) as e:
            warning(f"加载文件列表备份失败: {e}")
        return []

    def get_directory_space(self, directory):
        """
        获取目录所在磁盘的总容量和可用空间

        Args:
            directory (str): 目录路径

        Returns:
            tuple: (总容量字节数, 可用空间字节数)，如果获取失败返回(None, None)
        """
        try:
            if sys.platform == "win32":
                # Windows系统
                import ctypes
                free_bytes = ctypes.c_ulonglong(0)
                total_bytes = ctypes.c_ulonglong(0)
                # 调用Windows API获取磁盘空间
                ctypes.windll.kernel32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(directory), None, ctypes.byref(total_bytes), ctypes.byref(free_bytes))
                return total_bytes.value, free_bytes.value
            else:
                # Linux/macOS系统
                statvfs = os.statvfs(directory)
                total_bytes = statvfs.f_frsize * statvfs.f_blocks
                free_bytes = statvfs.f_frsize * statvfs.f_bavail
                return total_bytes, free_bytes
        except (OSError, PermissionError, FileNotFoundError) as e:
            warning(f"获取目录空间失败: {e}")
            return None, None

    def _calculate_folder_size(self, folder_path):
        """
        计算文件夹体积的线程函数
        使用 QThread 替代 Python 原生 threading，确保与 PyQt 的线程安全兼容

        Args:
            folder_path (str): 文件夹路径
        """
        # 清理已完成的线程
        self._cleanup_finished_calculators()

        # 创建并启动文件夹大小计算线程
        calculator = FolderSizeCalculator(folder_path, self.items, self)
        calculator.folder_size_calculated.connect(self._on_folder_size_calculated)

        # 跟踪活动线程
        self._active_size_calculators.append(calculator)

        # 线程完成时自动清理
        calculator.finished.connect(lambda: self._cleanup_finished_calculators())

        calculator.start()

    def _cleanup_finished_calculators(self):
        """
        清理已完成的计算线程
        从活动线程列表中移除已经完成的线程
        """
        self._active_size_calculators = [
            calc for calc in self._active_size_calculators
            if calc.isRunning()
        ]

    def stop_all_size_calculators(self):
        """
        停止所有活动的文件夹大小计算线程
        在组件销毁或程序退出时调用
        """
        for calculator in self._active_size_calculators:
            if calculator.isRunning():
                calculator.cancel()
                calculator.wait(500)
        self._active_size_calculators.clear()

    def _on_folder_size_calculated(self, result):
        """
        处理文件夹大小计算完成的回调

        Args:
            result (dict): 包含 folder_path 和 total_size 的字典
        """
        folder_path = result.get("path")
        total_size = result.get("size")

        try:
            for file_info in self.items:
                if file_info["path"] == folder_path:
                    file_info["size"] = total_size
                    file_info["size_calculating"] = False
                    self.folder_size_calculated.emit(file_info)
                    break
        except RuntimeError:
            pass

    def _get_thumbnail_path(self, file_path):
        """获取文件的缩略图路径

        使用缩略图管理器统一管理
        """
        thumbnail_manager = get_thumbnail_manager(self.dpi_scale)
        return thumbnail_manager.get_thumbnail_path(file_path)

    def _generate_thumbnail_async(self, file_path, card=None):
        """异步生成缩略图

        Args:
            file_path (str): 文件路径
            card (CustomFileHorizontalCard, optional): 对应的卡片对象，缩略图生成完成后会刷新该卡片
        """
        from PySide6.QtCore import QThreadPool, QRunnable

        # 获取缩略图管理器
        thumbnail_manager = get_thumbnail_manager(self.dpi_scale)

        class ThumbnailGenerator(QObject, QRunnable):
            """缩略图生成器，使用信号机制替代回调函数以确保线程安全"""
            thumbnail_ready = Signal(str, str, object)

            def __init__(self, thumbnail_manager, file_path, card):
                super().__init__()
                self.thumbnail_manager = thumbnail_manager
                self.file_path = file_path
                self.card = card

            def run(self):
                result_path = self.thumbnail_manager.create_thumbnail(self.file_path)
                if result_path:
                    self.thumbnail_ready.emit(result_path, self.file_path, self.card)

        generator = ThumbnailGenerator(thumbnail_manager, file_path, card)
        generator.thumbnail_ready.connect(
            self._on_thumbnail_ready,
            Qt.QueuedConnection
        )
        QThreadPool.globalInstance().start(generator)

    def _get_file_selector(self):
        """获取文件选择器组件"""
        try:
            parent = self.parent()
            while parent:
                if hasattr(parent, 'file_selector_a'):
                    return parent.file_selector_a
                parent = parent.parent()
        except Exception as e:
            error(f"获取文件选择器失败: {e}")
        return None

    def _refresh_selector_card(self, file_path):
        """刷新文件选择器中指定文件的卡片缩略图"""
        try:
            file_selector = self._get_file_selector()
            if not file_selector:
                return

            normalized_target = os.path.normpath(file_path)

            if hasattr(file_selector, '_refresh_visible_card_thumbnail'):
                file_selector._refresh_visible_card_thumbnail(normalized_target)
                return

            if hasattr(file_selector, '_find_visible_card_by_path'):
                widget = file_selector._find_visible_card_by_path(normalized_target)
                if widget and hasattr(widget, 'refresh_thumbnail'):
                    widget.refresh_thumbnail()
                    return
        except Exception as e:
            error(f"刷新文件选择器单个卡片缩略图失败: {e}")

    def _on_thumbnail_ready(self, thumb_path, file_path, card):
        """缩略图生成完成的回调函数

        Args:
            thumb_path (str): 缩略图路径
            file_path (str): 原文件路径
            card (CustomFileHorizontalCard): 需要刷新的卡片对象
        """
        debug(f"[FileStagingPool] 缩略图生成完成: {thumb_path}")
        if card and hasattr(card, 'refresh_thumbnail'):
            from PySide6.QtCore import QMetaObject, Qt
            QMetaObject.invokeMethod(
                card,
                "refresh_thumbnail",
                Qt.QueuedConnection
            )
            debug(f"[FileStagingPool] 已触发存储池卡片缩略图刷新")

        self._refresh_selector_card(file_path)

    def calculate_total_file_size(self, files):
        """
        计算待导出文件的总大小

        Args:
            files (list): 文件信息列表

        Returns:
            int: 总大小字节数
        """
        import time

        total_size = 0
        calculating_folders = []

        for file_info in files:
            if file_info.get("size_calculating") is True:
                calculating_folders.append(file_info["path"])
            elif "size" in file_info and file_info["size"] is not None:
                total_size += file_info["size"]
            else:
                # 如果没有size信息，尝试获取
                try:
                    if os.path.isfile(file_info["path"]):
                        file_size = os.path.getsize(file_info["path"])
                        total_size += file_size
                    elif os.path.isdir(file_info["path"]):
                        calculating_folders.append(file_info["path"])
                except (OSError, PermissionError, FileNotFoundError) as e:
                    warning(f"计算文件大小失败: {e}")

        # 等待正在计算中的文件夹
        max_wait_time = 30
        wait_interval = 0.5
        elapsed_time = 0

        while calculating_folders and elapsed_time < max_wait_time:
            time.sleep(wait_interval)
            elapsed_time += wait_interval

            still_calculating = []
            for folder_path in calculating_folders:
                for item in self.items:
                    if item["path"] == folder_path:
                        if item.get("size_calculating") is True:
                            still_calculating.append(folder_path)
                        elif item.get("size") is not None:
                            total_size += item["size"]
                        break
                else:
                    try:
                        if os.path.isdir(folder_path):
                            folder_size = 0
                            for root, dirs, files_in_dir in os.walk(folder_path):
                                for file in files_in_dir:
                                    file_path = os.path.join(root, file)
                                    folder_size += os.path.getsize(file_path)
                            total_size += folder_size
                    except (OSError, PermissionError, FileNotFoundError) as e:
                        warning(f"同步计算文件夹大小时失败: {e}")

            calculating_folders = still_calculating

        if calculating_folders:
            warning(f"警告: {len(calculating_folders)}个文件夹体积计算超时，这些文件夹大小将被忽略")

        return total_size

    def copy_files(self, files, target_dir):
        """
        复制文件到目标目录（直接导出模式）

        Args:
            files (list): 文件信息列表
            target_dir (str): 目标目录路径
        """
        import shutil
        import threading

        def copy_thread():
            """复制文件的线程函数"""
            success_count = 0
            error_count = 0
            errors = []

            for i, file_info in enumerate(files):
                source_path = file_info["path"]
                target_path = os.path.join(target_dir, file_info["display_name"])

                try:
                    if file_info["is_dir"]:
                        shutil.copytree(source_path, target_path)
                    else:
                        shutil.copy2(source_path, target_path)
                    success_count += 1
                except (IOError, OSError, PermissionError, shutil.Error) as e:
                    error_count += 1
                    errors.append(f"{file_info['display_name']}: {e}")
                    warning(f"复制文件失败: {source_path} -> {target_path}, 错误: {e}")

                # 发送进度更新信号（线程安全）
                progress = i + 1
                self.update_progress.emit(progress)

            # 发送导出完成信号（线程安全）
            self.export_finished.emit(success_count, error_count, errors)

        # 启动复制线程
        thread = threading.Thread(target=copy_thread)
        thread.daemon = True
        thread.start()

    def _show_categorized_export_dialog(self, files, target_dir, on_confirm_callback, on_cancel_callback):
        """
        显示分类导出确认弹窗
        展示将要创建的文件夹列表，允许用户重命名文件夹

        Args:
            files (list): 文件信息列表
            target_dir (str): 目标目录路径
            on_confirm_callback (callable): 确认导出时的回调函数，参数为 folder_name_mapping
            on_cancel_callback (callable): 取消时的回调函数
        """
        from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget
        from freeassetfilter.widgets.smooth_scroller import D_ScrollBar, SmoothScroller

        app = QApplication.instance()
        default_font_size = getattr(app, 'default_font_size', 9)
        scaled_font_size = int(default_font_size * self.dpi_scale)

        base_color = "#FFFFFF"
        auxiliary_color = "#E6E6E6"
        normal_color = "#808080"
        secondary_color = "#333333"
        accent_color = "#1890ff"

        if hasattr(app, 'settings_manager'):
            base_color = app.settings_manager.get_setting("appearance.colors.base_color", "#FFFFFF")
            auxiliary_color = app.settings_manager.get_setting("appearance.colors.auxiliary_color", "#E6E6E6")
            normal_color = app.settings_manager.get_setting("appearance.colors.normal_color", "#808080")
            secondary_color = app.settings_manager.get_setting("appearance.colors.secondary_color", "#333333")
            accent_color = app.settings_manager.get_setting("appearance.colors.accent_color", "#1890ff")

        dialog = CustomMessageBox(self)
        dialog.set_title("分类导出确认")
        dialog.set_text("以下文件夹将被创建，您可以重命名文件夹：")

        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        scroll_area.setVerticalScrollBar(D_ScrollBar(scroll_area, Qt.Vertical))
        scroll_area.verticalScrollBar().apply_theme_from_settings()

        SmoothScroller.apply_to_scroll_area(scroll_area)

        scrollbar_style = f"""
            QScrollArea {{
                border: 1px solid {normal_color};
                border-radius: 8px;
                background-color: {base_color};
                padding: 3px;
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: {base_color};
            }}
        """
        scroll_area.setStyleSheet(scrollbar_style)
        scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        scroll_area.setMinimumWidth(int(400 * self.dpi_scale))
        scroll_area.setMaximumHeight(int(300 * self.dpi_scale))

        # 创建列表内容容器
        list_content = QWidget()
        list_content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        list_content_layout = QVBoxLayout(list_content)
        list_content_layout.setContentsMargins(0, 0, 0, 0)
        list_content_layout.setSpacing(int(4 * self.dpi_scale))

        # 收集文件夹信息（按原始目录分组）
        folder_groups = {}
        for file_info in files:
            source_dir = os.path.dirname(file_info["path"])
            category_name = os.path.basename(source_dir)
            if not category_name:
                category_name = "未分类"

            if category_name not in folder_groups:
                folder_groups[category_name] = {
                    'original_path': source_dir,
                    'files': []
                }
            folder_groups[category_name]['files'].append(file_info)

        # 存储文件夹卡片和映射信息
        folder_cards = []
        folder_name_mapping = {name: name for name in folder_groups.keys()}

        # 创建文件夹卡片
        for folder_name, folder_data in folder_groups.items():
            card = CustomFileHorizontalCard(
                file_path=folder_data['original_path'],
                parent=list_content,
                enable_multiselect=False,
                display_name=folder_name,
                single_line_mode=False,
                enable_delete_button=False
            )
            # 设置自定义信息文本（显示原始路径）
            card.set_custom_info_text(folder_data['original_path'])

            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            list_content_layout.addWidget(card)

            folder_cards.append({
                'card': card,
                'original_name': folder_name,
                'current_name': folder_name
            })

            # 连接重命名信号
            def create_rename_handler(card_info):
                def on_rename_requested(path):
                    self._on_folder_rename(card_info, folder_name_mapping, dialog)
                return on_rename_requested

            card.renameRequested.connect(create_rename_handler(folder_cards[-1]))

        list_content.setLayout(list_content_layout)
        scroll_area.setWidget(list_content)
        dialog.list_layout.addWidget(scroll_area)
        dialog.list_widget.show()

        # 设置按钮
        dialog.set_buttons(["确定导出", "取消"], Qt.Horizontal, ["primary", "normal"])

        def on_button_clicked(button_index):
            if button_index == 0:
                dialog.close()
                on_confirm_callback(folder_name_mapping)
            elif button_index == 1:
                dialog.close()
                on_cancel_callback()

        dialog.buttonClicked.connect(on_button_clicked)
        dialog.exec()

    def _on_folder_rename(self, folder_card_info, folder_name_mapping, parent_dialog):
        """
        处理文件夹重命名

        Args:
            folder_card_info (dict): 文件夹卡片信息
            folder_name_mapping (dict): 文件夹名称映射
            parent_dialog (CustomMessageBox): 父对话框
        """
        from freeassetfilter.widgets.D_widgets import CustomInputBox

        original_name = folder_card_info['original_name']
        current_name = folder_card_info['current_name']

        input_dialog = CustomMessageBox(self)
        input_dialog.set_title("重命名文件夹")
        input_dialog.set_text(f"请输入新的文件夹名称：")
        input_dialog.set_input(text=current_name)
        input_dialog.set_buttons(["确定", "取消"], Qt.Horizontal, ["primary", "normal"])

        result = None

        def on_button_clicked(button_index):
            nonlocal result
            result = button_index
            input_dialog.close()

        input_dialog.buttonClicked.connect(on_button_clicked)
        input_dialog.exec()

        if result == 0:
            new_name = input_dialog.get_input()
            if new_name.strip() and new_name.strip() != current_name:
                # 检查名称是否已存在
                if new_name.strip() in folder_name_mapping.values() and new_name.strip() != current_name:
                    error_msg = CustomMessageBox(self)
                    error_msg.set_title("错误")
                    error_msg.set_text(f"文件夹名称 '{new_name.strip()}' 已存在！")
                    error_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                    error_msg.buttonClicked.connect(error_msg.close)
                    error_msg.exec()
                    return

                # 更新映射
                folder_name_mapping[original_name] = new_name.strip()
                folder_card_info['current_name'] = new_name.strip()

                # 更新卡片显示
                folder_card_info['card'].set_file_path(
                    folder_card_info['card'].file_path,
                    display_name=new_name.strip()
                )

    def copy_files_categorized(self, files, target_dir, folder_name_mapping=None):
        """
        复制文件到目标目录（分类导出模式）
        按照文件原始所在目录创建同名文件夹进行分类存储

        Args:
            files (list): 文件信息列表
            target_dir (str): 目标目录路径
            folder_name_mapping (dict, optional): 文件夹名称映射，键为原始文件夹名，值为自定义文件夹名
        """
        import shutil
        import threading

        def copy_thread():
            """复制文件的线程函数"""
            success_count = 0
            error_count = 0
            errors = []

            for i, file_info in enumerate(files):
                source_path = file_info["path"]

                # 获取原始文件所在的目录名
                source_dir = os.path.dirname(source_path)
                original_category_name = os.path.basename(source_dir)

                # 如果无法获取目录名（例如在根目录），使用默认名称
                if not original_category_name:
                    original_category_name = "未分类"

                # 使用自定义文件夹名称（如果存在映射）
                if folder_name_mapping and original_category_name in folder_name_mapping:
                    category_name = folder_name_mapping[original_category_name]
                else:
                    category_name = original_category_name

                # 创建分类文件夹路径
                category_dir = os.path.join(target_dir, category_name)

                # 确保分类文件夹存在
                try:
                    os.makedirs(category_dir, exist_ok=True)
                except (IOError, OSError, PermissionError) as e:
                    error_count += 1
                    errors.append(f"{file_info['display_name']}: 无法创建分类文件夹 - {e}")
                    warning(f"创建分类文件夹失败: {category_dir}, 错误: {e}")
                    progress = i + 1
                    self.update_progress.emit(progress)
                    continue

                # 生成目标文件路径，处理同名文件冲突
                target_path = self._get_unique_target_path(category_dir, file_info["display_name"])

                try:
                    if file_info["is_dir"]:
                        shutil.copytree(source_path, target_path)
                    else:
                        shutil.copy2(source_path, target_path)
                    success_count += 1
                except (IOError, OSError, PermissionError, shutil.Error) as e:
                    error_count += 1
                    errors.append(f"{file_info['display_name']}: {e}")
                    warning(f"复制文件失败: {source_path} -> {target_path}, 错误: {e}")

                progress = i + 1
                self.update_progress.emit(progress)

            self.export_finished.emit(success_count, error_count, errors)

        # 启动复制线程
        thread = threading.Thread(target=copy_thread)
        thread.daemon = True
        thread.start()

    def _get_unique_target_path(self, target_dir, file_name):
        """
        获取唯一的的目标文件路径，处理同名文件冲突

        Args:
            target_dir (str): 目标目录路径
            file_name (str): 文件名

        Returns:
            str: 唯一的文件路径
        """
        target_path = os.path.join(target_dir, file_name)

        # 如果文件不存在，直接返回
        if not os.path.exists(target_path):
            return target_path

        # 分离文件名主体和后缀名
        if "." in file_name:
            name_parts = file_name.rsplit(".", 1)
            name_base = name_parts[0]
            name_ext = name_parts[1]
        else:
            name_base = file_name
            name_ext = ""

        # 查找唯一的文件名
        counter = 1
        while True:
            if name_ext:
                new_name = f"{name_base}_{counter}.{name_ext}"
            else:
                new_name = f"{name_base}_{counter}"

            target_path = os.path.join(target_dir, new_name)
            if not os.path.exists(target_path):
                return target_path

            counter += 1
            # 防止无限循环
            if counter > 9999:
                break

        # 如果无法找到唯一名称，使用时间戳
        import time
        timestamp = int(time.time())
        if name_ext:
            new_name = f"{name_base}_{timestamp}.{name_ext}"
        else:
            new_name = f"{name_base}_{timestamp}"
        return os.path.join(target_dir, new_name)

    def set_previewing_file(self, file_path):
        """
        设置当前正在预览的文件，更新对应卡片的预览态

        Args:
            file_path (str): 文件路径
        """
        if not file_path:
            return

        # 保存当前预览的文件路径
        self.previewing_file_path = os.path.normpath(file_path)

        # 先清除所有卡片的预览态
        self.clear_previewing_state()

        # 规范化路径用于比较（Windows下使用normcase处理大小写）
        file_path_norm = os.path.normcase(os.path.normpath(file_path))

        # 查找并设置对应卡片的预览态
        found = False
        for card, card_file_info in self.cards:
            card_path_norm = os.path.normcase(os.path.normpath(card_file_info.get('path', '')))
            if card_path_norm == file_path_norm:
                card.set_previewing(True)
                found = True
                break

        # 调试输出
        debug(f"[FileStagingPool] set_previewing_file: {file_path}")
        debug(f"[FileStagingPool] normalized path: {file_path_norm}")
        debug(f"[FileStagingPool] found={found}, total_cards={len(self.cards)}")
        if self.cards:
            first_card_path = os.path.normcase(os.path.normpath(self.cards[0][1].get('path', '')))
            debug(f"[FileStagingPool] first card path: {first_card_path}")

    def clear_previewing_state(self):
        """
        清除所有卡片的预览态
        注意：不清除 previewing_file_path，以便在需要时仍能恢复预览态
        """
        for card, _ in self.cards:
            if hasattr(card, 'set_previewing'):
                card.set_previewing(False)


class FolderSizeCalculator(QThread):
    """
    文件夹大小计算线程
    使用 QThread 确保与 PyQt 的线程安全兼容，避免与主线程的文件操作冲突
    """
    folder_size_calculated = Signal(dict)  # 计算完成信号，传递结果字典

    def __init__(self, folder_path, items, parent=None):
        """
        初始化文件夹大小计算线程

        Args:
            folder_path (str): 要计算大小的文件夹路径
            items (list): 文件信息列表，用于查找对应的文件信息项
            parent (QObject, optional): 父对象，默认为 None
        """
        super().__init__(parent)
        self.folder_path = folder_path
        self.items = items
        self._is_cancelled = False

    def run(self):
        """
        线程执行逻辑
        在后台线程中安全地计算文件夹大小
        """
        total_size = 0

        try:
            # 使用 os.walk 遍历文件夹，添加异常处理防止访问冲突
            for root, dirs, files in os.walk(self.folder_path):
                if self._is_cancelled:
                    return

                for file in files:
                    if self._is_cancelled:
                        return

                    file_path = os.path.join(root, file)
                    try:
                        # 使用 try-except 包裹每个文件操作，防止单个文件错误影响整体
                        if os.path.exists(file_path):
                            # 使用 os.stat 替代 os.path.getsize，更底层且稳定
                            stat_result = os.stat(file_path)
                            total_size += stat_result.st_size
                    except (OSError, PermissionError, FileNotFoundError):
                        # 忽略无法访问的文件
                        pass
                    except Exception as e:
                        # 捕获所有其他异常，确保线程不会崩溃
                        debug(f"计算文件大小时发生错误: {e}")
                        pass
        except (OSError, PermissionError, FileNotFoundError):
            # 文件夹无法访问
            pass
        except Exception as e:
            # 捕获所有其他异常
            debug(f"遍历文件夹时发生错误: {e}")
            pass

        # 发送计算结果（通过信号，线程安全）
        if not self._is_cancelled:
            result = {
                "path": self.folder_path,
                "size": total_size
            }
            self.folder_size_calculated.emit(result)

    def cancel(self):
        """
        取消计算
        设置取消标志，线程会在下一个检查点退出
        """
        self._is_cancelled = True


# 测试代码
if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication, QMainWindow

    app = QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle("文件临时存储池测试")
    window.setGeometry(100, 100, 600, 400)

    pool = FileStagingPool()
    window.setCentralWidget(pool)

    # 测试添加文件
    test_file = {
        "name": "test.txt",
        "path": "C:/test.txt",
        "is_dir": False,
        "size": 1024,
        "modified": "2023-01-01T12:00:00",
        "created": "2023-01-01T12:00:00",
        "suffix": "txt"
    }
    pool.add_file(test_file)

    window.show()
    sys.exit(app.exec())
