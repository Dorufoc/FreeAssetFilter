#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 现代主题编辑器
实现主题的预设选择和自定义功能
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QGridLayout, 
    QScrollArea
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

# 导入独立的ThemeCard控件
from freeassetfilter.widgets.theme_card import ThemeCard

class ThemeEditor(QScrollArea):
    """
    现代主题编辑器
    包含预设组和自定义组的滚动布局窗口
    """
    
    theme_selected = pyqtSignal(dict)  # 主题选中信号
    add_new_design = pyqtSignal()  # 添加新设计信号
    theme_applied = pyqtSignal()  # 主题应用完成信号，用于关闭窗口
    
    def __init__(self, parent=None):
        """初始化主题编辑器"""
        super().__init__(parent)
        
        # 获取应用实例和设置管理器
        from PyQt5.QtWidgets import QApplication
        self.app = QApplication.instance()
        self.settings_manager = getattr(self.app, 'settings_manager', None)
        
        # 预设主题数据
        self.preset_themes = [
            {"name": "活力蓝", "colors": ["#0A59F7", "#000000", "#808080", "#D9D9D9"]},
            {"name": "热情红", "colors": ["#FC5454", "#000000", "#808080", "#D9D9D9"]},
            {"name": "蜂蜜黄", "colors": ["#F0C54D", "#000000", "#808080", "#D9D9D9"]},
            {"name": "宝石青", "colors": ["#58D9C0", "#000000", "#808080", "#D9D9D9"]},
            {"name": "魅力紫", "colors": ["#B036EE", "#000000", "#808080", "#D9D9D9"]},
            {"name": "清雅墨", "colors": ["#383F4C", "#FFFFFF", "#808080", "#D9D9D9"]}
        ]
        
        # 自定义主题数据
        self.custom_themes = [
            {"name": "自定义设计1", "colors": ["#27BE24", "#000000", "#808080", "#D9D9D9"]}
        ]
        
        # 加载当前主题设置
        self.current_theme = self._load_current_theme()
        
        self.selected_theme = None
        
        # 在初始化UI前检查当前主题是否与预设主题匹配
        self._check_current_theme_match()
        
        self.init_ui()
    
    def _check_current_theme_match(self):
        """
        检查当前主题是否与预设主题匹配
        """
        if not self.current_theme:
            return
        
        # 当前主题颜色列表
        current_colors = [
            self.current_theme["accent_color"],
            self.current_theme["secondary_color"],
            self.current_theme["normal_color"],
            self.current_theme["auxiliary_color"]
        ]
        
        # 检查是否与预设主题匹配
        for theme in self.preset_themes:
            if theme["colors"] == current_colors:
                self.selected_theme = theme
                return
        
        # 检查是否与自定义主题匹配
        for theme in self.custom_themes:
            if theme["colors"] == current_colors:
                self.selected_theme = theme
                return
    
    def _load_current_theme(self):
        """
        从设置管理器加载当前主题设置
        """
        if self.settings_manager:
            return {
                "accent_color": self.settings_manager.get_setting("appearance.colors.accent_color", "#007AFF"),
                "secondary_color": self.settings_manager.get_setting("appearance.colors.secondary_color", "#333333"),
                "normal_color": self.settings_manager.get_setting("appearance.colors.normal_color", "#e0e0e0"),
                "auxiliary_color": self.settings_manager.get_setting("appearance.colors.auxiliary_color", "#f1f3f5")
            }
        return None
    
    def init_ui(self):
        """初始化UI"""
        # 设置滚动区域
        self.setWidgetResizable(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        # 主窗口部件
        self.scroll_widget = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_widget)
        self.scroll_layout.setContentsMargins(20, 20, 20, 20)
        self.scroll_layout.setSpacing(40)
        
        # 预设组
        self.preset_group = QGroupBox("预设", self.scroll_widget)
        # 设置组标题字体大小
        font = QFont("Noto Sans SC", 16)
        self.preset_group.setFont(font)
        
        self.preset_group_layout = QVBoxLayout(self.preset_group)
        self.preset_group_layout.setContentsMargins(20, 30, 20, 20)
        self.preset_group_layout.setSpacing(20)
        
        # 预设主题网格布局
        self.preset_grid = QGridLayout()
        self.preset_grid.setContentsMargins(0, 0, 0, 0)
        self.preset_grid.setSpacing(20)
        
        # 添加预设主题卡片
        for index, theme in enumerate(self.preset_themes):
            row = index // 3
            col = index % 3
            
            # 检查是否是当前选中的主题
            is_selected = self.selected_theme and self.selected_theme["colors"] == theme["colors"]
            
            card = ThemeCard(
                theme["name"], 
                theme["colors"], 
                is_selected=is_selected,
                parent=self.preset_group
            )
            card.clicked.connect(self.on_theme_card_clicked)
            self.preset_grid.addWidget(card, row, col)
        
        self.preset_group_layout.addLayout(self.preset_grid)
        self.scroll_layout.addWidget(self.preset_group)
        
        # 自定义组
        self.custom_group = QGroupBox("自定义", self.scroll_widget)
        # 设置组标题字体大小
        font = QFont("Noto Sans SC", 16)
        self.custom_group.setFont(font)
        
        self.custom_group_layout = QVBoxLayout(self.custom_group)
        self.custom_group_layout.setContentsMargins(20, 30, 20, 20)
        self.custom_group_layout.setSpacing(20)
        
        # 自定义主题网格布局
        self.custom_grid = QGridLayout()
        self.custom_grid.setContentsMargins(0, 0, 0, 0)
        self.custom_grid.setSpacing(20)
        
        # 添加自定义主题卡片
        for index, theme in enumerate(self.custom_themes):
            # 检查是否是当前选中的主题
            is_selected = self.selected_theme and self.selected_theme["colors"] == theme["colors"]
            
            card = ThemeCard(
                theme["name"], 
                theme["colors"],
                is_selected=is_selected,
                parent=self.custom_group
            )
            card.clicked.connect(self.on_theme_card_clicked)
            self.custom_grid.addWidget(card, 0, index)
        
        # 添加新设计卡片
        self.add_card = ThemeCard(
            "", 
            [],
            is_add_card=True,
            parent=self.custom_group
        )
        self.add_card.clicked.connect(self.on_add_card_clicked)
        self.custom_grid.addWidget(self.add_card, 0, len(self.custom_themes))
        
        self.custom_group_layout.addLayout(self.custom_grid)
        self.scroll_layout.addWidget(self.custom_group)
        
        # 设置滚动部件
        self.setWidget(self.scroll_widget)
    
    def on_theme_card_clicked(self, card):
        """主题卡片点击事件"""
        if card.is_add_card:
            return
        
        # 取消之前选中的卡片
        if self.selected_theme:
            for i in range(self.preset_grid.count()):
                widget = self.preset_grid.itemAt(i).widget()
                if widget and widget.theme_name == self.selected_theme["name"]:
                    widget.is_selected = False
                    widget.update()
                    break
            
            for i in range(self.custom_grid.count()):
                widget = self.custom_grid.itemAt(i).widget()
                if widget and hasattr(widget, 'theme_name') and widget.theme_name == self.selected_theme["name"]:
                    widget.is_selected = False
                    widget.update()
                    break
        
        # 选中当前卡片
        card.is_selected = True
        card.update()
        
        # 更新选中主题
        self.selected_theme = {
            "name": card.theme_name,
            "colors": card.colors
        }
        
        # 发送主题选中信号
        self.theme_selected.emit(self.selected_theme)
    
    def on_add_card_clicked(self, card):
        """添加新设计卡片点击事件"""
        self.add_new_design.emit()
    
    def on_reset_clicked(self):
        """
        重置按钮点击事件
        重置所有颜色设置为默认值
        """
        # 默认颜色设置
        default_colors = {
            "accent_color": "#007AFF",
            "secondary_color": "#333333",
            "normal_color": "#e0e0e0",
            "auxiliary_color": "#f1f3f5"
        }
        
        # 更新设置管理器中的颜色设置
        if self.settings_manager:
            for color_key, color_value in default_colors.items():
                self.settings_manager.set_setting(f"appearance.colors.{color_key}", color_value)
            
            # 保存设置
            self.settings_manager.save_settings()
            
            # 重新加载当前主题设置
            self.current_theme = self._load_current_theme()
            
            # 更新选中主题
            self.selected_theme = None
            
            # 重新初始化UI
            self.init_ui()
    
    def on_apply_clicked(self):
        """
        应用按钮点击事件
        应用选中的主题颜色
        """
        import datetime
        def debug(msg):
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            print(f"[{timestamp}] [ThemeEditor.on_apply_clicked] {msg}")
        
        debug("开始应用选中的主题颜色")
        
        if self.selected_theme and "colors" in self.selected_theme:
            debug(f"选中的主题: {self.selected_theme['name']}")
            debug(f"主题颜色列表: {self.selected_theme['colors']}")
            
            # 发送主题选择信号
            debug("发送主题选择信号")
            self.theme_selected.emit(self.selected_theme)
            
            # 直接保存设置，确保配置被保存到文件
            if self.settings_manager:
                debug("使用设置管理器保存主题颜色")
                
                # 定义颜色映射
                color_mapping = {
                    "accent_color": self.selected_theme["colors"][0],
                    "secondary_color": self.selected_theme["colors"][1],
                    "normal_color": self.selected_theme["colors"][2],
                    "auxiliary_color": self.selected_theme["colors"][3]
                }
                
                # 保存每个颜色
                for color_key, color_value in color_mapping.items():
                    setting_path = f"appearance.colors.{color_key}"
                    debug(f"设置颜色: {color_key} = {color_value} (路径: {setting_path})")
                    self.settings_manager.set_setting(setting_path, color_value)
                
                # 保存设置到文件
                debug("保存所有设置到配置文件")
                self.settings_manager.save_settings()
                debug("主题颜色保存完成")
                # 发送主题应用完成信号
                debug("发送主题应用完成信号")
                self.theme_applied.emit()
            else:
                debug("警告: 没有找到设置管理器，无法保存主题颜色")
        else:
            debug("错误: 没有选中有效的主题或主题缺少颜色信息")

# 测试代码
if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication
    from freeassetfilter.widgets.message_box import CustomWindow
    
    app = QApplication(sys.argv)
    
    # 创建自定义窗口
    window = CustomWindow("主题编辑器")
    window.setGeometry(100, 100, 450, 350)
    
    # 创建主题编辑器
    theme_editor = ThemeEditor()
    
    # 设置主题编辑器为窗口的主控件
    window.setCentralWidget(theme_editor)
    
    window.show()
    sys.exit(app.exec_())