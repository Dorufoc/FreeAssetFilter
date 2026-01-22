#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 设置项类自定义控件
包含高度可定制的设置项控件，支持多种交互类型
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QLabel, QSizePolicy, QApplication, QLineEdit,
    QSpacerItem
)
from PyQt5.QtCore import Qt, pyqtSignal, QSize
from PyQt5.QtGui import QFont, QColor, QPainter, QPen, QBrush

# 导入现有自定义控件
from .input_widgets import CustomInputBox
from .button_widgets import CustomButton
from .progress_widgets import D_ProgressBar
from .switch_widgets import CustomSwitch

# 用于SVG渲染
from freeassetfilter.core.svg_renderer import SvgRenderer
import os


class CustomSettingItem(QWidget):
    """
    高度可定制的设置项控件
    特点：
    - 支持单行和双行文本显示模式
    - 支持四种交互类型：开关、按钮组、文本输入+按钮、数值控制条
    - 具有清晰的视觉层次和交互反馈
    - 支持DPI缩放
    """
    
    # 交互类型常量
    SWITCH_TYPE = 0
    BUTTON_GROUP_TYPE = 1
    INPUT_BUTTON_TYPE = 2
    VALUE_BAR_TYPE = 3
    
    # 信号定义
    switch_toggled = pyqtSignal(bool)  # 开关状态变化信号
    button_clicked = pyqtSignal(int)  # 按钮组点击信号，参数为按钮索引
    input_submitted = pyqtSignal(str)  # 输入框提交信号
    value_changed = pyqtSignal(int)  # 数值条值变化信号
    
    def __init__(self, parent=None, 
                 text="", secondary_text="", 
                 interaction_type=SWITCH_TYPE,
                 **kwargs):
        """
        初始化设置项控件
        
        Args:
            parent: 父控件
            text: 主文本
            secondary_text: 辅助文本（用于双行模式）
            interaction_type: 交互类型
            **kwargs: 交互类型相关的参数
                - 开关类型: initial_value (bool)
                - 按钮组类型: buttons (list of dict, 每个dict包含text和type)
                - 输入+按钮类型: placeholder, initial_text, button_text
                - 数值条类型: min_value, max_value, initial_value
        """
        super().__init__(parent)
        
        # 获取应用实例和DPI缩放因子
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 获取全局字体
        self.global_font = getattr(app, 'global_font', QFont())
        self.setFont(self.global_font)
        
        # 从app对象获取全局默认字体大小，确保使用正确的默认值
        self.default_font_size = getattr(app, 'default_font_size', 10)
        
        # 设置基本属性
        self.text = text
        self.secondary_text = secondary_text
        self.interaction_type = interaction_type
        self.kwargs = kwargs
        
        # 初始化UI
        self.init_ui()
        
    def init_ui(self):
        """初始化UI组件"""
        # 设置主布局
        main_layout = QHBoxLayout(self)
        # 应用DPI缩放因子到边距
        scaled_margin = int(3 * self.dpi_scale)
        scaled_spacing = int(2 * self.dpi_scale)
        main_layout.setContentsMargins(scaled_margin, scaled_margin, scaled_margin, scaled_margin)
        main_layout.setSpacing(scaled_spacing)
        
        # 设置背景色、圆角、边框和阴影，创建完整的卡片效果
        self.setObjectName("CustomSettingItem")
        # 应用DPI缩放因子到卡片样式参数
        scaled_border_radius = int(2 * self.dpi_scale)
        scaled_border_width = int(1 * self.dpi_scale)
        
        # 添加阴影效果，增强视觉层次感
        from PyQt5.QtWidgets import QGraphicsDropShadowEffect
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(int(1 * self.dpi_scale))
        shadow.setOffset(0, int(1 * self.dpi_scale))
        shadow.setColor(QColor(0, 0, 0, 15))
        self.setGraphicsEffect(shadow)
        
        # 获取主题颜色
        app = QApplication.instance()
        background_color = "#2D2D2D"  # 默认列表项正常背景色
        border_color = "#3C3C3C"  # 默认窗口边框色
        hover_background = "#3C3C3C"  # 默认列表项悬停背景色
        hover_border = "#4ECDC4"  # 默认高亮颜色
        
        # 尝试从应用实例获取主题颜色
        if hasattr(app, 'settings_manager'):
            background_color = app.settings_manager.get_setting("appearance.colors.list_item_normal", "#2D2D2D")
            border_color = app.settings_manager.get_setting("appearance.colors.window_border", "#3C3C3C")
            hover_background = app.settings_manager.get_setting("appearance.colors.list_item_hover", "#3C3C3C")
            hover_border = app.settings_manager.get_setting("appearance.colors.text_highlight", "#4ECDC4")
        
        self.setObjectName("CustomSettingItem")
        self.setStyleSheet("""
            QWidget#CustomSettingItem {
                background-color: %s;
                border: %dpx solid %s;
                border-radius: %dpx;
            }
            QWidget#CustomSettingItem:hover {
                background-color: %s;
                border-color: %s;
            }
            QWidget#CustomSettingItem > QWidget {
                background-color: transparent;
                border: none;
                border-radius: 0;
            }
        """ % (background_color, scaled_border_width, border_color, scaled_border_radius, hover_background, hover_border))
        
        # 设置主控件大小策略，允许自适应内容
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        # 左侧文本区域
        self.text_widget = self._create_text_widget()
        main_layout.addWidget(self.text_widget, 1)  # 文本区域占主要空间
        
        # 右侧交互区域
        self.interaction_widget = self._create_interaction_widget()
        # 设置交互区域的大小策略，确保它能获得足够的空间
        self.interaction_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        # 使用更合适的布局权重，确保交互区域能获得足够的空间
        main_layout.addWidget(self.interaction_widget, 0, Qt.AlignRight | Qt.AlignVCenter)
        # 确保布局能够正确计算最小尺寸
        main_layout.activate()
        
    def _create_text_widget(self):
        """创建左侧文本区域"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(int(1 * self.dpi_scale))  # 添加适当间距，避免文字重叠
        
        # 主文本
        self.main_text_label = QLabel(self.text)
        self.main_text_label.setFont(self.global_font)
        scaled_font_size = int(self.default_font_size * self.dpi_scale)
        # 获取主题文本颜色
        app = QApplication.instance()
        text_color = "#333333"  # 默认使用secondary_color作为默认值
        
        # 尝试从应用实例获取主题颜色
        if hasattr(app, 'settings_manager'):
            # 优先获取secondary_color
            text_color = app.settings_manager.get_setting("appearance.colors.secondary_color", "#333333")
        
        self.main_text_label.setStyleSheet("""
            QLabel {
                color: %s;
                font-family: '%s';
                font-size: %dpx;
                text-align: left;
                font-weight: normal;
            }
        """ % (text_color, self.global_font.family(), scaled_font_size))
        self.main_text_label.setWordWrap(True)  # 允许文字换行
        self.main_text_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)  # 顶部对齐，避免垂直居中导致的重叠
        layout.addWidget(self.main_text_label)
        
        # 如果有辅助文本，则显示双行模式
        if self.secondary_text:
            # 辅助文本字号为黑色文字大小的1/1.3取整
            secondary_font_size = int(scaled_font_size)
            self.secondary_text_label = QLabel(self.secondary_text)
            self.secondary_text_label.setFont(self.global_font)
            # 获取主题辅助文本颜色
            app = QApplication.instance()
            
            # 尝试获取normal_color
            normal_color_str = "#808080"  # 默认值
            
            # 优先从应用实例获取设置管理器
            if hasattr(app, 'settings_manager'):
                normal_color_str = app.settings_manager.get_setting("appearance.colors.normal_color", "#808080")
            else:
                # 回退方案：直接创建设置管理器实例获取设置
                from freeassetfilter.core.settings_manager import SettingsManager
                try:
                    settings_manager = SettingsManager()
                    normal_color_str = settings_manager.get_setting("appearance.colors.normal_color", "#808080")
                except Exception:
                    # 如果无法创建设置管理器，使用默认值
                    pass
            
            # 使用QColor将颜色加深30%
            from PyQt5.QtGui import QColor
            normal_color = QColor(normal_color_str)
            # darker(130)表示加深30%（100=不变，>100=加深，<100=变亮）
            secondary_text_color = normal_color.darker(130).name()
            
            self.secondary_text_label.setStyleSheet("""
                QLabel {
                    color: %s;
                    font-family: '%s';
                    font-size: %dpx;
                    text-align: left;
                    font-weight: normal;
                }
            """ % (secondary_text_color, self.global_font.family(), secondary_font_size))
            self.secondary_text_label.setWordWrap(True)  # 允许文字换行
            self.secondary_text_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)  # 顶部对齐
            layout.addWidget(self.secondary_text_label)
        
        return widget
    
    def _create_interaction_widget(self):
        """创建右侧交互区域"""
        if self.interaction_type == self.SWITCH_TYPE:
            # 开关控件
            return self._create_switch_widget()
        elif self.interaction_type == self.BUTTON_GROUP_TYPE:
            # 按钮组控件
            return self._create_button_group_widget()
        elif self.interaction_type == self.INPUT_BUTTON_TYPE:
            # 文本输入与按钮组合控件
            return self._create_input_button_widget()
        elif self.interaction_type == self.VALUE_BAR_TYPE:
            # 数值控制条控件
            return self._create_value_bar_widget()
        else:
            # 未知类型，返回空控件
            widget = QWidget()
            widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            return widget
    
    def _create_switch_widget(self):
        """创建开关控件"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        # 设置布局约束，允许完全自适应内容大小
        layout.setSizeConstraint(layout.SetMinAndMaxSize)
        
        # 创建自定义开关控件
        initial_value = self.kwargs.get('initial_value', False)
        self.switch_button = CustomSwitch(initial_value=initial_value)
        
        # 连接信号
        self.switch_button.toggled.connect(self._on_switch_toggled)
        
        layout.addWidget(self.switch_button)
        
        # 设置容器大小策略，允许自适应内容
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # 确保容器没有宽度限制，允许完全自适应内容
        widget.setMinimumWidth(0)
        widget.setMaximumWidth(16777215)
        return widget
    
    def _on_switch_toggled(self, checked):
        """开关状态变化处理"""
        self.switch_toggled.emit(checked)
    
    def _create_button_group_widget(self):
        """创建按钮组控件"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        # 设置布局约束，允许完全自适应内容大小
        layout.setSizeConstraint(layout.SetMinAndMaxSize)
        # 应用DPI缩放因子到按钮间距
        scaled_spacing = int(2 * self.dpi_scale)
        layout.setSpacing(scaled_spacing)
        
        # 获取按钮配置
        buttons = self.kwargs.get('buttons', [{'text': '确定', 'type': 'primary'}])
        
        self.button_group = []
        for i, btn_config in enumerate(buttons):
            btn = CustomButton(btn_config.get('text', '按钮'))
            btn_type = btn_config.get('type', 'primary')
            
            # 设置按钮类型样式
            if btn_type == 'secondary':
                btn.set_button_type('secondary')
            elif btn_type == 'primary':
                btn.set_button_type('primary')
            else:
                btn.set_button_type('normal')
            
            # 连接信号
            btn.clicked.connect(lambda checked, idx=i: self._on_button_clicked(idx))
            
            layout.addWidget(btn)
            self.button_group.append(btn)
        
        # 设置容器大小策略，允许自适应内容
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # 确保容器没有宽度限制，允许完全自适应内容
        widget.setMinimumWidth(0)
        widget.setMaximumWidth(16777215)
        return widget
    
    def _on_button_clicked(self, button_index):
        """按钮点击处理"""
        self.button_clicked.emit(button_index)
    
    def _create_input_button_widget(self):
        """创建文本输入与按钮组合控件"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        # 设置布局约束，允许完全自适应内容大小
        layout.setSizeConstraint(layout.SetMinAndMaxSize)
        # 应用DPI缩放因子到组件间距
        scaled_spacing = int(2 * self.dpi_scale)
        layout.setSpacing(scaled_spacing)
        
        # 创建文本输入框
        placeholder = self.kwargs.get('placeholder', '')
        initial_text = self.kwargs.get('initial_text', '')
        self.input_box = CustomInputBox(
            placeholder_text=placeholder,
            initial_text=initial_text,
            height=20  # 合理高度，确保输入框正常显示
        )
        
        # 确保输入框有合适的尺寸策略，能够正确扩展
        self.input_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        # 创建按钮
        button_text = self.kwargs.get('button_text', '确定')
        self.submit_button = CustomButton(button_text)
        
        # 连接信号
        self.submit_button.clicked.connect(self._on_input_button_clicked)
        
        layout.addWidget(self.input_box, 1)  # 输入框占主要空间
        layout.addWidget(self.submit_button, 0)  # 按钮占固定空间
        
        # 设置容器大小策略，允许自适应内容
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # 确保容器没有宽度限制，允许完全自适应内容
        widget.setMinimumWidth(0)
        widget.setMaximumWidth(16777215)
        return widget
    
    def _on_input_button_clicked(self):
        """输入按钮点击处理"""
        text = self.input_box.get_text()
        self.input_submitted.emit(text)
    
    def _create_value_bar_widget(self):
        """创建数值控制条控件"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        # 设置布局约束，允许完全自适应内容大小
        layout.setSizeConstraint(layout.SetMinAndMaxSize)
        # 应用DPI缩放因子到组件间距
        scaled_spacing = int(4 * self.dpi_scale)
        layout.setSpacing(scaled_spacing)
        
        # 数值控制条
        min_value = self.kwargs.get('min_value', 0)
        max_value = self.kwargs.get('max_value', 100)
        initial_value = self.kwargs.get('initial_value', 50)
        
        self.value_bar = D_ProgressBar(orientation=D_ProgressBar.Horizontal)
        self.value_bar.setRange(min_value, max_value)
        self.value_bar.setValue(initial_value)
        
        # 数值显示
        self.value_label = QLabel(str(initial_value))
        self.value_label.setFont(self.global_font)
        # 应用DPI缩放因子到字体大小
        scaled_font_size = int(self.default_font_size * self.dpi_scale)
        # 获取主题文本颜色
        app = QApplication.instance()
        text_color = "#333333"  # 默认使用secondary_color作为默认值
        
        # 尝试从应用实例获取主题颜色
        if hasattr(app, 'settings_manager'):
            # 优先获取secondary_color
            text_color = app.settings_manager.get_setting("appearance.colors.secondary_color", "#333333")
        
        self.value_label.setStyleSheet("""
            QLabel {
                color: %s;
                font-size: %dpx;
                text-align: center;
            }
        """ % (text_color, scaled_font_size))
        
        # 连接信号
        self.value_bar.valueChanged.connect(self._on_value_changed)
        
        layout.addWidget(self.value_bar)
        layout.addWidget(self.value_label)
        
        # 设置容器大小策略，允许自适应内容
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # 确保容器没有宽度限制，允许完全自适应内容
        widget.setMinimumWidth(0)
        widget.setMaximumWidth(16777215)
        return widget
    
    def _on_value_changed(self, value):
        """数值变化处理"""
        self.value_label.setText(str(value))
        self.value_changed.emit(value)
    

    
    # 公共方法
    def set_text(self, text):
        """设置主文本"""
        self.text = text
        self.main_text_label.setText(text)
    
    def set_secondary_text(self, text):
        """设置辅助文本"""
        self.secondary_text = text
        if hasattr(self, 'secondary_text_label'):
            self.secondary_text_label.setText(text)
    
    def set_switch_value(self, value):
        """设置开关状态"""
        if self.interaction_type == self.SWITCH_TYPE:
            self.switch_button.setChecked(value)
    
    def get_switch_value(self):
        """获取开关状态"""
        if self.interaction_type == self.SWITCH_TYPE:
            return self.switch_button.isChecked()
        return False
    
    def get_input_text(self):
        """获取输入框文本"""
        if self.interaction_type == self.INPUT_BUTTON_TYPE:
            return self.input_box.get_text()
        return ""
    
    def set_input_text(self, text):
        """设置输入框文本"""
        if self.interaction_type == self.INPUT_BUTTON_TYPE:
            self.input_box.set_text(text)
    
    def set_value(self, value):
        """设置数值条值"""
        if self.interaction_type == self.VALUE_BAR_TYPE:
            self.value_bar.setValue(value)
    
    def get_value(self):
        """获取数值条值"""
        if self.interaction_type == self.VALUE_BAR_TYPE:
            return self.value_bar.value()
        return 0


# 更新 __init__.py 文件，导出新控件
# 注意：在实际使用时，需要手动更新 custom_widgets.py 文件，将新控件添加到导入和导出列表中