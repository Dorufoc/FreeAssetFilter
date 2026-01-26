#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 菜单列表控件
结合D_HoverMenu和列表组件，提供悬浮列表菜单功能
特点：
- 基于D_HoverMenu的悬浮菜单功能
- 支持单选和多选模式
- 支持DPI缩放和主题颜色
- 支持项目点击和选择事件
- 横向宽度自适应文本内容
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QApplication, QScrollArea, QLabel
from PyQt5.QtCore import Qt, QPoint, pyqtSignal, QSize, QRect, QTimer
from PyQt5.QtGui import QFont, QFontMetrics

from .D_hover_menu import D_HoverMenu
from .smooth_scroller import D_ScrollBar
from .smooth_scroller import SmoothScroller


class D_MenuList(QWidget):
    """
    菜单列表控件
    结合D_HoverMenu和列表组件，提供悬浮列表菜单功能
    特点：
    - 基于D_HoverMenu的悬浮菜单功能
    - 支持单选模式
    - 支持DPI缩放和主题颜色
    - 支持项目点击事件
    - 横向宽度自适应文本内容
    """
    itemClicked = pyqtSignal(object)

    def __init__(self, parent=None, position="bottom"):
        """
        初始化菜单列表

        Args:
            parent: 父窗口部件
            position: 菜单位置，"top" 或 "bottom"，默认为下方
        """
        super().__init__(parent)

        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        self.global_font = getattr(app, 'global_font', QFont())

        self.settings_manager = None
        if hasattr(app, 'settings_manager'):
            self.settings_manager = app.settings_manager

        self._items = []
        self._current_item = None
        self._max_height = int(50 * self.dpi_scale)
        self._position = position

        self._init_ui()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.hover_menu = D_HoverMenu(self, position=self._position)
        self.hover_menu.set_offset(0, int(5 * self.dpi_scale))

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBar(D_ScrollBar(self.scroll_area, Qt.Vertical))
        self.scroll_area.verticalScrollBar().apply_theme_from_settings()
        SmoothScroller.apply_to_scroll_area(self.scroll_area)
        self.scroll_area.setStyleSheet(
            "QScrollArea { border: none; background-color: transparent; }"
        )

        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(0)

        self.scroll_area.setWidget(self.list_container)
        self.hover_menu.set_content(self.scroll_area)

    def set_items(self, items, default_item=None):
        """
        设置列表项

        Args:
            items (list): 列表项，可以是字符串列表或字典列表
            default_item: 默认选中项
        """
        for i in reversed(range(self.list_layout.count())):
            widget = self.list_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()

        self._items = items

        for item in items:
            if isinstance(item, dict):
                text = item.get('text', '')
                data = item.get('data', text)
            else:
                text = str(item)
                data = item

            item_button = QPushButton(text)
            item_button.setFont(self.global_font)
            item_button.setFlat(True)
            item_button.setCursor(Qt.PointingHandCursor)

            font_size = int(8 * self.dpi_scale)

            normal_color = "#e0e0e0"
            if self.settings_manager:
                normal_color = self.settings_manager.get_setting("appearance.colors.normal_color", "#e0e0e0")

            secondary_color = "#333333"
            if self.settings_manager:
                secondary_color = self.settings_manager.get_setting("appearance.colors.secondary_color", "#333333")

            button_height = int(20 * self.dpi_scale) / 2

            item_button.setStyleSheet(f"""
                QPushButton {{
                    font-size: {font_size}px;
                    color: {secondary_color};
                    padding: 2px 3px;
                    background-color: transparent;
                    border: none;
                    text-align: center;
                    vertical-align: center;
                    height: {button_height}px;
                }}
                QPushButton:hover {{
                    background-color: {normal_color};
                }}
            """)

            item_button.clicked.connect(lambda checked, d=data: self._on_item_clicked(d))

            self.list_layout.addWidget(item_button)

        if default_item is not None:
            self.set_current_item(default_item)
        elif items:
            self.set_current_item(items[0])

        self._adjust_menu_size()

    def set_current_item(self, item):
        """
        设置当前选中项

        Args:
            item: 要选中的项
        """
        if not self._items:
            return

        item_float = None
        if isinstance(item, str):
            try:
                item_float = float(item.replace('x', ''))
            except ValueError:
                pass

        for i, menu_item in enumerate(self._items):
            if isinstance(menu_item, dict):
                menu_text = menu_item.get('text', '')
                menu_data = menu_item.get('data', menu_text)

                if isinstance(item, dict):
                    item_text = item.get('text', '')
                    item_data = item.get('data', item_text)

                    if (menu_text == item_text or
                        menu_data == item_data or
                        menu_text == item_data or
                        menu_data == item_text):
                        self._current_item = menu_item
                        break
                else:
                    menu_text_float = None
                    if isinstance(menu_text, str):
                        try:
                            menu_text_float = float(menu_text.replace('x', ''))
                        except ValueError:
                            pass

                    menu_data_float = None
                    if isinstance(menu_data, str):
                        try:
                            menu_data_float = float(menu_data.replace('x', ''))
                        except ValueError:
                            pass

                    if (menu_text == item or
                        menu_data == item or
                        (item_float is not None and menu_text_float == item_float) or
                        (item_float is not None and menu_data_float == item_float)):
                        self._current_item = menu_item
                        break
            else:
                if isinstance(menu_item, str):
                    menu_float = None
                    try:
                        menu_float = float(menu_item.replace('x', ''))
                    except ValueError:
                        pass

                    if (menu_item == item or
                        (item_float is not None and menu_float == item_float)):
                        self._current_item = menu_item
                        break
                else:
                    if menu_item == item:
                        self._current_item = menu_item
                        break

    def current_item(self):
        """
        获取当前选中项

        Returns:
            当前选中项
        """
        return self._current_item

    def set_max_height(self, height):
        """
        设置最大高度

        Args:
            height (int): 最大高度值
        """
        self._max_height = height
        self._adjust_menu_size()

    def set_position(self, position):
        """
        设置菜单位置

        Args:
            position (str): 菜单位置，"top" 或 "bottom"
        """
        if position in ["top", "bottom"]:
            self._position = position
            self.hover_menu.set_position(position)

    def set_target_widget(self, widget):
        """
        设置目标控件，菜单将显示在该控件附近

        Args:
            widget: 目标控件
        """
        self.hover_menu.set_target_widget(widget)

    def _adjust_menu_size(self):
        """调整菜单大小"""
        self.list_container.adjustSize()

        scroll_height = min(self.list_container.height(), self._max_height)
        self.scroll_area.setFixedHeight(scroll_height)

        scroll_bar_width = self.scroll_area.verticalScrollBar().sizeHint().width()

        self.scroll_area.setFixedWidth(self.list_container.width() + scroll_bar_width)
        self.list_container.setFixedWidth(self.list_container.width())

        self.hover_menu.adjustSize()

    def _on_item_clicked(self, item_data):
        """
        列表项点击事件处理

        Args:
            item_data: 点击的列表项数据
        """
        self.set_current_item(item_data)
        self.itemClicked.emit(item_data)
        self.hide()

    def show(self):
        """显示菜单"""
        self.hover_menu.show()

    def hide(self):
        """隐藏菜单"""
        self.hover_menu.hide()

    def is_visible(self):
        """检查菜单是否正在显示"""
        return self.hover_menu.is_visible()

    def toggle(self):
        """切换显示/隐藏状态"""
        if self.is_visible():
            self.hide()
        else:
            self.show()


