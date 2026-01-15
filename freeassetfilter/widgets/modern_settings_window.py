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
        
        # 初始化UI
        self.init_modern_ui()
        
        # 加载当前设置
        self.load_settings()
    
    def init_modern_ui(self):
        """
        初始化现代化设置窗口UI
        """
        # 设置窗口大小（使用像素值）
        self.setMinimumSize(800, 600)
        self.resize(800, 600)
        
        # 创建主布局（左侧导航 + 右侧内容）
        main_layout = QHBoxLayout(self)
        self.content_layout = main_layout
        
        # 设置主布局边距和间距
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)
        
        # 左侧导航栏
        self.navigation_widget = self._create_navigation_widget()
        main_layout.addWidget(self.navigation_widget, 0)
        
        # 右侧内容区域
        self.content_area = self._create_content_area()
        main_layout.addWidget(self.content_area, 1)
    
    def _create_navigation_widget(self):
        """
        创建左侧导航栏
        """
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        
        # 设置导航栏宽度（使用像素值）
        widget.setFixedWidth(200)
        
        # 设置导航栏样式
        widget.setStyleSheet("""
            QWidget {
                background-color: #2C2C2C;
                border-radius: 8px;
                border: 1px solid #3C3C3C;
            }
        """)
        
        # 导航栏布局
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)
        
        # 导航标题
        title_label = QLabel("设置")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 18px;
                font-weight: 600;
                color: #FFFFFF;
                margin-bottom: 15px;
                padding: 8px;
            }
        """)
        layout.addWidget(title_label)
        
        # 导航选项列表
        self.navigation_list = CustomSelectList(default_width=180, default_height=400)
        
        # 添加导航项
        self.navigation_items = [
            {"text": "外观"},
            {"text": "字体"},
            {"text": "文件选择器"},
            {"text": "文件暂存池"},
            {"text": "播放器"},
            {"text": "通用"}
        ]
        self.navigation_list.add_items(self.navigation_items)
        
        # 连接导航信号
        self.navigation_list.itemClicked.connect(self._on_navigation_clicked)
        
        layout.addWidget(self.navigation_list, 1)
        
        return widget
    
    def _create_content_area(self):
        """
        创建右侧内容区域
        """
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # 设置内容区域样式
        widget.setStyleSheet("""
            QWidget {
                background-color: #2C2C2C;
                border-radius: 8px;
                border: 1px solid #3C3C3C;
            }
        """)
        
        # 内容区域布局
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # 内容标签页
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: none;
            }
            QTabBar::tab {
                background-color: transparent;
                color: #AAAAAA;
                padding: 5px 10px;
                margin-right: 5px;
                border-radius: 3px;
            }
            QTabBar::tab:selected {
                background-color: #4ECDC4;
                color: #FFFFFF;
            }
        """)
        
        # 添加各个设置标签页
        self.appearance_tab = self._create_appearance_tab()
        self.font_tab = self._create_font_tab()
        self.file_selector_tab = self._create_file_selector_tab()
        self.file_staging_tab = self._create_file_staging_tab()
        self.player_tab = self._create_player_tab()
        self.general_tab = self._create_general_tab()
        
        self.tab_widget.addTab(self.appearance_tab, "外观")
        self.tab_widget.addTab(self.font_tab, "字体")
        self.tab_widget.addTab(self.file_selector_tab, "文件选择器")
        self.tab_widget.addTab(self.file_staging_tab, "文件暂存池")
        self.tab_widget.addTab(self.player_tab, "播放器")
        self.tab_widget.addTab(self.general_tab, "通用")
        
        layout.addWidget(self.tab_widget, 1)
        
        # 底部按钮区域
        self.buttons_widget = self._create_buttons_widget()
        layout.addWidget(self.buttons_widget)
        
        return widget
    
    def _create_appearance_tab(self):
        """
        创建外观设置标签页
        """
        return self._create_scrollable_tab("外观设置")
    
    def _create_font_tab(self):
        """
        创建字体设置标签页
        """
        return self._create_scrollable_tab("字体设置")
    
    def _create_file_selector_tab(self):
        """
        创建文件选择器设置标签页
        """
        return self._create_scrollable_tab("文件选择器设置")
    
    def _create_file_staging_tab(self):
        """
        创建文件暂存池设置标签页
        """
        return self._create_scrollable_tab("文件暂存池设置")
    
    def _create_player_tab(self):
        """
        创建播放器设置标签页
        """
        return self._create_scrollable_tab("播放器设置")
    
    def _create_general_tab(self):
        """
        创建通用设置标签页
        """
        return self._create_scrollable_tab("通用设置")
    
    def _create_scrollable_tab(self, title):
        """
        创建可滚动的标签页内容
        
        Args:
            title (str): 标签页标题
        
        Returns:
            QWidget: 标签页内容部件
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
                color: #FFFFFF;
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
        self.scroll_layout = QVBoxLayout(scroll_content)
        
        # 应用DPI缩放因子到布局
        scaled_padding = 2
        scaled_spacing = 3
        self.scroll_layout.setContentsMargins(scaled_padding, scaled_padding, scaled_padding, scaled_padding)
        self.scroll_layout.setSpacing(scaled_spacing)
        
        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area, 1)
        
        return widget
    
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
        # 根据导航项索引切换标签页
        self.tab_widget.setCurrentIndex(index)
        
        # 导航项ID映射
        nav_ids = ["appearance", "font", "file_selector", "file_staging", "player", "general"]
        
        if 0 <= index < len(nav_ids):
            # 根据选中的标签页填充内容
            self._fill_tab_content(nav_ids[index])
    
    def _fill_tab_content(self, tab_id):
        """
        根据标签页ID填充内容
        
        Args:
            tab_id (str): 标签页ID
        """
        # 清空当前内容
        self._clear_scroll_layout()
        
        # 根据标签页ID添加设置项
        if tab_id == "appearance":
            self._add_appearance_settings()
        elif tab_id == "font":
            self._add_font_settings()
        elif tab_id == "file_selector":
            self._add_file_selector_settings()
        elif tab_id == "file_staging":
            self._add_file_staging_settings()
        elif tab_id == "player":
            self._add_player_settings()
        elif tab_id == "general":
            self._add_general_settings()
    
    def _clear_scroll_layout(self):
        """
        清空滚动区域布局
        """
        while self.scroll_layout.count() > 0:
            item = self.scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
    
    def _add_appearance_settings(self):
        """
        添加外观设置项
        """
        # 主题设置组
        theme_group = QGroupBox("主题")
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
    
    def _add_font_settings(self):
        """
        添加字体设置项
        """
        # 字体大小设置
        font_size_group = QGroupBox("字体设置")
        font_size_layout = QVBoxLayout(font_size_group)
        
        # 字体大小滑块
        self.font_size_bar = CustomSettingItem(
            text="字体大小",
            secondary_text="调整应用内字体大小",
            interaction_type=CustomSettingItem.VALUE_BAR_TYPE,
            min_value=10,
            max_value=30,
            initial_value=self.settings_manager.get_setting("font.size", 20)
        )
        self.font_size_bar.value_changed.connect(lambda value: self.current_settings.update({"font.size": value}))
        font_size_layout.addWidget(self.font_size_bar)
        
        self.scroll_layout.addWidget(font_size_group)
    
    def _add_file_selector_settings(self):
        """
        添加文件选择器设置项
        """
        file_selector_group = QGroupBox("文件选择器设置")
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
        
        # 恢复上次路径
        self.restore_last_path_switch = CustomSettingItem(
            text="恢复上次路径",
            secondary_text="启动时恢复上次打开的目录",
            interaction_type=CustomSettingItem.SWITCH_TYPE,
            initial_value=self.settings_manager.get_setting("file_selector.restore_last_path", True)
        )
        self.restore_last_path_switch.switch_toggled.connect(lambda value: self.current_settings.update({"file_selector.restore_last_path": value}))
        file_selector_layout.addWidget(self.restore_last_path_switch)
        
        self.scroll_layout.addWidget(file_selector_group)
    
    def _add_file_staging_settings(self):
        """
        添加文件暂存池设置项
        """
        file_staging_group = QGroupBox("文件暂存池设置")
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
            "file_selector.auto_clear_thumbnail_cache": self.settings_manager.get_setting("file_selector.auto_clear_thumbnail_cache", True),
            "file_selector.restore_last_path": self.settings_manager.get_setting("file_selector.restore_last_path", True),
            "file_staging.auto_restore_records": self.settings_manager.get_setting("file_staging.auto_restore_records", True),
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
    
    def reset_settings(self):
        """
        重置设置为默认值
        """
        # 重置所有设置项
        self.theme_switch.set_switch_value(False)
        self.font_size_bar.set_value(20)
        self.auto_clear_cache_switch.set_switch_value(True)
        self.restore_last_path_switch.set_switch_value(True)
        self.auto_restore_switch.set_switch_value(True)
        self.delete_original_switch.set_switch_value(False)
        self.speed_bar.set_value(100)
        self.volume_bar.set_value(100)
        
        # 重置当前设置
        self.load_settings()


# 更新 __init__.py 文件，导出新控件
# 注意：在实际使用时，需要手动更新 custom_widgets.py 文件，将新控件添加到导入和导出列表中
