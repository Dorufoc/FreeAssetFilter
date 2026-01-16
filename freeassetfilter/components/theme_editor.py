#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 现代主题编辑器
实现主题的预设选择和自定义功能
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QGridLayout, 
    QScrollArea, QLabel, QFrame, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal, QSize
from PyQt5.QtGui import QColor, QPen, QBrush, QPainter, QFont

class ThemeCard(QWidget):
    """
    主题卡片组件
    包含色彩行和文字行
    """
    
    clicked = pyqtSignal(object)  # 点击信号，传递主题信息
    
    def __init__(self, theme_name, colors, is_selected=False, is_add_card=False, parent=None):
        """
        初始化主题卡片
        
        Args:
            theme_name (str): 主题名称
            colors (list): 颜色列表 [主题色, 文本颜色, 次选颜色, 不可用颜色]
            is_selected (bool): 是否被选中
            is_add_card (bool): 是否为添加新设计的卡片
            parent (QWidget): 父控件
        """
        super().__init__(parent)
        self.theme_name = theme_name
        self.colors = colors
        self.is_selected = is_selected
        self.is_add_card = is_add_card
        
        # 增加卡片尺寸，为4px的选中边框留出足够空间
        self.setFixedSize(250, 170)
        self.setCursor(Qt.PointingHandCursor)
        
        # 主布局
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(20)
        
        if self.is_add_card:
            # 添加新设计的卡片
            self.add_layout = QHBoxLayout()
            self.add_label = QLabel("添加一个新设计..", self)
            self.add_label.setAlignment(Qt.AlignCenter)
            self.add_label.setFont(QFont("Noto Sans SC", 16))
            self.add_layout.addWidget(self.add_label)
            self.main_layout.addLayout(self.add_layout)
        else:
            # 色彩行
            self.color_layout = QHBoxLayout()
            self.color_layout.setSpacing(10)
            
            # 主题色
            self.theme_color = QFrame(self)
            self.theme_color.setFixedSize(66, 30)
            self.theme_color.setStyleSheet(f"background-color: {colors[0]}; border-radius: 10px;")
            self.color_layout.addWidget(self.theme_color)
            
            # 其他颜色
            for color in colors[1:]:
                color_frame = QFrame(self)
                color_frame.setFixedSize(30, 30)
                color_frame.setStyleSheet(f"background-color: {color}; border-radius: 10px;")
                self.color_layout.addWidget(color_frame)
            
            self.main_layout.addLayout(self.color_layout)
            
            # 文字行
            self.text_label = QLabel(theme_name, self)
            self.text_label.setAlignment(Qt.AlignCenter)
            self.text_label.setFont(QFont("Noto Sans SC", 16))
            self.main_layout.addWidget(self.text_label)
    
    def mousePressEvent(self, event):
        """鼠标点击事件"""
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self)
    
    def paintEvent(self, event):
        """绘制事件，处理选中状态的边框"""
        super().paintEvent(event)
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 绘制卡片背景（2px边框）
        painter.setBrush(QBrush(QColor("#FFFFFF")))
        border_width = 2
        x = border_width // 2
        y = border_width // 2
        width = self.width() - border_width
        height = self.height() - border_width
        painter.setPen(QPen(QColor("#000000"), border_width))
        painter.drawRoundedRect(x, y, width, height, 20, 20)
        
        # 如果是选中状态，绘制加粗边框（4px边框）
        if self.is_selected and not self.is_add_card:
            border_width = 4
            x = border_width // 2
            y = border_width // 2
            width = self.width() - border_width
            height = self.height() - border_width
            painter.setPen(QPen(QColor(self.colors[0]), border_width))
            painter.drawRoundedRect(x, y, width, height, 20, 20)
        
        # 如果是添加卡片，绘制虚线边框（2px边框）
        if self.is_add_card:
            border_width = 2
            x = border_width // 2
            y = border_width // 2
            width = self.width() - border_width
            height = self.height() - border_width
            pen = QPen(QColor("#000000"), border_width, Qt.DashLine)
            painter.setPen(pen)
            painter.drawRoundedRect(x, y, width, height, 20, 20)

class ThemeEditor(QScrollArea):
    """
    现代主题编辑器
    包含预设组和自定义组的滚动布局窗口
    """
    
    theme_selected = pyqtSignal(dict)  # 主题选中信号
    add_new_design = pyqtSignal()  # 添加新设计信号
    
    def __init__(self, parent=None):
        """初始化主题编辑器"""
        super().__init__(parent)
        
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
        
        self.selected_theme = None
        
        self.init_ui()
    
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
            
            is_selected = index == 0  # 默认选中第一个主题
            if is_selected:
                self.selected_theme = theme
            
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
            card = ThemeCard(
                theme["name"], 
                theme["colors"],
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

# 测试代码
if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication
    from freeassetfilter.widgets.window_widgets import CustomWindow
    
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