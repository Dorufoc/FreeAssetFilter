#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试主题编辑器功能
验证深色/浅色模式切换时的颜色显示效果
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton
from PyQt5.QtCore import Qt
from freeassetfilter.components.theme_editor import ThemeEditor
from freeassetfilter.core.settings_manager import SettingsManager
from freeassetfilter.components.theme_manager import ThemeManager

class TestThemeEditorWindow(QMainWindow):
    """
    测试主题编辑器的窗口
    """
    def __init__(self):
        super().__init__()
        
        # 初始化设置管理器
        self.settings_manager = SettingsManager()
        
        # 初始化主题管理器
        self.theme_manager = ThemeManager(self.settings_manager)
        
        # 设置窗口基本信息
        self.setWindowTitle("主题编辑器测试")
        self.setGeometry(100, 100, 800, 600)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建布局
        main_layout = QVBoxLayout(central_widget)
        
        # 添加主题编辑器
        self.theme_editor = ThemeEditor()
        self.theme_editor.settings_manager = self.settings_manager
        main_layout.addWidget(self.theme_editor)
        
        # 添加测试按钮
        button_layout = QVBoxLayout()
        
        # 深色模式切换按钮
        self.dark_mode_btn = QPushButton("切换深色模式")
        self.dark_mode_btn.clicked.connect(self.toggle_dark_mode)
        button_layout.addWidget(self.dark_mode_btn)
        
        # 应用主题按钮
        self.apply_btn = QPushButton("应用选中主题")
        self.apply_btn.clicked.connect(self.apply_theme)
        button_layout.addWidget(self.apply_btn)
        
        # 重置主题按钮
        self.reset_btn = QPushButton("重置主题")
        self.reset_btn.clicked.connect(self.reset_theme)
        button_layout.addWidget(self.reset_btn)
        
        main_layout.addLayout(button_layout)
        
        # 连接主题选择信号
        self.theme_editor.theme_selected.connect(self.on_theme_selected)
        
        # 连接主题应用完成信号
        self.theme_editor.theme_applied.connect(self.on_theme_applied)
    
    def toggle_dark_mode(self):
        """
        切换深色模式
        """
        # 获取当前深色模式状态
        is_dark = self.settings_manager.get_setting("appearance.theme", "default") == "dark"
        
        # 切换主题模式
        self.theme_manager.toggle_theme(not is_dark)
        
        # 重新初始化主题编辑器
        self.theme_editor.is_dark_mode = self.theme_editor._is_dark_mode()
        self.theme_editor.selected_theme = None
        self.theme_editor._check_current_theme_match()
        self.theme_editor.init_ui()
        
        # 更新按钮文本
        self.dark_mode_btn.setText("切换浅色模式" if not is_dark else "切换深色模式")
        
        print(f"深色模式已{'启用' if not is_dark else '禁用'}")
    
    def apply_theme(self):
        """
        应用选中的主题
        """
        self.theme_editor.on_apply_clicked()
    
    def reset_theme(self):
        """
        重置主题
        """
        self.theme_editor.on_reset_clicked()
    
    def on_theme_selected(self, theme):
        """
        主题选择信号处理
        """
        print(f"选中主题: {theme['name']}")
        print(f"主题颜色: {theme['colors']}")
    
    def on_theme_applied(self):
        """
        主题应用完成信号处理
        """
        print("主题应用完成")
        
        # 打印当前主题设置
        current_theme = {
            "accent_color": self.settings_manager.get_setting("appearance.colors.accent_color", "#007AFF"),
            "secondary_color": self.settings_manager.get_setting("appearance.colors.secondary_color", "#333333"),
            "normal_color": self.settings_manager.get_setting("appearance.colors.normal_color", "#e0e0e0"),
            "auxiliary_color": self.settings_manager.get_setting("appearance.colors.auxiliary_color", "#f1f3f5"),
            "base_color": self.settings_manager.get_setting("appearance.colors.base_color", "#f1f3f5")
        }
        
        print("当前主题设置:")
        for key, value in current_theme.items():
            print(f"  {key}: {value}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # 设置应用的设置管理器
    app.settings_manager = SettingsManager()
    
    window = TestThemeEditorWindow()
    window.show()
    
    sys.exit(app.exec_())
