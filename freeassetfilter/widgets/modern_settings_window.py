#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 现代化设置窗口
包含现代化设计风格的设置窗口实现
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QTabWidget, QPushButton, QGroupBox, QSizePolicy, QDialog
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtWidgets import QGraphicsDropShadowEffect

# 导入自定义控件
from .setting_widgets import CustomSettingItem
from .button_widgets import CustomButton
from .list_widgets import CustomSelectList

# 导入设置管理器
from freeassetfilter.core.settings_manager import SettingsManager


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
        super().__init__(parent)
        
        # 设置窗口标题
        self.setWindowTitle("设置")
        
        # 获取设置管理器
        app = parent if hasattr(parent, 'settings_manager') else None
        self.settings_manager = getattr(app, 'settings_manager', None) or SettingsManager()
        
        # 当前设置值
        self.current_settings = {}
        
        # 统一的设置组样式
        self.group_box_style = """
            QGroupBox {
                background-color: #FFFFFF;
                border: 1px solid #E0E0E0;
                border-radius: 8px;
                padding: 5px;
                margin-bottom: 0px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 10x;
                color: #333333;
                font-weight: 600;
                font-size: 8px;
            }
        """
        
        # 加载当前设置
        self.load_settings()
        
        # 初始化UI
        self.init_modern_ui()
    
    def init_modern_ui(self):
        """
        初始化现代化设置窗口UI
        """
        # 设置窗口大小（根据Figma设计调整）
        self.setMinimumSize(419, 268)
        self.resize(419, 268)
        
        # 设置窗口整体背景颜色为灰色色块（Figma: #D9D9D9）
        self.setStyleSheet("""
            QDialog {
                background-color: #D9D9D9;
            }
        """)
        
        # 创建主布局（左侧导航 + 右侧内容）
        main_layout = QHBoxLayout(self)
        self.content_layout = main_layout
        
        # 设置主布局边距和间距
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # 左侧导航栏
        self.navigation_widget = self._create_navigation_widget()
        main_layout.addWidget(self.navigation_widget, 0)
        
        # 右侧内容区域
        self.content_area = self._create_content_area()
        main_layout.addWidget(self.content_area, 1)
        
        # 默认填充第一个标签页内容
        self._fill_tab_content("appearance")
    
    def _create_navigation_widget(self):
        """
        创建左侧导航栏
        """
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        
        # 设置导航栏宽度（根据Figma设计：97px）
        widget.setFixedWidth(97)
        
        # 设置导航栏样式（Figma：白色背景，10px圆角）
        widget.setStyleSheet("""
            QWidget {
                background-color: #FFFFFF;
                border-radius: 10px;
                border: none;
            }
        """)
        
        # 导航栏布局
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 15, 5, 10)
        layout.setSpacing(10)
        
        # 导航标题（Figma："设置"文本）
        title_label = QLabel("设置")
        title_label.setStyleSheet("""
            QLabel {
                font-family: 'Noto Sans SC';
                font-size: 10px;
                font-weight: 400;
                color: #000000;
                margin-bottom: 15px;
                padding: 5px;
                text-align: center;
            }
        """)
        layout.addWidget(title_label)
        
        # 导航选项卡片
        self.navigation_buttons = []
        self.navigation_items = [
            {"text": "外观", "id": "appearance"},
            {"text": "文件选择器", "id": "file_selector"},
            {"text": "文件暂存池", "id": "file_staging"},
            {"text": "播放器", "id": "player"},
            {"text": "通用", "id": "general"}
        ]
        
        # 卡片式按钮样式（Figma：85x15px，圆角2px）
        card_style = """
            QPushButton {
                background-color: #F3F3F3;
                border: none;
                border-radius: 2px;
                padding: 0;
                height: 15px;
                width: 85px;
                text-align: center;
                font-size: 10px;
                color: #333333;
                font-weight: 400;
            }
            QPushButton:hover {
                background-color: #E8E8E8;
            }
            QPushButton:pressed {
                background-color: #E0E0E0;
            }
            QPushButton:checked {
                background-color: #4C9AED;
                color: #FFFFFF;
            }
        """
        
        # 创建导航按钮
        for i, item in enumerate(self.navigation_items):
            button = QPushButton(item["text"])
            button.setCheckable(True)
            button.setStyleSheet(card_style)
            button.clicked.connect(lambda checked, idx=i: self._on_navigation_clicked(idx))
            self.navigation_buttons.append(button)
            layout.addWidget(button)
        
        # 默认选中第一个按钮
        if self.navigation_buttons:
            self.navigation_buttons[0].setChecked(True)
        
        # 添加占位符
        layout.addStretch()
        
        return widget
    
    def _create_content_area(self):
        """
        创建右侧内容区域
        """
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # 设置内容区域样式（Figma：白色背景，10px圆角）
        widget.setStyleSheet("""
            QWidget {
                background-color: #FFFFFF;
                border-radius: 10px;
                border: none;
            }
        """)
        
        # 内容区域布局
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)
        
        # 内容标题
        self.content_title = QLabel("外观设置")
        self.content_title.setStyleSheet("""
            QLabel {
                font-family: 'Noto Sans SC';
                font-size: 14px;
                font-weight: 600;
                color: #000000;
                margin-bottom: 10px;
                padding: 5px;
            }
        """)
        layout.addWidget(self.content_title)
        
        # 滚动区域
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QScrollBar:vertical {
                width: 6px;
                background-color: transparent;
            }
            QScrollBar::handle:vertical {
                background-color: #CCCCCC;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #999999;
            }
        """)
        
        # 滚动内容
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(15)
        # 设置布局对齐方式为向上对齐
        self.scroll_layout.setAlignment(Qt.AlignTop)
        
        self.scroll_area.setWidget(self.scroll_content)
        # 让滚动区域填满整个显示区域
        layout.addWidget(self.scroll_area, 1)
        
        # 底部按钮区域
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
        scaled_font_size = int(default_font_size * 1.1)
        
        title_label.setStyleSheet("""
            QLabel {
                font-size: %dpx;
                font-weight: 600;
                color: #000000;
                margin-bottom: 15px;
                padding: 5px;
            }
        """ % scaled_font_size)
        layout.addWidget(title_label)
        
        # 滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QScrollBar:vertical {
                width: 8px;
                background-color: transparent;
            }
            QScrollBar::handle:vertical {
                background-color: #555;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #777;
            }
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
        # 导航项ID映射
        nav_ids = ["appearance", "file_selector", "file_staging", "player", "general"]
        
        if 0 <= index < len(nav_ids):
            # 更新按钮状态
            for i, button in enumerate(self.navigation_buttons):
                button.setChecked(i == index)
            
            # 根据选中的导航项填充内容
            self._fill_tab_content(nav_ids[index])
    
    def _fill_tab_content(self, tab_id):
        """
        根据标签页ID填充内容
        
        Args:
            tab_id (str): 标签页ID
        """
        # 更新内容标题
        title_mapping = {
            "appearance": "外观设置",
            "file_selector": "文件选择器设置",
            "file_staging": "文件暂存池设置",
            "player": "播放器设置",
            "general": "通用设置"
        }
        
        if tab_id in title_mapping:
            self.content_title.setText(title_mapping[tab_id])
        
        # 清空当前内容
        while self.scroll_layout.count() > 0:
            item = self.scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # 根据标签页ID添加设置项
        if tab_id == "appearance":
            self._add_appearance_settings()
        elif tab_id == "file_selector":
            self._add_file_selector_settings()
        elif tab_id == "file_staging":
            self._add_file_staging_settings()
        elif tab_id == "player":
            self._add_player_settings()
        elif tab_id == "general":
            self._add_general_settings()
    
    def _add_appearance_settings(self):
        """
        添加外观设置项
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
        self.theme_switch.switch_toggled.connect(lambda value: self.current_settings.update({"appearance.theme": "dark" if value else "default"}))
        theme_layout.addWidget(self.theme_switch)
        
        self.scroll_layout.addWidget(theme_group)
        
        # 主题颜色设置按钮
        self.theme_color_button = CustomButton("自定义主题颜色", button_type="secondary")
        self.theme_color_button.clicked.connect(self._open_theme_color_settings)
        self.scroll_layout.addWidget(self.theme_color_button)
        
        # 字体设置组
        font_group = QGroupBox("字体设置")
        font_group.setStyleSheet(self.group_box_style)
        font_layout = QVBoxLayout(font_group)
        
        # 字体样式选择
        from PyQt5.QtGui import QFontDatabase
        from .custom_dropdown_menu import CustomDropdownMenu
        font_db = QFontDatabase()
        font_families = font_db.families()
        
        # 获取当前字体设置
        current_font = self.settings_manager.get_setting("font.style", "Microsoft YaHei")
        
        # 创建字体样式选择控件（只用于显示标题和描述）
        font_style_label = CustomSettingItem(
            text="字体样式",
            secondary_text="选择应用内使用的字体",
            interaction_type=None  # 不添加交互控件
        )
        
        # 创建自定义下拉菜单（直接使用自带的按钮）
        self.font_dropdown_menu = CustomDropdownMenu(self, position="bottom")
        
        # 设置按钮样式为primary
        self.font_dropdown_menu.main_button.set_button_type("primary")
        
        # 设置字体列表项
        self.font_dropdown_menu.set_items(font_families, default_item=current_font)
        
        # 字体选择下拉菜单项点击处理
        def on_font_item_clicked(selected_font_family):
            self.current_settings.update({"font.style": selected_font_family})
        self.font_dropdown_menu.itemClicked.connect(on_font_item_clicked)
        
        # 将标签和下拉菜单添加到布局
        font_layout.addWidget(font_style_label)
        font_layout.addWidget(self.font_dropdown_menu)
        
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
    
    def _add_font_settings(self):
        """
        添加字体设置项
        """
        # 字体设置组
        font_group = QGroupBox("字体设置")
        font_group.setStyleSheet(self.group_box_style)
        font_layout = QVBoxLayout(font_group)
        
        # 字体样式选择
        from PyQt5.QtGui import QFontDatabase
        from .custom_dropdown_menu import CustomDropdownMenu
        font_db = QFontDatabase()
        font_families = font_db.families()
        
        # 获取当前字体设置
        current_font = self.settings_manager.get_setting("font.style", "Microsoft YaHei")
        
        # 创建字体样式选择控件（只用于显示标题和描述）
        font_style_label = CustomSettingItem(
            text="字体样式",
            secondary_text="选择应用内使用的字体",
            interaction_type=None  # 不添加交互控件
        )
        
        # 创建自定义下拉菜单（直接使用自带的按钮）
        self.font_dropdown_menu = CustomDropdownMenu(self, position="bottom")
        
        # 设置按钮样式为primary
        self.font_dropdown_menu.main_button.set_button_type("primary")
        
        # 设置字体列表项
        self.font_dropdown_menu.set_items(font_families, default_item=current_font)
        
        # 字体选择下拉菜单项点击处理
        def on_font_item_clicked(selected_font_family):
            self.current_settings.update({"font.style": selected_font_family})
        self.font_dropdown_menu.itemClicked.connect(on_font_item_clicked)
        
        # 将标签和下拉菜单添加到布局
        font_layout.addWidget(font_style_label)
        font_layout.addWidget(self.font_dropdown_menu)
        
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
        
        # 返回上级鼠标快捷键
        self.return_shortcut_setting = CustomSettingItem(
            text="返回上级鼠标快捷键",
            secondary_text="设置返回上级目录的鼠标操作快捷键",
            interaction_type=CustomSettingItem.BUTTON_GROUP_TYPE,
            buttons=[{"text": "设置", "type": "primary"}]
        )
        
        # 快捷键设置按钮点击处理
        def on_return_shortcut_clicked(button_index):
            # 在实际应用中，这里应该打开快捷键设置界面
            # 暂时使用默认设置
            self.current_settings.update({"file_selector.return_shortcut": "middle_click"})
        self.return_shortcut_setting.button_clicked.connect(on_return_shortcut_clicked)
        file_selector_layout.addWidget(self.return_shortcut_setting)
        
        self.scroll_layout.addWidget(file_selector_group)
    
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
        player_group = QGroupBox("播放器设置")
        player_group.setStyleSheet(self.group_box_style)
        player_layout = QVBoxLayout(player_group)
        
        # 播放速度设置
        self.speed_bar = CustomSettingItem(
            text="默认播放速度",
            secondary_text="设置视频默认播放速度",
            interaction_type=CustomSettingItem.VALUE_BAR_TYPE,
            min_value=50,
            max_value=200,
            initial_value=int(self.settings_manager.get_setting("player.speed", 1.0) * 100)
        )
        self.speed_bar.value_changed.connect(lambda value: self.current_settings.update({"player.speed": value / 100}))
        player_layout.addWidget(self.speed_bar)
        
        # 音量设置
        self.volume_bar = CustomSettingItem(
            text="默认音量",
            secondary_text="设置默认音量大小",
            interaction_type=CustomSettingItem.VALUE_BAR_TYPE,
            min_value=0,
            max_value=100,
            initial_value=self.settings_manager.get_setting("player.volume", 100)
        )
        self.volume_bar.value_changed.connect(lambda value: self.current_settings.update({"player.volume": value}))
        player_layout.addWidget(self.volume_bar)
        
        self.scroll_layout.addWidget(player_group)
    
    def _add_general_settings(self):
        """
        添加通用设置项
        """
        general_group = QGroupBox("通用设置")
        general_group.setStyleSheet(self.group_box_style)
        general_layout = QVBoxLayout(general_group)
        
        # 通用设置项可以在这里添加
        
        self.scroll_layout.addWidget(general_group)
    
    def _open_theme_color_settings(self):
        """
        打开主题颜色设置窗口
        """
        from .window_widgets import ThemeSettingsWindow
        
        theme_window = ThemeSettingsWindow(self)
        theme_window.exec_()
    
    def load_settings(self):
        """
        加载当前设置
        """
        self.current_settings = {
            "appearance.theme": self.settings_manager.get_setting("appearance.theme", "default"),
            "font.size": self.settings_manager.get_setting("font.size", 20),
            "font.style": self.settings_manager.get_setting("font.style", "Microsoft YaHei"),
            "file_selector.auto_clear_thumbnail_cache": self.settings_manager.get_setting("file_selector.auto_clear_thumbnail_cache", True),
            "file_selector.cache_cleanup_period": self.settings_manager.get_setting("file_selector.cache_cleanup_period", 7),
            "file_selector.cache_cleanup_threshold": self.settings_manager.get_setting("file_selector.cache_cleanup_threshold", 500),
            "file_selector.restore_last_path": self.settings_manager.get_setting("file_selector.restore_last_path", True),
            "file_selector.return_shortcut": self.settings_manager.get_setting("file_selector.return_shortcut", "middle_click"),
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
        # 更新设置管理器中的设置
        for key, value in self.current_settings.items():
            self.settings_manager.set_setting(key, value)
        
        # 保存设置到文件
        self.settings_manager.save_settings()
        
        # 发出设置保存信号
        self.settings_saved.emit(self.current_settings)
        
        # 关闭窗口
        self.close()
    
    def reset_settings(self):
        """
        重置设置为默认值
        """
        # 重置设置管理器
        self.settings_manager.reset_to_defaults()
        
        # 重新加载设置
        self.load_settings()
        
        # 更新UI显示
        self._fill_tab_content("appearance")
        self.settings_manager.save_settings()
        
        # 发送设置保存信号
        self.settings_saved.emit(self.current_settings)
        
        # 关闭窗口
        self.close()


# 更新 __init__.py 文件，导出新控件
# 注意：在实际使用时，需要手动更新 custom_widgets.py 文件，将新控件添加到导入和导出列表中
