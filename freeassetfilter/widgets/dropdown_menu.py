#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 自定义下拉菜单组件
用于提供类似视频倍速调整的列表选择功能
支持自适应文字显示、固定宽度和滚动布局
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QApplication, QScrollArea, QLabel
from PyQt5.QtCore import Qt, QPoint, pyqtSignal, QSize, QRect
from PyQt5.QtGui import QFont, QFontMetrics

from .control_menu import CustomControlMenu
from .button_widgets import CustomButton
from .smooth_scroller import D_ScrollBar
from .smooth_scroller import SmoothScroller
import os


class CustomDropdownMenu(QWidget):
    """
    自定义下拉菜单组件
    包含一个按钮和可弹出的列表菜单
    支持自适应文字显示和滚动布局
    """
    itemClicked = pyqtSignal(object)  # 列表项点击信号，传递选中项数据
    
    def __init__(self, parent=None, position="top"):
        """
        初始化下拉菜单
        
        Args:
            parent: 父窗口部件
            position: 菜单位置，"top" 或 "bottom"，默认为上方
        """
        super().__init__(parent)
        
        # 获取应用实例和DPI缩放因子
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        self.global_font = getattr(app, 'global_font', QFont())
        
        # 获取settings_manager实例（如果有）
        self.settings_manager = None
        if hasattr(app, 'settings_manager'):
            self.settings_manager = app.settings_manager
        
        # 核心属性
        self._items = []  # 列表项数据
        self._current_item = None  # 当前选中项
        self._menu_visible = False  # 菜单是否可见
        self._fixed_width = None  # 固定宽度
        self._max_height = int(50 * self.dpi_scale)  # 最大高度
        self._position = position  # 菜单位置："top" 或 "bottom"
        self._external_target_button = None  # 外部设置的目标按钮
        
        # 初始化UI
        self.init_ui()
        
    def init_ui(self):
        """
        初始化UI组件
        """
        # 设置布局
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 创建主按钮，使用CustomButton，与load_cube_button保持相同高度（默认20px，与ArchiveBrowser中的按钮保持一致）
        self.main_button = CustomButton(
            text="",
            button_type="normal",
            display_mode="text",
            #height=20
        )
        
        # 创建下拉菜单
        self.dropdown_menu = CustomControlMenu(self)
        
        # 调整菜单内边距
        self.dropdown_menu._padding = 2
        
        # 设置阴影半径
        self.dropdown_menu._shadow_radius = 0
        
        # 设置菜单样式
        self.dropdown_menu.setStyleSheet("QWidget { border: none; background-color: transparent; }")
        
        # 创建滚动区域
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        self.scroll_area.setVerticalScrollBar(D_ScrollBar(self.scroll_area, Qt.Vertical))
        self.scroll_area.verticalScrollBar().apply_theme_from_settings()
        
        SmoothScroller.apply_to_scroll_area(self.scroll_area)
        
        # 设置滚动区域样式表
        self.scroll_area.setStyleSheet(
            "QScrollArea { border: none; background-color: transparent; }"
        )
        
        # 创建列表容器
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(0)
        
        # 将列表容器设置到滚动区域
        self.scroll_area.setWidget(self.list_container)
        
        # 将滚动区域设置为菜单的内容
        self.dropdown_menu.set_content(self.scroll_area)
        
        # 强制调整菜单大小
        self.dropdown_menu.adjustSize()
        
        # 将按钮添加到主布局
        main_layout.addWidget(self.main_button)
        
        # 连接信号和槽
        self.main_button.clicked.connect(self.toggle_menu)
        
    def set_items(self, items, default_item=None):
        """
        设置下拉菜单的列表项
        
        Args:
            items (list): 列表项，可以是字符串列表或字典列表
            default_item: 默认选中项
        """
        # 清空现有列表项
        for i in reversed(range(self.list_layout.count())):
            widget = self.list_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()
        
        # 保存列表项
        self._items = items
        
        # 创建新的列表项
        for item in items:
            # 处理字符串和字典两种格式
            if isinstance(item, dict):
                text = item.get('text', '')
                data = item.get('data', text)
            else:
                text = str(item)
                data = item
            
            # 创建列表项按钮（使用QPushButton替代QLabel以支持cursor属性）
            item_button = QPushButton(text)
            item_button.setFont(self.global_font)
            item_button.setFlat(True)  # 设置为平面样式
            item_button.setCursor(Qt.PointingHandCursor)  # 设置鼠标指针为手型
            
            # 设置样式
            font_size = int(8 * self.dpi_scale)
            
            # 获取normal_color，默认#e0e0e0
            normal_color = "#e0e0e0"
            if self.settings_manager:
                normal_color = self.settings_manager.get_setting("appearance.colors.normal_color", "#e0e0e0")
            
            # 获取secondary_color，默认#333333
            secondary_color = "#333333"
            if self.settings_manager:
                secondary_color = self.settings_manager.get_setting("appearance.colors.secondary_color", "#333333")
            
            # 设置按钮高度，与主按钮保持一致
            button_height = int(20 * self.dpi_scale)/2  # 使用与主按钮相同的高度(20px)并应用DPI缩放
            
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
            
            # 设置点击事件
            item_button.clicked.connect(lambda checked, d=data: self._on_item_clicked(d))
            
            # 添加到布局
            self.list_layout.addWidget(item_button)
        
        # 设置默认选中项
        if default_item is not None:
            self.set_current_item(default_item)
        elif items:
            self.set_current_item(items[0])
        
        # 调整菜单大小
        self._adjust_menu_size()
        
    def set_current_item(self, item):
        """
        设置当前选中项

        Args:
            item: 要选中的项
        """
        if not self._items:
            return
        
        # 尝试将item转换为浮点数（用于倍速比较）
        item_float = None
        if isinstance(item, str):
            try:
                item_float = float(item.replace('x', ''))
            except ValueError:
                pass
        
        # 找到对应的项
        for i, menu_item in enumerate(self._items):
            if isinstance(menu_item, dict):
                menu_text = menu_item.get('text', '')
                menu_data = menu_item.get('data', menu_text)
                
                # 如果item是字典，比较text或data字段
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
                    # 尝试将menu_text转换为浮点数
                    menu_text_float = None
                    if isinstance(menu_text, str):
                        try:
                            menu_text_float = float(menu_text.replace('x', ''))
                        except ValueError:
                            pass
                    
                    # 尝试将menu_data转换为浮点数
                    menu_data_float = None
                    if isinstance(menu_data, str):
                        try:
                            menu_data_float = float(menu_data.replace('x', ''))
                        except ValueError:
                            pass
                    
                    # 比较：精确匹配或浮点数等值匹配
                    if (menu_text == item or 
                        menu_data == item or 
                        (item_float is not None and menu_text_float == item_float) or 
                        (item_float is not None and menu_data_float == item_float)):
                        self._current_item = menu_item
                        break
            else:
                # 处理字符串格式的菜单项
                if isinstance(menu_item, str):
                    # 尝试将menu_item转换为浮点数
                    menu_float = None
                    try:
                        menu_float = float(menu_item.replace('x', ''))
                    except ValueError:
                        pass
                    
                    # 比较：精确匹配或浮点数等值匹配
                    if (menu_item == item or 
                        (item_float is not None and menu_float == item_float)):
                        self._current_item = menu_item
                        break
                else:
                    # 处理非字符串格式的菜单项
                    if menu_item == item:
                        self._current_item = menu_item
                        break
        
        # 更新按钮显示
        self._update_button_text()
        
    def current_item(self):
        """
        获取当前选中项
        
        Returns:
            当前选中项
        """
        return self._current_item
    
    def set_fixed_width(self, width):
        """
        设置固定宽度
        
        Args:
            width (int): 固定宽度值
        """
        self._fixed_width = width
        self.main_button.setFixedWidth(width)
        self._adjust_menu_size()
    
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
            if hasattr(self, 'dropdown_menu'):
                self.dropdown_menu.set_position(position)
    
    def set_target_button(self, button):
        """
        设置目标按钮
        
        Args:
            button: 目标按钮部件
        """
        self._external_target_button = button
        if hasattr(self, 'dropdown_menu'):
            self.dropdown_menu.set_target_button(button)
    
    def _update_button_text(self):
        """
        更新按钮显示的文本
        """
        if not self._current_item:
            return
        
        if isinstance(self._current_item, dict):
            text = self._current_item.get('text', '')
        else:
            text = str(self._current_item)
        
        # 自适应文字显示
        if self._fixed_width:
            font_metrics = QFontMetrics(self.main_button.font())
            # 减小内边距以显示更多文本，并增加可用宽度
            elided_text = font_metrics.elidedText(text, Qt.ElideRight, self._fixed_width - 2)
            self.main_button.setText(elided_text)
        else:
            self.main_button.setText(text)
        
        self.main_button.update()
    
    def _adjust_menu_size(self):
        """
        调整菜单大小
        """
        # 计算列表容器的理想大小
        self.list_container.adjustSize()
        
        # 设置滚动区域的最大高度
        scroll_height = min(self.list_container.height(), self._max_height)
        self.scroll_area.setFixedHeight(scroll_height)
        
        # 获取滚动条宽度
        scroll_bar_width = self.scroll_area.verticalScrollBar().sizeHint().width()
        
        # 设置宽度
        if self._fixed_width:
            self.scroll_area.setFixedWidth(self._fixed_width)
            # 列表容器宽度减去滚动条宽度，避免文字被遮挡
            self.list_container.setFixedWidth(self._fixed_width - scroll_bar_width)
        else:
            # 自适应宽度：优先使用外部目标按钮的宽度，否则使用内部main_button的宽度
            if self._external_target_button:
                button_width = self._external_target_button.width()
            else:
                button_width = self.main_button.width()
            self.scroll_area.setFixedWidth(button_width)
            # 列表容器宽度减去滚动条宽度，避免文字被遮挡
            self.list_container.setFixedWidth(button_width - scroll_bar_width)
        
        # 调整菜单大小
        self.dropdown_menu.adjustSize()
    
    def toggle_menu(self):
        """
        切换菜单显示/隐藏状态
        """
        if self._menu_visible:
            self.hide_menu()
        else:
            self.show_menu()
            
    def show_menu(self):
        """
        显示菜单
        """
        if not self._menu_visible:
            # 优先使用外部设置的目标按钮，否则使用内部main_button
            target_button = self._external_target_button if self._external_target_button else self.main_button
            # 设置目标按钮
            self.dropdown_menu.set_target_button(target_button)
            # 设置菜单位置
            self.dropdown_menu.set_position(self._position)
            # 显示菜单
            self.dropdown_menu.show()
            self._menu_visible = True
            # 连接菜单关闭信号
            self.dropdown_menu.closeEvent = self._on_menu_close
            # 连接点击外部区域关闭菜单信号
            self.dropdown_menu.mousePressEvent = self._on_menu_click
            # 连接按钮的leaveEvent
            if target_button is self.main_button:
                self.main_button.leaveEvent = self._on_button_leave
            # 启动定时器，3秒后检查是否需要关闭菜单
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(3000, self._check_leave_and_close)
            
    def hide_menu(self):
        """
        隐藏菜单
        """
        if self._menu_visible:
            self.dropdown_menu.close()
            self._menu_visible = False
            # 断开按钮的leaveEvent
            if self._external_target_button is None:
                self.main_button.leaveEvent = None
            # 重置外部目标按钮，避免下次使用时产生混淆
            self._external_target_button = None
            
    def _on_menu_close(self, event):
        """
        菜单关闭事件处理
        """
        self._menu_visible = False
        # 断开按钮的leaveEvent
        self.main_button.leaveEvent = None
        # 调用原始的closeEvent
        super(CustomControlMenu, self.dropdown_menu).closeEvent(event)
        
    def _on_button_leave(self, event):
        """
        鼠标离开按钮事件
        """
        # 启动定时器，3秒后检查是否需要关闭菜单
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(3000, self._check_leave_and_close)
        # 调用父类的leaveEvent
        super(QPushButton, self.main_button).leaveEvent(event)
        
    def _on_menu_click(self, event):
        """
        菜单点击事件，处理点击外部区域关闭菜单
        """
        # 如果点击的是菜单内部，不处理
        if self.dropdown_menu.rect().contains(event.pos()):
            return
        # 否则关闭菜单
        self.hide_menu()
    
    def _on_item_clicked(self, item_data):
        """
        列表项点击事件处理
        
        Args:
            item_data: 点击的列表项数据
        """
        # 设置当前选中项
        self.set_current_item(item_data)
        # 触发信号
        self.itemClicked.emit(item_data)
        # 关闭菜单
        self.hide_menu()
    
    def _check_leave_and_close(self):
        """
        检查是否真正离开组件，并在离开3秒后关闭菜单
        """
        from PyQt5.QtGui import QCursor
        
        # 获取全局鼠标位置
        global_pos = QCursor.pos()
        
        # 检查鼠标是否在CustomDropdownMenu组件上
        widget_pos = self.mapToGlobal(QPoint(0, 0))
        widget_rect = QRect(widget_pos, self.size())
        if widget_rect.contains(global_pos):
            return
        
        # 检查鼠标是否在菜单上
        menu_pos = self.dropdown_menu.mapToGlobal(QPoint(0, 0))
        menu_rect = QRect(menu_pos, self.dropdown_menu.size())
        if menu_rect.contains(global_pos):
            return
        
        # 鼠标不在组件或菜单上，隐藏菜单
        self.hide_menu()
            
    def enterEvent(self, event):
        """
        鼠标进入组件事件
        """
        super().enterEvent(event)
        
    def leaveEvent(self, event):
        """
        鼠标离开组件事件
        """
        super().leaveEvent(event)
        
    def mousePressEvent(self, event):
        """
        鼠标按下事件
        """
        super().mousePressEvent(event)
        
    def resizeEvent(self, event):
        """
        窗口大小变化事件
        """
        super().resizeEvent(event)
        self._adjust_menu_size()
        
    def setStyleSheet(self, styleSheet):
        """
        设置样式表
        
        Args:
            styleSheet: 样式表字符串
        """
        # 只设置下拉菜单的样式表，不覆盖按钮自身的样式
        super().setStyleSheet(styleSheet)
        # 注意：不将样式表应用到main_button，保持其原有样式（如normal）
