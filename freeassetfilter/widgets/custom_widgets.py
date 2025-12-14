#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 自定义控件库
包含各种自定义UI组件，如自定义窗口、按钮、进度条等
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QLabel, QSizePolicy, QApplication, QDialog, QLineEdit
)
from PyQt5.QtCore import Qt, QPoint, pyqtSignal, QRect, QSize
from PyQt5.QtGui import QFont, QColor, QPainter, QPen, QBrush, QIcon, QPixmap
from PyQt5.QtWidgets import QGraphicsDropShadowEffect

# 用于SVG渲染
from freeassetfilter.utils.svg_renderer import SvgRenderer
import os


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
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
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
        self.border_size = 15  # 增加边框宽度，便于用户抓住边缘和角落
        
        # 获取全局字体
        app = QApplication.instance()
        self.global_font = getattr(app, 'global_font', QFont())
        self.setFont(self.global_font)
        
        # 初始化UI
        self.init_ui()
        
    def init_ui(self):
        """
        初始化自定义窗口UI
        """
        # 主布局（用于容纳内容和装饰）
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(0)
        
        # 创建窗口主体（带圆角）
        self.window_body = QWidget()
        self.window_body.setStyleSheet("""
            QWidget {
                background-color: #ffffff;
                border-radius: 12px;
                border: 1px solid #e9ecef;
            }
        """)
        
        # 添加阴影效果
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 60))
        self.window_body.setGraphicsEffect(shadow)
        
        # 窗口主体布局
        body_layout = QVBoxLayout(self.window_body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        
        # 标题栏
        title_bar = QWidget()
        title_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        title_bar.setMinimumHeight(40)
        title_bar.setMaximumHeight(40)
        title_bar.setStyleSheet("""
            QWidget {
                background-color: transparent;
            }
        """)
        
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(16, 0, 8, 0)
        title_layout.setSpacing(8)
        
        # 标题标签
        title_label = QLabel(self.title)
        title_label.setFont(self.global_font)
        title_label.setStyleSheet("""
            QLabel {
                font-size: 18px;
                font-weight: 500;
                color: #000000;
            }
        """)
        title_layout.addWidget(title_label, 1)
        
        # 关闭按钮
        self.close_button = QPushButton()
        self.close_button.setFixedSize(24, 24)
        self.close_button.setStyleSheet("""
            QPushButton {
                background-color: #0a59f7;
                border: none;
                border-radius: 12px;
                color: #ffffff;
                font-size: 18px;
                font-weight: 400;
            }
            QPushButton:hover {
                background-color: #0a59f7;
            }
            QPushButton:pressed {
                background-color: #0062A0;
            }
        """)
        self.close_button.setText("×")
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
        self.content_layout.setContentsMargins(16, 8, 16, 16)
        self.content_layout.setSpacing(12)
        
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
                self.resize_start_geometry = self.geometry()  # 保存初始几何形状
                event.accept()
            elif pos.y() < 40:  # 标题栏区域
                # 开始拖动
                self.dragging = True
                self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
                event.accept()
    
    def mouseMoveEvent(self, event):
        """
        鼠标移动事件，用于实现窗口拖拽和调整大小
        """
        pos = event.pos()
        
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
            min_width, min_height = 200, 150
            new_width = max(min_width, new_width)
            new_height = max(min_height, new_height)
            
            # 处理边界情况：当窗口达到最小值时，调整位置
            if new_width == min_width:
                if "left" in self.resize_direction:
                    # 左侧调整达到最小值，固定左侧位置
                    new_x = orig_x + orig_width - min_width
                # 右侧调整达到最小值，不需要调整位置
            
            if new_height == min_height:
                if "top" in self.resize_direction:
                    # 顶部调整达到最小值，固定顶部位置
                    new_y = orig_y + orig_height - min_height
                # 底部调整达到最小值，不需要调整位置
            
            # 更新窗口几何形状
            self.setGeometry(new_x, new_y, new_width, new_height)
            event.accept()
        elif self.dragging:
            # 处理拖动
            self.move(event.globalPos() - self.drag_position)
            event.accept()
    
    def mouseReleaseEvent(self, event):
        """
        鼠标释放事件，用于结束窗口拖拽或调整大小
        """
        self.dragging = False
        self.resizing = False
    
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


class CustomButton(QPushButton):
    """
    自定义按钮组件
    特点：
    - 圆角设计
    - 悬停和点击效果
    - 支持强调色和次选色方案
    - 支持文字和图标两种显示模式
    """
    
    def __init__(self, text="Button", parent=None, button_type="primary", display_mode="text"):
        """
        初始化自定义按钮
        
        Args:
            text (str): 按钮文本或SVG图标路径
            parent (QWidget): 父控件
            button_type (str): 按钮类型，可选值："primary"（强调色）、"secondary"（次选色）、"normal"（普通样式）
            display_mode (str): 显示模式，可选值："text"（文字显示）、"icon"（图标显示）
                              当未传入该参数或参数为空时，默认启用文字显示功能
                              当传入该参数且参数不为空时，启用图标显示功能
        """
        super().__init__(text, parent)
        self.button_type = button_type
        
        # 显示模式：text（文字）或icon（图标）
        self._display_mode = display_mode
        # SVG图标路径
        self._icon_path = text if self._display_mode == "icon" else None
        # 渲染后的图标Pixmap
        self._icon_pixmap = None
        
        # 获取全局字体
        app = QApplication.instance()
        self.global_font = getattr(app, 'global_font', QFont())
        self.setFont(self.global_font)
        
        # 如果是图标模式，渲染图标
        if self._display_mode == "icon":
            self._render_icon()
        
        self.update_style()
    
    def update_style(self):
        """
        更新按钮样式
        """
        # 添加阴影效果
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(2)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 15))
        self.setGraphicsEffect(shadow)
        
        if self.button_type == "primary":
            # 强调色方案
            self.setStyleSheet("""
                QPushButton {
                    background-color: #0a59f7;
                    color: #ffffff;
                    border: 1px solid #0a59f7;
                    border-radius: 20px;
                    padding: 8px 12px;
                    font-size: 18px;
                    font-weight: 400;
                }
                QPushButton:hover {
                    background-color: #0d6efd;
                    border-color: #0d6efd;
                }
                QPushButton:pressed {
                    background-color: #0A51E0;
                    border-color: #0A51E0;
                }
                QPushButton:disabled {
                    background-color: #88A9EB;
                    color: #FFFFFF;
                    border-color: #88A9EB;
                }
            """)
        elif self.button_type == "secondary":
            # 次选色方案
            self.setStyleSheet("""
                QPushButton {
                    background-color: #f8f9fa;
                    color: #0a59f7;
                    border: 1px solid #dee2e6;
                    border-radius: 20px;
                    padding: 8px 12px;
                    font-size: 18px;
                    font-weight: 400;
                }
                QPushButton:hover {
                    background-color: #e9ecef;
                    border-color: #adb5bd;
                }
                QPushButton:pressed {
                    background-color: #DADFE4;
                    border-color: #ced4da;
                }
                QPushButton:disabled {
                    background-color: #C7CBD0;
                    color: #515151;
                    border-color: #C7CBD0;
                }
            """)
        else:  # normal
            # 普通按钮方案：确保在白色背景下可见
            self.setStyleSheet("""
                QPushButton {
                    background-color: #ffffff;
                    color: #0a59f7;
                    border: 2px solid #0a59f7;
                    border-radius: 20px;
                    padding: 8px 12px;
                    font-size: 18px;
                    font-weight: 400;
                }
                QPushButton:hover {
                    background-color: #f0f4ff;
                    border-color: #0d6efd;
                }
                QPushButton:pressed {
                    background-color: #e0e7ff;
                    border-color: #0A51E0;
                }
                QPushButton:disabled {
                    background-color: #ffffff;
                    color: #DADFE4;
                    border-color: #DADFE4;
                }
            """)
    
    def set_primary(self, is_primary):
        """
        设置按钮是否使用强调色（兼容旧接口）
        
        Args:
            is_primary (bool): 是否使用强调色
        """
        self.button_type = "primary" if is_primary else "secondary"
        self.update_style()
        self.resizeEvent(None)  # 触发resizeEvent，更新圆角半径
    
    def set_button_type(self, button_type):
        """
        设置按钮类型
        
        Args:
            button_type (str): 按钮类型，可选值："primary"、"secondary"、"normal"
        """
        self.button_type = button_type
        self.update_style()
        self.resizeEvent(None)  # 触发resizeEvent，更新圆角半径
    
    def _render_icon(self):
        """
        渲染SVG图标为QPixmap
        调用项目中已开发的SVG渲染组件进行图标渲染
        """
        try:
            if self._icon_path and os.path.exists(self._icon_path):
                # 计算合适的图标大小，确保图标不会超出按钮范围
                icon_size = min(self.width(), self.height()) * 0.6
                # 使用项目中已有的SvgRenderer渲染SVG图标
                self._icon_pixmap = SvgRenderer.render_svg_to_pixmap(self._icon_path, int(icon_size))
            else:
                self._icon_pixmap = None
        except Exception as e:
            print(f"渲染SVG图标失败: {e}")
            self._icon_pixmap = None
    
    def resizeEvent(self, event):
        """
        大小变化事件，动态调整圆角半径为最短边的一半
        如果是图标模式，重新渲染图标
        """
        super().resizeEvent(event)
        
        # 计算最短边
        min_size = min(self.width(), self.height())
        radius = min_size // 2
        
        # 更新样式表中的圆角半径
        current_style = self.styleSheet()
        # 移除旧的border-radius属性
        lines = current_style.split('\n')
        new_lines = []
        for line in lines:
            if 'border-radius' not in line:
                new_lines.append(line)
        
        # 在适当位置添加新的border-radius属性
        new_style = '\n'.join(new_lines)
        # 找到QPushButton { 块
        if 'QPushButton {' in new_style:
            start_idx = new_style.find('QPushButton {') + len('QPushButton {')
            # 在QPushButton { 块中添加border-radius属性
            new_style = new_style[:start_idx] + f'\n                    border-radius: {radius}px;' + new_style[start_idx:]
        
        self.setStyleSheet(new_style)
        
        # 如果是图标模式，重新渲染图标以适应新尺寸
        if self._display_mode == "icon":
            self._render_icon()
    
    def paintEvent(self, event):
        """
        绘制按钮
        如果是图标模式，绘制图标；否则调用父类绘制文字
        """
        if self._display_mode == "icon" and self._icon_pixmap:
            # 图标模式，绘制图标
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            
            # 获取按钮中心位置
            center_x = self.width() // 2
            center_y = self.height() // 2
            
            # 计算图标绘制位置（居中）
            icon_rect = self._icon_pixmap.rect()
            icon_rect.moveCenter(self.rect().center())
            
            # 绘制图标
            painter.drawPixmap(icon_rect, self._icon_pixmap)
            painter.end()
        else:
            # 文字模式或图标渲染失败，调用父类绘制文字
            super().paintEvent(event)


