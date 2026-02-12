#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 列表类自定义控件
包含各种列表类UI组件，如自定义选择列表项、自定义选择列表等
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QLabel, QSizePolicy, QApplication, QDialog, QLineEdit, 
    QScrollArea
)
from PySide6.QtCore import Qt, QPoint, Signal, QRect, QSize
from PySide6.QtGui import QFont, QColor, QPainter, QPen, QBrush, QIcon, QPixmap
from PySide6.QtWidgets import QGraphicsDropShadowEffect

from freeassetfilter.widgets.smooth_scroller import D_ScrollBar
from freeassetfilter.widgets.smooth_scroller import SmoothScroller

# 用于SVG渲染
from freeassetfilter.core.svg_renderer import SvgRenderer
import os


class CustomSelectListItem(QWidget):
    """
    自定义选择列表项组件
    """
    clicked = Signal(int)  # 单击信号，传递索引
    doubleClicked = Signal(int)  # 双击信号，传递索引
    
    def __init__(self, parent=None, index=0, text="", icon_path="", is_selected=False):
        super().__init__(parent)
        self.index = index
        self.text = text
        self.icon_path = icon_path
        self.is_selected = is_selected
        
        # 获取应用实例和DPI缩放因子
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 获取全局字体
        self.global_font = getattr(app, 'global_font', QFont())
        self.setFont(self.global_font)
        
        # 初始化UI
        self.init_ui()
    
    def init_ui(self):
        """
        初始化列表项UI
        """
        # 应用DPI缩放 - 紧凑布局
        scaled_icon_size = int(3 * self.dpi_scale)  # 图标大小
        item_margin = int(1.5 * self.dpi_scale)  # 条目边距（左右）
        text_margin = int(1 * self.dpi_scale)  # 文本边距
        
        # 主布局
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(item_margin, item_margin, item_margin, item_margin)
        main_layout.setSpacing(item_margin)
        
        # 图标标签
        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(scaled_icon_size, scaled_icon_size)
        self.icon_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.icon_label)
        
        # 文本容器 - 用于实现文本边距
        text_container = QWidget()
        text_container.setObjectName("textContainer")
        text_container_layout = QVBoxLayout(text_container)
        # 设置文本边距，应用缩放因子
        text_container_layout.setContentsMargins(text_margin, text_margin, text_margin, text_margin)
        text_container_layout.setSpacing(0)
        
        # 文本标签
        self.text_label = QLabel(self.text)
        self.text_label.setFont(self.global_font)
        self.text_label.setAlignment(Qt.AlignCenter)  # 居中显示
        self.text_label.setWordWrap(True)  # 允许文本换行
        self.text_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        text_container_layout.addWidget(self.text_label)
        
        main_layout.addWidget(text_container, 1)
        
        # 设置样式
        # 计算合适的高度：考虑字体高度、边距和图标大小
        font_metrics = self.text_label.fontMetrics()
        font_height = font_metrics.height()
        # 优化高度计算：减少额外空间
        min_height = int(max(font_height + 2 * (scaled_margin + text_margin), scaled_icon_size + 2 * scaled_margin) * self.dpi_scale)
        self.setMinimumHeight(min_height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.update_style()
        
        # 加载图标
        self.load_icon()
    
    def load_icon(self):
        """
        加载并显示图标
        """
        if not self.icon_path:
            self.icon_label.setVisible(False)
            return
        
        # 根据文件扩展名处理不同类型的图标
        ext = os.path.splitext(self.icon_path)[1].lower()
        
        if ext in ['.png', '.jpg', '.jpeg', '.bmp', '.ico']:
            # 加载位图图标
            pixmap = QPixmap(self.icon_path)
            if not pixmap.isNull():
                # 调整图标大小
                scaled_size = self.icon_label.size()
                pixmap = pixmap.scaled(scaled_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.icon_label.setPixmap(pixmap)
                self.icon_label.setVisible(True)
            else:
                self.icon_label.setVisible(False)
        elif ext == '.svg':
            # 使用项目中的SvgRenderer渲染SVG图标
            from freeassetfilter.core.svg_renderer import SvgRenderer
            scaled_size = self.icon_label.size().width()
            pixmap = SvgRenderer.render_svg_to_pixmap(self.icon_path, scaled_size, self.dpi_scale)
            if not pixmap.isNull():
                self.icon_label.setPixmap(pixmap)
                self.icon_label.setVisible(True)
            else:
                self.icon_label.setVisible(False)
        else:
            self.icon_label.setVisible(False)
    
    def update_style(self):
        """
        更新列表项样式
        支持未选中、hover、选中三种状态
        """
        from PySide6.QtGui import QColor

        app = QApplication.instance()
        settings_manager = getattr(app, 'settings_manager', None)

        accent_color = "#B036EE"
        base_color = "#ffffff"
        normal_color = "#808080"
        secondary_color = "#3F3F3F"
        auxiliary_color = "#E6E6E6"

        if settings_manager:
            accent_color = settings_manager.get_setting("appearance.colors.accent_color", accent_color)
            base_color = settings_manager.get_setting("appearance.colors.base_color", base_color)
            normal_color = settings_manager.get_setting("appearance.colors.normal_color", normal_color)
            secondary_color = settings_manager.get_setting("appearance.colors.secondary_color", secondary_color)
            auxiliary_color = settings_manager.get_setting("appearance.colors.auxiliary_color", auxiliary_color)

        qcolor = QColor(accent_color)
        r, g, b = qcolor.red(), qcolor.green(), qcolor.blue()
        selected_bg = f"rgba({r}, {g}, {b}, 102)"

        scaled_radius = int(1 * self.dpi_scale)  # 圆角半径进一步减小
        scaled_border = int(1 * self.dpi_scale)

        if self.is_selected:
            card_style = ""
            card_style += "QWidget {"
            card_style += f"background-color: {selected_bg};"
            card_style += f"border: {scaled_border}px solid {accent_color};"
            card_style += f"border-radius: {scaled_radius}px;"
            card_style += "}"
            card_style += "QWidget:hover {"
            card_style += f"background-color: {selected_bg};"
            card_style += f"border: {scaled_border}px solid {accent_color};"
            card_style += f"border-radius: {scaled_radius}px;"
            card_style += "}"
            self.setStyleSheet(card_style)

            self.text_label.setStyleSheet(f"""
                QLabel {{
                    color: {secondary_color};
                    background: transparent;
                    border: none;
                }}
            """.strip())
        else:
            card_style = ""
            card_style += "QWidget {"
            card_style += f"background-color: {base_color};"
            card_style += f"border: {scaled_border}px solid {auxiliary_color};"
            card_style += f"border-radius: {scaled_radius}px;"
            card_style += "}"
            card_style += "QWidget:hover {"
            card_style += f"background-color: {auxiliary_color};"
            card_style += f"border: {scaled_border}px solid {normal_color};"
            card_style += f"border-radius: {scaled_radius}px;"
            card_style += "}"
            self.setStyleSheet(card_style)

            self.text_label.setStyleSheet(f"""
                QLabel {{
                    color: {secondary_color};
                    background: transparent;
                    border: none;
                }}
            """.strip())
    
    def set_selected(self, selected):
        """
        设置列表项选中状态
        """
        self.is_selected = selected
        self.update_style()
    
    def mousePressEvent(self, event):
        """
        鼠标按下事件
        """
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.index)
        super().mousePressEvent(event)
    
    def mouseDoubleClickEvent(self, event):
        """
        鼠标双击事件
        """
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit(self.index)
        super().mouseDoubleClickEvent(event)
    
    def heightHint(self):
        """
        返回建议高度
        
        Returns:
            int: 建议高度
        """
        return self.minimumHeight()


class CustomSelectList(QWidget):
    """
    自定义选择列表组件
    特点：
    - 可滚动窗口
    - 自定义默认长宽、最小长宽
    - 选中项目为蓝色底（圆角）白色字，其余为白色底黑色字
    - 每个项目左侧可以有图标也可以没有图标
    - 支持png、svg（调用项目中的svgrender）、ico等图标格式
    - 具有单击事件和双击事件
    - 支持单选模式和多选模式
    """
    # 信号定义
    itemClicked = Signal(int)  # 单项点击信号，传递索引
    itemDoubleClicked = Signal(int)  # 单项双击信号，传递索引
    selectionChanged = Signal(list)  # 选择变化信号，传递选中索引列表
    
    def __init__(self, parent=None, default_width=75, default_height=50, min_width=50, min_height=37.5, selection_mode="single"):
        """
        初始化自定义选择列表
        
        Args:
            parent (QWidget): 父控件
            default_width (int): 默认宽度
            default_height (int): 默认高度
            min_width (int): 最小宽度
            min_height (int): 最小高度
            selection_mode (str): 选择模式，可选值："single"（单选）、"multiple"（多选）
        """
        super().__init__(parent)
        
        # 获取应用实例和DPI缩放因子
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 设置尺寸，应用DPI缩放
        self.default_width = int(default_width * self.dpi_scale)
        self.default_height = int(default_height * self.dpi_scale)
        self.min_width = int(min_width * self.dpi_scale)
        self.min_height = int(min_height * self.dpi_scale)
        
        # 选择模式
        self.selection_mode = selection_mode
        
        # 列表项数据
        self.items = []
        # 选中索引列表
        self.selected_indices = []
        
        # 获取全局字体
        self.global_font = getattr(app, 'global_font', QFont())
        self.setFont(self.global_font)
        
        # 初始化UI
        self.init_ui()
    
    def init_ui(self):
        """
        初始化自定义选择列表UI
        """
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 滚动区域
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        self.scroll_area.setVerticalScrollBar(D_ScrollBar(self.scroll_area, Qt.Vertical))
        self.scroll_area.verticalScrollBar().apply_theme_from_settings()
        
        SmoothScroller.apply_to_scroll_area(self.scroll_area)
        
        # 滚动区域内容控件
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)
        
        # 将内容控件设置到滚动区域
        self.scroll_area.setWidget(self.content_widget)
        main_layout.addWidget(self.scroll_area)
        
        # 设置尺寸策略，允许宽度自适应
        self.setMinimumWidth(self.min_width)
        self.setFixedHeight(self.default_height)
        
        # 根据需要显示滚动条
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    
    def add_item(self, text, icon_path=""):
        """
        添加列表项
        
        Args:
            text (str): 列表项文本
            icon_path (str): 图标路径，可选
        """
        index = len(self.items)
        
        # 创建列表项
        item_widget = CustomSelectListItem(self, index, text, icon_path)
        
        # 连接信号
        item_widget.clicked.connect(self._on_item_clicked)
        item_widget.doubleClicked.connect(self._on_item_double_clicked)
        
        # 添加到列表
        self.items.append(item_widget)
        self.content_layout.addWidget(item_widget)
        
        # 设置间距，应用DPI缩放 - 条目外边距
        scaled_spacing = int(1.5 * self.dpi_scale)
        self.content_layout.setSpacing(scaled_spacing)
        
        # 自动调整宽度以适应内容
        self.adjust_width_to_content()
    
    def add_items(self, items):
        """
        批量添加列表项
        
        Args:
            items (list): 列表项数据，每个元素可以是字符串或字典
                        字符串格式：仅文本
                        字典格式：{"text": "文本", "icon_path": "图标路径"}
        """
        for item in items:
            if isinstance(item, str):
                self.add_item(item)
            elif isinstance(item, dict):
                text = item.get("text", "")
                icon_path = item.get("icon_path", "")
                self.add_item(text, icon_path)
        
        # 批量添加后自动调整宽度
        self.adjust_width_to_content()
    
    def _on_item_clicked(self, index):
        """
        列表项点击事件处理
        """
        if self.selection_mode == "single":
            # 单选模式：取消所有选中，然后选中当前项
            for i, item in enumerate(self.items):
                item.set_selected(i == index)
            self.selected_indices = [index] if index < len(self.items) else []
        else:
            # 多选模式：切换当前项选中状态
            if index in self.selected_indices:
                self.selected_indices.remove(index)
                self.items[index].set_selected(False)
            else:
                self.selected_indices.append(index)
                self.items[index].set_selected(True)
        
        # 发出信号
        self.itemClicked.emit(index)
        self.selectionChanged.emit(self.selected_indices)
    
    def _on_item_double_clicked(self, index):
        """
        列表项双击事件处理
        """
        self.itemDoubleClicked.emit(index)
    
    def set_selection_mode(self, mode):
        """
        设置选择模式
        
        Args:
            mode (str): 选择模式，可选值："single"（单选）、"multiple"（多选）
        """
        self.selection_mode = mode
        # 重置选择状态
        self.clear_selection()
    
    def clear_selection(self):
        """
        清空选择
        """
        for item in self.items:
            item.set_selected(False)
        self.selected_indices.clear()
        self.selectionChanged.emit(self.selected_indices)
    
    def get_selected_indices(self):
        """
        获取选中索引列表
        
        Returns:
            list: 选中索引列表
        """
        return self.selected_indices.copy()

    def set_current_item(self, index):
        """
        设置当前选中项（单选模式）

        Args:
            index (int): 要选中的索引，-1表示不选中任何项
        """
        self.clear_selection()
        if 0 <= index < len(self.items):
            self.items[index].set_selected(True)
            self.selected_indices.append(index)
            self.selectionChanged.emit(self.selected_indices)

    def set_selected_indices(self, indices):
        """
        设置选中索引列表
        
        Args:
            indices (list): 要选中的索引列表
        """
        # 清空当前选择
        self.clear_selection()
        
        # 设置新选择
        for index in indices:
            if 0 <= index < len(self.items):
                self.items[index].set_selected(True)
                self.selected_indices.append(index)
        
        # 发出信号
        self.selectionChanged.emit(self.selected_indices)
    
    def clear_items(self):
        """
        清空所有列表项
        """
        # 移除所有列表项
        for item in self.items:
            self.content_layout.removeWidget(item)
            item.deleteLater()
        
        # 清空数据
        self.items.clear()
        self.selected_indices.clear()
        
        # 发出信号
        self.selectionChanged.emit(self.selected_indices)
        
        # 清空后调整宽度到最小值
        self.adjust_width_to_content()
    
    def set_default_size(self, width, height):
        """
        设置默认尺寸

        Args:
            width (int): 默认宽度
            height (int): 默认高度
        """
        self.default_width = int(width * self.dpi_scale)
        self.default_height = int(height * self.dpi_scale)
        self.setFixedHeight(self.default_height)

    def set_minimum_size(self, width, height):
        """
        设置最小尺寸

        Args:
            width (int): 最小宽度
            height (int): 最小高度
        """
        self.min_width = int(width * self.dpi_scale)
        self.min_height = int(height * self.dpi_scale)
        self.setMinimumWidth(self.min_width)
        self.setFixedHeight(self.min_height)
    
    def adjust_width_to_content(self):
        """
        根据内容自动调整宽度
        计算所有列表项中最长的文本，并据此调整控件宽度
        """
        if not self.items:
            # 如果没有项目，使用最小宽度
            self.setFixedWidth(self.min_width)
            return
        
        # 计算所需宽度
        calculated_width = self._calculate_content_width()
        
        # 应用计算出的宽度
        self.setFixedWidth(calculated_width)
    
    def _calculate_content_width(self):
        """
        计算内容所需宽度
        
        Returns:
            int: 计算出的宽度
        """
        from PySide6.QtGui import QFontMetrics
        
        app = QApplication.instance()
        dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        global_font = getattr(app, 'global_font', QFont())
        
        font_metrics = QFontMetrics(global_font)
        
        max_text_width = 0
        has_icon = False
        
        # 遍历所有项目，找到最长的文本
        for item in self.items:
            text = item.text if hasattr(item, 'text') else ""
            if text:
                # 计算文本宽度（考虑换行，取最长的一行）
                lines = text.split('\n')
                for line in lines:
                    text_width = font_metrics.horizontalAdvance(line)
                    max_text_width = max(max_text_width, text_width)
            
            # 检查是否有图标
            if hasattr(item, 'icon_path') and item.icon_path:
                has_icon = True
        
        # 使用与CustomSelectListItem一致的极紧凑布局参数
        icon_size = int(3 * dpi_scale) if has_icon else 0  # 图标大小
        margin = int(0 * dpi_scale)  # 外部边距
        text_margin = int(1 * dpi_scale)  # 文本容器边距
        
        # 总宽度 = 左边距 + 图标宽度 + 图标间距 + 左文本边距 + 文本宽度 + 右文本边距 + 右边距
        calculated_width = margin * 2  # 左右边距
        if has_icon:
            calculated_width += icon_size + margin  # 图标宽度 + 图标与文本间距
        calculated_width += text_margin * 2  # 文本容器左右边距
        calculated_width += max_text_width  # 文本宽度
        
        # 确保宽度不小于最小宽度和默认宽度
        calculated_width = max(calculated_width, self.min_width, self.default_width)
        
        return calculated_width
    
    def sizeHint(self):
        """
        返回建议尺寸
        
        Returns:
            QSize: 建议尺寸
        """
        app = QApplication.instance()
        dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        global_font = getattr(app, 'global_font', QFont())
        
        from PySide6.QtGui import QFontMetrics
        font_metrics = QFontMetrics(global_font)
        
        max_text_width = 0
        total_height = 0
        
        if self.items:
            for item in self.items:
                text = item.text if hasattr(item, 'text') else ""
                if text:
                    # 计算文本宽度（考虑换行，取最长的一行）
                    lines = text.split('\n')
                    for line in lines:
                        text_width = font_metrics.horizontalAdvance(line)
                        max_text_width = max(max_text_width, text_width)
                
                item_height = item.heightHint() if hasattr(item, 'heightHint') else item.minimumHeight()
                total_height += item_height
        
        # 使用计算内容宽度的方法来获取精确的宽度
        calculated_width = self._calculate_content_width()
        
        # 计算总高度（包括项目间距）
        if self.items:
            spacing = int(1 * dpi_scale)
            total_height += spacing * (len(self.items) - 1)
        
        calculated_height = max(total_height, self.min_height, self.default_height)
        
        return QSize(calculated_width, calculated_height)
