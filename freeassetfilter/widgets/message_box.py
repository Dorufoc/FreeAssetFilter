#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 窗口类自定义控件
包含各种窗口类UI组件，如自定义窗口、自定义消息框等
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QLabel, QSizePolicy, QApplication, QDialog, QLineEdit, 
    QScrollArea
)
from PyQt5.QtCore import Qt, QPoint, pyqtSignal, QRect, QSize
from PyQt5.QtGui import QFont, QColor, QPainter, QPen, QBrush, QIcon, QPixmap
from PyQt5.QtWidgets import QGraphicsDropShadowEffect

# 导入自定义列表组件
from .list_widgets import CustomSelectList
# 导入自定义输入框组件
from .input_widgets import CustomInputBox


class CustomWindow(QWidget):
    """
    自定义窗口组件
    特点：
    - 纯白圆角矩形外观
    - 右上角圆形关闭按钮
    - 可拖拽移动
    - 支持内嵌其他控件
    - 可通过拖动边缘或四角调整大小
    """
    
    def __init__(self, title="Custom Window", parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # 窗口标题
        self.title = title
        
        # 拖拽相关变量
        self.dragging = False
        self.drag_position = QPoint()
        
        # 调整大小相关变量
        self.resizing = False
        self.resize_direction = ""
        self.resize_start_pos = QPoint()
        self.resize_start_size = None
        self.resize_start_geometry = None
        
        # 获取应用实例和DPI缩放因子
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 增加边框宽度，便于用户抓住边缘和角落，并应用DPI缩放
        self.border_size = 0
        
        # 获取全局字体
        self.global_font = getattr(app, 'global_font', QFont())
        self.setFont(self.global_font)
        
        # 初始化UI
        self.init_ui()
        
    def init_ui(self):
        """
        初始化自定义窗口UI
        """
        # 应用DPI缩放因子
        scaled_margin = int(2.5 * self.dpi_scale)
        scaled_radius = int(1.5 * self.dpi_scale)
        self.scaled_title_height = int(5 * self.dpi_scale)
        scaled_shadow_radius = int(2.5 * self.dpi_scale)
        scaled_shadow_offset = int(1 * self.dpi_scale)
        
        # 设置默认大小（调整为原始的一半）
        self.setMinimumSize(100, 75)
        self.resize(100, 75)
        
        # 主布局（用于容纳内容和装饰）
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(scaled_margin, scaled_margin, scaled_margin, scaled_margin)
        main_layout.setSpacing(0)
        
        # 创建窗口主体（带圆角）
        self.window_body = QWidget()
        
        # 获取主题颜色
        app = QApplication.instance()
        window_bg_color = "#ffffff"  # 默认白色
        window_border_color = "#ffffff"  # 默认白色
        
        # 尝试从应用实例获取主题颜色
        if hasattr(app, 'settings_manager'):
            window_bg_color = app.settings_manager.get_setting("appearance.colors.window_background", "#ffffff")
            window_border_color = app.settings_manager.get_setting("appearance.colors.window_border", "#ffffff")
        
        self.window_body.setStyleSheet(f"""
            QWidget {{
                background-color: {window_bg_color};
                border-radius: {scaled_radius}px;
                border: 1px solid {window_border_color};
            }}
        """)
        
        # 添加阴影效果
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(scaled_shadow_radius)
        shadow.setOffset(0, scaled_shadow_offset)
        shadow.setColor(QColor(0, 0, 0, 60))
        self.window_body.setGraphicsEffect(shadow)
        
        # 窗口主体布局
        body_layout = QVBoxLayout(self.window_body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        
        # 标题栏
        title_bar = QWidget()
        title_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        title_bar.setMinimumHeight(self.scaled_title_height)
        title_bar.setMaximumHeight(self.scaled_title_height)
        title_bar.setStyleSheet("""
            QWidget {
                background-color: transparent;
            }
        """)
        
        title_layout = QHBoxLayout(title_bar)
        # 应用DPI缩放因子到边距和间距
        scaled_left_margin = int(2 * self.dpi_scale)
        scaled_right_margin = int(2 * self.dpi_scale)
        scaled_spacing = int(2 * self.dpi_scale)
        title_layout.setContentsMargins(scaled_left_margin, 0, scaled_right_margin, 0)
        title_layout.setSpacing(scaled_spacing)
        
        # 标题标签
        title_label = QLabel(self.title)
        # 从app对象获取全局默认字体大小
        app = QApplication.instance()
        default_font_size = getattr(app, 'default_font_size', 9)
        scaled_font_size = int(default_font_size * self.dpi_scale)
        title_label.setFont(self.global_font)
        title_label.setStyleSheet(f"""
            QLabel {{
                font-size: {scaled_font_size}px;
                font-weight: 500;
                color: #000000;
            }}
        """)
        title_layout.addWidget(title_label, 1)
        
        # 关闭按钮
        # 使用CustomButton代替QPushButton以确保一致性和DPI缩放兼容性
        from .button_widgets import CustomButton
        self.close_button = CustomButton("×", button_type="primary", display_mode="text", height=12)
        self.close_button.setFixedSize(int(6 * self.dpi_scale), int(6 * self.dpi_scale))
        self.close_button.clicked.connect(self.close)
        title_layout.addWidget(self.close_button)
        
        # 内容区域
        self.content_widget = QWidget()
        self.content_widget.setStyleSheet("""
            QWidget {
                background-color: transparent;
            }
        """)
        
        self.content_layout = QVBoxLayout(self.content_widget)
        # 应用DPI缩放因子到内容区域边距和间距
        scaled_content_margin = int(2 * self.dpi_scale)
        scaled_content_top_margin = int(2 * self.dpi_scale)
        scaled_content_spacing = int(1.5 * self.dpi_scale)
        self.content_layout.setContentsMargins(scaled_content_margin, scaled_content_top_margin, scaled_content_margin, scaled_content_margin)
        self.content_layout.setSpacing(scaled_content_spacing)
        
        # 将标题栏和内容区域添加到窗口主体布局
        body_layout.addWidget(title_bar)
        body_layout.addWidget(self.content_widget, 1)
        
        # 将窗口主体添加到主布局
        main_layout.addWidget(self.window_body)
    
    def _get_resize_direction(self, pos):
        """
        根据鼠标位置判断调整大小的方向
        
        Args:
            pos (QPoint): 鼠标位置
            
        Returns:
            str: 调整方向，如"top", "bottom", "left", "right", "top-left", "top-right", "bottom-left", "bottom-right"或空字符串
        """
        x, y = pos.x(), pos.y()
        width, height = self.width(), self.height()
        
        # 考虑DPI和分辨率，确保边缘检测准确
        # 增加边框宽度，提高检测灵敏度
        actual_border_size = self.border_size
        
        # 检查是否在边缘
        on_left = x <= actual_border_size
        on_right = x >= width - actual_border_size
        on_top = y <= actual_border_size
        on_bottom = y >= height - actual_border_size
        
        # 判断方向
        direction = ""
        if on_top:
            direction += "top-"
        elif on_bottom:
            direction += "bottom-"
        
        if on_left:
            direction += "left"
        elif on_right:
            direction += "right"
        
        # 移除末尾的连字符（如果有的话）
        direction = direction.rstrip("-")
        
        return direction
    
    
    def mousePressEvent(self, event):
        """
        鼠标按下事件，用于实现窗口拖拽和调整大小
        """
        if event.button() == Qt.LeftButton:
            # 获取鼠标位置
            pos = event.pos()
            
            # 检查是否在调整大小的边缘
            direction = self._get_resize_direction(pos)
            if direction:
                # 开始调整大小
                self.resizing = True
                self.resize_direction = direction
                self.resize_start_pos = event.globalPos()
                self.resize_start_size = self.size()
                self.resize_start_geometry = self.geometry()
                event.accept()
            elif pos.y() < self.scaled_title_height:  # 标题栏区域，使用缩放后的高度
                # 开始拖动
                self.dragging = True
                # 使用鼠标全局位置减去窗口左上角位置，避免频繁调用frameGeometry()
                self.drag_position = event.globalPos() - self.pos()
                event.accept()
    
    def mouseMoveEvent(self, event):
        """
        鼠标移动事件，用于实现窗口拖拽和调整大小
        优化：减少重绘次数，提高拖动流畅度
        """
        if self.resizing:
            # 处理调整大小
            delta = event.globalPos() - self.resize_start_pos
            
            # 保存初始几何形状
            orig_x = self.resize_start_geometry.x()
            orig_y = self.resize_start_geometry.y()
            orig_width = self.resize_start_geometry.width()
            orig_height = self.resize_start_geometry.height()
            
            # 初始化新的位置和大小
            new_x = orig_x
            new_y = orig_y
            new_width = orig_width
            new_height = orig_height
            
            # 根据方向调整大小和位置
            if "right" in self.resize_direction:
                new_width = orig_width + delta.x()
            if "left" in self.resize_direction:
                new_width = orig_width - delta.x()
                new_x = orig_x + delta.x()
            if "bottom" in self.resize_direction:
                new_height = orig_height + delta.y()
            if "top" in self.resize_direction:
                new_height = orig_height - delta.y()
                new_y = orig_y + delta.y()
            
            # 设置最小大小限制
            min_width, min_height = 100, 75
            new_width = max(min_width, new_width)
            new_height = max(min_height, new_height)
            
            # 处理边界情况：当窗口达到最小值时，调整位置
            if new_width == min_width:
                if "left" in self.resize_direction:
                    # 左侧调整达到最小值，固定左侧位置
                    new_x = orig_x + orig_width - min_width
            
            if new_height == min_height:
                if "top" in self.resize_direction:
                    # 顶部调整达到最小值，固定顶部位置
                    new_y = orig_y + orig_height - min_height
            
            # 更新窗口几何形状
            self.setGeometry(new_x, new_y, new_width, new_height)
            event.accept()
        elif self.dragging:
            # 处理拖动
            # 直接计算新位置，避免频繁调用frameGeometry()
            new_pos = event.globalPos() - self.drag_position
            # 使用move方法移动窗口，这是最高效的方式
            self.move(new_pos)
            event.accept()
    
    def mouseReleaseEvent(self, event):
        """
        鼠标释放事件，用于结束窗口拖拽或调整大小
        """
        self.dragging = False
        self.resizing = False

    def resizeEvent(self, event):
        """
        窗口大小变化事件
        当窗口大小变化时，检查是否需要更新DPI缩放因子
        """
        super().resizeEvent(event)
        
        # 获取应用实例和最新的DPI缩放因子
        app = QApplication.instance()
        new_dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 如果DPI缩放因子发生变化，更新窗口样式
        if new_dpi_scale != self.dpi_scale:
            self.dpi_scale = new_dpi_scale
            # 重新初始化UI以应用新的DPI缩放因子
            self.init_ui()
    
    def add_widget(self, widget):
        """
        向窗口添加控件
        
        Args:
            widget (QWidget): 要添加的控件
        """
        self.content_layout.addWidget(widget)
    
    def add_layout(self, layout):
        """
        向窗口添加布局
        
        Args:
            layout (QLayout): 要添加的布局
        """
        self.content_layout.addLayout(layout)
    
    def set_title(self, title):
        """
        设置窗口标题
        
        Args:
            title (str): 窗口标题
        """
        self.title = title
        # 更新标题标签
        if hasattr(self, 'window_body'):
            title_bar = self.window_body.layout().itemAt(0).widget()
            title_layout = title_bar.layout()
            title_label = title_layout.itemAt(0).widget()
            title_label.setText(title)



    """
    主题设置窗口组件
    特点：
    - 使用原生窗口样式
    - 包含颜色选择器和控件预览区域
    - 实现颜色选择功能，允许用户自定义各种颜色
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 设置窗口标志，确保不使用WindowStaysOnTopHint
        self.setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.WindowSystemMenuHint | Qt.WindowCloseButtonHint)
        
        # 设置窗口标题
        self.setWindowTitle("主题设置")
        
        # 获取应用实例和设置管理器
        app = QApplication.instance()
        self.settings_manager = getattr(app, 'settings_manager', None)
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 设置窗口大小，应用DPI缩放（调整为原始的一半）
        self.setMinimumSize(int(75 * self.dpi_scale), int(62.5 * self.dpi_scale))
        self.resize(int(75 * self.dpi_scale), int(62.5 * self.dpi_scale))
        
        # 获取当前主题颜色
        if self.settings_manager:
            self.current_colors = self.settings_manager.get_setting("appearance.colors")
        else:
            # 使用默认颜色
            self.current_colors = {
                "window_background": "#1E1E1E",
                "text_normal": "#FFFFFF",
                "input_background": "#2D2D2D",
                "input_text": "#FFFFFF",
                "list_background": "#1E1E1E",
                "list_item_normal": "#2D2D2D",
                "list_item_text": "#FFFFFF"
            }
        
        # 创建主布局
        self.main_layout = QVBoxLayout(self)
        
        # 计算颜色
        self._calculate_colors()
        
        # 初始化UI
        self.init_theme_ui()
    
    def init_theme_ui(self):
        """
        初始化主题设置窗口UI
        """
        # 应用DPI缩放因子
        scaled_padding = int(2 * self.dpi_scale)
        scaled_spacing = int(3 * self.dpi_scale)
        
        # 创建主滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QScrollBar {
                background-color: transparent;
            }
            QScrollBar::vertical {
                width: 4px;
                background-color: transparent;
            }
            QScrollBar::horizontal {
                height: 4px;
                background-color: transparent;
            }
            QScrollBar::handle {
                background-color: #888;
                border-radius: 1px;
            }
            QScrollBar::handle:hover {
                background-color: #aaa;
            }
        """)
        
        # 滚动区域内容
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(scaled_padding, scaled_padding, scaled_padding, scaled_padding)
        scroll_layout.setSpacing(scaled_spacing)
        
        # 添加基础颜色配置区域
        self._add_color_section(scroll_layout, "基础颜色配置", [
            ("accent_color", "强调色"),
            ("secondary_color", "次选色"),
            ("normal_color", "普通色"),
            ("auxiliary_color", "辅助色"),
            ("base_color", "底层色")
        ])
        
        # 添加控件预览区域
        self._add_preview_section(scroll_layout)
        
        # 添加保存按钮
        from .button_widgets import CustomButton
        save_button = CustomButton("保存主题设置", button_type="primary", display_mode="text")
        save_button.clicked.connect(self.save_theme_settings)
        scroll_layout.addWidget(save_button)
        
        # 设置滚动区域
        scroll_area.setWidget(scroll_content)
        self.main_layout.addWidget(scroll_area)
    
    def _add_color_section(self, layout, title, color_items):
        """
        添加颜色配置区域
        
        Args:
            layout (QLayout): 父布局
            title (str): 区域标题
            color_items (list): 颜色配置项列表，每个项为元组 (color_key, color_name)
        """
        # 应用DPI缩放因子
        scaled_margin = int(8 * self.dpi_scale)
        scaled_spacing = int(8 * self.dpi_scale)
        scaled_border_radius = int(2 * self.dpi_scale)
        
        # 创建区域容器
        section_widget = QWidget()
        section_widget.setStyleSheet(f"""
            QWidget {{
                background-color: #f5f5f5;
                border-radius: {scaled_border_radius}px;
                padding: {scaled_margin}px;
            }}
        """)
        section_layout = QVBoxLayout(section_widget)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(scaled_spacing)
        
        # 添加标题
        title_label = QLabel(title)
        # 从应用实例获取全局默认字体大小和DPI缩放因子
        app = QApplication.instance()
        default_font_size = getattr(app, 'default_font_size', 16)
        scaled_font_size = int(default_font_size * self.dpi_scale)
        title_label.setStyleSheet(f"""
            QLabel {{ 
                font-size: {scaled_font_size}px;
                font-weight: 500;
                color: #333333;
                margin-bottom: 8px;
            }}
        """)
        section_layout.addWidget(title_label)
        
        # 添加颜色配置项
        for color_key, color_name in color_items:
            self._add_color_item(section_layout, color_key, color_name)
        
        # 将区域添加到父布局
        layout.addWidget(section_widget)
    
    def _add_color_item(self, layout, color_key, color_name):
        """
        添加颜色配置项
        
        Args:
            layout (QLayout): 父布局
            color_key (str): 颜色配置键
            color_name (str): 颜色配置名称
        """
        # 创建颜色配置项布局
        item_layout = QHBoxLayout()
        item_layout.setContentsMargins(0, 0, 0, 0)
        item_layout.setSpacing(4)
        
        # 颜色名称标签
        name_label = QLabel(color_name)
        # 从应用实例获取全局默认字体大小和DPI缩放因子
        app = QApplication.instance()
        default_font_size = getattr(app, 'default_font_size', 14)
        scaled_font_size = int(default_font_size * self.dpi_scale * 0.875)  # 14px 是 16px 的 0.875
        name_label.setStyleSheet(f"""
            QLabel {{ 
                font-size: {scaled_font_size}px;
                color: #333333;
                min-width: 120px;
            }}
        """)
        item_layout.addWidget(name_label)
        
        # 颜色显示框
        color_display = QWidget()
        color_display.setFixedSize(10, 6)
        color_display.setStyleSheet(f"""
            QWidget {{
                background-color: {self.current_colors.get(color_key, '#ffffff')};
                border: 1px solid #cccccc;
                border-radius: 2px;
            }}
        """)
        
        # 设置鼠标样式为可点击
        color_display.setCursor(Qt.PointingHandCursor)
        
        # 存储颜色键
        color_display.setProperty("color_key", color_key)
        
        # 添加点击事件
        color_display.mousePressEvent = lambda event: self._select_color(color_key)
        item_layout.addWidget(color_display)
        
        # 颜色值输入框
        from .input_widgets import CustomInputBox
        color_value = CustomInputBox(
            initial_text=self.current_colors.get(color_key, '#ffffff'),
            width=25,
            height=6,
            border_radius=2,
            border_color="#cccccc",
            background_color="#ffffff",
            text_color="#666666",
            placeholder_color="#999999",
            active_border_color="#0078d4",
            active_background_color="#ffffff"
        )
        
        # 设置等宽字体
        # 从应用实例获取全局默认字体大小和DPI缩放因子
        app = QApplication.instance()
        default_font_size = getattr(app, 'default_font_size', 14)
        scaled_font_size = int(default_font_size * self.dpi_scale * 0.875)  # 14px 是 16px 的 0.875
        color_value.line_edit.setStyleSheet(f"""
            QLineEdit {{ 
                font-family: Consolas, monospace;
                font-size: {scaled_font_size}px;
                padding: 0 4px;
            }}
        """)
        
        # 存储颜色键
        color_value.setProperty("color_key", color_key)
        
        # 添加文本变化事件
        color_value.textChanged.connect(lambda text: self._update_color_from_text(color_key, text))
        
        # 添加编辑完成事件
        color_value.editingFinished.connect(lambda text: self._validate_color_input(color_key, text))
        
        item_layout.addWidget(color_value)
        
        # 存储引用，用于后续更新
        if not hasattr(self, '_color_inputs'):
            self._color_inputs = {}
        self._color_inputs[color_key] = (color_display, color_value)
        
        # 将颜色配置项添加到父布局
        layout.addLayout(item_layout)
    
    def _select_color(self, color_key):
        """
        打开颜色选择器
        
        Args:
            color_key (str): 颜色配置键
        """
        from PyQt5.QtWidgets import QColorDialog
        
        # 获取当前颜色
        current_color = self.current_colors.get(color_key, '#ffffff')
        
        # 打开颜色选择器
        color_dialog = QColorDialog(QColor(current_color), self)
        color_dialog.setOption(QColorDialog.ShowAlphaChannel, False)
        
        if color_dialog.exec_() == QColorDialog.Accepted:
            # 获取选择的颜色
            selected_color = color_dialog.selectedColor().name()
            
            # 更新当前颜色
            self.current_colors[color_key] = selected_color
            
            # 重新计算所有颜色
            self._calculate_colors()
            
            # 更新UI
            self._update_color_ui(color_key, selected_color)
            
            # 实时应用主题
            self._apply_theme()
    
    def _darken_color(self, color_hex, percentage):
        """
        将颜色加深指定百分比
        
        Args:
            color_hex (str): 十六进制颜色值，如 "#007AFF"
            percentage (float): 加深百分比，如 0.02 表示加深2%
            
        Returns:
            str: 加深后的十六进制颜色值
        """
        from PyQt5.QtGui import QColor
        
        color = QColor(color_hex)
        r = max(0, int(color.red() * (1 - percentage)))
        g = max(0, int(color.green() * (1 - percentage)))
        b = max(0, int(color.blue() * (1 - percentage)))
        
        return f"#{r:02x}{g:02x}{b:02x}"
    
    def _calculate_colors(self):
        """
        根据基础颜色计算所有其他颜色
        """
        # 获取基础颜色
        accent_color = self.current_colors.get("accent_color", "#007AFF")
        secondary_color = self.current_colors.get("secondary_color", "#333333")
        normal_color = self.current_colors.get("normal_color", "#e0e0e0")
        auxiliary_color = self.current_colors.get("auxiliary_color", "#f1f3f5")
        base_color = self.current_colors.get("base_color", "#ffffff")
        
        # 窗口颜色
        self.current_colors["window_background"] = auxiliary_color  # 辅助色
        self.current_colors["window_border"] = normal_color  # 普通色
        
        # 强调样式按钮颜色
        self.current_colors["button_primary_normal"] = accent_color  # 强调色
        self.current_colors["button_primary_hover"] = self._darken_color(accent_color, 0.02)  # 强调色加深2%
        self.current_colors["button_primary_pressed"] = self._darken_color(accent_color, 0.05)  # 强调色加深5%
        self.current_colors["button_primary_text"] = base_color  # 底层色
        self.current_colors["button_primary_border"] = accent_color  # 强调色
        
        # 普通样式按钮颜色
        self.current_colors["button_normal_normal"] = base_color  # 底层色
        self.current_colors["button_normal_hover"] = self._darken_color(base_color, 0.02)  # 底层色加深2%
        self.current_colors["button_normal_pressed"] = self._darken_color(base_color, 0.05)  # 底层色加深5%
        self.current_colors["button_normal_text"] = secondary_color  # 次选色
        self.current_colors["button_normal_border"] = secondary_color  # 次选色
        
        # 次选样式按钮颜色
        self.current_colors["button_secondary_normal"] = base_color  # 底层色
        self.current_colors["button_secondary_hover"] = self._darken_color(base_color, 0.02)  # 底层色加深2%
        self.current_colors["button_secondary_pressed"] = self._darken_color(base_color, 0.05)  # 底层色加深5%
        self.current_colors["button_secondary_text"] = accent_color  # 强调色
        self.current_colors["button_secondary_border"] = accent_color  # 强调色
        
        # 文字颜色
        self.current_colors["text_normal"] = secondary_color  # 次选色
        self.current_colors["text_disabled"] = auxiliary_color  # 辅助色
        self.current_colors["text_highlight"] = accent_color  # 强调色
        self.current_colors["text_placeholder"] = normal_color  # 普通色
        
        # 输入框颜色
        self.current_colors["input_background"] = base_color  # 底层色
        self.current_colors["input_border"] = normal_color  # 普通色
        self.current_colors["input_focus_border"] = accent_color  # 强调色
        self.current_colors["input_text"] = secondary_color  # 次选色
        
        # 列表颜色
        self.current_colors["list_background"] = auxiliary_color  # 辅助色
        self.current_colors["list_item_normal"] = normal_color  # 普通色
        self.current_colors["list_item_hover"] = self._darken_color(normal_color, 0.02)  # 普通色加深2%
        self.current_colors["list_item_selected"] = accent_color  # 强调色
        self.current_colors["list_item_text"] = secondary_color  # 次选色
        
        # 滑块颜色
        self.current_colors["slider_track"] = base_color  # 底层色
        self.current_colors["slider_handle"] = accent_color  # 强调色
        self.current_colors["slider_handle_hover"] = accent_color  # 强调色
        
        # 进度条颜色
        self.current_colors["progress_bar_bg"] = base_color  # 底层色
        self.current_colors["progress_bar_fg"] = accent_color  # 强调色
    
    def _update_color_ui(self, color_key, color_value):
        """
        更新颜色配置项的UI
        
        Args:
            color_key (str): 颜色配置键
            color_value (str): 颜色值
        """
        # 更新颜色显示框
        for widget in self.findChildren(QWidget):
            if widget.property("color_key") == color_key:
                if isinstance(widget, QLabel):
                    widget.setText(color_value)
                else:
                    widget.setStyleSheet(f"""
                        QWidget {{
                            background-color: {color_value};
                            border: 1px solid #cccccc;
                            border-radius: 4px;
                        }}
                    """)
    
    def _add_preview_section(self, layout):
        """
        添加控件预览区域
        
        Args:
            layout (QLayout): 父布局
        """
        # 应用DPI缩放因子
        scaled_margin = int(8 * self.dpi_scale)
        scaled_spacing = int(8 * self.dpi_scale)
        scaled_border_radius = int(4 * self.dpi_scale)
        
        # 创建预览区域容器
        preview_widget = QWidget()
        preview_widget.setStyleSheet(f"""
            QWidget {{
                background-color: #f5f5f5;
                border-radius: {scaled_border_radius}px;
                padding: {scaled_margin}px;
            }}
        """)
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(scaled_spacing)
        
        # 添加标题
        title_label = QLabel("控件预览")
        # 从应用实例获取全局默认字体大小和DPI缩放因子
        app = QApplication.instance()
        default_font_size = getattr(app, 'default_font_size', 16)
        scaled_font_size = int(default_font_size * self.dpi_scale)
        title_label.setStyleSheet(f"""
            QLabel {{ 
                font-size: {scaled_font_size}px;
                font-weight: 500;
                color: #333333;
                margin-bottom: 8px;
            }}
        """)
        preview_layout.addWidget(title_label)
        
        # 添加预览控件
        self._add_preview_controls(preview_layout)
        
        # 将预览区域添加到父布局
        layout.addWidget(preview_widget)
    
    def _add_preview_controls(self, layout):
        """
        添加预览控件
        
        Args:
            layout (QLayout): 父布局
        """
        # 应用DPI缩放因子
        scaled_padding = int(12 * self.dpi_scale)
        scaled_spacing = int(8 * self.dpi_scale)
        scaled_border_radius = int(4 * self.dpi_scale)
        
        # 创建预览容器
        controls_widget = QWidget()
        controls_widget.setStyleSheet(f"""
            QWidget {{
                background-color: #ffffff;
                border-radius: {scaled_border_radius}px;
                padding: {scaled_padding}px;
                border: 1px solid #e0e0e0;
            }}
        """)
        controls_layout = QVBoxLayout(controls_widget)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(scaled_spacing)
        
        # 按钮预览
        btn_label = QLabel("按钮预览:")
        # 从应用实例获取全局默认字体大小和DPI缩放因子
        app = QApplication.instance()
        default_font_size = getattr(app, 'default_font_size', 14)
        scaled_font_size = int(default_font_size * self.dpi_scale * 0.875)  # 14px 是 16px 的 0.875
        btn_label.setStyleSheet(f"""
            QLabel {{ 
                font-size: {scaled_font_size}px;
                color: #333333;
                margin-bottom: 4px;
            }}
        """)
        controls_layout.addWidget(btn_label)
        
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(scaled_spacing)
        
        from .button_widgets import CustomButton
        preview_btn1 = CustomButton("普通按钮", button_type="primary", display_mode="text")
        preview_btn2 = CustomButton("悬停按钮", button_type="secondary", display_mode="text")
        
        btn_layout.addWidget(preview_btn1)
        btn_layout.addWidget(preview_btn2)
        controls_layout.addLayout(btn_layout)
        
        # 输入框预览
        input_label = QLabel("输入框预览:")
        # 从应用实例获取全局默认字体大小和DPI缩放因子
        app = QApplication.instance()
        default_font_size = getattr(app, 'default_font_size', 14)
        scaled_font_size = int(default_font_size * self.dpi_scale * 0.875)  # 14px 是 16px 的 0.875
        input_label.setStyleSheet(f"""
            QLabel {{ 
                font-size: {scaled_font_size}px;
                color: #333333;
                margin-bottom: 4px;
                margin-top: 12px;
            }}
        """)
        controls_layout.addWidget(input_label)
        
        input_edit = CustomInputBox(placeholder_text="请输入文本...")
        controls_layout.addWidget(input_edit)
        
        # 文本预览
        text_label = QLabel("文本预览:")
        # 从应用实例获取全局默认字体大小和DPI缩放因子
        app = QApplication.instance()
        default_font_size = getattr(app, 'default_font_size', 14)
        scaled_font_size = int(default_font_size * self.dpi_scale * 0.875)  # 14px 是 16px 的 0.875
        text_label.setStyleSheet(f"""
            QLabel {{ 
                font-size: {scaled_font_size}px;
                color: #333333;
                margin-bottom: 4px;
                margin-top: 12px;
            }}
        """)
        controls_layout.addWidget(text_label)
        
        text_preview = QLabel("这是普通文字，这是高亮文字")
        text_preview.setStyleSheet(f"""
            QLabel {{ 
                font-size: {scaled_font_size}px;
                color: #333333;
            }}
        """)
        controls_layout.addWidget(text_preview)
        
        # 添加预览容器到父布局
        layout.addWidget(controls_widget)
    
    def _apply_theme(self):
        """
        应用主题颜色
        """
        # 获取应用实例
        app = QApplication.instance()
        
        # 应用主题颜色到全局样式表
        if hasattr(app, 'global_style_sheet'):
            # 更新全局样式表
            self._update_global_style_sheet()
        
        # 触发应用更新
        if hasattr(app, 'update_theme'):
            app.update_theme()
    
    def _update_global_style_sheet(self):
        """
        更新全局样式表
        """
        # 获取应用实例
        app = QApplication.instance()
        
        # 创建主题样式表
        theme_stylesheet = """
            /* 窗口样式 */
            QMainWindow, QWidget, QDialog {
                background-color: %s;
                border: 1px solid %s;
            }
            
            /* 文字样式 */
            QLabel {
                color: %s;
            }
            
            /* 输入框样式 */
            QLineEdit, QTextEdit, QPlainTextEdit {
                background-color: %s;
                color: %s;
                border: 1px solid %s;
                border-radius: 4px;
                padding: 6px 8px;
            }
            QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
                border-color: %s;
            }
            
            /* 列表和表格样式 */
            QListWidget, QTableWidget, QTreeWidget {
                background-color: %s;
                color: %s;
                border: 1px solid %s;
                border-radius: 4px;
            }
            QListWidget::item, QTableWidget::item, QTreeWidget::item {
                background-color: %s;
                color: %s;
            }
            QListWidget::item:hover, QTableWidget::item:hover, QTreeWidget::item:hover {
                background-color: %s;
            }
            QListWidget::item:selected, QTableWidget::item:selected, QTreeWidget::item:selected {
                background-color: %s;
                color: %s;
            }
        """ % (
            self.current_colors.get("window_background", "#1E1E1E"),
            self.current_colors.get("window_border", "#3C3C3C"),
            self.current_colors.get("text_normal", "#FFFFFF"),
            self.current_colors.get("input_background", "#2D2D2D"),
            self.current_colors.get("input_text", "#FFFFFF"),
            self.current_colors.get("input_border", "#3C3C3C"),
            self.current_colors.get("input_focus_border", "#4ECDC4"),
            self.current_colors.get("list_background", "#1E1E1E"),
            self.current_colors.get("list_item_text", "#FFFFFF"),
            self.current_colors.get("window_border", "#3C3C3C"),
            self.current_colors.get("list_item_normal", "#2D2D2D"),
            self.current_colors.get("list_item_text", "#FFFFFF"),
            self.current_colors.get("list_item_hover", "#3C3C3C"),
            self.current_colors.get("list_item_selected", "#4ECDC4"),
            self.current_colors.get("list_item_text", "#FFFFFF")
        )
        
        # 设置全局样式表
        app.setStyleSheet(theme_stylesheet)
    
    def _update_color_from_text(self, color_key, text):
        """
        从文本输入更新颜色
        
        Args:
            color_key (str): 颜色配置键
            text (str): 颜色值文本
        """
        from PyQt5.QtGui import QColor
        
        # 简单验证：必须是#开头，后面跟6位十六进制字符
        if text.startswith("#") and len(text) == 7:
            try:
                # 尝试创建QColor对象来验证颜色值
                QColor(text)
                # 更新当前颜色
                self.current_colors[color_key] = text
                # 重新计算所有颜色
                self._calculate_colors()
                # 更新UI
                if hasattr(self, '_color_inputs') and color_key in self._color_inputs:
                    color_display, color_value = self._color_inputs[color_key]
                    color_display.setStyleSheet(f"""
                        QWidget {{
                            background-color: {text};
                            border: 1px solid #cccccc;
                            border-radius: 2px;
                        }}
                    """)
                # 实时应用主题
                self._apply_theme()
            except Exception:
                pass
    
    def _validate_color_input(self, color_key, text):
        """
        验证颜色输入
        
        Args:
            color_key (str): 颜色配置键
            text (str): 颜色值文本
        """
        # 验证颜色值格式
        if not (text.startswith("#") and len(text) == 7):
            # 如果格式不正确，恢复到之前的颜色值
            previous_color = self.current_colors.get(color_key, '#ffffff')
            if hasattr(self, '_color_inputs') and color_key in self._color_inputs:
                color_display, color_value = self._color_inputs[color_key]
                color_value.line_edit.setText(previous_color)
        else:
            try:
                # 尝试创建QColor对象来验证颜色值
                QColor(text)
            except Exception:
                # 如果颜色值无效，恢复到之前的颜色值
                previous_color = self.current_colors.get(color_key, '#ffffff')
                if hasattr(self, '_color_inputs') and color_key in self._color_inputs:
                    color_display, color_value = self._color_inputs[color_key]
                    color_value.line_edit.setText(previous_color)
    
    def save_theme_settings(self):
        """
        保存主题设置
        """
        if self.settings_manager:
            # 只保存基础颜色设置项，而不是整个colors字典
            # 这些基础颜色会在应用启动时重新计算其他颜色
            base_colors = {
                "accent_color": self.current_colors.get("accent_color", "#007AFF"),
                "secondary_color": self.current_colors.get("secondary_color", "#333333"),
                "normal_color": self.current_colors.get("normal_color", "#e0e0e0"),
                "auxiliary_color": self.current_colors.get("auxiliary_color", "#f1f3f5"),
                "base_color": self.current_colors.get("base_color", "#ffffff")
            }
            
            # 保存每个基础颜色
            for color_key, color_value in base_colors.items():
                self.settings_manager.set_setting(f"appearance.colors.{color_key}", color_value)
                
            # 保存设置
            self.settings_manager.save_settings()
            
            # 显示保存成功提示
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(self, "保存成功", "主题设置已保存！")
            
            # 应用主题
            self._apply_theme()
            
            # 关闭窗口
            self.close()
        else:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "保存失败", "无法保存主题设置，请重试！")


