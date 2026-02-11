#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 输入类自定义控件
包含各种输入类UI组件，如自定义输入框等
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QLabel, QSizePolicy, QApplication, QDialog, QLineEdit, 
    QScrollArea
)
from PyQt5.QtCore import Qt, QPoint, pyqtSignal, QRect, QSize, QRectF
from PyQt5.QtGui import QFont, QColor, QPainter, QPen, QBrush, QIcon, QPixmap
from PyQt5.QtWidgets import QGraphicsDropShadowEffect

from .D_more_menu import D_MoreMenu


class CustomInputBox(QWidget):
    """
    自定义输入框控件
    特点：
    - 支持默认显示文本（占位符）
    - 点击激活功能
    - 清晰的视觉反馈（激活/未激活状态、有内容/无内容状态）
    - 支持传入初始文本
    - 提供内容传出机制
    - 可自定义样式（边框、圆角、背景色、尺寸等）
    """
    
    # 内容变化信号，当输入内容改变时发出
    textChanged = pyqtSignal(str)
    # 焦点变化信号，当控件获得或失去焦点时发出
    focusChanged = pyqtSignal(bool)
    # 编辑完成信号，当用户按下回车键或失去焦点时发出
    editingFinished = pyqtSignal(str)
    
    def __init__(self,
                 parent=None,
                 placeholder_text="",
                 initial_text="",
                 width=None,
                 height=20,
                 border_radius=10,
                 border_color="#f1f3f5",  # 使用auxiliary_color
                 background_color="#ffffff",  # 使用base_color
                 text_color="#333333",  # 使用secondary_color
                 placeholder_color="#e0e0e0",  # 使用normal_color
                 active_border_color="#007AFF",  # 使用accent_color
                 active_background_color="#ffffff",  # 使用base_color
                 editable=True):  # 是否可编辑
        """
        初始化自定义输入框

        Args:
            parent (QWidget): 父控件
            placeholder_text (str): 默认显示文本（占位符）
            initial_text (str): 初始输入文本
            width (int): 控件宽度
            height (int): 控件高度，默认为40px，与CustomButton保持一致
            border_radius (int): 边框圆角半径
            border_color (str): 边框颜色
            background_color (str): 背景颜色
            text_color (str): 文本颜色
            placeholder_color (str): 占位符文本颜色
            active_border_color (str): 激活状态下的边框颜色
            active_background_color (str): 激活状态下的背景颜色
            editable (bool): 是否可编辑，默认可编辑
        """
        super().__init__(parent)

        # 获取应用实例和DPI缩放因子
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)

        # 设置基本属性
        self.placeholder_text = placeholder_text
        self._is_active = False
        self._has_content = False
        self._editable = editable  # 是否可编辑标志
        
        # 尝试从应用实例获取主题颜色
        use_theme_colors = False
        theme_border_color = border_color
        theme_background_color = background_color
        theme_text_color = text_color
        theme_placeholder_color = placeholder_color
        theme_active_border_color = active_border_color
        theme_active_background_color = active_background_color
        
        if hasattr(app, 'settings_manager'):
            use_theme_colors = True
            theme_border_color = app.settings_manager.get_setting("appearance.colors.input_border", border_color)
            theme_background_color = app.settings_manager.get_setting("appearance.colors.input_background", background_color)
            theme_text_color = app.settings_manager.get_setting("appearance.colors.input_text", text_color)
            theme_placeholder_color = app.settings_manager.get_setting("appearance.colors.text_placeholder", placeholder_color)
            theme_active_border_color = app.settings_manager.get_setting("appearance.colors.input_focus_border", active_border_color)
            theme_active_background_color = app.settings_manager.get_setting("appearance.colors.input_background", active_background_color)
        
        # 样式参数，应用DPI缩放
        self._width = int(width * self.dpi_scale) if width else None
        self._height = int(height * self.dpi_scale)
        self._border_radius = int(border_radius * self.dpi_scale)
        self._border_color = QColor(theme_border_color)
        self._background_color = QColor(theme_background_color)
        self._text_color = QColor(theme_text_color)
        self._placeholder_color = QColor(theme_placeholder_color)
        self._active_border_color = QColor(theme_active_border_color)
        self._active_background_color = QColor(theme_active_background_color)
        
        # 获取全局字体
        self.global_font = getattr(app, 'global_font', QFont())
        
        # 初始化UI
        self.init_ui()

        # 设置初始文本
        if initial_text:
            self.line_edit.setText(initial_text)
            self._has_content = True

        # 初始化右键菜单
        self._init_context_menu()
    
    def init_ui(self):
        """
        初始化UI组件
        """
        # 设置主布局
        main_layout = QVBoxLayout(self)
        # 设置布局边距，确保边框能显示
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 从app对象获取全局默认字体大小
        app = QApplication.instance()
        default_font_size = getattr(app, 'default_font_size', 9)
        
        # 应用DPI缩放因子到输入框样式
        scaled_padding = f"{int(4 * self.dpi_scale)}px {int(6 * self.dpi_scale)}px"
        scaled_font_size = int(default_font_size * self.dpi_scale)
        
        # 创建QLineEdit作为实际输入控件
        self.line_edit = QLineEdit()
        self.line_edit.setFont(self.global_font)
        self.line_edit.setPlaceholderText(self.placeholder_text)
        # 为line_edit添加内部边距，确保不会覆盖父控件的边框
        # 获取主题文本颜色
        text_color = "#333333"  # 使用secondary_color
        
        # 尝试从应用实例获取主题颜色
        app = QApplication.instance()
        if hasattr(app, 'settings_manager'):
            text_color = app.settings_manager.get_setting("appearance.colors.input_text", "#000000")
        
        self.line_edit.setStyleSheet("""
            QLineEdit {
                background-color: transparent;
                border: none;
                color: %s;
                font-size: %dpx;
                padding: %s;
                margin: 0px;
            }
            QLineEdit:focus {
                outline: none;
            }
        """ % (text_color, scaled_font_size, scaled_padding))
        
        # 连接信号
        self.line_edit.textChanged.connect(self._on_text_changed)
        self.line_edit.focusInEvent = lambda event: self._on_focus_in(event)
        self.line_edit.focusOutEvent = lambda event: self._on_focus_out(event)
        self.line_edit.returnPressed.connect(self._on_return_pressed)
        
        # 设置当前控件尺寸
        if self._width:
            self.setFixedWidth(self._width)
        self.setFixedHeight(self._height)
        
        # 添加到布局，通过布局管理line_edit大小
        main_layout.addWidget(self.line_edit)
        
        # 强制更新样式，确保边框显示
        self.update_style()
        self.repaint()
    
    def _on_text_changed(self, text):
        """
        文本变化事件处理
        """
        self._has_content = bool(text)
        self.update_style()
        self.textChanged.emit(text)
    
    def _on_focus_in(self, event):
        """
        获得焦点事件处理
        """
        self._is_active = True
        self.update_style()
        self.focusChanged.emit(True)
        # 调用原始的focusInEvent
        QLineEdit.focusInEvent(self.line_edit, event)
    
    def _on_focus_out(self, event):
        """
        失去焦点事件处理
        """
        self._is_active = False
        self.update_style()
        self.focusChanged.emit(False)
        # 发出编辑完成信号
        self.editingFinished.emit(self.line_edit.text())
        # 调用原始的focusOutEvent
        QLineEdit.focusOutEvent(self.line_edit, event)
    
    def _on_return_pressed(self):
        """
        回车键按下事件处理
        """
        self.editingFinished.emit(self.line_edit.text())
    
    def update_style(self):
        """
        更新输入框样式
        """
        # 更新样式后触发重绘
        self.update()
    
    def paintEvent(self, event):
        """
        绘制控件外观
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)  # 启用抗锯齿
        
        # 根据状态选择颜色
        if self._is_active:
            border_color = self._active_border_color
            background_color = self._active_background_color
        else:
            border_color = self._border_color
            background_color = self._background_color
        
        # 边框宽度设置为1，应用DPI缩放
        scaled_border_width = int(1 * self.dpi_scale)
        
        # 绘制背景矩形 - 使用整个控件区域，确保不会出现间隙
        rect = self.rect()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(background_color))
        painter.drawRoundedRect(rect, self._border_radius, self._border_radius)
        
        # 绘制边框 - 调整矩形以确保边框完全显示，不会被裁剪
        # 使用QRectF来确保更高的精度，避免浮点数计算误差
        border_rect = QRectF(self.rect())
        # 向内收缩边框宽度的一半，确保边框居中且完全可见
        border_rect.adjust(scaled_border_width / 2, scaled_border_width / 2, -scaled_border_width / 2, -scaled_border_width / 2)
        
        painter.setPen(QPen(border_color, scaled_border_width))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(border_rect, self._border_radius, self._border_radius)
    
    def set_text(self, text):
        """
        设置输入框文本
        
        Args:
            text (str): 要设置的文本
        """
        self.line_edit.setText(text)
        self._has_content = bool(text)
        self.update_style()
    
    def get_text(self):
        """
        获取输入框当前文本
        
        Returns:
            str: 当前输入框文本
        """
        return self.line_edit.text()
    
    def clear_text(self):
        """
        清空输入框文本
        """
        self.line_edit.clear()
        self._has_content = False
        self.update_style()
    
    def set_placeholder_text(self, text):
        """
        设置占位符文本
        
        Args:
            text (str): 占位符文本
        """
        self.placeholder_text = text
        self.line_edit.setPlaceholderText(text)
    
    def get_placeholder_text(self):
        """
        获取占位符文本
        
        Returns:
            str: 占位符文本
        """
        return self.placeholder_text
    
    def set_focus(self):
        """
        设置输入框获得焦点
        """
        self.line_edit.setFocus()
    
    def has_focus(self):
        """
        检查输入框是否获得焦点
        
        Returns:
            bool: 是否获得焦点
        """
        return self._is_active
    
    def has_content(self):
        """
        检查输入框是否有内容
        
        Returns:
            bool: 是否有内容
        """
        return self._has_content
    
    def setText(self, text):
        """
        设置输入框文本（Qt兼容接口）

        Args:
            text (str): 要设置的文本
        """
        self.set_text(text)

    def text(self):
        """
        获取输入框当前文本（Qt兼容接口）

        Returns:
            str: 当前输入框文本
        """
        return self.get_text()

    def set_editable(self, editable):
        """
        设置输入框是否可编辑

        Args:
            editable (bool): 是否可编辑
        """
        self._editable = editable
        self.line_edit.setReadOnly(not editable)

    def is_editable(self):
        """
        获取输入框是否可编辑

        Returns:
            bool: 是否可编辑
        """
        return self._editable

    def _init_context_menu(self):
        """
        初始化右键菜单
        使用D_MoreMenu实现复制、剪切、粘贴、全选功能
        对于不可编辑项目，只显示复制、全选
        """
        self._context_menu = D_MoreMenu(self)
        self._context_menu.itemClicked.connect(self._on_context_menu_item_clicked)

        # 设置右键菜单策略
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.line_edit.setContextMenuPolicy(Qt.NoContextMenu)  # 禁用原生右键菜单

        # 保存选区信息
        self._saved_selection_start = 0
        self._saved_selection_end = 0
        self._has_selection = False

    def _show_context_menu(self, pos):
        """
        显示右键菜单

        Args:
            pos: 鼠标位置
        """
        # 保存当前选区信息
        self._saved_selection_start = self.line_edit.selectionStart()
        self._saved_selection_end = self.line_edit.selectionEnd()
        self._has_selection = self.line_edit.hasSelectedText()

        # 清空现有菜单项
        self._context_menu.clear_items()

        # 检查QLineEdit的实际只读状态
        is_readonly = self.line_edit.isReadOnly()

        # 根据是否可编辑添加不同的菜单项
        if is_readonly:
            # 不可编辑状态：只显示复制、全选
            self._context_menu.add_item("复制", "copy")
            self._context_menu.add_item("全选", "select_all")
        else:
            # 可编辑状态：显示复制、剪切、粘贴、全选
            self._context_menu.add_item("复制", "copy")
            self._context_menu.add_item("剪切", "cut")
            self._context_menu.add_item("粘贴", "paste")
            self._context_menu.add_item("全选", "select_all")

        # 在鼠标位置显示菜单
        global_pos = self.mapToGlobal(pos)
        self._context_menu.popup(global_pos)

    def _on_context_menu_item_clicked(self, action):
        """
        处理右键菜单项点击事件

        Args:
            action: 菜单项动作标识
        """
        is_readonly = self.line_edit.isReadOnly()

        if action == "copy":
            # 如果用户已有选区，恢复选区后复制；否则全选复制
            if self._has_selection:
                self.line_edit.setSelection(self._saved_selection_start, self._saved_selection_end - self._saved_selection_start)
            else:
                self.line_edit.selectAll()
            self.line_edit.copy()
        elif action == "cut":
            if not is_readonly:
                if self._has_selection:
                    self.line_edit.setSelection(self._saved_selection_start, self._saved_selection_end - self._saved_selection_start)
                else:
                    self.line_edit.selectAll()
                self.line_edit.cut()
        elif action == "paste":
            if not is_readonly:
                self.line_edit.paste()
        elif action == "select_all":
            self.line_edit.selectAll()
