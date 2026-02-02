#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 现代化设置窗口
包含现代化设计风格的设置窗口实现
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QTabWidget, QPushButton, QGroupBox, QSizePolicy, QDialog,
    QApplication, QSplitter
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtWidgets import QGraphicsDropShadowEffect

# 导入自定义控件
from freeassetfilter.widgets.setting_widgets import CustomSettingItem
from freeassetfilter.widgets.button_widgets import CustomButton
from freeassetfilter.widgets.smooth_scroller import D_ScrollBar
from freeassetfilter.widgets.smooth_scroller import SmoothScroller
from freeassetfilter.widgets.list_widgets import CustomSelectList
from freeassetfilter.widgets.message_box import CustomMessageBox
from freeassetfilter.widgets.menu_list import D_MenuList, D_MenuListItem

# 导入设置管理器
from freeassetfilter.core.settings_manager import SettingsManager

# 导入SVG渲染器，用于主题颜色变化时刷新SVG图标
from freeassetfilter.core.svg_renderer import SvgRenderer

# 导入主题管理器组件
from freeassetfilter.core.theme_manager import ThemeManager

# 导入系统模块
import os
import sys

# 字体缓存，避免重复获取系统字体
_cached_font_families = None


def _get_font_families_cached():
    """
    获取系统字体列表（带缓存）

    Returns:
        list: 系统字体列表
    """
    global _cached_font_families
    if _cached_font_families is None:
        from PyQt5.QtGui import QFontDatabase
        font_db = QFontDatabase()
        _cached_font_families = font_db.families()
    return _cached_font_families


