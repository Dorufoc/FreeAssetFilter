#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 列表类自定义控件
包含各种列表类UI组件，如自定义选择列表项、自定义选择列表等
"""

import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QApplication, QListWidget, QListWidgetItem,
    QSizePolicy, QFileIconProvider
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QColor, QPixmap, QIcon

from freeassetfilter.widgets.smooth_scroller import D_ScrollBar, SmoothScroller
from freeassetfilter.core.svg_renderer import SvgRenderer


class CustomSelectListItem:
    """
    自定义选择列表项数据对象
    与旧接口保持兼容，供 CustomSelectList 内部管理使用
    """

    def __init__(self, index=0, text="", icon_path="", is_selected=False):
        self.index = index
        self.text = text
        self.icon_path = icon_path
        self.is_selected = is_selected


class CustomSelectList(QWidget):
    """
    自定义选择列表组件
    使用与文件夹预览器/压缩包预览器一致的 QListWidget 呈现方式
    """

    itemClicked = Signal(int)
    itemDoubleClicked = Signal(int)
    selectionChanged = Signal(list)

    def __init__(
        self,
        parent=None,
        default_width=75,
        default_height=50,
        min_width=50,
        min_height=37.5,
        selection_mode="single"
    ):
        super().__init__(parent)

        app = QApplication.instance()
        self.dpi_scale = getattr(app, "dpi_scale_factor", 1.0)
        self.global_font = getattr(app, "global_font", QFont())

        self.default_width = int(default_width * self.dpi_scale)
        self.default_height = int(default_height * self.dpi_scale)
        self.min_width = int(min_width * self.dpi_scale)
        self.min_height = int(min_height * self.dpi_scale)

        self.selection_mode = selection_mode
        self.items = []
        self.selected_indices = []

        self._icon_provider = QFileIconProvider()
        self._suppress_selection_signal = False

        self.setFont(self.global_font)
        self.init_ui()

    def init_ui(self):
        """初始化自定义选择列表 UI"""
        app = QApplication.instance()

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.list_widget = QListWidget(self)
        self.list_widget.setFont(self.global_font)
        self.list_widget.setFocusPolicy(Qt.NoFocus)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_widget.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list_widget.setHorizontalScrollMode(QListWidget.ScrollPerPixel)

        self.list_widget.setVerticalScrollBar(D_ScrollBar(self.list_widget, Qt.Vertical))
        self.list_widget.verticalScrollBar().apply_theme_from_settings()

        SmoothScroller.apply(self.list_widget, enable_mouse_drag=False)
        self.list_widget.setAttribute(Qt.WA_AcceptTouchEvents, False)
        self.list_widget.viewport().setAttribute(Qt.WA_AcceptTouchEvents, False)

        self._apply_reference_list_style()

        self.list_widget.itemClicked.connect(self._on_qt_item_clicked)
        self.list_widget.itemDoubleClicked.connect(self._on_qt_item_double_clicked)
        self.list_widget.itemSelectionChanged.connect(self._on_qt_selection_changed)

        main_layout.addWidget(self.list_widget)

        self.setMinimumWidth(self.min_width)
        self.setFixedHeight(self.default_height)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def _apply_reference_list_style(self):
        """应用与文件夹预览器/压缩包预览器一致的 QListWidget 样式"""
        app = QApplication.instance()
        settings_manager = getattr(app, "settings_manager", None)

        current_colors = {
            "secondary_color": "#FFFFFF",
            "base_color": "#212121",
            "auxiliary_color": "#3D3D3D",
            "normal_color": "#717171",
            "accent_color": "#B036EE"
        }
        if settings_manager:
            current_colors = settings_manager.get_setting("appearance.colors", current_colors)

        base_color = current_colors.get("base_color", "#212121")
        secondary_color = current_colors.get("secondary_color", "#FFFFFF")
        auxiliary_color = current_colors.get("auxiliary_color", "#3D3D3D")
        normal_color = current_colors.get("normal_color", "#717171")
        accent_color = current_colors.get("accent_color", "#B036EE")

        border_radius = int(6 * self.dpi_scale)
        scaled_item_height = int(15 * self.dpi_scale)
        item_margin = int(2 * self.dpi_scale)

        qcolor = QColor(accent_color)
        qcolor.setAlpha(155)
        selected_bg_color = f"rgba({qcolor.red()}, {qcolor.green()}, {qcolor.blue()}, 0.4)"

        self.list_widget.setStyleSheet(f"""
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

        if self.selection_mode == "multiple":
            self.list_widget.setSelectionMode(QListWidget.MultiSelection)
        else:
            self.list_widget.setSelectionMode(QListWidget.SingleSelection)

    def _create_icon(self, icon_path: str) -> QIcon:
        """根据路径创建图标"""
        if not icon_path:
            return QIcon()

        ext = os.path.splitext(icon_path)[1].lower()

        if ext in [".png", ".jpg", ".jpeg", ".bmp", ".ico"]:
            pixmap = QPixmap(icon_path)
            if pixmap.isNull():
                return QIcon()
            return QIcon(pixmap)

        if ext == ".svg":
            scaled_size = int(14 * self.dpi_scale)
            pixmap = SvgRenderer.render_svg_to_pixmap(icon_path, scaled_size, self.dpi_scale)
            if pixmap.isNull():
                return QIcon()
            return QIcon(pixmap)

        if os.path.exists(icon_path):
            file_info = self._icon_provider.icon(QFileInfo(icon_path))
            return file_info if isinstance(file_info, QIcon) else QIcon()

        return QIcon()

    def add_item(self, text, icon_path=""):
        """添加列表项"""
        index = len(self.items)
        item_info = CustomSelectListItem(index=index, text=text, icon_path=icon_path)
        self.items.append(item_info)

        item = QListWidgetItem()
        item.setText(text)
        item.setFont(self.global_font)
        item.setData(Qt.UserRole, index)
        item.setSizeHint(QSize(0, int(15 * self.dpi_scale)))

        icon = self._create_icon(icon_path)
        if not icon.isNull():
            item.setIcon(icon)

        self.list_widget.addItem(item)
        self.adjust_width_to_content()

    def add_items(self, items):
        """批量添加列表项"""
        for item in items:
            if isinstance(item, str):
                self.add_item(item)
            elif isinstance(item, dict):
                text = item.get("text", "")
                icon_path = item.get("icon_path", "")
                self.add_item(text, icon_path)

        self.adjust_width_to_content()

    def _sync_selected_indices_from_qt(self):
        """同步当前选中索引"""
        selected = []
        for i in range(self.list_widget.count()):
            qt_item = self.list_widget.item(i)
            if qt_item.isSelected():
                index = qt_item.data(Qt.UserRole)
                if isinstance(index, int):
                    selected.append(index)

        self.selected_indices = selected

        for item in self.items:
            item.is_selected = item.index in self.selected_indices

    def _on_qt_item_clicked(self, item: QListWidgetItem):
        """Qt 单击事件处理"""
        self._sync_selected_indices_from_qt()
        index = item.data(Qt.UserRole)
        if isinstance(index, int):
            self.itemClicked.emit(index)
            self.selectionChanged.emit(self.selected_indices.copy())

    def _on_qt_item_double_clicked(self, item: QListWidgetItem):
        """Qt 双击事件处理"""
        self._sync_selected_indices_from_qt()
        index = item.data(Qt.UserRole)
        if isinstance(index, int):
            self.itemDoubleClicked.emit(index)

    def _on_qt_selection_changed(self):
        """Qt 选择变化事件处理"""
        if self._suppress_selection_signal:
            return
        self._sync_selected_indices_from_qt()
        self.selectionChanged.emit(self.selected_indices.copy())

    def set_selection_mode(self, mode):
        """设置选择模式"""
        self.selection_mode = mode
        self._apply_reference_list_style()
        self.clear_selection()

    def clear_selection(self):
        """清空选择"""
        self._suppress_selection_signal = True
        self.list_widget.clearSelection()
        self._suppress_selection_signal = False

        self.selected_indices.clear()
        for item in self.items:
            item.is_selected = False

        self.selectionChanged.emit(self.selected_indices.copy())

    def get_selected_indices(self):
        """获取选中索引列表"""
        return self.selected_indices.copy()

    def set_current_item(self, index):
        """设置当前选中项（单选模式）"""
        self._suppress_selection_signal = True
        self.list_widget.clearSelection()

        if 0 <= index < self.list_widget.count():
            item = self.list_widget.item(index)
            item.setSelected(True)
            self.list_widget.setCurrentItem(item)

        self._suppress_selection_signal = False
        self._sync_selected_indices_from_qt()
        self.selectionChanged.emit(self.selected_indices.copy())

    def set_selected_indices(self, indices):
        """设置选中索引列表"""
        self._suppress_selection_signal = True
        self.list_widget.clearSelection()

        for index in indices:
            if 0 <= index < self.list_widget.count():
                self.list_widget.item(index).setSelected(True)

        self._suppress_selection_signal = False
        self._sync_selected_indices_from_qt()
        self.selectionChanged.emit(self.selected_indices.copy())

    def clear_items(self):
        """清空所有列表项"""
        self.list_widget.clear()
        self.items.clear()
        self.selected_indices.clear()
        self.selectionChanged.emit(self.selected_indices.copy())
        self.adjust_width_to_content()

    def set_default_size(self, width, height):
        """设置默认尺寸"""
        self.default_width = int(width * self.dpi_scale)
        self.default_height = int(height * self.dpi_scale)
        self.setFixedHeight(self.default_height)

    def set_minimum_size(self, width, height):
        """设置最小尺寸"""
        self.min_width = int(width * self.dpi_scale)
        self.min_height = int(height * self.dpi_scale)
        self.setMinimumWidth(self.min_width)
        self.setFixedHeight(self.min_height)

    def adjust_width_to_content(self):
        """根据内容自动调整宽度"""
        if not self.items:
            self.setFixedWidth(self.min_width)
            return

        calculated_width = self._calculate_content_width()
        self.setFixedWidth(calculated_width)

    def _calculate_content_width(self):
        """计算内容所需宽度"""
        from PySide6.QtGui import QFontMetrics

        app = QApplication.instance()
        dpi_scale = getattr(app, "dpi_scale_factor", 1.0)
        global_font = getattr(app, "global_font", QFont())

        font_metrics = QFontMetrics(global_font)
        max_text_width = 0
        has_icon = False

        for item in self.items:
            text = item.text if hasattr(item, "text") else ""
            if text:
                lines = text.split("\n")
                for line in lines:
                    text_width = font_metrics.horizontalAdvance(line)
                    max_text_width = max(max_text_width, text_width)

            if getattr(item, "icon_path", ""):
                has_icon = True

        icon_size = int(14 * dpi_scale) if has_icon else 0
        item_margin = int(2 * dpi_scale)
        list_padding = int(6 * dpi_scale)
        text_padding_left = int(8 * dpi_scale)

        calculated_width = list_padding * 2 + item_margin * 2
        if has_icon:
            calculated_width += icon_size + item_margin
        calculated_width += text_padding_left + max_text_width + int(24 * dpi_scale)

        return max(calculated_width, self.min_width, self.default_width)

    def sizeHint(self):
        """返回建议尺寸"""
        total_height = 0

        if self.list_widget.count() > 0:
            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                total_height += item.sizeHint().height()

            spacing = int(2 * self.dpi_scale)
            total_height += spacing * max(0, self.list_widget.count() - 1)
            total_height += int(12 * self.dpi_scale)

        calculated_width = self._calculate_content_width()
        calculated_height = max(total_height, self.min_height, self.default_height)

        return QSize(calculated_width, calculated_height)
