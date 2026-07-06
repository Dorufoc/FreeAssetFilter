#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 设置项类自定义控件
包含高度可定制的设置项控件，支持多种交互类型
"""

import weakref

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QSizePolicy, QApplication, QLineEdit,
    QLayout,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor

from .input_widgets import CustomInputBox
from .button_widgets import CustomButton
from .progress_widgets import D_ProgressBar
from .switch_widgets import CustomSwitch
from .hover_tooltip import HoverTooltip


def _get_sm_color(key, default):
    app = QApplication.instance()
    if app and hasattr(app, "settings_manager"):
        return app.settings_manager.get_setting(f"appearance.colors.{key}", default)
    return default


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
    FOLDER_BUTTON_TYPE = 4
    
    # 信号定义
    switch_toggled = Signal(bool)  # 开关状态变化信号
    button_clicked = Signal(int)  # 按钮组点击信号，参数为按钮索引
    input_submitted = Signal(str)  # 输入框提交信号
    value_changed = Signal(int)  # 数值条值变化信号
    folder_selected = Signal(str)  # 文件夹选择信号
    
    def __init__(self, parent=None,
                 text="", secondary_text="",
                 interaction_type=SWITCH_TYPE,
                 tooltip_text="",
                 dpi_scale=None,
                 global_font=None,
                 settings_manager=None,
                 **kwargs):
        """
        初始化设置项控件

        Args:
            parent: 父控件
            text: 主文本
            secondary_text: 辅助文本（用于双行模式）
            interaction_type: 交互类型
            tooltip_text: 悬浮提示文本（用于hover tooltip显示）
            dpi_scale: DPI缩放因子，None时从QApplication自动获取
            **kwargs: 交互类型相关的参数
                - 开关类型: initial_value (bool)
                - 按钮组类型: buttons (list of dict, 每个dict包含text和type)
                - 输入+按钮类型: placeholder, initial_text, button_text
                - 数值条类型: min_value, max_value, initial_value
        """
        super().__init__(parent)

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
            from freeassetfilter.core.managers.settings_manager import SettingsManager
            self._settings_manager = SettingsManager()

        # 从app对象获取全局默认字体大小，确保使用正确的默认值
        app = QApplication.instance()
        self.default_font_size = getattr(app, 'default_font_size', 10)

        # 设置基本属性
        self.text = text
        self.secondary_text = secondary_text
        self.interaction_type = interaction_type
        self._tooltip_text = tooltip_text  # 悬浮提示文本
        self.kwargs = kwargs
        self._hover_tooltip = None

        # 初始化UI
        self.init_ui()

        # 使用自定义 HoverTooltip
        if self._tooltip_text:
            self._ensure_hover_tooltip()
        
    def _ensure_hover_tooltip(self):
        if self._hover_tooltip is None:
            self._hover_tooltip = HoverTooltip(self)
            self._hover_tooltip.set_target_widget(self)

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        m = int(3 * self.dpi_scale)
        main_layout.setContentsMargins(m, m, m, m)
        main_layout.setSpacing(int(2 * self.dpi_scale))

        self.setObjectName("CustomSettingItem")
        br = int(2 * self.dpi_scale)
        base = self._settings_manager.get_setting("appearance.colors.base_color", "#FFFFFF")
        sc = self._settings_manager.get_setting("appearance.colors.secondary_color", "#333333")
        nc = self._settings_manager.get_setting("appearance.colors.normal_color", "#e0e0e0")
        self.setStyleSheet(f"""
            QWidget#CustomSettingItem {{
                background-color: transparent;
                border-radius: {br}px;
            }}
        """)
        
        # 设置主控件大小策略，允许自适应内容
        # 使用 Preferred 而不是 Fixed，允许控件根据内容自动调整高度
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        
        # 左侧文本区域
        self.text_widget = self._create_text_widget()
        main_layout.addWidget(self.text_widget, 1)  # 文本区域占主要空间
        
        # 右侧交互区域
        self.interaction_widget = self._create_interaction_widget()
        # 设置交互区域的大小策略，垂直方向使用 Preferred 以允许随文本区域扩展
        self.interaction_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        # 使用更合适的布局权重，确保交互区域能获得足够的空间
        main_layout.addWidget(self.interaction_widget, 0, Qt.AlignRight | Qt.AlignVCenter)
        # 确保布局能够正确计算最小尺寸
        main_layout.activate()
        
    def _create_text_widget(self):
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(int(1 * self.dpi_scale))

        sc = self._settings_manager.get_setting("appearance.colors.secondary_color", "#333333")
        nc = self._settings_manager.get_setting("appearance.colors.normal_color", "#e0e0e0")

        self.main_text_label = QLabel(self.text)
        self.main_text_label.setFont(self.global_font)
        self.main_text_label.setStyleSheet(f"color: {sc}; text-align: left;")
        self.main_text_label.setWordWrap(True)
        self.main_text_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.main_text_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.main_text_label.setMinimumHeight(0)
        layout.addWidget(self.main_text_label)

        if self.secondary_text:
            self.secondary_text_label = QLabel(self.secondary_text)
            self.secondary_text_label.setFont(self.global_font)
            darker = QColor(nc).darker(130).name()
            self.secondary_text_label.setStyleSheet(f"color: {darker}; text-align: left;")
            self.secondary_text_label.setWordWrap(True)
            self.secondary_text_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            self.secondary_text_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            self.secondary_text_label.setMinimumHeight(0)
            layout.addWidget(self.secondary_text_label)

        return widget
    
    def _create_interaction_widget(self):
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
        elif self.interaction_type == self.FOLDER_BUTTON_TYPE:
            # 文件夹选择按钮控件
            return self._create_folder_button_widget()
        else:
            # 未知类型，返回空控件
            widget = QWidget()
            widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            return widget
    
    def _create_switch_widget(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        # 设置布局约束，允许完全自适应内容大小 (Qt6中使用SizeConstraint枚举)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        
        # 创建自定义开关控件
        initial_value = self.kwargs.get('initial_value', False)
        self.switch_button = CustomSwitch(initial_value=initial_value)
        
        # 连接信号
        self.switch_button.toggled.connect(self._on_switch_toggled)
        
        layout.addWidget(self.switch_button)
        
        # 设置容器大小策略，垂直方向使用 Preferred 以允许随内容扩展
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        # 确保容器没有宽度限制，允许完全自适应内容
        widget.setMinimumWidth(0)
        widget.setMaximumWidth(16777215)
        return widget

    def _create_folder_button_widget(self):
        from PySide6.QtWidgets import QFileDialog

        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        layout.setSpacing(int(2 * self.dpi_scale))

        nc = self._settings_manager.get_setting("appearance.colors.normal_color", "#e0e0e0")
        sc = self._settings_manager.get_setting("appearance.colors.secondary_color", "#333333")
        initial_path = self.kwargs.get('initial_text', "")

        self.folder_path_label = QLabel(initial_path if initial_path else "未设置")
        self.folder_path_label.setFont(self.global_font)
        self.folder_path_label.setStyleSheet(f"color: {nc}; padding-left: 5px;")
        self.folder_path_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.folder_button = CustomButton("选择文件夹", button_type="normal")
        self.folder_button.clicked.connect(self._on_folder_button_clicked)

        layout.addWidget(self.folder_path_label)
        layout.addWidget(self.folder_button)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        widget.setMinimumWidth(0)
        widget.setMaximumWidth(16777215)
        return widget

    def _on_folder_button_clicked(self):
        from PySide6.QtWidgets import QFileDialog
        current_path = self.folder_path_label.text() if self.folder_path_label.text() != "未设置" else ""
        folder_path = QFileDialog.getExistingDirectory(self, "选择文件夹", current_path)
        if folder_path:
            self.folder_path_label.setText(folder_path)
            sc = self._settings_manager.get_setting("appearance.colors.secondary_color", "#333333")
            self.folder_path_label.setStyleSheet(f"color: {sc}; padding-left: 5px;")
            self.folder_selected.emit(folder_path)
    
    def _on_switch_toggled(self, checked):
        self.switch_toggled.emit(checked)

    def _create_button_group_widget(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        # 设置布局约束，允许完全自适应内容大小 (Qt6中使用SizeConstraint枚举)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
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
            weak_self = weakref.ref(self)
            btn.clicked.connect(lambda checked, idx=i: (s := weak_self()) and s._on_button_clicked(idx))
            
            layout.addWidget(btn)
            self.button_group.append(btn)

        # 设置容器大小策略，垂直方向使用 Preferred 以允许随内容扩展
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        # 确保容器没有宽度限制，允许完全自适应内容
        widget.setMinimumWidth(0)
        widget.setMaximumWidth(16777215)
        return widget

    def _on_button_clicked(self, button_index):
        self.button_clicked.emit(button_index)
    
    def _create_input_button_widget(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        # 设置布局约束，允许完全自适应内容大小 (Qt6中使用SizeConstraint枚举)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
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

        # 设置容器大小策略，垂直方向使用 Preferred 以允许随内容扩展
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        # 确保容器没有宽度限制，允许完全自适应内容
        widget.setMinimumWidth(0)
        widget.setMaximumWidth(16777215)
        return widget

    def _on_input_button_clicked(self):
        text = self.input_box.get_text()
        self.input_submitted.emit(text)
    
    def _create_value_bar_widget(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        layout.setSpacing(int(4 * self.dpi_scale))

        min_value = self.kwargs.get('min_value', 0)
        max_value = self.kwargs.get('max_value', 100)
        initial_value = self.kwargs.get('initial_value', 50)

        self.value_bar = D_ProgressBar(orientation=D_ProgressBar.Horizontal)
        self.value_bar.setRange(min_value, max_value)
        self.value_bar.setValue(initial_value)

        sc = self._settings_manager.get_setting("appearance.colors.secondary_color", "#333333")
        self.value_label = QLabel(str(initial_value))
        self.value_label.setFont(self.global_font)
        self.value_label.setStyleSheet(f"color: {sc}; text-align: center;")

        self.value_bar.valueChanged.connect(self._on_value_changed)

        layout.addWidget(self.value_bar)
        layout.addWidget(self.value_label)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        widget.setMinimumWidth(0)
        widget.setMaximumWidth(16777215)
        return widget
    
    def _on_value_changed(self, value):
        self.value_label.setText(str(value))
        self.value_changed.emit(value)
    

    
    # 公共方法
    def set_text(self, text):
        self.text = text
        self.main_text_label.setText(text)

    def set_secondary_text(self, text):
        self.secondary_text = text
        if hasattr(self, 'secondary_text_label'):
            self.secondary_text_label.setText(text)
    
    def set_switch_value(self, value):
        if self.interaction_type == self.SWITCH_TYPE:
            self.switch_button.setChecked(value)

    def get_switch_value(self):
        if self.interaction_type == self.SWITCH_TYPE:
            return self.switch_button.isChecked()
        return False
    
    def get_input_text(self):
        if self.interaction_type == self.INPUT_BUTTON_TYPE:
            return self.input_box.get_text()
        return ""

    def set_value(self, value):
        if self.interaction_type == self.VALUE_BAR_TYPE:
            self.value_bar.setValue(value)

    def get_value(self):
        if self.interaction_type == self.VALUE_BAR_TYPE:
            return self.value_bar.value()
        return 0

    def set_tooltip_text(self, text):
        self._tooltip_text = text
        if text:
            self._ensure_hover_tooltip()

    def get_tooltip_text(self):
        return self._tooltip_text
