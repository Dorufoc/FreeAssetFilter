#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 自定义右键菜单控件
提供带hover效果的列表式右键菜单
特点：
- 现代简洁的白色卡片样式
- 支持自定义菜单项列表
- 每项支持hover高亮效果
- 点击触发对应功能
- 支持DPI缩放和主题颜色
- 支持超时自动隐藏
- 宽度自适应文本内容
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QApplication, QFrame
from PySide6.QtCore import Qt, QPoint, Signal, QSize, QTimer, QEvent, QRect
from PySide6.QtGui import QFont, QFontMetrics, QColor, QPainter, QBrush, QPen

from .D_hover_menu import D_HoverMenu


class D_MoreMenuItem(QPushButton):
    """
    右键菜单项组件
    用于D_MoreMenu中的单个菜单项
    特点：
    - 支持文本显示
    - 支持悬停效果
    - 支持DPI缩放
    - 支持主题颜色
    - 文本左对齐
    """

    def __init__(self, text="", data=None, parent=None):
        """
        初始化菜单项

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

        self._apply_stylesheet()

    def _apply_stylesheet(self):
        """应用样式表"""
        # 圆角大小与外层一致
        border_radius = int(4 * self.dpi_scale)
        border_radius_item = 0
        padding_left = int(8 * self.dpi_scale)
        padding_right = int(20 * self.dpi_scale)  # 20dx右边距
        padding_v = int(6 * self.dpi_scale)
        # hover效果比内容小一圈的边距（更小）
        hover_margin = int(1 * self.dpi_scale)

        base_color = "#ffffff"
        hover_color = "#f0f0f0"
        text_color = "#333333"

        if self.settings_manager:
            colors = self.settings_manager.get_setting("appearance.colors", {})
            base_color = colors.get("base_color", "#ffffff")
            hover_color = colors.get("normal_color", "#f0f0f0")
            text_color = colors.get("secondary_color", "#333333")

        self.setStyleSheet(f"""
            QPushButton {{
                color: {text_color};
                padding: {padding_v}px {padding_right}px {padding_v}px {padding_left}px;
                background-color: transparent;
                border: none;
                border-radius: {border_radius_item}px;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
                margin: {hover_margin}px;
                padding: {padding_v - hover_margin}px {padding_right - hover_margin}px {padding_v - hover_margin}px {padding_left - hover_margin}px;
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


class D_MoreMenu(QWidget):
    """
    自定义右键菜单控件
    提供带hover效果的列表式右键菜单
    特点：
    - 现代简洁的白色卡片样式
    - 支持自定义菜单项列表
    - 每项支持hover高亮效果
    - 点击触发对应功能
    - 支持DPI缩放和主题颜色
    - 支持超时自动隐藏
    - 宽度自适应文本内容
    """
    itemClicked = Signal(object)

    def __init__(self, parent=None):
        """
        初始化右键菜单

        Args:
            parent: 父窗口部件
        """
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)

        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        self.global_font = getattr(app, 'global_font', QFont())

        self.settings_manager = None
        if hasattr(app, 'settings_manager'):
            self.settings_manager = app.settings_manager

        self._items = []
        self._timeout_enabled = True
        self._timeout_duration = 5000
        self._target_widget = None

        self._bg_color = QColor(255, 255, 255)
        self._shadow_color = QColor(0, 0, 0, 30)
        self._border_radius = int(4 * self.dpi_scale)
        self._shadow_radius = int(4 * self.dpi_scale)
        self._padding = int(4 * self.dpi_scale)
        self._normal_color = QColor(224, 224, 224)  # 默认normal颜色
        self._border_width = int(1 * self.dpi_scale)  # 1dx边框宽度

        self._content_widget = None
        self._list_layout = None

        self._load_theme_colors()
        self._init_ui()

    def _load_theme_colors(self):
        """加载主题颜色"""
        if self.settings_manager:
            base_color_str = self.settings_manager.get_setting("appearance.colors.base_color", "#ffffff")
            self._bg_color = QColor(base_color_str)
            normal_color_str = self.settings_manager.get_setting("appearance.colors.normal_color", "#e0e0e0")
            self._normal_color = QColor(normal_color_str)

    def _init_ui(self):
        """初始化UI组件"""
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(
            self._shadow_radius + self._padding,
            self._shadow_radius + self._padding,
            self._shadow_radius + self._padding,
            self._shadow_radius + self._padding
        )
        main_layout.setSpacing(0)

        self._content_widget = QWidget()
        self._content_widget.setStyleSheet(f"""
            QWidget {{
                background-color: {self._bg_color.name()};
                border-radius: {self._border_radius}px;
                border: {self._border_width}px solid {self._normal_color.name()};
            }}
        """)

        self._list_layout = QVBoxLayout(self._content_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(int(2 * self.dpi_scale))

        main_layout.addWidget(self._content_widget)

        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self.hide)

    def paintEvent(self, event):
        """绘制阴影和背景"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 计算内容区域的位置和大小
        content_x = self._shadow_radius + self._padding
        content_y = self._shadow_radius + self._padding
        content_width = self.width() - 2 * content_x
        content_height = self.height() - 2 * content_y

        # 绘制阴影层（与内容区域完全对齐）
        shadow_rect = QRect(content_x, content_y, content_width, content_height)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(self._shadow_color))
        painter.drawRoundedRect(shadow_rect, self._border_radius, self._border_radius)

    def set_items(self, items):
        """
        设置菜单项

        Args:
            items: 菜单项列表，每项可以是字符串或字典
                   字典格式: {"text": "显示文本", "data": 数据}
        """
        for i in reversed(range(self._list_layout.count())):
            widget = self._list_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        self._items = items

        for item in items:
            if isinstance(item, dict):
                text = item.get('text', '')
                data = item.get('data', text)
            else:
                text = str(item)
                data = item

            item_widget = D_MoreMenuItem(text, data, self)
            item_widget.clicked.connect(lambda checked, d=data: self._on_item_clicked(d))

            self._list_layout.addWidget(item_widget)

        self._adjust_menu_size()

    def add_item(self, text, data=None):
        """
        添加单个菜单项

        Args:
            text: 显示文本
            data: 关联数据
        """
        item_data = data if data is not None else text

        item_widget = D_MoreMenuItem(text, item_data, self)
        item_widget.clicked.connect(lambda checked, d=item_data: self._on_item_clicked(d))

        self._list_layout.addWidget(item_widget)
        self._items.append({"text": text, "data": item_data})
        self._adjust_menu_size()

    def insert_item(self, index, text, data=None):
        """
        在指定位置插入菜单项

        Args:
            index: 插入位置
            text: 显示文本
            data: 关联数据
        """
        item_data = data if data is not None else text

        item_widget = D_MoreMenuItem(text, item_data, self)
        item_widget.clicked.connect(lambda checked, d=item_data: self._on_item_clicked(d))

        self._list_layout.insertWidget(index, item_widget)

        if index <= len(self._items):
            self._items.insert(index, {"text": text, "data": item_data})
        else:
            self._items.append({"text": text, "data": item_data})

        self._adjust_menu_size()

    def remove_item(self, index):
        """
        移除指定位置的菜单项

        Args:
            index: 要移除的项索引
        """
        if 0 <= index < self._list_layout.count():
            widget = self._list_layout.itemAt(index).widget()
            if widget:
                widget.deleteLater()

            if index < len(self._items):
                self._items.pop(index)

            self._adjust_menu_size()

    def clear_items(self):
        """清空所有菜单项"""
        for i in reversed(range(self._list_layout.count())):
            widget = self._list_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        self._items = []
        self._adjust_menu_size()

    def _on_item_clicked(self, item_data):
        """
        菜单项点击事件处理

        Args:
            item_data: 点击的菜单项数据
        """
        self.itemClicked.emit(item_data)
        self.hide()

    def _adjust_menu_size(self):
        """调整菜单大小，宽度根据内容自适应"""
        self._content_widget.adjustSize()

        content_width = self._content_widget.sizeHint().width()
        content_height = self._content_widget.sizeHint().height()

        # 设置最短横向宽度为50dx
        min_width = int(50 * self.dpi_scale)
        if content_width < min_width:
            content_width = min_width

        # 不设置固定宽度，让控件根据内容自适应
        self._content_widget.setMinimumWidth(content_width)

        total_width = content_width + 2 * (self._shadow_radius + self._padding)
        total_height = content_height + 2 * (self._shadow_radius + self._padding)

        self.setFixedSize(total_width, total_height)

    def set_timeout_duration(self, duration):
        """
        设置超时自动隐藏时间

        Args:
            duration: 超时时间（毫秒）
        """
        self._timeout_duration = duration

    def set_timeout_enabled(self, enabled):
        """
        设置是否启用超时自动隐藏

        Args:
            enabled: 是否启用
        """
        self._timeout_enabled = enabled

    def set_target_widget(self, widget):
        """
        设置目标控件，菜单将显示在该控件附近

        Args:
            widget: 目标控件
        """
        self._target_widget = widget

    def popup(self, pos):
        """
        在指定位置弹出菜单

        Args:
            pos: 弹出位置（QPoint）
        """
        self._adjust_menu_size()
        self.move(pos.x(), pos.y())
        self.show()
        if self._timeout_enabled:
            self._timeout_timer.start(self._timeout_duration)

    def show_at_widget(self, widget):
        """
        在目标控件位置显示菜单

        Args:
            widget: 目标控件
        """
        self.set_target_widget(widget)
        self._adjust_menu_size()

        widget_rect = widget.rect()
        widget_global_pos = widget.mapToGlobal(QPoint(0, 0))

        x = widget_global_pos.x()
        y = widget_global_pos.y() + widget_rect.height() + int(5 * self.dpi_scale)

        self.move(x, y)
        self.show()

        if self._timeout_enabled:
            self._timeout_timer.start(self._timeout_duration)

    def show(self):
        """显示菜单"""
        super().show()
        if self._timeout_enabled:
            self._timeout_timer.start(self._timeout_duration)

    def hide(self):
        """隐藏菜单"""
        self._timeout_timer.stop()
        super().hide()

    def is_visible(self):
        """检查菜单是否正在显示"""
        return self.isVisible()

    def toggle(self):
        """切换显示/隐藏状态"""
        if self.is_visible():
            self.hide()
        else:
            self.show()

    def count(self):
        """
        获取菜单项数量

        Returns:
            菜单项数量
        """
        return len(self._items)

    def item_data(self, index):
        """
        获取指定索引的菜单项数据

        Args:
            index: 菜单项索引

        Returns:
            菜单项数据，如果索引无效则返回None
        """
        if 0 <= index < len(self._items):
            item = self._items[index]
            if isinstance(item, dict):
                return item.get('data', item)
            return item
        return None

    def item_text(self, index):
        """
        获取指定索引的菜单项文本

        Args:
            index: 菜单项索引

        Returns:
            菜单项文本，如果索引无效则返回空字符串
        """
        if 0 <= index < len(self._items):
            item = self._items[index]
            if isinstance(item, dict):
                return item.get('text', '')
            return str(item)
        return ""

    def items(self):
        """
        获取所有菜单项

        Returns:
            菜单项列表
        """
        return self._items.copy()

    def enterEvent(self, event):
        """鼠标进入事件"""
        self._timeout_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        """鼠标离开事件"""
        if self._timeout_enabled:
            self._timeout_timer.start(self._timeout_duration)
        super().leaveEvent(event)

    def connect_context_menu(self, widget):
        """
        连接控件的右键菜单

        Args:
            widget: 要连接右键菜单的控件
        """
        widget.setContextMenuPolicy(Qt.CustomContextMenu)
        widget.customContextMenuRequested.connect(
            lambda pos: self._on_context_menu_requested(widget, pos)
        )

    def _on_context_menu_requested(self, widget, pos):
        """
        右键菜单请求处理

        Args:
            widget: 发出请求的控件
            pos: 请求位置
        """
        global_pos = widget.mapToGlobal(pos)
        self.popup(global_pos)
