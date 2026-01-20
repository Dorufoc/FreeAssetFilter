#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 现代主题编辑器
实现主题的预设选择和自定义功能
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QGridLayout, QScrollArea, QApplication, QLabel
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
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
        
        self.app = QApplication.instance()
        self.settings_manager = getattr(self.app, 'settings_manager', None)
        self.dpi_scale = getattr(self.app, 'dpi_scale_factor', 1.0)
        self.global_font_size = getattr(self.app, 'default_font_size', 8)
        
        self.preset_themes = [
            {"name": "活力蓝", "colors": ["#0A59F7"]},
            {"name": "热情红", "colors": ["#FC5454"]},
            {"name": "蜂蜜黄", "colors": ["#F0C54D"]},
            {"name": "宝石青", "colors": ["#58D9C0"]},
            {"name": "魅力紫", "colors": ["#B036EE"]},
            {"name": "清雅墨", "colors": ["#383F4C"]}
        ]
        
        self.custom_themes = [
            {"name": "自定义设计1", "colors": ["#27BE24"]}
        ]
        
        self.current_theme = self._load_current_theme()
        self.is_dark_mode = self._is_dark_mode()
        
        self.selected_theme = None
        self._last_max_cols = 0
        self._last_container_width = 0
        self._slider_color = self._load_slider_color()
        
        self._check_current_theme_match()
        
        self.init_ui()
        
        QTimer.singleShot(100, self._on_layout_initialized)
    
    def _get_theme_colors(self, accent_color):
        """
        根据当前深色模式获取完整的主题颜色集
        
        参数：
            accent_color (str): 强调色
            
        返回：
            list: 包含完整主题颜色的列表 [accent_color, secondary_color, normal_color, auxiliary_color]
        """
        if self.is_dark_mode:
            # 深色模式颜色
            return [
                accent_color,       # 强调色保持不变
                "#FFFFFF",        # secondary_color (文字颜色)
                "#717171",        # normal_color
                "#313131"         # auxiliary_color
            ]
        else:
            # 浅色模式颜色
            return [
                accent_color,       # 强调色保持不变
                "#333333",        # secondary_color (文字颜色)
                "#e0e0e0",        # normal_color
                "#f3f3f3"         # auxiliary_color
            ]
    
    def _load_slider_color(self):
        """
        从设置中加载用户自定义的颜色
        
        返回：
            str: 保存的颜色值，默认为 #27BE24
        """
        default_color = "#27BE24"
        if self.settings_manager:
            return self.settings_manager.get_setting("appearance.colors.custom_design_color", default_color)
        return default_color
    
    def _save_slider_color(self, color):
        """
        将用户自定义的颜色保存到设置中
        
        参数：
            color (str): 要保存的颜色值
        """
        if self.settings_manager:
            self.settings_manager.set_setting("appearance.colors.custom_design_color", color)
    
    def _check_current_theme_match(self):
        """
        检查当前主题是否与预设主题匹配
        """
        if not self.current_theme:
            return
        
        current_accent = self.current_theme["accent_color"]
        
        for theme in self.preset_themes:
            if theme["colors"][0] == current_accent:
                full_colors = self._get_theme_colors(theme["colors"][0])
                self.selected_theme = {
                    "name": theme["name"],
                    "colors": full_colors
                }
                return
        
        for theme in self.custom_themes:
            if theme["colors"][0] == current_accent:
                full_colors = self._get_theme_colors(theme["colors"][0])
                self.selected_theme = {
                    "name": theme["name"],
                    "colors": full_colors
                }
                return
        
        if self._slider_color == current_accent:
            full_colors = self._get_theme_colors(self._slider_color)
            self.selected_theme = {
                "name": "自定义设计1",
                "colors": full_colors
            }
        elif not self.selected_theme:
            full_colors = self._get_theme_colors(self._slider_color)
            self.selected_theme = {
                "name": "自定义设计1",
                "colors": full_colors
            }
    
    def get_selected_theme(self):
        """
        获取当前选中的主题
        
        Returns:
            dict: 选中的主题信息，包含 name 和 colors，或 None
        """
        return self.selected_theme
    
    def _is_dark_mode(self):
        """
        检查当前是否为深色模式
        
        返回：
            bool: True为深色模式，False为浅色模式
        """
        if self.settings_manager:
            return self.settings_manager.get_setting("appearance.theme", "default") == "dark"
        return False
    
    def _load_current_theme(self):
        """
        从设置管理器加载当前主题设置
        """
        if self.settings_manager:
            return {
                "accent_color": self.settings_manager.get_setting("appearance.colors.accent_color", "#007AFF"),
                "secondary_color": self.settings_manager.get_setting("appearance.colors.secondary_color", "#333333"),
                "normal_color": self.settings_manager.get_setting("appearance.colors.normal_color", "#e0e0e0"),
                "auxiliary_color": self.settings_manager.get_setting("appearance.colors.auxiliary_color", "#f1f3f5"),
                "base_color": self.settings_manager.get_setting("appearance.colors.base_color", "#f1f3f5")
            }
        return None
    
    def init_ui(self):
        """初始化UI"""
        self.setWidgetResizable(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        base_color = "#FFFFFF"
        if self.settings_manager:
            base_color = self.settings_manager.get_setting("appearance.colors.base_color", "#FFFFFF")
        
        self.setStyleSheet(f"background-color: {base_color};")
        
        self.scroll_widget = QWidget()
        self.scroll_widget.setStyleSheet(f"background-color: {base_color};")
        self.scroll_layout = QVBoxLayout(self.scroll_widget)
        self.scroll_layout.setContentsMargins(int(6 * self.dpi_scale), int(6 * self.dpi_scale), int(6 * self.dpi_scale), int(6 * self.dpi_scale))
        self.scroll_layout.setSpacing(int(12 * self.dpi_scale))
        
        self.preset_group = QGroupBox(self.scroll_widget)
        font = QFont("Noto Sans SC", int(self.dpi_scale * self.global_font_size * 1.6))
        self.preset_group.setFont(font)
        
        base_color = "#FFFFFF"
        if self.settings_manager:
            base_color = self.settings_manager.get_setting("appearance.colors.base_color", "#FFFFFF")
        self.preset_group.setStyleSheet(f"QGroupBox {{ border: 1px solid {base_color}; border-radius: {int(3 * self.dpi_scale)}px; margin-top: {int(3 * self.dpi_scale)}px; margin-bottom: {int(6 * self.dpi_scale)}px; }}")
        
        self.preset_title_label = QLabel("预设", self.preset_group)
        self.preset_title_label.setFont(font)
        secondary_color = "#333333"
        if self.settings_manager:
            secondary_color = self.settings_manager.get_setting("appearance.colors.secondary_color", "#333333")
        self.preset_title_label.setStyleSheet(f"color: {secondary_color};")
        self.preset_title_label.setContentsMargins(0, 0, 0, int(3 * self.dpi_scale))
        
        self.preset_group_layout = QVBoxLayout(self.preset_group)
        self.preset_group_layout.setContentsMargins(int(6 * self.dpi_scale), int(6 * self.dpi_scale), int(6 * self.dpi_scale), int(6 * self.dpi_scale))
        self.preset_group_layout.setSpacing(int(6 * self.dpi_scale))
        self.preset_group_layout.addWidget(self.preset_title_label)
        
        self.preset_grid = QGridLayout()
        self.preset_grid.setContentsMargins(0, 0, 0, 0)
        self.preset_grid.setSpacing(int(6 * self.dpi_scale))
        
        # 添加预设主题卡片
        for index, theme in enumerate(self.preset_themes):
            row = index // 3
            col = index % 3
            
            # 根据当前深色模式获取完整颜色集
            card_colors = self._get_theme_colors(theme["colors"][0])
            
            # 检查是否是当前选中的主题
            is_selected = self.selected_theme and self.selected_theme["colors"] == card_colors
            
            card = ThemeCard(
                theme["name"], 
                card_colors, 
                is_selected=is_selected,
                parent=self.preset_group
            )
            card.clicked.connect(self.on_theme_card_clicked)
            self.preset_grid.addWidget(card, row, col)
        
        self.preset_group_layout.addLayout(self.preset_grid)
        self.scroll_layout.addWidget(self.preset_group)
        
        self.custom_group = QGroupBox(self.scroll_widget)
        font = QFont("Noto Sans SC", int(self.dpi_scale * self.global_font_size * 1.6))
        self.custom_group.setFont(font)
        
        base_color = "#FFFFFF"
        if self.settings_manager:
            base_color = self.settings_manager.get_setting("appearance.colors.base_color", "#FFFFFF")
        self.custom_group.setStyleSheet(f"QGroupBox {{ border: 1px solid {base_color}; border-radius: {int(3 * self.dpi_scale)}px; margin-top: {int(3 * self.dpi_scale)}px; margin-bottom: {int(6 * self.dpi_scale)}px; }}")
        
        self.custom_title_label = QLabel("自定义", self.custom_group)
        self.custom_title_label.setFont(font)
        secondary_color = "#333333"
        if self.settings_manager:
            secondary_color = self.settings_manager.get_setting("appearance.colors.secondary_color", "#333333")
        self.custom_title_label.setStyleSheet(f"color: {secondary_color};")
        self.custom_title_label.setContentsMargins(0, 0, 0, int(3 * self.dpi_scale))
        
        self.custom_group_layout = QVBoxLayout(self.custom_group)
        self.custom_group_layout.setContentsMargins(int(6 * self.dpi_scale), int(6 * self.dpi_scale), int(6 * self.dpi_scale), int(6 * self.dpi_scale))
        self.custom_group_layout.setSpacing(int(6 * self.dpi_scale))
        self.custom_group_layout.addWidget(self.custom_title_label)
        
        self.custom_grid = QGridLayout()
        self.custom_grid.setContentsMargins(0, 0, 0, 0)
        self.custom_grid.setSpacing(int(6 * self.dpi_scale))
        
        self.custom_design_card = None
        
        # 添加自定义主题卡片
        for index, theme in enumerate(self.custom_themes):
            # 根据当前深色模式获取完整颜色集
            card_colors = self._get_theme_colors(theme["colors"][0])
            
            # 对于自定义设计1，使用用户保存的滑条颜色
            if theme["name"] == "自定义设计1":
                card_colors = self._get_theme_colors(self._slider_color)
            
            # 检查是否是当前选中的主题
            is_selected = self.selected_theme and self.selected_theme["colors"] == card_colors
            
            card = ThemeCard(
                theme["name"], 
                card_colors,
                is_selected=is_selected,
                parent=self.custom_group
            )
            card.clicked.connect(self.on_theme_card_clicked)
            self.custom_grid.addWidget(card, 0, index)
            
            if theme["name"] == "自定义设计1":
                self.custom_design_card = card
        
        # 添加新设计卡片
        self.add_card = ThemeCard(
            "", 
            [],
            is_add_card=True,
            parent=self.custom_group
        )
        self.add_card.color_changed.connect(self._on_add_card_color_changed)
        self.custom_grid.addWidget(self.add_card, 0, len(self.custom_themes))
        
        self.custom_group_layout.addLayout(self.custom_grid)
        self.scroll_layout.addWidget(self.custom_group)
        
        # 设置滚动部件
        self.setWidget(self.scroll_widget)
        
        self.viewport().installEventFilter(self)
        
        # 延迟设置滑条初始颜色，确保UI完全初始化
        QTimer.singleShot(0, self._initialize_slider_color)
    
    def _initialize_slider_color(self):
        """初始化滑条颜色，从设置中加载保存的颜色"""
        if hasattr(self.add_card, 'color_slider') and self.add_card.color_slider:
            self.add_card.color_slider.set_color(self._slider_color)
            # 更新自定义设计卡片的颜色显示
            if self.custom_design_card:
                card_colors = self._get_theme_colors(self._slider_color)
                self.custom_design_card.set_colors(card_colors)
    
    def _on_layout_initialized(self):
        """布局初始化完成后更新卡片宽度"""
        self._update_all_cards_width()
    
    def eventFilter(self, obj, event):
        """事件过滤器，用于检测视口大小变化"""
        if obj == self.viewport() and event.type() == event.Resize:
            QTimer.singleShot(50, self._on_viewport_resized)
        return super().eventFilter(obj, event)
    
    def _on_viewport_resized(self):
        """当视口大小变化时，重新排列主题卡片"""
        self._update_all_cards_width()
    
    def _calculate_max_columns(self):
        """
        根据当前视口宽度精确计算每行卡片数量
        """
        viewport_width = self.viewport().width()
        
        card_width = int(75 * self.dpi_scale)
        spacing = int(6 * self.dpi_scale)
        actual_margin = int(6 * self.dpi_scale)
        margin = actual_margin * 2
        
        available_width = viewport_width - margin
        
        columns = 1
        max_possible_columns = 0
        
        while True:
            total_width = columns * card_width + (columns - 1) * spacing
            if total_width <= available_width:
                max_possible_columns = columns
                columns += 1
            else:
                break
        
        return max(1, max_possible_columns)
    
    def _calculate_card_width(self):
        """
        计算每个卡片可用的动态宽度
        """
        container_width = self.viewport().width()
        
        if container_width <= 0:
            return None
        
        max_cols = self._calculate_max_columns()
        if max_cols <= 0:
            return None
        
        spacing = self.preset_grid.spacing()
        margins = self.preset_grid.contentsMargins()
        total_margin = margins.left() + margins.right()
        
        available_width = container_width - (max_cols + 1) * spacing - total_margin
        card_width = available_width // max_cols
        
        return card_width
    
    def _update_all_cards_width(self):
        """更新所有卡片的动态宽度，并重新排列卡片"""
        container_width = self.viewport().width()
        if container_width <= 0:
            QTimer.singleShot(50, self._update_all_cards_width)
            return
        
        max_cols = self._calculate_max_columns()
        if max_cols <= 0:
            return
        
        spacing = self.preset_grid.spacing()
        margins = self.preset_grid.contentsMargins()
        total_margin = margins.left() + margins.right()
        
        available_width = container_width - (max_cols + 1) * spacing - total_margin
        card_width = available_width // max_cols
        
        if container_width != self._last_container_width:
            self._last_container_width = container_width
        
        if max_cols != self._last_max_cols:
            self._rearrange_cards(max_cols)
        
        self._last_max_cols = max_cols
        
        self._update_group_cards_width(self.preset_grid, card_width)
        self._update_group_cards_width(self.custom_grid, card_width)
    
    def _update_group_cards_width(self, grid_layout, card_width):
        """更新布局中所有卡片的宽度"""
        for i in range(grid_layout.count()):
            item = grid_layout.itemAt(i)
            if item is not None:
                widget = item.widget()
                if widget is not None and isinstance(widget, ThemeCard):
                    widget.set_flexible_width(card_width)
    
    def _rearrange_cards(self, max_cols):
        """重新排列卡片到新的行列位置"""
        self._rearrange_group_cards(self.preset_grid, max_cols)
        self._rearrange_group_cards(self.custom_grid, max_cols)
    
    def _rearrange_group_cards(self, grid_layout, max_cols):
        """重新排列单个组中的卡片"""
        cards = []
        for i in range(grid_layout.count()):
            item = grid_layout.itemAt(i)
            if item is not None:
                widget = item.widget()
                if widget is not None and isinstance(widget, ThemeCard):
                    cards.append(widget)
        
        if not cards:
            return
        
        while grid_layout.count() > 0:
            item = grid_layout.takeAt(0)
            if item.widget():
                grid_layout.removeWidget(item.widget())
        
        for i, card in enumerate(cards):
            row = i // max_cols
            col = i % max_cols
            grid_layout.addWidget(card, row, col)
    
    def on_theme_card_clicked(self, card):
        """主题卡片点击事件"""
        if card.is_add_card:
            return
        
        is_custom_design = card.theme_name == "自定义设计1"
        
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
        
        # 获取颜色：如果是自定义设计卡片，使用滑条颜色
        if is_custom_design:
            theme_colors = self._get_theme_colors(self._slider_color)
        else:
            theme_colors = card.colors
        
        # 更新选中主题
        self.selected_theme = {
            "name": card.theme_name,
            "colors": theme_colors
        }
        
        # 发送主题选中信号
        self.theme_selected.emit(self.selected_theme)
    
    def on_add_card_clicked(self, card):
        """添加新设计卡片点击事件"""
        self.add_new_design.emit()
    
    def _on_add_card_color_changed(self, color):
        """添加卡片颜色滑条变化事件，更新自定义设计卡片"""
        self._slider_color = color
        self._save_slider_color(color)
        if self.custom_design_card:
            card_colors = self._get_theme_colors(color)
            self.custom_design_card.set_colors(card_colors)
            self.custom_design_card.set_selected(True)
    
    def on_reset_clicked(self):
        """
        重置按钮点击事件
        重置所有颜色设置为默认值
        """
        # 默认强调色设置
        default_accent_color = "#007AFF"
        
        # 更新设置管理器中的颜色设置
        if self.settings_manager:
            # 只重置强调色，其他颜色通过深色模式自动获取
            self.settings_manager.set_setting("appearance.colors.accent_color", default_accent_color)
            
            # 保存设置
            self.settings_manager.save_settings()
            
            # 重新加载当前主题设置
            self.current_theme = self._load_current_theme()
            
            # 更新深色模式状态
            self.is_dark_mode = self._is_dark_mode()
            
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
                
                # 只保存强调色，其他颜色通过深色模式自动获取
                accent_color = self.selected_theme["colors"][0]
                setting_path = "appearance.colors.accent_color"
                debug(f"设置颜色: accent_color = {accent_color} (路径: {setting_path})")
                self.settings_manager.set_setting(setting_path, accent_color)
                
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