class D_MenuListItem(QPushButton):
    """
    菜单列表项组件
    用于D_MenuList中的单个列表项
    特点：
    - 支持文本和图标显示
    - 支持悬停效果
    - 支持DPI缩放
    - 支持主题颜色
    """

    def __init__(self, text="", data=None, parent=None):
        """
        初始化菜单列表项

        Args:
            text: 显示文本
            data: 关联数据
            parent: 父窗口部件
        """
        super().__init__(text, parent)

        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        self.global_font = getattr(app, 'global_font', QFont())

        self.settings_manager = None
        if hasattr(app, 'settings_manager'):
            self.settings_manager = app.settings_manager

        self._data = data if data is not None else text

        self._init_ui(text)

    def _init_ui(self, text):
        """初始化UI组件"""
        self.setFont(self.global_font)
        self.setFlat(True)
        self.setCursor(Qt.PointingHandCursor)

        font_size = int(8 * self.dpi_scale)

        normal_color = "#e0e0e0"
        if self.settings_manager:
            normal_color = self.settings_manager.get_setting("appearance.colors.normal_color", "#e0e0e0")

        secondary_color = "#333333"
        if self.settings_manager:
            secondary_color = self.settings_manager.get_setting("appearance.colors.secondary_color", "#333333")

        button_height = int(20 * self.dpi_scale) / 2

        self.setStyleSheet(f"""
            QPushButton {{
                font-size: {font_size}px;
                color: {secondary_color};
                padding: 2px 3px;
                background-color: transparent;
                border: none;
                text-align: center;
                vertical-align: center;
                height: {button_height}px;
            }}
            QPushButton:hover {{
                background-color: {normal_color};
            }}
        """)

    def set_data(self, data):
        """
        设置关联数据

        Args:
            data: 要设置的数据
        """
        self._data = data

    def data(self):
        """
        获取关联数据

        Returns:
            关联的数据
        """
        return self._data