class CustomProgressBar(QWidget):
    """
    自定义进度条控件
    支持点击任意位置跳转和拖拽功能
    特点：
    - 自定义外观，包括背景色、进度色和滑块样式
    - 使用SVG图标作为滑块
    - 支持悬停和点击状态变化
    - 提供丰富的信号机制
    - 支持横向和纵向布局
    """
    valueChanged = pyqtSignal(int)  # 值变化信号
    userInteracting = pyqtSignal()  # 用户开始交互信号
    userInteractionEnded = pyqtSignal()  # 用户结束交互信号
    
    # 方向常量
    Horizontal = 0
    Vertical = 1
    
    def __init__(self, parent=None, is_interactive=True):
        super().__init__(parent)
        
        # 方向属性
        self._orientation = self.Horizontal
        
        # 设置默认尺寸
        self.setMinimumSize(400, 28)
        self.setMaximumHeight(28)
        
        # 获取全局字体
        app = QApplication.instance()
        self.global_font = getattr(app, 'global_font', QFont())
        self.setFont(self.global_font)
        
        # 进度条属性
        self._minimum = 0
        self._maximum = 1000
        self._value = 0
        self._is_pressed = False
        self._last_pos = 0
        self._is_interactive = is_interactive  # 新增：控制是否可交互
        
        # 外观属性
        self._bg_color = QColor(229, 231, 233)  # 进度条背景颜色
        self._progress_color = QColor(10, 89, 247)  # #0a59f7
        self._handle_color = QColor(0, 120, 212)  # #0078d4
        self._handle_hover_color = QColor(16, 110, 190)  # #106ebe
        self._handle_pressed_color = QColor(0, 90, 158)  # #005a9e
        self._handle_radius = 12
        self._bar_height = 6
        self._bar_radius = 3
        
        # SVG 图标路径
        icon_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'icons')
        self._icon_path = os.path.join(icon_dir, '条-顶-尾.svg')
        self._head_icon_path = os.path.join(icon_dir, '条-顶-头.svg')
        self._middle_icon_path = os.path.join(icon_dir, '条-顶-中.svg')
        
        # 渲染 SVG 图标为 QPixmap
        self._handle_pixmap = SvgRenderer.render_svg_to_pixmap(self._icon_path, self._handle_radius * 2)
        self._head_pixmap = SvgRenderer.render_svg_to_pixmap(self._head_icon_path, self._handle_radius * 2)
        # 条顶中 SVG 会在绘制时根据需要直接渲染，这里只保存路径
    
    def setOrientation(self, orientation):
        """
        设置进度条方向
        
        Args:
            orientation: 方向常量，Horizontal 或 Vertical
        """
        if self._orientation != orientation:
            self._orientation = orientation
            
            # 根据新方向更新尺寸限制
            if orientation == self.Horizontal:
                self.setMinimumSize(400, 28)
                self.setMaximumHeight(28)
            else:  # Vertical
                self.setMinimumSize(28, 400)
                self.setMaximumWidth(28)
            
            self.update()
    
    def orientation(self):
        """
        获取进度条方向
        
        Returns:
            int: 方向常量
        """
        return self._orientation
    
    def setRange(self, minimum, maximum):
        """
        设置进度条范围
        
        Args:
            minimum (int): 最小值
            maximum (int): 最大值
        """
        self._minimum = minimum
        self._maximum = maximum
        self.update()
    
    def setValue(self, value):
        """
        设置进度条值
        
        Args:
            value (int): 进度值
        """
        if value < self._minimum:
            value = self._minimum
        elif value > self._maximum:
            value = self._maximum
        
        if self._value != value:
            self._value = value
            self.update()
            self.valueChanged.emit(value)
    
    def value(self):
        """
        获取当前进度值
        
        Returns:
            int: 当前进度值
        """
        return self._value
    
    def setInteractive(self, is_interactive):
        """
        设置进度条是否可交互
        
        Args:
            is_interactive (bool): 是否可交互
        """
        self._is_interactive = is_interactive
        self.update()
    
    def isInteractive(self):
        """
        获取进度条是否可交互
        
        Returns:
            bool: 是否可交互
        """
        return self._is_interactive
    
    def mousePressEvent(self, event):
        """
        鼠标按下事件，处理用户开始交互
        """
        if self._is_interactive and event.button() == Qt.LeftButton:
            self._is_pressed = True
            if self._orientation == self.Horizontal:
                self._last_pos = event.pos().x()
                self._update_value_from_pos(self._last_pos)
            else:  # Vertical
                self._last_pos = event.pos().y()
                self._update_value_from_pos(self._last_pos)
            self.userInteracting.emit()
    
    def mouseMoveEvent(self, event):
        """
        鼠标移动事件，处理拖拽交互
        """
        if self._is_interactive and self._is_pressed:
            if self._orientation == self.Horizontal:
                self._last_pos = event.pos().x()
                self._update_value_from_pos(self._last_pos)
            else:  # Vertical
                self._last_pos = event.pos().y()
                self._update_value_from_pos(self._last_pos)
    
    def mouseReleaseEvent(self, event):
        """
        鼠标释放事件，处理用户结束交互
        """
        if self._is_interactive and self._is_pressed and event.button() == Qt.LeftButton:
            self._is_pressed = False
            self.userInteractionEnded.emit()
    
    def _update_value_from_pos(self, pos):
        """
        根据鼠标位置更新进度值
        
        Args:
            pos (int): 鼠标坐标（横向为X坐标，纵向为Y坐标）
        """
        if self._orientation == self.Horizontal:
            # 横向处理
            # 计算进度条总宽度
            bar_length = self.width() - (self._handle_radius * 2)
            # 计算鼠标在进度条上的相对位置
            relative_pos = pos - self._handle_radius
            if relative_pos < 0:
                relative_pos = 0
            elif relative_pos > bar_length:
                relative_pos = bar_length
            
            # 计算对应的进度值
            if bar_length > 0:
                ratio = relative_pos / bar_length
            else:
                ratio = 0.0
            value = int(self._minimum + ratio * (self._maximum - self._minimum))
        else:  # Vertical
            # 纵向处理 - 滑动方向修正：向上滑动数值增加，向下滑动数值减少
            # 计算进度条总高度
            bar_length = self.height() - (self._handle_radius * 2)
            # 计算鼠标在进度条上的相对位置
            relative_pos = pos - self._handle_radius
            if relative_pos < 0:
                relative_pos = 0
            elif relative_pos > bar_length:
                relative_pos = bar_length
            
            # 计算对应的进度值 - 反向映射：relative_pos越大，值越小
            if bar_length > 0:
                ratio = 1.0 - (relative_pos / bar_length)
            else:
                ratio = 0.0
            value = int(self._minimum + ratio * (self._maximum - self._minimum))
        
        self.setValue(value)
    
    def paintEvent(self, event):
        """
        绘制进度条
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        rect = self.rect()
        
        if self._orientation == self.Horizontal:
            # 横向绘制
            # 计算进度条参数
            bar_y = (rect.height() - self._bar_height) // 2
            bar_width = rect.width() - 2 * self._handle_radius
            
            # 绘制背景
            bg_rect = QRect(
                self._handle_radius, bar_y, 
                bar_width, self._bar_height
            )
            
            painter.setBrush(QBrush(self._bg_color))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(bg_rect, self._bar_radius, self._bar_radius)
            
            # 计算已完成部分宽度
            progress_width = int(bar_width * (self._value - self._minimum) / (self._maximum - self._minimum))
            
            if progress_width > 0:
                try:
                    from PyQt5.QtCore import Qt as QtCore
                    from PyQt5.QtGui import QTransform
                    
                    # 计算垂直居中位置
                    middle_y = (rect.height() - self._handle_radius * 2) // 2
                    
                    if self._is_interactive:
                        # 可交互进度条 - 原有样式
                        # 使用条顶中 SVG 图形填充已播放部分
                        # 使用修复过的 SvgRenderer 方法渲染 SVG 到临时 QPixmap
                        icon_size = self._handle_radius * 2
                        temp_pixmap = SvgRenderer.render_svg_to_pixmap(self._middle_icon_path, icon_size)
                        
                        # 将临时 pixmap 旋转 90 度
                        transform = QTransform()
                        transform.rotate(90)
                        rotated_pixmap = temp_pixmap.transformed(transform, QtCore.SmoothTransformation)
                        
                        # 计算中间矩形
                        middle_rect = QRect(
                            self._handle_radius, middle_y, 
                            progress_width, self._handle_radius * 2
                        )
                        
                        # 拉伸渲染旋转后的 pixmap 到中间矩形
                        painter.drawPixmap(middle_rect, rotated_pixmap)
                        
                        # 绘制已完成区域的起始点 - 使用条-顶-头.svg图标（逆时针旋转90度）
                        head_x = -self._handle_radius // 2  # 向左偏移一点
                        
                        if not self._head_pixmap.isNull():
                            # 保存当前画家状态
                            painter.save()
                            
                            # 计算旋转中心
                            center_x = head_x + self._handle_radius
                            center_y = middle_y + self._handle_radius
                            
                            # 移动坐标原点到旋转中心
                            painter.translate(center_x, center_y)
                            
                            # 逆时针旋转90度
                            painter.rotate(-90)
                            
                            # 绘制旋转后的图标
                            painter.drawPixmap(-self._handle_radius, -self._handle_radius, self._head_pixmap)
                            
                            # 恢复画家状态
                            painter.restore()
                        
                        # 绘制滑块 - 使用 SVG 图标（逆时针旋转90度）
                        handle_x = self._handle_radius + progress_width
                        # 确保滑块不会超出进度条范围
                        handle_x = min(handle_x, self.width() - self._handle_radius * 2)
                        
                        # 确保图标已正确加载
                        if not self._handle_pixmap.isNull():
                            # 保存当前画家状态
                            painter.save()
                            
                            # 计算旋转中心
                            center_x = handle_x + self._handle_radius
                            center_y = middle_y + self._handle_radius
                            
                            # 移动坐标原点到旋转中心
                            painter.translate(center_x, center_y)
                            
                            # 逆时针旋转90度
                            painter.rotate(-90)
                            
                            # 绘制旋转后的图标
                            painter.drawPixmap(-self._handle_radius, -self._handle_radius, self._handle_pixmap)
                            
                            # 恢复画家状态
                            painter.restore()
                        else:
                            # 备用方案：如果 SVG 加载失败，绘制圆形滑块
                            painter.setBrush(QBrush(
                                self._handle_pressed_color if self._is_pressed else 
                                self._handle_hover_color if self.underMouse() else 
                                self._handle_color
                            ))
                            painter.setPen(Qt.NoPen)  # 去除滑块边框
                            painter.drawEllipse(handle_x, middle_y, self._handle_radius * 2, self._handle_radius * 2)
                    else:
                        # 不可交互进度条 - 简化的样式，避免裁切问题
                        # 直接绘制圆角矩形，确保显示正常
                        
                        # 计算进度条参数
                        bar_y = (rect.height() - self._bar_height) // 2
                        
                        # 绘制已完成部分
                        progress_rect = QRect(
                            self._handle_radius, bar_y, 
                            progress_width, self._bar_height
                        )
                        
                        painter.setBrush(QBrush(self._progress_color))
                        painter.setPen(Qt.NoPen)
                        painter.drawRoundedRect(progress_rect, self._bar_radius, self._bar_radius)
                except Exception as e:
                    print(f"渲染 SVG 失败: {e}")
                    # 备用方案：使用纯色填充
                    progress_rect = QRect(
                        self._handle_radius, bar_y, 
                        progress_width, self._bar_height
                    )
                    painter.setBrush(QBrush(self._progress_color))
                    painter.drawRoundedRect(progress_rect, self._bar_radius, self._bar_radius)
        else:  # Vertical
            # 纵向绘制
            # 计算进度条参数
            bar_x = (rect.width() - self._bar_height) // 2
            bar_height = rect.height() - 2 * self._handle_radius
            
            # 绘制背景
            bg_rect = QRect(
                bar_x, self._handle_radius, 
                self._bar_height, bar_height
            )
            
            painter.setBrush(QBrush(self._bg_color))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(bg_rect, self._bar_radius, self._bar_radius)
            
            # 计算已完成部分高度
            progress_height = int(bar_height * (self._value - self._minimum) / (self._maximum - self._minimum))
            
            if progress_height > 0:
                try:
                    from PyQt5.QtCore import Qt as QtCore
                    from PyQt5.QtGui import QTransform
                    
                    # 计算水平居中位置
                    middle_x = (rect.width() - self._handle_radius * 2) // 2
                    
                    if self._is_interactive:
                        # 可交互进度条 - 纵向样式
                        # 使用条顶中 SVG 图形填充已播放部分
                        # 使用修复过的 SvgRenderer 方法渲染 SVG 到临时 QPixmap
                        icon_size = self._handle_radius * 2
                        temp_pixmap = SvgRenderer.render_svg_to_pixmap(self._middle_icon_path, icon_size)
                        
                        # 计算中间矩形 - 从顶部开始向下延伸
                        middle_rect = QRect(
                            middle_x, self._handle_radius, 
                            self._handle_radius * 2, progress_height
                        )
                        
                        # 拉伸渲染 pixmap 到中间矩形
                        painter.drawPixmap(middle_rect, temp_pixmap)
                        
                        # 绘制已完成区域的起始点 - 使用条-顶-头.svg图标
                        head_y = -self._handle_radius // 2  # 向上偏移一点
                        
                        if not self._head_pixmap.isNull():
                            # 保存当前画家状态
                            painter.save()
                            
                            # 计算旋转中心
                            center_x = middle_x + self._handle_radius
                            center_y = head_y + self._handle_radius
                            
                            # 移动坐标原点到旋转中心
                            painter.translate(center_x, center_y)
                            
                            # 绘制图标（不需要旋转）
                            painter.drawPixmap(-self._handle_radius, -self._handle_radius, self._head_pixmap)
                            
                            # 恢复画家状态
                            painter.restore()
                        
                        # 绘制滑块 - 使用 SVG 图标
                        handle_y = self._handle_radius + progress_height
                        # 确保滑块不会超出进度条范围
                        handle_y = min(handle_y, self.height() - self._handle_radius * 2)
                        
                        # 确保图标已正确加载
                        if not self._handle_pixmap.isNull():
                            # 保存当前画家状态
                            painter.save()
                            
                            # 计算旋转中心
                            center_x = middle_x + self._handle_radius
                            center_y = handle_y + self._handle_radius
                            
                            # 移动坐标原点到旋转中心
                            painter.translate(center_x, center_y)
                            
                            # 绘制旋转后的图标
                            painter.drawPixmap(-self._handle_radius, -self._handle_radius, self._handle_pixmap)
                            
                            # 恢复画家状态
                            painter.restore()
                        else:
                            # 备用方案：如果 SVG 加载失败，绘制圆形滑块
                            painter.setBrush(QBrush(
                                self._handle_pressed_color if self._is_pressed else 
                                self._handle_hover_color if self.underMouse() else 
                                self._handle_color
                            ))
                            painter.setPen(Qt.NoPen)  # 去除滑块边框
                            painter.drawEllipse(middle_x, handle_y, self._handle_radius * 2, self._handle_radius * 2)
                    else:
                        # 不可交互进度条 - 简化的样式，避免裁切问题
                        # 直接绘制圆角矩形，确保显示正常
                        
                        # 绘制已完成部分 - 从顶部开始向下延伸
                        progress_rect = QRect(
                            bar_x, self._handle_radius, 
                            self._bar_height, progress_height
                        )
                        
                        painter.setBrush(QBrush(self._progress_color))
                        painter.setPen(Qt.NoPen)
                        painter.drawRoundedRect(progress_rect, self._bar_radius, self._bar_radius)
                except Exception as e:
                    print(f"渲染 SVG 失败: {e}")
                    # 备用方案：使用纯色填充
                    progress_rect = QRect(
                        bar_x, self._handle_radius, 
                        self._bar_height, progress_height
                    )
                    painter.setBrush(QBrush(self._progress_color))
                    painter.drawRoundedRect(progress_rect, self._bar_radius, self._bar_radius)
        
        painter.end()
    
    def enterEvent(self, event):
        """
        鼠标进入事件
        """
        self.update()
    
    def leaveEvent(self, event):
        """
        鼠标离开事件
        """
        self.update()


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
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # 确保窗口不被父窗口裁剪
        self.setWindowFlag(Qt.WindowTransparentForInput, False)  # 允许接收输入
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)  # 保持在最顶层
        
        # 获取全局字体
        app = QApplication.instance()
        self.global_font = getattr(app, 'global_font', QFont())
        self.setFont(self.global_font)
        
        # 初始化区域内容
        self._title = ""
        self._image = None
        self._text = ""
        self._progress = None
        self._buttons = []
        self._button_orientation = Qt.Vertical  # 默认按钮使用纵向排列
        
        # 初始化UI
        self.init_ui()
    
    def init_ui(self):
        """
        初始化自定义提示窗口UI
        """
        # 主布局（用于容纳内容和装饰）
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(0)
        
        # 创建窗口主体（带圆角）
        self.window_body = QWidget()
        self.window_body.setStyleSheet("""
            QWidget {
                background-color: #ffffff;
                border-radius: 12px;
                border: 1px solid #e9ecef;
            }
        """)
        
        # 添加阴影效果
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 60))
        self.window_body.setGraphicsEffect(shadow)
        
        # 窗口主体布局 - 正确的纵向排列顺序
        self.body_layout = QVBoxLayout(self.window_body)
        self.body_layout.setContentsMargins(20, 20, 20, 20)
        self.body_layout.setSpacing(16)  # 合理的纵向间距
        
        # 1. 标题区
        self.title_label = QLabel()
        self.title_label.setFont(self.global_font)
        self.title_label.setStyleSheet("""
            QLabel {
                font-size: 24px;
                font-weight: 400;
                color: #000000;
                background-color: transparent;
                padding: 24px 30px 0 30px;
                margin: 0;
            }
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
        self.text_label.setStyleSheet("""
            QLabel {
                font-size: 16px;
                color: #333333;
                background-color: transparent;
                padding: 0;
                margin: 0;
            }
        """)
        self.text_label.setWordWrap(True)
        self.text_label.setAlignment(Qt.AlignCenter)
        self.text_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        # 设置文字区默认最小宽度为400px
        self.text_label.setMinimumWidth(400)
        self.body_layout.addWidget(self.text_label)
        
        # 4. 进度条区
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
        self.button_layout.setContentsMargins(0, 8, 0, 0)  # 顶部添加8px间距
        self.button_layout.setSpacing(12)  # 按钮之间的合理间距
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
        
        # 设置布局属性，左右边距和进度条一样为30px
        # 底部添加16px边距，确保最后一个按钮的阴影不会被切掉
        self.button_layout.setContentsMargins(30, 8, 30, 16)  # 顶部8px，左右30px，底部16px边距
        self.button_layout.setSpacing(16)  # 增加按钮之间的间距，确保阴影不重叠
        
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
                 height=40,
                 border_radius=20,
                 border_color="#e5e7e9",
                 background_color="#ffffff",
                 text_color="#000000",
                 placeholder_color="#CCCCCC",
                 active_border_color="#e5e7e9",
                 active_background_color="#ffffff"):
        """
        初始化自定义输入框
        
        Args:
            parent (QWidget): 父控件
            placeholder_text (str): 默认显示文本（占位符）
            initial_text (str): 初始输入文本
            width (int): 控件宽度
            height (int): 控件高度
            border_radius (int): 边框圆角半径
            border_color (str): 边框颜色
            background_color (str): 背景颜色
            text_color (str): 文本颜色
            placeholder_color (str): 占位符文本颜色
            active_border_color (str): 激活状态下的边框颜色
            active_background_color (str): 激活状态下的背景颜色
        """
        super().__init__(parent)
        
        # 设置基本属性
        self.placeholder_text = placeholder_text
        self._is_active = False
        self._has_content = False
        
        # 样式参数
        self._width = width
        self._height = height
        self._border_radius = border_radius
        self._border_color = QColor(border_color)
        self._background_color = QColor(background_color)
        self._text_color = QColor(text_color)
        self._placeholder_color = QColor(placeholder_color)
        self._active_border_color = QColor(active_border_color)
        self._active_background_color = QColor(active_background_color)
        
        # 获取全局字体
        app = QApplication.instance()
        self.global_font = getattr(app, 'global_font', QFont())
        
        # 初始化UI
        self.init_ui()
        
        # 设置初始文本
        if initial_text:
            self.line_edit.setText(initial_text)
            self._has_content = True
    
    def init_ui(self):
        """
        初始化UI组件
        """
        # 设置主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 创建QLineEdit作为实际输入控件
        self.line_edit = QLineEdit()
        self.line_edit.setFont(self.global_font)
        self.line_edit.setPlaceholderText(self.placeholder_text)
        self.line_edit.setStyleSheet("""
            QLineEdit {
                background-color: transparent;
                border: none;
                padding: 8px 12px;
                color: %s;
                font-size: 14px;
                selection-background-color: #0a59f7;
                selection-color: white;
            }
            QLineEdit::placeholder {
                color: %s;
            }
        """ % (self._text_color.name(), self._placeholder_color.name()))
        
        # 连接信号
        self.line_edit.textChanged.connect(self._on_text_changed)
        self.line_edit.focusInEvent = self._on_focus_in
        self.line_edit.focusOutEvent = self._on_focus_out
        self.line_edit.returnPressed.connect(self._on_return_pressed)
        
        # 添加到布局
        main_layout.addWidget(self.line_edit)
        
        # 设置控件大小
        if self._width is not None:
            self.setFixedWidth(self._width)
            self.line_edit.setFixedWidth(self._width)
        else:
            # 支持自适应宽度
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.line_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        if self._height is not None:
            self.setFixedHeight(self._height)
            self.line_edit.setFixedHeight(self._height)
        else:
            # 支持自适应高度
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.line_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    
    def _on_text_changed(self, text):
        """
        文本变化事件处理
        """
        self._has_content = bool(text.strip())
        self.textChanged.emit(text)
        self.update()  # 更新绘制
    
    def _on_focus_in(self, event):
        """
        获得焦点事件处理
        """
        self._is_active = True
        self.focusChanged.emit(True)
        self.update()  # 更新绘制
        # 调用原始的focusInEvent
        QLineEdit.focusInEvent(self.line_edit, event)
    
    def _on_focus_out(self, event):
        """
        失去焦点事件处理
        """
        self._is_active = False
        self.focusChanged.emit(False)
        self.editingFinished.emit(self.line_edit.text())
        self.update()  # 更新绘制
        # 调用原始的focusOutEvent
        QLineEdit.focusOutEvent(self.line_edit, event)
    
    def _on_return_pressed(self):
        """
        回车键按下事件处理
        """
        self.editingFinished.emit(self.line_edit.text())
    
    def paintEvent(self, event):
        """
        绘制控件外观
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)  # 抗锯齿
        
        rect = self.rect()
        
        # 确定当前样式
        if self._is_active:
            border_color = self._active_border_color
            background_color = self._active_background_color
            border_width = 2
        else:
            border_color = self._border_color
            background_color = self._background_color
            border_width = 1
        
        # 绘制背景
        painter.setBrush(QBrush(background_color))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, self._border_radius, self._border_radius)
        
        # 绘制边框
        painter.setPen(QPen(border_color, border_width))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, self._border_radius, self._border_radius)
        
        painter.end()
    
    def text(self):
        """
        获取当前输入的文本
        
        Returns:
            str: 当前输入的文本
        """
        return self.line_edit.text()
    
    def setText(self, text):
        """
        设置输入文本
        
        Args:
            text (str): 要设置的文本
        """
        self.line_edit.setText(text)
        self._has_content = bool(text.strip())
        self.update()
    
    def setPlaceholderText(self, text):
        """
        设置占位符文本
        
        Args:
            text (str): 要设置的占位符文本
        """
        self.placeholder_text = text
        self.line_edit.setPlaceholderText(text)
    
    def clear(self):
        """
        清空输入文本
        """
        self.line_edit.clear()
        self._has_content = False
        self.update()
    
    def setFocus(self):
        """
        设置控件获得焦点
        """
        self.line_edit.setFocus()
    
    def clearFocus(self):
        """
        清除控件焦点
        """
        self.line_edit.clearFocus()
    
    def set_enabled(self, enabled):
        """
        设置控件是否可用
        
        Args:
            enabled (bool): 是否可用
        """
        self.line_edit.setEnabled(enabled)
        self.setEnabled(enabled)
    
    def is_enabled(self):
        """
        检查控件是否可用
        
        Returns:
            bool: 是否可用
        """
        return self.line_edit.isEnabled()
    
    def is_active(self):
        """
        检查控件是否处于激活状态
        
        Returns:
            bool: 是否激活
        """
        return self._is_active
    
    def has_content(self):
        """
        检查控件是否有输入内容
        
        Returns:
            bool: 是否有内容
        """
        return self._has_content
    
    def set_width(self, width):
        """
        设置控件宽度
        
        Args:
            width (int): 控件宽度
        """
        self._width = width
        self.setFixedSize(self._width, self._height)
        self.line_edit.setFixedSize(self._width, self._height)
        self.update()
    
    def set_height(self, height):
        """
        设置控件高度
        
        Args:
            height (int): 控件高度
        """
        self._height = height
        self.setFixedSize(self._width, self._height)
        self.line_edit.setFixedSize(self._width, self._height)
        self.update()
    
    def set_border_radius(self, radius):
        """
        设置边框圆角半径
        
        Args:
            radius (int): 圆角半径
        """
        self._border_radius = radius
        self.update()
    
    def set_border_color(self, color):
        """
        设置边框颜色
        
        Args:
            color (str or QColor): 边框颜色
        """
        self._border_color = QColor(color)
        self.update()
    
    def set_background_color(self, color):
        """
        设置背景颜色
        
        Args:
            color (str or QColor): 背景颜色
        """
        self._background_color = QColor(color)
        self.update()
    
    def set_text_color(self, color):
        """
        设置文本颜色
        
        Args:
            color (str or QColor): 文本颜色
        """
        self._text_color = QColor(color)
        # 更新样式表
        self.line_edit.setStyleSheet("""
            QLineEdit {
                background-color: transparent;
                border: none;
                padding: 8px 12px;
                color: %s;
                font-size: 14px;
                selection-background-color: #0a59f7;
                selection-color: white;
            }
            QLineEdit::placeholder {
                color: %s;
            }
        """ % (self._text_color.name(), self._placeholder_color.name()))
    
    def set_placeholder_color(self, color):
        """
        设置占位符文本颜色
        
        Args:
            color (str or QColor): 占位符文本颜色
        """
        self._placeholder_color = QColor(color)
        # 更新样式表
        self.line_edit.setStyleSheet("""
            QLineEdit {
                background-color: transparent;
                border: none;
                padding: 8px 12px;
                color: %s;
                font-size: 14px;
                selection-background-color: #0a59f7;
                selection-color: white;
            }
            QLineEdit::placeholder {
                color: %s;
            }
        """ % (self._text_color.name(), self._placeholder_color.name()))
    
    def set_active_border_color(self, color):
        """
        设置激活状态下的边框颜色
        
        Args:
            color (str or QColor): 激活状态下的边框颜色
        """
        self._active_border_color = QColor(color)
        if self._is_active:
            self.update()
    
    def set_active_background_color(self, color):
        """
        设置激活状态下的背景颜色
        
        Args:
            color (str or QColor): 激活状态下的背景颜色
        """
        self._active_background_color = QColor(color)
        if self._is_active:
            self.update()