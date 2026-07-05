#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 窗口类自定义控件
包含各种窗口类UI组件，如自定义窗口、自定义消息框等
"""

import weakref

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QLabel, QSizePolicy, QApplication, QDialog, QLineEdit, 
    QScrollArea
)
from PySide6.QtCore import (
    Qt,
    QPoint,
    Signal,
    QRect,
    QSize,
    QPropertyAnimation,
    QParallelAnimationGroup,
    QEasingCurve,
    QTimer,
)
from PySide6.QtGui import QFont, QColor, QPainter, QPen, QBrush, QIcon, QPixmap
from PySide6.QtWidgets import QGraphicsDropShadowEffect

# 导入自定义列表组件
from .list_widgets import CustomSelectList
# 导入自定义输入框组件
from .input_widgets import CustomInputBox
# 导入自定义进度条组件
from .progress_widgets import D_ProgressBar


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
    
    def __init__(self, title="Custom Window", parent=None, dpi_scale=None, global_font=None, settings_manager=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        self.title = title
        
        self.dragging = False
        self.drag_position = QPoint()
        
        self.resizing = False
        self.resize_direction = ""
        self.resize_start_pos = QPoint()
        self.resize_start_size = None
        self.resize_start_geometry = None
        
        if dpi_scale is not None:
            self.dpi_scale = dpi_scale
        else:
            self.dpi_scale = getattr(QApplication.instance(), 'dpi_scale_factor', 1.0)
        
        # 增加边框宽度，便于用户抓住边缘和角落
        self.border_size = 0
        
        # 存储全局字体
        if global_font is not None:
            self.global_font = global_font
        else:
            self.global_font = getattr(QApplication.instance(), 'global_font', QFont())
        self.setFont(self.global_font)
        
        # 注入 settings_manager
        if settings_manager is not None:
            self._settings_manager = settings_manager
        else:
            from freeassetfilter.core.settings_manager import SettingsManager
            self._settings_manager = SettingsManager()
        
        self.init_ui()
        
    def init_ui(self):
        """初始化自定义窗口UI"""
        scaled_margin = int(2.5 * self.dpi_scale)
        scaled_radius = int(1.5 * self.dpi_scale)
        self.scaled_title_height = int(5 * self.dpi_scale)
        scaled_shadow_radius = int(2.5 * self.dpi_scale)
        scaled_shadow_offset = int(1 * self.dpi_scale)
        
        # 默认大小缩小为原始的一半
        self.setMinimumSize(100, 75)
        self.resize(100, 75)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(scaled_margin, scaled_margin, scaled_margin, scaled_margin)
        main_layout.setSpacing(0)
        
        self.window_body = QWidget()
        
        window_bg_color = self._settings_manager.get_setting("appearance.colors.base_color", "#FFFFFF")
        window_border_color = self._settings_manager.get_setting("appearance.colors.base_color", "#FFFFFF")
        
        self.window_body.setStyleSheet(f"""
            QWidget {{
                background-color: {window_bg_color};
                border-radius: {scaled_radius}px;
                border: 1px solid {window_border_color};
            }}
        """)
        
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(scaled_shadow_radius)
        shadow.setOffset(0, scaled_shadow_offset)
        shadow.setColor(QColor(0, 0, 0, 60))
        self.window_body.setGraphicsEffect(shadow)
        
        body_layout = QVBoxLayout(self.window_body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        
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
        scaled_left_margin = int(2 * self.dpi_scale)
        scaled_right_margin = int(2 * self.dpi_scale)
        scaled_spacing = int(2 * self.dpi_scale)
        title_layout.setContentsMargins(scaled_left_margin, 0, scaled_right_margin, 0)
        title_layout.setSpacing(scaled_spacing)
        
        title_label = QLabel(self.title)
        # 使用全局字体，让Qt6自动处理DPI缩放
        title_font = QFont(self.global_font)
        title_font.setWeight(QFont.Medium)  # 字重500
        title_label.setFont(title_font)
        title_label.setStyleSheet("""
            QLabel {
                color: #000000;
            }
        """)
        title_layout.addWidget(title_label, 1)
        
        # 使用CustomButton代替QPushButton，确保DPI缩放兼容
        from .button_widgets import CustomButton
        self.close_button = CustomButton("×", button_type="primary", display_mode="text", height=12)
        self.close_button.setFixedSize(int(6 * self.dpi_scale), int(6 * self.dpi_scale))
        self.close_button.clicked.connect(self.close)
        title_layout.addWidget(self.close_button)
        
        self.content_widget = QWidget()
        self.content_widget.setStyleSheet("""
            QWidget {
                background-color: transparent;
            }
        """)
        
        self.content_layout = QVBoxLayout(self.content_widget)
        scaled_content_margin = int(2 * self.dpi_scale)
        scaled_content_top_margin = int(2 * self.dpi_scale)
        scaled_content_spacing = int(1.5 * self.dpi_scale)
        self.content_layout.setContentsMargins(scaled_content_margin, scaled_content_top_margin, scaled_content_margin, scaled_content_margin)
        self.content_layout.setSpacing(scaled_content_spacing)
        
        body_layout.addWidget(title_bar)
        body_layout.addWidget(self.content_widget, 1)
        
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
        
        direction = ""
        if on_top:
            direction += "top-"
        elif on_bottom:
            direction += "bottom-"
        
        if on_left:
            direction += "left"
        elif on_right:
            direction += "right"
        
        direction = direction.rstrip("-")
        
        return direction
    
    
    def mousePressEvent(self, event):
        """
        鼠标按下事件，用于实现窗口拖拽和调整大小
        """
        if event.button() == Qt.LeftButton:
            pos = event.pos()
            direction = self._get_resize_direction(pos)
            if direction:
                self.resizing = True
                self.resize_direction = direction
                self.resize_start_pos = event.globalPos()
                self.resize_start_size = self.size()
                self.resize_start_geometry = self.geometry()
                event.accept()
            elif pos.y() < self.scaled_title_height:  # 标题栏区域
                self.dragging = True
                self.drag_position = event.globalPos() - self.pos()
                event.accept()
    
    def mouseMoveEvent(self, event):
        """
        鼠标移动事件，用于实现窗口拖拽和调整大小
        优化：减少重绘次数，提高拖动流畅度
        """
        if self.resizing:
            delta = event.globalPos() - self.resize_start_pos
            
            orig_x = self.resize_start_geometry.x()
            orig_y = self.resize_start_geometry.y()
            orig_width = self.resize_start_geometry.width()
            orig_height = self.resize_start_geometry.height()
            
            new_x = orig_x
            new_y = orig_y
            new_width = orig_width
            new_height = orig_height
            
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
            
            min_width, min_height = 100, 75
            new_width = max(min_width, new_width)
            new_height = max(min_height, new_height)
            
            # 窗口达最小值时，调整位置防止漂移
            if new_width == min_width:
                if "left" in self.resize_direction:
                    # 左侧调整达到最小值，固定左侧位置
                    new_x = orig_x + orig_width - min_width
            
            if new_height == min_height:
                if "top" in self.resize_direction:
                    # 顶部调整达到最小值，固定顶部位置
                    new_y = orig_y + orig_height - min_height
            
            self.setGeometry(new_x, new_y, new_width, new_height)
            event.accept()
        elif self.dragging:
            new_pos = event.globalPos() - self.drag_position
            self.move(new_pos)
            event.accept()
    
    def mouseReleaseEvent(self, event):
        """
        鼠标释放事件，用于结束窗口拖拽或调整大小
        """
        self.dragging = False
        self.resizing = False

    def resizeEvent(self, event):
        """DPI缩放因子变化时重新初始化UI"""
        super().resizeEvent(event)
        
        app = QApplication.instance()
        new_dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        if new_dpi_scale != self.dpi_scale:
            self.dpi_scale = new_dpi_scale
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
        if hasattr(self, 'window_body'):
            title_bar = self.window_body.layout().itemAt(0).widget()
            title_layout = title_bar.layout()
            title_label = title_layout.itemAt(0).widget()
            title_label.setText(title)


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
    buttonClicked = Signal(int)
    
    def __init__(self, parent=None, dpi_scale=None, global_font=None, settings_manager=None):
        # 即使有parent，也要确保是独立窗口
        super().__init__(parent)
        # 设置窗口标志为顶级窗口，确保独立显示
        # 使用Dialog标志确保正确的窗口类型，同时保持无边框和透明背景
        # 注意：不使用NoDropShadowWindowHint，让Qt处理系统阴影，我们使用自定义阴影
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        # 确保窗口不被父窗口裁剪
        self.setWindowFlag(Qt.WindowTransparentForInput, False)  # 允许接收输入
        # 移除了保持在最顶层的设置，让窗口可以被其他窗口覆盖
        
        # 获取应用实例和DPI缩放因子
        if dpi_scale is not None:
            self.dpi_scale = dpi_scale
        else:
            self.dpi_scale = getattr(QApplication.instance(), 'dpi_scale_factor', 1.0)
        
        # 获取全局字体
        if global_font is not None:
            self.global_font = global_font
        else:
            self.global_font = getattr(QApplication.instance(), 'global_font', QFont())
        self.setFont(self.global_font)
        
        # 注入 settings_manager
        if settings_manager is not None:
            self._settings_manager = settings_manager
        else:
            from freeassetfilter.core.settings_manager import SettingsManager
            self._settings_manager = SettingsManager()
        
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
        
        # 初始化动画状态
        self._show_animation_group = None
        self._hide_animation_group = None
        self._fade_in_animation = None
        self._fade_out_animation = None
        self._move_in_animation = None
        self._move_out_animation = None
        self._is_show_animating = False
        self._is_hide_animating = False
        self._close_after_hide = False
        self._pending_result = None
        self._allow_direct_close = False
        self._animation_target_pos = None
        self._animation_offset = int(14 * self.dpi_scale)
        self._show_animation_duration = 220
        self._hide_animation_duration = 170
        self._has_played_show_animation = False
        self._show_animation_pending = False
        
        self.init_ui()
        self._setup_animations()
    
    def init_ui(self):
        """初始化自定义提示窗口UI"""
        scaled_radius = int(6 * self.dpi_scale)
        # 增大阴影使效果更明显
        scaled_shadow_radius = int(40 * self.dpi_scale)
        scaled_shadow_offset = int(4 * self.dpi_scale)
        # 边距需容纳阴影，至少为模糊半径的一半
        scaled_margin = int(25 * self.dpi_scale)
        scaled_body_margin = int(10 * self.dpi_scale)
        scaled_body_spacing = int(8 * self.dpi_scale)
        scaled_title_font_size = int(self.global_font.pointSize() * 1.2)
        scaled_title_padding = f"{int(12 * self.dpi_scale)}px {int(15 * self.dpi_scale)}px 0 {int(15 * self.dpi_scale)}px"
        scaled_text_font_size = self.global_font.pointSize()
        scaled_min_width = int(200 * self.dpi_scale)
        scaled_button_margin = int(4 * self.dpi_scale)
        scaled_button_spacing = int(6 * self.dpi_scale)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(scaled_margin, scaled_margin, scaled_margin, scaled_margin)
        main_layout.setSpacing(0)
        
        # 获取主题颜色
        base_color = self._settings_manager.get_setting("appearance.colors.base_color", "#FFFFFF")
        secondary_color = self._settings_manager.get_setting("appearance.colors.secondary_color", "#333333")
        
        self.window_body = QWidget()
        self.window_body.setStyleSheet(f"""
            QWidget {{
                background-color: {base_color};
                border-radius: {scaled_radius}px;
                border: 1px solid {base_color};
            }}
        """)
        
        # 阴影在控件外部渲染，需父控件透明背景
        self.shadow_effect = QGraphicsDropShadowEffect(self.window_body)
        self.shadow_effect.setBlurRadius(scaled_shadow_radius)
        self.shadow_effect.setOffset(0, scaled_shadow_offset)
        self.shadow_effect.setColor(QColor(0, 0, 0, 80))
        self.window_body.setGraphicsEffect(self.shadow_effect)
        
        self.body_layout = QVBoxLayout(self.window_body)
        self.body_layout.setContentsMargins(scaled_body_margin, scaled_body_margin, scaled_body_margin, scaled_body_margin)
        self.body_layout.setSpacing(scaled_body_spacing)
        
        # 1. 标题区
        self.title_label = QLabel()
        title_font = QFont(self.global_font)
        title_font.setPointSize(int(self.global_font.pointSize() * 1.2))
        title_font.setWeight(QFont.Normal)
        self.title_label.setFont(title_font)
        self.title_label.setStyleSheet(f"""
            QLabel {{
                color: {secondary_color};
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
                color: {secondary_color};
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
        
        secondary_color = self._settings_manager.get_setting("appearance.colors.secondary_color", "#333333")
        
        self.input_line_edit = CustomInputBox(
            parent=self,
            placeholder_text="",
            height=int(20 * self.dpi_scale),
            border_radius=4,
            border_color="#e0e0e0",
            background_color="#f5f5f5",
            text_color=secondary_color,
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
        
        # 7. 按钮区（默认纵向排列）
        self.button_widget = QWidget()
        self.button_widget.setStyleSheet("background-color: transparent;")
        self.button_layout = QVBoxLayout(self.button_widget)
        self.button_layout.setContentsMargins(0, scaled_button_margin, 0, 0)
        self.button_layout.setSpacing(scaled_button_spacing)
        self.button_layout.setAlignment(Qt.AlignCenter)
        self.button_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.body_layout.addWidget(self.button_widget, 0, Qt.AlignCenter)
        
        main_layout.addWidget(self.window_body)
        
        # 初始全部隐藏，按需显示
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
        self.clear_list()
        
        self._list = CustomSelectList(
            parent=self,
            default_width=default_width,
            default_height=default_height,
            min_width=min_width,
            min_height=min_height,
            selection_mode=selection_mode
        )
        
        self._list_selection_mode = selection_mode
        
        self._list.add_items(items)
        self._list_items = items
        
        self.list_layout.addWidget(self._list)
        self.list_widget.show()
        
        self.adjust_size()
    
    def add_list_item(self, item):
        """
        添加单个列表项

        Args:
            item (str or dict): 列表项数据
        """
        if not self._list:
            self.set_list([], self._list_selection_mode)
        
        self._list.add_item(item if isinstance(item, str) else item.get("text", ""), 
                           item.get("icon_path", "") if isinstance(item, dict) else "")
        self._list_items.append(item)
        
        self.adjust_size()
    
    def add_list_items(self, items):
        """
        批量添加列表项

        Args:
            items (list): 列表项数据列表
        """
        if not self._list:
            self.set_list([], self._list_selection_mode)
        
        self._list.add_items(items)
        self._list_items.extend(items)
        
        self.adjust_size()
    
    def clear_list(self):
        """清空列表"""
        for i in reversed(range(self.list_layout.count())):
            widget = self.list_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        
        self._list = None
        self._list_items = []
        self.list_widget.hide()
        
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
        
        for i in reversed(range(self.button_layout.count())):
            widget = self.button_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        
        # 底部留边距，防止按钮阴影被切掉
        scaled_left_right_margin = int(15 * self.dpi_scale)
        scaled_top_margin = int(4 * self.dpi_scale)
        scaled_bottom_margin = int(8 * self.dpi_scale)
        scaled_button_spacing = int(8 * self.dpi_scale)
        
        self.button_layout.setContentsMargins(scaled_left_right_margin, scaled_top_margin, scaled_left_right_margin, scaled_bottom_margin)
        self.button_layout.setSpacing(scaled_button_spacing)
        self.button_layout.setAlignment(Qt.AlignCenter)
        
        if button_types is None:
            button_types = []
            for i in range(len(self._buttons)):
                if i == 0:
                    button_types.append("primary")
                else:
                    button_types.append("normal")
        
        from freeassetfilter.widgets.button_widgets import CustomButton
        weak_self = weakref.ref(self)
        for i, (text, btn_type) in enumerate(zip(self._buttons, button_types)):
            button = CustomButton(text, self, btn_type)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.clicked.connect(lambda checked, idx=i: (s := weak_self()) and s._on_button_clicked(idx))
            self.button_layout.addWidget(button)
        
        if self._buttons:
            self.button_widget.show()
        else:
            self.button_widget.hide()
        
        self.adjust_size()
    
    def _setup_animations(self):
        """
        初始化显示/隐藏动画
        """
        self._fade_in_animation = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_in_animation.setDuration(self._show_animation_duration)
        self._fade_in_animation.setEasingCurve(QEasingCurve.OutCubic)
        
        self._move_in_animation = QPropertyAnimation(self, b"pos", self)
        self._move_in_animation.setDuration(self._show_animation_duration)
        self._move_in_animation.setEasingCurve(QEasingCurve.OutCubic)
        
        self._show_animation_group = QParallelAnimationGroup(self)
        self._show_animation_group.addAnimation(self._fade_in_animation)
        self._show_animation_group.addAnimation(self._move_in_animation)
        self._show_animation_group.finished.connect(self._on_show_animation_finished)
        
        self._fade_out_animation = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_out_animation.setDuration(self._hide_animation_duration)
        self._fade_out_animation.setEasingCurve(QEasingCurve.InCubic)
        
        self._move_out_animation = QPropertyAnimation(self, b"pos", self)
        self._move_out_animation.setDuration(self._hide_animation_duration)
        self._move_out_animation.setEasingCurve(QEasingCurve.InCubic)
        
        self._hide_animation_group = QParallelAnimationGroup(self)
        self._hide_animation_group.addAnimation(self._fade_out_animation)
        self._hide_animation_group.addAnimation(self._move_out_animation)
        self._hide_animation_group.finished.connect(self._on_hide_animation_finished)
    
    def _stop_animations(self):
        """停止所有动画"""
        if self._show_animation_group and self._show_animation_group.state() == QPropertyAnimation.Running:
            self._show_animation_group.stop()
        if self._hide_animation_group and self._hide_animation_group.state() == QPropertyAnimation.Running:
            self._hide_animation_group.stop()
    
    def _start_show_animation(self):
        """启动显示动画"""
        self._show_animation_pending = False
        if self._is_hide_animating or self._is_show_animating or self._has_played_show_animation:
            return
        
        self._stop_animations()
        self._is_show_animating = True
        self._is_hide_animating = False
        self._close_after_hide = False
        
        if self._animation_target_pos is None:
            self._animation_target_pos = self.pos()
        
        start_pos = QPoint(
            self._animation_target_pos.x(),
            self._animation_target_pos.y() + self._animation_offset
        )
        
        self.setWindowOpacity(0.0)
        self.move(start_pos)
        
        self._fade_in_animation.setStartValue(0.0)
        self._fade_in_animation.setEndValue(1.0)
        self._move_in_animation.setStartValue(start_pos)
        self._move_in_animation.setEndValue(self._animation_target_pos)
        
        self._show_animation_group.start()
    
    def _start_hide_animation(self):
        """启动隐藏动画"""
        if self._is_hide_animating:
            return
        
        self._stop_animations()
        self._is_show_animating = False
        self._is_hide_animating = True
        
        current_pos = self.pos()
        end_pos = QPoint(current_pos.x(), current_pos.y() + self._animation_offset)
        current_opacity = self.windowOpacity()
        if current_opacity <= 0.0:
            current_opacity = 1.0
        
        self._fade_out_animation.setStartValue(current_opacity)
        self._fade_out_animation.setEndValue(0.0)
        self._move_out_animation.setStartValue(current_pos)
        self._move_out_animation.setEndValue(end_pos)
        
        self._hide_animation_group.start()
    
    def _request_animated_close(self, result=None):
        """
        以动画方式关闭弹窗

        Args:
            result (int, optional): 对话框结果值
        """
        if self._close_after_hide or self._is_hide_animating:
            return
        
        if result is None:
            result = self.result()
        
        self._pending_result = result
        self._close_after_hide = True
        self._show_animation_pending = False
        self._start_hide_animation()
    
    def _on_show_animation_finished(self):
        """
        显示动画结束处理
        """
        self._is_show_animating = False
        self._has_played_show_animation = True
        self.setWindowOpacity(1.0)
        if self._animation_target_pos is not None:
            self.move(self._animation_target_pos)
    
    def _on_hide_animation_finished(self):
        """
        隐藏动画结束处理
        """
        self._is_hide_animating = False
        self.setWindowOpacity(1.0)
        
        if self._animation_target_pos is not None:
            self.move(self._animation_target_pos)
        
        pending_result = self._pending_result
        self._pending_result = None
        should_close = self._close_after_hide
        self._close_after_hide = False
        self._has_played_show_animation = False
        self._show_animation_pending = False
        
        if should_close:
            if pending_result is None:
                pending_result = self.result()
            self._allow_direct_close = True
            try:
                super().done(pending_result)
            finally:
                self._allow_direct_close = False
    
    def _on_button_clicked(self, button_index):
        """
        按钮点击事件处理
        
        Args:
            button_index (int): 按钮索引
        """
        self.buttonClicked.emit(button_index)
        self.setResult(button_index)
        self._request_animated_close(button_index)
    
    def adjust_size(self):
        """
        调整窗口大小以适应内容
        """
        self.window_body.adjustSize()
        self.adjustSize()
        # 调整大小后刷新阴影效果
        if hasattr(self, 'shadow_effect') and self.shadow_effect:
            self.shadow_effect.setEnabled(False)
            self.shadow_effect.setEnabled(True)
    
    def mousePressEvent(self, event):
        """拖拽窗口"""
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
    
    def mouseMoveEvent(self, event):
        """拖拽窗口"""
        if hasattr(self, 'drag_position'):
            self.move(event.globalPos() - self.drag_position)
            event.accept()
    
    def mouseReleaseEvent(self, event):
        """结束拖拽"""
        if hasattr(self, 'drag_position'):
            delattr(self, 'drag_position')
    
    def showEvent(self, event):
        """显示时居中并刷新阴影"""
        super().showEvent(event)
        self.center()
        self._animation_target_pos = self.pos()
        if hasattr(self, 'shadow_effect') and self.shadow_effect:
            self.window_body.update()
        
        if (
            not self._has_played_show_animation
            and not self._is_show_animating
            and not self._is_hide_animating
            and not self._show_animation_pending
        ):
            self._show_animation_pending = True
            self.setWindowOpacity(0.0)
            QTimer.singleShot(0, self._start_show_animation)
    
    def center(self):
        """窗口居中：优先主窗口，其次父窗口，最后屏幕"""
        main_window = None
        for widget in QApplication.topLevelWidgets():
            if hasattr(widget, 'windowTitle') and widget.windowTitle() and 'FreeAssetFilter' in widget.windowTitle():
                main_window = widget
                break
        
        if main_window:
            main_rect = main_window.frameGeometry()
            self.move(
                main_rect.center().x() - self.width() // 2,
                main_rect.center().y() - self.height() // 2
            )
        elif self.parent():
            parent_rect = self.parent().frameGeometry()
            self.move(
                parent_rect.center().x() - self.width() // 2,
                parent_rect.center().y() - self.height() // 2
            )
        else:
            screen = QApplication.primaryScreen()
            screen_rect = screen.availableGeometry()
            self.move(
                screen_rect.center().x() - self.width() // 2,
                screen_rect.center().y() - self.height() // 2
            )
    
    def closeEvent(self, event):
        """关闭事件统一接管为退场动画"""
        if self._allow_direct_close:
            event.accept()
            return

        if self._close_after_hide or self._is_hide_animating:
            event.ignore()
            return
        
        event.ignore()
        self._request_animated_close()
    
    def accept(self):
        """以动画方式接受对话框"""
        self._request_animated_close(QDialog.Accepted)
    
    def reject(self):
        """以动画方式拒绝对话框"""
        self._request_animated_close(QDialog.Rejected)
    
    def keyPressEvent(self, event):
        """阻止ESC键关闭"""
        if event.key() == Qt.Key_Escape:
            event.ignore()
        else:
            super().keyPressEvent(event)