class CustomMessageBox(QDialog):
    """
    自定义提示窗口组件
    特点：
    - 纯白圆角矩形外观
    - 带有阴影效果
    - 大小不可拖动
    - 支持自定义布局，包括标题区、图像区、文本区、进度条区和按钮区
    - 最多支持3个按钮，可横向或纵向排列
    - 默认第一个按钮为强调按钮，其余为普通按钮
    """
    
    # 按钮点击信号，传递按钮索引
    buttonClicked = pyqtSignal(int)
    
    def __init__(self, parent=None):
        # 即使有parent，也要确保是独立窗口
        super().__init__(parent)
        # 设置窗口标志为顶级窗口，确保独立显示
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # 确保窗口不被父窗口裁剪
        self.setWindowFlag(Qt.WindowTransparentForInput, False)  # 允许接收输入
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)  # 保持在最顶层
        
        # 获取应用实例和DPI缩放因子
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 获取全局字体
        self.global_font = getattr(app, 'global_font', QFont())
        self.setFont(self.global_font)
        
        # 初始化区域内容
        self._title = ""
        self._image = None
        self._text = ""
        self._progress = None
        self._buttons = []
        self._button_orientation = Qt.Vertical  # 默认按钮使用纵向排列
        
        # 列表相关属性
        self._list = None
        self._list_selection_mode = "single"  # 默认单选模式
        self._list_items = []
        
        # 初始化UI
        self.init_ui()
    
    def init_ui(self):
        """
        初始化自定义提示窗口UI
        """
        # 应用DPI缩放因子到UI参数
        scaled_margin = int(5 * self.dpi_scale)
        scaled_radius = int(6 * self.dpi_scale)
        scaled_shadow_radius = int(30 * self.dpi_scale)
        scaled_shadow_offset = int(2 * self.dpi_scale)
        scaled_body_margin = int(10 * self.dpi_scale)
        scaled_body_spacing = int(8 * self.dpi_scale)
        scaled_title_font_size = int(12 * self.dpi_scale)
        scaled_title_padding = f"{int(12 * self.dpi_scale)}px {int(15 * self.dpi_scale)}px 0 {int(15 * self.dpi_scale)}px"
        scaled_text_font_size = int(8 * self.dpi_scale)
        scaled_min_width = int(200 * self.dpi_scale)
        scaled_button_margin = int(4 * self.dpi_scale)
        scaled_button_spacing = int(6 * self.dpi_scale)
        
        # 主布局（用于容纳内容和装饰）
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(scaled_margin, scaled_margin, scaled_margin, scaled_margin)
        main_layout.setSpacing(0)
        
        # 创建窗口主体（带圆角）
        self.window_body = QWidget()
        self.window_body.setStyleSheet(f"""
            QWidget {{
                background-color: #ffffff;
                border-radius: {scaled_radius}px;
                border: 1px solid #ffffff;
            }}
        """)
        
        # 添加阴影效果
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(scaled_shadow_radius)
        shadow.setOffset(0, scaled_shadow_offset)
        shadow.setColor(QColor(0, 0, 0, 40))
        self.window_body.setGraphicsEffect(shadow)
        
        # 窗口主体布局 - 正确的纵向排列顺序
        self.body_layout = QVBoxLayout(self.window_body)
        self.body_layout.setContentsMargins(scaled_body_margin, scaled_body_margin, scaled_body_margin, scaled_body_margin)
        self.body_layout.setSpacing(scaled_body_spacing)  # 合理的纵向间距
        
        # 1. 标题区
        self.title_label = QLabel()
        self.title_label.setFont(self.global_font)
        self.title_label.setStyleSheet(f"""
            QLabel {{
                font-size: {scaled_title_font_size}px;
                font-weight: 400;
                color: #000000;
                background-color: transparent;
                padding: {scaled_title_padding};
                margin: 0;
            }}
        """)
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.body_layout.addWidget(self.title_label)
        
        # 2. 图像区
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background-color: transparent;")
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.body_layout.addWidget(self.image_label)
        
        # 3. 文本区
        self.text_label = QLabel()
        self.text_label.setFont(self.global_font)
        self.text_label.setStyleSheet(f"""
            QLabel {{
                font-size: {scaled_text_font_size}px;
                color: #333333;
                background-color: transparent;
                padding: 0;
                margin: 0;
            }}
        """)
        self.text_label.setWordWrap(True)
        self.text_label.setAlignment(Qt.AlignCenter)
        self.text_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        # 设置文字区默认最小宽度，应用DPI缩放
        self.text_label.setMinimumWidth(scaled_min_width)
        self.body_layout.addWidget(self.text_label)
        
        # 4. 列表区
        self.list_widget = QWidget()
        self.list_widget.setStyleSheet("background-color: transparent;")
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(0)
        self.list_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.body_layout.addWidget(self.list_widget)
        
        # 5. 输入框区
        self.input_widget = QWidget()
        self.input_widget.setStyleSheet("background-color: transparent;")
        self.input_layout = QVBoxLayout(self.input_widget)
        self.input_layout.setContentsMargins(0, 0, 0, 0)
        self.input_layout.setSpacing(0)
        self.input_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        # 输入框
        self.input_line_edit = CustomInputBox(
            parent=self,
            placeholder_text="",
            height=int(20 * self.dpi_scale),
            border_radius=4,
            border_color="#e0e0e0",
            background_color="#f5f5f5",
            text_color="#333333",
            active_border_color="#1890ff",
            active_background_color="#ffffff"
        )
        self.input_line_edit.setFont(self.global_font)
        self.input_layout.addWidget(self.input_line_edit)
        self.body_layout.addWidget(self.input_widget)
        
        # 6. 进度条区
        self.progress_widget = QWidget()
        self.progress_widget.setStyleSheet("background-color: transparent;")
        self.progress_layout = QVBoxLayout(self.progress_widget)
        self.progress_layout.setContentsMargins(0, 0, 0, 0)
        self.progress_layout.setSpacing(0)
        self.progress_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.body_layout.addWidget(self.progress_widget)
        
        # 5. 按钮区
        self.button_widget = QWidget()
        self.button_widget.setStyleSheet("background-color: transparent;")
        # 默认使用纵向布局
        self.button_layout = QVBoxLayout(self.button_widget)
        self.button_layout.setContentsMargins(0, scaled_button_margin, 0, 0)  # 顶部添加间距，应用DPI缩放
        self.button_layout.setSpacing(scaled_button_spacing)  # 按钮之间的合理间距，应用DPI缩放
        self.button_layout.setAlignment(Qt.AlignCenter)
        self.button_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # 确保按钮区在body_layout中居中显示
        self.body_layout.addWidget(self.button_widget, 0, Qt.AlignCenter)
        
        # 将窗口主体添加到主布局
        main_layout.addWidget(self.window_body)
        
        # 初始隐藏所有区域
        self.title_label.hide()
        self.image_label.hide()
        self.text_label.hide()
        self.list_widget.hide()
        self.input_widget.hide()
        self.progress_widget.hide()
        self.button_widget.hide()
    
    def set_title(self, title):
        """
        设置窗口标题
        
        Args:
            title (str): 窗口标题
        """
        self._title = title
        self.title_label.setText(title)
        if title:
            self.title_label.show()
        else:
            self.title_label.hide()
        self.adjust_size()
    
    def set_image(self, image):
        """
        设置图像
        
        Args:
            image (QPixmap or str): 图像，可以是QPixmap对象或图像路径
        """
        if isinstance(image, str):
            self._image = QPixmap(image)
        else:
            self._image = image
        
        if self._image:
            self.image_label.setPixmap(self._image)
            self.image_label.show()
        else:
            self.image_label.hide()
        self.adjust_size()
    
    def set_text(self, text):
        """
        设置文本内容
        
        Args:
            text (str): 文本内容
        """
        self._text = text
        self.text_label.setText(text)
        if text:
            self.text_label.show()
        else:
            self.text_label.hide()
        self.adjust_size()
    
    def set_progress(self, progress):
        """
        设置进度条
        
        Args:
            progress (CustomProgressBar): 进度条控件
        """
        self._progress = progress
        # 清空现有进度条
        for i in reversed(range(self.progress_layout.count())):
            widget = self.progress_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        
        if progress:
            # 给进度条控件左右设置30px的边距
            self.progress_layout.setContentsMargins(30, 0, 30, 0)
            self.progress_layout.addWidget(progress)
            self.progress_widget.show()
        else:
            self.progress_layout.setContentsMargins(0, 0, 0, 0)
            self.progress_widget.hide()
        self.adjust_size()
    
    def set_list(self, items, selection_mode="single", default_width=370, default_height=200, min_width=300, min_height=150):
        """
        设置列表内容
        
        Args:
            items (list): 列表项数据，每个元素可以是字符串或字典
                        字符串格式：仅文本
                        字典格式：{"text": "文本", "icon_path": "图标路径"}
            selection_mode (str): 选择模式，可选值："single"（单选）、"multiple"（多选）
            default_width (int): 列表默认宽度
            default_height (int): 列表默认高度
            min_width (int): 列表最小宽度
            min_height (int): 列表最小高度
        """
        # 清空现有列表
        self.clear_list()
        
        # 创建新的列表实例
        self._list = CustomSelectList(
            parent=self,
            default_width=default_width,
            default_height=default_height,
            min_width=min_width,
            min_height=min_height,
            selection_mode=selection_mode
        )
        
        # 设置选择模式
        self._list_selection_mode = selection_mode
        
        # 添加列表项
        self._list.add_items(items)
        self._list_items = items
        
        # 添加列表到布局
        self.list_layout.addWidget(self._list)
        self.list_widget.show()
        
        # 调整窗口大小
        self.adjust_size()
    
    def add_list_item(self, item):
        """
        添加单个列表项
        
        Args:
            item (str or dict): 列表项数据，可以是字符串或字典
        """
        if not self._list:
            # 如果列表不存在，创建默认列表
            self.set_list([], self._list_selection_mode)
        
        # 添加列表项
        self._list.add_item(item if isinstance(item, str) else item.get("text", ""), 
                           item.get("icon_path", "") if isinstance(item, dict) else "")
        self._list_items.append(item)
        
        # 调整窗口大小
        self.adjust_size()
    
    def add_list_items(self, items):
        """
        批量添加列表项
        
        Args:
            items (list): 列表项数据列表
        """
        if not self._list:
            # 如果列表不存在，创建默认列表
            self.set_list([], self._list_selection_mode)
        
        # 添加列表项
        self._list.add_items(items)
        self._list_items.extend(items)
        
        # 调整窗口大小
        self.adjust_size()
    
    def clear_list(self):
        """
        清空列表
        """
        # 清空现有列表
        for i in reversed(range(self.list_layout.count())):
            widget = self.list_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        
        self._list = None
        self._list_items = []
        self.list_widget.hide()
        
        # 调整窗口大小
        self.adjust_size()
    
    def get_selected_list_items(self):
        """
        获取选中的列表项
        
        Returns:
            list: 选中的列表项索引列表
        """
        if self._list:
            return self._list.get_selected_indices()
        return []
    
    def set_input(self, text="", placeholder=""):
        """
        设置输入框内容和占位符
        
        Args:
            text (str): 输入框初始内容
            placeholder (str): 输入框占位符
        """
        self.input_line_edit.setText(text)
        self.input_line_edit.set_placeholder_text(placeholder)
        if text or placeholder:
            self.input_widget.show()
        else:
            self.input_widget.hide()
        self.adjust_size()
    
    def get_input(self):
        """
        获取输入框内容
        
        Returns:
            str: 输入框内容
        """
        return self.input_line_edit.text()
    
    def clear_input(self):
        """
        清空输入框并隐藏
        """
        self.input_line_edit.clear_text()
        self.input_line_edit.set_placeholder_text("")
        self.input_widget.hide()
        self.adjust_size()
    
    def set_buttons(self, button_texts, orientations=Qt.Vertical, button_types=None):
        """
        设置按钮
        
        Args:
            button_texts (list): 按钮文本列表，最多3个按钮
            orientations (Qt.Orientation): 按钮排列方向，Qt.Horizontal或Qt.Vertical，默认为Qt.Vertical
            button_types (list): 按钮类型列表，可选值："primary"、"secondary"、"normal"，默认第一个为"primary"，其余为"normal"
        """
        # 限制按钮数量为最多3个
        self._buttons = button_texts[:3]
        self._button_orientation = orientations
        
        # 清空现有按钮
        for i in reversed(range(self.button_layout.count())):
            widget = self.button_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        
        # 设置布局属性，应用DPI缩放
        # 左右边距和进度条一样，底部添加边距确保最后一个按钮的阴影不会被切掉
        scaled_left_right_margin = int(15 * self.dpi_scale)
        scaled_top_margin = int(4 * self.dpi_scale)
        scaled_bottom_margin = int(8 * self.dpi_scale)
        scaled_button_spacing = int(8 * self.dpi_scale)
        
        self.button_layout.setContentsMargins(scaled_left_right_margin, scaled_top_margin, scaled_left_right_margin, scaled_bottom_margin)
        self.button_layout.setSpacing(scaled_button_spacing)  # 增加按钮之间的间距，确保阴影不重叠
        
        # 设置布局对齐方式
        self.button_layout.setAlignment(Qt.AlignCenter)
        
        # 设置默认按钮类型
        if button_types is None:
            button_types = []
            for i in range(len(self._buttons)):
                if i == 0:
                    button_types.append("primary")
                else:
                    button_types.append("normal")
        
        # 创建按钮
        from freeassetfilter.widgets.button_widgets import CustomButton
        for i, (text, btn_type) in enumerate(zip(self._buttons, button_types)):
            button = CustomButton(text, self, btn_type)
            # 让按钮左右填充，同时保持固定高度
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            # 连接按钮点击信号到处理函数
            button.clicked.connect(lambda checked, idx=i: self._on_button_clicked(idx))
            # 添加按钮到布局
            self.button_layout.addWidget(button)
        
        if self._buttons:
            self.button_widget.show()
        else:
            self.button_widget.hide()
        
        # 确保窗口能正确调整大小
        self.adjust_size()
    
    def _on_button_clicked(self, button_index):
        """
        按钮点击事件处理
        
        Args:
            button_index (int): 按钮索引
        """
        self.buttonClicked.emit(button_index)
        # 点击按钮后自动关闭弹窗
        self.close()
    
    def adjust_size(self):
        """
        调整窗口大小以适应内容
        """
        self.window_body.adjustSize()
        self.adjustSize()
    
    def mousePressEvent(self, event):
        """
        鼠标按下事件，用于实现窗口拖拽
        """
        if event.button() == Qt.LeftButton:
            # 开始拖动
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
    
    def mouseMoveEvent(self, event):
        """
        鼠标移动事件，用于实现窗口拖拽
        """
        if hasattr(self, 'drag_position'):
            # 处理拖动
            self.move(event.globalPos() - self.drag_position)
            event.accept()
    
    def mouseReleaseEvent(self, event):
        """
        鼠标释放事件，用于结束窗口拖拽
        """
        if hasattr(self, 'drag_position'):
            delattr(self, 'drag_position')
    
    def showEvent(self, event):
        """
        显示事件，确保窗口居中
        """
        super().showEvent(event)
        # 确保窗口居中
        self.center()
    
    def center(self):
        """
        将窗口居中显示
        优先相对于主窗口居中，然后尝试相对于父窗口，最后相对于屏幕
        """
        # 尝试获取主窗口
        main_window = None
        for widget in QApplication.topLevelWidgets():
            if hasattr(widget, 'windowTitle') and widget.windowTitle() and 'FreeAssetFilter' in widget.windowTitle():
                main_window = widget
                break
        
        if main_window:
            # 相对于主窗口居中
            main_rect = main_window.frameGeometry()
            self.move(
                main_rect.center().x() - self.width() // 2,
                main_rect.center().y() - self.height() // 2
            )
        elif self.parent():
            # 相对于父窗口居中
            parent_rect = self.parent().frameGeometry()
            self.move(
                parent_rect.center().x() - self.width() // 2,
                parent_rect.center().y() - self.height() // 2
            )
        else:
            # 相对于屏幕居中
            screen = QApplication.primaryScreen()
            screen_rect = screen.availableGeometry()
            self.move(
                screen_rect.center().x() - self.width() // 2,
                screen_rect.center().y() - self.height() // 2
            )