class ModernSettingsWindow(QDialog):
    """
    现代化设计风格的设置窗口
    特点：
    - 左侧导航栏 + 右侧内容区域的布局
    - 支持多个设置类别
    - 卡片式设计，带有圆角和阴影效果
    - 使用现有的自定义控件
    - 支持DPI缩放
    - 实时预览设置效果
    """
    
    # 信号定义
    settings_saved = pyqtSignal(dict)  # 设置保存信号
    
    def __init__(self, parent=None):
        super().__init__(parent, Qt.Dialog | Qt.WindowMaximizeButtonHint | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint)
        
        self.setWindowTitle("设置")
        self.setSizeGripEnabled(False)
        
        self.settings_manager = None
        if parent is not None:
            try:
                if hasattr(parent, 'settings_manager'):
                    self.settings_manager = parent.settings_manager
            except (RuntimeError, AttributeError):
                pass
        
        if self.settings_manager is None:
            try:
                app = QApplication.instance()
                if app is not None and hasattr(app, 'settings_manager'):
                    self.settings_manager = app.settings_manager
            except (RuntimeError, AttributeError):
                pass
        
        if self.settings_manager is None:
            self.settings_manager = SettingsManager()
        
        # 初始化主题管理器
        self.theme_manager = ThemeManager(self.settings_manager)
        
        # 当前设置值
        self.current_settings = {}
        
        # 加载当前设置
        self.load_settings()
        
        # 统一的设置组样式
        self._update_styles()
        
        # 初始化UI
        self.init_modern_ui()
    
    def init_modern_ui(self):
        """
        初始化现代化设置窗口UI
        """
        self.setMinimumSize(560, 380)
        self.resize(560, 380)

        self.setStyleSheet(f"""
            QDialog {{ 
                background-color: {self.theme_manager.get_theme_colors()['auxiliary_color']}; 
            }}
        """)

        app = QApplication.instance()
        dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        handle_width = int(10)
        base_color = self.theme_manager.get_theme_colors()['base_color']
        normal_color = self.theme_manager.get_theme_colors()['normal_color']
        secondary_color = self.theme_manager.get_theme_colors()['secondary_color']
        accent_color = self.theme_manager.get_theme_colors()['accent_color']
        auxiliary_color = self.theme_manager.get_theme_colors()['auxiliary_color']
        main_layout = QHBoxLayout(self)
        self.content_layout = main_layout
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(0)

        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.setContentsMargins(0, 0, 0, 0)
        main_splitter.setHandleWidth(handle_width)
        main_splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background-color: {auxiliary_color};
                width: {handle_width}px;
            }}
            QSplitter::handle:hover {{
                background-color: {accent_color};
            }}
        """)

        self.navigation_widget = self._create_navigation_widget()
        main_splitter.addWidget(self.navigation_widget)

        self.content_area = self._create_content_area()
        main_splitter.addWidget(self.content_area)

        min_nav_width = int(80 * dpi_scale)
        main_splitter.setSizes([min_nav_width, 300])
        main_splitter.setStretchFactor(1, 1)

        self._main_splitter = main_splitter
        main_layout.addWidget(main_splitter, 1)

        self._fill_tab_content("general")
    
    def _create_navigation_widget(self):
        """
        创建左侧导航栏
        """
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Expanding)

        app = QApplication.instance()
        dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        min_width = int(80 * dpi_scale)
        widget.setMinimumWidth(min_width)

        widget.setObjectName("navigationContainer")
        widget.setStyleSheet(f"""
            QWidget#navigationContainer {{ 
                background-color: {self.theme_manager.get_theme_colors()['base_color']}; 
                border-radius: 8px;
                border: 1px solid {self.theme_manager.get_theme_colors()['normal_color']};
            }}
        """)

        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 15, 8, 10)
        layout.setSpacing(8)

        title_label = QLabel("设置")
        title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        title_label.setStyleSheet(f"""
            QLabel {{ 
                font-family: 'Noto Sans SC'; 
                font-size: 14px;
                font-weight: 600;
                color: {self.theme_manager.get_theme_colors()['secondary_color']};
                margin-bottom: 10px;
                padding: 5px;
            }}
        """)
        layout.addWidget(title_label)

        nav_scroll_area = QScrollArea()
        nav_scroll_area.setWidgetResizable(True)
        nav_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        nav_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        base_color = self.theme_manager.get_theme_colors()['base_color']
        auxiliary_color = self.theme_manager.get_theme_colors()['auxiliary_color']
        normal_color = self.theme_manager.get_theme_colors()['normal_color']
        secondary_color = self.theme_manager.get_theme_colors()['secondary_color']
        accent_color = self.theme_manager.get_theme_colors()['accent_color']

        nav_scrollbar_style = f"""
            QScrollArea {{
                border: 0px solid transparent;
                background-color: transparent;
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: transparent;
            }}
            QScrollBar:vertical {{
                width: 6px;
                background-color: {auxiliary_color};
                border: 0px solid transparent;
                border-radius: 0px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {normal_color};
                min-height: 15px;
                border-radius: 3px;
                border: none;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {secondary_color};
                border: none;
            }}
            QScrollBar::handle:vertical:pressed {{
                background-color: {accent_color};
                border: none;
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height: 0px;
                border: none;
            }}
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {{
                background: none;
                border: 0px solid transparent;
                border: none;
            }}
        """
        nav_scroll_area.setStyleSheet(nav_scrollbar_style)

        nav_scroll_area.setVerticalScrollBar(D_ScrollBar(nav_scroll_area, Qt.Vertical))
        nav_scroll_area.verticalScrollBar().set_colors(normal_color, secondary_color, accent_color, auxiliary_color)

        SmoothScroller.apply_to_scroll_area(nav_scroll_area)

        nav_content = QWidget()
        nav_content.setStyleSheet(f"""
            QWidget {{
                background-color: transparent;
            }}
        """)
        nav_layout = QVBoxLayout(nav_content)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(8)
        nav_layout.setAlignment(Qt.AlignTop)

        self.navigation_buttons = []
        self.navigation_items = [
            {"text": "通用", "id": "general"},
            {"text": "文件选择器", "id": "file_selector"},
            {"text": "文件暂存池", "id": "file_staging"},
            {"text": "播放器", "id": "player"},
            {"text": "开发者设置", "id": "developer"}
        ]

        for i, item in enumerate(self.navigation_items):
            if i == 0:
                button = CustomButton(item["text"], button_type="primary", display_mode="text", height=20)
            else:
                button = CustomButton(item["text"], button_type="normal", display_mode="text", height=20)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.clicked.connect(lambda checked, idx=i: self._on_navigation_clicked(idx))
            self.navigation_buttons.append(button)
            nav_layout.addWidget(button)

        nav_scroll_area.setWidget(nav_content)
        layout.addWidget(nav_scroll_area, 1)

        return widget
    
    def _create_content_area(self):
        """
        创建右侧内容区域
        """
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        widget.setObjectName("contentContainer")
        widget.setStyleSheet(f"""
            QWidget#contentContainer {{ 
                background-color: {self.theme_manager.get_theme_colors()['base_color']}; 
                border-radius: 8px;
                border: 1px solid {self.theme_manager.get_theme_colors()['normal_color']};
            }}
        """)

        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)

        self.content_title = QLabel("通用设置")
        self.content_title.setStyleSheet(f"""
            QLabel {{ 
                font-family: 'Noto Sans SC'; 
                font-size: 14px;
                font-weight: 600;
                color: {self.theme_manager.get_theme_colors()['secondary_color']};
                margin-bottom: 10px;
                padding: 5px;
            }}
        """)
        layout.addWidget(self.content_title)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        base_color = self.theme_manager.get_theme_colors()['base_color']
        auxiliary_color = self.theme_manager.get_theme_colors()['auxiliary_color']
        normal_color = self.theme_manager.get_theme_colors()['normal_color']
        secondary_color = self.theme_manager.get_theme_colors()['secondary_color']
        accent_color = self.theme_manager.get_theme_colors()['accent_color']

        scrollbar_style = f"""
            QScrollArea {{
                border: 0px solid transparent;
                background-color: {base_color};
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: {base_color};
            }}
            QScrollBar:vertical {{
                width: 6px;
                background-color: {auxiliary_color};
                border: 0px solid transparent;
                border-radius: 0px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {normal_color};
                min-height: 15px;
                border-radius: 3px;
                border: none;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {secondary_color};
                border: none;
            }}
            QScrollBar::handle:vertical:pressed {{
                background-color: {accent_color};
                border: none;
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height: 0px;
                border: none;
            }}
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {{
                background: none;
                border: 0px solid transparent;
                border: none;
            }}
        """
        self.scroll_area.setStyleSheet(scrollbar_style)
        
        # 使用动画滚动条
        self.scroll_area.setVerticalScrollBar(D_ScrollBar(self.scroll_area, Qt.Vertical))
        self.scroll_area.verticalScrollBar().set_colors(normal_color, secondary_color, accent_color, auxiliary_color)
        
        SmoothScroller.apply_to_scroll_area(self.scroll_area)
        
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(15)
        self.scroll_layout.setAlignment(Qt.AlignTop)

        self.scroll_area.setWidget(self.scroll_content)
        layout.addWidget(self.scroll_area, 1)

        self.buttons_widget = self._create_buttons_widget()
        layout.addWidget(self.buttons_widget)

        return widget
    
    def _create_appearance_tab(self):
        """
        创建外观设置标签页
        """
        widget, layout = self._create_scrollable_tab("外观设置")
        self.appearance_layout = layout
        return widget
    
    def _create_font_tab(self):
        """
        创建字体设置标签页
        """
        widget, layout = self._create_scrollable_tab("字体设置")
        self.font_layout = layout
        return widget
    
    def _create_file_selector_tab(self):
        """
        创建文件选择器设置标签页
        """
        widget, layout = self._create_scrollable_tab("文件选择器设置")
        self.file_selector_layout = layout
        return widget
    
    def _create_file_staging_tab(self):
        """
        创建文件暂存池设置标签页
        """
        widget, layout = self._create_scrollable_tab("文件暂存池设置")
        self.file_staging_layout = layout
        return widget
    
    def _create_player_tab(self):
        """
        创建播放器设置标签页
        """
        widget, layout = self._create_scrollable_tab("播放器设置")
        self.player_layout = layout
        return widget
    
    def _create_general_tab(self):
        """
        创建通用设置标签页
        """
        widget, layout = self._create_scrollable_tab("通用设置")
        self.general_layout = layout
        return widget
    
    def _create_scrollable_tab(self, title):
        """
        创建可滚动的标签页内容
        
        Args:
            title (str): 标签页标题
        
        Returns:
            tuple: (QWidget, QLayout) 标签页内容部件和滚动布局
        """
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 标题标签
        title_label = QLabel(title)
        
        # 从app对象获取全局默认字体大小
        app = self.parent() if hasattr(self, 'parent') and self.parent() else None
        default_font_size = getattr(app, 'default_font_size', 18)
        scaled_font_size = int(default_font_size * 1)
        
        title_label.setStyleSheet(f"""
            QLabel {{ 
                font-size: {scaled_font_size}px;
                font-weight: 600;
                color: {self.theme_manager.get_theme_colors()['secondary_color']};
                margin-bottom: 5px;
                padding: 2px;
            }}
        """)
        layout.addWidget(title_label)
        
        # 滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{ 
                background-color: transparent;
                border: none;
            }}
            QScrollBar:vertical {{ 
                width: 8px;
                background-color: {self.theme_manager.get_theme_colors()['auxiliary_color']}; 
            }}
            QScrollBar::handle:vertical {{ 
                background-color: {self.theme_manager.get_theme_colors()['normal_color']}; 
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{ 
                background-color: {self.theme_manager.get_theme_colors()['accent_color']}; 
            }}
        """)
        
        # 滚动内容
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        
        # 应用DPI缩放因子到布局
        scaled_padding = 2
        scaled_spacing = 3
        scroll_layout.setContentsMargins(scaled_padding, scaled_padding, scaled_padding, scaled_padding)
        scroll_layout.setSpacing(scaled_spacing)
        
        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area, 1)
        
        return widget, scroll_layout
    
    def _create_buttons_widget(self):
        """
        创建底部按钮区域
        """
        widget = QWidget()
        layout = QHBoxLayout(widget)
        
        # 应用DPI缩放因子到布局
        scaled_spacing = 3
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(scaled_spacing)
        
        # 重置按钮
        self.reset_button = CustomButton("重置", button_type="secondary")
        self.reset_button.clicked.connect(self.reset_settings)
        layout.addWidget(self.reset_button)
        
        # 占位符
        layout.addStretch()
        
        # 保存按钮
        self.save_button = CustomButton("保存", button_type="primary")
        self.save_button.clicked.connect(self.save_settings)
        layout.addWidget(self.save_button)
        
        return widget
    
    def _on_navigation_clicked(self, index):
        """
        导航选项点击事件处理

        Args:
            index (int): 选中的导航项索引
        """
        nav_ids = ["general", "file_selector", "file_staging", "player", "developer"]
        
        if 0 <= index < len(nav_ids):
            for i, button in enumerate(self.navigation_buttons):
                if i == index:
                    button.button_type = "primary"
                    button.update_style()
                else:
                    button.button_type = "normal"
                    button.update_style()
            
            self._fill_tab_content(nav_ids[index])
    
    def _fill_tab_content(self, tab_id):
        """
        根据标签页ID填充内容

        Args:
            tab_id (str): 标签页ID
        """
        # 更新内容标题
        title_mapping = {
            "general": "通用设置",
            "file_selector": "文件选择器设置",
            "file_staging": "文件暂存池设置",
            "player": "播放器设置",
            "developer": "开发者设置"
        }

        if tab_id in title_mapping:
            self.content_title.setText(title_mapping[tab_id])

        # 清空当前内容
        while self.scroll_layout.count() > 0:
            item = self.scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 根据标签页ID添加设置项
        if tab_id == "general":
            self._add_general_settings()
        elif tab_id == "file_selector":
            self._add_file_selector_settings()
        elif tab_id == "file_staging":
            self._add_file_staging_settings()
        elif tab_id == "player":
            self._add_player_settings()
        elif tab_id == "developer":
            self._add_developer_settings()

    def _add_file_selector_settings(self):
        """
        添加文件选择器设置项
        """
        file_selector_group = QGroupBox("文件选择器设置")
        file_selector_group.setStyleSheet(self.group_box_style)
        file_selector_layout = QVBoxLayout(file_selector_group)
        
        # 自动清理缩略图缓存
        self.auto_clear_cache_switch = CustomSettingItem(
            text="自动清理缩略图缓存",
            secondary_text="退出应用时自动清理缩略图缓存",
            interaction_type=CustomSettingItem.SWITCH_TYPE,
            initial_value=self.settings_manager.get_setting("file_selector.auto_clear_thumbnail_cache", True)
        )
        self.auto_clear_cache_switch.switch_toggled.connect(lambda value: self.current_settings.update({"file_selector.auto_clear_thumbnail_cache": value}))
        file_selector_layout.addWidget(self.auto_clear_cache_switch)
        
        # 缓存清理周期
        self.cache_cleanup_period = CustomSettingItem(
            text="缓存清理周期",
            secondary_text="设置缓存自动清理的周期（天）",
            interaction_type=CustomSettingItem.VALUE_BAR_TYPE,
            min_value=1,
            max_value=30,
            initial_value=self.settings_manager.get_setting("file_selector.cache_cleanup_period", 7)
        )
        self.cache_cleanup_period.value_changed.connect(lambda value: self.current_settings.update({"file_selector.cache_cleanup_period": value}))
        file_selector_layout.addWidget(self.cache_cleanup_period)
        
        # 缓存清理阈值
        self.cache_cleanup_threshold = CustomSettingItem(
            text="缓存清理阈值",
            secondary_text="设置缓存大小阈值（MB），超过此值将自动清理",
            interaction_type=CustomSettingItem.VALUE_BAR_TYPE,
            min_value=100,
            max_value=2000,
            initial_value=self.settings_manager.get_setting("file_selector.cache_cleanup_threshold", 500)
        )
        self.cache_cleanup_threshold.value_changed.connect(lambda value: self.current_settings.update({"file_selector.cache_cleanup_threshold": value}))
        file_selector_layout.addWidget(self.cache_cleanup_threshold)
        
        # 恢复上次路径
        self.restore_last_path_switch = CustomSettingItem(
            text="恢复上次路径",
            secondary_text="启动时恢复上次打开的目录",
            interaction_type=CustomSettingItem.SWITCH_TYPE,
            initial_value=self.settings_manager.get_setting("file_selector.restore_last_path", True)
        )
        self.restore_last_path_switch.switch_toggled.connect(lambda value: self.current_settings.update({"file_selector.restore_last_path": value}))
        file_selector_layout.addWidget(self.restore_last_path_switch)

        # 触控操作优化
        self.touch_optimization_switch = CustomSettingItem(
            text="触控操作优化",
            secondary_text="启用后可以长按卡片拖拽到文件存储池和统一预览器实现对应操作",
            interaction_type=CustomSettingItem.SWITCH_TYPE,
            initial_value=self.settings_manager.get_setting("file_selector.touch_optimization", True)
        )
        self.touch_optimization_switch.switch_toggled.connect(lambda value: self.current_settings.update({"file_selector.touch_optimization": value}))
        file_selector_layout.addWidget(self.touch_optimization_switch)

        # 鼠标按钮交换
        self.mouse_buttons_swap_switch = CustomSettingItem(
            text="鼠标按钮交换",
            secondary_text="启用后交换鼠标左键和右键的预览/选中的功能",
            interaction_type=CustomSettingItem.SWITCH_TYPE,
            initial_value=self.settings_manager.get_setting("file_selector.mouse_buttons_swap", False)
        )
        self.mouse_buttons_swap_switch.switch_toggled.connect(lambda value: self.current_settings.update({"file_selector.mouse_buttons_swap": value}))
        file_selector_layout.addWidget(self.mouse_buttons_swap_switch)

        self.scroll_layout.addWidget(file_selector_group)

        # 实验性功能组
        experimental_group = QGroupBox("实验性")
        experimental_group.setStyleSheet(self.group_box_style)
        experimental_layout = QVBoxLayout(experimental_group)

        # 时间线视图开关
        self.timeline_view_switch = CustomSettingItem(
            text="时间线视图",
            secondary_text="在文件选择器中显示时间线按钮",
            interaction_type=CustomSettingItem.SWITCH_TYPE,
            initial_value=self.settings_manager.get_setting("file_selector.timeline_view_enabled", False)
        )
        self.timeline_view_switch.switch_toggled.connect(lambda value: self.current_settings.update({"file_selector.timeline_view_enabled": value}))
        experimental_layout.addWidget(self.timeline_view_switch)

        self.scroll_layout.addWidget(experimental_group)

    def _add_file_staging_settings(self):
        """
        添加文件暂存池设置项
        """
        file_staging_group = QGroupBox("文件暂存池设置")
        file_staging_group.setStyleSheet(self.group_box_style)
        file_staging_layout = QVBoxLayout(file_staging_group)
        
        # 自动恢复记录
        self.auto_restore_switch = CustomSettingItem(
            text="自动恢复记录",
            secondary_text="启动时自动恢复暂存池记录",
            interaction_type=CustomSettingItem.SWITCH_TYPE,
            initial_value=self.settings_manager.get_setting("file_staging.auto_restore_records", True)
        )
        self.auto_restore_switch.switch_toggled.connect(lambda value: self.current_settings.update({"file_staging.auto_restore_records": value}))
        file_staging_layout.addWidget(self.auto_restore_switch)
        
        # 默认导出数据路径设置
        self.default_export_data_path = CustomSettingItem(
            text="默认导出数据路径",
            secondary_text="设置默认的数据导出路径",
            interaction_type=CustomSettingItem.INPUT_BUTTON_TYPE,
            placeholder="输入导出数据路径",
            initial_text=self.settings_manager.get_setting("file_staging.default_export_data_path", ""),
            button_text="应用"
        )
        
        # 导出数据路径应用按钮点击处理
        def on_export_data_path_applied(text):
            self.current_settings.update({"file_staging.default_export_data_path": text})
        self.default_export_data_path.input_submitted.connect(on_export_data_path_applied)
        file_staging_layout.addWidget(self.default_export_data_path)
        
        # 默认导出文件路径设置
        self.default_export_file_path = CustomSettingItem(
            text="默认导出文件路径",
            secondary_text="设置默认的文件导出路径",
            interaction_type=CustomSettingItem.INPUT_BUTTON_TYPE,
            placeholder="输入导出文件路径",
            initial_text=self.settings_manager.get_setting("file_staging.default_export_file_path", ""),
            button_text="应用"
        )
        
        # 导出文件路径应用按钮点击处理
        def on_export_file_path_applied(text):
            self.current_settings.update({"file_staging.default_export_file_path": text})
        self.default_export_file_path.input_submitted.connect(on_export_file_path_applied)
        file_staging_layout.addWidget(self.default_export_file_path)
        
        # 导出后删除原始文件
        self.delete_original_switch = CustomSettingItem(
            text="导出后删除原始文件",
            secondary_text="导出后自动删除原始文件",
            interaction_type=CustomSettingItem.SWITCH_TYPE,
            initial_value=self.settings_manager.get_setting("file_staging.delete_original_after_export", False)
        )
        self.delete_original_switch.switch_toggled.connect(lambda value: self.current_settings.update({"file_staging.delete_original_after_export": value}))
        file_staging_layout.addWidget(self.delete_original_switch)

        self.scroll_layout.addWidget(file_staging_group)

    def _add_player_settings(self):
        """
        添加播放器设置项
        """
        # 音量设置组
        volume_group = QGroupBox("音量设置")
        volume_group.setStyleSheet(self.group_box_style)
        volume_layout = QVBoxLayout(volume_group)

        # 使用默认音量开关
        self.use_default_volume_switch = CustomSettingItem(
            text="使用默认音量",
            secondary_text="开启后每次启动都将使用设置的默认音量，否则继承上次播放的音量",
            interaction_type=CustomSettingItem.SWITCH_TYPE,
            initial_value=self.settings_manager.get_setting("player.use_default_volume", False)
        )
        self.use_default_volume_switch.switch_toggled.connect(lambda value: self._on_use_default_volume_changed(value))
        volume_layout.addWidget(self.use_default_volume_switch)

        # 默认音量滑块（仅在开启使用默认音量时显示）
        self.default_volume_bar = CustomSettingItem(
            text="默认音量",
            secondary_text="设置默认音量大小 (0-100%)",
            interaction_type=CustomSettingItem.VALUE_BAR_TYPE,
            min_value=0,
            max_value=100,
            initial_value=self.settings_manager.get_setting("player.default_volume", 100)
        )
        self.default_volume_bar.value_changed.connect(lambda value: self.current_settings.update({"player.default_volume": value}))
        # 根据开关状态设置初始可见性
        self.default_volume_bar.setVisible(self.use_default_volume_switch.get_switch_value())
        volume_layout.addWidget(self.default_volume_bar)

        self.scroll_layout.addWidget(volume_group)

        # 倍速设置组
        speed_group = QGroupBox("倍速设置")
        speed_group.setStyleSheet(self.group_box_style)
        speed_layout = QVBoxLayout(speed_group)

        # 使用默认倍速开关
        self.use_default_speed_switch = CustomSettingItem(
            text="使用默认倍速",
            secondary_text="开启后每次启动都将使用设置的默认倍速，否则继承上次播放的倍速",
            interaction_type=CustomSettingItem.SWITCH_TYPE,
            initial_value=self.settings_manager.get_setting("player.use_default_speed", True)
        )
        self.use_default_speed_switch.switch_toggled.connect(lambda value: self._on_use_default_speed_changed(value))
        speed_layout.addWidget(self.use_default_speed_switch)

        # 默认倍速选择按钮（仅在开启使用默认倍速时显示）
        from freeassetfilter.widgets.dropdown_menu import CustomDropdownMenu
        speed_options = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0]
        current_speed = self.settings_manager.get_setting("player.default_speed", 1.0)

        self.default_speed_setting = CustomSettingItem(
            text="默认倍速",
            secondary_text="设置默认播放倍速",
            interaction_type=CustomSettingItem.BUTTON_GROUP_TYPE,
            buttons=[{"text": f"{current_speed}x", "type": "primary"}]
        )

        # 倍速选择按钮点击处理
        def on_speed_button_clicked(button_index):
            # 创建倍速下拉菜单
            self.speed_dropdown_menu = CustomDropdownMenu(self, position="bottom")
            speed_items = [f"{speed}x" for speed in speed_options]
            self.speed_dropdown_menu.set_items(speed_items, default_item=f"{current_speed}x")

            def on_speed_item_clicked(selected_speed):
                speed_value = float(selected_speed.replace('x', ''))
                self.current_settings.update({"player.default_speed": speed_value})
                self.default_speed_setting.button_group[0].setText(selected_speed)

            self.speed_dropdown_menu.itemClicked.connect(on_speed_item_clicked)
            button = self.default_speed_setting.button_group[button_index]
            self.speed_dropdown_menu.set_target_button(button)
            self.speed_dropdown_menu.show_menu()

        self.default_speed_setting.button_clicked.connect(on_speed_button_clicked)
        # 根据开关状态设置初始可见性
        self.default_speed_setting.setVisible(self.use_default_speed_switch.get_switch_value())
        speed_layout.addWidget(self.default_speed_setting)

        self.scroll_layout.addWidget(speed_group)

        # 音频背景样式设置组
        theme_group = QGroupBox("音频背景样式")
        theme_group.setStyleSheet(self.group_box_style)
        theme_layout = QVBoxLayout(theme_group)

        # 背景样式选择（流体动画、封面模糊）
        background_styles = ["流体动画", "封面模糊"]
        current_style = self.settings_manager.get_setting("player.audio_background_style", "流体动画")

        self.audio_background_style_setting = CustomSettingItem(
            text="背景样式",
            secondary_text="选择音频播放时的背景显示样式",
            interaction_type=CustomSettingItem.BUTTON_GROUP_TYPE,
            buttons=[{"text": current_style, "type": "primary"}]
        )

        def on_background_style_button_clicked(button_index):
            self.background_style_dropdown = CustomDropdownMenu(self, position="bottom")
            self.background_style_dropdown.set_items(background_styles, default_item=current_style)

            def on_style_item_clicked(selected_style):
                self.current_settings.update({"player.audio_background_style": selected_style})
                self.audio_background_style_setting.button_group[0].setText(selected_style)

            self.background_style_dropdown.itemClicked.connect(on_style_item_clicked)
            button = self.audio_background_style_setting.button_group[button_index]
            self.background_style_dropdown.set_target_button(button)
            self.background_style_dropdown.show_menu()

        self.audio_background_style_setting.button_clicked.connect(on_background_style_button_clicked)
        theme_layout.addWidget(self.audio_background_style_setting)

        self.scroll_layout.addWidget(theme_group)

    def _on_use_default_volume_changed(self, value):
        """
        处理使用默认音量开关变化

        Args:
            value (bool): 开关状态
        """
        self.current_settings.update({"player.use_default_volume": value})
        # 显示/隐藏默认音量滑块
        self.default_volume_bar.setVisible(value)

    def _on_use_default_speed_changed(self, value):
        """
        处理使用默认倍速开关变化

        Args:
            value (bool): 开关状态
        """
        self.current_settings.update({"player.use_default_speed": value})
        # 显示/隐藏默认倍速选择按钮
        self.default_speed_setting.setVisible(value)

    def _add_general_settings(self):
        """
        添加通用设置项（包含原外观设置中的主题和字体设置）
        """
        # 主题设置组
        theme_group = QGroupBox("主题")
        theme_group.setStyleSheet(self.group_box_style)
        theme_layout = QVBoxLayout(theme_group)

        # 深色/浅色主题开关
        self.theme_switch = CustomSettingItem(
            text="深色主题",
            secondary_text="启用深色主题模式",
            interaction_type=CustomSettingItem.SWITCH_TYPE,
            initial_value=self.settings_manager.get_setting("appearance.theme", "default") == "dark"
        )
        def on_theme_toggled(value):
            theme_value = "dark" if value else "default"
            self.current_settings.update({"appearance.theme": theme_value})

            current_accent_color = self.current_settings.get("appearance.colors.accent_color", "#007AFF")

            if value:
                dark_colors = {
                    "base_color": "#212121",
                    "secondary_color": "#FFFFFF",
                    "normal_color": "#717171",
                    "auxiliary_color": "#313331"
                }
                for color_key, color_value in dark_colors.items():
                    self.current_settings.update({f"appearance.colors.{color_key}": color_value})
            else:
                light_colors = {
                    "base_color": "#FFFFFF",
                    "secondary_color": "#333333",
                    "normal_color": "#e0e0e0",
                    "auxiliary_color": "#f1f3f3"
                }
                for color_key, color_value in light_colors.items():
                    self.current_settings.update({f"appearance.colors.{color_key}": color_value})

            self._update_styles()

        self.theme_switch.switch_toggled.connect(on_theme_toggled)
        theme_layout.addWidget(self.theme_switch)

        # 主题颜色设置按钮
        self.theme_color_button = CustomButton("自定义主题颜色", button_type="secondary")
        self.theme_color_button.clicked.connect(self._open_theme_color_settings)
        theme_layout.addWidget(self.theme_color_button)

        self.scroll_layout.addWidget(theme_group)

        # 字体设置组
        font_group = QGroupBox("字体设置")
        font_group.setStyleSheet(self.group_box_style)
        font_layout = QVBoxLayout(font_group)

        # 字体样式选择
        from freeassetfilter.widgets.dropdown_menu import CustomDropdownMenu
        font_families = _get_font_families_cached()

        # 获取当前字体设置
        current_font = self.settings_manager.get_setting("font.style", "Microsoft YaHei")

        # 创建字体样式选择控件，使用按钮组交互类型
        self.font_style_setting = CustomSettingItem(
            text="字体样式",
            secondary_text="选择应用内使用的字体",
            interaction_type=CustomSettingItem.BUTTON_GROUP_TYPE,
            buttons=[{"text": current_font, "type": "primary"}]
        )

        # 字体样式选择按钮点击处理
        def on_font_style_button_clicked(button_index):
            # 创建自定义下拉菜单（点击时才创建，避免初始位置错误）
            self.font_dropdown_menu = CustomDropdownMenu(self, position="bottom")
            # 设置字体列表项
            self.font_dropdown_menu.set_items(font_families, default_item=current_font)
            # 字体选择下拉菜单项点击处理
            def on_font_item_clicked(selected_font_family):
                self.current_settings.update({"font.style": selected_font_family})
                # 更新按钮显示的字体名称
                self.font_style_setting.button_group[0].setText(selected_font_family)
            self.font_dropdown_menu.itemClicked.connect(on_font_item_clicked)

            # 设置目标按钮并显示下拉菜单
            button = self.font_style_setting.button_group[button_index]
            self.font_dropdown_menu.set_target_button(button)
            self.font_dropdown_menu.show_menu()
        self.font_style_setting.button_clicked.connect(on_font_style_button_clicked)

        # 将字体样式选择控件添加到布局
        font_layout.addWidget(self.font_style_setting)

        # 字体大小滑块
        self.font_size_bar = CustomSettingItem(
            text="字体大小",
            secondary_text="调整应用内字体大小",
            interaction_type=CustomSettingItem.VALUE_BAR_TYPE,
            min_value=6,
            max_value=40,
            initial_value=self.settings_manager.get_setting("font.size", 20)
        )
        self.font_size_bar.value_changed.connect(lambda value: self.current_settings.update({"font.size": value}))
        font_layout.addWidget(self.font_size_bar)

        self.scroll_layout.addWidget(font_group)

    def _add_developer_settings(self):
        """
        添加开发者设置项
        """
        app = QApplication.instance()
        dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        developer_group = QGroupBox("开发者选项")
        developer_group.setStyleSheet(self.group_box_style)
        developer_layout = QVBoxLayout(developer_group)
        developer_layout.setSpacing(int(10 * dpi_scale))

        hover_test_group = QGroupBox("hover类测试")
        hover_test_group.setStyleSheet(self.group_box_style)
        hover_test_layout = QVBoxLayout(hover_test_group)
        hover_test_layout.setSpacing(int(5 * dpi_scale))

        self.hover_menu_test_button = CustomButton("测试 Hover Menu", button_type="secondary")
        self.hover_menu_test_button.clicked.connect(self._run_hover_menu_test)
        hover_test_layout.addWidget(self.hover_menu_test_button)

        self.hover_tooltip_test_button = CustomButton("测试 Hover Tooltip", button_type="secondary")
        self.hover_tooltip_test_button.clicked.connect(self._run_hover_tooltip_test)
        hover_test_layout.addWidget(self.hover_tooltip_test_button)

        developer_layout.addWidget(hover_test_group)

        menu_list_test_group = QGroupBox("菜单列表测试")
        menu_list_test_group.setStyleSheet(self.group_box_style)
        menu_list_test_layout = QVBoxLayout(menu_list_test_group)
        menu_list_test_layout.setSpacing(int(8 * dpi_scale))

        menu_list_intro = QLabel("D_MenuList 测试（带滚动条）")
        menu_list_intro.setStyleSheet("font-weight: bold; color: #666; font-size: 12px;")
        menu_list_test_layout.addWidget(menu_list_intro)

        button_row1 = QHBoxLayout()
        button_row1.setSpacing(int(8 * dpi_scale))

        self.menu_list_toggle_btn = CustomButton("打开菜单列表", button_type="normal", display_mode="text")
        self.menu_list_toggle_btn.clicked.connect(self._toggle_menu_list)
        button_row1.addWidget(self.menu_list_toggle_btn)

        self.menu_list_add_btn = CustomButton("添加项目", button_type="normal", display_mode="text")
        self.menu_list_add_btn.clicked.connect(self._add_menu_list_item)
        button_row1.addWidget(self.menu_list_add_btn)

        self.menu_list_clear_btn = CustomButton("清空项目", button_type="normal", display_mode="text")
        self.menu_list_clear_btn.clicked.connect(self._clear_menu_list_items)
        button_row1.addWidget(self.menu_list_clear_btn)

        menu_list_test_layout.addLayout(button_row1)

        self.menu_list = D_MenuList(parent=self, position="bottom", selection_mode="single")
        self.menu_list.set_target_widget(self.menu_list_toggle_btn)
        self.menu_list.set_offset(0, int(5 * dpi_scale))
        self.menu_list.set_list_height(150)
        self.menu_list.set_min_width(100)
        self.menu_list.set_max_width(250)
        self.menu_list.set_timeout_enabled(True)
        self.menu_list.set_timeout_duration(5000)
        self.menu_list.add_items([
            "项目 1",
            "项目 2",
            "项目 3（长文本测试）",
            "项目 4",
            "项目 5"
        ])
        self.menu_list._ensure_width_updated()

        menu_list_item_test_group = QGroupBox("D_MenuListItem 测试（轻量级）")
        menu_list_item_test_group.setStyleSheet(self.group_box_style)
        menu_list_item_test_layout = QVBoxLayout(menu_list_item_test_group)
        menu_list_item_test_layout.setSpacing(int(8 * dpi_scale))

        menu_list_item_intro = QLabel("轻量级菜单列表，无滚动区域")
        menu_list_item_intro.setStyleSheet("font-weight: bold; color: #666; font-size: 12px;")
        menu_list_item_test_layout.addWidget(menu_list_item_intro)

        button_row2 = QHBoxLayout()
        button_row2.setSpacing(int(8 * dpi_scale))

        self.menu_list_item_toggle_btn = CustomButton("打开轻量菜单", button_type="normal", display_mode="text")
        self.menu_list_item_toggle_btn.clicked.connect(self._toggle_menu_list_item)
        button_row2.addWidget(self.menu_list_item_toggle_btn)

        self.menu_list_item_pos_btn = CustomButton("切换位置", button_type="normal", display_mode="text")
        self.menu_list_item_pos_btn.clicked.connect(self._change_menu_list_item_position)
        button_row2.addWidget(self.menu_list_item_pos_btn)

        menu_list_item_test_layout.addLayout(button_row2)

        self.menu_list_item = D_MenuListItem(parent=self, position="bottom")
        self.menu_list_item.set_target_widget(self.menu_list_item_toggle_btn)
        self.menu_list_item.add_items(["选项 A", "选项 B", "选项 C", "选项 D"])

        developer_layout.addWidget(menu_list_item_test_group)
        self.scroll_layout.addWidget(developer_group)

    def _toggle_menu_list(self):
        """切换菜单列表显示"""
        self.menu_list.toggle()

    def _add_menu_list_item(self):
        """添加项目到菜单列表"""
        import random
        for i in range(3):
            self.menu_list.add_item(f"新项目 {random.randint(100, 999)}")

    def _clear_menu_list_items(self):
        """清空菜单列表"""
        self.menu_list.clear_items()

    def _toggle_menu_list_item(self):
        """切换轻量菜单显示"""
        self.menu_list_item.toggle()

    def _change_menu_list_item_position(self):
        """切换轻量菜单位置"""
        current_pos = self.menu_list_item._position
        positions = ["bottom", "top", "left", "right"]
        try:
            idx = positions.index(current_pos)
            next_pos = positions[(idx + 1) % len(positions)]
            self.menu_list_item.set_position(next_pos)
        except (ValueError, IndexError):
            self.menu_list_item.set_position("bottom")

    def _run_hover_menu_test(self):
        """
        运行 Hover Menu 测试程序
        """
        import subprocess
        import sys
        test_script = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "test", "test_D_hover_menu.py")
        if os.path.exists(test_script):
            subprocess.Popen([sys.executable, test_script])

    def _run_hover_tooltip_test(self):
        """
        运行 Hover Tooltip 测试程序
        """
        import subprocess
        import sys
        test_script = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "test", "20260118", "test_hover_tooltip_interactive.py")
        if os.path.exists(test_script):
            subprocess.Popen([sys.executable, test_script])

    def _open_theme_color_settings(self):
        """
        打开主题颜色设置窗口
        """
        from freeassetfilter.components.theme_editor import ThemeEditor
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton
        from PyQt5.QtCore import Qt
        
        theme_window = QDialog(self)
        theme_window.setWindowTitle("主题设置")
        theme_window.resize(450, 350)
        
        theme_window.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.WindowSystemMenuHint | Qt.WindowCloseButtonHint)
        
        main_layout = QVBoxLayout(theme_window)
        
        self.theme_editor = ThemeEditor()
        
        main_layout.addWidget(self.theme_editor)
        
        buttons_layout = QHBoxLayout()
        buttons_layout.setAlignment(Qt.AlignCenter)
        
        from freeassetfilter.widgets.button_widgets import CustomButton
        
        reset_button = CustomButton("重置", button_type="secondary", height=20)
        reset_button.clicked.connect(lambda: self.theme_editor.on_reset_clicked())
        buttons_layout.addWidget(reset_button)
        
        confirm_button = CustomButton("确定", button_type="primary", height=20)
        confirm_button.clicked.connect(lambda: self._on_theme_confirmed(theme_window))
        buttons_layout.addWidget(confirm_button)
        
        main_layout.addLayout(buttons_layout)
        
        theme_window.exec_()
    
    def _on_theme_confirmed(self, theme_window):
        """
        主题颜色确认按钮点击事件
        将选中的主题强调色应用到 current_settings，并关闭对话框
        """
        theme = self.theme_editor.get_selected_theme()
        if theme and "colors" in theme:
            accent_color = theme["colors"][0]
            self.current_settings.update({f"appearance.colors.accent_color": accent_color})
            
            # 使SVG颜色缓存失效，确保下次渲染时使用新颜色
            SvgRenderer._invalidate_color_cache()
        
        theme_window.close()
        
    def _apply_selected_theme(self, theme):
        """
        应用选中的主题强调色
        """
        if theme and "colors" in theme:
            accent_color = theme["colors"][0]
            self.current_settings.update({f"appearance.colors.accent_color": accent_color})
            
            self._update_theme_display()
    
    def _update_theme_display(self):
        """
        更新UI显示的主题颜色
        """
        self._update_styles()
        
        base_color = self.current_settings.get("appearance.colors.base_color", "#FFFFFF")
        secondary_color = self.current_settings.get("appearance.colors.secondary_color", "#333333")
        normal_color = self.current_settings.get("appearance.colors.normal_color", "#e0e0e0")
        auxiliary_color = self.current_settings.get("appearance.colors.auxiliary_color", "#f1f3f3")
        accent_color = self.current_settings.get("appearance.colors.accent_color", "#007AFF")
        
        dark2 = self._darken_color(auxiliary_color, 0.1)
        dark5 = self._darken_color(auxiliary_color, 0.2)
        
        self.setStyleSheet(f"""
            QDialog {{ 
                background-color: {auxiliary_color}; 
            }}
        """)
        
        navigation_style = f"""
            QWidget {{ 
                background-color: {base_color}; 
                border-radius: 10px;
                border: none;
            }}
        """
        self.navigation_widget.setStyleSheet(navigation_style)
        
        title_style = f"""
            QLabel {{ 
                font-family: 'Noto Sans SC'; 
                font-size: 10px;
                font-weight: 400;
                color: {secondary_color};
                margin-bottom: 15px;
                padding: 5px;
                text-align: center;
            }}
        """
        for child in self.navigation_widget.children():
            if isinstance(child, QVBoxLayout):
                for i in range(child.count()):
                    item = child.itemAt(i)
                    if item and isinstance(item.widget(), QLabel):
                        item.widget().setStyleSheet(title_style)
                        break
        
        card_style = f"""
            QPushButton {{ 
                background-color: {auxiliary_color}; 
                border: none;
                border-radius: 2px;
                padding: 0;
                height: 15px;
                width: 85px;
                text-align: center;
                font-size: 10px;
                color: {secondary_color};
                font-weight: 400;
            }}
            QPushButton:hover {{ 
                background-color: {dark2}; 
            }}
            QPushButton:pressed {{ 
                background-color: {dark5}; 
            }}
            QPushButton:checked {{ 
                background-color: {accent_color}; 
                color: {base_color}; 
            }}
        """
        for button in self.navigation_buttons:
            button.setStyleSheet(card_style)
        
        content_style = f"""
            QWidget {{ 
                background-color: {base_color}; 
                border-radius: 10px;
                border: none;
            }}
        """
        self.content_area.setStyleSheet(content_style)
        
        content_title_style = f"""
            QLabel {{ 
                font-family: 'Noto Sans SC'; 
                font-size: 14px;
                font-weight: 600;
                color: {secondary_color};
                margin-bottom: 10px;
                padding: 5px;
            }}
        """
        self.content_title.setStyleSheet(content_title_style)
        
        # 更新滚动区域样式
        normal_color = self.current_settings.get("appearance.colors.normal_color", "#e0e0e0")
        accent_color = self.current_settings.get("appearance.colors.accent_color", "#007AFF")
        
        scroll_style = f"""
            QScrollArea {{ 
                background-color: transparent;
                border: none;
            }}
            QScrollBar:vertical {{ 
                width: 6px;
                background-color: {auxiliary_color}; 
            }}
            QScrollBar::handle:vertical {{ 
                background-color: {normal_color}; 
                border-radius: 3px;
            }}
            QScrollBar::handle:vertical:hover {{ 
                background-color: {accent_color}; 
            }}
        """
        self.scroll_area.setStyleSheet(scroll_style)
        
        # 使用动画滚动条
        hover_color = secondary_color
        self.scroll_area.setVerticalScrollBar(D_ScrollBar(self.scroll_area, Qt.Vertical))
        self.scroll_area.verticalScrollBar().set_colors(normal_color, hover_color, accent_color, auxiliary_color)
        
        SmoothScroller.apply_to_scroll_area(self.scroll_area)
        
        # 更新所有分组框样式
        for child in self.scroll_content.children():
            if isinstance(child, QVBoxLayout):
                for i in range(child.count()):
                    item = child.itemAt(i)
                    if item and isinstance(item.widget(), QGroupBox):
                        item.widget().setStyleSheet(self.group_box_style)
    

    
    def _darken_color(self, color_hex, factor):
        """
        使颜色变暗
        
        Args:
            color_hex: 十六进制颜色值，如 "#RRGGBB"
            factor: 变暗因子，0.0-1.0
            
        Returns:
            str: 变暗后的十六进制颜色值
        """
        color_hex = color_hex.lstrip('#')
        r = int(color_hex[0:2], 16)
        g = int(color_hex[2:4], 16)
        b = int(color_hex[4:6], 16)
        
        r = max(0, int(r * (1 - factor)))
        g = max(0, int(g * (1 - factor)))
        b = max(0, int(b * (1 - factor)))
        
        return f"#{r:02x}{g:02x}{b:02x}"
    
    def _update_styles(self):
        """
        更新所有样式表
        """
        base_color = self.current_settings.get("appearance.colors.base_color", "#FFFFFF")
        secondary_color = self.current_settings.get("appearance.colors.secondary_color", "#333333")
        auxiliary_color = self.current_settings.get("appearance.colors.auxiliary_color", "#f1f3f3")
        
        self.group_box_style = f"""
            QGroupBox {{
                background-color: {base_color};
                border: 1px solid {auxiliary_color};
                border-radius: 8px;
                padding: 10px;
                margin-bottom: 5px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0px 10px;
                color: {secondary_color};
                font-weight: 600;
                font-size: 6px;
                margin-bottom: 0px;
                top: -2px;
                background-color: {base_color};
            }}
        """
    
    def load_settings(self):
        """
        加载当前设置
        """
        self.current_settings = {
            "appearance.theme": self.settings_manager.get_setting("appearance.theme", "default"),
            "appearance.colors.base_color": self.settings_manager.get_setting("appearance.colors.base_color", "#FFFFFF"),
            "appearance.colors.secondary_color": self.settings_manager.get_setting("appearance.colors.secondary_color", "#333333"),
            "appearance.colors.auxiliary_color": self.settings_manager.get_setting("appearance.colors.auxiliary_color", "#f1f3f3"),
            "font.size": self.settings_manager.get_setting("font.size", 20),
            "font.style": self.settings_manager.get_setting("font.style", "Microsoft YaHei"),
            "file_selector.auto_clear_thumbnail_cache": self.settings_manager.get_setting("file_selector.auto_clear_thumbnail_cache", True),
            "file_selector.cache_cleanup_period": self.settings_manager.get_setting("file_selector.cache_cleanup_period", 7),
            "file_selector.cache_cleanup_threshold": self.settings_manager.get_setting("file_selector.cache_cleanup_threshold", 500),
            "file_selector.restore_last_path": self.settings_manager.get_setting("file_selector.restore_last_path", True),
            "file_selector.return_shortcut": self.settings_manager.get_setting("file_selector.return_shortcut", "middle_click"),
            "file_selector.timeline_view_enabled": self.settings_manager.get_setting("file_selector.timeline_view_enabled", False),
            "file_staging.auto_restore_records": self.settings_manager.get_setting("file_staging.auto_restore_records", True),
            "file_staging.default_export_data_path": self.settings_manager.get_setting("file_staging.default_export_data_path", ""),
            "file_staging.default_export_file_path": self.settings_manager.get_setting("file_staging.default_export_file_path", ""),
            "file_staging.delete_original_after_export": self.settings_manager.get_setting("file_staging.delete_original_after_export", False),
            "player.speed": self.settings_manager.get_setting("player.speed", 1.0),
            "player.volume": self.settings_manager.get_setting("player.volume", 100)
        }
    
    def save_settings(self):
        """
        保存设置
        """
        font_changed = self._check_font_changed()
        
        for key, value in self.current_settings.items():
            self.settings_manager.set_setting(key, value)
        
        self.settings_manager.save_settings()
        
        app = self.parent() if self.parent() else None
        
        if app and hasattr(app, 'unified_previewer'):
            try:
                app.unified_previewer.stop_preview()
            except Exception:
                pass
        
        self._apply_theme_if_needed()
        
        if font_changed:
            self._show_font_change_reminder()
        
        self.settings_saved.emit(self.current_settings)
        
        self.close()
    
    def _check_font_changed(self):
        """
        检查字体设置是否有变更
        
        Returns:
            bool: 如果字体设置有变更返回 True，否则返回 False
        """
        original_font_style = self.settings_manager.get_setting("font.style", "Microsoft YaHei")
        original_font_size = self.settings_manager.get_setting("font.size", 20)
        
        current_font_style = self.current_settings.get("font.style", original_font_style)
        current_font_size = self.current_settings.get("font.size", original_font_size)
        
        return current_font_style != original_font_style or current_font_size != original_font_size
    
    def _show_font_change_reminder(self):
        """
        如果字体设置有变更，显示提示弹窗
        """
        msg_box = CustomMessageBox(self)
        msg_box.set_title("提示")
        msg_box.set_text("当前字体修改将在下次启动后生效")
        msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
        msg_box.exec_()
    
    def _apply_theme_if_needed(self):
        """
        如果主题设置有变更，应用主题更新
        """
        theme_key = "appearance.theme"
        if theme_key in self.current_settings:
            app = self.parent() if self.parent() else None
            if hasattr(app, 'update_theme'):
                app.update_theme()
    
    def reset_settings(self):
        """
        重置设置为默认值
        """
        # 询问用户是否确认重置
        confirm_box = CustomMessageBox(self)
        confirm_box.set_title("确认重置")
        confirm_box.set_text("重置后所有设置将恢复为默认值，此操作不可撤销。\n是否继续？")
        confirm_box.set_buttons(["确认重置", "取消"], Qt.Vertical, ["warning", "secondary"])
        
        # 获取当前设置文件路径
        settings_file = self.settings_manager.settings_file
        
        if confirm_box.exec_() == 0:
            # 删除设置文件
            if os.path.exists(settings_file):
                try:
                    os.remove(settings_file)
                    print(f"已删除设置文件: {settings_file}")
                except Exception as e:
                    print(f"删除设置文件失败: {e}")
            
            # 清除内存中的设置缓存，强制重新加载
            self.settings_manager.settings = None
            
            # 显示重启提示窗口
            self._show_restart_required_dialog()
    
    def _show_restart_required_dialog(self):
        """
        显示重启提示窗口
        """
        restart_box = CustomMessageBox(self)
        restart_box.set_title("重启程序")
        restart_box.set_text("设置已重置，更改将在下次启动后生效。")
        restart_box.set_buttons(["立即重启程序"], Qt.Vertical, ["warning"])
        
        # 连接按钮点击事件
        restart_box.buttonClicked.connect(lambda idx: self._restart_application(restart_box))
        
        restart_box.exec_()
    
    def _restart_application(self, dialog):
        """
        关闭提示窗口并重启程序
        """
        dialog.close()
        
        app = QApplication.instance()
        if app:
            app.quit()
        
        # 使用 subprocess 重新启动程序
        import subprocess
        import os
        python_executable = sys.executable
        # settings_window.py 位于 freeassetfilter/components/，需要向上两级到 freeassetfilter/，然后进入 app/
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script_path = os.path.join(project_root, "app", "main.py")
        subprocess.Popen([python_executable, script_path])
        
        sys.exit(0)


# 更新 __init__.py 文件，导出新控件
# 注意：在实际使用时，需要手动更新 custom_widgets.py 文件，将新控件添加到导入和导出列表中
